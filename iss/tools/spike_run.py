#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`iss/tools/spike_run.py` — Spike（第二 ISS）调用封装：把「每次手写必踩的两个坑」固化下来。

为什么需要它（三条本机硬事实，锚＝`state/env.json` 的 `spike` 项 / `ISS-123` / `R-235`）
------------------------------------------------------------------------------------
1. **Spike 自生成的 DTB 在本机不可用**：`riscv/dts.cc:109 dtc_compile()` 走 `fork()`＋`pipe()`
   调外部 `dtc`，MSYS 的 fork 仿真下产物缺 `riscv,isa` ⇒ 必须显式带 `--dtb=<file>`。
   本脚本自动生成并缓存 DTB（`--dump-dts` → 去 banner → `dtc -I dts -O dtb`），缓存键＝ISA 串。
2. **Spike 跑在 MSYS2 的 msys 环境**（Cygwin-POSIX 层；它要 mmap/termios/fork）——Windows 侧直接
   调用会缺 `msys-2.0.dll`。本脚本统一经 `D:\\msys64\\usr\\bin\\env.exe MSYSTEM=MSYS bash -lc` 进入。
3. **`--isa` 必须显式给**（Spike 自带默认串与 `doc/spec/00` §2 的一期串不同）⇒ 默认取
   `spec/00` §2 一期串 `rv64imac_zicsr_zifencei`（单一真源，不在本脚本另造值）。

三条限制（`ISS-123`，本项目用不到，仅备查）：禁 `--extension`（`libcustomext.so` 未链）、
socket 调试口 `-s` 未编入、必须 `--dtb=`。

子命令
------
  check                   环境探针：spike 可执行 ＋ `--help` 命中 `log-commits`（可复核锚点）
  run <elf>               固化调用：备 DTB → spike `--isa/--dtb/--log-commits/-l` → 落 log（可选转 CSV）
  to-csv <log> <csv>      调 riscv-dv 的 `spike_log_to_trace_csv.py` 转标准 trace CSV（与 `vriss` 同列序）

**两份 oracle（`--preset`）**——存储器映射必须与项目一致才能逐条比 `pc`：
  · `project`（默认）＝ `D:/tools/riscv-isa-sim-vr1/build_vr1/spike`：把 `riscv/platform.h` 的
    `DRAM_BASE`→`0x1000`、`DEFAULT_RSTVEC`→`0x9000_0000`（boot ROM 让位）后重建的那份，
    配 `-m0x1000:0x4000,0x20000000:0x1000,0x40000000:0x10000` ⇒ **同一份 ELF 喂两边**，
    Spike 的 `pc` 与 `vriss`/RTL 直接同址可比。
    ⚠ **这是"改过的 oracle，非原版 Spike"**（ISS-129 R0 2026-09-26 裁定②）：改动面固化成
    `iss/tools/patches/spike-vr1-platform-map.patch`，身份纳入版本指纹 `iss/tools/spike_oracles.json`；
    本脚本每次 check/run **逐次核**二进制 md5＋补丁 md5＋改后源码 md5，不一致即**拒跑**。
    两侧不一致时**先核补丁本身**（口径见 `doc/verify/02` §8）。
  · `upstream` ＝ 上游映射那份（DRAM `0x8000_0000`，boot ROM `0x1000`）：**跑不了项目 ELF**
    （实测两条失败：带项目 `-m` ⇒ `devices … overlap`；不带 ⇒ `Memory address 0x1000 is invalid`）
    ——保留它只为留证与对照。

用法
----
  python iss/tools/spike_run.py check
  python iss/tools/spike_run.py run sim/image/rv64ui/rv64ui-p-simple.elf \
      --log sim/run_spike/spike.log --csv sim/run_spike/spike.csv
  python iss/tools/spike_run.py run prog.elf --log x.log -- --priv=m      # `--` 之后原样透传给 spike

口径
----
- 只跑 ELF：Spike 按 ELF 段装载（本项目链接脚本 `sw/env/link.ld`：代码窗 `0x1000`、`tohost` `0x4000_0010`）。
- 停机：程序向 `tohost` 写 1（riscv-tests 约定）⇒ Spike 退出码 0。
- **不开 `--misaligned`**（`spec/00` §2 口径统一，ISS-010）：一期不支持非对齐访存，两侧口径必须一致。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORACLE_MANIFEST = ROOT / "iss" / "tools" / "spike_oracles.json"   # 版本指纹（ISS-129 R0 2026-09-26 裁定②）

