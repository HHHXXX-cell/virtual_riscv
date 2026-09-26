# ADR-P-1 接口打包顺序（doc/decisions/ADR-P-1）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v1.0 | 2026-09-25 | RD 自决生效（属自决项；进 G1 评审 list 供 R0 确认） | 首版（事后建档）：把此前只被**引用**而**无实物**的打包顺序约定落成文件——`spec/01` §3 struct 表「表中自上而下 ＝ MSB→LSB」；四要素（选项与评估／选定／锚点／下游义务＋回退点） |

- **登记号**：`ADR-P-1`（编号分区见 `AGENTS.md` §0：`ADR-P-<n>` 为流程侧 ADR；本件台账历史条目 id 为 `ADR-1`；条款已由 `doc/process/ledger.json` 于 2026-09-25 补登记；编号一律 `python script/flow.py record` 自增，**禁手写**）。
- **建档缘由**：本编号此前只存在于引用面——台账 `ADR-1` 条目、`script/flow.py` 的 `PACK_ORDER_MSB_FIRST` 注释、`doc/decisions/ADR-P-2-接口字段切分与打包顺序.md` §1 尾句——**无独立实物文件**。本件补齐实物，内容与上述三处**逐点一致，不新造结论**。
- **角色**：RD 决策 AI（先例与依据：`doc/项目开发流程.md` §12.2「设计/规格类取舍由决策 AI 自决并留 ADR」）。
- **写边界声明**：本批**只写** `doc/decisions/**` ＋经 `flow.py record` 写台账；**未改** `doc/spec/**`、`script/**`、`rtl/**`、`iss/**`、`tb/**`（下游义务以清单形式交后续落文批）。

---

## 1. 问题（可核事实，非推理）

- `spec/01` §3 共 **28 个 struct、327 个成员行**；`script/width_check.py` 与 `script/flow.py types` 两处机判口径一致（`doc/process/ledger.json` ISS-106）。
- 生成件 `rtl/vr1/include/vr1_types.svh` 采用 `typedef struct packed { … }` ⇒ **声明序必须承载唯一语义**，
  否则同一 struct 在 RTL／SVA／覆盖率采样名三处可能各自解释（＝ISS-106 同型「同一位序两说」）。
- **`spec/01` 全篇未规定成员间的打包顺序**：实测 `grep -E "MSB|LSB|位序|最高位|最低位|bit ?序|字节序|first member"` 命中 **4 处**，
  逐条读后**无一是 struct 成员间的顺序**：

| 命中位置 | 原文要点 | 是否成员级顺序 |
|---|---|---|
| §3.6 行 229 | `type[6:0]` **单字段内**位序定死：bit0 `is_c`…bit6 `is_csr` | 否（字段内位分配） |
| §3.7 行 259 | `rob_entry_t.type` 与 §3.6 **逐位一致**（直连） | 否（同上） |
| 行 626 | `excp_t.sbe`/`cle` = `mstatus.SBE`/`CLE`（**字节序**相关，一期恒 0） | 否（CSR 域语义） |
| 行 893 | 监视器内部信号绑定说明（引 §3.6/§3.7 位序） | 否（TB 采样面） |

> 结论：**成员级打包顺序在 `spec/01` 中无表述**（可 grep 复核），故本约定是**自决项**，不得被当成「spec 已定」。

---

## 2. 选项与评估

| 选项 | 评估 | 结论 |
|---|---|---|
| (a) 表中自上而下 ＝ **MSB→LSB** | 与 `typedef struct packed` 的声明序语义同向（锚 A-1：「首个成员为最高位」）；与 §3 各表「控制位在前、载荷在后」的书写惯例同向；生成器**一处布尔**即可切换，判据面（types-drift／coverage／width-consistency／crosscheck／compile）已全在环 | **取** |
| (b) 表中自上而下 ＝ LSB→MSB | 与 (a) 逐位镜像；**无任何标准或文档锚点**支持本项目取反；且与 `[39:0]`／`[43:0]` 这类区间写法（`[N:0]` 左端为高位）的阅读直觉相反 | 否 |
| (c) 不作规定，留给实现 | 生成件属 G1 冻结面，无唯一顺序 ⇒ 位序退化为**不可核约定**（红线 R20：无锚点者不得记「已定」）；且会与 ADR-P-2 §1 R2/R3 的切分行顺序（「不改变行间相对顺序」）无法对接 | 否 |

---

## 3. 选定

