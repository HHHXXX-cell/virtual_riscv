#!/usr/bin/env python3
"""ISS 骨架的冒烟测试：不依赖工具链、不依赖 Spike，纯自研汇编器 + 断言。

覆盖：立即数/LUI、SW-LW、MUL/DIV/REM（含除零定义）、SLLI、BEQ 跳转、JAL 与链接地址、
**非对齐 store → M 态 trap → handler 改 mepc → MRET 跳过**、CSR 写与纯读（CSRRS rs1=x0
必须不写）、tohost 停机（PASS 值为 1）、trace CSV 落盘与内容抽查。

跑法（任意 cwd）：
    python iss/tests/test_smoke.py
它是 `AGENTS.md` §4「通过判定必须有显式证据」在 ISS 侧的最小实现——只看断言，不看"没报错"。
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vriss import (                                   # noqa: E402
    Csr, Exc, RESET_PC, TRACE_CSV_FIELDS, Bus, TraceWriter, VrIss, link, read_trace_csv,
)
from vriss.encode import (                            # noqa: E402
    ADDI, ADDIW, BEQ, CSRRS, CSRRW, DIV, JAL, LW, LUI, MUL, REM, SLLI, SW, MRET,
)

MASK64 = (1 << 64) - 1

CODE = 0x1000          # = RESET_PC
HANDLER = 0x1100
DRAM = 0x4000_0000
SIGWIN = 0x2000_0000
# tohost 必须落在**有后级支撑**的区域：PMA 里 0x2000_0000 窗是 non-cacheable 且未挂设备，
# 对其做普通 store 会正确报 store-access-fault（首轮跑测就是被它坑到）。故用 DRAM 区。
TOHOST = 0x4000_0010
TOHOST_HI = 0x40000
TOHOST_LO = 0x10          # 12 位有符号字段装得下；enc_i 现在会拦住超范围立即数
MEPC, MTVEC, MSCRATCH = int(Csr.MEPC), int(Csr.MTVEC), int(Csr.MSCRATCH)


def build_words() -> list[tuple[int, list[int]]]:
    # 每项 = 一条 4 字节指令，从 CODE 起连续排列
    prog = [
        LUI(1, 0x1),
        ADDI(1, 1, 0x100),
        CSRRW(0, MTVEC, 1),
        ADDI(6, 0, 31),
        LUI(7, 0x40000),
        SW(6, 7, 0),
        LW(8, 7, 0),
        ADDI(9, 0, -1),
        MUL(10, 9, 9),
        DIV(11, 6, 0),
        REM(12, 6, 0),
        SLLI(13, 6, 3),
        BEQ(8, 6, 8),                   # taken -> 跳过下一条
        ADDI(14, 0, 0x5A5),             # 必须被跳过
        ADDI(15, 0, 7),
        JAL(16, 8),                     # x16 = 本条+4；-> 跳过下一条
        ADDI(14, 0, 0x5A6),             # 必须被跳过
        ADDI(17, 0, 3),
        SW(17, 7, 1),                   # 非对齐 store -> trap，handler 跳过它
        ADDI(18, 0, 9),                 # trap 后恢复执行点
        ADDI(19, 0, 5),
        ADDIW(20, 19, 1),
        CSRRW(0, MSCRATCH, 19),        # mscratch <- x19 = 5（rd=x0 不写回）
        CSRRS(21, MSCRATCH, 0),         # 纯读：rs1=x0 ⇒ 不得写 CSR；x21 应为 5（非恒真断言）
        ADDI(22, 0, 1),
        LUI(23, TOHOST_HI),
        ADDI(23, 23, TOHOST_LO),         # x23 = TOHOST
        SW(22, 23, 0),                   # tohost <- 1 ⇒ riscv-tests PASS
        ADDI(14, 0, 0x7FF),            # 不应被执行（旧值 0xDEAD 装不进 12 位，被 _chk 拦下）
    ]
    handler = [
        CSRRS(5, MEPC, 0),
        ADDI(5, 5, 4),
        CSRRW(0, MEPC, 5),
        MRET(),
    ]
    return [(CODE, prog), (HANDLER, handler)]


EXPECT = {
    6: 31, 7: DRAM, 8: 31, 9: MASK64, 10: 1, 11: MASK64, 12: 31, 13: 248,
    14: 0,                                 # 两条“应跳过”的 ADDI 都没跑
    15: 7, 16: 0x103C + 4, 17: 3, 18: 9, 19: 5, 20: 6,
    21: 5,        # 旧断言写 0 是废断言（mscratch 从未被写过）；现在先写 5 再读，才能证伪
    22: 1, 23: TOHOST, 1: 0x1100,
}
EXPECTED_RETIRED = 30                      # 26 条主序（含 1 条异常退休）+ 4 条 handler


def run() -> int:
    parts = build_words()
    img = link(parts)
    bus = Bus(signature_addr=SIGWIN)
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=RESET_PC, tohost_addr=TOHOST)
    n, recs = iss.run(max_instr=100_000)

    out = Path(tempfile.gettempdir()) / "vriss_smoke_trace.csv"
    with TraceWriter(str(out)) as tw:
        for r in recs:
            tw.write(r)

    fails: list[str] = []

    if not iss.halted:
        fails.append("未停机：tohost 写没被识别")
    if iss.halt_val != 1:
        fails.append(f"halt_val={iss.halt_val:#x}，期望 1（riscv-tests 的 PASS 写的是 1）")
    if n != EXPECTED_RETIRED:
        fails.append(f"退休指令数={n}，期望 {EXPECTED_RETIRED}")
    for idx, want in EXPECT.items():
        got = iss.regs[idx]
        if got != (want & MASK64):
            fails.append(f"x{idx} = 0x{got:x}，期望 0x{want & MASK64:x}")

    # trap 现场：非对齐 store 必须报 store-address-misaligned，mtval = 出错 VA
    if iss.csr.get(Csr.MCAUSE) != int(Exc.STORE_ADDR_MISALIGNED):
        fails.append(f"mcause={iss.csr.get(Csr.MCAUSE)}，期望 {int(Exc.STORE_ADDR_MISALIGNED)}")
    if iss.csr.get(Csr.MTVAL) != DRAM + 1:
        fails.append(f"mtval=0x{iss.csr.get(Csr.MTVAL, 0):x}，期望 0x{DRAM + 1:x}")
    if iss.csr.get(Csr.MEPC) != 0x104C:
        fails.append(f"mepc=0x{iss.csr.get(Csr.MEPC, 0):x}，期望 0x104c（handler 已 +4 跳过）")
    if (iss.csr.get(Csr.MSTATUS) >> 11) & 3 != 0:
        fails.append("MRET 后 mstatus.MPP 应归底到 U(0)")

    # trace 文件本身也要成证
    rows = read_trace_csv(str(out))
    with open(out, encoding="utf-8") as f:
        header = f.readline().strip().split(",")
    if header != TRACE_CSV_FIELDS:
        fails.append(f"CSV 表头 {header} != {TRACE_CSV_FIELDS}")
    if len(rows) != EXPECTED_RETIRED:
        fails.append(f"CSV 行数 {len(rows)} != {EXPECTED_RETIRED}")
    csr_rows = {r["csr"] for r in rows if r["csr"]}
    if f"0x{MTVEC:03x}:0x{0x1100:016x}" not in csr_rows:
        fails.append(f"trace 里找不到 mtvec 写入记录，实得 {sorted(csr_rows)}")
    if f"0x{MEPC:03x}:0x{0x104C:016x}" not in csr_rows:
        fails.append(f"trace 里找不到 handler 改 mepc 的记录，实得 {sorted(csr_rows)}")
    bad = [r for r in rows if int(r["pc"], 16) in (0x1034, 0x1040, 0x1070)]
    if bad:
        fails.append(f"被跳过的指令出现在 trace 里：{[r['pc'] for r in bad]}")
    # CSRRS(rs1=x0) 不得产生 CSR 写；CSRRW 必须产生。两者用 pc 定位，避免恒真断言。
    by_pc = {int(r["pc"], 16): r for r in rows}
    if by_pc.get(0x1058, {}).get("csr", "") != f"0x{MSCRATCH:03x}:0x{5:016x}":
        fails.append(f"CSRRW 行(0x1058) 未记下 mscratch 新值，实得 {by_pc.get(0x1058, {}).get('csr')!r}")
    if by_pc.get(0x105C, {}).get("csr", "") != "":
        fails.append(f"CSRRS rs1=x0 不应写 CSR，但 0x105c 行带 csr={by_pc.get(0x105C, {}).get('csr')!r}")

    print(f"[smoke] retired={n} cycles={iss.cycle} halted={iss.halted} "
          f"halt_val={iss.halt_val} trace={out}")
    print(f"[smoke] mcause={iss.csr.get(Csr.MCAUSE)} mtval=0x{iss.csr.get(Csr.MTVAL, 0):x} "
          f"mepc=0x{iss.csr.get(Csr.MEPC, 0):x}")
    if fails:
        print(f"\n[FAIL] {len(fails)} 项：")
        for f in fails:
            print("  -", f)
        return 1
    print("[PASS] ISS 骨架冒烟全通过：退休数、寄存器、trap/MRET、CSR trace、CSV 口径全部符合断言")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
