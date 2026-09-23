# -*- coding: utf-8 -*-
"""doc 分类改造：全仓路径引用清扫（R0 2026-09-23 指令）。

规则：
  00-问题记录 → doc/process/00-问题记录      （R0 定：台账归流程类）
  01~10       → doc/verify/NN-…              （R0 定：验证文档归 doc/verify/）
  冻结证据 doc/spec/*-评审探针/ 一律不改内容（改历史证据＝伪造取证）
  工具状态件（gate.py 已手工同步、integrity_baseline.json 为指纹库）不动
用法：python script/tmp/sweep_doc.py [--apply]
"""
from __future__ import annotations
import io, os, re, sys

ROOT = r'D:\virtual_riscv'
APPLY = '--apply' in sys.argv
EXTS = {'.md', '.py', '.yaml', '.yml', '.sv', '.svh', '.tcl', '.do', '.f', '.json', '.txt'}
SKIP_DIRS = {'.git', 'sim', 'node_modules', 'tmp'}
SKIP_FILES = {'script/gate.py', 'script/path_audit.py',
              'script/gate/integrity_baseline.json',
              'script/gate/window_state.json'}   # 工具状态：上一窗口的路径+指纹，改它＝篡改历史快照
PAT = re.compile(r'doc/(00|01|02|03|04|05|06|07|08|09|10)(?![0-9])')


def dest(n):
    return 'process' if n == '00' else 'verify'


total, files = 0, []
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.endswith('评审探针')]
    for fn in fns:
        if os.path.splitext(fn)[1].lower() not in EXTS:
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT).replace('\\', '/')
        if rel in SKIP_FILES:
            continue
        try:
            t = io.open(p, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        hits = PAT.findall(t)
        if not hits:
            continue
        new = PAT.sub(lambda m: 'doc/%s/%s' % (dest(m.group(1)), m.group(1)), t)
        # 反向检查：替换后不得出现旧形态（doc/NN 后跟非数字）
        if PAT.search(new):
            print('! 残留未替换：%s' % rel)
        total += len(hits)
        files.append((rel, len(hits)))
        if APPLY:
            with io.open(p, 'w', encoding='utf-8', newline='') as f:
                f.write(new)

print('%s：%d 处引用 / %d 个文件' % ('已落盘' if APPLY else 'DRY-RUN', total, len(files)))
for rel, n in sorted(files, key=lambda x: (-x[1], x[0])):
    print('  %-46s %4d' % (rel, n))

# 反斜杠形态（doc\04）与已迁移文件是否仍被旧路径引用，单独列
bs = []
PAT_BS = re.compile(r'doc\\(0[0-9]|10)')
for dp, dns, fns in os.walk(ROOT):
    dns[:] = [d for d in dns if d not in SKIP_DIRS and not d.endswith('评审探针')]
    for fn in fns:
        if os.path.splitext(fn)[1].lower() not in EXTS:
            continue
        p = os.path.join(dp, fn)
        rel = os.path.relpath(p, ROOT).replace('\\', '/')
        try:
            t = io.open(p, encoding='utf-8').read()
        except (OSError, UnicodeDecodeError):
            continue
        n = len(PAT_BS.findall(t))
        if n:
            bs.append((rel, n))
print('反斜杠形态 doc\\NN：%d 处 %s' % (sum(n for _, n in bs), bs if bs else '（无）'))
