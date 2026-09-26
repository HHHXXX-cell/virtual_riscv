#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`iss/tools/gen_tb_trace_format.py` — 生成「TB 侧格式」trace 期望件（G1-I `GI-13` 的格式自证件）。

它做什么
--------
用 golden ISS（`iss/vriss`）读 `sim/image/m_smoke.hex`（**一份镜像喂两边**）重跑一遍，拿到逐条
`RetireRecord`，再按 **TB 写出器 `tb/unit/rt_t_trace_writer.sv` 的同一条格式化规则**渲染成
`sim/golden/tb_format_expect.csv`。

为什么需要它（红线 R8：判定必须有显式证据）
------------------------------------------
M1 的 RTL 侧 CSV 由 TB 写出器产出，而写出器的格式化规则写在 SV 里；在 RTL 尚未产出 trace 之前，
唯一能证的"格式契约"是：**同一套规则**把 golden 的 30 条渲染成 TB 侧格式后，与 golden 本身在
默认比对列上 **0 mismatch**（判据 `script/flow.py` → `trace-format-contract` ③）。这样 RTL 侧
CSV 一旦落盘，比对失败即可归因到 RTL/映射实现，而不是"两边格式不一样"这种无法归因的假 mismatch。

TB 侧格式（逐列；与 `iss/vriss/trace.py` 的 `TRACE_CSV_FIELDS` 同列序、同规则）
--------------------------------------------------------------------------
| 列 | 值 | 规则出处 |
|---|---|---|
| `pc` | `%08x` | `trace.py:to_trace_row()` |
| `instr` | **空串** | riscv-dv 该列 = 助记符 = `instr_str`；`rt_t`（spec/01 §3.21）**无文本成员** |
| `gpr` | `<abi名>:0x%016x`；`rd_idx==0` 或 `rd_wb_en==0` ⇒ 空串 | `trace.py:gpr_field()`；名表取 `ABI_NAMES` |
| `csr` | `0x%03x:0x%016x`（**写后新值** `csr_new`）；`csr_wr_en==0` ⇒ 空串 | `trace.py:csr_field()` + ISS-013 |
| `binary` | `%08x` | `trace.py:to_trace_row()` |
| `mode` | `PRV_U`/`PRV_S`/`PRV_M` | `trace.py:_mode_str()` |
| `instr_str` / `operand` | **空串** | 同 `instr`：TB 无反汇编文本来源；三文本列**默认不参与比对** |

三列留空**不是缺省**：`instr_str`/`operand`（及 `instr`）在 `trace_compare.py` 的 `DEFAULT_COLS` 之外，
要开需显式 `--with-asm`（放宽口径，须登记，红线 R6）——本件刻意留空，使 RTL 侧与期望件**同规**。

判据侧怎么用
------------
    python iss/tools/gen_tb_trace_format.py                     # 写 sim/golden/tb_format_expect.csv
    python iss/tools/gen_tb_trace_format.py --out <沙箱路径>     # 漂移复算（判据 ①）
    python iss/tools/trace_compare.py sim/golden/iss_smoke.csv sim/golden/tb_format_expect.csv
                                                                # ⇒ mismatch=0（判据 ③）

本脚本**不放宽任何既有判据**、不改 `iss/**` 既有逻辑（只读引用 `vriss`）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # iss/tools/<file>.py → 仓库根
sys.path.insert(0, str(ROOT / 'iss'))

from vriss import RESET_PC, TRACE_CSV_FIELDS             # noqa: E402
from vriss.machine import VrIss                          # noqa: E402
from vriss.mem import Bus                                # noqa: E402
# `ABI_NAMES`（名表真源）与 `_mode_str`（mode 映射真源）都在 trace.py：前者**刻意复用**——TB 侧
# `gpr` 列的名必须与 golden/Spike 口径逐字一致（判据 `trace-format-contract` ② 会把 SV 里的名表
# 与本表逐项机判）；后者只用于**交叉断言**（本件的 mode 表是本地实现，见 self_check ⑦）。
from vriss.trace import ABI_NAMES, _mode_str             # noqa: E402

