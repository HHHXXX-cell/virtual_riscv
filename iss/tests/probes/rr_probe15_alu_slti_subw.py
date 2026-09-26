#!/usr/bin/env python3
"""探针 15：vriss 的两个 ALU 缺陷（`doc/process/ledger.json` 的 ISS-124 / ISS-125）的**可复现证据**。

只读仓库、不改 `iss/vriss/**`：本探针直接构造两条指令并读回目的寄存器，与规范正文对照。

- **ISS-124（SLTI）**：`vriss/machine.py:345` 的 `int(_s(x) < _s(imm))` 把**已符号扩展的 Python
  负整数** `imm` 再送进 `_s()`（`_s` 的语义是「64 位补码→Python 有符号」，见 `:45-47`）——
  `v >> 63` 对负 Python 整数恒真 ⇒ `imm` 被再减 `2**64` 成大负数 ⇒ 比较恒错。
  锚点（一级依据）＝ `D:\\IC验证知识库\\_tools\\extracted\\riscv_spec\\riscv_spec_full.txt` 行 2382-2383：
  「SLTI … places the value 1 in register rd if register rs1 is less than the sign-extended immediate
  when both are treated as signed numbers, else 0 is written to rd」。
  ⇒ `slti x14, x1, -2048`，`x1 = 0xffffffff80000000`（= -2^31）：ISA 要求 1。
- **ISS-125（SUBW）**：`vriss/machine.py:400` 的 `_op32` f3=000 分支只做 `w + y`、**不读 funct7**
  ⇒ SUBW（funct7=0100000）被当 ADDW（同函数 f3=5 已按 funct7 分流，仅 f3=000 漏）。
  锚点＝同一提取件行 3609-3611：「ADDW and SUBW are RV64I-only instructions that are defined
  analogously to ADD and SUB but operate on 32-bit values …」。
  ⇒ `subw x15, x2, x3`，`x2 = x3 = 1`：ISA 要求 0。

跑法（任意 cwd）：`python iss/tests/probes/rr_probe15_alu_slti_subw.py`
退出码：0 = 两条都**命中缺陷**（即缺陷仍在，证据成立）；1 = 有任一条不再命中（缺陷已被修，须回填台账）。
**2026-09-26 心跳第 6 轮实测：两条均已按规范原文修复 ⇒ 本探针退出码 1、两条各自打印「符合 ISA」**
（修法见 `iss/vriss/machine.py` 的 `_op_imm` f3=2 与 `_op32` f3=0 分支注释；此后本探针转为**回归件**：
任一改动若把这两条语义改回去，本探针立即回到退出码 0 并点名）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # = <repo>/iss（本件在 iss/tests/probes/）

from vriss import RESET_PC, Bus, VrIss                 # noqa: E402
from vriss.encode import ADDI, SLTI, SUBW              # noqa: E402

MASK64 = (1 << 64) - 1
TOHOST = 0x4000_0010


def probe_once(words, init_regs):  # type: ignore[no-untyped-def]
    """在 RESET_PC 放 `words`，预置 `init_regs`，跑一条一停；返回 (n_retired, regs 快照)。"""
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(RESET_PC, b''.join(int(w).to_bytes(4, 'little') for w in words))
    iss = VrIss(bus=bus, reset_pc=RESET_PC, tohost_addr=TOHOST)
    for i, v in init_regs.items():
        iss.regs[i] = v & MASK64
    n, _ = iss.run(max_instr=len(words))
    return n, [iss.regs[i] for i in range(32)]


def main() -> int:
    bad = 0

    # ---- ISS-124：SLTI（负立即数）----
    # 序列：x1 预置 -2^31；slti x14, x1, -2048；其余槽用 ADDI x0,x0,0 填位（NOP）
    words = [SLTI(14, 1, -2048), ADDI(0, 0, 0), ADDI(0, 0, 0)]
    n, regs = probe_once(words, {1: 0xFFFFFFFF80000000})
    got, want = regs[14], 1
    hit = (got != want)
    bad += hit
    print('[probe15] ISS-124 SLTI: slti x14, x1(=0xffffffff80000000), -2048 → '
          'x14=0x%x (ISA 要求 %d) ⇒ %s（retired=%d）'
          % (got, want, '命中缺陷' if hit else '符合 ISA', n))

    # ---- ISS-125：SUBW（funct7=0100000 被忽略）----
    words = [SUBW(15, 2, 3), ADDI(0, 0, 0), ADDI(0, 0, 0)]
    n, regs = probe_once(words, {2: 1, 3: 1})
    got, want = regs[15], 0
    hit = (got != want)
    bad += hit
    print('[probe15] ISS-125 SUBW: subw x15, x2(=1), x3(=1) → '
          'x15=0x%x (ISA 要求 %d) ⇒ %s（retired=%d）'
          % (got, want, '命中缺陷（似 ADDW）' if hit else '符合 ISA', n))

    print('[probe15] 结论：%d/2 条缺陷仍可复现（0 条=两条均已按 ISA 修复，退出码 1；'
          '任一复发 ⇒ 退出码 0 并点名）' % bad)
    return 0 if bad else 1


if __name__ == '__main__':
    raise SystemExit(main())
