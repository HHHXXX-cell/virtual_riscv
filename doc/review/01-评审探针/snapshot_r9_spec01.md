# VR1 流水线与级间接口（doc/spec/01）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v0.1 | 2026-09-22 | **已由 R7 评审判为不通过** | 首版：17 级流水定义、13 个级间 struct 的成员位域、反压/冲刷/恢复点、trace 端口 |
| v0.2 | 2026-09-22 | 返工中（不是 G1 冻结候选） | 按 [`01-评审记录.md`](01-评审记录.md) 修正 21 项阻塞问题：位宽重算、`csr_wr_t` 补 `wdata`、`disp_x_t` 补预测反馈 4 域、映射历史栈、trace 异常条目与 PA 盲区、一期 NMI 移出等 |
| v0.3 | 2026-09-23 | 返工中（第 8 轮处置+复核、第 9 轮处置完成，待第 9 轮纯复核） | 按评审记录**附 E/F/G** 三轮处置：附 E 23 项（栈机制重构、冲刷/回填键闭合、nib 5 bit、slot16_start 移出、rt_t 四路来源、PERF 定死等）；第 8 轮复核新增 10 项（checkpoint 三元快照 `FL_ck` 回池防泄漏、CSR 队头发射门控、块起始 2 字节对齐、walk 规则重写、`src_val` 回填写口、csrq 截断回绕化、`rd_paddr` 载体、CT 措辞、BP3 `is_mem` 等） |

> 参数符号（`DECODE_WIDTH`、`ROB_ENTRIES` …）全部取自 `doc/spec/00` §4，本篇不另赋数值。
> 本篇一旦经 Review G1 签署即为**冻结基线**：RTL 端口表由此直接生成，之后任何位宽/语义变更
> 按红线 R5 先出改动报告待批（`AGENTS.md` §5.1）。
>
> ⚠️ **当前状态：未冻结。** v0.1 的出口自检表已被独立对抗评审证伪（见
> [`01-评审记录.md`](01-评审记录.md) Q21），**不得据本篇生成 RTL 端口表**。

---

## 1. 流水级定义

### 1.1 级号与职责

| 级号 | 名 | 所属段 | 时钟周期 | 主要动作 | 写哪些结构 |
|---|---|---|---|---|---|
| `P0` | `BP1` | 预测 | 1 | 取 `bp_pc`；查 L1BTB（64 直接映射）与 L2BTB（1024×4）；读 GHR/RAS 快照 | — |
| `P1` | `BP2` | 预测 | 1 | TAGE 多表并行读 → 最长历史命中仲裁 → SC-lite 校正 → ITTAGE-lite 目标选择 | — |
| `P2` | `BP3` | 预测 | 1 | 预测结果打包成 `ftq_req_t` 写入 FTQ；置 `ftq_id`（N15：原"spec_id"全篇无成员表定义，删除——投机块标签统一由 `ftq_id` 承担） | FTQ、GHR、RAS |
| `P3` | `F0` | 取指 | 1 | FTQ 队头出队；L1I TLB 查表（16 全相联）；PTW 缺失则挂起该 FTQ 项 | — |
| `P4` | `F1` | 取指 | 1 | L1I RAM 读（64B 行，按请求 `VA[5]` 选行内 32B 窗口——BLK-08：原写 `ftq.entry_offset`，该成员在任何 struct 中不存在，窗口选择本址就在请求 VA 里） | — |
| `P5` | `F2` | 取指 | 1 | 指令边界对齐（32B 窗口 → 最多 16 个 16bit 候选槽 / 8 个 32bit 槽）；写 IBUF | IBUF |
| `P6` | `D` | 译码 | 1 | **C 展开（16→32 位）+ 定长译码 + 立即数生成 + 预检非法** | — |
| `P7` | `R` | 重命名 | 1 | RAT 查/写、PRF 分配与回收、组内前递链、分支 checkpoint 分配 | RAT、PRF、free-list |
| `P8` | `S` | 分发 | 1 | **后读**读 PRF 取源值/置就绪、分配 ROB / IQ / LQ / SQ、写 `iq_wr_t` | ROB、IQ、LQ、SQ |
| `P9` | `W` | 发射 | 1 | 唤醒（CAM 相联）+ 选择（年龄 + 资源）→ 送执行单元 | IQ（清 valid） |
| `P10..P14` | `E1..E5` | 执行 | 1..5 | ALU/BRU/AGU 1 拍；MUL 3 拍；DIV 35 拍（不流水，独占） | — |
| `P15` | `WB` | 写回 | 1 | 结果写 PRF、置 `finish`、`wb_t` 广播唤醒 | PRF、ROB、IQ |
| `P16` | `CT` | 提交 | 1 | ROB 头按序提交（≤4/拍）：改 PRF 架构态、回收映射、触发 store、写 CSR | PRF、CSR、SQ、L1D |
| `P17` | `RT` | trace | 1 | 输出 `rt_t`（退休 trace，与 golden ISS 逐指令比对的唯一硬件真值） | — |

**关键时序结论（须在 `spec/13` 性能模型里体现）**：`WB(P15)` 与唤醒同拍，选择/发射在下一拍 `P9'`，
执行再下一拍 → **ALU→ALU 最短依赖间距 = 3 拍**（非旁路最优的 1 拍）。这是"后读 + 唤醒/选择分离"
换来的代价，依据与折中见【超】p.216-223、p.221-223；缓解手段是乱序窗口（ROB 128、6 发射）
覆盖依赖距离，而非把旁路网络加宽。**若 `spec/13` 的模型显示 IPC 因此达不到 1.8，回炉选项记录在
`doc/00`（新增条目），可选：①缩短到 2 拍（唤醒同拍完成选择，时序风险）；②前读 + 加宽 PRF 读口。**

### 1.2 为什么 IBUF 在译码之前（F2 写、D 读）

参照 P6 的解耦前端顺序：取指 → 指令队列 → 译码（ISB 引导）→ 重命名【超】p.415-419。
好处：①`F1` 的 L1I RAM 读与 `P0-P2` 的预测在时间上解耦，miss 时预测器可继续领先跑（FDIP）
【超】p.157-160；②译码器只消费已对齐、已落队列的指令字，缺失不再污染译码级；
③IBUF 只需存原始指令字（省面积），不必存 200 bit 的已译码 μop。
代价：`D` 级一拍内完成 C 展开 + 译码 + 立即数生成 + 非法预检，是关键路径候选（`spec/02` 里
按"展开查表 + 译码并行"处理：RV64C 展开为纯组合 64 项映射表）。

### 1.3 每拍吞吐

| 级 | 每拍最大数 | 参数 |
|---|---|---|
| 预测 | 1 个 FTQ 项（1 个预测块） | — |
| 取指→IBUF | 32 B / 16 个 16bit 候选槽（8 个 32bit 槽） | `FETCH_BYTES` |
| 译码 | 4 条（C 展开后统一 32bit 形式） | `DECODE_WIDTH` |
| 分发 | 4 μop | `DECODE_WIDTH` |
| 发射 | 6 μop（分 3 组：INT≤4、MEM≤2、BR≤1） | `ISSUE_WIDTH` |
| 写回 | 6 结果 | `WAKE_BCAST_PORTS` |
| 提交 | 4 条 | `COMMIT_WIDTH` |
| trace | 4 条 | `COMMIT_WIDTH` |

> 分组上限（INT≤4 / MEM≤2 / BR≤1）是各组的读口与执行单元数上限，不是队列条目数；
> 三组之和 7 > `ISSUE_WIDTH=6`，由选择器按年龄仲裁，见 `spec/05`。

---

## 2. 类型与位宽约定

| 类型名 | 定义 | 语义 |
|---|---|---|
| `xdata_t` | `logic [63:0]` | GPR 数据 |
| `va_t` | `logic [39:0]` | 虚拟地址/PC，宽 = `VA_STORE_W`（`spec/00` §4；含 bit39 规范检测位，Q22 定此参数并入了 `spec/00`）。**规范地址判据**：`VA[63:40] == {24{VA[39]}}` 且 `VA[39]==VA[38]`；不满足者由产生点（`D`/`AGU`/`bru`）置 `bad_va` |
| `pa_t` | `logic [43:0]` | 物理地址（`PA_BITS`） |
| `paddr_t` | `logic [5:0]` | PRF 索引（`PADDR_W`） |
| `areg_t` | `logic [4:0]` | 架构寄存器号（`RAT_IDX_W`） |
| `robptr_t` | `logic [7:0]` | 7 bit index + 1 bit wrap（`ROB_ENTRIES=128` 为 2 的幂） |
| `lqidx_t` | `logic [5:0]` | LQ 条目索引，值域 **0..47**（`LQ_ENTRIES=48`）；`lq_id`/`lqid` 一律用本类型 |
| `lqocc_t` | `logic [6:0]` | LQ 占用计数，值域 **0..48**。`empty=(occ==0)`、`full=(occ==48)`。**不再用“取模 96 的双指针差”判空满**（Q13：48 项既非 2 的幂、环长 96 又无独立占用计数，越权态与回绕都不可判定） |
| `sqptr_t` | `logic [5:0]` | 5 bit index + 1 wrap（32 为 2 的幂） |
| `seq_t` | `logic [11:0]` | 全局 μop 序号。年龄比较定死：`d=(a-b) mod 4096`；`d<2048` → b 更老；`d>2048` → a 更老；**`d==2048` → b 更老**（Q36：回绕边界不再外推给未评审篇目） |
| `isop_t` | `logic [9:0]` | 内部 op 编码；**完整枚举表只在 `spec/02` §3 定义**，本篇只引用位宽 |
| `exc_code_t` | `logic [3:0]` | 异常/中断原因码，值域见 `spec/10`（与 `mcause` 编码一致） |
| `csraddr_t` | `logic [11:0]` | CSR 地址 |
| `ckpt_t` | `logic [1:0]` | checkpoint **纯槽号 0..3**（`CHECKPOINT_COPIES=4`），无保留值。**“是否使用”由 `needs_ckpt` 唯一决定**：`needs_ckpt=0` 时 `ckpt_id` 无效且必写 `2'b00`（Q10；C1 复核指出“Q35”在评审记录中无对应行，引用已更正） |
| `ftqid_t` | `logic [4:0]` | FTQ 索引（4 bit index + 1 wrap，`FTQ_ENTRIES=16`）。**全篇 FTQ 序号一律本类型**；先后比较用含 wrap 位的回绕减法（同 `seq_t` 口径），禁止裸 `<`/`>`（N14：原 §3.2 `seq_of_ftq` 按"纯序号"另立第二编码，已删） |
| `ibufptr_t` | `logic [4:0]` | IBUF 索引（`IBUF_ENTRIES=16`） |

