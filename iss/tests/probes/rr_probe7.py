#!/usr/bin/env python3
"""探针 7：一条命令汇总所有"会导致错判"条目的实跑证据。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import Csr
from vriss.encode import (ADDI, LUI, SLLI, SRLI, SRAI, SRAIW, SRLIW, LBU, LHU, LB, JAL,
                          MRET, SRET, enc_r, OP_OP32)
from vriss.trace import RetireRecord

NEG = 0xFFFFFFFF80000000
BASE = [ADDI(9, 0, -1), SLLI(9, 9, 31)]      # x9 = 0xFFFFFFFF80000000


def mk(words):
    bus = Bus()
    bus.load_image(0x1000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in words))
    bus.load_image(0x4000_0000, bytes(range(0x40)))
    bus.load_image(0x1100, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                                    for w in [JAL(0, 0)] * 4))
    iss = VrIss(bus=bus, reset_pc=0x1000)
    iss.csr[Csr.MTVEC] = 0x1100
    return iss


def run(words, n, tag, regs):
    iss = mk(words)
    err = ""
    for _ in range(n):
        try:
            iss.step()
        except Exception as e:
            err = f" !!Python {type(e).__name__}: {e}"
            break
    last = iss.records[-1] if iss.records else None
    got = "  ".join(f"x{k}=0x{iss.regs[k]:016x}" for k in regs)
    print(f"  {tag:30s} bin=0x{words[-1] & 0xFFFFFFFF:08x} "
          f"exc_v={last.exc_v if last else '-'} cause={int(last.exc_cause) if last else '-'}  {got}{err}")
    return iss


print("### E1  RV64 SRA == SRL（machine.py:367 用 funct7 & 0x40 作算术标志）")
iss = mk(BASE)
for _ in range(2):
    iss.step()
iss.regs[10] = 4
print(f"      输入 x9=0x{iss.regs[9]:016x} x10=4   期望 SRA=0x0fffffffff8000000>>... =0x0ffffffff80000000/16")
for tag, w, rd in (("SRA x11,x9,x10", enc_r(0x20, 10, 9, 5, 11, 0x33), 11),
                   ("SRL x12,x9,x10", enc_r(0x00, 10, 9, 5, 12, 0x33), 12)):
    rec = RetireRecord(pc=0x9000, instr=w)
    iss.pc = 0x9000
    iss._exec(rec, w)
    print(f"      {tag:16s} -> x{rd}=0x{iss.regs[rd]:016x}")
print("      两条结果相同 => SRA 未做算术扩展（正确值 0x0fffffffff8000000 的低 60 位含符号 1）")

print("\n### E2  规范 SRAI/SRAIW（bit30=1）被判非法指令")
run(BASE + [SRAI(11, 9, 4)], 3, "SRAI x11,x9,4", [11])
run(BASE + [SRAIW(11, 9, 4)], 3, "SRAIW x11,x9,4", [11])
run(BASE + [SRLI(11, 9, 4)], 3, "SRLI x11,x9,4 对照", [11])

print("\n### E3  保留编码被当合法执行")
run(BASE + [0x80449593], 3, "SLLI funct6=100000 保留", [11])
run([ADDI(9, 0, 1), enc_r(0, 32, 9, 1, 11, OP_OP32)], 2, "SLLIW instr[25]=1 保留", [9, 11])
run([0x80a4a063], 1, "BRANCH funct3=2 保留", [])

print("\n### E4  W 型 M 扩展全被判非法")
for nm, f3 in (("MULW", 0), ("DIVW", 4), ("DIVUW", 5), ("REMW", 6), ("REMUW", 7)):
    run([ADDI(9, 0, 7), ADDI(10, 0, 5), enc_r(0x01, 10, 9, f3, 11, OP_OP32)], 3, nm, [11])

print("\n### E5  jal x0,0 死循环失效")
run([JAL(0, 0), ADDI(9, 0, 1), ADDI(9, 9, 1), ADDI(9, 9, 1), ADDI(9, 9, 1)],
    5, "jal x0,0 + 4 条加法", [9])

print("\n### E6  LBU/LHU 访问宽度错（machine.py:287）")
run([LUI(9, 0x40000), ADDI(9, 9, 5), LBU(10, 9, 0)], 3, "LBU @0x40000005 应 0x05", [10])
run([LUI(9, 0x40000), ADDI(9, 9, 16), LBU(10, 9, 0)], 3, "LBU @0x40000010 应 0x10", [10])
run([LUI(9, 0x40000), ADDI(9, 9, 32), LHU(10, 9, 0)], 3, "LHU @0x40000020 应 0x2120", [10])
run([LUI(9, 0x40000), ADDI(9, 9, 6), LB(10, 9, 0)], 3, "LB @0x40000006 对照 应 6", [10])

print("\n### E7  MRET()/SRET() 编码")
print(f"      本仓库 MRET()=0x{MRET():08x}  SRET()=0x{SRET():08x}")
print("      riscv-tests encoding.h: MATCH_MRET=0x30200073  MATCH_SRET=0x10200073")
run([MRET()], 1, "执行本仓库 MRET()", [])

print("\n### E8  ECALL 也算退休、也加 minstret")
iss = mk([0x00000073])
iss.step()
print(f"      records={len(iss.records)} seq(=minstret 读回)={iss.seq} "
      f"mcause={iss.csr.get(Csr.MCAUSE)} mepc=0x{iss.csr.get(Csr.MEPC, 0):x} "
      f"trace 行={iss.records[0].to_trace_row()}")
