#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_if_split.py — ADR-P-2 切分表（if_split.json）的独立自检器。

判据（全部为硬判据，任一不过即 FAIL）：
  C1 键集：if_split.json 的 struct 键集 == script/width_check.py --json 的 struct 清单（不含 @ 前缀伪项）。
  C2 行数守恒：每 struct 的切分行数 == 该 struct 的「非标量成员行」数（名字非合法 SV 标识符或位宽解析不出）。
  C3 行级位宽：第 i 行的 net（= Σfields.width − Σreplaces.width）== width_check 对第 i 行的独立实算值。
  C4 ——**已退役（本项不再判定，见下）**。原判据＝「已生成标量字段位宽 + Σ行 net == width_check 的 sum_computed」。
     退役理由：生成器（`script/flow.py` 的 `render_types`）已**消费本表**把 29 处非标量行落成真实字段声明，
     故生成件里的标量字段位宽**本身已含切分结果**——再叠加一次「切分 net」＝同一批位量的**双重计量**
     （实例：`ftq_entry_t` 已生成 145 与切分 net 143 相加得 288 ≠ 145）。该恒等式在此口径下**必然为假**，
     且**不是**产品缺陷，故按"退役"处理而非放宽阈值。
     **职能交接**：全篇恒等式的现行承担者＝`script/flow.py` 的判据 `types-width-consistency`
     （「生成宽度 == width_check 独立复算，**差额==0 即 OK**」；含 28 个 struct 的差额清单与不透明兜底 fail-closed）。
     本项仅保留**缺表/无法解析时的 fail-closed**：`if_split.json` 缺失/坏 JSON ⇒ C0 FAIL；C1 键集不全、
     C2 行数/顺序不符、行级无对应行 ⇒ FAIL（表一旦被消费方读不到或对不上，必须红）。
     运行输出仍打印「已生成标量／切分 net／生成−复算差额」三列，**仅供人读对照，不作判据**。
  C5 R2 展开等式：`= X` 行的 fields 必须逐字段等于 X 的「已解析字段序」（X 自身标量字段 + X 自身已切分字段），
     名字与位宽、顺序全等。
  C6 命名合法：所有 fields/replaces 的名字必须是合法 SV 标识符且不在 SV 保留字集合内。

