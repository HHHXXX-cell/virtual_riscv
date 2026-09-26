#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sw/tests/build_rv64ui.py — riscv-tests rv64ui 构建、镜像与"缺口清单"（M2 用）。

它做什么（三步，全部确定性）：
  1. **编译**：MSYS2 ucrt64 的 `riscv64-unknown-elf-gcc`（口径见 `doc/环境搭建.md`）把
     `sw/tests/riscv-tests/isa/rv64ui/<t>.S`（**逐字不改的上游测试体**）＋ 本项目 env 适配层
     （`sw/env/riscv_test.h` / `sw/env/link.ld`）编成 ELF，并落 objdump 反汇编（证据件）；
  2. **镜像**：解析 ELF 的 `SHF_ALLOC` 段 → 产 `$readmemh` 镜像（**一份镜像喂两边**，AGENTS.md §3.4 坑 2）：
       · `<name>.hex`      —— 全局地址口径，ISS 侧 `--hex` 读它（与 RTL 侧同源）；
       · `<name>.tb.hex`   —— TB 视图：只保留落在**取指窗**（< 0x4000）的段，地址不变、逐字相同。
         为什么需要：`tb/unit/m1_e2e_tb.sv` 的取指桩 `fmem` 只覆盖 0x0000~0x3FFF，
         而 `tohost`/`.data` 在 0x4000_0000 窗 ⇒ 镜像里的数据段会被 `$readmemh` 判越界。
       · `<name>.data.hex` —— TB **数据窗**视图（0x4000_0000 起 1 KiB，字地址**减窗基址**）：
         由 TB 的 `+DATA=` 预载（`$readmemh` 第二份镜像）。**2026-09-26 心跳第 6 轮加**
         （ledger ISS-126）：此前数据桩恒零填充 ⇒ `.data` 非全 0 的测试（`rv64ui-p-lw/p-sw`）
         与镜像**不等价**、不可判；加预载后等价性由"数据窗内容 = 镜像数据段"直接保证。
         三视图同源（同一 ELF、同一段数据），差异逐条记进 MANIFEST（含 md5、窗口与派生规则）；
         落在 TB 数据窗**之外**的数据字逐条计数（`n_words_data_outside_tb_win`）——非 0 即
         "该条不可在本 TB 上判"，由 `flow.py check-one m2-rv64ui` 判据② fail-closed。
  3. **缺口清单**（`--gap-all`）：逐条编译全部 rv64ui 测试并反汇编，取"测试体实际用到的助记符集合"，
     与 RTL 当前支持的指令面（G1-I 14 条）做差 → `GAP.json` ＋ stdout 表。
     它是"卡在哪"的机械依据：**不猜、不手抄**（助记符归一表见 `MNEMONIC_ALIAS`）。
     本轮（2026-09-26 心跳第 8 轮）增写 `GAP.json` 的 **`pending_subset`**（待补清单）：
     对全部 52 条测试逐条给出「是否在判定子集 / 缺哪些指令 / 编译是否过 / 实测失败签名」，
     即"**把 51 条能编的全编出来跑一遍**"的结果面——**不静默跳过任何一条**。
     实测签名由 `--run-evidence <log>` 从 `script/flow.py:chk_m2_rv64ui` 写的运行日志**机械解析**
     （该函数的三处写出点即三类节头：`[<name>]` 走到比对 / `[<name> RTL]` RTL 侧自报失败 /
     `[<name> ISS]` ISS 侧未 PASS），**不手抄、不美化**。

判据纪律：本脚本**不判通过**——它只产证据（ELF/hex/dump/MANIFEST/GAP）。
"过不过"由 `python script/flow.py check-one m2-rv64ui` 真跑 ISS ＋ RTL ＋ 逐条比对来判（红线 R6/R8）。

跑法（任意 cwd）：
    python sw/tests/build_rv64ui.py                    # 判定子集（默认＝JUDGE_SUBSET 36 条）
    python sw/tests/build_rv64ui.py --tests add addi and
    python sw/tests/build_rv64ui.py --gap-all \
        --run-evidence sim/run_m2_rv64ui/run.log       # 全量缺口＋待补清单（含上述构建）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_EXE = r'D:\msys64\usr\bin\env.exe'
