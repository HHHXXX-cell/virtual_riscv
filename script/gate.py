#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate.py — VR1 机械核销与派发器（R8 编排 AI 的执行工具）

为什么要有它：本仓库已发生 4 类"声明与实态脱钩"失效，且全部是人眼与 diff 拦不住的——
  ISS-021 处置列写了没落实 / ISS-022 只读约束被违反 34 个文件 / ISS-031 看板计数落后 10 条 /
  ISS-026 中文静默错字 7 处（扫 描→扇、锚→锈、经 验→骍、脱→脉…）。
所以核销只能是机器判据，不能靠自觉。

子命令：
  check      跑全部不变式，任一 FAIL 退出码 1（R8 每轮开工第一件事）
  snapshot   完整性长基线（ADR-4/ISS-024）：受控目录集逐文件 md5:size:mtime →
             script/gate/integrity_baseline.json；刷新须 --refresh --reason <折入集出处>
  rocheck    只读核查：--baseline 对长基线（内容侧差异非零退出）；--window <ISO>
             全仓窗口（含忽略区，仅排除 .git/、__pycache__/；纯 mtime 差记 MTIME-ONLY(INFO)）
  dispatch   取队首可执行项，打印归属角色 + 完成判据
  changed    生成"改动集"（改动节 + 被改标识符的引用闭包），供增量复核轮当复核面（§9.4）
             默认只列真信号（未展开项 + ≥10 的枢纽项），全表加 `--all`
  report     队列与门禁看板摘要
  escalate   把某条台账项打成"≤5 选项决策包"呈 R0（《AI进行IC开发验证工作流程》§5 格式）
  attempts   派发失败计数（ISS-053）：attempts <Q-id> [--reset]；达 3 自动 blocked 转人

依据：doc/项目开发流程.md §9.4（评审收敛两档制）、§12.1~12.4；
      《AI进行IC开发验证工作流程》v3.0 §6.1（评审收敛；该节 2026-09-23 由 v3.0 新建）；
      doc/AI角色与职责.md §2（角色与写边界）、§6.1（角色数封顶）。
