# -*- coding: utf-8 -*-
"""窗口工具加固的**回归探针**（归档自 2026-09-26 心跳第十一轮的 `script/tmp/_probe_win.py`）。

它验什么（三条行为，改 `script/flow.py` 的 `snapshot_files`／`cmd_window` 后**必须**仍成立）：
  ① `os.walk(..., onerror=cb)` 的枚举失败被**收集**（不再静默吞掉）；
  ② 快照有枚举错误时 `window --take` **拒绝折入**（返回码 2，且**不写** window.json）；
  ③ 新快照件数跌破上一份的 `WINDOW_TAKE_MIN_RATIO`（0.90）时**拒绝折入**；带 `--force` 才允许。
末段另打印一次**真快照**的件数与枚举错误数（与当前基线同量级＝正常）。

安全：探针把 `flow.WINDOW` 改指**临时目录**里的副本 ⇒ 绝不碰真 `state/window.json`。
用法：`python script/tools/win_hardening_probe.py`（退出码 0 = 三条全过；断言失败即非 0）。
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, 'script'))
import flow  # noqa: E402

# 沙箱化的 window.json（探针绝不碰真基线）
tmpd = tempfile.mkdtemp(prefix='winprobe_')
flow.WINDOW = os.path.join(tmpd, 'window.json')
flow.save_json(flow.WINDOW, {'taken': 'T0', 'reason': 'probe',
                             'files': {'a/%d.txt' % i: 'x:1' for i in range(100)}})
print('[probe] 沙箱 window.json =', flow.WINDOW)

# ---- ① 枚举失败被收集 -------------------------------------------------------
real_walk = os.walk


def bad_walk(top, onerror=None, **kw):
    if onerror is not None:
        onerror(OSError(13, 'Permission denied', os.path.join(top, 'locked_dir')))
    return real_walk(top, **kw)


os.walk = bad_walk
_files, errs = flow.snapshot_files([])
os.walk = real_walk
print('[probe ①] errors=%d ｜ 首条=%s' % (len(errs), errs[0] if errs else '(无)'))
assert errs, '枚举失败未被收集！'

# ---- ② 有枚举错误 ⇒ --take 拒绝 --------------------------------------------
os.walk = bad_walk
rc = flow.cmd_window(['--take', '--reason', 'probe-enum'])
os.walk = real_walk
after = flow.load_json(flow.WINDOW, default={})
print('[probe ②] rc=%d ｜ 基线 taken 仍为 %s（应未被改写）' % (rc, after.get('taken')))
assert rc == 2, '有枚举错误时 --take 未 FAIL'

# ---- ③ 件数骤降 ⇒ 拒绝；--force 例外 --------------------------------------
real_snap = flow.snapshot_files
flow.snapshot_files = lambda errors=None: ({'a/0.txt': 'x:1'}, [])   # 1 件 vs 基线 100 件
rc = flow.cmd_window(['--take', '--reason', 'probe-shrink'])
after = flow.load_json(flow.WINDOW, default={})
print('[probe ③a] rc=%d ｜ 基线 taken 仍为 %s（应未被改写）' % (rc, after.get('taken')))
assert rc == 2, '件数骤降未被拒绝'
rc = flow.cmd_window(['--take', '--reason', 'probe-force 正当批量删除', '--force'])
after = flow.load_json(flow.WINDOW, default={})
print('[probe ③b] rc=%d ｜ 基线件数 %d（--force 后应折入 1 件）'
      % (rc, len(after.get('files', {}))))
assert rc == 0 and len(after.get('files', {})) == 1, '--force 未放行'
flow.snapshot_files = real_snap

# ---- ④ 正常面：真快照件数与基线同量级、无枚举错误 --------------------------
n, e2 = flow.snapshot_files([])
print('[probe ④] 真快照 %d 件 ｜ 枚举错误 %d 处' % (len(n), len(e2)))
shutil.rmtree(tmpd, ignore_errors=True)
print('[probe] ALL OK')
