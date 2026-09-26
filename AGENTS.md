# VR1 项目 AI 协作指令（AGENTS.md）

> 本文件由 `D:\IC验证知识库\项目AGENTS模板\项目AGENTS模板.md` 复制填写而来。
> AI 进入项目会话先读本文件，再按 §5 规则与《AI验证工作流程》九步流水线工作。

---

## 0. 流程唯一入口（2026-09-25 起：方案 A · Runner-in-the-Loop）

- **日常只跑一条命令**：`python script/flow.py check`（全判据，0 FAIL 才算过）与
  `python script/flow.py next`（下一步，唯一权威）。状态唯一真值 = **`state/flow.json`**；
  编号由脚本自增（**禁手写**）。
- **流程定义（SSOT）**：`doc/process/03-自动化流程重构-三方案.md`（A 为骨架 / B 判据按模块增量 /
  C 里程碑边界启用）。人读镜像：`doc/当前目标卡.md`。
- **循环由系统件承载，不靠提示词、不靠定时任务**：`.zcode/config.json` 的
  `Stop`（有可跑的确定性步骤即请求继续，上限 3 次）、`SessionStart(startup|resume|clear|compact)`
  （压缩/续跑后强制重注入里程碑、exit 与禁令）、`PreToolUse`（写边界机械执行）。
  **改 hooks 后须重开一次会话**（hook 在会话启动时快照）。
- **角色**：`tools/vr1-plugin/agents/`（先在 设置→插件管理 装一次本地插件才可派发）；
  `vr1-auditor` 的工具白名单无 `Bash/Write/Edit`，机械只读。
- **退役件**：`doc/_legacy/2026-09-25-流程v1/`（自动推进说明 / 派发词模板 / 自动循环定时任务 / flow_run.py）；
  `script/gate.py`、`run_cmd/AutoQueue.yaml`、`doc/verify/03-验证计划.md` 原位保留但已打退役横幅。
- **ADR 编号分区（2026-09-25）**：`doc/decisions/ADR-P-<n>-*.md` ＝ 流程侧 ADR 分区（`P`＝process），
  由 `python script/flow.py record ADR` 自增（**禁手写**；台账 `next.ADR` 计数沿用，写入 id 形如 `ADR-P-<n>`，
  当前下一条＝4 号）。
  裸号 `ADR-<n>` 是规格/历史面既有编号（`spec/**` 内 `ADR-1~5`、`doc/verify/05` 的 `ADR-D3/D4/D5/S06` 等），
  **保留原义、不得再发新号**；两分区撞车与 `ADR-P-<n>` 断链由 `flow.py check` 的 `id-unique` 判据拦截。

---

## 1. 项目信息

- **项目名**：virtual_riscv / **VR1**（RV64GC 超标量乱序处理器核，规格先行）
- **项目定位**（2026-09-22 人确认，详见 `doc/spec/00` §1.0）：一期做**能力与方法证明**，
  不追 2026 年性能主流应用级核；**M5（首条 riscv-test 通过、拿到实测 IPC）后走路径 A 增量抬档**
  （D 提一期 / 依赖间距 3→2 拍 / μop cache / L2→1MB + L3 预留 / RVV 仅留架构位）。
  **禁止以“追现代主流性能”为由提前改架构**；抬档一律走 spec 升版 + Requirement Review。
- **DUT 模块/顶层**：`vr1_core`（计划代码位置 `rtl/vr1/core/vr1_core.sv`）
  - **当前状态：RTL 尚未存在**。本项目路线为「规格书写完 → Review G1 接口冻结 → 一次性实现」，
    冻结前 `rtl/` 只允许出现 `rtl/vr1/include/*.svh`（参数与 struct 定义，非可综合功能代码）。
