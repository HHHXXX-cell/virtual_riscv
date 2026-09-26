#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""flow_run.py — 确定性步骤 runner（方案 1+2+3 的"快回路"）。
读 plan.json，按序执行 status=pending 且有 cmd 的步骤；每步日志入 sim/run_<id>/run.log。
成功 -> 步骤置 done + 自动记账（flow.py record R）；失败 -> 打一行摘要并停止（把控制权交回主会话/orchestrator）。
停在 status=waiting_human 的步骤之前（需人物理项）。单次最多跑 max_steps_per_run 步。
"""
import json
import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
PLAN = os.path.join(ROOT, 'doc', 'process', 'plan.json')
PY = sys.executable


def load():
    with open(PLAN, 'r', encoding='utf-8') as f:
        return json.load(f)


def save(plan):
    with open(PLAN, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)


def one_line(text):
    for ln in reversed([x.strip() for x in text.splitlines() if x.strip()]):
        return ln[:200]
    return '(no output)'


def record(kind, text):
    subprocess.run([PY, os.path.join(ROOT, 'script', 'flow.py'), 'record', kind, text],
                   cwd=ROOT, stdout=subprocess.DEVNULL)


def main():
    plan = load()
    budget = int(plan.get('max_steps_per_run', 3))
    ran = 0
    for step in plan['steps']:
        st = step.get('status')
        if st == 'waiting_human':
            print('[STOP] 停在需人项 %s：%s' % (step['id'], step['task']))
            break
        if st != 'pending':
            continue
        if not step.get('cmd'):
            print('[SKIP] %s 无 cmd（需 agent 补命令）：%s' % (step['id'], step['task']))
            continue
        if ran >= budget:
            print('[STOP] 达到单次步数上限 %d，让位下一轮' % budget)
            break
        d = os.path.join(ROOT, 'sim', 'run_%s' % step['id'])
        os.makedirs(d, exist_ok=True)
        log = os.path.join(d, 'run.log')
        acc = []
        ok = True
        for argv in step['cmd']:
            p = subprocess.run(argv, cwd=ROOT, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, errors='replace')
            acc.append('$ ' + ' '.join(argv) + '\n' + (p.stdout or ''))
            if p.returncode != 0:
                ok = False
                break
        with open(log, 'w', encoding='utf-8', newline='\n') as f:
            f.write('\n'.join(acc))
        ran += 1
        if ok:
            step['status'] = 'done'
            step['evidence'] = (step.get('evidence', '') + ' | ' if step.get('evidence') else '') + \
                               '2026-09-25 runner OK：' + one_line(acc[-1])
            save(plan)
            record('R', '%s 通过（runner 自动记账）：%s' % (step['id'], one_line(acc[-1])))
            print('[PASS] %s | %s' % (step['id'], one_line(acc[-1])))
        else:
            step['fail_note'] = '2026-09-25 runner FAIL：' + one_line(acc[-1])
            save(plan)
            print('[FAIL] %s | %s' % (step['id'], one_line(acc[-1])))
            print('[STOP] 控制权交回 orchestrator（日志 %s）' % os.path.relpath(log, ROOT))
            return 1
    done = [s['id'] for s in plan['steps'] if s.get('status') == 'done']
    wait = [s['id'] for s in plan['steps'] if s.get('status') == 'waiting_human']
    print('---- flow_run: 本轮执行 %d 步；done=%s；等人类=%s ----' % (ran, done, wait))
    return 0


if __name__ == '__main__':
    sys.exit(main())
