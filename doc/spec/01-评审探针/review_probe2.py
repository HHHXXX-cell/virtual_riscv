"""临时取证脚本 2（只读探测，用完即删）。"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iss"))

from vriss import Bus, VrIss, link, Csr, Intr                          # noqa
from vriss.encode import *                                              # noqa

MASK64 = (1 << 64) - 1
CODE = 0x1000
STOP = BEQ(0, 0, 0)


def go(prog, init=None, n=None, pc=CODE, sig=0x2000_0000):
    words = list(prog) + [STOP]
    img = link([(CODE, words)])
    bus = Bus(signature_addr=sig)
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=pc)
    for r, v in (init or {}).items():
        iss.regs[r] = v & MASK64
    try:
        iss.run(max_instr=n or (len(words) + 2))
    except Exception as e:
        print(f"    !! CRASH {type(e).__name__}: {e}")
        return SimpleNamespace(regs=[0] * 32, csr={}, pc=0, priv=0, records=[],
                               cycle=0, halted=False, bus=bus), []
    return iss, iss.records


def cs(iss, a):
    return iss.csr.get(int(a))


print("=== SRAI 全面失效？ ===")
for sh in (1, 3, 31, 32, 63):
    iss, recs = go([SRAI(1, 2, sh)], {2: 0x8000_0000_0000_0000})
    print(f"  SRAI x1,x2,{sh:<2} -> x1=0x{iss.regs[1]:016x} exc={recs[0].exc_v if recs else '-'}"
          f" mnem={recs[0].instr_str if recs else '-'}")
iss, recs = go([SRLI(1, 2, 3)], {2: 0x8000_0000_0000_0000})
print(f"  SRLI x1,x2,3 对比 -> x1=0x{iss.regs[1]:016x} mnem={recs[0].instr_str}")
iss, recs = go([(0x20 << 26) | (1 << 20) | (2 << 15) | (1 << 12) | (1 << 7) | 0x13],
               {2: 0x8000_0000_0000_0000})
print(f"  RV128 保留编码 instr[31:26]=100000,f3=1 -> x1=0x{iss.regs[1]:x} exc={recs[0].exc_v if recs else '-'}")
iss, recs = go([ADDIW(1, 0, -1)], {})
print(f"  ADDIW x1,x0,-1 -> x1=0x{iss.regs[1]:x} exc={recs[0].exc_v if recs else '-'}")
iss, recs = go([SRA(1, 2, 3)], {2: 0xFFFF_FFFF_FFFF_FFF0, 3: 4})
print(f"  SRA -16>>4 -> x1=0x{iss.regs[1]:x} (期望 -1=0xffff...ff)")

print("=== LBU/LHU 在非 16 字节对齐地址 ===")
for off in (0, 4, 8, 0x10):
    img = link([(CODE, [LUI(2, 0x40001), ADDI(2, 2, 4), LBU(1, 2, off - 4 if off else 0), STOP])])
    bus = Bus(); bus.load_image(img.start, img.to_bytes())
    bus.write(0x4000_1000, 8, 0x1122_3344_5566_77FF)
    iss = VrIss(bus=bus, reset_pc=CODE)
    try:
        iss.run(8)
        print(f"  LBU addr=0x40001004+{off-4}: x1=0x{iss.regs[1]:x} mcause={cs(iss, Csr.MCAUSE)}")
    except Exception as e:
        print(f"  LBU CRASH {e}")

print("=== (c) CSR / trap ===")
iss, recs = go([CSRRW(1, 0x7F0, 2)], {2: 5})
print(f"  csrrw x1,0x7f0(不存在的 CSR): x1=0x{iss.regs[1]:x} mcause={cs(iss, Csr.MCAUSE)} "
      f"keys={[hex(k) for k in iss.csr]}")
iss, recs = go([CSRRW(1, 0xC00, 2)], {2: 5})
print(f"  csrrw 0xc00(只读)          : mcause={cs(iss, Csr.MCAUSE)} (期望 2)")
iss, recs = go([CSRRS(1, 0xC00, 0)], {})
print(f"  csrrs x1,0xc00,x0(纯读只读): mcause={cs(iss, Csr.MCAUSE)} x1=0x{iss.regs[1]:x}")
iss, recs = go([CSRRSI(1, 0xC01, 0)], {})
print(f"  csrrsi x1,time(0xc01),uimm=0: mcause={cs(iss, Csr.MCAUSE)}")
iss, recs = go([EBREAK(), ADDI(9, 0, 7)], {})
print(f"  EBREAK @0x1000: mepc=0x{cs(iss, Csr.MEPC):x} mtval=0x{cs(iss, Csr.MTVAL):x}")
iss, recs = go([ADDI(3, 0, 1), MRET()], {})
print(f"  MRET@M(MPP=0): priv={int(iss.priv)} pc=0x{iss.pc:x} mstatus=0x{cs(iss, Csr.MSTATUS):x}")
iss, recs = go([(1 << 7) | 0x73], {})
print(f"  ecall 变体 rd=x1(保留编码): mcause={cs(iss, Csr.MCAUSE)} rec0.instr_str={recs[0].instr_str!r} "
      f"exc={recs[0].exc_v}")
iss, recs = go([(0x18 << 25) | (1 << 7) | 0x73], {})
print(f"  mret 变体 rd=x1(保留编码): pc=0x{iss.pc:x} mcause={cs(iss, Csr.MCAUSE)}")
iss, recs = go([(0x18 << 25) | (0 << 20) | (0x1F << 15) | 0x73], {})
print(f"  mret 变体 rs1=x31: pc=0x{iss.pc:x}")
# CSR 权限：U 态访问 mstatus
img = link([(CODE, [CSRRS(1, 0x300, 0), STOP])])
bus = Bus(); bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=CODE)
iss.priv = __import__("vriss").Priv.USER
iss.run(4)
print(f"  U 态 csrrs mstatus: mcause={cs(iss, Csr.MCAUSE)} (期望 2 illegal)")
# medeleg 写非 0 后异常仍进 M
iss, recs = go([CSRRW(0, 0x302, 2), ECALL(), ADDI(9, 0, 1)], {2: 0x3FFF})
print(f"  medeleg=0x3fff 后 ecall: mcause={cs(iss, Csr.MCAUSE)} priv={int(iss.priv)} "
      f"medeleg=0x{iss.csr.get(0x302, 0):x}")
# mip/mie 软件任意写
iss, recs = go([CSRRW(0, 0x344, 2)], {2: MASK64})
print(f"  csrrw mip<-all1: mip=0x{iss.csr.get(0x344, 0):x} (平台位应为只读/WARL)")
# 非法指令 tval
iss, recs = go([(0x7F << 25) | 0x33], {})
print(f"  非法 R 型: mcause={cs(iss, Csr.MCAUSE)} mtval=0x{cs(iss, Csr.MTVAL):x} (期望=指令码 0x{(0x7F<<25)|0x33:x})")

print("--- 取指 fault 记录是否入 trace ---")
iss, recs = go([ADDI(1, 0, 1)], n=6, pc=0x5000_0000)
print(f"  reset_pc 落在无 PMA 区: run 返回 len(iss.records)={len(recs)}  pc=0x{iss.pc:x}")
bus = Bus()
img = link([(CODE, [ADDI(1, 0, 1)])])
bus.load_image(img.start, img.to_bytes())
iss2 = VrIss(bus=bus, reset_pc=0x5000_0000)
r = iss2.step()
print(f"  step() 返回 rec(exc_v={r.exc_v},cause={r.exc_cause}) 但 iss.records={iss2.records} "
      f"seq={iss2.seq}")

print("--- 中断 ---")
img = link([(CODE, [ADDI(1, 0, 1), ADDI(2, 0, 2), STOP])])
iss = VrIss(bus=Bus(), reset_pc=CODE)
iss.bus.load_image(img.start, img.to_bytes())
iss.csr[Csr.MTVEC] = 0x1100
iss.csr[Csr.MIE] = 1 << int(Intr.MTI)
iss.csr[Csr.MSTATUS] = 1 << 3
iss.inject_interrupt(Intr.MTI)
iss.run(8)
print("  ", [(f"{r.pc:08x}", f"{r.instr:08x}", r.instr_str, r.exc_v, r.exc_cause, r.is_intr)
             for r in iss.records])
print(f"     mcause=0x{iss.csr[Csr.MCAUSE]:x} mepc=0x{iss.csr[Csr.MEPC]:x} "
      f"mtval=0x{iss.csr[Csr.MTVAL]:x} mstatus=0x{iss.csr[Csr.MSTATUS]:x}")
# Vectored
img = link([(CODE, [STOP])])
iss = VrIss(bus=Bus(), reset_pc=CODE)
iss.bus.load_image(img.start, img.to_bytes())
iss.csr[Csr.MTVEC] = 0x1000 | 1
iss.csr[Csr.MIE] = 1 << int(Intr.MEI)
iss.csr[Csr.MSTATUS] = 1 << 3
iss.inject_interrupt(Intr.MEI)
iss.step()
print(f"  Vectored + MEI(11) -> pc=0x{iss.pc:x} (期望 0x1000+4*11=0x102c)")
iss.csr[Csr.MTVEC] = 0x1000 | 1
iss.csr[Csr.MSTATUS] = 1 << 3
iss.csr[Csr.MCAUSE] = 0
iss.pc = CODE
img = link([(CODE, [(0x7F << 25) | 0x33, STOP])])
iss.bus.load_image(img.start, img.to_bytes())
iss.step()
print(f"  Vectored + 同步异常(2) -> pc=0x{iss.pc:x} (期望 base=0x1000)")

print("=== (d) 结构性 ===")
# 看门狗
iss, recs = go([JAL(0, -4)], n=50)
print(f"  死循环: n={len(iss.records)} halted={iss.halted} 无报错")
# 未写页读取
iss, recs = go([LUI(2, 0x40001), LW(1, 2, 0)], {})
print(f"  读从未写过的 DRAM 页: mcause={cs(iss, Csr.MCAUSE)} (5=load access fault; 期望读 0)")
print(f"  dump_region 同地址 = {iss.bus.dump_region(0x4000_1000, 4)!r}")
# 写 signature 窗口的 4 字节
iss, recs = go([LUI(2, 0x20000), ADDI(3, 0, 5), SW(3, 2, 0), STOP], {})
print(f"  SW 到 signature 窗 0x20000000: mcause={cs(iss, Csr.MCAUSE)} "
      f"sig_writes={iss.bus.signature_writes}")
# tohost 语义
def tohost_run(val):
    img = link([(CODE, [LUI(2, 0x40000), ADDI(3, 0, val), SD(3, 2, 0x10), ADDI(9, 0, 1), STOP])])
    bus = Bus(); bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE, tohost_addr=0x4000_0010)
    iss.run(8)
    print(f"  tohost<-{val}: halted={iss.halted} halt_code={iss.halt_code} x9=0x{iss.regs[9]:x}")


for v in (1, 3, 0):
    tohost_run(v)
