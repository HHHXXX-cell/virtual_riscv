# G1-I 最小冻结清单与分段签路径（doc/decisions/G1-I-最小冻结清单.md）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v0.1 | 2026-09-25 | RD 自决产出（**待人**：G1-I 冻签由 R0 行使） | 首版：§1 范围声明（含/不含逐条）；§2 最小冻结面清单（①接口 struct 23 项 ②CSR ③异常 ④trace 口径 ⑤参数，另附首版恒 0 成员表）；§3 延后到 G1-F 的清单；§4 可签判据 14 条（逐条标现有判据覆盖情况）；§5 G1-F 推进方式；§6 分段签路径与四段材料；§7 出口自检 |

- **编号**：本清单**尚未**取台账号——按红线「编号一律 `python script/flow.py record` 自增、禁手写」，取号动作归落文批（本批只新建本文件，不 `record`）。
- **建档缘由**：`spec/00` §6 的冻结判据要求「每个 `*_t` 都有成员级位域定义与合法值域」，而该注（X5）点名的 13 个待闭合型中 12 个**零定义**（全库检索：仅有引用、无成员级位域表；唯一例外 `bp_upd_t` 已由 `spec/03` §2.9 定义，57 bit）⇒ **14 篇同时自洽**在当下不可满足。一期定位是「能力与方法证明」（`spec/00` §1.0），故按 R0 批准的建议执行：**先把冻结范围砍到「跑通首条 RTL-vs-ISS 闭环」所需的那一小撮**，其余按 §5/§6 逐版增量。
- **角色**：RD（决策 AI）。依据 `doc/项目开发流程.md` §12.2「设计/规格类取舍由决策 AI 自决并留 ADR」。
- **写边界声明**：本批**只写** `doc/decisions/G1-I-最小冻结清单.md` 一个文件。**未改** `doc/spec/**`、`doc/verify/**`、`script/**`、`state/**`、`rtl/**`、`tb/**`，**未改**既有 `doc/decisions/ADR-*`，**未** `record`。文中凡涉他人产物（`spec/01` §3.21 附录、`spec/10` `mtval` 口径、`doc/spec/14` 签署节、`guard-write` 白名单）一律只列为**下游义务**（§6.3），不代写。
- **编号约定（本文件局部）**：`GS-n`＝本清单的取舍条目；`GI-n`＝G1-I 可签判据；`GR-n`＝风险与残余；`GD-n`＝下游义务。**均为本文件内编号、不入台账编号空间**。

---

## 1. 范围声明（唯一依据，不得自行扩大）

### 1.0 口径本体（逐字沿用 R0 批准的口径）

- **里程碑 M1**（`state/flow.json`）＝ `vlog` 0 error ＋ 定向下 **RTL-vs-ISS 逐指令 trace 0 mismatch**（该里程碑两条 exit＝`rtl-compile`／`rtl-vs-iss`，均**待 G1 后注册**）。
- **镜像**＝`sim/image/m_smoke.hex`：68 字、base `0x1000`、md5 `4b289622…`（`sim/image/MANIFEST.json` 在册）。程序源＝`iss/tests/test_smoke.py:build_words()`，生成件由 `sw/tests/gen_smoke_image.py` 复用同一 `build_words()`（不另写一份）。
- **程序规模**＝30 条退休（26 条主序含 1 条异常退休 ＋ 4 条 handler）；golden＝`sim/golden/iss_smoke.csv`（31 行＝1 表头＋30 行，md5 `3e9bb799…`）。
- **比对**＝`python iss/tools/trace_compare.py sim/golden/iss_smoke.csv <rtl_side.csv>`，列 `pc,binary,gpr,csr`（`iss/tools/trace_compare.py` `DEFAULT_COLS`）。

### 1.1 含（依据＝smoke 程序**实测用到**的指令与 CSR，逐条）

| # | 含项 | 实测依据（可核） |
|---|---|---|
| 1 | 指令 **14 条**：`LUI`／`ADDI`／`ADDIW`／`SW`／`LW`／`MUL`／`DIV`／`REM`／`SLLI`／`BEQ`／`JAL`／`CSRRW`／`CSRRS`／`MRET` | `test_smoke.py` 的 import 集合与 `build_words()` 逐条；镜像另有 2 条被跳过、1 条不执行的 `ADDI`（同编码，不新增指令面） |
| 2 | 特权级：**仅 M** | `priv` 恒 3；trace `mode` 列恒 `PRV_M` |
| 3 | CSR **六个**：`mtvec` `mepc` `mscratch` `mcause` `mtval` `mstatus` | `CSRRW`(mtvec/mscratch/mepc)、`CSRRS`(mscratch/mepc)、trap 进场写(mepc/mcause/mtval/mstatus)、`MRET` 读/写(mstatus/mepc)；`misa`/`mhartid` **未被读** |
| 4 | 异常**一条**：非对齐 store → trap → handler 改 `mepc`(+4) → `MRET` | `SW x17,1(x7)`（VA `0x4000_0001`）⇒ cause 6；断言 `mcause==6`、`mtval==0x40000001`、`mepc==0x104C`、MRET 后 `MPP` 归底 0 |
| 5 | 完整数据通路：取指（含 taken 分支与 trap/MRET 重定向）→ 译码 → 重命名 → 分发 → 发射 → 执行（ALU/SHIFT/MUL/DIV/BRU/LSU）→ 写回 → 提交 → trace | 30 条退休必须按程序序出现；被跳过的 3 个 pc（`0x1034`/`0x1040`/`0x1070`）**不得**出现在 trace（断言在册） |
| 6 | 冲刷与恢复（误预测 + trap 两路） | taken `BEQ`／`JAL` 的解析；trap 的 ROB 头提交、`mepc` 返回重执行 |
| 7 | 内存面：SW／LW／tohost 写；地址窗 `0x1000` 代码、`0x1100` handler、`0x4000_0000` 数据 | `mem_req_t` 的 LD/ST/IF 三类 `kind`；TB 内存桩必须覆盖全部被访地址 |
| 8 | 停机口径：向 `0x4000_0010` 写 1 | ISS `tohost_addr=0x4000_0010`；riscv-tests PASS 值＝1 |

### 1.2 不含（明确不在 G1-I；逐条给"不在"的理由）

