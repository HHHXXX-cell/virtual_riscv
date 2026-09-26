# ADR-P-2 接口字段切分与打包顺序（doc/decisions/ADR-P-2）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v1.0 | 2026-09-25 | 自决生效（决策 1、决策 2）／**决策 3 标「判定口径类，需 R0 确认」** | 首版：§1 四条通用切分规则（R1~R4）；§2 逐条切分表（29 行）；§3 机判自检（28/28）；§4 `AXI_OUTSTANDING` 口径；§5 `spec/12` §4 成熟度口径（待 R0）；§6 下游义务；§7 风险自评；§8 出口自检 |
| v1.1 | 2026-09-25 | 事后回写（**不改原结论**，只加「已落地」行） | 生成器（`script/flow.py`）已消费本表：§1 的 414 bit 缺口归零（28/28 差额 0、合计 4442 bit）、§3 的「不透明兜底 `rmap_uop_t`」被 39 个真实字段取代、**C4 恒等式判据退役**（职能交 `types-width-consistency`）、§4 下游义务清单标注「待落 `spec/00` §4 与 `spec/06`／`spec/09`」、§6 义务 1/2 标「已落地」 |

- **登记号**：`ADR-P-2`（编号分区见 `AGENTS.md` §0：`ADR-P-<n>` 为流程侧 ADR，`python script/flow.py record ADR` 自增，2026-09-25；**禁手写编号**；本件台账历史条目 id 为 `ADR-2`）。
  同批另有一条 `ADR-P-1` 补登记（2026-09-25；台账历史条目 id `ADR-1`）：`spec/01` §3 的字段打包顺序自决「表中自上而下＝MSB→LSB」，
  此前已被 `doc/process/ledger.json` 的 ISS-106① 与 `script/flow.py` 的 `PACK_ORDER_MSB_FIRST` 注释引用，
  但 `ledger.json` 的 `next.ADR` 仍为 1（即从未入台账）——本批把它补成 `ADR-P-1`，使后续编号不再与之相撞。
  本件沿用 `ADR-P-2`（与引用面一致），并**确认** ADR-P-1 的打包顺序约定（本件不另立第二种顺序）。
- **角色**：RD 决策 AI（`vr1-decider`，隶属 R1 判定面；方法依据 `doc/项目开发流程.md` §12.2）。
- **决策审核面**：按 §12.5 由审核 AI 一次独立审核（风险五类见 §7，供其逐条对撞）。
- **写边界声明**：本批**只写** `doc/decisions/**`（`ADR-P-2-接口字段切分与打包顺序.md`、`if_split.json`、
  `check_if_split.py`）＋经 `flow.py record` 写台账。**未改** `doc/spec/**`、`script/**`、`state/**`、`rtl/**`、`tb/**`
  （§4/§5 的下游义务均以"清单"形式交后续落文批执行）。
  **v1.1 事后回写批的边界另计**：只改 `script/flow.py`、生成件 `rtl/vr1/include/*.svh`、`doc/decisions/**`；
  **仍未改** `doc/spec/**`、`doc/verify/**`、`iss/**`、`tb/**`（O-1~O-3/O-5 因此只能标注"待落"）。

---

## 0. 检索留痕（红线 RA2：先 L1+L2 检索，后决策）

**L1（本机知识库与仓库）**

| # | 位置 | 取用内容 |
|---|---|---|
| L1-1 | `D:\IC验证知识库\AI索引.md` | 路由：§1.4《SV标准LRM知识库》＝唯一带条款号的语义仲裁源；§0 资源层《RTL设计资源知识库》＝协议/开源 IP 导读 |
| L1-2 | `_tools\extracted\lrm1800\c07_aggregate_types.txt` §7.2／§7.2.1（book p136→p99） | 「packed structure consists of bit fields, which are packed together in memory without gaps」「The **first member specified is the most significant** and subsequent members follow in decreasing significance」「Only packed data types and the integer data types … shall be legal in packed structures」「By default, structures are unpacked」 |
| L1-3 | `_tools\extracted\lrm2023\lrm2023_full.txt` 行 **39326**（Table 22-5，IEEE Std 1800-2009 additional reserved keywords） | `type` 自 **1800-2009** 起为保留字（同表 39320 `super`）；`grp` 不在表内 |
| L1-4 | `_tools\extracted\riscv_spec\riscv_spec_full.txt` 行 3961–3963 | 「An AMO or LR instruction **with aq set** … **with both aq and rl set** …」⇒ `aq`／`rl` 各 1 bit |
| L1-5 | `RTL设计资源知识库\协议规范导读\01-AMBA-AXI协议导读.md` | 五通道独立（AR/AW/W/B/R）；in-flight 定义＝「Ax 拍已握手、最后一拍响应尚未握手」；「master 侧 outstanding 深度＝系统设计参数」；「outstanding 超限」列为经典失效面，pulp 以 `axi_throttle` 限流作答 |
| L1-6 | `_tools\axi-master\src\axi_throttle.sv` 行 12–28 | 参考实现把未决上限**拆成两个参数**：`MaxNumAwPending`（写侧，由 B 兑现）与 `MaxNumArPending`（读侧，由 R 兑现），附带各自 credit 宽度 |
| L1-7 | `_tools\ibex-master\README.md` 行 45–47 ＋ `ibex_configs.yaml` | 配置成熟度色标的原始实践：「Verification status is a rough guide to the overall maturity of **a particular configuration**」；Amber＝已做部分验证但仍属 experimental；且**每个配置＝全参数向量**（同文件头注：each configuration must specify the same set of parameters） |
| L1-8 | `doc\项目开发流程.md` §6.3／§12.2／§12.3／§12.5／§9.4 | 配置空间治理（「哪些组合我验过」）；设计/规格类取舍由决策 AI 自决；**§12.3 第 2 行「任何 ✅/已核对 陈述无复核手段时」必须上报**；决策审核只问风险；两档制 |
| L1-9 | `doc\process\ledger.json`（ISS-018／ISS-020／ISS-106） | ISS-018＝作者自检表造假的位置；ISS-020＝可机判量一律入机判；ISS-106 五类问题（本件闭其②，并涉①③④） |
| L1-10 | `doc\spec\01-流水线与寄存器接口.md` | §2 类型表（`paddr_t`/`areg_t`/`lqidx_t`/`sqptr_t`/`va_t`/`csraddr_t`/`seq_t`）；§3.1~§3.21 的 28 个成员表与合计行；§3 各行原始文本（本件 §2 的「原文」列逐字取自各表"成员"列，见 `script/width_check.py` 的解析口径） |
| L1-11 | `doc\spec\00-总体规格.md` §4.7 L256／§4.8；`doc\spec\06` §4 L55 与 §6 L74；`doc\spec\09` §2 L27；`doc\spec\12` §2/§4；`run_cmd\vr1_configs.yaml` | `AXI_OUTSTANDING`＝`2R + 2W` 的三个引用点；色标 11 配置与 `params` 列；6 组现值 |
| L1-12 | `script\flow.py`（`render_types`／`types_member_split`／`PACK_ORDER_MSB_FIRST`／`SV_KEYWORDS`／`COUNTSUM_RE`／`chk_types_width_consistency`）、`script\width_check.py`（`member_width` 的 `[a:b]`／`log2`／加式口径）、`script\gate.py`（`md-integrity`／`ra-token-defined` 判据面） | 现状机判口径与生成器行为（生成件 `rtl/vr1/include/vr1_types.svh` 中 `type`→`type_f`、`super`→`super_f` 的既有约定） |

