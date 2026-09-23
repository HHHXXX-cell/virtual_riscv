#!/usr/bin/env python3
"""全库路径核查 + 目录骨架自复（ISS-032 的 landable 要求①，也是换机后的一号体检）。

为什么单独成脚本而不是临时跑：
- 上一版本用 `python -c` 内联正则，被 PowerShell 的反斜杠转义吃掉，只匹配到 1 条路径就报
  「0 缺失」——**假阴性比没测更危险**，它会让人以为路径都活着。故固化为文件 + 自校验。
- AGENTS.md §2 的目录约定、§1 的锚点路径都属"声明"，声明必须可机判，否则就是 ISS-021 的老毛病。

用法：
    python script/path_audit.py            # 只报告
    python script/path_audit.py --fix      # 额外重建丢失的空骨架目录
    python script/path_audit.py --json     # 机器可读输出（供 gate.py 调用）

退出码：0 = 无缺失；1 = 有缺失路径或骨架目录缺失且未 --fix。
"""
from __future__ import annotations

import io
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 被扫描的"声明源"：这些文件里的绝对路径与目录约定都算承诺
DECL_FILES = [
    "AGENTS.md", "README.md",
    "doc/项目开发流程.md", "doc/AI角色与职责.md",
    "doc/环境搭建.md", "doc/交接说明.md",
    "run_cmd/AutoQueue.yaml",
]

# 绝对路径：Windows 盘符开头，允许中文；到空白/反引号/引号/中文标点/右括号为止
ABS_RE = re.compile(r"[A-Za-z]:\\\\?(?:[^\s`'\"|,，。；：）)、]+\\)*[^\s`'\"|,，。；：）)、]*")

# AGENTS.md §2 声明的项目内骨架目录（换机/压缩拷贝会丢空目录，必须能自复）
SKELETON = [
    "doc/spec", "doc/verify", "doc/process", "doc/design", "doc/review", "debug",
    "rtl/vr1/frontend", "rtl/vr1/rename", "rtl/vr1/issue", "rtl/vr1/exu",
    "rtl/vr1/lsu", "rtl/vr1/mmu", "rtl/vr1/cache", "rtl/vr1/ctrl",
    "rtl/vr1/core", "rtl/vr1/include",
    "tb/vr1_uvm", "tb/unit",
    "iss/vriss", "iss/tools", "iss/tests", "iss/tests/probes",
    "sw/env", "sw/tests", "filelist", "sim/covdb", "script/tmp", "run_cmd",
]

STRIP_TAIL = "。，；、）)》”’|"

# 假阳性过滤（实测两类）：
#  1) 含通配符/占位符的是举例写法（如 `参考书\*.pdf`），不是真路径；
#  2) 代码栏内的盘符路径是样本（如 `E:\kb\IC验证知识库` 全局替换示例）。
PLACEHOLDER = ("*", "?", "<", ">", "…")


def strip_code_fences(text: str) -> str:
    """去除 ``` 围栏内容：其中的路径都是示例，不是承诺。"""
    out, skip = [], False
    for line in text.splitlines(keepends=True):
        if line.lstrip().startswith("```"):
            skip = not skip
            continue
        if not skip:
            out.append(line)
    return "".join(out)


def norm(p: str) -> str:
    """清洗抓出来的路径：去尾部标点、折叠重复反斜杠。"""
    p = p.strip().rstrip(STRIP_TAIL)
    while "\\\\" in p:
        p = p.replace("\\\\", "\\")
    return p


def declared_paths() -> tuple[set[str], int]:
    """返回 (抓到的绝对路径集合, 扫描到的候选 token 数)。token 数用于自检抓取是否失效。"""
    found: set[str] = set()
    tokens = 0
    for rel in DECL_FILES:
        f = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(f):
            continue
        text = strip_code_fences(io.open(f, encoding="utf-8", errors="replace").read())
        for m in ABS_RE.finditer(text):
            tokens += 1
            p = norm(m.group(0))
            # 只要盘符开头的绝对路径；相对片段（如 _tools\xxx）由 KB 根拼接补测
            if re.match(r"^[A-Za-z]:\\", p) and len(p) > 3 \
                    and not any(ch in p for ch in PLACEHOLDER):
                found.add(p)
    return found, tokens