| # | 不含项 | 理由（与 §1.1 的反推关系） |
|---|---|---|
| 1 | MMU／Sv39／PTW／TLB／PMP／PMA **判决面** | 无翻译、无保护：镜像地址全规范、只走 M 态、无 Sv39 与权限判据 |
| 2 | cache 层次（L1I/L1D/L2/MSHR/替换/回写/AXI） | 首版以内存桩替换；取指与访存只保留**端口形态**（见 §2.1 `mem_req_t`/两个 `*cache_rsp_t`） |
| 3 | U/C 特权（含委托、`sstatus`/`stvec` 等 S 侧 CSR） | 镜像只切 M 态；无 `ECALL`/`SRET`/`SFENCE.VMA` |
| 4 | 中断（`mip`/`mie`/CLINT/PLIC/三条件仲裁/注入） | 镜像无中断源；`is_intr` 恒 0 |
| 5 | FP／D（含 `mstatus.FS`、PRF 预留位） | 非目标；镜像无 FP 指令 |
| 6 | 压缩指令（C 展开表、`is_c=1`、`xw_carry` 跨窗拼接） | 镜像全 32 bit；槽 15 起始不可达 ⇒ 拼接永不触发 |
| 7 | 分支预测器**更新路径**（`bp_upd_t`、IUM、TAGE/SC/ITTAGE 训练、校正队列出队） | 首版只需"预测→FTQ→取指"可用；`bp_upd_id`/`ftq_id` 随流携带但不回写 |
| 8 | 原子（LR/SC/AMO）、`fence`/`fence.i`、内存模型（RVWMO）判据 | 镜像不含；`amo_op`/`aq`/`rl`/`fm` 恒 0 |
| 9 | 性能口径（`spec/13` 周期模型、PERF 事件、预测准确率、IPC） | M1 判据只判 trace 0 mismatch，不判拍数/性能 |
| 10 | 复位序列完整面（仅保留"复位后取 `RESET_PC`=0x1000"一条） | 镜像 base 与 `RESET_PC` 一致即够 |

### 1.3 边界声明

- 本清单冻的是**接口定义、值域与口径**，不冻内部实现（`spec/00` §6 首句口径）。首版实现可在冻结接口之内做**结构性简化**（见 §6.2 ① 的取舍条目），但**不得新增、改名或自造任何接口类型**。
- 「含」集内的接口**整型冻结**（成员位宽/语义按已生成的 `rtl/vr1/include/vr1_types.svh`）；其中首版不消费的成员由 §2.6 逐条列明取值口径——**"冻结"不等于"首版全用"**。
- 「不含」集内的机制，首版**不得例化**其对应接口（§4 `GI-2` 的负判据）。

---

## 2. 最小冻结面清单

**判定规则（反推纪律，防凭印象扩大）**：

- **R-a 来源限定**：条目只能出自 `spec/00` §4（参数）、`spec/01` §3（28 个 struct）、`spec/10` §2.1/§4.1（异常码表/CSR 表）、`iss/README.md` §3（trace 映射）、`doc/process/00` ISS-013。
- **R-b 反推原则**：每条必须能指到 smoke 的**具体指令 / CSR / 判据步骤**（"反推依据"列）。指不到的，一律进 §3。
- **R-c 不扩大**：不做"以后可能要用"的预留（那属 G1-F）；`spec/01` §3 的 28 型中不在首版实例化面上的 5 型进 §3。

### 2.1 ① 接口 struct（23 项；全部为 `spec/01` §3 已定义型）

| 类别 | 条目 | 归属篇/节 | 冻结所需材料 | 当前是否已具备 | 反推依据（smoke/M1） |
|---|---|---|---|---|---|
| ①接口 struct | `ftq_req_t`（143 bit） | `spec/01` §3.1 | 成员级位域表＋合法值域（`spec/00` §6 冻结判据） | 已具备（已入 `vr1_types.svh`；`types-*` 判据全 PASS） | 前端产出取指块（`BEQ`/`JAL` 的方向与目标） |
| ①接口 struct | `ftq_entry_t`（145 bit） | `spec/01` §3.2 | 同上 | 已具备 | FTQ→IF：取指输入的队列形态 |
| ①接口 struct | `fetch_raw_t`（92 bit/槽） | `spec/01` §3.3 | 同上 | 已具备 | IBUF→D 译码入口（镜像全 32 bit，`is_c` 恒 0） |
| ①接口 struct | `uop_t`（239 bit） | `spec/01` §3.4 | 同上 | 已具备 | D→R：14 条指令的译码载荷 |
| ①接口 struct | `rmap_uop_t`（327 bit） | `spec/01` §3.5 | 同上 | 已具备 | R→S：重命名结果（`rd_old_paddr`/`rd_is_new` 供回滚） |
| ①接口 struct | `rob_alloc_t`（148 bit） | `spec/01` §3.6 | 同上 | 已具备 | S→ROB：30 条退休条目分配 |
| ①接口 struct | `rob_entry_t`（143 bit×128） | `spec/01` §3.7 | 同上 | 已具备 | ROB 存储体；trace 的 `pc`/`instr`/`priv`/`exc_*` 来源 |
| ①接口 struct | `iq_wr_t`（247 bit） | `spec/01` §3.8 | 同上 | 已具备 | S→IQ 入队（含 `lq_id`/`sq_id` 载荷） |
| ①接口 struct | `iq_entry_t`（27 bit/条目） | `spec/01` §3.9 | 同上 | 已具备 | IQ 就绪位与年龄仲裁（后读口径） |
| ①接口 struct | `wb_t`（80 bit×6） | `spec/01` §3.10 | 同上 | 已具备 | 写回＋唤醒；`src_kind=1` 为 CSR 旧值通路 |
| ①接口 struct | `disp_x_t`（338 bit×6） | `spec/01` §3.11 | 同上 | 已具备 | IQ→EU 发射载荷（`rs1_val`/`rs2_val` 后读） |
| ①接口 struct | `br_resolve_t`（149 bit） | `spec/01` §3.12 | 同上 | 已具备 | BRU 解析 `BEQ`/`JAL` → 冲刷与重定向 |
| ①接口 struct | `mem_req_t`（143 bit） | `spec/01` §3.13 | 同上 | 已具备 | LSU/IF→内存：`SW`/`LW`/取指三类请求 |
| ①接口 struct | `icache_rsp_t`（322 bit） | `spec/01` §3.16 | 同上 | 已具备 | 取指回填（内存桩的返回形态，与请求端成套） |
| ①接口 struct | `dcache_rsp_t`（87 bit） | `spec/01` §3.16 | 同上 | 已具备 | `LW` 数据返回（`rd_paddr` 透传） |
| ①接口 struct | `commit_t`（355 bit） | `spec/01` §3.17 | 同上 | 已具备 | ROB→CSR/回收/SQ；提交边界（含 `exc_pkt`/`ret_pkt`/`csr_wr`） |
| ①接口 struct | `excp_t`（177 bit） | `spec/01` §3.18 | 同上 | 已具备 | 非对齐 store 的 trap 现场（`cause`/`epc`/`tval`/`vec_off`） |
| ①接口 struct | `ret_ctrl_t`（49 bit） | `spec/01` §3.18 | 同上 | 已具备 | `MRET` 返回控制（镜像含 `MRET`） |
| ①接口 struct | `csr_wr_t`（81 bit） | `spec/01` §3.19 | 同上 | 已具备 | `CSRRW` 写通路（`mtvec`/`mscratch`/`mepc`） |
| ①接口 struct | `csrq_entry_t`（152 bit×8） | `spec/01` §3.19 | 同上 | 已具备 | CSR 写队列：队头命中、`old_val` 载体、`CSRRS` 读值 |
| ①接口 struct | `x_complete_t`（79 bit） | `spec/01` §3.20 | 同上 | 已具备 | EU→WB 结果（含 CSR 读回结果） |
| ①接口 struct | `ls_complete_t`（21 bit） | `spec/01` §3.20 | 同上 | 已具备 | LSU→LQ/ROB 完成与 fault 回报 |
| ①接口 struct | `rt_t`（543 bit） | `spec/01` §3.21 | 成员级位域表＋合法值域 | **部分（唯一"材料缺"的接口条目）**：成员表已具备且机判在册；但 §3.21 附录（RVFI 逐字段映射三清单，D-2／ISS-017 **处理中**）未填，本篇自述「**附录未填前，本节不得作为 G1 冻结依据**」⇒ 冻结材料不全（处置见 §4 `GI-10`／§6.2 ③ `GR-1`） | M1 判据本体（唯一真值接口） |

