# -*- coding: utf-8 -*-
"""全仓残留扫描（不限目录跳过，除 .git/冻结探针）：旧形态 doc/NN 是否仍存在。"""
import io, os, re

ROOT = r'D:\virtual_riscv'
PAT = re.compile(r'doc/(0[0-9]|10)(?![0-9])')
EXTS = {'.md', '.py', '.yaml', '.yml', '.sv', '.svh', '.tcl', '.do', '.f', '.txt', '.json'}
hits = {}
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in {'.git'} and not d.endswith('评审探针')]
    for fn in fns:
        if os.path.splitext(fn)[1].lower() not in EXTS:
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT).replace(os.sep, '/')
        try:
            t = io.open(p, encoding='utf-8').read()
        except Exception:
            continue
        ms = PAT.findall(t)
        if ms:
            hits[rel] = len(ms)
for rel in sorted(hits):
    print('%-50s %d' % (rel, hits[rel]))
print('合计 %d 文件 / %d 处' % (len(hits), sum(hits.values())))
