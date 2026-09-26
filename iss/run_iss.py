#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""iss/run_iss.py — 仓库根可直接调用的 ISS 入口（等价于在 iss/ 下 `python -m vriss ...`）。

为什么存在：确定性的 runner（script/flow.py run）以仓库根为 cwd 执行步骤，
而 `python -m vriss` 需要 iss/ 在 sys.path 上。此文件是那一步的稳定入口，
使步骤命令可写死为 `python iss/run_iss.py run --hex ... --csv ...`。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from vriss.__main__ import main  # noqa: E402

if __name__ == '__main__':
    raise SystemExit(main())