**非法组合防护**：所有 struct 的枚举型成员必须在 `spec/02`/`spec/08`/`spec/10` 的值域内，
由本篇 §7 的 SVA 与 `spec/11` 的 lint 规则共同保证（C6：原写“`spec/01` §8”系引用错位）（综合前用 `$onehot0`/`inside` 断言，
不用 SV 2023 新语法）。

---

## 3. 级间接口（struct 位域）

### 3.1 `ftq_req_t` — `BP3 → FTQ`（写，1/拍）

| 成员 | 位宽 | 语义 | 合法值域 |
|---|---|---|---|
| `valid` | 1 | 本拍有块入队 | |
| `pc` | 40 | 块起始 VA | 2 字节对齐（`pc[0]==0`；N-03：RVC 下条件分支/JALR 目标可 2 字节对齐，重定向后下一块起始=该目标，原"4 字节对齐"不可满足） |
| `nib` | 5 | 块内指令条数 | 1..16（0 保留；N7：32B 窗口全 RVC 可达 16 条，原 3 bit 三处口径互斥——编码容不下值域上界 8、又盖不住 16 槽，位宽按值域上限定） |
| `br_vld` | 1 | 块尾是分支 | |
| `br_type` | 2 | 00 条件 / 01 无条件 JAL / 10 间接(JALR) / 11 调用-返回对 | |
| `taken` | 1 | 预测方向 | |
| `target` | 40 | 预测目标 VA（`taken=1` 时有效） | 2 字节对齐 |
| `ras_op` | 2 | 00 无 / 01 push / 10 pop / 11 push+pop（尾调用） | |
| `ras_top` | 40 | push 数据 = `pc + 块内该分支长度` | |
| `pred_conf` | 2 | 置信度 0..3（SC 输出幅度分级） | |
| `bp_upd_id` | 8 | 预测更新表索引（提交反馈用；表结构与深度归 `spec/03`——**该篇待建**，N15③/CLR-02） | 0..255 |
| `bad_va` | 1 | `target` 非规范地址 | |

合计 1+40+5+1+2+1+40+2+40+2+8+1 = **143 bit**（机器核对通过；N7：`nib` 加宽后由 141 同步至此）

**FTQ 项覆盖范围（Q39 定死）**：一个 FTQ 项只覆盖到块内**首个可预测分支**为止（截断规则）；块内其后可能存在的分支由下拍重新走 `P0..P2` 预测。多分支块与双跳转列三期（`spec/00` 非目标）。`br_vld=0` 的块不消耗 checkpoint、不写预测表。

### 3.2 `ftq_entry_t` — `FTQ → IF`（读，≤1/拍）

= `ftq_req_t` 全字段（143 bit）+ 下表 2 个成员：

| 成员 | 位宽 | 语义 |
|---|---|---|
| `= ftq_req_t`（全字段复用） | 143 | 见 §3.1，机器核对基准行 |
| `icache_ready` | 1 | 缺失时为 0，令该项**停留队头**而非丢弃 |
| `ptw_req` | 1 | 该块需 PTW 预取 |

合计 143+1+1 = **145 bit**（Q34 引用的 `ptw_spec_id` 已改为本篇实际存在的 `ftq_id`；N14：原 `seq_of_ftq` 字段删除——读出口的序号由 FTQ 读指针自带，该字段既冗余又与 `ftqid_t` 构成双编码）

### 3.3 `fetch_raw_t` — `IBUF → D`（每拍至多 16 个候选槽，`D` 级消费 ≤4 条）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | 该 lane 有指令 |
| `pc` | 40 | 该指令首地址 |
| `raw32` | 32 | 原始指令字；压缩指令时 `is_c=1`、`raw32[31:16]` 无效（C6：原引的 `raw16_vld` 未在任何成员表中定义） |
| `is_c` | 1 | 原指令为 16 bit 压缩形式 |
| `bp_upd_id` | 8 | 所属 FTQ 项，供提交反馈 |
| `ftq_id` | 5 | |
| `err` | 1 | 取指侧已检出异常（I page fault / access fault / I misalign） |
| `err_code` | 4 | 异常码，见 `spec/08`/`spec/10` |

合计（逐成员相加）= 1+40+32+1+8+5+1+4 = **92 bit**
单槽 92 bit。**槽数两套（Q11 定死）**：16 个 16bit 候选槽（`FETCH_BYTES/2`）/ 8 个 32bit 槽。
**lane 语义与消费方式（N8 定案）**：IBUF→D 每拍组合读出全部 16 槽（1,472 bit），每 lane = 一个候选槽；`D` 级按 §3.16 的指令边界 walk 结果从中选取 ≤`DECODE_WIDTH` 个**起始槽**构建 uop——原标题"4 条/拍"与 16×92=1,472 bit 的矛盾就此消除（接口宽 1,472，消费 ≤4 条）。
**err 口径（N12 定案）**：L1I 侧 `icache_rsp_t` 的 `err_pos`（出错槽号）+`err_code` 在 P5 被展开为对应 lane 的 `err`/`err_code`——两套字段是**同一异常码**（`spec/10` 一张表）的"集中标注 → 按槽展开"两级表达，不是两种编码；边界判定职责：L1I 只标"哪些半字在窗内 + 哪个槽错"，**指令起始位图由 P5 判定**（§3.16），IBUF 存的仍是未译码原始字。
**IBUF 例化**：16 项 × 92 bit = **1,472 bit**（`spec/00` §4.8 表按此修正）。

### 3.4 `uop_t` — `D → R`（4 条/拍）

| 成员 | 位宽 | 语义 | 合法值域 |
|---|---|---|---|
| `valid` | 1 | | |
| `pc` | 40 | | |
| `raw32` | 32 | trace 用原始字 | |
| `is_c` | 1 | | |
| `isop` | 10 | 内部 op | `spec/02` §3 枚举 |
| `cls` | 3 | 000 ALU/逻辑 001 BR 010 LD 011 ST 100 MUL 101 DIV 110 CSR/SYS 111 FENCE/AMO | 8 值 |
| `rs1_en`/`rs2_en` | 2 | 源存在标志 | |
| `rs1`/`rs2` | 5+5 | 架构源号 | `x0` 合法（读恒 0，不分配 PRF） |
| `rd_en` | 1 | 有目的寄存器 | |
| `rd` | 5 | 架构目的号 | |
| `dst_kind` | 2 | 00 无 01 GPR 10 FPR(二期) 11 CSR 旧值→GPR | |
| `imm` | 44 | 已按 ISA 语义符号扩展 | |
| `imm_kind` | 2 | 00 地址偏移 01 ALU 立即数 10 CSR uimm[4:0] 11 shamt[5:0] | |
| `src_sel` | 2 | 00 PRF 01 imm 10 pc 11 zero | |
| `dm` | 2 | 访存宽度 00 B 01 H 10 W 11 D | |
| `sext` | 1 | load 符号扩展 / W 型指令结果按 bit31 扩展 | |
| `is_w` | 1 | W 型（32 bit 运算） | |
| `aq`/`rl` | 2 | AMO/LR-SC 与 fence 的 Acquire/Release 位【超】p.326-337 | |
| `fm` | 4 | fence 域位，`fence_pred[3:0]`/`fence_suc[3:0]` 两种取用共用此宽（Q24 定死 4 bit：原同写 3 bit 与 `fm[3:0]` 自相矛盾）；值域与取用方式归 `spec/02` | 见 `spec/02` |
| `csr_addr` | 12 | | |
| `csr_wr_type` | 2 | 00 RW 01 RS 10 RC 11 读使能-only | |
| `pred_taken` | 1 | 来自 FTQ 的预测 | |
| `pred_target` | 40 | | |
| `bp_upd_id` | 8 | | |
| `ftq_id` | 5 | | |
| `pre_exc` | 1 | 译码期已判异常 | |
| `pre_exc_code` | 4 | illegal / I misalign 等 | `spec/10` |
| `bad_va` | 1 | | |

合计（逐成员相加，脚本核对）= 1+40+32+1+10+3+2+10+1+5+2+44+2+2+2+1+1+2+4+12+2+1+40+8+5+1+4+1 = **239 bit**
（Q6 复算 238 是按 `fm=3`；Q24 定 `fm=4` 后为 239。`spec/00` §4.8 目前**没有 μop 行**（BLK-17），本值已列入 §8.2 待同步清单。）
一期不实现的 F/D 相关成员（`fm` 的浮点舍入用途）保留位宽但 `D` 级恒 0，满足 `spec/00` §7 的“二期不重构拓扑”要求；
**`rs3` 引用已删除**——本篇任何 struct 里都不存在该成员（Q6）。

### 3.5 `rmap_uop_t` — `R → S`（4 条/拍）

= `uop_t`（239）基础上按下表替换/追加（**融合 PRF 的关键简化**：源永远只有一个 `paddr`，就绪与否由 PRF 条目状态给出，不存在【超】p.224-230 的“三情况读源” mux）：

| 变化 | 位宽 | 说明 |
|---|---|---|
| `= uop_t`（全字段复用） | 239 | 见 §3.4，机器核对基准行 |
| `rs1`/`rs2`（架构号 5+5）→ `psrc1`/`psrc2`（`paddr_t` 6+6） | +2 | RAT 查表结果。**全篇统一名 `psrc1`/`psrc2`**（Q38：原 `ps1`/`ps2` 与 `psrc1`/`psrc2` 同物异名已消除） |
| 新增 `rd_paddr` | 6 | 分配到的目的物理号 |
| 新增 `rd_old_paddr` | 6 | 被覆盖的旧物理号（回滚堆栈写入口，见 §5.2 `R`） |
| 新增 `rd_is_new` | 1 | 目的号是否本拍新分配（回滚时据此判是否归还 free-list） |
| 新增 `ckpt_id` | 2 | 本 μop 所属 checkpoint 槽（`needs_ckpt=0` 时无效，见 §2 `ckpt_t`） |
| 新增 `is_br` | 1 | 分支标记（`S` 级消耗 checkpoint 用） |
| 新增 `needs_ckpt` | 1 | 该分支是否持有 checkpoint |
| 新增 `rs1_val` | 64 | `CSRRS/CSRRC` 需 `old PID rs1` 在提交拍可用（Q3：CSR 写通路不能断在 `commit_t` 之外）；**产生点 = `S` 级后读**（N-05 标注：本成员随 R→S 传递，但值在 P8 读 PRF 才产生） |