def kb_relative_paths() -> set[str]:
    r"""抓 `_tools\...`《知识库》相对引用，按 KB 根补全后测（这类最容易在换机时断）。"""
    kb = r"D:\IC验证知识库"
    out: set[str] = set()
    pat = re.compile(r"(_tools\\[^\s`'\"|,，。；：）)、]+|参考书\\[^\s`'\"|,，。；：）)、]+)")
    for rel in DECL_FILES:
        f = os.path.join(ROOT, rel.replace("/", os.sep))
        if not os.path.exists(f):
            continue
        body = strip_code_fences(io.open(f, encoding="utf-8", errors="replace").read())
        for m in pat.finditer(body):
            cand = os.path.join(kb, norm(m.group(1)))
            if not any(ch in cand for ch in PLACEHOLDER):
                out.add(cand)
    return out


def skeleton_state(fix: bool) -> list[tuple[str, bool, bool, bool]]:
    """逐目录返回 (相对路径, 修复前是否存在, 是否新建, 是否有占位文件)。

    占位判据：目录内**一个文件都没有**则视为会丢（git/GitHub 不传递空目录，ISS-035/036）。
    占位文件可以是 `.gitkeep`、`README.md` 或任何普通文件。
    """
    rows = []
    for rel in SKELETON:
        p = os.path.join(ROOT, rel.replace("/", os.sep))
        existed = os.path.isdir(p)
        created = False
        if not existed and fix:
            os.makedirs(p, exist_ok=True)
            created = True
        has_ph = existed or created
        if has_ph and not os.listdir(p):
            if fix:
                io.open(os.path.join(p, ".gitkeep"), "w", encoding="utf-8", newline="").write(
                    "# git/GitHub 不收空目录，本文件唯一作用是占位（见 doc/process/00 ISS-036）。\n")
                has_ph = True
            else:
                has_ph = False
        rows.append((rel, existed, created, has_ph))
    return rows


def main(argv: list[str]) -> int:
    fix = "--fix" in argv
    as_json = "--json" in argv

    abs_paths, tokens = declared_paths()
    rel_paths = kb_relative_paths()
    if tokens < 20:
        # 抓取自检：历史上这里曾因转义问题只抓到 1 条却报“0 缺失”
        print(f"[WARN] 仅扫到 {tokens} 个候选 token，抓取很可能失效，本结果不可信", file=sys.stderr)

    missing = sorted(p for p in sorted(abs_paths | rel_paths) if not os.path.exists(p))
    rows = skeleton_state(fix)
    miss_skel = [r for r in rows if not r[1] and not r[2]]
    no_ph = [r for r in rows if not r[3]]
    
    if as_json:
        print(json.dumps({
            "scanned_tokens": tokens,
            "declared_total": len(abs_paths | rel_paths),
            "missing_paths": missing,
            "skeleton_missing": [m[0] for m in miss_skel],
            "skeleton_created": [r[0] for r in rows if r[2]],
            "skeleton_no_placeholder": [m[0] for m in no_ph],
        }, ensure_ascii=False, indent=2))
    else:
        print(f"=== 路径核查（声明源 {len(DECL_FILES)} 份，候选 token {tokens}，去重后路径 {len(abs_paths | rel_paths)}）===")
        if missing:
            for m in missing:
                print("  MISSING ", m)
        else:
            print("  全部声明路径均存在")
        print("=== 目录骨架 ===")
        for rel, existed, created, has_ph in rows:
            if not existed:
                print(f"  {'CREATED' if created else 'MISSING '}  {rel}")
        for rel, _e, _c, has_ph in no_ph:
            print(f"  NO-PLACEHOLDER  {rel}（空目录无占位文件，git 不会传递）")
        if not any(not e for _, e, _, _ in rows) and not no_ph:
            print("  骨架完整且均有占位文件")
    
    fail = bool(missing) or bool(miss_skel) or bool(no_ph)
    print(f"---- 缺失路径 {len(missing)} 项 / 骨架缺失 {len(miss_skel)} 项 / 无占位 {len(no_ph)} 项 ----")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
