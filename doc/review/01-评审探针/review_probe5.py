"""临时取证脚本 5（用完即删）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "iss"))

from vriss import Bus, VrIss, link, Csr                                 # noqa
from vriss.encode import *                                               # noqa

CODE, HDL = 0x1000, 0x1080
STOP = BEQ(0, 0, 0)


def mk(prog, extra=None):
    parts = [(CODE, list(prog) + [STOP]), (HDL, [STOP])]
    if extra:
        parts.append(extra)
    img = link(parts)
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(img.start, img.to_bytes())
    return bus


def go(prog, extra=None, steps=None):
    iss = VrIss(bus=mk(prog, extra), reset_pc=CODE)
    iss.csr[Csr.MTVEC] = HDL
    iss.run(max_instr=steps or (len(prog) + 3))
    return iss


print("1) load access fault 于 VA=0")
iss = go([ADDI(2, 0, 0), LW(1, 2, 0)])
r = iss.records[1]
print(f"   lw x1,0(x0=0) -> rec1 pc=0x{r.pc:x} instr=0x{r.instr:08x} exc={r.exc_v} "
      f"cause={r.exc_cause} | mtval=0x{iss.csr[Csr.MTVAL]:x} (规范要求 = 0，出错地址)")

print("2) store 到 DEVICE 窗口但无设备挂载")
iss = go([LUI(2, 0x0), ADDI(2, 2, 0), ADDI(3, 0, 7), SW(3, 2, 0x40)])
r = iss.records[3]
print(f"   sw 到 0x40（reset/ROM device 窗，未挂设备）: exc={r.exc_v} "
      f"pages[0] 被写入? {bytes(iss.bus.pages.get(0, bytearray(4))[0x40:0x44])!r}")

print("3) mcycle 写入后读回")
iss = go([CSRRW(0, 0xB00, 2), CSRRS(1, 0xB00, 0)], steps=4)
iss.regs[2] = 12345
iss2 = go([LUI(2, 0x8), ADDI(2, 2, 0x3E9), CSRRW(0, 0xB00, 2), CSRRS(1, 0xB00, 0)], steps=5)
print(f"   csrrw mcycle<-x2(=0x{iss2.regs[2]:x}) 后 csrrs 读回 x1=0x{iss2.regs[1]:x} "
      f"(dict 存了 0x{iss2.csr.get(0xB00, 0):x}) -> 写入被静默丢弃")

print("4) minstret / mcycle 计数口径")
print(f"   csr[MINSTRET] 读回函数在 csr_read 里返回 self.seq；"
      f"seq 只在非取指异常路径自增 -> 与真实退休数不一致")

print("5) sstatus/sie 与 mstatus/mie 的别名")
iss = go([ADDI(2, 0, 0x202), CSRRW(0, 0x304, 2), CSRRS(1, 0x104, 0)], steps=4)
print(f"   mie<-0x202 后读 sie: x1=0x{iss.regs[1]:x} (规范：sie 是 mie 的视图，应=0x2)")
iss = go([ADDI(2, 0, 0x103), CSRRW(0, 0x100, 2), CSRRS(1, 0x300, 0)], steps=4)
print(f"   sstatus<-0x103 后读 mstatus: x1=0x{iss.regs[1]:x}")
iss = go([ADDI(2, 0, 8), CSRRW(0, 0x100, 2)], steps=3)
print(f"   sstatus<-bit3 写入是否被丢弃: mstatus=0x{iss.csr.get(0x300, 0):x} (期望 0)")

print("6) 取指权限：从 PLIC/CLINT 设备窗取指")
iss = go([LUI(2, 0x0C000), JALR(0, 2, 0)], steps=3)
print(f"   jalr 到 0x0C000000（PLIC device 窗）: mcause={iss.csr.get(Csr.MCAUSE)} "
      f"mepc=0x{iss.csr.get(Csr.MEPC):x} (PMA 无 X 权限概念)")