`raw32`/`pred_target` 在此级之后仍随流携带（trace 与恢复需要）。

合计 239+2+6+6+1+2+1+1+64 = **322 bit**（= `uop_t` 239 + 下表各项增量）

### 3.6 `rob_alloc_t` — `S → ROB`（4 条/拍）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `slot` | 8 | 分配到的 ROB 索引 |
| `pc` | 40 | |
| `raw32` | 32 | |
| `type[6:0]` | 7 | 类型位，**位序定死**：bit0 `is_c`、bit1 `is_br`、bit2 `is_comp`（C 展开的第二半）、bit3 `is_wfi`、bit4 `is_fence`、bit5 `is_mem`、**bit6 `is_csr`**。`rob_entry_t.type`（§3.7）与本域逐位直连（Q25 统一位序；**B1：`is_csr` 必须占位**——提交级没有 `cls`/`isop`，不能靠它们判 CSR） |
| `dst_kind` | 2 | |
| `rd_arch` | 5 | |
| `rd_paddr` | 6 | |
| `rd_old_paddr` | 6 | |
| `ckpt_id` | 2 | |
| `priv` | 2 | 该指令所在特权级（提交异常与委托判据） |
| `lq_v` | 1 | |
| `lq_id` | 6 | |
| `sq_v` | 1 | |
| `sq_id` | 5 | |
| `pre_exc` | 5 | {v, code[3:0]}——**纯译码异常，无 is_intr 位**（N11：中断不投机入 ROB，注入路径见 §5.1 与 §3.7 `is_intr` 行） |
| `seq` | 12 | |
| `grp_last` | 1 | 拆分组尾标记（Q26：同组任一资源不足则整组不分发，`S` 级据此保证不出现“等后辈的半条指令”） |
| `needs_ckpt` | 1 | 该分支是否持有 checkpoint（B2/Q10：槽释放判据与 A6 断言都依赖它，必须随 ROB 携带） |

合计（逐成员相加）= 1+8+40+32+7+2+5+6+6+2+2+1+6+1+5+5+12+1+1 = **143 bit**
（Q7：原写 125 系漏项，实算 140；Q26 新增 `grp_last`、B1/B2 新增 `is_csr` 位与 `needs_ckpt` 后为 143）

### 3.7 `rob_entry_t`（ROB 存储位域，128 项）

= `rob_alloc_t` 的存储子集 + 状态位：

| 成员 | 位宽 | 语义 |
|---|---|---|
| `v` | 1 | 条目有效 |
| `pc` | 40 | `mepc`/trace 用 |
| `raw32` | 32 | trace 用（`WB` 期不写，仅 `S` 期一次写） |
| `priv` | 2 | |
| `type[6:0]` | 7 | 位序与 §3.6 逐位一致（bit0 `is_c` … bit6 `is_csr`），直连 |
| `finish` | 1 | 结果已回（或无需结果） |
| `exc_v` | 1 | 异常/中断**标记**位——不立即处理，到 ROB 头才生效【超】p.368 |
| `exc_code` | 4 | |
| `is_intr` | 1 | **仅由提交边界中断注入路径置位**（连同 `exc_v`/`exc_code` 对 ROB 头条目写入，见 §5.1；N11：译码/执行异常路径恒 0，不存在投机中断条目） |
| `dst_kind` | 2 | |
| `rd_arch` | 5 | |
| `rd_paddr` | 6 | |
| `rd_old_paddr` | 6 | |
| `ckpt_id` | 2 | |
| `lq_v`/`lq_id` | 1+6 | |
| `sq_v`/`sq_id` | 1+5 | |
| `mem_done` | 1 | load 数据已回 / store 数据已入 SQ |
| `fdirty` | 1 | **一期用途 = 回滚归还判据**（该条目在 `S` 期分配过 PRF 目的号）；`spec/00` §7.3 承诺的二期 FP 脏位另设 `fp_dirty`（二期新增，一期不占位）——**BLK-10：两文档原语义冲突，此处定案并列入待同步** |
| `needs_ckpt` | 1 | 该分支持有 checkpoint（B2：提交级据此释放槽） |
| `seq` | 12 | 供 trace 与调试排序 |

合计（逐成员相加）= 1+40+32+2+7+1+1+4+1+2+5+6+6+2+7+6+1+1+12+1 = **138 bit** × 128 = **17,664 bit**
（Q8：原写 122 为漏项错算；B1/B2 新增类型位与 `needs_ckpt` 后为 138；`spec/00` §4.8 同步）

### 3.8 `iq_wr_t` — `S → IQ×3`（4 条/拍，带组选）

成员 = 执行与恢复所需全部域（**不含 `raw32`**，避免与 ROB 重复存储；Q9：逐成员定宽，**冻结基线禁止“≈”**）：

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `grp[1:0]` | 2 | 目标发射组（INT/MEM/BR） |
| `iq_slot` | 5 | 分配到的 IQ 条目号（0..23 / 0..19；N15：原 `slot` 与 `rob_alloc_t.slot` 同名异空间，改名；队列最深 24 项，5 bit 足够） |
| `isop` | 10 | |
| `cls` | 3 | |
| `psrc1` | 6 | 源 1 物理号（CAM 键） |
| `psrc2` | 6 | 源 2 物理号（CAM 键） |
| `rd_paddr` | 6 | |
| `rd_en` | 1 | |
| `dst_kind` | 2 | |
| `imm` | 44 | |
| `imm_kind` | 2 | |
| `pc` | 40 | |
| `src_sel` | 2 | |
| `dm` | 2 | |
| `sext` | 1 | |
| `is_w` | 1 | |
| `aq`/`rl` | 1+1 | |
| `csr_addr` | 12 | |
| `csr_wr_type` | 2 | |
| `rob_id` | 8 | |
| `seq` | 12 | |
| `pred_taken` | 1 | Q14：随发射送出 |
| `pred_target` | 40 | Q14 |
| `bp_upd_id` | 8 | Q14 |
| `ckpt_id` | 2 | Q14 |
| `ftq_id` | 5 | 所属 FTQ 项（N5：冲刷按 `ftq_id` 清 IQ 投机项——Q14 补了预测反馈 4 域却漏了冲刷键，本行闭合） |

合计（逐成员相加）= 1+2+5+10+3+6+6+6+1+2+44+2+40+2+2+1+1+1+1+12+2+8+12+1+40+8+2+5 = **226 bit**
（Q9：原”≈181”不可复现；Q14：新增 `bp_upd_id`/`ckpt_id`；N5：新增 `ftq_id`；N15：`slot`→`iq_slot` 5 bit 后为 226。）
队列例化：`IQ_INT 24×226 + IQ_MEM 20×226 + IQ_BR 20×226` = 64×226 = **14,464 bit**（Q9：原 11,584 按 181 估算，一并改）。

### 3.9 `iq_entry_t` 就绪位（每条目额外）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `v` | 1 | 条目有效 |
| `rdy1`/`rdy2` | 1+1 | 两个源的就绪位 |
| `psrc1` | 6 | 源 1 物理号（CAM 比较对象） |
| `psrc2` | 6 | 源 2 物理号 |
| `age` | 12 | `seq_t`，发射年龄比较 |

合计（逐成员相加）= 1+1+1+6+6+12 = **27 bit/条目**（全 IQ 附加 = 64×27 = 1,728 bit）。
CAM 唤醒比较键 = `paddr[5:0]` + `wb_valid`，每条目 2 次 6 bit 比较、广播 6 端口（`WAKE_BCAST_PORTS`）
→ 全队列比较数 `(24+20+20)×2×6 = 768` 次 6bit 比较/拍（【超】p.229-230、p.432-434：CAM 是乱序核心的成本中心；
此数即 `spec/05` 的时序评估入口）。**该数只取决于队列条目数与比较键宽，与 `iq_wr_t` 位宽无关**；
`psrc1`/`psrc2` 命名与 §3.5/§3.8 统一（Q38：同物异名已消除）。

### 3.10 `wb_t` — 结果写回与唤醒广播（6 条/拍）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `paddr` | 6 | 目的物理寄存器号（CAM key） |
| `data` | 64 | 结果 |
| `rob_id` | 8 | 置 `finish` |
| `src_kind` | 1 | 0=执行结果 1=CSR 旧值。**产生点定死（N10）**：E 级 `vr1_csr` 读端口投机读出 old——**执行授权门控（N-02 修正）：该 μop 此刻为 `csrq` 队头**（更老 CSR 均已提交出队）⇒ 读出值必为提交序最新（原稿"`csrq` 空"门控与"`R` 级入队"自相矛盾、恒假，BLK-09 同型"条件永假"错）；提交拍产生的是**写**（`csrq` 出队执行），**读**（`rd_data`/`csr_old` 来源）在执行级完成——原"old 在提交拍组合产生"使 `wb_t.src_kind=1` 无承载通路 |

合计 1+6+64+8+1 = **80 bit** × 6（第 1 轮评审 A 类：原写 79 系漏算 `src_kind`；逐成员相加 = `valid`1+`paddr`6+`data`64+`rob_id`8+`src_kind`1。N15：原引"Q7"系归因漂移——Q7 实为 `rob_alloc_t`，据此更正引用）

### 3.11 `disp_x_t` — `IQ → 执行单元`（6 条/拍）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `eu_id` | 4 | 目标单元号（0..8，`N_EU_TOTAL=9` 需 4 bit；Q12：原 3 bit 使第 9 号单元永远选不到） |
| `isop` | 10 | |
| `rs1_val`/`rs2_val` | 64+64 | 分发级已读出的操作数（后读，队列不存值） |
| `imm` | 44 | |
| `pc` | 40 | |
| `rob_id` | 8 | |
| `dm`/`sext`/`is_w`/`aq`/`rl` | 2+1+1+1+1 | |
| `csr_addr`/`csr_wr_type` | 12+2 | |
| `lq_id`/`sq_id` | 6+5 | |
| `pred_taken` | 1 | 来自 FTQ 的预测方向（Q14：随发射送给 BRU） |
| `pred_target` | 40 | 预测目标（Q14） |
| `bp_upd_id` | 8 | 预测表更新索引（Q14，转交 `br_resolve_t` 回写 `spec/03`） |
| `ckpt_id` | 2 | 该分支占用的 checkpoint 槽（Q14；`needs_ckpt=0` 时无效） |
| `ftq_id` | 5 | 所属 FTQ 项（N5：随发射携带，BRU 解析后冲刷按它清 FTQ） |

