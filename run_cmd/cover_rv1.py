#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_cmd/cover_rv1.py — VR1 覆盖率批（**M2 exit (c) 的机制件**，非判据本体）

定位（务必读；判据本体在 `script/flow.py` 的 `m2-cov`，本文件**不改**它）
  M2 exit (c) 的口径（`state/flow.json` 的 `m2-cov` 行）＝「覆盖率机制**在环**：出一份报告落
  `doc/verify/` ＋ 编译指纹（RTL 版本 ＋ filelist hash）；**不要求达阈值**（阈值属 M3）」。
  本文件把"机制在环"落成一条真跑链（每一环都有产物、有证据行，红线 R8）：

    vlog -cover bcesf（编译期插桩，AGENTS.md §3.1 口径）
      → vopt -cover=bcesf
      → 逐用例 vsim -coverage ＋ `coverage save -onexit <case>.ucdb`
      → `vcover merge -out sim/covdb/<batch>.ucdb <逐例 ucdb…>`（**合并集限同一编译版本**，
        AGENTS.md §3.4 坑 3 —— 本批逐例 ucdb 全部来自**同一次** vlog/vopt，故可相加）
      → `vcover report -cvg -detail <merged>` → `doc/verify/07-<batch>.txt`§A（功能覆盖：covergroup）
      → `vcover report -assert <merged>` → 同报告 §D（断言覆盖：**证"断言真的在跑"**，红线 R8）
      → `sim/covdb/FINGERPRINT.json`（RTL filelist hash ＋ 生成件 md5 ＋ 编译/仿真/合并命令 ＋
        工具版本 ＋ 逐例 ucdb 清单；`sim/covdb/README.md` 要求的"必须可追溯到源"）

口径声明（写进报告头，**不美化**）
  · 本阶段只要求**机制在环**，覆盖率高/低都**不作 PASS/FAIL 判据**；阈值判定归 M3/签核
    （AGENTS.md §4 的功能覆盖率 100%／代码覆盖率 ≥90% 是**签核阈值**，不是本批口径）。
  · 报告**原样**收录 `vcover` 的输出（不挑数字、不美化、不做任何 exclude/waiver——红线 R7：
    任何 waiver 都要逐条附理由并经人批；本批**一条都没有**）。
  · 编译集含 TB 侧两件（`tb/unit/rt_t_trace_writer.sv`／`tb/unit/m1_e2e_tb.sv`）：它们与 DUT 同批
    编译（`filelist/tb_m1_e2e.f` 的口径），报告里**不区分**，需按 DUT 面判定时按文件名过滤
    `rtl/vr1/**`（本脚本在报告尾附"DUT 面代码覆盖率"一节做这一过滤，口径写在那一节里）。

写边界：`sim/run_cover_<batch>/**`（沙箱）、`sim/covdb/<batch>.ucdb` ＋ `sim/covdb/FINGERPRINT.json`
（签核证据区，按 `sim/covdb/README.md` 的规则**必须**与 ucdb 同时产生）、`doc/verify/07-<batch>.txt`。
**不写** `rtl/**`、`doc/spec/**`、`rtl/vr1/include/*.svh`、`script/flow.py`。

退出码：0 = 报告＋指纹均落盘；1 = 跑完但报告/指纹不全；3 = 环境/配置错误（fail-closed）。

TODO（如实登记）
  · TODO(M2-c-1)：`sim/covdb/README.md` 的"当前状态：**本目录目前为空**"段落**已过期**（本批产生
    第一条真实数据）——该文件在 `sim/covdb/**` 受 `guard-write` 保护，本轮**未改**，待人工登记。
  · TODO(M2-c-2)：**部分闭合（2026-09-26 心跳第 8 轮）**——首批功能覆盖模型（3 个 covergroup、
    14 个 coverpoint）与 SVA 断言（6 条）已落在 **TB 侧** `tb/unit/m1_e2e_cov.sv`（VP 号／`spec/11`
    规则号逐条写在件头），§A 的 `-cvg` 面自此**有数据**、§D 的断言覆盖可证"断言在跑"。
    **剩余未落**：`spec/11` §1 的 A1~A19（free-list/RAT/PRF/`csrq`/checkpoint 等机制尚未实现
    ⇒ 该篇篇首②"不新造语义"下一条都落不了）；`doc/verify/02` VP 清单→covergroup 的全量映射
    （含 VP-03/04/11~15/19~21/23/25/26/28~31/33）归 M3 用例批。
  · TODO(M2-c-3)：toggle（`t`/`x`）未开（AGENTS.md §3.1 的 `bcesf` 口径里没有 t/x），
    "逐项 ≥90%" 的 FSMs/Toggle 面要到 M3 再定口径。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import sys
import time
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    import regress_rv1 as R          # 逐例口径**逐字复用**（同一判据面，不复制、不放宽）
except Exception as e:               # noqa: BLE001
    print('[cover] 无法复用 run_cmd/regress_rv1.py：%s' % e)
    raise SystemExit(3)

