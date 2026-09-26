// ==========================================================================
// tb/unit/decode_unit_smoke_tb.sv — M1-S2 译码级（M05 `vr1_decode`）**件 1**：直连单元冒烟
//
// 它是什么：直连 `vr1_decode`，合成 4 个窗 + 一段 R 级反压（`uop_ready_i=0`），查
//   「起始槽选择/打包顺序、逐窗 drain 脉冲（一拍一次）、反压不丢不重、指针推进」；
//   并逐**呈现拍**打证据行 `[decode_unit] pres lanes=… pc0=… drain=… accept=…`
//   （M1-S2 判据 `rtl-decode-win` 的机判入口，见 `script/flow.py`）。
//
// 它不是什么（边界，红线 R6/R8）：**不是** M1 判据本体（M1 的两条 exit 是 `rtl-compile`/
//   `rtl-vs-iss`）；**不产 trace**（DUT 的 `rt_valid_o` 恒 0）；不含平台面（停机判据/`rt_t`
//   写出器/2,000,000 拍 watchdog 归 `GI-13`/`GD-6`）；本文件的 `TD_CYC` 只是本冒烟自我保护上限。
//
// 为什么要拆文件（2026-09-26，M1-S2 收口批）：本件原与「件 2 流冒烟」同处
//   `decode_smoke_tb.sv`；一个文件含两个顶层模块会让「`-- Compiling` 计数 == 编译清单条目数」
//   的不变式失效（8 行 vs 7 文件）⇒ 按模块边界拆成两个单模块文件，**模块内容逐字未改**。
//
// 注（日志编码）：所有 `$display` 一律 **ASCII**——ModelSim 控制台会把非 ASCII 替换为 `?`
//   （实测），中文注释不进入日志；证据行必须逐字可读（红线 R3/R8）。
//
// 跑法（沙箱独占，红线 R10；路径全绝对、cwd＝沙箱；与 `flow.py` 的 ModelSim 调用同口径）：
//   cd /d sim\run_rtl_decode_win
//   vlib work
//   vlog -64 -sv -work work +incdir+<仓库根>/rtl/vr1/include <rtl.f 的单元> <本文件>
//   vopt -64 work.decode_unit_tb -o unit_opt && vsim -64 -c -do "run -all; quit -f" unit_opt
//
// 依据：doc/spec/01 §3.3/§3.4/§3.16、§1.1 `P6` 行；doc/spec/02 §9.1/§9.3/§9.4-(6)/§9.5/§4.1 SI-1；
//       doc/spec/10 §2.1（码 2）；doc/decisions/G1-I-最小冻结清单.md §1.1 第 1 条/§1.2 第 6 条/§2.6。
// ==========================================================================
`ifndef VR1_DECODE_UNIT_SMOKE_TB_SV
`define VR1_DECODE_UNIT_SMOKE_TB_SV