> 计数：23 项 ＝ `spec/01` §3 的 28 型 − 5 型（`mmu_transl_req_t`／`mmu_transl_rsp_t`／`miss_req_t`／`fill_t`／`mshr_wake_t`，见 §3）。28 − 23 = 5，与 §3 排除名单**恒等**（机可核：两份名单互补）。

### 2.2 ② CSR（首条闭环用到的六个；`misa`/`mhartid` 不在内）

| 类别 | 条目 | 归属篇/节 | 冻结所需材料 | 当前是否已具备 | 反推依据（smoke/M1） |
|---|---|---|---|---|---|
| ②CSR | `mtvec`（0x305） | `spec/10` §4.1 | 地址／复位值／位段（首版只需 `MODE=Direct`；`BASE` 4 B 对齐）／WARL／权限 | 已具备（表行在册） | `CSRRW x0,mtvec,x1`（handler 入口 `0x1100`） |
| ②CSR | `mscratch`（0x340） | `spec/10` §4.1 | 全 64 位 R/W | 已具备 | `CSRRW x0,mscratch,x19`（写 5）＋`CSRRS x21,mscratch,x0`（**rs1=x0 纯读不得写**） |
| ②CSR | `mepc`（0x341） | `spec/10` §4.1 | bit0 恒 0（`IALIGN` 口径见 §6.2 ③ `GR-3`）／trap 写与读回 | 已具备 | trap 进场写；handler `CSRRS x5,mepc,x0` → `+4` → `CSRRW x0,mepc,x5` |
| ②CSR | `mcause`（0x342） | `spec/10` §4.1＋§2.1 | 值域＝§2.1 唯一码表／写入口径 | 已具备 | trap 进场写 6；断言 `mcause==6` |
| ②CSR | `mtval`（0x343） | `spec/10` §4.1 | **取值口径缺**：非对齐 store ⇒ `mtval`＝出错 VA | **缺**（§4.1 行仅写"非法指令回填指令位"；非对齐 VA 口径目前只存在于 ISS 与规范侧，见 §4 `GI-6`） | trap 进场写 `0x4000_0001`；断言 `mtval==0x40000001` |
| ②CSR | `mstatus`（0x300） | `spec/10` §4.1＋§2 | `MIE`/`MPIE`/`MPP` 位段＋进场/返回动作（`MPP` 归底） | 已具备（§4.1 行＋§2 进场 6 动作／返回动作在文） | trap 进场（`MPIE←MIE`、`MIE←0`、`MPP←前级`）；`MRET`（`MPP←0`，断言"归底 U(0)"） |
| ②CSR | `misa`／`mhartid` | — | — | **不在本清单** | 镜像零读取（未读即不冻）；`misa.C` 只经 `IALIGN` 口径间接影响 `mepc`/`mtvec` 对齐（§6.2 ③ `GR-3`） |

### 2.3 ③ 异常

| 类别 | 条目 | 归属篇/节 | 冻结所需材料 | 当前是否已具备 | 反推依据（smoke/M1） |
|---|---|---|---|---|---|
| ③异常 | 码 **6** Store/AMO address misaligned | `spec/10` §2.1 | 码值＋可达性＋判决点（`MISALIGNED_EN=0`：非对齐一律报 fault，不拆包） | 已具备（§2.1 行标"本实现可产生"；`spec/00` §2 口径） | **实测触发**：`SW x17,1(x7)`（VA `0x4000_0001`） |
| ③异常 | 码 **4** Load address misaligned | `spec/10` §2.1 | 同码 6 口径（同一判决点的对偶） | 已具备（§2.1 行） | 与码 6 共用同一判决点（`spec/00` §2：「非对齐 load/store 一律报对应 fault」）；镜像未触发 |
| ③异常 | 码 **1/5/7** I/Load/Store access fault | `spec/10` §2.1 | 码值（已具备）＋**判决面**（PMA/PMP） | 码值已具备；**判决面延后** ⇒ 首版不可达（§3） | 内存桩对越界/非法访问的兜底（无兜底则挂死而非报错）；镜像内不可达 |
| ③异常 | 码 **2** Illegal instruction | `spec/10` §2.1＋§4.2 | 码值（已具备）＋判决点（译码期 `pre_exc`；CSR 权限/不存在） | 码值已具备；判决点首版仅"译码期预检" | 越界取指读零填充（`0x00000000`）会产生潜在非法字（§6.2 ③ `GR-2`） |
| ③异常 | trap 进场/返回动作与写面抑制 | `spec/10` §2＋§4.3；`spec/02` §19 | 进场 6 动作；`MRET` 返回动作；异常提交的 CSR 写抑制 | 已具备（两篇在文，含 `csrq` 规则 5） | trap→`MRET` 一条路径的全部可观测面 |

### 2.4 ④ trace 口径

