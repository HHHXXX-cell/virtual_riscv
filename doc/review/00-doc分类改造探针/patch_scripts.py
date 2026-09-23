# -*- coding: utf-8 -*-
"""gate.py / path_audit.py 的 doc 分类改造同步（每个锚点必须命中且仅命中一次，否则整体不落盘）。"""
import io, sys

ROOT = r'D:\virtual_riscv'


def patch(rel, pairs):
    p = ROOT + '\\' + rel.replace('/', '\\')
    t = io.open(p, encoding='utf-8').read()
    for old, new in pairs:
        n = t.count(old)
        if n != 1:
            print('ABORT %s: 锚点命中 %d 次（应为 1）: %r' % (rel, n, old[:70]))
            return False
        t = t.replace(old, new)
    with io.open(p, 'w', encoding='utf-8', newline='') as f:
        f.write(t)
    print('OK  %s（%d 处锚点全部唯一命中）' % (rel, len(pairs)))
    return True


GATE = [
    # 判据常量
    ("LEDGER = os.path.join(ROOT, 'doc', '00-问题记录.md')\nBOARD = os.path.join(ROOT, 'doc', '04-验证进度.md')",
     "LEDGER = os.path.join(ROOT, 'doc', 'process', '00-问题记录.md')\n"
     "BOARD = os.path.join(ROOT, 'doc', 'verify', '04-验证进度.md')"),
    ("# 坏词表：每条必须能指到一次真实事故（doc/00 ISS-026 / ISS-033）",
     "# 坏词表：每条必须能指到一次真实事故（doc/process/00 ISS-026 / ISS-033）"),
    ("    p = os.path.join(ROOT, 'doc', '05-回归记录.md')",
     "    p = os.path.join(ROOT, 'doc', 'verify', '05-回归记录.md')"),
    ('    """doc/05 回归记录不得重号',
     '    """doc/verify/05 回归记录不得重号'),
    ("# 评审记录/探针）。两条理由：① 记录类文本（`doc/00`/`doc/04`/`doc/05`）是叙事件，其中",
     "# 评审记录/探针）。两条理由：① 记录类文本（`doc/process/00`/`doc/verify/0[45]`）是叙事件，其中"),
    ("# 每轮必改件（doc/00|04|05、HANDOFF、队列、评审记录）不入长基线——否则每轮必报 MODIFIED，",
     "# 每轮必改件（doc/process/00、doc/verify/04|05、HANDOFF、队列、评审记录）不入长基线——否则每轮必报 MODIFIED，"),
    ("                             r'|^doc/0[045]-|(^|/)评审记录\\.md$')",
     "                             r'|^doc/(?:process/00|verify/0[45])-|(^|/)评审记录\\.md$')"),
    ("'只折\"已进复核面\"的改动集；执行者＝R8；独立提交＋doc/05 留痕（旧→新指纹、折入集出处）；'",
     "'只折\"已进复核面\"的改动集；执行者＝R8；独立提交＋doc/verify/05 留痕（旧→新指纹、折入集出处）；'"),
    ("        print('--refresh 必须随 --reason（折入集出处：如 doc/05:R-0xx 行 / 提交号 / 评审结论）；'",
     "        print('--refresh 必须随 --reason（折入集出处：如 doc/verify/05:R-0xx 行 / 提交号 / 评审结论）；'"),
    ("           'exclude': '每轮必改件不入长基线：doc/00|04|05-*、HANDOFF.md、AutoQueue.yaml、*评审记录*.md',",
     "           'exclude': '每轮必改件不入长基线：doc/process/00、doc/verify/04|05、HANDOFF.md、AutoQueue.yaml、*评审记录*.md',"),
    ("        print('  旧→新指纹：%s → %s（须独立提交并把本行贴进 doc/05）'",
     "        print('  旧→新指纹：%s → %s（须独立提交并把本行贴进 doc/verify/05）'"),
    ("        print('队列为空：领队先按 doc/项目开发流程.md §10 与 doc/04 播种。')",
     "        print('队列为空：领队先按 doc/项目开发流程.md §10 与 doc/verify/04 播种。')"),
    ("        print('队列已清空。下一步不是\"项目完成\"：请领队汇总 doc/07/08/09 与台账闭环情呈 R0 做阶段出口判定。')",
     "        print('队列已清空。下一步不是\"项目完成\"：请领队汇总 doc/verify/07/08/09 与台账闭环情呈 R0 做阶段出口判定。')"),
    # 扫描面：doc/ 递归（跳过冻结的评审探针），否则新子目录掉出 check_md/check_text 判据面
    ("""    files = [os.path.join(ROOT, 'doc', f) for f in sorted(os.listdir(os.path.join(ROOT, 'doc')))
             if f.endswith('.md')]
    files += [os.path.join(ROOT, f) for f in ('AGENTS.md', 'README.md')]
    files += role_agent_files()""",
     """    files = []
    for dp, dns, fns in os.walk(os.path.join(ROOT, 'doc')):
        dns[:] = [d for d in dns if not d.endswith('评审探针')]   # 探针＝冻结证据，不入判据面
        files += [os.path.join(dp, f) for f in sorted(fns) if f.endswith('.md')]
    files.sort()
    files += [os.path.join(ROOT, f) for f in ('AGENTS.md', 'README.md')]
    files += role_agent_files()"""),
]

PATH_AUDIT = [
    # 骨架目录（新三类 + 预留的 design）
    ('    "doc/spec", "debug",',
     '    "doc/spec", "doc/verify", "doc/process", "doc/design", "debug",'),
    ("                    \"# git/GitHub 不收空目录，本文件唯一作用是占位（见 doc/00 ISS-036）。\\n\")",
     "                    \"# git/GitHub 不收空目录，本文件唯一作用是占位（见 doc/process/00 ISS-036）。\\n\")"),
]

ok = patch('script/gate.py', GATE) and patch('script/path_audit.py', PATH_AUDIT)
sys.exit(0 if ok else 1)
