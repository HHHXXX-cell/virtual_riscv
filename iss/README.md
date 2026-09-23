# `iss/` — VR1 golden ISS（Python 实现的 RV64IMAC 机器模型）

双线方案里的 **软件真值线**。它是 `doc/spec/02`（逐指令行为）与 `doc/spec/10`（CSR/trap）
的**可执行化身**，与 RTL 逐指令退休 trace 比对。当前状态：**骨架可跑，指令覆盖为 RV64I + M 子集**。

## 1. 组成

| 文件 | 职责 | 规格锚点 |
|---|---|---|
| `vriss/consts.py` | 特权模式、异常/中断码、CSR 地址、mstatus 位段与写掩码、PMA 区域表、signature 握手常量 | `doc/spec/00` §4.1/§4.7、`doc/spec/10` |
| `vriss/encode.py` | 六种格式位级编码 + 具名构造器 + 立即数范围检查 + `Image`（bin / `$readmemh`） | `doc/spec/02` |
| `vriss/mem.py` | 稀疏页存储器、PMA 判决、非对齐报 fault、MMIO 设备、CLINT-lite、signature 截获 | `doc/spec/09` |
| `vriss/trace.py` | `RetireRecord`（`rt_t` 的软件化身）、标准 trace CSV、debug CSV、归一化 | `doc/spec/01` §3.21 |
| `vriss/state.py` — | （状态并入 `machine.py`；拆分留待寄存器模型 RAL 对齐时做） | — |
| `vriss/machine.py` | 取指/译码/执行/CSR/trap/MRET/中断主循环 | `doc/spec/02`、`doc/spec/10` |
| `vriss/__main__.py` | CLI：`python -m vriss run/dump` | `AGENTS.md` §3 |
| `tools/trace_compare.py` | 两份 trace 逐指令比对（RTL-vs-ISS 与 ISS-vs-ISS 共用） | `doc/spec/01` §7 |
| `tests/test_smoke.py` | 冒烟：29 条退休、trap/MRET、CSR trace、CSV 口径，全断言 | — |

## 2. 跑法

```bash
# 冒烟（零外部依赖，任何装有 Python 3.11+ 的机器可跑）
python iss/tests/test_smoke.py

# 跑一份镜像并出 trace（bin 与 hex 二选一；hex 与 RTL 共用同一份文件）
cd iss && python -m vriss run --hex sim/prog.hex --csv sim/prog.csv --tohost 0x40000010 --max 2000000
python -m vriss run --bin prog.bin --base 0x40000000 --reset-pc 0x1000 --csv prog.csv --debug

# 两份 trace 比对
python iss/tools/trace_compare.py sim/rtl.csv sim/prog.csv
python iss/tools/trace_compare.py vriss.csv spike.csv --final-only   # 放宽，须登记 doc/verify/05
```

## 3. trace 字段映射（规格 ↔ CSV，唯一权威表）

`doc/spec/01` §3.21 的 `rt_t` 成员 → riscv-dv 标准 trace CSV 列
（列序取 `_tools/riscv-dv-master/scripts/riscv_trace_csv.py` 的
`pc,instr,gpr,csr,binary,mode,instr_str,operand`）：

| `rt_t` 成员 | CSV 列 | 规则 | 参与比对 |
|---|---|---|---|
| `pc` | `pc` | 8 位十六进制，无 `0x` | ✅ |
| `instr` | `binary` | 8 位十六进制原始字 | ✅ |
| `rd_idx`,`rd_data`,`rd_wb_en` | `gpr` | `<abi名>:0x%016x`；`rd_idx==0` 或 `rd_wb_en==0` ⇒ 空串 | ✅ |
| `csr_addr`,`csr_new`,`csr_wr_en` | `csr` | `0x<addr 3位>:0x%016x`，**取写后新值**（与 Spike commit log 同口径，ISS-013）；未写 ⇒ 空串 | ✅ |
| `priv` | `mode` | `PRV_U` / `PRV_S` / `PRV_M` | ✅（可用 `--cols` 关掉） |
| `instr_str`,`operand` | `instr`,`instr_str`,`operand` | 反汇编文本；**默认不比对**（工具自定义文本会造成假 mismatch），需 `--with-asm` 显式开启 | ❌默认 |
| `is_c`,`exc_v`,`exc_cause`,`is_intr`,`is_br` | —（debug 列） | 由 `pc/binary/gpr/csr` 间接可证；异常类用例改比 `--final-only` + `WRITE_GPR` 握手 | ❌ |
| **`cycle`** | `cycle`（仅 `--debug`） | **不参与比对**（时序量，ISS 无流水线概念） | ❌ |
| **`mispred`** | `mispred`（仅 `--debug`） | **不参与比对**（投机信息，ISS 无对应物） | ❌ |
| `seq` | `seq`（仅 `--debug`） | **不参与比对**，仅排序/定位 | ❌ |

