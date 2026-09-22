#!/usr/bin/env python3
"""探针 3：trap/中断/mstatus/mem/编码器范围检查。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import MStatus, Priv, Exc, Csr
from vriss.encode import (ADDI, LUI, CSRRW, CSRRS, CSRRWI, ECALL, EBREAK, SW, LW, SD, LD,
                          MRET, enc_r, OP_SYSTEM, enc_i, JAL, BEQ)
BASE = 0x1000
H = 0x1100


def fresh(words, extra=None, tohost=None, handler_addr=H):
    bus = Bus()
    for a, ws in words.items():
        bus.load_image(a, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in ws))
    iss = VrIss(bus=bus, reset_pc=BASE, tohost_addr=tohost)
    iss.csr[Csr.MTVEC] = handler_addr
    if extra:
        extra(iss)
    return iss, bus


print("=== 1. mstatus.MPP=2（保留值）-> MRET 崩 ===")
# 主序：csrw mstatus, (2<<11)  ;  mret
iss, _ = fresh({BASE: [ADDI(9, 0, 2), enc_r(0, 0, 0, 2, 0, 0x73) if False else
                       CSRRW(0, 0x300, 9), MRET()],
                H: [ADDI(11, 0, 0x5a)]})
iss.csr[Csr.MSTATUS] = int(MStatus.MIE)      # MIE=1，MPP=0
try:
    for _ in range(4):
        iss.step()
    print("  无异常，records=", [(hex(r.pc), r.instr_str, int(r.exc_cause)) for r in iss.records])
except Exception as e:
    print(f"  ★Python 崩：{type(e).__name__}: {e}")

print("\n=== 2. EBREAK 的 mtval（应 0 或 ebreak 自身 pc）===")
iss, _ = fresh({BASE: [ADDI(9, 0, 1), EBREAK(), ADDI(9, 9, 1)],
                H: [MRET()]})
for _ in range(4):
    iss.step()
r = [x for x in iss.records if x.exc_v][0]
print(f"  ebreak pc=0x{r.pc:x}  mepc=0x{iss.csr[Csr.MEPC]:x}  mtval=0x{iss.csr[Csr.MTVAL]:x}"
      f"  (mtval 落在 pc+4，即已自增后的 pc)")

print("\n=== 3. trap 进入的 mstatus 6 步 + MRET 复原 ===")
iss, _ = fresh({BASE: [ECALL()], H: [MRET()]})
iss.csr[Csr.MSTATUS] = int(MStatus.MIE) | int(MStatus.MPIE) | (int(Priv.MACHINE) << 11)
for _ in range(3):
    iss.step()
m_after_trap = iss.csr[Csr.MSTATUS]
print(f"  ECALL 前 mstatus=0x{int(MStatus.MIE)|int(MStatus.MPIE)|(3<<11):x} -> 陷阱后 0x{m_after_trap:x}"
      f"  (MIE={bool(m_after_trap & MStatus.MIE)}, MPIE={bool(m_after_trap & MStatus.MPIE)},"
      f" MPP={(m_after_trap >> 11) & 3})")

print("\n=== 4. mtvec=Vectored：中断 base+4*cause / 同步异常 base ===")
for mode, label in ((0, "Direct"), (1, "Vectored"), (2, "Reserved MODE=2"), (3, "Reserved MODE=3")):
    iss, _ = fresh({BASE: [ADDI(9, 0, 1), ADDI(9, 9, 1), ADDI(9, 9, 1), ADDI(9, 9, 1)],
                    H: [ADDI(11, 0, 0xaa)]})
    iss.csr[Csr.MTVEC] = H | mode
    iss.csr[Csr.MIE] = 1 << 7                      # MTIE
    iss.csr[Csr.MSTATUS] = int(MStatus.MIE)        # 全局 MIE=1（M 态下也放行）
    iss.inject_interrupt(__import__("vriss.consts", fromlist=["Intr"]).Intr.MTI)
    for _ in range(2):
        r = iss.step()
    tgt = iss.csr[Csr.MEPC], iss.pc
    print(f"  {label:16s} 第一条指令 pc=0x{BASE:x} -> 中断后 pc=0x{iss.pc:x}"
          f"  (base+4*7=0x{H + 28:x});  mcause=0x{iss.csr[Csr.MCAUSE]:x}")

print("\n=== 5. 中断退休记录：被中断指令仍进 trace 且 seq 双计 ===")
iss, _ = fresh({BASE: [ADDI(9, 0, 1), ADDI(9, 9, 1)], H: [MRET()]})
iss.csr[Csr.MIE] = 1 << 7
iss.csr[Csr.MSTATUS] = int(MStatus.MIE)
iss.inject_interrupt(__import__("vriss.consts", fromlist=["Intr"]).Intr.MTI)
recs = []
for _ in range(4):
    recs.append(iss.step())
print("  退休序列：")
for r in iss.records:
    print(f"    pc=0x{r.pc:x} instr=0x{r.instr:08x} str={r.instr_str!r} exc_v={r.exc_v} "
          f"is_intr={r.is_intr} rd={r.rd_idx} wb={r.gpr_field()}")
print(f"  seq(=minstret 读回)={iss.seq}, 实际执行过的指令字条数=2 (ADDI 各一次) + 1 中断记录")

print("\n=== 6. mip 可被软件随意写 -> 造出 DUT 不可能有的中断 ===")
iss, _ = fresh({BASE: [LUI(9, 0x0), ADDI(9, 9, 0x400), CSRRW(0, 0x344, 9), ADDI(9, 9, 7)],
                H: [MRET()]})
iss.csr[Csr.MSTATUS] = int(MStatus.MIE)
x9_before = None
for _ in range(5):
    iss.step()
print(f"  csrw mip,0x400 之后：records={[(hex(r.pc), r.instr_str, int(r.exc_cause), r.is_intr) for r in iss.records]}")

print("\n=== 7. 读从未写过的页（.bss 场景）===")
bus = Bus()
bus.load_image(0x4000_0000, b"\x11" * 8)          # 只分配第一页
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[Csr.MTVEC] = H
iss.pc = 0x4000_1000                              # 未分配页
iss.bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in [0]))
bus.write(0x4000_1000, 4, int(LW(10, 0, 0x1000 >> 12 if False else 0) & 0xFFFFFFFF)) if False else None
# 直接在 0x40001000 放一条 lui+lw 序列
bus.load_image(0x4000_1000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                                     for w in [LUI(9, 0x40002), LW(10, 9, 0)]))
iss.pc = 0x4000_1000
for _ in range(3):
    r = iss.step()
    print(f"    step pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} "
          f"mtval=0x{iss.csr[Csr.MTVAL]:x} 在 records 里={r in iss.records}")

print("\n=== 8. 载入地址 0（fault tval=0）被兜底改成指令字 ===")
bus = Bus()
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [ADDI(9, 0, 0), LW(10, 9, 0)]))
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[Csr.MTVEC] = H
for _ in range(3):
    r = iss.step()
print(f"  lw 从地址 0 读：mtval=0x{iss.csr[Csr.MTVAL]:x}  "
      f"(应为 0，实得兜底值=指令字 0x{0x0004A503:x})  记录数={len(iss.records)}")

print("\n=== 9. 编码器范围检查漏洞 ===")
from vriss.encode import CSRRW as CSRRW_f, LUI as LUI_f, SLLI as SLLI_f, ADDI as ADDI_f, enc_j
try:
    w = CSRRW_f(1, 0x1234, 2)          # CSR 地址 12 位越界
    print(f"  CSRRW(rd=1, csr=0x1234) -> 0x{w:08x} 未报错；csr 域实得 0x{(w >> 20) & 0xFFF:x}"
          f"（静默截断成另一个 CSR）")
except ValueError as e:
    print("  CSRRW csr 越界被拦（不符合预期）:", e)
try:
    w = LUI_f(1, 0x123456)             # 20 位越界
    print(f"  LUI(1, 0x123456) -> 0x{w:08x} imm20 实得 0x{(w >> 12) & 0xFFFFF:x}（静默截断）")
except ValueError as e:
    print("  LUI 越界被拦:", e)
try:
    w = ADDI_f(1, 2, 0x800)
    print("  ADDI 越界应报错:", e)
except ValueError:
    print("  ADDI 0x800 -> ValueError（正确拦住）")
try:
    w = SLLI_f(1, 2, 64)
    print(f"  SLLI(1,2,64) -> 0x{w:08x} 未报错，instr[25:20]=0x{(w >> 20) & 0x3F:x}"
          f" instr[31:26]=0x{(w >> 26) & 0x3F:x}（移位量被吃掉一位）")
except ValueError as e:
    print("  SLLI 越界被拦:", e)
try:
    w = enc_r(0x00, 0x20, 2, 0, 1, 0x33)   # rs2=32 越界
    print(f"  enc_r(rs2=0x20) -> 0x{w:08x} 未报错（rs2 域溢出进 funct7，静默编成另一条指令）")
except ValueError as e:
    print("  enc_r 越界被拦:", e)
try:
    from vriss.encode import BEQ as BEQ_f
    print(f"  BEQ 奇数偏移: ", end="")
    BEQ_f(1, 2, 5)
    print("未报错（★应报错）")
except ValueError as e:
    print("ValueError（正确拦住）:", e)

print("\n=== 10. signature 窗口：非 8 字节写 / 读 ===")
bus = Bus()
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [LUI(9, 0x20000), ADDI(9, 9, 0), SW(0, 9, 0), SD(0, 9, 0)]))
iss = VrIss(bus=bus, reset_pc=BASE, tohost_addr=None)
iss.csr[Csr.MTVEC] = H
for _ in range(5):
    r = iss.step()
    print(f"  pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} "
          f"mem_wr={r.mem_wr} signature_writes={bus.signature_writes}")
