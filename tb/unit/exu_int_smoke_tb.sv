// ==========================================================================
// tb/unit/exu_int_smoke_tb.sv — M09 `vr1_exu_int` 定向单元冒烟（M1-S3b）
//
// 它是什么：直连 `vr1_exu_int`，逐案喂 `disp_x_t`，查结果值与**占用拍数**（`MUL_LAT`/`DIV_LAT`
//   与 FSM 实测拍数一致）；每案打一行证据，末行 `PASS`/`FAIL`。
// 覆盖（全部取自 `sim/image/m_smoke.hex` 的实际指令 ＋ 规范边界）：
//   · `LUI`（sext32）、`ADDI`（负立即数）、`ADDIW`（32 位加＋bit31 扩展）、`SLLI`（shamt 6 bit）；
//   · `MUL`（含 (-1)×(-1)=1，`spec/02` §17.1 #1）；`DIV` 除零＝全 1；`REM` 除零＝被除数；
//   · `DIV` 溢出（最小负数 ÷ -1 ＝ 被除数）；`REM` 溢出＝0；`DIV/REM` 负数向零取整/余数随被除数；
//   · 占用拍数：ALU/SHIFT=1、MUL=`MUL_LAT`、DIV/REM=`DIV_LAT`（`spec/00` §4.4）。
// 边界（红线 R6/R8）：**不是** M1 判据本体（M1 exit 是 `rtl-compile`/`rtl-vs-iss`）；不放宽任何检查；
//   未完成面（其余 87 成员）在该模块文件头逐条 TODO(G1-F)，本冒烟**不**为其产假期望。
// 跑法（沙箱独占，红线 R10）：见 `sim/run_m1_backend_smoke/run.log` 的命令行（由临时跑手生成）。
// 依据：doc/spec/02 §10.1/§10.6/§17.1；doc/spec/01 §3.11/§3.20；doc/spec/00 §4.4。
// ==========================================================================
`ifndef EXU_INT_SMOKE_TB_SV
`define EXU_INT_SMOKE_TB_SV

