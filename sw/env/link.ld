/***************************************************************
 * sw/env/link.ld — VR1 平台链接脚本（riscv-tests 用）
 *
 * 来源与性质（可核）：
 *   · 上游参考：`sw/tests/riscv-tests/env/p/link.ld`（riscv-tests，BSD-3-Clause）——
 *     代码 0x8000_0000、`tohost` 0x8000_1000；
 *   · 本文件是**本项目存储器映射的适配版**（env 层＝平台适配层，见 ORIGIN.md §2）。
 *
 * 映射依据（逐条可回溯）：
 *   · 代码窗 0x1000 起 = `spec/00` §4.1 `RESET_PC=0x1000`；
 *     上界 0x3FFF = TB 取指桩 `fmem` 的覆盖（`tb/unit/m1_e2e_tb.sv`：`byte_addr[39:14]==0` ⇒ 0x0000~0x3FFF）；
 *   · 数据窗基址 0x4000_0000 = ISS `DRAM_BASE`（`iss/vriss/consts.py`）与 TB 数据桩 `DRAM_BASE` 同口径；
 *   · `tohost` = 0x4000_0010 = TB 停机判据 `TOHOST_ADDR`（`tb/unit/m1_e2e_tb.sv` localparam）
 *     与 `iss/tests/test_smoke.py` 的 `TOHOST` 同值（riscv-tests 语义：写 1 = PASS）。
 *
 * 记：数据窗首版只有 TB 桩的 1 KB（`DMEM_WORDS=256`）会被响应 ⇒ `.data` 放在 0x4000_0200 起，
 *     `.data`/`.bss` 合计 >1 KB 的测试需先扩 TB 桩（登记为 TODO(M2)，不静默截断）。
 ***************************************************************/
OUTPUT_ARCH( "riscv" )
ENTRY(_start)

SECTIONS
{
  /* ---- 代码窗：0x1000 ~ 0x3FFF（TB 取指桩覆盖域）---- */
  . = 0x1000;
  .text.init : { *(.text.init) }
  . = ALIGN(0x100);
  .text : { *(.text) }

  /* ---- 数据窗：0x4000_0000 起（ISS DRAM_BASE ／ TB 数据桩）---- */
  . = 0x40000010;
  .tohost : { *(.tohost) }        /* tohost / fromhost（RVTEST_DATA_BEGIN 产出） */

  . = 0x40000200;
  .data : { *(.data) }            /* begin_signature 等（TB 桩当前**不预载** .data，见 TODO(M2)） */
  .bss : { *(.bss) }
  _end = .;
}
