"""临时取证脚本 4（用完即删）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iss"))

from vriss import Bus, VrIss, link, Csr, Exc                            # noqa
from vriss.encode import *                                              # noqa
from vriss.machine import _b_imm, _j_imm, _s_imm, _s                    # noqa

MASK64 = (1 << 64) - 1
CODE, HDL = 0x1000, 0x1080
STOP = BEQ(0, 0, 0)


def go(prog, init=None, csr=None, tohost=None, steps=None):
    img = link([(CODE, list(prog) + [STOP]), (HDL, [STOP])])
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE, tohost_addr=tohost)
    iss.csr[Csr.MTVEC] = HDL
    for k, v in (csr or {}).items():
        iss.csr[k] = v
    for r, v in (init or {}).items():
        iss.regs[r] = v & MASK64
    iss.run(max_instr=steps or (len(prog) + 3))
    return iss


print("=== 立即数抽取 round-trip ===")
bad = 0
for off in range(-2048, 2048, 7):
    if go.__name__ == "x":
        pass
    w = ADDI(1, 2, off)
    got = _s((w >> 20) & 0xFFF) if False else None
from vriss.consts import sext
for off in list(range(-2048, 2048)) :
    w = ADDI(1, 2, off)
    if sext((w >> 20) & 0xFFF, 12) != off:
        bad += 1
print(f"  I 型 round-trip 失败 {bad} 例")
bad = sum(1 for off in range(-4096, 4096, 2) if _b_imm(BEQ(1, 2, off)) != off)
print(f"  B 型 round-trip 失败 {bad} 例 (offset -4096..4094 步长 2)")
bad = sum(1 for off in range(-1048576, 1048576, 1012) if _j_imm(JAL(1, off)) != off)
print(f"  J 型 round-trip 失败 {bad} 例")
bad = sum(1 for off in range(-2048, 2048) if _s_imm(SD(1, 2, off)) != off)
print(f"  S 型 round-trip 失败 {bad} 例")

print("=== W 型 / 移位 判决面 ===")
tests = [
    ("SRAIW x1,x2,3", SRAIW(1, 2, 3), {2: 0xFFFF_8000}),
    ("SRLIW x1,x2,3", SRLIW(1, 2, 3), {2: 0xFFFF_8000}),
    ("SLLIW x1,x2,31", SLLIW(1, 2, 31), {2: 1}),
    ("ADDIW x1,x2,-1000", ADDIW(1, 2, -1000), {2: 0}),
    ("ADDIW x1,x2,1000", ADDIW(1, 2, 1000), {2: 0}),
    ("SRAI x1,x2,3", SRAI(1, 2, 3), {2: 0x8000_0000_0000_0000}),
    ("SRA x1,x2,x3", SRA(1, 2, 3), {2: -16, 3: 4}),
    ("SUBW x1,x2,x3", SUBW(1, 2, 3), {2: 5, 3: 3}),
]
for name, w, init in tests:
    iss = go([w], init)
    r = iss.records[0]
    print(f"  {name:22s} 0x{w:08x} -> x1=0x{iss.regs[1]:016x} exc={r.exc_v}"
          f" cause={r.exc_cause} mnem={r.instr_str!r}")

print("=== 编码器缺检查 ===")
for name, thunk in [
    ("ADDI rd=64 越界", lambda: ADDI(64, 0, 1)),
    ("LUI imm20=0x100000 越界", lambda: LUI(1, 0x100000)),
    ("SLLI sh=64 越界", lambda: SLLI(1, 0, 64)),
    ("CSRRW csr=0x1FFF 越界", lambda: CSRRW(1, 0x1FFF, 0)),
    ("SD rs1=33 越界", lambda: SD(0, 33, 0)),
]:
    try:
        w = thunk()
        print(f"  {name:26s} -> 静默接受 0x{w:08x}")
    except Exception as e:
        print(f"  {name:26s} -> {type(e).__name__}: {e}")

print("=== tohost 写 0 ===")
img = link([(CODE, [LUI(2, 0x40000), SD(0, 2, 0x10), ADDI(9, 0, 99), STOP]), (HDL, [STOP])])
bus = Bus(); bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=CODE, tohost_addr=0x4000_0010)
iss.csr[Csr.MTVEC] = HDL
iss.run(8)
print(f"  向 tohost 写 0（清零，非停机语义）: halted={iss.halted} code={iss.halt_code} x9=0x{iss.regs[9]:x}")

print("=== signature 截获后读不回 ===")
img = link([(CODE, [LUI(2, 0x20000), ADDI(3, 0, 0x1FF), SD(3, 2, 0), LD(1, 2, 0), STOP]),
            (HDL, [STOP])])
bus = Bus(signature_addr=0x2000_0000)
bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=CODE)
iss.csr[Csr.MTVEC] = HDL
iss.run(8)
print(f"  SD->0x20000000 后 LD 同地址: x1=0x{iss.regs[1]:x} mcause={iss.csr.get(Csr.MCAUSE)} "
      f"mem_writes={bus.mem_writes} sig={bus.signature_writes}")

print("=== 分支 taken 的 trace 文本 ===")
iss = go([ADDI(6, 0, 31), BEQ(6, 6, 8), ADDI(7, 0, 1)], steps=4)
for r in iss.records[:3]:
    print(f"  {r.pc:08x} {r.instr_str!r} operand={r.operand!r} is_br={r.is_br}")
