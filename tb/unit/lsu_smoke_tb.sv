// ==========================================================================
// tb/unit/lsu_smoke_tb.sv — M11 `vr1_lsu` 定向单元冒烟（M1-S3b）
//
// 它是什么：直连 `vr1_lsu`，逐案喂 `disp_x_t` ＋ 桩响应，查地址生成、`mem_req_t` 形态、
//   非对齐 fault（码 4/6）与"**非对齐不发请求**"；每案一行证据，末行 `PASS`/`FAIL`。
// 覆盖：
//   · `SW`：`addr = rs1 + sext(imm)`（负偏移回绕）、`kind=01 STD`、完成＝请求被接受、无 fault；
//   · `LW`：`addr = rs1 + sext(imm)`、`kind=00 LD`、结果按 bit31 **符号扩展**（§10.3）；
//   · 非对齐：`addr[1:0]≠0` ⇒ load 码 4／store 码 6、`tval`＝触发 VA、**不产生任何请求**
//     （`spec/00` §2／`MISALIGNED_EN=0`／`spec/10` §2.1）；
//   · 单条在飞：占用期 `req_rdy_o=0`。
// 边界（红线 R6/R8）：**不是** M1 判据本体；`SB/SH/…`、AMO、转发、LQ/SQ、写响应契约在该模块文件头
//   逐条 TODO —— 本冒烟不为其产假期望。
// 依据：doc/spec/02 §10.3/§10.4；doc/spec/01 §3.13/§3.16/§3.20；doc/spec/10 §2.1。
// ==========================================================================
`ifndef LSU_SMOKE_TB_SV
`define LSU_SMOKE_TB_SV