- **语言/方法学**：SystemVerilog（可综合子集，只用 IEEE 1800-2009/2012 已有特性）+ UVM 1.2 + SVA
- **规格文件**：`doc/spec/00-总体规格.md` ~ `14-接口冻结记录.md`（共 14 篇；**已成稿 2/14**，逐篇升版——当前 `spec/00` v0.1 待评审、`spec/01` 已被 R7 评审判为不通过、降为 **v0.2 返工中**且不再是 G1 冻结候选，见 ISS-018/020/021）
  - **`doc/spec/00` §4 参数总表是所有数值的唯一权威源**；`spec/01~14` 只引用不另赋值
  - 规范口径唯一来源：`D:\IC验证知识库\_tools\riscv-spec.pdf` 与全文提取件
    `D:\IC验证知识库\_tools\extracted\riscv_spec\riscv_spec_full.txt`（非特权卷 I + 特权卷 II 1.13）
    **2026-09-23 更新：`_tools\` 已恢复**（ISS-032 已闭合——补拷完成、4 条锚点复验命中）——上述两个路径、
    §3.3 的 riscv-dv 与 §4 参考核源码**均可达**；`doc/spec/` 内【权】§号引用按一级依据（本机提取件）标注，
    不再一律标 `待锚点`（红线 R20 仍要求"关键结论必绑锚点"，只是锚点现已可用）。
  - 设计空间与选型依据：`D:\IC验证知识库\Verilog与CPU设计知识库\CPU卷\04-高性能超标量CPU精读.md`
- **验证阶段**（AI 每次会话结束前更新此项）：
  **流程 A 已落地（2026-09-25），实时状态一律看 `state/flow.json` + `python script/flow.py next`**
  （本节只留指针，不再镜像长文本——旧写法正是"状态住在对话/长文里"的病根）。
  - 已达成：**M0.5 流水线自证 + 参数单源**（2026-09-25 15:15；六项 exit：params-drift /
    params-coverage / params-invariants / params-compile / image-hex / trace-self 全过）；
    **M1a 接口类型单源**（2026-09-25 15:24）；**M1-I G1-I 机判面**（22:47，11 条 exit 全过）；
    **M1 RTL-vs-ISS 首条闭环**（2026-09-26 02:24；`rtl-compile` + `rtl-vs-iss` 两条 exit 全过，
    步骤 P7 由 `flow.py run` 收口置 done）；**M2 riscv-tests rv64ui 定向子集闭环**
    （2026-09-26 08:43 met；三条 exit 全过，证据在心跳第 10 轮刷新，见下）。
  - **G1-I 已由 R0 签署**（2026-09-25；记录 `doc/spec/14` §7；状态件 `state/freeze.json`）
    ⇒ `rtl/` 进**实现期**（写边界＝`guard-write` 三档：未冻／G1-I 已签授权／基线宣布后先批后改）。
  - **M2 三条 exit（met；2026-09-26 心跳第 10 轮刷新证据，第 12 轮随激励面变更复验）**：
    `m2-rv64ui`（判定子集 **52/52 全过**——第 12 轮把定向用例 `vr1dir-p-dir_csr` 与导入镜像
    `m_smoke` 纳入 `MANIFEST.tests`，判定面随之扩到 52 条；逐条 ISS `halt_val=0x1` ＋ RTL
    `HALT_PASS` ＋ `trace_compare` 列 pc,binary,gpr,csr 0 mismatch；数据面逐条 `+DATA=` 预载）／
    `m2-regress`（两轮 r6/r7 各 50/50、`new_fail=0`、`same_config=yes`、R9/R10 在环）／
    `m2-cov`（**读最新批 `m3cov_r1`**：报告 `doc/verify/07-m3cov_r1.txt`＋编译指纹；**不判阈值**，
    阈值属 M3）。
  - **已达成：M3 覆盖率与回归收敛（2026-09-26 心跳第十六轮；`flow.py check` 末行 PASS，记账 R-272）**——
    三条 exit 已是**已注册真判据**（`m3-code-cov`／`m3-func-cov`／`m3-regress-stab`，本体在 `script/flow.py`；
    口径＝**只核证据＋时效**、不重跑重活；阈值取本文件 §4 原文、未达标**如实 FAIL**、不放宽）。第十六轮实跑：
    `m3-regress-stab` **PASS**（本版本同配置 r5/r6/r7 三轮全过、轮间 0 新 FAIL；证据时效口径＝**只锚 RTL 面**
    ——TB 面不进版本校验，R0 2026-09-26 认可、已写进判据消息）；`m3-code-cov` **PASS**
    （Statements **98.56%**（1025/1040）／Branches **100.00%**（447/447）／Conditions **100.00%**（71/71）／
    FSM Transitions **100.00%**（6/6）——后三项的"原分母"现值写在判据消息里（447/463、71/79、6/8），
    差额＝**R0 2026-09-26 授权的「列缺豁免」**；Statements 的 15 处未命中**不在**豁免清单内、照旧计入分母）；
    `m3-func-cov` **PASS**（`cg_fetch` **8/8**、`cg_lsu_fsm` **12/12**——`t_req_idle`/`t_rsp_idle` 经
    **R0 裁定①受控复位注入通道**实测命中：`rst_*` 前缀条目仅入覆盖率批 `run_cmd/cover_m3_testlist.txt`、
    不进回归同配置与 `m2-rv64ui`，机制件＝`tb/unit/m1_e2e_tb.sv` 的 `+RESET_INJECT=`＋
    `run_cmd/cover_rv1.py:run_case_rst`；`cg_retire` **34/34**＝原 34/35 扣豁免 1＝`priv_u`
    （R0 裁定②列缺带归属 G1-F/二期，逐条落 `doc/verify/02` §6））。
    **列缺豁免机制（本轮 R0 授权，改判据本体）**：判据解析 `doc/verify/02` 的列缺清单（§7.2 机器可读豁免集／
    §6 表体）→ **从分母扣除** → 消息**逐条回显**（含清单位置行号与依据／归属）。四条硬边界：① 只豁免清单内、
    依据可查的条目（code 面每条须回指**非**「已纳入／处置项」的 `CC-` 主表行＋非空归属＋行号能落到
    `filelist/rtl.f` 在册单元源码的**非空行**）；② **不改**任何 bin／采样条件／阈值／检查器逻辑（红线 R6/R7）；
    ③ 判据用**报告现值设反向上界**（同一 单元×面 ≤ 该格 misses、同一面 ≤ 该面 misses）⇒ **报告没报缺的项
    豁免不了**，且逐条依据＋清单行号回显 ⇒ 防"新增／改写列缺条目凑达标"；④ **豁免集为空时判据行为与消息与
    落地前逐字一致**（已实测），而"清单本体解析不到"一律 **FAIL**（fail-closed）。自证伪：4 种造假注入
    （超上界／回指「已纳入」行／凭空行号／对全命中单元灌豁免）**全被拦**；Conditions"差的 1 项"经逐项源码
    对账＝**啃不掉**（8 项全为结构性／无产生者／死路径／无中断源，非 ISA 行为面）⇒ 留在豁免集内并写明，
    落点 `doc/verify/02` §7.2／§7.3。
    **前情（第 13~15 轮，详见 `doc/verify/02` §7 与台账 R-269/R-270）**：R0 三项裁定（受控复位注入通道／
    `priv_u` 列缺带归属／回归证据只锚 RTL 面）＋ **ISS-128 五组对账消解**（组 1 `JALR f3≠000`／组 2
    `MRET rs1≠0·rd≠0`＝真保留编码 ⇒ **补 ISS 守卫**，CC-2/CC-3 转「已纳入」；组 3/4/5＝在册合法成员
    ⇒ ISS 正确、不收窄）＋ `07-m3cov_r2` §B 逐行分类（(i) 可达未激励由 `sw/tests/direct/dec_probe.S` 补上、
    (ii) 不可达逐条列缺带归属）。
    第三条 M3 exit（`m3-mutation-audit`／错误注入保真度抽检）**机制尚无落点** ⇒ 保留待注册（TODO(M3-3)）。
  - **M3 前置（已完成）：M3-(d)「补缺指令」**——RTL 合法面由 41 条扩到
    **57 条**（心跳第 10 轮增补 16 条：条件分支余 4 `BLT/BGE/BLTU/BGEU` ＋ `JALR` ＋ 载入余 6
    `LB/LH/LD/LBU/LHU/LWU` ＋ 存储余 3 `SB/SH/SD` ＋ `FENCE/FENCE.I` 最小语义）；riscv-tests
    52 条里 **50 条在册可判**，余 2 条**显式列缺带归属**（`sim/image/rv64ui/GAP.json` 的
    `pending_subset`，**不静默跳过**）：`fence_i`＝缺机制（取指侧可执行域 0x0000~0x3FFF 与数据窗
    不统一；实测 ISS PASS／RTL 取指回 0）、`ma_data`＝缺机制（`MISALIGNED_EN=0`，两侧一致不支持，
    `doc/process/00` ISS-010）。**余 30 成员**（A 11／M 余 10／CSR 余 4／SYSTEM 余 5）随 G1-F。
    ~~旧编号体系的 M3（平台 smoke）~~已改名 **M-B**（人的决策点／基线宣布），见 `doc/verify/04` §①。
  - 仿真器/环境**已就位、不再是阻塞项**（ModelSim `vsim` license 已由 `flow.py` 注入环境变量解决＝R-224，
    `vlog`/`vsim` 实测均通；~~WSL2 路线~~已作废——R0 定「永不装 Linux」，改 MSYS2 纯 Windows 宿主，
    见 §3.2；riscv-tests 的构建走 ucrt64 `riscv64-unknown-elf-gcc`，见 `doc/环境搭建.md`）；
    环境事实单源＝`state/env.json`（`env-facts-consistency` 对账）。
  - 实现期已落（2026-09-25 首批）：`rtl/vr1/include/vr1_pkg.sv`（参数件/类型件**包裹式** `include，
    生成件禁手改）＋ `rtl/vr1/core/vr1_core.sv`（G1-I 冻结端口面 ＋ 取指骨架，未完成项标 `TODO(M1-S<n>)`）
    ＋ `filelist/rtl.f`。
  - 规格侧：`doc/spec/` 00~14 全 15 篇在册（00 待评审；01/02/03 已收口；04~14 已起稿）；
    **G1-I 已签**；G1-F（全量冻结）前置余项＝`spec/00` 过 RR／04~13 余项 T-xx 清零或列缺带归属／
    `spec/10` T-10-1（CSR 全表）闭合。
  - 环境：**纯 Windows 全链已就位（2026-09-25，R-235；R0 定「永不装 Linux」⇒ WSL2 路线作废）**：
    MSYS2 装于 `D:\msys64`（msys 环境 gcc/make/git/dtc；ucrt64 环境 `riscv64-unknown-elf-gcc` 16.1.0
    ＋binutils 2.47＋Verilator 5.050＋gcc 16.2.0＋dtc＋boost）；**Spike 自建成功**（`/d/tools`，
    Spike 1.1.1-dev，含 `--log-commits`；调用须带 `--dtb=`，补丁与三条限制见 ISS-123）；证据
    `sim/run_env_msys2/run.log`；步骤与坑见 `doc/环境搭建.md`。**ISS-vs-ISS 对手方口径**（用哪一份 Spike）
    ＝ `doc/verify/02` §8：`--preset project`（**改过的 oracle、非原版**；改动面固化成补丁件
    `iss/tools/patches/spike-vr1-platform-map.patch` ＋ 版本指纹 `iss/tools/spike_oracles.json`，由
    `iss/tools/spike_run.py` 每次核 md5、不符即拒跑；ISS-129 已按 R0 裁定②闭合）。`_tools/` 可达（ISS-032 闭）、
    git 可用（MSYS2 侧 2.55.0）。ModelSim license 见 R-224（ISS-104 的 OS 侧 rehost 仍待人）。
  - 台账 102 条历史（`doc/process/00`，归档不再续写）→ 现行台账 `doc/process/ledger.json`
    （由 `flow.py record` 自增编号；`flow.py board` 看计数）。
