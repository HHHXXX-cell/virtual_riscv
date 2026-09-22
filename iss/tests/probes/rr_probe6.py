#!/usr/bin/env python3
"""探针 6：把 encode.py 的每个具名构造器与 riscv-test-env/encoding.h 的
MATCH_*/MASK_*（riscv-tests 官方编码表）逐条对账。
只读外部文件，不改仓库。"""
import re
import sys

sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss.encode import *          # noqa
from vriss import encode as E

HDR = r"D:\IC验证知识库\_tools\ibex-master\vendor\riscv-test-env\encoding.h"
txt = open(HDR, encoding="utf-8", errors="ignore").read()
match = {m.group(1).lower(): int(m.group(2), 16)
         for m in re.finditer(r"#define MATCH_(\w+)\s+(0x[0-9a-fA-F]+)", txt)}
mask = {m.group(1).lower(): int(m.group(2), 16)
        for m in re.finditer(r"#define MASK_(\w+)\s+(0x[0-9a-fA-F]+)", txt)}

RD, RS1, RS2, IM, SHM = 5, 6, 7, -9, 9

CASES = [
    ("lui",     LUI(RD, 0x12345)),
    ("auipc",   AUIPC(RD, 0x12345)),
    ("jal",     JAL(RD, 8)),
    ("jalr",    JALR(RD, RS1, IM)),
    ("beq",     BEQ(RS1, RS2, 8)),
    ("bne",     BNE(RS1, RS2, 8)),
    ("blt",     BLT(RS1, RS2, 8)),
    ("bge",     BGE(RS1, RS2, 8)),
    ("bltu",    BLTU(RS1, RS2, 8)),
    ("bgeu",    BGEU(RS1, RS2, 8)),
    ("lb",      LB(RD, RS1, IM)),
    ("lh",      LH(RD, RS1, IM)),
    ("lw",      LW(RD, RS1, IM)),
    ("ld",      LD(RD, RS1, IM)),
    ("lbu",     LBU(RD, RS1, IM)),
    ("lhu",     LHU(RD, RS1, IM)),
    ("lwu",     LWU(RD, RS1, IM)),
    ("sb",      SB(RS2, RS1, IM)),
    ("sh",      SH(RS2, RS1, IM)),
    ("sw",      SW(RS2, RS1, IM)),
    ("sd",      SD(RS2, RS1, IM)),
    ("addi",    ADDI(RD, RS1, IM)),
    ("slti",    SLTI(RD, RS1, IM)),
    ("sltiu",   SLTIU(RD, RS1, IM)),
    ("xori",    XORI(RD, RS1, IM)),
    ("ori",     ORI(RD, RS1, IM)),
    ("andi",    ANDI(RD, RS1, IM)),
    ("slli",    SLLI(RD, RS1, SHM)),
    ("srli",    SRLI(RD, RS1, SHM)),
    ("srai",    SRAI(RD, RS1, SHM)),
    ("addiw",   ADDIW(RD, RS1, IM)),
    ("slliw",   SLLIW(RD, RS1, SHM)),
    ("srliw",   SRLIW(RD, RS1, SHM)),
    ("sraiw",   SRAIW(RD, RS1, SHM)),
    ("add",     ADD(RD, RS1, RS2)),
    ("sub",     SUB(RD, RS1, RS2)),
    ("sll",     SLL(RD, RS1, RS2)),
    ("slt",     SLT(RD, RS1, RS2)),
    ("sltu",    SLTU(RD, RS1, RS2)),
    ("xor",     XOR(RD, RS1, RS2)),
    ("srl",     SRL(RD, RS1, RS2)),
    ("sra",     SRA(RD, RS1, RS2)),
    ("or",      OR(RD, RS1, RS2)),
    ("and",     AND(RD, RS1, RS2)),
    ("addw",    ADDW(RD, RS1, RS2)),
    ("subw",    SUBW(RD, RS1, RS2)),
    ("sllw",    SLLW(RD, RS1, RS2)),
    ("srlw",    SRLW(RD, RS1, RS2)),
    ("sraw",    SRAW(RD, RS1, RS2)),
    ("mul",     MUL(RD, RS1, RS2)),
    ("mulh",    MULH(RD, RS1, RS2)),
    ("mulhsu",  MULHSU(RD, RS1, RS2)),
    ("mulhu",   MULHU(RD, RS1, RS2)),
    ("div",     DIV(RD, RS1, RS2)),
    ("divu",    DIVU(RD, RS1, RS2)),
    ("rem",     REM(RD, RS1, RS2)),
    ("remu",    REMU(RD, RS1, RS2)),
    ("csrrw",   CSRRW(RD, 0x340, RS1)),
    ("csrrs",   CSRRS(RD, 0x340, RS1)),
    ("csrrc",   CSRRC(RD, 0x340, RS1)),
    ("csrrwi",  CSRRWI(RD, 0x340, 9)),
    ("csrrsi",  CSRRSI(RD, 0x340, 9)),
    ("csrrci",  CSRRCI(RD, 0x340, 9)),
    ("ecall",   ECALL()),
    ("ebreak",  EBREAK()),
    ("mret",    MRET()),
    ("sret",    SRET()),
    ("wfi",     WFI()),
    ("sfence_vma", SFENCE_VMA(RS1, RS2)),
    ("fence",   FENCE()),               # 本仓库生成
    ("fence_i", 0x0000100F),            # 规范权威字
]

bad = 0
for name, word in CASES:
    if name not in match:
        print(f"  ?? {name:12s} encoding.h 无 MATCH_{name.upper()}")
        continue
    ok = (word & mask[name]) == match[name]
    if not ok:
        bad += 1
        print(f"  ★ {name:12s} 本仓库=0x{word:08x}  官方=0x{match[name]:08x}"
              f" (mask=0x{mask[name]:08x})")
print(f"\n编码对账：{len(CASES)} 条，不一致 {bad} 条")

# 反向：把官方 MRET 字喂给 ISS，看它当成什么
print("\n== 把官方 0x30200073 (MRET) 送进 VrIss ==")
from vriss import VrIss, Bus
from vriss.consts import Csr
for w, tag in ((0x30200073, "官方 MRET"), (0x10500073, "官方 WFI"),
               (0x10200073, "官方 SRET"), (0x12000073, "官方 SFENCE.VMA"),
               (0x0000000F, "FENCE(权威字)"), (0x0000100F, "FENCE.I(权威字)"),
               (0x00000000, "全 0 字"),
               (0x00000063, "beq x0,x0,0（合法自旋）"),
               (0x80449593, "保留：SLLI funct6=100000"),
               (0x0204959b, "保留：SLLIW shamt=32"),
               (0x80a4a063, "保留：BRANCH funct3=2")):
    bus = Bus()
    bus.load_image(0x1000, int(w & 0xFFFFFFFF).to_bytes(4, "little"))
    iss = VrIss(bus=bus, reset_pc=0x1000)
    iss.csr[Csr.MTVEC] = 0x1100
    bus.load_image(0x1100, int(JAL(0, 0)).to_bytes(4, "little"))
    try:
        r = iss.step()
        extra = f"exc_v={r.exc_v} cause={int(r.exc_cause)} mnemonic={r.instr_str!r}"
    except Exception as e:
        extra = f"!!Python {type(e).__name__}: {e}"
    print(f"  {tag:22s} 0x{w:08x} -> {extra}")
