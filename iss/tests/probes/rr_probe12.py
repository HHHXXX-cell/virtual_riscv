import sys
sys.path.insert(0, r'd:\virtual_riscv\iss')
from vriss.mem import Bus
from vriss.machine import VrIss
from vriss.consts import Csr, Exc, MASK64
from vriss.encode import *
from vriss.encode import enc_r, enc_i, enc_s, enc_b, enc_u, link

OP_SYSTEM = 0x73
def csrrw(rd, csr, rs1): return enc_i(csr, rs1, 1, rd, OP_SYSTEM)
def csrrs(rd, csr, rs1): return enc_i(csr, rs1, 2, rd, OP_SYSTEM)

def fresh(prog, pc=0x1000, extra=None):
    img = link([(pc, prog)])
    bus = Bus()
    if extra:
        bus.load_image(extra[0], extra[1].to_bytes())
    bus.load_image(img.start, img.to_bytes())
    return VrIss(bus=bus, reset_pc=pc, tohost_addr=None)

print('--- (a) mepc 是否 WARL 强制 [1:0]=0 ---')
iss = fresh([csrrw(0, Csr.MEPC, 9)])
iss.regs[9] = 0xFFFFFFFF_FFFFFFFF
r = iss.step()
print('  csrw mepc, -1 -> 读回 0x%016x  (架构上应读回 0x...fffc 或更少位)' % iss.csr[Csr.MEPC])
print('  MRET 隐式读 mepc 是否掩码 ->')
iss2 = fresh([csrrw(0, Csr.MEPC, 9), MRET()])
iss2.regs[9] = 0x1235
for _ in range(2): iss2.step()
print('    csrw mepc,0x1235; mret -> pc=0x%x (应为 0x1234)' % iss2.pc)

print('--- (b) mip 的 MTIP/MSIP/MEIP(7/3/11) 是否可写 ---')
iss = fresh([csrrw(0, Csr.MIP, 9)])
iss.regs[9] = (1 << 7) | (1 << 3) | (1 << 11)
iss.step()
print('  csrw mip, 0x888 -> 读回 0x%x  (规范：MTIP/MSIP/MEIP 在 mip 中 read-only)' % iss.csr[Csr.MIP])

print('--- (c) mtvec MODE 保留值 2/3 ---')
for mode in (0, 1, 2, 3):
    iss = fresh([csrrw(0, Csr.MTVEC, 9), ECALL()])
    iss.regs[9] = 0x1100 | mode
    iss.step()
    st = iss.csr_read(Csr.MTVEC)
    iss.step()
    print(f'  写 mode={mode}: mtvec 读回=0x{st:x}  ecall 后 pc=0x{iss.pc:x} '
          f'(mode>=2 规范为 Reserved，应落回 0/1)')

print('--- (d) mstatus.MPP 写保留值 2 后 MRET ---')
iss = fresh([LUI(9, 0x8), ADDI(9, 9, 0), CSRRW_x := csrrw(0, Csr.MSTATUS, 9), MRET()]) if False else None
iss = fresh([csrrw(0, Csr.MSTATUS, 9), MRET()])
iss.regs[9] = 2 << 11           # MPP = 2b10 (保留)
iss.step()
print('  csrw mstatus, MPP=2 -> 读回 0x%016x (MPP 字段=%d)' % (iss.csr[Csr.MSTATUS], (iss.csr[Csr.MSTATUS] >> 11) & 3))
try:
    iss.step()
    print('  MRET -> priv=%d' % iss.priv)
except Exception as e:
    print('  MRET -> !! Python 层异常：%s: %s   (应为 illegal-instruction 或 MPP 归 0)' % (type(e).__name__, e))

print('--- (e) LBU / LHU 实际读宽度 ---')
img = link([(0x1000, [LUI(9, 0x40000), ADDI(9, 9, 0x10), enc_i(0, 9, 4, 10, 0x03),
                       enc_i(0, 9, 5, 11, 0x03)])])
bus = Bus(); bus.load_image(img.start, img.to_bytes())
for i in range(8):
    bus.write(0x40000010 + i, 1, 0x10 + i)
iss = VrIss(bus=bus, reset_pc=0x1000)
rs = [iss.step() for _ in range(4)]
print('  LBU  x10 -> 0x%016x   rec.mem_size=%d   (规范 0x10, size=1)' % (iss.regs[10], rs[2].mem_size))
print('  LHU  x11 -> 0x%016x   rec.mem_size=%d   (规范 0x2120, size=2)' % (iss.regs[11], rs[3].mem_size))
iss2 = fresh([LUI(9, 0x40000), ADDI(9, 9, 5), enc_i(0, 9, 4, 10, 0x03)])
rr = [iss2.step() for _ in range(3)]
print('  LBU 奇地址 0x40000005 -> exc_v=%d cause=%d (=%s)  规范要求：自然对齐不得报 misaligned'
      % (rr[2].exc_v, rr[2].exc_cause, Exc(rr[2].exc_cause).name if rr[2].exc_v else '-'))

print('--- (f) R 型 SRA vs SRL ---')
iss = fresh([ADDI(9, 0, -1) if False else LUI(9, 0x80000), enc_r(0x20, 10, 9, 5, 11, 0x33),
             enc_r(0x00, 10, 9, 5, 12, 0x33)])
iss.regs[10] = 4
rs = [iss.step() for _ in range(3)]
print('  x9=0x%016x  SRA-> x11=0x%016x  SRL-> x12=0x%016x  (SRA 应=0xfffffffffffffff8)'
      % (iss.regs[9], iss.regs[11], iss.regs[12]))

print('--- (g) 保留 funct6=100000 的 SLLI 与 SRAI ---')
for nm, w in (('SRAI  funct6=010000(合法)', enc_r(0x10, 4, 9, 5, 11, 0x13)),
              ('SLLI  funct6=100000(保留)', enc_r(0x20, 4, 9, 1, 11, 0x13)),
              ('SRAIW funct6=010000(合法)', enc_r(0x10, 4, 9, 5, 11, 0x1B)),
              ('SRLIW funct6=100000(保留)', enc_r(0x20, 4, 9, 5, 11, 0x1B))):
    iss = fresh([LUI(9, 0x80000), w])
    rs = [iss.step() for _ in range(2)]
    print(f'  {nm}: bin=0x{w:08x} exc_v={rs[1].exc_v} cause={rs[1].exc_cause} x11=0x{iss.regs[11]:016x}')
