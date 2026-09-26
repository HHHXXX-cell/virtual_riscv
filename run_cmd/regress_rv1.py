#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""run_cmd/regress_rv1.py — VR1 批级回归 runner（**M2 exit (b) 的机制件**，非判据本体）

定位（务必读；判据本体在 `script/flow.py`，本文件**不改**它）
  · 本文件只产**可被判据消费的产物**：批级 `summary.txt`（逐例一行 + 尾行）＋ `config.json`
    （同配置的机判面）＋ `cases.json`（机器可读逐例明细）＋ 每例两侧 trace CSV ＋ `run.log`。
  · M2 exit (b) 的口径（`state/flow.json` 的 `m2-regress` 行）＝「同配置 **≥2 轮** 0 新 FAIL；
    R10 并发 ≤4 且每 runner 独占沙箱；R9 watchdog 在环」。本文件把这四条落成**可跑**的机制：
      同配置   → `config.json` 记录 testlist md5／MANIFEST md5／jobs／两个超时／编译命令／用例序，
                 `--diff A B` 直接机判两轮配置是否同一（`SAME_CONFIG yes/no`）；
      RTL 版本 → `config.json.fingerprint`＝`filelist/rtl.f` md5 ＋ `filelist/tb_m1_e2e.f` md5 ＋
                 **每个编译单元的 md5**（编译后立刻采），收尾复算写 `changed_since_fingerprint`
                 （轮内被改即非空 ⇒ 如实落证、判据侧判红）。消费方＝`script/flow.py` 的 `m2-regress`
                 判据的**时效面**（"两轮与**当前** RTL 同版本"），判据本体在 flow.py，本文件**不改**它；
      ≥2 轮   → 一轮一次调用（`--runner-id r1` / `--runner-id r2`），轮间差异落
                 `sim/run_regress_<head>/round_diff.txt`（含 `NEW_FAIL=<n>`）；
      R10     → `MAX_JOBS = 4` **硬编码**（>4 直接拒绝，不静默截断）；每 runner 独占
                 `sim/run_regress_<runner_id>/`，用 `.runner.lock`（pid 存活即拒启动）互斥；
      R9      → TB 侧 2,000,000 拍 watchdog（`tb/unit/rt_t_trace_writer.sv`）
                ＋ 本 runner 侧挂钟双闸：单用例 `--case-timeout`（默认 1200 s ＝ R9「ModelSim
                20 分钟/用例」）与批累计 `--batch-budget`（默认 7200 s ＝ R9「单轮总时长 2 小时」）；
                超时用 `taskkill /T`（Windows）杀**进程树**，不留孤儿 vsim 占库。

逐例口径（逐字对齐 `script/flow.py:chk_m2_rv64ui` 的 ④，**不新立、不放宽**）
  ① ISS 侧：`python iss/run_iss.py run --hex <hex> --csv <iss.csv> --tohost 0x40000010`
     退出码 0 且输出含 `halt_val=0x1`；
  ② RTL 侧：`vsim … m1_e2e_tb 优化产物 +IMAGE=<tb_hex> +DATA=<data_hex> +RT_T_CSV=<rtl.csv>`，
     **无** `HALT_FAIL`／`WATCHDOG_TIMEOUT`，有 `HALT_PASS … rows=N` 且 N == ISS 侧数据行数；
  ③ 比对：`python iss/tools/trace_compare.py <iss.csv> <rtl.csv>` 退出码 0 且输出含 `mismatch=0`
     （列 `pc,binary,gpr,csr`；**不开** `--final-only`／`--cols`／`--with-asm`，红线 R6）；
  ④ 镜像面：逐条 hex/tb_hex/data_hex 的存在性 + md5 复算 == `MANIFEST.json`（"一份镜像喂两边"未漂移）。

批中止判据（AGENTS.md §5 规则 10 的 AB1/AB5/AB6；**映射口径显式声明**）
  本 runner 跑的是 **RTL 端到端＋ISS＋比对**，**没有 UVM 平台** ⇒ AB5 里的 `UVM_FATAL` 按
  「**平台/环境级致命**」映射 = `vlog`/`vopt` 失败、`vsim` 退出码非 0（加载/仿真器错误）、
  批级预算耗尽。**DUT 功能面失败不计入 fatal**：`HALT_FAIL`（riscv-tests tohost 非 1）、
  行数不等、`mismatch>0`、ISS 侧 `halt_val≠1` 一律记 `FAIL` 计数（对应 §4 的用例 FAIL，
  不中止批——中止批是"环境已坏、再跑是烧机器"的判据，不是"发现 bug"的判据）。
  · AB1：**连续 ≥2 例**编译/加载失败 → 中止（编译阶段失败即刻中止，整批不可跑）；
  · AB5：已完成 ≥5 例且 fatal 占比 ≥10% → 中止；
  · AB6：单用例 watchdog 超时（TB `WATCHDOG_TIMEOUT` 行，或挂钟超 `--case-timeout`）
         → 立即中止；批累计挂钟超 `--batch-budget` → 中止。
  中止时 summary 尾行为 `REGRESSION_ABORTED <ABx>：<原因>`，退出码非 0（=2）。

退出码
  0 = 批跑完且 0 FAIL（尾行 `REGRESSION_PASS`）
  1 = 批跑完但有 FAIL（尾行 `REGRESSION_FAIL`；**不是**中止）
  2 = `REGRESSION_ABORTED`（AB1/AB5/AB6）
  3 = 环境/配置错误（fail-closed：缺件、testlist 不可用、`--jobs` 越界、沙箱被占、镜像 md5 漂移）