合计（逐成员相加）= 1+4+10+64+64+44+40+8+2+1+1+1+1+12+2+6+5+1+40+8+2+5 = **322 bit** × 6
（Q14：原 293 且缺预测反馈 4 域，导致前端反馈与 checkpoint 恢复在接口链上断裂，已补齐；N5：再补冲刷键 `ftq_id` 后为 322）

### 3.12 `br_resolve_t` — `BRU → 冲刷控制`（1 条/拍）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `rob_id` | 8 | |
| `pc` | 40 | 分支 PC（更新预测表与 `mepc`） |
| `taken_real` | 1 | 实际方向 |
| `target_real` | 40 | 实际目标（间接分支用 `rs1_val+imm` 再判规范地址） |
| `mispred` | 1 | = `taken_real != pred_taken`，或 taken 且 `target_real != pred_target` |
| `bad_va` | 1 | 目标非规范地址（→ instruction access fault） |
| `is_jalr_ret` | 1 | RAS 更新用 |
| `pred_taken`/`pred_target` | 1+40 | 反馈给 `spec/03` 的 IUM 更新模仿器 |
| `bp_upd_id` | 8 | |
| `ckpt_id` | 2 | 恢复 RAT 用（**仅错误分支使用**，不依赖 ROB 回滚） |
| `ftq_id` | 5 | 本分支所属 FTQ 项（N5：§5.2 `F0..F2` 行"清 `ftq_id` 之后的 FTQ 项"的键——Q14 漏补项，无它则冲刷键断链） |

合计（逐成员相加）= 1+8+40+1+40+1+1+1+1+40+8+2+5 = **149 bit**

### 3.13 `mem_req_t` — `LSU/IF → L1D/L1I`（含 `mmu_transl_*` 的下游请求形态）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `kind` | 2 | 00 LD 01 STD 10 IF 11 PTW |
| `va` | 40 | 翻译前地址（PTW/TLB 用） |
| `pa` | 44 | 翻译后（`mmu` 输出后回填） |
| `size` | 2 | `dm` |
| `amo_op` | 4 | `spec_union{LR,SC,SWAP,ADD,XOR,OR,AND,MIN,MAX,MINU,MAXU}`（`AMO` 在 L1D 内 RMW，不发总线，见 `spec/00` §8） |
| `sign_ext` | 1 | |
| `rob_id` | 8 | |
| `rd_paddr` | 6 | load 结果的目的 PRF 号（N-08：`dcache_rsp_t.rd_paddr` 的来源，随请求携带、响应透传） |
| `lq_id`/`sq_id` | 6+5 | |
| `priv` | 2 | 翻译/PMP 判据 |
| `is_fetch` | 1 | 取指访问不参与数据侧 store-forward 比较 |
| `ifetch_offset` | 6 | L1I 行内窗口偏移（**必须显式携带**，否则 32B 窗口取 64B 行的选择逻辑说不清） |
| `req_id` | 3 | 与 `mshr_wake_t` 对应的 outstanding 号 |
| `seq` | 12 | |

合计（逐成员相加）= 1+2+40+44+2+4+1+8+6+6+5+2+1+6+3+12 = **143 bit**
（原写 149 系漏项错算；成员表即权威，改动不得反向回填数字。N-08：新增 `rd_paddr` 后为 143）

### 3.14 MMU 翻译接口（req / rsp）

#### `mmu_transl_req_t` — `LSU/IF → MMU`（请求）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `va` | 40 | 翻译前地址 |
| `kind` | 2 | 00 LD 01 ST 10 IF 11 PTW |
| `priv` | 2 | 当前特权级 |
| `rw` | 2 | 访问权限检查（R/W/X） |
| `fetch` | 1 | 取指访问 |
| `ftq_id` | 5 | 触发本翻译的 FTQ 项（N4：PTW fill 写 TLB 前须按 A5 与冲刷集比对——原断言引用的键在任何 struct 都不存在；仅 IF/PTW 类请求有效） |
| `lqid` | 6 | Q23 定宽 |
| `robid` | 8 | |

合计（逐成员相加）= 1+40+2+2+2+1+5+6+8 = **67 bit**（原写 69 为漏项；N4：新增 `ftq_id` 后为 67）

#### `mmu_transl_rsp_t` — `MMU → LSU/IF`（回填）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `pa` | 44 | |
| `super` | 3 | 命中大页级别（0=4KB,1=2MB,2=1GB，其余保留） |
| `pma` | 4 | {`cacheable`,`strong_order`,`no_prefetch`,`device`}（`spec/00` §8、`spec/09`） |
| `fault` | 2 | 00 无 01 page-fault 10 access-fault 11 保留 |
| `code` | 4 | `exc_code_t` 细分 |
| `tlb_hit` | 1 | |
| `ftq_id` | 5 | 回传请求侧 `ftq_id`（N4：IF 类响应按它路由与做 A5 冲刷比对；fill 侧同键贯穿） |
| `lqid` | 6 | |
| `robid` | 8 | |

合计（逐成员相加）= 1+44+3+4+2+4+1+5+6+8 = **78 bit**（原写 68 为漏项；N4：新增 `ftq_id` 后为 78）

### 3.15 缺失处理接口（miss / fill / wake）

#### `miss_req_t` — L1 → MSHR/L2（缺失请求）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `pa` | 44 | |
| `way` | 4 | |
| `set` | 6 | L1 的 64 set |
| `is_write` | 1 | |
| `order` | 2 | Q23：`ro[1:0]` 改名；0=Normal / 1=RO / 2=Device-nRnE，指向 `spec/08` |
| `kind` | 2 | |
| `req_id` | 3 | 8 个 outstanding |

合计（逐成员相加）= 1+44+4+6+1+2+2+3 = **63 bit**（原写 62 为错算）

#### `fill_t` — L2 → L1（行填充）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `pa` | 44 | |
| `way` | 4 | |
| `set` | 8 | L2 的 256 set（与 L1 的 6 bit 不同宽，**有意为之**，不做统一 `set_idx_t`） |
| `victim_dirty` | 1 | |
| `victim` | 64 | 逐出行数据 |
| `sel` | 2 | 窗口选择 |
| `req_id` | 3 | 对应 outstanding 号（N6：§5.2 `F0..F2` 行"按 `req_id` 丢弃回填"的钥匙——原 `fill_t` 无此成员，错误路径 fill 无法判归属） |
| `seq` | 12 | |

合计（逐成员相加）= 1+44+4+8+1+64+2+3+12 = **139 bit**（原写 138 为错算；N6：新增 `req_id` 后为 139）

#### `mshr_wake_t` — MSHR 唤醒（9 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `idx` | 3 | MSHR 号；**本地副本表归 `vr1_l2`**，且**入队当拍不得重用同一 `idx`**（Q36） |
| `ok` | 1 | |
| `code` | 4 | 失败细分 |

合计（逐成员相加）= 1+3+1+4 = **9 bit**（原写 14 为错算；只发索引，不重复携带 PA）

### 3.16 cache 响应接口

#### `icache_rsp_t` — L1I → IF（取指返回）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `err` | 1 | |
| `code` | 4 | |
| `win` | 256 | Q15：32B 窗口原文 |
| `seq` | 12 | |
| `win_base_pc` | 40 | 窗口基址 = 请求 VA[39:5] 补 5 个 0。**产生点定死（BLK-08）**：由 `vr1_l1i` 对请求 VA 做 32B 对齐得出，随响应返回（原”B5 新增”未写产生者，属不可实现悬空）；槽地址 = 基址 + 2×槽号 |
| `slot16_vld` | 16 | 16 个 16bit 槽各是否**完整落在窗口内** |
| `err_pos` | 4 | Q15：原 3 bit 索引不了 16 个槽 |
| `err_code` | 4 | 与 §3.3 `err_code` 同表同义（N12） |

合计（逐成员相加）= 1+1+4+256+12+40+16+4+4 = **338 bit**
（B5 修正：原 `entry_vld2[7:0]` + `entry_pc[7:0]` 方案既无基址载体、又覆盖不了 16 条全 RVC 展开、且未定义 32bit 起始于奇数槽的边界；改用**基址 + 槽标志**表达。**BLK-08/N12：`slot16_start` 从本接口删除**——指令起始判定要读半字内容（低 2 bit ≠`11` 为 16 bit），属译码动作，L1I 不做；起始位图由 P5（`vr1_ifetch` 内部）按下述规则 walk 产出。）

**指令边界 walk 规则（P5 内部，BLK-08③ 定案；N-04 修正）**：窗口槽号 0..15，槽地址 = `win_base_pc` + 2×槽号；**块首槽 = 块起始 `pc[4:1]`**（`win_base_pc[1:0]` 恒 00，无定位信息，不作定位键）。①从块首槽起逐槽判定：槽半字低 2 bit ≠`11` → 16 bit，下一起始 = 当前+1；= `11` → 32 bit，占当前槽与当前+1 槽，下一起始 = 当前+2（**起始可落任意槽号**，由指令字节对齐决定，无"只落偶数槽"约束）；②32 bit 指令起始槽 =**15** 时跨窗口尾（后半不在窗内）→ 不产出起始（`slot16_vld` 仍置位），该条**随下一窗口重取**，取指窗口不跨 32B 边界拼接指令；③`err_pos` 命中槽处截断：其后槽不再产出起始，错误经 `err_pos` 展开为 §3.3 按 lane 的 `err`/`err_code`。

#### `dcache_rsp_t` — L1D → LSU（数据返回）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `data` | 64 | |
| `rd_paddr` | 6 | 目的 PRF 号（N-08 定案：由 LSU 经 `mem_req_t.rd_paddr` 携带、L1D **透传**——L1D 无从自知 PRF 号；原名 `paddr` 语义列空白，与 44 bit 物理地址构成两读歧义，故改名并填语义） |
| `robid` | 8 | |
| `fwd_hit` | 2 | 00 无 01 单源 10 双源拼接 11 保留（`FWD_MAX_SOURCES=2`） |
| `fwd_src` | 6 | |

合计（逐成员相加）= 1+64+6+8+2+6 = **87 bit**（原写 84 为错算）

