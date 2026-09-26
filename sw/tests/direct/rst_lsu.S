/***************************************************************
 * sw/tests/direct/rst_lsu.S — VR1 定向用例（受控复位注入通道）：**LSU 长访存循环**
 *
 * 为什么写它（逐条对上缺 bin；`doc/verify/02-验证点清单.md` §6 NU-2 行）：
 *   `cg_lsu_fsm.cp_trans` 的 `t_req_idle`（L_REQ => L_IDLE）与 `t_rsp_idle`
 *   （L_RSP => L_IDLE）两 bin 只有**复位边**能产生——`rtl/vr1/lsu/vr1_lsu.sv` 的 FSM
 *   从 L_REQ 只能进 L_DONE/L_RSP、从 L_RSP 只能进 L_DONE（其文件头顺序段逐行可核），
 *   ⇒ 必须在"运行中再次断言复位"才能命中。本用例提供**长且密**的载入/存储流：
 *   300 轮 `sw`+`lw` 循环 ⇒ LSU 反复穿过 L_REQ/L_RSP，供 TB 的
 *   `+RESET_INJECT=<cycle>`（`tb/unit/m1_e2e_tb.sv` 的机制件）在指定拍注入复位，
 *   使复位恰落在请求拍/响应拍。
 *
 * 通道口径（**R0 2026-09-26 三项裁定①**＝NU-2 受控通道，写死防误读）：
 *   · 本用例**只进覆盖率批**（`run_cmd/cover_m3_testlist.txt` 的 `rst_lsu` 条目），
 *     **不进**回归面（`run_cmd/rv64ui_testlist.txt` 无 rst_ 前缀 ⇒ 回归同配置签名不变）；
 *   · **不进** `MANIFEST.json` 的 `tests`（`m2-rv64ui` 判据逐条 ISS<->RTL 比对，而复位注入
 *     使 trace 出现"重启后第二段"，**构造性不可比**——NU-2 行原文）；登记于同 MANIFEST 的
 *     `cov_only_tests`，其判定＝RTL 侧 HALT_PASS ＋ 无 HALT_FAIL/WATCHDOG ＋ TB 复位注入
 *     证据行（`run_cmd/cover_rv1.py` 的受控通道单例执行，fail-closed）；
 *   · bin 不删、判定阈值不改（红线 R7；判据侧通道标注见 `script/flow.py:chk_m3_func_cov`）。
 *
 * 行为惰性说明（为什么重启后仍能跑通停机）：循环体不用循环外的任何先前状态
 *   （x5/x6/x7/x28 都由本段自己初始化，且 `RVTEST_CODE_BEGIN` 的 `INIT_XREG` 在每次
 *   复位释放后重跑一遍）⇒ 复位注入若干次后，程序仍从 `_start` 完整重跑并以
 *   `RVTEST_PASS`（tohost<-1）停机——停机判据（`tb/unit/rt_t_trace_writer.sv`）不受影响。
 *
 * 用到的指令（全部在 RTL 合法面 57 条内，`rtl/vr1/ctrl/vr1_decode.sv` isop 表可核）：
 *   `lui`/`addi`（`li` 的展开）、`sw`、`lw`、`addiw`、`bne`（`bnez`）。
 *
 * 依据：`doc/verify/02` §6 NU-2 行；`doc/spec/00` §2 ISA 串与 §4.1（RESET_PC/数据窗）；
 *       `sw/env/riscv_test.h`（RVTEST_CODE_BEGIN/PASS 口径）、`sw/env/link.ld`
 *       （tohost=0x4000_0010；数据窗 0x4000_0000 起 1 KiB）。
 ***************************************************************/
#include "riscv_test.h"

RVTEST_RV64U
RVTEST_CODE_BEGIN

        /* 数据窗内 scratch（0x4000_0100：避开 tohost=0x4000_0010/fromhost=0x4000_0018；
           窗内偏移 0x100 < 1 KiB ⇒ TB 数据桩可承载） */
        li      x5, 0x40000100
        li      x6, 0               /* 存储数据模式（逐轮 +4） */
        li      x7, 300             /* 迭代数：拉长 LSU 活动窗，便于按拍注入复位 */
1:
        sw      x6, 0(x5)           /* store：L_IDLE -> L_REQ -> L_DONE */
        lw      x28, 0(x5)          /* load ：L_IDLE -> L_REQ -> L_RSP -> L_DONE */
        addiw   x28, x28, 1
        addi    x6, x6, 4
        addi    x7, x7, -1
        bnez    x7, 1b

        RVTEST_PASS                     /* tohost <- 1（riscv-tests PASS 语义，停机判据） */
RVTEST_CODE_END

RVTEST_DATA_BEGIN
RVTEST_DATA_END
