"""临时取证脚本（只读探测，用完即删）。"""
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iss"))

from vriss import Bus, VrIss, link, Csr, Exc                          # noqa
from vriss.encode import *                                             # noqa

MASK64 = (1 << 64) - 1
CODE = 0x1000
STOP = BEQ(0, 0, 0)          # 自循环终止器


def go(prog, init=None, n=None, pc=CODE):
    words = list(prog) + [STOP]
    img = link([(CODE, words)])
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=pc)
    for r, v in (init or {}).items():
        iss.regs[r] = v & MASK64
    try:
        iss.run(max_instr=n or (len(words) + 2))
    except Exception as e:
        print(f"    !! CRASH {type(e).__name__}: {e}")
        return None, None
    return iss, iss.records


def show(tag, iss, recs, keys=()):
    if iss is None:
        print(f"  {tag}: CRASH")
        return
    head = [f"{r.pc:08x} {r.instr:08x} {r.instr_str or '?'}"
            f"{' EXC' + str(r.exc_cause) if r.exc_v else ''}" for r in recs[:4]]
    reg = " ".join(f"x{k}=0x{iss.regs[k]:016x}" for k in keys)
    print(f"  {tag}: {reg} | mcause={iss.csr.get(0x342)} mtval=0x{iss.csr.get(0x343,0):x} "
          f"| {' ; '.join(head)}")


print("=== (a) 指令语义 ===")
a, b = 0xFFFF_FFFF_8000_0000, 8
iss, recs = go([SRA(1, 2, 3)], {2: a, 3: b}); show(f"SRA 0x{a:x}>>8  期望 0xffffffffff800000", iss, recs, (1,))
iss, recs = go([SRL(1, 2, 3)], {2: a, 3: b}); show(f"SRL 同上      期望 0x00ffffff_f8000000", iss, recs, (1,))
iss, recs = go([SRAI(1, 2, 63)], {2: a}); show("SRAI 63         期望 -1", iss, recs, (1,))
iss, recs = go([SUBW(1, 2, 3)], {2: 5, 3: 3}); show("SUBW 5-3        期望 2", iss, recs, (1,))
iss, recs = go([ADDW(1, 2, 3)], {2: 5, 3: 3}); show("ADDW 5+3        期望 8", iss, recs, (1,))
iss, recs = go([SUBW(1, 2, 3)], {2: MASK64, 3: 1}); show("SUBW -1-1       期望 0xffff...fffe", iss, recs, (1,))
iss, recs = go([ADDIW(1, 0, 2047)], {}); show("ADDIW x0,2047   期望 2047", iss, recs, (1,))
iss, recs = go([ADDIW(1, 0, 40)], {}); show("ADDIW x0,40     期望 40", iss, recs, (1,))
iss, recs = go([ADDIW(1, 0, 5)], {}); show("ADDIW x0,5      期望 5", iss, recs, (1,))
iss, recs = go([SLLIW(1, 2, 40)], {2: 1}); show("SLLIW sh=40     期望 illegal", iss, recs, (1,))

print("--- load 宽度 ---")
base = [LUI(2, 0x40001)]                      # x2 = 0x4000_1000
img = link([(CODE, base + [LBU(1, 2, 0), STOP])])
bus = Bus(); bus.load_image(img.start, img.to_bytes())
bus.write(0x4000_1000, 8, 0x1122_3344_5566_77FF)
iss = VrIss(bus=bus, reset_pc=CODE)
try:
    iss.run(6)
    print(f"  LBU  @0x40001000 -> x1=0x{iss.regs[1]:x} 期望 0xff  mcause={iss.csr.get(0x342)}")
except Exception as e:
    print(f"  LBU CRASH {e}")
for nm, mk in (("LHU", LHU), ("LWU", LWU), ("LD", LD)):
    img = link([(CODE, base + [mk(1, 2, 0), STOP])])
    bus = Bus(); bus.load_image(img.start, img.to_bytes())
    bus.write(0x4000_1000, 8, 0x1122_3344_5566_77FF)
    iss = VrIss(bus=bus, reset_pc=CODE)
    try:
        iss.run(6)
        print(f"  {nm:3s} -> x1=0x{iss.regs[1]:016x} mcause={iss.csr.get(0x342)}")
    except Exception as e:
        print(f"  {nm} CRASH {e}")

print("--- 分支/跳转 ---")
iss, recs = go([(2 << 12) | 0x63], {}); show("BRANCH f3=2 (期望 illegal)", iss, recs)
iss, recs = go([JAL(0, 0)], {}); print(f"  jal x0,0 自循环: 退休 {len(recs)} 条, pc 序列 {sorted({r.pc for r in recs})}  (期望只有 0x1000)")
iss, recs = go([BEQ(0, 0, 0)], {}); print(f"  beq x0,x0,0 自循环: 退休 {len(recs)} 条, pc {sorted({r.pc for r in recs})}")
iss, recs = go([(0 << 31) | (0 << 12) | (0 << 20) | (0 << 7) | 0x6F | (2 << 12)], {})
show("jal x0,+2 (无 C 时应 illegal/misaligned)", iss, recs)

