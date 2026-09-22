#!/usr/bin/env python3
"""两份 trace CSV 的逐指令比对器（RTL-vs-ISS 与 ISS-vs-ISS 共用）。

判据口径（务必读）：
- 默认比对列 `pc,binary,gpr,csr`。`csr` 取**写后新值**（与 Spike commit log 同口径，doc/00 ISS-013）。
- `instr_str`/`operand` **默认不比对**：反汇编文本是工具自定义的（Spike 与 vriss 的助记符、
  操作数排布不同），拿它当判据会制造大量假 mismatch。要开需显式 `--with-asm`。
- `--final-only` 是 riscv-dv `compare_final_value_only` 的对应物，**只允许按 testlist 白名单启用，
  每次启用必须记 `doc/05-回归记录.md`**（红线 R6：放宽比对视同 Review 级变更）。
- 长度不等、或第 N 条起 pc 不对齐 → 先报"流断裂"，按回归终止判据 T1/T5 处置，不逐条硬比。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vriss.trace import normalize_row, read_trace_csv  # noqa: E402

DEFAULT_COLS = ["pc", "binary", "gpr", "csr"]
ASM_COLS = ["instr_str", "operand"]


def _final_state(rows: list[dict[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    gpr: dict[str, str] = {}
    csr: dict[str, str] = {}
    for r in rows:
        for bucket, key in ((gpr, "gpr"), (csr, "csr")):
            field = r.get(key, "") or ""
            for item in field.split(","):
                name, sep, val = item.partition(":")
                if sep and name.strip():
                    bucket[name.strip().lower()] = val.strip()
    return gpr, csr


def compare(path_a: str, path_b: str, cols: list[str], final_only: bool,
            misalign_limit: int = 4) -> int:
    a = [normalize_row(r) for r in read_trace_csv(path_a)]
    b = [normalize_row(r) for r in read_trace_csv(path_b)]

    if final_only:
        ga, ca = _final_state(a)
        gb, cb = _final_state(b)
        bad = 0
        for k in sorted(set(ga) | set(gb)):
            if ga.get(k, "") != gb.get(k, ""):
                print(f"MISMATCH gpr[{k}]: {ga.get(k)!r} != {gb.get(k)!r}")
                bad += 1
        for k in sorted(set(ca) | set(cb)):
            if ca.get(k, "") != cb.get(k, ""):
                print(f"MISMATCH csr[{k}]: {ca.get(k)!r} != {cb.get(k)!r}")
                bad += 1
        print(f"[trace_compare] final-only 模式：{len(a)} vs {len(b)} 条，"
              f"gpr={len(ga)}/{len(gb)} csr={len(ca)}/{len(cb)}，mismatch={bad}")
        print("!! 该模式为比对放宽，须在 doc/05 记录启用原因（红线 R6）")
        return 1 if bad else 0

    n = min(len(a), len(b))
    if len(a) != len(b):
        print(f"[warn] 两条 trace 长度不等：{path_a}={len(a)} {path_b}={len(b)}"
              f"（可能是流断裂，优先按 T1/T5 判环境/激励问题而非 DUT bug）")
    bad = 0
    for i in range(n):
        for c in cols:
            if a[i].get(c, "") != b[i].get(c, ""):
                bad += 1
                print(f"MISMATCH @{i} {c}:\n  {path_a}: {a[i].get(c,'')!r}\n"
                      f"  {path_b}: {b[i].get(c,'')!r}\n  pc={a[i].get('pc')}")
                if bad >= misalign_limit:
                    print(f"[abort] 累计 {bad} 处不一致，停止逐条比对（先定位首处根因）")
                    return 1
                break
    print(f"[trace_compare] 比对 {n} 条 × 列 {cols}，mismatch={bad}")
    return 1 if bad or len(a) != len(b) else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="RISC-V trace CSV 逐指令比对")
    p.add_argument("csv_a")
    p.add_argument("csv_b")
    p.add_argument("--cols", default=",".join(DEFAULT_COLS),
                   help=f"逗号分隔比对列，默认 {','.join(DEFAULT_COLS)}")
    p.add_argument("--with-asm", action="store_true",
                   help="额外比对 instr_str/operand（默认关闭，见模块 docstring）")
    p.add_argument("--final-only", action="store_true", help="只比最终值（放宽，须登记）")
    p.add_argument("--misalign-limit", type=int, default=4)
    args = p.parse_args(argv)
    cols = [c.strip() for c in args.cols.split(",") if c.strip()]
    if args.with_asm:
        cols += ASM_COLS
    return compare(args.csv_a, args.csv_b, cols, args.final_only, args.misalign_limit)


if __name__ == "__main__":
    raise SystemExit(main())
