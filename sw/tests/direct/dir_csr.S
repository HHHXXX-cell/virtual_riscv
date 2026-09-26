/***************************************************************
 * sw/tests/direct/dir_csr.S — VR1 定向用例（覆盖缺口补激励）：**7 条 CSR 纯读**
 *
 * 为什么写它（逐条对上缺 bin；`doc/verify/07-m2cov_r2.txt` §A 的 ZERO bin 清单）：
 *   `cg_retire.cp_csr` 的 6 个 bin 在 2026-09-26 心跳第 11 轮的合并报告里为 **ZERO**
 *   （`csr_mstatus`/`csr_misa`/`csr_mscratch`/`csr_mepc`/`csr_mcause`/`csr_mtval`；只有
 *   `csr_mtvec` 因 env 的 `reset_vector` 写 mtvec 而命中）。本用例逐条读这 7 个 CSR，
 *   使**每条退休条目的 `rt_t.csr_addr`** 落在对应 bin 上（`rt_o.csr_addr` 源＝
 *   `vr1_rob` 的 `csr_addr_q` ← `uop_t.csr_addr` ← `vr1_decode` 的 `u.csrc_addr = w[31:20]`，
 *   见 `rtl/vr1/ctrl/vr1_decode.sv` 624 行 / `vr1_rob.sv` 200 行）。
 *
 * 位置与口径（VP 号逐条给出；依据 `doc/verify/02-验证点清单.md`）：
 *   · **VP-05（F-05 Zicsr；检查手段＝"ISA CSR 读回逐条核对；rd=x0 不读"）**：本用例的形态
 *     正是 VP-05 的「G 逐 CSR；W 读」帧——7 条 `csrrs rd=x0, csr, rs1=x0`＝**纯读**：
 *     `rd=x0` ⇒ 无架构写回（`spec/02` §4.1 SI-1）、`rs1=x0` ⇒ 不写 CSR（`spec/10` §4.1
 *     CSRRS 语义）⇒ **对 gpr 与 CSR 状态零影响**，只产生"读过该 CSR"的可观测事实
 *     （退休条目的 `csr_addr`）。故本用例是**行为惰性**的：不改变任何既有 trace 语义
 *     （M2 判据 `m2-rv64ui` 的逐条比对仍成立）。
 *   · 7 条读**逐条对应** `cp_csr` 的 7 个 bin：0x300/0x301/0x305/0x340/0x341/0x342/0x343
 *     （`spec/10` §4.1 的 7 条 CSR 全表）。
 *
 * 为什么不用 `csrr`（伪指令）写法：显式 `csrrs rd, csr, rs1` 三操作数形式，避免伪指令在
 * 不同汇编器版本下的 rd 约定歧义（`sw/env/riscv_test.h` 的差异表第 3 条已列 `csrr`/`csrw`
 * 为本 env 允许的写法；本件仍取显式形式，**不引入新语义**）。
 *
 * 判据纪律（红线 R6/R8）：本件**不产任何通过结论**；它由 `run_cmd/cover_rv1.py` 的覆盖率批
 * （`--testlist run_cmd/cover_m3_testlist.txt`）跑，逐例判定仍走 ISS ＋ RTL ＋ `trace_compare`
 * 三面（与 rv64ui 同口径，不放宽）。
 *
 * 依据：`doc/verify/02` VP-05；`doc/spec/10` §4.1；`doc/spec/02` §9.1.7／§4.1 SI-1；
 *       `doc/verify/07-m2cov_r2.txt` §A（ZERO bin 清单）；
 *       `sw/env/riscv_test.h`（RVTEST_CODE_BEGIN/PASS 口径）、`sw/env/link.ld`（tohost=0x4000_0010）。
 ***************************************************************/
#include "riscv_test.h"

RVTEST_RV64U
RVTEST_CODE_BEGIN

        /* VP-05：逐 CSR 纯读（rd=x0 ⇒ 无写回；rs1=x0 ⇒ 不写）——7 条 = cp_csr 的 7 个 bin */
        csrrs x0, mstatus,  x0          /* 0x300 — VP-05 / spec/10 §4.1 */
        csrrs x0, misa,     x0          /* 0x301 — VP-05（只读常量；读不写） */
        csrrs x0, mtvec,    x0          /* 0x305 — VP-05（env 的 reset_vector 已写；此处补读面） */
        csrrs x0, mscratch, x0          /* 0x340 — VP-05 */
        csrrs x0, mepc,     x0          /* 0x341 — VP-05 */
        csrrs x0, mcause,   x0          /* 0x342 — VP-05 */
        csrrs x0, mtval,    x0          /* 0x343 — VP-05 */

        RVTEST_PASS                     /* tohost <- 1（riscv-tests PASS 语义，停机判据） */
RVTEST_CODE_END

RVTEST_DATA_BEGIN
RVTEST_DATA_END