# ---- 单一真源引用（改这些值前先看 state/env.json 与 doc/spec/00 §2）----
ISA_DEFAULT = "rv64imac_zicsr_zifencei"          # doc/spec/00 §2 一期串
MSYS2_ROOT = Path(r"D:\msys64")                   # state/env.json: msys2_host（R-235）
SPIKE_MSYS_DEFAULT = "/d/tools/riscv-isa-sim-master/build_msys/spike"  # state/env.json: spike（R-235）
# 项目映射版 Spike（另一份源码副本＋platform.h 两处常量补丁；见 --preset 说明与 ISS-124 待裁）
SPIKE_VR1_MSYS = "/d/tools/riscv-isa-sim-vr1/build_vr1/spike"
# 项目存储器映射（与 sw/env/link.ld 对齐）：代码窗 0x1000 起 16 KB／signature 窗／数据窗
# 注：Spike 自带 CLINT(0x2000000) 等设备与「默认 2048 MB DRAM」重叠，故必须用 -m 显式给区域。
PROJECT_MEM_ARGS = "-m0x1000:0x4000,0x20000000:0x1000,0x40000000:0x10000"
CONVERTER_DEFAULT = Path(r"D:\IC验证知识库\_tools\riscv-dv-master\scripts\spike_log_to_trace_csv.py")
DTB_CACHE_DIR = ROOT / "sim" / "spike"            # 生成件，可清理（不属签核证据保护区 sim/covdb）
PRESETS = {                                       # preset → (spike, 内存区域参数)
    "project":  (SPIKE_VR1_MSYS, PROJECT_MEM_ARGS),
    "upstream": (SPIKE_MSYS_DEFAULT, ""),
}
# Spike commit 行：`core   0: 3 0x<pc> (0x<bin>) [xN 0xVAL] [mem 0xA 0xV] [csr 0xA 0xV]`
COMMIT_RE = re.compile(r"^core\s+\d+:\s+(?P<pri>\d)\s+0x(?P<pc>[0-9a-f]+)\s+"
                       r"\(0x(?P<bin>[0-9a-fA-F]+)\)(?P<rest>.*)$")
XWR_RE = re.compile(r"\bx(?P<idx>\d+)\s+0x(?P<val>[0-9a-f]+)")
# CSR 写：Spike 对**有名字的 CSR** 打印老式名 `c<十进制号>_<名>`（如 `c773_mtvec` ＝ 0x305），
# 对无名号才打印 `csr 0x<addr>`。两种都要收（2026-09-26 实测：漏了前者会把 mtvec 写漏成空）。
CSRWR_RE = re.compile(r"(?:\bcsr\s+0x(?P<addr>[0-9a-f]+)"
                      r"|\bc(?P<num>\d+)_(?P<cname>[A-Za-z0-9_]+))\s+0x(?P<val>[0-9a-f]+)")
MEMW_RE = re.compile(r"\bmem\s+0x(?P<addr>[0-9a-f]+)\s+0x(?P<val>[0-9a-f]+)")
# trace 两端裁切的锚点（规格单一真源，不在本脚本另造值）
ENTRY_DEFAULT = 0x1000          # doc/spec/00 §4.1 `RESET_PC`（＝ sw/env/link.ld 的 `_start`）
TOHOST_DEFAULT = 0x40000010     # G1-I 清单 §1.1 第 8 条：停机口径＝向 tohost 写 1


def win_to_msys(path: str | Path) -> str:
    """`D:\\a\\b` → `/d/a/b`（MSYS2 路径；本机项目路径无空格）。"""
    p = Path(path).resolve()
    drive = p.drive.rstrip(":").lower()
    return "/" + drive + p.as_posix()[len(p.drive):] if p.drive else p.as_posix()