ROOT = R.ROOT
COVDB = os.path.join(ROOT, 'sim', 'covdb')
VERIFY = os.path.join(ROOT, 'doc', 'verify')
DEFAULT_TESTLIST = R.DEFAULT_TESTLIST
COVER_SPEC = 'bcesf'                 # AGENTS.md §3.1：-cover bcesf（statement/branch/condition/expr/fsm）
VCOVER = os.path.join(R.MTI, 'vcover.exe')          # 覆盖率合并/报告工具（本脚本专用）
EXIT_OK, EXIT_BAD, EXIT_ENV = 0, 1, 3
RE_DUT = re.compile(r'^(rtl/vr1/|.*[\\/]rtl[\\/]vr1[\\/])')

# --------------------------------------------------------------------------- #
# **受控复位注入通道**（2026-09-26 心跳第 13 轮；**R0 2026-09-26 三项裁定①**＝
# `doc/verify/02` §6 NU-2）：testlist 里 `rst_` 前缀的条目从 MANIFEST 的
# `cov_only_tests`（**不是** `tests`）解析，逐例只跑 **RTL 单侧**（＋`+RESET_INJECT=`）。
# 为什么不能 ISS↔RTL 比对：复位注入使 trace 出现"重启后第二段"，与 ISS 单段 golden
# **构造性不可比**（NU-2 行原文）；本通道判定＝RTL 侧 `HALT_PASS` ＋ 无 `HALT_FAIL`/
# `WATCHDOG` ＋ TB 复位注入证据行 `[rst_inj]` ＋ ucdb 在盘（fail-closed）。
# **该通道不污染 M2 的同配置口径**：回归面（`run_cmd/rv64ui_testlist.txt`）不含 `rst_`，
# 条目也不在 `MANIFEST.tests`（构建侧口径见 `sw/tests/build_rv64ui.py` COV_ONLY 段）。
# --------------------------------------------------------------------------- #
RST_PREFIX = 'rst_'
RE_RST_INJ_EVID = re.compile(r'\[rst_inj\] ASSERT rst_n=0 at cyc=\d+')


def run_case_rst(case, workdir, case_timeout, log, tag, opt_name='cov_opt', ucdb=None):
    """受控复位注入通道（R0 2026-09-26 裁定 NU-2）单例执行：**只跑 RTL 侧**。

    与 `regress_rv1.run_case` 的差异（仅此三处，其余逐字同口径）：
      ① 不跑 ISS、不做 trace_compare（构造性不可比，见上方通道注释）；
      ② vsim 命令多 `+RESET_INJECT=<cycle>[,...]`（取自条目 `reset_inject_cycles`）；
      ③ 判定＝HALT_PASS ＋ 无 HALT_FAIL/WATCHDOG ＋ 数据窗预载证据行 ＋ `[rst_inj]` 证据行
         ＋ ucdb 在盘。返回 dict 结构与 run_case 同形（多 `channel` 字段）。
    """
    name = case['name']
    t0 = time.time()
    r = {'name': name, 'status': 'FAIL', 'reason': '', 'rows_iss': None, 'rows_rtl': None,
         'mismatch': None, 'cyc': None, 'elapsed_s': None, 'csv_iss': '',
         'csv_rtl': '', 'channel': 'reset_inject(NU-2)'}
    rtl_csv = os.path.join(workdir, '%s.rtl.csv' % name)
    if os.path.exists(rtl_csv):
        os.remove(rtl_csv)
    inj = ','.join(str(c) for c in (case.get('reset_inject_cycles') or []))
    if not inj:
        raise RuntimeError('受控通道条目 %s 缺 `reset_inject_cycles`（fail-closed）' % name)
    vsim_args = [R.VSIM, '-64', '-c']
    do_cmd = 'run -all; quit -f'
    if ucdb:
        vsim_args += ['-coverage']
        do_cmd = 'coverage save -onexit %s; run -all; quit -f' % R.fwd(ucdb)
    vsim_args += ['-do', do_cmd, opt_name,
                  '+IMAGE=%s' % R.fwd(os.path.join(ROOT, case['tb_hex'])),
                  '+DATA=%s' % R.fwd(os.path.join(ROOT, case['data_hex'])),
                  '+RT_T_CSV=%s' % R.fwd(rtl_csv),
                  '+RESET_INJECT=%s' % inj]
    R._log(log, '[%s] rst 通道 +RESET_INJECT=%s' % (name, inj))
    rc2, o2, timed2 = R.run_capture(vsim_args, workdir, case_timeout, '%s.rtl' % name, log)
    r['csv_rtl'] = R.rel(rtl_csv)
    if ucdb:
        r['ucdb'] = R.rel(ucdb) if os.path.exists(ucdb) else ''
    if timed2:
        r.update(status='TIMEOUT', reason='RTL 侧挂钟超时（>%ds，进程树已杀；R9/AB6）' % case_timeout)
        return r
    bad = [ln.strip() for ln in o2.splitlines() if 'HALT_FAIL' in ln or 'WATCHDOG_TIMEOUT' in ln]
    wd = [x for x in bad if 'WATCHDOG_TIMEOUT' in x]
    if wd:
        r.update(status='TIMEOUT', reason='TB watchdog 超时（R9/AB6）：%s' % wd[0][:100])
        return r
    mf = R.RE_HALT_FAIL.search(o2)
    if mf:
        r.update(status='FAIL', reason='RTL 侧自报 HALT_FAIL（tohost val=%s testnum=%s）'
                 % (mf.group(2), mf.group(3)))
        return r
    if rc2 != 0:
        r.update(status='FATAL', reason='vsim 退出码 %d（加载/仿真器级错误；AB1/AB5 的 fatal 面）'
                 % rc2)
        return r
    mh = R.RE_HALT_PASS.search(o2)
    if not mh:
        r.update(status='FATAL', reason='RTL 侧未见 `HALT_PASS … rows=…`（fail-closed：无停机证据）')
        return r
    r['rows_rtl'] = int(mh.group(3))
    if 'data window preloaded:' not in o2:
        r.update(status='FAIL', reason='RTL 侧未见数据窗预载证据行（`+DATA=` 未生效 ⇒ 等价性无证据）')
        return r
    n_inj = len(RE_RST_INJ_EVID.findall(o2 or ''))
    if n_inj < 1:
        r.update(status='FAIL', reason='RTL 侧未见复位注入证据行 `[rst_inj] ASSERT`（fail-closed：'
                                       '受控通道的激励无证据行即不可信）')
        return r
    if not os.path.exists(rtl_csv):
        r.update(status='FATAL', reason='RTL 侧 CSV 未落盘（fail-closed）')
        return r
    r.update(status='PASS', reason='rst 通道（R0 2026-09-26 NU-2）：RTL 单侧判定，注入 %d 次，'
                                   '不做 ISS 比对（构造性不可比）' % n_inj)
    r['elapsed_s'] = round(time.time() - t0, 2)
    return r


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def vcover(args, cwd, timeout, tagname):
    """跑一条 `vcover` 命令，**无论成败都落证**（返回 (rc, out)）。"""
    argv = [VCOVER] + args
    rc, out, timed = R.run_capture(argv, cwd, timeout, tagname, None)
    if timed:
        rc = 99
    return rc, out


