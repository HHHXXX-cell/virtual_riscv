#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""width_check.py — 从 struct 成员表实算位宽，对撞文档里声明的合计值

为什么要有它：ISS-018 的根因是"作者声称逐项相加核对过，但从未加过"，13 个 struct 里
12 个合计与成员不符（差 1~34 bit）。凡可机器判定的量，一律不许靠人算或靠声明。

用法：
  python script/width_check.py            全篇差异表
  python script/width_check.py --json     机读输出（供 gate.py / CI 用）
  python script/width_check.py uop_t      只看某个 struct 的逐项明细

判定口径：
  成员宽度列取整数；`log2(N)`→N 的位宽；`[a:b]`→a-b+1；带 `×2`/多名字合并行等无法单值解析的，
  一律记 UNRESOLVED 并**不计入和**——宁可报"算不了"，也不许猜一个数凑平。
"""
import io
import json
import os
import re
import sys

try:                                        # 保留控制台原编码，只对打不出的字符容错；
    sys.stdout.reconfigure(errors='replace')      # 强行改 utf-8 反而会在 gbk 控制台造成乱码
except Exception:
    pass
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
SPEC01 = os.path.join(ROOT, 'doc', 'spec', '01-流水线与寄存器接口.md')
SPEC00 = os.path.join(ROOT, 'doc', 'spec', '00-总体规格.md')
HEAD3 = re.compile(r'^###\s+3\.\d+[a-z]?\s+`([A-Za-z_0-9]+)`')
HEAD4 = re.compile(r'^####\s+`([A-Za-z_0-9]+)`')      # 同节多 struct 时用 h4 分块，保证“一节一 struct 一合计”
CLAIM_NUM = re.compile(r'([\d,]+)\s*(?:bit|b)\b')


def params():
    """从 spec/00 §4 参数表取整数参数，供成员列里的参数名求值。"""
    out = {}
    if not os.path.exists(SPEC00):
        return out
    for line in io.open(SPEC00, encoding='utf-8', errors='replace').read().splitlines():
        m = re.match(r'\|\s*`([A-Z0-9_]+)`\s*\|\s*\**([0-9]+)', line)
        if m:
            out[m.group(1)] = int(m.group(2))
    return out


def member_width(cell, P):
    """返回 (int 或 None, 说明)"""
    s = cell.strip().strip('*').strip()
    if not s:
        return None, '空'
    if re.fullmatch(r'\d+', s):
        return int(s), ''
    # 合并行/增量行：'64+64'、'2+1+1+1+1'、'1+6'、'+2' —— 纯数字加法求和，不做语义猜测
    if re.fullmatch(r'[+\d\s]+', s) and any(ch.isdigit() for ch in s):
        return sum(int(x) for x in re.findall(r'\d+', s)), '数值求和'
    m = re.fullmatch(r'(\d+)\s*[×x*]\s*(\d+)', s)      # 如 entry_pc[7:0][39:0] 写 8×40
    if m:
        return int(m.group(1)) * int(m.group(2)), '乘积求值'
    m = re.fullmatch(r'log2\((\d+)\)', s)
    if m:
        n = int(m.group(1))
        w, v = 0, n - 1
        while v:
            w += 1
            v >>= 1
        return w, 'log2 求值'
    m = re.fullmatch(r'\[(\d+):(\d+)\]', s)
    if m:
        return abs(int(m.group(1)) - int(m.group(2))) + 1, '位区间'
    if s in P:
        return P[s], '取自 spec/00 参数'
    m = re.search(r'(\d+)\s*bit', s)
    if m and ('/' in s or '、' in s or '×' in s or '（' in s):
        return None, '复合格式（多名字/乘倍），拒绝猜测'
    if m:
        return int(m.group(1)), '从文字提取'
    return None, '无法解析'


def parse():
    txt = io.open(SPEC01, encoding='utf-8', errors='replace').read().splitlines()
    P = params()
    structs, cur = [], None
    for ln, line in enumerate(txt, 1):
        h = HEAD3.match(line) or HEAD4.match(line)
        if h:
            cur = {'name': h.group(1), 'head': ln, 'head_txt': line.strip(),
                   'members': [], 'claims': [], 'sum_expr': None}
            structs.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith('#'):              # 任何非 struct 标题 = 本节结束
            cur = None
            continue
        if line.startswith('|'):
            c = [x.strip() for x in line.split('|')]
            if len(c) < 4 or set(''.join(c)) <= set('-: '):
                continue
            fname = c[1].strip('`* ')
            if not fname or fname in ('字段', '成员') or fname.startswith('---'):
                continue
            if c[2].strip('`* ') in ('位宽', '宽度'):      # 表头行（如 `| 变化 | 位宽 | 说明 |`）
                continue
            w, note = member_width(c[2], P)
            cur['members'].append({'field': fname, 'declared': c[2], 'width': w,
                                   'note': note, 'line': ln})
            continue
        m = re.search(r'合计[^\n]*?=\s*([\d+\s]+?)\s*=*\s*\**([\d,]+)\s*bit', line)
        if m:
            cur['sum_expr'] = (m.group(1), ln)
        # 声明值只从 `合计` 行取：陈述句里出现的 `16bit 槽`/`32bit 槽` 这类词不算声明
        # （旧写法曾把它们当成声明，造出 fetch_raw_t 的假 MISMATCH）。
        # 紧跟乘号的数（`136 bit × 128 = 17,408 bit`）是例化总量，不计入 struct 自身合计。
        if line.strip().startswith('合计'):
            for cm in CLAIM_NUM.finditer(line):
                if '×' in line[max(0, cm.start() - 14):cm.start()]:
                    continue
                cur['claims'].append({'value': int(cm.group(1).replace(',', '')),
                                      'line': ln, 'text': line.strip()[:78]})
    return structs


def main():
    only = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith('--') else None
    structs = parse()
    rows = []
    for s in structs:
        ok = [m for m in s['members'] if m['width'] is not None]
        bad = [m for m in s['members'] if m['width'] is None]
        total = sum(m['width'] for m in ok)
        claims = sorted({c['value'] for c in s['claims']})
        # 判定口径：有成员宽度未能解析时，不得判 OK——“看起来相等”很可能是漏算凑出来的
        # （实测例：rob_entry_t 成员和 122 + 2 个未解析 = 135，与 R7 报的值一致；若不去重
        #  这个未解析就会造出一个假 PASS，比人算错更危险）。
        if not s['members']:
            verdict = 'NO-TABLE'
        elif bad:
            verdict = 'UNVERIFIED'
        elif not claims:
            verdict = 'NO-CLAIM'
        elif claims == [total]:
            verdict = 'OK'
        else:
            verdict = 'MISMATCH'
        rows.append({'struct': s['name'], 'head_line': s['head'], 'members': len(s['members']),
                     'resolved': len(ok), 'unresolved': len(bad), 'sum_computed': total,
                     'claims': claims, 'verdict': verdict})
        if only and s['name'] != only:
            continue
    if '--json' in sys.argv:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 1 if any(r['verdict'] == 'MISMATCH' for r in rows) else 0

    print('== struct 位宽实算 vs 文档声明 ==')
    print('%-16s %6s %6s %8s %-22s %s' % ('struct', '成员', '未解析', '实算和', '文档声明值', '判定'))
    for r in rows:
        if only and r['struct'] != only:
            continue
        print('%-16s %6d %6d %8d %-22s %s' % (r['struct'], r['members'], r['unresolved'],
                                               r['sum_computed'], ','.join(map(str, r['claims'])),
                                               r['verdict']))
    mis = [r for r in rows if r['verdict'] in ('MISMATCH', 'UNVERIFIED', 'NO-TABLE')]
    print('\n合计 %d 个 struct：可机器核对=%d，不符=%d，未能核实=%d'
          % (len(rows), len(rows) - len(mis),
             len([r for r in rows if r['verdict'] == 'MISMATCH']),
             len([r for r in rows if r['verdict'] in ('UNVERIFIED', 'NO-TABLE')])))
    if mis:
        print('\n== 差异明细（返工时逐条消）==')
        for r in mis:
            delta = [c - r['sum_computed'] for c in r['claims']]
            print('  %-14s L%-4d 实算 %4d  声明 %-12s %-11s 差 %s' %
                  (r['struct'], r['head_line'], r['sum_computed'],
                   ','.join(map(str, r['claims'])) or '-', r['verdict'],
                   ','.join(map(str, delta)) or '-'))
            if r['unresolved']:
                print('        └ 另有 %d 个成员宽度无法单值解析，未计入和（需人工定值）' % r['unresolved'])
            if r['verdict'] == 'NO-TABLE':
                print('        └ 本节无逐成员位宽表（只有行内算式），不可机器核对 —— 属 Q1/Q9 待落实项')
    if only:
        s = [x for x in parse() if x['name'] == only]
        if s:
            print('\n== %s 逐项 ==' % only)
            for m in s[0]['members']:
                print('  L%-4d %-26s %-14s -> %s %s' % (m['line'], m['field'][:26], m['declared'][:14],
                                                         m['width'] if m['width'] is not None else 'UNRESOLVED',
                                                         m['note']))
    return 1 if mis else 0


if __name__ == '__main__':
    sys.exit(main())
