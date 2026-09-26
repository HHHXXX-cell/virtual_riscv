/***************************************************************
 * sw/env/riscv_test.h — VR1 平台适配版 riscv-tests 环境头（env 层）
 *
 * 性质：env 层是 riscv-tests 的**平台适配层**（上游即分 p/v 两个 env 变体）；
 *       本文件 = 上游 `sw/tests/riscv-tests/env/p/riscv_test.h`（低RISC fork，BSD-3-Clause，
 *       逐字副本留在 `sw/tests/riscv-tests/env/p/`）针对 VR1 一期的适配版。
 *       **测试体（`isa/rv64ui/*.S`）与 `isa/macros/scalar/test_macros.h` 逐字不改**（红线 R6）。
 *
 * 适配差异表（逐条可核；未列出的部分与上游同构）：
 *   1. `RVTEST_PASS`/`RVTEST_FAIL`：落 **`tohost`**（riscv-tests 语义：写 1 = PASS，
 *      写 `(testnum<<1)|1` = 对应编号 FAIL）。上游 fork 改为写 `SIGNATURE_ADDR` 后自旋、
 *      **不再写 `tohost`** ⇒ 与本项目停机判据（TB `TOHOST_ADDR=0x4000_0010`、
 *      ISS `--tohost`、`iss/tests/test_smoke.py` 的 `TOHOST`）不符，必须改回 `tohost` 口径；
 *      落地址用 `lui %hi` + `addi %lo` 显式装载（上游 `sw TESTNUM, tohost, t5` 隐含依赖 t5 的值）。
 *   2. FAIL 值 `(t<<1)|1` 用 `slli` + `addi` 合成（`slli` 后 bit0 恒 0 ⇒ 与上游 `ori` 等价）；
 *      本核一期无 `ORI`（G1-I 14 条子集）——这样 env 自身**不引入 RTL 子集外的任何新指令**，
 *      使 RTL 侧首处分歧必然来自**测试体**而非平台脚手架（实验设计要点，见 M2 的 findings）。
 *   3. 删除（依赖本核一期不具备的机制，逐条给依据）：
 *      · `RISCV_MULTICORE_DISABLE`（`csrr mhartid`）——一期 6 CSR 无 `mhartid`（`spec/10`）；
 *      · `INIT_SATP`（`csrwi satp`）／`DELEGATE_NO_TRAPS`（`mie`/`medeleg`/`mideleg`）——无 S 态、无委派（`spec/00` §2）；
 *      · `INIT_PMP`（`pmpaddr0`/`pmpcfg0`）——无 PMP（G1-I 清单 §1.2）；
 *      · `mtvec_handler` 委派段（`la t5, mtvec_handler; beqz t5, 1f; jr t5`）——无 `JALR`／`BEQZ`（14 条子集）；
 *      · 进测试体的 `la t0, 1f; csrw mepc, t0; csrr a0, mhartid; mret` 绕行——改为**直接落入测试体**
 *        （一期无 `mhartid`；`mret` 只在 handler 里用）。
 *   4. 未处理异常路径：上游 `ori TESTNUM, TESTNUM, 1337`（打 1337 标记）改为 `li TESTNUM, 1337`
 *      （`addi` 即可；语义更强——TESTNUM 直接置为标记值而不是按位或）。
 *   5. 入口：`_start` 即 `RESET_PC`（0x1000）——去掉上游 `.org 0x80`（低RISC fork 加）与
 *      `.balign 256`；`trap_vector` 仍按 256 B 对齐（`.align 8`，mtvec 直连模式的基址对齐）。
 *   6. `CHECK_XLEN` **保留**（上游原样）：需 `BGE`，属 RV64I 面（rv64ui 的 bge/blt 族本就要它）。
 *   7. `RVTEST_DATA_BEGIN` 的 `.tohost` 段内对齐 `.align 6`（64 B）改为 `.align 3`（8 B，`.dword` 所需）：
 *      上游 64 B 对齐会把段基址从 0x4000_0010 顶到 0x4000_0040（实测），而本项目的停机地址口径是
 *      **0x4000_0010**（TB `TOHOST_ADDR`／ISS `--tohost`／`test_smoke.TOHOST`）⇒ 不对齐到底会让
 *      测试写 `tohost` 落在 TB 认不出的地址上（表现为"跑完不停机"）。改 8 B 后符号 `tohost`
 *      恰在 0x4000_0010，`fromhost` 在 0x4000_0018（`sw/env/link.ld` 同址声明）。
 *
 * 本 env 用到的指令（⊂ G1-I 14 条子集，逐条核过）：`jal`（`j`）、`addi`（`li`/INIT_XREG）、
 *   `lui`（`%hi`）、`slli`、`beq`、`csrrw`（`csrw`）、`csrrs`（`csrr`）、`sw`。
 *   ⇒ **env 自身无缺口**；缺口清单由 `sw/tests/build_rv64ui.py --gap-all` 从测试体反算（机械）。
 *
 * 参考：riscv-tests README（env 层职责）；`doc/spec/00` §4.1（RESET_PC）；
 *       G1-I 清单 §1.1（14 条指令子集）；`doc/spec/02` §10（RV64I 全量条目）。
 ***************************************************************/
#ifndef _VR1_ENV_PHYSICAL_SINGLE_CORE_H
#define _VR1_ENV_PHYSICAL_SINGLE_CORE_H

