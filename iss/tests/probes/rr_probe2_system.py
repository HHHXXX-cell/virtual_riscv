#!/usr/bin/env python3
"""探针 2：SYSTEM 子指令编码 / M 扩展 W 型 / 非法编码空间 / trace 漏记录。"""
import sys
sys.path.insert(0, r"d:\virtual_riscv\iss")
from vriss import VrIss, Bus
from vriss.encode import (MRET, WFI, SRET, SFENCE_VMA, ECALL, EBREAK, enc_r, enc_i,
                          LUI, ADDI, SW, LW, JAL, BEQ, CSRRW, CSRRS, OP_SYSTEM,
                          OP_OP32, OP_OP, OP_MISC_MEM, OP_BR)
BASE = 0x1000

print("=== A. SYSTEM 子指令编码对照（真实工具链编码 vs encode.py 产物）===")
truth = {"MRET": 0x30200073, "SRET": 0x10200073, "WFI": 0x10500073,
         "FENCE.I": 0x0000100F, "SFENCE.VMA x0,x0": 0x12000073,
         "EBREAK": 0x00100073, "ECALL": 0x00000073}
mine = {"MRET": MRET(), "SRET": SRET(), "WFI": WFI(), "FENCE.I": None,
        "SFENCE.VMA x0,x0": SFENCE_VMA(0, 0), "EBREAK": EBREAK(), "ECALL": ECALL()}
for k, v in truth.items():
    m = mine[k]
    print(f"  {k:18s} 规范=0x{v:08x}  本仓库=0x{(m & 0xFFFFFFFF) if m else 0:08x}  "
          f"{'一致' if m == v else '★不一致★'}")

print("\n=== B. 真实编码送进 ISS 的后果 ===")


def trace_words(words, base=BASE, steps=8, tohost=None):
    bus = Bus()
    bus.load_image(base, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in words))
    iss = VrIss(bus=bus, reset_pc=base, tohost_addr=tohost)
    err = None
    for _ in range(steps):
        try:
            iss.step()
        except Exception as e:
            err = type(e).__name__ + ": " + str(e)
            break
        if iss.halted:
            break
    return iss, err


for name, enc in (("MRET 0x30200073", 0x30200073), ("WFI 0x10500073", 0x10500073),
                  ("SFENCE.VMA 0x12000073", 0x12000073), ("FENCE.I 0x0000100F", 0x0000100F),
                  ("本仓库 MRET() 0x%08x" % MRET(), MRET()),
                  ("MULW  x11,x9,x10", enc_r(0x01, 10, 9, 0, 11, OP_OP32)),
                  ("DIVW  x11,x9,x10", enc_r(0x01, 10, 9, 4, 11, OP_OP32)),
                  ("REMW  x11,x9,x10", enc_r(0x01, 10, 9, 6, 11, OP_OP32)),
                  ("MUL   x11,x9,x10", enc_r(0x01, 10, 9, 0, 11, OP_OP))):
    iss, err = trace_words([ADDI(9, 0, 5), ADDI(10, 0, 3), enc, ADDI(11, 0, 0x7f)], steps=6)
    causes = [(r.pc, int(r.exc_cause) if r.exc_v else None, r.instr_str) for r in iss.records]
    print(f"  {name:34s} err={err}  records={causes}")

print("\n=== C. BRANCH funct3=2/3（规范非法）→ Python 异常 ===")
bad_br = (1 << 31) | (0 << 25) | (10 << 20) | (9 << 15) | (2 << 12) | (0 << 7) | 0x63
iss, err = trace_words([bad_br], steps=3)
print(f"  0x63/funct3=2 指令字 0x{bad_br:08x} -> {err}")

