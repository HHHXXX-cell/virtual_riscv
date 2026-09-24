# VR1 访存与 cache 层次（doc/spec/06）

| 版本 | 日期 | 状态 | 变更摘要 |
|---|---|---|---|
| v0.1 | 2026-09-24 | 草稿（**骨架·首片**；未评审、未定稿） | 首片：篇首三段式；§1 层次与地址流；§2 LSU 数据通路（LQ/SQ/转发/重试）；§3 MMU/TLB/PTW 衔接（walk 细则转 `spec/08`）；§4 L1/L2 与总线；§5 时序引用与待补清单；§6 出口自检 |

> **① 范围**：本篇给出访存路径与 **cache 层次**的结构性口径：LSU 资源与转发纪律、MMU/PTW 与本层的交界、L1I/L1D/L2 的组织与 miss 处理、外部总线（AXI4/OBI）与 MMIO 口径。
> **② 边界**：接口位域以 `spec/01` 为准（§3.13 `mem_req_t`、§3.14 MMU 翻译、§3.15 PTW、§3.16 L1I 取指）；**拍序与等待口径以 `spec/05` 为准**；Sv39 walk/PTE 细则与 PMP/PMA 语义归 `spec/08`（待建）；cache 条目位域与替换态归 `spec/09`（待建）；**数值一律引 `spec/00` §4**（本篇不另赋值）。
> **③ 引用纪律**：每处结论绑「篇号＋节号」；与 `spec/00`/`spec/01` 冲突时以彼为准并登记差异（红线 R20）。

---

## 1. 层次总览与地址流

```
取指：IF → MMU(翻译/PMP/PMA) → L1I 32KB/8w/64B VIPT → L2 256KB/16w → AXI4 → 外部
数据：LSU → MMU(翻译/PMP/PMA) → L1D 32KB/8w/64B VIPT → L2 → AXI4 → 外部
旁路：CLINT/PLIC 经 MMIO（non-cacheable 区，单拍传输）
```

| 项 | 口径 | 引 |
|---|---|---|
| 参数 | `LQ_ENTRIES=48`／`SQ_ENTRIES=32`／`L1_SETS=64`/`L1_WAYS=8`/`L1_LINE=64B`／`L2_SIZE`/`L2_WAYS`/`L2_LINE` | `spec/00` §4.6 |
| 地址宽 | `VA_BITS=39`（Sv39）／`PA_BITS=44` | `spec/00` §4.1 |
| 单核假设 | 无一致性需求；L2 **non-inclusive**；LR/SC 不在总线层实现独占 | `spec/00` §4.6/§5 D10/§8 |
| 非对齐 | **不支持**：非对齐 load/store/AMO/LR/SC 一律报 address-misaligned | `spec/00` §2/§4.7；`spec/02` §18.2 |
| 访存类型判据 | `type.bit5 is_mem`（LD/ST/AMO）——**不按 `cls`**（FENCE 不占 LQ/SQ） | `spec/01` §4 BP3 |

## 2. LSU 数据通路

- **资源与分配**：LQ/SQ 条目由 `S` 级分配（`spec/01` §3.6/§3.8），满则按类反压（BP3：`lq_full`/`sq_full` 只拦访存类）。
- **转发（forward）**：比较键＝**PA 全宽 44 bit（含 PPN）**、字节掩码保留（`FWD_CMP_BITS`，ADR-S2-3，`spec/00` §4.6）；比较键口径与 LR/SC 保留键同源（`spec/02` §18.2）。
- **转发不可行**：**延迟重试**（不设"截断次数"计数——该指标已废，改 `fwd_blocked_replay`，`spec/00` §9）。
- **store 写入时机**：**只在 ROB 头提交后写 cache**（禁止投机 store 写 cache，`spec/00` §3/§8；`spec/01` §5.2 `S` 行）。
- **AMO**：读改写在一期 **L1D 内 RMW 原子完成、不发到 AXI**（`spec/00` §8）；μop＝2（`spec/02` §18.4）。
- **异常与抑制写**：异常提交时内存写不发生（对照表见 `spec/02` §19）。
- **在途/SCB**：MSHR 唤醒（`mshr_wake_t`，`spec/01` §3.16）与未命中合并口径归 `spec/09`（待建）细化。

## 3. MMU / TLB / PTW 衔接