### 3.17 `commit_t` — `ROB → CSR / freelist / SQ`（4 条/拍）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `rd_en` | 1 | |
| `rd_paddr` | 6 | PRF 状态由"缓冲有效"改"架构态"，**不搬数据**【超】p.183-186 |
| `rd_old_paddr` | 6 | 回收进 free-list |
| `lq_dealloc`/`lq_id` | 1+6 | load 可提交 = 数据已回 + 无异常 |
| `sq_dealloc`/`sq_id` | 1+5 | store 从此刻才允许写 cache |
| `csr_vld` | 1 | 本条为 CSR 写（`type[6]=1`）**且** `csrq` 队头 `rob_id` 命中本条（B1 定死） |
| `csr_wr` | 81 | `csr_wr_t`（§3.19，含 `wdata[63:0]`） |
| `exc_vld` | 1 | 本条提交时进入 trap（Q2：原标 138 是拿整个异常包当标志位） |
| `exc_pkt` | 177 | `excp_t`（§3.18），`exc_vld=1` 时有效 |
| `ret_vld` | 1 | MRET/SRET |
| `ret_pkt` | 49 | `ret_ctrl_t`（§3.18，含 `is_sret` 组别位） |
| `wfi_vld` | 1 | |
| `seq` | 12 | |

合计（逐成员相加）= 1+1+6+6+1+6+1+5+1+81+1+177+1+49+1+12 = **350 bit**

**WFI 语义（Q37 定死）**：唤醒事件 = 任何 `mip & mie` 的 pending 变化（**不看全局 MIE、不看委托**）；
假醒后按【权】§3.3.3 回查重试；tb 侧必须带超时退出判据并计入回归，否则裸机 WFI 表现为永久停住（伪挂死）。

### 3.18 异常包与返回控制（`excp_t` 177 bit / `ret_ctrl_t` 49 bit）

#### `excp_t` — trap 现场（177 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `vld` | 1 | |
| `cause` | 4 | 原因码；Q20：一期 `NMI_EN=0`，值域**不含 NMI** |
| `is_intr` | 1 | |
| `epc` | 40 | |
| `tval` | 40 | |
| `from` | 2 | 触发时特权级 |
| `to` | 2 | 目标特权级 |
| `deleg` | 1 | `medeleg`/`mideleg` 组合输出（见下） |
| `vec_off` | 6 | vectored 模式偏移 |
| `instr` | 32 | |
| `is_c` | 1 | |
| `sbe` | 1 | |
| `cle` | 1 | |
| `svae` | 1 | |
| `va_bad` | 1 | |
| `mprv_at_trigger` | 1 | |
| `mpp_at_trigger` | 2 | |
| `spep` | 40 | |

合计（逐成员相加）= 1+4+1+40+40+2+2+1+6+32+1+1+1+1+1+1+2+40 = **177 bit**
（Q1：原同 struct 三处合计 96/138/177 互斥，此后**只认此表**，行内算式一律废弃。）

#### `ret_ctrl_t` — MRET/SRET 返回控制（49 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `vld` | 1 | |
| `epc` | 40 | |
| `pp` | 2 | |
| `pie` | 1 | |
| `ie` | 1 | |
| `mprv_clr` | 1 | MRET 隐式清 MPRV（Q29 串行化规则绑定） |
| `mode` | 2 | 返回目标模式（归底规则在提交拍判定） |
| `is_sret` | 1 | **C10 新增**：MRET(0)/SRET(1)，选择 `mepc/sepc` 与 `mstatus/sstatus` 组；**生产点 = `vr1_csr` 在提交拍组合输出**（与 `deleg` 同法） |

合计（逐成员相加）= 1+40+2+1+1+1+2+1 = **49 bit**
（Q2：`commit_t.exc_vld` 改 1 bit、异常包改挂 `exc_pkt`(177)；C10 复核后新增 `is_sret` 组别位 → **49 bit**。**BLK-12 三个数定案**：50 系评审处置列笔误、48 系 `is_sret` 加入前的旧值、49 为现值（成员表为唯一权威，标题与本行均已改 49）；本更正记入评审记录**附 F**，机判输出留档 `doc/05` R-005。）
- **`deleg_to_s` 判定所需的 `medeleg`/`mideleg` 位由 `vr1_csr` 以组合输出随 `excp_t` 给出**（`deleg`），
  避免 `vr1_trap` 直接索引 CSR 数组、污染 CSR 模块边界。
- **`mprv_at_trigger`（1）与 `mpp_at_trigger`（2）必须在 `excp_t` 里**：`MPRV=1` 时数据访存按 MPP
  特权级做翻译/保护，而 trap 现场保存用的是**真实** `priv`，二者不同【权】§3.7。
- **`svae` 必须显式**：一期为"硬件置 A/D"（`spec/00` §4.6 `AD_BITS_POLICY`），故无 Svade 异常；
  若二期改 Svade，位段已留。
- `ret_ctrl_t` 中的 `epc[39:0]` 与 `mode` **必须打包进本 struct 并随 commit 流水传递**，理由：`xPP←最低可用模式`
  的归底规则要在提交拍判定【权】§3.3.2，若留在 CSR 单元里按 ROB 号回查，需要为 4 个提交 lane 各开
  一条回查通路。
- **NMI（Q20）**：一期 `NMI_EN=0`（`spec/00` §4.7 同步），`cause` 值域中**不含 NMI**；硬件致命错误上报
  走“置复位”；NMI 与 `Smrnmi` 整体移入非目标（`spec/00` 非目标表同步）。
- **MPRV 一致性（Q29）**：写 `mstatus`（MPRV 变化）与 `MRET/SRET` 一律按**串行化指令**处理——提交时冲刷
  在途指令，且禁止后续翻译越过该提交点，否则会拿旧特权级建的 TLB 项做新特权级访问（【权】§3.7）；
  `doc/02` 需有对应验证点。
- **xPP WARL（Q30）**：向 MPP 写 `2'b10` 保持原值不变；`mepc[0]` 写忽略、读恒 0（`IALIGN=32` 时 bit1 同理）；
  RTL 与 ISS 必须同口径，细则归 `spec/10`。

`excp_t` 的 `sbe`/`cle` = `mstatus.SBE`/`mstatus.CLE`（字节序与大端相关，一期恒 0，见 `spec/10`）。

### 3.19 `csr_wr_t` — CSR 写端口（81 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `vld` | 1 | |
| `addr` | 12 | |
| `op` | 2 | 00 RW 01 RS 10 RC 11 读使能-only |
| `wdata_sel` | 2 | 选择 `rs1_val`/`imm`/`old` 之一 |
| `wdata` | 64 | 待写值 |

合计（逐成员相加）= 1+12+2+2+64 = **81 bit**

（Q3：CSR 写数据**必须走本端口**——原稿“值由 `commit_t` 其他成员取得”使写通路在冻结接口上断开：
`commit_t` 里除 `excp_t`（trap 专用）外没有任何成员携带待写值。原写 14 bit 亦错，逐成员相加为
17 + `wdata` 64；`wdata` 的来源由 `wdata_sel` 选择，编码归 `spec/10`。）

#### `csrq_entry_t` — CSR 写队列（`R` 级入队 → 提交拍出队）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `rob_id` | 8 | 对应 ROB 条目（提交拍的命中判据） |
| `addr` | 12 | |
| `op` | 2 | |
| `wdata_sel` | 2 | |
| `src_val` | 64 | `rs1_val`（RS/RC/RW）；立即数型由 `wdata_sel` 指定取 `imm`。**回填写口定案（N-05）**：寄存器型在 `S` 级后读拍按 `rob_id` 命中写入（`rs1_val` 在 P8 才读出，入队拍尚不存在），I 型在 `R` 级入队时即写定——队列因此需按 `rob_id` 的命中写口（`S` 写 `src_val`、`E` 写 `old_val`，同一机制） |
| `old_val` | 64 | E 级投机读出的 CSR 旧值，按 `rob_id` 命中写回本条目（N10：trace 的 `csr_old` 与 CSRRW 类 `rd_data` 的共同载体；发射门控见 §3.10 `src_kind` 行） |

合计（逐成员相加）= 8+12+2+2+64+64 = **152 bit**（队列例化：8 项 × 152 bit = **1,216 bit**）

（**B1 新增，闭环 Q3**：`R` 级把每个 CSR μop 推入本队列；提交拍 `csr_vld = type[6] && (csrq 队头 rob_id == ROB 头 rob_id)`，
`csr_wr` 的 `addr/op/wdata_sel/wdata` 全由队头驱动，`old` 由 CSRA 组合读、`RS/RC` 的 `old|src_val` 在 CSR 单元内合成（编码归 `spec/10`）。
深度 8 的依据：CSR 写必须按序，深度只影响 CSR 密集程序的性能、**容量安全由 `R` 级反压保底**（原写“8 项覆盖两拍”的依据不成立，第 6 轮 CLR-01）；溢满时 `R` 级反压（与 BP2 同口径）。）

**csrq 的三条硬规则（第 6 轮 BLK-01/02/03 补齐）**：

1. **冲刷作废**：入队顺序 = 程序顺序，故冲刷时直接把队列**截断到冲刷点之前**——保留**比冲刷分支更老**的条目，判据 `older(e, f) ≜ ((f − e) mod 256) < 128`（`e`=条目 `rob_id`，`f`=冲刷分支 `rob_id`；与 `robptr_t`/`seq_t` 同回绕减法口径，**禁裸比较**——N-07：裸 `≤` 在 `rob_id` 回绕后判定反向，BLK-01 原后果复发）；否则僵尸条目会卡住队头，且 `rob_id` 回绕后会误命中陈旧 `addr/op/wdata`。
2. **`src_val` 的解析责任在 `R` 级**：`src_val` = 该指令 rs1 语义值，来源由 `imm_kind`/指令类型判定（寄存器型取 `rs1_val`，**I 型 CSR 取 `imm[4:0]` 零扩展**——CSR uimm 是 5 bit **无符号**数【用】§2.8；N13：原"符号扩展后的 imm"会在 uimm≥16 时与 Spike 分叉，分叉点落在 `csr_wr.wdata`，属假红或静默写错）——故 `csrq_entry_t` 不需另带 `imm` 字段。
3. **同包多 CSR = 序列化提交**：一个提交包内一旦出现 `type[6]=1`，本拍**只提交最老的那条**，同包其余 lane 下拍重提（否则除最老 lane 外的 CSR 全被静默跳过，A12 也检不出）。

### 3.20 执行/访存完成回报

#### `x_complete_t` — 执行单元结果（79 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `vld` | 1 | |
| `robid` | 8 | |
| `paddr` | 6 | 目的物理号 |
| `data` | 64 | |

合计（逐成员相加）= 1+8+6+64 = **79 bit**（原写 78 系漏算）

#### `ls_complete_t` — 访存完成（21 bit）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `vld` | 1 | |
| `robid` | 8 | |
| `fault` | 2 | |
| `code` | 4 | |
| `lqid` | 6 | 48 项 LQ 需 6 bit（`spec/00` §4.6 `LQ_ENTRIES=48`） |

