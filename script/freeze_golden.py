# -*- coding: utf-8 -*-
"""把 ISS smoke 的 trace 冻结为 golden 语料（sim/golden/ + MANIFEST）。
输入定位策略：优先复用仓库内既有产物（sim/run_S*/iss_smoke_trace.csv），找不到则重跑 smoke 生成。
运行前提：cwd = 仓库根。"""
import glob
import hashlib
import os
import shutil
import subprocess
import sys

os.makedirs('sim/golden', exist_ok=True)
cands = sorted(glob.glob('sim/run_S*/iss_smoke_trace.csv'))
if cands:
    src = cands[0]
else:
    subprocess.run([sys.executable, 'iss/tests/test_smoke.py'],
                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    tmp = sorted(glob.glob(os.path.join(os.environ.get('TEMP', ''), 'vriss_smoke_trace.csv')))
    src = tmp[-1]

dst = 'sim/golden/iss_smoke.csv'
shutil.copy(src, dst)
b = open(dst, 'rb').read()
h = hashlib.md5(b).hexdigest()
n = len(b.decode('utf-8', errors='replace').splitlines())
with open('sim/golden/MANIFEST.txt', 'w', newline='\n') as f:
    f.write('source=%s\ngolden=%s\nmd5=%s\nlines=%d\n' % (src, dst, h, n))
print('golden %s md5=%s lines=%d (from %s)' % (dst, h, n, src))