IMAGE_HEX = 'sim/image/m_smoke.hex'
OUT_CSV = 'sim/golden/tb_format_expect.csv'
TOHOST = 0x4000_0010            # `iss/tests/test_smoke.py:TOHOST`（riscv-tests 停机点）
SIGWIN = 0x2000_0000            # signature 窗（避开随机 data page；iss/README.md §4）
MAX_INSTR = 100_000             # 本镜像 30 条退休 ⇒ 该上限只作 watchdog 兜底

# `mode` 列映射：**本地成表**（不从 trace.py 借）——这样"本地规则 vs 真源"才能互证（见 self_check）
MODE_STR = {0: 'PRV_U', 1: 'PRV_S', 3: 'PRV_M'}


def _mode(priv: int) -> str:
    """trace.py `_mode_str()` 的本地实现（含未定义 priv 的 `PRV_?<n>` 分支）。"""
    return MODE_STR.get(priv, 'PRV_?%d' % priv)


def tb_row(rec) -> list[str]:
    """把一条 `RetireRecord` 渲染成 TB 侧格式的 8 列（规则表见模块 docstring）。"""
    gpr = '' if (not rec.rd_wb_en or rec.rd_idx == 0) else '%s:0x%016x' % (ABI_NAMES[rec.rd_idx], rec.rd_data)
    csr = '' if not rec.csr_wr_en else '0x%03x:0x%016x' % (rec.csr_addr, rec.csr_new)
    return [
        '%08x' % rec.pc,        # pc
        '',                     # instr（助记符列：TB 无来源 ⇒ 空串）
        gpr,                    # gpr
        csr,                    # csr（写后新值）
        '%08x' % rec.instr,     # binary
        _mode(rec.priv),        # mode
        '',                     # instr_str（文本列：空串）
        '',                     # operand（文本列：空串）
    ]


def render(recs) -> str:
    """整件 CSV 文本（与 `trace.py:TraceWriter` 同款：csv 默认 dialect ⇒ 行尾 CRLF、无表头外加）。"""
    import io
    buf = io.StringIO(newline='')
    w = csv.writer(buf)                       # 默认 lineterminator='\r\n'（= $fwrite 在文本模式的落盘结果）
    w.writerow(TRACE_CSV_FIELDS)
    for r in recs:
        w.writerow(tb_row(r))
    return buf.getvalue()


def run_image(hex_path: Path, tohost: int, max_instr: int):
    """读 `$readmemh` 镜像跑 golden ISS（与 P3 步骤同口径：同一份 .hex 喂两边）。"""
    bus = Bus(signature_addr=SIGWIN)
    bus.load_readmemh(str(hex_path))
    iss = VrIss(bus=bus, reset_pc=RESET_PC, tohost_addr=tohost)
    n, recs = iss.run(max_instr=max_instr)
    return iss, n, recs