| 类别 | 条目 | 归属篇/节 | 冻结所需材料 | 当前是否已具备 | 反推依据（smoke/M1） |
|---|---|---|---|---|---|
| ④trace 口径 | `rt_t` → CSV 列映射（逐成员→列规则） | `spec/01` §3.21＋`iss/README.md` §3 | 唯一权威映射表（含空串规则） | 已具备（表在册、行级可核） | M1 判据本体 |
| ④trace 口径 | `csr` 列取**写后新值** | `spec/01` §3.21（`csr_new`）＋`doc/process/00` ISS-013 | 单列口径 | 已具备（`iss/vriss/trace.py:csr_field()`） | 3 条 CSR 写/读的可判性（只给旧值无法直接比对） |
| ④trace 口径 | 比对列集 `pc,binary,gpr,csr`；**不参与比对** `cycle`/`mispred`/`seq`/（默认关）`instr_str`/`operand` | `iss/tools/trace_compare.py`＋§3.21 | 列集与放宽纪律 | 已具备（`DEFAULT_COLS`／`NON_COMPARED`／`--final-only` 需登记） | M1 判据命令 |
| ④trace 口径 | `gpr` 列空串规则（`rd_idx==0` 或 `rd_wb_en==0` ⇒ 空串） | `iss/README.md` §3 | 规则 | 已具备 | `CSRRW x0,mtvec,x1`／`CSRRW x0,mscratch,x19`（`rd=x0` 不得写回） |
| ④trace 口径 | 停机口径（`tohost` `0x4000_0010` 写 1）＋超时（watchdog 2,000,000 拍／ModelSim 20 min） | `test_smoke.py`＋`AGENTS.md` §5 规则 9 | TB 侧同口径实现 | **部分**：ISS 侧已具备；TB 侧**无实现**（`tb/vr1_uvm/` 现为占位骨架，无 DUT、无 trace 写出器、无停机判据） | 30 条退休后停机；防"裸机假挂死" |
| ④trace 口径 | 流断裂处置（长度不等 ⇒ 先归因环境/激励，按批中止判据 `AB1`/`AB6`，不逐条硬比） | `AGENTS.md` §5 规则 10＋比对器行为 | 判据 | 已具备（代码在册） | 比对器行为一致性 |

### 2.5 ⑤ 参数（`spec/00` §4 中首条闭环用到的）

| 类别 | 条目 | 归属篇/节 | 冻结所需材料 | 当前是否已具备 | 反推依据（smoke/M1） |
|---|---|---|---|---|---|
| ⑤参数 | `XLEN=64`／`VA_STORE_W=40`／`PA_BITS=44` | `spec/00` §4.1 | 值＋出处 | 已具备（`vr1_params.svh`＋`params-*` 判据全 PASS） | `xdata_t`/`pc`/`va`/`imm` 位宽；`mem_req_t.pa` 44 bit |
| ⑤参数 | `RESET_PC=0x1000` | `spec/00` §4.1 | 值＋与 `sw/env/link.ld` 一致 | 已具备（镜像 base＝`0x1000`，`image-hex` 判据在册） | 镜像 base／复位向量 |
| ⑤参数 | `FETCH_BYTES=32` | `spec/00` §4.1 | 值 | 已具备 | 取指窗口（16 个 16 bit 槽） |
| ⑤参数 | `DECODE_WIDTH=4`／`COMMIT_WIDTH=4` | `spec/00` §4.3/§4.5 | 值 | 已具备（表内断言 `COMMIT_WIDTH==DECODE_WIDTH`） | 每拍提交 4 条／trace 4 条 |
| ⑤参数 | `ISSUE_WIDTH=6`／`WAKE_BCAST_PORTS=6` | `spec/00` §4.4 | 值 | 已具备 | `disp_x_t`／`wb_t` 的条数 |
| ⑤参数 | `ROB_ENTRIES=128`／`ROB_PTR_W=8` | `spec/00` §4.5 | 值 | 已具备（表内断言 `2**(W-1)==ENTRIES`） | `rob_id` 8 bit；ROB 阵列 128 项 |
| ⑤参数 | `PRF_INT_ENTRIES=64`／`PADDR_W=6` | `spec/00` §4.3 | 值 | 已具备 | `paddr_t` 6 bit |
| ⑤参数 | `RAT_ENTRIES=32`／`RAT_IDX_W=5` | `spec/00` §4.3 | 值 | 已具备 | `areg_t` 5 bit；重命名的架构号面 |
| ⑤参数 | `IQ_INT_ENTRIES=24`／`IQ_MEM_ENTRIES=20`／`IQ_BR_ENTRIES=20`／`IQ_TAG_W=12` | `spec/00` §4.4 | 值 | 已具备 | `iq_slot` 5 bit／`age` 12 bit；三路队列 |
| ⑤参数 | `LQ_ENTRIES=48`／`SQ_ENTRIES=32` | `spec/00` §4.6 | 值 | 已具备 | `lq_id` 6 bit／`sq_id` 5 bit；`SW`/`LW` 需队列 |
| ⑤参数 | `N_EU_TOTAL=9`／`ALU_NUM=3`／`BRU_NUM=1`／`SHIFT_NUM=1`／`MUL_NUM=1`／`DIV_NUM=1`／`AGU_NUM=2` | `spec/00` §4.4 | 值 | 已具备（表内 `N_EU_TOTAL` 加总断言） | `eu_id` 4 bit；14 条指令的执行单元分布 |
| ⑤参数 | `CHECKPOINT_COPIES=4`／`HIST_DEPTH=33`／`ROLLBACK_RATE=8`／`ROLLBACK_MAX=33` | `spec/00` §4.3/§4.5 | 值＋恢复机制口径 | 已具备（ADR-S2 已定值） | taken `BEQ`/`JAL` 与 trap 的冲刷恢复路径 |
| ⑤参数 | `MISALIGNED_EN=0` | `spec/00` §4.7 | 值＋判决点 | 已具备 | 非对齐 store ⇒ cause 6（唯一实测异常） |
| ⑤参数 | `BP_STAGES=3`／`IF_STAGES=3`／`FTQ_ENTRIES=16`／`IBUF_ENTRIES=16` | `spec/00` §4.2 | 值 | 已具备 | `ftqid_t` 5 bit／`ibufptr_t` 5 bit；前端队列深度 |
| ⑤参数 | `PRF_RD_PORTS=16`（发射读 12＋提交读 4） | `spec/00` §4.3 | 值 | 已具备（表内断言 `==ISSUE_WIDTH×2+4`） | `spec/01` §3.21① 提交拍读 PRF（trace `rd_data`） |
| ⑤参数 | `CLK_DOMAINS=1`／`RESET_SCHEME`（异步复位、同步释放） | `spec/00` §4.7 | 值 | 已具备（TB 侧时钟/复位占位已建） | TB 驱动 `clk`/`rst_n`；单时钟域 |

> 未列入的参数面（属 §3）：`VA_BITS`（无翻译）、§4.2 预测器**表结构**参数（`L1BTB_*`…`IUM_EN`）、§4.4 延迟值（`MUL_LAT`/`DIV_LAT`/`BYPASS_CLUSTERS`）、§4.6 cache/TLB/PTW/PMP 面、§4.7 总线/中断面。

### 2.6 首版恒 0／不消费成员表（防"冻结＝全用"误读）

