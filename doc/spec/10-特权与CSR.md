# VR1 特权架构、CSR 与 trap（doc/spec/10）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v0.1 | 2026-09-24 | 草稿（**骨架·首片**；未评审、未定稿） | 首片：篇首三段式＋**规范版本声明（三段式，ISS-007 ADR）**；§1 特权级与 CSR 分类；§2 trap 机制（进场/返回/委托）；§3 中断面（CLINT/PLIC/优先级）；§4 关键 CSR 一期口径；§5 系统指令语义面；§6 待补清单；§7 出口自检 |
| v0.1 续1（深化片 T-10-1） | 2026-09-25 | 草稿（待 Requirement Review） | **T-10-1 闭合**：§4.1 CSR 全表（地址/复位值/位段/WARL/权限）＋§4.2 委托细则＋§4.3 终裁（T-10-2/T-10-6）；三 ID／`misa` 定值／PMP 形态 经 **RD 决策（ADR-1~5，2026-09-25）** 自决并落文；新增参数落 `spec/00` §4.7（R-181） |

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

**进场（6 动作，M 侧；`spec/01` §3.18 承接）**：`mepc ← 触发指令 pc`（锚：【权】行 **46130–46131**「written with the virtual address of the instruction that was interrupted or that encountered the exception」——附 AK B3 更正：原标 46131，引句跨该两行）／`mcause ← 码`／`mtval ←` 触发信息（非法指令可回填指令位，锚：【权】行 46408–46421）／`mstatus.MPIE ← MIE`、`MIE ← 0`、`MPP ← 前级`／入口＝`mtvec`（Direct or Vectored，`spec/00` §4.7 `MTVEC_MODES`；【权】§3.1.7）。
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

### 4.1 CSR 全表（T-10-1；地址/复位值/位段/WARL/权限）

**说明**：数值除下表所列复位常量外**一律引 `spec/00` §4/§7**；不存在 CSR 的访问按 §4.2 权限口径判 illegal（锚：【权】42983）。`misa` 复位常量 `MISA_VALUE`＝`0x8000_0000_0014_1105`（MXL=2 RV64＋I/M/A/C/S/U；**写忽略**——只读常量；锚：44661–44704 复位＝maximal set／44682–44690 表 100 MXL／44730–44790 表 101 位号／44824–44831 `C` 位合规）。`mvendorid`/`marchid`/`mimpid`/`mhartid` 恒 0（锚：44842–44843／44867–44869／44898–44899／44913–44916）。