def _run_bash(cmd: str, timeout: int = 600) -> subprocess.CompletedProcess:
    """经 MSYS2 的 msys 环境跑一条 bash 命令（Spike 只能在此环境运行）。"""
    env_exe = MSYS2_ROOT / "usr" / "bin" / "env.exe"
    bash_exe = MSYS2_ROOT / "usr" / "bin" / "bash.exe"
    if not env_exe.exists() or not bash_exe.exists():
        raise SystemExit("[spike_run] FAIL：找不到 %s（MSYS2 未装或路径变；见 doc/环境搭建.md §1）" % env_exe)
    return subprocess.run([str(env_exe), "MSYSTEM=MSYS", str(bash_exe), "-lc", cmd],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def ensure_dtb(spike: str, isa: str, elf: Path, dtb: Path | None = None,
               force: bool = False, mem_args: str = "") -> Path:
    """生成/复用 DTB（见文件头理由 1）。缓存键＝ISA ＋ spike 名 ＋ 内存区域（不同 map 产不同 DTB）。"""
    key = "%s-%s-%s" % (re.sub(r"[^\w.-]", "_", isa), Path(spike).name or "spike",
                        re.sub(r"[^\w.-]", "_", mem_args) or "default")
    target = dtb or (DTB_CACHE_DIR / ("spike-dtb-%s.dtb" % key))
    if target.exists() and not force:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    dts = target.with_suffix(".dts")
    cmd = ("set -e; %s --isa=%s %s --dump-dts %s | sed -n '/^\\/dts-v1\\/;/,$p' > %s; "
           "dtc -I dts -O dtb -o %s %s >/dev/null 2>&1; rm -f %s") % (
        spike, isa, mem_args, win_to_msys(elf), win_to_msys(dts), win_to_msys(target),
        win_to_msys(dts), win_to_msys(dts))
    r = _run_bash(cmd)
    if r.returncode != 0 or not target.exists():
        raise SystemExit("[spike_run] FAIL：DTB 生成失败（见 ISS-123②）rc=%d\n%s%s"
                         % (r.returncode, r.stdout, r.stderr))
    print("[spike_run] DTB 生成 %s（isa=%s，源 ELF=%s）" % (target, isa, elf.name))
    return target


def _resolve_target(args: argparse.Namespace) -> tuple[str, str]:
    """preset → (spike, 内存区域参数)；显式 `--spike`/`--mem-args` 覆盖 preset。"""
    spike, mem = PRESETS.get(args.preset, PRESETS["project"])
    if args.spike:
        spike = args.spike
    if args.mem_args is not None:
        mem = args.mem_args
    return spike, mem


def _md5_file(p: Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _win_exe(spike_msys: str) -> Path:
    """MSYS 写法 `/d/tools/x/spike` → Windows 路径（MSYS 调可执行件时省略 `.exe`，两个名字都试）。"""
    s = str(spike_msys).replace("\\", "/")
    m = re.match(r"^/([A-Za-z])/(.*)$", s)
    base = (m.group(1).upper() + ":\\" + m.group(2).replace("/", "\\")) if m else s
    for c in (Path(base), Path(base + ".exe")):
        if c.exists():
            return c
    return Path(base + ".exe")


def oracle_identity(preset: str, spike_msys: str | None = None) -> str:
    """核 oracle **版本指纹**并给出身份串（ISS-129 R0 2026-09-26 裁定②；fail-closed）。

    指纹件＝`iss/tools/spike_oracles.json`。逐条核：清单在／可解析 ⇒ 该 preset 条目在 ⇒ 二进制在且
    md5 == 清单 ⇒ 补丁件（`patch.path`）md5 == 清单 ⇒ 改后源码（`platform_h.path`）md5 == 清单。
    任一不成立 ⇒ `raise SystemExit`（**拒跑**，并把期望/实际 md5 亮出——"两侧不一致先核补丁本身"）。
    **为什么每次核**：project preset 是"改过的 oracle，非原版"，其改动面必须与受版本控制的补丁件
    逐字对应；改了补丁/重建却不更新指纹，这里就会红。
    """
    if not ORACLE_MANIFEST.exists():
        raise SystemExit("[spike_run] FAIL：缺版本指纹 %s（ISS-129 R0 2026-09-26 裁定②；fail-closed）"
                         % ORACLE_MANIFEST)
    try:
        man = json.loads(ORACLE_MANIFEST.read_text(encoding="utf-8"))
    except Exception as e:                                            # noqa: BLE001
        raise SystemExit("[spike_run] FAIL：%s 不可解析：%s（fail-closed）" % (ORACLE_MANIFEST, e))
    o = ((man.get("oracles") or {}).get(preset)) or {}
    if not o:
        raise SystemExit("[spike_run] FAIL：指纹 %s 无 preset `%s` 条目（fail-closed）"
                         % (ORACLE_MANIFEST, preset))
    bad = []
    tgt = _win_exe(spike_msys or PRESETS[preset][0])
    if not tgt.exists():
        bad.append('二进制不在：%s' % tgt)
    elif o.get("spike_md5") and _md5_file(tgt) != o["spike_md5"]:
        bad.append('二进制 md5 现盘 %s ≠ 指纹 %s（%s）' % (_md5_file(tgt)[:16], o["spike_md5"][:16], tgt))
    if o.get("patched"):
        pp = ROOT / (o.get("patch") or {}).get("path", "")
        if not pp.exists():
            bad.append('补丁件不在：%s' % pp)
        elif (o.get("patch") or {}).get("md5") and _md5_file(pp) != o["patch"]["md5"]:
            bad.append('补丁件 md5 现盘 %s ≠ 指纹 %s' % (_md5_file(pp)[:16], o["patch"]["md5"][:16]))
    ph = o.get("platform_h") or {}
    if ph.get("path"):
        p = Path(ph["path"])
        if not p.exists():
            bad.append('源码不在：%s' % p)
        elif ph.get("md5") and _md5_file(p) != ph["md5"]:
            bad.append('`riscv/platform.h` md5 现盘 %s ≠ 指纹 %s（%s）'
                       % (_md5_file(p)[:16], ph["md5"][:16], p))
    if bad:
        raise SystemExit('[spike_run] FAIL：oracle 版本指纹不符（fail-closed；ISS-129 口径＝先核补丁本身）：'
                         '%s\n    指纹件 %s ｜ 复核后请更新指纹或重建 oracle（步骤见 '
                         'iss/tools/patches/spike-vr1-platform-map.patch 头）' % ('；'.join(bad), ORACLE_MANIFEST))
    c = o.get("constants") or {}
    if o.get("patched"):
        ch = '／'.join('%s %s→%s' % (x['name'], x['from'], x['to']) for x in (o.get("constants_changed") or []))
        return ('preset=%s（**改过的 oracle，非原版 Spike**：riscv/platform.h %s；patch md5=%s；'
                'spike md5=%s）' % (preset, ch or '(?)', ((o.get('patch') or {}).get('md5') or '?')[:8],
                                    (o.get("spike_md5") or "?")[:8]))
    return ('preset=%s（原版 Spike 未改：DEFAULT_RSTVEC %s／DRAM_BASE %s；仅留证/对照——跑不了项目 ELF；'
            'spike md5=%s）' % (preset, c.get("DEFAULT_RSTVEC", "?"), c.get("DRAM_BASE", "?"),
                                (o.get("spike_md5") or "?")[:8]))


def cmd_check(args: argparse.Namespace) -> int:
    spike, mem = _resolve_target(args)
    ident = oracle_identity(args.preset, spike)
    r = _run_bash("%s --help 2>&1 | grep -i log-commits" % spike)
    hit = r.returncode == 0 and r.stdout.strip()
    print("[spike_run] check %s" % ident)
    print("[spike_run] check log-commits: %s" % ("PASS ｜ %s" % hit.strip() if hit else "FAIL"))
    return 0 if hit else 1


def cmd_run(args: argparse.Namespace) -> int:
    elf = Path(args.elf)
    if not elf.exists():
        raise SystemExit("[spike_run] FAIL：找不到 ELF %s（Spike 按 ELF 装载；.hex 请先经 sw/tests 构建）" % elf)
    spike, mem = _resolve_target(args)
    ident = oracle_identity(args.preset, spike)
    dtb = ensure_dtb(spike, args.isa, elf, Path(args.dtb) if args.dtb else None,
                     args.force_dtb, mem)
    log = Path(args.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    extra = " ".join(args.extra or [])
    cmd = ("%s --isa=%s %s --dtb=%s -l --log=%s --log-commits %s %s; echo __SPIKE_RC=$?"
           % (spike, args.isa, mem, win_to_msys(dtb), win_to_msys(log), win_to_msys(elf), extra))
    print("[spike_run] oracle %s mem='%s'" % (ident, mem or "(默认)"))
    r = _run_bash(cmd, timeout=args.timeout)
    m = re.search(r"__SPIKE_RC=(\d+)", r.stdout or "")
    rc = int(m.group(1)) if m else r.returncode
    commits = 0
    if log.exists():
        commits = sum(1 for line in log.open(encoding="utf-8", errors="replace")
                      if line.startswith("core"))
    print("[spike_run] run rc=%d commits=%d isa=%s log=%s" % (rc, commits, args.isa, log))
    if rc != 0:
        return _fail_with_diagnosis(rc, r, log)
    if commits == 0:
        return _fail_with_diagnosis(999, r, log, extra="log 里 0 条 commit 行（--log-commits 未生效？）")
    if args.csv:
        out = Path(args.csv)
        n, skipped, halted = _convert_log(log, out, args.entry, args.tohost)
        print("[spike_run] to-csv（本机解析，与 vriss 同格式）%s → %s 行数=%d"
              "（跳过 boot ROM 前导 %d 行；命中 tohost 停机写=%s）" % (log, out, n, skipped, halted))
        return 0 if (n and halted) else 1
    return 0


# 已知失败模式 → 可执行指引（fail-closed：不猜、不静默，把出路写清楚）
_DIAGNOSIS = [
    ("Access exception occurred while loading payload",
     "**存储器映射不匹配**（本机 Spike 的编译期常量 `riscv/platform.h`：`DRAM_BASE=0x8000_0000`、\n"
     "    `DEFAULT_RSTVEC=0x1000` 处是 boot ROM）——而本项目 ELF 由 `sw/env/link.ld` 链接在\n"
     "    代码窗 `0x1000`（`spec/00` §4.1 `RESET_PC`）、`tohost` `0x4000_0010`。两条出路：\n"
     "      (a) 用项目映射重建 Spike（改 `DRAM_BASE`/`DEFAULT_RSTVEC` 后另编一份 spike-vr1）\n"
     "          ⇒ 保住「一份镜像喂两边」，但 oracle 的映射被改（须登记，属口径类）；\n"
     "      (b) 用上游 `sw/tests/riscv-tests/env/p/link.ld`（代码 `0x8000_0000`／`tohost` `0x8000_1000`）\n"
     "          另出一份 Spike 版 ELF ⇒ 地址不同，`pc` 列不可直接比对（需归一化＝放宽，红线 R6）。"),
    ("invalid or missing 'riscv,isa'",
     "DTB 不能用：Spike 自生成 DTB 在本机失效（`dts.cc` 的 fork+pipe 调 dtc），必须带 `--dtb=<file>`\n"
     "    （本脚本默认自动生成并缓存到 `sim/spike/`；若缓存件坏了加 `--force-dtb`）。见 ISS-123②。"),
    ("is not a valid ISA", "ISA 串不被本机 Spike 接受：核对 `--isa`（默认取 `spec/00` §2 一期串）。"),
]


def _fail_with_diagnosis(rc: int, r: subprocess.CompletedProcess, log: Path,
                         extra: str | None = None) -> int:
    """失败时把 stderr 与 log 尾部一并亮出，命中已知模式则给可执行指引（不吞错）。"""
    blob = "%s\n%s" % (r.stderr or "", r.stdout or "")
    print("[spike_run] FAIL rc=%d%s" % (rc, ("（%s）" % extra) if extra else ""))
    tail = [ln for ln in blob.strip().splitlines() if ln and not ln.startswith("__SPIKE_RC")]
    if tail:
        print("[spike_run] spike stderr/stdout 尾部：")
        for ln in tail[-4:]:
            print("    " + ln)
    if log.exists() and log.stat().st_size:
        lines = log.open(encoding="utf-8", errors="replace").read().splitlines()
        if lines:
            print("[spike_run] log 尾部：%s" % lines[-1][:160])
    for pat, hint in _DIAGNOSIS:
        if pat in blob:
            print("[spike_run] 诊断：%s" % hint)
            break
    return rc if 0 < rc < 256 else 1



def cmd_to_csv(args: argparse.Namespace) -> int:
    """Spike commit log → 项目标准 trace CSV。

    默认走**本机解析**：复用 `vriss.trace` 的 `RetireRecord`/`TraceWriter` ⇒ 与 golden ISS 侧
    同列序（`TRACE_CSV_FIELDS`）同格式（`gpr` 用 ABI 名、`csr` 取写后新值），保证可直接 `trace_compare`。
    为什么不用 riscv-dv 的 `spike_log_to_trace_csv.py`（`--riscv-dv` 仍保留）：
    它的 `read_spike_trace()` **硬编码假设 Spike 的 trampoline 在 `0x1000` 并丢弃到 `0x1010` 的指令**；
    本机 `--preset project` 把 boot ROM 挪到了 `0x9000_0000`、程序正好落在 `0x1000` 起
    ⇒ 它会把真程序的前几条当 trampoline 丢掉，实测解析出 **0 条**（2026-09-26）。
    """
    if getattr(args, "riscv_dv", False):
        return _to_csv_riscv_dv(args)
    log, out = Path(args.log), Path(args.csv)
    if not log.exists():
        raise SystemExit("[spike_run] FAIL：找不到 log %s" % log)
    n, skipped, halted = _convert_log(log, out, args.entry, args.tohost)
    print("[spike_run] to-csv（本机解析，与 vriss 同格式）%s → %s 行数=%d"
          "（跳过 boot ROM 前导 %d 行；命中 tohost 停机写=%s）" % (log, out, n, skipped, halted))
    if not n:
        print("[spike_run] FAIL：0 条 commit 行被解析（log 是否用 --log-commits 产出？）")
        return 1
    if not halted:
        print("[spike_run] FAIL：未命中 tohost 停机写（地址 0x%x）——程序未停机或口径不符，"
              "trace 会被停机后自旋噪声污染" % args.tohost)
        return 1
    return 0


def _convert_log(log: Path, out: Path, entry: int = ENTRY_DEFAULT,
                 tohost: int = TOHOST_DEFAULT) -> tuple[int, int, bool]:
    """解析 Spike commit 行 → `vriss.trace.TraceWriter` 行（同格式同列序）。

    **两端裁切（确定性规则，锚＝规格而非 Spike 内部）**：
      · 起点：跳过 `pc != entry` 的前导行——本机 project-map Spike 的 boot ROM（`0x9000_0000` 起）
        是 **oracle 自有产物**，不属被测镜像（`sw/env/link.ld` 的 `_start` = `0x1000`，
        即 `spec/00` §4.1 `RESET_PC`）。
      · 终点：写到 `tohost`（`0x4000_0010`）那一行**含**在内后即停 —— 与 golden ISS 的收尾一致；
        Spike 是分批执行、批边界才轮询 HTIF，停机请求后还会多跑最多一批（实测 5000 条）自旋
        （`write_tohost` 循环），那属停机后噪声，不算程序 trace。
    返回 `(行数, 跳过的前导行数, 是否命中停机写)`。
    """
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))          # → iss/
    from vriss.trace import RetireRecord, TraceWriter                      # noqa: E402

    n = skipped = 0
    started = False
    halted = False
    writer = TraceWriter(str(out))
    try:
        for line in log.open(encoding="utf-8", errors="replace"):
            m = COMMIT_RE.match(line.rstrip("\r\n"))
            if not m:
                continue
            pc = int(m["pc"], 16)
            if not started:
                if pc != entry:
                    skipped += 1
                    continue
                started = True
            rec = RetireRecord(pc=pc, instr=int(m["bin"], 16), priv=int(m["pri"]))
            if (x := XWR_RE.search(m["rest"])):
                rec.rd_idx, rec.rd_data, rec.rd_wb_en = int(x["idx"]), int(x["val"], 16), 1
            if (c := CSRWR_RE.search(m["rest"])):
                rec.csr_addr = int(c["addr"], 16) if c["addr"] else int(c["num"], 10)
                rec.csr_new, rec.csr_wr_en = int(c["val"], 16), 1
            writer.write(rec)
            n += 1
            # 停机写判定按**数值**比（Spike 把地址零填充成 16 位十六进制，字面量匹配会漏）
            if (mw := MEMW_RE.search(m["rest"])) and int(mw["addr"], 16) == tohost:
                halted = True
                break
    finally:
        writer.close()
    return n, skipped, halted


def _to_csv_riscv_dv(args: argparse.Namespace) -> int:
    """riscv-dv 的转换器路径（只对 `--preset upstream` 的 log 有意义；见 cmd_to_csv 说明）。"""
    conv = Path(args.converter)
    if not conv.exists():
        raise SystemExit("[spike_run] FAIL：找不到转换器 %s（riscv-dv 本地副本缺失；ISS-004）" % conv)
    cmd = [sys.executable, str(conv), "--log", str(Path(args.log).resolve()),
           "--csv", str(Path(args.csv).resolve())]
    if getattr(args, "full", False):
        cmd.append("--full_trace")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    n = 0
    if r.returncode == 0 and Path(args.csv).exists():
        n = sum(1 for _ in Path(args.csv).open(encoding="utf-8", errors="replace")) - 1
    print("[spike_run] to-csv（riscv-dv）%s → %s 行数=%d rc=%d" % (args.log, args.csv, n, r.returncode))
    if r.returncode != 0 or not n:
        print((r.stdout or "") + (r.stderr or ""))
        return 1
    return 0



def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Spike（第二 ISS）调用封装；见本文件头三条硬事实")
    ap.add_argument("--preset", choices=sorted(PRESETS), default="project",
                    help="project＝项目映射版 Spike（默认；与 sw/env/link.ld 对齐，可直接与 vriss CSV 比）"
                         "／upstream＝上游映射版（DRAM 0x8000_0000）")
    ap.add_argument("--spike", default=None, help="覆盖 preset 的 spike 可执行路径（MSYS 写法）")
    ap.add_argument("--mem-args", default=None, help="覆盖 preset 的内存区域参数（原样拼进 spike 命令行）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("check", help="环境探针：spike 可执行 + --help 命中 log-commits")

    pr = sub.add_parser("run", help="固化调用 spike（自动备 DTB）")
    pr.add_argument("elf", help="待跑 ELF（Spike 按 ELF 装载）")
    pr.add_argument("--isa", default=ISA_DEFAULT, help="ISA 串（默认＝spec/00 §2 一期串）")
    pr.add_argument("--log", required=True, help="commit log 落盘路径")
    pr.add_argument("--csv", help="可选：同时转标准 trace CSV")
    pr.add_argument("--dtb", help="可选：显式指定 DTB（默认自动生成并缓存到 sim/spike/）")
    pr.add_argument("--force-dtb", action="store_true", help="强制重新生成 DTB")
    pr.add_argument("--timeout", type=int, default=600, help="单次调用挂钟上限（秒）")
    pr.add_argument("--converter", default=str(CONVERTER_DEFAULT), help="（riscv-dv 路径）日志→CSV 转换器")
    pr.add_argument("--entry", type=lambda s: int(s, 0), default=ENTRY_DEFAULT,
                    help="trace 起点＝程序入口（默认 spec/00 §4.1 RESET_PC）")
    pr.add_argument("--tohost", type=lambda s: int(s, 0), default=TOHOST_DEFAULT,
                    help="trace 终点＝tohost 地址（默认 G1-I 清单 §1.1 第 8 条）")
    pr.add_argument("extra", nargs="*", help="`--` 之后原样透传给 spike 的参数")

    pc = sub.add_parser("to-csv", help="Spike log → 标准 trace CSV（默认本机解析，与 vriss 同格式）")
    pc.add_argument("log")
    pc.add_argument("csv")
    pc.add_argument("--riscv-dv", action="store_true",
                    help="改用 riscv-dv 的转换器（只对 --preset upstream 的 log 有意义；见 cmd_to_csv 说明）")
    pc.add_argument("--converter", default=str(CONVERTER_DEFAULT))
    pc.add_argument("--full", action="store_true", help="（riscv-dv 路径）生成完整 trace（含反汇编列）")
    pc.add_argument("--entry", type=lambda s: int(s, 0), default=ENTRY_DEFAULT,
                    help="trace 起点＝程序入口（默认 spec/00 §4.1 RESET_PC）")
    pc.add_argument("--tohost", type=lambda s: int(s, 0), default=TOHOST_DEFAULT,
                    help="trace 终点＝tohost 地址（默认 G1-I 清单 §1.1 第 8 条）")

    args = ap.parse_args(argv)
    # `--` 之后的透传参数：argparse 会吃进 extra（含前导 '--'），这里剥掉
    if getattr(args, "extra", None) and args.extra and args.extra[0] == "--":
        args.extra = args.extra[1:]
    return {"check": cmd_check, "run": cmd_run, "to-csv": cmd_to_csv}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