"""
import datetime
import glob
import hashlib
import io
import json
import os
import re
import sys

# Windows 控制台默认 GBK：输出含 ⚠ 等字符时 print 会抛 UnicodeEncodeError（A7-BLK-1 根因）
for _s in (getattr(sys, 'stdout', None), getattr(sys, 'stderr', None)):
    if _s is not None and hasattr(_s, 'reconfigure'):
        try:
            _s.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LEDGER = os.path.join(ROOT, 'doc', 'process', '00-问题记录.md')
BOARD = os.path.join(ROOT, 'doc', 'verify', '04-验证进度.md')
QUEUE = os.path.join(ROOT, 'run_cmd', 'AutoQueue.yaml')
HANDOFF = os.path.join(ROOT, '.qoder', 'handoff', 'HANDOFF.md')

# 坏词表：每条必须能指到一次真实事故（doc/process/00 ISS-026 / ISS-033），无出处者不得入表——
# 本表初版曾收“跳页同偏”“帐台”两条凭印象写的条目，跑一次即发现“跳页同偏”其实是
# ISS-020 正文的合法用词，属工具自造的假阳。**单字级**形近字表已证明不可用（会把“脉冲”误报）。
# 同理“计数脉”也已删除：它在 spec/01 里是“计数脉冲”这种正确用词的前三个字。
SUSPECT_BIGRAMS = ['锈点', '待锈', '已锈', '扇描', '扇扫', '脉钩', '脉陷', '脉同步',
                   '脸钩', '经骍', '环环境', '捾任务', '进徚', '呷 R']  # 逐条对应已发生的错字事故；新事故即加一行
ZERO_WIDTH = (0x200b, 0x200c, 0x200d, 0xfeff, 0x00a0)
REQ_FIELDS = ['id', 'task', 'role', 'basis', 'done_when', 'state', 'priority',
              'depends_on', 'blocked_by', 'review_rounds']
VALID_STATE = {'ready', 'blocked', 'in_progress', 'in_review', 'done', 'fused'}
REVIEW_CAP = 5
FULL_ROUND_CAP = 5      # §9.4：终局全量复核轮上限，到限 fused 转 R0
CHANGED_PREFIXES = ('doc/', 'iss/', 'rtl/', 'tb/', 'sw/', 'script/', 'run_cmd/', '.qoder/')


def _qint(v):
    """队列字段取整。parse_queue 一律返回字符串，故旧代码里的 isinstance(x, int) 恒假——
    这会让 queue-review-cap / queue-attempts-cap 两项判据变成**永不触发的死代码**
    （第 6 轮复核 BLK-16 实测指出）。此处统一转换，无法转换返回 None（由调用方决定口径）。"""
    try:
        return int(str(v).strip())
    except Exception:
        return None


def read(p):
    return io.open(p, encoding='utf-8', errors='replace').read()


# ---------------------------------------------------------------- 台账解析
def parse_ledger():
    txt = read(LEDGER)
    rows, declared = {}, {}
    for line in txt.splitlines():
        if line.startswith('| **ISS-') and line.count('|') >= 11:
            cols = [c.strip() for c in line.split('|')]
            m = re.search(r'ISS-(\d{3})', cols[1])
            if not m:
                continue
            if len(cols) < 12:
                rows[m.group(1)] = {'malformed': len(cols)}
                continue
            rows[m.group(1)] = {'cat': cols[2], 'state': cols[7],
                                'fixed_at': cols[10], 'plan': cols[9]}
        elif re.match(r'\|\s*(?:\*\*)?(待决策|处理中|已解决|合计)(?:\*\*)?\s*\|', line):
            key = re.match(r'\|\s*(?:\*\*)?(待决策|处理中|已解决|合计)', line).group(1)
            num = re.search(r'\|\s*\**([0-9]+)\**\s*\|', line)
            if num:
                declared[key] = int(num.group(1))
    # 待决策清单节里出现的 ID（分组行 "ISS-025 / 027 / 028" 也认）
    pend_ids = set()
    if '## 待决策清单' in txt:
        for line in txt.split('## 待决策清单', 1)[1].splitlines():
            if line.startswith('| ISS-') or line.startswith('| **ISS-'):
                ids = re.findall(r'ISS-(\d{3})', line)
                tail = re.findall(r'/\s*(\d{3})', line)
                for t in tail:
                    ids.append(t)
                pend_ids.update(ids)
    return txt, rows, declared or {}, pend_ids


RA_DEFINED = {1, 2, 3, 4}
RULE_FILES = ['AGENTS.md', os.path.join('doc', '项目开发流程.md'),
              os.path.join('doc', 'AI角色与职责.md'),
              os.path.join('.qoder', 'agents', 'vr1-auditor.md'),
              os.path.join('.qoder', 'agents', 'vr1-decider.md')]
# 活引用面（2026-09-23 R0 批扩面）：规则承载件 + 工具/队列**全件**；HANDOFF 只取**最后一条记录**的
# 未完成/下一手（最新交接面，其下均为快照记录）。依据：ISS-049 实证——工具打印串与队列协议头
# 曾残留未定义编号，而旧扫描面（仅 RULE_FILES）不覆盖 ⇒ 靠人工回头核查才发现。
RA_LIVE_FILES = (RULE_FILES + ['script/gate.py', os.path.join('run_cmd', 'AutoQueue.yaml'),
                # 送审批补齐（Q-031/ISS-090 B-1，2026-09-24）：原扫面缺三角色件与两流程/计划件 ⇒
                # 未定义编号可在这些文件回流；构造证据＝在其中写入未定义编号后旧扫面仍 PASS（送审报告 B-1）。
                os.path.join('.qoder', 'agents', 'vr1-designer.md'),
                os.path.join('.qoder', 'agents', 'vr1-planner.md'),
                os.path.join('.qoder', 'agents', 'vr1-verifier.md'),
                os.path.join('doc', '自动推进说明.md'),
                os.path.join('doc', 'verify', '03-验证计划.md')])
RA_RECORD_EXEMPT = '记录不改写'   # 行级豁免标记：行内含它即跳过（记录性出现须逐行显式标注理由）


def check_ledger(rep):
    txt, rows, declared, pend_ids = parse_ledger()
    ids = sorted(int(k) for k in rows)
    n = len(ids)
    # 1) 状态计数
    real = {'待决策': 0, '处理中': 0, '已解决': 0}
    for k, v in rows.items():
        st = v.get('state', '')
        for key in real:
            if key in st:
                real[key] += 1
                break
        else:
            rep.fail('ledger-state-unknown', 'ISS-%s 状态列无法识别：%r' % (k, st))
    for key, cnt in real.items():
        if key not in declared:
            rep.fail('ledger-count-row-missing', '状态总览缺「%s」行或未加粗包数字' % key)
        elif declared[key] != cnt:
            rep.fail('ledger-count', '%s 总览写 %s，实测 %d' % (key, declared[key], cnt))
        else:
            rep.ok('ledger-count-' + key, '%s = %d 一致' % (key, cnt))
    if '合计' in declared and declared['合计'] != n:
        rep.fail('ledger-total', '合计写 %s，实测 %d 行' % (declared['合计'], n))
    else:
        rep.ok('ledger-total', '合计 %d 行一致' % n)
    # 2) ID 连续
    gaps = [i for i in range(1, n + 1) if ('%03d' % i) not in rows]
    rep.res('ledger-contiguous', gaps, '缺号 %s' % ['ISS-%03d' % g for g in gaps])
    # 3) 已解决必须有时间
    nofix = [k for k, v in rows.items() if '已解决' in v.get('state', '')
             and v.get('fixed_at', '—').strip() in ('—', '', '-')]
    rep.res('solved-needs-date', nofix, '已解决但无解决时间：%s' % nofix)
    # 4) 待决策状态必须出现在待决策清单
    miss = [k for k, v in rows.items() if '待决策' in v.get('state', '') and k not in pend_ids]
    rep.res('pending-in-list', miss, '状态=待决策但未列入待决策清单：%s' % ['ISS-' + m for m in miss])
    # 4b) 反向：清单里不得留已闭环项（清单语义＝待拍板的决策点，闭环后须移出）
    stale = []
    for k in sorted(pend_ids):
        v = rows.get(k)
        if v is None:
            stale.append('ISS-%s(台账无此行)' % k)
        elif '已解决' in v.get('state', ''):
            stale.append('ISS-%s(已解决)' % k)
    rep.res('pending-list-stale', stale, '待决策清单仍列已闭环项：%s' % stale)
    # 5) 处置必须"已落实"：已解决项的解决方案/时间须有落点线索（含 ISS/§/文件扩展名/脚本名）
    thin = []
    for k, v in rows.items():
        if '已解决' not in v.get('state', ''):
            continue
        plan = v.get('plan', '') + ' ' + v.get('fixed_at', '')
        if not re.search(r'`\S+\.(sv|svh|py|md|yaml|do)|[\w]+\.\w+\(|`_?\w+\(|§\d|ISS-\d|doc/\d|L\d+', plan):
            thin.append('ISS-' + k)
    rep.res('solved-needs-landing', thin, '已解决但解决方案里找不到可回查落点：%s' % thin)


# ---------------------------------------------------------------- 看板解析
def check_board(rep):
    txt, rows, _, _ = parse_ledger()
    if not os.path.exists(BOARD):
        rep.fail('board-missing', '看板不存在')
        return
    b = read(BOARD)
    m = re.search(r'(\d+)\s*\*\*\s*条?\s*[（(]\s*(\d+)\s*待决策\s*/\s*(\d+)\s*处理中\s*/\s*(\d+)\s*已解决', b)
    if not m:
        m = re.search(r'\*\*(\d+)\*\*\s*条\s*[（(]\s*(\d+)\s*待决策\s*/\s*(\d+)\s*处理中\s*/\s*(\d+)\s*已解决', b)
    if not m:
        rep.warn('board-no-counter', '看板未写台账计数镜像行（可选）')
        return
    got = [int(x) for x in m.groups()]
    want = [len(rows), sum(1 for v in rows.values() if '待决策' in v.get('state', '')),
            sum(1 for v in rows.values() if '处理中' in v.get('state', '')),
            sum(1 for v in rows.values() if '已解决' in v.get('state', ''))]
    rep.res('board-mirrors-ledger', [] if got == want else [1],
            '看板写 %s，台账实测 %s（看板须镜像台账）' % (got, want))


# ---------------------------------------------------------------- 队列解析
def parse_queue():
    txt = read(QUEUE)
    items, cur = [], None
    for raw in txt.splitlines():
        line = raw.split('#')[0].rstrip() if not raw.lstrip().startswith('#') else ''
        if not line.strip():
            continue
        s = line.strip()
        if s.startswith('- '):
            cur = {}
            items.append(cur)
            s = s[2:]
        elif s.startswith('meta:') or not s or cur is None:
            if s.startswith('meta:'):
                cur = None
            continue
        m = re.match(r'([A-Za-z_]+)\s*:\s*(.*)$', s)
        if m and cur is not None:
            v = m.group(2).strip()
            if v.startswith('[') and v.endswith(']'):
                v = [x.strip() for x in v[1:-1].split(',') if x.strip()]
            cur[m.group(1)] = v
    return [i for i in items if i.get('id')]


def check_queue(rep):
    if not os.path.exists(QUEUE):
        rep.fail('queue-missing', QUEUE)
        return
    items = parse_queue()
    ids = [str(i.get('id')) for i in items]
    dups = {x for x in ids if ids.count(x) > 1}
    rep.res('queue-id-unique', sorted(dups), '重复 id %s' % sorted(dups))
    _, rows, _, _ = parse_ledger()
    for i in items:
        qid = i.get('id', '?')
        lack = [f for f in REQ_FIELDS if f not in i]
        if lack:
            rep.fail('queue-schema', '%s 缺字段 %s' % (qid, lack))
        if i.get('state') not in VALID_STATE:
            rep.fail('queue-state', '%s state=%r 非法' % (qid, i.get('state')))
        rr = _qint(i.get('review_rounds'))
        if rr is not None and rr > REVIEW_CAP:
            # 轮次上限是红线，但**可以由人越权**：须带 cap_waiver（写明谁在何时批准）；
            # 无人批准就不得越过——“继续直到收敛”这类指令必须留痕，不能靠口头。
            if str(i.get('cap_waiver', '')).strip():
                rep.ok('queue-review-cap-waiver', '%s 已越权继续（%s）' % (qid, str(i['cap_waiver'])[:60]))
            else:
                rep.fail('queue-review-cap', '%s 评审 %d 轮 > 上限 %d（§6.1 应已 fused 并升级）'
                         % (qid, rr, REVIEW_CAP))
        # 派发失败（空返回/取消/超时）可自动重派，但不得超过 2 次；第 3 次必须转人
        at = _qint(i.get('attempts'))
        if at is not None and at >= 3 and i.get('state') not in ('blocked', 'fused'):
            rep.fail('queue-attempts-cap',
                     '%s attempts=%d ≥3 但仍为 %s（失败重派上限 2 次，到限须置 blocked/fused 转人）'
                     % (qid, at, i.get('state')))
        # §9.4：终局全量复核轮上限 5 次。语义＝**已消耗**的全量轮数；已达 5 即不得再加轮，
        # 须置 fused 并 escalate 转 R0。与 review_rounds 同源：人可越权（须带 cap_waiver 写明谁在何时批准），
        # 无批文一律 FAIL——不许靠"再跑一轮看看"把上限磨掉。
        fr = _qint(i.get('full_rounds'))
        if fr is not None and fr >= FULL_ROUND_CAP and i.get('state') not in ('done', 'blocked', 'fused'):
            if str(i.get('cap_waiver', '')).strip():
                rep.ok('queue-full-round-cap-waiver', '%s 全量轮已用 %d/%d，越权继续（%s）'
                       % (qid, fr, FULL_ROUND_CAP, str(i['cap_waiver'])[:60]))
            else:
                rep.fail('queue-full-round-cap',
                         '%s 全量复核轮已用 %d/%d（§9.4：应已 fused 并 escalate 转 R0）'
                         % (qid, fr, FULL_ROUND_CAP))
        elif fr is not None:
            # 已闭合项（done/fused）不适用上限——措辞单列，避免"5/5 未达限"式误读（ISS-070/C-3）
            if i.get('state') in ('done', 'fused'):
                rep.ok('queue-full-round-cap', '%s 全量轮 %d/%d（已闭合，cap 不适用）' % (qid, fr, FULL_ROUND_CAP))
            else:
                rep.ok('queue-full-round-cap', '%s 全量轮 %d/%d（未达限）' % (qid, fr, FULL_ROUND_CAP))
        for d in i.get('depends_on', []) or []:
            if d not in ids:
                rep.fail('queue-deps', '%s 依赖不存在的 %s' % (qid, d))
        for b in i.get('blocked_by', []) or []:
            if b.startswith('ISS-') and b[4:].lstrip('0') not in {k.lstrip('0') for k in rows}:
                rep.fail('queue-block', '%s 的 blocked_by 指向不存在台账项 %s' % (qid, b))
        if i.get('state') == 'done' and not str(i.get('landable', '')).strip():
            rep.fail('queue-landing', '%s 标 done 但 landable 为空（C1：无落点不算闭环）' % qid)
    # ISS-053：attempts>0 却仍留 ready（“计了失败却仍在待派”）→ WARN 提醒人工确认；
    # 非 FAIL：可能是计完手动重派成功后再回 ready，须人判，不自动改状态。
    att = ['%s(attempts=%s)' % (x.get('id'), x.get('attempts'))
           for x in items if (_qint(x.get('attempts')) or 0) > 0 and x.get('state') == 'ready']
    if att:
        rep.warn('queue-attempts-ready', '计了派发失败数却仍在待派（人工确认：转人 or 重派）：%s' % ', '.join(att))
    rep.ok('queue-schema', '队列 %d 项：ready=%d / blocked=%d / 评审中=%d / done=%d'
           % (len(items),
              sum(1 for i in items if i.get('state') == 'ready'),
              sum(1 for i in items if i.get('state') == 'blocked'),
              sum(1 for i in items if i.get('state') in ('in_review', 'in_progress')),
              sum(1 for i in items if i.get('state') == 'done')))


# ---------------------------------------------------------------- 文本完整性
def role_agent_files():
    d = os.path.join(ROOT, '.qoder', 'agents')
    return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith('.md')] \
        if os.path.isdir(d) else []


FREQ_BASE = []   # 字频基线缓存：(全库 md + 本仓文档) 的字符频次


def char_freq():
    if FREQ_BASE:
        return FREQ_BASE[0]
    fr = {}
    roots = []
    docroot = os.path.join(ROOT, 'doc')   # 语料根恒为 doc/ 全树（台账迁移后不得缩到 doc/process/）
    if os.path.isdir(docroot):
        roots.append(docroot)
    try:
        kb = 'D:\\' + [d for d in os.listdir('D:\\') if d.startswith('IC')][0]
        roots.append(kb)
    except OSError:
        pass
    for rt in roots:
        for r, _ds, fs in os.walk(rt):
            if '参考书' in r or '_tools' in r:
                continue
            for f in fs:
                if f.endswith('.md'):
                    try:
                        txt = io.open(os.path.join(r, f), encoding='utf-8', errors='ignore').read()
                    except OSError:
                        continue
                    for c in txt:
                        fr[c] = fr.get(c, 0) + 1
    FREQ_BASE.append(fr)
    return fr


def scanned_docs():
    """需校字符完整性与表格结构的文档（含交接记录本身—它也会写错字）。"""
    files = []
    for dp, dns, fns in os.walk(os.path.join(ROOT, 'doc')):
        dns[:] = [d for d in dns if not d.endswith('评审探针')]   # 探针＝冻结证据，不入判据面
        files += [os.path.join(dp, f) for f in sorted(fns) if f.endswith('.md')]
    files.sort()
    files += [os.path.join(ROOT, f) for f in ('AGENTS.md', 'README.md')]
    files += role_agent_files()
    hd = os.path.join(ROOT, '.qoder', 'handoff')
    if os.path.isdir(hd):
        files += [os.path.join(hd, f) for f in sorted(os.listdir(hd)) if f.endswith('.md')]
    return files


def check_text(rep):
    files = scanned_docs()
    if os.path.exists(QUEUE):
        files.append(QUEUE)
    bad = []
    once_all = []
    for p in files:
        s = read(p)
        for bg in SUSPECT_BIGRAMS:
            if bg not in s:
                continue
            # 允许豁免，但必须是**逐行显式声明理由**（红线 R7 口径：放宽判据要可审）：
            #   行内含 'ISS-026'（台账与进度件引用错字本身当证据）或 '码点豁免' 标记
            bad_lines = [l for l in s.splitlines()
                         if bg in l and 'ISS-026' not in l and '码点豁免' not in l]
            if bad_lines:
                bad.append('%s: %s（%d 行，首行起 %s）'
                           % (os.path.basename(p), bg, len(bad_lines), bad_lines[0][:40]))
        zw = [hex(ord(c)) for c in s if ord(c) in ZERO_WIDTH]
        if zw:
            bad.append('%s: 零宽字符 %d 个' % (os.path.basename(p), len(zw)))
        # 字频法（ISS-026 的首选实现）：全库+全仓仅出现 1 次的汉字 = 疑错字。
        # 实测作 FAIL 会满屏假阳（“苗子/够狠/淡化/隶属”均为只用一次的正当词），
        # 所以只作 WARN 供人工扫读；硬判据仍留给下面的错词表与零宽。
        fr = char_freq()
        once = []
        for ln, line in enumerate(s.splitlines(), 1):
            for c in line:
                if '\u4e00' <= c <= '\u9fff' and fr.get(c, 0) <= 1 and c not in once_all:
                    once_all.append(c)
                    once.append(c)
    rep.res('codepoints', bad, '可疑词/零宽：%s' % bad[:10])
    if once_all:
        rep.warn('rare-chars(人工判)', '低频字 %d 个：%s' % (len(once_all), ' '.join(once_all[:14])))


def _ra_live_lines():
    """返回 [(显示名, 行号, 行文本)]：只含"活引用面"的行。
    规则承载件与工具/队列取全件；HANDOFF 只取**最后一条记录**的"未完成/下一手"两字段
    （最新交接面＝活指令；记录内其余字段与更早记录均属快照，按"记录不改写"免扫——理由：记录面不改写的既有约定；ISS-052）。"""
    out = []
    for rel in RA_LIVE_FILES:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            out.append((rel, 0, '<<MISSING>>'))
            continue
        for ln, line in enumerate(read(p).splitlines(), 1):
            out.append((rel, ln, line))
    if os.path.exists(HANDOFF):
        lines = read(HANDOFF).splitlines()
        # B-5（S-13 送审修复，2026-09-24，附 AJ／ISS-090）：原只认 `- [Q-` 标题，
        # 非 Q 标题条目（如 `- [S-xx…]`／`- [停轮…]`）被略过 ⇒「最新交接面」落后多轮。
        # 现＝最后一个 `- [` 引导的条目块；块内无五字段行时**全块细扫**（fail-closed）。
        idx = [i for i, l in enumerate(lines) if l.startswith('- [')]
        if idx:
            head = idx[-1]
            end = head + 1
            while end < len(lines) and not lines[end].startswith('- ['):
                end += 1
            key = None
            for ln, line in enumerate(lines[head:end], head + 1):
                m = re.match(r'- (产物|依据|机判|未完成|下一手)[：:]', line.strip())
                if m:
                    key = m.group(1)
                if key in ('未完成', '下一手'):
                    out.append(('.qoder/handoff/HANDOFF.md(最新记录)', ln, line))
            if key is None:                     # 无字段行 ⇒ 不静默跳过：整块纳入
                for ln, line in enumerate(lines[head:end], head + 1):
                    out.append(('.qoder/handoff/HANDOFF.md(最新记录无字段)', ln, line))
    return out


def check_redlines(rep):
    """活引用面不得引用未定义的 RA 编号（防"引用悬空"回流）。
    RA1~RA4 出自知识库《AI进行IC开发验证工作流程》§8；库内未定义更多编号
    （2026-09-23 两次实证：ISS-048 规则承载件 7 处、ISS-049 工具/队列 3 处——
    后者的旧扫描面盲区由 ISS-052 的人批扩面闭合）。
    扫描面＝规则承载件 + `script/gate.py` + `run_cmd/AutoQueue.yaml` 全件，
    加 HANDOFF **最后一条记录**的"未完成/下一手"（最新交接面）。
    记录面豁免：台账/回归记录/评审记录/HANDOFF 历史记录——那些是"已移除"的事后记载，不是引用；
    行级豁免标记 `记录不改写` 供个别例外逐行显式标注（沿用 codepoints 判据的先例；理由：同上；ISS-052）。"""
    bad = []
    for rel, ln, line in _ra_live_lines():
        if line == '<<MISSING>>':
            bad.append('%s: 规则承载件不存在' % rel)
            continue
        if RA_RECORD_EXEMPT in line:
            # B-4（S-13 送审修复，2026-09-24，附 AJ／ISS-090）：原「含标记即整行跳过」无理由/无审批；
            # 现要求同行显式理由（JS-编号 或「理由」字样），否则按未豁免处理（fail-closed）。
            if ('理由' in line) or re.search(r'ISS-\d{3}', line):
                continue
        # B-2（S-13）：原正则只认无分隔紧邻大写形，漏「连字符/空格/全小写」等形式（含大小写混写）；
        # 词边界（前非字母数字下划线）防「更长单词内子串」类误报。
        for m in re.finditer(r'(?<![A-Za-z0-9_])RA[\s\-]?(\d+)', line, re.I):
            if int(m.group(1)) not in RA_DEFINED:
                bad.append('%s:%d 引用未定义的 RA%s（知识库只定义 RA1~RA4）' % (rel, ln, m.group(1)))
    rep.res('ra-token-defined', bad, '活引用面未引用未定义 RA 编号')


def check_doc05_numbers(rep):
    """doc/verify/05 回归记录不得重号（2026-09-23 实测曾出现 R-032/R-033 各一对：并行会话与领队先后追加所致）。
    只判重号；序号因"补录/后移"本就非严格升序（R-014/R-037/R-038 为例外），故不判倒序。"""
    p = os.path.join(ROOT, 'doc', 'verify', '05-回归记录.md')
    seen, dup = set(), []
    for ln, line in enumerate(read(p).splitlines(), 1):
        m = re.match(r'\| (R-\d{3})\s*\|', line)
        if not m:
            continue
        n = m.group(1)
        if n in seen:
            dup.append('%s 重号（行 %d）' % (n, ln))
        seen.add(n)
    # 只抓"R- 后不是三位数字"的畸形态（如 R-%03d）；'…备注' 类是合法的注记行，跳过
    bad_fmt = [l.split('|')[1].strip() for l in read(p).splitlines()
               if re.match(r'\| R-(?!\d)', l) and '备注' not in l]
    dup += ['格式非法：%s' % x for x in bad_fmt]
    rep.res('doc05-numbering', dup, 'R 编号无重号且格式合法（共 %d 条）' % len(seen))


def check_md(rep):
    """文档结构完整性：粗体重号、表格列数与表头不符。
    这些破损均源于 2026-09-23 的真实手改（粗体加号重叠、括号被吃）——肉眼反复漏，改由工具看。"""
    files = scanned_docs()
    problems = []
    for p in files:
        rel = os.path.relpath(p, ROOT)
        header_cols = None
        for ln, line in enumerate(read(p).splitlines(), 1):
            # 括号失配不做逐行判定：跨行括号结构（上一行开、下一行闭）是本文档集的合法写法，
            # 逐行查会满屏假阳（与“单字级形近字表”同一类粒度错误）。
            if re.search(r'\*{4,}', line.replace('---', '')):
                problems.append('%s:%d 粗体标记重叠 %s' % (rel, ln, line[:40]))
            if line.startswith('|'):
                n = line.replace('\\|', '').count('|')   # 转义竖线不算列分隔符
                if set(line.replace('|', '').strip()) <= set('-: '):
                    header_cols = n        # 分隔行定列数
                    continue
                if header_cols and n != header_cols and not line.startswith('|---'):
                    problems.append('%s:%d 表格列数 %d≠%d' % (rel, ln, n, header_cols))
            else:
                header_cols = None
    rep.res('md-integrity', problems, '；'.join(problems[:8]) + ('' if len(problems) <= 8 else ' …'))


HANDOFF_KEYS = ('产物', '依据', '机判', '未完成', '下一手')


def parse_handoff():
    """返回 {基项号: [(整项号, 缺字段列表)]}。一项可多条（多轮/子记录）。"""
    if not os.path.exists(HANDOFF):
        return None
    lines = read(HANDOFF).splitlines()
    idx = [i for i, l in enumerate(lines) if l.startswith('- [Q-')]
    out = {}
    for n, i in enumerate(idx):
        end = idx[n + 1] if n + 1 < len(idx) else len(lines)
        m = re.match(r'- \[(Q-\d+[a-z]?)\]', lines[i])
        if not m:
            continue
        body = '\n'.join(lines[i + 1:end])
        lack = [k for k in HANDOFF_KEYS if (k + ':') not in body and (k + '：') not in body]
        full = m.group(1)
        base = re.sub(r'[a-z]$', '', full)
        out.setdefault(base, []).append((full, lack))
    return out


def check_handoff(rep):
    """每个动过手的队列项必须有交接记录（子代理无主会话记忆，文件是唯一交接面）。"""
    if not os.path.exists(HANDOFF):
        rep.fail('handoff-missing', '.qoder/handoff/HANDOFF.md 不存在')
        return
    rec = parse_handoff()
    items = parse_queue()
    need = [str(i['id']) for i in items
            if i.get('state') in ('done', 'fused', 'in_progress')]
    gone = [q for q in need if q not in rec]
    rep.res('handoff-exists', gone, '已开工/已完/已熔断但无交接记录：%s' % gone)
    bad = [(full, lack) for lst in rec.values() for (full, lack) in lst if lack]
    rep.res('handoff-fields', bad, '交接记录缺字段：%s' % bad)
    qids = {re.sub(r'[a-z]$', '', str(i['id'])) for i in items}
    orphan = sorted({b for b in rec if b not in qids})
    rep.res('handoff-no-orphan', orphan, '交接记录指向不存在的队列项：%s' % orphan)


def check_width(rep):
    """机判位宽：调 width_check.py --json，将 MISMATCH 作 FAIL、UNVERIFIED/NO-TABLE 作 WARN。
    后者不能算过——它意味着该节无可核对的成员位宽表（正是 Q1/Q9 待落实项）。"""
    wc = os.path.join(ROOT, 'script', 'width_check.py')
    if not os.path.exists(wc):
        rep.warn('width-check-missing', 'script/width_check.py 不存在')
        return
    import subprocess
    try:
        out = subprocess.run([sys.executable, wc, '--json'], capture_output=True, text=True,
                             encoding='utf-8', errors='replace', timeout=60).stdout
        rows = json.loads(out[out.index('['):])
    except Exception as e:                        # 解析失败不得默认为过
        rep.fail('width-check-run', '调用失败：%s' % e)
        return
    bad = ['%s 实算%d vs 声明%s' % (r['struct'], r['sum_computed'], ','.join(map(str, r['claims'])))
           for r in rows if r['verdict'] in ('MISMATCH', 'TITLE-MISMATCH')]
    unver = [r['struct'] for r in rows if r['verdict'] in ('UNVERIFIED', 'NO-TABLE', 'NO-CLAIM')]
    rep.res('width-mismatch', bad, '；'.join(bad))
    if unver:
        rep.warn('width-unverifiable', '%d 个 struct 无法机器核对（缺成员位宽表或宽度为复合格式）：%s'
                 % (len(unver), ', '.join(unver)))


class Reporter(object):
    def __init__(self):
        self.fails, self.warns, self.oks = [], [], []

    def fail(self, tag, msg):
        self.fails.append((tag, msg))

    def warn(self, tag, msg):
        self.warns.append((tag, msg))

    def ok(self, tag, msg):
        self.oks.append((tag, msg))

    def res(self, tag, bad, msg):
        if bad:
            self.fail(tag, msg)
        else:
            self.ok(tag, '通过')

    def dump(self):
        for t, m in self.oks:
            print('  PASS  %-22s %s' % (t, m))
        for t, m in self.warns:
            print('  WARN  %-22s %s' % (t, m))
        for t, m in self.fails:
            print('  FAIL  %-22s %s' % (t, m))
        print('---- %d PASS / %d WARN / %d FAIL ----' % (len(self.oks), len(self.warns), len(self.fails)))
        return 1 if self.fails else 0


def cmd_check(_):
    rep = Reporter()
    print('== gate check（机械核销）==')
    check_ledger(rep)
    check_board(rep)
    check_queue(rep)
    check_text(rep)
    check_redlines(rep)
    check_doc05_numbers(rep)
    check_md(rep)
    check_handoff(rep)
    check_width(rep)
    check_capability_landed(rep)
    rc = rep.dump()
    if rc:
        print('R8 纪律：有 FAIL 即不得宣布任何"已落实"；修完重跑，不信任何口头结论。')
    return rc


def cmd_dispatch(_):
    items = parse_queue()
    done = {str(i['id']) for i in items if i.get('state') == 'done'}
    cand = [i for i in items
            if i.get('state') == 'ready'
            and not (i.get('blocked_by') or [])
            and all(d in done for d in (i.get('depends_on') or []))]
    if not cand:
        print('无可自决项（全被阻塞或已做完）。R8 转 escalate：把 blocked_by 逐条打决策包呈 R0。')
        return 2
    cand.sort(key=lambda i: (str(i.get('priority', 'P9')), str(i.get('id'))))
    it = cand[0]
    print('== dispatch：本轮切到 %s 做 %s ==' % (it.get('role'), it.get('id')))
    print('任务：%s' % it.get('task'))
    print('依据：%s' % it.get('basis'))
    print('完成判据（必须逐字满足，"已接受/同意改"不算）：\n  %s' % it.get('done_when'))
    print('写权限边界见 doc/AI角色与职责.md §2；完成后回填本项 state 与 landable，再跑 gate check。')
    rest = [i.get('id') for i in cand[1:]]
    if rest:
        print('后续可自决项：%s' % ', '.join(rest))
    print('（若本次派发失败——空返回/超时/被拒——请执行 `python script/gate.py attempts %s` 递增）' % it.get('id'))
    return 0


def cmd_report(_):
    items = parse_queue()
    print('== R8 看板 ==')
    for st in ('ready', 'in_progress', 'in_review', 'blocked', 'done', 'fused'):
        got = [str(i['id']) for i in items if i.get('state') == st]
        if got:
            print('  %-12s %2d  %s' % (st, len(got), ', '.join(got)))
    p1 = [i for i in items if i.get('priority') == 'P1' and i.get('state') != 'done']
    print('  挡门禁(P1 未完)：%s' % ', '.join('%s(%s)' % (i['id'], i.get('state')) for i in p1) or '无')
    blk = {}
    for i in items:
        for b in (i.get('blocked_by') or []):
            blk.setdefault(b, []).append(str(i['id']))
    if blk:
        print('  外部阻塞源：')
        for b, qs in sorted(blk.items()):
            print('    %-10s 卡住 %s' % (b, ', '.join(qs)))
    return 0


def cmd_escalate(argv):
    if len(argv) < 1:
        print('用法：gate.py escalate ISS-032')
        return 2
    want = argv[0].replace('ISS-', '').lstrip('0')
    _, rows, _, _ = parse_ledger()
    hit = {k: v for k, v in rows.items() if k.lstrip('0') == want}
    if not hit:
        print('台账无此条：%s' % argv[0])
        return 2
    k, v = list(hit.items())[0]
    print('【升级类型】需人拍板（doc/项目开发流程.md §12.3；红线 RA1：R8 不自决）')
    print('【问题】ISS-%s｜分类 %s｜状态 %s' % (k, v.get('cat'), v.get('state')))
    print('【已尝试】见台账"证据"列（原文含文件/节号与实跑结果）')
    print('【选项】A（推荐）按台账"决策"列的建议值执行；B 待你另给方案；C 暂缓但须写明影响面')
    print('【默认策略】本项属可回退时 24h 未选按 A 继续并在看板标"待追认"；'
          '属不可回退（接口冻结/基线/waiver/spec 升版）则必须等待明确答复')
    print('【挂起影响】gate.py report 的"挡门禁(P1 未完)"清单每轮会重复列出，直至本条闭环。')
    return 0


# ---------------------------------------------------------------- 改动集（§9.4 增量复核轮的复核面）
HUNK_RE = re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@')
HEAD_RE = re.compile(r'^(#{2,6})\s+(.+?)\s*$')
SYM_BT = re.compile(r'`([^`\n]{2,40})`')
# (?![./]) 是关键：否则 `riscv_spec_full.txt`、`gate.py` 会被切成标识符 `riscv_spec_full`，
# 报成"闭包未展开＝断链候选"——那是工具自造假阳（同一类错误见 ISS-026 的单字级形近字表）。
SYM_ID = re.compile(r'\b([a-z][a-z0-9_]*_[a-z0-9_]+)\b(?![./\w])')


def _git(args):
    import subprocess
    try:
        return subprocess.run(['git'] + args, cwd=ROOT, capture_output=True, text=True,
                              encoding='utf-8', errors='replace', timeout=90)
    except (OSError, subprocess.SubprocessError) as e:
        return None


def _heading_index(path):
    """当前文本的 (行号, 节号/标题) 递增表——把 diff 的 hunk 位置映射回**节号**。
    取证一律用节号而非行号：行号随编辑漂移，下一轮就得重新定位一遍（§9.4 第 3 条）。"""
    idx = []
    try:
        for ln, line in enumerate(read(path).splitlines(), 1):
            m = HEAD_RE.match(line)
            if m:
                idx.append((ln, m.group(2)))
    except OSError:
        pass
    return idx


def _section_at(idx, lineno):
    cur = '(篇首)'
    for ln, title in idx:
        if ln <= lineno:
            cur = title
        else:
            break
    return cur


def cmd_changed(argv):
    """改动集 ＝ 改动节 ∪ 被改标识符在全文的引用闭包。

    为什么由机器生成而非作者自报：本项目最大的一类缺陷**住在没改的那一侧**（断链/缺失型，
    如 N9/N10/X1——被改的 struct 有了新字段，未改的承载方却从不引用它），
    而作者自报已有前科（第 7 轮抓到"自报待办四项中三项半未落地"）。"""
    rev = next((a for a in argv if not a.startswith('-')), 'HEAD')
    show_all = '--all' in argv
    p = _git(['-c', 'core.quotePath=false', 'diff', '-U0', '--no-color', rev, '--']
             + list(CHANGED_PREFIXES))
    if p is None:
        print('git 不可调用 → 改动集无法生成。**不得据此认为"无改动"**（§9.4）。')
        return 2
    if p.returncode != 0:
        print('git diff 非零退出，改动集不可信：%s' % p.stderr.strip()[:200])
        return 2
    files, cur, syms = {}, None, {}
    for line in p.stdout.splitlines():
        if line.startswith('+++ b/'):
            cur = line[6:].strip()
            files.setdefault(cur, {'add': 0, 'del': 0, 'hunks': []})
            continue
        if cur is None:
            continue
        # 标识符抽取的**来源**与闭包**语料**必须同类：只取规格篇正文（`doc/spec/NN-*.md`；
        # 评审件已迁 `doc/review/`，此处靠路径天然隔离，下方排除式是防御性保留）。两条理由：① 记录类文本（`doc/process/00`/`doc/verify/0[45]`）是叙事件，其中
        # 引述的示例词（如描述缺陷时写到的 `clk_i`/`from`）会被当成"被改标识符"，凭空制造假未展开项；
        # ② 更致命的是反向——记录里提过一次的标识符会把规格正文里**只有 1 处**的真孤儿抬到 hits≥2
        # 而漏报（与第 7 轮"语料误含评审记录致假阴"同根因，该轮修了计数侧、本轮补上抽取侧）。
        # 证据/探针目录同理**只列不计**（其中 `snapshot_*.md` 是规格篇全文拷贝，会把整篇标识符重数一遍，
        # 实测使"未展开"由真值 7 项暴涨到 127 项）。两类文件**都仍照列于改动清单（不藏）**。
        evidence = '评审探针' in cur
        spec_prose = (bool(re.match(r'^doc/spec/\d{2}-', cur))
                      and '评审' not in os.path.basename(cur))
        m = HUNK_RE.match(line)
        if m:
            files[cur]['hunks'].append(int(m.group(1)))
            continue
        if line.startswith('+') and not line.startswith('+++'):
            body = line[1:]
            files[cur]['add'] += 1
        elif line.startswith('-') and not line.startswith('---'):
            body = line[1:]
            files[cur]['del'] += 1
        else:
            continue
        if evidence or not spec_prose:
            continue          # 见上：抽取侧与语料侧同类；记录/台账/脚本/队列另列，不参与闭包
        found = set()
        for s in SYM_BT.findall(body):
            if '/' in s:
                continue                      # 路径与文件名不是接口标识符
            for t in SYM_ID.findall(s) + ([s.strip()] if re.match(r'^[a-z][a-z0-9_]*$', s.strip()) else []):
                found.add(t)
        for t in SYM_ID.findall(body):
            found.add(t)
        for t in found:
            syms[t] = syms.get(t, 0) + 1
    ut = _git(['ls-files', '--others', '--exclude-standard', '--'] + list(CHANGED_PREFIXES))
    untracked = ut.stdout.splitlines() if ut and ut.returncode == 0 else []

    if not files and not untracked:
        print('改动集：相对 %s **无改动**。若你确知本轮动过手，先查 git 状态，勿直接宣布"本轮无改动面"。' % rev)
        return 0
    if len(syms) < 8:
        print('⚠ 自检：本轮仅提取到 %d 个标识符，低于可信阈值 8——扫描可能不完整'
              '（diff 为空/编码/路径前缀漏配），输出按**不可信**处理。' % len(syms))

    specdir = os.path.join(ROOT, 'doc', 'spec')
    # 闭包语料 ＝ **规格篇正文**（`NN-*.md`），**不含评审记录/探针**：后者是叙事件，把它的提及计进命中数两头失真——
    # 既会把 `cap_waiver`/`fused` 这类队列词报成"断链候选"，也会让"只在评审记录里被提过、规格正文里没有生产者"
    # 的真断链被抬到 hits≥2 而漏报。闭包问的是"规格里谁生产/谁消费"，不是"谁写过这个词"。
    corpus = [os.path.join(specdir, f) for f in sorted(os.listdir(specdir))
              if re.match(r'^\d{2}-.*\.md$', f) and '评审' not in f] if os.path.isdir(specdir) else []
    print('== 改动集（增量复核轮的复核面，doc/项目开发流程.md §9.4）：基线 = %s ==' % rev)
    print('改动文件：')
    for f, v in sorted(files.items()):
        prose = (bool(re.match(r'^doc/spec/\d{2}-', f)) and '评审' not in os.path.basename(f)
                 and '评审探针' not in f)
        tag = '' if prose else '（不参与标识符闭包：记录/台账/探针/脚本只列不计）'
        print('  %-46s +%d/-%d，%d 处 hunk%s' % (f, v['add'], v['del'], len(v['hunks']), tag))
        idx = _heading_index(os.path.join(ROOT, f.replace('/', os.sep)))
        for sec in sorted({_section_at(idx, ln) for ln in v['hunks']}):
            print('      节：%s' % sec)
    if untracked:
        print('  未入版本控制的新增文件 %d 个（diff 看不到其内容，须并入复核面）：' % len(untracked))
        for f in untracked[:12]:
            print('      %s' % f)
        if len(untracked) > 12:
            print('      …其余 %d 个' % (len(untracked) - 12))

    def label(f):
        # 只用数字前缀会让 `01-流水线…` 与 `01-评审记录` 撞成同一个 "01"，闭包命中数无法归位——
        # 这里取"编号 + 标题前两字"，保证同篇号的不同文件可区分。
        b = os.path.basename(f)
        return b.split('.')[0][:len(b.split('-')[0]) + 3]
    rows = []
    for s in sorted(syms):
        hits, where = 0, []
        for f in corpus:
            c = read(f).count(s)
            if c:
                hits += c
                where.append('%s×%d' % (label(f), c))
        rows.append((s, hits, ' '.join(where)))
    keep = [(s, h, w) for s, h, w in rows if h >= 1]
    off = len(rows) - len(keep)
    # 输出瘦身（2026-09-23）：真信号只有两类——"未展开"（hits≤1，可能断链）与枢纽项（多处引用）；
    # 中间档多为同篇复用词。实测全表 149 行 token 里真信号仅 14 行，全列会把真信号淹掉（ISS-026 同型教训）。
    HUB = 10
    shown = sorted([r for r in keep if show_all or r[1] <= 1 or r[1] >= HUB],
                   key=lambda r: (r[1] > 1, -r[1]))
    mid = len(keep) - len(shown)
    print('被改标识符 → 引用闭包（命中处数；**＝1 即"只在被改处出现、别处不引用"**，逐条问生产者/消费者是否断链；'
          '%s）：' % ('全表' if show_all else '默认只列"未展开"与 ≥%d 的枢纽项' % HUB))
    for s, hits, where in shown:
        print('  %-26s %3d  %-28s%s' % (s, hits, where, '  ← 闭包未展开' if hits <= 1 else ''))
    if mid:
        print('  （中间档 %d 个 token 命中 2~%d 次未列出：多为同篇复用词，但**"未列出"≠"已判无问题"**，'
              '取全表加 `--all`）' % (mid, HUB - 1))
    if off:
        print('  （另 %d 个 token 在各规格篇正文中 0 命中——多为队列字段/工具子命令/只出现在评审记录里的词，'
              '不参与闭包判定；列出来只会淹掉真信号）' % off)
    print('提示：本清单只界定**复核面下界**（§9.4 来源①），不替代语义推演。'
          '①"未展开"项必须逐条分流再定级——可能是真断链（改了 A 而别处不引用），'
          '也可能是模块名/未写篇目持有的端口（属 §9.4 来源③ 的复述），还可能是改名留痕；'
          '②缺失型缺陷（"该写的动作没写"，如 N1）不在本集内，须由终局全量轮覆盖（上限 %d 次）。' % FULL_ROUND_CAP)
    return 0


# ---------------------------------------------------------------- 完整性长基线 / 只读核查（ADR-4，ISS-024）
# 为什么：ISS-022 实测"只读"子代理在忽略区留下 34 个新建文件，而当时的核查手段是人工
# "仓库清单比对 + mtime 窗口"——mtime 一碰就变、清单不认内容，两头都能骗过。本段把核查
# 落到内容指纹（md5:size）：窗口制扫全仓（含忽略区），长基线制管受控目录集。
GATEDIR = os.path.join(ROOT, 'script', 'gate')
BASE_JSON = os.path.join(GATEDIR, 'integrity_baseline.json')
WINDOW_STATE = os.path.join(GATEDIR, 'window_state.json')
BASE_DIRS = ['rtl', 'sim/covdb', 'iss', 'sw', 'filelist', 'run_cmd', 'tb']
BASE_GLOBS = [os.path.join('doc', 'review', '*-评审探针')]
# 每轮必改件（doc/process/00、doc/verify/04|05、HANDOFF、队列、评审记录）不入长基线——否则每轮必报 MODIFIED，
# 基线的判别力会被日常记录噪音淹没（与 ISS-026"全表列 token 淹掉真信号"同型）。
BASE_EXCLUDE_RE = re.compile(r'(^|/)AutoQueue\.yaml$|(^|/)HANDOFF\.md$'
                             r'|^doc/(?:process/00|verify/0[45])-|(^|/)评审记录\.md$')
# 工具自身状态件不算第三方改动、且每次运行自我改写——两制扫描均排除（否则自我引用假阳）。
TOOL_STATE = ('script/gate/window_state.json', 'script/gate/integrity_baseline.json')
SKIP_DIRS = {'.git', '__pycache__'}
SNAP_RULE = ('长基线刷新硬规则（ADR-4/B5）：仅处置轮开工写产物前每轮 ≤1 次；评审轮与 FAIL 轮后禁刷；'
             '只折"已进复核面"的改动集；执行者＝R8；独立提交＋doc/verify/05 留痕（旧→新指纹、折入集出处）；'
             '作不出折入集出处即作废回滚。')


def _now_iso():
    return datetime.datetime.now().isoformat(timespec='seconds')


def _fingerprint(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    st = os.stat(path)
    return {'md5': h.hexdigest(), 'size': st.st_size,
            'mtime': datetime.datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')}


def _scan(roots, exclude_re=None, extra_exclude=()):
    """roots＝文件/目录绝对路径表 → {仓相对路径（/ 分隔）: md5:size:mtime 三元组}。"""
    out = {}
    for r in roots:
        if os.path.isfile(r):
            cand = [r]
        elif os.path.isdir(r):
            cand = []
            for dp, dns, fns in os.walk(r):
                dns[:] = [d for d in dns if d not in SKIP_DIRS]
                cand.extend(os.path.join(dp, f) for f in fns)
        else:
            continue
        for p in cand:
            rel = os.path.relpath(p, ROOT).replace(os.sep, '/')
            if rel in extra_exclude or (exclude_re and exclude_re.search(rel)):
                continue
            try:
                out[rel] = _fingerprint(p)
            except OSError:
                continue                      # 扫描瞬间被删的文件按跳过处理，不判 DELETED
    return out


def _base_roots():
    roots = [os.path.join(ROOT, d.replace('/', os.sep)) for d in BASE_DIRS]
    for g in BASE_GLOBS:
        roots.extend(glob.glob(os.path.join(ROOT, g)))
    return roots


def _files_fingerprint(files):
    h = hashlib.sha256()
    for rel in sorted(files):
        h.update(('%s|%s|%d\n' % (rel, files[rel]['md5'], files[rel]['size'])).encode('utf-8'))
    return 'sha256:' + h.hexdigest()


def _classify(old, new):
    """四分类。**判定只看内容侧（md5/size）**；纯 mtime 差归 MTIME-ONLY(INFO)。"""
    mod = [r for r in sorted(new) if r in old
           and (new[r]['md5'] != old[r]['md5'] or new[r]['size'] != old[r]['size'])]
    add = [r for r in sorted(new) if r not in old]
    dele = sorted(set(old) - set(new))
    mt = [r for r in sorted(new) if r in old and r not in mod
          and new[r].get('mtime') != old[r].get('mtime')]
    return mod, add, dele, mt


def _print_classes(mod, add, dele, mt):
    for tag, lst in (('MODIFIED', mod), ('ADDED', add), ('DELETED', dele),
                     ('MTIME-ONLY(INFO)', mt)):
        head = ' '.join(lst[:8]) + (' …' if len(lst) > 8 else '')
        print('  %-16s %3d  %s' % (tag, len(lst), head))


def cmd_snapshot(argv):
    """完整性长基线：受控目录集逐文件 md5:size:mtime → script/gate/integrity_baseline.json。
    刷新（--refresh）与**首次建立**都必须随 --reason <折入集出处>，否则拒绝执行（A-4）。"""
    exists = os.path.exists(BASE_JSON)
    refresh = '--refresh' in argv
    reason = argv[argv.index('--reason') + 1] if ('--reason' in argv and
                                                  argv.index('--reason') + 1 < len(argv)) else ''
    if (refresh or not exists) and not reason.strip():
        # A-4（S-13 送审修复，2026-09-24，附 AJ／ISS-090）：原「建立」路径免 --reason ⇒
        # 先删 JSON 再 snapshot 即可绕过折入纪律；现要求建立亦须出处（写入 JSON.reason 字段）。
        print('长基线「建立」与「刷新」均须随 --reason（折入集出处：如 doc/verify/05:R-0xx 行 / 提交号 / 评审结论）；'
              '作不出出处即不得建立或刷新。拒绝执行。')
        print(SNAP_RULE)
        return 2
    if exists and not refresh:
        print('长基线已存在：%s' % os.path.relpath(BASE_JSON, ROOT).replace(os.sep, '/'))
        print('按 ADR-4 硬规则，刷新只能走 `snapshot --refresh --reason <折入集出处>`；'
              '评审轮与 FAIL 轮后禁刷。**拒绝覆盖**。')
        return 2
    files = _scan(_base_roots(), BASE_EXCLUDE_RE)
    prev = None
    if exists:
        try:
            prev = json.loads(read(BASE_JSON))
        except ValueError:
            prev = None
    doc = {'tool': 'script/gate.py snapshot（ADR-4 / ISS-024）',
           'generated_at': _now_iso(), 'reason': reason,
           'scan_dirs': [d + '/' for d in BASE_DIRS] + ['doc/review/*-评审探针/'],
           'exclude': '每轮必改件不入长基线：doc/process/00、doc/verify/04|05、HANDOFF.md、AutoQueue.yaml、*评审记录*.md',
           'file_count': len(files),
           'prev_fingerprint': prev.get('fingerprint') if isinstance(prev, dict) else None,
           'fingerprint': _files_fingerprint(files), 'files': files}
    if not os.path.isdir(GATEDIR):
        os.makedirs(GATEDIR)
    with io.open(BASE_JSON, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(doc, f, ensure_ascii=False, indent=1, sort_keys=True)
        f.write('\n')
    print('== snapshot：%s ==' % ('基线已刷新' if prev is not None else '基线已建立'))
    print('  目录集：%s' % '、'.join(doc['scan_dirs']))
    print('  文件数 %d ；指纹 %s' % (len(files), doc['fingerprint']))
    if prev is not None:
        print('  旧→新指纹：%s → %s（须独立提交并把本行贴进 doc/verify/05）'
              % (prev.get('fingerprint'), doc['fingerprint']))
    print('  写盘：%s' % os.path.relpath(BASE_JSON, ROOT).replace(os.sep, '/'))
    return 0


def cmd_rocheck(argv):
    """只读核查（规则 22 机械化）。
    --baseline    对长基线比对受控目录集：MODIFIED/ADDED/DELETED 任一非空 → 退出码 1；
                  MTIME-ONLY 恒不改变退出码（仅打印）。
    --window <ISO> 扫全仓（含 script/tmp/ 等忽略区；仅排除 .git/、__pycache__/ 与工具状态件）；
                  首次调用建立窗口快照（INIT 只记录起点、不判定），同 ISO 再调即出四分类；
                  **已有旧窗口且 ISO 不等 ⇒ 默认拒跑（rc=2）**，确需重建须显式 `--reset`（A-2）。"""
    if '--baseline' in argv:
        if not os.path.exists(BASE_JSON):
            print('长基线不存在：先 `python script/gate.py snapshot`。不比对即不得宣布"无改动"。')
            return 2
        try:
            doc = json.loads(read(BASE_JSON))
        except ValueError as e:
            print('长基线 JSON 损坏（%s）：不得据此判"无改动"。' % e)
            return 2
        old = doc.get('files', {})
        new = _scan(_base_roots(), BASE_EXCLUDE_RE)
        mod, add, dele, mt = _classify(old, new)
        print('== rocheck --baseline（基线 %s，生成于 %s）=='
              % (doc.get('fingerprint', '?'), doc.get('generated_at', '?')))
        print('  基线文件 %d / 现态文件 %d' % (len(old), len(new)))
        _print_classes(mod, add, dele, mt)
        if mod or add or dele:
            print('  判定：内容侧差异非空 → 退出码 1。差异只能走 snapshot --refresh --reason（ADR-4/B5）'
                  '重折，不得顺手重刷基线把差异抹掉。')
            return 1
        print('  判定：内容侧 0 差异（MTIME-ONLY 恒不改变退出码）。')
        return 0
    if '--window' in argv:
        i = argv.index('--window')
        iso = argv[i + 1].strip() if i + 1 < len(argv) else ''
        if not iso:
            print('用法：gate.py rocheck --window <窗口起点 ISO 时间>')
            return 2
        new = _scan([ROOT], None, extra_exclude=set(TOOL_STATE))
        st = None
        if os.path.exists(WINDOW_STATE):
            try:
                st = json.loads(read(WINDOW_STATE))
            except ValueError:
                st = None
        if st is not None and st.get('window_start') != iso and '--reset' not in argv:
            # A-2（S-13 送审修复，2026-09-24，见 doc/review/01-评审记录.md 附 AJ／ISS-090）：
            # 原行为＝静默重建窗口并 rc=0 ⇒ 可造「改后换新 ISO 重建」假绿。改为默认拒跑。
            print('== rocheck --window %s：已有窗口 %s（建于 %s）——ISO 不等，默认拒跑（rc=2）=='
                  % (iso, st.get('window_start'), st.get('created_at', '?')))
            print('  规则：同 ISO 复跑＝判定；换 ISO 重建＝须显式 --reset（重建丢弃旧快照，差异此后不可再判）。')
            print('        若本意是判定，请用原 ISO：rocheck --window %s' % st.get('window_start'))
            return 2
        if st is None or st.get('window_start') != iso:
            if not os.path.isdir(GATEDIR):
                os.makedirs(GATEDIR)
            with io.open(WINDOW_STATE, 'w', encoding='utf-8', newline='\n') as f:
                json.dump({'window_start': iso, 'created_at': _now_iso(),
                           'file_count': len(new), 'files': new}, f,
                          ensure_ascii=False, sort_keys=True)
            print('== rocheck --window %s：窗口已建立（INIT%s，本次只记录起点、不判定）=='
                  % (iso, '（--reset 重建）' if st is not None else ''))
            print('  全仓文件 %d（含 script/tmp/ 等忽略区；仅排除 .git/、__pycache__/ 与工具状态件）'
                  % len(new))
            print('  子代理动完手后重跑同一命令 → 四分类（判定只看内容侧 md5/size）。')
            return 0
        old = st.get('files', {})
        mod, add, dele, mt = _classify(old, new)
        print('== rocheck --window %s（窗口快照建于 %s）==' % (iso, st.get('created_at', '?')))
        print('  窗口起点文件 %d / 现态文件 %d' % (len(old), len(new)))
        _print_classes(mod, add, dele, mt)
        if mod or add or dele:
            print('  判定：内容侧有变更/新增/删除（**新增/删除恒计入**）→ 退出码 1；'
                  '须逐条归因；纯 mtime 差不作判据。')
            return 1
        print('  判定：内容侧 0 变更（纯 mtime 差仅列 INFO，不改判）。')
        return 0
    print('用法：gate.py rocheck --baseline | --window <ISO>')
    return 2


def check_capability_landed(rep):
    """规则承载件声明了 rocheck / integrity_baseline 而实件不存在 ⇒ FAIL。
    模式同 ra-token-defined：本项目的失效多是"声明已改、实件未落"（ISS-021/022），
    所以声明的另一半必须是存在性检查，不是口头承诺。"""
    files = ['AGENTS.md', os.path.join('doc', '项目开发流程.md')]
    files += [os.path.relpath(p, ROOT) for p in role_agent_files()]
    hits = []
    for rel in files:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        s = read(p)
        for tok in ('rocheck', 'integrity_baseline'):
            if tok in s:
                hits.append('%s:%s' % (rel.replace(os.sep, '/'), tok))
    if not hits:
        rep.ok('capability-landed', '规则承载件未出现 rocheck/integrity_baseline（无声明即无核销对象）')
        return
    miss = []
    if 'rocheck' not in CMDS:
        miss.append('gate.py 无 rocheck 子命令')
    # A-5（S-13 送审修复，2026-09-24，附 AJ）：行为面探针——声明的是「子命令名」，
    # 但规则 22 用的是「窗口模式」。子命令名在而 `--window` 分支被删时，原判据仍 PASS。
    src = read(os.path.join(ROOT, 'script', 'gate.py'))
    if '--window' not in src:
        miss.append('gate.py 无 --window 分支（规则 22 窗口模式缺失）')
    if not os.path.exists(BASE_JSON):
        miss.append('script/gate/integrity_baseline.json 不存在')
    else:
        # A-3（部分）：快照字段与 reason 可回查——ADR-4 硬规则⑤「独立提交＋留痕（旧→新指纹、折入集出处）」的机判半。
        try:
            doc = json.loads(read(BASE_JSON))
            for k in ("fingerprint", "files", "reason"):
                if not str(doc.get(k, "")).strip():
                    miss.append('基线字段缺失/为空：%s' % k)
            rsn = str(doc.get("reason", ""))
            if rsn and not (re.search(r"R-\d{3}", rsn) or re.search(r"\b[0-9a-f]{7,}\b", rsn)):
                miss.append('基线 reason 不可回查（须含 R-nnn 或提交号）：%s' % rsn[:40])
        except ValueError as e:
            miss.append('基线 JSON 损坏：%s' % e)
    if miss:
        rep.fail('capability-landed', '规则承载件已声明（%s）但实件缺失：%s'
                 % ('；'.join(hits[:6]), '；'.join(miss)))
    else:
        rep.ok('capability-landed', '声明 %d 处，实件齐（rocheck 子命令 + --window 分支 + 基线字段/reason 可回查）'
               % len(hits))


ROLE2AGENT = {'R1': 'vr1-designer / vr1-planner', 'R2': 'vr1-verifier', 'R3': 'vr1-designer',
              'R4': 'vr1-verifier', 'R5': 'vr1-verifier（取证已并入验证）',
              'R6': 'vr1-auditor（模式 P）', 'R7': 'vr1-auditor（模式 T）', 'R8': '主会话（领队）'}
PLAN_WORDS = ('验证点', '清单', '计划', '看板', '队列', '理解', '排期')
DECIDE_CAP = 3


def cmd_loop(_):
    """给出本轮唯一动作。退出码：0=有可执行动作，3=必须停下等人，4=全部完成待 R0 出口判定。"""
    items = parse_queue()
    if not items:
        print('队列为空：领队先按 doc/项目开发流程.md §10 与 doc/verify/04 播种。')
        return 3
    done = {str(i['id']) for i in items if i.get('state') == 'done'}

    live = [i for i in items if i.get('state') == 'in_progress']
    if live:
        i = live[0]
        print('继续未完成的 %s（%s）：%s' % (i['id'], i.get('role'), i.get('task')))
        if i.get('review_rounds'):
            # §9.4：处置轮的 diff 基线须在开工前提交，否则下一轮增量复核无基线可用
            print('  §9.4 提醒：本轮若为处置轮，开工前先提交 git 基线（提交信息标「%s r<n> 基线」），'
                  '再动正文；基线之后的两点差异即下一轮增量复核的复核面。' % i['id'])
        print('完成后回填 state 与 landable，再跑 check。不得中途改派他项。')
        return 0

    rev = [i for i in items if i.get('state') == 'in_review'
           and (int(i.get('review_rounds', 0) or 0) < REVIEW_CAP
                or str(i.get('cap_waiver', '')).strip())]      # 人批准的越权，允许继续
    if rev:
        i = rev[0]
        fr = _qint(i.get('full_rounds')) or 0
        print('评审未收敛。按 doc/项目开发流程.md §9.4 两档制，本轮唯一动作（档位由上一轮状态决定，勿自行选档）：')
        print('  ① **增量复核轮**（默认）：派 vr1-auditor（模式 T）只查「%s」——'
              '上轮旧问题是否真改 + 改动集及其引用闭包内有无新增；不得改产物。' % i['id'])
        print('     复核面由 `python script/gate.py changed` 生成，须连同 '
              '`gate.py check`、`width_check.py` 输出一并写进派发词（评审者无执行工具，不给它跑脚本的权限）。')
        print('  ② 增量轮已"新增 0" → 本轮改派**终局全量复核轮**（读整篇，判 §6.1 C2 对全篇成立），'
              '并把该项 full_rounds 加 1。')
        print('  ③ 全量轮已用 %d/%d：到限仍不收敛即置 fused 并 `gate.py escalate` 转 R0，不得默认通过（红线 RA1/RA3）。'
              % (fr, FULL_ROUND_CAP))
        if str(i.get('cap_waiver', '')).strip():
            print('     **本项已持越权批文**（%s）——上限不挡继续；但批文不是免检：'
                  '每轮仍须留痕，且"新增 0"未达成前不得宣布收敛、不得申请关闭。'
                  % str(i['cap_waiver']).strip())
        print('  （另：作者侧 review_rounds=%s，R7 轮次上限 %d，越权须带 cap_waiver）' %
              (i.get('review_rounds'), REVIEW_CAP))
        return 0

    ready = [i for i in items if i.get('state') == 'ready' and not (i.get('blocked_by') or [])
             and all(d in done for d in (i.get('depends_on') or []))]
    if ready:
        ready.sort(key=lambda i: (str(i.get('priority', 'P9')), str(i.get('id'))))
        i = ready[0]
        ag = ROLE2AGENT.get(str(i.get('role')), str(i.get('role')))
        if '/' in ag:
            ag = 'vr1-planner' if any(w in str(i.get('task')) for w in PLAN_WORDS) else 'vr1-designer'
        print('本轮派发给子代理：%s（队列归属 %s）' % (ag, i.get('role')))
        print('任务 %s：%s' % (i['id'], i.get('task')))
        print('完成判据：%s' % i.get('done_when'))
        rest = [str(x['id']) for x in ready[1:]]
        if rest:
            print('后续可自决项：%s（一次只做一项，保持 in_progress 不并发改产物）' % ', '.join(rest))
        return 0

    pend = [i for i in items if i.get('state') != 'done']
    if not pend:
        print('队列已清空。下一步不是"项目完成"：请领队汇总 doc/verify/07/08/09 与台账闭环情呈 R0 做阶段出口判定。')
        return 4

    blockers = sorted({b for i in pend for b in (i.get('blocked_by') or [])})
    need = [i for i in pend if int(i.get('decision_rounds', 0) or 0) < DECIDE_CAP]
    if need and blockers:
        i = need[0]
        print('无可执行项，卡在：%s' % ', '.join(blockers))
        print('本轮派 vr1-decider 处理 %s（已决 %s 次，上限 %d）；' %
              (i['id'], i.get('decision_rounds', 0), DECIDE_CAP))
        print('  它先查知识库/网络给建议；属 §12.3 三类必报项则第 0 次即转人。')
        print('  无论结论如何，须把该项 decision_rounds 加 1 并回写台账（计数不涨即视为空转）。')
        return 0
    print('**停下等人**：以下项被不可自决的问题阻塞，且决策轮次已用尽（上限 %d）：' % DECIDE_CAP)
    for i in pend:
        print('  %s  卡在 %s' % (i['id'], ', '.join(i.get('blocked_by') or []) or '-'))
    print('请逐项跑：python script/gate.py escalate ISS-0xx  生成决策包。领队不得默认通过（红线 RA1/RA3）。')
    return 3


# ---------------------------------------------------------------- 派发失败计数（ISS-053 实装）
def _queue_block(lines, qid):
    """qid 所在项的行区间 [start, end)：`- id:` 行 → 下一 `- id:` 行；找不到返回 (None, None)。"""
    marks = []
    for j, l in enumerate(lines):
        m = re.match(r'^\s*-\s*id\s*:\s*(\S+)\s*$', l.rstrip('\r\n'))
        if m:
            marks.append((j, m.group(1)))
    for k, (j, v) in enumerate(marks):
        if v == qid:
            return j, (marks[k + 1][0] if k + 1 < len(marks) else len(lines))
    return None, None


def _line_ending(s):
    return s[len(s.rstrip('\r\n')):]


def cmd_attempts(argv):
    """派发失败计数写入口（ISS-053）：此前全表 0 处 attempts、queue-attempts-cap 永不触发。
    每失败一次 +1（--reset 置 0）；达 3 自动 state: blocked ＋ block_reason 转人。
    写回＝逐行插入/替换，不重排、不改动其它行（保持 YAML 其余内容逐字节不变）。"""
    args = [a for a in argv if not a.startswith('-')]
    reset = '--reset' in argv
    if len(args) != 1:
        print('用法：gate.py attempts <Q-id> [--reset]（递增；达 3 自动置 blocked 转人；--reset 置 0）')
        return 2
    qid = args[0]
    raw = io.open(QUEUE, encoding='utf-8', errors='replace', newline='').read()
    nl = '\r\n' if '\r\n' in raw else '\n'
    lines = raw.splitlines(True)
    start, end = _queue_block(lines, qid)
    if start is None:
        print('队列无此项：%s（先核对 id，不得凭印象计数；未写盘）' % qid)
        return 2

    def find(pat):
        for j in range(start + 1, end):
            if re.match(pat, lines[j].rstrip('\r\n')):
                return j
        return None

    def set_scalar(j, valstr):
        m = re.match(r'^(\s*[A-Za-z_]+\s*:\s*)\S+([^\r\n]*)(\r?\n?)$', lines[j])
        if not m:
            return False
        lines[j] = m.group(1) + valstr + m.group(2) + m.group(3)
        return True

    at_i = find(r'^\s*attempts\s*:')
    cur = _qint(lines[at_i].split(':', 1)[1]) if at_i is not None else None
    val = 0 if reset else (cur or 0) + 1
    if at_i is not None:
        if not set_scalar(at_i, str(val)):
            print('attempts 行格式异常，未写盘：%r' % lines[at_i])
            return 2
    else:
        a_i = find(r'^\s*review_rounds\s*:')
        anchor = a_i if a_i is not None else start
        lead = re.match(r'^\s*', lines[anchor]).group(0)
        lines.insert(anchor + 1,
                     lead + 'attempts: %d' % val + (_line_ending(lines[anchor]) or nl))
        end += 1
    note = ''
    if val >= 3:
        s_i = find(r'^\s*state\s*:')
        s_cur = lines[s_i].split(':', 1)[1].strip() if s_i is not None else ''
        if s_cur in ('blocked', 'fused'):
            note = 'state 已是 %s（保持不动）' % s_cur
        elif s_i is not None and set_scalar(s_i, 'blocked'):
            note = 'state: %s → blocked' % s_cur
        else:
            note = 'state 行未找到：须人工置 blocked！'
        reason = '"派发失败 3 次，转人"'
        b_i = find(r'^\s*block_reason\s*:')
        if b_i is not None:
            set_scalar(b_i, reason)
        else:
            anchor = s_i if s_i is not None else start
            lead = re.match(r'^\s*', lines[anchor]).group(0)
            lines.insert(anchor + 1,
                         lead + 'block_reason: %s' % reason + (_line_ending(lines[anchor]) or nl))
        note += '；block_reason 已写（达上限须 escalate 转人，不得口头重派了事）'
    with io.open(QUEUE, 'w', encoding='utf-8', newline='') as f:
        f.write(''.join(lines))
    print('== attempts：%s %s ⇒ %d ==' % (qid, 'reset' if reset else '+1', val))
    if note:
        print('  %s' % note)
    print('  落盘：%s（逐行插入/替换，其余内容未动）；复验：python script/gate.py check' % QUEUE)
    return 0



CMDS = {'check': cmd_check, 'dispatch': cmd_dispatch, 'changed': cmd_changed, 'report': cmd_report,
        'loop': cmd_loop, 'escalate': cmd_escalate, 'attempts': cmd_attempts,
        'snapshot': cmd_snapshot, 'rocheck': cmd_rocheck}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        print('可用子命令：%s' % ', '.join(CMDS))
        return 2
    return CMDS[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
