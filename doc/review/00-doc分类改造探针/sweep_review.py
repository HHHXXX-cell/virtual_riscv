# -*- coding: utf-8 -*-
"""评审件迁移引用清扫：doc/spec/{01-评审记录.md,01-评审探针} → doc/review/…（R0 2026-09-23 指令）。
冻结证据（探针目录内文件）不改；工具状态 JSON 不改（长基线走 snapshot --refresh 重折）。
用法：python script/tmp/sweep_review.py [--apply]"""
from __future__ import annotations
import io, os, re, sys

ROOT = r'D:\virtual_riscv'
APPLY = '--apply' in sys.argv
EXTS = {'.md', '.py', '.yaml', '.yml', '.sv', '.svh', '.tcl', '.do', '.f', '.json', '.txt'}
SKIP_DIRS = {'.git', 'sim', 'node_modules', 'tmp'}
SKIP_FILES = {'script/gate.py', 'script/path_audit.py',
              'script/gate/integrity_baseline.json',
              'script/gate/window_state.json'}
RULES = [
    (re.compile(r'doc/spec/01-评审记录'), 'doc/review/01-评审记录'),
    (re.compile(r'doc/spec/01-评审探针'), 'doc/review/01-评审探针'),
    (re.compile(r'doc/spec/\*-评审探针'), 'doc/review/*-评审探针'),
]
RESID = re.compile(r'doc/spec/(\*-评审探针|01-评审)')
BS = re.compile(r'doc\\spec\\01-评审(记录|探针)')

total, files, resid, bs = 0, [], [], []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.endswith('评审探针')]
    for fn in fns:
        if os.path.splitext(fn)[1].lower() not in EXTS:
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT).replace(os.sep, '/')
        if rel in SKIP_FILES:
            continue
        try:
            t = io.open(p, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        n = 0
        new = t
        for pat, dst in RULES:
            n += len(pat.findall(new))
            new = pat.sub(dst, new)
        for m in BS.finditer(t):
            bs.append('%s: %s' % (rel, m.group(0)))
        if not n:
            continue
        if RESID.search(new):
            resid.append(rel)
        total += n
        files.append((rel, n))
        if APPLY:
            with io.open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(new)

print('%s：%d 处 / %d 文件' % ('已落盘' if APPLY else 'DRY-RUN', total, len(files)))
for rel, n in sorted(files, key=lambda x: (-x[1], x[0])):
    print('  %-46s %4d' % (rel, n))
if resid:
    print('! 替换后仍残留 doc/spec/…评审：%s' % resid)
if bs:
    print('反斜杠形态（历史引文，留原样）：%d 处 %s' % (len(bs), bs))