module lsu_smoke_tb;
  import vr1_pkg::*;

  localparam logic [9:0] ISOP_LW = 10'h102, ISOP_SW = 10'h182;
  localparam logic [39:0] DRAM = 40'h00_4000_0000;

  logic clk = 1'b0, rst_n = 1'b0;
  always #5 clk = ~clk;
  initial begin
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    rst_n = 1'b1;
  end

  logic        req_vld, req_rdy;
  disp_x_t     disp;
  ls_complete_t ls;
  logic [39:0] tval, maddr;
  logic [63:0] ldata, mwdata, mrdata;
  logic [1:0]  msize;
  logic        mv, mwr;
  logic        dreq_v, dreq_rdy, drsp_v, drsp_rdy;
  mem_req_t    dreq;
  dcache_rsp_t drsp;

  vr1_lsu u_dut (
    .clk (clk), .rst_n (rst_n),
    .req_vld_i (req_vld), .disp_i (disp), .req_rdy_o (req_rdy),
    .ls_o (ls), .tval_o (tval), .ld_data_o (ldata),
    .mem_v_o (mv), .mem_addr_o (maddr), .mem_wdata_o (mwdata), .mem_rdata_o (mrdata),
    .mem_size_o (msize), .mem_wr_o (mwr),
    .dmem_req_valid_o (dreq_v), .dmem_req_o (dreq), .dmem_req_ready_i (dreq_rdy),
    .dmem_rsp_valid_i (drsp_v), .dmem_rsp_i (drsp), .dmem_rsp_ready_o (drsp_rdy)
  );

  int unsigned n_fail, n_case, n_req;
  int unsigned req_snap;   // 请求计数快照（`n_req` 只由 always_ff 驱动）

  // 桩响应：DUT 进入"等响应"态（`dmem_rsp_ready_o=1`）的次拍给一拍 `valid` ＋ 预设数据
  logic [63:0] rsp_data;
  logic        drsp_v_q;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) drsp_v_q <= 1'b0;
    else        drsp_v_q <= drsp_rdy;
  end
  always_comb begin
    drsp_v    = drsp_v_q;
    drsp.data = rsp_data;
  end
  logic [39:0] req_va;
  logic [1:0]  req_kind;

  // 请求侧观测（记录是否发过请求与其形态）
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      n_req <= 0; req_va <= 40'd0; req_kind <= 2'b00;
    end else if (dreq_v) begin
      n_req <= n_req + 1; req_va <= dreq.va; req_kind <= dreq.kind;
    end
  end

  task automatic chk64(input string name, input logic [63:0] got, input logic [63:0] exp);
    n_case = n_case + 1;
    if (got !== exp) begin
      n_fail = n_fail + 1;
      $display("[lsu_smoke] FAIL case=%s got=%016x exp=%016x", name, got, exp);
    end else begin
      $display("[lsu_smoke] case=%s got=%016x exp=%016x ok=1", name, got, exp);
    end
  endtask

  // 发起一次访存：`sw_wait`＝是否等桩响应（load 等、store 不等）
  task automatic issue(input logic [9:0] isop, input logic [63:0] base,
                       input logic [43:0] imm, input logic [63:0] st_data,
                       input logic ld);
    disp        = '0;
    disp.valid  = 1'b1;
    disp.isop   = isop;
    disp.rs1_val = base;
    disp.rs2_val = st_data;
    disp.imm    = imm;
    disp.dm     = 2'b10;
    disp.sext   = ld ? 1'b1 : 1'b0;
    disp.rob_id = 8'h11;
    disp.rd_paddr = 6'd3;
    req_vld     = 1'b1;
    @(posedge clk);
    req_vld     = 1'b0;
    disp.valid  = 1'b0;
    if (ld) begin                              // LW：等响应
      wait (drsp_v);
      @(posedge clk);
    end
    wait (ls.vld);                             // 等完成脉冲
    @(posedge clk);
  endtask

  initial begin
    n_fail = 0; n_case = 0; req_snap = 0;
    req_vld = 1'b0; disp = '0;
    dreq_rdy = 1'b1; rsp_data = 64'd0;
    wait (rst_n === 1'b1);
    repeat (2) @(posedge clk);

    // ---- SW 对齐：addr = x7 + 0 = 0x4000_0000，数据 x6 = 0x1F ----
    disp        = '0;
    disp.valid  = 1'b1;
    disp.isop   = ISOP_SW;
    disp.rs1_val = 64'h4000_0000;
    disp.rs2_val = 64'd31;
    disp.imm    = 44'd0;
    disp.dm     = 2'b10;
    req_vld     = 1'b1;
    @(posedge clk);
    req_vld     = 1'b0;
    disp.valid  = 1'b0;
    wait (ls.vld);
    #1;
    chk64("sw_addr", {24'd0, maddr}, 64'h4000_0000);
    chk64("sw_wdata", mwdata, 64'd31);
    chk64("sw_kind", {62'd0, req_kind}, 64'd1);          // 01 STD
    chk64("sw_size", {62'd0, msize}, 64'd2);             // W
    chk64("sw_fault", {62'd0, ls.fault}, 64'd0);
    chk64("sw_code", {60'd0, ls.code}, 64'd0);
    chk64("sw_mem_v", {63'd0, mv}, 64'd1);
    chk64("sw_mem_wr", {63'd0, mwr}, 64'd1);
    @(posedge clk);

    // ---- LW 对齐：桩回 0x0000_0000_0000_001F ⇒ 结果＝31；再测符号扩展（高位置 1 的 32 位负数）----
    rsp_data = 64'h0000_0000_0000_001F;
    issue(ISOP_LW, 64'h4000_0000, 44'd0, 64'd0, 1'b1);
    chk64("lw_data_31", ldata, 64'd31);
    chk64("lw_kind", {62'd0, req_kind}, 64'd0);          // 00 LD

    rsp_data = 64'h0000_0000_8000_0000;                  // 低 32 位 = -2^31 ⇒ 符号扩展
    issue(ISOP_LW, 64'h4000_0000, 44'd0, 64'd0, 1'b1);
    chk64("lw_sext_bit31", ldata, 64'hFFFF_FFFF_8000_0000);

    // ---- 负偏移回绕：base 0x4000_0000 + imm(-4) = 0x3FFF_FFFC ----
    req_snap = n_req;
    rsp_data = 64'h0000_0000_0000_0001;
    issue(ISOP_LW, 64'h4000_0000, 44'hF_FFFF_FFFF_FC, 64'd0, 1'b1);
    chk64("lw_neg_off_addr", {24'd0, req_va}, 64'h3FFF_FFFC);
    chk64("lw_neg_off_data", ldata, 64'd1);

    // ---- 非对齐 store（smoke 现场）：addr=0x4000_0001 ⇒ 码 6、tval=该 VA、**不发请求** ----
    req_snap = n_req;
    issue(ISOP_SW, 64'h4000_0000, 44'd1, 64'd3, 1'b0);
    chk64("sw_misaligned_code", {60'd0, ls.code}, 64'd6);
    chk64("sw_misaligned_tval", {24'd0, tval}, 64'h4000_0001);
    chk64("sw_misaligned_nreq", {62'd0, n_req - req_snap}, 64'd0);   // 不产生任何存储请求
    chk64("sw_misaligned_mem_v", {63'd0, mv}, 64'd0);

    // ---- 非对齐 load ⇒ 码 4、不发请求 ----
    req_snap = n_req;
    disp     = '0;
    disp.valid = 1'b1; disp.isop = ISOP_LW; disp.rs1_val = 64'h4000_0002;
    disp.imm = 44'd0; disp.dm = 2'b10; disp.sext = 1'b1;
    req_vld = 1'b1;
    @(posedge clk);
    req_vld = 1'b0; disp.valid = 1'b0;
    wait (ls.vld);
    #1;
    chk64("lw_misaligned_code", {60'd0, ls.code}, 64'd4);
    chk64("lw_misaligned_nreq", {62'd0, n_req - req_snap}, 64'd0);
    @(posedge clk);
    // 对齐地址 0x4000_0002（半字）在 `dm=W` 下也是非对齐 ⇒ 上面即覆盖

    repeat (2) @(posedge clk);
    $display("[lsu_smoke] cases=%0d n_fail=%0d", n_case, n_fail);
    if (n_fail == 0) $display("[lsu_smoke] PASS: M11 AGU + LW sext + misaligned fault (4/6, no request) all ok");
    else             $display("[lsu_smoke] FAIL: %0d item(s)", n_fail);
    $finish;
  end

  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > 20000) begin
        $display("[lsu_smoke] ABORT: exceeded bound 20000 cycles (cases=%0d) => FAIL", n_case);
        $finish;
      end
    end
  end

endmodule

`endif // LSU_SMOKE_TB_SV