比对判据（红线 R8）：默认比 `pc,binary,gpr,csr` 四列，全部由 `normalize_row()` 归一到
"数值等价即等价"；长度不等先报流断裂并按 T1/T5 归因，不逐条硬比。

## 4. signature 握手

程序向 `signature_addr`（本项目取 `0x2000_0000` 窗，PMA 标 non-cacheable）写 64 bit 字：
低 8 位 = `SigType`，其上按类型取载荷（逐值对齐 `_tools/riscv-dv-master/src/riscv_signature_pkg.sv`）：

| 类型 | 载荷位置 | 后续动作 |
|---|---|---|
| `CORE_STATUS=0` | `data[12:8]` = `SigStatus` | ISS 记入 `bus.signature_writes` |
| `TEST_RESULT=1` | `data[8]`：0=PASS 1=FAIL | 程序内自判定用例（CSR 定向测试）走这条 |
| `WRITE_GPR=2` | 后接 32 次写 x0..x31 | 中断/异常现场核对 |
| `WRITE_CSR=3` | `data[19:8]`=CSR 地址，后接 1 次写值 | 同上 |

> `signature_addr` 必须避开随机 data page，否则程序的普通 store 会被当成握手消息（riscv-dv 已知坑）。

## 5. 覆盖状态与 TODO（对着 `doc/spec/02` 逐条清账）

| 块 | 状态 | 依据/阻塞 | 备注 |
| --- | --- | --- | --- |
| RV64I 40 条 | 🟡 执行分支已写全，但**冒烟只跑过其中 ~15 条** | `doc/spec/02` | 不得当“已覆盖”报；待 `tests/test_instr.py` 逐条定向 |
| RV64M 8 条（含除零/溢出定义） | 🟡 冒烟覆盖 MUL/DIV/REM + 除零 | `doc/spec/02` §4 | `MULH/MULHU/MULHSU/DIVU/REMU` 未逐条验证 |
| RV64A（LR/SC + 11 条 AMO） | ❌ 显式 `NotImplementedError` | 等 `doc/spec/02` §6 + `spec/07` reservation 语义冻结 | — |
| RV64C 展开表（64 项） | ❌ 显式 `NotImplementedError` | 等 `doc/spec/02` §5 | — |
| CSR 全集 + WARL 逐位 | 🟡 仅实现用到的 12 个，mstatus 用写掩码近似 | 等 `doc/spec/10` CSR 全表（含 ISS-007 版本裁定） | — |
| medeleg/mideleg 委托 | ❌ 恒进 M | 同上 | — |
| S 态 + SRET | ❌ 显式未实现 | 同上 | — |
| Sv39 翻译（恒 Bare） | ❌ | 等 `doc/spec/08` | — |
| PMP | ❌（只有 PMA 区域表） | 等 `doc/spec/08` | — |
| 中断注入与三条件仲裁 | 🟡 M 侧已实现，S 侧委托未接 | `doc/spec/10` | — |
| 与 Spike 逐指令互检（M1） | ⏸ 未开始 | **阻塞在 ISS-002（WSL 未装）** | — |

## 6. 纪律

- ISS 属**验证代码**：它的 bug 直接修，但必须记 `doc/process/00`（红线 R2/R4）。
- **禁止**为了让 RTL 通过而改 ISS 行为（红线 R6）；两边分歧必须先归因（谁与规范不符）。
- `--final-only` 之类的比对放宽，只允许按 testlist 白名单启用，每次启用记 `doc/verify/05`（红线 R6）。
- 镜像只有一份：`Image.to_bytes()` 与 `to_readmemh()` 必须来自同一次构建（`AGENTS.md` §3.4 坑 2）。
