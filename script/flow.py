#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flow.py — 方案 A（Runner-in-the-Loop）的唯一推进命令。

SSOT：本文件是唯一推进权威；状态唯一真值 = `state/flow.json`；编号由本脚本自增（禁手写）。
落地依据：`doc/process/03-自动化流程重构-三方案.md`（A 为骨架 / B 判据按模块增量 / C 里程碑边界启用）。

子命令
  check                     全部判据（0 FAIL 才算过）；判据只判**产品**，不判流程仪式
                            退出码：0 = 全过 ／ 1 = 有 FAIL ／ 3 = **产品面只剩** ENV-BLOCKED
                            （判 3 的条件：存在环境阻塞且**无**非环境的产品/前置 FAIL；
                            常跑守卫不判产品，其 FAIL 不把 3 压回 1，但仍在摘要行单列。
                            环境阻塞**绝不返回 0**；ENV-BLOCKED 明细由判据结果自报识别，
                            不再只依赖里程碑手填字段 `env_blocked`）
  next                      输出下一步（唯一权威；人/脚本/agent 都读它）
  run                       执行确定性步骤（编译/仿真/比对…），失败即停并交回控制权
  params                    从 doc/spec/00 §4 重新生成 rtl/vr1/include/vr1_params.svh（参数单源）
  ctx                       SessionStart hook 用：注入 ≤2K token 的当前目标/判据/禁令
  gate-stop                 Stop hook 用：里程碑未达则请求继续（自带上限，防死循环）
  guard-write               PreToolUse(Write|Edit) hook：机械执行写边界（三档，见下）
  guard-bash                PreToolUse(Bash) hook：机械拦截破坏性命令

写边界三档（`guard-write`；状态件＝`state/freeze.json`）
  档 1 未冻结（`state/freeze.json` 不存在，G1 前）：`rtl/**` 只允许 `rtl/vr1/include/*.svh`
  档 2 G1-I 已签授权（`rtl_write_authorized` 为真且 `baseline` 未宣布）：`rtl/**` 允许写，
       依据＝R0 2026-09-25 签署 G1-I 的人令（记录落 `doc/spec/14` §7）
  档 3 基线已宣布（`baseline != "未宣布"`，优先于档 2）：`rtl/**` 拒绝（红线 R5 先批后改）
  兜底：状态件在但既未授权、基线也未宣布 ⇒ 按已冻结处理（`rtl/**` 只读，红线 R1）
  恒久受保护：`sim/covdb/**`（签核证据）、`.git/**`、`state/window.json`
  window [--take --reason]  内容指纹窗口（收工即查 / 折入基线）
  record <ISS|R|ADR> "文本"  自动编号登记（禁手写编号）
                            ADR 走编号分区：id 形如 `ADR-P-<n>`（分区口径见 `AGENTS.md` §0）
  board                     台账计数

hook 约定（ZCode）：stdin 收 JSON；exit 0 = 放行，exit 2 = 阻断/请求继续，其余非零 = 出错。
守卫策略刻意 fail-open（解析不了就放行并告警）：守卫是安全网，不是产品门；
若因 schema 变化把守卫写成 fail-closed，会一票否决所有写操作，反而停摆主线。
真正的产品门在 `check` / `run`，那两条是 fail-closed（解析不到证据行一律 FAIL）。
"""
from __future__ import annotations

import csv
import hashlib
import glob
import io
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
STATE = os.path.join(ROOT, 'state', 'flow.json')
LEDGER = os.path.join(ROOT, 'doc', 'process', 'ledger.json')
WINDOW = os.path.join(ROOT, 'state', 'window.json')
SPEC00 = os.path.join(ROOT, 'doc', 'spec', '00-总体规格.md')
SPEC01 = os.path.join(ROOT, 'doc', 'spec', '01-流水线与寄存器接口.md')
PARAMS_SVH = os.path.join(ROOT, 'rtl', 'vr1', 'include', 'vr1_params.svh')
TYPES_SVH = os.path.join(ROOT, 'rtl', 'vr1', 'include', 'vr1_types.svh')
PARAMS_PKG = os.path.join(ROOT, 'tb', 'unit', 'params_pkg.sv')
TYPES_PKG = os.path.join(ROOT, 'tb', 'unit', 'types_pkg.sv')
# ADR-P-2 的机判切分表（决策 AI 产出，自检器 doc/decisions/check_if_split.py）。**只读输入**：
# flow.py 只消费它把非标量成员行展开成真实字段声明，不改写、不合成、不猜测。
IF_SPLIT = os.path.join(ROOT, 'doc', 'decisions', 'if_split.json')
ADR_DIR = os.path.join(ROOT, 'doc', 'decisions')
IMAGE_MANIFEST = os.path.join(ROOT, 'sim', 'image', 'MANIFEST.txt')
ISS_HEX_CSV = 'sim/run_P3/hex_side.csv'
GOLDEN = os.path.join(ROOT, 'sim', 'golden', 'iss_smoke.csv')
MTI = os.environ.get('MTI', r'D:\modeltech64_2020.4\win64')
VLOG = os.path.join(MTI, 'vlog.exe')
VLIB = os.path.join(MTI, 'vlib.exe')
VOPT = os.path.join(MTI, 'vopt.exe')
VSIM = os.path.join(MTI, 'vsim.exe')
# ModelSim license（ISS-104 双网卡漂移）：本机两块网卡**谁在机上会变**，两份节点锁 license 各绑一个
# MAC（`C:\flexlm_2020\LICENSE.TXT` 绑 `…5abe`＝板载 WLAN；`C:\flexlm\LICENSE.TXT` 绑 `…5aa2`＝
# 可拔插 USB GbE）⇒ 只固定指向某一份仍会再翻车，故**两份都列上**让 flexlm 自行挑匹配的那份。
# 实测（2026-09-25）：两份都指陈旧那份 ⇒ `Invalid host.` ＋ `Failure to obtain a Verilog simulation
# license`；两份并列 ⇒ PASS。只在 ModelSim 子进程**会话内**注入，不改系统环境变量、不写注册表。
MSIM_LICENSE_PATHS = (r'C:\flexlm_2020\LICENSE.TXT', r'C:\flexlm\LICENSE.TXT')

try:                                    # GBK 控制台下不得因特殊字符炸掉退出码（ISS-103 教训）
    sys.stdout.reconfigure(errors='replace')
    sys.stderr.reconfigure(errors='replace')
except Exception:
    pass

KINDS = ('ISS', 'R', 'ADR')
KIND_KEY = {'ISS': 'ISS', 'R': 'R', 'ADR': 'ADR'}

# 写边界（guard-write）：恒久受保护；rtl/ 仅在 state/freeze.json 存在时受保护
ALWAYS_PROTECTED = ('sim/covdb/', '.git/', 'state/window.json')
BASH_DENY = [
    (r'\brm\s+-[a-z]*[rf]', 'rm -rf/rf 类删除'),
    (r'\brmdir\s+/s', 'rmdir /s 递归删除'),
    (r'\bdel\s+/[sq]', 'del /s|/q 删除'),
    (r'\bformat\s+[a-z]:', '格式化磁盘'),
    (r'git\s+reset\s+--hard', 'git reset --hard（丢弃工作区）'),
    (r'git\s+clean\s+-[a-z]*f', 'git clean -f（删未跟踪文件）'),
    (r'git\s+push\b.*--force', 'git push --force'),
    (r'>\s*sim/covdb', '重定向写入签核受保护区 sim/covdb'),
]
FREEZE = os.path.join(ROOT, 'state', 'freeze.json')


# --------------------------------------------------------------------------- #
# 基础
# --------------------------------------------------------------------------- #
def run(cmd, cwd=None, timeout=None, env=None):
    p = subprocess.run(cmd, cwd=cwd or ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, errors='replace', timeout=timeout, env=env)
    return p.returncode, p.stdout or ''


def last_line(text):
    for ln in reversed([x.strip() for x in (text or '').splitlines() if x.strip()]):
        return ln
    return '(no output)'


def load_json(path, default=None):
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def md5_of(path):
    with open(path, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()


def norm_path(p):
    return p.replace('\\', '/').lstrip('./')


def read_stdin_json():
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:                                   # noqa: BLE001
        print('[flow] stdin 不是 JSON：%s' % e, file=sys.stderr)
        return None


# --------------------------------------------------------------------------- #
# 参数单源（B 的判据内核，第一块：spec/00 §4 → vr1_params.svh）
# --------------------------------------------------------------------------- #
SECTION_RE = re.compile(r'^#{2,3}\s')
ROW_RE = re.compile(r'^\|(.+)\|\s*$')
NAMES_RE = re.compile(r'`([A-Za-z_][A-Za-z0-9_]*)(\[\d+\])?`')
LIT_RE = re.compile(r"^(\d+)'([hbod])([0-9a-fA-F_]+)$")
INT_RE = re.compile(r'^(\d+)')
ARR_RE = re.compile(r'^(\d+)(\s*,\s*\d+)+$')
# 0x/0b/0o 前缀字面量（spec 里的书写形式，如 `0x8000_0000_0014_1105`）。
# 必须走字面量分支：INT_RE 的 `^(\d+)` 会把它读成十进制 0（假绿，见 ISS-107④）。
PREFIXLIT_RE = re.compile(r'^0([xbo])([0-9a-fA-F_]+)$')
PREFIX_RE = re.compile(r'^0[xbo]')
BASE_DIGIT = {'x': r'[0-9a-fA-F]', 'b': r'[01]', 'o': r'[0-7]'}
BASE_BIT = {'x': 4, 'b': 1, 'o': 3}
BASE_SV = {'x': 'h', 'b': 'b', 'o': 'o'}        # spec 前缀 → SystemVerilog 进制符（hex 写作 'h）
# 计数项加式：`2R + 2W`（仅 '数字[+单字母单位]' 项以 '+' 相连时才求和；其余一律 UNPARSED）
COUNTSUM_RE = re.compile(r'^\d+[A-Za-z]?(\s*\+\s*\d+[A-Za-z]?)+$')
# 「数字＋单位」单元格（如 `32 KB`／`64 B`／`4 B（G=0）`／`256 KB / 16 / 64 B` 的逐项）：
# **数值照取、单位随原文落盘**（生成件在该行旁落 `// 单位：<U>`），单位绝不静默吞掉
# —— 否则 `L1I_SIZE = 32`（原文 `32 KB`）会被消费者当 32 字节。只认明确单位 token；
# `64，直接映射`／`1024,无标签,2bit ctr` 之类**首 token 非单位者不产单位行**（不猜测）。
UNIT_RE = re.compile(r'^\s*(\d[\d_]*)\s*([A-Za-z]+)')
UNIT_TOKENS = ('B', 'KB', 'MB', 'GB', 'TB', 'KiB', 'MiB', 'GiB', 'TiB',
               'b', 'bit', 'bits', 'byte', 'bytes', 'Byte', 'Bytes')


def strip_md(s):
    s = s.replace('**', '').replace('`', '')
    return s.strip()


def parse_spec_params():
    """解析 doc/spec/00 §4.1~§4.7 参数表。

    fail-closed：任何一行无法归入 INT / LIT / ARRAY / ENUM(登记) 或列数不是 3，
    一律产出 kind='UNPARSED'，由 `check` 判 FAIL——绝不静默丢弃（旧流程最贵的教训）。
    """
    lines = io.open(SPEC00, 'r', encoding='utf-8').read().splitlines()
    start = end = None
    for i, ln in enumerate(lines):
        if ln.startswith('## 4.') and start is None:
            start = i
        elif start is not None and ln.startswith('### 4.8'):
            end = i
            break
    if start is None or end is None:
        return [], {'error': '找不到 §4 或 §4.8 边界'}
    section = '§4'
    rows = []
    for i in range(start, end):
        ln = lines[i]
        if ln.startswith('### 4.'):
            section = ln.split()[1]
            continue
        if not ln.startswith('|'):
            continue
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        if len(cells) < 3 or set(cells[0]) <= set('- :') or cells[0] == '参数':
            continue
        name_cell, val_cell = cells[0], cells[1]
        names = NAMES_RE.findall(name_cell)
        if not names:
            rows.append(dict(section=section, line=i + 1, names=[], kind='UNPARSED',
                             value=[], value_text=strip_md(val_cell), raw=ln, unit='',
                             why='参数名列无可识别标识符'))
            continue
        val_clean = strip_md(val_cell).replace('，', ',')
        vals = [v.strip() for v in re.split(r'\s*/\s*', val_clean)]
        if len(names) > 1 and len(vals) == len(names):          # 一行两参数：`MUL_NUM` / `MUL_LAT` | 1 / 3
            assign = [(names[k][0], names[k][1], vals[k]) for k in range(len(names))]
        else:
            assign = [(names[0][0], names[0][1], val_clean)]
        for nm, arr, val in assign:
            m_int = INT_RE.match(val)
            m_lit = LIT_RE.match(val.split()[0] if val.split() else '')
            m_pre = PREFIXLIT_RE.match(val)
            why, derived = '', ''
            if ARR_RE.match(val):
                kind = 'ARRAY'
                pv = [int(x) for x in re.findall(r'\d+', val)]
            elif m_lit:
                kind, pv = 'LIT', [m_lit.group(0)]
            elif m_pre or PREFIX_RE.match(val):
                # 洞 1：前缀字面量入口**不许回落 INT**。合法者转成等宽 SV 字面量（数字原文逐字保留，
                # 仅前缀 0x→'h / 0b→'b / 0o→'o；原始文本另以「原文：」行落盘），不合法者 UNPARSED。
                if m_pre and re.fullmatch(BASE_DIGIT[m_pre.group(1)] + r'+',
                                          m_pre.group(2).replace('_', '')):
                    digs = m_pre.group(2)
                    kind = 'LIT'
                    pv = ["%d'%s%s" % (BASE_BIT[m_pre.group(1)] * len(digs.replace('_', '')),
                                       BASE_SV[m_pre.group(1)], digs)]
                else:
                    kind, pv = 'UNPARSED', [val]
                    why = '0x/0b/0o 字面量不合法（进制位不符），拒绝猜测'
            elif val[:1].isdigit() and '+' in val:
                # 洞 2：加式单元格（如 `2R + 2W`）。旧代码经 INT_RE 只取到首个数字（丢 W 侧）。
                # 只在「数字[+单字母单位]项以 '+' 相连」这种明确的计数相加时求和，其余 UNPARSED。
                if COUNTSUM_RE.match(val):
                    terms = re.findall(r'\d+', val)
                    kind = 'INT'
                    pv = [sum(int(x) for x in terms)]
                    derived = '计数项求和 %s = %d' % (' + '.join(terms), pv[0])
                else:
                    kind, pv = 'UNPARSED', [val]
                    why = '加式含非计数项（多字母/标识符），拒绝猜测'
            elif m_int:
                kind, pv = 'INT', [int(m_int.group(1))]
            elif val and not val[0].isdigit():
                kind, pv = 'ENUM', [val]
            else:
                kind, pv = 'UNPARSED', [val]
                why = '值形式无法归类'
            m_unit = UNIT_RE.match(val)                     # 「数字＋单位」：数值照取，单位随原文落盘
            unit = m_unit.group(2) if (m_unit and m_unit.group(2) in UNIT_TOKENS) else ''
            rows.append(dict(section=section, line=i + 1, names=[nm], array=arr, kind=kind,
                             value=pv, value_text=strip_md(val_cell), raw=ln, unit=unit,
                             derived=derived, why=why))
    return rows, {}


def render_params(rows, spec_md5):
    out = []
    w = out.append
    n_param = sum(1 for r in rows if r['kind'] in ('INT', 'LIT', 'ARRAY'))
    n_enum = sum(1 for r in rows if r['kind'] == 'ENUM')
    n_bad = sum(1 for r in rows if r['kind'] == 'UNPARSED')
    w('// ' + '=' * 74)
    w('// vr1_params.svh — 由 doc/spec/00 §4 参数总表生成（全项目数值唯一权威源）')
    w('// DO NOT EDIT BY HAND. 改数值请改 spec/00 §4，再跑：python script/flow.py params')
    w('// 生成时间 %s ／ 源文件 md5 %s' % (datetime.now().strftime('%Y-%m-%d %H:%M'), spec_md5))
    w('// 覆盖对账：表体 %d 行 = parameter %d 条 + 非数值登记 %d 条 + 未解析 %d 条'
      % (len(rows), n_param, n_enum, n_bad))
    w('// 单位口径：spec/00 §4 的「数字＋单位」单元格（如 `32 KB`／`64 B`）**数值照取、不换算**，')
    w('//   单位随行以 `// 单位：<U>` 落盘（绝不静默吞掉；清单见 `flow.py check-one params-units`，只报告不判定）。')
    w('// G1 冻结后本文件由 rtl/vr1/include/vr1_pkg.sv 包裹（spec/00 §4 命名约定）')
    w('// ' + '=' * 74)
    w('`ifndef VR1_PARAMS_SVH')
    w('`define VR1_PARAMS_SVH')
    w('')
    sec = None
    for r in rows:
        if r['section'] != sec:
            sec = r['section']
            w('// ---- %s ----' % sec)
        name = r['names'][0] if r['names'] else '(?)'
        note = ' // spec/00 %s L%d' % (r['section'], r['line'])
        if r['kind'] == 'INT':
            w('parameter int unsigned %s = %d;%s' % (name, r['value'][0], note))
        elif r['kind'] == 'LIT':
            lit = r['value'][0]
            width = int(lit.split("'")[0])
            w('parameter logic [%d:0] %s = %s;%s' % (width - 1, name, lit, note))
        elif r['kind'] == 'ARRAY':
            arr = r['array'] or ('[%d]' % len(r['value']))
            w('parameter int unsigned %s%s = \'{%s};%s'
              % (name, arr, ', '.join(str(x) for x in r['value']), note))
        elif r['kind'] == 'ENUM':
            w('// [非数值·登记] %s = %s%s（编码由归属篇定义，不在此处臆造）'
              % (name, r['value_text'], note))
        else:
            w('// [UNPARSED·必须修] %s = %s%s  <<< %s'
              % (name, r['value_text'], note, r['why']))
        if r['kind'] in ('INT', 'LIT', 'ARRAY') and r['value_text'] not in ('', str(r['value'][0])):
            w('//   原文：%s' % r['value_text'][:160])
        if r.get('unit'):                       # 「数字＋单位」单元格：数值未换算，单位随原文（只报告，见 params-units）
            w('//   单位：%s（数值照取、**未换算**；消费者须按 %s 解释本值）' % (r['unit'], r['unit']))
        if r.get('derived'):                    # 由表内文字推导出的值：把推导式一并落盘（可审计）
            w('//   推导：%s' % r['derived'])
            if r['derived'].startswith('计数项求和'):
                # 多项求和成单一参数的**口径**必须显式落盘：方向/通道项被合并，消费者可能误读（ISS-107 同型）
                w('//   口径：原文 `%s` 为**分方向计数项**，本行只有求和后的单一数值 %s；'
                  % (r['value_text'][:60], r['value'][0]))
                w('//        若下游需按方向/通道分别记账（ADR-P-2 §4），须拆参——本行口径待 ADR-P-2 §4 '
                  '下游义务 O-1/O-2/O-3 落 `spec/00` §4 与 `spec/06`／`spec/09`（本生成件暂不拆）。')
    w('')
    w('`endif // VR1_PARAMS_SVH')
    return '\n'.join(out) + '\n'


def cmd_params(write=True):
    rows, err = parse_spec_params()
    if err:
        print('[flow] params: %s' % err)
        return 1
    text = render_params(rows, md5_of(SPEC00))
    n_bad = sum(1 for r in rows if r['kind'] == 'UNPARSED')
    n_enum = sum(1 for r in rows if r['kind'] == 'ENUM')
    if write:
        os.makedirs(os.path.dirname(PARAMS_SVH), exist_ok=True)
        with open(PARAMS_SVH, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('[flow] params: 生成 %s（%d 行 → %d 条 parameter / %d 条登记 / %d 条未解析）'
              % (os.path.relpath(PARAMS_SVH, ROOT).replace('\\', '/'), len(rows),
                 len(rows) - n_enum - n_bad, n_enum, n_bad))
    for r in rows:
        if r['kind'] == 'UNPARSED':
            print('  [UNPARSED] spec/00 L%d  %s' % (r['line'], r['value_text'][:80]))
    ok, msg = chk_params_units()                 # 只报告：单位随原文的参数清单（不作判据）
    print('[flow] params-units: %s' % msg)
    return 1 if n_bad else 0


# --------------------------------------------------------------------------- #
# 判据（check 的每一项都必须是「可执行证据」，不判文档措辞）
# --------------------------------------------------------------------------- #
def chk_params_drift():
    rows, err = parse_spec_params()
    if err:
        return False, err
    want = render_params(rows, md5_of(SPEC00))
    if not os.path.exists(PARAMS_SVH):
        return False, 'missing %s（先跑 flow.py params）' % os.path.relpath(PARAMS_SVH, ROOT)
    got = io.open(PARAMS_SVH, 'r', encoding='utf-8').read()
    # 时间戳行不参与漂移比对
    norm = lambda t: '\n'.join(x for x in t.splitlines() if '生成时间' not in x)
    if norm(want) != norm(got):
        return False, 'spec/00 §4 与磁盘 svh 不一致（参数漂移）→ 跑 flow.py params'
    return True, 'spec/00 §4 重算 == 磁盘 svh（md5 %s）' % md5_of(PARAMS_SVH)[:8]


def chk_params_coverage():
    rows, err = parse_spec_params()
    if err:
        return False, err
    bad = [r for r in rows if r['kind'] == 'UNPARSED' or not r['names']]
    if bad:
        return False, '%d 行未解析/无参数名：L%s' % (
            len(bad), ','.join(str(r['line']) for r in bad[:5]))
    n_enum = sum(1 for r in rows if r['kind'] == 'ENUM')
    return True, '表体 %d 行全覆盖（%d parameter + %d 非数值登记）' % (
        len(rows), len(rows) - n_enum, n_enum)


def chk_params_units():
    """params-units（**只报告，不判定**：恒 PASS，不作门禁、不放宽任何既有判据）。

    spec/00 §4 里「数字＋单位」的单元格（`32 KB`／`64 B`／`4 B（G=0）`／`256 KB / 16 / 64 B` 的逐项）
    一律**数值照取、单位随原文**（生成件每行旁有 `// 单位：<U>` 标记）。本项把这类参数逐个列出，
    供人核「数值单位是否与消费者一致」（例：`L1I_SIZE = 32` 的消费者若按字节读即错，应为 32 KB）。
    **红线 R6**：本项不改阈值、不判红；若人裁某处应拆成「数值＋单位」两参数，按 `doc/项目开发流程.md`
    §12.3 上报后由人/ADR 落文，**不由本项自决**。
    """
    rows, err = parse_spec_params()
    if err:
        return True, '仅报告（不作判据）：%s' % err
    hits = [(r['names'][0], r['unit'], r['value'][0], r['section'], r['line'])
            for r in rows if r.get('unit') and r['names']]
    if not hits:
        return True, '仅报告（不作判据）：spec/00 §4 未见「数字＋单位」单元格'
    return True, '仅报告（不作判据）：%d 个带单位参数 → %s' % (
        len(hits), '；'.join('%s=%s%s（%s L%d）' % (n, v, u, s, l) for n, u, v, s, l in hits))


def msim_env():
    """ModelSim 子进程专用环境：两份 license 都列上（`;` 分隔），**保留继承的 os.environ**。

    只覆盖 `LM_LICENSE_FILE` / `MGLS_LICENSE_FILE` 两个键——无论哪块网卡在机上都能命中
    （ISS-104；机理与实测见 `MSIM_LICENSE_PATHS`）。不存在的路径不列入（少一条无效告警）；
    两份都不存在则原样继承，不做猜测。
    """
    env = dict(os.environ)
    paths = [p for p in MSIM_LICENSE_PATHS if os.path.exists(p)]
    if paths:
        val = ';'.join(paths)
        env['LM_LICENSE_FILE'] = val
        env['MGLS_LICENSE_FILE'] = val
    return env


def _msim(d, steps, tag):
    """跑一串 ModelSim 命令；**无论成败都落日志**（失败证据不能丢）。"""
    acc, rc = [], 0
    env = msim_env()
    try:
        for argv in steps:
            acc.append('$ ' + ' '.join(argv))
            try:
                rc, o = run(argv, cwd=d, timeout=300, env=env)
            except subprocess.TimeoutExpired:
                acc.append('!! TIMEOUT 300s')
                rc = 99
                break
            acc.append(o)
            if rc != 0:
                break
    finally:
        with open(os.path.join(d, 'run.log'), 'a', encoding='utf-8', newline='\n') as f:
            f.write('\n[%s]\n' % tag + '\n'.join(acc))
    return '\n'.join(acc), rc


def chk_params_compile():
    """编译在环（vlog）：证据 = `-- Compiling` 计数 + `Errors: 0`。**不涉仿真 license**（vsim 另判）。"""
    if not os.path.exists(VLOG):
        return False, 'vlog 不存在：%s' % VLOG
    d = os.path.join(ROOT, 'sim', 'run_params')
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'run.log'), 'w', encoding='utf-8').close()
    inc = os.path.join(ROOT, 'rtl', 'vr1', 'include').replace('\\', '/')
    text, rc = _msim(d, [
        [VLIB, 'work'],
        [VLOG, '-64', '-sv', '-work', 'work', '+incdir+%s' % inc, PARAMS_PKG.replace('\\', '/')],
    ], 'vlog')
    n_err = re.findall(r'Errors:\s*(\d+)', text)
    n_comp = len(re.findall(r'^-- Compiling', text, re.M))
    if not n_err:
        return False, '编译日志无 `Errors: N` 证据行（fail-closed）→ %s' % rel(os.path.join(d, 'run.log'))
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(os.path.join(d, 'run.log')))
    if n_comp < 2:
        return False, '`-- Compiling` 计数 %d < 2（package+module 未全部编过）' % n_comp
    if rc != 0:
        return False, 'vlog 退出码 %d → %s' % (rc, rel(os.path.join(d, 'run.log')))
    return True, 'vlog 编译 %d 个单元 ｜ Errors: 0 ｜ %s' % (n_comp, rel(os.path.join(d, 'run.log')))


def chk_params_elab():
    """elaboration/仿真（vsim）：license 由 `_msim()` 在子进程会话内注入（两份并列，R-224 已解决
    ISS-104 的 HOSTID 漂移）；本判据不进 M0.5 出口，只作环境可观测项——注入失败才自报 ENV-BLOCKED。
    """
    if not os.path.exists(VSIM):
        return False, 'vsim 不存在：%s' % VSIM
    d = os.path.join(ROOT, 'sim', 'run_params')
    os.makedirs(d, exist_ok=True)
    text, rc = _msim(d, [
        [VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'work.vr1_params_smoke'],
    ], 'vsim')
    if 'License' in text and ('Failure to obtain' in text or 'Invalid host' in text):
        host = re.search(r'Failed to obtain a license|Cannot find license file.*', text)
        return False, 'ENV-BLOCKED(ISS-104) ModelSim license：%s' % (host.group(0)[:70] if host else 'license 失败')
    n_err = re.findall(r'Errors:\s*(\d+)', text)
    if int(n_err[-1] if n_err else 1) != 0:
        return False, 'vsim 报错（Errors: %s）→ %s' % (n_err[-1] if n_err else '?', rel(os.path.join(d, 'run.log')))
    smoke = [ln for ln in text.splitlines() if '[params_smoke]' in ln]
    if not smoke:
        return False, '未见 [params_smoke] 证据行 → %s' % rel(os.path.join(d, 'run.log'))
    return True, '%s ｜ %s' % (rel(os.path.join(d, 'run.log')), smoke[-1].strip()[:90])


def param_values():
    rows, err = parse_spec_params()
    vals = {}
    for r in rows:
        if r['kind'] == 'INT' and r['names']:
            vals[r['names'][0]] = r['value'][0]
        elif r['kind'] == 'ARRAY' and r['names']:
            vals[r['names'][0]] = list(r['value'])
    return vals


# 表内自洽断言：全部来自 doc/spec/00 §4 表内文字，机器可判（旧流程靠"读 50 个评审附录"找这类缺陷）
INVARIANTS = [
    ('XLEN == 64', lambda v: v['XLEN'] == 64),
    ('VA_STORE_W > VA_BITS（含 bit39 规范检测位）', lambda v: v['VA_STORE_W'] > v['VA_BITS']),
    ('ALEN == PA_BITS', lambda v: v['ALEN'] == v['PA_BITS']),
    ('FTQ_ENTRIES >= BP_STAGES + IF_STAGES（在途重定向窗口）',
     lambda v: v['FTQ_ENTRIES'] >= v['BP_STAGES'] + v['IF_STAGES']),
    ('IBUF_ENTRIES > IF_STAGES × DECODE_WIDTH', lambda v: v['IBUF_ENTRIES'] > v['IF_STAGES'] * v['DECODE_WIDTH']),
    ('N_EU_TOTAL == ALU+BRU+SHIFT+MUL+DIV+AGU',
     lambda v: v['N_EU_TOTAL'] == v['ALU_NUM'] + v['BRU_NUM'] + v['SHIFT_NUM'] + v['MUL_NUM'] + v['DIV_NUM'] + v['AGU_NUM']),
    ('ROB_NEAR_FULL < ROB_ENTRIES', lambda v: v['ROB_NEAR_FULL'] < v['ROB_ENTRIES']),
    ('COMMIT_WIDTH == DECODE_WIDTH', lambda v: v['COMMIT_WIDTH'] == v['DECODE_WIDTH']),
    ('2**RAT_IDX_W == RAT_ENTRIES', lambda v: 2 ** v['RAT_IDX_W'] == v['RAT_ENTRIES']),
    ('2**PADDR_W == PRF_INT_ENTRIES', lambda v: 2 ** v['PADDR_W'] == v['PRF_INT_ENTRIES']),
    ('2**(ROB_PTR_W-1) == ROB_ENTRIES（7bit index + 1bit wrap）',
     lambda v: 2 ** (v['ROB_PTR_W'] - 1) == v['ROB_ENTRIES']),
    ('PRF_WR_PORTS == ISSUE_WIDTH', lambda v: v['PRF_WR_PORTS'] == v['ISSUE_WIDTH']),
    ('WAKE_BCAST_PORTS == ISSUE_WIDTH', lambda v: v['WAKE_BCAST_PORTS'] == v['ISSUE_WIDTH']),
    ('PRF_RD_PORTS == ISSUE_WIDTH×2 + 4（发射读 12 + 提交读 4；ADR-S08 已删"+2 恢复读"）',
     lambda v: v['PRF_RD_PORTS'] == v['ISSUE_WIDTH'] * 2 + 4),
    ('GHR_BITS > max(TAGE_HIST_LEN)', lambda v: v['GHR_BITS'] > max(v['TAGE_HIST_LEN'])),
    ('ITTAGE_TARGET_W == VA_STORE_W（存 VA[39:0]）', lambda v: v['ITTAGE_TARGET_W'] == v['VA_STORE_W']),
    ('SAME_GROUP_BYPASS_DEPTH <= DECODE_WIDTH', lambda v: v['SAME_GROUP_BYPASS_DEPTH'] <= v['DECODE_WIDTH']),
]


def chk_params_invariants():
    v = param_values()
    bad, missing = [], []
    for desc, fn in INVARIANTS:
        try:
            ok = bool(fn(v))
        except KeyError as e:
            missing.append('%s(缺 %s)' % (desc.split('（')[0], e.args[0]))
            continue
        if not ok:
            bad.append(desc)
    if missing:
        return False, '%d 条断言引用了表中不存在的参数：%s' % (len(missing), '；'.join(missing[:3]))
    if bad:
        return False, '%d/%d 条表内自洽断言不成立：%s' % (len(bad), len(INVARIANTS), '；'.join(bad[:3]))
    return True, '%d 条表内自洽断言全过（源自 spec/00 §4 表内文字）' % len(INVARIANTS)


def chk_image_hex():
    """一份镜像喂两边：.hex + .bin + MANIFEST(md5)。"""
    man = load_json(IMAGE_MANIFEST.replace('.txt', '.json')) or {}
    hexf = man.get('hex')
    if not hexf or not os.path.exists(os.path.join(ROOT, hexf)):
        return False, '缺 sim/image/*.hex（先跑 run，见 sw/tests/gen_smoke_image.py）'
    if not man.get('md5'):
        return False, 'MANIFEST 缺 md5'
    live = md5_of(os.path.join(ROOT, hexf))
    if live != man['md5']:
        return False, '镜像 md5 漂移：磁盘 %s != MANIFEST %s' % (live[:8], man['md5'][:8])
    return True, '%s md5=%s base=0x%x words=%s' % (
        hexf, live[:8], man.get('base_byte', 0), man.get('words'))


def chk_trace_self():
    """ISS 读 .hex 跑出的 trace 与 golden 逐条比对（cross-check「一份镜像喂两边」的往返等价）。"""
    csv = os.path.join(ROOT, ISS_HEX_CSV)
    if not os.path.exists(csv):
        return False, '缺 %s（先跑 run）' % rel(csv)
    if not os.path.exists(GOLDEN):
        return False, '缺 golden %s' % rel(GOLDEN)
    rc, o = run([sys.executable, 'iss/tools/trace_compare.py', rel(GOLDEN), rel(csv)])
    line = last_line(o)
    if rc != 0 or 'mismatch=0' not in line:
        return False, line
    return True, line


def chk_ledger():
    led = load_json(LEDGER)
    if not led or 'entries' not in led or 'next' not in led:
        return False, 'ledger.json 缺失或结构不符'
    ids = [e['id'] for e in led['entries']]
    if len(ids) != len(set(ids)):
        return False, '编号重复'
    return True, '%d 条；next=%s' % (len(ids), led['next'])


def chk_state():
    st = load_json(STATE)
    if not st:
        return False, 'state/flow.json 缺失或不可解析'
    ids = [s['id'] for s in st.get('steps', [])]
    if len(ids) != len(set(ids)):
        return False, '步骤 ID 重复'
    for s in st.get('steps', []):
        if s.get('status') == 'done' and not s.get('evidence'):
            return False, '步骤 %s 置 done 但无 evidence（R8：判定必须有显式证据）' % s['id']
        for ev in [s.get('evidence', '')]:
            for m in re.findall(r'(sim/run_[A-Za-z0-9_]+/run\.log)', ev or ''):
                if not os.path.exists(os.path.join(ROOT, m)):
                    return False, '步骤 %s 的证据文件不存在：%s' % (s['id'], m)
    return True, '%d 步；active 里程碑 %s' % (len(ids), active_milestone(st).get('id', '无'))


def rel(p):
    return os.path.relpath(p, ROOT).replace('\\', '/')


def chk_ra_tokens():
    """规则承载件不得引用未定义的 RA 红线号（继承退役 gate.py 的 ra-token-defined，判据名保持不变）。

    定义面 = AGENTS.md 的「红线记号（RA 系列）说明」；本项目只承认 RA1~RA4（知识库 §8）。
    """
    live = ['AGENTS.md', 'doc/项目开发流程.md', 'doc/AI角色与职责.md', 'doc/当前目标卡.md',
            'doc/process/03-自动化流程重构-三方案.md']
    defined = set(re.findall(r'RA([1-9])', io.open(os.path.join(ROOT, 'AGENTS.md'),
                                                  'r', encoding='utf-8').read()))
    if not defined:
        return False, 'AGENTS.md 里找不到 RA 定义（fail-closed）'
    bad = []
    for f in live:
        p = os.path.join(ROOT, f)
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(io.open(p, 'r', encoding='utf-8').read().splitlines(), 1):
            for n in re.findall(r'\bRA([0-9]+)\b', ln):
                if n not in defined:
                    bad.append('%s:%d RA%s' % (f, i, n))
    if bad:
        return False, '引用了未定义的 RA 号：%s' % '；'.join(bad[:4])
    return True, '已定义 RA%s；%d 个承载件无越界引用' % ('/RA'.join(sorted(defined)), len(live))


def chk_width():
    """struct 成员位宽实算 vs 文档声明（复用 script/width_check.py；ISS-018 的教训）。

    UNRESOLVED/NO-TABLE 等"算不出"按该工具自身口径**不计入合计**，也不判 FAIL——
    宁可报"算不出"，也不许猜一个数凑平。
    """
    p = os.path.join(ROOT, 'script', 'width_check.py')
    if not os.path.exists(p):
        return False, 'width_check.py 缺失'
    rc, out = run([sys.executable, 'script/width_check.py', '--json'])
    i, j = out.find('['), out.rfind(']')
    if i < 0 or j < i:
        return False, 'width_check --json 输出无法解析（fail-closed）'
    try:
        rows = json.loads(out[i:j + 1])
    except Exception as e:                                          # noqa: BLE001
        return False, 'width_check JSON 解析失败：%s' % e
    mis = [r['struct'] for r in rows if r.get('verdict') in ('MISMATCH', 'TITLE-MISMATCH')]
    unver = [r['struct'] for r in rows if r.get('verdict') in ('UNVERIFIED', 'NO-TABLE', 'NO-CLAIM')]
    if mis:
        return False, '位宽不符 %d 个 struct：%s' % (len(mis), '、'.join(mis[:5]))
    return True, '%d 个 struct 位宽自洽（另有 %d 个算不出，按工具口径不计）' % (
        len(rows) - len(unver), len(unver))


def _doc_files():
    """现行文档面（门禁只判现行件；`doc/_legacy/` 是归档历史记录，不进判据）。"""
    out = []
    d = os.path.join(ROOT, 'doc')
    for base, dirs, names in os.walk(d):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and x != '_legacy']
        out += [os.path.join(base, n) for n in names if n.endswith('.md')]
    ag = os.path.join(ROOT, 'tools', 'vr1-plugin', 'agents')
    if os.path.isdir(ag):
        out += [os.path.join(ag, n) for n in os.listdir(ag) if n.endswith('.md')]
    for extra in ('AGENTS.md', 'README.md'):
        q = os.path.join(ROOT, extra)
        if os.path.exists(q):
            out.append(q)
    return out


def chk_md_integrity():
    """文档结构完整性（端口自退役 gate.py 的同名判据）：粗体标记重叠 + 同表列数一致。

    转义竖线 `\\|` 不算列分隔符（这条正是新方案落地当天抓到自己一个表格缺陷的原因）。
    """
    problems = []
    files = _doc_files()
    for p in files:
        header_cols = None
        for ln, line in enumerate(io.open(p, 'r', encoding='utf-8').read().splitlines(), 1):
            if re.search(r'\*{4,}', line.replace('---', '')):
                problems.append('%s:%d 粗体标记重叠' % (rel(p), ln))
            if line.startswith('|'):
                n = line.replace('\\|', '').count('|')
                if set(line.replace('|', '').strip()) <= set('-: '):
                    header_cols = n
                    continue
                if header_cols and n != header_cols and not line.startswith('|---'):
                    problems.append('%s:%d 表格列数 %d≠%d' % (rel(p), ln, n, header_cols))
            else:
                header_cols = None
    if problems:
        return False, '%d 处：%s' % (len(problems), '；'.join(problems[:4]))
    return True, '%d 个文档表格/粗体结构一致' % len(files)


ZW_CHARS = {'\u200b': 'ZWSP', '\u200c': 'ZWNJ', '\u200d': 'ZWJ', '\u200e': 'LRM', '\u200f': 'RLM',
            '\u202a': 'LRE', '\u202b': 'RLE', '\u202c': 'PDF', '\u202d': 'LRO', '\u202e': 'RLO',
            '\ufeff': 'BOM/ZWNBSP'}


def chk_codepoints():
    """零宽/双向控制码点扫描（端口自退役 gate.py 的 codepoints 判据）。"""
    bad = []
    files = _doc_files()
    for p in files:
        for ln, line in enumerate(io.open(p, 'r', encoding='utf-8').read().splitlines(), 1):
            for ch, name in ZW_CHARS.items():
                if ch in line:
                    bad.append('%s:%d %s' % (rel(p), ln, name))
                    break
    if bad:
        return False, '零宽/双向控制码点 %d 处：%s' % (len(bad), '；'.join(bad[:4]))
    return True, '%d 个文档无零宽/双向控制码点' % len(files)


# --------------------------------------------------------------------------- #
# 文档面守卫（每轮常跑三条）：断链 / 编号撞车 / 退役件活引用
#   病灶同源：编号与引用只写在正文里、没有机械对账 ⇒ 靠人对账必漏（三轮复核抓到的三类
#   成规模问题）。三条一律 **fail-closed**：解析不出目标即报出；同类过多时给「计数 + 前 15 条」。
#   （红线 R6/R7 口径：这三条只报问题，不改阈值、不豁免任何既有判据。）
# --------------------------------------------------------------------------- #
CIRCLED = '①②③④⑤⑥⑦⑧⑨⑩'
# 退役件清单（与 `AGENTS.md` §0「退役件」同源）：现行件不得把它们当**现行权威**引用
RETIRED = [
    (r'doc[/\\]verify[/\\]03-验证计划\.md|`doc/verify/03`|doc[/\\]verify[/\\]03(?![-\d])|verify/03-验证计划',
     'doc/verify/03-验证计划.md'),
    (r'run_cmd[/\\]AutoQueue\.ya?ml|AutoQueue\.ya?ml', 'run_cmd/AutoQueue.yaml'),
    (r'script[/\\]gate\.py|`?gate\.py`?', 'script/gate.py'),
    (r'doc[/\\]自动推进说明\.md|自动推进说明', 'doc/自动推进说明.md'),
    (r'doc[/\\]_legacy|_legacy[/\\]', 'doc/_legacy/**'),
]
# 「退役语境」关键词白名单：同句/同行出现即放行（历史记录不是活引用）
RETIRED_CTX = ('已退役', '退役', '留档', '历史', '快照', '作废', '原位保留')
# 「现行性措辞」：与退役件名**同句/同列表项**出现才判红（否则是历史叙述）
LIVE_WORDS = re.compile(r'现行|唯一权威|唯一真值|唯一入口|权威源|为准|入口|遵照|依照|遵循|依据|据此'
                        r'|判据|机判|实跑|执行|命令|记入|见')
# 引用目标识别：`ref` §X（含 §①），或裸路径 ref §X
REF_TOK_RE = re.compile(r'`([^`\n]{2,120}?)`\s*(?:的\s*)?§\s*([0-9][0-9A-Za-z.\-]*|[%s])' % CIRCLED)
REF_BARE_RE = re.compile(
    r'(?<![`\w/])((?:doc[/\\])?(?:spec|verify|process|decisions|review|design)[/\\]'
    r'[^\s，。；）（()`]{0,80}?\.md)\s*§\s*([0-9][0-9A-Za-z.\-]*|[%s])' % CIRCLED)
# 外部引用（知识库/绝对路径）不判：它们不在仓库引用面内
REF_EXT_RE = re.compile(r'^[A-Za-z]:|^_tools[/\\]|IC验证知识库')
REF_TOPDIR = ('iss/', 'run_cmd/', 'sw/', 'tb/', 'rtl/', 'sim/', 'script/', 'filelist/',
              'debug/', 'tools/', 'state/', 'doc/')
REF_HEAD_RE = re.compile(r'^\s{0,3}#{1,6}\s+(.*)$')


def _ref_scan_files():
    """判据面文件集：`doc/spec/**/*.md`（不含 `_legacy`）、`AGENTS.md`、`doc/当前目标卡.md`、
    `doc/process/03`、`doc/verify/*.md`、`doc/decisions/*.md`。"""
    out = []
    for base, dirs, names in os.walk(os.path.join(ROOT, 'doc', 'spec')):
        dirs[:] = [d for d in dirs if d != '_legacy']
        out += [os.path.join(base, n) for n in names if n.endswith('.md')]
    for d in ('verify', 'decisions'):
        q = os.path.join(ROOT, 'doc', d)
        if os.path.isdir(q):
            out += [os.path.join(q, n) for n in sorted(os.listdir(q)) if n.endswith('.md')]
    for r in ('AGENTS.md', 'doc/当前目标卡.md'):
        out.append(os.path.join(ROOT, r))
    pd = os.path.join(ROOT, 'doc', 'process')
    if os.path.isdir(pd):
        out += [os.path.join(pd, n) for n in sorted(os.listdir(pd)) if n.startswith('03')]
    return [p for p in sorted(set(out)) if os.path.exists(p)]


def _basename_index():
    """裸文件名 → 仓库内路径（唯一命中才可判；多命中/零命中都按「不可解析」报出）。"""
    idx = {}
    for base, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d != 'sim']
        for n in names:
            idx.setdefault(n, []).append(rel(os.path.join(base, n)))
    return {k: sorted(v) for k, v in idx.items()}


def _ref_target(tok, base_index):
    """解析引用目标 → (kind, paths, why)；kind ∈ ok|missing|unparsed|skip。"""
    t = tok.replace('\\', '/').strip().rstrip('/')
    if not t or ' ' in t or REF_EXT_RE.search(t):
        return 'skip', [], ''
    if t.startswith('doc/'):
        p = t
    elif re.match(r'^(spec|verify|review|process|decisions|design)/', t):
        p = 'doc/' + t
    elif t.startswith(REF_TOPDIR) or t in ('AGENTS.md', 'README.md'):
        p = t
    elif t.endswith('.md'):
        hits = base_index.get(os.path.basename(t), [])
        if len(hits) == 1:
            return 'ok', hits, ''
        return 'unparsed', [], '裸文件名 %s（%s）' % (
            t, '全库无此文件' if not hits else '全库命中 %d 处' % len(hits))
    else:
        return 'unparsed', [], '非仓库路径 %s' % t[:40]
    if '*' in p or re.match(r'^doc/(?:spec|verify|review|process|decisions)/\d+$', p):
        pat = p if '*' in p else p + '-*.md'
        hits = sorted(rel(x) for x in glob.glob(os.path.join(ROOT, pat)))
        if not hits:
            return 'missing', [], '编号 glob 无匹配 %s' % pat
        return 'ok', hits, ''
    if p.endswith('.md'):
        if os.path.exists(os.path.join(ROOT, p)):
            return 'ok', [p], ''
        return 'missing', [], '文件不存在 %s' % p
    if os.path.isdir(os.path.join(ROOT, p)):
        return 'unparsed', [], '目标为目录（非文件）%s' % p
    return 'missing', [], '文件不存在 %s' % p


def _headings(paths):
    hs = []
    for p in paths:
        full = os.path.join(ROOT, p)
        if not os.path.exists(full):
            continue
        for ln in io.open(full, 'r', encoding='utf-8').read().splitlines():
            m = REF_HEAD_RE.match(ln)
            if m:
                hs.append(m.group(1).strip())
    return hs


def _sec_found(paths, sec):
    """节号存在性：`§4` 命中 `## 4. …`／`## §4 …`；`§9.5` 命中 `### 9.5` 与 `### 9.5.x`；
    `§①` 命中含圈号的标题。`§3.x` 这类通配按前缀判（宽松侧不作为判定：命中即过）。"""
    hs = _headings(paths)
    if sec and all(c in CIRCLED for c in sec):
        return any(sec in h for h in hs)
    m = re.match(r'^(\d+(?:\.\d+)*)', sec or '')
    if not m:
        return None                      # 非数值/非圈号：解析不出 → fail-closed 报出
    pat = re.compile(r'^(?:§\s*)?%s(?![0-9])' % re.escape(m.group(1)))
    return any(pat.match(h) for h in hs)


def chk_ref_target_exists():
    """ref-target-exists：现行规则与规格文档的交叉引用必须「目标文件在 + 节号在」（fail-closed）。

    识别形如「见 `spec/NN` §X」「见 `doc/xxx.md` §Y」「`spec/NN` §X」的引用；`doc/spec/NN`／
    `doc/verify/NN` 走编号 glob（`NN-*.md`）。解析不出目标（裸文件名全库零/多命中、非仓库路径、
    目标为目录）与节号不存在一律记一条；外部知识库路径（`D:\\IC验证知识库\\…`、`_tools/…`）不判。
    """
    base = _basename_index()
    bad = []
    for p in _ref_scan_files():
        for i, ln in enumerate(io.open(p, 'r', encoding='utf-8').read().splitlines(), 1):
            refs = []
            for m in REF_TOK_RE.finditer(ln):
                if (re.search(r'[/\\]', m.group(1)) or m.group(1).endswith('.md')
                        or m.group(1) in ('AGENTS.md', 'README.md')):
                    refs.append((m.group(1), m.group(2)))
            refs += [(m.group(1), m.group(2)) for m in REF_BARE_RE.finditer(ln)]
            seen = set()
            for tok, sec in refs:
                if (tok, sec) in seen:
                    continue
                seen.add((tok, sec))
                kind, paths, why = _ref_target(tok, base)
                if kind == 'skip':
                    continue
                if kind != 'ok':
                    bad.append('%s:%d `%s` §%s %s｜原文:%s'
                               % (rel(p), i, tok[:40], sec, why, ln.strip()[:60]))
                    continue
                ok = _sec_found(paths, sec)
                if ok is False:
                    bad.append('%s:%d `%s` §%s 节号不存在（%s）｜原文:%s'
                               % (rel(p), i, tok[:40], sec, ','.join(paths[:2]), ln.strip()[:60]))
                elif ok is None:
                    bad.append('%s:%d `%s` §%s 节号不可解析（fail-closed）｜原文:%s'
                               % (rel(p), i, tok[:40], sec, ln.strip()[:60]))
    if bad:
        return False, '共 %d 条交叉引用断链：%s%s' % (
            len(bad), '；'.join(bad[:15]), '…（只列前 15 条）' if len(bad) > 15 else '')
    return True, '%d 个现行文档的交叉引用全解析（目标文件 + 节号）' % len(_ref_scan_files())


def _carrier_texts():
    """现行承载件（id-unique 判据面）：AGENTS.md／`doc/process/03`／state/flow.json／
    `doc/decisions/ADR-P-*.md`／`script/flow.py`。"""
    out = []
    for r in ('AGENTS.md', 'doc/process/03-自动化流程重构-三方案.md', 'state/flow.json',
              'script/flow.py'):
        if os.path.exists(os.path.join(ROOT, r)):
            out.append(r)
    if os.path.isdir(ADR_DIR):
        out += ['doc/decisions/' + n for n in sorted(os.listdir(ADR_DIR))
                if re.match(r'^ADR-P-\d+-.*\.md$', n)]
    return out


def chk_id_unique():
    """id-unique：全库编号唯一性与命名空间（ADR 分区 + 需求号同篇唯一）。

    ①`doc/decisions/` 不得存在裸号文件 `ADR-<数字>-*.md`（只许 `ADR-P-<数字>-*.md`）；
    ②`ADR-P-*` 编号唯一、无缺号；③现行承载件里的 `ADR-P-<n>` 必须都能找到对应文件；
    ④`doc/spec/**` 的 `T-\\d+-\\d+` 需求号**同篇内唯一**（跨篇允许重复：按篇编号）——
       判定面＝**定义位**（表格行首格／行首 `**T-xx-y**：`），且定义篇号须与该文件篇号一致。
    """
    bad = []
    dec = os.path.join(ROOT, 'doc', 'decisions')
    files = sorted(os.listdir(dec)) if os.path.isdir(dec) else []
    for n in files:
        if re.match(r'^ADR-\d+-.*\.md$', n):
            bad.append('裸号 ADR 文件（只许 ADR-P-<n>-*.md）：doc/decisions/%s' % n)
    nums = sorted(int(re.match(r'^ADR-P-(\d+)-', n).group(1)) for n in files
                  if re.match(r'^ADR-P-\d+-.*\.md$', n))
    dup = sorted({n for n in nums if nums.count(n) > 1})
    if dup:
        bad.append('ADR-P 编号重复：%s' % dup)
    if nums and nums != list(range(1, max(nums) + 1)):
        bad.append('ADR-P 缺号：现有 %s（应为 1..%d 连续）' % (nums, max(nums)))
    for r in _carrier_texts():
        for i, ln in enumerate(io.open(os.path.join(ROOT, r), 'r', encoding='utf-8')
                              .read().splitlines(), 1):
            for m in re.finditer(r'ADR-P-(\d+)', ln):
                if int(m.group(1)) not in nums:
                    bad.append('%s:%d 引用 ADR-P-%s 但 doc/decisions/ 无对应文件'
                               % (r, i, m.group(1)))
    for base_d, dirs, names in os.walk(os.path.join(ROOT, 'doc', 'spec')):
        for n in sorted(names):
            if not n.endswith('.md'):
                continue
            fnum = re.match(r'^(\d+)', n)
            fnum = fnum.group(1) if fnum else ''
            defs = {}
            for i, ln in enumerate(io.open(os.path.join(base_d, n), 'r', encoding='utf-8')
                                  .read().splitlines(), 1):
                for m in re.finditer(
                        r'^\|\s*~{0,2}\s*`?(T-\d+-\d+[a-z]?)`?\s*~{0,2}\s*\|'
                        r'|^\s*(?:[-*]\s*)?\**`?(T-\d+-\d+[a-z]?)`?\**\s*[:：|]', ln):
                    tid = m.group(1) or m.group(2)
                    if tid:
                        defs.setdefault(tid, []).append(i)
            for tid, lns in sorted(defs.items()):
                if len(lns) > 1:
                    bad.append('doc/spec/%s 需求号 %s 同篇定义 %d 次（行 %s）'
                               % (n, tid, len(lns), ','.join(map(str, lns))))
                if fnum and tid.split('-')[1] != fnum:
                    bad.append('doc/spec/%s 定义 %s（篇号应为 %s）' % (n, tid, fnum))
    if bad:
        return False, '共 %d 条编号问题：%s%s' % (
            len(bad), '；'.join(bad[:15]), '…（只列前 15 条）' if len(bad) > 15 else '')
    return True, ('ADR-P %s 唯一无缺号（%d 件）；承载件 ADR-P 引用全解析；'
                  'doc/spec 需求号同篇唯一' % (nums if nums else '（无）', len(nums)))


def chk_no_live_legacy_ref():
    """no-live-legacy-ref：现行件不得把已退役件当现行权威引用。

    现行件＝`doc/spec/**/*.md`、`AGENTS.md`、`doc/当前目标卡.md`、`doc/process/03`；
    退役件清单＝`doc/verify/03-验证计划.md`／`run_cmd/AutoQueue.yaml`／`script/gate.py`／
    `doc/自动推进说明.md`／`doc/_legacy/**`。判定：命中退役件名 **且** 同句（表格行按整行＝一个
    列表项）出现现行性措辞 ⇒ 报出；句内命中「已退役/退役/留档/历史/快照/作废」之一 ⇒ 放行。
    """
    live = []
    for base, dirs, names in os.walk(os.path.join(ROOT, 'doc', 'spec')):
        live += [os.path.join(base, n) for n in names if n.endswith('.md')]
    for r in ('AGENTS.md', 'doc/当前目标卡.md', 'doc/process/03-自动化流程重构-三方案.md'):
        live.append(os.path.join(ROOT, r))
    bad = []
    for p in sorted(set(live)):
        if not os.path.exists(p):
            continue
        for i, ln in enumerate(io.open(p, 'r', encoding='utf-8').read().splitlines(), 1):
            for pat, name in RETIRED:
                if not re.search(pat, ln):
                    continue
                units = [ln] if ln.lstrip().startswith('|') else re.split(r'[；;。]', ln)
                for u in units:
                    if re.search(pat, u) and LIVE_WORDS.search(u) \
                            and not any(w in u for w in RETIRED_CTX):
                        bad.append('%s:%d 退役件 `%s` 被当现行引用｜原文:%s'
                                   % (rel(p), i, name, u.strip()[:60]))
                        break
                break
    if bad:
        return False, '共 %d 条退役件活引用：%s%s' % (
            len(bad), '；'.join(bad[:15]), '…（只列前 15 条）' if len(bad) > 15 else '')
    return True, '%d 个现行件无「退役件当现行权威」引用' % len(set(live))


# --------------------------------------------------------------------------- #
# 接口类型单源（B 的判据内核，第二块：spec/01 §3 struct → vr1_types.svh）
# --------------------------------------------------------------------------- #
def load_width_check():
    """复用 script/width_check.py 的解析函数——**不写第二个解析器**（单一解析源）。"""
    sys.path.insert(0, os.path.join(ROOT, 'script'))
    import width_check
    return width_check


def structs():
    """返回 [{name, members, total, unresolved, baseline, claims, head}]，来自 width_check.parse()。"""
    wc = load_width_check()
    out = []
    for s in wc.parse():
        mem = s['members']
        bad = [m for m in mem if m['width'] is None]
        out.append({'name': s['name'], 'members': mem, 'head': s['head'],
                    'total': sum(m['width'] for m in mem if m['width'] is not None),
                    'unresolved': bad, 'baseline': s.get('baseline', 0),
                    'claims': [c['value'] for c in s.get('claims', [])],
                    'claims_raw': s.get('claims', [])})
    return out


# 打包顺序约定（ADR-P-1，RD 自决 2026-09-25）：
#   spec/01 §3 的 struct 表**未规定字段打包顺序**（全篇无 MSB/LSB/位序 表述，实测 grep 为空）。
#   取"表中自上而下 = MSB→LSB"（`typedef struct packed` 的声明序即 [MSB:LSB]），
#   锚＝SystemVerilog LRM 1800-2012 §7.2.1 packed struct 声明序语义 ＋ 本项目表格惯例（高位在前）。
#   回退点：若 G1 评审改判为 LSB-first，改 `render_types()` 里一处 `reversed()` 即可，生成件与判据同批刷新。
PACK_ORDER_MSB_FIRST = True


IDENT_OK = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
# SystemVerilog 保留字（字段名撞上时必须机械化处理，不能生成非法声明；只列可能出现在本表中的）
SV_KEYWORDS = {'super', 'this', 'type', 'bit', 'byte', 'int', 'integer', 'logic', 'reg', 'wire',
               'time', 'event', 'real', 'shortint', 'longint', 'void', 'class', 'end', 'local',
               'static', 'const', 'ref', 'input', 'output', 'inout', 'do', 'for', 'if', 'case',
               'wait', 'table', 'primitive', 'module', 'package', 'interface', 'program', 'alias',
               'always', 'assign', 'begin', 'break', 'continue', 'default', 'disable', 'enum',
               'export', 'extern', 'final', 'function', 'generate', 'genvar', 'import', 'initial',
               'typedef', 'union', 'struct', 'unique', 'priority', 'signed', 'unsigned', 'return'}


def load_if_split():
    """读 ADR-P-2 的机判切分表 `{struct: [行]}`；缺件/坏件返回 {}（由判据侧 FAIL，不在此处合成）。"""
    d = load_json(IF_SPLIT, default=None)
    if not isinstance(d, dict):
        return {}
    return {k: v for k, v in d.items() if not k.startswith('_') and isinstance(v, list)}


def norm_raw(s):
    """成员列原文归一（与 `doc/decisions/check_if_split.py` 的 norm() 同式）：去反引号/星号、压空白。"""
    return re.sub(r'\s+', ' ', (s or '').replace('`', '').replace('*', '')).strip()


def is_scalar_member(m):
    """可生成标量字段 = 位宽解析得出 且 字段名是合法 SV 标识符（否则走切分表/登记，fail-closed）。"""
    return m['width'] is not None and bool(IDENT_OK.match(m['field']))


def split_lookup(trows, m, used):
    """按「成员列原文归一」在切分表里取该非标量行的条目；查不到返回 None（调用方转为登记注释）。

    `used` 记录已消费的表内下标，防同一表行被两行源成员重复消费（一行对一行）。
    """
    key = norm_raw(m['field'])
    for i, r in enumerate(trows or []):
        if i in used:
            continue
        if norm_raw(r.get('raw')) == key:
            used.add(i)
            return r
    return None


def types_member_split():
    """把每个 struct 的成员分成「可生成标量字段」与「非标量行（查切分表展开／查不到则登记）」。

    非标量行 = 字段名不是合法 SV 标识符（如 `＝ ftq_req_t（全字段复用）`、`type[6:0]`）
    或位宽解析不出。这些在 `spec/01` 里以 29 处简写出现，其切分由 ADR-P-2 明确规定
    （`doc/decisions/if_split.json`）；本函数只负责归类，展开在 `render_types` 内查表完成。
    """
    structs_l, irregular = [], []
    for s in structs():
        scalar, other = [], []
        for m in s['members']:
            if not is_scalar_member(m):
                other.append(m)
                irregular.append((s['name'], m))
            else:
                scalar.append(m)
        structs_l.append(dict(s, scalar=scalar, other=other))
    return structs_l, irregular


def render_types():
    """spec/01 §3 的 28 个 struct → vr1_types.svh。

    逐 struct 按 `width_check.parse()` 的**源成员行顺序**产出声明：
      · 标量行 → 一行 `logic [w-1:0] <名>;`，带 `// src: L<行号> <成员列原文>` 标记；
      · 非标量行 → 查 ADR-P-2 切分表（`if_split.json`）按 `fields` 展开 k 个字段（同一 src 标记 =
        一个「行组」）；带 `replaces` 的行先扣除先前展开出的同名字段（净额口径见 ADR-P-2 §1 R1）；
      · **查不到切分表的行只登记注释**（`// [非标量·登记]`）——绝不猜名、不猜宽、不静默丢弃。
    """
    rows, _irregular = types_member_split()
    table = load_if_split()
    n_mem = sum(len(s['members']) for s in rows)
    n_scalar = sum(len(s['scalar']) for s in rows)
    unexpanded = []
    out, w = [], None
    w = out.append
    w('// ' + '=' * 74)
    w('// vr1_types.svh — 由 doc/spec/01 §3 接口 struct 表生成（字段名/位宽唯一权威源）')
    w('// DO NOT EDIT BY HAND. 改字段请改 spec/01 §3，再跑：python script/flow.py types')
    w('// 生成时间 %s ／ 源文件 md5 %s' % (datetime.now().strftime('%Y-%m-%d %H:%M'), md5_of(SPEC01)))
    w('// 覆盖对账：%d 个 struct / %d 个源成员行 = %d 个标量行 + %d 个非标量行'
      % (len(rows), n_mem, n_scalar, n_mem - n_scalar))
    w('//   非标量行按 doc/decisions/if_split.json（ADR-P-2 切分表）展开为**真实字段声明**；')
    w('//   切分表查不到的源行**只登记、不猜测**（fail-closed），由判据 types-coverage 逐行复核。')
    w('// 源行可核：每个字段行带 `// src: L<行号> <成员列原文>`；同一源行的字段共享同一标记（＝1 个行组）。')
    w('// 打包顺序：ADR-P-1（RD 自决 2026-09-25）——表中自上而下 = MSB→LSB。')
    w('//   spec/01 全篇未规定打包顺序（实测无 MSB/LSB/位序 表述）；本约定为**自决项**，')
    w('//   已进 G1 评审 list 供人确认；回退点＝改 PACK_ORDER_MSB_FIRST 后重生成。')
    w('// 解析复用 script/width_check.py 的 parse()/member_width()（不另写解析器）；')
    w('// 切分复用 doc/decisions/if_split.json（ADR-P-2；自检器 doc/decisions/check_if_split.py）。')
    w('// ' + '=' * 74)
    w('`ifndef VR1_TYPES_SVH')
    w('`define VR1_TYPES_SVH')
    for s in rows:
        w('')
        w('// ---- spec/01 §3 L%d `%s`（合计 %d bit%s）----'
          % (s['head'], s['name'], s['total'],
             '，声明 %s' % '/'.join(str(c) for c in s['claims']) if s['claims'] else ''))
        mem = list(s['members'])
        if not PACK_ORDER_MSB_FIRST:
            mem = list(reversed(mem))
        trows = table.get(s['name'], [])
        used, fields = set(), []            # fields: {name,width,tag} 或 {reg:成员行}
        for m in mem:
            if is_scalar_member(m):
                nm, note = m['field'], ''
                if nm in SV_KEYWORDS:
                    note = ' ｜ 原名 %s（SV 保留字，加 _f 后缀；G1 可改）' % nm
                    nm += '_f'
                if m['note']:
                    note += ' ｜ %s' % m['note']
                fields.append({'name': nm, 'width': m['width'],
                               'tag': '// src: L%d %s%s' % (m['line'], norm_raw(m['field']), note)})
                continue
            r = split_lookup(trows, m, used)
            if r is None:                   # 查不到 → fail-closed：原样登记，绝不猜
                fields.append({'reg': m, 'name': m['field']})
                unexpanded.append((s['name'], m))
                continue
            tag = '// src: L%d %s ｜ %s 展开' % (m['line'], norm_raw(m['field']), r.get('rule', '?'))
            if r.get('replaces'):
                names = [x['name'] for x in r['replaces']]
                tag += '（替换 %s）' % '/'.join(names)
                fields = [f for f in fields if f['name'] not in names]
            if r.get('rename'):
                rn = r['rename']
                tag += '（改名 %s→%s：%s）' % (rn.get('from', '?'), rn.get('to', '?'),
                                              (rn.get('why') or '')[:60])
            for f in r['fields']:
                fields.append({'name': f['name'], 'width': f['width'], 'tag': tag})
        seen, dups = set(), []
        for f in fields:
            if f['name'] in seen:
                dups.append(f['name'])
            seen.add(f['name'])
        if dups:                            # 重现声明会让生成件非法 SV → 显式标红（判据 side FAIL）
            w('// [FAIL·字段名重复] %s 内重复声明：%s（切分表与源行冲突，须先修表）'
              % (s['name'], '、'.join(sorted(set(dups)))))
        if not fields:                      # 退化兜底（ADR-P-2 §6 已取消该分支：出现即由判据判 FAIL）
            w('// [兜底·异常] 本 struct 的源成员行无一可生成/可展开 → 不透明位宽兜底')
            w('typedef logic [%d:0] %s;' % (max(s['total'] - 1, 0), s['name']))
            w('localparam int unsigned %s_W = %d;' % (s['name'].upper(), s['total']))
            continue
        w('typedef struct packed {')
        for f in fields:
            if f.get('reg') is not None:
                m = f['reg']
                w('  // [非标量·登记] %s  ← 原文 %s（%s）' % (m['field'], m['declared'], m['note']))
            else:
                w('  logic [%d:0] %s;  %s' % (f['width'] - 1, f['name'], f['tag']))
        w('} %s;' % s['name'])
        w('localparam int unsigned %s_W = %d;' % (s['name'].upper(), s['total']))
    w('')
    w('// ---- 未展开行清单（以下行不属任何 struct 块；由 flow.py 的 types-coverage 判据复核）----')
    w('// 切分表（if_split.json）无对应行的非标量源行在此登记（fail-closed；当前应为 0 条）。')
    if unexpanded:
        for name, m in unexpanded:
            w('//   [未展开] %s.%s  ← 原文 %s（%s）' % (name, m['field'], m['declared'], m['note']))
    else:
        w('//   （空：全部非标量源行均已按 ADR-P-2 切分表展开为真实字段）')
    w('')
    w('`endif // VR1_TYPES_SVH')
    return '\n'.join(out) + '\n'


def cmd_types(write=True):
    text = render_types()
    rows, _irregular = types_member_split()
    n_mem = sum(len(s['members']) for s in rows)
    n_grp, n_reg = trace_stats(text)
    if write:
        os.makedirs(os.path.dirname(TYPES_SVH), exist_ok=True)
        with open(TYPES_SVH, 'w', encoding='utf-8', newline='\n') as f:
            f.write(text)
        print('[flow] types: 生成 %s（%d struct / %d 源成员行 = %d 个 src 行组 + %d 个登记行）'
              % (os.path.relpath(TYPES_SVH, ROOT).replace('\\', '/'),
                 len(rows), n_mem, n_grp, n_reg))
    if n_reg:
        for ln in text.splitlines():
            if TYPE_REG_RE.match(ln):
                print('  [非标量·登记·未展开] %s' % ln.strip()[:110])
    return 0


def trace_stats(text):
    """数生成件里的「src 行组」与「登记行」（与 types-coverage 判据同口径，读产品不读内存态）。"""
    groups, n_reg = set(), 0
    for ln in text.splitlines():
        m = TYPE_SRC_RE.search(ln)
        if m:
            groups.add(m.group(0))
        elif TYPE_REG_RE.match(ln):
            n_reg += 1
    return len(groups), n_reg


def chk_types_coverage():
    """不变式（ADR-P-2 生效后改为**按源行可核**）：每个源成员行都要有痕迹，缺一即 FAIL。

    旧不变式「`logic [` 行数 + 登记行数 == 成员数」在非标量行被展开后不再成立（一行拆 k 个字段）。
    新口径：`spec/01` §3 的每个源成员行 → 要么产出一组带 `// src: L<行号> …` 的字段行（同一源行的
    k 个字段共享同一标记 ＝ 1 个「src 行组」），要么保留一行 `// [非标量·登记]`。
    判据：逐 struct（并全篇合计）**源行数 == src 行组数 + 登记行数**；另：登记行数必须等于切分表
    未命中的非标量行数（防「标量行被登记」与「命中的行没展开」两类错位）；出现 `[兜底·异常]`
    或 `[FAIL·字段名重复]` 标记亦 FAIL。
    """
    rows, _irregular = types_member_split()
    if not os.path.exists(TYPES_SVH):
        return False, '缺 %s' % rel(TYPES_SVH)
    table = load_if_split()
    groups, regs, bad = {}, {}, []
    cur = None
    for ln, line in enumerate(io.open(TYPES_SVH, 'r', encoding='utf-8').read().splitlines(), 1):
        if TYPE_TAIL_RE.match(line):        # 未展开清单区：以下行不属任何 struct 块
            cur = None
            continue
        m = TYPE_BLOCK_RE.match(line)
        if m:
            cur = m.group(2)
            groups.setdefault(cur, set())
            regs.setdefault(cur, 0)
            continue
        if cur is None:
            continue
        if TYPE_BAD_RE.search(line):
            bad.append('%s:%d %s' % (cur, ln, line.strip()[:66]))
            continue
        s = TYPE_SRC_RE.search(line)
        if s:
            groups[cur].add(s.group(0))
        elif TYPE_REG_RE.match(line):
            regs[cur] += 1
    n_src_all = n_grp_all = n_reg_all = 0
    for st in rows:
        nm = st['name']
        n_src = len(st['members'])
        n_grp, n_reg = len(groups.get(nm, ())), regs.get(nm, 0)
        used, hit = set(), 0                # 该 struct 在切分表里能命中的非标量行数
        for m in st['other']:
            if split_lookup(table.get(nm, []), m, used) is not None:
                hit += 1
        if n_src != n_grp + n_reg:
            bad.append('%s 源行 %d ≠ src 行组 %d + 登记行 %d' % (nm, n_src, n_grp, n_reg))
        elif n_reg != len(st['other']) - hit:
            bad.append('%s 登记行 %d ≠ 切分表未命中的非标量行 %d（错位：标量行被登记或命中行未展开）'
                       % (nm, n_reg, len(st['other']) - hit))
        n_src_all += n_src
        n_grp_all += n_grp
        n_reg_all += n_reg
    if bad:
        return False, '源行不可核 %d 处：%s' % (len(bad), '；'.join(bad[:4]))
    return True, ('%d 个 struct／%d 个源成员行 = %d 个 src 行组 + %d 个登记行'
                  '（源行守恒：无静默丢弃／无猜测）' % (len(rows), n_src_all, n_grp_all, n_reg_all))


# 生成件里每个 struct 的块头/字段/不透明位宽类型（只读磁盘产品面，不读生成器内存态）
TYPE_BLOCK_RE = re.compile(r'^// ---- spec/01 §3 L(\d+) `([A-Za-z_0-9]+)`')
TYPE_OPAQUE_RE = re.compile(r'^typedef logic \[(\d+):(\d+)\] ([A-Za-z_0-9]+);')
TYPE_FIELD_RE = re.compile(r'^\s+logic \[(\d+):(\d+)\] ')
# 源行可核标记（types-coverage 判据面）：`// src: L<行号> ` = 一个源成员行的「行组」；
# 未展开的非标量行保留 `// [非标量·登记]`；两个 FAIL 标记出现即判红（fail-closed）。
TYPE_SRC_RE = re.compile(r'// src: L\d+ ')
TYPE_REG_RE = re.compile(r'^\s+// \[非标量·登记\]')
TYPE_TAIL_RE = re.compile(r'^// -+ 未展开行清单')
TYPE_BAD_RE = re.compile(r'\[兜底·异常\]|\[FAIL·字段名重复\]')


def generated_widths():
    """读磁盘 vr1_types.svh：每个 struct 已生成声明的位宽之和（不透明位宽类型按整体宽度）。"""
    gen, opaque, name = {}, [], None
    for ln in io.open(TYPES_SVH, 'r', encoding='utf-8').read().splitlines():
        m = TYPE_BLOCK_RE.match(ln)
        if m:
            name = m.group(2)
            gen.setdefault(name, 0)
            continue
        if name is None:
            continue
        m = TYPE_FIELD_RE.match(ln)
        if m:
            gen[name] += abs(int(m.group(1)) - int(m.group(2))) + 1
            continue
        m = TYPE_OPAQUE_RE.match(ln)
        if m:
            gen[name] = abs(int(m.group(1)) - int(m.group(2))) + 1
            opaque.append(name)
    return gen, opaque


def chk_types_width_consistency():
    """types-width-consistency（ISS-107④ 洞 3；ADR-2 生效后改为**期望零差额**）。

    口径：逐 struct「生成出来的宽度」（磁盘 vr1_types.svh 的字段位宽和）== `width_check.py --json`
    的 `sum_computed`（独立复算）；**任一差额即 FAIL 并列差额清单**——ADR-2 切分表已把 29 处
    非标量行落成真实字段声明，差额不再是"未裁定的设计缺口"而是实质问题（红线 R6：
    **不放宽判据凑绿**；有差额就停下如实报告）。
    另两条 fail-closed：出现不透明兜底类型（ADR-2 §6 已取消该分支）／生成件缺 struct 或解析不出。
    """
    if not os.path.exists(TYPES_SVH):
        return False, '缺 %s（先跑 flow.py types）' % rel(TYPES_SVH)
    rc, out = run([sys.executable, 'script/width_check.py', '--json'])
    i, j = out.find('['), out.rfind(']')
    if i < 0 or j < i:
        return False, 'width_check --json 输出无法解析（fail-closed）'
    try:
        ref = {r['struct']: r for r in json.loads(out[i:j + 1])}
    except Exception as e:                                          # noqa: BLE001
        return False, 'width_check JSON 解析失败：%s' % e
    gen, opaque = generated_widths()
    unknown = [n for n in ref if not n.startswith('@') and n not in gen]
    if unknown:
        return False, '%d 个 struct 在 %s 中无法核对（生成件缺件，fail-closed）：%s' % (
            len(unknown), rel(TYPES_SVH), '、'.join(unknown[:5]))
    if opaque:
        return False, ('出现不透明位宽兜底类型（ADR-2 §6 已取消该分支，出现即须修）：%s'
                       % '、'.join(opaque))
    diffs, n_ok = [], 0
    for name, r in ref.items():
        if name.startswith('@') or name not in gen:
            continue
        d = r.get('sum_computed', 0) - gen[name]
        if d:
            diffs.append('%s 生成 %d bit ≠ 独立复算 %d bit（差 %+d bit）'
                         % (name, gen[name], r.get('sum_computed', 0), d))
        else:
            n_ok += 1
    if diffs:
        return False, ('%d/%d struct 生成宽度 ≠ 独立复算（差额清单）：%s'
                       % (len(diffs), n_ok + len(diffs), '；'.join(diffs)))
    return True, '%d 个 struct 生成宽度 == 独立复算（差 0 bit，合计 %d bit）' % (
        n_ok, sum(gen[n] for n in gen))


def chk_types_drift():
    want = render_types()
    if not os.path.exists(TYPES_SVH):
        return False, 'missing %s（先跑 flow.py types）' % os.path.relpath(TYPES_SVH, ROOT)
    got = io.open(TYPES_SVH, 'r', encoding='utf-8').read()
    norm = lambda t: '\n'.join(x for x in t.splitlines() if '生成时间' not in x)
    if norm(want) != norm(got):
        return False, 'spec/01 §3 与磁盘 svh 不一致（类型漂移）→ 跑 flow.py types'
    return True, 'spec/01 §3 重算 == 磁盘 svh（md5 %s）' % md5_of(TYPES_SVH)[:8]


def chk_types_crosscheck():
    """差分核对：本次生成的每 struct 合计 == width_check.py 独立算出的 sum_computed。

    两个实现（生成本文件 vs width_check 的 check 路径）对同一份 spec 表各自求和，
    一致才算数——这是"不用同一实现在自证"的最低要求。
    """
    rc, out = run([sys.executable, 'script/width_check.py', '--json'])
    i, j = out.find('['), out.rfind(']')
    if i < 0:
        return False, 'width_check --json 无输出（fail-closed）'
    ref = {r['struct']: r for r in json.loads(out[i:j + 1])}
    mine = {s['name']: s for s in structs()}
    bad = []
    for name, s in mine.items():
        r = ref.get(name)
        if r is None:
            continue
        if r.get('sum_computed') != s['total']:
            bad.append('%s 生成 %s ≠ width_check %s' % (name, s['total'], r.get('sum_computed')))
    if bad:
        return False, '%d 个 struct 两实现不一致：%s' % (len(bad), '；'.join(bad[:3]))
    return True, '%d 个 struct 合计与 width_check 独立复算一致' % len(mine)


def chk_types_compile():
    """vlog 编译：参数包 + 类型包 + 接口骨架 一起编（证据 = -- Compiling 计数 + Errors: 0）。"""
    if not os.path.exists(VLOG):
        return False, 'vlog 不存在：%s' % VLOG
    if not os.path.exists(TYPES_PKG):
        return False, '缺 %s' % rel(TYPES_PKG)
    d = os.path.join(ROOT, 'sim', 'run_types')
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'run.log'), 'w', encoding='utf-8').close()
    inc = os.path.join(ROOT, 'rtl', 'vr1', 'include').replace('\\', '/')
    srcs = [TYPES_PKG.replace('\\', '/'), os.path.join(ROOT, 'tb', 'vr1_uvm', 'vr1_if.sv').replace('\\', '/')]
    text, rc = _msim(d, [
        [VLIB, 'work'],
        [VLOG, '-64', '-sv', '-work', 'work', '+incdir+%s' % inc] + srcs,
    ], 'vlog')
    n_err = re.findall(r'Errors:\s*(\d+)', text)
    n_comp = len(re.findall(r'^-- Compiling', text, re.M))
    if not n_err:
        return False, '编译日志无 `Errors: N`（fail-closed）→ %s' % rel(os.path.join(d, 'run.log'))
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(os.path.join(d, 'run.log')))
    if n_comp < 3:
        return False, '`-- Compiling` 计数 %d < 3（类型包/接口未全部编过）' % n_comp
    return True, 'vlog 编译 %d 个单元（类型包+参数包+接口骨架）｜ Errors: 0 ｜ %s' % (
        n_comp, rel(os.path.join(d, 'run.log')))


def chk_types_elab():
    """vsim elaboration：类型包 + 参数包 + 接口骨架能否被仿真器展开（证据 = [types_smoke] 行）。"""
    if not os.path.exists(VSIM):
        return False, 'vsim 不存在：%s' % VSIM
    d = os.path.join(ROOT, 'sim', 'run_types')
    os.makedirs(d, exist_ok=True)
    text, rc = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'work.vr1_types_smoke']], 'vsim')
    if 'License' in text and ('Failure to obtain' in text or 'Invalid host' in text):
        return False, 'ENV-BLOCKED ModelSim license（见 ISS-104）'
    smoke = [ln for ln in text.splitlines() if '[types_smoke]' in ln]
    if not smoke:
        return False, '未见 [types_smoke] 证据行 → %s' % rel(os.path.join(d, 'run.log'))
    return True, '%s ｜ %s' % (rel(os.path.join(d, 'run.log')), smoke[-1].strip()[:96])


def active_milestone(st):
    for m in st.get('milestones', []):
        if m.get('state') == 'active':
            return m
    return {}


def milestone_to_check(st):
    """判据面：优先 active；无 active 则复核**最近一个已 met 的里程碑**（防止"达成后回归"无人看）。"""
    m = active_milestone(st)
    if m:
        return m, True
    met = [x for x in st.get('milestones', []) if x.get('state') == 'met']
    return (met[-1] if met else {}), False


def next_milestone(st):
    for m in st.get('milestones', []):
        if m.get('state') in ('blocked', 'pending'):
            return m
    return {}


def cmd_check(quiet=False):
    st = load_json(STATE) or {}
    fails = []
    env_fails = []                      # 仅**环境阻塞**（ENV-BLOCKED，ISS-104 类）引起的 FAIL：单列一档
    print('== flow check（判据只判产品；流程完整性由脚本副产品承担）==')
    led = load_json(LEDGER)
    if led and led.get('entries'):
        print('  PASS  ledger                %d 条；next=%s' % (len(led['entries']), led['next']))
    else:
        print('  FAIL  ledger                ledger.json 缺失或结构不符')
        fails.append('ledger')
    ok, msg = chk_state()
    print('  %s  state                 %s' % ('PASS' if ok else 'FAIL', msg))
    if not ok:
        fails.append('state')
    guard_fails, exit_fails = [], []
    for g in GUARDS:
        try:
            gok, gmsg = CHECKS[g]()
        except Exception as exc:                                   # noqa: BLE001
            gok, gmsg = False, '判据异常 %s' % exc
        print('  %s  %-20s %s' % ('PASS' if gok else 'FAIL', g, gmsg))
        if not gok:
            fails.append(g)
            guard_fails.append(g)
    m, is_active = milestone_to_check(st)
    env_decl = set(b.get('check') for b in m.get('env_blocked', []))
    exits = m.get('exit', [])
    print('  里程碑： %s %s [%s]%s' % (m.get('id', '(无)'), m.get('name', ''), m.get('state', '-'),
                                      '' if is_active else '（active 已空 → 复核最近达成项，防达成后回归）'))
    for e in exits:
        fn = CHECKS.get(e['check'])
        if fn is None:
            print('  FAIL  %-20s 未注册判据 %s' % (e['check'], e['check']))
            fails.append(e['check'])
            continue
        try:
            ok, msg = fn()
        except Exception as exc:                                   # noqa: BLE001
            ok, msg = False, '判据异常 %s: %s' % (type(exc).__name__, exc)
        tag = e['check'] + ' ' * max(0, 20 - len(e['check']))
        print('  %s  %s%s' % ('PASS' if ok else 'FAIL', tag, msg))
        if not ok:
            fails.append(e['check'])
            exit_fails.append(e['check'])
            # 环境阻塞＝判据**自报** ENV-BLOCKED，或里程碑 `env_blocked` 显式声明该判据（二者取或）
            if 'ENV-BLOCKED' in (msg or '') or e['check'] in env_decl:
                env_fails.append(e['check'])
    nxt = next_step(st)
    if nxt:
        print('  下一步： [%s] %s' % (nxt['id'], nxt.get('task', '')))
    else:
        print('  下一步： 无待派步骤')
    for s in blocked_steps(st):
        print('  步骤阻塞： [%s] %s ｜ 因：%s' % (s['id'], s.get('task', '')[:60],
                                              (s.get('blocked_by') or '')[:90]))
    if not fails and is_active:                           # 里程碑达成：状态机推进 + 自动记账
        m['state'] = 'met'
        m['met_at'] = datetime.now().strftime('%Y-%m-%d %H:%M')
        st['stop_requests'] = 0
        save_json(STATE, st)
        rid = record('R', '里程碑 %s exit 全过（%s）'
                     % (m['id'], ','.join(e['check'] for e in m.get('exit', []))), quiet=True)
        print('  里程碑： %s 达成（记账 %s）' % (m['id'], rid))
    nonenv_prod = [x for x in fails if x not in env_fails and x not in guard_fails]
    if not fails:
        print('---- flow check: PASS / 里程碑 %s exit 全过 ----' % m.get('id', '-'))
    else:
        # 末行须区分「里程碑 exit 未过」与「常跑守卫未过」（守卫不判产品；否则会误报里程碑状态）
        bits = []
        if exit_fails:
            bits.append('里程碑 %s exit 未过' % m.get('id', '-'))
        if guard_fails:
            bits.append('常跑守卫未过：%s' % '、'.join(guard_fails))
        other = [x for x in fails if x not in guard_fails and x not in exit_fails]
        if other:
            bits.append('前置项未过：%s' % '、'.join(other))
        if env_fails:
            bits.append('环境阻塞（ENV-BLOCKED，退出码 %d）：%s'
                        % (3 if not nonenv_prod else 1, '、'.join(env_fails)))
        print('---- flow check: FAIL（%s；见上列 FAIL 项）----' % '；'.join(bits))
    # ENV-BLOCKED 明细：**判据自报者自动补充打印**（旧写法只读里程碑手填字段，会漏印，见 doc/review/06 F-1）
    shown = set()
    for b in m.get('env_blocked', []):
        print('  ENV-BLOCKED  %-16s %s（%s）' % (b['check'], b.get('why', '')[:80], b.get('iss', '')))
        shown.add(b.get('check'))
    for c in env_fails:
        if c not in shown:
            print('  ENV-BLOCKED  %-16s 判据自报（摘要见上列 FAIL 行）' % c)
    if not fails:
        return 0
    # 3 = **产品/前置面只剩环境阻塞**（常跑守卫不判产品，不参与这一档的压制；混有非环境的
    # 产品/前置 FAIL 时仍返回 1）。环境阻塞**绝不与「全过」共用 0**。
    return 3 if (env_fails and not nonenv_prod) else 1


def next_step(st):
    """第一个**可跑**的待派步骤：`blocked_by` 非空的 pending 步骤**不算下一步**（它是等待项）。

    2026-09-26 修正：原实现返回第一个 pending（不读 `blocked_by`），于是 `next`/`check` 会把
    "被阻塞的步骤"报成下一步（实测：M2-2 被 RV64I 指令面扩展阻塞却排在下一步）；
    `cmd_run` 本来就跳过 blocked 步骤（口径在两处不一致）。现在统一：可跑者才叫下一步，
    阻塞者单列一行（可见但不误导）。停机的正确形态由此自然成立：只剩阻塞项/需人项时
    `next_step` 返回 None ⇒ Stop hook 不再请求续跑（规则 24 ④）。
    """
    for s in st.get('steps', []):
        if s.get('status') == 'pending' and not s.get('blocked_by'):
            return s
    return None


def blocked_steps(st):
    """被阻塞的 pending 步骤（列报用；不进"下一步"）。"""
    return [s for s in st.get('steps', [])
            if s.get('status') == 'pending' and s.get('blocked_by')]


# --------------------------------------------------------------------------- #
# next / run
# --------------------------------------------------------------------------- #
def cmd_next():
    st = load_json(STATE) or {}
    m, is_active = milestone_to_check(st)
    print('流程     : A（Runner-in-the-Loop）  状态唯一真值 state/flow.json')
    title = '里程碑   : %s %s [%s]' % (m.get('id', '(无)'), m.get('name', ''), m.get('state', '-'))
    print(title + ('' if is_active else '  ← 已达成，下列判据为回归复核'))
    if m.get('blocked_by'):
        print('阻塞     : %s' % m['blocked_by'])
    for e in m.get('exit', []):
        fn = CHECKS.get(e['check'])
        try:
            ok, msg = fn() if fn else (False, '未注册')
        except Exception as exc:                                   # noqa: BLE001
            ok, msg = False, str(exc)
        print('  [%s] %-18s %s' % ('x' if ok else ' ', e['check'], e.get('desc', '')))
    nm = next_milestone(st)
    if nm:
        print('下一里程碑: %s %s [%s]' % (nm.get('id'), nm.get('name', ''), nm.get('state')))
        if nm.get('blocked_by'):
            print('  阻塞   : %s' % nm['blocked_by'])
    hw = [s for s in st.get('steps', []) if s.get('status') == 'waiting_human']
    for s in hw:
        print('需人项   : [%s] %s' % (s['id'], s.get('task', '')))
    s = next_step(st)
    if s is None:
        print('下一步   : 无（里程碑达成或队列空 → 呈现人）')
        for b in blocked_steps(st):
            print('步骤阻塞 : [%s] %s' % (b['id'], (b.get('blocked_by') or '')[:120]))
        return 0
    print('下一步   : [%s] %s' % (s['id'], s.get('task', '')))
    print('  判据   : %s' % s.get('done', ''))
    if s.get('cmd'):
        print('  命令   : %s' % ' ; '.join(' '.join(c) for c in s['cmd']))
    print('  预算   : %s' % s.get('budget', '≤30 分钟'))
    for b in blocked_steps(st):
        print('步骤阻塞 : [%s] %s' % (b['id'], (b.get('blocked_by') or '').split('（')[0][:100]))
    return 0


def record(kind, text, quiet=False):
    """台账自增登记。**ADR 走编号分区**：写入 id 形如 `ADR-P-<n>`（`P`＝process 侧 ADR；
    裸号 `ADR-<n>` 是规格/历史面既有编号，保留原义、不再发新号）。计数沿用 `next.ADR`。"""
    led = load_json(LEDGER) or {'next': {'ISS': 1, 'R': 1, 'ADR': 1}, 'entries': []}
    num = led['next'][KIND_KEY[kind]]
    led['next'][KIND_KEY[kind]] = num + 1
    rid = 'ADR-P-%d' % num if kind == 'ADR' else '%s-%d' % (kind, num)
    led['entries'].append({'id': rid, 'kind': kind, 'text': text,
                           'ts': datetime.now().strftime('%Y-%m-%d %H:%M')})
    save_json(LEDGER, led)
    if not quiet:
        print('[flow] 已登记 %s（自动编号）' % rid)
    return rid


def cmd_run(budget=3):
    st = load_json(STATE)
    if not st:
        print('[flow] state/flow.json 缺失')
        return 2
    ran = 0
    skipped_human = []
    for s in st.get('steps', []):
        stt = s.get('status')
        if stt == 'waiting_human':
            skipped_human.append(s)     # 需人项不阻塞后续可自动跑的步骤（A 的要点：能做的全做掉）
            continue
        if stt != 'pending' or not s.get('cmd'):
            continue
        if s.get('blocked_by'):
            print('[BLOCKED] %s：%s' % (s['id'], s['blocked_by']))
            continue
        if ran >= budget:
            print('[STOP] 本轮步数上限 %d（防单轮失控）' % budget)
            break
        d = os.path.join(ROOT, 'sim', 'run_%s' % s['id'])
        os.makedirs(d, exist_ok=True)
        log = os.path.join(d, 'run.log')
        acc, ok = [], True
        for argv in s['cmd']:
            acc.append('$ ' + ' '.join(argv))
            try:
                rc, o = run(argv, timeout=s.get('timeout', 900))
            except subprocess.TimeoutExpired:
                acc.append('!! TIMEOUT')
                ok = False
                break
            acc.append(o)
            if rc != 0:
                ok = False
                break
        with open(log, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(acc))
        ran += 1
        line = last_line(acc[-1] if acc else '')
        if ok and not s.get('require'):
            s['status'] = 'done'
            s['evidence'] = ('%s %s ｜ %s ｜ %s' % (
                s.get('evidence', '').strip(), rel(log), line[:120],
                datetime.now().strftime('%Y-%m-%d %H:%M'))).strip(' ｜')
            save_json(STATE, st)
            record('R', '%s 通过：%s' % (s['id'], line[:150]), quiet=True)
            print('[PASS] %s ｜ %s' % (s['id'], line[:150]))
        else:
            s['fail_note'] = '%s ｜ %s' % (rel(log), line[:150])
            save_json(STATE, st)
            print('[FAIL] %s ｜ %s' % (s['id'], line[:150]))
            print('[STOP] 控制权交回编排（日志 %s）' % rel(log))
            return 1
    done = [x['id'] for x in st['steps'] if x.get('status') == 'done']
    print('---- flow run：本轮 %d 步；done=%s ----' % (ran, done))
    for s in skipped_human:
        print('[需人] %s：%s' % (s['id'], s.get('task', '')))
    return 0


# --------------------------------------------------------------------------- #
# hook 三件
# --------------------------------------------------------------------------- #
def flow_context(max_chars=2400):
    st = load_json(STATE) or {}
    m, is_active = milestone_to_check(st)
    out = ['流程 A（Runner-in-the-Loop）｜ 状态真值 state/flow.json']
    if m:
        out.append('里程碑 %s %s [%s]%s' % (m.get('id'), m.get('name', ''), m.get('state', '-'),
                                            '' if is_active else '（已达成；以下为回归复核）'))
        unmet = []
        for e in m.get('exit', []):
            fn = CHECKS.get(e['check'])
            try:
                ok, msg = fn() if fn else (False, '未注册')
            except Exception as exc:                               # noqa: BLE001
                ok, msg = False, str(exc)[:60]
            if not ok:
                unmet.append('- [%s] %s：%s' % (e['check'], e.get('desc', ''), msg[:80]))
        out.append('exit：' + ('全过' if not unmet else '未达'))
        out.extend(unmet)
    nm = next_milestone(st)
    if nm:
        out.append('下一里程碑 %s %s：%s' % (nm.get('id'), nm.get('name', ''),
                                            nm.get('blocked_by', '')))
    for s in st.get('steps', []):
        if s.get('status') == 'waiting_human':
            out.append('需人项 [%s]：%s' % (s['id'], s.get('task', '')))
    s = next_step(st)
    out.append('下一步：' + ('[%s] %s ｜ 判据 %s' % (s['id'], s.get('task', ''), s.get('done', ''))
                            if s else '无待派步骤（呈现人）'))
    for b in blocked_steps(st):
        out.append('步骤阻塞 [%s]：%s' % (b['id'], (b.get('blocked_by') or '')[:120]))
    out.append('禁令：禁手写编号；禁改 sim/covdb/**；G1 冻结前 rtl/ 只允许 include/*.svh 生成件；'
               '确定性工作走 `python script/flow.py run`，不得口头声明完成。')
    txt = '\n'.join(out)
    return txt[:max_chars]


def cmd_ctx():
    print(json.dumps({'additionalContext': flow_context()}, ensure_ascii=False))
    return 0


def cmd_gate_stop():
    """Stop hook：只在**真有可跑的确定性步骤**时请求继续。

    刻意不做昂贵判据（否则每次停轮都跑一遍 ModelSim）；里程碑判定归 `check`。
    上限 3 次（与 ZCode Stop 续跑上限同量级），防"卡住仍硬撑"烧预算。
    """
    st = load_json(STATE) or {}
    for s in st.get('steps', []):
        if s.get('status') != 'pending':
            continue
        if s.get('blocked_by') or not s.get('cmd'):
            continue                        # 被阻塞/无命令：放行，别空转
        n = int(st.get('stop_requests', 0))
        if n >= 3:
            print('[flow] 已请求续跑 3 次仍未推进步骤 %s（放行，交人裁决）' % s['id'],
                  file=sys.stderr)
            return 0
        st['stop_requests'] = n + 1
        save_json(STATE, st)
        print(json.dumps({'decision': 'block',
                          'reason': '有可跑的确定性步骤 %s：%s。请执行 `python script/flow.py run` '
                                    '（判据：%s），FAIL 则读 sim/run_%s/run.log 处置；不要口头声明完成。'
                                    % (s['id'], s.get('task', ''), s.get('done', ''), s['id'])},
                         ensure_ascii=False))
        return 0
    return 0                               # 无待跑步骤：放行


def cmd_guard_write():
    """机械执行 AGENTS.md §5.1 的写边界（三档，状态件＝`state/freeze.json`）。

      · 档 1 未冻结（状态件不存在，G1 前）：rtl/** 只允许 include/*.svh（参数与 struct 定义，生成件）；
      · 档 2 G1-I 已签授权（rtl_write_authorized 为真且 baseline 未宣布）：rtl/** 允许写，
        依据＝R0 2026-09-25 签署 G1-I 的人令（记录落 doc/spec/14 §7）；实现期仍不得实现清单 §3 延后类；
      · 档 3 基线已宣布（baseline != "未宣布"，优先于档 2）：rtl/** 拒绝（红线 R5 先批后改）；
      · 兜底：状态件在但既未授权、基线也未宣布 ⇒ 按已冻结处理（rtl/** 只读，红线 R1）；
        状态件在但不可解析 ⇒ fail-closed 同样按已冻结处理。
    恒久受保护：sim/covdb/**（签核证据）、.git/**、state/window.json。
    """
    data = read_stdin_json()
    if data is None:
        return 0
    ti = data.get('tool_input') or {}
    p = norm_path(str(ti.get('file_path') or ti.get('path') or ''))
    if not p:
        return 0
    if os.path.isabs(p):
        try:
            p = norm_path(os.path.relpath(p, ROOT))
        except ValueError:
            pass
    if p.startswith('..'):
        print('[guard-write] 拒绝：写入仓库外路径 %s' % p, file=sys.stderr)
        return 2
    for pat in ALWAYS_PROTECTED:
        if p.startswith(pat):
            print('[guard-write] 拒绝：%s 属受保护路径（%s）' % (p, pat), file=sys.stderr)
            return 2
    if p.startswith('rtl/'):
        fz = load_json(FREEZE) if os.path.exists(FREEZE) else None
        if isinstance(fz, dict):
            baseline = str(fz.get('baseline', '未宣布') or '未宣布').strip()
            if baseline != '未宣布':
                print('[guard-write] 拒绝：基线已宣布（state/freeze.json baseline=%s）⇒ rtl/ 转'
                      '「先批后改」（红线 R5）：先出改动报告待批。' % baseline, file=sys.stderr)
                return 2
            if fz.get('rtl_write_authorized'):
                print('[guard-write] 放行：依 R0 2026-09-25 G1-I 签署授权'
                      '（state/freeze.json rtl_write_authorized=true），rtl/ 处实现期；'
                      '不得实现冻结清单 §3 的延后类机制。本路径：%s' % p)
                return 0
            print('[guard-write] 拒绝：接口已冻结（state/freeze.json）且无 RTL 写授权，'
                  'rtl/ 转只读。疑似 RTL 缺陷只记录不修改（红线 R1）。', file=sys.stderr)
            return 2
        if os.path.exists(FREEZE):
            print('[guard-write] 拒绝：state/freeze.json 存在但不可解析（fail-closed）⇒ rtl/ 只读。'
                  '疑似 RTL 缺陷只记录不修改（红线 R1）。', file=sys.stderr)
            return 2
        if not (p.startswith('rtl/vr1/include/') and p.endswith('.svh')):
            print('[guard-write] 拒绝：G1 接口冻结前 rtl/ 只允许 rtl/vr1/include/*.svh'
                  '（参数与 struct 定义）。本路径：%s。见 AGENTS.md §5.1。' % p, file=sys.stderr)
            return 2
    return 0


def cmd_guard_bash():
    data = read_stdin_json()
    if data is None:
        return 0
    ti = data.get('tool_input') or {}
    cmd = str(ti.get('command') or '')
    low = cmd.lower()
    for pat, why in BASH_DENY:
        if re.search(pat, low):
            print('[guard-bash] 拒绝：命中破坏性模式「%s」→ %s\n命令：%s'
                  % (why, pat, cmd[:200]), file=sys.stderr)
            return 2
    return 0


# --------------------------------------------------------------------------- #
# 内容指纹窗口（收工即查 / 折入基线）
# --------------------------------------------------------------------------- #
SKIP_DIRS = {'.git', '__pycache__', '.pytest_cache', 'work', 'work_params'}
# `--take` 的合理性下限（件数比）：新快照 < 上一份 × 本比例 ⇒ 拒绝折入（除 `--force` ＋ reason 写明）。
# 取值 0.90 的口径：正常收工批的净删/净增都是十几件量级（≈1~2%），跌破 10% 只可能是"快照缺件"或
# 大规模删除（后者需人显式 `--force`），故不设更宽的容差——**宁拒一次，不污染基线**。
WINDOW_TAKE_MIN_RATIO = 0.90


def snapshot_files(errors=None):
    """内容指纹快照 = {仓库相对路径: 'md5:size'（>8 MB 记 'big:size'）}。

    **枚举失败不再静默吞掉**（2026-09-26 第十一轮加固；R-264 的病灶）：`os.walk` 默认
    `onerror=None` ⇒ 目录列举失败（权限/占用/路径过长）时**静默跳过整棵子树**，产出的快照
    **看起来正常但缺件**；08:29 那次折入即因此缺件。现在：
      · `os.walk(..., onerror=cb)` 的失败**逐条收集**（含目录名与原因）；
      · 文件级 `os.stat`/`md5` 失败同样收集（同病灶：一样会让快照缺件），不再 `continue` 瞒过。
    `errors` 传入时把错误追加进去；调用方（`cmd_window`）**有错即 FAIL**，不产出可能缺件的快照。
    """
    out = errors if errors is not None else []
    files = {}

    def _onerr(err):
        out.append('目录列举失败：%s（%s）' % (getattr(err, 'filename', '?'),
                                            getattr(err, 'strerror', err)))

    for base, dirs, names in os.walk(ROOT, onerror=_onerr):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith('work_')]
        for n in names:
            full = os.path.join(base, n)
            r = rel(full)
            if r.startswith('sim/run_') or r == 'state/window.json':
                continue
            try:
                st = os.stat(full)
                if st.st_size > 8 * 1024 * 1024:
                    files[r] = 'big:%d' % st.st_size
                    continue
                files[r] = '%s:%d' % (md5_of(full)[:12], st.st_size)
            except OSError as exc:                       # 不静默缺件：收集后由调用方 FAIL
                out.append('文件读取失败：%s（%s）' % (r, getattr(exc, 'strerror', exc)))
    return files, out


def cmd_window(args):
    take = '--take' in args
    force = '--force' in args
    reason = ''
    if '--reason' in args:
        i = args.index('--reason')
        reason = args[i + 1] if i + 1 < len(args) else ''
    errors = []
    now, errors = snapshot_files(errors)
    base = load_json(WINDOW, default={}) or {}
    old = base.get('files', {})
    # ① 枚举面：**有错即 FAIL**（不再产出/折入可能缺件的快照；R-264 的机械兜底）
    if errors:
        print('== window: FAIL（快照枚举有 %d 处错误 ⇒ 本快照可能缺件，既不比对也不折入）=='
              % len(errors))
        for e in errors[:20]:
            print('  ENUM-ERR  %s' % e)
        if len(errors) > 20:
            print('  ENUM-ERR  … 其余 %d 处（同类，略）' % (len(errors) - 20))
        print('---- window: FAIL（先排除枚举失败再重跑；不得拿缺件快照当基线）----')
        return 2
    if take:
        if not reason:
            print('[flow] window --take 必须带 --reason <折入集出处>（规则 22）')
            return 2
        # ② 合理性校验：件数**明显下降** ⇒ 拒绝折入（防"缺件快照"污染基线），除非 --force 且写明
        prev_n, new_n = len(old), len(now)
        floor = int(prev_n * WINDOW_TAKE_MIN_RATIO)
        if prev_n and new_n < floor and not force:
            print('== window --take 拒绝折入：件数异常下降（新 %d < 上一份 %d 的 %.0f%%＝%d）=='
                  % (new_n, prev_n, WINDOW_TAKE_MIN_RATIO * 100, floor))
            miss = sorted(set(old) - set(now))
            for k in miss[:20]:
                print('  MISSING   %s' % k)
            if len(miss) > 20:
                print('  MISSING   … 其余 %d 项（略）；全清单：可对比 state/window.json' % (len(miss) - 20))
            print('---- window: FAIL（缺件疑云：先查缺失项；确系正当批量删除才可 `--force`，'
                  '并在 --reason 里写明原因）----')
            return 2
        if prev_n and new_n < floor and force:
            print('[flow] 注意：件数 %d < 上一份 %d 的 %.0f%%（%d），本次因 --force 仍折入'
                  % (new_n, prev_n, WINDOW_TAKE_MIN_RATIO * 100, floor))
        save_json(WINDOW, {'taken': datetime.now().strftime('%Y-%m-%d %H:%M'),
                           'reason': reason, 'files': now})
        print('[flow] 窗口基线已刷新（%d 件，上一份 %d 件）；reason=%s' % (len(now), prev_n, reason))
        return 0
    added = sorted(set(now) - set(old))
    removed = sorted(set(old) - set(now))
    changed = sorted(k for k in set(now) & set(old) if now[k] != old[k])
    print('== window（基线 %s，%d 件）==' % (base.get('taken', '(无，首跑即全量)'), len(old)))
    cap = 40
    for tag, items in (('ADDED', added), ('REMOVED', removed), ('CHANGED', changed)):
        for k in items[:cap]:
            print('  %-8s %s' % (tag, k))
        if len(items) > cap:
            print('  %-8s … 其余 %d 项（同一类，略）' % (tag, len(items) - cap))
    print('---- window: +%d / -%d / ~%d ----' % (len(added), len(removed), len(changed)))
    return 1 if (added or removed) else 0


# --------------------------------------------------------------------------- #
# G1-I 冻结面判据（清单 `doc/decisions/G1-I-最小冻结清单.md` §2／§4 的机判面）
#
# 病灶同源：清单 §2 的「23 型／6 CSR／异常码表／参数集」只写在清单与各篇正文里，**没有机械对账** ⇒
# §6.1 的签署语义「清单完整 ＋ 我接受其风险」缺机判兜底；§4 的 14 条判据里 10 条「现有判据覆盖不到」，
# §6.3 `GD-1` 点名要在本文件的 `CHECKS` 注册表里补齐。
# 两条纪律：
#   · 一律 **fail-closed**：表/行/值解析不到即报出（不猜、不豁免；红线 R6 不放宽凑绿）；
#   · 一律**读真源**：ISS 侧走 `import iss/vriss/*`（真枚举/真构造器），不另写解析器或副本。
# 写边界：只读 `doc/spec/**`、`doc/decisions/G1-I-*.md`、`iss/**`、`rtl/vr1/include/*.svh`。
# --------------------------------------------------------------------------- #
SPEC10 = os.path.join(ROOT, 'doc', 'spec', '10-特权与CSR.md')
SPEC02 = os.path.join(ROOT, 'doc', 'spec', '02-指令集与逐指令行为.md')
G1I_LIST = os.path.join(ROOT, 'doc', 'decisions', 'G1-I-最小冻结清单.md')
ISS_SMOKE = os.path.join(ROOT, 'iss', 'tests', 'test_smoke.py')
# 清单 §2.2 的六个 CSR（顺序照清单）
G1I_CSRS = ('mtvec', 'mscratch', 'mepc', 'mcause', 'mtval', 'mstatus')
# 码名归一表（GI-5）：只做**规范通用缩写**替换，不猜语义；Reserved 行归一为空（不参与比对）
EXC_NAME_FIX = {'INSTRUCTION': 'INSTR', 'ADDRESS': 'ADDR', 'AMO': None}
# ISS `Intr` 成员名 → 规范名（缩写见 `spec/10` §3 优先级行与 §4.1 `mie`/`mideleg` 行，非自造）
INTR_ABBR = {'SSI': 'SUPERVISOR SOFTWARE INTERRUPT', 'STI': 'SUPERVISOR TIMER INTERRUPT',
             'SEI': 'SUPERVISOR EXTERNAL INTERRUPT', 'MSI': 'MACHINE SOFTWARE INTERRUPT',
             'MTI': 'MACHINE TIMER INTERRUPT', 'MEI': 'MACHINE EXTERNAL INTERRUPT',
             'LCOFI': 'COUNTER OVERFLOW INTERRUPT'}


def _doc_lines(path):
    return io.open(path, 'r', encoding='utf-8').read().splitlines()


def sec_slice(lines, pat, level=3):
    """取节区间 [start, end)（0-based）。标题未找到返回 None（调用方 FAIL，fail-closed）。

    `level`＝止步标题层级：默认 3（`####` 子标题不断节，止于 `#`~`###`）；取 `##` 级节（其下含
    `###` 子节，如 `spec/02` §9）时传 `level=2`。跨篇判据（CSR 表／isop 表／清单）共用。
    """
    start = None
    for i, ln in enumerate(lines):
        if re.match(pat, ln):
            start = i
            break
    if start is None:
        return None
    stop = r'^#{1,%d}\s' % level
    for j in range(start + 1, len(lines)):
        if re.match(stop, lines[j]):
            return start, j
    return start, len(lines)


def md_tables(lines, lo=0, hi=None):
    """解析 [lo, hi) 内的 markdown 表格 → [(表头行号, 表头单元格, [(行号, 单元格)])]（行号 1-based）。"""
    hi = len(lines) if hi is None else hi
    out, cur = [], None
    for i in range(lo, hi):
        s = lines[i].strip()
        if s.startswith('|') and s.endswith('|'):
            cells = [c.strip() for c in s.strip('|').split('|')]
            if cur is None:
                cur = [i + 1, cells, []]
            elif not set(s.replace('|', '').strip()) <= set('-: '):   # 跳过 `|---|` 分隔行
                cur[2].append((i + 1, cells))
        elif cur is not None:
            out.append(tuple(cur))
            cur = None
    if cur is not None:
        out.append(tuple(cur))
    return out


def ticks(cell):
    """单元格内反引号包的 token 列表（保序）。"""
    return [t.strip() for t in re.findall(r'`([^`]+)`', cell or '')]


def _iss_mod(name):
    """import `iss/vriss/<name>.py`（ISS 真源）；加载失败返回 None（调用方 FAIL，不另写副本）。"""
    p = os.path.join(ROOT, 'iss')
    if p not in sys.path:
        sys.path.insert(0, p)
    try:
        return __import__('vriss.' + name, fromlist=['*'])
    except Exception:                                              # noqa: BLE001
        return None


def _one_bit_run(v):
    """v 是否为「单段连续 1」（位段形态：某位置起 k 个连续 1，k≥1）——位段的机械判据。"""
    if v <= 0:
        return False
    t = v >> ((v & -v).bit_length() - 1)       # 右移到最低位 1 处（去前导偏移）
    return (t & (t + 1)) == 0                  # 2**k − 1


def chk_csr_table():
    """csr-table（GI-3／GI-4）：清单 §2.2 六个 CSR 在 `spec/10` §4.1 逐行在册，且地址与位段
    与 `iss/vriss/consts.py`（`Csr`／`MStatus`／`MTVEC_*`）逐值一致。

    判据面（逐条可核）：
      ①六个 CSR 各有一独立行（名在 CSR 列、地址列可解析）——缺行即 FAIL（GI-3）；
      ②每行「复位值／位段要点／WARL 可写／权限」四列非空（GI-3）；
      ③地址逐值：spec 行 == `Csr.<NAME>`（GI-4，不一致即列两侧值）；
      ④`mstatus` 位段（GI-4）：spec 行须命名 `MIE`/`MPIE`/`MPP`，ISS `MStatus` 须有同名成员，
         三掩码互不重叠、各自连续（`MPP` 2 bit＝`spec/01` §3.18 Q30「向 MPP 写 2'b10」；`MIE`/`MPIE` 各 1 bit）；
      ⑤`mtvec` MODE 逐值：spec「0 Direct／1 Vectored」== `MTVEC_DIRECT/VECTORED`（GI-4）。
    **只报不判**（spec 侧无对应数值锚，判据不替 spec 造值）：`mepc` bit0 恒 0／`mscratch` 全 64 位／
    `mtval` 取值口径——末项即清单 §4 `GI-6` 的材料缺（已登记待材料）。
    """
    if not os.path.exists(SPEC10):
        return False, '缺 %s（fail-closed）' % rel(SPEC10)
    lines = _doc_lines(SPEC10)
    sec = sec_slice(lines, r'^#{3}\s*4\.1\s')
    if sec is None:
        return False, '`spec/10` §4.1 标题未找到（fail-closed）'
    tabs = [t for t in md_tables(lines, *sec)
            if len(t[1]) >= 6 and t[1][0].replace('`', '') == 'CSR']
    if not tabs:
        return False, '`spec/10` §4.1 的 CSR 表未找到（fail-closed）'
    idx = {}
    for ln, cells in tabs[0][2]:
        for nm in ticks(cells[0]):
            idx.setdefault(nm, (ln, cells))
    consts = _iss_mod('consts')
    if consts is None:
        return False, 'ISS `iss/vriss/consts.py` 无法 import（fail-closed）'
    bad, seen = [], {}
    for name in G1I_CSRS:
        hit = idx.get(name)
        if hit is None:
            bad.append('`%s` 在 §4.1 表内无独立行' % name)
            continue
        ln, cells = hit
        if len(cells) < 7:
            bad.append('`%s`（L%d）列数 %d < 7' % (name, ln, len(cells)))
            continue
        for k, col in ((2, '复位值'), (3, '位段要点'), (4, 'WARL/可写'), (5, '权限')):
            if not strip_md(cells[k]):
                bad.append('`%s`（L%d）「%s」列空' % (name, ln, col))
        m = re.match(r'^0x([0-9A-Fa-f]+)$', strip_md(cells[1]))
        if not m:
            bad.append('`%s`（L%d）地址列不可解析：%r' % (name, ln, cells[1][:24]))
            continue
        spec_addr = int(m.group(1), 16)
        member = getattr(consts.Csr, name.upper(), None)
        if member is None:
            bad.append('`%s`：ISS `Csr` 无 %s 成员' % (name, name.upper()))
        elif int(member) != spec_addr:
            bad.append('`%s` 地址不一致：spec/10 §4.1 = 0x%x ≠ ISS Csr.%s = 0x%x'
                       % (name, spec_addr, name.upper(), int(member)))
        else:
            seen[name] = spec_addr
    # ④ mstatus 位段（spec 只有「名」，ISS 有「掩码」⇒ 名对齐 + 掩码结构与重叠可核）
    ms = getattr(consts, 'MStatus', None)
    masks = {}
    row = idx.get('mstatus')
    if row is not None and len(row[1]) >= 7:
        for f in ('MIE', 'MPIE', 'MPP'):
            if not re.search(r'\b%s\b' % f, row[1][3]):
                bad.append('`mstatus` 位段列未命名 %s（GI-4 要求 MIE/MPIE/MPP 在册）' % f)
            v = getattr(ms, f, None) if ms is not None else None
            if v is None:
                bad.append('ISS `MStatus` 无 %s 成员（fail-closed）' % f)
            else:
                masks[f] = int(v)
    for f, v in masks.items():
        if not _one_bit_run(v):
            bad.append('ISS `MStatus.%s` = %#x 非「连续 1 段」位段（fail-closed）' % (f, v))
    if len(masks) == 3:
        if len({masks['MIE'], masks['MPIE'], masks['MPP']}) != 3:
            bad.append('ISS `MStatus` MIE/MPIE/MPP 掩码重叠：%s'
                       % {f: hex(v) for f, v in masks.items()})
        if bin(masks['MPP']).count('1') != 2:
            bad.append('ISS `MStatus.MPP` = %#x 非 2 bit（`spec/01` §3.18 Q30：向 MPP 写 2\'b10）'
                       % masks['MPP'])
        for f in ('MIE', 'MPIE'):
            if bin(masks[f]).count('1') != 1:
                bad.append('ISS `MStatus.%s` = %#x 非 1 bit' % (f, masks[f]))
    # ⑤ mtvec MODE 逐值
    row = idx.get('mtvec')
    if row is not None and len(row[1]) >= 7:
        pairs = re.findall(r'(\d+)\s*(Direct|Vectored)', row[1][3])
        if not pairs:
            bad.append('`mtvec` 位段列未给出 MODE 值对（0 Direct／1 Vectored）⇒ 无法逐值核（fail-closed）')
        else:
            want = {'Direct': int(getattr(consts, 'MTVEC_DIRECT', -1)),
                    'Vectored': int(getattr(consts, 'MTVEC_VECTORED', -2))}
            for k, v in pairs:
                if want.get(v, -3) != int(k):
                    bad.append('`mtvec` MODE 不一致：spec = %s %s ≠ ISS MTVEC_%s = %s'
                               % (k, v, v.upper(), want.get(v)))
    if bad:
        return False, '%d 处：%s（清单 §2.2／§4 GI-3·GI-4）' % (len(bad), '；'.join(bad[:6]))
    shift = lambda v: (v & -v).bit_length() - 1      # 位段起始位（trailing zeros；2 bit 域不报顶位）
    return True, ('六 CSR 逐行在册（地址｜复位值｜位段｜WARL｜权限非空）；地址 == ISS `Csr` 逐值（%s）；'
                  '`mstatus` MIE/MPIE/MPP 名 + 掩码结构一致（%s）；`mtvec` MODE {0 Direct,1 Vectored} '
                  '== `MTVEC_*`；只报不判：`mepc` bit0=0／`mscratch` 全 64 位／`mtval` 口径（GI-6 待材料）'
                  % (','.join('%s=0x%x' % (k, v) for k, v in seen.items()),
                     ','.join('%s=%#x(shift%d,width%d)' % (f, masks[f], shift(masks[f]),
                                                          bin(masks[f]).count('1'))
                              for f in ('MIE', 'MPIE', 'MPP') if f in masks)))


def _canon_tokens(name):
    """码名归一（GI-5）：Reserved → 空表（不参与比对）；其余走 `EXC_NAME_FIX`＋`INTR_ABBR`。"""
    raw = (name or '').strip()
    if raw in INTR_ABBR:
        return INTR_ABBR[raw].split()
    t = re.sub(r'[^A-Z0-9]+', ' ', raw.upper()).split()
    if not t or t[0] == 'RESERVED':
        return []
    if t[:3] == ['ENVIRONMENT', 'CALL', 'FROM'] and len(t) >= 5:      # 「Environment call from U-mode」
        return ['ECALL', t[3][0]]
    out = []
    for x in t:
        fix = EXC_NAME_FIX.get(x, x)
        if fix is None:                                               # Store/AMO 的 AMO 词干归并
            continue
        out.append(fix)
    return out


def chk_code_table():
    """code-table（GI-5）：`spec/10` §2.1 的异常/中断码表 与 `iss/vriss/consts.py` 的
    `Exc`／`Intr` 逐值一致（只比两侧都出现的码；某侧独有者单列报告）。

    判据面：
      ①§2.1 两张码表存在，每行码单元格可解析（`N`／`N–M`／`≥N`）——解析不出即 FAIL（fail-closed）；
      ②逐行「本实现可产生」的 是/否 集合 == 同节「可产生集合（校正口径）」行声明的集合；
      ③两侧共有的码：§2.1 规范名 与 `Exc`/`Intr` 枚举名 归一后逐码一致；
      ④ISS 侧枚举值在 §2.1 无对应单码行 ⇒ FAIL（ISS 独有）；
      ⑤spec 侧 Reserved/范围/平台行为「单列报告」（不判红）；另报告「spec 标不可产生而 ISS 枚举在册」的码。
    """
    if not os.path.exists(SPEC10):
        return False, '缺 %s（fail-closed）' % rel(SPEC10)
    lines = _doc_lines(SPEC10)
    sec = sec_slice(lines, r'^#{3}\s*2\.1\s')
    if sec is None:
        return False, '`spec/10` §2.1 标题未找到（fail-closed）'
    sync = intr = None
    for t in md_tables(lines, *sec):
        hdr = [h.replace('`', '') for h in t[1]]
        if len(hdr) < 4 or '码' not in hdr[0] or '规范名' not in hdr[1] or '可产生' not in hdr[2]:
            continue
        if '产生点' in hdr[3]:
            sync = sync or t
        else:
            intr = intr or t
    if sync is None or intr is None:
        return False, ('`spec/10` §2.1 码表未找齐（同步 %s／中断 %s，fail-closed）'
                       % ('缺' if sync is None else '有', '缺' if intr is None else '有'))
    bad, notes = [], []

    def parse_rows(t, tag):
        rows, single = [], {}
        for ln, cells in t[2]:
            if len(cells) < 4:
                bad.append('%s码表 L%d 列数 %d < 4' % (tag, ln, len(cells)))
                continue
            raw = cells[0].replace('`', '').replace('*', '').strip()
            rec = dict(line=ln, raw=raw, name=strip_md(cells[1]),
                       mark=''.join(ch for ch in cells[2] if ch in '是否'))
            if re.match(r'^\d+$', raw):
                rec['code'] = int(raw)
                single[int(raw)] = rec
            elif re.match(r'^\d+\s*[–\-~]\s*\d+$', raw):
                a, b = [int(x) for x in re.findall(r'\d+', raw)]
                rec['codes'] = set(range(a, b + 1))
            elif re.match(r'^≥\s*\d+$', raw):
                rec['ge'] = int(re.findall(r'\d+', raw)[0])
            else:
                bad.append('%s码表 L%d 码单元格不可解析：%r' % (tag, ln, raw[:20]))
                continue
            rows.append(rec)
        return rows, single

    srows, ssing = parse_rows(sync, '同步')
    irows, ising = parse_rows(intr, '中断')
    decl = {}
    for i in range(sec[0], sec[1]):
        if '可产生集合' not in lines[i]:
            continue
        for tag, m in (('同步', re.search(r'同步[^＝]{0,24}＝\{([^}]*)\}', lines[i])),
                       ('中断', re.search(r'中断[^＝]{0,24}＝\{([^}]*)\}', lines[i]))):
            decl[tag] = set(int(x) for x in re.findall(r'\d+', m.group(1))) if m else None
        break
    for tag, rows in (('同步', srows), ('中断', irows)):
        if decl.get(tag) is None:
            bad.append('§2.1「可产生集合」行缺 %s 集合（fail-closed）' % tag)
            continue
        got = set()
        for r in rows:
            if r['mark'] == '是':
                got |= r.get('codes', set()) | ({r['code']} if 'code' in r else set())
        if got != decl[tag]:
            bad.append('%s可产生集合不一致：表内「是」= {%s} ≠ 声明 {%s}'
                       % (tag, ','.join(str(x) for x in sorted(got)),
                          ','.join(str(x) for x in sorted(decl[tag]))))
    consts = _iss_mod('consts')
    if consts is None:
        return False, 'ISS `iss/vriss/consts.py` 无法 import（fail-closed）'
    n_both, only, both_list = 0, [], []
    for tag, single, rows, enum in (('同步', ssing, srows, consts.Exc),
                                    ('中断', ising, irows, consts.Intr)):
        emap = {int(m): m.name for m in enum}
        for code, nm in sorted(emap.items()):
            rec = single.get(code)
            if rec is None:
                bad.append('%s码 %d（ISS `%s`）在 §2.1 无对应行（ISS 独有）' % (tag, code, nm))
                continue
            a, b = _canon_tokens(rec['name']), _canon_tokens(nm)
            if not a or not b:
                continue
            if a != b:
                bad.append('%s码 %d 名不一致：spec「%s」≠ ISS `%s`' % (tag, code, rec['name'], nm))
            else:
                n_both += 1
                both_list.append('%d=%s' % (code, nm))
        for code, rec in sorted(single.items()):
            if code not in emap and _canon_tokens(rec['name']):
                only.append('%s%d「%s」' % (tag, code, rec['name']))
        for r in rows:
            if r['mark'] == '否' and r.get('code') in emap:
                notes.append('%s码 %d（%s）spec 标「不可产生」而 ISS 枚举在册'
                             % (tag, r['code'], emap[r['code']]))
    if bad:
        return False, '%d 处：%s（清单 §4 GI-5）' % (len(bad), '；'.join(bad[:6]))
    msg = ('§2.1 同步 %d 行／中断 %d 行；两侧共有 %d 码名逐值一致（%s）；「是」集合 == 声明集合'
           % (len(srows), len(irows), n_both, ','.join(both_list[:8]) + ('…' if n_both > 8 else '')))
    if only:
        msg += '；spec 独有（单列，Reserved/范围行不参与比对）：%s' % '、'.join(only[:4])
    if notes:
        msg += '；两侧张力（spec §2.1／§3 已登记，不判红）：%s' % '；'.join(notes)
    return True, msg


def chk_gi_pkg_binding():
    """gi-pkg-binding（GI-2 正判据）：清单 §2 的 struct 名与 §2.5 的参数名，逐名在生成件里有对应声明。

    清单体例（排除符号）：§3「不在 G1-I 内」全节的 `*_t` 名 ＋ §2.1 计数注里的 5 型 = **排除集**；
    这些名字即使出现在清单表格里也应被忽略（不当作 G1-I 冻结面成员）。
    判定：①§2.1 表体 struct 名（减排除集）计数 == 标题声明项数（23）；②逐名在 `vr1_types.svh` 有
    `typedef … <name>;` 闭包 ＋ `<NAME>_W` localparam ＋ `spec/01 §3 L…` 块头；③§2.5 表体参数名在
    `vr1_params.svh` 有 `parameter … NAME =` 或 `// [非数值·登记] NAME =`。任一缺失即 FAIL（fail-closed）。
    负判据面（§3 延后类不得被实例化于 `rtl/`／`tb/`）待 RTL 落地后随 `rtl-*` 判据补（清单 §4 GI-2 后半）。
    """
    for p, tag in ((G1I_LIST, '清单'), (TYPES_SVH, '生成件'), (PARAMS_SVH, '生成件')):
        if not os.path.exists(p):
            return False, '缺 %s（%s，fail-closed）' % (rel(p), tag)
    lines = _doc_lines(G1I_LIST)
    sec21 = sec_slice(lines, r'^#{3}\s*2\.1\s')
    sec25 = sec_slice(lines, r'^#{3}\s*2\.5\s')
    sec3 = sec_slice(lines, r'^#{2}\s*3\.\s')
    if sec21 is None or sec25 is None or sec3 is None:
        return False, ('清单 §2.1／§2.5／§3 标题未找齐（%s/%s/%s，fail-closed）'
                       % (bool(sec21), bool(sec25), bool(sec3)))
    t_re = re.compile(r'^[a-z][a-z0-9_]*_t$')
    excl = set()
    for ln in lines[sec3[0]:sec3[1]]:
        excl |= {t for t in ticks(ln) if t_re.match(t)}
    tabs = [t for t in md_tables(lines, *sec21)
            if len(t[1]) >= 3 and t[1][0].replace('`', '').startswith('类别')]
    ptabs = [t for t in md_tables(lines, *sec25)
             if len(t[1]) >= 3 and t[1][0].replace('`', '').startswith('类别')]
    if not tabs or not ptabs:
        return False, '清单 §2.1／§2.5 表未找到（fail-closed）'
    m = re.search(r'（\s*(\d+)\s*项', lines[sec21[0]])
    if not m:
        return False, '清单 §2.1 标题未给出项数（fail-closed）'
    want_n = int(m.group(1))
    bad, structs, dropped = [], [], []
    for ln, cells in tabs[0][2]:
        nm = next((t for t in ticks(cells[1]) if t_re.match(t)), None)
        if nm is None:
            bad.append('§2.1 L%d 未取到 struct 名（fail-closed）：%s' % (ln, cells[1][:30]))
            continue
        if nm in excl:
            dropped.append(nm)                    # 清单体例：标「G1-I 不含」者忽略
            continue
        if nm in structs:
            bad.append('§2.1 struct 名重复：%s' % nm)
        structs.append(nm)
    if len(structs) != want_n:
        bad.append('§2.1 struct 计数 %d ≠ 标题声明 %d（排除集 %d 个：%s）'
                   % (len(structs), want_n, len(excl), '、'.join(sorted(excl)[:5])))
    pnames = []
    for ln, cells in ptabs[0][2]:
        for t in ticks(cells[1]):
            nm = t.split('=')[0].strip()
            if re.match(r'^[A-Z][A-Z0-9_]*$', nm) and nm not in pnames:
                pnames.append(nm)
    ttext = io.open(TYPES_SVH, 'r', encoding='utf-8').read()
    ptext = io.open(PARAMS_SVH, 'r', encoding='utf-8').read()
    blocks = set()                              # `// ---- spec/01 §3 L… \`name\`` 块头（逐行 match，不加 re.M）
    for ln in ttext.splitlines():
        mb = TYPE_BLOCK_RE.match(ln)
        if mb:
            blocks.add(mb.group(2))
    typedefs = set(re.findall(r'^\}\s*([A-Za-z_][A-Za-z0-9_]*);', ttext, re.M))
    typedefs |= set(re.findall(r'^typedef\s+\w+\s*\[[^\]]*\]\s+([A-Za-z_][A-Za-z0-9_]*);', ttext, re.M))
    ws = set(x + '_W' for x in
             re.findall(r'^localparam int unsigned ([A-Z][A-Z0-9_]*)_W\s*=', ttext, re.M))
    pdecl = set(re.findall(r'^parameter\b.*?\b([A-Za-z_][A-Za-z0-9_]*)\s*=', ptext, re.M))
    pdecl |= set(re.findall(r'^//\s*\[非数值·登记\]\s*([A-Za-z_][A-Za-z0-9_]*)\s*=', ptext, re.M))
    for nm in structs:
        miss = []
        if nm not in blocks:
            miss.append('块头')
        if nm not in typedefs:
            miss.append('typedef')
        if nm.upper() + '_W' not in ws:
            miss.append('%s_W' % nm.upper())
        if miss:
            bad.append('`%s` 在 %s 缺 %s' % (nm, rel(TYPES_SVH), '/'.join(miss)))
    miss_p = [nm for nm in pnames if nm not in pdecl]
    if miss_p:
        bad.append('%d 个参数名在 %s 无声明：%s'
                   % (len(miss_p), rel(PARAMS_SVH), '、'.join(miss_p[:6])))
    if bad:
        return False, '%d 处：%s（清单 §4 GI-2）' % (len(bad), '；'.join(bad[:6]))
    return True, ('§2.1 %d 型（声明 %d，排除集 %d 个已按清单体例忽略：%s）逐名有 typedef/_W/块头；'
                  '§2.5 %d 个参数名逐名有 parameter/登记声明'
                  % (len(structs), want_n, len(excl), '、'.join(sorted(excl)[:4]), len(pnames)))


def chk_isop_subset():
    """isop-subset（GI-8）：清单 §1.1 的 14 条 G1-I 指令，其 `isop` 与 `spec/02` §9.1/§9.3 在册值一致，
    且 `iss/vriss/encode.py` 的具名构造器与之一一对应（**同 (cls.g) 占位 ⇒ 同 opcode**）。

    判据面：
      ①§9.1 八张成员表逐行可解析（编码 + 成员名），每节行数 == 小节标题声明成员数、合计 == §9.2 的 87；
      ②位段规则（§9.3）：`isop = cls<<7 | g<<4 | m`，`(cls,g)` ∈ 该节 §9.3 占位表，组内 `m` 自 0 起连续；
      ③§9.3「例码核验（14/14）」行的 14 个值 == §9.1 表值（同篇两侧逐值）；
      ④§9.5 的 `cls` 值域 == `spec/01` §3.4 的 `cls` 值域（跨篇逐值）；
      ⑤G1-I 14 条：spec 侧在册 ＋ ISS 侧有具名构造器；实编字低 2 位 == 0b11（32 bit 指令）、
         opcode ∈ `encode.py` 的 `OP_*` 常量集；同占位成员编出的 opcode 必须相同。
    """
    for p in (SPEC02, G1I_LIST):
        if not os.path.exists(p):
            return False, '缺 %s（fail-closed）' % rel(p)
    bad = []
    lines = _doc_lines(SPEC02)
    sec = sec_slice(lines, r'^#{2}\s*9\.\s', level=2)      # §9 含 `### 9.1`/`#### 9.1.x` 子节
    if sec is None:
        return False, '`spec/02` §9 标题未找到（fail-closed）'
    subheads = [(i + 1, lines[i]) for i in range(sec[0], sec[1])
                if re.match(r'^#{4}\s*9\.1\.\d', lines[i])]
    tabs = [t for t in md_tables(lines, *sec)
            if len(t[1]) >= 3 and t[1][0].replace('`', '') == '编码']
    if not tabs or not subheads:
        return False, '`spec/02` §9.1 成员表/小节标题未找到（fail-closed）'
    place = {}
    for t in md_tables(lines, *sec):
        if not (len(t[1]) >= 3 and '小类' in t[1][0] and '占位' in t[1][1]):
            continue
        for ln, cells in t[2]:
            cells = (cells + ['', ''])[:3]
            key = cells[0].split('（')[0].strip()
            # `cls` 在 §9.3 表内写作 3 bit 二进制字面量（`010.g0`）⇒ 按 base=2 解析，与 isop[9:7] 同口径
            groups = [(int(a, 2), int(b)) for a, b in re.findall(r'(\d{3})\.g(\d)', cells[1])]
            if key:
                place[key] = groups
        break
    if not place:
        return False, '`spec/02` §9.3 的小类→占位表未找到（fail-closed）'
    members, g1i_isop = {}, {}
    for t in tabs:
        head = [h for h in subheads if h[0] < t[0]]
        if not head:
            bad.append('§9.1 表（L%d）上方无小节标题（fail-closed）' % t[0])
            continue
        sub = head[-1][1]
        key = re.sub(r'^#{4}\s*9\.1\.\d\s*', '', sub).split('（')[0].strip()
        grp = place.get(key)
        if grp is None:
            bad.append('§9.1 小节「%s」在 §9.3 占位表无对应行（fail-closed）' % key)
            continue
        m = re.search(r'(\d+)\s*成员', sub)          # 「（19 成员…）」「（OP-32，9 成员）」都取首个「N 成员」
        if not m:
            bad.append('§9.1 小节「%s」标题未声明成员数（fail-closed）' % key)
            continue
        rows = []
        for ln, cells in t[2]:
            code = cells[0].replace('`', '').strip()
            if not re.match(r'^0x[0-9A-Fa-f]{3}$', code):
                bad.append('§9.1「%s」L%d 编码不可解析：%r' % (key, ln, code[:16]))
                continue
            nm = next((x for x in ticks(cells[1]) if re.match(r'^[A-Z][A-Z0-9.]*$', x)), None)
            if nm is None:
                bad.append('§9.1「%s」L%d 成员名不可解析（fail-closed）' % (key, ln))
                continue
            rows.append((int(code, 16), nm, ln))
        if len(rows) != int(m.group(1)):
            bad.append('§9.1「%s」表体 %d 行 ≠ 标题声明 %d 成员' % (key, len(rows), int(m.group(1))))
        by_grp = {}
        for code, nm, ln in rows:
            cls, g, mm = (code >> 7) & 7, (code >> 4) & 7, code & 0xF
            if (cls, g) not in grp:
                bad.append('§9.1「%s」`%s`=0x%03x 的 (cls,g)=(%d,%d) 不在 §9.3 占位表' % (key, nm, code, cls, g))
            by_grp.setdefault((cls, g), []).append((mm, nm))
            if nm in members:
                bad.append('§9.1 成员名跨节重复：%s' % nm)
            members[nm] = code
            g1i_isop[nm] = (code, (cls, g))
        for (cls, g), lst in by_grp.items():
            ms = [x[0] for x in lst]
            if ms != list(range(len(ms))):
                bad.append('§9.1「%s」占位 (%d.%d) 组内 m = %s 非「自 0 起连续」'
                           % (key, cls, g, ms))
        for (cls, g) in grp:
            if (cls, g) not in by_grp:
                bad.append('§9.1「%s」占位 (%d.%d) 无成员行（§9.3 已列该占位）' % (key, cls, g))
    tot = len(members)
    if tot != 87:
        bad.append('§9.1 解析出 %d 个成员 ≠ §9.2 的 87（fail-closed）' % tot)
    # ③ §9.3 例码核验行（同篇两侧逐值）
    n_ex = 0
    for i in range(sec[0], sec[1]):
        if '例码核验' not in lines[i]:
            continue
        for nm, val in re.findall(r'([A-Z][A-Z0-9.]*)\s*＝\s*(0x[0-9A-Fa-f]{3})', lines[i]):
            n_ex += 1
            if nm not in members:
                bad.append('§9.3 例码核验引用的 `%s` 不在 §9.1 成员表内' % nm)
            elif members[nm] != int(val, 16):
                bad.append('§9.3 例码核验 `%s` = %s ≠ §9.1 表值 0x%03x' % (nm, val, members[nm]))
        break
    if n_ex != 14:
        bad.append('§9.3 例码核验行解析出 %d 项 ≠ 14（fail-closed）' % n_ex)
    # ④ cls 值域跨篇逐值（spec/01 §3.4 ↔ spec/02 §9.5）
    def cls_pairs(path, secpat):
        L = _doc_lines(path) if os.path.exists(path) else []
        s = sec_slice(L, secpat) if L else None
        if s is None:
            return None
        for t in md_tables(L, *s):
            for ln, cells in t[2]:
                if cells[0].replace('`', '') == 'cls' and len(cells) >= 3:
                    return [(int(a), b) for a, b in
                            re.findall(r'(\d{3})\s*([A-Za-z]+(?:/[A-Za-z]+)?)', cells[2])]
        return None
    ca, cb = cls_pairs(SPEC01, r'^#{3}\s*3\.4\s'), cls_pairs(SPEC02, r'^#{3}\s*9\.5\s')
    if not ca or not cb:
        bad.append('`cls` 值域行未取到（spec/01 §3.4=%s／spec/02 §9.5=%s）⇒ fail-closed'
                   % (bool(ca), bool(cb)))
    elif ca != cb:
        bad.append('`cls` 值域不一致：spec/01 §3.4 %s ≠ spec/02 §9.5 %s' % (ca, cb))
    # ⑤ G1-I 子集 ↔ ISS 构造器（清单 §1.1 的 14 条）
    g1 = _doc_lines(G1I_LIST)
    s11 = sec_slice(g1, r'^#{3}\s*1\.1\s')
    if s11 is None:
        return False, '清单 §1.1 标题未找到（fail-closed）'
    want14, g1i = None, []
    for t in md_tables(g1, *s11):
        for ln, cells in t[2]:
            if '指令' not in cells[1]:
                continue
            mm = re.search(r'指令\s*\*{0,2}\s*(\d+)\s*条', cells[1])
            if mm:
                want14 = int(mm.group(1))
                g1i = [x for x in ticks(cells[1]) if re.match(r'^[A-Z][A-Z0-9.]*$', x)]
                break
        if want14 is not None:
            break
    if want14 is None or not g1i:
        return False, '清单 §1.1 的指令子集未解析出（fail-closed）'
    if len(g1i) != want14:
        bad.append('清单 §1.1 指令数 %d ≠ 声明 %d' % (len(g1i), want14))
    enc = _iss_mod('encode')
    if enc is None:
        return False, 'ISS `iss/vriss/encode.py` 无法 import（fail-closed）'
    import inspect as _inspect
    arg = {'rd': 1, 'rs1': 2, 'rs2': 3, 'sh': 4, 'imm': 4, 'off': 4, 'imm20': 4, 'uimm': 4,
           'csr': 0x305, 'funct3': 0, 'funct5': 0, 'funct7': 0}
    opcodes = set(v for k, v in vars(enc).items()
                  if re.match(r'^OP_[A-Z0-9_]+$', k) and isinstance(v, int))
    words, n_miss = {}, []
    for nm in g1i:
        if nm not in members:
            bad.append('G1-I 指令 `%s` 在 spec/02 §9.1 成员表内无编码（spec 侧缺）' % nm)
            continue
        fn = getattr(enc, nm.replace('.', '_'), None)
        if fn is None or not callable(fn):
            n_miss.append('%s（ISS 无具名构造器）' % nm)
            continue
        try:
            kw = {}
            for pn in _inspect.signature(fn).parameters:
                if pn not in arg:
                    raise KeyError(pn)
                kw[pn] = arg[pn]
            w = int(fn(**kw))
        except KeyError as e:
            n_miss.append('%s（构造器参数 %s 不在可填充表）' % (nm, e.args[0]))
            continue
        except Exception as e:                                     # noqa: BLE001
            n_miss.append('%s（构造器调用异常 %s）' % (nm, e))
            continue
        words[nm] = w
        if (w & 3) != 3:
            bad.append('`%s` 实编字 %#x 低 2 位 ≠ 0b11（非 32 bit 指令）' % (nm, w))
        if (w & 0x7F) not in opcodes:
            bad.append('`%s` 实编 opcode 0x%02x 不在 encode.py 的 OP_* 常量集' % (nm, w & 0x7F))
    if n_miss:
        bad.append('G1-I 指令在 ISS 侧不可编：%s' % '；'.join(n_miss))
    by_g = {}
    for nm in g1i:
        if nm in words and nm in g1i_isop:
            by_g.setdefault(g1i_isop[nm][1], []).append(nm)
    same = []
    for g, mns in sorted(by_g.items()):
        ops = {words[x] & 0x7F for x in mns}
        if len(ops) > 1:
            bad.append('同占位 (%d.%d) 的成员编出不同 opcode：%s'
                       % (g[0], g[1], {x: hex(words[x] & 0x7F) for x in mns}))
        else:
            same.append('%d.%d:%s→0x%02x' % (g[0], g[1], '/'.join(mns), list(ops)[0]))
    if bad:
        return False, '%d 处：%s（清单 §4 GI-8）' % (len(bad), '；'.join(bad[:6]))
    return True, ('§9.1 %d 成员／8 节计数与位段规则（cls<<7|g<<4|m）全过；§9.3 例码核验 14/14 逐值一致；'
                  '§9.5 `cls` 值域 == spec/01 §3.4；G1-I %d 条：spec 在册 + ISS 构造器可编，'
                  '同占位 opcode 一致（%s）'
                  % (tot, len(words), '；'.join(same[:5])))


def chk_iss_smoke():
    """iss-smoke（GI-7）：跑 `python iss/tests/test_smoke.py`，退出码 0 且末行 `[PASS]`（断言在环）。

    ISS 侧行为断言（30 条退休／寄存器期望／trap 的 `cause`+`mtval`+`mepc`／`mstatus.MPP` 归底／
    CSV 表头 == `TRACE_CSV_FIELDS`／`CSRRW`·`CSRRS` 的 CSR 写面）由该测试自证；本判据只认
    **退出码 + 证据行**（红线 R8），整段输出落 `sim/run_iss_smoke/run.log` 供回溯。
    """
    if not os.path.exists(ISS_SMOKE):
        return False, '缺 %s（fail-closed）' % rel(ISS_SMOKE)
    d = os.path.join(ROOT, 'sim', 'run_iss_smoke')
    os.makedirs(d, exist_ok=True)
    try:
        rc, o = run([sys.executable, rel(ISS_SMOKE)], timeout=300)
    except subprocess.TimeoutExpired:
        return False, '`iss/tests/test_smoke.py` 超时（>300s）'
    log = os.path.join(d, 'run.log')
    with open(log, 'w', encoding='utf-8', newline='\n') as f:
        f.write('$ python %s\n%s' % (rel(ISS_SMOKE), o))
    if rc != 0:
        return False, '退出码 %d（%s）｜%s' % (rc, rel(log), last_line(o)[:110])
    if '[PASS]' not in (o or ''):
        return False, '未见 `[PASS]` 证据行（fail-closed）｜%s' % rel(log)
    smoke = [ln.strip() for ln in o.splitlines() if ln.strip().startswith('[smoke]')]
    return True, '%s ｜ 退出码 0 ｜ %s' % (rel(log), (smoke[0] if smoke else last_line(o))[:120])


# DUT 编译清单（`rtl-compile` 的唯一编译集合来源；G1-I 冻签后 rtl/ 进实现期）
RTL_F = os.path.join(ROOT, 'filelist', 'rtl.f')


def _parse_f_list(path):
    """解析 vlog `-f` 清单：返回 (编译单元列表, incdir 列表)；**不做路径猜测**（fail-closed）。

    · 空行与 `//`／`#` 注释行忽略；`+incdir+<p>` 收进 incdir；`+<其它>` 开关忽略（不计单元）；
    · 其余按空白切分（一行可写多个单元）；相对路径按**仓库根**解析（与 filelist/tb.f 表头口径一致）。
    """
    units, incs = [], []
    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('//') or line.startswith('#'):
                continue
            for tok in line.split():
                if tok.startswith('+incdir+'):
                    incs.append(tok[len('+incdir+'):])
                elif not tok.startswith('+'):
                    units.append(tok)
    return units, incs


def chk_rtl_compile():
    """rtl-compile（M1 exit 之一；GI-14）：**真实 vlog 编译 `filelist/rtl.f`**（G1-I 冻签后登记）。

    判据（红线 R8：只认证据行，不看"没报错"）：
      ① vlog 段末自报 `Errors: 0`；
      ② `-- Compiling` 计数 == `filelist/rtl.f` 的**编译单元条目数**（少编/多编都不算过，fail-closed）；
      ③ vlog 退出码 0。
    编译单元清单的**唯一来源＝`filelist/rtl.f`**（本函数不硬编码文件表）；命令里把仓库根相对路径
    展开成绝对路径，只为与沙箱 cwd（`sim/run_rtl_compile/`，红线 R10 独占）解耦，**不改编译集合**。
    本判据**不涉 license**（vlog 编译不需要 license；vsim 侧由 `_msim()` 注入＝R-224）⇒ 与
    `rtl-vs-iss` 的阻塞面不同档。
    """
    if not os.path.exists(RTL_F):
        return False, '缺 %s（fail-closed：G1-I 冻签后 DUT 编译清单应在册）' % rel(RTL_F)
    units, incs = _parse_f_list(RTL_F)
    if not units:
        return False, '%s 无编译单元条目（fail-closed）' % rel(RTL_F)
    if not incs:
        return False, ('%s 无 `+incdir+` 行（参数件/类型件的 `include 会找不到；fail-closed）'
                       % rel(RTL_F))
    if not os.path.exists(VLOG):
        return False, 'vlog 不存在：%s' % VLOG
    d = os.path.join(ROOT, 'sim', 'run_rtl_compile')
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'run.log'), 'w', encoding='utf-8').close()
    args = [VLOG, '-64', '-sv', '-work', 'work']
    args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    text, rc = _msim(d, [[VLIB, 'work'], args], 'vlog')
    n_err = re.findall(r'Errors:\s*(\d+)', text)
    n_comp = len(re.findall(r'^-- Compiling', text, re.M))
    if not n_err:
        return False, '编译日志无 `Errors: N`（fail-closed）→ %s' % rel(os.path.join(d, 'run.log'))
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(os.path.join(d, 'run.log')))
    if n_comp != len(units):
        return False, ('`-- Compiling` 计数 %d ≠ filelist/rtl.f 条目数 %d（少编/多编都不算过；'
                       'fail-closed）→ %s' % (n_comp, len(units), rel(os.path.join(d, 'run.log'))))
    if rc != 0:
        return False, 'vlog 退出码 %d → %s' % (rc, rel(os.path.join(d, 'run.log')))
    return True, 'vlog 编译 %d 个单元（filelist/rtl.f）｜ Errors: 0 ｜ %s' % (
        n_comp, rel(os.path.join(d, 'run.log')))


def chk_rtl_vs_iss():
    """rtl-vs-iss（M1 exit 之一；GI-14）：**真跑 M1 端到端并逐指令比对**（2026-09-26 真实化）。

    判据（红线 R8：只认证据行与退出码；**不猜、不放宽**）：
      ① 同批编译 `filelist/rtl.f` ＋ `filelist/tb_m1_e2e.f`：`-- Compiling` 计数 == 两清单条目数之和、
         各段 `Errors: 0`、退出码 0；`vopt`/`vsim` 同款（vsim 涉 license，见下"分档"）；
      ② `vsim` 证据行：`HALT_PASS`（riscv-tests `tohost` 写 1）＋ `CLOSE … rows=<golden 行数>`；
         **无** `HALT_FAIL`／`WATCHDOG_TIMEOUT`（红线 R9 的 watchdog 未触发 = 未挂死）；
      ③ **比对**：`python iss/tools/trace_compare.py sim/golden/iss_smoke.csv <沙箱>/rtl_side.csv`
         退出码 0 **且**输出含 `mismatch=0` ⇒ 长度相等 ∧ 列 `pc,binary,gpr,csr` 逐条 0 mismatch
         （`trace_compare.py` 的 `DEFAULT_COLS`；**不开** `--final-only`／`--with-asm`／`--cols`——
         任何放宽须白名单＋登记，红线 R6）。

    为什么不进常跑守卫：本判据要 vlog＋vopt＋vsim（vsim 涉 ModelSim license，ISS-104 抖动会把产品面
    误报成 ENV-BLOCKED ⇒ 不进 GUARDS；M1 的 exit 本就是"贵判据"）。消息里不写 `ENV-BLOCKED` 字样
    （license 抖动由 `_msim` 注入两份 license 路径缓解，R-224；工具缺件属 fail-closed 的 FAIL）。
    """
    for p in (RTL_F, TB_M1_E2E_F, IMAGE_HEX, GOLDEN, TRACE_COMPARE):
        if not os.path.exists(p):
            return False, '缺 %s（fail-closed）' % rel(p)
    rtl_units, rtl_incs = _parse_f_list(RTL_F)
    tb_units, tb_incs = _parse_f_list(TB_M1_E2E_F)
    if not rtl_units or not tb_units:
        return False, '编译清单条目为空（%s / %s；fail-closed）' % (rel(RTL_F), rel(TB_M1_E2E_F))
    units = rtl_units + tb_units
    incs = list(dict.fromkeys(rtl_incs + tb_incs))
    if not incs:
        return False, '两份清单均无 `+incdir+` 行（生成件的 `include 会找不到；fail-closed）'
    gold = _golden_pc_binary(GOLDEN)
    if not gold:
        return False, 'golden 的 `pc→binary` 不可用（fail-closed）→ %s' % rel(GOLDEN)
    if not (os.path.exists(VLOG) and os.path.exists(VOPT) and os.path.exists(VSIM)):
        return False, 'ModelSim 工具缺件（vlog/vopt/vsim）：%s' % MTI
    d = os.path.join(ROOT, 'sim', 'run_rtl_vs_iss')                      # 沙箱独占（红线 R10）
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, 'run.log')
    open(log, 'w', encoding='utf-8').close()
    csv_rtl = os.path.join(d, 'rtl_side.csv')
    if os.path.exists(csv_rtl):
        os.remove(csv_rtl)                                               # 防"用上次的 CSV 交差"
    vlog_args = [VLOG, '-64', '-sv', '-work', 'work']
    vlog_args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    vlog_args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    t_c, rc_c = _msim(d, [[VLIB, 'work'], vlog_args], 'vlog')
    if rc_c != 0:
        return False, 'vlog 退出码 %d → %s' % (rc_c, rel(log))
    n_err = re.findall(r'Errors:\s*(\d+)', t_c)
    n_comp = len(re.findall(r'^-- Compiling', t_c, re.M))
    if not n_err:
        return False, 'vlog 段无 `Errors: N` 证据行（fail-closed）→ %s' % rel(log)
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(log))
    if n_comp != len(units):
        return False, ('`-- Compiling` 计数 %d ≠ rtl.f+tb_m1_e2e.f 条目数 %d（少编/多编都不算过；'
                       'fail-closed）→ %s' % (n_comp, len(units), rel(log)))
    t_o, rc_o = _msim(d, [[VOPT, '-64', 'work.m1_e2e_tb', '-o', 'e2e_opt']], 'vopt')
    if rc_o != 0:
        return False, 'vopt（m1_e2e_tb）退出码 %d → %s' % (rc_o, rel(log))
    n_o = re.findall(r'Errors:\s*(\d+)', t_o)
    if not n_o or int(n_o[-1]) != 0:
        return False, 'vopt 段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_o[-1] if n_o else '?', rel(log))
    t_s, rc_s = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'e2e_opt',
                           '+IMAGE=%s' % IMAGE_HEX.replace('\\', '/'),
                           '+RT_T_CSV=%s' % csv_rtl.replace('\\', '/')]], 'vsim')
    if rc_s != 0:
        return False, 'vsim（m1_e2e_tb）退出码 %d → %s' % (rc_s, rel(log))
    bad_s = [ln.strip() for ln in t_s.splitlines()
             if 'HALT_FAIL' in ln or 'WATCHDOG_TIMEOUT' in ln]
    if bad_s:
        return False, '端到端自报失败（tohost 非 1 或 watchdog 超时）：%s ｜ %s' % (
            bad_s[0][:120], rel(log))
    mh = RE_E2E_HALT.search(t_s)
    if not mh:
        return False, '未见 `HALT_PASS … rows=…` 证据行（tohost 停机判据未命中；fail-closed）→ %s' % rel(log)
    rows_hw = int(mh.group(1))
    if rows_hw != len(gold):
        return False, ('写出器自报 rows=%d ≠ golden 行数 %d（长度不等；fail-closed）→ %s'
                       % (rows_hw, len(gold), rel(log)))
    if not os.path.exists(csv_rtl):
        return False, 'RTL 侧 CSV 未落盘（fail-closed）→ %s' % csv_rtl.replace('\\', '/')
    try:
        rc_cmp, o_cmp = run([sys.executable, rel(TRACE_COMPARE), rel(GOLDEN), csv_rtl], timeout=300)
    except subprocess.TimeoutExpired:
        return False, '`trace_compare` 超时（>300s）'
    with open(log, 'a', encoding='utf-8', newline='\n') as f:
        f.write('\n[trace_compare]\n$ python %s %s %s\n%s' % (
            rel(TRACE_COMPARE), rel(GOLDEN), csv_rtl, o_cmp))
    if rc_cmp != 0:
        return False, '`trace_compare` 退出码 %d（长度不等或存在 mismatch）｜%s ｜ %s' % (
            rc_cmp, last_line(o_cmp)[:120], rel(log))
    if 'mismatch=0' not in (o_cmp or ''):
        return False, '比对输出未见 `mismatch=0`（fail-closed）｜%s' % rel(log)
    return True, ('M1 闭环：RTL 侧 %d 条退休（tohost 停机 PASS）vs golden %d 条，'
                  '列 `pc,binary,gpr,csr` **0 mismatch**（`trace_compare` 退出码 0）｜'
                  'vlog %d 单元／vopt／vsim 逐段 Errors: 0 ｜ %s'
                  % (rows_hw, len(gold), n_comp, rel(log)))


# M1 端到端冒烟的 TB 侧编译清单（`rtl-vs-iss` 的唯一编译集合来源之二；与 `filelist/rtl.f` 同批）
TB_M1_E2E_F = os.path.join(ROOT, 'filelist', 'tb_m1_e2e.f')
# 该 TB 的源文（判据②的单源防漂移面：数据窗常量 `DRAM_BASE`／`DMEM_WORDS` 从源文机械读回）
TB_M1_E2E_SV = os.path.join(ROOT, 'tb', 'unit', 'm1_e2e_tb.sv')
# `rtl-vs-iss` 的证据行正则：写出器的停机证据行 `HALT_PASS … rows=<n>`
RE_E2E_HALT = re.compile(r'HALT_PASS\s+tohost=\S+\s+val=\S+\s+rows=(\d+)')
# RTL-vs-ISS 比对器（`iss/tools/trace_compare.py`；列集 `DEFAULT_COLS` 由该工具自身定死）
TRACE_COMPARE = os.path.join(ROOT, 'iss', 'tools', 'trace_compare.py')


# --------------------------------------------------------------------------- #
# M2 exit (a)：riscv-tests rv64ui 定向子集（真跑 ISS ＋ RTL ＋ 逐条比对）
#
# 里程碑口径（R0 2026-09-26 心跳批）：`rv64ui` 定向子集 **≥5 条** RTL 侧全 PASS
#   ＋ 逐条 RTL-vs-ISS trace 0 mismatch。镜像与清单由 `sw/tests/build_rv64ui.py` 产（构建侧），
#   本判据负责**跑**（ISS 侧＋RTL 侧＋比对）——判据与生产分离，禁用"上次的 CSV 交差"。
# --------------------------------------------------------------------------- #
RV64UI_DIR = os.path.join(ROOT, 'sim', 'image', 'rv64ui')
RV64UI_MANIFEST = os.path.join(RV64UI_DIR, 'MANIFEST.json')
M2_MIN_TESTS = 5                       # M2 exit (a) 的条数口径（≥5，不放宽）
RV64UI_TOHOST = 0x4000_0010            # 与 TB `TOHOST_ADDR`／`iss/tests/test_smoke.py:TOHOST` 同值


def chk_m2_rv64ui():
    """m2-rv64ui（M2 exit (a)）：riscv-tests `rv64ui` 定向子集 ≥5 条**真跑**并逐条比对。

    判据（红线 R6/R8：只认证据行与退出码，**不放宽、不豁免**）：
      ① `sim/image/rv64ui/MANIFEST.json` 在册且可解析；逐条 `hex_md5`／`tb_hex_md5`／`data_hex_md5`
         **复算一致**（三视图未漂移；md5 复算＝"一份镜像喂两边"的机判面）；
      ② **数据面等价性**（前置不变式，fail-closed）：每条的 `data_hex` 在册＋md5 复算一致（数据视图
         ＝该条 ELF 的数据段字、落 TB 数据窗内）；`n_words_data_outside_tb_win == 0`（有数据字落在
         TB 数据窗外 ⇒ 该条**不可在本 TB 上判**，报 FAIL 并指名，不静默跳过）；且 MANIFEST 声明的
         数据窗与 `tb/unit/m1_e2e_tb.sv` 的 `DRAM_BASE`／`DMEM_WORDS` **逐字一致**（单源防漂移）。
         **口径变更记录（2026-09-26 心跳第 6 轮；ledger ISS-126 机制件）**：本项原式为「`data_words_all_zero`
         必须为真」——那是"TB 数据桩恒零填充 ≡ 镜像"的**代理条件**。TB 加 `+DATA=` 预载（`$readmemh`
         第二份镜像）后，等价性改由"数据窗内容 ＝ 镜像数据段"**直接**保证（`data.hex` 与镜像同源、
         md5 复算、逐条喂 `vsim`）⇒ 代理条件由其真身取代。**不是放宽**：比对列、`--final-only` 政策、
         条数阈值（`M2_MIN_TESTS`）与 `trace_compare` 本体一律未动；对新式更严（旧式对 `.data` 非全 0
         的测试只能整条拒判，新式照判且要求 md5/窗口逐条相符）。
      ③ 同批编译 `filelist/rtl.f` ＋ `filelist/tb_m1_e2e.f`：`-- Compiling` 计数 == 两清单条目数之和、
         各段 `Errors: 0`、退出码 0；`vopt` 同款（与 `rtl-vs-iss` 同一口径与同一编译集合）；
      ④ 逐条：
         · ISS 侧：`python iss/run_iss.py run --hex <hex> --tohost 0x4000_0010` 退出码 0
           ⇒ 已停机 且 `halt_val==1`（riscv-tests PASS 语义）；
         · RTL 侧：`vsim m1_e2e_tb +IMAGE=<tb_hex> +DATA=<data_hex> +RT_T_CSV=<沙箱>/<name>.rtl.csv`，
           **无** `HALT_FAIL`／`WATCHDOG_TIMEOUT`，且 `HALT_PASS … rows=` == ISS 侧行数（长度相等）；
         · 比对：`trace_compare <iss.csv> <rtl.csv>` 退出码 0 **且**输出含 `mismatch=0`
           （列 `pc,binary,gpr,csr`；**不开** `--final-only`／`--cols`，红线 R6）；
      ⑤ 通过条数 ≥ `M2_MIN_TESTS` 且失败条数 == 0 ⇒ PASS；否则 FAIL 并点名首条失败原因
         （不足条数也 FAIL——"跑了 2 条全过"不等于"≥5 条全过"）。

    为什么不进常跑守卫：本判据要 vlog＋vopt＋**逐条 vsim**（vsim 涉 ModelSim license，ISS-104 抖动
    会把产品面误报成 ENV-BLOCKED ⇒ 不入 GUARDS；M2 的 exit 本就是"贵判据"）。
    """
    if not os.path.exists(RV64UI_MANIFEST):
        return False, ('缺 %s（fail-closed）；先跑 `python sw/tests/build_rv64ui.py`'
                       % rel(RV64UI_MANIFEST))
    man = load_json(RV64UI_MANIFEST) or {}
    tests = man.get('tests') or []
    if not tests:
        return False, 'MANIFEST.tests 为空（fail-closed）→ %s' % rel(RV64UI_MANIFEST)
    if int((man.get('abi') or {}).get('tohost', -1)) != RV64UI_TOHOST:
        return False, ('MANIFEST.abi.tohost ≠ 0x%x（与 TB `TOHOST_ADDR` 口径不符；fail-closed）→ %s'
                       % (RV64UI_TOHOST, rel(RV64UI_MANIFEST)))
    iss_run = os.path.join(ROOT, 'iss', 'run_iss.py')
    for p in (RTL_F, TB_M1_E2E_F, TB_M1_E2E_SV, TRACE_COMPARE, iss_run):
        if not os.path.exists(p):
            return False, '缺 %s（fail-closed）' % rel(p)

    # ---- ①/② 镜像面复核（纯文件、fail-closed）----
    #   ② 单源防漂移：MANIFEST 声明的数据窗必须与 TB 源文里的 `DRAM_BASE`／`DMEM_WORDS` 逐字一致
    #   （TB 窗变小而 MANIFEST 仍声明大窗 ⇒ 数据视图会被 `$readmemh` 静默截断，属"假等价"）。
    tb_src = ''
    if os.path.exists(TB_M1_E2E_SV):
        with open(TB_M1_E2E_SV, 'r', encoding='utf-8', errors='replace') as f:
            tb_src = f.read()
    m_base = re.search(r"DRAM_BASE\s*=\s*40'h([0-9A-Fa-f_]+)", tb_src)
    m_words = re.search(r'DMEM_WORDS\s*=\s*(\d+)', tb_src)
    win = (man.get('abi') or {}).get('data_window') or []
    win_consts = (man.get('abi') or {}).get('tb_data_window_consts') or {}
    if not m_base or not m_words:
        return False, ('TB 数据窗常量在 %s 中不可解析（`DRAM_BASE`＝40\'h… ／ `DMEM_WORDS`＝数字；'
                       'fail-closed）' % rel(TB_M1_E2E_SV))
    tb_base = int(m_base.group(1).replace('_', ''), 16)
    tb_words = int(m_words.group(1))
    if len(win) != 2 or int(win[0]) != tb_base or int(win[1]) != tb_words * 4:
        return False, ('MANIFEST 数据窗 %s ≠ TB 源文常量（base=0x%x words=%d ⇒ %d B）；'
                       'fail-closed（单源漂移）→ %s'
                       % (win or '?', tb_base, tb_words, tb_words * 4, rel(TB_M1_E2E_SV)))
    if int(win_consts.get('DRAM_BASE', -1)) != tb_base or int(win_consts.get('DMEM_WORDS', -1)) != tb_words:
        return False, ('MANIFEST.tb_data_window_consts %s ≠ TB 源文常量（base=0x%x words=%d）；'
                       'fail-closed（单源漂移；重跑 build_rv64ui.py）'
                       % (win_consts or '?', tb_base, tb_words))
    for t in tests:
        for key in ('name', 'hex', 'tb_hex', 'hex_md5', 'tb_hex_md5',
                    'data_hex', 'data_hex_md5'):
            if not t.get(key):
                return False, 'MANIFEST 条目缺 `%s`（fail-closed）：%s' % (key, t.get('name', '?'))
        for key in ('hex', 'tb_hex', 'data_hex'):
            p = os.path.join(ROOT, t[key])
            if not os.path.exists(p):
                return False, '条目 %s 的 %s 不存在（fail-closed）' % (t['name'], t[key])
            got = md5_of(p)
            if got != t[key + '_md5']:
                return False, ('%s 镜像漂移：%s md5=%s ≠ MANIFEST %s（重跑 build_rv64ui.py；'
                               'fail-closed）' % (t['name'], t[key], got[:12], t[key + '_md5'][:12]))
        if 'n_words_data_outside_tb_win' not in t:
            return False, ('%s 条目缺 `n_words_data_outside_tb_win`（旧 MANIFEST 格式；'
                           '重跑 build_rv64ui.py；fail-closed）' % t['name'])
        if int(t['n_words_data_outside_tb_win']) != 0:
            return False, ('%s 有 %s 个数据字落在 TB 数据窗外（无承载）⇒ TB 与镜像**不等价**，'
                           '该条不可在本 TB 上判（fail-closed，不静默跳过）'
                           % (t['name'], t['n_words_data_outside_tb_win']))

    # ---- ③ 编译在环（与 rtl-vs-iss 同集合、同口径）----
    if not (os.path.exists(VLOG) and os.path.exists(VOPT) and os.path.exists(VSIM)):
        return False, 'ModelSim 工具缺件（vlog/vopt/vsim）：%s' % MTI
    rtl_units, rtl_incs = _parse_f_list(RTL_F)
    tb_units, tb_incs = _parse_f_list(TB_M1_E2E_F)
    units = rtl_units + tb_units
    incs = list(dict.fromkeys(rtl_incs + tb_incs))
    if not units or not incs:
        return False, '编译清单条目/incdir 为空（fail-closed）'
    d = os.path.join(ROOT, 'sim', 'run_m2_rv64ui')                     # 沙箱独占（红线 R10）
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, 'run.log')
    open(log, 'w', encoding='utf-8').close()
    vlog_args = [VLOG, '-64', '-sv', '-work', 'work']
    vlog_args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    vlog_args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    t_c, rc_c = _msim(d, [[VLIB, 'work'], vlog_args], 'vlog')
    if rc_c != 0:
        return False, 'vlog 退出码 %d → %s' % (rc_c, rel(log))
    n_err = re.findall(r'Errors:\s*(\d+)', t_c)
    n_comp = len(re.findall(r'^-- Compiling', t_c, re.M))
    if not n_err or int(n_err[-1]) != 0:
        return False, 'vlog 段 `Errors: %s`（expect 0；fail-closed）→ %s' % (n_err[-1:] or '?', rel(log))
    if n_comp != len(units):
        return False, '`-- Compiling` 计数 %d ≠ 清单条目数 %d（fail-closed）→ %s' % (
            n_comp, len(units), rel(log))
    t_o, rc_o = _msim(d, [[VOPT, '-64', 'work.m1_e2e_tb', '-o', 'rv64ui_opt']], 'vopt')
    n_o = re.findall(r'Errors:\s*(\d+)', t_o)
    if rc_o != 0 or not n_o or int(n_o[-1]) != 0:
        return False, 'vopt 退出码 %d／`Errors: %s`（expect 0；fail-closed）→ %s' % (
            rc_o, n_o[-1] if n_o else '?', rel(log))

    # ---- ④ 逐条真跑（ISS ＋ RTL ＋ 比对）----
    n_pass, fails = 0, []
    with open(log, 'a', encoding='utf-8', newline='\n') as f:
        f.write('\n[m2-rv64ui] 编译 %d 单元；逐条跑 %d 条（%s）\n'
                % (n_comp, len(tests), ', '.join(t['name'] for t in tests)))
    for t in tests:
        name = t['name']
        iss_csv = os.path.join(d, '%s.iss.csv' % name)
        rtl_csv = os.path.join(d, '%s.rtl.csv' % name)
        for p in (iss_csv, rtl_csv):
            if os.path.exists(p):
                os.remove(p)                                    # 防"用上次的 CSV 交差"
        hexp = os.path.join(ROOT, t['hex']).replace('\\', '/')
        tbhexp = os.path.join(ROOT, t['tb_hex']).replace('\\', '/')
        datahexp = os.path.join(ROOT, t['data_hex']).replace('\\', '/')
        note = []
        try:
            rc_i, o_i = run([sys.executable, rel(iss_run), 'run', '--hex', t['hex'],
                             '--csv', rel(iss_csv), '--tohost', '0x%x' % RV64UI_TOHOST], timeout=600)
        except subprocess.TimeoutExpired:
            fails.append('%s：ISS 运行超时（>600s）' % name)
            continue
        note.append('$ python %s run --hex %s --csv %s --tohost 0x%x\n%s'
                    % (rel(iss_run), t['hex'], rel(iss_csv), RV64UI_TOHOST, o_i))
        if rc_i != 0 or 'halt_val=0x1' not in (o_i or ''):
            fails.append('%s：ISS 侧未 PASS（退出码 %d；%s）——镜像/测试自身或 ISS 缺陷，先归因'
                         % (name, rc_i, last_line(o_i)[:100]))
            with open(log, 'a', encoding='utf-8', newline='\n') as f:
                f.write('\n[%s ISS]\n%s\n' % (name, '\n'.join(note)))
            continue
        # 长度预检：`ISS 侧行数`（**逐条退休记录条数**，与 `trace_compare.py:77` 的长度判据同源）。
        # 缺陷与修法（2026-09-26 心跳第 5 轮，登记 `doc/process/ledger.json`；依规则 2「checker 自身
        #   错误」＝直接解决＋登记 / 规则 4 问题闭环）：此处原为 `len(_golden_pc_binary(iss_csv))`，
        #   而 `_golden_pc_binary` 返回的是 **`{pc: binary}` 映射**，其 `len()` 是**互异 pc 数**——
        #   与判据 docstring 第 ④ 条「`HALT_PASS … rows=` == **ISS 侧行数**」不是同一量。含循环的
        #   测试（riscv-tests 必有）会被误判为"长度不等"（实测 `rv64ui-p-add`：RTL rows=470 ＝ ISS
        #   行 470，而互异 pc＝358 ⇒ 误报 FAIL，且 `trace_compare` 根本未被调用）。
        #   **这不是放宽**：比对列、`--final-only` 政策、条数阈值（`M2_MIN_TESTS`）与 `trace_compare`
        #   本体一律未动；长度不等仍由 `trace_compare` 退出码 1 兜底（见其 `return 1 if bad or
        #   len(a) != len(b)`），本预检只是**改回度量它自称度量的量**（比原式对含循环测试更严）。
        n_iss = _csv_data_rows(iss_csv)
        if n_iss is None:
            fails.append('%s：ISS 侧 CSV 不可读（fail-closed）→ %s' % (name, rel(iss_csv)))
            continue
        t_s, rc_s = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'rv64ui_opt',
                               '+IMAGE=%s' % tbhexp, '+DATA=%s' % datahexp,
                               '+RT_T_CSV=%s' % rtl_csv.replace('\\', '/')]],
                          'vsim-%s' % name)
        note.append(t_s)
        bad_s = [ln.strip() for ln in t_s.splitlines()
                 if 'HALT_FAIL' in ln or 'WATCHDOG_TIMEOUT' in ln]
        if bad_s:
            fails.append('%s：RTL 侧自报失败——%s（未停机/超时；RTL 侧**未跑通**，归因见 %s）'
                         % (name, bad_s[0][:110], rel(log)))
            with open(log, 'a', encoding='utf-8', newline='\n') as f:
                f.write('\n[%s RTL]\n%s\n' % (name, '\n'.join(note)))
            continue
        mh = RE_E2E_HALT.search(t_s)
        if not mh:
            fails.append('%s：RTL 侧未见 `HALT_PASS … rows=…`（fail-closed）→ %s' % (name, rel(log)))
            continue
        # 数据窗预载**已在环**的证据行（TB 自报；红线 R8：机制不得"配了没生效"）。
        # 缺它 ⇒ 数据窗可能仍是零填充（本判据已按 `data.hex` 传 `+DATA=`）⇒ 等价性无证据。
        if 'data window preloaded:' not in (t_s or ''):
            fails.append('%s：RTL 侧未见数据窗预载证据行（`data window preloaded: …`；'
                         '`+DATA=` 未生效 ⇒ 数据桩仍为零填充，等价性无证据；fail-closed）→ %s'
                         % (name, rel(log)))
            continue
        if int(mh.group(1)) != n_iss:
            fails.append('%s：RTL 侧 rows=%s ≠ ISS 行数 %d（长度不等；fail-closed）'
                         % (name, mh.group(1), n_iss))
            continue
        if not os.path.exists(rtl_csv):
            fails.append('%s：RTL 侧 CSV 未落盘（fail-closed）' % name)
            continue
        try:
            rc_cmp, o_cmp = run([sys.executable, rel(TRACE_COMPARE), rel(iss_csv), rtl_csv],
                                timeout=300)
        except subprocess.TimeoutExpired:
            fails.append('%s：trace_compare 超时（>300s）' % name)
            continue
        note.append('$ python %s %s %s\n%s' % (rel(TRACE_COMPARE), rel(iss_csv), rtl_csv, o_cmp))
        with open(log, 'a', encoding='utf-8', newline='\n') as f:
            f.write('\n[%s]\n%s\n' % (name, '\n'.join(note)))
        if rc_cmp != 0 or 'mismatch=0' not in (o_cmp or ''):
            fails.append('%s：RTL-vs-ISS 未 0 mismatch（退出码 %d；%s）'
                         % (name, rc_cmp, last_line(o_cmp)[:100]))
            continue
        n_pass += 1

    if fails:
        return False, ('%d/%d 条通过（口径 ≥%d 且 0 失败）；首fail：%s ｜ %s'
                       % (n_pass, len(tests), M2_MIN_TESTS, fails[0], rel(log)))
    if n_pass < M2_MIN_TESTS:
        return False, ('仅 %d 条在册/跑通 < 口径 %d 条（不足即 FAIL，不放宽；'
                       '把更多 rv64ui 测试加进 build_rv64ui.py 的 --tests 再跑）｜ %s'
                       % (n_pass, M2_MIN_TESTS, rel(log)))
    return True, ('rv64ui 定向子集 %d 条全过（≥%d）：逐条 ISS `halt_val=0x1` ＋ RTL `HALT_PASS` '
                  '（tohost 停机）＋ 逐条比对 `mismatch=0`（列 pc,binary,gpr,csr）｜ 数据面：逐条 '
                  '`+DATA=` 预载（数据窗＝镜像数据段；md5 复算＋TB 证据行）｜ vlog %d 单元'
                  '／vopt 逐段 Errors: 0 ｜ %s' % (n_pass, M2_MIN_TESTS, n_comp, rel(log)))


# TB **单元级**编译清单（`tb-compile` 的唯一编译集合来源；与 `filelist/rtl.f` 分域）
TB_UNIT_F = os.path.join(ROOT, 'filelist', 'tb_unit.f')


# --------------------------------------------------------------------------- #
# M2 exit (b)/(c)：回归批 与 覆盖率批
#
#   **判据只核证据，不重跑重活**（R0 2026-09-26 授权口径 A，心跳第 9 轮）：
#   这两条 exit 的"重活"（vlog/vopt/逐例 vsim/ISS/比对/覆盖率合并）由**机制件**承担
#   （`run_cmd/regress_rv1.py`、`run_cmd/cover_rv1.py`），判据本体只核**已有证据**的
#   **齐全性／一致性／时效性**，全部 **fail-closed**（缺文件、解析不到、格式不符一律 FAIL 并列出
#   具体缺什么）。判据**不隐式触发**机制件（否则每次 `check` 都要几分钟 ⇒ 常跑面会烂掉）；
#   证据过期时由人或 `flow.py run` 显式重跑机制件刷新。
#
#   时效（"两轮/报告与**当前** RTL 同版本"）的判定源＝机制件落盘的**版本指纹**：
#     · 回归轮：`sim/run_regress_<id>/config.json` 的 `fingerprint`（`filelist/rtl.f` md5 ＋
#       `filelist/tb_m1_e2e.f` md5 ＋ 逐编译单元 md5 ＋ 收尾复算的 `changed_since_fingerprint`）；
#     · 覆盖率批：`sim/covdb/FINGERPRINT.json` 的 `rtl_filelist.md5` ＋ `compile_units`（同为逐单元 md5）。
#   判据把指纹与**现盘**比：`filelist/rtl.f` md5、`rtl.f` 的每个 RTL 单元的 md5 逐条复核；不等即
#   "证据过期"⇒ FAIL 并给出两侧值 ＋ 重跑提示。**TB 面与沙箱内逐例产物不进本判据口径**：
#   `filelist/tb_m1_e2e.f` 与 `sim/run_*/**` 属"可清理/可演进的平台面"（AGENTS.md §2：sim/ 是编译
#   仿真工作目录），把它们绑进 M2 的 exit 会让平台侧正常演进（如新增覆盖模型）把 DUT 侧证据判红；
#   口径据此**只锚 RTL 面**，与授权口径（"与当前 `filelist/rtl.f` md5 一致"）逐字一致。
# --------------------------------------------------------------------------- #
M2_R10_MAX_JOBS = 4            # 红线 R10：并发 ≤4（与 run_cmd/regress_rv1.py:MAX_JOBS 同值）
M2_R9_CASE_TIMEOUT = 1200      # 红线 R9：单用例挂钟上限 1200 s（ModelSim 20 分钟/用例）
M2_R9_BATCH_BUDGET = 7200      # 红线 R9：单轮总时长上限 7200 s（2 小时）
M2_R9_WATCHDOG = 2000000       # 红线 R9：TB 侧单用例 watchdog 拍数
# 轮间差异里**不参与同配置比对**的字段（与该机制件 `cmd_diff` 的 ignore 集合同源：逐轮身份，非配置）
REGRESS_IGNORE_KEYS = ('runner_id', 'round', 'sandbox', 'started', 'finished', 'elapsed_s', 'verdict')
RE_REGRESS_COUNTS = re.compile(r'^\[regress\] counts:\s*total=(\d+)\s+pass=(\d+)\s+fail=(\d+)\s+'
                               r'timeout=(\d+)\s+fatal=(\d+)\s+skip=(\d+)\s*$', re.M)
RE_ROUND_DIFF = re.compile(r'^REGRESSION_DIFF base=(\S+) head=(\S+) new_fail=(\d+) lost_fail=(\d+)\s+'
                           r'same_fail=(\d+) new_timeout=(\d+) same_config=(yes|no)\s*$', re.M)
RE_DIFF_COUNTS = re.compile(r'^\[diff\] (base|head):\s*total=(\d+)\s+pass=(\d+)\s+fail=(\d+)\s+'
                            r'timeout=(\d+)\s+fatal=(\d+)\s*$', re.M)
RE_REPORT_RTL_MD5 = re.compile(r'RTL filelist md5=([0-9a-f]{32})')


def _round_dir(rid):
    return os.path.join(ROOT, 'sim', 'run_regress_%s' % rid)


def _newest_round_diff():
    """最近一次 `--diff` 的产物（判据据此确定**被判的两轮**；mtime 最新者，并列报全部候选）。

    为什么按"最新"取而不写死 `r1/r2`：轮次编号是机制件的实现细节（`--runner-id` 由人指定），
    判据只认"最近一次机判出的两轮"，并把它点名写进结论（可审计）；轮次 id 不写进判据硬编码。
    """
    hits = sorted(glob.glob(os.path.join(ROOT, 'sim', 'run_regress_*', 'round_diff.txt')))
    if not hits:
        return None, hits
    return max(hits, key=lambda p: (os.path.getmtime(p), p)), hits


def _fingerprint_unit_check(fp, tag, hint):
    """版本指纹的**逐 RTL 单元 md5** 与现盘比对（只核 `filelist/rtl.f` 的单元——口径见上）。

    返回错误串或 None。不核 TB 单元：TB 面不在 M2 的 RTL 版本口径内（理由见节头注释）。
    """
    units, _ = _parse_f_list(RTL_F)
    fp_units = {x['path']: x.get('md5') for x in (fp.get('compile_units') or [])
                if isinstance(x, dict) and x.get('path')}
    for u in units:
        if u not in fp_units or not fp_units[u]:
            return '%s 指纹缺编译单元 %s 的 md5（fail-closed）%s' % (tag, u, hint)
        live = md5_of(os.path.join(ROOT, u))
        if fp_units[u] != live:
            return ('%s 指纹的 %s md5=%s ≠ 现盘 %s（证据过期：该单元在指纹采集之后被改）%s'
                    % (tag, u, fp_units[u][:8], live[:8], hint))
    return None


def _regress_round_evidence(rid):
    """**单轮**回归证据核（fail-closed）：summary／cases.json／config.json 三者自洽 ＋ R9/R10 ＋ 指纹。

    返回 (err, info)：err 为 None ⇒ 该轮自洽；info 供跨轮比对（counts／config／逐例数）。
    """
    d = _round_dir(rid)
    p_sum, p_cfg, p_cas = (os.path.join(d, 'summary.txt'), os.path.join(d, 'config.json'),
                           os.path.join(d, 'cases.json'))
    for p in (p_sum, p_cfg, p_cas):
        if not os.path.exists(p):
            return ('轮 %s 缺 %s（fail-closed）⇒ 重跑 run_cmd/regress_rv1.py' % (rid, rel(p))), None
    cfg, cas = load_json(p_cfg, default=None), load_json(p_cas, default=None)
    if not isinstance(cfg, dict) or not isinstance(cas, dict):
        return '轮 %s 的 config.json／cases.json 不可解析（fail-closed）' % rid, None
    text = io.open(p_sum, 'r', encoding='utf-8').read()
    tail = last_line(text)
    if not tail.startswith('REGRESSION_PASS'):
        return ('轮 %s summary 尾行不是 `REGRESSION_PASS`（实为「%s」）⇒ 该轮非"0 FAIL 全过"'
                '（fail-closed；不放宽）' % (rid, tail[:70])), None
    hard = [ln.strip() for ln in text.splitlines()
            if ln.strip().startswith(('REGRESSION_FAIL', 'REGRESSION_ABORTED'))]
    if hard:
        return '轮 %s summary 含「%s」（fail-closed）' % (rid, hard[0][:70]), None
    m = RE_REGRESS_COUNTS.search(text)
    if not m:
        return '轮 %s summary 无可解析的 `[regress] counts:` 行（fail-closed）' % rid, None
    counts = dict(zip(('total', 'pass', 'fail', 'timeout', 'fatal', 'skip'),
                      (int(x) for x in m.groups())))
    if counts['total'] <= 0:
        return '轮 %s 的 counts total=0（未跑任何用例；fail-closed）' % rid, None
    if (counts['total'] != counts['pass'] or counts['fail'] or counts['timeout']
            or counts['fatal'] or counts['skip']):
        return ('轮 %s counts=%s：口径要求 total==pass 且 fail/timeout/fatal/skip 全 0（不放宽）'
                % (rid, counts)), None
    cc, cases = cas.get('counts') or {}, cas.get('cases') or []
    if any(int(cc.get(k, -1)) != counts[k] for k in counts):
        return ('轮 %s 的 cases.json counts %s ≠ summary counts %s（证据不一致，fail-closed）'
                % (rid, cc, counts)), None
    if len(cases) != counts['total']:
        return ('轮 %s 的 cases.json 逐例 %d 条 ≠ counts.total %d（fail-closed）'
                % (rid, len(cases), counts['total'])), None
    notpass = [c.get('name') for c in cases if c.get('status') != 'PASS']
    if notpass:
        return '轮 %s 有非 PASS 用例：%s（fail-closed）' % (rid, '、'.join(notpass[:4])), None
    if cas.get('verdict') != 'PASS' or cfg.get('verdict') != 'PASS':
        return ('轮 %s verdict＝cases.json:%s／config.json:%s（须均 PASS；fail-closed）'
                % (rid, cas.get('verdict'), cfg.get('verdict'))), None
    # R10：并发 ≤4 且**沙箱独占**（本轮 runner_id ↔ 沙箱路径一一对应）
    sb = 'sim/run_regress_%s' % rid
    if cfg.get('runner_id') != rid or cfg.get('sandbox') != sb:
        return ('轮 %s 的 runner_id/sandbox＝%s/%s ≠ 目录身份 %s（红线 R10 沙箱独占；fail-closed）'
                % (rid, cfg.get('runner_id'), cfg.get('sandbox'), sb)), None
    if not (1 <= int(cfg.get('jobs', 0)) <= M2_R10_MAX_JOBS) \
            or int(cfg.get('jobs_cap', 0)) != M2_R10_MAX_JOBS:
        return ('轮 %s jobs=%s／jobs_cap=%s（口径 jobs ∈1..%d 且 cap==%d；红线 R10，fail-closed）'
                % (rid, cfg.get('jobs'), cfg.get('jobs_cap'), M2_R10_MAX_JOBS, M2_R10_MAX_JOBS)), None
    # R9：watchdog（TB 拍数）＋ 双挂钟闸在环（值须与机制件常量同值；只认参数，不认"说法"）
    r9 = (int(cfg.get('case_timeout_s', 0)), int(cfg.get('batch_budget_s', 0)),
          int(cfg.get('watchdog_cycles', 0)))
    if r9 != (M2_R9_CASE_TIMEOUT, M2_R9_BATCH_BUDGET, M2_R9_WATCHDOG):
        return ('轮 %s 的 R9 面 case_timeout/batch_budget/watchdog=%s ≠ 口径 %s（红线 R9；fail-closed）'
                % (rid, r9, (M2_R9_CASE_TIMEOUT, M2_R9_BATCH_BUDGET, M2_R9_WATCHDOG))), None
    # 版本指纹（时效面）：指纹须在册，且与现盘 RTL 逐条相符
    fp = cfg.get('fingerprint')
    if not isinstance(fp, dict):
        return ('轮 %s 的 config.json 无 `fingerprint`（旧机制件产物 ⇒ 无法判"与当前 RTL 同版本"）'
                '⇒ 重跑 run_cmd/regress_rv1.py 刷新证据' % rid), None
    rf = fp.get('rtl_filelist') or {}
    live_fl = md5_of(RTL_F)
    if rf.get('path') != 'filelist/rtl.f' or not rf.get('md5'):
        return '轮 %s 指纹缺 `rtl_filelist`（path=filelist/rtl.f ＋ md5；fail-closed）' % rid, None
    if rf['md5'] != live_fl:
        return ('轮 %s 指纹的 rtl.f md5=%s ≠ 当前 filelist/rtl.f md5=%s（证据过期：清单在该轮之后变过）'
                '⇒ 重跑 run_cmd/regress_rv1.py' % (rid, rf['md5'], live_fl)), None
    err = _fingerprint_unit_check(fp, '轮 %s' % rid, '；⇒ 重跑 run_cmd/regress_rv1.py')
    if err:
        return err, None
    # 收尾复算的轮内变更：必须空（非空 ⇒ 该轮跑动期间源被改，那一轮的产物不可当"同版本证据"）
    ch = fp.get('changed_since_fingerprint')
    if ch is None or ch != []:
        return ('轮 %s 的 `changed_since_fingerprint`=%s（须为 []；非空 ⇒ 该轮运行期间源被改，'
                '证据不可用；fail-closed）' % (rid, ch)), None
    rtl_units, _ = _parse_f_list(RTL_F)
    rec = [u for u in (cfg.get('compile', {}).get('units') or []) if u.startswith('rtl/')]
    if set(rec) != set(rtl_units):
        return ('轮 %s 的编译单元（rtl/ 前缀 %d 个）≠ 当前 filelist/rtl.f 条目（%d 个）：%s'
                '（fail-closed）⇒ 重跑 run_cmd/regress_rv1.py'
                % (rid, len(rec), len(rtl_units),
                   '、'.join(sorted(set(rec) ^ set(rtl_units))[:4]) or '?')), None
    return None, {'cfg': cfg, 'counts': counts, 'n_cases': len(cases), 'n_units': len(rtl_units),
                  'rtl_md5': live_fl}


def chk_m2_regress():
    """m2-regress（M2 exit (b)）：同配置 **≥2 轮 0 新 FAIL**；R10 与 R9 在环；两轮与**当前 RTL 同版本**。

    判据（R0 2026-09-26 授权口径 A；**只核证据、不重跑重活**；全部 fail-closed）：
      ① 机制件在册（`run_cmd/regress_rv1.py` ＋ `run_cmd/rv64ui_testlist.txt`）；
      ② 被判两轮＝最近一次 `--diff` 产出的 `sim/run_regress_<head>/round_diff.txt`（mtime 最新者；
         两轮名取自其 `REGRESSION_DIFF base=… head=…` 尾行，结论里点名，可审计）；
      ③ **单轮**：`summary.txt` 尾行 `REGRESSION_PASS`（且全文无 `REGRESSION_FAIL`／
         `REGRESSION_ABORTED`）、`[regress] counts:` 解析得出 total==pass 且 fail/timeout/fatal/skip
         全 0、`cases.json` 的 counts/逐例/verdict 与之一致、`config.json.verdict==PASS`；
         R10：`jobs ∈1..4` 且 `jobs_cap==4` 且 `runner_id↔沙箱`一一对应（独占）；
         R9：`case_timeout_s=1200`／`batch_budget_s=7200`／`watchdog_cycles=2000000`（与机制件常量同值）；
      ④ **跨轮**：`round_diff` 自报 `new_fail==0`／`new_timeout==0`／`same_config==yes`，且其
         base/head 计数行与两轮 summary counts 逐值相符；同配置面**独立复算**——两轮 `config.json`
         除逐轮身份字段（`REGRESS_IGNORE_KEYS`）外逐字段相等（与机制件 `cmd_diff` 同口径，判据自带）；
      ⑤ **时效（版本）**：两轮 `config.fingerprint` 的 `filelist/rtl.f` md5 == 现盘 md5，且 `rtl.f`
         的**每个 RTL 单元**的 md5 逐条 == 现盘，`changed_since_fingerprint == []`，编译器记录的
         RTL 单元集合 == 当前 `filelist/rtl.f` 条目集合。不等即"证据过期"⇒ FAIL 并给两侧值与重跑提示。

    为什么不自己跑：本判据若内联重跑（vlog+vopt+逐例 vsim+ISS+比对），每次 `check` 都要数分钟且
    撞 ModelSim license 抖动（ISS-104）⇒ 常跑面会烂掉；重活由机制件承担、**由人显式发起**（规则 23
    的"判据只判产品"）。为什么不进 `GUARDS`：同上（比常跑守卫重，且证据刷新要跑仿真）。
    """
    for p in (os.path.join(ROOT, 'run_cmd', 'regress_rv1.py'),
              os.path.join(ROOT, 'run_cmd', 'rv64ui_testlist.txt')):
        if not os.path.exists(p):
            return False, '缺机制件 %s（fail-closed；M2 exit (b) 无法判）' % rel(p)
    if not os.path.exists(RTL_F):
        return False, '缺 %s（fail-closed）' % rel(RTL_F)
    newest, cands = _newest_round_diff()
    if newest is None:
        return False, ('缺 sim/run_regress_*/round_diff.txt（两轮同配置的机判面；fail-closed）'
                       '⇒ 跑 `python run_cmd/regress_rv1.py --runner-id a --round 1`、'
                       '`--runner-id b --round 2`、`--diff a b`')
    md = RE_ROUND_DIFF.search(io.open(newest, 'r', encoding='utf-8').read())
    if not md:
        return False, ('%s 无可解析的 `REGRESSION_DIFF …` 尾行（fail-closed）' % rel(newest))
    base, head = md.group(1), md.group(2)
    new_fail, new_to, same = int(md.group(3)), int(md.group(6)), md.group(7)
    if base == head:
        return False, ('轮间差异的 base==head=%s（须两轮不同沙箱；fail-closed）' % base)
    info = {}
    for rid in (base, head):
        err, dat = _regress_round_evidence(rid)
        if err:
            return False, '%s ｜ 判据面 %s' % (err, rel(newest))
        info[rid] = dat
    if new_fail or new_to or same != 'yes':
        return False, ('%s 自报 new_fail=%d new_timeout=%d same_config=%s（口径：≥2 轮 0 新 FAIL ＋ '
                       '同配置；fail-closed 不放宽）' % (rel(newest), new_fail, new_to, same))
    cbh, chh = info[base]['cfg'], info[head]['cfg']
    diffs = [k for k in sorted(set(cbh) | set(chh))
             if k not in REGRESS_IGNORE_KEYS and cbh.get(k) != chh.get(k)]
    if diffs:
        return False, ('两轮 config.json 逐字段独立复算不一致：%s（round_diff 自报 same_config=yes，'
                       '复算不符 ⇒ 证据不可信；fail-closed）' % '、'.join(diffs[:5]))
    # 轮间差异件与两轮证据**配对**（防"用别的轮的 diff 交差"）
    dmap = {g[0]: tuple(int(x) for x in g[1:]) for g in RE_DIFF_COUNTS.findall(
        io.open(newest, 'r', encoding='utf-8').read())}
    for rid, key in ((base, 'base'), (head, 'head')):
        got = dmap.get(key)
        c = info[rid]['counts']
        want = (c['total'], c['pass'], c['fail'], c['timeout'], c['fatal'])
        if got != want:
            return False, ('%s 的 `[diff] %s:` 计数行 %s ≠ 轮 %s 的 summary counts %s'
                           '（配对不符；fail-closed）' % (rel(newest), key, got, rid, want))
    c = info[head]['counts']
    return True, ('同配置两轮 0 新 FAIL（base=%s head=%s；各 total=%d pass=%d fail=0 '
                  'timeout/fatal/skip=0）｜ round_diff new_fail=0 same_config=yes（逐字段复算亦一致）｜ '
                  'R10 jobs=%s≤%d 沙箱独占 sim/run_regress_<id> ｜ R9 watchdog=%d 拍＋单例 %ds/批 %ds ｜ '
                  '版本：两轮 rtl.f md5=%s == 当前（逐单元 md5 复核 %d 个 RTL 单元；轮内变更=无）｜ %s'
                  % (base, head, c['total'], c['pass'], info[head]['cfg'].get('jobs'),
                     M2_R10_MAX_JOBS, M2_R9_WATCHDOG, M2_R9_CASE_TIMEOUT, M2_R9_BATCH_BUDGET,
                     info[head]['rtl_md5'], info[head]['n_units'], rel(newest)))


def chk_m2_cov():
    """m2-cov（M2 exit (c)）：覆盖率**机制在环**＝报告在册 ＋ 编译指纹在册且与**当前 RTL 同版本**。

    判据（R0 2026-09-26 授权口径 A；**只核证据、不重跑重活**；**不要求达阈值**——阈值属 M3/签核）：
      ① 机制件在册（`run_cmd/cover_rv1.py`）；② 编译指纹 `sim/covdb/FINGERPRINT.json` 在册可解析；
      ③ **时效**：其 `rtl_filelist.path==filelist/rtl.f` 且 `md5` == 现盘 md5，且 `compile_units` 里
         `rtl.f` 的每个 RTL 单元 md5 逐条 == 现盘（依 AGENTS.md §3.4 坑 3：合并/报告只对同一编译版本
         有效）⇒ 不等即"报告过期"，FAIL 并给出两侧值 ＋ 重跑 `python run_cmd/cover_rv1.py`；
      ④ **报告在册**：指纹声明的 `report.path` 必须落在 `doc/verify/07-*.txt`、存在、非空、字节数与
         指纹记录一致（防事后改动），且含**指纹段**要素（`编译指纹` ＋ `sim/covdb/FINGERPRINT.json`
         ＋ `batch=<指纹的 batch>`）＋ 段内 `RTL filelist md5=<32hex>` 与当前 md5 相符（报告↔指纹同批）；
      ⑤ 合并件在册：`merged_ucdb.path` 存在、非空、字节数与指纹一致。
      **不进判据口径**：沙箱 `sim/run_cover_*/**` 的逐例 ucdb（AGENTS.md §2 明示 `sim/` 是可清理的
      编译仿真工作目录；把可清理区绑进 exit 会让"清工作目录"把 DUT 侧证据判红）；阈值（M3）。
    """
    mech = os.path.join(ROOT, 'run_cmd', 'cover_rv1.py')
    if not os.path.exists(mech):
        return False, '缺机制件 %s（fail-closed；M2 exit (c) 无法判）' % rel(mech)
    fp_path = os.path.join(ROOT, 'sim', 'covdb', 'FINGERPRINT.json')
    if not os.path.exists(fp_path):
        return False, ('缺编译指纹 %s（fail-closed）⇒ 跑 `python run_cmd/cover_rv1.py`'
                       % rel(fp_path))
    fp = load_json(fp_path, default=None)
    if not isinstance(fp, dict):
        return False, '%s 不可解析（fail-closed）' % rel(fp_path)
    if not os.path.exists(RTL_F):
        return False, '缺 %s（fail-closed）' % rel(RTL_F)
    live = md5_of(RTL_F)
    rf = fp.get('rtl_filelist') or {}
    if rf.get('path') != 'filelist/rtl.f' or not rf.get('md5'):
        return False, ('指纹缺 `rtl_filelist`（path=filelist/rtl.f ＋ md5；fail-closed）→ %s'
                       % rel(fp_path))
    if rf['md5'] != live:
        return False, ('报告过期：指纹的 rtl.f md5=%s ≠ 当前 filelist/rtl.f md5=%s ⇒ 重跑 '
                       '`python run_cmd/cover_rv1.py`（本项**不要求达阈值**，阈值属 M3/签核）'
                       % (rf['md5'], live))
    err = _fingerprint_unit_check(fp, '指纹', '；⇒ 重跑 `python run_cmd/cover_rv1.py`')
    if err:
        return False, err
    rep = (fp.get('report') or {}).get('path')
    if not rep:
        return False, '指纹缺 `report.path`（fail-closed）→ %s' % rel(fp_path)
    if not (rep.startswith('doc/verify/07-') and rep.endswith('.txt')):
        return False, ('报告路径 %s 不落 `doc/verify/07-*.txt`（口径：报告在册；fail-closed）' % rep)
    rp = os.path.join(ROOT, rep)
    if not os.path.exists(rp):
        return False, '覆盖率报告不在册：%s（指纹声明；fail-closed）' % rep
    size = os.path.getsize(rp)
    if size <= 0:
        return False, '覆盖率报告 %s 为空文件（fail-closed）' % rep
    if size != int((fp.get('report') or {}).get('size', -1)):
        return False, ('报告 %s 现盘 %d B ≠ 指纹记录 %s B（报告被事后改动／与指纹不同批；fail-closed）'
                       % (rep, size, (fp.get('report') or {}).get('size')))
    txt = io.open(rp, 'r', encoding='utf-8', errors='replace').read()
    miss = [x for x in ('编译指纹', 'sim/covdb/FINGERPRINT.json', 'batch=%s' % fp.get('batch'))
            if x not in txt]
    if miss:
        return False, ('报告 %s 缺指纹段要素：%s（fail-closed）' % (rep, '、'.join(miss)))
    m = RE_REPORT_RTL_MD5.search(txt)
    if not m:
        return False, ('报告 %s 无可解析的 `RTL filelist md5=<32hex>`（fail-closed）' % rep)
    if m.group(1) != live:
        return False, ('报告 %s 内嵌 rtl.f md5=%s ≠ 当前 %s（报告与当前 RTL 不同版本 ⇒ 过期；'
                       '重跑 `python run_cmd/cover_rv1.py`）' % (rep, m.group(1), live))
    merged = (fp.get('merged_ucdb') or {}).get('path')
    if not merged or not os.path.exists(os.path.join(ROOT, merged)):
        return False, '合并件不在册：%s（指纹声明；fail-closed）' % (merged or '?')
    msize = os.path.getsize(os.path.join(ROOT, merged))
    if msize <= 0 or msize != int((fp.get('merged_ucdb') or {}).get('size', -1)):
        return False, ('合并件 %s 现盘 %d B ≠ 指纹记录 %s B（fail-closed）'
                       % (merged, msize, (fp.get('merged_ucdb') or {}).get('size')))
    return True, ('报告在册 %s（%d B，含指纹段）｜ 编译指纹 %s：rtl.f md5=%s == 当前（逐单元 md5 复核 '
                  '%d 个 RTL 单元）｜ batch=%s 逐例 ucdb %s 份 → 合并件 %s（%d B）｜ **不判阈值**'
                  '（阈值属 M3/签核）'
                  % (rep, size, rel(fp_path), live[:8], len(_parse_f_list(RTL_F)[0]),
                     fp.get('batch'), fp.get('n_ucdb'), merged, msize))


# --------------------------------------------------------------------------- #
# M3 exit 三条（2026-09-26 心跳第十一轮入册；R0 授权口径 A）
#
# 病灶：`process/03` 的 M3 三条 exit 只有**名字**（`m3-cov-threshold`／`m3-regress-zero-error`／
# `m3-mutation-audit`），CHECKS 里**一条都未注册** ⇒ `state=active` 时 `cmd_check` 会按"未注册判据"
# fail-closed 报 FAIL（该里程碑自带 `register_before_activate` 注记）。本轮把可判的两条半落成真判据：
#   · `m3-code-cov`    —— 代码覆盖率四项逐项 ≥90%（AGENTS.md §4）＋证据时效（指纹 == 当前 rtl.f）；
#   · `m3-func-cov`    —— 功能覆盖（covergroup）面：已纳入判定范围的 VP 项 100% 命中 ＋
#                         `doc/verify/02` 的「未纳入项」须**显式列缺带归属**（缺列即 FAIL）；
#   · `m3-regress-stab`—— 同配置 ≥3 轮全过且轮间 0 新 FAIL ＋各轮与当前 rtl.f 同指纹。
# 第三条 M3 exit（`m3-mutation-audit`／错误注入保真度抽检）**仍未注册**：其机制（VP-X05 的变异注入）
# 尚无落点，按"未注册即 fail-closed"的口径**保留待注册**，不假落（留 TODO(M3-3)）。
#
# 纪律（与 M2 两条同源）：**只核证据＋时效，不重跑重活**（vlog/vopt/vsim/回归由机制件承担、由人显式
# 发起）；阈值一律取 `AGENTS.md` §4 原文，**不得在判据里放宽**；未达标一律**如实 FAIL** 并在消息里给出
# 现值与缺口（红线 R6/R7/R8）；一律 fail-closed（解析不到即报错，不猜、不豁免）。
# --------------------------------------------------------------------------- #
M3_CODE_COV_FLOOR = 90.0                            # AGENTS.md §4：代码覆盖率 ≥90%（逐项）
M3_CODE_COV_FACES = ('Statements', 'Branches', 'Conditions', 'FSM Transitions')
M3_REG_MIN_ROUNDS = 3                               # AGENTS.md §4「稳定性 ≥2 轮」⇒ M3 取同配置 3 轮
M3_COV_MODEL = os.path.join(ROOT, 'tb', 'unit', 'm1_e2e_cov.sv')   # VP→covergroup 映射的声明件
VERIFY02 = os.path.join(ROOT, 'doc', 'verify', '02-验证点清单.md')
COV_FP = os.path.join(ROOT, 'sim', 'covdb', 'FINGERPRINT.json')    # 与 chk_m2_cov 同路径（不抽公共件）
RE_COV_METRIC = re.compile(r'^[ \t]+([A-Za-z][A-Za-z ]*?)[ \t]+(\d+)[ \t]+(\d+)[ \t]+(\d+)[ \t]+[\d.]+%[ \t]*$',
                           re.M)
RE_DESIGN_UNIT = re.compile(r'^===\s*Design Unit:\s*work\.(\w+)\s*$')
RE_CVG_INST = re.compile(r'^[ \t]*Covergroup instance[ \t]+(\S+)', re.M)
RE_CVG_BINS_PAIR = re.compile(r'covered/total bins:[ \t]+(\d+)[ \t]+(\d+)')
RE_CVG_BIN_ZERO = re.compile(r'^[ \t]+bin[ \t]+(\S+)[ \t]+\d+[ \t]+\d+[ \t]+-[ \t]+ZERO[ \t]*$', re.M)
RE_CVG_TOTAL = re.compile(r'^TOTAL COVERGROUP COVERAGE:\s*([\d.]+)%', re.M)
RE_CVG_TYPES = re.compile(r'COVERGROUP TYPES:\s*(\d+)')
RE_CG_DECL = re.compile(r'CG(\d+)\s+`([A-Za-z_]\w*)`')
RE_VP_TOKEN = re.compile(r'VP-[A-Za-z]?\d+[a-f]?')
# 「归属」的机械判据（`doc/verify/02` 未纳入节）：指向某件（路径式）或某步骤/里程碑/ADR 号
RE_OWNER = re.compile(r'(?:doc|spec|rtl|tb|iss|sw|sim|run_cmd|filelist)/[\w./\-]+'
                      r'|\bM\d[\w.\-]*\b|\bADR-P?-\d+\b')
# **受控复位注入通道的 bin 说明**（R0 2026-09-26 三项裁定①＝`doc/verify/02` §6 NU-2 受控通道）：
# 这 2 个 bin（`cg_lsu_fsm.cp_trans` 的 `t_req_idle`/`t_rsp_idle`）的**激励**经受控通道产生——
# `run_cmd/cover_m3_testlist.txt` 的 `rst_*` 条目（仅覆盖率批；不进回归同配置、不进 `m2-rv64ui`）
# ＋ `tb/unit/m1_e2e_tb.sv` 的 `+RESET_INJECT=<cycle>` 机制件（受控通道单例判定见
# `run_cmd/cover_rv1.py:run_case_rst`）。**判定口径不变**：仍要求 100% 命中——本常量只做
# **通道说明**（写进判据消息防后人误判为豁免/漏洞），不是豁免清单、不是 waiver（红线 R7）。
M3_FUNC_COV_CONTROLLED_BINS = ('t_req_idle', 't_rsp_idle')

# --------------------------------------------------------------------------- #
# **列缺豁免机制**（R0 2026-09-26 授权；两条 M3 判据共用）
#
# 病灶：`doc/verify/02` §6／§7 已把「判定范围之外／当前范围不可达」的项**逐条列缺**（含依据与
# 归属，且经人/R0 裁定），但 (a)(b) 两条判据只按**全分母**判 ⇒ 同一批条目每轮必然报 FAIL、判据
# 无法收敛。R0 2026-09-26 授权落成机制（＝ §7 主表 CC-X1 行「是否从分母口径中剔除…须 R0 裁定」
# 的裁定执行面）：把列缺清单**机械解析**成"豁免集"，判定时**从分母扣除**并在消息里逐条回显。
#
# 四条硬边界（**同文写进两条判据的 docstring 与消息**，防后人误判成 waiver）：
#   ① 豁免**仅限**清单内、**依据可查**的条目：code 面每条须回指一个**非**「已纳入／处置项」的
#      `CC-` 主表行；func 面须出现在「未纳入」节表体首列的反引号 token 里；二者都须带非空归属。
#      清单外的项**一律照旧计入分母**。
#   ② 豁免**不改**任何 bin／采样条件／阈值／检查器逻辑（红线 R6／R7）——只改**分母口径**。
#   ③ 豁免**不得**靠新增／改写列缺条目凑达标：判据**用工具现值反向设上界**——同一 `单元×面` 的
#      豁免项数 ≤ 报告该格 misses、同一面 ≤ 该面 misses（**报告没报缺的项豁免不了**），并把每条
#      豁免的**依据与清单位置行号**回显进消息（可人工复核）。
#   ④ **豁免集为空时，判据行为与消息与本机制落地前逐字一致**；而"清单本体解析不到"（缺
#      `doc/verify/02`／缺 §6／§7 节／节内无表体行）一律 **FAIL**（fail-closed：加了豁免通道
#      也不放行"清单没了"这种状态）。
# --------------------------------------------------------------------------- #
VERIFY02_CODE_GAP_HEAD = '代码覆盖率（M3-(a)）未命中项'    # §7 主表所在节（标题片段）
VERIFY02_EXEMPT_HEAD = '豁免集'                            # §7 下的机器可读子表（标题片段）
RE_CC_ID = re.compile(r'CC-[A-Z]?\d+')
RE_EXEMPT_NOT_EXEMPTIBLE = re.compile(r'已纳入|处置项')    # 这两类主表行**不得**被豁免
M3_EXEMPT_FACES = M3_CODE_COV_FACES                        # 「面」须逐字取四项之一
RE_EXEMPT_LINES = re.compile(r'\d+')


def _rtl_unit_src(name):
    """单元名（`vr1_ifetch.sv` 或 `vr1_ifetch`）→ 仓库根相对源码路径（按 `filelist/rtl.f` 匹配）。

    只认 `rtl.f` 在册单元（fail-closed：无匹配返回 None，调用方按"条目不可核"报 FAIL）——
    豁免集里的行号必须能落到**真编译单元**的源码上，否则"依据可查"无从谈起。
    """
    want = os.path.basename((name or '').replace('\\', '/').strip())
    if not want.endswith('.sv'):
        want += '.sv'
    for u in _parse_f_list(RTL_F)[0]:
        if os.path.basename(u.replace('\\', '/')) == want:
            return u
    return None


def _verify02_code_exemptions():
    """解析 `doc/verify/02` §7 的**机器可读「豁免集」子表** → (豁免集, 附注, 错误串 | None)。

    返回的豁免集＝按子表顺序的 dict 列表：
      `{'face','unit','lines','count','basis','owner','sec_line','row_line','src'}`
    （`src`＝该行号在该单元源码里的原文，供消息回显；`sec_line`/`row_line`＝清单位置，供人工复核）。

    口径（机械、fail-closed；**不猜、不静默跳过**）：
      · `doc/verify/02` **必须**在，且**必须**有标题含 `VERIFY02_CODE_GAP_HEAD` 的节、该节内
        **必须有 `CC-` 主表行**——否则返回错误 ⇒ 调用方 FAIL（"清单本体解析不到"≠"豁免集为空"）；
      · §7 内**无**标题含 `VERIFY02_EXEMPT_HEAD` 的子表 ⇒ 豁免集＝**空**（判据行为与落地前逐字一致）；
      · 子表每行**六列**（面／单元／行／项数／依据／归属）：面须逐字取四项之一；`项数` 正整数；
        `行` 为数字（顿号/逗号/空格分隔，须能在该单元源码里定位到**非空行**）；`依据` 须回指
        **在册**的 `CC-` 主表行且该行**不得**含「已纳入／处置项」；`归属` 非空。任一不满足 ⇒ FAIL。
    """
    if not os.path.exists(VERIFY02):
        return None, None, '缺 %s（fail-closed；列缺清单不在册）' % rel(VERIFY02)
    lines = _doc_lines(VERIFY02)
    hd = [(i, re.match(r'^(#{2,4})\s+(.*)$', ln)) for i, ln in enumerate(lines)]
    lo = lvl = None
    for i, m in hd:
        if m and VERIFY02_CODE_GAP_HEAD in m.group(2):
            lo, lvl = i, len(m.group(1))
            break
    if lo is None:
        return None, None, ('`doc/verify/02` 无标题含「%s」的节 ⇒ 代码覆盖列缺清单缺失（fail-closed；'
                            '本判据不认"没有清单"）' % VERIFY02_CODE_GAP_HEAD)
    hi = len(lines)
    for i, m in hd:
        if m and i > lo and len(m.group(1)) <= lvl:
            hi = i
            break
    mains = {}
    for ln_no, cells in [r for _h, _c, rs in md_tables(lines, lo, hi) for r in rs]:
        # 只认**主表**行：首列就是 `CC-<n>` 号（豁免子表首列是「面」，其「依据」列虽含 `CC-n`
        # 但不算主表行——否则可借子表行绕过主表「已纳入／处置项」的禁豁免判据）
        m = re.match(r'^(CC-[A-Z]?\d+)\b', strip_md(cells[0]) if cells else '')
        if m:
            mains.setdefault(m.group(1), (ln_no, ' '.join(cells)))
    if not mains:
        return None, None, ('`doc/verify/02` §7（标题第 %d 行）无 `CC-` 主表行 ⇒ 列缺清单不可解析'
                            '（fail-closed）' % (lo + 1))
    elo = None
    for i, m in hd:
        if m and lo < i < hi and VERIFY02_EXEMPT_HEAD in m.group(2):
            elo = i
            break
    if elo is None:
        return [], {'gap_line': lo + 1, 'ex_line': None, 'main_rows': len(mains)}, None
    ehi = hi
    for i, m in hd:
        if m and i > elo and len(m.group(1)) <= len(re.match(r'^(#{2,4})', lines[elo]).group(1)):
            ehi = i
            break
    rows, bad = [], []
    for ln_no, cells in [r for _h, _c, rs in md_tables(lines, elo, ehi) for r in rs]:
        if len(cells) < 6:
            bad.append('第 %d 行 列数 %d < 6' % (ln_no, len(cells)))
            continue
        face, unit, ln_s, cnt_s, basis, owner = [strip_md(c) for c in cells[:6]]
        if face not in M3_EXEMPT_FACES:
            bad.append('第 %d 行「面」= %s 不在 %s' % (ln_no, face or '(空)', '/'.join(M3_EXEMPT_FACES)))
            continue
        src = _rtl_unit_src(unit)
        if src is None:
            bad.append('第 %d 行「单元」= %s 不在 `filelist/rtl.f` 在册单元内' % (ln_no, unit or '(空)'))
            continue
        nums = [int(x) for x in RE_EXEMPT_LINES.findall(ln_s)]
        if not nums:
            bad.append('第 %d 行「行」列无可解析行号（%s）' % (ln_no, ln_s or '(空)'))
            continue
        try:
            cnt = int(cnt_s)
        except ValueError:
            cnt = 0
        if cnt < 1:
            bad.append('第 %d 行「项数」= %s 非正整数' % (ln_no, cnt_s or '(空)'))
            continue
        cids = RE_CC_ID.findall(basis)
        if not cids:
            bad.append('第 %d 行「依据」列未回指 `CC-` 主表行（%s）' % (ln_no, basis or '(空)'))
            continue
        ref_bad = [c for c in cids
                   if c not in mains or RE_EXEMPT_NOT_EXEMPTIBLE.search(mains[c][1])]
        if ref_bad:
            bad.append('第 %d 行「依据」%s 不是可豁免主表行（不在册／含「已纳入｜处置项」）'
                       % (ln_no, '、'.join(ref_bad)))
            continue
        if not owner:
            bad.append('第 %d 行「归属」列空' % ln_no)
            continue
        text = io.open(os.path.join(ROOT, src), 'r', encoding='utf-8', errors='replace').read().splitlines()
        bad_ln = [n for n in nums if not (1 <= n <= len(text)) or not text[n - 1].strip()]
        if bad_ln:
            bad.append('第 %d 行行号 %s 在 %s（%d 行）里定位不到非空行'
                       % (ln_no, '、'.join(str(n) for n in bad_ln), src, len(text)))
            continue
        rows.append({'face': face, 'unit': os.path.basename(src), 'lines': nums, 'count': cnt,
                     'basis': '/'.join(dict.fromkeys(cids)), 'owner': owner, 'sec_line': elo + 1,
                     'row_line': ln_no, 'src': src})
    if bad:
        return None, None, ('`doc/verify/02` §7 豁免集子表（第 %d 行起）有 %d 行不合规（fail-closed；'
                            '不猜、不静默跳过）：%s' % (elo + 1, len(bad), '；'.join(bad[:4])))
    return rows, {'gap_line': lo + 1, 'ex_line': elo + 1, 'main_rows': len(mains)}, None


def _verify02_func_exemptions():
    """解析 `doc/verify/02`「未纳入」节表体 → (候选 bin 集, 附注, 错误串 | None)。

    候选＝该节**表体行首列**里反引号包的 token（＝列缺条目名，与 `_verify02_gap_ownership` 同源
    读法）。真正的豁免**只在判定时**取「候选 ∩ 报告 §A 当前 missing bin」——**报告没报缺的 bin
    豁免不了**（反向上界，防"拿豁免凑绿"）。首列之外（依据／归属列）的 token 不取，避免把叙述里
    的旁证 token 当条目名。
    """
    if not os.path.exists(VERIFY02):
        return None, None, '缺 %s（fail-closed；列缺清单不在册）' % rel(VERIFY02)
    lines = _doc_lines(VERIFY02)
    hd = [(i, re.match(r'^(#{2,4})\s+(.*)$', ln)) for i, ln in enumerate(lines)]
    lo = lvl = None
    for i, m in hd:
        if m and '未纳入' in m.group(2):
            lo, lvl = i, len(m.group(1))
            break
    if lo is None:
        return None, None, ('`doc/verify/02` 无标题含「未纳入」的节 ⇒ 功能覆盖列缺清单缺失'
                            '（fail-closed；本判据不认"没有清单"）')
    hi = len(lines)
    for i, m in hd:
        if m and i > lo and len(m.group(1)) <= lvl:
            hi = i
            break
    rows = []
    for _h, hcells, rs in md_tables(lines, lo, hi):
        # 条目名列＝表头含「未纳入项」的那一列（§6 表首列是 `#`）；表头认不出时退回首列
        ci = next((j for j, c in enumerate(hcells) if '未纳入项' in c), 0)
        rows += [(ln_no, cells, ci) for ln_no, cells in rs]
    if not rows:
        return None, None, ('`doc/verify/02`「未纳入」节（第 %d 行起）无表体行 ⇒ 列缺清单不可解析'
                            '（fail-closed）' % (lo + 1))
    cand = {}
    for ln_no, cells, ci in rows:
        cell = cells[ci] if ci < len(cells) else ''
        for tok in ticks(cell):
            cand.setdefault(tok, (ln_no, cells))
    return cand, {'sec_line': lo + 1, 'rows': len(rows)}, None


def _report_dut_units(txt):
    """从报告 §C **逐实例节**取 `{单元名: {面: {'bins','hits','misses'}}}`（DUT 面；失败返回 None）。

    与 `_report_dut_rollup` 同一切节口径（同正则、同 `filelist/rtl.f` 单元名集合），但**保留单元维**
    ——豁免机制要用「同一 单元×面 的 misses」做**反向上界**（工具报缺多少，最多只能豁免多少）。
    """
    body = _report_block(txt, '§C DUT 面（', ('§D `vcover report -assert -detail`',))
    if body is None:
        return None
    units, _ = _parse_f_list(RTL_F)
    stems = set()
    for u in units:
        p = '/' + u.replace('\\', '/').lstrip('/')
        if '/rtl/vr1/' in p:
            stems.add(os.path.basename(p).rsplit('.', 1)[0])
    out, cur_u = {}, None
    for ln in body.splitlines():
        m = RE_DESIGN_UNIT.match(ln)
        if m:
            cur_u = m.group(1) if m.group(1) in stems else None
            if cur_u:
                out.setdefault(cur_u, {})
            continue
        if cur_u is None:
            continue
        g = RE_COV_METRIC.match(ln)
        if g:
            out[cur_u][g.group(1).strip()] = {'bins': int(g.group(2)), 'hits': int(g.group(3)),
                                              'misses': int(g.group(4))}
    return out or None


def _exempt_bound_check(rows, units, note):
    """把豁免集对到报告现值上（**反向上界**）→ (逐面扣除数, 问题清单)。

    上界两条（缺一不可，fail-closed）：① 同一 `单元×面`：Σ 项数 ≤ 报告该格 `misses`；② 同一面：
    Σ 项数 ≤ 报告该面 `misses`。报告**没报缺**的项因此豁免不了——"拿豁免凑绿"在机制上不可行。
    另核：豁免集里点名的单元必须在报告 §C 里**有该面**（否则是凭空条目）。
    """
    import collections
    per = collections.Counter()
    cell = collections.Counter()
    bad = []
    for r in rows:
        stem = r['unit'].rsplit('.', 1)[0]
        u = (units or {}).get(stem)
        if not u or r['face'] not in u:
            bad.append('%s/%s 在报告 §C 里没有该面（凭空条目？）' % (r['unit'], r['face']))
            continue
        per[r['face']] += r['count']
        cell[(stem, r['face'])] += r['count']
    for (stem, face), n in sorted(cell.items()):
        miss = ((units or {}).get(stem) or {}).get(face, {}).get('misses', 0)
        if n > miss:
            bad.append('%s/%s 豁免 %d > 报告该格 misses %d' % (stem, face, n, miss))
    for face, n in sorted(per.items()):
        miss = sum((u.get(face) or {}).get('misses', 0) for u in (units or {}).values())
        if n > miss:
            bad.append('%s 面豁免 %d > 报告该面 misses %d' % (face, n, miss))
    return per, bad


def _exempt_echo_code(rows, per, roll, note):
    """豁免回显串（消息用）：逐条给出 面／单元／行／项数／依据／归属／清单行号 ＋ 扣除后面值。

    这段文本**同时是反"凑达标"的公开面**：读者可据此逐条回原始清单与报告复核（硬边界③）。
    """
    bits = []
    for r in rows:
        bits.append('%s %s:%s ×%d（依据 §7 第 %s 行；归属 %s）'
                    % (r['face'], r['unit'], '、'.join(str(n) for n in r['lines']), r['count'],
                       r['basis'], r['owner'][:36]))
    eff = []
    for f in M3_CODE_COV_FACES:
        v = roll.get(f) or {}
        n = per.get(f, 0)
        if not n:
            continue
        den = max(0, (v.get('bins') or 0) - n)
        pct = (100.0 * v.get('hits', 0) / den) if den else None
        eff.append('%s %s/%d = %s' % (f, v.get('hits'), den,
                                      '%.2f%%' % pct if pct is not None else '无数据'))
    return (' ｜ [列缺豁免（R0 2026-09-26 授权；`doc/verify/02` §7 豁免集第 %s 行起）] 本次豁免 %d 条：'
            '%s ｜ 扣除后：%s ｜ **仅限**清单内、依据可查的条目；**不得**新增/改写列缺条目凑达标'
            '（本判据已用报告现值设反向上界：报告没报缺的项豁免不了）；豁免**不改**任何 bin／采样条件／'
            '阈值／检查器逻辑（红线 R6/R7）'
            % (note.get('ex_line'), len(rows), '；'.join(bits[:8]) or '(无)', '；'.join(eff)))


def _report_block(txt, start, ends):
    """取报告中**含标记 `start` 的分节行**之后的正文（止于含 `ends` 中任一项的行）。找不到 ⇒ None。

    注意：报告的分节标记行形如 `──────── §A `vcover report …` ────────`（**不以 `§A` 起头**），
    故用「行内含标记」而不是「行首匹配」；标记本身取足够长的片段，避免命中头部自述里对 §A/§C 的**引用**
    （如「§C 原文」「§A（`-cvg -detail`…）」——那些行不含本函数用的长标记）。
    """
    lines = txt.splitlines()
    lo = None
    for i, ln in enumerate(lines):
        if start in ln:
            lo = i
            break
    if lo is None:
        return None
    for j in range(lo + 1, len(lines)):
        if any(e in lines[j] for e in ends):
            return '\n'.join(lines[lo + 1:j])
    return '\n'.join(lines[lo + 1:])


def _cov_evidence():
    """覆盖率证据的**时效面**核（fail-closed）：返回 (错误串 | None, {'fp','txt','rep','live'})。

    与 `chk_m2_cov` 的①②③④⑤**同口径**（机制件在册／指纹在册可解析／rtl.f md5 == 当前＋逐单元
    md5 == 现盘／报告落在 `doc/verify/07-*.txt` 且字节数与内嵌 md5 均与指纹相符／合并件在册）。
    这里**不复用 chk_m2_cov 的函数体**而另立一处，是为了不让 M3 的改动碰到 M2 那条**已 PASS** 的判据
    （口径相同、实现独立；两处都在读同一对文件 ⇒ 无法用"改判据凑绿"）
    """
    mech = os.path.join(ROOT, 'run_cmd', 'cover_rv1.py')
    if not os.path.exists(mech):
        return '缺机制件 %s（fail-closed）⇒ 跑 `python run_cmd/cover_rv1.py`' % rel(mech), None
    if not os.path.exists(COV_FP):
        return '缺编译指纹 %s（fail-closed）⇒ 跑 `python run_cmd/cover_rv1.py`' % rel(COV_FP), None
    fp = load_json(COV_FP, default=None)
    if not isinstance(fp, dict):
        return '%s 不可解析（fail-closed）' % rel(COV_FP), None
    if not os.path.exists(RTL_F):
        return '缺 %s（fail-closed）' % rel(RTL_F), None
    live = md5_of(RTL_F)
    rf = fp.get('rtl_filelist') or {}
    if rf.get('path') != 'filelist/rtl.f' or not rf.get('md5'):
        return '指纹缺 `rtl_filelist`（path=filelist/rtl.f ＋ md5；fail-closed）', None
    if rf['md5'] != live:
        return ('证据过期：指纹的 rtl.f md5=%s ≠ 当前 filelist/rtl.f md5=%s ⇒ 重跑 '
                '`python run_cmd/cover_rv1.py`（M3 阈值面**不因过期而放宽**）' % (rf['md5'], live)), None
    err = _fingerprint_unit_check(fp, '指纹', '；⇒ 重跑 `python run_cmd/cover_rv1.py`')
    if err:
        return err, None
    rep = (fp.get('report') or {}).get('path')
    if not rep:
        return '指纹缺 `report.path`（fail-closed）', None
    if not (rep.startswith('doc/verify/07-') and rep.endswith('.txt')):
        return '报告路径 %s 不落 `doc/verify/07-*.txt`（fail-closed）' % rep, None
    rp = os.path.join(ROOT, rep)
    if not os.path.exists(rp):
        return '覆盖率报告不在册：%s（指纹声明；fail-closed）' % rep, None
    size = os.path.getsize(rp)
    if size <= 0 or size != int((fp.get('report') or {}).get('size', -1)):
        return ('报告 %s 现盘 %d B ≠ 指纹记录 %s B（报告被事后改动／与指纹不同批；fail-closed）'
                % (rep, size, (fp.get('report') or {}).get('size'))), None
    txt = io.open(rp, 'r', encoding='utf-8', errors='replace').read()
    m = RE_REPORT_RTL_MD5.search(txt)
    if not m:
        return '报告 %s 无可解析的 `RTL filelist md5=<32hex>`（fail-closed）' % rep, None
    if m.group(1) != live:
        return ('报告 %s 内嵌 rtl.f md5=%s ≠ 当前 %s（报告与当前 RTL 不同版本 ⇒ 过期；重跑 '
                '`python run_cmd/cover_rv1.py`）' % (rep, m.group(1), live)), None
    return None, {'fp': fp, 'txt': txt, 'rep': rep, 'live': live}


def _report_dut_rollup(txt):
    """从报告 §C 逐实例节**独立复算** DUT 面 Σhits/Σbins（返回 (过卷, 错误串)）。

    口径：只收 `Design Unit: work.<名>` 的 `<名>` ∈ `filelist/rtl.f` 编译单元名集合（模块名=文件
    stem）的实例节——与 `run_cmd/cover_rv1.py:_rollup` 同口径但**实现独立**（两实现结果须一致，
    不一致即"证据不可信"⇒ 调用方 FAIL）。
    """
    body = _report_block(txt, '§C DUT 面（', ('§D `vcover report -assert -detail`',))
    if body is None:
        return None, '报告缺 §C 分节（DUT 面代码覆盖率；fail-closed）'
    units, _ = _parse_f_list(RTL_F)
    stems = set()
    for u in units:
        p = '/' + u.replace('\\', '/').lstrip('/')
        if '/rtl/vr1/' in p:
            stems.add(os.path.basename(p).rsplit('.', 1)[0])
    if not stems:
        return None, '`filelist/rtl.f` 解析不到 rtl/vr1/** 编译单元（fail-closed）'
    secs, cur_u, cur = [], None, []
    for ln in body.splitlines():
        m = RE_DESIGN_UNIT.match(ln)
        if m:
            if cur_u is not None:
                secs.append((cur_u, cur))
            cur_u, cur = m.group(1), []
        else:
            cur.append(ln)
    if cur_u is not None:
        secs.append((cur_u, cur))
    kept = [(u, b) for u, b in secs if u in stems]
    if not kept:
        return None, ('§C 未识别到任何 DUT 面实例节（rtl.f 单元名集合 %s；fail-closed）'
                      % '、'.join(sorted(stems)[:4]))
    roll = {}
    for _u, blk in kept:
        for g in RE_COV_METRIC.finditer('\n'.join(blk)):
            k, bins, hits = g.group(1).strip(), int(g.group(2)), int(g.group(3))
            a = roll.setdefault(k, [0, 0])
            a[0] += bins
            a[1] += hits
    return ({k: {'bins': v[0], 'hits': v[1], 'pct': (100.0 * v[1] / v[0] if v[0] else None)}
             for k, v in roll.items()},
            {'units_kept': len(kept), 'units_all': len(stems)})


def _fmt_faces(roll, faces):
    """把四项现值排成一行（缺失面记 `无数据`；`pct` 取一位小数）。"""
    bits = []
    for f in faces:
        v = roll.get(f)
        bits.append('%s %s' % (f, '无数据' if not v or v.get('pct') is None
                               else '%.2f%%（%d/%d）' % (v['pct'], v['hits'], v['bins'])))
    return '；'.join(bits)


def _fmt_faces_eff(roll, per):
    """**扣除豁免后**的四项面值（仅当豁免集非空时用；空集走 `_fmt_faces` 保持逐字一致）。"""
    bits = []
    for f in M3_CODE_COV_FACES:
        v = roll.get(f) or {}
        n = per.get(f, 0)
        if not v or v.get('pct') is None:
            bits.append('%s 无数据' % f)
            continue
        den = max(0, v['bins'] - n)
        pct = (100.0 * v['hits'] / den) if den else None
        rest = max(0, den - v['hits'])
        bits.append('%s %s（%d/%d%s；余 %d 处未命中仍计入分母）'
                    % (f, '无数据' if pct is None else '%.2f%%' % pct, v['hits'], den,
                       '' if not n else '，原 %d/%d 扣列缺豁免 %d' % (v['hits'], v['bins'], n), rest))
    return '；'.join(bits)


def chk_m3_code_cov():
    """m3-code-cov（M3 exit (a)）：**代码覆盖率四项逐项 ≥90%**（AGENTS.md §4）＋证据时效＋列缺豁免。

    判据（**只核证据＋时效**，不重跑重活；全部 fail-closed）：
      ① 证据时效＝`_cov_evidence()` 全过（指纹与**当前** `filelist/rtl.f` 同版本、逐单元 md5 相符、
         报告在册且字节数/内嵌 md5 与指纹相符、合并件在册）；过期即 FAIL 并提示重跑机制件；
      ② 从报告 §C（DUT 面＝`rtl/vr1/**` 编译单元实例节）**独立复算** Σhits/Σbins，取
         `Statements`／`Branches`／`Conditions`／`FSM Transitions` 四项，**每项须 ≥ `M3_CODE_COV_FLOOR`**；
      ③ 两实现互证：复算结果须与指纹的 `dut_face_rollup_selfcomputed`（`cover_rv1.py` 自算）逐项一致，
         不一致 ⇒ 证据不可信，FAIL（fail-closed）；
      ④ **列缺豁免**（R0 2026-09-26 授权）：解析 `doc/verify/02` §7 的「豁免集」子表得到豁免集，
         **从分母扣除**该集内的项后判 ②。四条硬边界（同文见 §7 与该子表表头）：
         ①豁免**仅限**清单内、依据可查的条目（每条须回指非「已纳入／处置项」的 `CC-` 主表行 ＋
         带非空归属 ＋ 行号能在 `filelist/rtl.f` 在册单元源码里落到非空行）；
         ②豁免**不改**任何 bin／采样条件／阈值／检查器逻辑（红线 R6／R7），只改**分母口径**；
         ③**不得**靠新增／改写列缺条目凑达标——判据用报告现值设**反向上界**（同一 单元×面 ≤ 报告
         该格 misses、同一面 ≤ 该面 misses），**报告没报缺的项豁免不了**，并把每条豁免的依据与
         清单行号回显进消息；
         ④**豁免集为空时行为与消息与本机制落地前逐字一致**；而"清单本体解析不到"（缺清单／缺 §7
         节／节内无 `CC-` 主表行／子表行不合规）一律 FAIL（fail-closed）。
    阈值**取 `AGENTS.md` §4 原文**、不设"本批先不判"的过渡口径；未达标即如实 FAIL 并给出四项现值与缺口
    （不给"差多少就调阈值"的余地——调阈值＝红线 R6/R7 的放宽）。
    """
    err, dat = _cov_evidence()
    if err:
        return False, err
    roll, extra = _report_dut_rollup(dat['txt'])
    if roll is None:
        return False, '%s ｜ 报告 %s' % (extra, rel(os.path.join(ROOT, dat['rep'])))
    ex_rows, ex_note, xerr = _verify02_code_exemptions()
    if xerr:
        return False, ('列缺豁免解析失败：%s ｜ 报告 %s' % (xerr, rel(os.path.join(ROOT, dat['rep']))))
    per, xbad = _exempt_bound_check(ex_rows, _report_dut_units(dat['txt']), ex_note)
    if xbad:
        return False, ('列缺豁免集与报告现值相抵（fail-closed，拒判）：%s ｜ 清单 `doc/verify/02` §7'
                       '「豁免集」第 %s 行起 ｜ 反向上界口径＝同一 单元×面 的豁免项数 ≤ 报告该格 misses、'
                       '同一面 ≤ 该面 misses（报告没报缺的项豁免不了；凑达标在机制上不可行）'
                       % ('；'.join(xbad[:4]), ex_note.get('ex_line')))
    xecho = _exempt_echo_code(ex_rows, per, roll, ex_note) if ex_rows else ''
    eff = {}
    for f in M3_CODE_COV_FACES:
        v = roll.get(f) or {}
        den = (v.get('bins') or 0) - per.get(f, 0)
        eff[f] = (100.0 * v.get('hits', 0) / den) if den > 0 else None
    faces = _fmt_faces_eff(roll, per) if ex_rows else _fmt_faces(roll, M3_CODE_COV_FACES)
    bad = [f for f in M3_CODE_COV_FACES
           if eff.get(f) is None or eff[f] < M3_CODE_COV_FLOOR]
    fp_roll = (dat['fp'].get('coverage_numbers_as_is') or {}).get('dut_face_rollup_selfcomputed') or {}
    mism = []
    for f in M3_CODE_COV_FACES:
        a, b = roll.get(f) or {}, fp_roll.get(f) or {}
        if b and (a.get('bins'), a.get('hits')) != (b.get('bins'), b.get('hits')):
            mism.append('%s 复算 %s/%s ≠ 指纹自算 %s/%s'
                        % (f, a.get('hits'), a.get('bins'), b.get('hits'), b.get('bins')))
    if mism:
        return False, ('证据不可信：报告 §C 复算 与 指纹 `dut_face_rollup_selfcomputed` 不一致：%s'
                       '（fail-closed）⇒ 重跑 `python run_cmd/cover_rv1.py`' % '；'.join(mism))
    if bad:
        return False, ('代码覆盖率**未达 AGENTS.md §4 的 ≥%d%%（逐项）**：%s ｜ 未达项：%s ｜ '
                       '证据 %s（batch=%s，rtl.f md5=%s == 当前）｜ §C 复算与指纹自算逐项一致（%d/%d 单元节）'
                       '｜ 补法＝**补激励**（该阈值不因未达而放宽；红线 R6/R7）%s'
                       % (int(M3_CODE_COV_FLOOR), faces, '、'.join(bad), rel(os.path.join(ROOT, dat['rep'])),
                          dat['fp'].get('batch'), dat['live'][:8], extra['units_kept'], extra['units_all'],
                          xecho))
    return True, ('代码覆盖率四项逐项 ≥%d%%：%s ｜ 证据 %s（batch=%s，rtl.f md5=%s == 当前，'
                  '§C 复算与指纹自算逐项一致）%s'
                  % (int(M3_CODE_COV_FLOOR), faces, rel(os.path.join(ROOT, dat['rep'])),
                     dat['fp'].get('batch'), dat['live'][:8], xecho))


def _cvg_model_vp_map():
    """从覆盖模型件的**头部「覆盖模型清单」块**解析 `CG<n> `<covergroup>` —— VP-xx／…` 映射。

    返回 (映射 | None, 错误串)。为什么锚这里：VP 清单（`doc/verify/02`）是**文字**，覆盖率报告里只有
    covergroup **名字**，两者之间唯一的机械映射就是该件头明写的「CG→VP」清单（该件自述"每条 bin 的
    注释给 VP 号"）。块边界＝含「覆盖模型清单」的注释行起，到含「口径与纪律」的注释行止（找不到即 FAIL）。
    """
    if not os.path.exists(M3_COV_MODEL):
        return None, '缺覆盖模型件 %s（fail-closed；功能覆盖面无可核的 VP 映射）' % rel(M3_COV_MODEL)
    lines = io.open(M3_COV_MODEL, 'r', encoding='utf-8', errors='replace').read().splitlines()
    lo = hi = None
    started = False
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s.startswith('//'):
            if lo is not None and hi is None:
                hi = i
                break
            continue
        body = s.lstrip('/').strip()
        if lo is None:
            if '覆盖模型清单' in body:
                lo = i
            continue
        if hi is not None:
            break
        # 块内：只收「CG 声明行」与其**续行**（含 VP 号）；空注释行/别的块标题即止
        if RE_CG_DECL.search(body):
            started = True
            continue
        if started and RE_VP_TOKEN.search(body):
            continue
        hi = i
        break
    if lo is None:
        return None, ('%s 头部未找到「覆盖模型清单」块（fail-closed：VP→covergroup 映射不可判）'
                      % rel(M3_COV_MODEL))
    hi = hi if hi is not None else len(lines)
    text = '\n'.join(lines[lo:hi])
    hits = list(RE_CG_DECL.finditer(text))
    if not hits:
        return None, ('%s 的「覆盖模型清单」未声明 `CG<n> `<covergroup>` —— VP-…` 映射'
                      '（fail-closed；不得无映射就宣称"已纳入判定范围"）' % rel(M3_COV_MODEL))
    out = {}
    for i, m in enumerate(hits):
        seg = text[m.end():hits[i + 1].start() if i + 1 < len(hits) else len(text)]
        out[m.group(2)] = sorted(set(RE_VP_TOKEN.findall(seg)))
    no_vp = sorted(k for k, v in out.items() if not v)
    if no_vp:
        return None, ('覆盖模型清单里 %s 未挂任何 VP 号（fail-closed：无法据「已纳入判定范围的 VP 项」'
                      '判 100%%）' % '、'.join(no_vp))
    return out, None


def _report_cvg(txt):
    """取报告 §A 的 covergroup 面：{cg 名: {'covered','total','missing':[缺 bin],'dup':bool}} + 合计行。

    返回 (数据 | None, 错误串)。逐 bin 明细只在 `Covergroup instance …` 分节里；同一 covergroup 在
    §A 出现两处（明细段与 `COVERGROUP COVERAGE` 汇总段），两处数字若不一致 ⇒ FAIL（工具面自相矛盾）。
    """
    body = _report_block(txt, '§A `vcover report -cvg -detail`', ('§B `vcover report -code sbcef`',))
    if body is None:
        return None, '报告缺 §A 分节（`vcover report -cvg -detail`；fail-closed）'
    if 'No matching coverage data' in body:
        return None, ('报告 §A **无功能覆盖数据**（vcover 报 `No matching coverage data found`）⇒ '
                      '功能覆盖率不是"未达标"而是"未在环"（fail-closed；先补 covergroup 激励面）')
    insts = list(RE_CVG_INST.finditer(body))
    if not insts:
        return None, '报告 §A 无 `Covergroup instance` 分节（fail-closed：功能覆盖面无逐 bin 证据）'
    out = {}
    for i, m in enumerate(insts):
        name = m.group(1).replace('\\', '').rstrip('/').rsplit('/', 1)[-1]
        name = re.sub(r'_i$', '', name)
        seg = body[m.end():insts[i + 1].start() if i + 1 < len(insts) else len(body)]
        pair = RE_CVG_BINS_PAIR.search(seg)
        if not pair:
            return None, ('报告 §A 的 covergroup `%s` 分节无 `covered/total bins:` 行（fail-closed）' % name)
        rec = {'covered': int(pair.group(1)), 'total': int(pair.group(2)),
               'missing': [g.group(1) for g in RE_CVG_BIN_ZERO.finditer(seg)], 'dup': False}
        if name in out and (out[name]['covered'], out[name]['total']) != (rec['covered'], rec['total']):
            rec['dup'] = True
        out[name] = rec
    m_tot = RE_CVG_TOTAL.search(txt)
    m_ty = RE_CVG_TYPES.search(txt)
    return {'cgs': out, 'total_line': m_tot.group(0).strip() if m_tot else None,
            'types': int(m_ty.group(1)) if m_ty else None}, None


def _verify02_gap_ownership():
    """核 `doc/verify/02` 是否**显式列出「未纳入（功能覆盖判定范围）」的项并逐条带归属**。

    返回 (问题清单, 附注串)。口径（机械、fail-closed；缺列即 FAIL）：
      ① 该篇须有**标题含「未纳入」**的节（`##`~`####`）；
      ② 该节须有 ≥1 条表体行（列「未纳入项」）；
      ③ 每行须带**归属 token**（`doc|spec|rtl|tb|iss|sw|sim|run_cmd|filelist/路径` 或
         `M<n>…` 里程碑/步骤号 或 `ADR-P<n>`／`ADR-P-<n>` 号）——"归属"＝该缺口由哪件/哪步闭合。
    为什么这么判：`doc/verify/02` §3 现有「本清单不含：…」只声明**类别**（用例文件、bin 定义归 06/07），
    不列**未纳入判定的 VP 项**本身 ⇒ 读者无法据此知道"哪些 VP 尚未进功能覆盖判定、各由谁闭合"。
    """
    if not os.path.exists(VERIFY02):
        return ['缺 %s（fail-closed）' % rel(VERIFY02)], ''
    lines = _doc_lines(VERIFY02)
    hd = [(i, re.match(r'^(#{2,4})\s+(.*)$', ln)) for i, ln in enumerate(lines)]
    lo = lvl = None
    for i, m in hd:
        if m and '未纳入' in m.group(2):
            lo, lvl = i, len(m.group(1))
            break
    if lo is None:
        return (['`doc/verify/02` **无标题含「未纳入」的节** ⇒ "未纳入项"缺列带归属（缺列即 FAIL）'], '')
    hi = len(lines)
    for i, m in hd:
        if m and i > lo and len(m.group(1)) <= lvl:
            hi = i
            break
    tabs = md_tables(lines, lo, hi)
    rows = [r for _h, _c, rs in tabs for r in rs]
    if not rows:
        return (['`doc/verify/02`「未纳入」节（第 %d 行起）**无表体行** ⇒ 未逐条列缺（缺列即 FAIL）'
                 % (lo + 1)], '')
    bad = []
    for ln_no, cells in rows:
        if not RE_OWNER.search(' '.join(cells)):
            bad.append('第 %d 行「%s」' % (ln_no, (cells[0] if cells else '?')[:24]))
    notes = ('「未纳入」节第 %d 行起，%d 条表体行' % (lo + 1, len(rows)))
    if bad:
        return (['`doc/verify/02`「未纳入」节有 %d 行**未给归属 token**（口径：路径式归属件／'
                 '`M<n>` 步骤号／ADR 号）：%s' % (len(bad), '、'.join(bad[:4]))], notes)
    return [], notes


def chk_m3_func_cov():
    """m3-func-cov（M3 exit (b)）：**已纳入判定范围的 VP 项 100% 命中** ＋ 未纳入项列缺带归属 ＋ 列缺豁免。

    判据（只核证据＋时效；fail-closed）：
      ① 证据时效＝`_cov_evidence()` 全过（同 (a)：报告须与**当前** RTL 同批）；
      ② 报告 §A 有功能覆盖数据（`No matching coverage data` ⇒ FAIL：不是"未达标"而是"未在环"）；
      ③ 映射：`_cvg_model_vp_map()` 从覆盖模型件头部「覆盖模型清单」取 `CG→VP` 声明（**已纳入判定
         范围的 VP 项**由此确定；声明缺失/某 CG 未挂 VP ⇒ FAIL）；
      ④ **逐 CG**：该 CG 必须在报告 §A 出现，且 `covered == 有效分母`（＝已纳入的 VP 项 100% 命中）；
         未达标如实 FAIL 并给出**缺 bin 清单**（`ZERO` 状态逐条）＋所挂 VP 号（供下一轮补激励）；
         同一 CG 两处数字不一致 ⇒ FAIL（工具面自相矛盾）；
         —— 其中 `t_req_idle`/`t_rsp_idle` 两 bin 经 R0 2026-09-26 裁定走**受控复位注入通道**
         （NU-2：仅覆盖率批 `rst_*` 条目；见 M3_FUNC_COV_CONTROLLED_BINS），**判定口径不变**；
      ⑤ **列缺豁免**（R0 2026-09-26 授权）：解析 `doc/verify/02`「未纳入」节表体首列的反引号 token
         得到候选条目名，**只对「候选 ∩ 报告 §A 当前 missing bin」生效**（报告没报缺的 bin 豁免不了
         ＝反向上界），命中者**从该 CG 的分母扣除**后再判 ④。四条硬边界（同文见该节与该节表头）：
         ①豁免**仅限**清单内、依据可查的条目（须带归属；归属缺失另由 `_verify02_gap_ownership` 判红）；
         ②豁免**不改**任何 bin／采样条件／阈值／检查器逻辑（红线 R6／R7），只改**分母口径**；
         ③**不得**靠新增／改写列缺条目凑达标——每条豁免的来源行号与依据／归属**回显进消息**供人工复核；
         ④**豁免集为空时行为与消息与本机制落地前逐字一致**；而"清单本体解析不到"（缺清单／缺
         「未纳入」节／节内无表体行）一律 FAIL（fail-closed）。
      ⑥ `doc/verify/02` 的「未纳入项」须**显式列缺带归属**（`_verify02_gap_ownership`；缺列即 FAIL）。
    **不判**沙箱 `sim/run_cover_*/**` 的逐例 ucdb（可清理区；口径同 `m2-cov`）。
    """
    err, dat = _cov_evidence()
    if err:
        return False, err
    cvg, cerr = _report_cvg(dat['txt'])
    if cvg is None:
        return False, '%s ｜ 报告 %s' % (cerr, rel(os.path.join(ROOT, dat['rep'])))
    vpm, verr = _cvg_model_vp_map()
    if vpm is None:
        return False, verr
    exbins, ex_note, xerr = _verify02_func_exemptions()
    if xerr:
        return False, ('列缺豁免解析失败：%s ｜ 报告 %s' % (xerr, rel(os.path.join(ROOT, dat['rep']))))
    used = {}
    bad, missing_desc = [], []
    for cg in sorted(vpm):
        rec = cvg['cgs'].get(cg)
        if rec is None:
            bad.append('CG `%s`（%s）**未出现在报告 §A**（fail-closed）' % (cg, '／'.join(vpm[cg])))
            continue
        if rec['dup']:
            bad.append('CG `%s` 在 §A 两处数字不一致（fail-closed）' % cg)
            continue
        ex_b = [b for b in rec['missing'] if b in exbins]
        for b in ex_b:
            used.setdefault(b, exbins[b])
        eff_total = rec['total'] - len(ex_b)
        if rec['covered'] < eff_total:
            miss = [b for b in rec['missing'][:8] if b not in ex_b] or \
                ['(工具未列 ZERO bin，按总数差计)']
            ctrl = [b for b in miss if b in M3_FUNC_COV_CONTROLLED_BINS]
            note = ('（其中 %s 经 R0 2026-09-26 裁定走受控复位注入通道（NU-2；仅覆盖率批 '
                    '`rst_*` 条目），判定口径不变——仍要求命中）' % '、'.join(ctrl)) if ctrl else ''
            bad.append('CG `%s` %d/%d bins（%s）缺 bin：%s%s'
                       % (cg, rec['covered'], eff_total, '／'.join(vpm[cg]),
                          '、'.join(miss), note))
            missing_desc.append('%s 缺 %d 个 bin' % (cg, eff_total - rec['covered']))
    gap_issues, gap_note = _verify02_gap_ownership()
    bad.extend(gap_issues)
    cg_bits = []
    for cg in sorted(vpm):
        if cg not in cvg['cgs']:
            continue
        rec, n = cvg['cgs'][cg], sum(1 for b in cvg['cgs'][cg]['missing'] if b in exbins)
        cg_bits.append('%s %d/%d%s' % (cg, rec['covered'], rec['total'] - n,
                                       '' if not n else '（原 %d/%d，扣列缺豁免 %d）'
                                       % (rec['covered'], rec['total'], n)))
    faces = '功能覆盖合计行 %s ｜ 逐 CG：%s' % (cvg['total_line'] or '(未解析到 TOTAL 行)',
                                              '；'.join(cg_bits) or '(无)')
    xecho = ''
    if used:
        def _cut(cell, n=52):
            s = strip_md(cell or '')
            return s[:n] + '…' if len(s) > n else s
        bits = ['`%s`（`doc/verify/02` §6 第 %d 行；依据摘录：%s；归属摘录：%s）'
                % (b, used[b][0], _cut(used[b][1][3]) if len(used[b][1]) > 3 else '?',
                   _cut(used[b][1][4]) if len(used[b][1]) > 4 else '?')
                for b in sorted(used)]
        xecho = (' ｜ [列缺豁免（R0 2026-09-26 授权；`doc/verify/02`「未纳入」节第 %s 行起）] 本次豁免 '
                 '%d 个 bin：%s ｜ **仅限**清单内、依据可查的条目；**不得**新增/改写列缺条目凑达标'
                 '（判据已设反向上界：报告没报缺的 bin 豁免不了）；豁免**不改**任何 bin／采样条件／'
                 '阈值／检查器逻辑（红线 R6/R7）'
                 % (ex_note.get('sec_line'), len(used), '；'.join(bits[:6])))
    if bad:
        return False, ('功能覆盖**未达 100%%（已纳入判定范围的 VP 项）**：%s ｜ 缺项：%s ｜ '
                       '映射件 %s（覆盖模型清单：%s）｜ 证据 %s（batch=%s，rtl.f md5=%s == 当前）｜ '
                       '`doc/verify/02`：%s ｜ 补法＝**补定向激励**（红线 R7：禁删 bin／改采样条件／waiver）%s'
                       % (faces, '；'.join(bad[:6]),
                          rel(M3_COV_MODEL),
                          '；'.join('%s↔%s' % (k, '／'.join(vpm[k])) for k in sorted(vpm)),
                          rel(os.path.join(ROOT, dat['rep'])), dat['fp'].get('batch'), dat['live'][:8],
                          gap_note or '(无「未纳入」节)', xecho))
    return True, ('功能覆盖 100%%（已纳入判定范围的 VP 项）：%s ｜ 映射件 %s ｜ 证据 %s（batch=%s，'
                  'rtl.f md5=%s == 当前）｜ `doc/verify/02`：%s%s'
                  % (faces, rel(M3_COV_MODEL), rel(os.path.join(ROOT, dat['rep'])),
                     dat['fp'].get('batch'), dat['live'][:8], gap_note, xecho))


def chk_m3_regress_stab():
    """m3-regress-stab（M3 exit (c)）：**同配置 ≥3 轮全过 ＋ 轮间 0 新 FAIL ＋ 与当前 RTL 同指纹**。

    判据（只核证据＋时效；不重跑重活；fail-closed）：
      ① 机制件在册（`run_cmd/regress_rv1.py` ＋ `run_cmd/rv64ui_testlist.txt`）；
      ② **候选轮次**＝`sim/run_regress_*/` 里三件产物（summary/config/cases）齐备、且
         `config.fingerprint.rtl_filelist.md5 == 当前 rtl.f md5` 的轮次（＝**本版本**的轮次；旧版本轮次
         **不计入**但在结论里点明条数，不静默丢）；按 config 的**同配置签名**（除逐轮身份字段
         `REGRESS_IGNORE_KEYS` 外逐字段）分组，取**轮数最多**的那组（并列取最近一轮更晚者）；
      ③ 该组须 **≥ `M3_REG_MIN_ROUNDS` 轮**，且**每轮**过 `_regress_round_evidence`（summary 尾行
         `REGRESSION_PASS`、counts total==pass 且 fail/timeout/fatal/skip 全 0、cases/config 自洽、
         R9/R10 在环、指纹逐单元 md5 == 现盘）——逐轮口径与 `m2-regress` 同源，**不放宽**；
      ④ **轮间 0 新 FAIL**：按时间序**独立复算**（比 `cases.json` 的 FAIL 用例集合，不比原因文本）；
         若头轮沙箱有配对 `round_diff.txt`（base==前一轮），另核其自报 `new_fail==0`／`same_config==yes`
         （两实现互证；不符 ⇒ 证据不可信，FAIL）；
      ⑤ **证据时效口径（R0 2026-09-26 认可，明文写死防误读）**：回归证据的"版本"校验**只锚 RTL 面**
         （`filelist/rtl.f` 的 md5 ＋ 逐单元 md5 == 现盘）；**TB 面（`filelist/tb_m1_e2e.f` 及其
         所列文件）不进版本校验**——这是**现状即合规的明文**，不是漏洞：TB 变更后既有轮次仍按
         "本版本（rtl.f 未变）"计入，但 TB 面证据已过期 ⇒ **需人工按需重跑轮次**补齐
         （本判据不因此自动 FAIL，也不自动重跑）。

    为什么自己算而不只读 `round_diff`：`--diff` 的产物**只覆盖人挑的那一对**轮次，3 轮两两之间未必都有；
    本判据的零新 FAIL 面因此**自带复算**（`run_cmd/regress_rv1.py` 的 `--diff` 仍可作旁证）。
    """
    for p in (os.path.join(ROOT, 'run_cmd', 'regress_rv1.py'),
              os.path.join(ROOT, 'run_cmd', 'rv64ui_testlist.txt')):
        if not os.path.exists(p):
            return False, '缺机制件 %s（fail-closed；M3 exit (c) 无法判）' % rel(p)
    if not os.path.exists(RTL_F):
        return False, '缺 %s（fail-closed）' % rel(RTL_F)
    live = md5_of(RTL_F)
    cands, stale = [], []
    for d in sorted(glob.glob(os.path.join(ROOT, 'sim', 'run_regress_*'))):
        rid = os.path.basename(d)[len('run_regress_'):]
        if not (os.path.exists(os.path.join(d, 'summary.txt'))
                and os.path.exists(os.path.join(d, 'config.json'))
                and os.path.exists(os.path.join(d, 'cases.json'))):
            continue
        cfg = load_json(os.path.join(d, 'config.json'), default=None)
        if not isinstance(cfg, dict):
            continue
        md5 = ((cfg.get('fingerprint') or {}).get('rtl_filelist') or {}).get('md5')
        (cands if md5 == live else stale).append(
            (cfg.get('started') or '', rid, cfg))
    if not cands:
        return False, ('无**本版本**（rtl.f md5=%s）的回归轮次（候选 %d 个旧版本轮次不计入：%s）⇒ '
                       '跑 `python run_cmd/regress_rv1.py --runner-id <新id> --round 1`（每轮独占沙箱，'
                       '红线 R10）' % (live[:8], len(stale), '、'.join(x[1] for x in stale[:6])))
    groups = {}
    for started, rid, cfg in cands:
        sig = json.dumps({k: v for k, v in cfg.items() if k not in REGRESS_IGNORE_KEYS},
                         sort_keys=True, ensure_ascii=False)
        groups.setdefault(sig, []).append((started, rid))
    pool = max(groups.values(), key=lambda g: (len(g), max(x[0] for x in g)))
    pool = sorted(pool)
    if len(pool) < M3_REG_MIN_ROUNDS:
        return False, ('本版本同配置的回归轮次只有 %d 轮（%s）＜ %d 轮（AGENTS.md §4 稳定性面；'
                       '其余 %d 轮为异配置/旧版本，不计入）⇒ 再跑第 %d 轮：'
                       '`python run_cmd/regress_rv1.py --runner-id <新id> --round %d`（红线 R10 独占沙箱）'
                       % (len(pool), '、'.join(x[1] for x in pool), M3_REG_MIN_ROUNDS,
                          len(cands) - len(pool), len(pool) + 1, len(pool) + 1))
    info = {}
    for _started, rid in pool:
        err, dat = _regress_round_evidence(rid)
        if err:
            return False, '%s ｜ 判据面＝本版本同配置 %d 轮（%s）' % (err, len(pool),
                                                                  '、'.join(x[1] for x in pool))
        info[rid] = dat
    # 轮间 0 新 FAIL：**独立复算**（逐例 FAIL 集合，不比原因文本）
    runs = [rid for _s, rid in pool]
    for a, b in zip(runs, runs[1:]):
        fa = {c.get('name') for c in (load_json(os.path.join(_round_dir(a), 'cases.json'),
                                                default={}) or {}).get('cases', [])
              if c.get('status') != 'PASS'}
        fb = {c.get('name') for c in (load_json(os.path.join(_round_dir(b), 'cases.json'),
                                                default={}) or {}).get('cases', [])
              if c.get('status') != 'PASS'}
        if fb - fa:
            return False, ('轮间**新 FAIL**：%s → %s 新增 %d 例：%s（复算自 cases.json；fail-closed）'
                           % (a, b, len(fb - fa), '、'.join(sorted(fb - fa)[:5])))
        rd = os.path.join(_round_dir(b), 'round_diff.txt')
        if os.path.exists(rd):
            m = RE_ROUND_DIFF.search(io.open(rd, 'r', encoding='utf-8').read())
            if m and m.group(1) == a:
                if int(m.group(3)) or m.group(7) != 'yes':
                    return False, ('配对 round_diff（base=%s head=%s）自报 new_fail=%s same_config=%s '
                                   '（与复算不符/口径未达；fail-closed）⇒ %s'
                                   % (a, b, m.group(3), m.group(7), rel(rd)))
    c = info[runs[-1]]['counts']
    return True, ('本版本同配置 %d 轮全过且轮间 0 新 FAIL（%s；各 total=%d pass=%d fail=0 '
                  'timeout/fatal/skip=0）｜ 轮间零新 FAIL＝**独立复算**（cases.json 的 FAIL 集合，'
                  '不比原因文本）｜ R10 jobs=%s≤%d 沙箱独占 ｜ 版本：%d 轮 rtl.f md5=%s == 当前'
                  '（逐单元 md5 复核 %d 个 RTL 单元）｜ 回归证据时效**只锚 RTL 面**（TB 面不进版本'
                  '校验——R0 2026-09-26 认可；TB 变更后需人工重跑轮次）｜ 另有 %d 个旧版本轮次不计入'
                  % (len(runs), '、'.join(runs), c['total'], c['pass'],
                     info[runs[-1]]['cfg'].get('jobs'), M2_R10_MAX_JOBS, len(runs), live[:8],
                     info[runs[-1]]['n_units'], len(stale)))


def chk_tb_compile():
    """tb-compile（GI-13 的 TB 侧首件；**常跑守卫**，不进 M1 的 exit）：真实 vlog 编译 `filelist/tb_unit.f`。

    判据（与 `rtl-compile` **同一口径**，恕不放宽）：
      ① vlog 段末自报 `Errors: 0`；② `-- Compiling` 计数 == 清单编译单元条目数；③ 退出码 0。

    为什么另立清单与判据，而不是把 TB 件并进 `rtl-compile` / `filelist/rtl.f`：
      · `rtl-compile` 的不变式是「`-- Compiling` 计数 == `filelist/rtl.f` 条目数」，而 `rtl.f` 表头明写
        「本表**不含 tb/**」＝**域分离**（DUT 与平台各自成清单）；把 TB 单元塞进去会同时破坏不变式与域分离；
      · 本判据**只跑 vlog、不涉 vsim license**（chk_rtl_compile 同款口径：ISS-104 只挡仿真）⇒ 可作
        常跑守卫；若把 vsim 跑放进守卫，license 抖动会把产品面误报成 ENV-BLOCKED（退出码 3）。
    """
    if not os.path.exists(TB_UNIT_F):
        return False, '缺 %s（fail-closed：TB 单元件清单应在册）' % rel(TB_UNIT_F)
    units, incs = _parse_f_list(TB_UNIT_F)
    if not units:
        return False, '%s 无编译单元条目（fail-closed）' % rel(TB_UNIT_F)
    if not incs:
        return False, ('%s 无 `+incdir+` 行（TB 件引用生成件的 `include 时会找不到；fail-closed）'
                       % rel(TB_UNIT_F))
    if not os.path.exists(VLOG):
        return False, 'vlog 不存在：%s' % VLOG
    d = os.path.join(ROOT, 'sim', 'run_tb_compile')
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, 'run.log'), 'w', encoding='utf-8').close()
    args = [VLOG, '-64', '-sv', '-work', 'work']
    args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    text, rc = _msim(d, [[VLIB, 'work'], args], 'vlog')
    n_err = re.findall(r'Errors:\s*(\d+)', text)
    n_comp = len(re.findall(r'^-- Compiling', text, re.M))
    if not n_err:
        return False, '编译日志无 `Errors: N`（fail-closed）→ %s' % rel(os.path.join(d, 'run.log'))
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(os.path.join(d, 'run.log')))
    if n_comp != len(units):
        return False, ('`-- Compiling` 计数 %d ≠ filelist/tb_unit.f 条目数 %d（少编/多编都不算过；'
                       'fail-closed）→ %s' % (n_comp, len(units), rel(os.path.join(d, 'run.log'))))
    if rc != 0:
        return False, 'vlog 退出码 %d → %s' % (rc, rel(os.path.join(d, 'run.log')))
    return True, 'vlog 编译 %d 个单元（filelist/tb_unit.f）｜ Errors: 0 ｜ %s' % (
        n_comp, rel(os.path.join(d, 'run.log')))


# --------------------------------------------------------------------------- #
# M1-S1 取指通路判据（`rtl-fetch-win`；口径＝`doc/design/M1-实现计划.md` §5 S1 判据②）
#
# 注册依据：`GD-1` 口径「补判据直接改、记台账」；§5 判据纪律「注册前不得把该步置 done，
# 红线 R8/R23」——本判据落地后 S1 才允许置 done（此前只有阶段证据 `sim/run_rtl_fetch_smoke/`）。
# --------------------------------------------------------------------------- #
# TB 侧冒烟的编译清单：**必须与 `filelist/rtl.f` 同批编译**（该 TB 例化 `vr1_core`，单编不成单元）
TB_FETCH_SMOKE_F = os.path.join(ROOT, 'filelist', 'tb_fetch_smoke.f')
# 一份镜像喂两边：RTL 冒烟与 ISS 侧同一份 .hex（字地址口径与 TB 的 `$readmemh` 同源）
IMAGE_HEX = os.path.join(ROOT, 'sim', 'image', 'm_smoke.hex')
RE_FSW_WIN = re.compile(r'\[fetch_smoke\] win(\d+) checked: pc=([0-9a-f]+) wbase=([0-9a-f]+) '
                        r'aligned32B=([01]) starts=(\d+)')
RE_FSW_S1_1 = re.compile(r'\[fetch_smoke\] S1-1 first_req_va=([0-9a-f]+) \(RESET_PC=([0-9a-f]+)\) '
                         r'ok=([01])')
RE_FSW_S1_2 = re.compile(r'\[fetch_smoke\] S1-2 win_base 32B aligned: (\d+)/(\d+) windows checked '
                         r'\(\[4:0\]==0\) ok=([01])')
RE_FSW_S1_3 = re.compile(r'\[fetch_smoke\] S1-3 stride=(\d+) ok=([01]) va=')
RE_FSW_CNT = re.compile(r'\[fetch_smoke\] n_req=(\d+) n_checked=(\d+) n_fail=(\d+)')
RE_FSW_RAW = re.compile(r'\[fetch_smoke\] ibuf_win0 lanes\[([0-9,\s]*)\]\.raw32 = ([^(]*)')


def _spec_param(name):
    """按名读 `doc/spec/00` §4 的单值参数：**真源＝spec**（不读生成件、不抄常量、不猜）。

    `INT` 取数值；`LIT`（如 `RESET_PC` = `44'h0000_1000`）按字面进制换算。
    找不到 / 类型不符 / 字面量解析不了 ⇒ 返回 `(None, value_text)`，调用方一律 fail-closed。
    """
    rows, _ = parse_spec_params()
    for r in rows:
        if name not in r['names']:
            continue
        if r['kind'] == 'INT':
            return r['value'][0], r['value_text']
        if r['kind'] == 'LIT':
            m = LIT_RE.match(r['value'][0])
            if m:
                return int(m.group(3).replace('_', ''),
                           {'b': 2, 'o': 8, 'd': 10, 'h': 16}[m.group(2)]), r['value_text']
        return None, r['value_text']
    return None, ''


def _hex_words(path):
    """解析 `readmemh` 形态 `.hex` → `{字索引: 32bit 值}`。

    `@<n>` 的 `n` 是**字（数组下标）地址**（与 TB 的 `$readmemh(img, mem)` 同口径；见
    `sim/image/MANIFEST.txt` 的 `base_word`/`base_byte`）。无 `@` 头则按 0 起算。
    """
    out, idx = {}, None
    if not os.path.exists(path):
        return out
    for raw in io.open(path, 'r', encoding='utf-8'):
        ln = raw.split('//')[0].strip()
        if not ln:
            continue
        if ln.startswith('@'):
            idx = int(ln[1:].strip(), 16)
            continue
        if idx is None:
            idx = 0
        for tok in ln.split():
            out[idx] = int(tok, 16)
            idx += 1
    return out


def _manifest_kv():
    """`sim/image/MANIFEST.txt` 的 `key=value` 行 → dict（解析不到即空，由调用方 fail-closed）。"""
    kv = {}
    if not os.path.exists(IMAGE_MANIFEST):
        return kv
    for raw in io.open(IMAGE_MANIFEST, 'r', encoding='utf-8'):
        if '=' in raw:
            k, v = raw.split('=', 1)
            kv[k.strip()] = v.strip()
    return kv


def chk_rtl_fetch_win():
    """rtl-fetch-win（M1-S1 判据②；口径＝`doc/design/M1-实现计划.md` §5 S1 与 §5 附注⑥）。

    **判什么**（一律 fail-closed：哪条证据行解析不到即 FAIL；不猜、不豁免，红线 R6/R8）：
      ① 同批编译（`filelist/rtl.f` 单元 ＋ `filelist/tb_fetch_smoke.f` 单元）→ `vopt` → `vsim`：
         `-- Compiling` 计数 == 两清单条目数之和（少编/多编都不算过）、逐段 `Errors: 0`、三条退出码 0；
      ② `S1-1`：首次请求 VA == `doc/spec/00` §4 的 `RESET_PC`（真源读 spec）且 `ok=1`；
      ③ `S1-2`：窗基址 32 B 对齐——逐窗行 `win<i> checked: … aligned32B=1` 全为 1，且
         `N/N windows checked … ok=1`（N == M == 逐窗行数 **≥ 4**：不得缩小判据注册时的观测面）；
      ④ `S1-3` ＋ 逐窗 `wbase`：连续窗按 `FETCH_BYTES`（spec/00 §4）推进，且每窗 `wbase == pc[39:5]<<5`
         （窗基址由响应侧按 §3.16 BLK-08 产生，逐窗对齐，不只查窗 0）；
      ⑤ `n_req=… n_checked=… n_fail=0`：`n_fail` 必须 0，`n_checked` == 已校验窗数，`n_req ≥ n_checked`；
      ⑥ `ibuf_win0 … raw32 = <8 字>`：逐字 == `sim/image/m_smoke.hex` 的窗 0 镜像字
         （字地址口径与 TB 的 `$readmemh` 同源：`MANIFEST.txt` 的 `base_word`/`base_byte`）；
      ⑦ 出现 `PASS: S1 fetch path`，且全段无 `FAIL`/`ABORT` 行。

    **为什么不进常跑守卫、也不进 M1 的两条 exit**：本判据要 vlog+vopt+vsim（较贵）且 vsim 涉
    ModelSim license（ISS-104 抖动会把产品面误报成 ENV-BLOCKED）；M1 的 exit 是 `rtl-compile`／
    `rtl-vs-iss`（GI-14，语义不得改动）——本判据是 **M1-S1 步**的完成判据（步骤面）。
    """
    if not os.path.exists(RTL_F):
        return False, '缺 %s（fail-closed：本判据须与 DUT 清单同批编译）' % rel(RTL_F)
    if not os.path.exists(TB_FETCH_SMOKE_F):
        return False, '缺 %s（fail-closed：S1 的 TB 侧编译清单应在册）' % rel(TB_FETCH_SMOKE_F)
    rtl_units, rtl_incs = _parse_f_list(RTL_F)
    tb_units, tb_incs = _parse_f_list(TB_FETCH_SMOKE_F)
    if not rtl_units or not tb_units:
        return False, '编译清单条目为空（%s / %s；fail-closed）' % (rel(RTL_F), rel(TB_FETCH_SMOKE_F))
    units = rtl_units + tb_units
    incs = list(dict.fromkeys(rtl_incs + tb_incs))                  # 去重保序
    if not incs:
        return False, '两份清单均无 `+incdir+` 行（参数件/类型件的 `include 会找不到；fail-closed）'
    if not os.path.exists(IMAGE_HEX):
        return False, '缺 %s（fail-closed：一份镜像喂两边）' % rel(IMAGE_HEX)
    reset_pc, rp_txt = _spec_param('RESET_PC')
    fetch_bytes, fb_txt = _spec_param('FETCH_BYTES')
    if reset_pc is None:
        return False, 'doc/spec/00 §4 未解析到 RESET_PC（fail-closed；原文 %s）' % (rp_txt or '?')
    if not fetch_bytes or fetch_bytes <= 0:
        return False, 'doc/spec/00 §4 的 FETCH_BYTES 不可用（fail-closed；原文 %s）' % (fb_txt or '?')
    kv = _manifest_kv()
    try:
        base_word, base_byte = int(kv['base_word'], 16), int(kv['base_byte'], 16)
    except (KeyError, ValueError):
        return False, 'MANIFEST 缺 base_word/base_byte（fail-closed；%s）' % rel(IMAGE_MANIFEST)
    if not (os.path.exists(VLOG) and os.path.exists(VOPT) and os.path.exists(VSIM)):
        return False, 'ModelSim 工具缺件（vlog/vopt/vsim）：%s' % MTI
    d = os.path.join(ROOT, 'sim', 'run_rtl_fetch_win')               # 沙箱独占（红线 R10）
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, 'run.log')
    open(log, 'w', encoding='utf-8').close()
    vlog_args = [VLOG, '-64', '-sv', '-work', 'work']
    vlog_args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    vlog_args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    t_c, rc_c = _msim(d, [[VLIB, 'work'], vlog_args], 'vlog')
    if rc_c != 0:
        return False, 'vlog 退出码 %d → %s' % (rc_c, rel(log))
    n_err = re.findall(r'Errors:\s*(\d+)', t_c)
    n_comp = len(re.findall(r'^-- Compiling', t_c, re.M))
    if not n_err:
        return False, 'vlog 段无 `Errors: N` 证据行（fail-closed）→ %s' % rel(log)
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(log))
    if n_comp != len(units):
        return False, ('`-- Compiling` 计数 %d ≠ rtl.f+tb_fetch_smoke.f 条目数 %d（少编/多编都不算过；'
                       'fail-closed）→ %s' % (n_comp, len(units), rel(log)))
    t_o, rc_o = _msim(d, [[VOPT, '-64', 'work.vr1_fetch_smoke_tb', '-o', 'fetch_smoke_opt']], 'vopt')
    if rc_o != 0:
        return False, 'vopt 退出码 %d → %s' % (rc_o, rel(log))
    n_err_o = re.findall(r'Errors:\s*(\d+)', t_o)
    if not n_err_o or int(n_err_o[-1]) != 0:
        return False, 'vopt 段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_err_o[-1] if n_err_o else '?', rel(log))
    t_s, rc_s = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'fetch_smoke_opt',
                           '+IMAGE=%s' % IMAGE_HEX.replace('\\', '/')]], 'vsim')
    if rc_s != 0:
        return False, 'vsim 退出码 %d → %s' % (rc_s, rel(log))
    n_err_s = re.findall(r'Errors:\s*(\d+)', t_s)
    if not n_err_s:
        return False, 'vsim 段无 `Errors: N` 证据行（fail-closed）→ %s' % rel(log)
    if int(n_err_s[-1]) != 0:
        return False, 'vsim 报 %s 个 error → %s' % (n_err_s[-1], rel(log))
    # ---- 证据行（红线段：解析不到即 FAIL）----
    bad = [ln.strip() for ln in t_s.splitlines()
           if '[fetch_smoke] FAIL' in ln or '[fetch_smoke] ABORT' in ln]
    if bad:
        return False, 'TB 自报 %d 条 FAIL/ABORT：%s ｜ %s' % (len(bad), bad[0][:100], rel(log))
    m11 = RE_FSW_S1_1.search(t_s)
    if not m11:
        return False, '未解析到 `S1-1 first_req_va=… ok=…` 证据行（fail-closed）→ %s' % rel(log)
    va0, rpc = int(m11.group(1), 16), int(m11.group(2), 16)
    if m11.group(3) != '1' or va0 != reset_pc or rpc != reset_pc:
        return False, ('S1-1 不符：first_req_va=%x / 打印的 RESET_PC=%x（ok=%s），expect 两者都 == '
                       'spec/00 §4 的 %s（0x%x）→ %s' % (va0, rpc, m11.group(3), rp_txt, reset_pc, rel(log)))
    wins = {}
    for m in RE_FSW_WIN.finditer(t_s):
        wins[int(m.group(1))] = (int(m.group(2), 16), int(m.group(3), 16), m.group(4), int(m.group(5)))
    if not wins:
        return False, '未解析到逐窗 `win<i> checked: …` 证据行（fail-closed）→ %s' % rel(log)
    m12 = RE_FSW_S1_2.search(t_s)
    if not m12:
        return False, '未解析到 `S1-2 win_base 32B aligned: N/M … ok=…`（fail-closed）→ %s' % rel(log)
    n_align, n_win = int(m12.group(1)), int(m12.group(2))
    if m12.group(3) != '1' or n_win < 4 or n_align != n_win:
        return False, ('S1-2 不符：%d/%d 窗对齐 ok=%s（须 ok=1、N==M、且 M ≥ 4——不得缩小观测面）→ %s'
                       % (n_align, n_win, m12.group(3), rel(log)))
    if sorted(wins) != list(range(n_win)):
        return False, ('逐窗行窗号 %s 与 S1-2 的 %d 窗不齐（fail-closed）→ %s'
                       % (sorted(wins), n_win, rel(log)))
    bad_align = sorted(i for i, w in wins.items() if w[2] != '1')
    if bad_align:
        return False, '窗 %s 的 `aligned32B=0`（窗基址未按 §3.16 BLK-08 对齐）→ %s' % (
            bad_align, rel(log))
    wb0, offs = wins[0][1], []
    for i, w in sorted(wins.items()):
        if w[1] != (w[0] & ~0x1F):
            offs.append('win%d: wbase=%x ≠ pc[39:5]<<5=%x' % (i, w[1], w[0] & ~0x1F))
        elif w[1] != wb0 + i * fetch_bytes:
            offs.append('win%d: wbase=%x ≠ win0(%x)+%d×%d' % (i, w[1], wb0, i, fetch_bytes))
    if wins[0][0] != reset_pc or offs:
        return False, ('窗推进不符（首窗前 %s / 逐窗 %s）→ %s'
                       % ('pc=%x ≠ RESET_PC=%x' % (wins[0][0], reset_pc) if wins[0][0] != reset_pc else 'ok',
                          '；'.join(offs[:3]) if offs else 'ok', rel(log)))
    m13 = RE_FSW_S1_3.search(t_s)
    if not m13:
        return False, '未解析到 `S1-3 stride=… ok=…`（fail-closed）→ %s' % rel(log)
    if m13.group(2) != '1' or int(m13.group(1)) != fetch_bytes:
        return False, ('S1-3 不符：stride=%s ok=%s，expect stride == spec/00 §4 的 FETCH_BYTES=%d 且 ok=1'
                       '（原文 %s）→ %s' % (m13.group(1), m13.group(2), fetch_bytes, fb_txt, rel(log)))
    mcnt = RE_FSW_CNT.search(t_s)
    if not mcnt:
        return False, '未解析到 `n_req=… n_checked=… n_fail=…` 证据行（fail-closed）→ %s' % rel(log)
    n_req, n_checked, n_fail = (int(mcnt.group(1)), int(mcnt.group(2)), int(mcnt.group(3)))
    if n_fail != 0:
        return False, 'n_fail=%d（必须 0；TB 自检项见同段 FAIL 行）→ %s' % (n_fail, rel(log))
    if n_checked != n_win or n_req < n_checked:
        return False, ('n_checked=%d ≠ 已校验窗数 %d（或 n_req=%d < n_checked；fail-closed）→ %s'
                       % (n_checked, n_win, n_req, rel(log)))
    # ---- 窗 0 的 8 个 32 bit 字 == 镜像常量（独立于 TB 内部常量，读 .hex 真源）----
    raw_ln = next((ln.strip() for ln in t_s.splitlines() if '[fetch_smoke] ibuf_win0 lanes[' in ln), None)
    if raw_ln is None:
        return False, '未解析到 `ibuf_win0 … raw32 = …` 镜像常量证据行（fail-closed）→ %s' % rel(log)
    mraw = RE_FSW_RAW.search(raw_ln)
    if not mraw:
        return False, '`raw32` 证据行形状不符（fail-closed）：%s' % raw_ln[:110]
    try:
        slots = [int(x) for x in mraw.group(1).replace(' ', '').split(',') if x]
        got = [int(x, 16) for x in mraw.group(2).split()]
    except ValueError:
        return False, '`raw32` 证据行的槽号/字面量不可解析（fail-closed）：%s' % raw_ln[:110]
    exp_slots = list(range(0, fetch_bytes // 2, 2))     # S1 无 C：每指令占 2 槽 ⇒ 偶数槽起始
    if slots != exp_slots or len(got) != len(slots):
        return False, ('窗 0 槽号/字数不符（槽 %s，期望 %s；%d 字 vs %d）：fail-closed → %s'
                       % (slots, exp_slots, len(got), len(exp_slots), rel(log)))
    words = _hex_words(IMAGE_HEX)
    exp, miss = [], []
    for s in slots:
        off_b = wb0 + 2 * s - base_byte
        if off_b < 0 or off_b % 4 or (base_word + off_b // 4) not in words:
            miss.append('槽%d(byte 0x%x)' % (s, wb0 + 2 * s))
            continue
        exp.append(words[base_word + off_b // 4])
    if miss:
        return False, '窗 0 有 %d 个字落在镜像字地址空间外（fail-closed）：%s ｜ %s' % (
            len(miss), '、'.join(miss[:4]), rel(log))
    diffs = [(s, g, e) for s, g, e in zip(slots, got, exp) if g != e]
    if diffs:
        return False, ('窗 0 raw32 与镜像常量不符 %d/%d 字：槽%d %08x != %08x ｜ %s'
                       % (len(diffs), len(got), diffs[0][0], diffs[0][1], diffs[0][2], rel(log)))
    if '[fetch_smoke] PASS: S1 fetch path' not in t_s:
        return False, '未见 `PASS: S1 fetch path` 证据行（fail-closed）→ %s' % rel(log)
    return True, ('n_fail=0；窗基址 %d/%d 对齐；S1-1 首请求 VA=%x==RESET_PC；stride=%d==FETCH_BYTES；'
                  'raw32 %d/%d 字==镜像；vlog %d 单元+vopt+vsim Errors: 0 ｜ %s'
                  % (n_align, n_win, va0, fetch_bytes, len(got), len(exp), n_comp, rel(log)))


# --------------------------------------------------------------------------- #
# M1-S2 译码级判据（`rtl-decode-win`；口径＝`doc/design/M1-实现计划.md` §5 S2 行判据② 与 §5 附注·S2）
#
# 注册依据：`GD-1` 口径「补判据直接改、记台账」；§5 判据纪律「注册前不得把该步置 done」（红线 R8/R23）。
# 为什么现在可注册（把判据② 的"不依赖 S4"部分切出来）：判据② 原文＝「定向用例（单条指令）RTL 侧 CSV
#   前缀比对 `pc,binary` 0 mismatch」——`pc`/`binary` 两列在 **D 级**（`uop_t.pc` / `uop_t.raw32`）
#   即已确定，**不需要**提交/`rt_t` 面；`gpr`/`csr` 两列确需执行/提交面（S4）⇒ 本判据只判前者。
#   本判据把"RTL 侧 CSV"落成 **TB 逐条证据行**（`[decode_stream] uop …`），并与两个**独立真源**
#   比对：① `sim/image/m_smoke.hex`（镜像字）② `sim/golden/iss_smoke.csv`（ISS 的 `pc→binary`）；
#   `isop` 面与 `spec/02` §9.1／清单 §1.1 的 14 条成员表逐值比对（不硬编码、不抄生成件）。
# 边界（不得越读）：本判据**不得**当 M1 判据、**不得**冒充 `rtl-vs-iss`（后者仍是 BLOCKED 桩）；
#   也不判 `gpr`/`csr`/拍数/IPC/预测准确率（计划 §1.3 第 1/2 条）。
# --------------------------------------------------------------------------- #
TB_DECODE_SMOKE_F = os.path.join(ROOT, 'filelist', 'tb_decode_smoke.f')
RE_DUW_SUM = re.compile(r'\[decode_unit\] A/B/C/D: uops=(\d+) drain_pulses=(\d+) n_fail=(\d+)')
RE_DUW_PRES = re.compile(r'\[decode_unit\] pres lanes=(\d+) pc0=([0-9a-f]+) drain=([01x]) accept=([01x])')
RE_DSW_B3 = re.compile(r'\[decode_stream\] S2-B3 windows: requests=(\d+) drain_pulses=(\d+)')
RE_DSW_UOP = re.compile(r'\[decode_stream\] uop pc=([0-9a-f]+) raw32=([0-9a-fx]+) isop=([0-9a-fx]+) '
                        r'cls=([0-9a-fx]+) pre_exc=([01x]) code=(\d+)')
DEC_FILL_WORD = 0xFFFFFFFF
DEC_UNIT_LANES = 15          # 定向场景（件 1 的 win A/B/C/D = 4+3+6+2 条起始槽）
DEC_UNIT_DRAINS = 4
DEC_UNIT_BASES = (0x1000, 0x2000, 0x3000, 0x4000)


def _golden_pc_binary(path):
    """golden trace CSV 的 `pc(hex) → binary(hex)`（列名缺失/值不可解析 ⇒ None；调用方 fail-closed）。"""
    if not os.path.exists(path):
        return None
    out = {}
    try:
        with io.open(path, 'r', encoding='utf-8', newline='') as f:
            rd = csv.DictReader(f)
            if not rd.fieldnames or 'pc' not in rd.fieldnames or 'binary' not in rd.fieldnames:
                return None
            for r in rd:
                pc = (r.get('pc') or '').strip()
                bi = (r.get('binary') or '').strip()
                if not pc or not bi:
                    return None
                out[int(pc, 16)] = int(bi, 16)
    except (ValueError, OSError, csv.Error):
        return None
    return out or None


def _csv_data_rows(path):
    """CSV 的**数据行数**（不含表头）；文件缺失/不可解析 ⇒ None（调用方 fail-closed）。

    与 `iss/tools/trace_compare.py` 的长度判据同源：该工具对 `len(a) != len(b)` 直接退 1 ⇒
    两侧"行数"＝**逐条退休记录条数**（循环体会重复计数）。
    **不要**用 `len(_golden_pc_binary(p))` 代替本函数——那返回的是**互异 pc 数**（映射基数），
    与"行数"不是同一量（2026-09-26 心跳第 5 轮：`rv64ui-p-add` 470 行 vs 358 互异 pc）。
    """
    if not os.path.exists(path):
        return None
    try:
        n = 0
        with io.open(path, 'r', encoding='utf-8', newline='') as f:
            rd = csv.reader(f)
            next(rd, None)                       # 表头（无表头文件 ⇒ 记 0 行、不静默取整）
            for _ in rd:
                n += 1
    except (ValueError, OSError, csv.Error):
        return None
    return n


def _spec02_members():
    """`spec/02` §9.1 八张成员表 → `{成员名: isop 编码}`（解析不到 ⇒ None；调用方 fail-closed）。

    解析口径与 `chk_isop_subset` 同源（列首＝`编码`、成员名取反引号内的全大写 token），
    本函数只做**只读提取**，不另赋任何值。
    """
    if not os.path.exists(SPEC02):
        return None
    lines = _doc_lines(SPEC02)
    sec = sec_slice(lines, r'^#{2}\s*9\.\s', level=2)
    if sec is None:
        return None
    out = {}
    for t in md_tables(lines, *sec):
        if not (len(t[1]) >= 3 and t[1][0].replace('`', '') == '编码'):
            continue
        for _ln, cells in t[2]:
            code = cells[0].replace('`', '').strip()
            if not re.match(r'^0x[0-9A-Fa-f]{3}$', code):
                continue
            nm = next((x for x in ticks(cells[1]) if re.match(r'^[A-Z][A-Z0-9.]*$', x)), None)
            if nm:
                out[nm] = int(code, 16)
    return out or None


def _g1i_names():
    """清单 §1.1 的 G1-I 指令名表（与 `chk_isop_subset` 同一解析口径；解析不到 ⇒ None）。"""
    g1 = _doc_lines(G1I_LIST)
    s11 = sec_slice(g1, r'^#{3}\s*1\.1\s')
    if s11 is None:
        return None
    for t in md_tables(g1, *s11):
        for _ln, cells in t[2]:
            if '指令' not in cells[1]:
                continue
            if re.search(r'指令\s*\*{0,2}\s*(\d+)\s*条', cells[1]):
                return [x for x in ticks(cells[1]) if re.match(r'^[A-Z][A-Z0-9.]*$', x)]
    return None


def chk_rtl_decode_win():
    """rtl-decode-win（M1-S2 步判据；口径＝`doc/design/M1-实现计划.md` §5 S2 行判据②／§5 附注·S2）。

    **判什么**（一律 fail-closed：哪条证据行解析不到/不符即 FAIL；不猜、不豁免，红线 R6/R8）：
      ① 同批编译（`filelist/rtl.f` 单元 ＋ `filelist/tb_decode_smoke.f` 单元）→ 两个 TB 顶层各自
         `vopt`+`vsim`：`-- Compiling` 计数 == 两清单条目数之和（少编/多编都不算过）、各段
         `Errors: 0`、各步退出码 0；
      ② **件 1（反压面）**：逐呈现行 `pres lanes=… pc0=… drain=… accept=…` 自洽——`accept=0` 的拍
         必须与其**前一拍同组**（同 `lanes`/同 `pc0`＝反压不丢不重）、接受 lane 总数 == 15、
         `drain=1` 恰 4 次且每次 `lanes>0 ∧ accept=1`、`lanes=0 ⇒ drain=0`、`lanes>0` 的 `pc0`
         ∈ 场景四窗基址、末拍无 lane（窗口取尽）；且 `uops=15 drain_pulses=4 n_fail=0` 逐值相符；
      ③ **件 2（判据② 的 `pc,binary` 面）**：逐条行 `uop pc=… raw32=… isop=… cls=… pre_exc=… code=…`
         · `pc` 自 `spec/00` §4 的 `RESET_PC` 起**逐条 +4 连续**（无丢、无重）；
         · 行数 == 窗数 ×（`FETCH_BYTES`/4），且 `S2-B3` 行的 `requests == drain_pulses`（一窗一 drain）；
         · 镜像字（真源 `sim/image/m_smoke.hex` ＋ `MANIFEST` 的 `base_word`/`base_byte`/`words`）：
           非填充字 ⇒ `pre_exc=0 ∧ isop≠0 ∧ cls==isop[9:7]`；`0xFFFFFFFF` 填充字 ⇒ `pre_exc=1 ∧
           code=2 ∧ isop=0`；越出镜像装载区（内存桩未装载）⇒ 同上非法路径；
         · **ISS golden 互证**：`sim/golden/iss_smoke.csv` 的每个 `pc` 都必须在流里出现，且该行
           `raw32 == golden.binary`（覆盖"漏条/错字"两类）；
         · **isop 14/14**：合法行的 `isop` 值集合 == 清单 §1.1 的 14 条指令在 `spec/02` §9.1 的编码集；
      ④ 两段各出现 `PASS` 证据行，且均无 `FAIL`/`ABORT` 行。

    **为什么不进常跑守卫、也不进 M1 的两条 exit**：本判据要 vlog＋vopt×2＋vsim×2（较贵）且 vsim 涉
    ModelSim license（ISS-104 抖动会把产品面误报成 ENV-BLOCKED）；M1 的 exit 是 `rtl-compile`／
    `rtl-vs-iss`（GI-14，语义不得改动）——本判据是 **M1-S2 步**的完成判据（步骤面）。
    """
    for p in (RTL_F, TB_DECODE_SMOKE_F, IMAGE_HEX, IMAGE_MANIFEST, GOLDEN):
        if not os.path.exists(p):
            return False, '缺 %s（fail-closed）' % rel(p)
    rtl_units, rtl_incs = _parse_f_list(RTL_F)
    tb_units, tb_incs = _parse_f_list(TB_DECODE_SMOKE_F)
    if not rtl_units or not tb_units:
        return False, '编译清单条目为空（%s / %s；fail-closed）' % (rel(RTL_F), rel(TB_DECODE_SMOKE_F))
    units = rtl_units + tb_units
    incs = list(dict.fromkeys(rtl_incs + tb_incs))
    if not incs:
        return False, '两份清单均无 `+incdir+` 行（生成件的 `include 会找不到；fail-closed）'
    reset_pc, rp_txt = _spec_param('RESET_PC')
    fetch_bytes, fb_txt = _spec_param('FETCH_BYTES')
    if reset_pc is None:
        return False, 'doc/spec/00 §4 未解析到 RESET_PC（fail-closed；原文 %s）' % (rp_txt or '?')
    if not fetch_bytes or fetch_bytes <= 0 or fetch_bytes % 4:
        return False, 'doc/spec/00 §4 的 FETCH_BYTES 不可用（fail-closed；原文 %s）' % (fb_txt or '?')
    kv = _manifest_kv()
    try:
        base_word, base_byte = int(kv['base_word'], 16), int(kv['base_byte'], 16)
        img_words = int(kv['words'], 10)
    except (KeyError, ValueError):
        return False, 'MANIFEST 缺 base_word/base_byte/words（fail-closed；%s）' % rel(IMAGE_MANIFEST)
    words = _hex_words(IMAGE_HEX)
    if len(words) != img_words:
        return False, '镜像字数 %d ≠ MANIFEST.words %d（fail-closed）→ %s' % (
            len(words), img_words, rel(IMAGE_HEX))
    gold = _golden_pc_binary(GOLDEN)
    if not gold:
        return False, 'golden 的 `pc→binary` 不可用（fail-closed）→ %s' % rel(GOLDEN)
    members, g1i = _spec02_members(), _g1i_names()
    if not members:
        return False, '`spec/02` §9.1 成员表未解析出（fail-closed）'
    if not g1i:
        return False, '清单 §1.1 的 G1-I 指令子集未解析出（fail-closed）'
    miss = [n for n in g1i if n not in members]
    if miss:
        return False, 'G1-I 指令在 `spec/02` §9.1 无编码：%s（fail-closed）' % '、'.join(miss)
    want_isop = set(members[n] for n in g1i)
    isop_all = set(members.values())            # §9.1 全量成员编码集（合法行的值域收口）
    if not (os.path.exists(VLOG) and os.path.exists(VOPT) and os.path.exists(VSIM)):
        return False, 'ModelSim 工具缺件（vlog/vopt/vsim）：%s' % MTI
    d = os.path.join(ROOT, 'sim', 'run_rtl_decode_win')               # 沙箱独占（红线 R10）
    os.makedirs(d, exist_ok=True)
    log = os.path.join(d, 'run.log')
    open(log, 'w', encoding='utf-8').close()
    vlog_args = [VLOG, '-64', '-sv', '-work', 'work']
    vlog_args += ['+incdir+%s' % os.path.join(ROOT, i).replace('\\', '/') for i in incs]
    vlog_args += [os.path.join(ROOT, u).replace('\\', '/') for u in units]
    t_c, rc_c = _msim(d, [[VLIB, 'work'], vlog_args], 'vlog')
    if rc_c != 0:
        return False, 'vlog 退出码 %d → %s' % (rc_c, rel(log))
    n_err = re.findall(r'Errors:\s*(\d+)', t_c)
    n_comp = len(re.findall(r'^-- Compiling', t_c, re.M))
    if not n_err:
        return False, 'vlog 段无 `Errors: N` 证据行（fail-closed）→ %s' % rel(log)
    if int(n_err[-1]) != 0:
        return False, 'vlog 报 %s 个 error → %s' % (n_err[-1], rel(log))
    if n_comp != len(units):
        return False, ('`-- Compiling` 计数 %d ≠ rtl.f+tb_decode_smoke.f 条目数 %d（少编/多编都不算过；'
                       'fail-closed）→ %s' % (n_comp, len(units), rel(log)))
    # ---- 件 1：单元冒烟（反压 / 逐窗 drain 面）----
    t_o1, rc_o1 = _msim(d, [[VOPT, '-64', 'work.decode_unit_tb', '-o', 'unit_opt']], 'vopt-unit')
    if rc_o1 != 0:
        return False, 'vopt（decode_unit_tb）退出码 %d → %s' % (rc_o1, rel(log))
    n_o1 = re.findall(r'Errors:\s*(\d+)', t_o1)
    if not n_o1 or int(n_o1[-1]) != 0:
        return False, 'vopt（decode_unit_tb）段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_o1[-1] if n_o1 else '?', rel(log))
    t_u, rc_u = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'unit_opt']], 'vsim-unit')
    if rc_u != 0:
        return False, 'vsim（decode_unit_tb）退出码 %d → %s' % (rc_u, rel(log))
    n_us = re.findall(r'Errors:\s*(\d+)', t_u)
    if not n_us or int(n_us[-1]) != 0:
        return False, 'vsim（decode_unit_tb）段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_us[-1] if n_us else '?', rel(log))
    bad_u = [ln.strip() for ln in t_u.splitlines()
             if '[decode_unit] FAIL' in ln or '[decode_unit] ABORT' in ln]
    if bad_u:
        return False, '件 1 自报 %d 条 FAIL/ABORT：%s ｜ %s' % (len(bad_u), bad_u[0][:100], rel(log))
    msum = RE_DUW_SUM.search(t_u)
    if not msum:
        return False, '未解析到 `[decode_unit] A/B/C/D: uops=… drain_pulses=… n_fail=…`（fail-closed）→ %s' % rel(log)
    u_n, u_dr, u_nf = int(msum.group(1)), int(msum.group(2)), int(msum.group(3))
    if (u_n, u_dr, u_nf) != (DEC_UNIT_LANES, DEC_UNIT_DRAINS, 0):
        return False, ('件 1 计数不符：uops=%d drain_pulses=%d n_fail=%d（expect %d/%d/0）→ %s'
                       % (u_n, u_dr, u_nf, DEC_UNIT_LANES, DEC_UNIT_DRAINS, rel(log)))
    pres = [(int(a), int(b, 16), c, e) for a, b, c, e in RE_DUW_PRES.findall(t_u)]
    if len(pres) < 8:
        return False, '逐呈现行仅 %d 条（expect ≥8；fail-closed）→ %s' % (len(pres), rel(log))
    for i, (nl, pc0, dr, ac) in enumerate(pres):
        if nl == 0 and dr == '1':
            return False, '第 %d 条呈现：lanes=0 却 drain=1（无 lane 不得 drain）→ %s' % (i + 1, rel(log))
        if dr == '1' and (nl == 0 or ac != '1'):
            return False, ('第 %d 条呈现：drain=1 但 lanes=%d accept=%s（drain 必与接受同拍且 ≥1 lane）→ %s'
                           % (i + 1, nl, ac, rel(log)))
        if nl > 0 and not any(b <= pc0 < b + fetch_bytes and (pc0 - b) % 2 == 0
                              for b in DEC_UNIT_BASES):
            return False, ('第 %d 条呈现：pc0=%x 不在场景四窗的槽地址域内（base ≤ pc0 < base+%d 且槽地址'
                           '偶对齐；窗基址 %s）（fail-closed）→ %s'
                           % (i + 1, pc0, fetch_bytes, [hex(b) for b in DEC_UNIT_BASES], rel(log)))
        if ac == '0' and i > 0 and pres[i - 1][3] == '0' and (nl, pc0) != (pres[i - 1][0], pres[i - 1][1]):
            return False, ('第 %d 条呈现：反压连续拍之间换了组（lanes/pc0 由 %s 变为 %s ⇒ 丢或重）→ %s'
                           % (i + 1, (pres[i - 1][0], hex(pres[i - 1][1])), (nl, hex(pc0)), rel(log)))
    acc_lanes = sum(nl for nl, _p, _d, ac in pres if ac == '1')
    if acc_lanes != DEC_UNIT_LANES:
        return False, '被接受 lane 总数 %d ≠ %d（定向场景 4+3+6+2；fail-closed）→ %s' % (
            acc_lanes, DEC_UNIT_LANES, rel(log))
    ndr = sum(1 for _n, _p, dr, _a in pres if dr == '1')
    if ndr != DEC_UNIT_DRAINS:
        return False, 'drain 脉冲 %d ≠ %d（一窗一次）→ %s' % (ndr, DEC_UNIT_DRAINS, rel(log))
    if pres[-1][3] != '1' or pres[-1][2] != '1':
        return False, ('末条呈现不是「最后一批被接受且同拍 drain」（末条 lanes=%d drain=%s accept=%s）→ %s'
                       % (pres[-1][0], pres[-1][2], pres[-1][3], rel(log)))
    if '[decode_unit] PASS' not in t_u:
        return False, '未见 `[decode_unit] PASS` 证据行（fail-closed）→ %s' % rel(log)
    # ---- 件 2：流冒烟（判据② 的 pc,binary 面）----
    t_o2, rc_o2 = _msim(d, [[VOPT, '-64', 'work.decode_stream_tb', '-o', 'stream_opt']], 'vopt-stream')
    if rc_o2 != 0:
        return False, 'vopt（decode_stream_tb）退出码 %d → %s' % (rc_o2, rel(log))
    n_o2 = re.findall(r'Errors:\s*(\d+)', t_o2)
    if not n_o2 or int(n_o2[-1]) != 0:
        return False, 'vopt（decode_stream_tb）段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_o2[-1] if n_o2 else '?', rel(log))
    t_s, rc_s = _msim(d, [[VSIM, '-64', '-c', '-do', 'run -all; quit -f', 'stream_opt',
                           '+IMAGE=%s' % IMAGE_HEX.replace('\\', '/')]], 'vsim-stream')
    if rc_s != 0:
        return False, 'vsim（decode_stream_tb）退出码 %d → %s' % (rc_s, rel(log))
    n_ss = re.findall(r'Errors:\s*(\d+)', t_s)
    if not n_ss or int(n_ss[-1]) != 0:
        return False, 'vsim（decode_stream_tb）段 `Errors:` = %s（expect 0；fail-closed）→ %s' % (
            n_ss[-1] if n_ss else '?', rel(log))
    bad_s = [ln.strip() for ln in t_s.splitlines()
             if '[decode_stream] FAIL' in ln or '[decode_stream] ABORT' in ln]
    if bad_s:
        return False, '件 2 自报 %d 条 FAIL/ABORT：%s ｜ %s' % (len(bad_s), bad_s[0][:100], rel(log))
    mb3 = RE_DSW_B3.search(t_s)
    if not mb3:
        return False, '未解析到 `S2-B3 windows: requests=… drain_pulses=…`（fail-closed）→ %s' % rel(log)
    n_req, n_win_dr = int(mb3.group(1)), int(mb3.group(2))
    if n_req != n_win_dr:
        return False, '件 2：requests=%d ≠ drain_pulses=%d（一窗恰一 drain；fail-closed）→ %s' % (
            n_req, n_win_dr, rel(log))
    rows = [(int(a, 16), b, c, d2, e, int(f)) for a, b, c, d2, e, f in RE_DSW_UOP.findall(t_s)]
    if not rows:
        return False, '未解析到逐条 `uop pc=… raw32=…` 证据行（fail-closed）→ %s' % rel(log)
    per_win = fetch_bytes // 4
    if len(rows) != n_req * per_win:
        return False, ('逐条行数 %d ≠ 窗数 %d ×（FETCH_BYTES/4=%d）（少条/多条都不算过；fail-closed）→ %s'
                       % (len(rows), n_req, per_win, rel(log)))
    ill_n, legal_n, got_isop, gold_seen = 0, 0, set(), set()
    for i, (pc, r32s, isops, clss, pe, code) in enumerate(rows):
        if pc != reset_pc + 4 * i:
            return False, ('第 %d 条 uop：pc=%x ≠ RESET_PC+4×%d=%x（流丢/重/错位；fail-closed）→ %s'
                           % (i + 1, pc, i, reset_pc + 4 * i, rel(log)))
        off = pc - base_byte
        widx = base_word + off // 4
        in_img = (off >= 0) and (off % 4 == 0) and (widx in words)
        if in_img:
            w = words[widx]
            if not re.fullmatch(r'[0-9a-f]{8}', r32s):
                return False, ('第 %d 条 uop：pc=%x 落在镜像内，但 raw32=%s 非全定义十六进制（fail-closed）'
                               '→ %s' % (i + 1, pc, r32s, rel(log)))
            if int(r32s, 16) != w:
                return False, ('第 %d 条 uop：pc=%x raw32=%s ≠ 镜像字 %08x（判据② 的 binary 面）→ %s'
                               % (i + 1, pc, r32s, w, rel(log)))
            ill = (w == DEC_FILL_WORD)
        else:
            ill = True                       # 越出镜像装载区（内存桩未装载）⇒ 只允许非法路径
        if not (re.fullmatch(r'[0-9a-f]{3}', isops) and re.fullmatch(r'[0-9a-f]', clss)
                and pe in '01'):
            return False, ('第 %d 条 uop 证据行含 x/形状不符（fail-closed）：raw32=%s isop=%s cls=%s '
                           'pre_exc=%s → %s' % (i + 1, r32s, isops, clss, pe, rel(log)))
        isop, clsv = int(isops, 16), int(clss, 16)
        if ill:
            ill_n += 1
            if pe != '1' or code != 2 or isop != 0:
                return False, ('第 %d 条 uop：pc=%x 属填充字/越界区，应走非法路径（expect pre_exc=1 '
                               'code=2 isop=000），实得 pre_exc=%s code=%d isop=%03x → %s'
                               % (i + 1, pc, pe, code, isop, rel(log)))
        else:
            legal_n += 1
            if pe != '0':
                return False, ('第 %d 条 uop：pc=%x 是镜像程序字却判非法（pre_exc=%s；程序字全为 G1-I 14 条）'
                               '→ %s' % (i + 1, pc, pe, rel(log)))
            if isop not in isop_all:
                return False, ('第 %d 条 uop：pc=%x isop=%03x 不在 `spec/02` §9.1 成员编码集内'
                               '（fail-closed）→ %s' % (i + 1, pc, isop, rel(log)))
            if clsv != ((isop >> 7) & 0x7):
                return False, ('第 %d 条 uop：pc=%x cls=%x ≠ isop[9:7]=%x（`spec/02` §9.4-(6) 恒等投影）'
                               '→ %s' % (i + 1, pc, clsv, (isop >> 7) & 0x7, rel(log)))
            got_isop.add(isop)
        if pc in gold:
            gold_seen.add(pc)
            if not re.fullmatch(r'[0-9a-f]{8}', r32s) or int(r32s, 16) != gold[pc]:
                return False, ('第 %d 条 uop：pc=%x 与 ISS golden 的 `binary` 不符（%s vs %08x）→ %s'
                               % (i + 1, pc, r32s, gold[pc], rel(log)))
    if len(gold_seen) != len(gold):
        miss_pc = sorted(set(gold) - gold_seen)[:4]
        return False, ('golden 的 %d 条里有 %d 条未在流中出现（漏条）：%s …（fail-closed）→ %s'
                       % (len(gold), len(gold) - len(gold_seen), [hex(x) for x in miss_pc], rel(log)))
    if got_isop != want_isop:
        only_dut = sorted(got_isop - want_isop)
        only_spec = sorted(want_isop - got_isop)
        return False, ('isop 14/14 不符：D 侧多出 %s；spec 侧未见 %s（清单 §1.1 × `spec/02` §9.1）→ %s'
                       % ([hex(x) for x in only_dut], [hex(x) for x in only_spec], rel(log)))
    if '[decode_stream] PASS' not in t_s:
        return False, '未见 `[decode_stream] PASS` 证据行（fail-closed）→ %s' % rel(log)
    return True, ('逐条 uop %d 条：pc 自 %x 连续 +4；raw32 全部 == 镜像字/填充字判定；golden %d/%d 条'
                  '互证（binary 逐字一致）；isop 14/14 == 清单 §1.1 × spec/02 §9.1；'
                  '窗 %d 个（requests==drains）、填充/越界非法路径 %d 条；件 1 反压 uops=%d drains=%d '
                  'n_fail=0；vlog %d 单元+vopt×2+vsim×2 Errors: 0 ｜ %s'
                  % (len(rows), reset_pc, len(gold_seen), len(gold), n_req, ill_n,
                     acc_lanes, ndr, n_comp, rel(log)))


# TB 侧格式契约的三件套（`trace-format-contract` 的唯一输入面）
TB_WRITER = os.path.join(ROOT, 'tb', 'unit', 'rt_t_trace_writer.sv')
TB_FORMAT_EXPECT = os.path.join(ROOT, 'sim', 'golden', 'tb_format_expect.csv')
TB_FORMAT_GEN = os.path.join(ROOT, 'iss', 'tools', 'gen_tb_trace_format.py')


def _sv_format_consts(path):
    """从 TB 写出器的 SV 源里取「格式常量」：表头字面量 + ABI 名表（保序）+ 名表声明长度。

    **只认字面量声明**（fail-closed）：按 `localparam ... = "…"` / `localparam string ABI_NAMES[N] = '{…}`
    的**声明形状**解析（注释里提到 `ABI_NAMES`/`TRACE_CSV_HEADER` 的字样不会被当成声明）；解析不到即
    返回 None，不猜、不合成、不从别处借。
    """
    if not os.path.exists(path):
        return None, None, None
    text = io.open(path, 'r', encoding='utf-8').read()
    m = re.search(r'localparam\s+string\s+TRACE_CSV_HEADER\s*=\s*"([^"]*)"', text)
    hdr = m.group(1) if m else None
    m2 = re.search(r"localparam\s+string\s+ABI_NAMES\s*\[(\d+)\]\s*=\s*'\{([^}]*)\}", text, re.S)
    names, n_decl = (re.findall(r'"([^"]*)"', m2.group(2)), int(m2.group(1))) if m2 else (None, None)
    return hdr, names, n_decl


def chk_trace_format_contract():
    """trace-format-contract（G1-I `GI-13` 的 TB 侧格式契约；**常跑守卫**，不进 M1 的 exit）：

      ① **期望件零漂移**：用 `iss/vriss` 重跑 `sim/image/m_smoke.hex` 并按 TB 写出器的同一套规则重渲染
         （落 `sim/run_trace_format/` 沙箱），重算 == 磁盘 `sim/golden/tb_format_expect.csv`
         （口径与 `params-drift`/`types-drift` 同款；行尾 CRLF/LF 差异不参与判定）；
      ② **格式常量逐字一致**：`tb/unit/rt_t_trace_writer.sv` 里写死的表头 == `TRACE_CSV_FIELDS`，
         且 ABI 名表逐项 == `trace.ABI_NAMES`（`gpr` 列的名不同即 mismatch，与数值无关）；
      ③ **两端可比**：`trace_compare sim/golden/iss_smoke.csv sim/golden/tb_format_expect.csv`
         报 `mismatch=0`（列 `pc,binary,gpr,csr`）——即"TB 侧格式"与 golden 在默认比对列上等价。

    为什么放常跑守卫而不进 M1 exit：M1 的两条 exit 是 `rtl-compile`/`rtl-vs-iss`（不得改动其语义）；
    本判据判的是**格式契约**（不判 RTL 行为），且很便宜（一次 ISS 重跑 + 两次子进程比对，无 ModelSim）。
    为什么**不**把写出器的 vsim 实跑也并进来：守卫每轮都跑，一旦依赖 vsim license（ISS-104 已知会抖），
    license 故障会把产品面误报成 ENV-BLOCKED（退出码 3）——写出器的实跑证据走
    `tb/unit/rt_t_trace_writer_smoke.sv` 的运行配方（M1-S4 的仿真步骤），不占守卫。
    """
    tr = _iss_mod('trace')
    if tr is None:
        return False, 'ISS `iss/vriss/trace.py` 无法 import（fail-closed）'
    cols = list(tr.TRACE_CSV_FIELDS)
    header = ','.join(cols)
    abi_ref = list(tr.ABI_NAMES)
    # ---- ② 格式常量（先判，纯读不跑东西；文件缺即 fail-closed）----
    hdr, abi, abi_w = _sv_format_consts(TB_WRITER)
    if hdr is None or abi is None or abi_w is None:
        return False, ('缺 %s 或其 `TRACE_CSV_HEADER`/`ABI_NAMES` 字面量声明（fail-closed）'
                       % rel(TB_WRITER))
    if hdr != header:
        return False, 'TB 写出器表头 != TRACE_CSV_FIELDS：%r vs %r' % (hdr, header)
    if abi_w != len(abi_ref):
        return False, ('TB 写出器 ABI 名表声明长度 %d != trace.ABI_NAMES 长度 %d'
                       % (abi_w, len(abi_ref)))
    if abi != abi_ref:
        bad = next((('%d' % i, a, b) for i, (a, b) in enumerate(zip(abi, abi_ref)) if a != b), None)
        return False, ('TB 写出器 ABI 名表（%d 项）!= trace.ABI_NAMES（%d 项）%s'
                       % (len(abi), len(abi_ref),
                          '' if not bad else '；首个不符 @%s %r vs %r' % bad))
    # ---- ① 期望件零漂移 ----
    if not os.path.exists(TB_FORMAT_GEN):
        return False, '缺 %s（fail-closed）' % rel(TB_FORMAT_GEN)
    d = os.path.join(ROOT, 'sim', 'run_trace_format')
    os.makedirs(d, exist_ok=True)
    regen_rel = 'sim/run_trace_format/tb_format_expect.regen.csv'
    rc, o = run([sys.executable, rel(TB_FORMAT_GEN), '--out', regen_rel])
    with open(os.path.join(d, 'run.log'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('$ python %s --out %s\n%s' % (rel(TB_FORMAT_GEN), regen_rel, o))
    if rc != 0 or '[PASS]' not in (o or ''):
        return False, '重生成失败（rc=%d）→ %s ｜ %s' % (
            rc, rel(os.path.join(d, 'run.log')), last_line(o)[:110])
    if not os.path.exists(TB_FORMAT_EXPECT):
        return False, '缺 %s（跑 `python %s` 生成）' % (rel(TB_FORMAT_EXPECT), rel(TB_FORMAT_GEN))
    norm = lambda t: t.replace('\r\n', '\n')
    want = norm(io.open(os.path.join(ROOT, regen_rel), 'r', encoding='utf-8', newline='').read())
    got = norm(io.open(TB_FORMAT_EXPECT, 'r', encoding='utf-8', newline='').read())
    if want.splitlines()[:1] != [header]:
        return False, '重算件表头 %r != TRACE_CSV_FIELDS（fail-closed）' % want.splitlines()[:1]
    if want != got:
        wl, gl = want.splitlines(), got.splitlines()
        k = next((i for i in range(max(len(wl), len(gl)))
                  if (wl[i] if i < len(wl) else None) != (gl[i] if i < len(gl) else None)), 0)
        return False, ('期望件漂移：重算 %d 行 != 磁盘 %d 行（首处差异 L%d：重算 %r vs 磁盘 %r）'
                       '→ 跑 `python %s` 重生成'
                       % (len(wl) - 1, len(gl) - 1, k + 1,
                          wl[k] if k < len(wl) else None, gl[k] if k < len(gl) else None,
                          rel(TB_FORMAT_GEN)))
    n_rows = len(got.splitlines()) - 1
    # ---- ③ 两端可比：golden vs TB 格式期望件 ----
    if not os.path.exists(GOLDEN):
        return False, '缺 golden %s' % rel(GOLDEN)
    rc, o = run([sys.executable, 'iss/tools/trace_compare.py', rel(GOLDEN), rel(TB_FORMAT_EXPECT)])
    line = last_line(o)
    if rc != 0 or 'mismatch=0' not in line:
        return False, 'TB 格式期望件 vs golden 比对未过：%s' % line[:130]
    return True, ('① 重算 == 磁盘（%d 行，md5 %s）② 表头 == TRACE_CSV_FIELDS（8 列）且 ABI 名表 == '
                  'trace.ABI_NAMES（%d 项）③ %s' % (n_rows, md5_of(TB_FORMAT_EXPECT)[:8],
                                                     len(abi_ref), line))


# --------------------------------------------------------------------------- #
# 环境事实单源（`state/env.json`）——「环境可用性」只许有一处表述，其余活文档与它对齐
#
# 病灶（2026-09-26 立据）：WSL2 路线作废、改 MSYS2（R-235/R-236，R0 定「永不装 Linux」）、Spike 自建
# 就位（R-235/ISS-123）、ModelSim license 由本脚本会话内注入解决（R-224）之后，**同一事实在别处仍留旧话**
# （旧话，已更正）：`state/flow.json` 的 `M1.blocked_by` 与 `P7.blocked_by` 曾写「③仿真器不可用
# （ISS-104 vsim license 或 ISS-002 WSL2）」，而这些旧话现已作废并改写——同一轮 `rtl-vs-iss` 判据的
# 消息里早已写「仿真器已就位、不再是阻塞项」⇒ 判据与状态件自相矛盾（R-237 声称去旧化、漏了该字段）。根因不是"漏改一处"，
# 而是**同一事实有多处表述、无人对账**。治法：把环境可用性收敛进 `state/env.json`，其余活文档只许与它一致。
# 三条纪律：① fail-closed（env.json 缺/结构坏/事实无别名登记/锚点查无 ⇒ FAIL，不猜不绕）；
#           ② 双向对齐（已就位的不许被写成不可用；未就位的不许被写成已就位；已作废路线只许出现在
#              「作废/更正」语境——同句含 ENV_SETTLED_RE 者视为历史叙述或更正句，放行）；
#           ③ 报行号/字段名（不许"感觉不一致"式结论）。
# --------------------------------------------------------------------------- #
ENV_FACTS = os.path.join(ROOT, 'state', 'env.json')

# fact 别名：键 ＝ `state/env.json` 的 facts/groups 键；值 ＝ 活文档里指代该事实的写法（正则片段）。
# 新增事实必须同步本表（缺别名 ⇒ 判据 FAIL：不让任何事实"没人扫"）。`groups` 是集合别名（如「仿真器」）。
ENV_ALIASES = {
    'modelsim': r'(?i)modelsim|\bvsim\b|\bvlog\b',
    'spike': r'\bSpike\b',
    'verilator': r'[Vv]erilator',
    'riscv_toolchain': r'riscv64-unknown-elf|RISC-V 交叉工具链|RISC-V 工具链|riscv64 工具链|工具链',
    'msys2_host': r'MSYS2|msys64',
    'qemu_backup_iss': r'\bQEMU\b',
    'wsl2_route': r'WSL2|\bWSL\b',   # 作废路线（ISS-122/R-235）：只许出现在「作废/更正」语境
    'simulators': r'仿真器',          # groups.simulators 的集合别名
}
# 「不可用/未就位」类措辞：对 ready=true 的事实说这种话＝与实况相抵
ENV_UNAVAIL_RE = re.compile(
    r'不可用|不可仿真|无法仿真|不能仿真|未就位|未安装|待安装|待装|未装|没装|无法接通|无法连接|不可达|'
    r'尚未可用|尚未就位|(?:被|受|仍)[^，。;；、]{0,12}?阻塞')
# 「已就位」类措辞：对 ready=false 的事实说这种话＝把未就位写成 ready（RA1/规则 23 不许）
ENV_AVAIL_RE = re.compile(
    r'已就位|已可用|已实测|实测可用|实测均通|自建成功|已装|已安装|已通过|在册|已冒烟')
# 已处置/时效标记：同句出现即视为历史叙述或更正句（口径同 no-live-legacy-ref 的 RETIRED_CTX）
ENV_SETTLED_RE = re.compile(
    r'不再是|已解决|已闭合|已恢复|已处置|作废|退役|留档|历史|快照|更正|已过期|不阻塞|不得|禁止|永不')


def _env_units(text, base=0):
    """文本 → 判定单元 `[(行号, 单元文本)]`：表格行整行＝一个单元（同 no-live-legacy-ref 口径），
    其余按 `；;。` 切句。**行号基准**＝`base`（供切片场景保留原文行号）。"""
    out = []
    for i, ln in enumerate((text or '').splitlines(), 1):
        if not ln.strip():
            continue
        if ln.lstrip().startswith('|'):
            out.append((base + i, ln))
            continue
        for u in re.split(r'[；;。]', ln):
            if u.strip():
                out.append((base + i, u))
    return out


def _env_agents1():
    """`AGENTS.md` §1「项目信息」切片：返回 [(行号, 单元)]；缺件/找不到该节 ⇒ None（由判据 fail-closed）。"""
    p = os.path.join(ROOT, 'AGENTS.md')
    if not os.path.exists(p):
        return None
    lines = io.open(p, 'r', encoding='utf-8').read().splitlines()
    lo = hi = None
    for i, ln in enumerate(lines):
        if lo is None and re.match(r'^##\s*1\.', ln):
            lo = i
        elif lo is not None and re.match(r'^##\s', ln):
            hi = i
            break
    if lo is None:
        return None
    seg = '\n'.join(lines[lo:hi if hi is not None else len(lines)])
    return _env_units(seg, base=lo + 1)


def _env_scan_sources():
    """活文档速查面（4 面）：本文件的判据消息文本 ／ `state/flow.json` 的
    `blocked_by`·`env_blocked`·需人项字段 ／ `AGENTS.md` §1 ／ `doc/当前目标卡.md`。
    返回 `(sources, missing)`：`sources=[(显示名, [(标签, 单元文本)])]`；缺件进 `missing`（fail-closed）。"""
    src, missing = [], []
    with io.open(os.path.abspath(__file__), 'r', encoding='utf-8') as f:
        src.append(('script/flow.py', [('L%d' % i, u) for i, u in _env_units(f.read())]))
    st = load_json(STATE) or {}
    js = []
    for m in st.get('milestones', []):
        if m.get('blocked_by'):
            js.append(('milestones[%s].blocked_by' % m.get('id'), str(m['blocked_by'])))
        for k, b in enumerate(m.get('env_blocked') or []):
            if b.get('why'):
                js.append(('milestones[%s].env_blocked[%d].why' % (m.get('id'), k), str(b['why'])))
    for s in st.get('steps', []):
        if s.get('blocked_by'):
            js.append(('steps[%s].blocked_by' % s.get('id'), str(s['blocked_by'])))
        if s.get('role') == 'human' or s.get('status') == 'waiting_human':
            for fld in ('task', 'done'):
                if s.get(fld):
                    js.append(('steps[%s].%s' % (s.get('id'), fld), str(s[fld])))
    src.append(('state/flow.json', [(k, u) for k, v in js for _, u in _env_units(v)]))
    a1 = _env_agents1()
    if a1 is None:
        missing.append('AGENTS.md §1')
    else:
        src.append(('AGENTS.md §1', [('L%d' % i, u) for i, u in a1]))
    card = os.path.join(ROOT, 'doc', '当前目标卡.md')
    if not os.path.exists(card):
        missing.append('doc/当前目标卡.md')
    else:
        src.append(('doc/当前目标卡.md',
                    [('L%d' % i, u) for i, u in _env_units(io.open(card, encoding='utf-8').read())]))
    return src, missing


def chk_env_facts_consistency():
    """env-facts-consistency：活文档对**环境可用性**的表述必须与单一真源 `state/env.json` 对齐。

    扫描面（4 面，均为活文档速查面）：本文件的判据消息文本 ／ `state/flow.json` 的
    `blocked_by`·`env_blocked`·需人项字段 ／ `AGENTS.md` §1 ／ `doc/当前目标卡.md`。
    判定三向（同句含 ENV_SETTLED_RE 者放行＝历史叙述/更正句）：
      ① ready=true 的事实被写成"不可用/未就位/待装"类 ⇒ FAIL；
      ② ready=false 的事实被写成"已就位/已装"类 ⇒ FAIL（防把未就位写成 ready）；
      ③ retired=true 的事实（已作废路线）被提及而无"作废/更正"语境 ⇒ FAIL。
    fail-closed：env.json 缺失/结构坏/事实无别名登记/ref 锚点在台账查无/扫描面缺件 ⇒ 一律 FAIL。
    """
    env = load_json(ENV_FACTS)
    if not isinstance(env, dict) or not isinstance(env.get('facts'), dict) or not env['facts']:
        return False, ('缺/坏 %s（环境可用性单一真源；fail-closed）' % rel(ENV_FACTS))
    facts = env['facts']
    groups = env.get('groups') or {}
    ent_all = dict(facts)
    ent_all.update(groups)
    bad = []
    for k, v in ent_all.items():
        if k not in ENV_ALIASES:
            bad.append('%s 未在 ENV_ALIASES 登记别名（fail-closed）' % k)
        if not isinstance(v, dict) or not isinstance(v.get('ready'), bool):
            bad.append('%s 无布尔 ready' % k)
        elif not str(v.get('ref') or '').strip():
            bad.append('%s 无 ref 锚点' % k)
    for k, v in groups.items():
        mem = (v or {}).get('members') or []
        if not mem or any(x not in facts for x in mem):
            bad.append('groups.%s 的 members 未全部登记为 facts' % k)
        elif v.get('ready') is not all(facts[x].get('ready') is True for x in mem):
            bad.append('groups.%s.ready 与成员实况不符（表内自洽断言）' % k)
    led = load_json(LEDGER) or {}
    ents = led.get('entries') or []
    ids = set(str(e.get('id')) for e in ents)
    ltxt = ' '.join(str(e.get('text') or '') for e in ents)
    for k, v in ent_all.items():
        for tok in re.findall(r'\b(?:R|ISS)-\d+\b', str((v or {}).get('ref') or '')):
            if tok not in ids and tok not in ltxt:
                bad.append('%s.ref 锚点 %s 在台账查无（fail-closed）' % (k, tok))
    if bad:
        return False, ('state/env.json 结构/锚点 %d 处不合（fail-closed）：%s'
                       % (len(bad), '；'.join(bad[:8])))
    src, missing = _env_scan_sources()
    if missing:
        return False, '扫描面缺件（fail-closed）：%s' % '、'.join(missing)
    hits, n_units = [], 0
    for name, units in src:
        for label, u in units:
            n_units += 1
            if ENV_SETTLED_RE.search(u):
                continue
            for k, pat in ENV_ALIASES.items():
                if not re.search(pat, u):
                    continue
                v = ent_all.get(k) or {}
                if v.get('retired'):
                    hits.append('%s:%s 已作废事实被当活引用（%s）｜原文:%s'
                                % (name, label, k, u.strip()[:44]))
                elif v.get('ready') and ENV_UNAVAIL_RE.search(u):
                    hits.append('%s:%s 已就位事实被写成不可用（%s）｜原文:%s'
                                % (name, label, k, u.strip()[:44]))
                elif v.get('ready') is False and ENV_AVAIL_RE.search(u):
                    hits.append('%s:%s 未就位事实被写成已就位（%s）｜原文:%s'
                                % (name, label, k, u.strip()[:44]))
    if hits:
        return False, ('活文档与 state/env.json 相抵 %d 处：%s%s'
                       % (len(hits), '；'.join(hits[:12]),
                          '…（只列前 12）' if len(hits) > 12 else ''))
    return True, ('state/env.json 登记 %d 条事实/组（ref 锚点全可查）与 %d 个活文档面一致；'
                  '扫 %d 个判定单元，0 处相抵' % (len(ent_all), len(src), n_units))


# --------------------------------------------------------------------------- #
# 判据注册表（放在文件末尾构建：模块级名字需在调用时才解析，故位置不影响）
CHECKS = {
    'params-drift': chk_params_drift,
    'params-coverage': chk_params_coverage,
    'params-invariants': chk_params_invariants,
    'params-compile': chk_params_compile,
    'params-units': chk_params_units,          # 只报告（恒 PASS，不作门禁）：见函数 docstring
    'params-elab': chk_params_elab,
    'types-elab': chk_types_elab,
    'image-hex': chk_image_hex,
    'trace-self': chk_trace_self,
    'width-check': chk_width,
    'types-drift': chk_types_drift,
    'types-coverage': chk_types_coverage,
    'types-width-consistency': chk_types_width_consistency,
    'types-crosscheck': chk_types_crosscheck,
    'types-compile': chk_types_compile,
    # G1-I 冻结面（清单 §2／§4；doc/decisions/G1-I-最小冻结清单.md）
    'csr-table': chk_csr_table,
    'code-table': chk_code_table,
    'gi-pkg-binding': chk_gi_pkg_binding,
    'isop-subset': chk_isop_subset,
    'iss-smoke': chk_iss_smoke,
    # M1 两条 exit（GI-14）：`rtl-compile` 已真实化（vlog 编 filelist/rtl.f）；
    # `rtl-vs-iss` 仍为自报 BLOCKED 的桩（产出侧未就位，见该函数 docstring）
    'rtl-compile': chk_rtl_compile,
    'rtl-vs-iss': chk_rtl_vs_iss,
    # M1-S1 步的完成判据（判据②；**不进 M1 的两条 exit、不进常跑守卫**——要 vlog+vopt+vsim，
    # 且 vsim 涉 license 抖动：口径见 chk_rtl_fetch_win 的 docstring）
    'rtl-fetch-win': chk_rtl_fetch_win,
    # M1-S2 步的完成判据（判据② 的"S4 之前可判"部分：D 级 `uop_t.pc/raw32/isop` 与握手面；
    # **不进 M1 的两条 exit、不进常跑守卫**——要 vlog+vopt×2+vsim×2，且 vsim 涉 license 抖动：
    # 口径见 chk_rtl_decode_win 的 docstring）
    'rtl-decode-win': chk_rtl_decode_win,
    # M2 exit 三条（2026-09-26 入册，R0 心跳批口径）：
    #   · `m2-rv64ui`  —— 真判（真跑 ISS＋RTL＋逐条比对，见其 docstring）；
    #   · `m2-regress` —— 真判（**只核证据、不重跑重活**：两轮 summary/cases/config 自洽 ＋
    #                     round_diff 0 新 FAIL ＋ R10/R9 在环 ＋ 两轮指纹与当前 rtl.f 同版本）；
    #   · `m2-cov`     —— 真判（报告在册 ＋ 编译指纹在册且与当前 rtl.f 同版本；**不要求达阈值**）。
    #   两条都**不进 GUARDS**（核证据虽便宜，但证据刷新要靠跑仿真；且它们是 M2 的 exit 而非常跑守卫）。
    'm2-rv64ui': chk_m2_rv64ui,
    'm2-regress': chk_m2_regress,
    'm2-cov': chk_m2_cov,
    # M3 exit 三条（2026-09-26 心跳第十一轮入册，R0 授权口径 A）：**只核证据＋时效，不重跑重活**；
    # 阈值取 `AGENTS.md` §4 原文（功能 100%／代码 ≥90% 逐项），未达标**如实 FAIL**、不放宽；
    # 三条都**不进 GUARDS**（要读报告/指纹/多轮证据，且证据刷新靠跑仿真，与 M2 两条同口径）。
    # 第三条 M3 exit（`m3-mutation-audit`）**仍未注册**：机制（VP-X05 变异注入）尚无落点，
    # 按"未注册即 fail-closed"保留待注册，不假落（TODO(M3-3)）。
    'm3-code-cov': chk_m3_code_cov,
    'm3-func-cov': chk_m3_func_cov,
    'm3-regress-stab': chk_m3_regress_stab,
    # GI-13 的 TB 侧（2026-09-26）：TB 单元件编译 + trace 格式契约（两条都不进 M1 exit，列常跑守卫）
    'tb-compile': chk_tb_compile,
    'trace-format-contract': chk_trace_format_contract,
    'env-facts-consistency': chk_env_facts_consistency,
    'md-integrity': chk_md_integrity,
    'codepoints': chk_codepoints,
    'ra-token-defined': chk_ra_tokens,
    'ref-target-exists': chk_ref_target_exists,
    'id-unique': chk_id_unique,
    'no-live-legacy-ref': chk_no_live_legacy_ref,
}
# 常跑守卫（不判产品，判「规则承载件/文档自身没坏」；很便宜，每轮都跑）
#   2026-09-26 追加两条 TB 侧守卫（口径见各自 docstring）：
#     · `tb-compile`——vlog 编 filelist/tb_unit.f（**只 vlog、不涉 vsim license** ⇒ 可常跑，不把
#       license 抖动（ISS-104）误报成产品 FAIL）；
#     · `trace-format-contract`——TB 格式期望件零漂移 + 表头/ABI 名表逐字 + golden 端 0 mismatch（纯 Python）。
GUARDS = ['ra-token-defined', 'md-integrity', 'codepoints',
          'ref-target-exists', 'id-unique', 'no-live-legacy-ref',
          'env-facts-consistency', 'tb-compile', 'trace-format-contract']


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 0
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == 'check':
        return cmd_check()
    if cmd == 'check-one':                      # 单判据入口：供 run 的步骤复用同一判据函数（禁二次实现）
        if not args or args[0] not in CHECKS:
            print('用法: flow.py check-one <%s>' % '|'.join(sorted(CHECKS)))
            return 2
        ok, msg = CHECKS[args[0]]()
        print('[%s] %s: %s' % ('PASS' if ok else 'FAIL', args[0], msg))
        return 0 if ok else 1
    if cmd == 'next':
        return cmd_next()
    if cmd == 'run':
        return cmd_run(int(args[0]) if args else 3)
    if cmd == 'params':
        return cmd_params()
    if cmd == 'types':
        return cmd_types()
    if cmd == 'ctx':
        return cmd_ctx()
    if cmd == 'gate-stop':
        return cmd_gate_stop()
    if cmd == 'guard-write':
        return cmd_guard_write()
    if cmd == 'guard-bash':
        return cmd_guard_bash()
    if cmd == 'window':
        return cmd_window(args)
    if cmd == 'record':
        if len(args) < 2 or args[0] not in KINDS:
            print('用法: flow.py record <ISS|R|ADR> "文本"\n'
                  '      ADR 走编号分区：写入 id 形如 ADR-P-<n>（禁手写；分区口径见 AGENTS.md §0）')
            return 2
        record(args[0], args[1])
        return 0
    if cmd == 'board':
        led = load_json(LEDGER) or {'entries': [], 'next': {}}
        print('台账 %d 条；next=%s' % (len(led['entries']), led.get('next')))
        for e in led['entries'][-6:]:
            print('  %-8s %s' % (e['id'], e.get('text', '')[:70]))
        return 0
    print('未知子命令 %s' % cmd)
    return 2


if __name__ == '__main__':
    sys.exit(main())