**L2（网络；仅作 L1 缺口的补充，二手来源已注明）**

| # | 检索式 | 结论（本件取用） |
|---|---|---|
| L2-1 | `SystemVerilog IEEE 1800 Annex B keyword list "type" reserved keyword` | 与 L1-3 一致：`type` 属 1800-2005/2009 起新增保留字，Annex B（normative）汇总裁定。命中 3 处交叉来源（ACL2 `*vl-2012-keywords*` 复刻 Table B-1／《RTL Modeling with SV》Table B-5／IEC 62530 互操作注），**均无可用 URL** ⇒ 本件以 L1-3（本机标准提取件）为一级依据，L2-1 仅作第二来源 |
| L2-2 | `AMBA AXI outstanding transactions counted separately read and write channels maximum outstanding` | 读/写**各自**有独立上限属性：Arm 定义「read issuing／read acceptance」与「write issuing／write acceptance」（另有 read data reordering depth／AXI3 write interleave depth）；Xilinx AXI Interconnect 以 `C_M_AXI_READ_ISSUING` 与 `C_M_AXI_WRITE_ISSUING` 分别参数化；Cortex-R5 实例＝7 outstanding reads／2 outstanding writes。**方向二分的上限是协议/互连层既有属性**，非本设计自造 |

> **无锚点声明（规则 20）**：`spec/00` §4.7 中 `2R + 2W` 的**数值本身**（＝2 与 2）在原文依据列只写「简单从端可支撑」，
> **未指名任何具体从端、文档或实测**——故本件**不把数值记为"已定"**，只记「登记＋预测＋回退点」（见 §4）。

---

## 1. 四条通用切分规则（覆盖 29 处非标量写法的全部形态）

**基线事实（可回查）**：`spec/01` §3 共 28 个 struct、327 个成员行；其中 **29 行**为非标量写法
（字段名不是合法 SV 标识符，或位宽列无法单值解析）——`script/width_check.py` 与 `script/flow.py types`
两处机判口径一致（`doc/process/ledger.json` ISS-106②）。29 行分布在 11 个 struct，
**当前生成件共缺 414 bit**（`ftq_entry_t` 143／`disp_x_t` 159／`br_resolve_t` 41／`rob_entry_t` 20／`uop_t` 14／
`commit_t` 13／`mem_req_t` 11／`rob_alloc_t` 7／`iq_wr_t` 4／`iq_entry_t` 2；`rmap_uop_t` 327 bit 由"不透明兜底类型"
临时覆盖故不在差额清单内，但其 10 行仍属 G1 须裁定的接口几何）。

> **事后回写（2026-09-25 修复批；原结论保留不改）**：上段「当前生成件共缺 414 bit」是**切分前**的基线事实。
> 生成器（`script/flow.py` 的 `render_types`／`types_member_split`）**已消费本表**把 29 处非标量行落成**真实字段声明**
> ⇒ **该 414 bit 缺口已归零**：28/28 struct 生成宽度 == `width_check` 独立复算（**差额 0**，合计 **4442 bit**，
> 判据 `types-width-consistency`）；`rmap_uop_t` 的「不透明兜底类型」已被 **39 个真实字段**
> （R2 复用 `uop_t` 的 31 ＋ 本表 #7~#14 的 8）取代。原文「当前」二字自此按**历史基线**读。

**打包顺序**：沿用 `ADR-P-1`（表中自上而下＝MSB→LSB），锚＝L1-2「first member specified is the most significant」；
本件所有切分行**不改变**行间相对顺序，只把一行拆成组内相邻的 k 个字段。

### R1 同行多字段（同一成员行以 `/` 并列 k 个名字）

- **选项与评估**：
  (a) **合并成一个字段**取总位宽（如 `rs1_rs2`＝10 bit）——与语义列相抵（§3.4 明写 `rs1`／`rs2` 是「两个独立架构源号」，`x0` 合法、可各自为 0），且 `iq_wr_t.psrc1/psrc2`、`disp_x_t.rs1_val/rs2_val` 等下游域按名对接，合并会造成"同一信息两种编码"（ISS-106 同型的双编码）⇒ 否。
  (b) **按"名字数 k ↔ 位宽列项数 k"逐项对应切分**（顺序＝名字从左到右 ↔ 位宽加式从左到右）——**不引入任何新数值**（位宽列已给出逐项加式），纯机械动作 ⇒ 取。
  (c) **退稿**（要求 `spec/01` 拆表重写）——把机械动作推回给人/后续批，而 G1 冻结在即、且切分不改变任何位量 ⇒ 否（但 §6 把"spec 是否加注"列为可选下游义务）。
  (d) **等分**——**仅当**位宽列是单个整数 N 且名字数 k 时使用（全篇仅 2 处：`uop_t.rs1_en/rs2_en`＝2、`uop_t.aq/rl`＝2；两名字语义列对称，等分是唯一自洽读法；N 不能被 k 整除者应 fail-closed 报 UNRESOLVED，本批未出现）。
