#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate.py — VR1 机械核销与派发器（R8 编排 AI 的执行工具）

为什么要有它：本仓库已发生 4 类"声明与实态脱钩"失效，且全部是人眼与 diff 拦不住的——
  ISS-021 处置列写了没落实 / ISS-022 只读约束被违反 34 个文件 / ISS-031 看板计数落后 10 条 /
  ISS-026 中文静默错字 7 处（扫 描→扇、锚→锈、经 验→骍、脱→脉…）。
所以核销只能是机器判据，不能靠自觉。

子命令：
  check      跑全部不变式，任一 FAIL 退出码 1（R8 每轮开工第一件事）
  dispatch   取队首可执行项，打印归属角色 + 完成判据
  report     队列与门禁看板摘要
  escalate   把某条台账项打成"≤5 选项决策包"呈 R0（《AI进行IC开发验证工作流程》§5 格式）

依据：doc/项目开发流程.md §12.1~12.4；《AI进行IC开发验证工作流程》v2.1 §6.1（评审收敛）；
      doc/AI角色与职责.md §2（角色与写边界）、§6.1（角色数封顶）。
"""
import io
import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LEDGER = os.path.join(ROOT, 'doc', '00-问题记录.md')
BOARD = os.path.join(ROOT, 'doc', '04-验证进度.md')
QUEUE = os.path.join(ROOT, 'run_cmd', 'AutoQueue.yaml')
HANDOFF = os.path.join(ROOT, '.qoder', 'handoff', 'HANDOFF.md')

# 坏词表：每条必须能指到一次真实事故（doc/00 ISS-026 / ISS-033），无出处者不得入表——
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
        rr = i.get('review_rounds', 0)
        if isinstance(rr, int) and rr > REVIEW_CAP:
            # 轮次上限是红线，但**可以由人越权**：须带 cap_waiver（写明谁在何时批准）；
            # 无人批准就不得越过——“继续直到收敛”这类指令必须留痕，不能靠口头。
            if str(i.get('cap_waiver', '')).strip():
                rep.ok('queue-review-cap-waiver', '%s 已越权继续（%s）' % (qid, str(i['cap_waiver'])[:60]))
            else:
                rep.fail('queue-review-cap', '%s 评审 %d 轮 > 上限 %d（§6.1 应已 fused 并升级）'
                         % (qid, rr, REVIEW_CAP))
        # 派发失败（空返回/取消/超时）可自动重派，但不得超过 2 次；第 3 次必须转人
        at = i.get('attempts')
        if isinstance(at, int) and at >= 3 and i.get('state') not in ('blocked', 'fused'):
            rep.fail('queue-attempts-cap',
                     '%s attempts=%d ≥3 但仍为 %s（失败重派上限 2 次，到限须置 blocked/fused 转人）'
                     % (qid, at, i.get('state')))
        for d in i.get('depends_on', []) or []:
            if d not in ids:
                rep.fail('queue-deps', '%s 依赖不存在的 %s' % (qid, d))
        for b in i.get('blocked_by', []) or []:
            if b.startswith('ISS-') and b[4:].lstrip('0') not in {k.lstrip('0') for k in rows}:
                rep.fail('queue-block', '%s 的 blocked_by 指向不存在台账项 %s' % (qid, b))
        if i.get('state') == 'done' and not str(i.get('landable', '')).strip():
            rep.fail('queue-landing', '%s 标 done 但 landable 为空（C1：无落点不算闭环）' % qid)
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
    if os.path.isdir(os.path.dirname(LEDGER)):
        roots.append(os.path.dirname(LEDGER))
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
    files = [os.path.join(ROOT, 'doc', f) for f in sorted(os.listdir(os.path.join(ROOT, 'doc')))
             if f.endswith('.md')]
    files += [os.path.join(ROOT, f) for f in ('AGENTS.md', 'README.md')]
    files += role_agent_files()
    spec = os.path.join(ROOT, 'doc', 'spec')
    if os.path.isdir(spec):
        files += [os.path.join(spec, f) for f in sorted(os.listdir(spec)) if f.endswith('.md')]
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
           for r in rows if r['verdict'] == 'MISMATCH']
    unver = [r['struct'] for r in rows if r['verdict'] in ('UNVERIFIED', 'NO-TABLE')]
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
    check_md(rep)
    check_handoff(rep)
    check_width(rep)
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


ROLE2AGENT = {'R1': 'vr1-designer / vr1-planner', 'R2': 'vr1-verifier', 'R3': 'vr1-designer',
              'R4': 'vr1-verifier', 'R5': 'vr1-verifier（取证已并入验证）',
              'R6': 'vr1-auditor（模式 P）', 'R7': 'vr1-auditor（模式 T）', 'R8': '主会话（领队）'}
PLAN_WORDS = ('验证点', '清单', '计划', '看板', '队列', '理解', '排期')
DECIDE_CAP = 3


def cmd_loop(_):
    """给出本轮唯一动作。退出码：0=有可执行动作，3=必须停下等人，4=全部完成待 R0 出口判定。"""
    items = parse_queue()
    if not items:
        print('队列为空：领队先按 doc/项目开发流程.md §10 与 doc/04 播种。')
        return 3
    done = {str(i['id']) for i in items if i.get('state') == 'done'}

    live = [i for i in items if i.get('state') == 'in_progress']
    if live:
        i = live[0]
        print('继续未完成的 %s（%s）：%s' % (i['id'], i.get('role'), i.get('task')))
        print('完成后回填 state 与 landable，再跑 check。不得中途改派他项。')
        return 0

    rev = [i for i in items if i.get('state') == 'in_review'
           and (int(i.get('review_rounds', 0) or 0) < REVIEW_CAP
                or str(i.get('cap_waiver', '')).strip())]      # 人批准的越权，允许继续
    if rev:
        i = rev[0]
        print('评审未收敛，本轮唯一动作：派 vr1-auditor（模式 T）对 %s 跑%s' %
              (i['id'], '纯复核轮（§6.1 C2：只查旧问题是否真改 + 有无新增，本轮不得改产物）'
               if int(i.get('review_rounds', 0) or 0) >= 1 else '评审轮'))
        print('已跑 %s 轮，上限 %d；到限即置 fused 并 escalate，不得默认通过（RA5）。' %
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
        print('队列已清空。下一步不是"项目完成"：请领队汇总 doc/07/08/09 与台账闭环情呈 R0 做阶段出口判定。')
        return 4

    blockers = sorted({b for i in pend for b in (i.get('blocked_by') or [])})
    need = [i for i in pend if int(i.get('decision_rounds', 0) or 0) < DECIDE_CAP]
    if need and blockers:
        i = need[0]
        print('无可执行项，卡在：%s' % ', '.join(blockers))
        print('本轮派 vr1-decider 处理 %s（已决 %s 次，上限 %d）；' %
              (i['id'], i.get('decision_rounds', 0), DECIDE_CAP))
        print('  它先查知识库/网络给建议；属 §12.3 四类必报项则第 0 次即转人。')
        print('  无论结论如何，须把该项 decision_rounds 加 1 并回写台账（计数不涨即视为空转）。')
        return 0
    print('**停下等人**：以下项被不可自决的问题阻塞，且决策轮次已用尽（上限 %d）：' % DECIDE_CAP)
    for i in pend:
        print('  %s  卡在 %s' % (i['id'], ', '.join(i.get('blocked_by') or []) or '-'))
    print('请逐项跑：python script/gate.py escalate ISS-0xx  生成决策包。领队不得默认通过（RA1/RA5）。')
    return 3


CMDS = {'check': cmd_check, 'dispatch': cmd_dispatch, 'report': cmd_report,
        'loop': cmd_loop, 'escalate': cmd_escalate}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in CMDS:
        print(__doc__)
        print('可用子命令：%s' % ', '.join(CMDS))
        return 2
    return CMDS[sys.argv[1]](sys.argv[2:])


if __name__ == '__main__':
    sys.exit(main())