| struct（`spec/01` 节） | 成员 | 首版口径 | 依据／后续 |
|---|---|---|---|
| `ftq_req_t`/`ftq_entry_t`（§3.1/§3.2） | `pred_conf`、`ras_op`、`ras_top`、`bp_upd_id` | 恒 0／不消费 | 预测器更新路径与 RAS 不在 G1-I（§1.2 第 7 条） |
| `ftq_entry_t`（§3.2） | `icache_ready`、`ptw_req` | 恒 1／恒 0（无 miss、无 PTW） | 无 cache 层次、无 MMU |
| 全 `pc`/`va`/`target` 类成员（§3.1~§3.21） | 规范地址判据（`bad_va`） | 恒 0 | 镜像地址全规范；判决点归 G1-F |
| `fetch_raw_t`（§3.3） | `is_c`、`err`、`err_code` | 恒 0 | 无 C；无取指异常（越界面见 §6.2 ③ `GR-2`） |
| `uop_t`/`iq_wr_t`/`disp_x_t`（§3.4/§3.8/§3.11） | `aq`、`rl`、`fm` | 恒 0 | 无 AMO/`fence` |
| `rob_alloc_t`/`rob_entry_t`（§3.6/§3.7） | `type[2] is_comp`、`is_wfi`、`is_fence` | 恒 0 | `is_comp` 一期恒 0（T-4 定案）＋镜像无 WFI/FENCE |
| `rob_entry_t`/`rt_t`（§3.7/§3.21） | `is_intr` | 恒 0 | 无中断 |
| `br_resolve_t`（§3.12） | `is_jalr_ret`、`pred_taken`/`pred_target`（反馈面）、`bp_upd_id` | 恒 0／不消费 | 镜像无 `JALR`；更新路径不在 G1-I |
| `mem_req_t`（§3.13） | `amo_op`、`req_id` | 恒 0 | 无 AMO；无 MSHR/outstanding 语义 |
| `dcache_rsp_t`（§3.16） | `fwd_hit`、`fwd_src` | 恒 0 | 首版不引入转发（§6.2 ① `GS-5`） |
| `excp_t`/`ret_ctrl_t`（§3.18） | `is_intr`、`deleg`、`sbe`、`cle`、`svae`、`spep`、`is_sret`、`mprv_at_trigger`、`mprv_clr` | 恒 0 | 无中断/委托/S 侧/字节序面；首版不写 `mstatus.MPRV` |
| `commit_t`（§3.17） | `wfi_vld` | 恒 0 | 镜像无 `WFI` |
| `icache_rsp_t`（§3.16） | `err_pos` | 恒 0 | 无取指异常 |
| `uop_t`/`rob_alloc_t`/`rob_entry_t`/`mem_req_t`（§3.4/§3.6/§3.7/§3.13） | `priv` | 恒 3（M） | 首版仅 M 模式 |
| `rt_t`（§3.21） | `mispred`、`cycle`、`seq`、`mem_*` | 不参与比对（可任意／仅调试） | §3.21 与 `iss/README.md` §3 已定 |

---

## 3. 不在 G1-I 内、明确延后到 G1-F 的（一行一类）

| 类 | 条目 | 归属篇/节 | 延后理由 | G1-F 触发源 |
|---|---|---|---|---|
| 未定义型①：**零定义 12 型** | `ibuf_wr_t`／`lq_alloc_t`／`sq_alloc_t`／`rob_head_t`／`trap_req_t`／`freelist_ret_t`／`x_csr_rd`／`mstatus_t`／`satp_t`／`ipend_t`／`flush_all_t`／`redirect_t` | `spec/00` §6 注（X5）所指各篇 | 首版不在其**实例化面**上（逐条对应关系见 §6.2 ① `GS-2`~`GS-4`）；且自造定义＝越界 | 首次需要该机制的那一版（§5 表） |
| 未定义型②：已定义但更新路径延后 | `bp_upd_t`（`spec/03` §2.9，57 bit） | `spec/03` §2.9 | 属"预测器更新路径"（§1.2 第 7 条） | 预测器精度目标进判据时 |
| `spec/01` §3 排除的 **5 型** | `mmu_transl_req_t`／`mmu_transl_rsp_t`／`miss_req_t`／`fill_t`／`mshr_wake_t` | `spec/01` §3.14/§3.15 | 无 MMU、无 cache 缺失面 | `spec/08`／`spec/09` 收口 |
| 取指拼接细则 | `xw_carry` 与跨窗拼接（ISS-039 定案 A）、`slot16_vld` 回退点 | `spec/01` §3.16 | 镜像全 4 B 对齐 ⇒ 槽 15 起始不可达 | 并入 C 展开那一版 |
| 复位值／WARL 全面 | `spec/10` §4.1 表**外**行（S 侧 CSR、PMP、计数器、三 ID、`misa` 位段、`satp`） | `spec/10` §4.1 | 首版只读 6 个 CSR | S/U 特权与 MMU 入面时 |
| 延迟数字 | `MUL_LAT`／`DIV_LAT`／前端各级延迟／`BYPASS_CLUSTERS` 拍数／冲刷总延迟（5 拍档） | `spec/00` §4.2/§4.4、`spec/01` §5.3 | M1 判据**不含拍数**（只判 trace 0 mismatch） | `spec/13` 成稿／M5 性能面 |
| 保护判决面 | PMA 区域表、PMP（`PMP_ENTRIES`/`PMP_GRAIN`/`PMP_A_MODES`/`AD_BITS_POLICY`） | `spec/00` §4.6、`spec/08` | 首版无保护（M 态、地址直通） | `spec/08` 收口 |
| 中断面 | CLINT/PLIC、受理三条件、级间优先、委托、NMI | `spec/00` §4.7、`spec/10` §3 | 镜像无中断源 | 中断用例入面时 |
| MMU 面 | Sv39／PTW／TLB／`satp` 行为／`sfence.vma` | `spec/08` | 不含 MMU | `spec/08` 收口 |
| cache 层次 | L1I/L1D/L2／MSHR／替换／写回／AXI4 主端口 | `spec/09` | 首版内存桩 | `spec/09` 收口 |
| C 展开 | 64 项展开表、`is_c` 语义、IBUF→D 的展开级接口（`ibuf_wr_t`） | `spec/02` §2.2/§5 | 镜像无 C 指令 | C 用例入面时 |
| 原子与内存序 | LR/SC／AMO（`amo_op`/`aq`/`rl`）、`fence`/`fence.i`、RVWMO 判据 | `spec/00` §8、`spec/02` §18 | 镜像不含 | 一致性子系统入面时 |
| FP/D 预留 | `mstatus.FS`、PRF/ROB 预留位、FP 发射组 | `spec/00` §7 | 非目标 | 二期 |
| 性能与度量口径 | `spec/13` 周期模型、PERF 事件、预测准确率、IPC | `spec/00` §9、`spec/13` | M1 不判性能 | M5 前 |
| 位量/面积类 | `spec/00` §4.8 估算表（含未计项折入口径） | `spec/00` §4.8 | 非接口 | G1-F 全量 |