print("=== (b) M 扩展 ===")
cases = [
    ("DIV  -2^63/-1", DIV, -(1 << 63), -1, 1 << 63),
    ("REM  -2^63%-1", REM, -(1 << 63), -1, 0),
    ("DIV  7/-2", DIV, 7, -2, -3),
    ("REM  7/-2", REM, 7, -2, 1),
    ("REM -7/2", REM, -7, 2, -1),
    ("DIVU 7/0", DIVU, 7, 0, MASK64),
    ("REMU 7/0", REMU, 7, 0, 7),
    ("MULHU ff*ff", MULHU, MASK64, MASK64, (MASK64 * MASK64) >> 64),
    ("MULH -1*-1", MULH, -1, -1, 0),
    ("MULHSU -1*1", MULHSU, -1, 1, (-(1 << 64) + MASK64) >> 64),
    ("MULHSU 1*-1", MULHSU, 1, -1, 0xFFFFFFFF7FFFFFFF),
    ("DIV -1/1", DIV, -1, 1, MASK64),
]
for name, mk, x, y, want in cases:
    iss, recs = go([mk(1, 2, 3)], {2: x, 3: y})
    got = iss.regs[1] if iss else None
    ok = "OK" if got == (want & MASK64) else "<<< MISMATCH"
    print(f"  {name:16s} got=0x{(got or 0):016x} want=0x{want & MASK64:016x} {ok}")

print("=== (c) CSR / trap ===")
iss, recs = go([CSRRW(0, 0x300, 2), CSRRS(1, 0x300, 0)], {2: MASK64})
print(f"  CSRRW mstatus<-all1: trace csr 列={[r.csr_field() for r in recs if r.csr_wr_en]}")
print(f"     实际 mstatus=0x{iss.csr.get(0x300):016x} / 下一条 CSRRS 读回 x1=0x{iss.regs[1]:016x}")
iss, recs = go([CSRRW(0, 0x301, 2)], {2: 0})
print(f"  CSRRW misa<-0: trace={[r.csr_field() for r in recs if r.csr_wr_en]} 实际 misa=0x{iss.csr.get(0x301):x}")
iss, recs = go([CSRRW(0, 0x300, 2), MRET()], {2: 2 << 11})
print(f"  mstatus.MPP=2 保留值: 写入被接受? mstatus=0x{iss.csr.get(0x300):x} -> MRET 见上 CRASH?")
iss, recs = go([CSRRW(1, 0x7F0, 2)], {2: 5})
print(f"  csrrw 0x7f0(不存在): x1=0x{iss.regs[1]:x} mcause={iss.csr.get(0x342)} keys={[hex(k) for k in iss.csr]}")
iss, recs = go([CSRRW(1, 0xC00, 2)], {2: 5})
print(f"  csrrw 0xc00(只读): mcause={iss.csr.get(0x342)}")
iss, recs = go([CSRRS(1, 0xC00, 0)], {})
print(f"  csrrs x1,0xc00,x0(纯读只读 CSR): mcause={iss.csr.get(0x342)} (期望无异常)")
iss, recs = go([EBREAK(), ADDI(0, 0, 0x7FF)], {})
print(f"  EBREAK: mepc=0x{iss.csr.get(0x341):x} mtval=0x{iss.csr.get(0x343):x} (mtval 应为 0 或本指令 VA)")
iss, recs = go([MRET()], {})
print(f"  MRET@M态: priv={iss.priv} pc=0x{iss.pc:x} mstatus=0x{iss.csr.get(0x300):x}")
iss, recs = go([(1 << 7) | 0x73], {})
print(f"  ecall 变体 rd=x1 (保留编码): mcause={iss.csr.get(0x342)} mnem={recs[0].instr_str!r}")
iss, recs = go([(0x18 << 25) | (1 << 7) | 0x73], {})
print(f"  mret 变体 rd=x1 (保留编码): pc=0x{iss.pc:x} mcause={iss.csr.get(0x342)}")

print("--- 取指 fault 是否入 trace ---")
img = link([(CODE, [ADDI(1, 0, 1)])])
bus = Bus(); bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=0x5000_0000)
n = iss.run(6)[0]
print(f"  reset_pc 落在无 PMA 区: step 返回记录数={len(iss.records)} run()={n} pc=0x{iss.pc:x}")
r = iss.step()
print(f"  单次 step() 返回 rec: valid={r.valid} exc_v={r.exc_v} cause={r.exc_cause} "
      f"但该 rec 不在 iss.records 里 -> {r in iss.records}")

print("--- 中断 ---")
iss2 = VrIss(bus=bus, reset_pc=CODE)
iss2.csr[Csr.MIE] = 1 << 7
iss2.csr[Csr.MSTATUS] = 1 << 3
iss2.inject_interrupt(__import__("vriss").Intr.MTI)
img = link([(CODE, [ADDI(1, 0, 1), ADDI(2, 0, 2), STOP])])
iss2 = VrIss(bus=Bus(), reset_pc=CODE)
iss2.bus.load_image(img.start, img.to_bytes())
iss2.csr[Csr.MIE] = 1 << 7
iss2.csr[Csr.MSTATUS] = 1 << 3
iss2.inject_interrupt(__import__("vriss").Intr.MTI)
iss2.run(6)
print("  ", [(f"{r.pc:08x}", r.instr_str, r.exc_v, r.exc_cause, r.is_intr) for r in iss2.records])
print(f"     mcause=0x{iss2.csr[Csr.MCAUSE]:x} mepc=0x{iss2.csr[Csr.MEPC]:x} "
      f"mtval=0x{iss2.csr[Csr.MTVAL]:x} mtvec 未设置 -> pc=0x{iss2.pc:x}")

print("=== (d) 其它 ===")
iss, recs = go([LUI(2, 0x40001), LW(1, 2, 0)], {})
print(f"  读从未写过的 DRAM 页 0x40001000: mcause={iss.csr.get(0x342)} (5=load access fault)")
print(f"  同一地址 dump_region 返回 {bus.dump_region(0x4000_1000, 4)!r}")
img = link([(CODE, [JAL(0, 0)])])
bus2 = Bus(); bus2.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus2, reset_pc=CODE)
n, recs = iss.run(50)
print(f"  死循环 jal：run 静默返回 n={n} halted={iss.halted}（无 watchdog 报错）")
