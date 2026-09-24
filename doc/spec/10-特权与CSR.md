# VR1 特权架构、CSR 与 trap（doc/spec/10）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v0.1 | 2026-09-24 | 草稿（**骨架·首片**；未评审、未定稿） | 首片：篇首三段式＋**规范版本声明（三段式，ISS-007 ADR）**；§1 特权级与 CSR 分类；§2 trap 机制（进场/返回/委托）；§3 中断面（CLINT/PLIC/优先级）；§4 关键 CSR 一期口径；§5 系统指令语义面；§6 待补清单；§7 出口自检 |

> **① 范围**：本篇给出**特权架构**的权威口径：特权级与 CSR 分类、trap 进场/返回、中断与委托、系统指令（ECALL/EBREAK/MRET/SRET/WFI/SFENCE.VMA）的语义面。
> **② 边界**：CSR 的**全表（地址/复位值/位段/WARL/访问权限）**在本篇深化片落成（首片只给分类与已定项）；接口与拍序引 `spec/01`（§3.17/§3.18/§3.19）与 `spec/05`；翻译/保护面归 `spec/08`；**数值一律引 `spec/00` §4**。
> **③ 引用纪律**：规范锚＝【权】特权卷（本机提取件；已取证行号直接标注，未取证项标「待补」并按规则 20 登记）。

**规范版本声明（三段式，ISS-007 ADR；ADR-5 口径）**：
1. **依据版本**：本机提取件 `riscv_spec_full.txt`（非特权卷 I ＋ 特权卷 II，实测版本行＝`Version 20260922: Intermediate Release`，`spec/02` §16.4-(4) T-11 定案）；
2. **锁定口径**：一期特权实现**锁特权 1.13 语义面**（知识库 ADR 选定），本机提取件为唯一一级依据；
3. **差异处理**：【用】等旧版 §号不可回查者只登记不裁定（T-11 同口径）。

---

## 1. 特权级与 CSR 分类

| 级 | 一期 | 说明 | 引 |
|---|---|---|---|
| M | 实现 | 唯一具备 trap 入口/委托权的级 | `spec/00` §2/§4.7 |
| S | 实现 | Sv39 翻译（`satp`）、`sfence.vma` | `spec/00` §2/§4.7 |
| U | 实现 | 无特权操作 | `spec/00` §2 |

**CSR 分类（首片口径）**：M 侧＝`mstatus/misa/medeleg/mideleg/mie/mtvec/mscratch/mepc/mcause/mtval/mip/mhartid/mvendorid/marchid/mimpid/mcounteren/mcountinhibit`；S 侧＝`sstatus/stvec/sie/sscratch/sepc/scause/stval/sip/scounteren/satp`（`spec/00` §4.7 `CSR_TRAP_SET` 行＝权威清单；**地址/位段/WARL 归本篇深化片**）。
**计数器**：`mcycle`/`minstret`/`time`（读外部 `mtime`）；`mhpcounter3..31` 不实现（读回 0）；`mcountinhibit` 只显 2 位（`spec/00` §4.7 `COUNTERS`）。

## 2. trap 机制（进场/返回/委托）

**进场（6 动作，M 侧；`spec/01` §3.18 承接）**：`mepc ← 触发指令 pc`（锚：【权】行 46131「written with the virtual address of the instruction that was interrupted or that encountered the exception」）／`mcause ← 码`／`mtval ←` 触发信息（非法指令可回填指令位，锚：【权】行 46408–46421）／`mstatus.MPIE ← MIE`、`MIE ← 0`、`MPP ← 前级`／入口＝`mtvec`（Direct or Vectored，`spec/00` §4.7 `MTVEC_MODES`；【权】§3.1.7）。
**返回（MRET/SRET）**：`pc ← xepc`；`MIE ← MPIE`、`MPIE ← 1`、`MPP ← 0`（锚：【权】行 52455–52458：MRET 先按 MPP/MPV 定新级，再写位段，最后置级与 `pc=mepc`）；**`MPP=M` 时不得清 `mstatus.MPRV`**（锚：【权】行 45127–45130「If y≠M, xRET also sets MPRV=0」；ISS-064 已按此修 ISS 侧）。
**重执行**：trap 返回后**重试触发指令**（锚：【权】行 52453「retrying the faulting instruction」）；该指令的写面抑制见 `spec/02` §19。
**委托**：`medeleg`/`mideleg` 决定 S 侧处置（S 侧进场动作与 M 同构、寄存器换名）；委托面首片只锁清单，细则归深化片（T-10-1）。
**trap 类 B 的冲刷/重取**：归 `spec/01` §5.3（D3-① 三路）——`mepc` 返回路径承担重执行。

