#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""script/tools/vcover_zeros_diff.py —— vcover `-details -code sbcef -zeros` 转储的**零项差集工具**。

用途（M3-(a) 覆盖缺口闭环的机械面；防"手抄未命中项"）：
  给定两份 `vcover report -details -code sbcef -zeros <batch>.ucdb` 的输出，抽出全部 `***0***`
  未命中项（按实例/类分组、带源码行号与项名），输出 **CLOSED（before 有、after 无 ⇒ 本轮变可达）**
  与 **STILL（after 仍有）** 两个差集。

来历（可追溯）：2026-09-26 心跳第 15 轮（ISS-128 消解批）落于 `script/tmp/`，本轮归档到
`script/tools/`（同心跳第 11 轮的归档口径）；当时证据落
`sim/run_cover_m3cov_r5/zeros_diff_r4_r5.txt`（CLOSED 4 项＝`vr1_decode.sv` 516／523／613×2）。

两种输出格式都要收（vcover 2020.4 实测）：
  ① 分支/语句：`    <line>   <item>   ***0***`
  ② 条件/表达式「Focused View」：`Row N:  ***0***  <term>  <non-masking>`，其行号来自
     同段上方的 `Line  <n> Item  <m>  (<expr>)` 头。

用法（仓库根）：
    D:\\modeltech64_2020.4\\win64\\vcover.exe report -details -code sbcef -zeros sim/covdb/<A>.ucdb > before.txt
    D:\\modeltech64_2020.4\\win64\\vcover.exe report -details -code sbcef -zeros sim/covdb/<B>.ucdb > after.txt
    python script/tools/vcover_zeros_diff.py before.txt after.txt

纪律：只读转储、只打印差集；**不产通过结论**（判定仍归 `script/flow.py` 的 `m3-code-cov`）。
"""
import io
import re
import sys

RE_INST = re.compile(r'^=== Instance: (\S+)')
RE_KIND = re.compile(r'^----------+(\w+)\s+(Condition|Branch|Statement|Expression|FSM\w*)\s*----')
RE_HDR = re.compile(r'^Line\s+(\d+)\s+Item\s+(\d+)\s*(.*)$')
RE_ZERO = re.compile(r'^\s*(\d+)\s+(\d+)\s+\*\*\*0\*\*\*')
RE_ROW0 = re.compile(r'^\s*Row\s+\d+:\s+\*\*\*0\*\*\*\s+(\S+)')


def grab(path):
    """抽出全部零项：键＝(实例, 类, 行号, 项名/项号)。"""
    out = {}
    inst, kind, line = '?', '?', 0
    for ln in io.open(path, encoding='utf-8', errors='replace'):
        m = RE_INST.match(ln)
        if m:
            inst = m.group(1)
            continue
        m = RE_KIND.match(ln)
        if m:
            kind = m.group(2)
            continue
        m = RE_HDR.match(ln)
        if m:
            line = int(m.group(1))
            continue
        m = RE_ZERO.match(ln)
        if m:
            out[(inst, kind, int(m.group(1)), 'item%s' % m.group(2))] = True
            continue
        m = RE_ROW0.match(ln)
        if m:
            out[(inst, kind, line, m.group(1))] = True
    return out


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    b, a = grab(sys.argv[1]), grab(sys.argv[2])
    gone, still = sorted(set(b) - set(a)), sorted(set(a) - set(b))
    print('BEFORE %d items  AFTER %d items' % (len(b), len(a)))
    print('--- CLOSED（before 有、after 无；本轮变可达）%d ---' % len(gone))
    for x in gone:
        print('  %-40s %-11s line %-5d %s' % (x[0], x[1], x[2], x[3]))
    print('--- STILL（after 仍有）%d ---' % len(still))
    for x in still:
        print('  %-40s %-11s line %-5d %s' % (x[0], x[1], x[2], x[3]))
    return 1 if still else 0


if __name__ == '__main__':
    raise SystemExit(main())