- **接口**：`mmu_transl_req_t` / `mmu_transl_rsp_t`（成员与位宽＝`spec/01` §3.14，本篇不复述）；**`ptw_mem_req_t`＝`spec/00` §6 M12 行/X5 注所列「G1 冻结前必须闭合」型，`spec/01` 现文未定义 ⇒ 登记 `spec/01` 后续片（ISS-092 处置项②）**。
- **翻译口径**：Sv39 三级页表（`VA_BITS=39`）；大页级别（4K/2M/1G）在 `rsp.super` 域；`rw` 域值域＝{R,W,X,保留}（`spec/01` §3.14）。
- **PMP/PMA**：PMP 8 项；PMA 静态区域表（non-cacheable/strong-order/no-prefetch）；**MAG PMA 不配置**（不实现 `Zama16b`，ADR-S06-A，`spec/00` §2/§8）。
- **walk 与 A/D 位**：`spec/08`（待建）为权威；本期口径：A/D 位**硬件置**（`spec/00` §5 D8）。
- **fault 分流**：page-fault 与 access-fault 的判定点与优先级归 `spec/08`；本层只承载 `mem_req_t` 的请求语义（`spec/01` §3.13）。

## 4. L1 / L2 / 总线

| 层 | 组织（引 `spec/00` §4.6/§4.7） | miss 处理 |
|---|---|---|
| L1I | 32KB/8w/64B VIPT；L1I TLB16；取指粒度 32B 窗口 | miss ⇒ PTW/回填；`xw_carry` 跨窗拼接见 `spec/05` §3 |
| L1D | 32KB/8w/64B VIPT | miss ⇒ MSHR 合并 ⇒ L2；store 未命中走 write-allocate 口径归 `spec/09`（待建） |
| L2 | `L2_SIZE`/`L2_WAYS`/`L2_LINE`；**non-inclusive**（避免写回风暴、一期无一致性需求） | miss ⇒ AXI4 读；回填粒度归 `spec/09` |
| 总线 | AXI4：128 bit data／44 bit addr／ID 4 bit；burst 仅 **INCR**；`AXI_OUTSTANDING`＝2R+2W | 从端错误响应 ⇒ 转 access-fault（`spec/08` 口径） |
| MMIO | non-cacheable 区**单拍**（`MMIO_BURST`：len=0，size=2..8B） | 不经 cache；`fence` 处排空 SQ（`spec/00` §8） |

- **CLINT/PLIC**：8 source PLIC-lite（3 bit 优先级＋3 bit threshold，claim/complete）；CLINT 为单 hart（`mtimecmp`/`msip`/`mtime`）——**挂接与中断语义归 `spec/10`（待建）**（`spec/00` §4.7）。

## 5. 时序引用与待补清单

- **拍序**：访问发起/完成拍、转发拍序、重试拍序、MSHR 唤醒时序**一律引 `spec/05`**（本篇不定义拍序）。
- **T-06-1**：L1D store 未命中策略（write-allocate vs no-write-allocate）与行粒度 → `spec/09`（待建）。
- **T-06-2**：MSHR 条目数、合并规则与请求 ID 分配（`req_id` 3 bit）→ `spec/09` + `spec/01` §3.13 对账。
- **T-06-3**：L2 回填/写回粒度与 non-inclusive 目录位 → `spec/09`。
- **T-06-4**：预取/预读口径（一期不实现，登记）→ `spec/09`/二期。
- **T-06-5**：`ptw_mem_req_t` 的优先级与 L1D 竞争（walk 请求与数据请求仲裁）→ `spec/08`（待建）。
- **T-06-6**：perf 计数（`MPKI`/`fwd_blocked_replay`）的采样点 → `spec/13`（待建）与 `spec/01` §3.22。

## 6. 出口自检（每项附复核手段）

| # | 检查项 | 复核手段 | 本轮结果 |
|---|---|---|---|
| 1 | 数值零自造（全部引 `spec/00` §4） | 本篇数字 token 逐项回溯（48/32/64/8/64B/39/44/128/4/2+2 等均带篇号节号） | 本片实读 |
| 2 | 接口零定义（位域全部引 `spec/01`） | 本篇不出现 struct 成员表；`width_check` 28/28 不变 | 待本轮实跑 |
| 3 | 拍序不越篇（统一引 `spec/05`） | §5 首条声明；正文无拍数/拍序新述 | 一致 |
| 4 | 结构完整（表列数/粗体/码点） | `gate.py check` 的 `md-integrity`/`codepoints` | 待本轮实跑 |