---

## 4. G1-I 达到可签的判据（`GI-n`；可机判优先）

**判据写法**：每条给出可执行形式（命令或"文本在册＋可逐值核"），并标**现有判据是否覆盖**——「未覆盖」的条目即后续补判据的清单（§6.3 `GD-1`）。

| # | 判据（可执行形式） | 现有判据覆盖 |
|---|---|---|
| `GI-1` | `python script/flow.py check` 的 `types-drift`／`types-coverage`／`types-width-consistency`／`types-crosscheck`／`types-compile`／`types-elab` **全 PASS**（= §2.1 的 23 型成员级位域为真且可编译/可展开） | **已覆盖**（`types-*` 判据在环，2026-09-25 实跑全 PASS） |
| `GI-2` | §2.1 的 23 型**⊆** `rtl/vr1/include/vr1_types.svh` 的 28 个 `// ---- spec/01 §3 L…` 块；§3 排除的 5 型 + 12 个零定义型名**不得**出现在 `rtl/vr1/**`（除 `include/vr1_types.svh` 自身）与 `tb/vr1_uvm/**`（负判据） | **未覆盖**（需新增：清单↔生成件绑定 + 排除符号扫描） |
| `GI-3` | `spec/10` §4.1 表含 `mtvec/mepc/mscratch/mcause/mtval/mstatus` 六行，且每行"复位值／位段要点／WARL 可写／权限"四列非空 | **未覆盖**（文本判据，需新增） |
| `GI-4` | 六个 CSR **地址**逐值一致：`spec/10` §4.1 地址列 == `iss/vriss/consts.py` 的 `Csr` 枚举（0x300/0x305/0x340/0x341/0x342/0x343）；`mstatus` 位段（`MIE/MPIE/MPP`）与 `MStatus` 位掩码一致 | **未覆盖**（需新增：CSR↔ISS 逐值判据） |
| `GI-5` | `spec/10` §2.1 在册，且同步 14 项码值与 `iss/vriss/consts.py` 的 `Exc` **逐值**一致、中断 7 项与 `Intr` 一致；§2.3 所列码 {4,6} 在表内且标"可产生" | **未覆盖**（需新增：异常码表↔ISS 逐值判据） |
| `GI-6` | `spec/10` 有一行成文定义 **`mtval` 非对齐取值口径**（= 出错 VA），且与 ISS 断言一致 | **未覆盖＋材料缺**（§4.1 `mtval` 行现仅"非法指令回填指令位"；本轮不写 `spec/`） |
| `GI-7` | `python iss/tests/test_smoke.py` 退出码 0 且出 `[PASS]` 行（覆盖：30 条退休数、寄存器期望、trap `cause`/`mtval`/`mepc`、`mstatus.MPP` 归底、CSV 表头 == `TRACE_CSV_FIELDS`、`CSRRW`/`CSRRS` 的 CSR 写面） | **未覆盖**（`flow.py` 无该判据；现 ISS 侧只有 `trace-self` 的往返比对，未跑行为断言） |
| `GI-8` | 14 条指令的 `isop` 取值 ⊆ `spec/02` §9.1 具值表，且 `iss/vriss/encode.py` 的具名构造器与之同源；派生视图（`cls`/`src_sel`/`dm`/`sext`）取值 ⊆ `spec/02` §9.5 | **未覆盖**（需新增：isop 子集↔ISS 编码判据） |
| `GI-9` | §2.5 所列参数名 **⊆** `rtl/vr1/include/vr1_params.svh` 的 parameter 名；`params-drift`／`params-coverage`／`params-invariants`／`params-compile`／`params-elab` 全 PASS | **部分覆盖**（`params-*` 在环；"清单↔参数表绑定"未覆盖） |
| `GI-10` | `spec/01` §3.21 附录（RVFI 逐字段映射三清单）成文，或由 R0 明示豁免该自述句；`iss/README.md` §3 的 `rt_t`→列映射与 §3.21 成员表**行级一一对应**；`TRACE_CSV_FIELDS` 与映射表列序一致 | **部分覆盖**（映射表在册；"附录未填"这一前置未覆盖，且是**材料缺**） |
| `GI-11` | `image-hex` PASS（md5＋base `0x1000`＋words 68）；TB 侧 `$readmemh` 采用同一路径、同一字/字节口径（二选一并留证） | **已覆盖（镜像面）**；TB 侧采用**未覆盖**（并入 `GI-14`） |
| `GI-12` | `trace-self` PASS（golden vs ISS 读 `.hex` 侧，`pc,binary,gpr,csr` × 30 条，mismatch 0） | **已覆盖**（判据在环） |
| `GI-13` | TB 侧 trace 写出器字段序 == `TRACE_CSV_FIELDS`；停机判据＝`tohost` 写；watchdog 2,000,000 拍／挂钟 20 min 在 TB 内可见 | **未覆盖**（`tb/vr1_uvm/` 现为占位骨架：无 DUT、无写出器、无停机判据） |
| `GI-14` | M1 两条 exit 判据在 `state/flow.json` **注册**并带证据：`rtl-compile`（vlog `-- Compiling` 计数 + `Errors: 0`）、`rtl-vs-iss`（`sim/golden/iss_smoke.csv` vs RTL 侧 CSV，长度相等且 `mismatch=0`） | **未覆盖**（两条判据尚未注册，属 M1 阶段动作，不由本清单签） |

> 覆盖统计（供 §6.3 补判据用）：**现有判据覆盖不到的有 10 条**＝`GI-2`／`GI-3`／`GI-4`／`GI-5`／`GI-6`／`GI-7`／`GI-8`／`GI-13`／`GI-14`，＋半覆盖两条（`GI-9`／`GI-10` 的"绑定/前置"面）与 `GI-11` 的 TB 侧采用面。

---

## 5. G1-F 的推进方式（缺口驱动、逐版增量）

**原则**：**不**先把 14 篇写全再签，而是**由 M1 闭环实测暴露的缺口驱动**，每次只把"下一次实测必需"的那一类搬进冻结面。每版增量的动作固定为：`spec` 升版（走 Requirement Review）→ 该类的接口/口径成文（成员级位域或码表）→ 增量复审（知识库 §6.1 增量轮：旧问题真改＋改动集闭包内新增 0）→ 四段材料（§6.2）→ `python script/flow.py check` 0 FAIL → 回填台账（`flow.py record`）。