- **选定**：(b) 为主，(d) 为 k 名字＋单整数宽的收窄情形。全篇 R1 行 **16 处**（其中 1 处为替换子例 `rmap_uop_t` L207），与 §2 表逐行可数。
- **外部锚点**：位宽列自带加式（`5+5`／`1+6`／`64+64`／`2+1+1+1+1`／`12+2`／`6+5`／`1+40`／`1+1`）＝**文档内锚**，与 `script/width_check.py` 的"数值求和"口径同式；`aq`／`rl` 各 1 bit＝L1-4（ISA 原文）；组内顺序＝L1-2（首成员为最高位）＋ADR-P-1。
- **回退点**：若 G1 改判组内顺序或某个配比，**只改 `if_split.json` 对应行的 `fields` 顺序/配比**并重生成生成件（一行级回退，不动 spec 正文）。

### R2 全字段复用（`＝ X`）

- **选项与评估**：
  (a) **嵌套成员** `ftq_req_t req;`——语法合法（`packed struct` 本身是 packed 类型，见 L1-2 第 3 句），位宽与"合计 143+1+1"一致；但**必须新造一个 spec 中不存在的成员名**（`req`？`ftq`？），字段访问路径变成 `e.req.pc`（§3 其余 27 个 struct 全平铺），**且 `rmap_uop_t` 的替换行（`rs1/rs2`→`psrc1/psrc2`）在嵌套形态下无法表达**（无法"部分替换"嵌套成员内部字段）⇒ 同一规则无法两用。
  (b) **逐字段展开（flatten）**——零新名、位宽/位序与 (a) 逐位等价（同 143 bit、同在 struct 高位端）、全篇风格一致、且可组合替换语义 ⇒ 取。
  (c) **维持现状（只登记）**——414 bit 缺口永久留在生成件里，G1 冻结的将是"宽度确定、切分未定"的接口（ISS-106 结论句）⇒ 否。
- **选定**：(b)。全篇仅 2 处 `＝ X` 行（`ftq_entry_t`＝`ftq_req_t`；`rmap_uop_t`＝`uop_t`），与 `width_check` 的 `baseline` 计数 2 一致。
- **外部锚点**：L1-2（packed struct 无间隙拼接＋首成员最高位⇒展开与嵌套逐位等价）；生成件实测（`ftq_entry_t` 只生成 2 bit 而声明 145 ⇒ 缺口 143 可复算）。
- **回退点**：若 G1 选 (a)，则改本表该行规则为"嵌套"＋生成器加嵌套分支；位宽不变，代价＝RTL 字段引用路径与断言全改（故不取）。
- **下游义务**：展开内容属**派生件**，`spec/01` §3.1／§3.4 变更时必须同批刷新本表——已入机判（`check_if_split.py` C5：展开序必须逐字段等于被复用 struct 的"解析字段序"，名字与位宽、顺序全等）。

### R3 增量行（`新增 X`）

- **选项与评估**：(a) 字段名＝`X`、宽度＝该行位宽列；(b) 并入上一行/基线；(c) 退稿。`新增` 是相对 `＝ X` 复用基线的**增量**语义（§3.5 合计行自带逐项加式 `239+2+5+6+6+1+2+1+1+64 = 327` ⇒ 每行都是独立加项）。(b) 会丢掉"该域是替换后重新携带"的沿革（如 `rs1_arch` 的 B1/L13 补入史），(c) 同 R1(c) ⇒ 选 (a)。
- **选定**：(a)。全篇 8 处（均在 `rmap_uop_t`）。
- **外部锚点**：该 8 行的位宽列（5/6/6/1/2/1/1/64）＋§3.5 合计行逐项加式（文档内锚，可复算到 327）。
- **回退点**：不引入新语义，无需回退；若 G1 判定某增量应并入基线，改本表一行即可。
- **下游义务**：8 个字段名的生产/消费链已在 §3.5／§3.8／§3.11 对齐（B1/L13、Q-036），本件不改名。

### R4 名带位区间（`name[a:b]`）

- **选项与评估**：
  (a) 字段名＝区间前的标识符、宽度＝`|a−b|+1`、声明保留区间（`logic [6:0] type_f;`）——位序知识留在区间里（§3.6 明写 bit0 `is_c` … bit6 `is_csr`），下游按位取用不变 ⇒ 取。
  (b) 把区间写进名字（`type_6_0`）——造出全篇唯一的命名体例，下游引用名变化而零收益 ⇒ 否。
  (c) 拆成 7 个 1 bit 字段——把"位序定死、逐位直连"的语义打散成 7 个名字，与 §3.6 的位序表相抵 ⇒ 否。
- **选定**：(a)。全篇 3 处：`rob_alloc_t.type[6:0]`、`rob_entry_t.type[6:0]`（宽 7，**逐位直连**故必须同名）、`iq_wr_t.grp[1:0]`（宽 2）。
  **保留字处理**：`type` 自 IEEE 1800-2009 起为保留字（L1-3 行 39326）⇒ 机械改名 `type_f`（沿用 `script/flow.py` 的 `SV_KEYWORDS`＋`_f` 后缀既有约定，与生成件中 `mmu_transl_rsp_t` 的 `super`→`super_f` 同例），
  生成件须以注释写明原名 `type`；`grp` 非保留字 ⇒ 名不变。
- **外部锚点**：L1-3（保留字表）；§6.9.1／§7.4.1 的位区间宽度定义（与 `width_check.member_width` 的 `[a:b]`→`|a−b|+1` 同式）。
- **回退点**：命名策略**集中在生成器一处**（`SV_KEYWORDS` 集合与 `_f` 后缀），G1 若改判（例：`typ`／`type_bits`）只改该处并重生成；本表 `rename` 字段已把 `from`/`to`/`why` 显式落盘，改名不触碰位量。
- **下游义务**：`type_f`（两处）与既有 `super_f` 命名口径一致；若 `spec/01` §3.6／§3.7 加注"生成期改名 `type_f`"，与本表同批。

---

## 2. 逐条切分表（29 行；原文逐字取自 `spec/01` §3 各表"成员"列）