## 3. 中断面

| 项 | 口径 | 引 |
|---|---|---|
| 源 | CLINT（MTIP/MSIP；`mtimecmp`/`msip`/`mtime`）＋PLIC-lite（8 source，3+3 bit，claim/complete） | `spec/00` §4.7 |
| 优先级 | `MEI > MSI > MTI > SEI > SSI > STI > LCOFI`（定死） | `spec/00` §4.7（【权】§3.1.9） |
| 采样 | 指令边界（`spec/01` §5.1 注入路径；`is_intr` 仅提交边界置位） | `spec/01` §3.7/§5.1 |
| NMI | **不实现**（`NMI_EN=0`；`nmi_i` 必须 tie 0；致命错误走「置复位」） | `spec/00` §4.7 |
| 委托 | `mideleg`（S 侧中断）；STIP/SSIP 由 CLINT 映射 | `spec/00` §4.7 |

## 4. 关键 CSR 一期口径（已定项；余归深化片）

| CSR | 一期口径 | 引 |
|---|---|---|
| `mstatus.FS` | 读回**恒 0（Off）**、非零写忽略；FP 指令 illegal | `spec/00` §7.3 |
| `misa` | 位段与定值归深化片（C/A/M 置位；`misa.C=1` 与 ISS 自账矛盾已在 `spec/02` §16.3.2 登记） | `spec/00` §2；`spec/02` §16.3.2 |
| `mtvec` | Direct＋Vectored | `spec/00` §4.7 |
| `satp` | 仅 Sv39（`MODE` 其余 WARL 归深化片） | `spec/08` §1 |

## 5. 系统指令语义面（行为归本篇；μop/分类引 `spec/02` §10.9）

| 指令 | 语义要点 | 引 |
|---|---|---|
| `ECALL` | 按当前级触发对应 cause（U/S/M） | `spec/02` §10.9 |
| `EBREAK` | 触发 breakpoint 异常（Debug 后置） | `spec/00` §4.7 |
| `MRET`/`SRET` | §2 返回动作；串行化类冲刷归 `spec/01` §5.3② | 本条 §2 |
| `WFI` | 一期＝NOP（挂起语义不实现，登记 T-10-2） | `spec/02` §16.3.3 行 2 |
| `SFENCE.VMA` | 失效纪律句见 `spec/08` §5；细则（ASID/VA 粒度）归深化片 | `spec/08` §5 |

## 6. 待补清单（T-10-x）

| # | 项 | 出口 |
|---|---|---|
| T-10-1 | CSR 全表（地址/复位值/位段/WARL/访问权限）＋委托细则 | 本篇深化片（**G1 前必须闭合**） |
| T-10-2 | `WFI` 挂起是否实现（一期 NOP 的最终裁定） | 深化片＋`spec/00` §4.7 对账 |
| T-10-3 | `misa` 位段与 `mvendorid`/`marchid`/`mimpid` 定值 | 深化片 |
| T-10-4 | trap 进场动作与 `spec/01` §3.18 的逐拍对账（`vec_off`/`ret_ctrl_t`） | 深化片 |
| T-10-5 | `SFENCE.VMA` 失效面细则与 `satp` 序（含 ASID 复用） | `spec/08` T-08-4 同源 |
| T-10-6 | CSR 读副作用/`rd=x0` 语义的终局口径（ISS 互校 D-3 遗留） | 深化片 |

## 7. 出口自检（每项附复核手段）

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 规范版本声明三段式在位 | 篇首 1/2/3 条逐条可回查（版本行＝`spec/02` T-11 定案） | 一致 |
| 2 | 已取证锚直接标注 | §2 三处【权】行号（46131／45127–45130／52453／52455–52458／46408–46421）逐条实读在案 | 一致 |
| 3 | 未取证项已登记不裁定 | T-10-1~6 逐项有出口；CSR 全表明标「归深化片」 | 一致 |
| 4 | 数值零自造 | 数字 token 全量清点（8/3/3/2/6/0/39/31 等均带篇号节号） | 待本轮实跑 |
| 5 | 结构完整（表列数/码点） | `gate.py check` 的 `md-integrity`/`codepoints` | 待本轮实跑 |