BASH = r'D:\msys64\usr\bin\bash.exe'
SRC_DIR = ROOT / 'sw' / 'tests' / 'riscv-tests' / 'isa' / 'rv64ui'
OUT_DIR = ROOT / 'sim' / 'image' / 'rv64ui'
# --------------------------------------------------------------------------- #
# **定向用例**（2026-09-26 心跳第 12 轮加；M3-(b)「补定向激励」批）——VR1 自建源，与 rv64ui
# **同一构建口径**（同一 env/link.ld/ELF→三视图派生），命名前缀 `vr1dir-p-`（与上游镜像可区分）：
#   `dir_csr` —— 7 条 CSR 纯读（`csrrs rd=x0, csr, rs1=x0`）⇒ 命中 `cg_retire.cp_csr` 的 7 个 bin
#   （VP-05；缺 bin 依据见该源文件头与 `doc/verify/07-m2cov_r2.txt` §A 的 ZERO 清单）。
# **导入用例**（同一批）：`m_smoke` —— **既有自研镜像**（`sim/image/m_smoke.hex`，由
#   `sw/tests/gen_smoke_image.py` 产，且是 M1 判据 `rtl-vs-iss` 的激励：golden ↔ RTL 30 条
#   0 mismatch）。纳入覆盖率批可覆盖 `cg_retire.exc`（非对齐 store → M 态 trap 条目的退休）
#   与 `cg_lsu_fsm.t_idle_done`（非对齐 ⇒ 不发请求直接报 fault）；这两条**不能**用 riscv-tests
#   的 env 触发（`sw/env/riscv_test.h` 的 trap_vector 只把 ecall 类引向 tohost，其余异常一律
#   TESTNUM=1337 ⇒ HALT_FAIL）。三视图同源＝同一份 `m_smoke.hex`（`hex` 原样、`tb.hex` 只保留
#   取指窗内的字、`data.hex` 只保留 TB 数据窗内的字）。
# 判据纪律：本清单的**全部条目**都是 `m2-rv64ui` 的判定面（该判据逐条真跑 ISS+RTL+比对），
#   故定向/导入用例**必须**同样跑通——不设"覆盖率专用"的免判通道（红线 R6/R8）。
# --------------------------------------------------------------------------- #
DIRECT_DIR = ROOT / 'sw' / 'tests' / 'direct'
# `dir_csr` —— VP-05 的 CSR 读面（心跳第 12 轮）；
# `dec_probe` —— 保留编码/未激励面探针（心跳第 14 轮，M3-(a) 补激励）：逐条对上
#   `doc/verify/07-m3cov_r2.txt` §B 的逐行未命中清单（RTL 行号写在该源文件头），全部编码
#   逐一核过 **RTL 与 ISS 两侧同为非法**（故意排除 MULDIV f3≠{0,4,6}／JALR f3≠0／SYSTEM f3=3／
#   SYSTEM f7=0x08／OP32 f7=0x01 等"ISS 侧合法"的编码——那属两侧口径差，不属激励缺口）。
DIRECT_TESTS = ('dir_csr', 'dec_probe')
DIRECT_PREFIX = 'vr1dir-p-'
IMPORT_CASES = ('m_smoke',)
IMAGE_DIR = ROOT / 'sim' / 'image'
# --------------------------------------------------------------------------- #
# **受控复位注入用例**（2026-09-26 心跳第 13 轮；**R0 2026-09-26 三项裁定①**＝`doc/verify/02`
# §6 NU-2 受控通道）：
#   `rst_lsu` —— 载入/存储长循环（源 `sw/tests/direct/rst_lsu.S`）⇒ LSU 反复穿过 L_REQ/L_RSP；
#   由覆盖率批 vsim 的 `+RESET_INJECT=<cycle>[,...]`（`tb/unit/m1_e2e_tb.sv` 的机制件）在
#   指定拍注入复位，命中 `cg_lsu_fsm.cp_trans` 的 `t_req_idle`/`t_rsp_idle`（复位落在请求拍/
#   响应拍——该两迁移只有复位边能产生，`rtl/vr1/lsu/vr1_lsu.sv` 的 FSM 可核）。
# **通道口径（R0 裁定原文落地，写死防误读）**：
#   · 本清单条目**只进覆盖率批**（`run_cmd/cover_m3_testlist.txt` 的 `rst_*` 前缀条目），
#     **不进回归面**：`run_cmd/rv64ui_testlist.txt` 不含 `rst_` ⇒ 回归"同配置"签名不变
#     （**不污染 M2 的同配置口径**）；
#   · **不进 `MANIFEST.tests`** ⇒ 不受 `m2-rv64ui` 判定（该判据逐条 ISS↔RTL 比对，而复位注入
#     使 trace 出现"重启后第二段"，**构造性不可比**——NU-2 行原文）；本清单登记在同 MANIFEST
#     的 **`cov_only_tests`** 字段，其判定＝RTL 侧 `HALT_PASS` ＋ 无 `HALT_FAIL`/`WATCHDOG`
#     ＋ TB 复位注入证据行 `[rst_inj]`（`run_cmd/cover_rv1.py` 的受控通道单例执行，fail-closed）；
#   · bin 不删、判定阈值不改（红线 R7；判据侧通道标注见 `script/flow.py:chk_m3_func_cov`）。
#   注入拍＝探针实测（沙箱 `+RST_INJ_TRACE` 逐拍迹；拍计数＝TB 复位释放后第 N 个 posedge，
#   两拍分别落在 L_REQ（state=1）与重启后的 L_RSP（state=2））。
# --------------------------------------------------------------------------- #
COV_ONLY_TESTS = (
    # (源名, 用例名, 复位注入拍列表)
    # 拍＝探针实测（sim/run_rstinj_probe/out_inject.txt 的 [rst_inj] trace 逐拍迹；
    # sample@N 读的是 trace[N] 的沿前值 ⇒ N 取该值所在拍）：
    #   3695 ∈ L_REQ（state=1，store 请求等待被接受）⇒ t_req_idle；
    #   3796 ∈ L_RSP（state=2，首轮重启后的 load 响应拍）  ⇒ t_rsp_idle。
    ('rst_lsu', 'rst_lsu', (3695, 3796)),
)
GCC_FLAGS = ('-march=rv64im_zicsr -mabi=lp64 -static -mcmodel=medany -fvisibility=hidden '
             '-nostdlib -nostartfiles')
# 逐测试的 `-march` 覆盖（默认不覆盖）。**唯一用途＝把 `fence.i` 编出来**（Zifencei）：`spec/00` §2
# 一期 ISA 串 ＝ `rv64imac_zicsr_zifencei` ⇒ 该扩展**在一期范围内**，本工具链口径按 ISA 串补齐；
# 其余测试**一律保持默认串**，以免改动既有 36 条已被判过的镜像字节（`-march` 会改 ELF 属性与
# 潜在代码生成 ⇒ 不做全量切换）。缺省覆盖时 `fence.i` 编不过（`unrecognized opcode`）。
MARCH_OVERRIDE = {'fence_i': 'rv64im_zicsr_zifencei'}
INC_FLAGS = ('-I sw/env -I sw/tests/riscv-tests/isa/macros/scalar -I sw/tests/riscv-tests/env')
LD = 'sw/env/link.ld'
TOHOST = 0x4000_0010          # TB `TOHOST_ADDR` ／ ISS `--tohost` ／ test_smoke.TOHOST
CODE_LIMIT = 0x4000           # TB 取指桩覆盖面（字地址 0x0000~0x0FFF）
# TB 数据窗（`tb/unit/m1_e2e_tb.sv` 的 `DRAM_BASE` / `DMEM_WORDS`；**同名常量两处必须一致**，
# 由 `flow.py check-one m2-rv64ui` 判据②逐字比对 TB 源文（漂移即 fail-closed））。
# 数据视图 `data.hex` = 落在本窗内的段字，地址**相对 DATA_BASE**（TB `+DATA=` 的口径）。
DATA_BASE = 0x4000_0000
DATA_WIN_BYTES = 1024         # = DMEM_WORDS(256) × 4

# RTL 当前支持的指令面（依据：G1-I 清单 §1.1 第 1 条 = 14 条，加 2026-09-26 心跳第 5 轮的 M2 增补 27 条，
# 加 2026-09-26 心跳第 10 轮（M3-(d)「补缺指令」批）的 16 条 —— 分支余 4（BLT/BGE/BLTU/BGEU）＋ JALR
# ＋ 载入余 6（LB/LH/LD/LBU/LHU/LWU）＋ 存储余 3（SB/SH/SD）＋ FENCE/FENCE.I ⇒ 合 **57 条**；
# 真值＝`rtl/vr1/ctrl/vr1_decode.sv` 的 `isop` 表 —— 本集合只做**对照**，不产语义）。
RTL_SUPPORTED = {'addi', 'slti', 'sltiu', 'xori', 'ori', 'andi', 'slli', 'srli', 'srai',   # OP-IMM 9
                 'lui', 'auipc',                                                            # U 2
                 'addiw', 'slliw', 'srliw', 'sraiw', 'addw', 'subw', 'sllw', 'srlw', 'sraw', # OP-32 9
                 'add', 'sub', 'sll', 'slt', 'sltu', 'xor', 'srl', 'sra', 'or', 'and',       # OP 10
                 'mul', 'div', 'rem',                                                       # M 3
                 'beq', 'bne', 'blt', 'bge', 'bltu', 'bgeu', 'jal', 'jalr',                 # BR/JMP 8
                 'lb', 'lh', 'lw', 'ld', 'lbu', 'lhu', 'lwu',                               # LOAD 7
                 'sb', 'sh', 'sw', 'sd',                                                    # STORE 4
                 'fence', 'fence_i',                                                        # MISC-MEM 2
                 'csrrw', 'csrrs', 'mret'}                                                  # CSR/SYS 3
