# doc 分类改造探针（2026-09-23，`ISS-055` / `Q-035`）

> 本目录是**一次性结构改造的取证件**，不是规格篇目的评审探针，故不随 `doc/spec/NN` 编号。
> 目录名刻意不带 `-评审探针` 后缀 ⇒ 不进 `script/gate.py snapshot` 的长基线扫描集
> （本轮长基线已按 ADR-4 重折一次，`≤1 次/轮` 已用满，事后新增件不得再扰动基线）。

## 改造内容

| 项 | 结果（下表"旧路径"是本探针的**改造记录**，非遗留引用） |
|---|---|
| 迁移 | 旧 `doc/00-问题记录.md` → `doc/process/`；旧 `doc/03/04/05` → `doc/verify/`；旧 `doc/spec/01-评审记录.md` ＋ `doc/spec/01-评审探针/` → `doc/review/`；`doc/design/` 空置预留 |
| 引用清扫 | **744 处**：`doc/NN` 形态 703（`sweep_doc.py`）＋评审件路径 37（`sweep_review.py`）＋裸 `spec/01-评审记录.md` 等 4（`patch_resid.py`） |
| 冻结证据 | `01-评审探针/` 内 30 件**内容零改动**（md5 未变，仅换路径键）；`doc/review/01-评审记录.md` 内 3 处历史引文（旧绝对路径）**保留原文不追改** |
| 判据同步 | `patch_scripts.py`（台账/看板常量、`scanned_docs()` 改递归、`char_freq()` 语料根、`BASE_GLOBS`）、`patch_review.py`（`BASE_GLOBS`/`scan_dirs` 改指 `doc/review/*-评审探针/`） |

## 复核入口（第三人可重跑）

```bash
python script/gate.py check          # 期望：24 PASS / 0 WARN / 0 FAIL
python script/path_audit.py          # 期望：缺失路径 0 / 骨架缺失 0 / 无占位 0
python script/gate.py rocheck --baseline   # 期望：内容侧 0 差异（退出码 0）
# 例外（已披露，见 doc/verify/05 R-060）：收尾补漏的 sim/covdb/README.md 落在扫描面内，
# 本轮刷新额度已用满 ⇒ 下次该命令预期报 MODIFIED 1，下轮处置开工时随例行刷新折入。
```

残留自查（不依赖本目录脚本）：全仓 grep `doc/0[0-9]` 与 `doc/spec/01-评审`。
**豁免面**（命中属预期，非残留）：① 本目录（改造记录与补丁脚本，按定义含旧路径）；
② `script/gate/{window_state,integrity_baseline}.json`（工具状态：上一窗口与长基线指纹，
改它＝篡改历史快照）；③ `doc/review/01-评审记录.md` 内 3 处历史引文（旧绝对路径，
冻结取证不追改）；④ `doc/review/01-评审探针/`（冻结证据，全目录不扫）。

## 本目录文件

| 文件 | 说明 |
|---|---|
| `sweep_doc.py` | 主清扫器（`doc/NN` → `doc/process` 或 `doc/verify`），跳过冻结探针目录与工具状态件 |
| `sweep_review.py` | 评审件路径清扫器（`doc/spec/01-评审*` → `doc/review/…`） |
| `patch_resid.py` | 裸形态定点修补（4 处） |
| `patch_scripts.py` / `patch_review.py` | 两个判据脚本的改动集（锚点唯一性断言，命中≠1 即整体不落盘） |
| `rocheck_before_refresh.txt` | 长基线折前差异取证（MODIFIED 8 / ADDED 40 / DELETED 30 / MTIME 1） |
| `snapshot_refresh.txt` | 重折输出（旧→新指纹、文件数 88→98） |
| `gate_check_final.txt` | 改造后终局判据输出 |
