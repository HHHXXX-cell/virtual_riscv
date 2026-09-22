#!/usr/bin/env python3
"""独立语义评审探针 1：移位/SRA/SRAI/SRAIW 位段。只读仓库，不修改任何文件。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.encode import (SRA, SRL, SRAI, SRAIW, ADDI, LUI, OP_OP, OP_OP_IMM,
                          OP_OP_IMM32, enc_r)

BASE = 0x1000


def make(words):
    bus = Bus()
    bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                                  for w in words))
    iss = VrIss(bus=bus, reset_pc=BASE)
    return iss


def show(tag, words, regs, steps=12):
    iss = make(words)
    excs = []
    for _ in range(steps):
        if iss.pc >= BASE + 4 * len(words) + 0x100:      # 越界 -> 停
            break
        try:
            r = iss.step()
            if r.exc_v:
                excs.append((hex(r.pc), int(r.exc_cause)))
        except Exception as e:
            excs.append(("PY-EXC", type(e).__name__ + ":" + str(e)))
            break
        if iss.pc == BASE + 4 * len(words):
            break
    print(f"--- {tag}")
    print("    words:", " ".join(f"0x{w & 0xFFFFFFFF:08x}" for w in words))
    for r in regs:
        print(f"    x{r} = 0x{iss.regs[r]:016x}")
    print(f"    异常/错误: {excs}")
    print(f"    mcause={iss.csr.get(0x342)} mepc=0x{iss.csr.get(0x341,0):x} "
          f"mtval=0x{iss.csr.get(0x343,0):x}  trace_len={len(iss.records)}")
    return iss


# 负数被移位对象：x9 = 0xFFFFFFFF00000000（bit63=1）
NEG = [LUI(9, 0x80000),                 # x9 = 0xFFFFFFFF80000000 (sext32)
       enc_r(0x00, 1, 9, 1, 9, OP_OP_IMM),   # x9 <<= 1 -> 0x0000000100000000? 见输出
       ]

print("== 证据1：R 型 SRA（寄存器右移）==")
print(f"   encode.SRA(11,9,10) = 0x{SRA(11, 9, 10):08x}   (funct7=0x20 -> instr[30]=1，编码本身正确)")
print(f"   encode.SRL(12,9,10) = 0x{SRL(12, 9, 10):08x}")
w1 = [LUI(9, 0x80000),          # x9 = 0xFFFFFFFF80000000 (bit63 = 1)
      ADDI(10, 0, 4),
      SRA(11, 9, 10),           # 应为 0xFFFFFFFFFF800000
      SRL(12, 9, 10),           # 应为 0x03FFFFFFFE000000
      ]
show("SRA vs SRL, x9=0xFFFFFFFF80000000, shamt=4", w1, [9, 11, 12])

print("== 证据2：RV64 SRAI 的 funct6 = 010000（bit30），不是 bit31 ==")
real_srai = (0b010000 << 26) | (4 << 25) | (9 << 15) | (5 << 12) | (11 << 7) | 0x13
print(f"   规范 SRAI(11,9,36) = 0x{real_srai:08x}  (shamt=36 需要 instr[25]=1)")
print(f"   encode.SRAI(11,9,36)= 0x{SRAI(11, 9, 36):08x}")
w2 = [LUI(9, 0x80000), ADDI(10, 0, 0), real_srai]
show("执行规范编码的 SRAI", w2, [9, 11])
w3 = [LUI(9, 0x80000), ADDI(10, 0, 0), SRAI(11, 9, 4)]
show("执行 encode.SRAI 的产物", w3, [9, 11])

print("== 证据3：RV64 SRAIW 的 funct6 = 010000 ==")
real_srailiw = (0b010000 << 26) | (4 << 20) | (9 << 15) | (5 << 12) | (11 << 7) | 0x1B
print(f"   规范 SRAIW(11,9,4)   = 0x{real_srailiw:08x}")
print(f"   encode.SRAIW(11,9,4) = 0x{SRAIW(11, 9, 4):08x}")
show("执行规范编码的 SRAIW", [LUI(9, 0x80000), real_srailiw], [9, 11])
show("执行 encode.SRAIW 的产物", [LUI(9, 0x80000), SRAIW(11, 9, 4)], [9, 11])

print("== 证据4：W 型移位量越界（imm[5]!=0 属 reserved）静默变小移位 ==")
bad = enc_r(0x00, 32, 9, 1, 11, OP_OP_IMM32)   # SLLIW x11,x9,32 -> instr[25]=1
print(f"   encode 层 SLLIW(11,9,32) = 0x{bad:08x}（未抛 ValueError）")
show("SLLIW sh=32", [LUI(9, 0x1), bad], [9, 11])

print("== 证据5：SLLI 保留编码 instr[31:26]=100000 被当合法 SLLI ==")
reserved = (0b100000 << 26) | (4 << 20) | (9 << 15) | (1 << 12) | (11 << 7) | 0x13
show("instr[31:26]=100000, funct3=1（规范中保留/非法）", [LUI(9, 0x80000), reserved], [9, 11])