| # | struct | 原文（字段列） | 切分后字段名与位宽 | 依据 |
|---|---|---|---|---|
| 1 | `ftq_entry_t` L137 | `= ftq_req_t`（全字段复用） | `valid`1 `pc`40 `nib`5 `br_vld`1 `br_type`2 `taken`1 `target`40 `ras_op`2 `ras_top`40 `pred_conf`2 `bp_upd_id`8 `bad_va`1（Σ143） | R2：展开＝§3.1 十二行原样（Σ143＝该行位宽列 143）；打包＝首成员最高位（ADR-P-1） |
| 2 | `uop_t` L172 | `rs1_en`/`rs2_en` | `rs1_en`1 `rs2_en`1 | R1(d)：位宽列＝单整数 2、名字数 2、语义列两名对称（「源存在标志」）⇒ 等分 |
| 3 | `uop_t` L173 | `rs1`/`rs2` | `rs1`5 `rs2`5 | R1：位宽列 `5+5` 两项 ↔ 两名按序；类型＝`areg_t`（§2 行 89，5 bit） |
| 4 | `uop_t` L183 | `aq`/`rl` | `aq`1 `rl`1 | R1：位宽列＝单整数 2、两名对称；且 `aq`／`rl` 各 1 bit（ISA 锚 L1-4） |
| 5 | `rmap_uop_t` L206 | `= uop_t`（全字段复用） | §3.4 全部 31 个字段（28 行拆分后）Σ239：`valid`1 `pc`40 `raw32`32 `is_c`1 `isop`10 `cls`3 `rs1_en`1 `rs2_en`1 `rs1`5 `rs2`5 `rd_en`1 `rd`5 `dst_kind`2 `imm`44 `imm_kind`2 `src_sel`2 `dm`2 `sext`1 `is_w`1 `aq`1 `rl`1 `fm`4 `csr_addr`12 `csr_wr_type`2 `pred_taken`1 `pred_target`40 `bp_upd_id`8 `ftq_id`5 `pre_exc`1 `pre_exc_code`4 `bad_va`1 | R2：展开＝§3.4 的"已切分字段序"（含本表 #2~#4 的拆分结果）；Σ239＝该行位宽列 239 |
| 6 | `rmap_uop_t` L207 | `rs1`/`rs2`（架构号 5+5）→ `psrc1`/`psrc2`（`paddr_t` 6+6） | `psrc1`6 `psrc2`6（**替换** #5 中的 `rs1`5／`rs2`5，净 +2） | R1（替换子例）：`paddr_t`＝`logic [5:0]`（§2 行 88，`PADDR_W`=6）；净额＝该行位宽列 `+2`；全篇统一名 `psrc1`/`psrc2`（Q38） |
| 7 | `rmap_uop_t` L208 | 新增 `rs1_arch` | `rs1_arch`5 | R3：位宽列 5；类型＝`areg_t`；直通 `uop_t.rs1`（B1/L13） |
| 8 | `rmap_uop_t` L209 | 新增 `rd_paddr` | `rd_paddr`6 | R3：位宽列 6；类型＝`paddr_t` |
| 9 | `rmap_uop_t` L210 | 新增 `rd_old_paddr` | `rd_old_paddr`6 | R3：位宽列 6；类型＝`paddr_t`（回滚堆栈写入口） |
| 10 | `rmap_uop_t` L211 | 新增 `rd_is_new` | `rd_is_new`1 | R3：位宽列 1 |
| 11 | `rmap_uop_t` L212 | 新增 `ckpt_id` | `ckpt_id`2 | R3：位宽列 2；类型＝`ckpt_t`（§2 行 98） |
| 12 | `rmap_uop_t` L213 | 新增 `is_br` | `is_br`1 | R3：位宽列 1 |
| 13 | `rmap_uop_t` L214 | 新增 `needs_ckpt` | `needs_ckpt`1 | R3：位宽列 1 |
| 14 | `rmap_uop_t` L215 | 新增 `rs1_val` | `rs1_val`64 | R3：位宽列 64；CSRRS/CSRRC 后读拍产生（N-05） |
| 15 | `rob_alloc_t` L229 | `type[6:0]` | `type_f`7 | R4：区间 `[6:0]`⇒7；`type` 为 1800-2009 保留字（L1-3）⇒`type_f`；位序 bit0 `is_c`…bit6 `is_csr` 保留在区间内（§3.6 明写） |
| 16 | `rob_entry_t` L259 | `type[6:0]` | `type_f`7 | R4：同上；§3.7 要求与 §3.6「逐位一致（直连）」⇒ **两处必须同名同宽** |
| 17 | `rob_entry_t` L269 | `lq_v`/`lq_id` | `lq_v`1 `lq_id`6 | R1：位宽列 `1+6` 两项 ↔ 两名按序；`lq_id`＝`lqidx_t`（§2 行 91） |
| 18 | `rob_entry_t` L270 | `sq_v`/`sq_id` | `sq_v`1 `sq_id`5 | R1：位宽列 `1+5`；`sq_id`＝`sqptr_t` 的 index 域（§2 行 93 ＋ 附M-D4-①） |
| 19 | `iq_wr_t` L289 | `grp[1:0]` | `grp`2 | R4：区间 `[1:0]`⇒2；`grp` 非保留字 ⇒ 名不变；值域 INT/MEM/BR 三值（§3.8） |
| 20 | `iq_wr_t` L305 | `aq`/`rl` | `aq`1 `rl`1 | R1：位宽列 `1+1` 显式两项；ISA 锚 L1-4 |
| 21 | `iq_entry_t` L329 | `rdy1`/`rdy2` | `rdy1`1 `rdy2`1 | R1：位宽列 `1+1`；语义列「两个源的就绪位」对称（§3.9） |
| 22 | `disp_x_t` L365 | `rs1_val`/`rs2_val` | `rs1_val`64 `rs2_val`64 | R1：位宽列 `64+64`；`xdata_t`＝`logic [63:0]`（§2 行 85） |
| 23 | `disp_x_t` L370 | `dm`/`sext`/`is_w`/`aq`/`rl` | `dm`2 `sext`1 `is_w`1 `aq`1 `rl`1 | R1：位宽列 `2+1+1+1+1` 五项 ↔ 五名按序；各名与 §3.4 同名列同宽同义 |
| 24 | `disp_x_t` L371 | `csr_addr`/`csr_wr_type` | `csr_addr`12 `csr_wr_type`2 | R1：位宽列 `12+2`；`csr_addr`＝`csraddr_t`（§2 行 97）；`csr_wr_type` 编码 00 RW…11 读使能-only |
| 25 | `disp_x_t` L372 | `lq_id`/`sq_id` | `lq_id`6 `sq_id`5 | R1：位宽列 `6+5`；源＝`iq_wr_t` 载荷（附M-B-4）；口径同 #17/#18 |
| 26 | `br_resolve_t` L396 | `pred_taken`/`pred_target` | `pred_taken`1 `pred_target`40 | R1：位宽列 `1+40`；`pred_target`＝`va_t`（§2 行 86，40 bit） |
| 27 | `mem_req_t` L416 | `lq_id`/`sq_id` | `lq_id`6 `sq_id`5 | R1：位宽列 `6+5`；LSU 消费方，经本接口透传（附M-B-4） |
| 28 | `commit_t` L547 | `lq_dealloc`/`lq_id` | `lq_dealloc`1 `lq_id`6 | R1：位宽列 `1+6`；语义「load 可提交＝数据已回＋无异常」 |
| 29 | `commit_t` L548 | `sq_dealloc`/`sq_id` | `sq_dealloc`1 `sq_id`5 | R1：位宽列 `1+5`；语义「store 从此刻才允许写 cache」 |

