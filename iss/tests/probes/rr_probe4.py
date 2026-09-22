#!/usr/bin/env python3
"""探针 4：tval 兜底 / 编码器范围 / signature 窗口 / 全 0 指令字。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import Csr, MStatus, Intr
from vriss.encode import (ADDI, LUI, CSRRW, CSRRS, SW, LW, SD, LD, SLLI, enc_r, enc_j,
                          BEQ, JALR, ADD)

BASE, H = 0x1000, 0x1100


def mk(main, handler=(ADDI(0, 0, 0),) * 40, tohost=None):
    bus = Bus()
    bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in main))
    bus.load_image(H, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in handler))
    iss = VrIss(bus=bus, reset_pc=BASE, tohost_addr=tohost)
    iss.csr[Csr.MTVEC] = H
    return iss


def steps(iss, n):
    msgs = []
    for _ in range(n):
        try:
            iss.step()
        except Exception as e:
            msgs.append(f"!!Python {type(e).__name__}: {e}")
            break
    return msgs


print("=== 8. fault tval 合法为 0 时被兜底成指令字 ===")
iss = mk([ADDI(9, 0, 0), LW(10, 9, 0)])
print("   ", steps(iss, 3) or "无 Python 异常")
print(f"    lw 地址=0：cause={iss.csr.get(Csr.MCAUSE,0)} mtval=0x{iss.csr.get(Csr.MTVAL,0):08x}"
      f"（规范要求 mtval=访问地址 0；实得指令字）")

print("\n=== 8b. 全 0 指令字（link() 空洞 / 程序尾）===")
iss = mk([0x00000013, 0x00000000])          # addi x0,x0,0 后跟一条全 0 字
print("   ", steps(iss, 3) or "无 Python 异常")
print(f"    records={[(hex(r.pc), r.instr_str, int(r.exc_cause)) for r in iss.records]}")
print("    （0x00000000 低 2 位=00b，不是压缩指令，规范里是非法指令 → 应报 illegal-instr）")

print("\n=== 9. 编码器范围检查 ===")
w = CSRRW(1, 0x1234, 2)
print(f"  CSRRW(rd=1, csr=0x1234) -> 0x{w:08x}，指令内 csr 域 = 0x{(w >> 20) & 0xFFF:x}（无报错，静默截断）")
iss = mk([LUI(2, 0x123), CSRRS(10, 0x234, 0), CSRRW(0, 0x234, 2), CSRRS(11, 0x1234 & 0xFFF, 0)])
print("   ", steps(iss, 5) or "无异常", " -> 写 0x234 与 0x1234 是同一个槽:",
      hex(iss.csr.get(0x234, -1)))
w = LUI(1, 0x123456)
print(f"  LUI(1, 0x123456) -> 0x{w:08x}，imm20 = 0x{(w >> 12) & 0xFFFFF:x}（无报错，静默截断）")
for nm, fn in (("ADDI(1,2,0x800)", lambda: ADDI(1, 2, 0x800)),
               ("SLLI(1,2,64)", lambda: SLLI(1, 2, 64)),
               ("ADD(rd=1,rs1=2,rs2=32)", lambda: ADD(1, 2, 32)),
               ("BEQ(1,2,5) 奇数", lambda: BEQ(1, 2, 5)),
               ("JALR off=0x800", lambda: JALR(1, 2, 0x800)),
               ("enc_j(0x1FFFFF)", lambda: enc_j(0x1FFFFF, 1, 0x6F))):
    try:
        v = fn()
        print(f"  {nm:26s} -> 0x{v & 0xFFFFFFFF:08x}   ★无报错★")
    except ValueError as e:
        print(f"  {nm:26s} -> ValueError（正确拦住）")

print("\n=== 10. signature 窗口写入宽度 ===")
iss = mk([LUI(9, 0x20000), SW(0, 9, 0), SD(0, 9, 0), LW(10, 9, 0)], tohost=None)
for _ in range(5):
    try:
        r = iss.step()
    except Exception as e:
        print("   ", type(e).__name__, e)
        break
    print(f"  pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} mem_wr={r.mem_wr} "
          f"sig_writes={iss.bus.signature_writes}")

print("\n=== 11. 4 字节 store 到 tohost（riscv-tests 用 sw）===")
iss = mk([LUI(9, 0x40000), ADDI(9, 9, 0x20), ADDI(10, 0, 1), SW(10, 9, 0)], tohost=0x4000_0020)
print("   ", steps(iss, 5) or "", f"halted={iss.halted} code={iss.halt_code}")
iss = mk([LUI(9, 0x40000), ADDI(9, 9, 0x20), ADDI(10, 0, 3), SD(10, 9, 0)], tohost=0x4000_0020)
print("   ", steps(iss, 5) or "", f"halted={iss.halted} code={iss.halt_code}")

print("\n=== 12. 非对齐 load / LD 宽度 ===")
iss = mk([LUI(9, 0x40000), LD(10, 9, 0), LW(11, 9, 4)], H=(LD(0, 0, 0),) * 40)
iss.bus.load_image(0x4000_0000, (0xFFF0_0000_0000_0000 ^ 0).to_bytes(8, "little"))
print("   ", steps(iss, 4) or "", f"x10=0x{iss.regs[10]:016x} x11=0x{iss.regs[11]:016x}")
iss = mk([LUI(9, 0x40000), ADDI(10, 9, 1), LW(11, 10, 0)])
print("   非对齐 lw:", steps(iss, 4) or "", f"cause={iss.csr.get(Csr.MCAUSE,0)} "
      f"mtval=0x{iss.csr.get(Csr.MTVAL,0):x}")