# `vcover report -code` 的**分节**规则：每节以 `=== Instance: <路径>` 起头，紧随
# `=== Design Unit: work.<单元名>`（2020.4 实测格式）。识别不到即整段作一节（不猜不切）。
RE_INSTANCE = re.compile(r'^=+\s*$|^===\s*Instance:\s*(\S+)\s*$')


def _split_instances(text):
    """把 `-code` 文本按实例节切成 [(实例路径, 该节原文), …]；无节头 ⇒ [('', 全文)]。"""
    secs, cur, hdr = [], [], None
    for ln in (text or '').splitlines():
        m = re.match(r'^===\s*Instance:\s*(\S+)\s*$', ln)
        if m:
            if hdr is not None:
                secs.append((hdr, '\n'.join(cur)))
            hdr, cur = m.group(1), []
        else:
            cur.append(ln)
    if hdr is not None:
        secs.append((hdr, '\n'.join(cur)))
    if not secs:
        secs = [('', text or '')]
    return secs


def _dut_unit_stems(units):
    """`filelist/rtl.f` 的编译单元 → 单元名集合（`rtl/vr1/**/vr1_bp.sv` → `vr1_bp`）。

    注意：`_parse_f_list` 返回的是**仓库根相对**路径（`rtl/vr1/...`，无前导 `/`）⇒ 判据前先补
    一个前导 `/` 再找 `/rtl/vr1/`（2026-09-26 首跑踩到：按带前导斜杠的串找 ⇒ 集合恒空 ⇒ §C 空节）。
    """
    stems = set()
    for u in units:
        p = '/' + u.replace('\\', '/').lstrip('/')
        if '/rtl/vr1/' not in p:
            continue
        stems.add(os.path.basename(p).rsplit('.', 1)[0])
    return stems


def _rollup(sections):
    """按 `Enabled Coverage | Bins | Hits | Misses | Coverage` 行自算 Σhits/Σbins（**口径显式标注**）。

    这是**本脚本自算**的汇总（与 AGENTS.md §4 功能覆盖率行「Σhits/Σ目标 bins」同形），
    **不是** vcover 自报数；工具自报的合计行原文另在 §B/§C 里（两者都留，读者自行核对）。
    """
    tot = {}
    for _, body in sections:
        for ln in body.splitlines():
            m = re.match(r'^\s+([A-Za-z][A-Za-z ]+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+[\d.]+%\s*$', ln)
            if not m:
                continue
            k, bins, hits = m.group(1).strip(), int(m.group(2)), int(m.group(3))
            a = tot.setdefault(k, [0, 0])
            a[0] += bins
            a[1] += hits
    return {k: {'bins': v[0], 'hits': v[1],
                'pct': round(100.0 * v[1] / v[0], 2) if v[0] else None}
            for k, v in tot.items()}