合计（逐成员相加）= 1+8+2+4+6 = **21 bit**（原值正确：**改工时不得把对值改错**）

（原稿 `ls_complete_t` 里写 5 bit 是错的（草稿自审发现，已修正并登记 `doc/00` ISS-011）；
§2 的 LQ 索引类型现名为 `lqidx_t`。）

### 3.21 `rt_t` — 退休 trace（`P17` 输出，验证平台唯一真值接口）

| 成员 | 位宽 | 语义 |
|---|---|---|
| `valid` | 1 | |
| `pc` | 40 | |
| `instr` | 32 | 原始指令字 |
| `is_c` | 1 | |
| `rd_idx` | 5 | |
| `rd_wb_en` | 1 | GPR 写回（trace 的 `gpr` 字段来源） |
| `rd_data` | 64 | |
| `priv` | 2 | |
| `csr_addr` | 12 | |
| `csr_old` | 64 | |
| `csr_new` | 64 | **写后的新值**。Trace 比对必须用新值（与 Spike commit log 同口径）；只给 `csr_old` 无法直接比 CSR 行为，只能靠后读回间接推——`doc/00` ISS-013 补上 |
| `csr_wr_en` | 1 | |
| `exc_v` | 1 | 本条退休时进入 trap |
| `exc_cause` | 4 | |
| `is_intr` | 1 | |
| `mispred` | 1 | 仅调试用，**不参与比对** |
| `is_br` | 1 | |
| `mem_v` | 1 | |
| `mem_addr` | 40 | |
| `mem_wdata` | 64 | |
| `mem_rdata` | 64 | |
| `mem_size` | 2 | |
| `mem_wr` | 1 | |
| `seq` | 12 | 全局 μop 序号（Q4：IR 比对名单原引用了不存在的 `seq`，现补上；调试排序需要） |
| `cycle` | 64 | 仅性能统计/调试，**不参与比对** |

合计（逐成员相加）= 1+40+32+1+5+1+64+2+12+64+64+1+1+4+1+1+1+1+40+64+64+2+1+12+64 = **543 bit**
（Q4：原写 554 系错算；补 `seq[11:0]` 后为 543，`§6` 端口表同步——原写 490 同样作废）。字段与标准 trace CSV
`pc,instr,gpr,csr,binary,mode,instr_str,operand`（《riscv-dv 精读》appendix 口径）的
映射与归一化规则在 `iss/README.md` §3 定义；**已确认不参与比对的成员**：
`cycle`、`mispred`、`seq`，以及默认关闭的 `instr_str`/`operand`（工具自定义文本）。

**rt_t 数据来源（N9 定案，逐字段可溯源——否则 Q3 型断链在提交级复发）**：
① `rd_data`/`mem_rdata` = **提交拍读 PRF**[`rd_paddr`]（`PRF_RD_PORTS` 由 14 增至 **18**：原 14 + 提交读 4，`spec/00` §4.3 已同步；提交与写回同拍时由 `wb_t` 按 `paddr` 比较旁路）；
② `mem_addr`/`mem_wdata` = 提交拍读 SQ（store 的地址与数据 SQ 本就持有）与 LQ（load 地址）；`mem_rdata` 与 ① 同值（load 结果即写 PRF 的数据）；
③ `csr_old`/`csr_new` = `csrq` 队头 `old_val`（E 级读出，§3.19）与 `vr1_csr` 提交拍合成 `new = op(old, src_val)`；
④ `pc`/`instr`/`is_c`/`priv`/`exc_*` 取自 `rob_entry_t`；`rd_idx` = `rd_arch`。
ROB 不存结果（`ROB_STORES_RESULT=0`）不受影响——数据由旁路与既有队列读出，不新增 ROB 位量。

---

## 4. 反压与停顿

| # | 反压源 | 被反压对象 | 机制 | 出口条件 | 断言 |
|---|---|---|---|---|---|
| BP1 | `rob_near_full`（占用 ≥ `ROB_NEAR_FULL`，即 `ROB_ENTRIES - free >= ROB_NEAR_FULL`；Q31 统一引用绝对水位，BLK-09：原式方向写反——`ROB_ENTRIES - free < ROB_NEAR_FULL` 等于“空闲不足 120 才触发”，几乎全程触发） | `S` 级停止分发 | 组合门控，不冲刷 | ROB 有 ≥ `DECODE_WIDTH` 空闲 | 不变式 **I1：`ROB 可提交条目数 > 0`（至少一个槽能被撤销）**，直接决定不死锁 |
| BP2 | `free_list_empty` | **`R`（分配点）与 `S` 同时停**（门控执行点定死，CLR-05：①`R` 级 = free-list 申请口——无空表则 `rd_paddr` 不分配、μop 不入流，信号 `r_alloc_grant`；②`S` 级 = `dispatch_grant_needs_rd`，即 `S` 级对 `dst_kind≠00` μop 的分发授权——原"无定义"） | 同上 | 提交回收或回滚归还 | **I2：free-list 空不阻塞提交**。不死锁论证（Q18 修正版，B4）：①PRF 条目**唯一申请点是 `R` 级**（`rd_paddr` 分配），故门控范围必须含 `R`；②在途指令的完成路径（发射/执行/写回）**不申请 free-list 条目**；③提交依赖链 = ROB 头 `finish` + L1D 完成 + CSR 读，**三者均不依赖 free-list**；④回收来源有三个——提交回收、逐条回滚归还（`new_alloc=1` 条目）、checkpoint 恢复回池（`FL_ck` 重置）——故 `free_list_empty` 时系统仍有推进路径 ⇒ 无环等待。完整不变式推导归 `spec/04` |
| BP3 | `lq_full` / `sq_full` | 仅**访存类**（`rob_alloc_t.type` bit5 `is_mem`=1，即 LD/ST/AMO）的 `S` | 按类门控 | 条目释放 | FENCE 不占 LQ/SQ 条目、不受本反压（N-10：`cls` 编码无独立 AMO 值，按 `cls` 门控会把 FENCE 误拦；`is_mem` 才是访存判据） |
| BP4 | 某 `IQ_*` 满 | 该类 `S` 停 | 按组门控 | 发射释放 | 允许组间不均衡 |
| BP5 | `ibuf_empty` | `D` 停 | — | 取指填回 | `D` 不构造伪指令占位 |
| BP6 | `ftq_full` | `BP3` 停入队 | 预测侧停，**不冲预测器** | 取指消费 | `BP1` 触发时 FTQ 不得清空 |

**原则**：一律**反压而非全局停**，避免整条流水线连锁停顿【超】p.397-401（P6 三段解耦队列满则
反压前级）。

---

## 5. 冲刷与恢复点

### 5.1 触发源（4 类）

| 触发源 | 检测级 | 优先级 | 备注 |
|---|---|---|---|
| `NMI` | — | — | **一期 `NMI_EN=0`，本行不可达**（Q20：不实现 `Smrnmi` 则进得去出不来；NMI 整体移入非目标） |
| 内部异常（含译码期非法指令、访存期 fault） | `S`（译码期）/ `E`（执行期）/ `WB` | 高 | 同拍多异常按 `spec/02` 固定优先序，**不允许"或"起来当一个** |
| 外部中断 | 提交边界 | 中 | **只在提交边界插入**（ROB 头之前的指令不得被抢占；Q27：原”`S` 级 ROB 头附近””早于此为架构允许”不可判定）。**注入接口（N11 定案）**：`vr1_csr` 输出 `ipend`（`ipend_t` 结构定义归 `spec/10`，本篇只定消费点）；`ipend&mie≠0` 且 ROB 头无异常时，当拍对 **ROB 头条目**合成 trap——置 `exc_v=is_intr=1`、写 `exc_code`、`epc=头 pc`（§3.7 `is_intr` 行），该条按 trap 提交、不正常退休，中断因此不需要单独的”入 ROB 接口” |
| 分支误预测 | `BRU`(`E`) | 最低（仅误预测自身排序） | 投机路径处理量应被统计上限约束（`spec/13` 性能口径） |

### 5.2 恢复点表（每级各拍必须做的动作，逐字冻结）

| 级号 | 冲刷当拍动作 | 不得做 | 正确性要求 |
|---|---|---|---|
| `BP1..BP3` | 清 GHR 投机历史、RAS 用 SARAS-lite 恢复【超】p.141-143、TAGE 不训练错误路径、`IUM_EN` 取消待更新项、重定向到 `target_real` | 不得用误预测分支训练主表 | `mispred` 由 `br_resolve_t` 携带，非事后推导 |
| `F0..F2` | 清 `mispred` 所属 `ftq_id` 之后的 FTQ 项 + 在途 L1I/PTW 请求（L1I/L1D 回填按 `req_id` 丢弃；PTW→TLB 写入前按 A5 与 `ftq_id` 冲刷集比对——N4/N6 闭合） | **已授予但属错误路径的 PTW fill 不得进 TLB** | 否则污染长期状态 |
| `D` | 清流水线寄存器、`pre_exc` 丢弃 | | |
| `R` | ①`needs_ckpt=1`：从 checkpoint 恢复 RAT（只此一路），并重置 `SP := SP_ck`（N2）与 free-list 分配指针 `head := FL_ck`（N-01：B 后分配自动回池，防物理号泄漏）；②`needs_ckpt=0`：按 `ROLLBACK_RATE=8` 条/拍从**映射历史栈**逐条回滚（**不读 ROB 条目**、不恢复 PRF 数据，条目 `new_alloc=1` 的 `new_paddr` 归还 free-list）。**`R` 级在途组不入栈**：冲刷杀 `P7` 在途组时，由本级的在途映射寄存器（每 lane `{arch, old_paddr}`）当拍直接恢复（§5.3；BLK-05/N3 定案） | 不得同时用 checkpoint 与回滚恢复同一分支 | 两者混用会把正确映射改错 |
| `S` | 清 ROB 尾指针到错误分支 ROB ID【超】p.383、清 IQ 中投机条目（按条目所存 `ftq_id` 与冲刷 `ftq_id` 比对，N5）、释放 LQ/SQ 中投机项；**压栈（每 lane 一条融合条目，本拍被冲刷作废的 lane 不得压栈，§5.3）**；**`rollback_busy` 期间不得分配 ROB/IQ/LQ/SQ** | **必须撤销 store 在 L1D 的投机写**（若二期允许投机 store 填行） | 一期禁止投机 store 写 cache，规则简单：store 只在 ROB 头提交后写 |
| `E1..E5` | 取消已发未回的 L1D 访问（按 `req_id`）；**DIV 不可中途取消**——冲刷时其 ROB 条目随组作废，`busy` 由 DIV FSM 末拍自然释放（Q33） | 不得假设 DIV 可被半途 kill | DIV 不流水、独占，协议细节归 `spec/06` |
| `WB` | 取消写回与唤醒脉冲 | **不得撤销已写 PRF 的数据**（PRF 条目未提交即不可见，撤销靠 RAT 不靠清数据） | 撤销 RAT 映射即可，硬件最简且正确 |
| `CT`/`RT` | 状态不被冲刷回退（`RT` 已发出的 trace 不回退）；**CT 在回滚完成拍必须执行下述③**（N-09：原"不参与冲刷"与③相抵，按字面实现会漏释槽）。**CT 每拍必做（BLK-06/N1 定案，动作实体入表）**：①**提交弹栈**——每提交一条写过 RAT 的 μop（`dst_kind≠00`）从栈底弹一条（§5.3/A14）；②提交 `needs_ckpt=1` 分支时释放其 `ckpt_id` 槽；③回滚完成拍，释放 `ckpt_holder_vec[i]` 全零的槽（被冲刷分支的槽随 ROB 条目作废而露出，A6 向量即释放掩码证据） | | 保序提交的根 |

