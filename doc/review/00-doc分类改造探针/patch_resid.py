# -*- coding: utf-8 -*-
"""残余形态定点修补：裸 spec/ 前缀与 <篇> 泛化写法 → doc/review/。"""
import io, sys

ROOT = r'D:\virtual_riscv'
JOBS = [
    ('doc/process/00-问题记录.md', [('spec/01-评审记录.md', 'doc/review/01-评审记录.md')]),
    ('doc/verify/05-回归记录.md', [('spec/01-评审记录.md', 'doc/review/01-评审记录.md')]),
    ('run_cmd/AutoQueue.yaml', [('spec/01-评审记录.md', 'doc/review/01-评审记录.md')]),
    ('doc/项目开发流程.md', [('`doc/spec/<篇>-评审记录.md`', '`doc/review/<篇>-评审记录.md`')]),
]
ok = True
for rel, pairs in JOBS:
    p = ROOT + '\\' + rel.replace('/', '\\')
    t = io.open(p, encoding='utf-8').read()
    for old, new in pairs:
        n = t.count(old)
        if n < 1:
            print('MISS %s: %r' % (rel, old[:40]))
            ok = False
            continue
        t = t.replace(old, new)
        print('OK   %-34s %s x%d' % (rel, old[:34], n))
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(t)
sys.exit(0 if ok else 1)