print("\n=== D. jal x0,0 （自旋等待循环）是否真停机 ===")
selfloop = enc_i(0, 0, 0, 0, 0)  # placeholder
jal0 = (0 << 31) | (0 << 12) | (0 << 20) | (0 << 21) | (0 << 7) | 0x6F   # jal x0, 0
iss, err = trace_words([ADDI(9, 0, 1), jal0, ADDI(9, 9, 7)], steps=6)
print(f"  jal x0,0 = 0x{jal0:08x}; 执行后 x9={iss.regs[9]} (期望 1 = 仍在原地循环), "
      f"pc=0x{iss.pc:x}, records={[(r.pc, r.instr_str) for r in iss.records]}")
beq0 = (0 << 31) | (0 << 25) | (0 << 20) | (0 << 15) | (0 << 12) | (0 << 7) | 0x63  # beq x0,x0,0
iss, err = trace_words([ADDI(9, 0, 1), beq0, ADDI(9, 9, 7)], steps=8)
print(f"  beq x0,x0,0 死循环: records={[(hex(r.pc), r.instr_str) for r in iss.records]}")

print("\n=== E. watchdog 静默截断：run() 无任何失败标记 ===")
iss, err = trace_words([beq0], steps=2)
n, recs = iss.run(max_instr=5000)
print(f"  run(max_instr=5000) -> n={n} halted={iss.halted} halt_code={iss.halt_code} "
      f"len(records)={len(recs)}  (函数返回值里没有任何'被截断'标志)")

print("\n=== F. 取指失败的退休记录不进 trace（trace 少一行）===")
bus = Bus()
bus.load_image(BASE, b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little")
                              for w in [ADDI(9, 0, 1), ECALL()]))
iss = VrIss(bus=bus, reset_pc=BASE)
iss.csr[0x305] = 0x200000          # mtvec 指向无支撑区 -> 取指 access fault
stepped = 0
for _ in range(5):
    r = iss.step()
    stepped += 1
    print(f"  step{stepped}: pc=0x{r.pc:x} exc_v={r.exc_v} cause={int(r.exc_cause)} "
          f"in_rec_list={r in iss.records}")
print(f"  -> 执行了 {stepped} 次 step，但 len(iss.records)={len(iss.records)}，"
      f"minstret(csr 读回)={iss.csr.get(0xB02, 'n/a')} / seq={iss.seq}")

print("\n=== G. 未实现 CSR 静可用（setdefault）===")
iss, err = trace_words([LUI(9, 0x12345), CSRRW(0, 0x7f0, 9), CSRRS(10, 0x7f0, 0),
                        CSRRW(0, 0x3a0, 9), CSRRS(11, 0x3a0, 0)], steps=8)
print(f"  csrw 0x7f0(自定义)/0x3a0(未分配) 后: 是否产生异常 = "
      f"{[(r.pc, int(r.exc_cause)) for r in iss.records if r.exc_v]}")
print(f"  iss.csr 里新增的键 = {sorted(k for k in iss.csr if k in (0x7f0, 0x3a0))}, "
      f"x10=0x{iss.regs[10]:x} x11=0x{iss.regs[11]:x}")
print(f"  misa 读回 = 0x{iss.csr_read(0x301):016x}（advertises I,M,A,C）")

print("\n=== H. mcycle 写了没生效 / mepc[0] WARL ===")
iss, err = trace_words([LUI(9, 0x0), ADDI(9, 9, 123), CSRRW(0, 0xB00, 9),
                        CSRRS(10, 0xB00, 0), ADDI(9, 9, 1), CSRRS(11, 0xB02, 0)], steps=8)
print(f"  csrw mcycle,123 后 csrr mcycle -> x10={iss.regs[10]} (期望 123)")
print(f"  trace 中 mcycle 的写入记录 = {[(hex(r.pc), r.csr_addr, r.csr_new) for r in iss.records if r.csr_wr_en]}")
iss2, _ = trace_words([LUI(9, 0xFFFFF), ADDI(9, 9, -1), CSRRW(0, 0x341, 9),
                       CSRRS(10, 0x341, 0)], steps=8)
print(f"  csrw mepc,-1 后 csrr mepc -> x10=0x{iss2.regs[10]:016x} (规范要求 mepc[0] 恒 0)")
