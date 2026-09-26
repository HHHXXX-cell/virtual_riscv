#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sw/tests/gen_smoke_image.py — 定向冒烟程序 → 存储器镜像（"一份产物喂两边"）。

判据纪律（AGENTS.md §3.4 坑 2 / doc/process/00 ISS-010）：
  同一份镜像既喂 Python ISS，又喂 RTL 侧 TB（`$readmemh`）。两侧镜像一旦漂移，
  会把"环境差异"伪装成 DUT bug。故本脚本产出：
    sim/image/m_smoke.hex    $readmemh（ModelSim 侧；@<字地址> 段头，与 vriss.load_readmemh 同口径）
    sim/image/m_smoke.bin    裸二进制（备用/外部工具）
    sim/image/MANIFEST.json  md5 + base_byte/base_word + words + 生成来源（判据据它比对）
  程序体**直接复用** iss/tests/test_smoke.py 的 build_words()，不另写一份——
  否则"镜像与 golden trace 同源"就断了，往返比对会变成自证。

跑法（任意 cwd）：python sw/tests/gen_smoke_image.py
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'iss'))
sys.path.insert(0, str(ROOT / 'iss' / 'tests'))

from vriss.encode import link                       # noqa: E402
from test_smoke import build_words, CODE, HANDLER, TOHOST   # noqa: E402


def main() -> int:
    img = link(build_words())
    out = ROOT / 'sim' / 'image'
    out.mkdir(parents=True, exist_ok=True)

    hex_text = img.to_readmemh()
    (out / 'm_smoke.hex').write_text(hex_text, encoding='utf-8', newline='\n')
    (out / 'm_smoke.bin').write_bytes(img.to_bytes())

    md5 = hashlib.md5((out / 'm_smoke.hex').read_bytes()).hexdigest()
    man = {
        'hex': 'sim/image/m_smoke.hex',
        'bin': 'sim/image/m_smoke.bin',
        'md5': md5,
        'base_byte': img.start,
        'base_word': img.start // 4,
        'words': len(img.words),
        'segments': {'code': CODE, 'handler': HANDLER, 'tohost': TOHOST},
        'source': 'iss/tests/test_smoke.py:build_words() + vriss.encode.link()',
        'tb_note': 'TB 侧 mem 若按字索引，$readmemh 的 @<字地址> 直接是 mem 下标；'
                   '若按字节索引，需 @<<2。两侧必须取同一份本文件。',
    }
    (out / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=1) + '\n',
                                       encoding='utf-8', newline='\n')
    (out / 'MANIFEST.txt').write_text(
        'hex=%s\nbin=%s\nmd5=%s\nbase_byte=0x%x\nbase_word=0x%x\nwords=%d\nsource=%s\n'
        % (man['hex'], man['bin'], md5, img.start, img.start // 4, len(img.words), man['source']),
        encoding='utf-8', newline='\n')

    print('[image] %s md5=%s base=0x%x words=%d (code=0x%x handler=0x%x tohost=0x%x)'
          % (man['hex'], md5[:12], img.start, len(img.words), CODE, HANDLER, TOHOST))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