| CSR | 地址 | 复位值 | 位段要点（一期） | WARL/可写 | 权限 | 锚/引 |
|---|---|---|---|---|---|---|
| `mstatus` | 0x300 | 0 | `MIE/MPIE/MPP/MPRV/SIE/SPIE/SPP/SUM/MXR`＝R/W（**最小集**）；`TVM/TW/TSR` 常 0；`FS/XS/SD` 恒 0、写忽略；`MPP` 写保留值保原值 | WARL（ADR-2） | M=R/W；S 经 `sstatus` 子集（锚 47960） | `spec/00` §7.3；45327–45330／45352–45355／45250–45253（44149–44150 SUM） |
| `misa` | 0x301 | `MISA_VALUE` | 见上（写忽略） | 只读常量 | M=RO | 44661–44704 |
| `medeleg` | 0x302 | 0 | 可写位 {0,1,2,3,4,5,6,7,8,9,12,13,15}；位 11/16 恒 0 | WARL | M=R/W | 45706–45708 |
| `mideleg` | 0x303 | 0 | 可写位 {1,5,9}；LCOFI(13) 恒 0 | WARL | M=R/W | 45652–45674 |
| `mie` | 0x304 | 0 | 位 {1,3,5,7,9,11}（SSI/STI/SEI/MSI/MTI/MEI）；13 恒 0 | R/W | M=R/W | `spec/00` §4.7 |
| `mtvec` | 0x305 | 0 | `MODE`∈{0 Direct,1 Vectored}（写 ≥2 保旧值，同 Q30 法）；`BASE` 对齐 4B | WARL | M=R/W | 45610/45621 图 19＋表 104 |
| `mcounteren` | 0x306 | 0 | 位 {CY,TM,IR}（低 3 位；HPMn 不实现＝0） | WARL（锚 46035） | M=R/W | 45974–46037／图 27(46008) |
| `mscratch` | 0x340 | 0 | 全 64 位 R/W | — | M=R/W | — |
| `mepc` | 0x341 | 0 | bit0 恒 0；IALIGN=16 下 bit1 有效 | WARL | M=R/W | §2（46130–46131）；`spec/01` §3.18 Q30 |
| `mcause` | 0x342 | 0 | WLRL：12 类同步＋6 类中断 | — | M=R/W | §2（46408–46421） |
| `mtval` | 0x343 | 0 | 非法指令回填指令位 | — | M=R/W | 46408–46421 |
| `mip` | 0x344 | 0 | 位 {1,3,5,7,9,11}；**SSIP(1) 可写**、STIP(5)/MTIP(7) 由 CLINT 置位（写忽略）、SEIP/MSIP/MEIP 只读 | 部分 R/W | M=R/W | 45852–45897（45858–45859 msip） |
| `mcountinhibit` | 0x320 | 0 | 位 {CY,IR}（仅 2 位） | WARL | M=R/W | 46075–46083 |
| `mcycle` | 0xB00 | 0 | 64 位计数器；`mcountinhibit.CY` 门控 | — | M=R/W | 45940–45965 |
| `minstret` | 0xB02 | 0 | 64 位；`IR` 门控 | — | M=R/W | 45940–45965 |
| `mvendorid`/`marchid`/`mimpid`/`mhartid` | 0xF11/0xF12/0xF13/0xF14 | 0 | 恒 0（非商业实现合规） | 只读 | M=RO | 44842–44899／44913–44916 |
| `mhpmcounter3..31`（含 h 组） | 0xB03..0xB1F | 0 | **读回 0**（不实现） | 只读 0 | M=RO | `spec/00` §4.7；44004–44013（*h 组 RV32 only ⇒ 不存在） |
| `pmpcfg0`/`pmpcfg2` | 0x3A0/0x3A2 | 0 | RV64 每寄存器 8 条（`R/W/X/A[1:0]/L`）；**奇号寄存器不存在** | WARL（A∈{OFF,NA4,NAPOT}；L=1 后写忽略） | M=R/W | 47481–47492／47761–47762 |
| `pmpaddr0..7` | 0x3B0..0x3B7 | 0 | NAPOT/NA4 编码；`G`＝4B（G=0 无强制置零位） | WARL | M=R/W | 47680／47693–47729／47748–47752 |
| `sstatus` | 0x100 | 0 | ＝`mstatus` 的 S 可见子集（`SIE/SPIE/SPP/SUM/MXR`；`FS` 恒 0） | 同 `mstatus` | S=R/W | 47960 |
| `sie`/`sip` | 0x104/0x144 | 0 | 位 {1,5,9}（SSIE/STIE/SEIE）／{1,5,9}（SSIP 可写、其余 CLINT 置位） | 部分 R/W | S=R/W | `spec/00` §4.7 |
| `stvec` | 0x105 | 0 | 同 `mtvec` | WARL | S=R/W | 45610/45621（同构） |
| `scounteren` | 0x106 | 0 | 位 {CY,TM,IR} | WARL | S=R/W | 48248–48287（与 `mcounteren` 同置方可读） |
| `sscratch`/`sepc`/`scause`/`stval` | 0x140/0x141/0x142/0x143 | 0 | 同 M 侧对偶（`sepc` bit0 恒 0） | — | S=R/W | §2（S 侧同构） |
| `satp` | 0x180 | 0 | `MODE`：仅 8=Sv39（其余 WARL 保旧值）；`ASID` 宽=`ASID_BITS`；`PPN` | WARL | S=R/W | `spec/08` §1；`spec/00` §4 |
| `cycle`/`time`/`instret` | 0xC00/0xC01/0xC02 | 0 | 只读；受 `mcounteren`/`scounteren` 同位置位门控 | 只读 | U/S=RO（门控） | 46011–46037／48285–48287 |

**PMP 形态（ADR-3）**：8 项（`PMP_ENTRIES=8`）／粒度 `PMP_GRAIN=4B`（引 `spec/00` §4.6）；匹配模式＝**OFF＋NA4＋NAPOT（无 TOR）**——TOR 写合法化为 OFF（回退点：标准测试若用到 TOR ⇒ 升版补全）；`L=1` 对全模式强制、检查面为 S/U（锚 47766／47465–47469）；无匹配时 M 通过、S/U 拒绝（锚 47789）⇒ PMP 全 0 时 U 侧访问拒绝。

