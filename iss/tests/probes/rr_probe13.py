#!/usr/bin/env python3
"""探针 13：ISS-063 / ISS-064 复现＋RV64 移位保留编码同族排查。

对应台账（本探针为 verifier 面 R-097 片的落盘复现件，原 P1~P3 为内联脚本）：
- ISS-063  SLLI 保留编码（bit30=1 ∧ funct3=001）被 ISS 接受（exc=0）
- ISS-064  MRET 在 MPP=M 时误清 mstatus.MPRV（1→0）
同族排查：SRLI/SRAI 保留构型、SLLIW/SRLIW/SRAIW 的 imm[5]≠0 保留构型、ADDIW 立即数域。

输出件 `rr_out13.txt` 由"修复前（复现）→ 修复后（回归）"两次运行依次追加构成；
两次块头打印 `machine.py` 的 md5，哈希不同即修复落地的独立标识。

跑法（仓库根，UTF-8 输出）：
    set PYTHONIOENCODING=utf-8 （bash: PYTHONIOENCODING=utf-8）
    python iss/tests/probes/rr_probe13.py

规范锚（提取件 `D:\\IC验证知识库\\_tools\\extracted\\riscv_spec\\riscv_spec_full.txt`）：
- 行 3459–3467  RV64 移位：imm[11:6] = 000000(SLLI)/000000(SRLI)/010000(SRAI)，右移类型位在 bit30
- 行 3516–3518  SLLIW/SRLIW/SRAIW encodings with imm[5]≠0 are reserved
- 行 3417       ADDIW = 加"符号扩展的 12 位立即数"（无保留立即数构型）
- 行 45127–45130  xRET 语义；"If y≠M, xRET also sets MPRV=0"（行 45130）

断言口径与 `iss/tests/test_isa_semantics.py` 一致：只写规范语义，
不改 machine.py 去迎合本探针（红线 R6）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]            # probes/ -> tests/ -> iss/ -> 仓库根
sys.path.insert(0, str(ROOT / "iss"))

from vriss import Bus, VrIss, link                     # noqa: E402
from vriss.consts import Csr, Exc                      # noqa: E402

# ---- 官方指令字（常量写死，不经 iss 自己的 encode.py） --------------------- #
I_SLLI_RESERVED_B30 = 0x40449593      # f3=001, imm[11:6]=010000（bit30=1）→ RV64 保留
I_SLLI_LEGAL = 0x00449593             # shamt=4
I_SLLI_LEGAL_SH5 = 0x02449593         # shamt=0b100100=36（bit25=1；RV64 六位 shamt，合法）
I_SRLI_LEGAL = 0x0044D593
I_SRAI_LEGAL = 0x4044D593
I_SLLIW_RESERVED_B30 = 0x4044959B     # f3=001, imm[11:5]=0100000 → 保留
I_SLLIW_RESERVED_I5 = 0x0244959B      # f3=001, imm[5]=1 → 保留
I_SRLIW_RESERVED_I5 = 0x0244D59B      # f3=101, imm[5]=1 → 保留
I_SRAIW_RESERVED_I5 = 0x4244D59B      # f3=101, imm[11:5]=0100001 → 保留
I_SLLIW_LEGAL = 0x0044959B
I_SRAIW_LEGAL = 0x4044D59B
I_ADDIW_100 = 0x0644859B              # addiw x11, x9, 100
I_ADDIW_M1 = 0xFFF4859B               # addiw x11, x9, -1
I_ADDIW_400 = 0x4004859B              # addiw x11, x9, 0x400
I_MRET = 0x30200073
I_SRET = 0x10200073

MSTATUS_MPIE = 1 << 7
MSTATUS_MPP_M = 3 << 11
MPRV = 1 << 17
MSTATUS_MIE = 1 << 3

FAILS: list[str] = []
_COUNT = [0]


def chk(cid: str, expect: str, ok: bool, got: str) -> None:
    _COUNT[0] += 1
    print("  [%s] %s  expect: %s | got: %s" % (cid, "PASS" if ok else "FAIL", expect, got))
    if not ok:
        FAILS.append(cid)


def single(word: int, regs: dict[int, int] | None = None,
           csrs: dict[int, int] | None = None):
    img = link([(0x1000, [word])])
    bus = Bus()
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=0x1000)
    for i, v in (regs or {}).items():
        iss.regs[i] = v
    for a, v in (csrs or {}).items():
        iss.csr[a] = v
    return iss.step(), iss


def main() -> int:
    print("== rr_probe13: ISS-063/ISS-064 reproduce + RV64 shift-reserved family sweep ==")
    print("CMD: python iss/tests/probes/rr_probe13.py   (cwd = 仓库根；PYTHONIOENCODING=utf-8)")
    m5 = hashlib.md5((ROOT / "iss" / "vriss" / "machine.py").read_bytes()).hexdigest()
    print("machine.py md5 = %s" % m5)
    print("spec anchors = lines 3459-3467 / 3516-3518 / 3417 / 45127-45130")

    print("-- P1  ISS-063: SLLI reserved (f3=001, bit30=1) --")
    r, _ = single(I_SLLI_RESERVED_B30, {9: 1})
    chk("P1a", "illegal (exc_v=1 cause=2)",
        r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR),
        "exc_v=%d cause=%d mnem=%r" % (r.exc_v, r.exc_cause, r.instr_str))

    print("-- P1c controls: legal 64-bit shifts（含 6 位 shamt 的 bit25） --")
    r, _ = single(I_SLLI_LEGAL, {9: 1})
    chk("P1c1", "slli executes (exc_v=0)", r.exc_v == 0 and r.instr_str == "slli",
        "exc_v=%d mnem=%r" % (r.exc_v, r.instr_str))
    r, iss = single(I_SLLI_LEGAL_SH5, {9: 1})
    chk("P1c2", "slli shamt=36 legal (bit25=1 属 RV64 六位 shamt；x11=0x10_0000_0000)",
        r.exc_v == 0 and iss.regs[11] == 0x10_0000_0000,
        "exc_v=%d x11=0x%x" % (r.exc_v, iss.regs[11]))
    r, _ = single(I_SRLI_LEGAL, {9: 0xFF})
    chk("P1c3", "srli legal (exc_v=0)", r.exc_v == 0 and r.instr_str == "srli",
        "exc_v=%d mnem=%r" % (r.exc_v, r.instr_str))
    r, _ = single(I_SRAI_LEGAL, {9: 0xFF})
    chk("P1c4", "srai legal (exc_v=0)", r.exc_v == 0 and r.instr_str == "srai",
        "exc_v=%d mnem=%r" % (r.exc_v, r.instr_str))

    print("-- P2  SLLIW/SRLIW/SRAIW reserved configs (spec 行 3516-3518) --")
    for cid, w, note in (("P2a", I_SLLIW_RESERVED_B30, "imm[11:5]=0100000"),
                         ("P2b", I_SLLIW_RESERVED_I5, "imm[5]=1"),
                         ("P2c", I_SRLIW_RESERVED_I5, "imm[5]=1"),
                         ("P2d", I_SRAIW_RESERVED_I5, "imm[5]=1(hi6=0x10)")):
        r, _ = single(w, {9: 1})
        chk(cid, "illegal (%s)" % note,
            r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR),
            "exc_v=%d cause=%d mnem=%r" % (r.exc_v, r.exc_cause, r.instr_str))
    r, _ = single(I_SLLIW_LEGAL, {9: 1})
    chk("P2c1", "slliw legal (exc_v=0)", r.exc_v == 0 and r.instr_str == "slliw",
        "exc_v=%d mnem=%r" % (r.exc_v, r.instr_str))
    r, _ = single(I_SRAIW_LEGAL, {9: 0x8000_0000})
    chk("P2c2", "sraiw legal (exc_v=0)", r.exc_v == 0 and r.instr_str == "sraiw",
        "exc_v=%d mnem=%r" % (r.exc_v, r.instr_str))

    print("-- P3  ADDIW 全 12 位立即数域（spec 行 3417；无保留构型） --")
    r, iss = single(I_ADDIW_100, {9: 7})
    chk("P3a", "addiw x9=7, imm=100 -> exc_v=0, x11=107",
        r.exc_v == 0 and iss.regs[11] == 107,
        "exc_v=%d x11=%d" % (r.exc_v, iss.regs[11]))
    r, iss = single(I_ADDIW_M1, {9: 7})
    chk("P3b", "addiw x9=7, imm=-1 -> exc_v=0, x11=6",
        r.exc_v == 0 and iss.regs[11] == 6,
        "exc_v=%d x11=%d" % (r.exc_v, iss.regs[11]))
    r, iss = single(I_ADDIW_400, {9: 0})
    chk("P3c", "addiw x9=0, imm=0x400 -> exc_v=0, x11=0x400",
        r.exc_v == 0 and iss.regs[11] == 0x400,
        "exc_v=%d x11=0x%x" % (r.exc_v, iss.regs[11]))

    print("-- P4  ISS-064: MRET 的 MPRV 语义（spec 行 45127-45130） --")
    r, iss = single(I_MRET, csrs={int(Csr.MSTATUS): MSTATUS_MPP_M | MPRV | MSTATUS_MPIE,
                                  int(Csr.MEPC): 0x2000})
    m = iss.csr[int(Csr.MSTATUS)]
    chk("P4a", "MPP=M: MPRV 保持 1, MPP->0, MIE<-MPIE=1, priv=M, pc=mepc",
        (m >> 17) & 1 == 1 and (m >> 11) & 3 == 0 and (m >> 3) & 1 == 1
        and (m >> 7) & 1 == 1 and iss.priv == 3 and iss.pc == 0x2000,
        "mstatus=0x%x priv=%d pc=0x%x" % (m, iss.priv, iss.pc))
    r, iss = single(I_MRET, csrs={int(Csr.MSTATUS): MPRV, int(Csr.MEPC): 0x2000})
    m = iss.csr[int(Csr.MSTATUS)]
    chk("P4b", "MPP=U: MPRV 清 0, priv=U, MPP->0（y!=M 分支）",
        (m >> 17) & 1 == 0 and iss.priv == 0 and (m >> 11) & 3 == 0,
        "mstatus=0x%x priv=%d" % (m, iss.priv))
    r, iss = single(I_MRET, csrs={int(Csr.MSTATUS): MSTATUS_MPP_M | MSTATUS_MPIE,
                                  int(Csr.MEPC): 0x2000})
    m = iss.csr[int(Csr.MSTATUS)]
    chk("P4c", "MPP=M 且 MPRV=0: 不得被置 1（防过度修正）",
        (m >> 17) & 1 == 0 and (m >> 11) & 3 == 0,
        "mstatus=0x%x" % m)

    print("-- P5  记录：SRET 仍为显式未实现（README §5；不在本片修复范围） --")
    try:
        single(I_SRET)
        print("  [P5] INFO  SRET 未抛 NotImplementedError（状态与 README 声明不符，需复核）")
    except NotImplementedError as e:
        print("  [P5] INFO  SRET -> NotImplementedError: %s" % e)

    n_fail = len(FAILS)
    print("== probe13 summary: checks=%d fail=%d %s =="
          % (_COUNT[0], n_fail, ("| FAIL ids: " + ",".join(FAILS)) if FAILS else ""))
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