**冲刷总延迟（Q16 定死两档）**：
- **命中 checkpoint**：`BRU` 解析拍 → 全级清空 → 重定向取指拍 = **5 拍**（`E`→`WB`→`CT` 反查 1、
  `R` 恢复 1、`F0` 重发 1、`F1` L1I 读 1、`D` 出 1）。**N2 定案后本档无弹栈代价**——栈指针重置 `SP:=SP_ck` 为 1 拍组合动作，不延长 `rollback_busy`。
- **无 checkpoint（逐条回滚）**：**5 + ceil(待撤销映射数 / `ROLLBACK_RATE`)** 拍；`ROLLBACK_RATE=8`。**待撤销数上限取参数 `ROLLBACK_MAX`（待 `spec/04` 定）——不得写死 128**（B7）；新机制下上界推导收敛为 `ROB_ENTRIES`（栈只存已过 `R` 级的写 RAT μop，`R` 级在途组由本级寄存器恢复，原"+`R` 级在途组"不再需要）。原稿宣称"冲刷 5 拍完成"对无 checkpoint 分支不成立。
- 回滚全程 `rollback_busy=1`，**门控范围定死为“只挡新指令进入 `R`/`S`（`P6`/`P7` 入流使能）”**；**回滚执行体（栈读、RAT 写、free-list 归还、尾指针与队列清理）不受门控**，且回滚不申请任何分配资源 ⇒ 与 BP1~BP6（均为资源状态反压）**无反压互等，排除条件性死锁**（B9：原句未写门控范围，读作“`R` 级整级冻结”时与回滚推进互等）。否则新指令会写进半回滚状态的 RAT，映射被交错改错。
**若启用 μop cache（三期预留）**，误预测需额外清/失效对应行，恢复点表须重定义——
此预留改动在 `spec/03` §预留 中记录（**该篇待建**，C7），一期不做。

### 5.3 冲刷与反压的交互

**映射历史栈（Q17 定死方案；第 8 轮处置 N1/N2/N3 重构，BLK-05/06 随之定案）**：逐条回滚只读该栈，
**不依赖 ROB 条目**——否则“冲刷当拍就清 ROB 尾指针并释放投机项”会让回滚无数据可用。ROB 释放与回滚就此解耦，
同时解开与 `rob_near_full` 同拍重算的矛盾。

**栈条目（单一融合形态，N3 定案；N-01 补元）**：`{arch[4:0], old_paddr[5:0], new_paddr[5:0], new_alloc, br_mark, rob_id[7:0]}` = **27 bit**（`new_paddr`+`new_alloc` 供逐条回滚显式归还物理号；checkpoint 路径经 `FL_ck` 批量回池，两路径互补）。
**每个写过 RAT 的 μop 恰好压入一条**：普通 μop `br_mark=0`；分支 μop `br_mark=1`——**分支自身映射与回滚终止标记融合为一条**（原“映射条目 + 独立 br_mark”两形态下，“弹到标记即停”会残留分支自身映射未撤销，且 R/S 两级双写口的压栈顺序无解，N3）。

**压栈点唯一 = `S` 级（`P8`）**：`rob_id` 在此已分配；按 lane 序（0→3）压入，每拍 ≤4 条、单写口；
冲刷优先于压栈——本拍被冲刷作废的 lane 不得压栈。
**`R` 级在途组不入栈**：冲刷杀 `P7` 在途组时，由 `R` 级本级的**在途映射寄存器**（每 lane `{arch, old_paddr}`）当拍直接恢复——
两级压栈/双写口/同拍顺序问题就此消除（BLK-05“rob_id 时点无值”与 N3 的定案）。

**提交弹栈（N1 定案——原设计只有回滚一个弹者，直线代码下栈单调填满反压成永久停摆）**：
`CT` 每提交一条写过 RAT 的 μop（`dst_kind≠00`）即从**栈底**弹出其对应条目（只丢弃、不写 RAT）。
栈序 = 程序序 = 提交序，故栈底条目的 `rob_id` 必等于最老未提交的写 RAT μop；不匹配或空栈属实现缺陷，由 §7 **A14** 兜底置致命。
提交弹栈动**栈底指针**、回滚/清栈动**栈顶指针**，两者相向而动互不重叠，相遇即空栈。

**逐条回滚（flush at B，`needs_ckpt=0`）终止规则**：以 `ROLLBACK_RATE=8` 条/拍从栈顶弹出：每弹一条即将
`RAT[arch] := old_paddr`，且条目 `new_alloc=1` 时将 `new_paddr` 归还 free-list；**弹出 `br_mark=1 && rob_id == B` 的融合条目并完成其撤销后停止**（B 自身映射已随融合条目撤销）；弹到栈底仍无匹配 → 置致命错误并复位（防御路径）。

**checkpoint 恢复（flush at B，`needs_ckpt=1`）的栈与 free-list 处置（N2/N-01 定案）**：checkpoint = **三元快照** `{RAT 整表, 栈深 SP_ck, free-list 分配指针 FL_ck}`。恢复动作（1 拍）：①`RAT :=` 快照整表；②`SP := SP_ck[B.ckpt_id]`——B 及其之上的栈条目就地作废，由后续压栈自然覆盖（后续逐条回滚不会再弹出陈旧条目）；③`free_list.head := FL_ck[B.ckpt_id]`——**B 之后的一切分配自动回池**（分配序 = 程序序，`(FL_ck, 当前 head)` 区间的物理号只可能被 B 之后的 μop 取走），被作废栈条目因此**无需逐条归还**，堵住 checkpoint 路径的 PRF 号泄漏（N-01：原二元快照下这些号既不在 RAT 新映射也不在 free-list，单调泄漏至 `free_list_empty` 死锁）。提交回收推的是尾指针，与 head 重置天然衔接（free-list 环容量条件归 `spec/04`）。`SP_ck` 采样点 = `S` 级 lane 序处理到 B 时、B 压栈前一刻；同组比 B 老的 lane 条目在 `SP_ck` 之下、保留不动。

**快照时点（CLR-06 定案；N-01 扩三元）**：checkpoint 数据 = {RAT 整表快照, `SP_ck`, `FL_ck`}，物理采样点两个、语义分界一个（"B 生效前"）：
RAT 快照与 `FL_ck` 在 `R` 级按 **lane 序**处理的过程中、本分支 lane 生效前采样（RAT 写与 free-list 分配均按 lane 0→3 顺序生效为本设计定死的实现约束）；
`SP_ck` 在 `S` 级 B 压栈前采样（栈压栈亦按 lane 序）。三者语义一致：都取"同组更老 lane 已生效、本分支未生效"的分界态。

深度 = 参数 `HIST_DEPTH`（**待 `spec/04` 定**，`spec/00` §4.3 以“待定”占位，X4）；**栈满时 `S` 级反压**（压栈点在 `S`，与 BP2 同口径），不得静默丢弃条目。
**双写者仲裁（C8）**：free-list 的两个写者——提交回收与回滚归还——**作用集合不相交**（提交即不可撤销；回滚只针对未提交条目），同一物理号不存在“既被回滚又被提交回收”的路径，故无需同拍仲裁；若出现同拍同号两次归还，属实现缺陷，由 §7 A13 断言兜底。**栈深度推导归 `spec/04`**（ISS-003 未决即污染冻结面，一并记入）。

冲刷发生时 `BP1..BP6` 的 pending 状态**不得**被冲刷改写（反压是资源状态，不是投机状态）；
`BP1` 的 `rob_near_full` 在 ROB 尾指针回退后由组合逻辑重算，**不得打一拍延迟**——
否则刚回退 20 个条目后仍报“满”，白停一拍。此条列为断言（§7 A4；BLK-14：原写“§8 A4”系引用错位）。

---

## 6. 顶层端口表（`vr1_core`）

| 端口组 | 方向 | 位宽 | 说明 |
|---|---|---|---|
| `clk_i` | I | 1 | 单时钟域 |
| `rst_ni` | I | 1 | 低有效异步复位、内部同步释放 |
| `hart_id_i` | I | 4 | → `mhartid`（一期 1 hart，tie 0） |
| `irq_meip_i`/`irq_mtip_i`/`irq_msip_i` | I | 1×3 | CLINT/PLIC 直连（SoC 层例化，见 `spec/10`） |
| `irq_seip_i`/`irq_stip_i`/`irq_ssip_i` | I | 1×3 | S 侧 |
| `nmi_i` | I | 1 | **一期不实现**（`NMI_EN=0`，Q20/C5）：输入必须 tie 0，综合后无逻辑；保留端口仅为二期 `Smrnmi` 预留 |
| `ibex_dbg*` | — | — | **一期无调试端口**（`spec/00` §1.2 非目标） |
| `axi_aw*/ar*/w*/r*/b*` | O/I | — | AXI4-128 主端口，`spec/09`；行填充 `arsize=4`/`len=3`（4 拍×16B=64B 行），MMIO `len=0`（Q32：原 `awlen=8` 与 64B 行、与“仅 INCR + MMIO len=1”均不吻合） |
| `rt_valid_o` / `rt_o` | O | 1 / 543 | 退休 trace（§3.21），tb monitor 消费（Q4：原写 490 作废） |
| `perf_*_o` | O | 64×8 = **512** | `PERF_W=64 × PERF_EVT_NUM=8`（X3/C4 定死：两参数已入 `spec/00` §9——事件清单 cycle/instret/br_retire/br_mispred/l1d_miss/fwd_hit/freelist_stall/rollback_cycles；原"~40"与"待定"违反本篇冻结基线禁止 ≈）。口径见 `spec/00` §9、实现见 `spec/13` |
| `fencei_req_o`/`fencei_ack_i` | O/I | 1/1 | 维护握手（SoC 级，`spec/09`） |