**切分净额核对**：Σ29 行净额 = 741 bit = 414（10 个 struct 的当前缺口）＋ 327（`rmap_uop_t`，其行由"不透明兜底类型"临时覆盖）。

---

## 3. 机判自检（`doc/decisions/if_split.json`；判据 = 已生成标量位宽 + 本表切分净额 == `width_check.py --json` 的 `sum_computed`）

> **口径已随生成器落地而更新（2026-09-25 修复批）**：本标题与下条 C4 写的是**切分前**判据式；生成器消费本表后，
> 「已生成标量」本身已含切分结果，全篇恒等式职能改为 **`script/flow.py` 的 `types-width-consistency`（差额==0 即 OK）**，
> `check_if_split.py` 的 **C4 判据退役**（详见本节末「事后回写」）。本标题按历史保留。

**自检器**：`python doc/decisions/check_if_split.py`（末行＝机判结论）。判据六条：
**C1** 键集（28 struct 与 `width_check --json` 一一对应，防静默漏项）；
**C2** 行数守恒＋逐行原文对账（归一后与 `width_check.parse()` 的第 i 个非标量行相等）；
**C3** 行级位宽（每行净额 == `width_check` 对该行的独立实算；`width_total` == Σ`fields`）；
**C4** 全篇恒等式（28/28）——**已退役（2026-09-25）；见本节末「事后回写」③**；
**C5** R2 展开等式（`＝ X` 行的 fields 必须逐字段等于 X 的"解析字段序"）；
**C6** 命名合法（合法 SV 标识符且不撞 `SV_KEYWORDS`）。

| struct | 切分行 | 已生成标量 | 切分净额 | sum_computed | 判定 |
|---|---|---|---|---|---|
| `ftq_req_t` | 0 | 143 | 0 | 143 | OK |
| `ftq_entry_t` | 1 | 2 | 143 | 145 | OK |
| `fetch_raw_t` | 0 | 92 | 0 | 92 | OK |
| `uop_t` | 3 | 225 | 14 | 239 | OK |
| `rmap_uop_t` | 10 | 0 | 327 | 327 | OK |
| `rob_alloc_t` | 1 | 141 | 7 | 148 | OK |
| `rob_entry_t` | 3 | 123 | 20 | 143 | OK |
| `iq_wr_t` | 2 | 243 | 4 | 247 | OK |
| `iq_entry_t` | 1 | 25 | 2 | 27 | OK |
| `wb_t` | 0 | 80 | 0 | 80 | OK |
| `disp_x_t` | 4 | 179 | 159 | 338 | OK |
| `br_resolve_t` | 1 | 108 | 41 | 149 | OK |
| `mem_req_t` | 1 | 132 | 11 | 143 | OK |
| `mmu_transl_req_t` | 0 | 66 | 0 | 66 | OK |
| `mmu_transl_rsp_t` | 0 | 78 | 0 | 78 | OK |
| `miss_req_t` | 0 | 63 | 0 | 63 | OK |
| `fill_t` | 0 | 139 | 0 | 139 | OK |
| `mshr_wake_t` | 0 | 9 | 0 | 9 | OK |
| `icache_rsp_t` | 0 | 322 | 0 | 322 | OK |
| `dcache_rsp_t` | 0 | 87 | 0 | 87 | OK |
| `commit_t` | 2 | 342 | 13 | 355 | OK |
| `excp_t` | 0 | 177 | 0 | 177 | OK |
| `ret_ctrl_t` | 0 | 49 | 0 | 49 | OK |
| `csr_wr_t` | 0 | 81 | 0 | 81 | OK |
| `csrq_entry_t` | 0 | 152 | 0 | 152 | OK |
| `x_complete_t` | 0 | 79 | 0 | 79 | OK |
| `ls_complete_t` | 0 | 21 | 0 | 21 | OK |
| `rt_t` | 0 | 543 | 0 | 543 | OK |

- **末行结论**：`---- check_if_split: PASS（28/28 struct：已生成标量 + 切分 net == sum_computed；行级 29/29 与 width_check 逐行一致）----`
- **口径声明（防"凑数"误读）**：「已生成标量」＝`rtl/vr1/include/vr1_types.svh` 中该 struct 的
  `logic [N:0]` 字段位宽和；`rmap_uop_t` 是**唯一**全成员非标量的 struct，生成器给它的是"不透明位宽兜底类型"
  （`typedef logic [326:0] rmap_uop_t;`）——**兜底不计入已生成标量**（本表生效后它被 31 个真实字段取代）。
  §3 表另附"口径 A（兜底计入）"列于自检器输出，仅作对照：该口径下 `rmap_uop_t` 为 327+327，属**同一个 327 bit** 的
  兜底形态与真实形态，不是重复计量。
- **双向验证（机判非空转）**：注入 `ftq_entry_t` 的 `valid` 1→2 ⇒ `C3/C4/C5` 三项 FAIL、退出码 1；
  注入 `type_f`→`type` ⇒ `C6` FAIL；两次还原后 md5 回到 `8ee9700987a85dad9746f46e2403e2b4` 且末行 PASS。