| 版次（建议序） | 增量内容 | 触发源（缺口驱动） |
|---|---|---|
| v1 | MMU/Sv39 面：`spec/01` §3.14 两型 + `satp_t` + `x_csr_rd`（若 M1 实测暴露 CSR 读口跨模块） | M1 后第一条含翻译/保护的用例 |
| v2 | cache 层次：`miss_req_t`/`fill_t`/`mshr_wake_t` + `rob_head_t` | 首个 L1 miss 用例 |
| v3 | 中断面：`ipend_t` + `spec/10` §3 受理条件 | 首个中断用例 |
| v4 | S/U 与委托：`mstatus_t` + `spec/10` §4.1 表外行（复位值/WARL 全面） | 首个 S 态用例 |
| v5 | C 展开：`ibuf_wr_t` + `xw_carry` + `spec/02` §2.2/§5 表 | 首个 C 指令用例 |
| v6 | 控制组拆分：`trap_req_t`／`freelist_ret_t`／`flush_all_t`／`redirect_t`（把首版控制组内部信号升格为冻结接口） | 若 M1 后要做模块级划分/覆盖率签核 |
| v7 | 预测器更新路径：`bp_upd_t` + 预测精度目标 + `spec/03` 表结构收口 | IPC/准确率进判据时 |
| v8 | 原子/内存序 + 性能口径（`spec/13`） | M5 前的路径 A 抬档评审 |

> **禁止**：借升版顺手改已冻面（任何已冻接口变更＝升版＋RR＋重签，`spec/00` §6 同口径）；**禁止**在未升版的批次里实现 §3 延后类的机制（`GI-2` 负判据）。

---

## 6. 分段签路径

### 6.1 路径（照知识库 §6.2／§10 P1 口径）

| 段 | 签什么 | 签署人 | 前置 | 签后解锁 | 不得 |
|---|---|---|---|---|---|
| **段 0：G1-I 冻签** | 本清单 §2 冻结面（23 型 + 6 CSR + 异常集 + trace 口径 + 参数集）与 §1 范围 | **R0（人）** | §4 的 `GI-1`~`GI-13` 满足（`GI-14` 属段 1）；§6.2 四段材料齐 | `rtl/` 对**冻结面**解禁（含 `guard-write` 白名单更新，见 `GD-5`）；可写首版 RTL | 不得实现 §3 延后类；不得自造接口 |
| **段 1：M1 闭环** | 判据结果（`rtl-compile` + `rtl-vs-iss` 0 mismatch） | 验证执行（AI）→ **R0 过目** | 仿真器可用（ISS-104 或 ISS-002）；TB 写出器/停机判据就位（`GI-13`） | M1 达成；基线触发点之一成立（`AGENTS.md` §1） | 不得改判据口径让结果通过（红线 R6） |
| **段 2：每次升版签增量** | 该版增量的冻结面（§5 表一行） | **R0（人）** | 该版 spec 过 RR + 增量复审 0 新增 + 四段材料 + `flow.py check` 0 FAIL | 该版对应机制的实现面解禁 | 不得用"清单外临时口径"；不得积压未复核项 |
| **段 3：G1-F（全量冻结）** | `spec/00` §6 全表（M01~M20）＋ 13 型全定义 ＋ 未决项清零 | **R0（人）** | 前置状态表逐篇"可冻"（`doc/spec/14` §2）＋ §9.5 评审 list 四段人读无异议 | `rtl/` 转只读；基线可宣布 | 不得跳过 RR；不得留"待锚点"项 |

**签署语义（照抄知识库 §6.2）**：人签的是「**清单完整 ＋ 我接受其风险**」，**不要求**人重算或复核全部细节——那是锚点、审计与机判的职责。**list 缺项＝材料不全，不得签署**（知识库 §10 P1 行同款）。

### 6.2 每次签署前必须齐的四段材料（含**本轮 G1-I 的实例**）

**① 取舍条目表**（每条：`ID｜取舍点｜选定｜替代方案≥1｜依据链｜回退方式｜下游义务`）

| ID | 取舍点 | 选定 | 替代方案 | 依据链 | 回退方式 |
|---|---|---|---|---|---|
| `GS-1` | 冻结面大小 | 冻结 23 型、明确排除 5 型（MMU/cache-missing） | 全 28 型／只冻 trace+trap 边界 | `spec/00` §6 冻结判据＋§1.0 一期定位；§1 的 smoke 反推表 | 单点扩表即可（新增行，不改已冻面） |
| `GS-2` | 13 个未定义 `*_t` 的处置 | **不冻、不自造**；首版控制组的内部信号不受冻结约束（G1 冻接口不冻实现，`spec/00` §6 首句） | 先补写 13 型再冻（= 14 篇写全，已判不可满足） | `spec/00` §6 首句＋注（X5）；`spec/03` §2.9（唯一已定义者 `bp_upd_t`） | 若 R0 要求先补型 ⇒ 段 0 前插一批 spec 落文（成本＝4~6 张字段表） |
| `GS-3` | C 展开级（`ibuf_wr_t`） | 首版 **D 级直读 `fetch_raw_t`**（§3.3 定义的 IBUF→D 形态）、展开级恒等旁路 | 先定义 `ibuf_wr_t` 再冻 | `spec/01` §3.3（IBUF→D）＋`spec/00` §6 M04 行；镜像无 C | 若 R0 判必须保持 M04/M05 两模块边界 ⇒ 段 0 前补 `ibuf_wr_t` 定义 |
| `GS-4` | LQ/SQ 分配接口 | 分配结果**折入** `rob_alloc_t`/`iq_wr_t`（附M-B-4 定案），首版不设 `lq_alloc_t`/`sq_alloc_t` | 另立两型 | `spec/01` §3.6/§3.8（`lq_id`/`sq_id` 成员在册）＋附M-B-4 | 同上（补型） |
| `GS-5` | 存储可见性（`SW`→`LW` 同址） | 首版以**"等更老 store 提交"**保证可见（保守、trace 正确） | 实现 `spec/07` 转发（`FWD_MAX_SOURCES` 面） | `spec/01` §5.2 `S` 行（一期禁投机 store 写 cache）＋§3.17 `sq_dealloc` | 引入转发即可（`dcache_rsp_t.fwd_*` 已冻，接口不变） |
| `GS-6` | 预测器 | 接口在、机制简（顺序/静态预测 + 直连 FTQ） | 首版即做 TAGE/BTB/RAS | §1.2 第 7 条（只排更新路径）＋`spec/00` §4.2 | 表结构在接口之内演进（不改冻结面） |
| `GS-7` | trace 前置（§3.21 附录） | 段 0 前须补附录或由 R0 明示豁免 | 无视该自述句直接冻（违反本篇自述） | `spec/01` §3.21 附录行＋ISS-017（处理中） | 补附录（三清单）＝一次性落文 |

**② 未决项**：**须为 0**。本轮候选未决项与处置：