module exu_int_smoke_tb;
  import vr1_pkg::*;

  localparam logic [9:0] ISOP_ADDI = 10'h000, ISOP_SLLI = 10'h006, ISOP_ADDIW = 10'h020;
  localparam logic [9:0] ISOP_LUI = 10'h040, ISOP_MUL = 10'h200, ISOP_DIV = 10'h280,
                         ISOP_REM = 10'h282;

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;
  initial begin
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
  end

  logic        disp_vld, disp_rdy;
  disp_x_t     disp;
  x_complete_t xc;

  vr1_exu_int u_dut (
    .clk (clk), .rst_n (rst_n),
    .disp_vld_i (disp_vld), .disp_i (disp), .disp_rdy_o (disp_rdy), .xc_o (xc)
  );

  int unsigned n_fail, n_case;

  task automatic chk(input string name, input logic [63:0] got, input logic [63:0] exp);
    n_case = n_case + 1;
    if (got !== exp) begin
      n_fail = n_fail + 1;
      $display("[exu_smoke] FAIL case=%s got=%016x exp=%016x", name, got, exp);
    end else begin
      $display("[exu_smoke] case=%s got=%016x exp=%016x occupancy=%0d ok=1", name, got, exp, 0);
    end
  endtask

  // 单案驱动：低电平发起 → 数占用拍 → 比对值与随流键（采样口径见文件头）
  task automatic run_case(input string name, input logic [9:0] isop,
                          input logic [63:0] a, input logic [63:0] b,
                          input logic [43:0] imm, input logic [63:0] exp,
                          input int unsigned exp_lat);
    int unsigned lat;
    @(negedge clk);
    disp          = '0;
    disp.valid    = 1'b1;
    disp.isop     = isop;
    disp.rs1_val  = a;
    disp.rs2_val  = b;
    disp.imm      = imm;
    disp.rob_id   = 8'h5A;
    disp.rd_paddr = 6'd7;
    disp_vld      = 1'b1;
    @(posedge clk);                    // 发起拍
    @(negedge clk);
    disp_vld      = 1'b0;
    disp.valid    = 1'b0;
    lat           = 0;
    forever begin
      #1;                              // NBA 落定后采样（见文件头"采样口径"）
      lat = lat + 1;
      if (xc.vld === 1'b1 || lat > 200) break;
      @(posedge clk);
      @(negedge clk);
    end
    n_case = n_case + 1;
    if (xc.vld !== 1'b1) begin
      n_fail = n_fail + 1;
      $display("[exu_smoke] FAIL case=%s no completion within 200 cycles", name);
    end else if (xc.data !== exp) begin
      n_fail = n_fail + 1;
      $display("[exu_smoke] FAIL case=%s data=%016x exp=%016x", name, xc.data, exp);
    end else if (lat != exp_lat) begin
      n_fail = n_fail + 1;
      $display("[exu_smoke] FAIL case=%s occupancy=%0d exp=%0d (MUL_LAT/DIV_LAT)", name, lat, exp_lat);
    end else if ((xc.robid !== 8'h5A) || (xc.paddr !== 6'd7)) begin
      n_fail = n_fail + 1;
      $display("[exu_smoke] FAIL case=%s robid=%02x paddr=%02x (expect 5A/07)", name, xc.robid, xc.paddr);
    end else begin
      $display("[exu_smoke] case=%s data=%016x exp=%016x occupancy=%0d exp=%0d ok=1",
               name, xc.data, exp, lat, exp_lat);
    end
    @(negedge clk);                    // 释放拍（单元次拍可收新请求）
  endtask

  initial begin
    n_fail = 0; n_case = 0; disp_vld = 1'b0; disp = '0;
    wait (rst_n === 1'b1);
    repeat (3) @(posedge clk);

    // ---- ALU/SHIFT（占用 1 拍）----
    run_case("lui_x1_0x1",    ISOP_LUI,   64'd0, 64'd0, 44'h000_0000_1000, 64'h0000_0000_0000_1000, 1);
    run_case("addi_x1_0x100", ISOP_ADDI,  64'h1000, 64'd0, 44'h000_0000_0100, 64'h0000_0000_0000_1100, 1);
    run_case("addi_neg",      ISOP_ADDI,  64'd0, 64'd0, 44'hFFF_FFFF_FFFF, 64'hFFFF_FFFF_FFFF_FFFF, 1);
    run_case("addiw_19p1",    ISOP_ADDIW, 64'd5, 64'd0, 44'h000_0000_0001, 64'd6, 1);
    run_case("slli_31sh3",    ISOP_SLLI,  64'd31, 64'd0, 44'h000_0000_0003, 64'h0000_0000_0000_00F8, 1);
    // ---- MUL（MUL_LAT 拍）----
    run_case("mul_m1m1",      ISOP_MUL,   64'hFFFF_FFFF_FFFF_FFFF, 64'hFFFF_FFFF_FFFF_FFFF,
              44'd0, 64'h0000_0000_0000_0001, MUL_LAT);
    run_case("mul_31x31",     ISOP_MUL,   64'd31, 64'd31, 44'd0, 64'd961, MUL_LAT);
    // ---- DIV/REM（DIV_LAT 拍）----
    run_case("div_31_by_0",   ISOP_DIV,   64'd31, 64'd0, 44'd0, 64'hFFFF_FFFF_FFFF_FFFF, DIV_LAT);
    run_case("rem_31_by_0",   ISOP_REM,   64'd31, 64'd0, 44'd0, 64'd31, DIV_LAT);
    run_case("div_min_by_m1", ISOP_DIV,   64'h8000_0000_0000_0000, 64'hFFFF_FFFF_FFFF_FFFF,
              44'd0, 64'h8000_0000_0000_0000, DIV_LAT);
    run_case("rem_min_by_m1", ISOP_REM,   64'h8000_0000_0000_0000, 64'hFFFF_FFFF_FFFF_FFFF,
              44'd0, 64'd0, DIV_LAT);
    run_case("div_m7_by_2",   ISOP_DIV,   64'hFFFF_FFFF_FFFF_FFF9, 64'd2, 44'd0,
              64'hFFFF_FFFF_FFFF_FFFD, DIV_LAT);          // -7/2 = -3（向零取整）
    run_case("rem_m7_by_2",   ISOP_REM,   64'hFFFF_FFFF_FFFF_FFF9, 64'd2, 44'd0,
              64'hFFFF_FFFF_FFFF_FFFF, DIV_LAT);          // -7%2 = -1（余数随被除数）
    run_case("div_31_by_3",   ISOP_DIV,   64'd31, 64'd3, 44'd0, 64'd10, DIV_LAT);
    run_case("rem_31_by_3",   ISOP_REM,   64'd31, 64'd3, 44'd0, 64'd1, DIV_LAT);

    repeat (5) @(posedge clk);
    $display("[exu_smoke] cases=%0d n_fail=%0d", n_case, n_fail);
    if (n_fail == 0) $display("[exu_smoke] PASS: M09 INT EU values + MUL_LAT/DIV_LAT occupancy all ok");
    else             $display("[exu_smoke] FAIL: %0d item(s)", n_fail);
    $finish;
  end

  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > 20000) begin
        $display("[exu_smoke] ABORT: exceeded bound 20000 cycles (cases=%0d) => FAIL", n_case);
        $finish;
      end
    end
  end

endmodule

`endif // EXU_INT_SMOKE_TB_SV
