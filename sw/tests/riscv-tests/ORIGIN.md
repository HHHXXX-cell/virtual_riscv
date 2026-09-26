# riscv-tests 源码入库说明（sw/tests/riscv-tests/ORIGIN.md）

> 本目录是 **RISC-V 官方 riscv-tests 仓库的逐字拷贝**（含 LICENSE），用于 M2 的合规回归。
> 入库批：2026-09-26 心跳批（M2 入册首片）。**入库后不得手改**：测试体与 `test_macros.h`
> 是**第三方判据面**，改一个字就等于换测试（红线 R6：禁改检查器让结果通过）。

## 1. 来源（本机路径，未联网）

| 项 | 值 |
|---|---|
| 上游仓库 | `riscv-tests`（UC Berkeley / Regents，BSD-3-Clause，见本目录 `LICENSE`） |
| 本机载体 | `D:\IC验证知识库\_tools\ibex-master\vendor\`（lowRISC ibex 仓库 vendored 副本） |
| 拷贝来源① | `…\vendor\riscv-tests\isa\rv64ui\*` → 本目录 `isa/rv64ui/`（50 个 `.S` ＋ `Makefrag`） |
| 拷贝来源② | `…\vendor\riscv-tests\isa\macros\scalar\test_macros.h` → 本目录 `isa/macros/scalar/` |
| 拷贝来源③ | `…\vendor\riscv-tests\LICENSE` → 本目录 `LICENSE` |
| 拷贝来源④ | `…\vendor\riscv-test-env\{LICENSE,encoding.h,p\riscv_test.h,p\link.ld}` → 本目录 `env/` |
| 工具链 | MSYS2 ucrt64 `riscv64-unknown-elf-gcc` 16.1.0 ＋ binutils 2.47（`doc/环境搭建.md`） |

**注意（来源侧与上游的差异）**：ibex 的 vendored 副本是 **lowRISC fork**——`env/p/riscv_test.h` 的
`RVTEST_PASS/FAIL` 改为写 `SIGNATURE_ADDR`（memory-mapped signature）后自旋，**不再写 `tohost`**；
且 `INIT_PMP`/`INIT_SATP`/`csrr mhartid` 等依赖 PMP／S 态 CSR。本项目的停机判据是 **`tohost`**
（`iss/tests/test_smoke.py` 的 `TOHOST=0x4000_0010` 与 `tb/unit/rt_t_trace_writer.sv` 同口径），
一期又只有 6 个 CSR、无 PMP／无 S 态 ⇒ **env 层必须做平台适配**（见 §2）。`env/p/` 与 `env/encoding.h`
在此**只作 diff 依据保留**（不参与编译）。

## 2. 本项目的 env 适配层（`sw/env/`，不在本目录）

| 文件 | 作用 | 与上游 `env/p/` 的差异（逐条可核） |
|---|---|---|
| `sw/env/riscv_test.h` | `RVTEST_*` 宏的平台适配版 | 见该文件头「适配差异表」：PASS/FAIL 落 `tohost`（上游 fork 落 signature）；删 `INIT_PMP`／`INIT_SATP`／`RISCV_MULTICORE_DISABLE`／`DELEGATE_NO_TRAPS`／`mtvec_handler` 委派；入口即 `RESET_PC=0x1000`；FAIL 值用 `slli+addi` 代上游 `ori`（等价，待 RTL 有 `ORI` 后换回，标 `TODO(M2)`） |
| `sw/env/link.ld` | 存储器映射（代码窗 0x1000~0x3FFF；数据窗 0x4000_0000＋；`tohost`＝0x4000_0010） | 上游 `env/p/link.ld`（代码 0x8000_0000／`tohost` 0x8000_1000）与 `tb/unit/m1_e2e_tb.sv` 的取指桩/数据桩窗口不符 |

**纪律**：`isa/rv64ui/*.S` 与 `isa/macros/scalar/test_macros.h` **逐字不改**（本目录内容只由拷贝产生）；
平台差异**只允许**落在 `sw/env/` 两个文件里，且必须逐条登记上表。

## 3. 编译与镜像（谁产出、怎么复核）

- 构建脚本：`sw/tests/build_rv64ui.py`（工具链调用、ELF 解析、`$readmemh` 镜像、MANIFEST、缺口清单）；
- 产物：`sim/image/rv64ui/<test>.{elf,hex,tb.hex,dump}` ＋ `sim/image/rv64ui/MANIFEST.json`；
- 复核：`python script/flow.py check-one m2-rv64ui`（真跑 ISS ＋ RTL 并逐条比对，fail-closed）。