写边界（本文件**只写**这些位置）
  `sim/run_regress_<runner_id>/**`（沙箱，含 work 库/CSV/日志/summary/config/cases）与
  `sim/run_regress_<head>/round_diff.txt`。**不写** `rtl/**`、`doc/spec/**`、`rtl/vr1/include/*.svh`、
  `script/flow.py`。沙箱独占＝红线 R10（同 runner_id 二次启动会被锁挡住）。

TODO（本机制件的已知未落项，如实登记，不得当"已做"）
  · TODO(M2-b-1)：`jobs>1` 时每 worker 复制一份编译库到 `job<k>/`（库体积 ~9 MB/份，实测可接受）；
    并发路径的**中止语义**为"结果回收侧判定、在飞用例不打断"（与 jobs=1 的严格顺序中止不同）——
    正式两轮回归用默认 `jobs=1`，故不影响已跑证据。
  · TODO(M2-b-2)：`--case-timeout` 触发时只杀 `vsim` 进程树；若底层 license 守护进程残留，
    需人工确认（观察项，未复现）。
  · TODO(M2-b-3)：`round_diff.txt` 目前只比"用例名集合的 FAIL 差"，**不比**失败原因文本（原因文本
    易随 waring 措辞漂移）；判据若要"原因级新失败"需另立口径。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'script'))
try:                                              # 只读复用（**不复制、不改写**其判据逻辑）
    import flow as flowmod                        # msim_env / _parse_f_list / md5_of / load_json
except Exception as e:                            # noqa: BLE001
    print('[regress] 无法复用 script/flow.py 的工具函数：%s' % e)
    raise SystemExit(3)

MTI = os.environ.get('MTI', r'D:\modeltech64_2020.4\win64')
VLOG = os.path.join(MTI, 'vlog.exe')
VLIB = os.path.join(MTI, 'vlib.exe')
VOPT = os.path.join(MTI, 'vopt.exe')
VSIM = os.path.join(MTI, 'vsim.exe')

RTL_F = os.path.join(ROOT, 'filelist', 'rtl.f')
TB_F = os.path.join(ROOT, 'filelist', 'tb_m1_e2e.f')
MANIFEST = os.path.join(ROOT, 'sim', 'image', 'rv64ui', 'MANIFEST.json')
ISS_RUN = os.path.join(ROOT, 'iss', 'run_iss.py')
TRACE_COMPARE = os.path.join(ROOT, 'iss', 'tools', 'trace_compare.py')
DEFAULT_TESTLIST = os.path.join(ROOT, 'run_cmd', 'rv64ui_testlist.txt')

RV64UI_TOHOST = 0x4000_0010            # 与 TB `TOHOST_ADDR` 同值（口径来自 sw/tests/env）
MAX_JOBS = 4                           # 红线 R10：回归并发 ≤4（**硬编码**，不随参数放大）
DEFAULT_CASE_TIMEOUT = 1200            # 红线 R9：ModelSim 挂钟上限 20 分钟/用例
DEFAULT_BATCH_BUDGET = 7200            # 红线 R9：AI 自主连续仿真单轮总时长上限 2 小时
DEFAULT_ISS_TIMEOUT = 600
WATCHDOG_CYCLES = 2000000              # 红线 R9：TB 侧单用例 watchdog 拍数（同值，仅作记录）

AB1_CONSEC_FATAL = 2                   # AB1：连续 ≥2 例编译/加载失败 → 批中止
AB5_MIN_DONE = 5                       # AB5：完成 ≥5 例且 fatal 占比 ≥10% → 批中止
AB5_FATAL_RATIO = 0.10
AB6_LABEL = 'AB6'

RE_HALT_PASS = re.compile(r'HALT_PASS\s+tohost=(\S+)\s+val=(\S+)\s+rows=(\d+)')
RE_HALT_FAIL = re.compile(r'HALT_FAIL\s+tohost=(\S+)\s+val=(\S+)\s+testnum=(\d+)')
RE_ERRORS = re.compile(r'Errors:\s*(\d+)')

EXIT_OK, EXIT_FAIL, EXIT_ABORTED, EXIT_ENV = 0, 1, 2, 3


def now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def rel(p):
    return os.path.relpath(p, ROOT).replace('\\', '/')


def fwd(p):
    return os.path.abspath(p).replace('\\', '/')


def log_open(path):
    return io.open(path, 'a', encoding='utf-8', newline='\n')


def _log(path, text):
    with log_open(path) as f:
        f.write(text if text.endswith('\n') else text + '\n')


