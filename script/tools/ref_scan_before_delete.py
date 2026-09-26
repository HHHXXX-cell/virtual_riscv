# -*- coding: utf-8 -*-
"""目录清理前的**引用扫描**（归档自 2026-09-26 心跳第十一轮的 `script/tmp/_inv2.py`）。

用途：删/移一个目录下的散件前，先机械核对"是否有活件引用它们"（规则 22/R3 的可回溯要求）。
两种扫描（都是**只读**）：
  ① 全仓文本件里含 `<目标目录>` **路径式**引用（`script/tmp`／`script\\tmp`）的行；
  ② 活机制面（`script/ run_cmd/ filelist/ tb/ rtl/ iss/ sw/ doc/ state/ .zcode/` 顶层）里出现
     目标目录下**任意文件名**的行（含 import 场景）。

用法：`python script/tools/ref_scan_before_delete.py <目录相对路径>`（默认 `script/tmp`）。
判读：命中的若是**历史快照件**（如 `script/gate/window_state.json` 这类"记录当时文件清单"的产物）
不算活引用；命中的若是**机制件/现行文档**正文，则必须先处置再删。
"""
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TARGET = sys.argv[1] if len(sys.argv) > 1 else 'script/tmp'
TARGET_ABS = os.path.join(ROOT, *TARGET.replace('\\', '/').split('/'))
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', 'work', 'work_params'}
TEXT_EXT = {'.py', '.md', '.txt', '.json', '.f', '.svh', '.sv', '.do', '.tcl', '.yaml', '.yml',
            '.cfg', '.ld', '.S', '.sh', '.bat'}
LIVE_TOP = ('script', 'run_cmd', 'filelist', 'tb', 'rtl', 'iss', 'sw', 'doc', 'state', '.zcode')

names = set()
for base, dirs, fs in os.walk(TARGET_ABS):
    dirs[:] = [d for d in dirs if d != '__pycache__']
    for n in fs:
        names.add(n)
print('%s 文件名 %d 个（不含 __pycache__）' % (TARGET, len(names)))

print('\n== ① 全仓 `%s` 路径式引用 ==' % TARGET)
n1 = 0
for base, dirs, fs in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('work_')
               and os.path.join(base, d) != TARGET_ABS]
    for n in fs:
        p = os.path.join(base, n)
        if os.path.splitext(n)[1].lower() not in TEXT_EXT:
            continue
        try:
            txt = io.open(p, 'r', encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            if re.search(re.escape(TARGET).replace('/', r'[\\/]'), ln):
                print('  %s:%d: %s' % (os.path.relpath(p, ROOT).replace('\\', '/'), i, ln.strip()[:160]))
                n1 += 1
if not n1:
    print('  （无）')

print('\n== ② 活机制面里出现目标目录件**裸名**的行 ==')
n2 = 0
for base, dirs, fs in os.walk(ROOT):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('work_')
               and os.path.join(base, d) != TARGET_ABS]
    relbase = os.path.relpath(base, ROOT).replace('\\', '/')
    if not (relbase == '.' or relbase.split('/')[0] in LIVE_TOP):
        continue
    for n in fs:
        p = os.path.join(base, n)
        if os.path.splitext(n)[1].lower() not in TEXT_EXT or n in names:
            continue
        try:
            txt = io.open(p, 'r', encoding='utf-8', errors='replace').read()
        except OSError:
            continue
        for i, ln in enumerate(txt.splitlines(), 1):
            for nm in sorted(names):
                if nm in ln and nm != 'README.md':
                    print('  %s:%d: [%s] %s'
                          % (os.path.relpath(p, ROOT).replace('\\', '/'), i, nm, ln.strip()[:140]))
                    n2 += 1
if not n2:
    print('  （无）')
