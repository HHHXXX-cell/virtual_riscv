import sys
sys.path.insert(0, r'd:\virtual_riscv\iss')
from vriss.mem import Bus
from vriss.machine import VrIss
from vriss.encode import LUI, ADDI, SW, link

TOHOST = 0x40002000          # PMA: DRAM CACHEABLE

def once(val, name):
    lo = TOHOST & 0xFFF
    prog = [LUI(9, TOHOST >> 12), ADDI(9, 9, 0), ADDI(10, 0, val), SW(10, 9, lo)]
    img = link([(0x1000, prog)])
    bus = Bus(); bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=0x1000, tohost_addr=TOHOST)
    n, recs = iss.run(max_instr=200)
    cmd_exit = 0 if iss.halt_code == 1 else 1          # __main__.py L47 原样照抄
    print(f"{name:22s} 写 tohost={val:<3d} halted={iss.halted} halt_code={iss.halt_code} "
          f"-> cmd_run 退出码={cmd_exit}  ({'判成功' if cmd_exit==0 else '判失败'})")

once(1, 'riscv-tests PASS')       # 标准：写 1 = PASS
once(3, 'riscv-tests FAIL test 1') # 标准：写 (1<<1)|1 = 3 = 第 1 个用例失败
once(5, 'riscv-tests FAIL test 2')
