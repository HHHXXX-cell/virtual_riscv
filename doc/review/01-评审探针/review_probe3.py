"""临时取证脚本 3：带真实 handler 的 CSR/trap 取证（用完即删）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iss"))

from vriss import Bus, VrIss, link, Csr, Intr, Priv                    # noqa
from vriss.encode import *                                              # noqa

MASK64 = (1 << 64) - 1
CODE, HDL = 0x1000, 0x1080
STOP = BEQ(0, 0, 0)


def go(prog, init=None, csr=None, tohost=None, steps=None, priv=None):
    img = link([(CODE, list(prog) + [STOP]), (HDL, [STOP])])
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE, tohost_addr=tohost)
    iss.csr[Csr.MTVEC] = HDL                       # Direct 模式
    for k, v in (csr or {}).items():
        iss.csr[k] = v
    for r, v in (init or {}).items():
        iss.regs[r] = v & MASK64
    if priv is not None:
        iss.priv = priv
    iss.run(max_instr=steps or (len(prog) + 3))
    return iss, iss.records


def rpt(tag, iss, keys=(), fields=(Csr.MCAUSE, Csr.MTVAL, Csr.MEPC)):
    r0 = iss.records[0] if iss.records else None
    s = " ".join(f"x{k}=0x{iss.regs[k]:x}" for k in keys)
    c = " ".join(f"{f.name.lower()}=0x{iss.csr.get(int(f), 0):x}" for f in fields)
    print(f"  {tag}\n     {s} | {c} | rec0(exc_v={r0.exc_v if r0 else '-'},cause="
          f"{r0.exc_cause if r0 else '-'},instr_str={r0.instr_str if r0 else '-'!r})")


print("=== mtval / mcause 取证（mtvec=0x1080 Direct）===")
iss, _ = go([(0x7F << 25) | 0x33])          # funct7=0x7F 非法 R 型
print(f"  非法 R 型 0x{(0x7F<<25)|0x33:08x}: mcause={iss.csr[Csr.MCAUSE]} "
      f"mtval=0x{iss.csr[Csr.MTVAL]:x} mepc=0x{iss.csr[Csr.MEPC]:x}")
iss, _ = go([CSRRW(1, 0xC00, 2)], {2: 5})
print(f"  csrrw 只读 0xc00      : mcause={iss.csr[Csr.MCAUSE]} mtval=0x{iss.csr[Csr.MTVAL]:x}")
iss, _ = go([CSRRS(1, 0x300, 0)], {}, priv=Priv.USER)
print(f"  U 态 csrrs mstatus    : mcause={iss.csr[Csr.MCAUSE]} (期望 2)")
iss, _ = go([SRAI(1, 2, 3)], {2: 0x8000_0000_0000_0000})
print(f"  SRAI x1,x2,3          : mcause={iss.csr[Csr.MCAUSE]} (0=正常执行, 2=被误判非法)")
iss, _ = go([ADDIW(1, 0, -1)])
print(f"  ADDIW x1,x0,-1        : mcause={iss.csr[Csr.MCAUSE]} x1=0x{iss.regs[1]:x}")
iss, _ = go([EBREAK()])
r_eb = iss.records[0]
print(f"  EBREAK@0x1000         : mcause={iss.csr[Csr.MCAUSE]} mtval=0x{iss.csr[Csr.MTVAL]:x} "
      f"mepc=0x{iss.csr[Csr.MEPC]:x} (mtval 期望 0 或 0x1000)")
iss, _ = go([ECALL()])
print(f"  ECALL@M               : mcause={iss.csr[Csr.MCAUSE]} mtval=0x{iss.csr[Csr.MTVAL]:x}")
iss, _ = go([MRET()])
print(f"  MRET(mstatus=0)       : priv={int(iss.priv)} pc=0x{iss.pc:x} mstatus=0x{iss.csr[Csr.MSTATUS]:x}")
iss, _ = go([(1 << 7) | 0x73])
print(f"  ecall 且 rd=x1(保留)  : mcause={iss.csr[Csr.MCAUSE]} (非 0 才正确)")
iss, _ = go([(0x18 << 25) | (1 << 7) | 0x73])
print(f"  mret  且 rd=x1(保留)  : mcause={iss.csr[Csr.MCAUSE]} pc=0x{iss.pc:x}")

print("=== mstatus / trap 位段 ===")
iss, _ = go([CSRRW(0, 0x300, 2), MRET()], {2: (1 << 17) | (3 << 11)})   # MPRV=1 MPP=M
print(f"  MPRV=1,MPP=M 后 MRET  : mstatus=0x{iss.csr[Csr.MSTATUS]:x} (MPRV 应保持 1)")
iss, _ = go([CSRRW(0, 0x300, 2), MRET()], {2: (1 << 17) | (0 << 11)})   # MPRV=1 MPP=U
print(f"  MPRV=1,MPP=U 后 MRET  : mstatus=0x{iss.csr[Csr.MSTATUS]:x} (MPRV 应清 0)")
iss, _ = go([CSRRW(0, 0x300, 2)], {2: 2 << 11})
print(f"  mstatus.MPP<-2(保留值): mstatus=0x{iss.csr[Csr.MSTATUS]:x}")
iss, _ = go([CSRRW(0, 0x300, 2), CSRRS(1, 0x300, 0)], {2: MASK64})
print(f"  mstatus<-全 1         : trace={[r.csr_field() for r in iss.records if r.csr_wr_en]}")
print(f"     实际=0x{iss.csr[Csr.MSTATUS]:x} 读回 x1=0x{iss.regs[1]:x} -> trace 与实际不一致")
iss, _ = go([ECALL()], {}, csr={Csr.MSTATUS: 1 << 3})
m = iss.csr[Csr.MSTATUS]
print(f"  trap 进 M: mstatus=0x{m:x} MIE={bool(m & 8)} MPIE={bool(m & 128)} MPP={(m >> 11) & 3}")
iss, _ = go([ECALL()], {}, csr={Csr.MSTATUS: 0})
m = iss.csr[Csr.MSTATUS]
print(f"  MIE=0 时 trap: MIE={bool(m & 8)} MPIE={bool(m & 128)} (MPIE 应为 0)")
iss, _ = go([CSRRW(0, 0x305, 2), ECALL()], {2: HDL | 1})
print(f"  mtvec=Vectored + 同步异常: pc=0x{iss.pc:x} (期望 base=0x{HDL:x} 而非 base+4*2)")

print("=== 中断 ===")
iss, _ = go([ADDI(1, 0, 1), ADDI(2, 0, 2)], csr={Csr.MIE: 1 << int(Intr.MTI),
                                                 Csr.MSTATUS: 1 << 3}, steps=4)
iss.inject_interrupt(Intr.MTI)
iss.run(4)
print("   records:", [(f"{r.pc:08x}", f"{r.instr:08x}", r.instr_str, r.exc_v, r.exc_cause,
                       r.is_intr, r.rd_wb_en) for r in iss.records])
print(f"     mcause=0x{iss.csr[Csr.MCAUSE]:x} mepc=0x{iss.csr[Csr.MEPC]:x} "
      f"mtval=0x{iss.csr[Csr.MTVAL]:x} pc=0x{iss.pc:x}")
# 同一条指令被记录两次（中断一次 + 真正执行一次）
dups = [r.pc for r in iss.records]
print(f"     pc 序列={dups} -> 同一指令 pc 是否重复: {len(dups) != len(set(dups))}")
# Vectored 中断
iss, _ = go([ADDI(1, 0, 1)], csr={Csr.MTVEC: HDL | 1, Csr.MIE: 1 << int(Intr.MEI),
                                  Csr.MSTATUS: 1 << 3}, steps=2)
iss.inject_interrupt(Intr.MEI)
iss.step()
print(f"  Vectored + MEI(11) -> pc=0x{iss.pc:x} (期望 0x{HDL:x}+4*11=0x{HDL + 44:x})")

print("=== tohost ===")
for v in (1, 2, 3):
    img = link([(CODE, [LUI(2, 0x40000), ADDI(3, 0, v), SD(3, 2, 0x10), ADDI(9, 0, 99), STOP]),
                (HDL, [STOP])])
    bus = Bus(); bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE, tohost_addr=0x4000_0010)
    iss.csr[Csr.MTVEC] = HDL
    iss.run(8)
    print(f"  tohost<-{v}: halted={iss.halted} halt_code={iss.halt_code} x9=0x{iss.regs[9]:x}")

print("=== 非法编码落点抽查 ===")
encs = {
    "LOAD f3=7": (7 << 12) | 0x03,
    "STORE f3=4": (4 << 12) | 0x23,
    "OP f3=1 funct7=0x01(MULH? )": (0x01 << 25) | (1 << 12),
    "LWU/LBU 宽度": None,
    "SYSTEM f3=4": (4 << 12) | 0x73,
    "MISC-MEM fm=1": (1 << 12) | 0x0F,
    "AMO": (2 << 12) | 0x2F,
    "OP-IMM f3=1 shamt6=1(RV128)": (0x20 << 26) | (1 << 12) | 0x13,
    "BRANCH f3=2": (2 << 12) | 0x63,
    "BRANCH f3=3": (3 << 12) | 0x63,
    "JALR f3!=0": (1 << 12) | 0x67,
    "LUI rd=x0": (0 << 7) | 0x37,
    "OP32 f3=2": (2 << 12) | 0x3B,
}
for k, w in encs.items():
    if w is None:
        continue
    try:
        iss, recs = go([w], steps=3)
        r = recs[0] if recs else None
        print(f"  {k:34s} 0x{w:08x} -> exc_v={r.exc_v if r else '-'} cause={r.exc_cause if r else '-'} "
              f"mnem={r.instr_str if r else '-'}")
    except Exception as e:
        print(f"  {k:34s} 0x{w:08x} -> CRASH {type(e).__name__}: {e}")