def self_check(iss, n, recs, text: str, hex_rel: str) -> list[str]:
    """本件自身的断言（fail-closed；每条返回一行 ASCII 证据）。"""
    out = []
    # ① 停机语义（riscv-tests：tohost 写 1 = PASS）
    if not iss.halted:
        raise AssertionError('未停机：tohost 写未被识别（trace 会被截断，期望件不可用）')
    if iss.halt_val != 1:
        raise AssertionError('halt_val=0x%x != 1（riscv-tests 语义：非 1 即 FAIL 编码 (testnum<<1)|1）'
                             % (iss.halt_val or 0))
    out.append('[tb_format_expect] hex=%s retired=%d halted=True halt_val=0x%x max_instr=%d'
               % (hex_rel, n, iss.halt_val, MAX_INSTR))
    # ② 表头逐字 == TRACE_CSV_FIELDS
    lines = text.splitlines()
    if lines[0].split(',') != TRACE_CSV_FIELDS:
        raise AssertionError('表头 %r != TRACE_CSV_FIELDS %r' % (lines[0], TRACE_CSV_FIELDS))
    out.append('[tb_format_expect] header==TRACE_CSV_FIELDS cols=%d %s'
               % (len(TRACE_CSV_FIELDS), ','.join(TRACE_CSV_FIELDS)))
    # ③ 行数 == ISS 退休条数（自洽；golden 的 30 条由判据 ①②③ 共同钉住）
    if len(lines) - 1 != n or len(recs) != n:
        raise AssertionError('行数 %d / 记录 %d != 退休条数 %d' % (len(lines) - 1, len(recs), n))
    # ④ 逐行交叉核对：本件的 4 个比对列 == `trace.py:to_trace_row()` 的同名列（两实现互证）
    bad = 0
    for i, r in enumerate(recs):
        ref = r.to_trace_row()
        mine = dict(zip(TRACE_CSV_FIELDS, tb_row(r)))
        for col in ('pc', 'binary', 'gpr', 'csr'):
            if mine[col] != ref[col]:
                bad += 1
                if bad <= 4:
                    print('  [MISMATCH] @%d %s: 本件 %r != trace.py %r' % (i, col, mine[col], ref[col]))
    if bad:
        raise AssertionError('与 trace.py 的打包规则不一致 %d 处（本件规则须逐字同源）' % bad)
    out.append('[tb_format_expect] cross-check vs trace.py:to_trace_row rows=%d cols=[pc,binary,gpr,csr] mismatch=0'
               % len(recs))
    # ⑤ 三文本列恒为空（TB 无来源；若将来要填，须走 --with-asm 的登记流程，不许悄悄填）
    text_cols = set()
    for r in recs:
        for col in ('instr', 'instr_str', 'operand'):
            text_cols.add(dict(zip(TRACE_CSV_FIELDS, tb_row(r)))[col])
    if text_cols != {''}:
        raise AssertionError('文本列 %r 非空（TB 侧无反汇编来源，须恒为空串）' % sorted(text_cols))
    # ⑥ 逐字节同规：任一单元格含 `,`/`"` 都会让 csv 写出加引号，而 `$fwrite` 不会 ⇒ 静默破坏"两件同规"
    for i, r in enumerate(recs):
        for c in tb_row(r):
            if ',' in c or '"' in c or '\n' in c:
                raise AssertionError('第 %d 行有需转义的单元格 %r：$fwrite 无法复现 csv 的引号规则' % (i, c))
    # ⑦ `mode` 映射与真源逐值互证（本地表 vs trace.py:_mode_str）
    for p in (0, 1, 3):
        if _mode(p) != _mode_str(p):
            raise AssertionError('mode 映射与 trace.py:_mode_str(%d) 不一致' % p)
    out.append('[tb_format_expect] mode map==trace.py:_mode_str(0/1/3); text cols empty; no cell needs quoting')
    return out


IMAGE_REL = IMAGE_HEX


def build(hex_path: Path, tohost: int, max_instr: int, hex_rel: str = IMAGE_HEX):
    """返回 (text, evidence lines)。"""
    iss, n, recs = run_image(hex_path, tohost, max_instr)
    text = render(recs)
    ev = self_check(iss, n, recs, text, hex_rel)
    return text, ev


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description='生成 TB 侧格式的 trace 期望件（G1-I GI-13）')
    p.add_argument('--hex', default=IMAGE_HEX, help='golden 镜像（$readmemh，与 RTL 共用同一份）')
    p.add_argument('--out', default=OUT_CSV, help='输出 CSV（默认 sim/golden/tb_format_expect.csv）')
    p.add_argument('--tohost', type=lambda s: int(s, 0), default=TOHOST)
    p.add_argument('--max', type=int, default=MAX_INSTR)
    args = p.parse_args(argv)

    hex_rel = args.hex.replace('\\', '/')
    hex_path = (ROOT / args.hex) if not Path(args.hex).is_absolute() else Path(args.hex)
    out_path = (ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    if not hex_path.exists():
        print('[FAIL] tb_format_expect: 缺镜像 %s（先跑 sw/tests/gen_smoke_image.py）' % hex_rel)
        return 2
    try:
        text, ev = build(hex_path, args.tohost, args.max, hex_rel)
    except AssertionError as exc:
        print('[FAIL] tb_format_expect: %s' % exc)
        return 1
    for ln in ev:
        print(ln)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, 'w', encoding='utf-8', newline='') as f:
        f.write(text)
    md5 = hashlib.md5(text.encode('utf-8')).hexdigest()
    rows = len(text.splitlines()) - 1
    print('[tb_format_expect] wrote %s rows=%d md5=%s'
          % (args.out.replace('\\', '/'), rows, md5))
    print('[PASS] tb_format_expect: TB 侧格式期望件已生成（rows=%d，表头==TRACE_CSV_FIELDS，'
          '与 trace.py 打包规则 0 mismatch；比对判据见 trace-format-contract ③）' % rows)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