### 4.2 委托细则与 CSR 访问权限（T-10-1）

- **委托位域**：`medeleg` 可写 {0,1,2,3,4,5,6,7,8,9,12,13,15}（指令/访存/断点/环境/ECALL×3/页错误×3/浮点…按 12 类同步异常逐位；位 11/16 恒 0，锚 45706–45708）；`mideleg` 可写 {1,5,9}（SSI/STI/SEI）；**LCOFI(13) 恒 0**（`mip[13]=0`，与 `spec/00` §4.7 字面对账）。
- **委托命中进场（S 侧，与 M 同构换名）**：`scause ← 码`；`sepc ← 触发 pc`；`stval ←` 触发信息；`sstatus.SPP ← 前级`、`SPIE ← SIE`、`SIE ← 0`；入口＝`stvec`（Direct/Vectored，同 `mtvec`）；返回按 SRET（§2）。
- **特权与不存在的 CSR**：U 访问 `s*`/`m*`、S 访问 `m*`（除明文允许者）⇒ **cause=2 illegal instruction＋`mtval`＝指令位**（锚 46408–46421）；写只读 CSR（如 `misa`、`mvendorid`）同判 illegal；不存在的 CSR（含奇号 `pmpcfg1/3/…`、RV32-only 的 `*h` 组）⇒ 同上（锚 42983）。
- **`sfence.vma`/`satp` 的特权**：S 侧允许（`TVM=1` 时拦截，锚 45327–45330）；**U 侧执行 SFENCE.VMA ⇒ illegal**（特权指令；行号待补 ⇒ 登记）。

### 4.3 两项终裁（T-10-2／T-10-6）

- **WFI（T-10-2）＝NOP**（不实现挂起；锚：【权】47010「a legal implementation is to simply implement the WFI instruction as a NOP」＋47029–47031）；S/U 侧 WFI 若 `TW`/`TSR` 面将来放开另议（一期 `TW=0`）；唤醒面二期预留。
- **CSR 读副作用／`rd=x0`（T-10-6）**：**CSR 读零副作用**；`CSRRW` 且 `rd=x0` **不读 CSR**；`CSRRS/CSRRC` 恒读（即使 `rs1=x0`）（锚：5084–5085）；配套 `spec/01` §3.19 规则 5 与 ISS `csr_old=0` 口径。

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
| ~~T-10-1~~ | CSR 全表＋委托细则 | **已闭合（深化片，R-181）**：§4.1/§4.2 在文；RD ADR-1~5 自决 |
| ~~T-10-2~~ | `WFI` 挂起 | **已闭合（R-181）**：§4.3 终裁＝NOP（锚 47010） |
| ~~T-10-3~~ | `misa`/三 ID 定值 | **已闭合（R-181）**：§4.1（`MISA_VALUE`；三 ID+mhartid 恒 0） |
| T-10-4 | trap 进场动作与 `spec/01` §3.18 的逐拍对账（`vec_off`/`ret_ctrl_t`） | 深化片 |
| T-10-5 | `SFENCE.VMA` 失效面细则与 `satp` 序（含 ASID 复用） | `spec/08` T-08-4 同源 |
| ~~T-10-6~~ | CSR 读副作用/`rd=x0` | **已闭合（R-181）**：§4.3（零副作用；CSRRW rd=x0 不读） |

## 7. 出口自检（每项附复核手段）

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 规范版本声明三段式在位 | 篇首 1/2/3 条逐条可回查（版本行＝`spec/02` T-11 定案） | 一致 |
| 2 | 已取证锚直接标注 | §2 **五处**【权】行号（**46130–46131**／45127–45130／46408–46421／52453／52455–52458）逐条实读在案（附 AK C3 更正：原写「三处」系计数笔误） | 一致 |
| 3 | 未取证项已登记不裁定 | T-10-1/2/3/6 **已闭**（§4.1~§4.3）；T-10-4/5 留出口；SFENCE.VMA U 侧句行号待补（登记） | 一致（本片更新） |
| 4 | 数值零自造 | 数字 token 全量清点（8/3/3/2/6/0/39/31 等均带篇号节号） | 待本轮实跑 |
| 5 | 结构完整（表列数/码点） | `gate.py check` 的 `md-integrity`/`codepoints` | 待本轮实跑 |