- **基线状态**：**未基线**（机判真值＝`state/freeze.json` 的 `baseline` 字段）
  - 基线触发点预告（满足其一即可由人宣布）：① Review G1 接口冻结签署（**分段签口径**：以 **G1-F 全量
    冻结**为准——G1-I 已签只解锁实现期，不构成基线触发，见 G1-I 清单 §6.1 段 0/段 3）；② UVM 平台
    smoke 用例通过。二者取先。基线后 `rtl/` 转只读、平台改动走 R5。
- **工作流规则**：**现行执行层 SSOT ＝ `doc/process/03-自动化流程重构-三方案.md`（方案 A）**，
  日常命令只有 `script/flow.py`；项目级流程定义（阶段/门禁/度量/管理）见 **`doc/项目开发流程.md`**（保留为阶段语义术语表）；
  AI 角色分工与独立性机制（**R0~R8**、读写边界、对抗评审、核销）见 **`doc/AI角色与职责.md`**；
  执行层九步流水线见 `D:\IC验证知识库\AI验证工作流程\AI验证工作流程.md`（库已于 2026-09-22 改名，
  冲突时以项目流程文件为准）；阶段门与角色总纲见同库 `AI进行IC开发验证工作流程\`（含 §6.1 评审收敛判据）。
- **知识库路由**：每次会话先读 `D:\IC验证知识库\AI索引.md`；SV 语义争议查《SV标准LRM知识库》；
  1800-2023 新特性（`soft` 约束 / `tagged union` / `$assertcontrol` / `default disable iff`）
  按《SV标准1800-2023差异知识库》逐条规避（ModelSim SE 2020.4 覆盖度所限）。

## 2. 目录约定

```
virtual_riscv/
├── AGENTS.md          # 本文件
├── .zcode/config.json # 流程 A 的三个 hook（Stop / SessionStart / PreToolUse）；改后需重开会话生效
├── state/flow.json    # ★ 状态唯一真值（里程碑/exit 判据/步骤/证据）；flow.py next 是唯一权威顺序
├── tools/vr1-plugin/  # 本地插件：agents/*.md 五个角色（auditor 无 Bash/Write/Edit，机械只读）
├── doc/               # 项目开发流程.md（阶段/门禁/度量/管理，术语表）/ AI角色与职责.md
│   │                  # 环境搭建.md / 交接说明.md / 当前目标卡.md（治理类留顶层；末件＝流程 A 的人类可读镜像）
│   │                  # _legacy/2026-09-25-流程v1/（自动推进说明 / 派发词模板 / 自动循环定时任务 / flow_run.py）
│   ├── spec/          # ★ 规格书 00~14（设计承诺，本项目第一阶段主体交付）
│   ├── design/        # 设计侧非规格产物（ADR 汇总 / 接口冻结记录 / 模块实现说明；预留）
│   ├── verify/        # 验证产物 01-理解清单 ~ 10-基线记录（九步流水线；04/05 现行，03 已退役留档）
│   ├── review/        # 评审记录与评审探针（按篇目编号：01-评审记录.md / 01-评审探针/）
│   └── process/       # ledger.json（★ 现行台账，编号自增）/ 00-问题记录.md（历史归档）/ 01~03 方案与流程件
├── debug/             # debug 分析文档（七段骨架，见《问题分析方法论》§4A）
├── rtl/vr1/           # DUT：frontend/ rename/ issue/ exu/ lsu/ mmu/ cache/ ctrl/ core/ include/
├── tb/vr1_uvm/        # UVM 平台与用例（AI 工作区）
├── iss/               # Python golden ISS（vriss）+ tools/ trace 归一化与比对
├── sw/                # env/（link.ld、crt0、启动码）+ tests/（定向与 riscv-tests/arch-test 接入）
├── filelist/          # rtl.f / tb.f / rv64gc.core.f
├── sim/               # 编译仿真工作目录（可清理）
│   └── covdb/         # ★ 签核证据受保护区：合并覆盖率 ucdb + 编译指纹，clean 不得触碰
├── script/            # 构建/解析脚本；tools/ 归档工具（`window` 加固探针／清理前引用扫描／文件速查）；script/tmp/ 临时件用完即删
└── run_cmd/           # Makefile、vsim 入口 do/tcl、回归 runner、riscv-dv target 配置
```

## 3. 工具链命令（AI 直接执行并解析输出）

### 3.1 Windows / ModelSim SE-64 2020.4（UVM + 覆盖率 + 签核）

```batch
:: 绝对路径，避免 PATH 依赖
set MTI=D:\modeltech64_2020.4\win64