# 助记符归一（objdump 打印的是"汇编写法"，含伪指令；归一到基础指令名——只做**规范同义**替换，不猜语义）
MNEMONIC_ALIAS = {
    'j': 'jal', 'jr': 'jalr', 'ret': 'jalr', 'nop': 'addi', 'mv': 'addi', 'li': 'addi',
    'beqz': 'beq', 'bnez': 'bne', 'blez': 'bge', 'bgez': 'bge', 'bltz': 'blt', 'bgtz': 'blt',
    'bgt': 'blt', 'ble': 'bge', 'bgtu': 'bltu', 'bleu': 'bgeu',
    'not': 'xori', 'neg': 'sub', 'negw': 'subw', 'sext.w': 'addiw', 'zext.b': 'andi',
    'snez': 'sltu', 'sltz': 'slt', 'sgtz': 'slt', 'seqz': 'sltiu', 'csrr': 'csrrs',
    'csrw': 'csrrw',
    'csrs': 'csrrs', 'csrc': 'csrrc', 'csrwi': 'csrrwi', 'csrsi': 'csrrsi', 'csrci': 'csrrci',
    'fence.i': 'fence_i', 'call': 'jal', 'tail': 'jal', 'bgezal': 'bge', 'lga': 'auipc',
}
RE_DIS = re.compile(r'^\s*[0-9a-f]+:\s+(?:[0-9a-f]{2}\s+)*[0-9a-f]{8}\s+(\S+)')


def bash(cmd: str, timeout: int = 900) -> tuple[int, str]:
    p = subprocess.run([ENV_EXE, 'MSYSTEM=UCRT64', BASH, '-lc', cmd],
                       capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=timeout)
    return p.returncode, (p.stdout or '') + (p.stderr or '')


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# ELF 解析（标准库；只取 SHF_ALLOC 的 PROGBITS 段 —— 段表口径与 objdump 一致）
# --------------------------------------------------------------------------- #
def parse_elf(path: Path) -> tuple[int, list[dict], dict]:
    b = path.read_bytes()
    if b[:4] != b'\x7fELF' or b[4] != 2 or b[5] != 1:
        raise SystemExit('非 ELF64-LE：%s' % path)
    e_entry = struct.unpack_from('<Q', b, 0x18)[0]
    e_shoff = struct.unpack_from('<Q', b, 0x28)[0]
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from('<HHH', b, 0x3A)

    def sh(i: int) -> dict:
        o = e_shoff + i * e_shentsize
        name, typ = struct.unpack_from('<II', b, o)
        flags, addr, off, size = struct.unpack_from('<QQQQ', b, o + 8)
        link, _, entsize = struct.unpack_from('<III', b, o + 40)
        return {'name_off': name, 'type': typ, 'flags': flags, 'addr': addr,
                'off': off, 'size': size, 'link': link, 'entsize': entsize}

    shs = [sh(i) for i in range(e_shnum)]
    strs = b[shs[e_shstrndx]['off']:shs[e_shstrndx]['off'] + shs[e_shstrndx]['size']]

    def nm_at(off: int) -> str:
        return strs[off:strs.find(b'\0', off)].decode('ascii', 'replace')

    segs = []
    for s in shs:
        if s['type'] != 1 or not (s['flags'] & 0x2) or s['size'] == 0:
            continue                                    # 只取 PROGBITS + SHF_ALLOC（LOAD 面）
        segs.append({'name': nm_at(s['name_off']), 'addr': s['addr'],
                     'data': b[s['off']:s['off'] + s['size']]})
    segs.sort(key=lambda s: s['addr'])

    syms: dict[str, int] = {}
    for s in shs:                                       # .symtab（type=2）
        if s['type'] != 2 or not s['link']:
            continue
        nstr = shs[s['link']]
        nstrs = b[nstr['off']:nstr['off'] + nstr['size']]
        step = s['entsize'] or 24
        for i in range(0, s['size'], step):
            noff, = struct.unpack_from('<I', b, s['off'] + i)
            val, = struct.unpack_from('<Q', b, s['off'] + i + 8)
            nm = nstrs[noff:nstrs.find(b'\0', noff)].decode('ascii', 'replace')
            if nm and nm not in syms:
                syms[nm] = val
    return e_entry, segs, syms


def seg_words(segs: list[dict]) -> list[tuple[int, int]]:
    out = []
    for s in segs:
        assert s['addr'] % 4 == 0 and len(s['data']) % 4 == 0, '段 %s 非 4 B 对齐' % s['name']
        for i in range(0, len(s['data']), 4):
            out.append((s['addr'] + i, int.from_bytes(s['data'][i:i + 4], 'little')))
    return out