def pid_alive(pid):
    """进程存活判定（**不得**在 Windows 上用 `os.kill(pid, 0)`：那会 TerminateProcess 掉别人）。"""
    if pid <= 0:
        return False
    if os.name == 'nt':
        try:
            out = subprocess.run(['tasklist', '/FI', 'PID eq %d' % pid, '/NH'],
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=30).stdout or ''
        except Exception:                                     # noqa: BLE001
            return True                                       # 查不动 ⇒ 保守当占用
        return ('%d' % pid) in out
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def run_capture(argv, cwd, timeout, tag, log=None):
    """跑一条子进程并**连超时一起落证**。返回 (rc, out, timed_out)。

    timeout 到点后杀**进程树**（Windows `taskkill /F /T`）：ModelSim 会派生 vish/db 子进程，
    只杀直接子进程会留孤儿占住编译库（R9 的 watchdog 必须真的在环，不能只"设了个参数"）。
    """
    env = flowmod.msim_env()
    t0 = time.time()
    try:
        p = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, errors='replace', env=env)
    except OSError as e:
        return 99, '[%s] 启动失败：%s' % (tag, e), False
    try:
        out, _ = p.communicate(timeout=timeout)
        rc, timed = p.returncode, False
    except subprocess.TimeoutExpired:
        timed = True
        if os.name == 'nt':
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(p.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            p.kill()
        try:
            out, _ = p.communicate(timeout=60)
        except Exception:                                     # noqa: BLE001
            out = ''
        rc = 99
        out = (out or '') + '\n!! TIMEOUT %ss（进程树已杀）\n' % timeout
    out = out or ''
    if log:
        _log(log, '\n[%s] $ %s  (cwd=%s, %ss, rc=%d)\n%s'
             % (tag, ' '.join(argv), rel(cwd), round(time.time() - t0, 1), rc, out))
    return rc, out, timed


class SandboxLock:
    """`sim/run_regress_<runner_id>/` 的**独占**（红线 R10）。pid 存活即拒启动（fail-closed）。"""

    def __init__(self, sandbox, tag):
        self.sandbox = sandbox
        self.path = os.path.join(sandbox, '.runner.lock')
        self.tag = tag

    def acquire(self):
        os.makedirs(self.sandbox, exist_ok=True)
        log = os.path.join(self.sandbox, 'run.log')
        if os.path.exists(self.path):
            info = flowmod.load_json(self.path, default={}) or {}
            pid = int(info.get('pid', 0) or 0)
            if pid_alive(pid):
                raise RuntimeError(
                    '沙箱 %s 已被占用（pid=%d tag=%s since %s）——红线 R10：每 runner 独占沙箱，'
                    '请换 `--runner-id` 或等它结束' % (rel(self.sandbox), pid, info.get('tag'),
                                                       info.get('started')))
            _log(log, '[lock] 陈旧锁（pid=%d 已不在）→ 接管；旧记录：%s' % (pid, info))
        with log_open(log):
            pass
        flowmod.save_json(self.path, {'pid': os.getpid(), 'tag': self.tag,
                                      'started': now_str(), 'cwd': os.getcwd()})
        _log(log, '\n==== regress 启动 %s ｜ %s ｜ pid=%d ｜ sandbox=%s ===='
             % (self.tag, now_str(), os.getpid(), rel(self.sandbox)))

    def release(self):
        try:
            if os.path.exists(self.path):
                os.remove(self.path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 输入面：testlist + MANIFEST（全 fail-closed）
# --------------------------------------------------------------------------- #
def load_manifest():
    man = flowmod.load_json(MANIFEST, default=None)
    if not isinstance(man, dict) or not man.get('tests'):
        raise RuntimeError('MANIFEST 不可解析或缺 tests：%s（fail-closed）' % rel(MANIFEST))
    if int((man.get('abi') or {}).get('tohost', -1)) != RV64UI_TOHOST:
        raise RuntimeError('MANIFEST.abi.tohost ≠ 0x%x（与 TB `TOHOST_ADDR` 口径不符；fail-closed）'
                           % RV64UI_TOHOST)
    return man


def read_testlist(path):
    if not os.path.exists(path):
        raise RuntimeError('testlist 不存在：%s（fail-closed）' % rel(path))
    names = []
    for ln in io.open(path, 'r', encoding='utf-8').read().splitlines():
        s = ln.strip()
        if not s or s.startswith('#'):
            continue
        names.append(s)
    if not names:
        raise RuntimeError('testlist 为空：%s（fail-closed）' % rel(path))
    return names


def resolve_cases(names, man, limit=0):
    """testlist 名字 → 逐例镜像路径（存在性 + md5 复算 == MANIFEST；漂移即 fail-closed）。"""
    by_name = {t['name']: t for t in man['tests']}
    cases = []
    for nm in names:
        if nm not in by_name:
            raise RuntimeError('testlist 的 `%s` 不在 MANIFEST.tests 在册名单里（fail-closed；'
                               '不静默跳过）' % nm)
        cases.append(dict(by_name[nm]))
    if limit:
        cases = cases[:limit]
    for c in cases:
        for key in ('hex', 'tb_hex', 'data_hex'):
            p = os.path.join(ROOT, c[key])
            if not os.path.exists(p):
                raise RuntimeError('条目 %s 的 %s 不存在（fail-closed）' % (c['name'], c[key]))
            got = flowmod.md5_of(p)
            if got != c.get(key + '_md5'):
                raise RuntimeError('%s 镜像漂移：%s md5=%s ≠ MANIFEST %s（重跑 build_rv64ui.py；'
                                   'fail-closed）' % (c['name'], c[key], got[:12],
                                                      str(c.get(key + '_md5'))[:12]))
    return cases


# --------------------------------------------------------------------------- #
# 编译（vlog + vopt；集合＝rtl.f + tb_m1_e2e.f，与 m2-rv64ui/rtl-vs-iss 同口径）
# --------------------------------------------------------------------------- #
def compile_design(sandbox, log, cover=None, opt_name='m2_opt'):
    for p in (RTL_F, TB_F):
        if not os.path.exists(p):
            raise RuntimeError('缺编译清单 %s（fail-closed）' % rel(p))
    for exe in (VLOG, VLIB, VOPT, VSIM):
        if not os.path.exists(exe):
            raise RuntimeError('ModelSim 工具缺件：%s（fail-closed）' % exe)
    rtl_units, rtl_incs = flowmod._parse_f_list(RTL_F)
    tb_units, tb_incs = flowmod._parse_f_list(TB_F)
    units = rtl_units + tb_units
    incs = list(dict.fromkeys(rtl_incs + tb_incs))
    if not units or not incs:
        raise RuntimeError('编译清单条目/incdir 为空（fail-closed）')
    vlog_args = [VLOG, '-64', '-sv']
    if cover:
        vlog_args += ['-cover', cover]                 # AGENTS.md §3.1 口径：编译期就要带
    vlog_args += ['-work', 'work']
    vlog_args += ['+incdir+%s' % fwd(os.path.join(ROOT, i)) for i in incs]
    vlog_args += [fwd(os.path.join(ROOT, u)) for u in units]
    vopt_args = [VOPT, '-64']
    if cover:
        # 实测（2026-09-26）：vopt 只认 `+cover=<spec>`（`-cover=…` 报 vopt-10538 非法选项），
        # 与 vlog 的 `-cover <spec>`（AGENTS.md §3.1 口径）是**同一插桩语义**的两个工具拼写。
        vopt_args += ['+cover=%s' % cover]
    vopt_args += ['work.m1_e2e_tb', '-o', opt_name]
    _log(log, '\n[compile] %s\n[compile] 单元 %d（rtl %d + tb %d）／incdir %d'
              % (now_str(), len(units), len(rtl_units), len(tb_units), len(incs)))
    rc1, o1, t1 = run_capture([VLIB, 'work'], sandbox, 300, 'vlib', log)
    if rc1 != 0 or t1:
        raise RuntimeError('vlib 失败（rc=%d）' % rc1)
    rc2, o2, t2 = run_capture(vlog_args, sandbox, 1800, 'vlog', log)
    n_err = RE_ERRORS.findall(o2)
    n_comp = len(re.findall(r'^-- Compiling', o2, re.M))
    if t2 or rc2 != 0 or not n_err or int(n_err[-1]) != 0:
        raise RuntimeError('vlog 失败（rc=%d ／ Errors: %s；fail-closed）'
                           % (rc2, n_err[-1] if n_err else '?'))
    if n_comp != len(units):
        raise RuntimeError('`-- Compiling` 计数 %d ≠ 清单条目数 %d（fail-closed）' % (n_comp, len(units)))
    rc3, o3, t3 = run_capture(vopt_args, sandbox, 1800, 'vopt', log)
    n_o = RE_ERRORS.findall(o3)
    if t3 or rc3 != 0 or not n_o or int(n_o[-1]) != 0:
        raise RuntimeError('vopt 失败（rc=%d ／ Errors: %s；fail-closed）'
                           % (rc3, n_o[-1] if n_o else '?'))
    return {
        'vlog_cmd': ' '.join(vlog_args),
        'vopt_cmd': ' '.join(vopt_args),
        'units': units,
        'incdirs': incs,
        'n_compiling': n_comp,
        'cover': cover or '',
    }


# --------------------------------------------------------------------------- #
# 单例执行：ISS → RTL → 比对
# --------------------------------------------------------------------------- #
def run_case(case, workdir, case_timeout, iss_timeout, log, tag, opt_name='m2_opt', ucdb=None):
    """返回 dict（status ∈ PASS/FAIL/FATAL/TIMEOUT + reason + 证据字段）。

    `ucdb` 非空 ⇒ **覆盖率批**形态：vsim 加 `-coverage`，并在 `run -all` 前 `coverage save -onexit`。
    除这两处，逐例口径与回归批**逐字相同**（同一判据面，不因开覆盖率而放宽任何一项）。
    """
    name = case['name']
    t0 = time.time()
    r = {'name': name, 'status': 'FAIL', 'reason': '', 'rows_iss': None, 'rows_rtl': None,
         'mismatch': None, 'cyc': None, 'elapsed_s': None, 'csv_iss': '', 'csv_rtl': ''}
    iss_csv = os.path.join(workdir, '%s.iss.csv' % name)
    rtl_csv = os.path.join(workdir, '%s.rtl.csv' % name)
    for p in (iss_csv, rtl_csv):
        if os.path.exists(p):
            os.remove(p)                                  # 防"用上次的 CSV 交差"
    # ---- ① ISS 侧 ----
    rc, o, timed = run_capture([sys.executable, ISS_RUN, 'run', '--hex', case['hex'],
                                '--csv', rel(iss_csv), '--tohost', '0x%x' % RV64UI_TOHOST],
                               ROOT, iss_timeout, '%s.iss' % name, log)
    if timed:
        r.update(status='TIMEOUT', reason='ISS 侧挂钟超时（>%ds）' % iss_timeout)
        return r
    if rc != 0 or 'halt_val=0x1' not in o:
        r.update(status='FAIL', reason='ISS 侧未 PASS（退出码 %d；%s）——镜像/测试自身或 ISS 缺陷，先归因'
                 % (rc, flowmod.last_line(o)[:90]))
        return r
    n_iss = flowmod._csv_data_rows(iss_csv)
    r['rows_iss'] = n_iss
    r['csv_iss'] = rel(iss_csv)
    if n_iss is None:
        r.update(status='FATAL', reason='ISS 侧 CSV 不可读（fail-closed）')
        return r
    # ---- ② RTL 侧 ----
    vsim_args = [VSIM, '-64', '-c']
    do_cmd = 'run -all; quit -f'
    if ucdb:
        vsim_args += ['-coverage']
        do_cmd = 'coverage save -onexit %s; run -all; quit -f' % fwd(ucdb)
    vsim_args += ['-do', do_cmd, opt_name,
                  '+IMAGE=%s' % fwd(os.path.join(ROOT, case['tb_hex'])),
                  '+DATA=%s' % fwd(os.path.join(ROOT, case['data_hex'])),
                  '+RT_T_CSV=%s' % fwd(rtl_csv)]
    rc2, o2, timed2 = run_capture(vsim_args, workdir, case_timeout, '%s.rtl' % name, log)
    r['csv_rtl'] = rel(rtl_csv)
    if ucdb:
        r['ucdb'] = rel(ucdb) if os.path.exists(ucdb) else ''
    if timed2:
        r.update(status='TIMEOUT', reason='RTL 侧挂钟超时（>%ds，进程树已杀；R9/AB6）' % case_timeout)
        return r
    bad = [ln.strip() for ln in o2.splitlines() if 'HALT_FAIL' in ln or 'WATCHDOG_TIMEOUT' in ln]
    wd = [x for x in bad if 'WATCHDOG_TIMEOUT' in x]
    if wd:
        r.update(status='TIMEOUT', reason='TB watchdog 超时（R9/AB6）：%s' % wd[0][:100])
        return r
    mf = RE_HALT_FAIL.search(o2)
    if mf:
        r.update(status='FAIL', reason='RTL 侧自报 HALT_FAIL（tohost val=%s testnum=%s）'
                 % (mf.group(2), mf.group(3)))
        return r
    if rc2 != 0:
        r.update(status='FATAL', reason='vsim 退出码 %d（加载/仿真器级错误；AB1/AB5 的 fatal 面）'
                 % rc2)
        return r
    mh = RE_HALT_PASS.search(o2)
    if not mh:
        r.update(status='FATAL', reason='RTL 侧未见 `HALT_PASS … rows=…`（fail-closed：无停机证据）')
        return r
    r['rows_rtl'] = int(mh.group(3))
    mcy = re.search(r'HALT_PASS\s+tohost=\S+\s+val=\S+\s+rows=\d+\s+cyc=(\d+)', o2)
    r['cyc'] = int(mcy.group(1)) if mcy else None
    if 'data window preloaded:' not in o2:
        r.update(status='FAIL', reason='RTL 侧未见数据窗预载证据行（`+DATA=` 未生效 ⇒ 等价性无证据）')
        return r
    if r['rows_rtl'] != n_iss:
        r.update(status='FAIL', reason='RTL 侧 rows=%d ≠ ISS 行数 %d（长度不等）'
                 % (r['rows_rtl'], n_iss))
        return r
    if not os.path.exists(rtl_csv):
        r.update(status='FATAL', reason='RTL 侧 CSV 未落盘（fail-closed）')
        return r
    # ---- ③ 比对（列集由 trace_compare 定死；不传任何放宽开关）----
    rc3, o3, timed3 = run_capture([sys.executable, TRACE_COMPARE, rel(iss_csv), rel(rtl_csv)],
                                  ROOT, 300, '%s.cmp' % name, log)
    m = re.search(r'mismatch=(\d+)', o3 or '')
    r['mismatch'] = int(m.group(1)) if m else None
    if timed3:
        r.update(status='TIMEOUT', reason='trace_compare 超时（>300s）')
        return r
    if rc3 != 0 or 'mismatch=0' not in (o3 or ''):
        r.update(status='FAIL', reason='RTL-vs-ISS 未 0 mismatch（退出码 %d；%s）'
                 % (rc3, flowmod.last_line(o3)[:90]))
        return r
    r.update(status='PASS', reason='')
    r['elapsed_s'] = round(time.time() - t0, 2)
    return r


# --------------------------------------------------------------------------- #
# 一轮回归
# --------------------------------------------------------------------------- #
def cmd_round(args):
    runner_id = args.runner_id
    if args.jobs < 1:
        print('[regress] --jobs 必须 ≥1')
        return EXIT_ENV
    if args.jobs > MAX_JOBS:
        print('[regress] --jobs=%d 超红线 R10 硬上限 %d（**不静默截断**，拒绝启动）'
              % (args.jobs, MAX_JOBS))
        return EXIT_ENV
    testlist = args.testlist if os.path.isabs(args.testlist) else os.path.join(ROOT, args.testlist)
    sandbox = os.path.join(ROOT, 'sim', 'run_regress_%s' % runner_id)
    lock = SandboxLock(sandbox, 'regress_%s' % runner_id)
    try:
        lock.acquire()
    except RuntimeError as e:
        print('[regress] %s' % e)
        return EXIT_ENV
    log = os.path.join(sandbox, 'run.log')
    try:
        man = load_manifest()
        names = read_testlist(testlist)
        cases = resolve_cases(names, man, args.limit)
        t_start = time.time()
        cfg = {
            'runner_id': runner_id,
            'round': args.round,
            'testlist': rel(testlist),
            'testlist_md5': flowmod.md5_of(testlist),
            'manifest': rel(MANIFEST),
            'manifest_md5': flowmod.md5_of(MANIFEST),
            'cases': [c['name'] for c in cases],
            'n_cases': len(cases),
            'limit': args.limit,
            'jobs': args.jobs,
            'jobs_cap': MAX_JOBS,
            'case_timeout_s': args.case_timeout,
            'iss_timeout_s': args.iss_timeout,
            'batch_budget_s': args.batch_budget,
            'watchdog_cycles': WATCHDOG_CYCLES,
            'tohost': '0x%x' % RV64UI_TOHOST,
            'sandbox': rel(sandbox),
            'layout': 'flat' if args.jobs == 1 else 'job<k>',
            'started': now_str(),
        }
        # 编译（一次，批内共享；jobs>1 时编译库按 worker 复制，见 TODO(M2-b-1)）
        comp = compile_design(sandbox, log)
        cfg['compile'] = {'vlog_cmd': comp['vlog_cmd'], 'vopt_cmd': comp['vopt_cmd'],
                          'units': comp['units'], 'incdirs': comp['incdirs'],
                          'n_compiling': comp['n_compiling']}
        # RTL 版本指纹（判据 `m2-regress` 的时效面）：**编译完成后立刻**采 md5，收尾复算比对。
        # 判据侧拿它与**当前** filelist/rtl.f（及逐单元）比 ⇒ 不等即"证据过期"（RTL 在该轮之后被改）。
        # **不放任何时间戳**：本块参与 `--diff` 的同配置逐字段比对（时间戳会让两轮"配置不同"）；
        # 采集时刻由 summary 头的生成时间与 config.finished 承载，本块只放**内容指纹**。
        fp = {'rtl_filelist': {'path': rel(RTL_F), 'md5': flowmod.md5_of(RTL_F)},
              'tb_filelist': {'path': rel(TB_F), 'md5': flowmod.md5_of(TB_F)},
              'compile_units': [{'path': u, 'md5': flowmod.md5_of(os.path.join(ROOT, u))}
                                for u in comp['units']]}
        cfg['fingerprint'] = fp
        vopt_name = 'm2_opt'
        worker_dirs = [sandbox]
        if args.jobs > 1:
            worker_dirs = []
            for k in range(1, args.jobs + 1):
                wd = os.path.join(sandbox, 'job%d' % k)
                os.makedirs(wd, exist_ok=True)
                dst = os.path.join(wd, 'work')
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(os.path.join(sandbox, 'work'), dst)
                worker_dirs.append(wd)
        _log(log, '\n[round] runner=%s round=%d cases=%d jobs=%d sandbox=%s'
                  % (runner_id, args.round, len(cases), args.jobs, rel(sandbox)))

        results = [None] * len(cases)
        abort = None
        consec_fatal = 0
        fatal = timeout = 0

        def note_result(i, r):
            """中止判据的**逐例**求值点（jobs=1 严格顺序；jobs>1 在结果回收侧）。"""
            nonlocal abort, consec_fatal, fatal, timeout
            results[i] = r
            if r['status'] == 'FATAL':
                fatal += 1
                consec_fatal += 1
            else:
                consec_fatal = 0
            if r['status'] == 'TIMEOUT':
                timeout += 1
            done = sum(1 for x in results if x is not None)
            if abort:
                return
            if r['status'] == 'TIMEOUT':
                abort = ('%s：单用例 watchdog 超时——%s' % (AB6_LABEL, r['reason']))
            elif consec_fatal >= AB1_CONSEC_FATAL:
                abort = ('AB1：连续 %d 例编译/加载失败（最近：%s——%s）'
                         % (consec_fatal, r['name'], r['reason']))
            elif done >= AB5_MIN_DONE and fatal / float(done) >= AB5_FATAL_RATIO:
                abort = ('AB5：完成 %d 例中 fatal（平台/环境级）%d 例 = %.1f%% ≥ %.0f%%'
                         % (done, fatal, 100.0 * fatal / done, 100.0 * AB5_FATAL_RATIO))
            elif time.time() - t_start > args.batch_budget:
                abort = ('%s：批累计挂钟 %.0fs > --batch-budget %ds（R9：单轮总时长上限）'
                         % (AB6_LABEL, time.time() - t_start, args.batch_budget))

        if args.jobs == 1:
            wd = worker_dirs[0]
            for i, c in enumerate(cases):
                if abort:
                    results[i] = {'name': c['name'], 'status': 'SKIP', 'reason': '批已中止', 'elapsed_s': None}
                    continue
                r = run_case(c, wd, args.case_timeout, args.iss_timeout, log,
                             'case-%d/%d' % (i + 1, len(cases)))
                note_result(i, r)
                _log(log, '[case] %-18s %-8s %s' % (r['name'], r['status'],
                                                    r['reason'] or ('rows=%s mismatch=%s'
                                                                    % (r['rows_rtl'], r['mismatch']))))
                print('[regress] %2d/%d %-18s %s' % (i + 1, len(cases), r['name'],
                                                     r['status'] if r['status'] != 'PASS'
                                                     else 'PASS'))
        else:
            q = queue.Queue()
            for d in worker_dirs:
                q.put(d)

            def task(i_c):
                i, c = i_c
                wd = q.get()
                try:
                    return i, run_case(c, wd, args.case_timeout, args.iss_timeout, log,
                                       'case-%d/%d' % (i + 1, len(cases)))
                finally:
                    q.put(wd)
            with ThreadPoolExecutor(max_workers=args.jobs) as ex:
                futs = [ex.submit(task, (i, c)) for i, c in enumerate(cases)]
                for fu in futs:
                    if abort:
                        fu.cancel()
                        continue
                    try:
                        i, r = fu.result()
                    except Exception as e:                       # noqa: BLE001
                        continue
                    note_result(i, r)
                    _log(log, '[case] %-18s %-8s %s' % (r['name'], r['status'],
                                                        r['reason'] or ''))
            for i, c in enumerate(cases):
                if results[i] is None:
                    results[i] = {'name': c['name'], 'status': 'SKIP', 'reason': '批已中止（在飞用例未回收）',
                                  'elapsed_s': None}

        elapsed = time.time() - t_start
        n_pass = sum(1 for r in results if r and r['status'] == 'PASS')
        n_fail = sum(1 for r in results if r and r['status'] == 'FAIL')
        n_fatal = sum(1 for r in results if r and r['status'] == 'FATAL')
        n_to = sum(1 for r in results if r and r['status'] == 'TIMEOUT')
        n_skip = sum(1 for r in results if r and r['status'] == 'SKIP')
        done = n_pass + n_fail + n_fatal + n_to
        max_case = max([r['elapsed_s'] or 0 for r in results if r]) if results else 0

        # 收尾复算指纹：采集之后**轮内**有没有被改（有即如实落证；不掩盖、不重采成"看起来一致"）
        changed = sorted(x['path'] for x in fp['compile_units']
                         if not os.path.exists(os.path.join(ROOT, x['path']))
                         or flowmod.md5_of(os.path.join(ROOT, x['path'])) != x['md5'])
        for key, path in (('rtl_filelist', RTL_F), ('tb_filelist', TB_F)):
            if flowmod.md5_of(path) != fp[key]['md5']:
                changed.append(fp[key]['path'])
        fp['changed_since_fingerprint'] = sorted(set(changed))
        cfg['finished'] = now_str()
        cfg['elapsed_s'] = round(elapsed, 1)
        cfg['verdict'] = ('ABORTED' if abort else ('PASS' if (n_fail == 0 and n_fatal == 0
                                                             and n_to == 0 and n_skip == 0)
                                                   else 'FAIL'))
        flowmod.save_json(os.path.join(sandbox, 'config.json'), cfg)
        flowmod.save_json(os.path.join(sandbox, 'cases.json'),
                          {'runner_id': runner_id, 'round': args.round, 'verdict': cfg['verdict'],
                           'counts': {'total': len(cases), 'pass': n_pass, 'fail': n_fail,
                                      'fatal': n_fatal, 'timeout': n_to, 'skip': n_skip,
                                      'done': done},
                           'r9': {'case_timeout_s': args.case_timeout,
                                  'batch_budget_s': args.batch_budget,
                                  'watchdog_cycles': WATCHDOG_CYCLES},
                           'r10': {'jobs': args.jobs, 'jobs_cap': MAX_JOBS,
                                   'sandbox': rel(sandbox), 'layout': cfg['layout']},
                           'compile': cfg['compile'],
                           'cases': results})

        lines = []
        lines.append('# VR1 批级回归 summary（机制件产物；消费方：`script/flow.py` 的 `m2-regress` 判据）')
        lines.append('# 生成 %s ｜ runner=%s round=%d ｜ 沙箱 %s（红线 R10 独占）'
                     % (now_str(), runner_id, args.round, rel(sandbox)))
        lines.append('# testlist=%s md5=%s ｜ MANIFEST md5=%s ｜ 用例 %d 条'
                     % (cfg['testlist'], cfg['testlist_md5'][:12], cfg['manifest_md5'][:12],
                        len(cases)))
        lines.append('# 口径：ISS `halt_val=0x1` ＋ RTL `HALT_PASS`（tohost）＋ `trace_compare` '
                     '`mismatch=0`（列 pc,binary,gpr,csr）；不放宽、不豁免（红线 R6/R8）')
        lines.append('# 同配置面＝config.json（换 testlist/jobs/超时/编译集合即换配置）；'
                     '轮间差异见 `sim/run_regress_<head>/round_diff.txt`')
        lines.append('# RTL 版本面（判据 `m2-regress` 的时效校验）：filelist/rtl.f md5=%s ｜ 单元 %d 个'
                     '（逐单元 md5 见 config.json 的 fingerprint）｜ 轮内变更=%s'
                     % (fp['rtl_filelist']['md5'], len(comp['units']),
                        '、'.join(fp['changed_since_fingerprint']) or '无'))
        lines.append('[regress] compile: vlog %d 单元（Errors: 0）｜ vopt Errors: 0 ｜ %s'
                     % (comp['n_compiling'], comp['vopt_cmd']))
        for r in results:
            if r is None:
                continue
            if r['status'] == 'PASS':
                lines.append('PASS %s rows=%s mismatch=%s cyc=%s iss_rows=%s elapsed=%ss'
                             % (r['name'], r['rows_rtl'], r['mismatch'], r['cyc'], r['rows_iss'],
                                r['elapsed_s']))
            else:
                lines.append('%s %s：%s' % (r['status'], r['name'], r['reason'] or '(无原因)'))
        lines.append('[regress] counts: total=%d pass=%d fail=%d timeout=%d fatal=%d skip=%d'
                     % (len(cases), n_pass, n_fail, n_to, n_fatal, n_skip))
        lines.append('[regress] ab: AB1(连续 fatal 阈值)=%d ｜ AB5(≥%d 例且 fatal≥%.0f%%)=%.1f%% '
                     '｜ AB6(单例 watchdog)=%s ｜ max_case=%ss batch_elapsed=%.1fs/预算 %ds'
                     % (AB1_CONSEC_FATAL, AB5_MIN_DONE, 100 * AB5_FATAL_RATIO,
                        100.0 * n_fatal / done if done else 0.0,
                        '命中' if n_to else '未命中', max_case, elapsed, args.batch_budget))
        if abort:
            tail = 'REGRESSION_ABORTED runner=%s %s ｜ 已完成 total=%d pass=%d fail=%d fatal=%d timeout=%d' \
                   % (runner_id, abort, len(cases), n_pass, n_fail, n_fatal, n_to)
        elif n_fail == 0 and n_fatal == 0 and n_to == 0 and n_skip == 0:
            tail = ('REGRESSION_PASS runner=%s total=%d pass=%d fail=0 elapsed=%.1fs new_fail=n/a'
                    '（轮间新增失败数在 `--diff` 的 round_diff.txt 里给，单轮 summary 不猜）'
                    % (runner_id, len(cases), n_pass, elapsed))
        else:
            tail = ('REGRESSION_FAIL runner=%s total=%d pass=%d fail=%d fatal=%d timeout=%d '
                    'elapsed=%.1fs' % (runner_id, len(cases), n_pass, n_fail, n_fatal, n_to, elapsed))
        lines.append(tail)
        with io.open(os.path.join(sandbox, 'summary.txt'), 'w', encoding='utf-8',
                     newline='\n') as f:
            f.write('\n'.join(lines) + '\n')
        _log(log, '\n' + '\n'.join(lines))
        print('\n'.join(lines[-3:]))
        if abort:
            return EXIT_ABORTED
        return EXIT_OK if cfg['verdict'] == 'PASS' else EXIT_FAIL
    except RuntimeError as e:
        _log(log, '[regress] 环境/配置错误（fail-closed）：%s' % e)
        print('[regress] 环境/配置错误（fail-closed）：%s' % e)
        return EXIT_ENV
    finally:
        lock.release()


# --------------------------------------------------------------------------- #
# 轮间差异（第 2 轮相对第 1 轮的新增 FAIL 数 ＋ 同配置机判）
# --------------------------------------------------------------------------- #
def cmd_diff(base, head):
    sb = os.path.join(ROOT, 'sim', 'run_regress_%s' % base)
    sh = os.path.join(ROOT, 'sim', 'run_regress_%s' % head)
    for p, tag in ((sb, base), (sh, head)):
        if not os.path.exists(os.path.join(p, 'cases.json')):
            print('[diff] 缺 %s/cases.json（fail-closed）' % rel(p))
            return EXIT_ENV
    cb = flowmod.load_json(os.path.join(sb, 'cases.json'), default={}) or {}
    ch = flowmod.load_json(os.path.join(sh, 'cases.json'), default={}) or {}
    fb = {r['name'] for r in cb.get('cases', []) if r and r.get('status') == 'FAIL'}
    fh = {r['name'] for r in ch.get('cases', []) if r and r.get('status') == 'FAIL'}
    tb = {r['name'] for r in cb.get('cases', []) if r and r.get('status') == 'TIMEOUT'}
    th = {r['name'] for r in ch.get('cases', []) if r and r.get('status') == 'TIMEOUT'}
    new_fail = sorted(fh - fb)
    lost_fail = sorted(fb - fh)
    same_fail = sorted(fb & fh)
    new_to = sorted(th - tb)
    cfg_b = flowmod.load_json(os.path.join(sb, 'config.json'), default={}) or {}
    cfg_h = flowmod.load_json(os.path.join(sh, 'config.json'), default={}) or {}
    ignore = {'runner_id', 'round', 'sandbox', 'started', 'finished', 'elapsed_s', 'verdict'}
    keys = sorted((set(cfg_b) | set(cfg_h)) - ignore)
    diffs = [k for k in keys if cfg_b.get(k) != cfg_h.get(k)]
    same_cfg = not diffs
    out = os.path.join(sh, 'round_diff.txt')
    lines = [
        '# VR1 回归轮间差异（机制件产物）',
        '# base=%s head=%s ｜ 生成 %s' % (base, head, now_str()),
        '# 口径：FAIL 集合按**用例名**取差（红线 R6：不比对原因文本、不放宽任何判据）',
        '[diff] base: total=%s pass=%s fail=%s timeout=%s fatal=%s'
        % (cb.get('counts', {}).get('total'), cb.get('counts', {}).get('pass'),
           cb.get('counts', {}).get('fail'), cb.get('counts', {}).get('timeout'),
           cb.get('counts', {}).get('fatal')),
        '[diff] head: total=%s pass=%s fail=%s timeout=%s fatal=%s'
        % (ch.get('counts', {}).get('total'), ch.get('counts', {}).get('pass'),
           ch.get('counts', {}).get('fail'), ch.get('counts', {}).get('timeout'),
           ch.get('counts', {}).get('fatal')),
        '[diff] new_fail=%d ｜ lost_fail=%d ｜ same_fail=%d ｜ new_timeout=%d'
        % (len(new_fail), len(lost_fail), len(same_fail), len(new_to)),
        '[diff] new_fail 明细：%s' % (', '.join(new_fail) if new_fail else '(无)'),
        '[diff] same_fail 明细：%s' % (', '.join(same_fail) if same_fail else '(无)'),
        '[diff] same_config=%s ｜ 不一致字段：%s'
        % ('yes' if same_cfg else 'no', ', '.join(diffs) if diffs else '(无)'),
        'REGRESSION_DIFF base=%s head=%s new_fail=%d lost_fail=%d same_fail=%d new_timeout=%d '
        'same_config=%s' % (base, head, len(new_fail), len(lost_fail), len(same_fail),
                            len(new_to), 'yes' if same_cfg else 'no'),
    ]
    with io.open(out, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    print('\n'.join(lines[-4:]))
    ok = (not new_fail) and (not new_to) and same_cfg
    print('[diff] 落盘 %s ｜ 判定：%s' % (rel(out), 'OK' if ok else 'NOT-OK'))
    return EXIT_OK if ok else EXIT_FAIL


def main(argv=None):
    ap = argparse.ArgumentParser(description='VR1 批级回归 runner（M2 exit (b) 机制件）')
    ap.add_argument('--diff', nargs=2, metavar=('BASE', 'HEAD'),
                    help='轮间差异模式：比两轮 FAIL 集合与同配置面，写 `sim/run_regress_<head>/round_diff.txt`')
    ap.add_argument('--runner-id', default='r1', help='runner 标识（沙箱 sim/run_regress_<id>/，红线 R10）')
    ap.add_argument('--round', type=int, default=1, help='轮号（仅记账；沙箱由 --runner-id 决定）')
    ap.add_argument('--testlist', default=DEFAULT_TESTLIST, help='用例清单（默认 run_cmd/rv64ui_testlist.txt）')
    ap.add_argument('--jobs', type=int, default=1, help='并发（默认 1；硬上限 %d，红线 R10）' % MAX_JOBS)
    ap.add_argument('--case-timeout', type=int, default=DEFAULT_CASE_TIMEOUT,
                    help='单用例挂钟上限 s（默认 %d ＝ R9「20 分钟/用例」）' % DEFAULT_CASE_TIMEOUT)
    ap.add_argument('--iss-timeout', type=int, default=DEFAULT_ISS_TIMEOUT, help='ISS 侧挂钟上限 s')
    ap.add_argument('--batch-budget', type=int, default=DEFAULT_BATCH_BUDGET,
                    help='批累计挂钟上限 s（默认 %d ＝ R9「单轮 2 小时」）' % DEFAULT_BATCH_BUDGET)
    ap.add_argument('--limit', type=int, default=0,
                    help='只用前 N 条（**仅机制冒烟**；写进 config 参与同配置比对）')
    args = ap.parse_args(argv)
    if args.diff:
        return cmd_diff(args.diff[0], args.diff[1])
    return cmd_round(args)


if __name__ == '__main__':
    raise SystemExit(main())
