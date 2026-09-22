import sys
sys.path.insert(0, r'd:\virtual_riscv\iss')
from vriss.mem import Bus
from vriss.machine import VrIss
from vriss.encode import LUI, ADDI, JALR, JAL, link

prog = [
    LUI(9, 0x1),        # x9 = 0x1000
    ADDI(9, 9, 1),      # x9 = 0x1001 -> 奇数
    JALR(1, 9, 0),      # 目标 (0x1001)&~1 = 0x1001，未对齐，应 instr-address-misaligned
    ADDI(2, 0, 7),      # 不应执行
    LUI(9, 0x2),        # 让 PC 有地方可去
]
img = link([(0x1000, prog)])
bus = Bus()
bus.load_image(img.start, img.to_bytes())
iss = VrIss(bus=bus, reset_pc=0x1000, tohost_addr=None)
for _ in range(4):
    r = iss.step()
    print(f"pc=0x{r.pc:08x} bin=0x{r.instr:08x} exc_v={r.exc_v} cause={r.exc_cause} "
          f"rd_wb_en={r.rd_wb_en} rd=x{r.rd_idx} data=0x{r.rd_data:x} "
          f"gpr列='{r.gpr_field()}' mcause={iss.csr.get(0x342,0)} mepc=0x{iss.csr.get(0x341,0):x}")
print("x1 实际 =", hex(iss.regs[1]), " 期望：trapping 的 JALR 不得写 x1")