| 候选未决项 | 处置 | 说明 |
|---|---|---|
| §3.21 附录未填 ⇒ `rt_t` 能否冻 | 转 `GS-7`（段 0 前置义务 `GD-2`） | 不是"未决"，是**有明确出口的前置**：补附录或 R0 豁免 |
| `mtval` 非对齐取值口径缺 | 转 `GD-3`（`spec/10` 落文一行） | 同上：出口明确（`GI-6`） |
| C 展开级接口形态（`GS-3`） | 已自决（`GS-3` 选定） | 自决面内（设计/规格类取舍，规则 R2 口径） |
| 控制组内部闭环 vs 拆分（`GS-2`） | 已自决（`GS-2` 选定） | 同上；代价＝G1-F 升版时重排内部信号（`GR-5`） |
| 13 型中是否有"首个跨模块即必须"者（`x_csr_rd`） | 已自决：首版 CSR 读口在控制组内闭环 | 若 R0 判必须跨模块 ⇒ 回退路径见 `GS-2` |

**③ 风险与残余**（逐条带出口）

| ID | 风险 | 影响 | 处置／出口 |
|---|---|---|---|
| `GR-1` | `spec/01` §3.21 附录未填（ISS-017 处理中） | `rt_t` 的冻结依据在本篇自述下不成立 | `GD-2`：段 0 前补附录或 R0 明示豁免 |
| `GR-2` | 越界取指读零填充（`0x00000000`）产生潜在非法指令，两侧处置须一致 | 可能造成假 mismatch 或挂死 | 首版口径二选一并写入 TB/断言：报 `cause=2` 或"不产出起始"；与 ISS 口径对齐（`GI-7` 覆盖不到，属首版实现取舍） |
| `GR-3` | `IALIGN` 口径：`misa.C=1`（`MISA_VALUE`）但首版无 C ⇒ `mepc` bit1/`mtvec` 对齐的 IALIGN 面未定 | 镜像内不影响（全 4 B 对齐） | 首版按 `mepc` bit0=0、`mtvec` 低 2 位=0；IALIGN 全面随 C 版收口 |
| `GR-4` | `mtval` 口径缺 | cause 6 的 `mtval` 无规格依据（只有 ISS/规范） | `GD-3`（`spec/10` 一行） |
| `GR-5` | 首版控制组内部信号（CSR/trap/冲刷）在 G1-F 升版时需重排 | 实现返工（接口面不变） | 升版批次内做（`§5` v6）；不含接口变更 ⇒ 不触发重签 |
| `GR-6` | 同模型多角色共享盲点（红线 R21）；锚点面本清单以**内部锚**（`spec`/ISS/机判）为主，外锚少 | 残余判断风险 | 由 R0 签署＋`doc/verify/05` 增补留痕兜底 |

**④ 抽查建议**（供人优先读；高风险与不可回退处）

| # | 建议抽查处 | 为什么优先 |
|---|---|---|
| 1 | §2.1 的 23 型判定在 **R-b 反推原则**下是否可核（尤其 `ftq_req_t`/`icache_rsp_t`/`dcache_rsp_t` 三项：属"接口在、机制不在"的边界） | 本次唯一的"范围边界"取舍（`GS-1`/`GS-2`），改一次要动 §1/§2/§3/§4 四节 |
| 2 | §2.2 的 6 个 CSR 行 + §2.3 的异常集 | 首条闭环的全部架构可见状态都在这里 |
| 3 | §2.6 首版恒 0 成员表 | "冻结≠全用"的口径若被误读，会在首版埋下静默不用/误用 |
| 4 | §4 的 10 条未覆盖判据（`GI-2`~`GI-8`/`GI-13`/`GI-14`） | 这些是段 0 的机判空白；补判据清单即由它派生（`GD-1`） |

### 6.3 下游义务（`GD-n`；本批只登记，不代写）

| ID | 义务 | 落点 | 归属 |
|---|---|---|---|
| `GD-1` | 按 §4 的未覆盖清单补机判据（优先 `GI-2` 负判据、`GI-4`/`GI-5` 逐值一致、`GI-7` ISS 冒烟在环） | `script/flow.py` 的 `CHECKS` 注册表 | 验证代码（直接改，记台账） |
| `GD-2` | 填 `spec/01` §3.21 附录（RVFI 三清单）或由 R0 明示豁免 | `doc/spec/01` §3.21 | spec 落文批（ISS-017） |
| `GD-3` | 补 `mtval` 非对齐取值口径一行（= 出错 VA） | `doc/spec/10` §4.1 `mtval` 行 | spec 落文批 |
| `GD-4` | G1-I 冻签的时间戳与"清单完整"结论落记录 | `doc/spec/14`（新增分段签节） | 冻结记录批（人在场） |
| `GD-5` | `guard-write` 的 `rtl/**` 白名单随冻签更新（解禁范围＝冻结面；§3 延后类仍拒写） | `.zcode/config.json`＋`script/flow.py` `cmd_guard_write` | 机械动作，须 R0 批准（红线 R1/R22） |
| `GD-6` | TB 侧：trace 写出器（`TRACE_CSV_FIELDS` 同序）＋停机判据（`tohost` 写）＋watchdog | `tb/vr1_uvm/`（现为占位） | 验证平台批 |
| `GD-7` | M1 两条 exit 判据在 `state/flow.json` 注册（`rtl-compile`/`rtl-vs-iss`） | `state/flow.json` | G1-I 冻签后、M1 实施批 |
| `GD-8` | `AGENTS.md` §1「验证阶段」与 `doc/当前目标卡.md` 的指针刷新 | 两件 | 会话收尾（规则 11） |

---

## 7. 出口自检

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 范围口径与 R0 批准的建议逐条一致（含/不含） | §1.0 与 §1.1/§1.2 逐条对照（含项均带实测依据） | 一致 |
| 2 | §2 每条可反推到 smoke 的具体指令/CSR/判据步骤 | §2 各表"反推依据"列逐行；R-b 规则在 §2 前置 | 一致 |
| 3 | 接口 struct 计数自洽（28 = 23 + 5） | §2.1 表 23 行 + §3 排除 5 型逐名点数 | 一致（23/5） |
| 4 | 13 个未定义型的处置有出处 | `spec/00` §6 注（X5）逐名；`bp_upd_t` 例外引 `spec/03` §2.9 | 一致 |
| 5 | §4 判据均为可执行形式，且覆盖情况逐条标注 | §4 表 14 行；未覆盖 10 条逐条列出 | 一致 |
| 6 | 四段材料齐（取舍/未决/风险/抽查） | §6.2 ①~④ 四表 | 一致 |
| 7 | 未越写边界 | 本批只新建本文件；`doc/spec/**`、`doc/verify/**`、`script/**`、`state/**`、`rtl/**`、`tb/**` 未动；未 `record` | 一致 |
| 8 | 文档结构/码点不破仓门 | `python script/flow.py check` 的 `md-integrity`／`codepoints` | 见本批 `flow.py check` 输出 |
