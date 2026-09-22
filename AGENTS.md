# VR1 项目 AI 协作指令（AGENTS.md）

> 本文件由 `D:\IC验证知识库\项目AGENTS模板\项目AGENTS模板.md` 复制填写而来。
> AI 进入项目会话先读本文件，再按 §5 规则与《AI验证工作流程》九步流水线工作。

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
    ⚠ **2026-09-23 实测：`_tools\` 整目录在本机不存在（换机漏拷，见 ISS-032）**——上述两个路径与
    §3.3 的 riscv-dv、§4 参考核源码均不可达；恢复前，`doc/spec/` 内所有【权】§号引用一律标
    `待锚点`，**不得当作已锚定结论参与 Review G1 冻结判定**（红线 R20）。
  - 设计空间与选型依据：`D:\IC验证知识库\Verilog与CPU设计知识库\CPU卷\04-高性能超标量CPU精读.md`
- **验证阶段**（AI 每次会话结束前更新此项）：
  **Step 1 理解规格**（进行中——spec 为自产文档，`doc/01` 以 `doc/spec/` 已定稿篇目为输入滚动生成；
  `doc/spec/` 已成 2/14 篇）
  **2026-09-22 的“已暂停/待换机”状态已失效**：工程已在新机继续，知识库 md 笔记可用，
  但 `_tools/` 漏拷（ISS-032）；工具链与 git 仍未装（ISS-001/002）。**当前权威进度看 `doc/04` 看板**，
  待办与阻塞由 `run_cmd/AutoQueue.yaml` + `script/gate.py` 驱动（规则 23）。
- **基线状态**：**未基线**
  - 基线触发点预告（满足其一即可由人宣布）：① Review G1 接口冻结签署；② UVM 平台 smoke 用例通过。
    二者取先。基线后 `rtl/` 转只读、平台改动走 R5。
- **工作流规则**：项目级流程定义（阶段/门禁/度量/管理）见 **`doc/项目开发流程.md`**；
  AI 角色分工与独立性机制（**R0~R8**、读写边界、对抗评审、编排与核销）见 **`doc/AI角色与职责.md`**；
  执行层九步流水线见 `D:\IC验证知识库\AI验证工作流程\AI验证工作流程.md`（库已于 2026-09-22 改名，
  冲突时以项目流程文件为准）；阶段门与角色总纲见同库 `AI进行IC开发验证工作流程\`（含 §6.1 评审收敛判据）。
- **知识库路由**：每次会话先读 `D:\IC验证知识库\AI索引.md`；SV 语义争议查《SV标准LRM知识库》；
  1800-2023 新特性（`soft` 约束 / `tagged union` / `$assertcontrol` / `default disable iff`）
  按《SV标准1800-2023差异知识库》逐条规避（ModelSim SE 2020.4 覆盖度所限）。

## 2. 目录约定

```
virtual_riscv/
├── AGENTS.md          # 本文件
├── doc/               # 00-问题记录 / 01-理解清单 / 02-验证点清单 / 03-验证计划 / 04-验证进度
│   │                  # 05-回归记录 / 06-缺陷归因 / 07-覆盖率报告 / 08-验证报告
│   │                  # 09-一致性与收敛检查 / 10-基线记录 / 环境搭建.md / 交接说明.md
│   │                  # 项目开发流程.md（阶段/门禁/度量/管理，本表上位约束）
│   └── spec/          # ★ 规格书 00~14（本项目第一阶段主体交付）
├── debug/             # debug 分析文档（七段骨架，见《问题分析方法论》§4A）
├── rtl/vr1/           # DUT：frontend/ rename/ issue/ exu/ lsu/ mmu/ cache/ ctrl/ core/ include/
├── tb/vr1_uvm/        # UVM 平台与用例（AI 工作区）
├── iss/               # Python golden ISS（vriss）+ tools/ trace 归一化与比对
├── sw/                # env/（link.ld、crt0、启动码）+ tests/（定向与 riscv-tests/arch-test 接入）
├── filelist/          # rtl.f / tb.f / rv64gc.core.f
├── sim/               # 编译仿真工作目录（可清理）
│   └── covdb/         # ★ 签核证据受保护区：合并覆盖率 ucdb + 编译指纹，clean 不得触碰
├── script/            # 构建/解析脚本；script/tmp/ 临时件用完即删
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
%MTI%\vlog -64 -sv -cover bcesf -ntb_opts uvm-1.2 -f filelist/filelist.f -l sim\vlog_compile.log