:: 建库并映射预编译 UVM 1.2（安装目录已带 uvm-1.2\win64 编译库）
%MTI%\vlib  work
%MTI%\vmap   work work
%MTI%\vmap  mtiUvm D:/modeltech64_2020.4/uvm-1.2

:: 编译（覆盖率开关编译期就要带：-cvgexpr -cvgseq 按项选择）
:: **实测更正（D-7/ISS-054）：本机 vlog 不支持 -ntb_opts（vlog-1902）⇒ 用 +incdir；编译判据=产物证据行（-- Compiling 计数+段末 Errors: N，ADR-5）**
%MTI%\vlog -64 -sv -cover bcesf +incdir+%MTI%/../verilog_src/uvm-1.2/src -f filelist/tb.f -l sim\vlog_compile.log

:: 优化 + 批仿真（命令行模式，必带超时与 log）
%MTI%\vopt -64 -cover=bcesf work.vr1_top_tb -o work_opt
%MTI%\vsim  -64 -c -coverage -do "run -all; quit -f" -l sim\case.log work_opt

:: 覆盖率：逐用例 ucdb 不可相加，必须批级合并后再判定
%MTI%\vcover merge -out sim/covdb/<batch>.ucdb sim/ucdb/*.ucdb
%MTI%\vcover report -cvg -detail sim/covdb/<batch>.ucdb -output doc/verify/07-<batch>.txt
```

### 3.2 MSYS2（纯 Windows；编译 / ISS 互检 / 高速仿真）—— 已就位，命令见 `doc/环境搭建.md`

> **两套环境别混用**：`ucrt64`（原生 Windows，装 riscv 交叉工具链／Verilator／dtc／原生 gcc）与
> `msys`（Cygwin-POSIX 层，装 git/make/dtc 并**承载 Spike 的编译与运行**——它要 mmap/termios/fork）。
> 脚本调用式：`D:\msys64\usr\bin\env.exe MSYSTEM=UCRT64 D:\msys64\usr\bin\bash.exe -lc "<cmd>"`。

```bash
riscv64-unknown-elf-gcc -static -mcmodel=medany -nostdlib -nostartfiles \
    -march=rv64imac_zicsr_zifencei -mabi=lp64 -T sw/env/link.ld <in>.S -o <out>.o
riscv64-unknown-elf-objcopy -O binary <out>.o <out>.bin
spike --isa=rv64imac_zicsr_zifencei --priv=m -l --log-commits \
      --dtb=<file.dtb> <out>.o     # 本机自建版：--dtb 必须带（ISS-123②）；commitlog 已默认编入
verilator --cc --exe --build -j 4 --trace-fst -CFLAGS -O2 -f filelist/rtl.f          # 长跑回归与性能
```

> **口径提醒（doc/process/00 ISS-010）**：一期 `MISALIGNED_EN=0`——硬件不支持非对齐访存，
> 因此 Spike **不得带 `--misaligned`**；两侧口径必须一致，否则非对齐激励会伪装成 DUT bug。

### 3.3 激励生成（riscv-dv，本地副本）

- 生成器根：`D:\IC验证知识库\_tools\riscv-dv-master`（`simulator.yaml` **无 ModelSim 条目**，
  需自加 `modelsim` 条或走 `pygen` 纯 Python 路线；已登记 doc/process/00 ISS-004）。
- target：`run_cmd/riscv_dv_target/rv64gc_vr1/`（`riscv_core_setting.sv` 逐字段照 `doc/spec/00` 参数表填）。

### 3.4 已知工具坑位

1. ModelSim SE 的 DPI-C 需要宿主 C++ 编译器——本机现有 MSYS2 的 gcc，但**口径不变：ISS 一律走文件级解耦**
   （不做 DPI 耦合）：跨工具链 ABI 与可复现性风险仍在，且解耦后 trace 可比对、可留证（ISS-006 的理由更新）。
   Spike/ISS 与 RTL 一律只交换落盘文件（`.hex`／trace CSV）。
2. `.bin`/`.hex` 镜像必须"一份产物喂两边"（ISS 与 RTL 存储器），否则两侧镜像漂移会伪装成 DUT bug。
3. `vcover merge` 的合并集仅限同一编译版本 → covdb 目录必须记**编译指纹**（RTL 版本 + filelist hash）。
4. PowerShell 不支持 `&&`，脚本一律用 `;` 或走 `cmd /c` / MSYS2 bash。

## 4. 验证签核标准（Step 5~8 循环终止条件）

**判定口径与阈值以本节为准，工具自报百分比不作判定源。**

| 项 | 阈值 | 口径 |
|---|---|---|
| 功能覆盖率 | **100%** | `doc/verify/02-验证点清单.md` 中每条覆盖率项，批级合并后 Σhits/Σ目标 bins |
| 代码覆盖率 | **≥ 90%** | `vcover report` 的 Statements / Branches / Conditions / FSMs **逐项**；waiver 从分母扣除且逐条人批 |
| 回归 | **0 UVM_ERROR / 0 UVM_FATAL** | 全部用例通过；稳定性 ≥ **2** 轮同配置 0 新 FAIL |
| 一致性 | ISS-vs-ISS + RTL-vs-ISS | 逐指令 trace 比对 0 mismatch；`compare_final_value_only` 仅按 testlist 白名单启用 |
| 合规 | riscv-tests rv64ui/um/ua/uc **100%**；riscv-arch-test **≥ 95%** | arch-test 作 ~70% 起点（《标准协议验证经验》口径） |
| 缺陷 | `doc/verify/06` 每条闭环 | 修复复验通过或有明确处置结论 |
| 台账 | `doc/process/00` 无「待决策/处理中」残留 | 已解决条目均回填【已解决】+ 时间 + 方案摘要 |

**循环时间盒（SMART 之 T）**

- 每个 Step 时间盒 **10 工作日**；单项挂起超 **3 工作日** 触发 R2 停止并报告。
- 连续 **3 轮**覆盖率无增量 → 按 R2 停下汇报，不许空转烧机器。

## 5. 工作规则（AI 必须遵守，前 10 条为红线约束，优先级最高）

### 5.1 本项目对 R1 的口径细化（设计期 vs 验证期）

红线 R1「rtl/ 只读」在**基线前**按如下口径执行，不得自行放宽：

- **规格与接口冻结（Review G1）之前**：`rtl/vr1/**` 是**设计产出物**，AI 可在人的明确指令下编写，
  每次改动必须输出 diff 摘要并登记 `doc/process/00`（分类=文档/流程按实际归类）。
- **Review G1 签署接口冻结之后**：`rtl/` 立即转为**只读**（回归为纯验证活动）；发现疑似设计缺陷
  只输出缺陷记录（`doc/process/00` 分类=代码 + 独立缺陷单），停止报告，**修复 RTL 永远是人在人明确指令下
  的单独动作，不属于验证流水线**。
- **基线（= G1 与 Step4 smoke 通过二者取先）之后**：任何 `rtl/` 或 `tb/` 改动一律先分析报告待批（R5）。

### 5.2 二十四条规则（前 10 条为红线约束；标题原写「十八条」与实际条数不符，2026-09-23 校正为「二十三条」，2026-09-24 增规则 24 后为「二十四条」）

1. **【红线 R1】DUT 不动**：口径见 §5.1；冻结/基线后任何情况不自动修改 `rtl/`，疑似设计问题只记录。
2. **【红线 R2】问题处置分级**：基线前——平台/验证代码问题（编译错误、脚本、checker 自身错误）
   **直接解决无需停止**，但必须记 `doc/process/00`；**设计/规格类问题**（`doc/spec/` 的取舍与缺陷）按
   2026-09-23 口径（`doc/项目开发流程.md` §12.2/§12.3）**由决策 AI 自决并留 ADR，不停止主线**；
   仅**放宽/判定口径类、无复核手段的✅陈述、环境权限类**停止自动验证、输出问题报告、等待决策。
   基线后——按 R5。
3. **【红线 R3】过程可追溯**：每步产出落盘 `doc/verify/01~10`；执行的命令、随机种子、结果全记 `doc/verify/05`；
   任何结论可回溯到具体 log 行 / 波形时刻 / 代码行，"口头结论"不算完成。
4. **【红线 R4】问题闭环**：五类（平台/代码/文档/流程/验证代码）发现即登记 `doc/process/00`；解决后在
   **原条目**回填【已解决】+ 时间 + 方案摘要；Sign-off 前台账必须全闭环。
5. **【红线 R5】基线后先批后改**：平台/RTL 改动 → 分析影响 → 输出改动报告（改什么/为什么/影响面/
   需回归范围）→ 等批准 → 才动手。批准的修改验证中，平台问题直接修（记录照做），其他问题停止报告。
6. **【红线 R6】禁止改检查器让结果通过**：禁止放宽 scoreboard 容差、注释/删除断言、降级 ERROR、
   弱化约束。`compare_final_value_only` 之类的比对放宽**只能按 testlist 白名单启用，每次启用记 doc/process/00**。
7. **【红线 R7】禁止刷覆盖率**：waiver/exclude_bins 逐条附理由并经人批；禁删 bins、改采样条件、
   加无意义 cover 抬数。
8. **【红线 R8】通过判定必须有显式证据**：trace 比对通过 / 断言通过 / 覆盖率采样命中至少其一；
   "仿真跑完没 error" 不作判据。
9. **【红线 R9】仿真必须带超时**：单用例 watchdog **2,000,000 拍**（功能比对类）；ModelSim 挂钟上限
   **20 分钟/用例**；AI 自主连续仿真**单轮总时长上限 2 小时**；回归批累计上限 **6 小时**。超时按 R2。
10. **【红线 R10】资源并发上限**：回归并发 **≤ 4**，不得为提速擅自提高。**并发额度与沙箱互斥是两回事**
    ——每套 runner 必须独占 `sim/run_<runner_id>/` 沙箱，否则互抢致 FAIL_ENV（2026-09-19 XDH 实测教训）。
    回归终止判据：AB1 连续 ≥2 例编译/加载失败 → 批中止；AB5 完成 ≥5 例且 UVM_FATAL 占比 ≥10% → 批中止；
    AB6 单用例 watchdog 超时或批累计超 R9 上限 → 批中止。中止时已跑结果保留有效，summary 尾行标
    `REGRESSION_ABORTED + 原因`，退出码非 0，判据号记 `doc/verify/05`。
    **旧名对照（F5 改名，2026-09-23，见 `doc/verify/05` R-049）**：批中止判据旧名 `T1`/`T5`/`T6` → 新名 `AB1`/`AB5`/`AB6`（翻选触发族见 `spec/01` `PT1`/`PT2`；`spec/02` `T-n` 族不变）。
11. **产出落盘（流程 A 口径）**：状态写 `state/flow.json`（唯一真值，脚本维护）；每个确定性步骤的命令与
    证据入 `sim/run_<step_id>/run.log`；台账编号由 `python script/flow.py record` 自增（**禁手写**）。
    **不再手写 R/ISS/Q/D/S 编号，不再有"每片记录批四件套"**；会话结束前更新本文件 §1「验证阶段」指针
    与 `doc/当前目标卡.md`（里程碑切换时刷新）。
12. **知识库路由**：语法/机制/工程写法有争议先查 `AI索引.md` 定位，结论注明出处（库名/文件/卡片号）；
    SV 语义以《SV标准LRM知识库》仲裁。
13. **diff 可见**：每次代码改动输出修改点摘要，禁止静默重写已有组件。
14. **检查器严审**：scoreboard 比对逻辑与 SVA 断言的新增/修改，必须先展示设计思路待确认。
15. **种子管理**：所有随机种子记 `doc/verify/05`；随机失败先用同种子复现再修，修复后先复验出错种子再进回归。
16. **循环纪律**：Step 5~8 未达 §4 标准必须继续循环；循环中按 R2 分级处置；连续 3 轮无进展停下汇报。
17. **纪律补充**：三同步（验证点清单-用例-文档映射同步更新，禁两张皮）；规格升版必重过 Requirement
    Review；force/backdoor 只用于调试定位，正式判定必须前门 + 显式检查；**禁止顺手重构无关代码**
    （无关问题只记 doc/process/00）；检查器真实 bug 修复也须登记说明。
18. **不跳步**：跳过工作流任何验收标准前必须显式说明并征得同意。
19. **【角色边界】每活动只有一个 A，跨角色只读**：详见 `doc/AI角色与职责.md` §2/§3。
    不得代写他人职责范围内的产物；对抗评审子代理（R7）不得读作者当轮上下文、不得下“通过”结论。
20. **【外部锚点】关键结论必须绑锚点**：规范原文 / Spike / 参考实现（picorv32、ibex、cv32e40p）/
    可证伪实验 / 工具自报数，至少选一个并写入正文；只有“我推导/我认为”的一律标 `待锚点`，
    审计角色不得勾销（对应红线 R8 与《AI验证工作流》检查点 1 的三方回顾补偿）。
    **2026-09-23 起本条同时是"AI 自决的交换条件"**：设计类取舍**无锚点者不得记"已定"**，
    只能降级为"登记＋预测＋回退点"，并进 `doc/项目开发流程.md` §9.5 评审 list 的 ④ 段供人读。
21. **【独立性声明】同模型多角色共享盲点**：不得把“换了个角色评审”当独立性证据；
    残余风险由 R0 人签署 + 锚点兜底。
22. **【角色边界机械化】写禁令不靠声明**：子代理声称"只读"时以**工具白名单**为准
    （`tools/vr1-plugin/agents/*.md` 的 `tools:` 字段；`vr1-auditor` 无 `Bash/Write/Edit` ⇒ 机械只读）。
    只读轮/处置轮收工必须跑**内容指纹窗口**核查：`python script/flow.py window`（md5:size；新增/删除恒计入；
    纯 mtime 差不作改动判据）；**评审探针与输出必须归入受版本控制的证据目录**
    （`iss/tests/probes/`、`doc/review/*-评审探针/`），不得留在忽略区；
    窗口基线折入只走 `python script/flow.py window --take --reason <折入集出处>`，每轮 ≤1 次，
    **作不出出处即作废回滚**。此外，**写操作要经 `PreToolUse` hook 复核**（`guard-write` 拒绝冻结后写 `rtl/**`、
    拒绝写 `sim/covdb/**`；`guard-bash` 拦 `rm -rf`/`git reset --hard` 等破坏性命令）。

23. **【编排与机械核销（流程 A）】** 日常只有一条命令：`python script/flow.py check`——
    判据只判产品（参数零漂移／表体全覆盖／表内自洽／vlog 编译／镜像 md5／trace 比对）加两条常跑守卫
    （台账结构、RA 号越界），**0 FAIL 才算过**；`python script/flow.py next` 给出唯一权威顺序
    （取代旧队列制与分层计划制）。**"已落实"只认脚本产出**：步骤 `status=done` 必须带 `evidence`
    （由 `flow.py run` 自动写），不认口头与转述。**硬停机**：撞 `doc/项目开发流程.md` §12.1 的 P1~P4、
    §12.3 必报三类（放宽比对/waiver/改检查器；无复核手段的 ✅ 陈述；环境权限）、红线 R9/R10 资源上限时，
    一律停下并出 ≤5 条选项决策包呈人，**不得自决、不得默认通过**（知识库 RA1/RA3）。
    **编排不接管任何角色的 A**；关键节点（签署/冻结/基线）永远是人。
24. **【开工即自动推进（流程 A）】** 会话第一件事就是继续循环，不等指令：
    ①**开工三步**：读本文件 §0 与 `doc/当前目标卡.md` → `python script/flow.py check`（有 FAIL 先修/即报）
    → `python script/flow.py next`（下一步＋需人项＋阻塞；**工作顺序以它为准**）；
    ②**循环**：`python script/flow.py run`（确定性步骤；PASS 只认证据行，FAIL 读 `sim/run_<id>/run.log` 处置）
    → 需实现/判断时派子代理（**审计与决策＝独立子代理；计划/开发/验证＝本体**，短派发词 ≤40 行）
    → 收工即查 `python script/flow.py window` → 记账由脚本完成 → 取下一切片；
    **【落文即派审】**：每批落文后自动派 `vr1-auditor` 只读复核片（复核面＝本批改动集；有阻塞不得置 done，
    先处置再复核）；**禁止把复核攒到"收口"再补**；
    ③**遇待决项**：设计/规格类 → 派 `vr1-decider` 出 ADR（四要素）自决；判定口径/放宽/无复核手段/
    环境权限类 → 出决策包呈 R0；
    ④**停机条件（仅此四条）**：撞 §12.1 P1~P4 或 §12.3 必报／`flow.py next` 无待派步骤且只剩需人项／
    同一门禁连续 3 次不过／R0 叫停；
    ⑤**默认不请示、不得中途停**（`doc/项目开发流程.md` §12.2）：凡未撞 ④ 就连续执行，不得以
    "汇报进展/询问是否继续"结束本轮；停下时必须写明"因撞【哪条停机条件】而停"。
    **循环由系统件承载**：`.zcode/config.json` 的 `Stop` hook 在有可跑步骤时请求继续、
    `SessionStart` 在压缩/续跑后强制重注入状态与禁令——**不再依赖定时任务（已证伪）或人不断说话**。

> **红线记号（RA 系列）说明**（2026-09-23 加，登记 `doc/process/00` ISS-048）：RA 系列出自知识库
> 《AI进行IC开发验证工作流程》§8，**只有 RA1~RA4 四条**——RA1 自治决策不进入关键节点／
> RA2 升级须走完 L1+L2 并留痕／RA3 默认策略只许用于非破坏可回退事项（不可回退事项必须等人
> 明确选择）／RA4 审计发现不得删除。**本项目不新设额外的 RA 红线**（2026-09-23 R0 决定：
> 知识库只到 RA4，凡此前出现的"第五条 RA"类引用**已全部移除**；其实质由 **RA1、RA3** 与本文件
> 规则 23「不得默认通过」、`doc/项目开发流程.md` §12.4 尾注承载）。草拟新自治/审计红线时，
> **先在本节登记编号与条文，再引用**；规则承载件引用未定义 RA 编号由 `flow.py check` 的
> `ra-token-defined` 判据拦截（继承退役的 `gate.py`，判据名保持不变）。知识库只读：如需在库内补条文，
> 须人明确指令＋双确认＋留痕。

**权威原则补充（本项目特有）**：`doc/spec/` 是设计意图权威源。发现 spec 与 RTL/ISS 行为不一致 →
登记差异反馈包 → 交人裁决/修订 spec → spec 回归权威后闭环。差异未决的过渡期内可以 RTL 为行为真值，
但必须显式标注为**过渡态临时裁定**，不得上升为通则。

`debug/` 下的问题定位/移交/取证文档按《问题分析方法论》§4A 七段骨架书写
（`D:\IC验证知识库\问题分析方法论\问题分析方法论.md`）。