def main(argv=None):
    ap = argparse.ArgumentParser(description='VR1 覆盖率批（M2 exit (c) 机制件）')
    ap.add_argument('--batch', default='m2cov_r1', help='批名（ucdb／报告／沙箱都用它命名）')
    ap.add_argument('--testlist', default=DEFAULT_TESTLIST)
    ap.add_argument('--jobs', type=int, default=1, help='并发（默认 1；硬上限 %d，红线 R10）' % R.MAX_JOBS)
    ap.add_argument('--case-timeout', type=int, default=R.DEFAULT_CASE_TIMEOUT)
    ap.add_argument('--limit', type=int, default=0, help='只用前 N 条（**仅机制冒烟**）')
    ap.add_argument('--keep-going', action='store_true',
                    help='逐例失败也继续（覆盖率批的"在环"判据不依赖逐例全过；**默认不中止**）')
    args = ap.parse_args(argv)

    if args.jobs < 1 or args.jobs > R.MAX_JOBS:
        print('[cover] --jobs 必须在 1..%d（红线 R10 硬上限，不静默截断）' % R.MAX_JOBS)
        return EXIT_ENV
    testlist = args.testlist if os.path.isabs(args.testlist) else os.path.join(ROOT, args.testlist)
    sandbox = os.path.join(ROOT, 'sim', 'run_cover_%s' % args.batch)
    lock = R.SandboxLock(sandbox, 'cover_%s' % args.batch)
    try:
        lock.acquire()
    except RuntimeError as e:
        print('[cover] %s' % e)
        return EXIT_ENV
    log = os.path.join(sandbox, 'run.log')
    try:
        man = R.load_manifest()
        names = R.read_testlist(testlist)
        # ---- 受控复位注入通道（R0 2026-09-26 裁定 NU-2）：`rst_` 前缀条目另路解析 ----
        #   从 MANIFEST 的 `cov_only_tests`（非 `tests`）解析；缺字段/缺拍数即 fail-closed。
        rst_names = [n for n in names if n.startswith(RST_PREFIX)]
        norm_names = [n for n in names if not n.startswith(RST_PREFIX)]
        if rst_names:
            cov_only = man.get('cov_only_tests') or []
            if not cov_only:
                raise RuntimeError('testlist 有 %s* 条目而 MANIFEST 缺 `cov_only_tests` 字段'
                                   '（受控通道 fail-closed；重跑 sw/tests/build_rv64ui.py）'
                                   % RST_PREFIX)
            rst_cases = R.resolve_cases(rst_names, {'tests': cov_only}, 0)
            for c in rst_cases:
                if not c.get('reset_inject_cycles'):
                    raise RuntimeError('受控通道条目 %s 缺 `reset_inject_cycles`（fail-closed）'
                                       % c['name'])
        else:
            rst_cases = []
        cases = R.resolve_cases(norm_names, man, 0)
        cases = cases + rst_cases
        if args.limit:
            cases = cases[:args.limit]
        t_start = time.time()
        ucdb_dir = os.path.join(sandbox, 'ucdb')
        os.makedirs(ucdb_dir, exist_ok=True)
        # ---- ① 带覆盖率开关编译（本批**唯一**编译版本；合并集合法性由它保证）----
        comp = R.compile_design(sandbox, log, cover=COVER_SPEC, opt_name='cov_opt')
        fp_units = [{'path': u, 'md5': R.flowmod.md5_of(os.path.join(ROOT, u))}
                    for u in comp['units']]
        gen_files = [{'path': p, 'md5': R.flowmod.md5_of(os.path.join(ROOT, p))}
                     for p in ('rtl/vr1/include/vr1_params.svh', 'rtl/vr1/include/vr1_types.svh')
                     if os.path.exists(os.path.join(ROOT, p))]
        filelist_hash = R.flowmod.md5_of(R.RTL_F)
        tb_filelist_hash = R.flowmod.md5_of(R.TB_F)
        _log = R._log
        _log(log, '\n[cover] batch=%s 编译版本：vlog -cover %s ／ vopt -cover=%s ／ 单元 %d'
                  % (args.batch, COVER_SPEC, COVER_SPEC, comp['n_compiling']))

        # ---- ② 逐用例取 ucdb（同批编译版本；逐例记录 PASS/FAIL 只为如实说明"哪些用例贡献了数据"）----
        results, n_pass, n_fail = [], 0, 0
        wd = sandbox
        for i, c in enumerate(cases):
            ucdb = os.path.join(ucdb_dir, '%s.ucdb' % c['name'])
            if os.path.exists(ucdb):
                os.remove(ucdb)                         # 防"用上次的 ucdb 交差"
            if c.get('cov_only'):
                # 受控复位注入通道（R0 2026-09-26 裁定 NU-2）：RTL 单侧判定，见 run_case_rst
                r = run_case_rst(c, wd, args.case_timeout, log,
                                 'cov-rst-%d/%d' % (i + 1, len(cases)),
                                 opt_name='cov_opt', ucdb=ucdb)
            else:
                r = R.run_case(c, wd, args.case_timeout, R.DEFAULT_ISS_TIMEOUT, log,
                               'cov-%d/%d' % (i + 1, len(cases)), opt_name='cov_opt', ucdb=ucdb)
            r['ucdb'] = R.rel(ucdb) if os.path.exists(ucdb) else ''
            results.append(r)
            n_pass += 1 if r['status'] == 'PASS' else 0
            n_fail += 1 if r['status'] != 'PASS' else 0
            print('[cover] %2d/%d %-18s %-8s ucdb=%s' % (i + 1, len(cases), c['name'], r['status'],
                                                         'Y' if r['ucdb'] else 'N'))
            if not r['ucdb'] and not args.keep_going:
                R._log(log, '[cover] %s 未产 ucdb 且未开 --keep-going ⇒ 停（fail-closed）' % c['name'])
                return EXIT_ENV
        have = [r for r in results if r['ucdb']]
        if not have:
            R._log(log, '[cover] 无任何 ucdb 落盘（fail-closed）')
            print('[cover] 无任何 ucdb 落盘（fail-closed）')
            return EXIT_ENV

        # ---- ③ 合并（限同一编译版本）----
        merged = os.path.join(COVDB, '%s.ucdb' % args.batch)
        os.makedirs(COVDB, exist_ok=True)
        if os.path.exists(merged):
            os.remove(merged)
        rc, out = vcover(['merge', '-out', merged] + [os.path.join(ROOT, r['ucdb']) for r in have],
                         sandbox, 1800, 'vcover-merge')
        R._log(log, '\n[vcover merge] rc=%d\n%s' % (rc, out))
        if rc != 0 or not os.path.exists(merged):
            print('[cover] vcover merge 失败（rc=%d）→ %s' % (rc, R.rel(log)))
            return EXIT_ENV
        # ---- ④ 报告（AGENTS.md §3.1 的 `-cvg -detail`；本版 usage 正拼写为 `-details`，二者等价）----
        rc_r, rep = vcover(['report', '-cvg', '-detail', merged], sandbox, 1800, 'vcover-report-cvg')
        R._log(log, '\n[vcover report -cvg -detail] rc=%d\n%s' % (rc_r, rep))
        if rc_r != 0:
            print('[cover] vcover report（-cvg -detail）失败（rc=%d）→ %s' % (rc_r, R.rel(log)))
            return EXIT_ENV
        # 断言覆盖（**2026-09-26 心跳第 8 轮加**；ADR-5 式的"证据行"口径）：`-detail` 给出**逐条**
        # `Failure Count / Pass Count` ⇒ 用**工具自报数**证"断言真的在跑、且 0 失败"（红线 R8：
        # 断言通过＝判据之一；"配了没生效"不算）。只报告不判定（阈值归 M3/签核）。
        rc_a, repa = vcover(['report', '-assert', '-detail', merged], sandbox, 1800,
                            'vcover-report-assert')
        R._log(log, '\n[vcover report -assert] rc=%d\n%s' % (rc_a, repa))
        if rc_a != 0:
            print('[cover] vcover report（-assert）失败（rc=%d）→ %s' % (rc_a, R.rel(log)))
            return EXIT_ENV
        rc_c, repc = vcover(['report', '-code', 'sbcef', merged], sandbox, 1800,
                            'vcover-report-code')
        R._log(log, '\n[vcover report -code sbcef] rc=%d\n%s' % (rc_c, repc))
        if rc_c != 0:
            print('[cover] vcover report（-code sbcef）失败（rc=%d）→ %s' % (rc_c, R.rel(log)))
            return EXIT_ENV
        with io.open(os.path.join(sandbox, 'report_code_raw.txt'), 'w', encoding='utf-8',
                     newline='\n') as f:
            f.write(repc or '')
        # DUT 面切分：只按 **编译单元名**（`filelist/rtl.f` 的模块名）过滤，**不改任何数字**
        dut_stems = _dut_unit_stems(comp['units'])
        secs = _split_instances(repc or '')
        mdu = re.compile(r'Design Unit:\s*work\.(\w+)\s*$', re.M)
        dut_secs = [s for s in secs if mdu.search(s[1]) and mdu.search(s[1]).group(1) in dut_stems]
        dut_roll = _rollup(dut_secs)
        tool_total = [ln.strip() for ln in (repc or '').splitlines() if 'Total Coverage' in ln]
        dut_block = '\n\n'.join(s[1].strip() for s in dut_secs) if dut_secs else \
            '(未识别到 DUT 面实例节——切分规则见本节注)'
        # §A/§D 的**照实**自述（2026-09-26 心跳第 8 轮改为**从工具输出派生**，不再写死文案——
        #   写死会在落首批 covergroup/SVA 后变成与正文矛盾的假陈述）
        cvg_nodata = ('No matching coverage data' in (rep or ''))
        cvg_total = [ln.strip() for ln in (rep or '').splitlines()
                     if ln.strip().startswith('TOTAL COVERGROUP COVERAGE')]
        m_cp = re.search(r'Coverpoints/Crosses\s+(\d+)', rep or '')
        # 断言覆盖的**合计行**（`-detail` 版式实测无 `TOTAL ASSERTION COVERAGE` 行，只有逐条表 +
        #   段首 `Assertions  <bins> <hits> <misses> <pct>`；两种版式都取，取到即用——**照实转抄**）
        asr_total = [ln.strip() for ln in (repa or '').splitlines()
                     if ln.strip().startswith('TOTAL ASSERTION COVERAGE')]
        if not asr_total:
            for ln in (repa or '').splitlines():
                m_a = re.match(r'^\s*Assertions\s+(\d+)\s+(\d+)\s+(\d+)\s+([\d.]+)%\s*$', ln)
                if m_a:
                    asr_total = ['Assertions bins=%s hits=%s misses=%s coverage=%s%%（`-assert -detail` '
                                 '段首合计行，原文照录）' % m_a.groups()]
                    break
        a_cvg = ('【当前水平·照实】§A（`-cvg -detail`，AGENTS.md §3.1 的指定口径）**没有数据** —— '
                 'DUT 侧尚无 covergroup／SVA ⇒ vcover 报 `No matching coverage data found`。'
                 '本批的实质数字在 §B/§C 的**代码覆盖率**面：' if cvg_nodata else
                 '【当前水平·照实】§A（`-cvg -detail`，AGENTS.md §3.1 的指定口径）**本批有数据** —— '
                 '功能覆盖模型落 TB 侧 `tb/unit/m1_e2e_cov.sv`（3 个 covergroup／%s 个 coverpoint；'
                 'VP 号见该件头），工具自报合计行：%s。'
                 % (m_cp.group(1) if m_cp else '?',
                    ' ／ '.join(cvg_total) if cvg_total else '(未解析到 TOTAL 行)'))
        a_asr = ('§D（`-assert -detail`）**本批有数据**：%s ⇒ 断言**真的在跑**（逐条 `Failure/Pass` '
                 '计数原文即证据；红线 R8 的"断言通过"面由此可证）；'
                 '`Pass=0 且 Failure=0` 的条目＝本批**未被激励**（如实标注，见件头 TODO(M2-c-2-b)）'
                 % (' ／ '.join(asr_total) if asr_total else '(未解析到 TOTAL 行)') if asr_total else
                 '§D（`-assert -detail`）**没有数据**（本批编译集内无断言）')

        # ---- ⑤ 报告落 `doc/verify/07-<batch>.txt`（含**溯源头**与口径声明，不美化）----
        os.makedirs(VERIFY, exist_ok=True)
        report = os.path.join(VERIFY, '07-%s.txt' % args.batch)
        hdr = [
            '=' * 78,
            'VR1 覆盖率报告 ｜ batch=%s ｜ 生成 %s' % (args.batch, now_str()),
            '=' * 78,
            '【定位】M2 exit (c) 的**机制件产物**：本阶段只要求"机制在环"，**不要求达阈值**。',
            '        阈值判定（功能覆盖率 100%／代码覆盖率 ≥90% 逐项）归 M3／签核（AGENTS.md §4）。',
            '【溯源】编译指纹：sim/covdb/FINGERPRINT.json（RTL filelist md5=%s）'
            % filelist_hash,
            '【合并】vcover merge 的合并集 = 本批**同一次** vlog/vopt 产生的 %d 份逐例 ucdb'
            % len(have),
            '        （AGENTS.md §3.4 坑 3：跨编译版本不可相加；本批无跨版本合并）',
            '【命令】vlog -64 -sv -cover %s …（%d 单元）／vopt +cover=%s／vsim -64 -c -coverage '
            '-do "coverage save -onexit <case>.ucdb; run -all; quit -f"'
            % (COVER_SPEC, comp['n_compiling'], COVER_SPEC),
            '【逐例】用例 %d 条：PASS %d ／ 非 PASS %d（覆盖率批的"在环"不依赖逐例全过，'
            '逐例状态见沙箱 cases' % (len(cases), n_pass, n_fail),
            '        沙箱 sim/run_cover_%s/ 的 summary.txt ＋ ucdb/ 目录）' % args.batch,
            *(('【受控通道】用例 %s 走 R0 2026-09-26 裁定的**受控复位注入通道**（NU-2）：'
               '仅覆盖率批、RTL 单侧判定（HALT_PASS＋无 HALT_FAIL/WATCHDOG＋[rst_inj] 证据行），'
               '不做 ISS↔RTL 比对（复位注入使 trace 出现第二段，构造性不可比）；'
               '不进回归同配置与 m2-rv64ui（通道口径见 sw/tests/build_rv64ui.py COV_ONLY 段）。'
               % ', '.join(c['name'] for c in rst_cases)) if rst_cases else ()),
            '【如实声明】下列数字是**原样**的 vcover 输出：不作 exclude、不作 waiver、不挑数字',
            '        （红线 R7：waiver/exclude 一律逐条附理由并经人批，本批一条都没有）。',
            a_cvg.replace('\n', '\n        '),
            '        工具自报合计行（代码覆盖率）：%s' % ('\n        '.join(tool_total) or '(无)'),
            '        DUT 面逐单元数字＝§C 原文（`rtl/vr1/**` 编译单元，含 `vr1_core` 顶层实例）。',
            a_asr,
            '【DUT/TB 面】编译集含 TB 三件（`filelist/tb_m1_e2e.f`：写出器／覆盖模型／TB 顶层，'
            '心跳第 8 轮起为三件）；§B 是所有实例的原文（含 TB），',
            '        §C 只保留 `Design Unit: work.<rtl.f 单元名>` 的实例节，切分规则写在那一节里，',
            '        **未改任何数字**（TB 面覆盖率因此只在 §B 里读；covergroup 数据在 §A 独立成面）。',
            '【已知缺口】`spec/11` §1 的 A1~A19 断言**尚未落**（其归属面 free-list/RAT/PRF/`csrq`/',
            '        checkpoint 等机制未实现）⇒ 本批 §D 只有首批 6 条（VP-32/18/X02/24/09 面）；',
            '        验证点→covergroup 的全量映射归 M3（TODO(M2-c-2)）。',
            '【已知缺口】未开 toggle（t/x）：本批口径 ＝ AGENTS.md §3.1 的 `bcesf`（TODO(M2-c-3)）。',
            '=' * 78,
            '',
            '──────────── §A `vcover report -cvg -detail`（AGENTS.md §3.1 口径原文）────────────',
            rep.rstrip(),
            '',
            '──────────── §B `vcover report -code sbcef`（代码覆盖率原文）────────────',
            (repc or '').rstrip(),
            '',
            '──────────── §C DUT 面（`rtl/vr1/**`）代码覆盖率（只做单元名过滤）────────────',
            '过滤口径：按 `=== Instance:` 切节，只保留 `Design Unit: work.<名>` 的 <名> 属于',
            '`filelist/rtl.f` 编译单元名集合（模块名 = 文件名 stem）的节；节内文字**原文照录**。',
            'TB 两件（`m1_e2e_tb`／`rt_t_trace_writer`）与 DUT 同批编译，故只在 §B 里读它们的数字。',
            '',
            'C-1 本脚本自算的 DUT 面汇总（口径：Σhits/Σbins，与 AGENTS.md §4 功能覆盖率行同形；',
            '    **不是** vcover 自报数；工具自报合计行见 §B 末）：',
            '    ' + ('；'.join('%s %s/%s = %s%%' % (k, v['hits'], v['bins'], v['pct'])
                            for k, v in sorted(dut_roll.items())) or '(未解析到指标行)'),
            '',
            'C-2 DUT 面逐实例原文：',
            dut_block,
            '',
            '──────────── §D `vcover report -assert -detail`（断言覆盖原文；**心跳第 8 轮加**）────────────',
            '口径：逐条 `Failure Count / Pass Count` ＝该断言**失败/被求值且未失败**的次数（工具自报）；',
            '`0/0` ＝本批**未被激励**（前提条件从未成立 ⇒ 空真），**不是**"通过"——本批只有 6 条首批断言，',
            '不覆盖任何阈值判定。本节的用途是**证"断言真的在跑且 0 失败"**（红线 R8：断言通过是判据之一，',
            '而"配了没生效"不算）；阈值归 M3。',
            (repa or '').rstrip(),
            '',
        ]
        with io.open(report, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(hdr) + '\n')

        # ---- ⑥ 编译指纹（sim/covdb/README.md：每个 <batch>.ucdb 旁必须有指纹）----
        fp = {
            'batch': args.batch,
            'generated': now_str(),
            'producer': 'run_cmd/cover_rv1.py（M2 exit (c) 机制件；判据本体在 script/flow.py 的 m2-cov）',
            'rtl_filelist': {'path': R.rel(R.RTL_F), 'md5': filelist_hash},
            'tb_filelist': {'path': R.rel(R.TB_F), 'md5': tb_filelist_hash},
            'compile_units': fp_units,
            'generated_files': gen_files,
            'compile_commands': {'vlib': 'vlib work',
                                 'vlog': comp['vlog_cmd'],
                                 'vopt': comp['vopt_cmd']},
            'sim_command_template': ('vsim -64 -c -coverage -do "coverage save -onexit '
                                     '<case>.ucdb; run -all; quit -f" cov_opt +IMAGE=<tb_hex> '
                                     '+DATA=<data_hex> +RT_T_CSV=<sandbox>/<case>.rtl.csv'),
            'coverage_switches': {'vlog': '-cover %s' % COVER_SPEC,
                                  'vopt': '+cover=%s' % COVER_SPEC,
                                  'vsim': '-coverage'},
            'report_commands': {'cvg': 'vcover report -cvg -detail %s' % R.rel(merged),
                                'code': 'vcover report -code sbcef %s' % R.rel(merged),
                                'assert': 'vcover report -assert -detail %s' % R.rel(merged)},
            'coverage_numbers_as_is': {
                'note': ('**照实**记录：功能覆盖（`-cvg`）与断言覆盖（`-assert`）自 '
                         '2026-09-26 心跳第 8 轮起有数据（模型落 TB 侧 `tb/unit/m1_e2e_cov.sv`）；'
                         '下列代码覆盖率数字为 vcover 自报的合计行原文与 DUT 面自算汇总。'),
                'cvg_no_matching_data_found': cvg_nodata,
                'cvg_total_lines': cvg_total,
                'assert_total_lines': asr_total,
                'tool_total_lines': tool_total,
                'dut_face_rollup_selfcomputed': dut_roll,
                'dut_face_units_kept': sorted(dut_stems),
                'statement_branch_etc_have_no_threshold_in_this_batch': True,
            },
            'merge_command': 'vcover merge -out %s <逐例 ucdb × %d>'
                             % (R.rel(merged), len(have)),
            'merge_policy': ('AGENTS.md §3.4 坑 3：vcover merge 的合并集仅限**同一编译版本**。'
                             '本批逐例 ucdb **全部**来自上面 compile_commands 的同一次编译'
                             '（无跨版本合并）。'),
            'merged_ucdb': {'path': R.rel(merged), 'size': os.path.getsize(merged)},
            'report': {'path': R.rel(report), 'size': os.path.getsize(report)},
            'source_ucdbs': [r['ucdb'] for r in have],
            'n_cases': len(cases),
            'n_ucdb': len(have),
            'cases': [{'name': r['name'], 'status': r['status'], 'ucdb': r['ucdb'],
                       'channel': r.get('channel', 'iss+rtl+cmp')} for r in results],
            # 受控通道溯源（R0 2026-09-26 裁定 NU-2）：哪些条目走了 RTL 单侧判定与注入拍
            'controlled_channel_cases': [
                {'name': c['name'], 'reset_inject_cycles': c.get('reset_inject_cycles'),
                 'ruling': 'R0 2026-09-26 三项裁定①（doc/verify/02 §6 NU-2 受控通道）'}
                for c in rst_cases],
            'testlist': {'path': R.rel(testlist), 'md5': R.flowmod.md5_of(testlist)},
            'manifest': {'path': R.rel(R.MANIFEST), 'md5': R.flowmod.md5_of(R.MANIFEST)},
            'tool': {'mti': R.MTI, 'vlog': R.VLOG, 'vopt': R.VOPT, 'vsim': R.VSIM,
                     'vcover': VCOVER},
            'threshold_note': ('本批**不判**阈值（M3/签核口径：功能覆盖率 100%／代码覆盖率 ≥90% 逐项）；'
                               '本指纹只证"机制在环 + 数据可追溯"。'),
            'todos': ['M2-c-1 sim/covdb/README.md 状态段待人工更新（受 guard-write 保护，本轮未改）',
                      'M2-c-2 首批 covergroup/SVA 已落 TB 侧 tb/unit/m1_e2e_cov.sv（-cvg/-assert 面有数据）；'
                      'spec/11 §1 的 A1~A19 待机制在环后逐条落（free-list/RAT/PRF/csrq/checkpoint）',
                      'M2-c-3 toggle(t/x) 未开'],
            'elapsed_s': round(time.time() - t_start, 1),
        }
        R.flowmod.save_json(os.path.join(COVDB, 'FINGERPRINT.json'), fp)

        summary = [
            '# VR1 覆盖率批 summary（机制件产物；消费方：`script/flow.py` 的 `m2-cov` 判据）',
            '# 生成 %s ｜ batch=%s ｜ 沙箱 %s（红线 R10 独占）'
            % (now_str(), args.batch, R.rel(sandbox)),
            '# 编译版本：vlog %d 单元（-cover %s）／vopt +cover=%s ｜ rtl.f md5=%s'
            % (comp['n_compiling'], COVER_SPEC, COVER_SPEC, filelist_hash),
            '# 逐例 ucdb %d 份（合并集限同一编译版本）；合并件 %s' % (len(have), R.rel(merged)),
            '# 报告 %s ｜ 指纹 sim/covdb/FINGERPRINT.json' % R.rel(report),
            '# 口径：**不要求达阈值**（M3 才判）；不作 exclude/waiver（红线 R7）',
            '# 数字（照实）：§A 功能覆盖（-cvg）%s；§D 断言覆盖（-assert）：%s'
            % ('**无数据**（No matching coverage data found）' if cvg_nodata
               else ('有数据 → ' + (' ／ '.join(cvg_total) if cvg_total else '(未解析到 TOTAL 行)')),
               ('有数据 → ' + (' ／ '.join(asr_total) if asr_total else '(未解析到 TOTAL 行)'))
               if asr_total else '无数据（编译集内无断言）'),
            '# 数字（照实·代码覆盖率工具自报合计行）：%s'
            % (' ／ '.join(tool_total) if tool_total else '(无)'),
            '# 数字（照实·自算 DUT 面 Σhits/Σbins，非工具自报数）：%s'
            % ('；'.join('%s %s/%s=%s%%' % (k, v['hits'], v['bins'], v['pct'])
                         for k, v in sorted(dut_roll.items())) or '(未解析到指标行)'),
        ]
        for r in results:
            summary.append('%s %s ucdb=%s %s' % (r['status'], r['name'], 'Y' if r['ucdb'] else 'N',
                                                 r['reason'] or ''))
        summary.append('[cover] counts: total=%d pass=%d notpass=%d ucdb=%d'
                       % (len(cases), n_pass, n_fail, len(have)))
        summary.append('COVERAGE_MECHANISM_OK batch=%s merged=%s report=%s fingerprint=%s cases=%d'
                       % (args.batch, R.rel(merged), R.rel(report),
                          'sim/covdb/FINGERPRINT.json', len(have)))
        with io.open(os.path.join(sandbox, 'summary.txt'), 'w', encoding='utf-8',
                     newline='\n') as f:
            f.write('\n'.join(summary) + '\n')
        R._log(log, '\n' + '\n'.join(summary))
        print('\n'.join(summary[-2:]))
        print('[cover] 报告 %s（%d B）｜ 指纹 sim/covdb/FINGERPRINT.json ｜ 合并件 %s'
              % (R.rel(report), os.path.getsize(report), R.rel(merged)))
        return EXIT_OK
    except RuntimeError as e:
        R._log(log, '[cover] 环境/配置错误（fail-closed）：%s' % e)
        print('[cover] 环境/配置错误（fail-closed）：%s' % e)
        return EXIT_ENV
    finally:
        lock.release()


if __name__ == '__main__':
    raise SystemExit(main())
