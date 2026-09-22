# 评审探针（证据索引）

本目录是 **R7 独立对抗评审的证据文件**，不是回归测试。价值：`doc/00` 的 **ISS-019** 每一条指控
都必须能在这里找到"实跑输入 → 实跑输出"的对应物（红线 R3：结论可回溯到具体 log/代码行）。

| 文件 | 证明的评审条目 | 内容 |
|---|---|---|
| `rr_probe1_shift.py` / `rr_out*` | Q18/Q19（SRA/SRAI/SRAIW、保留 funct6） | 移位类实跑值 |
| `rr_probe2_system.py` | Q8/Q27（MRET/SRET/WFI/FENCE.I/SFENCE 编码与解码） | 与官方 `encoding.h` 逐字对账输出 |
| `rr_probe3_trap.py` / `rr_probe3b.py` | Q3/Q4/Q5/Q9/Q26（mtval、伪退休、minstret、目标对齐、EBREAK） | trap 现场逐条打印 |
| `rr_probe4.py` | Q17（LBU/LHU/LWU 宽度与对齐）、Q15（编码器范围截断）、Q13（signature 窗） | 访存与编码越界实跑 |
| `rr_probe5.py` | Q10/Q11（未实现 CSR 静默可写、mcycle 自相矛盾） | CSR 影子寄存器实跑 |
| `rr_probe6.py` | Q27（71 条指令字与官方编码逐条对账） | 编码一致性总表 |
| `rr_probe7.py` | Q1/Q2/Q5/Q6/Q20（无异常列、取指失败丢记录、保留编码崩溃、MULW 族） | 假绿路径清单 |
| `rr_probe8.py` | Q2/Q12/Q14/Q21（跑飞静默、tohost 判定、自旋穿过） | 停机与流完整性 |
| `rr_probe9.py` ~ `rr_probe12.py` | Q22~Q27（MPP/mip/mtvec/mepc WARL、移位编码复核） | CSR 边界实跑 |
| `_e.txt` `_m1.txt` `_m2.txt` `_m3.txt` `_sm.txt` | 中间输出片段 | 原始 stdout 留档 |

## 使用注意

1. **这些脚本是"案发时快照"，不是可重跑的回归**。它们原本位于 `script/tmp/`，且多数按
   *缺陷存在时* 的行为写断言/打印；移动到本目录后其内部的 `sys.path` 相对层级已失效。
   → **回归职责归 `iss/tests/test_isa_semantics.py`**（那里是"修好后必须为真"的断言）。
2. 若需重跑某条证据：把脚本内路径改指 `iss/`（两层深）后执行，或参照它在本目录新建 probe。
   不得为了让它通过而修改断言——那正是红线 R6 禁止的事。
3. 本目录**受版本控制**（原先放在被 `.gitignore` 排除的 `script/tmp/`，证据会随清理丢失，
   见 `doc/00` ISS-022）。