用法： python doc/decisions/check_if_split.py          （末行 = 机判结论）
"""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys

try:
    sys.stdout.reconfigure(errors='replace')
except Exception:
    pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SPLIT = os.path.join(ROOT, 'doc', 'decisions', 'if_split.json')
TYPES_SVH = os.path.join(ROOT, 'rtl', 'vr1', 'include', 'vr1_types.svh')

IDENT_OK = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
# 与 script/flow.py 的 SV_KEYWORDS 同源（此处只用于判非法命名；两处集合若漂移，本项会报出差异）
SV_KEYWORDS = {'super', 'this', 'type', 'bit', 'byte', 'int', 'integer', 'logic', 'reg', 'wire',
               'time', 'event', 'real', 'shortint', 'longint', 'void', 'class', 'end', 'local',
               'static', 'const', 'ref', 'input', 'output', 'inout', 'do', 'for', 'if', 'case',
               'wait', 'table', 'primitive', 'module', 'package', 'interface', 'program', 'alias',
               'always', 'assign', 'begin', 'break', 'continue', 'default', 'disable', 'enum',
               'export', 'extern', 'final', 'function', 'generate', 'genvar', 'import', 'initial',
               'typedef', 'union', 'struct', 'unique', 'priority', 'signed', 'unsigned', 'return'}


def norm(s):
    """名字归一：去反引号/星号、压空白——用于「字段列原文」与解析件的对账。"""
    return re.sub(r'\s+', ' ', s.replace('`', '').replace('*', '')).strip()


def load_json(p):
    return json.loads(io.open(p, encoding='utf-8').read())


def wc_rows():
    """width_check --json（子进程，published 形态）：{struct: row}。"""
    out = subprocess.run([sys.executable, 'script/width_check.py', '--json'],
                         cwd=ROOT, capture_output=True)
    t = out.stdout.decode('utf-8', 'replace')
    i, j = t.find('['), t.rfind(']')
    if i < 0 or j < i:
        raise SystemExit('FAIL: width_check --json 无输出')
    return {r['struct']: r for r in json.loads(t[i:j + 1])}


def wc_members():
    """width_check.parse() 的逐成员行（同一解析器，第二入口）：{struct: [member,...]}。"""
    sys.path.insert(0, os.path.join(ROOT, 'script'))
    import width_check
    return {s['name']: s['members'] for s in width_check.parse()}


def is_nonscalar(m):
    return m['width'] is None or not IDENT_OK.match(m['field'])


def gen_widths():
    """读磁盘 vr1_types.svh：{struct: (标量字段位宽和, 兜底不透明位宽)}。"""
    gen, opaque, name = {}, {}, None
    block = re.compile(r'^// ---- spec/01 §3 L\d+ `([A-Za-z_0-9]+)`')
    field = re.compile(r'^\s+logic \[(\d+):(\d+)\] ')
    opaq = re.compile(r'^typedef logic \[(\d+):(\d+)\] ([A-Za-z_0-9]+);')
    for ln in io.open(TYPES_SVH, encoding='utf-8').read().splitlines():
        m = block.match(ln)
        if m:
            name = m.group(1)
            gen.setdefault(name, 0)
            opaque.setdefault(name, 0)
            continue
        if name is None:
            continue
        m = field.match(ln)
        if m:
            gen[name] += abs(int(m.group(1)) - int(m.group(2))) + 1
            continue
        m = opaq.match(ln)
        if m:
            opaque[name] = abs(int(m.group(1)) - int(m.group(2))) + 1
    return gen, opaque


def expand(ref, members, split, depth=0):
    """把 struct ref 展开成「字段序」：标量字段原样 + 非标量行按切分表展开（替换行扣除 replaces）。"""
    if depth > 3:
        raise SystemExit('FAIL: R2 展开递归过深（环？）')
    seq = []
    for m in members.get(ref, []):
        if not is_nonscalar(m):
            seq.append((m['field'], m['width']))
            continue
        hit = [r for r in split.get(ref, []) if norm(r['raw']) == norm(m['field'])]
        if not hit:
            raise SystemExit('FAIL: %s 的非标量行 %r 在切分表中无对应行' % (ref, m['field']))
        r = hit[0]
        if r['rule'] == 'R2':
            seq.extend(expand(r['expand'], members, split, depth + 1))
        else:
            rep = {x['name'] for x in r.get('replaces', [])}
            seq = [x for x in seq if x[0] not in rep]
            seq.extend((f['name'], f['width']) for f in r['fields'])
    return seq


def main():
    if not os.path.exists(SPLIT):
        print('FAIL C0 切分表缺失：%s（fail-closed：消费方读不到表即红）' % SPLIT)
        print('---- check_if_split: FAIL（1 项） ----')
        return 1
    try:
        split = load_json(SPLIT)
    except Exception as e:                                          # noqa: BLE001
        print('FAIL C0 切分表无法解析：%s（%s）' % (SPLIT, e))
        print('---- check_if_split: FAIL（1 项） ----')
        return 1
    keys = [k for k in split if not k.startswith('_')]
    ref = wc_rows()
    want = [k for k in ref if not k.startswith('@')]
    mem = wc_members()
    gen, opaque = gen_widths()
    fails, warns, table = [], [], []
    n_row = 0                                # C3 行级实算覆盖的行数（供末行结论）

    # C1 键集
    if set(keys) != set(want):
        fails.append('C1 键集不符：缺 %s／多 %s'
                     % (sorted(set(want) - set(keys)), sorted(set(keys) - set(want))))
    # C6 命名合法（先做，便于后续展开）
    for s in keys:
        for r in split[s]:
            for f in list(r['fields']) + list(r.get('replaces', [])):
                if not IDENT_OK.match(f['name']):
                    fails.append('C6 %s 字段名非法：%r' % (s, f['name']))
                elif f['name'] in SV_KEYWORDS:
                    fails.append('C6 %s 字段名撞 SV 保留字：%r' % (s, f['name']))

    for s in want:
        rows = split.get(s, [])
        ns = [m for m in mem.get(s, []) if is_nonscalar(m)]
        # C2 行数守恒 + 顺序对账（raw 归一后逐行相等）
        if len(rows) != len(ns):
            fails.append('C2 %s 切分行 %d ≠ 非标量行 %d' % (s, len(rows), len(ns)))
        else:
            for i, (r, m) in enumerate(zip(rows, ns), 1):
                if norm(r['raw']) != norm(m['field']):
                    fails.append('C2 %s 第 %d 行原文不符：表 %r ≠ 文档 %r'
                                 % (s, i, norm(r['raw']), norm(m['field'])))
        # C3 行级位宽（net == 独立实算）
        net = 0
        for i, r in enumerate(rows, 1):
            fsum = sum(f['width'] for f in r['fields'])
            if fsum != r['width_total']:
                fails.append('C3 %s 第 %d 行 width_total %d ≠ Σfields %d'
                             % (s, i, r['width_total'], fsum))
            rsum = sum(f['width'] for f in r.get('replaces', []))
            if r.get('net', fsum - rsum) != fsum - rsum:
                fails.append('C3 %s 第 %d 行 net 字段与 Σfields−Σreplaces 不符' % (s, i))
            net += fsum - rsum
            if i <= len(ns) and ns[i - 1]['width'] is not None and (fsum - rsum) != ns[i - 1]['width']:
                fails.append('C3 %s 第 %d 行 net %d ≠ width_check 实算 %d'
                             % (s, i, fsum - rsum, ns[i - 1]['width']))
            elif i <= len(ns) and ns[i - 1]['width'] is not None:
                n_row += 1
        # C4 已退役：只算三列供人读对照，**不作判据**（判定归 script/flow.py 的 types-width-consistency）
        g, gA = gen.get(s, 0), gen.get(s, 0) + opaque.get(s, 0)
        tot = ref[s]['sum_computed']
        table.append((s, len(rows), g, net, tot, gA, g - tot))

    # C5 R2 展开等式
    for s in keys:
        for r in split[s]:
            if r['rule'] != 'R2':
                continue
            exp = expand(s, mem, split)
            # 只校验被复用 struct 自身的字段序（去掉本 struct 自身的 replaces 影响）
            rep = {x['name'] for x in r.get('replaces', [])}
            exp = [x for x in exp if x[0] not in rep]
            got = [(f['name'], f['width']) for f in r['fields']]
            # 复用行的 fields 应 == 被复用 struct 的字段序（不含本 struct 追加行）
            sub = expand(r['expand'], mem, split)
            if got != sub:
                fails.append('C5 %s `= %s` 展开不符：表 %s ≠ %s'
                             % (s, r['expand'], got[:6], sub[:6]))

    print('== ADR-P-2 切分表自检（if_split.json vs width_check 独立复算）==')
    print('判据 C1 键集／C2 行数＋顺序／C3 行级位宽／C5 R2 展开／C6 命名合法；'
          '**C4 已退役**（全篇恒等式职能交 script/flow.py 的 types-width-consistency）。')
    print('%-16s %5s %9s %8s %8s %9s %s' % ('struct', '切分行', '已生成标量', '切分net',
                                            'sum计算', '口径A兜底', '生成−复算*'))
    for t in table:
        print('%-16s %5d %9d %8d %8d %9d %+d' % t)
    print('* 末列与「已生成标量」为**只报告**列（C4 退役后不作判据）：生成器已消费本表，故「已生成标量」'
          '含切分结果、与 sum_computed 应相等（差额 0）；判定见 `python script/flow.py check` 的 types-width-consistency。')
    print('')
    if warns:
        for w in warns:
            print('WARN %s' % w)
    if fails:
        for f in fails:
            print('FAIL %s' % f)
        print('---- check_if_split: FAIL（%d 项） ----' % len(fails))
        return 1
    print('---- check_if_split: PASS（C1/C2/C3/C5/C6 全过；C4 已退役 → 交 script/flow.py '
          'types-width-consistency；行级 %d/%d 行与 width_check 逐行一致）----' % (n_row, n_row))
    return 0


if __name__ == '__main__':
    sys.exit(main())