#include "encoding.h"       /* 上游件逐字副本：sw/tests/riscv-tests/env/encoding.h */

/* ---------------------------------------------------------------------------
 * 测试体类型（-p 物理变体；本核一期无 S 态/无 MMU ⇒ 只支持 RV64U 一族）
 * ------------------------------------------------------------------------- */
#define RVTEST_RV64U                                                    \
  .macro init;                                                          \
  .endm

/* ---------------------------------------------------------------------------
 * 体量/寄存器初始化（上游原样）
 * ------------------------------------------------------------------------- */
#if __riscv_xlen == 64
# define CHECK_XLEN li a0, 1; slli a0, a0, 31; bgez a0, 1f; RVTEST_PASS; 1:
#else
# error "VR1 env 只支持 RV64（-march=rv64im_zicsr）"
#endif

#define INIT_XREG                                                       \
  li x1, 0;                                                             \
  li x2, 0;  li x3, 0;  li x4, 0;  li x5, 0;  li x6, 0;  li x7, 0;      \
  li x8, 0;  li x9, 0;  li x10, 0; li x11, 0; li x12, 0; li x13, 0;     \
  li x14, 0; li x15, 0; li x16, 0; li x17, 0; li x18, 0; li x19, 0;     \
  li x20, 0; li x21, 0; li x22, 0; li x23, 0; li x24, 0; li x25, 0;     \
  li x26, 0; li x27, 0; li x28, 0; li x29, 0; li x30, 0; li x31, 0;

/* 测试可覆盖的钩子（上游同名；本版不用 EXTRA_TVEC_*，用错即编译报错 ⇒ fail-closed） */
#define EXTRA_INIT
#define EXTRA_INIT_TIMER

/* ---------------------------------------------------------------------------
 * Begin Macro：复位向量 / trap 向量 / write_tohost / reset_vector
 *   布局（sw/env/link.ld 固定）：0x1000 = `_start`（j reset_vector）
 *                              0x1100 = `trap_vector`（256 B 对齐）
 * ------------------------------------------------------------------------- */
#define RVTEST_CODE_BEGIN                                               \
        .section .text.init;                                            \
        .weak mtvec_handler;                                            \
        .globl _start;                                                  \
_start:                                                                 \
        /* reset vector：入口即 RESET_PC（sw/env/link.ld 把 .text.init 放 0x1000）*/ \
        j reset_vector;                                                 \
        .align 8;                                                       \
trap_vector:                                                            \
        /* 是否来自 ecall：riscv-tests 的 ecall 型 PASS/FAIL 走这条路径 */ \
        csrr t5, mcause;                                                \
        li t6, CAUSE_USER_ECALL;                                        \
        beq t5, t6, write_tohost;                                       \
        li t6, CAUSE_SUPERVISOR_ECALL;                                  \
        beq t5, t6, write_tohost;                                       \
        li t6, CAUSE_MACHINE_ECALL;                                     \
        beq t5, t6, write_tohost;                                       \
        /* 未能处理的异常：TESTNUM 置 1337 标记（差异表第 4 条）后落盘 */ \
        li TESTNUM, 1337;                                               \
write_tohost:                                                           \
        lui t5, %hi(tohost);                                            \
        addi t5, t5, %lo(tohost);                                       \
        sw TESTNUM, 0(t5);                                              \
        j write_tohost;                                                 \
reset_vector:                                                           \
        INIT_XREG;                                                      \
        li TESTNUM, 0;                                                  \
        lui t0, %hi(trap_vector);                                       \
        addi t0, t0, %lo(trap_vector);                                  \
        csrw mtvec, t0;                                                 \
        init;                                                           \
        EXTRA_INIT;                                                     \
        /* 上游此处：INIT_PMP / INIT_SATP / DELEGATE_NO_TRAPS / csrw mepc+mret
           —— 均依赖本核一期不具备的机制，见差异表第 3 条；此处直接落入测试体 */

/* ---------------------------------------------------------------------------
 * End Macro
 * ------------------------------------------------------------------------- */
#define RVTEST_CODE_END                                                 \
        unimp

/* ---------------------------------------------------------------------------
 * Pass / Fail（差异表第 1、2 条：落 tohost，值 1 = PASS、(testnum<<1)|1 = FAIL）
 * ------------------------------------------------------------------------- */
#define RVTEST_PASS                                                     \
        li TESTNUM, 1;                                                  \
        j write_tohost

#define RVTEST_FAIL                                                     \
        slli TESTNUM, TESTNUM, 1;                                       \
        addi TESTNUM, TESTNUM, 1;                                       \
        j write_tohost

#define TESTNUM gp

/* ---------------------------------------------------------------------------
 * Data Section Macro（上游原样：`.tohost` 段由 link.ld 置于 0x4000_0010）
 * ------------------------------------------------------------------------- */
#define RVTEST_DATA_BEGIN                                               \
        .pushsection .tohost,"aw",@progbits;                            \
        .align 3; .global tohost; tohost: .dword 0;                     \
        .align 3; .global fromhost; fromhost: .dword 0;                 \
        .popsection;                                                    \
        .align 4; .global begin_signature; begin_signature:

#define RVTEST_DATA_END .align 4; .global end_signature; end_signature:

#endif /* _VR1_ENV_PHYSICAL_SINGLE_CORE_H */
