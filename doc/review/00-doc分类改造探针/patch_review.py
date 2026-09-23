# -*- coding: utf-8 -*-
"""gate.py 评审件迁移同步（锚点唯一性断言）。"""
import io, sys

ROOT = r'D:\virtual_riscv'
p = ROOT + r'\script\gate.py'
t = io.open(p, encoding='utf-8').read()
PAIRS = [
    ("        # 标识符抽取的**来源**与闭包**语料**必须同类：只取规格篇正文（`doc/spec/NN-*.md`，排除\n"
     "        # 评审记录/探针）。两条理由：",
     "        # 标识符抽取的**来源**与闭包**语料**必须同类：只取规格篇正文（`doc/spec/NN-*.md`；\n"
     "        # 评审件已迁 `doc/review/`，此处靠路径天然隔离，下方排除式是防御性保留）。两条理由："),
    ("BASE_GLOBS = [os.path.join('doc', 'spec', '*-评审探针')]",
     "BASE_GLOBS = [os.path.join('doc', 'review', '*-评审探针')]"),
    ("           'scan_dirs': [d + '/' for d in BASE_DIRS] + ['doc/spec/*-评审探针/'],",
     "           'scan_dirs': [d + '/' for d in BASE_DIRS] + ['doc/review/*-评审探针/'],"),
]
for old, new in PAIRS:
    n = t.count(old)
    if n != 1:
        print('ABORT：锚点命中 %d 次（应为 1）：%r' % (n, old[:60]))
        sys.exit(1)
    t = t.replace(old, new)
with io.open(p, 'w', encoding='utf-8', newline='') as f:
    f.write(t)
print('OK gate.py：%d 处锚点唯一命中' % len(PAIRS))