def write_hex(words: list[tuple[int, int]], path: Path, per_line: int = 4) -> None:
    """`$readmemh`（**字地址** `@<addr/4>` 口径，与 `vriss.encode.Image.to_readmemh` 同构）。

    多段：地址不连续处新开一个 `@` 记录（iss/vriss/mem.py:load_readmemh 与 ModelSim 都支持）。
    """
    lines, buf, cur = [], [], None
    for addr, w in words:
        if cur is None or addr != cur:
            if buf:
                lines.append(' '.join(buf))
                buf = []
            lines.append('@%08x' % (addr // 4))
            cur = addr
        buf.append('%08x' % (w & 0xFFFFFFFF))
        cur = addr + 4
        if len(buf) == per_line:
            lines.append(' '.join(buf))
            buf = []
    if buf:
        lines.append(' '.join(buf))
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')


def mnemonics_of(dump: str) -> list[str]:
    out = []
    for ln in dump.splitlines():
        m = RE_DIS.match(ln)
        if m:
            mn = m.group(1).lower()
            out.append(MNEMONIC_ALIAS.get(mn, mn))
    return out


def build_one(test: str, verbose: bool = True, src_dir: 'Path | None' = None,
              name: 'str | None' = None) -> dict:
    src_dir = src_dir or SRC_DIR
    src = src_dir / ('%s.S' % test)
    if not src.exists():
        raise SystemExit('[rv64ui] 找不到测试源 %s（上游清单见 isa/rv64ui/Makefrag）' % src)
    name = name or ('rv64ui-p-%s' % test)
    elf, dump = OUT_DIR / ('%s.elf' % name), OUT_DIR / ('%s.dump' % name)
    march = MARCH_OVERRIDE.get(test)
    flags = GCC_FLAGS if not march else GCC_FLAGS.replace(
        '-march=rv64im_zicsr', '-march=%s' % march, 1)
    rc, out = bash('cd /d/virtual_riscv && riscv64-unknown-elf-gcc %s %s -T %s %s -o %s'
                   % (flags, INC_FLAGS, LD, src.relative_to(ROOT).as_posix(),
                      elf.relative_to(ROOT).as_posix()))
    if rc != 0 or not elf.exists():
        raise SystemExit('[rv64ui] 编译失败 %s（rc=%d）\n%s' % (name, rc, out[-2000:]))
    rc, dis = bash('cd /d/virtual_riscv && riscv64-unknown-elf-objdump -d %s'
                   % elf.relative_to(ROOT).as_posix())
    if rc != 0:
        raise SystemExit('[rv64ui] objdump 失败 %s（rc=%d）\n%s' % (name, rc, dis[-2000:]))
    dump.write_text(dis, encoding='utf-8', newline='\n')

    entry, segs, syms = parse_elf(elf)
    # fail-closed 不变式（本批实测踩过：上游 `.align 6` 会把 tohost 顶到 0x4000_0040，表现为"不停机"）
    if syms.get('tohost') != TOHOST:
        raise SystemExit('[rv64ui] %s 的 `tohost` 符号 = 0x%x ≠ 约定停机地址 0x%x（fail-closed）'
                         % (name, syms.get('tohost', 0), TOHOST))
    if entry != syms.get('_start') or entry != 0x1000:
        raise SystemExit('[rv64ui] %s entry=0x%x / _start=0x%x：入口必须＝RESET_PC 0x1000（fail-closed）'
                         % (name, entry, syms.get('_start', 0)))
    words = seg_words(segs)
    hexp, tbhexp = OUT_DIR / ('%s.hex' % name), OUT_DIR / ('%s.tb.hex' % name)
    write_hex(words, hexp)
    tb_words = [(a, w) for a, w in words if a < CODE_LIMIT]
    write_hex(tb_words, tbhexp)

    data_words = [(a, w) for a, w in words if a >= CODE_LIMIT]
    data_all_zero = all(w == 0 for _, w in data_words)
    # ---- 数据视图（`<name>.data.hex`；TB `+DATA=` 预载用；ISS-126 机制件）----
    # 只保留落在 **TB 数据窗** [DATA_BASE, DATA_BASE+DATA_WIN_BYTES) 内的数据字，地址**减去
    # DATA_BASE**（TB 数组以窗首为 0 基址）——窗外的数据字在 TB 上**无承载**，逐条计数落 MANIFEST，
    # 由 `flow.py` 判据②据此 fail-closed（"该条不可在本 TB 上判"，不静默跳过）。
    data_win = [(a - DATA_BASE, w) for a, w in data_words
                if DATA_BASE <= a < DATA_BASE + DATA_WIN_BYTES]
    n_data_out = len(data_words) - len(data_win)
    datahexp = OUT_DIR / ('%s.data.hex' % name)
    write_hex(data_win, datahexp)
    ents = mnemonics_of(dis)
    gap = sorted(set(ents) - RTL_SUPPORTED)
    info = {
        'name': name, 'src': src.relative_to(ROOT).as_posix(),
        'elf': elf.relative_to(ROOT).as_posix(), 'dump': dump.relative_to(ROOT).as_posix(),
        'hex': hexp.relative_to(ROOT).as_posix(), 'hex_md5': md5(hexp),
        'tb_hex': tbhexp.relative_to(ROOT).as_posix(), 'tb_hex_md5': md5(tbhexp),
        'data_hex': datahexp.relative_to(ROOT).as_posix(), 'data_hex_md5': md5(datahexp),
        'entry': entry, 'tohost': TOHOST,
        'segments': [{'name': s['name'], 'addr': s['addr'], 'bytes': len(s['data'])}
                     for s in segs],
        'n_words_code': len(tb_words), 'n_words_data': len(data_words),
        'data_words_all_zero': data_all_zero,
        'n_words_data_win': len(data_win), 'n_words_data_outside_tb_win': n_data_out,
        'mnemonics': sorted(set(ents)), 'n_instr': len(ents),
        'gap_vs_rtl_subset': gap,
    }
    if verbose:
        print('[rv64ui] %-16s elf=%s entry=0x%x seg=%s code=%d 字 data=%d 字(zero=%s) 指令 %d 种'
              % (name, elf.name, entry,
                 ','.join('%s@0x%x(%dB)' % (s['name'], s['addr'], len(s['data'])) for s in segs),
                 len(tb_words), len(data_words), data_all_zero, len(set(ents))))
        print('[rv64ui] %-16s 数据视图 %d/%d 字入窗（窗外 %d），data.hex=%s'
              % (name, len(data_win), len(data_words), n_data_out, datahexp.name))
        print('[rv64ui] %-16s 缺口（vs RTL %d 条）%d 种：%s'
              % (name, len(RTL_SUPPORTED), len(gap), ' '.join(gap)))
    return info


def build_direct(test: str, verbose: bool = True) -> dict:
    """**定向用例**（`sw/tests/direct/<t>.S`，VR1 自建）：与 rv64ui **同一构建口径**（同 env/link.ld、
    同 ELF→三视图派生、同 fail-closed 预检），只有**源目录**与**命名前缀**不同。"""
    return build_one(test, verbose=verbose, src_dir=DIRECT_DIR,
                     name='%s%s' % (DIRECT_PREFIX, test))


def build_cov_only(spec: tuple[str, str, tuple[int, ...]], verbose: bool = True) -> dict:
    """**受控复位注入用例**（R0 2026-09-26 三项裁定①；口径见 COV_ONLY_TESTS 段注释）：
    与定向用例**同一构建口径**（同 env/link.ld、同三视图派生、同 fail-closed 预检），
    但命名前缀＝`rst_`、**不进 `tests`**，并携带 `reset_inject_cycles`（探针实测）。"""
    src, name, cycles = spec
    info = build_one(src, verbose=verbose, src_dir=DIRECT_DIR, name=name)
    info['cov_only'] = True
    info['reset_inject_cycles'] = [int(c) for c in cycles]
    info['channel_note'] = ('R0 2026-09-26 裁定 NU-2 受控通道：仅覆盖率批'
                            '（run_cmd/cover_m3_testlist.txt 的 rst_* 条目）；不进回归'
                            '（run_cmd/rv64ui_testlist.txt 无 rst_ ⇒ 回归同配置签名不变）；'
                            '不进 tests ⇒ 不受 m2-rv64ui 的 ISS<->RTL 逐条比对（复位注入使 trace '
                            '出现"重启后第二段"，构造性不可比——doc/verify/02 §6 NU-2 行）。'
                            '本通道判定＝RTL 侧 HALT_PASS ＋ 无 HALT_FAIL/WATCHDOG ＋ TB [rst_inj] '
                            '证据行（run_cmd/cover_rv1.py，fail-closed）。bin 不删、判定阈值不改'
                            '（红线 R7；判据侧通道标注见 script/flow.py:chk_m3_func_cov）。')
    return info


def _readmemh_words(path: Path) -> list[tuple[int, int]]:
    """解析 `$readmemh` 文本 → `[(字下标, 32bit 值)]`（`@n` 的 `n` 是**字**下标：与 TB 的
    `$readmemh(img, mem)` 同口径；`..` 重复语法本镜像是镜像生成器自己写的，不含）。"""
    out: list[tuple[int, int]] = []
    idx = None
    for raw in path.read_text(encoding='utf-8').splitlines():
        ln = raw.split('//')[0].strip()
        if not ln:
            continue
        if ln.startswith('@'):
            idx = int(ln[1:].strip(), 16)
            continue
        if idx is None:
            idx = 0
        for tok in ln.split():
            out.append((idx, int(tok, 16)))
            idx += 1
    return out


def import_smoke(name: str = 'm_smoke', verbose: bool = True) -> dict:
    """把**既有自研镜像**（`sim/image/<name>.hex`）纳入本清单，并在 rv64ui 目录派生
    TB 视图（`<name>.tb.hex`：只保留取指窗 `< CODE_LIMIT` 的字）与数据视图
    （`<name>.data.hex`：只保留 TB 数据窗内的字、地址减窗基址）。三视图同源＝同一份 `<name>.hex`。

    **为什么导入**（逐条可核，见文件头"导入用例"）：该镜像是 M1 判据 `rtl-vs-iss` 的激励
    （ISS golden ↔ RTL 30 条退休 0 mismatch），复用它给覆盖率批补上 `exc`／`t_idle_done`
    两个 bin，且**不引入新的未互证镜像**（"一份镜像喂两边"口径不变）。
    """
    src_hex = IMAGE_DIR / ('%s.hex' % name)
    if not src_hex.exists():
        raise SystemExit('[rv64ui] 缺 %s（fail-closed）⇒ 先跑 python sw/tests/gen_smoke_image.py'
                         % src_hex)
    words_byte = [(w * 4, v) for w, v in _readmemh_words(src_hex)]      # 字下标 → 字节地址
    if not words_byte:
        raise SystemExit('[rv64ui] %s 解析出 0 个字（fail-closed）' % src_hex)
    tb_words = [(a, v) for a, v in words_byte if a < CODE_LIMIT]
    data_all = [(a, v) for a, v in words_byte if a >= CODE_LIMIT]
    data_win = [(a - DATA_BASE, v) for a, v in data_all
                if DATA_BASE <= a < DATA_BASE + DATA_WIN_BYTES]
    n_data_out = len(data_all) - len(data_win)
    tbhexp = OUT_DIR / ('%s.tb.hex' % name)
    datahexp = OUT_DIR / ('%s.data.hex' % name)
    write_hex(tb_words, tbhexp)
    write_hex(data_win, datahexp)
    info = {
        'name': name, 'src': src_hex.relative_to(ROOT).as_posix(),
        'elf': '', 'dump': '',                       # 无 ELF（自研汇编器直接产镜像）
        'hex': src_hex.relative_to(ROOT).as_posix(), 'hex_md5': md5(src_hex),
        'tb_hex': tbhexp.relative_to(ROOT).as_posix(), 'tb_hex_md5': md5(tbhexp),
        'data_hex': datahexp.relative_to(ROOT).as_posix(), 'data_hex_md5': md5(datahexp),
        'entry': 0x1000, 'tohost': TOHOST,
        'segments': [{'name': 'imported', 'addr': words_byte[0][0], 'bytes': 4 * len(words_byte)}],
        'n_words_code': len(tb_words), 'n_words_data': len(data_all),
        'data_words_all_zero': all(v == 0 for _a, v in data_all),
        'n_words_data_win': len(data_win), 'n_words_data_outside_tb_win': n_data_out,
        'mnemonics': [], 'n_instr': 0, 'gap_vs_rtl_subset': [],
        'imported': True,
        'source_note': ('**导入**：镜像源＝%s（自研汇编器产；M1 `rtl-vs-iss` 的激励，'
                        'ISS↔RTL 30 条 0 mismatch）。三视图由本脚本从同一份 .hex 派生：'
                        'tb.hex 只保留 addr < 0x%x 的字、data.hex 只保留 TB 数据窗内（地址减窗基址）'
                        '的字。`mnemonics` 面留空（无 objdump 反汇编；该面只服务 GAP 清单，'
                        '不参与任何判据）。' % (src_hex.relative_to(ROOT).as_posix(), CODE_LIMIT)),
    }
    if verbose:
        print('[rv64ui] %-16s 导入：%d 字（取指窗 %d ／ 数据窗 %d ／ 窗外 %d）；tb.hex=%s data.hex=%s'
              % (name, len(words_byte), len(tb_words), len(data_win), n_data_out,
                 tbhexp.name, datahexp.name))
    return info


ALL_TESTS = ('add addi addiw addw and andi auipc beq bge bgeu blt bltu bne simple fence_i '
             'jal jalr lb lbu lh lhu lw lwu ld lui ma_data or ori sb sh sw sd sll slli slliw '
             'sllw slt slti sltiu sltu sra srai sraiw sraw srl srli srliw srlw sub subw xor '
             'xori').split()

# --------------------------------------------------------------------------- #
# 判定子集：＝`MANIFEST.tests`＝`run_cmd/rv64ui_testlist.txt` 的集合，由
# `python script/flow.py check-one m2-rv64ui` **逐条真跑**（ISS + RTL + trace_compare）。
#
# 入集判据（四条，全部机械可复核；任一不满足即**不进集**并落 `GAP.json.pending_subset`）：
#   ① **能编**：`riscv64-unknown-elf-gcc` 过（`fence_i` 需 `MARCH_OVERRIDE` 的 `zifencei`）；
#   ② **不依赖未实现指令**：助记符缺口（vs `RTL_SUPPORTED`）仅剩 `unimp`
#      （`unimp` 是 `RVTEST_CODE_END` 的编码，恒出现在 `tohost` 停机**之后** ⇒ 两侧都不执行）；
#   ③ **本 TB 可承载**：`n_words_data_outside_tb_win == 0`（数据视图全落在 TB 数据窗内）；
#   ④ **实测过**：`check-one m2-rv64ui` 真跑 0 失败。
#
# 实测面（2026-09-26 心跳第 8 轮）：把 51 条能编的全编出来跑一遍 ⇒ 36 条过为子集；其余 15 条
#   失败逐条落 `GAP.json.pending_subset`（**不静默跳过**）。失败面：14 条 RTL 侧
#   `HALT_FAIL val=0x539`（＝`sw/env/riscv_test.h` 差异表第 4 条的"未处理异常"标记 1337，
#   即测试体用到本核未实现的指令 ⇒ 非法指令路径）＋ 1 条 `ma_data` ISS 侧 `halt_val=0x539`。
#
# **2026-09-26 心跳第 10 轮（M3-(d)「补缺指令」批）**：RTL 侧补入分支余 4 条／JALR／载入余 6 条／
#   存储余 3 条／FENCE.FENCE.I，并把 TB 访存桩扩到双字窗 ＋ 字节使能 ⇒ 判定子集扩到 50 条
#   （原 36 ＋ 新纳入 14）；`fence_i`（缺机制：代码窗 store 无承载）与 `ma_data`（缺机制：
#   `MISALIGNED_EN=0` 口径）**显式列缺带归属**，留在子集外。
# --------------------------------------------------------------------------- #
JUDGE_SUBSET = ('add addi addiw addw and andi auipc beq bne simple jal lui or ori xor xori slt sltiu '
                'sltu sll slli slliw sllw srl srli srliw srlw sra srai sraiw sraw sub slti subw lw '
                'sw blt bge bltu bgeu jalr lb lbu lh lhu lwu ld sb sh sd').split()

# 逐条机制性缺口（**声明式**，每条带出处；用于 `pending_subset` 里"哪个机制"一栏）。
# 只列**机械判据判不出**（助记符缺口之外）的机制依赖；未列入者其唯一原因是助记符缺口。
MECHANISM_NEEDS = {
    'fence_i': '自修改代码（SMC）＋**取指侧可执行域与数据窗不统一**：测试体把指令字写进 **`.data` 段**'
               '（0x4000_0200 起，`2:`/`3:` 两个标签都落在 `.data`）后 `fence.i` ＋ `jalr` **跳进数据窗执行**'
               '—— 本 TB 取指桩 `fmem` 只覆盖 0x0000~0x3FFF（`fetch_word` 的 `byte_addr[39:14]==0` 守卫），'
               '0x4000_02xx 的取指**回 0**（＝非法指令字）⇒ RTL 侧必然走异常路径（首版无 L1I／无统一内存／'
               '无 I-cache 无效化面）。**实测（2026-09-26 心跳第 10 轮）**：ISS 侧 `halt_val=0x1`（**PASS**，'
               '其 `Bus` 是统一内存、数据窗可执行）；RTL 侧 `HALT_FAIL val=0x539 testnum=668 rows=73`，'
               '首个分歧＝pc=0x40000204 取回 `bin=00000000`（ISS 同址取回真实指令字 `14d68693`）'
               '⇒ **本阶段不可判**（非"指令未实现"：`fence.i` 已入 RTL 面，见 `rtl/vr1/ctrl/vr1_decode.sv`）。'
               '证据：`sim/run_m3d_pending/probe.log` ＋ 该目录两侧 CSV。'
               '**缺带归属（2026-09-26 心跳第 15 轮补）**：机制实现批＝`spec/09`（L1I／取指粒度与统一内存）'
               '＋ `spec/03` 的 SMC／`fence.i` 无效化面（G1-I 清单 §3 延后类「cache 层次」）；该面落地后'
               '本条目从本清单移出并进 `tests`（届时同受 `m2-rv64ui` 判定）。',
    'ma_data': '非对齐访存：`spec/00` §4 的 `MISALIGNED_EN=0`（ISS 侧同样不得带 `--misaligned`，'
               '`doc/process/00` ISS-010）⇒ **两侧口径一致地不支持**，本阶段不可判。'
               '**实测（2026-09-26 心跳第 10 轮）**：ISS 侧 `halt_val=0x539`（FAIL）／RTL 侧 '
               '`HALT_FAIL val=0x539 testnum=668 rows=52`（`dmem_ld=0`＝非对齐 load **不发任何请求**即报 '
               'fault，码 4；构造性证据）—— 与"两侧一致不支持"逐条相符，**不是** DUT 缺陷。'
               '证据：`sim/run_m3d_pending/probe.log` ＋ 该目录两侧 CSV。'
               '**缺带归属（2026-09-26 心跳第 15 轮补）**：一期**参数口径**面（`MISALIGNED_EN=0` 是一期'
               '取值，非缺陷）⇒ 一期判据面内**永久不判**且两侧一致；二期若抬档改 `MISALIGNED_EN=1`'
               '（须走 spec 升版＋Requirement Review，`AGENTS.md` §1 路径 A），本条目随该批重评。',
}

# `check-one m2-rv64ui` 的三处写出点（`script/flow.py:chk_m2_rv64ui`）：节头即判定类别。
RE_RUN_SEC = re.compile(r'\n\[(rv64ui-p-[a-z_0-9]+)(?: (RTL|ISS))?\]\n')
RE_RUN_HALT_FAIL = re.compile(r'HALT_FAIL\s+tohost=\S+\s+val=(\S+)\s+testnum=(\S+)')
RE_RUN_HALT_VAL = re.compile(r'halt_val=(\S+)')
RE_RUN_MISMATCH = re.compile(r'mismatch=(\d+)')


def parse_run_evidence(path: 'Path | str | None') -> dict | None:
    """从 `check-one m2-rv64ui` 的运行日志**机械**提取逐条判定签名（不手抄、不美化）。

    节头语义（与 `script/flow.py:chk_m2_rv64ui` 的写出点一一对应）：
      `[<name> ISS]` ⇒ ISS 侧未 PASS（`halt_val≠1`，测试/镜像侧或 ISS 面，先归因）；
      `[<name> RTL]` ⇒ RTL 侧自报 `HALT_FAIL`/`WATCHDOG_TIMEOUT`（未停机/超时）；
      `[<name>]`     ⇒ 走到比对（可能仍 FAIL：长度不等 / CSV 缺失 / `mismatch>0`）。
    每条测试在日志里**恰有一节**（三种节头互斥）⇒ 节头即判定类别；段内只取**首个**匹配
    （`_msim` 会把下一例的 transcript 追加在本节尾，取首个才保同一条）。
    """
    if not path:
        return None
    p = Path(path) if os.path.isabs(str(path)) else (ROOT / str(path))
    if not p.exists():
        return None
    s = p.read_text(encoding='utf-8', errors='replace')
    hs = list(RE_RUN_SEC.finditer(s))
    out = {}
    for i, m in enumerate(hs):
        name, tag = m.group(1), (m.group(2) or 'FULL')
        end = hs[i + 1].start() if i + 1 < len(hs) else len(s)
        body = s[m.end():end]
        hf = RE_RUN_HALT_FAIL.search(body)
        hv = RE_RUN_HALT_VAL.search(body)
        mm = RE_RUN_MISMATCH.search(body)
        if tag == 'ISS':
            verdict, why = 'FAIL_ISS', ('ISS 侧未 PASS（halt_val=%s）——镜像/测试自身或 ISS 缺陷，先归因'
                                        % (hv.group(1) if hv else '?'))
        elif tag == 'RTL':
            verdict, why = 'FAIL_RTL', ('RTL 侧自报失败（HALT_FAIL val=%s testnum=%s；未停机/超时）——'
                                        'RTL 侧未跑通' % (hf.group(1) if hf else '?',
                                                          hf.group(2) if hf else '?'))
        elif (mm is not None) and mm.group(1) == '0':
            verdict, why = 'PASS', ''
        else:
            verdict, why = 'FAIL_CMP', ('未 0 mismatch（mismatch=%s）或未走到比对（长度不等/CSV 缺失）'
                                        % (mm.group(1) if mm else '?'))
        out[name] = {'verdict': verdict, 'detail': why}
    return out or None


def pending_subset(gap_all: dict, evidence: dict | None, judge: list[str]) -> dict:
    """待补清单：全部 `ALL_TESTS` 逐条给「是否在判定子集 / 缺哪些指令 / 编译过否 / 实测签名」。"""
    per = (gap_all or {}).get('per_test') or {}
    judge_set = set(judge)
    entries = []
    for t in ALL_TESTS:
        info = per.get(t) or {}
        name = 'rv64ui-p-%s' % t
        gap = [m for m in (info.get('gap_vs_rtl_subset') or []) if m != 'unimp']
        if info.get('error'):
            kind = '编译失败'
        elif t in MECHANISM_NEEDS:
            kind = '缺机制'
        elif gap:
            kind = '缺指令'
        else:
            kind = '（无缺口）'
        ev = (evidence or {}).get(name)
        entries.append({
            'name': name,
            'in_judge_subset': t in judge_set,
            'kind': kind,
            'missing_instructions': gap,
            'mechanism_need': MECHANISM_NEEDS.get(t, ''),
            'buildable': not bool(info.get('error')),
            'empirical': (ev or {}).get('verdict', '(未提供本轮运行证据)'),
            'empirical_detail': (ev or {}).get('detail', ''),
        })
    return {
        'meaning': '**待补清单**：判定子集之外的每一条 rv64ui-p-* 的如实归属与原因'
                   '（`script/flow.py check-one m2-rv64ui` 只判 `MANIFEST.tests`＝判定子集；'
                   '不在子集里的条目在此逐条交代，**不静默跳过**）',
        'judge_subset': ['rv64ui-p-%s' % t for t in judge],
        'n_judge_subset': len(judge),
        'n_all_tests': len(ALL_TESTS),
        'kind_legend': {'缺指令': '测试体用到 RTL 子集外指令（见 missing_instructions）',
                        '缺机制': '助记符缺口之外的机制依赖（见 mechanism_need）',
                        '编译失败': '本工具链口径下编不过（见 per_test 的 error 字段）'},
        'evidence': ('实测面＝`sim/run_m2_rv64ui/run.log`（由 `--run-evidence` 机械解析；'
                     '`script/flow.py:chk_m2_rv64ui` 的节头即判定类别）'),
        'entries': entries,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='riscv-tests rv64ui 构建与镜像')
    ap.add_argument('--tests', nargs='*', default=list(JUDGE_SUBSET),
                    help='构建入 MANIFEST 的测试名（默认＝判定子集 JUDGE_SUBSET，%d 条）'
                         % len(JUDGE_SUBSET))
    ap.add_argument('--gap-all', action='store_true', help='额外对全部 rv64ui 测试算缺口清单')
    ap.add_argument('--run-evidence', default='sim/run_m2_rv64ui/run.log',
                    help='`check-one m2-rv64ui` 的运行日志（机械解析成 pending_subset 的实测签名；'
                         '缺文件时如实标"未提供"）')
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rc, ver = bash('riscv64-unknown-elf-gcc --version | head -1')
    toolchain = ver.strip().splitlines()[0] if rc == 0 else 'unknown'

    infos = [build_one(t) for t in args.tests]
    # **定向用例 ＋ 导入镜像**（2026-09-26 心跳第 12 轮；见文件头 DIRECTION 段）——它们同为
    # `MANIFEST.tests` 的成员 ⇒ 同样受 `m2-rv64ui` 逐条真跑判定（无免判通道）。
    direct_infos = [build_direct(t) for t in DIRECT_TESTS]
    import_infos = [import_smoke(n) for n in IMPORT_CASES]
    all_infos = infos + direct_infos + import_infos
    # **受控复位注入用例**（2026-09-26 心跳第 13 轮；R0 三项裁定①）——**不进** `tests`，
    # 只落 `cov_only_tests` 字段（受控通道：仅覆盖率批；见 COV_ONLY_TESTS 段注释）。
    cov_only_infos = [build_cov_only(s) for s in COV_ONLY_TESTS]

    gap_all = None
    if args.gap_all:
        per, union = {}, set()
        for t in ALL_TESTS:
            try:
                info = build_one(t, verbose=False)
            except SystemExit as exc:
                per[t] = {'error': str(exc)[:200]}
                continue
            per[t] = {'mnemonics': info['mnemonics'], 'gap_vs_rtl_subset': info['gap_vs_rtl_subset'],
                      'n_instr': info['n_instr']}
            union |= set(info['mnemonics'])
        gap_all = {
            'rtl_supported': sorted(RTL_SUPPORTED),
            'union_mnemonics': sorted(union),
            'union_gap_vs_rtl_subset': sorted(union - RTL_SUPPORTED),
            'n_tests': len(ALL_TESTS), 'per_test': per,
            'note': '助记符由 objdump -d 机械提取并归一到基础指令名（MNEMONIC_ALIAS）；'
                    'RTL 支持面＝G1-I 清单 §1.1 的 14 条 ＋ M2 增补 27 条（合 41 条，'
                    'rtl/vr1/ctrl/vr1_decode.sv 的 isop 表）。'
                    '`unimp` 恒出现在清单里（RVTEST_CODE_END 的编码），但它在 tohost 停机之后'
                    '⇒ 两侧都不执行（被停机短路），不计为真实缺口——判据以 RTL 侧实跑的首处分歧为准。',
        }
        ev = parse_run_evidence(args.run_evidence)
        gap_all['pending_subset'] = pending_subset(gap_all, ev, args.tests)
        if ev is None:
            print('[rv64ui] 注意：未取到运行证据（%s 不存在）⇒ pending_subset.entries[].empirical '
                  '标"(未提供本轮运行证据)"（如实标注，不假装）' % args.run_evidence)
        (OUT_DIR / 'GAP.json').write_text(json.dumps(gap_all, ensure_ascii=False, indent=1) + '\n',
                                          encoding='utf-8', newline='\n')
        pend = [e for e in gap_all['pending_subset']['entries'] if not e['in_judge_subset']]
        print('[rv64ui] 缺口清单（union，全部 %d 条测试）：%d 种指令，其中 RTL 子集外 %d 种：\n        %s'
              % (len(ALL_TESTS), len(union), len(union - RTL_SUPPORTED),
                 ' '.join(sorted(union - RTL_SUPPORTED))))
        print('[rv64ui] 待补清单：判定子集 %d 条 ／ 子集外 %d 条（%s）'
              % (len(args.tests), len(pend),
                 '；'.join('%s=%s' % (e['name'].replace('rv64ui-p-', ''), e['kind']) for e in pend)))
        print('[rv64ui] GAP.json → %s' % (OUT_DIR / 'GAP.json').relative_to(ROOT).as_posix())

    man = {
        'generator': 'sw/tests/build_rv64ui.py',
        'toolchain': toolchain,
        'judge_subset': {
            'rule': '入集四条（机械）：①能编 ②助记符缺口仅剩 unimp ③TB 数据窗可承载 '
                    '④`check-one m2-rv64ui` 真跑 0 失败；详见本脚本 JUDGE_SUBSET 处注释与 '
                    'doc/verify/05 的 R 记录',
            'n': len(args.tests),
            'names': ['rv64ui-p-%s' % t for t in args.tests],
            'pending': 'GAP.json 的 `pending_subset`（子集外逐条原因：缺指令/缺机制/编译失败'
                       '＋本轮实测签名，**不静默跳过**）',
        },
        'env': {'header': 'sw/env/riscv_test.h', 'link': 'sw/env/link.ld',
                'macros': 'sw/tests/riscv-tests/isa/macros/scalar/test_macros.h',
                'src': 'sw/tests/riscv-tests/isa/rv64ui/<t>.S（上游逐字副本，见 ORIGIN.md）'},
        'abi': {'arch': 'rv64im_zicsr', 'mabi': 'lp64', 'entry': '_start (RESET_PC)',
                'tohost': TOHOST, 'code_window': [0x1000, CODE_LIMIT],
                'data_window': [DATA_BASE, DATA_WIN_BYTES],
                'tb_data_window_consts': {'DRAM_BASE': DATA_BASE, 'DMEM_WORDS': DATA_WIN_BYTES // 4}},
        'derivation': '三视图同源（同一 ELF、同一段字序）：tb.hex 只保留 addr < 0x%x 的段、地址与字'
                      '**逐字不变**；data.hex 只保留落在 TB 数据窗 [0x%x, 0x%x) 的字、地址**减去窗基址**'
                      '（TB `+DATA=` 的数组口径）；窗外的数据字在 TB 上无承载（逐条记 '
                      '`n_words_data_outside_tb_win`，非 0 ⇒ 该条不可在本 TB 上判，判据② fail-closed）。'
                      '`data_words_all_zero` 保留为**记录事实**：自 2026-09-26 心跳第 6 轮加 `+DATA=` '
                      '预载后，等价性不再依赖它，而由「数据窗内容 = 镜像数据段」直接保证（data.hex 的 '
                      'md5 ＋ 窗口声明为机判面）' % (CODE_LIMIT, DATA_BASE, DATA_BASE + DATA_WIN_BYTES),
        # **定向/导入用例面**（2026-09-26 心跳第 12 轮）：与 rv64ui 同为 `tests` 成员（同受
        # `m2-rv64ui` 判定）。定向源＝`sw/tests/direct/<t>.S`（命名 `vr1dir-p-<t>`）；
        # 导入源＝既有自研镜像（`sim/image/<n>.hex`，M1 `rtl-vs-iss` 的激励）。
        'directed': {
            'why': 'M3-(b) 覆盖缺口补激励（VP-05 的 CSR 读面／VP-08＋VP-X02 的异常条目面）；'
                   '缺 bin 依据＝`doc/verify/07-m2cov_r2.txt` §A 的 ZERO 清单',
            'direct_src_dir': DIRECT_DIR.relative_to(ROOT).as_posix(),
            'direct_names': [i['name'] for i in direct_infos],
            'imported_names': [i['name'] for i in import_infos],
            'rule': '与 rv64ui **同一构建口径**（同 env/link.ld、同三视图派生、同 fail-closed 预检）；'
                    '全部条目都在 `tests` 里 ⇒ 受 `m2-rv64ui` 逐条真跑判定，无"覆盖率专用"免判通道',
        },
        # **受控复位注入通道**（2026-09-26 心跳第 13 轮；**R0 三项裁定①**＝`doc/verify/02` §6 NU-2）：
        # 条目**只在 `cov_only_tests`**、不进 `tests` ⇒ 不进 `m2-rv64ui` 判定面、不进回归同配置；
        # 仅覆盖率批按 `rst_` 前缀从本字段解析（`run_cmd/cover_rv1.py`），并按条目的
        # `reset_inject_cycles` 给 vsim 加 `+RESET_INJECT=`。这是 R0 授权的**唯一**通道例外，
        # 其判定口径见各条目 `channel_note`（fail-closed，非免判）。
        'controlled_channel': {
            'why': 'NU-2：`cg_lsu_fsm` 的 t_req_idle/t_rsp_idle 只有运行中复位能命中，而该用例'
                   '不能进 `tests`（ISS↔RTL 比对构造性不可比）⇒ R0 2026-09-26 裁定走受控通道',
            'mechanism': 'tb/unit/m1_e2e_tb.sv 的 +RESET_INJECT=<cycle>[,...]（不给 plusarg 时'
                         '逐字保持原行为）；判定＝run_cmd/cover_rv1.py 受控通道单例执行',
            'regression_isolation': 'run_cmd/rv64ui_testlist.txt（回归面）不含 rst_ 前缀 ⇒ 回归'
                                    '同配置签名不受影响；MANIFEST.tests 也不含本字段条目',
            'names': [i['name'] for i in cov_only_infos],
        },
        'cov_only_tests': cov_only_infos,
        'tests': all_infos,
    }
    (OUT_DIR / 'MANIFEST.json').write_text(json.dumps(man, ensure_ascii=False, indent=1) + '\n',
                                           encoding='utf-8', newline='\n')
    m = infos[0]
    print('[rv64ui] MANIFEST -> %s（%d 条；%s hex_md5=%s）'
          % ((OUT_DIR / 'MANIFEST.json').relative_to(ROOT).as_posix(), len(all_infos),
             m['name'], m['hex_md5'][:12]))
    if cov_only_infos:
        print('[rv64ui] cov_only_tests -> %s（%d 条；受控复位注入通道，R0 2026-09-26 裁定 NU-2；'
              '不进 tests/不进回归）'
              % (' '.join('%s@%s' % (i['name'], ','.join(str(c) for c in i['reset_inject_cycles']))
                          for i in cov_only_infos), len(cov_only_infos)))
    gap_union = sorted({m for i in all_infos for m in i['gap_vs_rtl_subset']})
    print('[rv64ui] built=%s gap_union=%d 种：%s'
          % (' '.join(i['name'] for i in all_infos), len(gap_union), ' '.join(gap_union)))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