- **事后回写（2026-09-25 修复批；原结论保留不改）**：上两处为**切分前**口径。生成器落地后——
  ① `rmap_uop_t` 的不透明兜底（`typedef logic [326:0] rmap_uop_t;`）**已取消**，改由 **39 个真实字段**声明
  （R2 复用 `uop_t` 的 31 ＋ 本表 #7~#14 的 8；`rs1`/`rs2`→`psrc1`/`psrc2` 净 +2 见 #6）；
  ② §3 表的「已生成标量」列自本轮起＝**含切分结果**的生成件标量和（应等于 `sum_computed`），故自检器末列
  由「判定」改为**只报告**的「生成−复算」差额列（不作判据）；
  ③ **C4 恒等式判据已退役**：生成器消费本表后再叠加「切分 net」属同一批位量的**双重计量**（实例：`ftq_entry_t`
  145 + 143 = 288 ≠ 145），该式在此口径下必然为假、且**不是**产品缺陷 ⇒ 按退役处理（**非**放宽阈值，红线 R6）；
  全篇恒等式职能**交 `script/flow.py` 的 `types-width-consistency`（差额==0 即 OK）**，
  `check_if_split.py` 仅保留**缺表/无法解析时的 fail-closed**（C0 缺表＋C1/C2 覆盖与行序）；
  ④ 自检器末行现为：`---- check_if_split: PASS（C1/C2/C3/C5/C6 全过；C4 已退役 → 交 script/flow.py types-width-consistency；行级 29/29 行与 width_check 逐行一致）----`
  （上列旧末行文本按历史保留）；实测口径：`ftq_entry_t` 已生成 145（含切分）＝ `sum_computed` 145，差额 0。
  ⑤ C4 退役后按上列同法注入复验（`ftq_entry_t` 的 `valid` 1→2）：红 **C3 两条 + C5**、**无 C4 项**，
  还原后 md5 仍 `8ee9700987a85dad9746f46e2403e2b4` 且末行 PASS（机判非空转，退役项确已不参与判定）。

---

## 4. 决策 2：`AXI_OUTSTANDING` 的取值口径

**现状**（三处引用面）：`spec/00` §4.7 行 256 格值 `2R + 2W`（依据列「简单从端可支撑」）；
生成器经 `COUNTSUM_RE` 走"计数项求和"路径，产出 `rtl/vr1/include/vr1_params.svh` 行 145–147：
`parameter int unsigned AXI_OUTSTANDING = 4;` ＋注释 `原文：2R + 2W` ＋`推导：计数项求和 2 + 2 = 4`；
消费者＝`spec/06` §4 总线行（L55）与 §6 出口自检行（L74 的 `2+2` token）、`spec/09` §2 回退点句（L27）。

**选项与评估**

| 选项 | 评估 | 结论 |
|---|---|---|
| (a) 单参数 `AXI_OUTSTANDING = 4` | AXI 读/写**通道与记账独立**（L1-5／L2-2）：一个共享计数器语义是"总在途 ≤4"，会把协议上合法的 3R+2W 挡掉（比规范**更严且不同义**）；而被下游误读为"每方向 ≤4"时又放到 8 在途（比从端能力**更宽**）。对任何 RTL 消费者都产生**方向性歧义**，且歧义的两种读法都可能致错 | 否 |
| (b) 拆 `AXI_OSTD_R = 2` / `AXI_OSTD_W = 2` | 与 `2R + 2W` 逐项对应（零猜测、零新数值）；读写可分别限流（RTL 需要的正是两侧各自记账——写侧由 B 兑现、读侧由 RLAST 兑现）；生成器**天然支持**（两行普通 INT，无需改 `script/**`）；色标/引用面可逐项回指 | **取** |
| (c) 保留 `2R + 2W` 原样并标"不可机判" | 需把该格改成非数值写法 ⇒ 生成器判 `UNPARSED` ⇒ `gate.py` 的 params 判据 FAIL（"UNPARSED 必须修"），与"本批不改 `script/**`"直接相抵；且 `spec/00` §4 是数值唯一权威源，权威格里留不可机判表达式会污染整表机判面 | 否 |

**选定**：(b)。**但只把"表示形式"记为已定**——数值面按规则 20 降级，见下。

**外部锚点**：L1-6（`axi_throttle` 的 `MaxNumAwPending` / `MaxNumArPending` 两参数＋读写各自 credit）；
L1-5（五通道独立、in-flight 定义＝事务级、outstanding 深度属系统设计参数、超限是经典失效面）；
L2-2（Arm 把 read/write issuing 与 acceptance capability 列为**独立属性**；Xilinx 互连以
`C_M_AXI_READ_ISSUING` / `C_M_AXI_WRITE_ISSUING` 分别参数化；Cortex-R5 实例 7R／2W）。

**数值面：无锚点，降级为"登记＋预测＋回退点"（规则 20）**

- 登记：`spec/00` §4.7 原文的 `2R`／`2W` 两值本身**无锚**（依据列只有「简单从端可支撑」，未指名从端/文档/实测）。
- 预测：若"简单从端"指一个 2R+2W 能力的 AXI4 从端，则拆参后 `AXI_OSTD_R=2`／`AXI_OSTD_W=2` 与之等价；
  预测**可被证伪**的观测点＝`spec/09` 深化片给出 MSHR/回填吞吐的时序论证时，若要求 >2 笔读并发即证伪。
- 回退点：①数值改判 ⇒ 只改 `spec/00` §4.7 两格的数字（生成件重跑，全链自动跟）；②表示形式改判（如回到单参数）
  ⇒ 生成器需一处小改（`COUNTSUM_RE` 现状会继续求和），成本一处；③若日后确认从端具体型号 ⇒ 数值升为"已定"。
- **计数单位（须随落文写明，否则同一参数会有多种读法）**：一笔**事务**＝`AR`/`AW` 握手至其最后一拍响应握手
  （锚＝L1-5 的 in-flight 定义）；**不是** beat 数、也不是 burst 内拍数。

**下游义务清单（同批执行，缺一即断链）**

> **状态标注（2026-09-25 修复批；事后回写）**：本清单**待落 `spec/00` §4 与 `spec/06`／`spec/09`**——
> O-1／O-2／O-3／O-5 四个 **spec 落文点均未执行**（属他人书写面，本批**未动** `doc/spec/**`）；
> **O-4**（生成件）现状＝仍为**单参数** `AXI_OUTSTANDING = 4`，其注释已显式标注「原文 `2R + 2W` 为分方向计数项，
> 本行只有求和后的单一数值 4；若下游需按方向/通道分别记账（ADR-P-2 §4）须拆参——本行口径待 ADR-P-2 §4 下游义务
> O-1/O-2/O-3 落 `spec/00` §4 与 `spec/06`／`spec/09`」（生成件内可 grep）；**O-6** 不变。
> ⇒ 拆分**只在 ADR 层已定**，**落文批次未启动**，任何引用**不得声称已拆**。

