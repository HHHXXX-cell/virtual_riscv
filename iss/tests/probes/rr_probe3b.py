#!/usr/bin/env python3
"""探针 3b：trap/中断/mstatus/编码器范围检查（异常安全版）。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import MStatus, Priv, Exc, Csr, Intr
from vriss.encode import (ADDI, LUI, CSRRW, CSRRS, ECALL, EBREAK, SW, LW, SD, MRET,
                          SLLI, enc_r, enc_j, BEQ)
BASE, H = 0x1000, 0x1100


def fresh(main, handler, mtvec=H, tohost=None):
    if isinstance(main, dict):
        segs = main
    else:
        segs = {BASE: main, H: handler}
    bus = Bus()
    for a, ws in segs.items():
        bus.load_image(a, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in ws))
    iss = VrIss(bus=bus, reset_pc=BASE, tohost_addr=tohost)
    iss.csr[Csr.MTVEC] = mtvec
    return iss


def drive(iss, n):
    out = []
    for _ in range(n):
        try:
            iss.step()
        except Exception as e:
            out.append(f"!!Python {type(e).__name__}: {e}")
            break
    return out


print("=== 1. csrw mstatus, (2<<11) 后 MRET（MPP=2 是保留值）===")
iss = fresh({BASE: [ADDI(9, 0, 2), SLLI(9, 9, 11), CSRRW(0, 0x300, 9), MRET()],
             0x1200: [ADDI(11, 0, 0x77)]}, None)
print("  写入值 x9 = 0x%x ; WMASK 允许后 mstatus=0x%x, MPP=%d" %
      (2 << 11, iss.csr.get(Csr.MSTATUS, 0), (iss.csr.get(Csr.MSTATUS, 0) >> 11) & 3))
print(" ", drive(iss, 4) or "无 Python 异常")
print(f"  结果 priv={iss.priv} records={[(hex(r.pc), r.instr_str, int(r.exc_cause)) for r in iss.records]}")

print("\n=== 2. mtvec MODE 各值 + 中断向量 ===")
for mode, label in ((0, "Direct"), (1, "Vectored"), (2, "MODE=2(保留)"), (3, "MODE=3(保留)")):
    iss = fresh([ADDI(9, 0, 1)] * 4, [ADDI(11, 0, 0xaa)] * 40, mtvec=H | mode)
    iss.csr[Csr.MIE] = 1 << 7
    iss.csr[Csr.MSTATUS] = int(MStatus.MIE)
    iss.inject_interrupt(Intr.MTI)
    r0 = iss.step()
    print(f"  {label:14s}: 中断后 pc=0x{iss.pc:x}  (base=0x{H:x}, base+4*7=0x{H+28:x})  "
          f"记录 instr_str={r0.instr_str!r} is_intr={r0.is_intr}")

print("\n=== 3. 同步异常在 Vectored 模式下也应跳 base ===")
iss = fresh([ECALL()] * 4, [ADDI(11, 0, 0xaa)] * 40, mtvec=H | 1)
iss.step()
print(f"  ECALL + MODE=Vectored -> pc=0x{iss.pc:x} (期望 0x{H:x})")

print("\n=== 4. 被中断指令仍带指令字进 trace，且 seq 双计 ===")
iss = fresh([ADDI(9, 0, 1), ADDI(9, 9, 1)], [MRET()])
iss.csr[Csr.MIE] = 1 << 7
iss.csr[Csr.MSTATUS] = int(MStatus.MIE)
iss.inject_interrupt(Intr.MTI)
drive(iss, 4)
for r in iss.records:
    print(f"    pc=0x{r.pc:x} instr=0x{r.instr:08x} str={r.instr_str!r} exc_v={r.exc_v} "
          f"is_intr={r.is_intr} gpr={r.gpr_field()!r}")
print(f"    seq={iss.seq} (真正执行 2 条 ADDI + 1 条中断伪记录)")

print("\n=== 5. 软件写 mip 造中断 ===")
iss = fresh([LUI(9, 0x0), ADDI(9, 9, 1 << 7), CSRRW(0, 0x344, 9), ADDI(9, 9, 7)],
            [ADDI(11, 0, 0xbb)] * 20)
iss.csr[Csr.MSTATUS] = int(MStatus.MIE)
iss.csr[Csr.MIE] = 1 << 7
drive(iss, 6)
print(f"    records={[(hex(r.pc), r.instr_str, int(r.exc_cause), r.is_intr) for r in iss.records]}")
print(f"    mip 读回=0x{iss.csr_read(0x344):x}（软件写 MTIP 被接受，RTL 里 MTIP 只读）")

print("\n=== 6. satp / medeleg / mcounteren 静默接受 ===")
iss = fresh([LUI(9, 0x80000), CSRRW(0, 0x180, 9), CSRRS(10, 0x180, 0),
             CSRRW(0, 0x302, 9), CSRRS(11, 0x302, 0)], [MRET()])
print("   ", drive(iss, 5) or "无异常")
print(f"    satp(0x180) 读回=0x{iss.regs[10]:016x} medeleg(0x302) 读回=0x{iss.regs[11]:016x}")
print(f"    UXL/SATP.MODE=8(Sv39) 被接受，但后续访存仍按物理地址（无任何实现）")

print("\n=== 7. 读从未写过的页 + tval=0 兜底 ===")
bus = Bus()
bus.load_image(0x4000_0000, b"\x11" * 8)
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[Csr.MTVEC] = H
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [LUI(9, 0x40002), LW(10, 9, 0)]))
for _ in range(3):
    r = iss.step()
    print(f"    pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} "
          f"mtval=0x{iss.csr.get(Csr.MTVAL,0):x} 该记录进 trace={r in iss.records}")
print("    (0x40002000 是合法 DRAM(CACHEABLE) 但页未分配 -> 报 load access fault)")

print("\n=== 8. fault tval=0 被兜底成指令字 ===")
bus = Bus()
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [ADDI(9, 0, 0), LW(10, 9, 0)]))
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[Csr.MTVEC] = H
for _ in range(3):
    r = iss.step()
print(f"    lw 地址=0：mtval=0x{iss.csr.get(Csr.MTVAL,0):x}（应为 0，实为指令字）")

print("\n=== 9. 编码器范围检查 ===")
w = CSRRW(1, 0x1234, 2)
print(f"  CSRRW(rd=1, csr=0x1234, rs1=2) -> 0x{w:08x}，csr 域实得 0x{(w >> 20) & 0xFFF:x}（无报错，静默截断）")
w = LUI(1, 0x123456)
print(f"  LUI(1, 0x123456) -> 0x{w:08x}，imm20 实得 0x{(w >> 12) & 0xFFFFF:x}（无报错）")
try:
    ADDI(1, 2, 0x800)
    print("  ADDI 0x800 未报错（★）")
except ValueError:
    print("  ADDI(1,2,0x800) -> ValueError（正确拦住）")
w = SLLI(1, 2, 64)
print(f"  SLLI(1,2,64) -> 0x{w:08x}，shamt 域=0x{(w >> 20) & 0x3F:x}，funct6=0x{(w >> 26) & 0x3F:x}（无报错）")
w = enc_r(0x00, 0x20, 2, 0, 1, 0x33)
print(f"  ADD(rd=1,rs1=2,rs2=32 越界) -> 0x{w:08x}（rs2 溢出进 funct7 位，无报错）")
try:
    BEQ(1, 2, 5)
    print("  BEQ 奇数偏移未报错（★）")
except ValueError:
    print("  BEQ 奇数偏移 -> ValueError（正确拦住）")
try:
    enc_j(0x1FFFFF, 1, 0x6F)
    print("  JAL 21 位越界未报错（★）")
except ValueError:
    print("  JAL 21 位越界 -> ValueError（正确拦住）")

print("\n=== 10. signature 窗口 4 字节写 / 读 ===")
bus = Bus()
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [LUI(9, 0x20000), SW(0, 9, 0), SD(0, 9, 0), LW(10, 9, 0)]))
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[Csr.MTVEC] = H
for _ in range(5):
    r = iss.step()
    print(f"  pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} mem_wr={r.mem_wr} "
          f"signature_writes={bus.signature_writes}")