**选定 (a)：`spec/01` §3 struct 表中自上而下的成员序 ＝ 打包后的 MSB→LSB**
（即 `typedef struct packed` 的声明序：首个成员占最高位，后续成员依降序排列）。

- **机械落点（唯一）**：`script/flow.py` 的 `PACK_ORDER_MSB_FIRST = True` → `render_types()` 按
  `width_check.parse()` 的源成员行顺序产出字段声明（关闭时为 `reversed()`，功能位只此一处）。
- **生成件留痕**：`rtl/vr1/include/vr1_types.svh` 头注释已载明本约定、依据与回退点。
- **不改切分**：本约定**只定行间顺序**；ADR-P-2 的切分行组内顺序（`fields` 列表序）由 ADR-P-2 决定，二者不冲突。

---

## 4. 锚点

- **A-1（一级依据）**：IEEE Std 1800-2012 §7.2.1 Packed structures ——
  「The **first member specified is the most significant** and subsequent members follow in decreasing significance.」
  本机提取件：`D:\IC验证知识库\_tools\extracted\lrm1800\c07_aggregate_types.txt`（`§7.2 Structures` 行 19／
  `§7.2.1 Packed structures` 行 56；条文 **行 62–63**）。该条文自 1800-2005 起一脉未变（台账历史条目 `ADR-1` 引作
  IEEE 1800-2009、`script/flow.py` 注释引作 1800-2012，**同一节号同一语义**，本件以 1800-2012 标注）。
- **A-2（本项目惯例）**：`spec/01` §3 各成员表自上而下按语义书写（控制/资格位在前，地址与载荷在后），
  生成件与 §3 **逐行可核**（每个字段行带 `// src: L<行号> <成员列原文>`，判据 `types-coverage` 源行守恒）。
  与 §3.6 的 `bit0…bit6` 书写**不在同一层**（那是字段内位序，见 §1 表），故不构成反例。
- **无锚点声明（红线 R20）**：`spec/01` 对本约定**无原文表述**（§1 的 4 处命中均非成员级顺序）
  ⇒ 本项按「登记＋回退点」方式成立，**不得**在引用时表述为「spec 已规定」。
- **编号分区（2026-09-25）**：本件原名 `ADR-1-接口打包顺序.md`（裸号），按分区口径改名为
  `ADR-P-1-接口打包顺序.md`；裸号 `ADR-<n>` 属规格/历史面既有编号，**不再发新号**。

---

## 5. 下游义务

| # | 义务 | 落点 | 状态 |
|---|---|---|---|
| D-1 | G1 评审确认本约定（或改判为 LSB-first） | G1 评审 list（`doc/verify/04`／`doc/spec/14` 冻结记录） | **待人（R0）** |
| D-2 | 生成件头注释载明约定＋依据＋回退点 | `script/flow.py` `render_types()` | **已落**（本批复核在文） |
| D-3 | RTL／SVA／覆盖率采样面**不得各自另立**打包顺序（须回引本 ADR） | `spec/11` 与 tb 面后续批 | 待落 |
| D-4 | 若改判：执行 §6 唯一机械动作并回填本 ADR 与台账 | `script/flow.py`＋生成件 | 回退点（见 §6） |

---

## 6. 回退点（唯一机械动作）

`PACK_ORDER_MSB_FIRST = False`（`script/flow.py`）→ `python script/flow.py types` 重生成生成件 →
`python script/flow.py check`（`types-drift`／`types-coverage`／`types-width-consistency`／`types-crosscheck`／
`types-compile` 五项须全 PASS）→ 回填本 ADR 与 `doc/process/ledger.json`。
**成本＝一处布尔 ＋ 一次重生成**；判据面无须改（判据只判产品，不判顺序取值）。

---

## 7. 出口自检

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 「spec 未规定成员级顺序」是可核陈述 | 上列 grep 与 4 处命中逐条读（§1 表） | 可核（4/4 非成员级） |
| 2 | 选定项有标准锚点 | A-1 条文行 62–63（本机提取件） | 在文 |
| 3 | 机械落点唯一、可切换 | `PACK_ORDER_MSB_FIRST` ＋ `reversed()` 一处 | 在文（`script/flow.py`） |
| 4 | 与 ADR-P-2 不冲突（行间序 vs 行内组序） | ADR-P-2 §1 尾句「不改行间相对顺序」 | 一致 |
| 5 | 未自行生效关键节点 | 本件为自决项，D-1 交 G1 评审确认 | 在文 |
| 6 | 文档结构/码点不破仓门 | `python script/flow.py check` 的 `md-integrity`／`codepoints` | 见本轮 `flow.py check` 输出 |