// ---------------------------------------------------------------------------
// 件 1：直连 `vr1_decode` 的单元冒烟（合成窗 + 反压）
// ---------------------------------------------------------------------------
module decode_unit_tb;
  import vr1_pkg::*;

  localparam int unsigned TD_CYC = 5000;

  logic clk = 1'b0;
  logic rst_n = 1'b0;
  always #5 clk = ~clk;

  logic                    win_vld;
  fetch_raw_t              lanes [IBUF_ENTRIES];
  logic                    drain;
  uop_t                    uop [DECODE_WIDTH];
  logic                    ready;

  int unsigned n_fail;
  int unsigned n_drain;
  int unsigned n_uop;

  vr1_decode u_dut (
    .clk            (clk),
    .rst_n          (rst_n),
    .ibuf_win_vld_i (win_vld),
    .ibuf_rd_i      (lanes),
    .ibuf_drain_o   (drain),
    .uop_o          (uop),
    .uop_ready_i    (ready),
    .flush_i        (1'b0)      // 件 1 不改冲刷面（M1-S3b 新增端口；冲刷面归 `flush` 专项冒烟）
  );

  // 装一个合成窗：`mask` 指定起始槽，`base` 为该窗基址（槽 pc = base + 2×槽号，§3.16）
  task automatic set_win(input logic [IBUF_ENTRIES-1:0] mask, input logic [39:0] base);
    for (int unsigned i = 0; i < IBUF_ENTRIES; i++) begin
      lanes[i]        = '0;
      lanes[i].valid  = mask[i];
      lanes[i].pc     = base + 40'(2*i);
      lanes[i].raw32  = 32'h0000_0013;                // addi x0,x0,0：合法字（本件不查字段）
      lanes[i].ftq_id = 5'd0;
    end
  endtask

  // 查本拍呈现的 lane 数、各 lane 的 pc（`n`＝期望有效 lane 数，`first_slot`＝首个期望槽号）
  task automatic chk_lanes(input int unsigned n, input logic [39:0] base, input int unsigned first_slot);
    int unsigned seen;
    seen = 0;
    for (int unsigned k = 0; k < DECODE_WIDTH; k++) if (uop[k].valid) seen++;
    if (seen != n) begin
      n_fail++;
      $display("[decode_unit] FAIL lanes=%0d expect %0d", seen, n);
    end
    for (int unsigned k = 0; k < n; k++) begin
      if (!uop[k].valid) begin
        n_fail++;
        $display("[decode_unit] FAIL lane%0d invalid (expect valid)", k);
      end else if (uop[k].pc !== (base + 40'(2*(first_slot + 2*k)))) begin
        n_fail++;
        $display("[decode_unit] FAIL lane%0d pc=%h expect %h", k, uop[k].pc,
                 base + 40'(2*(first_slot + 2*k)));
      end
    end
    if (ready) n_uop += n;                            // 只计"被接受"的 lane（反压拍重复呈现不计）

    // 逐呈现证据行（M1-S2 判据 `rtl-decode-win` 的机判入口）：本拍实采的 lane 数 / lane0 pc /
    //   drain / 是否被接受。**一次呈现一行**（含反压拍的重复呈现）⇒ 判据侧据此核对
    //   「反压拍与前一拍同组（不丢不重）」「drain 恰在末批且与接受同拍」「接受 lane 总数」。
    $display("[decode_unit] pres lanes=%0d pc0=%h drain=%b accept=%b", seen, uop[0].pc, drain, ready);
  endtask

  task automatic chk_drain(input logic exp, input string why);
    if (drain !== exp) begin
      n_fail++;
      $display("[decode_unit] FAIL drain=%b expect %b (%s)", drain, exp, why);
    end
    if (drain) n_drain++;
  endtask

  initial begin
    n_fail  = 0;
    n_drain = 0;
    n_uop   = 0;
    win_vld = 1'b0;
    ready   = 1'b0;
    set_win('0, 40'h1000);
    rst_n = 1'b0;
    repeat (4) @(posedge clk);
    @(negedge clk); rst_n = 1'b1;

    // ---- 窗 A：槽 0/2/4/6（4 条，恰满一拍）→ 一拍取尽 + drain ----
    @(negedge clk);
    set_win(16'b0000_0000_0101_0101, 40'h1000);
    win_vld = 1'b1; ready = 1'b1;
    #1;
    chk_lanes(4, 40'h1000, 0);
    chk_drain(1'b1, "win A fits in one cycle");
    @(posedge clk); #1;
    win_vld = 1'b0;                                   // 消费方：清窗有效位（ifetch 侧同款）
    @(negedge clk);
    chk_lanes(0, 40'h1000, 0);
    chk_drain(1'b0, "no window -> no drain");

    // ---- 窗 B：槽 2/4/6（3 条）＋ R 级反压 3 拍（不推进、不 drain、不丢不重）----
    @(negedge clk);
    set_win(16'b0000_0000_0101_0100, 40'h2000);
    win_vld = 1'b1; ready = 1'b0;
    #1;
    chk_lanes(3, 40'h2000, 2);
    for (int unsigned i = 0; i < 3; i++) begin
      chk_drain(1'b0, "ready=0 -> not taken");
      @(posedge clk); #1;
      chk_lanes(3, 40'h2000, 2);                      // 同一组重新呈现（不丢不重）
    end
    ready = 1'b1; #1;
    chk_lanes(3, 40'h2000, 2);
    chk_drain(1'b1, "taken after ready=1");
    @(posedge clk); #1;
    win_vld = 1'b0;
    @(negedge clk);

    // ---- 窗 C：槽 0/2/4/6/8/10（6 条）→ 两拍取尽（4 + 2）----
    @(negedge clk);
    set_win(16'b0000_0101_0101_0101, 40'h3000);
    win_vld = 1'b1; ready = 1'b1;
    #1;
    chk_lanes(4, 40'h3000, 0);
    chk_drain(1'b0, "6 lanes: last batch not yet");
    @(posedge clk); #1;
    chk_lanes(2, 40'h3000, 8);                        // 第二拍：槽 8/10
    chk_drain(1'b1, "last batch of win C");
    @(posedge clk); #1;
    win_vld = 1'b0;
    @(negedge clk);

    // ---- 窗 D：槽 1/3（奇数槽亦为合法起始，§3.16「起始可落任意槽号」）----
    @(negedge clk);
    set_win(16'b0000_0000_0000_1010, 40'h4000);
    win_vld = 1'b1; ready = 1'b1;
    #1;
    chk_lanes(2, 40'h4000, 1);
    chk_drain(1'b1, "win D fits in one cycle");
    @(posedge clk); #1;
    win_vld = 1'b0;
    @(negedge clk);

    // ---- 收尾 ----
    $display("[decode_unit] A/B/C/D: uops=%0d drain_pulses=%0d n_fail=%0d", n_uop, n_drain, n_fail);
    if ((n_fail == 0) && (n_uop == 15) && (n_drain == 4))
      $display("[decode_unit] PASS: lane select/pack order + per-window drain + backpressure (no loss/dup) all ok");
    else
      $display("[decode_unit] FAIL: %0d item(s) (uops=%0d expect 15, drains=%0d expect 4)", n_fail, n_uop, n_drain);
    $finish;
  end

  // 自我保护上限（**非** M1 watchdog 口径）
  int unsigned cycles;
  always_ff @(posedge clk or negedge rst_n) begin
    if (!rst_n) cycles <= 0;
    else begin
      cycles <= cycles + 1;
      if (cycles > TD_CYC) begin
        $display("[decode_unit] ABORT: exceeded smoke bound %0d cycles => FAIL", TD_CYC);
        $finish;
      end
    end
  end

endmodule



`endif // VR1_DECODE_UNIT_SMOKE_TB_SV
