# -*- coding: utf-8 -*-
"""文件速查小工具（归档自 2026-09-26 心跳第十一轮的 `script/tmp/dump.py` ＋ `g.py`，两件并入一件）。

两个子命令（**只读**，不写任何仓库文件）：
  · `dump <src> <dst> <a-b[,c-d…]>` —— 把 src 的指定行区间（1-based，闭区间）带行号写到 dst；
  · `grep <正则> <文件…>`        —— 逐文件逐行正则匹配，输出 `文件:行号: 行文`。

为什么留：本机 shell 是 cmd.exe（无 `sed`/`grep`），而"取某几行原文入证据件"与"跨多文件正则核销"
是复核批里反复出现的动作；两件原在 `script/tmp`（不入库、用完即删）⇒ 逐件重写。本件是二者的**原文合并**
（行为未改；argv 形态改了，见下），归档到 `script/tools/` 后受版本控制。

用法：`python script/tools/file_peek.py dump <src> <dst> 10-20,44-44`
      `python script/tools/file_peek.py grep <正则> <文件…>`
"""
import re
import sys


def dump(src, dst, ranges):
    s = open(src, encoding='utf-8').read().splitlines()
    idx = []
    for part in ranges.split(','):
        a, b = part.split('-')
        idx += list(range(int(a) - 1, min(int(b), len(s))))
    with open(dst, 'w', encoding='utf-8') as f:
        for i in idx:
            f.write('%d\t%s\n' % (i + 1, s[i]))
    print('wrote', dst, len(idx), 'lines')


def grep(pat, files):
    rx = re.compile(pat)
    for fp in files:
        s = open(fp, encoding='utf-8', errors='replace').read().splitlines()
        for i, l in enumerate(s):
            if rx.search(l):
                print('%s:%d: %s' % (fp, i + 1, l))


def main(argv):
    if not argv or argv[0] not in ('dump', 'grep'):
        print(__doc__)
        return 2
    if argv[0] == 'dump':
        if len(argv) != 4:
            print('用法: file_peek.py dump <src> <dst> <a-b[,c-d…]>')
            return 2
        dump(argv[1], argv[2], argv[3])
        return 0
    if len(argv) < 3:
        print('用法: file_peek.py grep <正则> <文件…>')
        return 2
    grep(argv[1], argv[2:])
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
