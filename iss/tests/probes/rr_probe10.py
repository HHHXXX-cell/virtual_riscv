import sys
sys.path.insert(0, r'd:\virtual_riscv\iss')
from vriss.mem import Bus
from vriss.machine import VrIss
from vriss.encode import LUI, ADDI, JAL, link

print("=== P1: JAL 目标 = 0x1002 (mod4==2)，RV64I 无 C 时应 instr-address-misaligned ===")
prog = [JAL(0, 2), ADDI(1, 0, 1), ADDI(2, 0, 2)]
img = link([(0x1000, prog)])
bus = Bus()
bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=0x1000, tohost_addr=None)
for i in range(3):
    r = iss.step()
    print(f" step{i}: pc=0x{r.pc:08x} bin=0x{r.instr:08x} exc_v={r.exc_v} cause={r.exc_cause} "
          f"tval=->mcause={iss.csr.get(0x342,0)} mtval=0x{iss.csr.get(0x343,0):x}")
print(" _branch 的 `target & 1` 判据实测放行 0x1002；此后 pc 落到 0x1002")
print(" run() 再跑 6 步：records 是否增长？")
n0, recs0 = len(iss.records), iss.records
for i in range(6):
    iss.step()
print(f"   6 步后 len(records) {n0} -> {len(iss.records)}   cycle={iss.cycle} seq={iss.seq}")
print(f"   全部记录 pc: {[hex(r.pc) for r in iss.records]}")

print()
print("=== P2: JALR 目标 &~1 使 `target & 1` 永不可达（死代码证明）===")
prog2 = [LUI(9, 0x1), ADDI(9, 9, 3), JALR(1, 9, 0)]   # 0x1003 & ~1 = 0x1002
img2 = link([(0x2000, prog2)])
b2 = Bus(); b2.load_image(img2.start, img2.to_bytes())
i2 = VrIss(bus=b2, reset_pc=0x2000, tohost_addr=None)
for k in range(3):
    rr = i2.step()
    print(f" step{k}: pc=0x{rr.pc:08x} exc_v={rr.exc_v} cause={rr.exc_cause} -> pc_now=0x{i2.pc:08x} "
          f"x1=0x{i2.regs[1]:x}")
print(" 目标被 ~1 掩成 0x1002，L425 的 &1 判据形同不存在")