:: 优化 + 批仿真（命令行模式，必带超时与 log）
%MTI%\vopt -64 -cover=bcesf work.vr1_top_tb -o work_opt
%MTI%\vsim  -64 -c -coverage -do "run -all; quit -f" -l sim\case.log work_opt

:: 覆盖率：逐用例 ucdb 不可相加，必须批级合并后再判定
%MTI%\vcover merge -out sim/covdb/<batch>.ucdb sim/ucdb/*.ucdb
%MTI%\vcover report -cvg -detail sim/covdb/<batch>.ucdb -output doc/07-<batch>.txt
```

### 3.2 WSL2 Ubuntu（编译 / ISS 互检 / 高速仿真）—— 尚未安装，命令见 `doc/环境搭建.md`

```bash
riscv64-unknown-elf-gcc -static -mcmodel=medany -nostdlib -nostartfiles \
    -march=rv64imac_zicsr_zifencei -mabi=lp64 -T sw/env/link.ld <in>.S -o <out>.o
riscv64-unknown-elf-objcopy -O binary <out>.o <out>.bin
spike --log-commits --isa=rv64imac_zicsr_zifencei --priv=m -l <out>.o   # 需带 --enable-commitlog 编译
verilator --cc --exe --build -j 4 --trace-fst -CFLAGS -O2 -f filelist/rtl.f          # 长跑回归与性能
```

> **口径提醒（doc/00 ISS-010）**：一期 `MISALIGNED_EN=0`——硬件不支持非对齐访存，
> 因此 Spike **不得带 `--misaligned`**；两侧口径必须一致，否则非对齐激励会伪装成 DUT bug。

### 3.3 激励生成（riscv-dv，本地副本）

- 生成器根：`D:\IC验证知识库\_tools\riscv-dv-master`（`simulator.yaml` **无 ModelSim 条目**，
  需自加 `modelsim` 条或走 `pygen` 纯 Python 路线；已登记 doc/00 ISS-004）。
- target：`run_cmd/riscv_dv_target/rv64gc_vr1/`（`riscv_core_setting.sv` 逐字段照 `doc/spec/00` 参数表填）。

### 3.4 已知工具坑位

1. ModelSim SE 的 DPI-C 需要宿主 C++ 编译器（本机无 gcc/VS）→ **ISS 一律走文件级解耦**，不做 DPI 耦合。
2. `.bin`/`.hex` 镜像必须"一份产物喂两边"（ISS 与 RTL 存储器），否则两侧镜像漂移会伪装成 DUT bug。
3. `vcover merge` 的合并集仅限同一编译版本 → covdb 目录必须记**编译指纹**（RTL 版本 + filelist hash）。
4. PowerShell 不支持 `&&`，脚本一律用 `;` 或走 `cmd /c` / WSL bash。

## 4. 验证签核标准（Step 5~8 循环终止条件）

**判定口径与阈值以本节为准，工具自报百分比不作判定源。**

| 项 | 阈值 | 口径 |
|---|---|---|
| 功能覆盖率 | **100%** | `doc/02-验证点清单.md` 中每条覆盖率项，批级合并后 Σhits/Σ目标 bins |
| 代码覆盖率 | **≥ 90%** | `vcover report` 的 Statements / Branches / Conditions / FSMs **逐项**；waiver 从分母扣除且逐条人批 |
| 回归 | **0 UVM_ERROR / 0 UVM_FATAL** | 全部用例通过；稳定性 ≥ **2** 轮同配置 0 新 FAIL |
| 一致性 | ISS-vs-ISS + RTL-vs-ISS | 逐指令 trace 比对 0 mismatch；`compare_final_value_only` 仅按 testlist 白名单启用 |
| 合规 | riscv-tests rv64ui/um/ua/uc **100%**；riscv-arch-test **≥ 95%** | arch-test 作 ~70% 起点（《标准协议验证经验》口径） |
| 缺陷 | `doc/06` 每条闭环 | 修复复验通过或有明确处置结论 |
| 台账 | `doc/00` 无「待决策/处理中」残留 | 已解决条目均回填【已解决】+ 时间 + 方案摘要 |

**循环时间盒（SMART 之 T）**

- 每个 Step 时间盒 **10 工作日**；单项挂起超 **3 工作日** 触发 R2 停止并报告。
- 连续 **3 轮**覆盖率无增量 → 按 R2 停下汇报，不许空转烧机器。

## 5. 工作规则（AI 必须遵守，前 10 条为红线约束，优先级最高）

### 5.1 本项目对 R1 的口径细化（设计期 vs 验证期）

红线 R1「rtl/ 只读」在**基线前**按如下口径执行，不得自行放宽：

- **规格与接口冻结（Review G1）之前**：`rtl/vr1/**` 是**设计产出物**，AI 可在人的明确指令下编写，
  每次改动必须输出 diff 摘要并登记 `doc/00`（分类=文档/流程按实际归类）。
- **Review G1 签署接口冻结之后**：`rtl/` 立即转为**只读**（回归为纯验证活动）；发现疑似设计缺陷
  只输出缺陷记录（`doc/00` 分类=代码 + 独立缺陷单），停止报告，**修复 RTL 永远是人在人明确指令下
  的单独动作，不属于验证流水线**。
- **基线（= G1 与 Step4 smoke 通过二者取先）之后**：任何 `rtl/` 或 `tb/` 改动一律先分析报告待批（R5）。

### 5.2 二十三条规则（前 10 条为红线约束；标题原写「十八条」与实际条数不符，2026-09-23 校正）

1. **【红线 R1】DUT 不动**：口径见 §5.1；冻结/基线后任何情况不自动修改 `rtl/`，疑似设计问题只记录。
2. **【红线 R2】问题处置分级**：基线前——平台/验证代码问题（编译错误、脚本、checker 自身错误）
   **直接解决无需停止**，但必须记 `doc/00`；代码（设计）/文档/流程类问题——停止自动验证，
   输出问题报告，等待决策。基线后——按 R5。
3. **【红线 R3】过程可追溯**：每步产出落盘 `doc/01~10`；执行的命令、随机种子、结果全记 `doc/05`；
   任何结论可回溯到具体 log 行 / 波形时刻 / 代码行，"口头结论"不算完成。
4. **【红线 R4】问题闭环**：五类（平台/代码/文档/流程/验证代码）发现即登记 `doc/00`；解决后在
   **原条目**回填【已解决】+ 时间 + 方案摘要；Sign-off 前台账必须全闭环。
5. **【红线 R5】基线后先批后改**：平台/RTL 改动 → 分析影响 → 输出改动报告（改什么/为什么/影响面/
   需回归范围）→ 等批准 → 才动手。批准的修改验证中，平台问题直接修（记录照做），其他问题停止报告。
6. **【红线 R6】禁止改检查器让结果通过**：禁止放宽 scoreboard 容差、注释/删除断言、降级 ERROR、
   弱化约束。`compare_final_value_only` 之类的比对放宽**只能按 testlist 白名单启用，每次启用记 doc/00**。
7. **【红线 R7】禁止刷覆盖率**：waiver/exclude_bins 逐条附理由并经人批；禁删 bins、改采样条件、
   加无意义 cover 抬数。
8. **【红线 R8】通过判定必须有显式证据**：trace 比对通过 / 断言通过 / 覆盖率采样命中至少其一；
   "仿真跑完没 error" 不作判据。
9. **【红线 R9】仿真必须带超时**：单用例 watchdog **2,000,000 拍**（功能比对类）；ModelSim 挂钟上限
   **20 分钟/用例**；AI 自主连续仿真**单轮总时长上限 2 小时**；回归批累计上限 **6 小时**。超时按 R2。
10. **【红线 R10】资源并发上限**：回归并发 **≤ 4**，不得为提速擅自提高。**并发额度与沙箱互斥是两回事**
    ——每套 runner 必须独占 `sim/run_<runner_id>/` 沙箱，否则互抢致 FAIL_ENV（2026-09-19 XDH 实测教训）。
    回归终止判据：T1 连续 ≥2 例编译/加载失败 → 批中止；T5 完成 ≥5 例且 UVM_FATAL 占比 ≥10% → 批中止；
    T6 单用例 watchdog 超时或批累计超 R9 上限 → 批中止。中止时已跑结果保留有效，summary 尾行标
    `REGRESSION_ABORTED + 原因`，退出码非 0，判据号记 `doc/05`。
11. **产出落盘**：每步产出写 `doc/` 对应文件，下一步以上一步文件为输入；会话结束前更新本文件
    §1「验证阶段」与「基线状态」，并同步 `doc/04` 看板（事件驱动更新：状态变更即记 / 用户收尾指令 /
    里程碑完成 / 上下文压缩兜底）。
12. **知识库路由**：语法/机制/工程写法有争议先查 `AI索引.md` 定位，结论注明出处（库名/文件/卡片号）；
    SV 语义以《SV标准LRM知识库》仲裁。
13. **diff 可见**：每次代码改动输出修改点摘要，禁止静默重写已有组件。
14. **检查器严审**：scoreboard 比对逻辑与 SVA 断言的新增/修改，必须先展示设计思路待确认。
15. **种子管理**：所有随机种子记 `doc/05`；随机失败先用同种子复现再修，修复后先复验出错种子再进回归。
16. **循环纪律**：Step 5~8 未达 §4 标准必须继续循环；循环中按 R2 分级处置；连续 3 轮无进展停下汇报。
17. **纪律补充**：三同步（验证点清单-用例-文档映射同步更新，禁两张皮）；规格升版必重过 Requirement
    Review；force/backdoor 只用于调试定位，正式判定必须前门 + 显式检查；**禁止顺手重构无关代码**
    （无关问题只记 doc/00）；检查器真实 bug 修复也须登记说明。
18. **不跳步**：跳过工作流任何验收标准前必须显式说明并征得同意。
19. **【角色边界】每活动只有一个 A，跨角色只读**：详见 `doc/AI角色与职责.md` §2/§3。
    不得代写他人职责范围内的产物；对抗评审子代理（R7）不得读作者当轮上下文、不得下“通过”结论。
20. **【外部锚点】关键结论必须绑锚点**：规范原文 / Spike / 参考实现（picorv32、ibex、cv32e40p）/
    可证伪实验 / 工具自报数，至少选一个并写入正文；只有“我推导/我认为”的一律标 `待锚点`，
    审计角色不得勾销（对应红线 R8 与《AI验证工作流》检查点 1 的三方回顾补偿）。
21. **【独立性声明】同模型多角色共享盲点**：不得把“换了个角色评审”当独立性证据；
    残余风险由 R0 人签署 + 锚点兜底。
22. **【角色边界机械化】写禁令不靠声明**：子代理（R6/R7）声称“只读”时，每轮结束后必须跑
    “仓库清单比对 + mtime 窗口”核查并记入 `doc/05`；**评审探针与输出不得留在 `script/tmp/`
    等忽略区**，必须归入受版本控制的证据目录（`iss/tests/probes/`、`doc/spec/*-评审探针/`）。
    本轮已实测发生一次违反（34 个新建文件，无既有文件被改），见 ISS-022。

23. **【R8 编排与逐轮机械核销】** 项目设 **R8 项目编排 AI（PM）**，职责是按《AI进行IC开发验证工作流程》§1.3/§6.1 与本文件驱动阶段推进（角色边界见 `doc/AI角色与职责.md` §2/§3.1）：
    **每轮开工先跑 `python script/gate.py check`**（12 项机械不变式：台账计数与状态、ID 连续性、已解决项落点存否、
    看板镜像一致、队列 schema 与依赖、中文错词表等），**有 FAIL 即不得宣布任何「已落实」**；再 `dispatch` 取队首并按其
    `role` 字段切换角色执行；`done_when` 未满足不得置 done（不凭口头声明）。**硬停机**：撞 `doc/项目开发流程.md`
    §12.1 的 P1~P4、§12.3 四类必报项、评审 5 轮上限（§6.1）、红线 R9/R10 资源上限时，一律停下并用
    `escalate` 生成 ≤5 条选项决策包呈人，**不得自决、不得默认通过**（知识库红线 RA1/RA5；本文件规则 20 同源）。
    **R8 不接管任何角色的 A**，只写 `run_cmd/AutoQueue.yaml`、`doc/04` 状态列与台账镜像行、`doc/05` 调度留痕段；
    R8 自身受 R6 审计。设立依据与失效举证见 `doc/00` ISS-033。

**权威原则补充（本项目特有）**：`doc/spec/` 是设计意图权威源。发现 spec 与 RTL/ISS 行为不一致 →
登记差异反馈包 → 交人裁决/修订 spec → spec 回归权威后闭环。差异未决的过渡期内可以 RTL 为行为真值，
但必须显式标注为**过渡态临时裁定**，不得上升为通则。

`debug/` 下的问题定位/移交/取证文档按《问题分析方法论》§4A 七段骨架书写
（`D:\IC验证知识库\问题分析方法论\问题分析方法论.md`）。