---

## 7. 断言（`spec/01` 侧，SVA 写法遵循 `spec/11`）

| # | 断言（示意） | 依据 |
|---|---|---|
| A1 | `rob_full \|-> !rob_alloc_grant` | §4 BP1 |
| A2 | **安全属性**：`free_list_empty \|-> ##1 (!dispatch_grant_needs_rd && !r_alloc_grant)`（空表时 `R` 级不得分配、`S` 级不得分发任何需要新目的寄存器的 μop——CLR-05：原式只盖 `S` 级，`R` 级分配点漏门控且信号无定义）；**长度不设断言上限**——最坏等待拍数改为统计项 `perf_freelist_stall_cycles`（B3：原 `##[1:128]` 仍会在 DIV 35 拍 / L2 miss 数百拍场景假红） | §4 BP2 |
| A3 | 多源同拍冲刷**合法**；仲裁输出必须等于 §5.1 优先级表的单热预期（Q28：原“同源禁止”会把合法场景反复打红，或迫使实现人为延迟制造新互锁） | §5.1 |
| A4 | `rob_tail_rollback \|-> ##0 !rob_near_full_d`（回退后同拍反压重算） | §5.3 |
| A5 | `ptw_fill_valid && (ptw_ftq_id ∈ 冲刷集) \|-> !tlb_write_en`（**N4 定案**：键 = 经 `mmu_transl_req_t.ftq_id` 随行至 fill 的 FTQ 号，§3.14——原式引用任何 struct 都不存在的 `ptw_spec_id`，改引后也曾因 mmu 结构无 `ftq_id` 而永不触发；现键已落在结构里，断言可触发＝漏测闭合） | §5.2 `F0..F2` |
| A6 | **持有唯一性（按槽判）**：对 `i = 0..3` 各断言 `$onehot0(ckpt_holder_vec[i])`，其中 `ckpt_holder_vec[i][k] = rob_entry[k].v && rob_entry[k].needs_ckpt && (rob_entry[k].ckpt_id == i)`（**BLK-07**：原全局 `$onehot0(ckpt_held_vec)` 与 4 槽可并行持有相矛盾；向量产生点即 ROB 扫描，属监视器内部信号）；释放判据 = `needs_ckpt && (ROB 头提交 \| 被冲刷回滚完成)`（BLK-06） | §5.2 `R` |
| A7 | `wb_valid \|-> rob_entry[rob_id].v`（写回必须命中有效条目；C9：原写法与其余断言风格不一致） | §3.10 |
| A8 | `lq_full && !sq_full && cls==LD \|-> !dispatch_grant[LD]` | §3.13 |
| A9a | IQ 唤醒 CAM：`$countones(iq_cam_hit_vec) <= WAKE_BCAST_PORTS`（挂 IQ 唤醒，不挂 LSU；Q38：原 A9 用唤醒 CAM 去约束 LSU 转发源数，挂错模块＝永不触发） | §3.9 |
| A9b | LSU 转发 CAM：`$countones(fwd_hit_vec) <= FWD_MAX_SOURCES` | `spec/08` |
| A10 | `rt_valid && !commit_stage_grant` → error（trace 只能由 CT 产生） | §3.21 |
| A11 | LQ 域三条（Q13）：①`lq_id < LQ_ENTRIES`（越权值不得出现在任何随流信号上）②`lq_occ <= LQ_ENTRIES` ③`(lq_occ==0) == lq_empty`（空满不歧义） | §2 `lqidx_t`/`lqocc_t` |
| A12 | CSR 链（B1）：`csr_vld \|-> (csrq_head.rob_id == rob_head_id) && rob_head_type[6]`；`type[6]==0 \|-> !csr_vld` | §3.17/§3.19 |
| A13 | free-list 归还唯一性（C8/BLK-04）：`(commit_fl_ret_vec & rollback_fl_ret_vec) == 0`——两路归还使能均为**按物理号展开的位图**，交集非空即同号双归还；原式 `$onehot0(a \| b)` 无”号比较”能力，位图读法下同号双归还经 `\|` 合并后仍为单 bit（永不触发），属假绿 | §5.3 |
| A14 | **提交弹栈匹配（N1/§5.3）**：CT 提交 `dst_kind≠00` 的 μop 时，栈非空且栈底条目 `rob_id` 等于该 μop `rob_id`；不匹配或空栈 → 致命错误（防提交弹栈错位静默污染栈序） | §5.3 |

**trace 比对口径**：`cycle`、`mispred`、`seq` 三个成员**不参与比对**，已在
`iss/README.md` §3 的映射表中逐行列出（`machine.py` 侧已实现）。
注：`rt_t` 必须同时带 `csr_old` 与 `csr_new`，否则 CSR 写入行为无法与 Spike 直接对查（ISS-013）。

**异常条目三条规定（Q19，双线验证的真漏洞）**：
1. `exc_v=1` 的条目**仍逐条比 `pc`/`binary`/`mode`**；清零**按 lane 粒度**（B10 定死）：**仅异常条目自身**的 `gpr`/`csr`/`mem` 清零且两侧同规则；**同一提交包内其之前 lane 的正确写照常逐条比对**（原稿“条目级”会被读成“整包清零”，把 trap 前的正确写一并掩盖）。异常指令自身的错误写由 ② 内存镜像点 + 保留的 `csr_old` 字段覆盖。映射规则同步写进
   `iss/README.md` §3（**该文件现与本条不一致，以本篇为准**，C3）。
2. **新增内存镜像比对点**：程序结束 + trap 边界 + signature 握手扩 `WRITE_MEM`——只比 VA 的 trace 对
   “翻译错、写进错误 PA”是两侧一致地看不见。
3. `doc/02` 必须含“**转发后又被冲刷重做**”专项功能覆盖项。

---

## 8. 本篇出口自检（v0.2 重建版）

> **v0.1 更正记录（不得静默删除）**：下表 v0.1 的全部 ✅ 均不可信。
> R7 独立评审证明：作得最多的一行「合计值已逐项相加核对」**当时根本没做过**
> （13 个 struct 里 12 个合计与成员相加不符），所以 v0.1 的自检表整体作废。
> 逐条问题与处置见 [`01-评审记录.md`](01-评审记录.md)。

### 8.1 机器可核项（本轮实跑，输出已留档）

| 自检项 | 复核手段（可复现命令） | 本轮结果 |
|---|---|---|
| 28 个 struct 合计 = 成员逐项相加，且**标题位宽数与实算一致** | `python script/width_check.py`（v0.3 起含 N16①②③：标题核对、NO-CLAIM 不再计为可核对、转录基准行单列） | **可机器核对 28 / 不符 0 / 未能核实 0 / 基准行 2**（留档 `doc/05` R-005） |
| 成员位宽只引用 `spec/00` §4 参数或行内给定 | 同上（参数名代入求值；无值者记 UNRESOLVED，不许猜） | 通过（0 处 UNRESOLVED；`HIST_DEPTH`/`ROLLBACK_MAX` 不入 struct 成员表，走 §8.2 人判清单） |
| 表格与台账机械核销 | `python script/gate.py check` | **18 PASS / 1 WARN（低频字人工判）/ 0 FAIL**（留档 `doc/05` R-005） |

### 8.2 人判项（机器看不到，须评审轮核查）

| 自检项 | 复核手段 | 状态 |
|---|---|---|
| 每个枚举成员值域指向唯一定义处 | 逐成员值域行 | Q23/Q24/Q30 已补；其余待 `spec/02/08/10` 定稿时回查 |
| 反压出口条件为可判定状态 | 死锁自由论证 + 断言 | Q18 论证已写入 §4 BP2；完整 I1/I2 推导归 `spec/04`（ISS-003） |
| 恢复点表逐拍定义 | 逐拍表 + 手工推演例 | Q16/Q17 已定两档延迟与映射历史栈；**推演例待 `spec/04`** |
| 接口链无断点 | 逐信号溯源 | Q3（CSR 写数据）/Q14（预测反馈 4 域）已闭合；**N4/N5/N6（`ftq_id`/`req_id` 键）与 N9/N10（`rt_t` 数据来源、`old_val` 载体）本轮闭合**（v0.3） |
| 待同步清单 | 逐条跟踪 | `spec/10`（Q27/Q29/Q30 + `csrq` 命中/`wdata_sel` 编码 + `is_sret` 生产点 + `ipend_t` 定义，N11）、`spec/06`（Q33）、`spec/04`（Q16/Q17/Q18 + `HIST_DEPTH`/`ROLLBACK_MAX` 定值并回填 `spec/00` §4.3 + S1/SUS-01 读点口径 + 栈深度推导）、`iss/README.md` §3（Q19① 映射表，C3：**以本篇 §7 为准**）与 §4（签名表扩 `WRITE_MEM`，C2）与异常类”`--final-only`”行（X7）——**iss/README 三处合并登记 `doc/00` ISS-037，同步动作归 R2 角色**、`doc/02`（Q19③/Q29 + “转发后又被冲刷重做”专项）、tb 超时（Q37）、`perf_freelist_stall_cycles` 登记（CLR-03）。**本轮已完成、移出本清单**：`spec/00` §4.8 补 μop/`csrq` 行（X2/BLK-17/CLR-04）、§7.3 `fdirty` 口径（BLK-10/X1）、§9 `PERF_W`/`PERF_EVT_NUM`（X3/C4）、§4.3 `PRF_RD_PORTS=18`（N9）。**引用未建篇目（`spec/03` 等）时必须在首次出现处标注”该篇待建”**（C7/CLR-02） |

### 新增自检纪律（由 ISS-018 促生，适用于 `doc/spec/*` 全部篇目）

1. **禁止无手段的 ✅**：打 ✅ 必须同行列出可复现复核手段（脚本名 + 输出片断 / 实验 / 规范条款）。
2. **可机器判定的事一律交给机器**：位宽相加、参数名一致性、枚举值域引用完整，均写成脚本
   （`script/`）并在每篇返工后跑一次；输出留档。人的眼睛不该用来核对加法。
3. **“作者自证”不构成门禁**：出口自检只能作为提交给评审的清单，不能作为放行依据
   （对应《AI角色与职责》§1.2：同模型多角色共享盲点）。