| # | 落点 | 动作 | 判据 |
|---|---|---|---|
| O-1 | `doc/spec/00` §4.7 行 256 | 拆成两行 `AXI_OSTD_R = 2`、`AXI_OSTD_W = 2`；依据列保留「简单从端可支撑」并加"数值锚点待补（ADR-P-2 §4）" | 两行皆可机判为 INT 且和为 4；版本表加批行 |
| O-2 | `doc/spec/06` §4 行 55 与 §6 行 74 | 总线行的 `AXI_OUTSTANDING`＝`2R+2W` 改为引 `AXI_OSTD_R`/`AXI_OSTD_W`；§6 自检行的 `2+2` token 同批改 | 全篇无 `AXI_OUTSTANDING` 旧名残留（`grep` 可核） |
| O-3 | `doc/spec/09` §2 行 27 | 回退点句改为引两参数名 | 同上 |
| O-4 | `rtl/vr1/include/vr1_params.svh` | 重跑 `python script/flow.py params`（旧单参数作废；`chk_params_drift` 会强制同批） | 生成件出现两条 parameter；`flow check` 的 params 判据 PASS |
| O-5 | `doc/spec/09` 深化片（T-09-1／T-09-2 面） | 补一句口径：`MSHR_ENTRIES=8` 与 `AXI_OSTD_R=2` 不是相抵——8 个未决缺失中 ≤2 已发 AR、其余等信用 | 读者面不再出现"8 vs 2 相抵"读法 |
| O-6 | `run_cmd/vr1_configs.yaml` | 若新增两参数需被某配置覆盖则补名（当前 6 组现值均未覆盖本参数，故本批可不改） | 色标件与 `spec/12` §2 不出现旧名 |

---

## 5. 决策 3：`spec/12` §4 成熟度口径（**判定口径类，需 R0 确认；本件不宣布其生效**）

**问题两面（均有机判事实支撑）**

1. **同一参数跨配置**：`FWD_CMP_BITS` 同时列在 `FWD`（Amber，依据＝单拍可实现性登记）与 `WIDE`（Green，依据＝"三者同源＝`PA_BITS`"）
   的 `params` 里（`run_cmd/vr1_configs.yaml`）。按现文两行都成立，于是同一参数同时是 Amber 与 Green。
2. **Green 判据不可证伪**：「无未闭合承接项」没有可核清单。实测（`flow.py parse_spec_params` 口径）`spec/00` §4 表体 **118 行** =
   97 INT ＋ 2 LIT ＋ 2 ARRAY（**101 个可机判参数**）＋ 17 条 ENUM 登记；而 6 组现值的 `params` 列并集只覆盖 **25 个参数名**
   （全部为 INT，含 `FWD_CMP_BITS` 跨两格）⇒ **未入组 = 101 − 25 = 76 个可机判参数**（另有 17 条 ENUM 登记同样不在覆盖内，
   参数名合计 93）。这 76 项的"成熟度"既非 Green 也非 Amber，而"无未闭合承接项"这句话**没有判定域**，故无法核对
   （与 L1-8 §12.3 第 2 行的上报条件同类）。

**建议口径（M1~M3；取严）**

- **M1 判定域显式化**：成熟度是对**配置（其 `params` 列所示参数子集）**的声称，引用时必须指名配置 id；
  **未列入某配置 `params` 的参数，该配置的色不对它作任何声称**（记 `unclaimed`，不得由"配置是 Green"反推该参数已验）。
- **M2 跨配置取严**：同一参数被多个配置覆盖时，**该参数的有效色 = 覆盖它的各配置色中的最严者**（Green < Amber < Red）。
  任何以"参数 P 已定/已验证"为前提的签核陈述，其强度不得超过 P 的有效色。
  ⇒ `FWD_CMP_BITS` 的有效色 = min(FWD=Amber, WIDE=Green) = **Amber**。
- **M3 向量降级**：若某配置标 Green 但其 `params` 中存在有效色 < Green 的参数（由 M2 判定），则该配置**降级**，
  并在 `basis` 写明降级来源（例：`downgraded_from: Green; cause: FWD_CMP_BITS@FWD=Amber`）。
  ⇒ 该口径下 **`WIDE` 由 Green 降为 Amber**（除非 `FWD_CMP_BITS` 从 `FWD` 的 `params` 移出，或 `FWD` 升 Green）。
- **承接项的可核形式（把"无未闭合承接项"变成可枚举＋空集可核）**：每条配置增字段
  `open_items: []`；每个元素必须是结构化对象 `{id, kind, owner, exit}`——`id` 必须是台账号（`ISS-nn`）或队列号（`Q-nn`）
  或待补项号（`T-nn-n`）且**在册可查**（机判：存在性）；`kind` ∈ {登记型, 无锚点型, 待综合型}；`exit` ＝可核出口判据。
  于是 Green 判据变成两条**可机判**的合取：①`params` 逐项等于 `spec/00` §4 现值；②`open_items` 为空表。
- **覆盖守恒（签核面前提，单独一条，防"未声称"被当"已验"）**：签核所需的参数集必须被 ∪(Green 配置的 `params`) 覆盖；
  未被覆盖者只能在签核面标 `unclaimed` 并单列，不得计入已验范围。此条同时给 T-12-1（参数→消费篇全矩阵）一个收敛口径。

**为何取严（锚点）**

- L1-7：色标原始实践把成熟度挂在**"a particular configuration"**上，而 ibex 的配置是**全参数向量**
  （"each configuration must specify the same set of parameters"）——即"配置级结论 → 参数级结论"的方向是**导出**，
  故当同一参数在不同配置里得到不同结论时，**没有"取宽"的依据**（不能声称某参数比它所在的某个配置更成熟）。
- L1-8 §12.3 第 2 行：取宽等于把"无复核手段的 Green"当证据用——正是该条要上报的形态；取严则永远不会把已登记风险洗掉。
- 项目内先例：R0 2026-09-24 的裁决取"最严格口径"；`AGENTS.md` 硬停机条款同源（不得默认通过）。

