#!/usr/bin/env python3
"""探针 8：tohost 停机码方向（cmd_run 的 exit code）+ run() 截断。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.consts import Csr
from vriss.encode import ADDI, LUI, SW, SD, JAL
from vriss.__main__ import cmd_run

TO = 0x4000_0020


def build(words):
    bus = Bus()
    bus.load_image(0x1000, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in words))
    iss = VrIss(bus=bus, reset_pc=0x1000, tohost_addr=TO)
    n, recs = iss.run(max_instr=1000)
    return iss, n


print("riscv-tests 约定：tohost=1 -> PASS；tohost=(testnum<<1)|1 -> FAIL")
for tag, val in (("PASS(1)", 1), ("FAIL testnum=1 (3)", 3), ("FAIL testnum=2 (5)", 5)):
    hi, lo = (val >> 12) & 0xFFFFF, val & 0xFFF
    iss, n = build([LUI(10, hi), ADDI(10, 10, lo - 0x1000 if lo >= 0x800 else lo),
                    LUI(9, TO >> 12), SD(10, 9, TO & 0xFFF)])
    print(f"  {tag:20s} halt_code={iss.halt_code} "
          f"cmd_run 的判据 `0 if halt_code==1 else 1` -> exit="
          f"{0 if iss.halt_code == 1 else 1}")

print("\n4 字节 sw 到 tohost（RV32 风格 / 半字写）")
iss, n = build([LUI(10, 0), ADDI(10, 10, 1), LUI(9, TO >> 12), SW(10, 9, TO & 0xFFF)])
print(f"  sw 1 -> halted={iss.halted} halt_code={iss.halt_code}")

print("\n未停机（程序跑飞 / watchdog）时 run() 的返回值")
try:
    iss, n = build([JAL(0, 0)])      # jal x0,0 -> 因 PC 前推 bug 会一路跑到全 0 字
except Exception as e:
    print(f"  run() 直接抛 Python 异常：{type(e).__name__}: {e}")
    iss = None
if iss is not None:
    print(f"  run(max_instr=1000) -> n={n} halted={iss.halted} 返回值里没有截断标志")
iss2 = VrIss(bus=Bus(), reset_pc=0x9_0000_0000)   # 未映射地址取指
n2, recs2 = iss2.run(max_instr=200)
print(f"  从不可取指处启动：n={n2} len(records)={len(recs2)} halted={iss2.halted} "
      f"-> trace 完全为空但 run 正常返回")
