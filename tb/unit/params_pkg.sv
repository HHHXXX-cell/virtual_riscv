// tb/unit/params_pkg.sv — 参数单源的"编译 + elaboration"冒烟（不含任何 DUT 功能逻辑）
//
// 判据：`vlog` 报 Errors: 0，且 `vsim` 跑出的日志里出现 `[params_smoke]` 证据行。
//   - 只读生成件 rtl/vr1/include/vr1_params.svh（由 doc/spec/00 §4 机械生成，禁手改）
//   - 下面几条 $fatal 是"参数表自身的自洽约束"，全部来自 spec/00 §4 表内文字，
//     任一不成立说明 spec 值或生成器有错——在写第一行 RTL 之前就把它们钉住。
// 本文件不是 DUT、不进 filelist/rtl.f（G1 冻结前 rtl/ 只允许 include/*.svh）。
package vr1_params_pkg;
  `include "vr1_params.svh"
endpackage

module vr1_params_smoke;
  import vr1_params_pkg::*;

  logic [VA_STORE_W-1:0] va_dbg;
  logic [PA_BITS-1:0]    pa_dbg;
  logic [ROB_PTR_W-1:0]  rob_ptr_dbg;

  initial begin
    if (XLEN != 64)
      $fatal(1, "XLEN=%0d，期望 64（RV64）", XLEN);
    if (VA_STORE_W <= VA_BITS)
      $fatal(1, "VA_STORE_W(%0d) 必须 > VA_BITS(%0d)（含 bit39 规范检测位）", VA_STORE_W, VA_BITS);
    if (ALEN != PA_BITS)
      $fatal(1, "ALEN(%0d) 必须 = PA_BITS(%0d)", ALEN, PA_BITS);
    if (FTQ_ENTRIES < BP_STAGES + IF_STAGES)
      $fatal(1, "FTQ_ENTRIES(%0d) < BP_STAGES+IF_STAGES(%0d)：在途重定向窗口不足",
             FTQ_ENTRIES, BP_STAGES + IF_STAGES);
    if (IBUF_ENTRIES <= IF_STAGES * DECODE_WIDTH)
      $fatal(1, "IBUF_ENTRIES(%0d) 必须 > IF_STAGES×DECODE_WIDTH(%0d)",
             IBUF_ENTRIES, IF_STAGES * DECODE_WIDTH);
    if (N_EU_TOTAL != 3 + 1 + 1 + 1 + 1 + 2)
      $fatal(1, "N_EU_TOTAL=%0d 与 §4.4 的 ALU3+BRU1+SHIFT1+MUL1+DIV1+AGU2 不符", N_EU_TOTAL);
    if (ROB_NEAR_FULL >= ROB_ENTRIES)
      $fatal(1, "ROB_NEAR_FULL(%0d) 必须 < ROB_ENTRIES(%0d)", ROB_NEAR_FULL, ROB_ENTRIES);

    va_dbg = '0;
    pa_dbg = '0;
    rob_ptr_dbg = '0;
    $display("[params_smoke] XLEN=%0d VA_BITS=%0d VA_STORE_W=%0d PA_BITS=%0d ROB=%0d FTQ=%0d IQ=%0d/%0d/%0d PRF=%0d ISSUE=%0d",
             XLEN, VA_BITS, VA_STORE_W, PA_BITS, ROB_ENTRIES, FTQ_ENTRIES,
             IQ_INT_ENTRIES, IQ_MEM_ENTRIES, IQ_BR_ENTRIES, PRF_INT_ENTRIES, ISSUE_WIDTH);
    $display("[params_smoke] PASS");
  end
endmodule