**生效声明**：以上 M1~M3、`open_items` 字段与覆盖守恒**一律待 R0 确认后方可生效**。
本件在 R0 确认前**不改** `run_cmd/vr1_configs.yaml`、**不改** `spec/12` 正文，仅把建议与判据写入本 ADR 供呈报；
在此之前 `FWD`/`WIDE` 的色标**维持现状**（不因本 ADR 自动降级）。
**若 R0 采 M1~M3**，下游同批义务：①`run_cmd/vr1_configs.yaml` 的 `WIDE` 行改 Amber＋写 `basis` 降级来源、
六条现值配置补 `open_items: []`；②`spec/12` §4 判定口径三条改写＋§4 映射表 `WIDE` 行同步＋§6 补 `T-12-5`（承接项字段与覆盖守恒判据）；
③机判落到 `script/gate.py`（配置色标的固定点计算与 `open_items` 存在性）——归 script 面批次执行。
**回退点**：若 R0 选"按配置各自判定（不取严）"，则 `WIDE` 维持 Green，但**必须**在 `basis` 声明
"本配置的 Green 不覆盖 `FWD_CMP_BITS` 的时序风险面"，且任何以该参数为前提的 Green 级引用须回指 `FWD` 的 Amber 登记；
两种写法不得同时省略（否则又回到"同参数同色两说"的不可证伪态）。

---

## 6. 下游义务汇总

| # | 义务 | 落点 | 批次 |
|---|---|---|---|
| 1 | 生成器改为**查本表**生成非标量行（当前只登记注释）；`rmap_uop_t` 的不透明兜底分支随之取消 | `script/flow.py` `render_types`／`types_member_split` | script 面批次（**已落地** 2026-09-25：`render_types`／`types_member_split` 消费本表；28/28 差额 0、合计 4442 bit、`rmap_uop_t` 由 39 个真实字段取代；兜底分支保留为「出现即 FAIL」的兜底标记） |
| 2 | 生成件重跑并回写 `chk_types_width_consistency` 的期望（届时差额应为 0） | `rtl/vr1/include/vr1_types.svh` ＋ `sim/run_types` 编译证据 | **已落地**（生成件已重跑，`types-width-consistency` 差额 0；`types-compile` 4 单元 ｜ Errors: 0） |
| 3 | `spec/01` §3 各表可选加注"生成期名 `type_f`"与"位宽列＝字段 a + 字段 b"（**可选**，因本表已是机判源） | `doc/spec/01` §3.6／§3.7 等 | spec 落文批 |
| 4 | O-1~O-6（决策 2 的下游义务清单） | `spec/00`／`spec/06`／`spec/09`／生成件／色标件 | spec 落文批（**待落**：O-1~O-3/O-5 未执行，见 §4 状态标注；O-4 生成件面现状＝单参数＋口径注释） |
| 5 | 决策 3：**待 R0**；确认后按 §5 尾段的 ①②③ 执行 | `spec/12`／`vr1_configs.yaml`／`script/gate.py` | R0 确认后 |
| 6 | `ADR-P-1` 编号补登记已在本批完成（台账历史条目 id `ADR-1`）；`doc/verify/04` 看板与 `AGENTS.md` 的 G1 余项叙述由 R8 按其轮次镜像 | 台账／看板 | R8 轮次 |

---

## 7. 风险自评（供 `doc/项目开发流程.md` §12.5 决策审核对撞）

| 风险源 | 触发条件 | 影响面 | 现有兜底 | 残余 |
|---|---|---|---|---|
| ① 判错（锚点可回查性） | 切分规则 R1 的"名字序 ↔ 位宽项序"若与作者原意相反 | 29 行中 16 行（R1 行数）的字段归属 | 位宽列自带加式 + 逐行位量对撞 `width_check`（C3）；组内顺序与 ADR-P-1 同源 | 可接受（有位量机判兜底；顺序语义由 G1 读 §2 表一次即可） |
| ② 不可逆 | 生成件已被下游引用后再改切分 | RTL/断言/覆盖率采样名 | 本表为**唯一机判源**且改名/改序都在一行内；`type_f` 改名集中在生成器一处 | 可接受（回退＝改一行＋重生成） |
| ③ 下游缺失 | O-1~O-6 未随落文批执行 | `spec/00` §4 数值权威源与两个消费者长期不同名 ⇒ 生成件与文档分叉 | 义务清单已列点列判据；`chk_params_drift` 会强制生成件与 §4 同批 | **需进 §9.5 list ④段人读**（防止只改一处） |
| ④ 自洽 | 决策 3 取严使 `WIDE` 由 Green 降 Amber，而 `spec/12` §4 映射表仍写 Green | 色标件与 spec 表两说 | 本件明确"R0 确认前维持现状、不自动降级"，并列出同批义务 | 可接受（口径声明与实例更新是同批动作） |
| ⑤ 致死 | `AXI_OSTD_R`/`W` 若被消费方误读为"beat 数上限"，64B 行填充需 4 拍 ⇒ 误算成 2 拍可能截断 | L2↔AXI 数据面 | §4 已写"计数单位＝事务"并列为落文义务；`spec/09` 深化片复算 | 需决策 AI 回应（若 `spec/09` 明确采用 beat 粒度） |

---

## 8. 出口自检（每项附复核手段）

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 切分表与 `width_check` 逐 struct 恒等（28/28） | `python doc/decisions/check_if_split.py` 末行 | PASS（见 §3） |
| 2 | 29 行逐行位量守恒（C3 行级对撞） | 同上（行级 29/29） | PASS |
| 3 | 机判非空转（注入即红） | 两次注入（`valid` 1→2；`type_f`→`type`）→ FAIL；还原后 md5 一致 | 已验证 |
| 4 | 非标量写法全覆盖（无静默漏项） | C1 键集 28/28 ＋ C2 行数守恒（17 空表 + 11 有表） | PASS |
| 5 | 保留字命名分歧显式落盘 | `if_split.json` 的 `rename` 字段（`from`/`to`/`why`）＋ L1-3 锚 | 在文 |
| 6 | 无锚点项已降级（未记"已定"） | §0 无锚点声明 ＋ §4 数值面"登记＋预测＋回退点" | 在文 |
| 7 | 判定口径类未自行生效 | §5 生效声明（`FWD`/`WIDE` 维持现状） | 在文 |
| 8 | 文档结构/码点不破坏仓门 | `python script/gate.py check` 的 `codepoints`（本批新文件在扫描面内）＋ `md-integrity` 等价复算（逐表列数一致） | `codepoints` PASS（含本件）；`md-integrity` 的 FAIL 落在 `doc/_legacy/…/派发词模板.md:28`、`ra-token-defined` 的 FAIL 因 `doc/自动推进说明.md` 缺件——**两者均非本批引入**（本件不在 `RA_LIVE_FILES` 扫描面内）；日常门禁为 `script/flow.py check`，由 R8 轮次执行 |
