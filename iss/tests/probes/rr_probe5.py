#!/usr/bin/env python3
"""探针 5：load 宽度 / 保留移位编码 / jal 自旋 / halt 码方向。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import Csr
from vriss.encode import ADDI, LUI, LW, LH, LBU, LHU, LWU, LB, JAL, enc_r

DATA = bytes(range(0x40))


def run(words, base=0x1000, n=6, tag=""):
    bus = Bus()
    bus.load_image(base, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in words))
    bus.load_image(0x4000_0000, DATA)
    bus.load_image(0x2000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                                    for w in [JAL(0, 0)]))
    iss = VrIss(bus=bus, reset_pc=base)
    iss.csr[Csr.MTVEC] = 0x2000
    for _ in range(n):
        try:
            r = iss.step()
        except Exception as e:
            print(f"   [{tag}] !!Python {type(e).__name__}: {e}")
            break
        print(f"   [{tag}] pc=0x{r.pc:x} str={r.instr_str:9s} exc_v={r.exc_v} "
              f"cause={int(r.exc_cause)} mem_size={r.mem_size} rd=0x{r.rd_data:x} "
              f"mtval=0x{iss.csr.get(Csr.MTVAL, 0):x}")
    return iss


print("== 内存 0x4000_0000 起 = 00 01 02 ... 3f ==")
run([LUI(9, 0x40000), ADDI(9, 9, 5), LB(10, 9, 0)], tag="lb@5 应0x05")
run([LUI(9, 0x40000), ADDI(9, 9, 5), LBU(10, 9, 0)], tag="lbu@5 应0x05")
run([LUI(9, 0x40000), ADDI(9, 9, 0x10), LBU(10, 9, 0)], tag="lbu@16 应0x10")
run([LUI(9, 0x40000), ADDI(9, 9, 0x20), LHU(10, 9, 0)], tag="lhu@32 应0x2120")
run([LUI(9, 0x40000), ADDI(9, 9, 2), LHU(10, 9, 0)], tag="lhu@2 应0x0302")
run([LUI(9, 0x40000), ADDI(9, 9, 6), LH(10, 9, 0)], tag="lh@6 应0x0706")
run([LUI(9, 0x40000), ADDI(9, 9, 4), LWU(10, 9, 0)], tag="lwu@4 应0x07060504")

print("\n== 保留的 W 型移位编码：instr[25]=1 (shamt=32) 应非法 ==")
run([ADDI(9, 0, 1), enc_r(0x00, 32, 9, 1, 11, 0x1B)], tag="slliw sh=32")

print("\n== jal x0,0 自旋（死循环，应停在同一条）==")
run([JAL(0, 0), ADDI(9, 0, 1), ADDI(9, 9, 1), ADDI(9, 9, 1)], tag="j0")
run([enc_r(0, 0, 0, 0, 0, 0x63), ADDI(9, 0, 1)], tag="beq x0,x0,0")

print("\n== 未实现 CSR：trace 报出 csr_new，机器里其实没有 ==")
from vriss.encode import CSRRW, CSRRS
bus = Bus()
bus.load_image(0x1000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                               for w in [LUI(9, 0x12345), ADDI(9, 9, 0), CSRRW(0, 0x7F0, 9),
                                         CSRRS(10, 0x7F0, 0)]))
iss = VrIss(bus=bus, reset_pc=0x1000)
iss.csr[Csr.MTVEC] = 0x2000
for _ in range(4):
    r = iss.step()
    print(f"   pc=0x{r.pc:x} str={r.instr_str:8s} csr_wr_en={r.csr_wr_en} "
          f"csr_field={r.csr_field()!r} x10=0x{iss.regs[10]:x}")

print("\n== mcycle 写后读回与 trace 自相矛盾 ==")
bus = Bus()
bus.load_image(0x1000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                               for w in [LUI(9, 0), ADDI(9, 9, 0x7B), CSRRW(0, 0xB00, 9),
                                         CSRRS(10, 0xB00, 0)]))
iss = VrIss(bus=bus, reset_pc=0x1000)
for _ in range(4):
    r = iss.step()
    print(f"   pc=0x{r.pc:x} str={r.instr_str:8s} csr_field={r.csr_field()!r} "
          f"实际 csrr 读回 x10=0x{iss.regs[10]:x}")
