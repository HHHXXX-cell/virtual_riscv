#!/usr/bin/env python3
r"""ISS 语义回归测试 —— 逐条钉住 R7 独立评审（doc/process/00 ISS-019）的实测缺陷。

分工：`test_smoke.py` 证明"一条程序能跑通"，本文件证明"具体指令的规范语义正确"。
**两者都通过 ≠ ISS 可信**：本文件只覆盖**已修**部分，未修项集中在末尾 `KNOWN_OPEN`
并随每次运行打印，防止这份绿被误读成 golden model 已可用。

关键手法：**官方指令字以常量写死**（不经过我们自己的 `encode.py`）。
评审 Q27 的真实成因就是"编码器与解码器同时错、彼此自洽"——自造编码自证永远发现不了。

锚点：`_tools\ibex-master\vendor\riscv-test-env\encoding.h`（官方指令字）、
`_tools\extracted\riscv_spec\riscv_spec_full.txt`（规范原文，可 grep）。

跑法：`python iss/tests/test_isa_semantics.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from vriss import Bus, VrIss, link                                   # noqa: E402
from vriss.consts import Csr, Exc                                    # noqa: E402
from vriss.encode import (ADDI, CSRRW, JAL, LBU, LHU, LWU, MULW,     # noqa: E402
                          SRA, SRAI, SRAIW, SRLI, SW)

MASK64 = (1 << 64) - 1
DRAM = 0x4000_0000
TOHOST = 0x4000_0010
BASE = 0x1000

# ---- 官方指令字常量（不经我们的编码器） --------------------------------- #
I_MRET = 0x30200073
I_SRET = 0x10200073
I_WFI = 0x10500073
I_FENCE_I = 0x0000100F
I_RESERVED_SRAI = 0x8044D593          # funct6=100000，RV64 保留，必须非法
I_SRAI_LEGAL = 0x4044D593             # funct6=010000
I_BR_F3_2 = 0x80A4A063                # BRANCH funct3=2，保留编码


def sext32(v: int) -> int:
    v &= 0xFFFF_FFFF
    return v - (1 << 32) if v >> 31 else v


def build(words: list[int], tohost=None) -> VrIss:
    """只装载镜像、不执行。（评审 Q2 的教训：构造与执行必须分开，否则测不到首条指令。）"""
    img = link([(BASE, words)])
    bus = Bus(signature_addr=0x2000_0000)
    bus.load_image(img.start, img.to_bytes())
    return VrIss(bus=bus, reset_pc=BASE, tohost_addr=tohost)


def one(word: int, regs: dict[int, int] | None = None):
    """单步一条指令，返回 (记录, iss)。

    `NotImplementedError` 是**预期行为**（RV64C / RV64A / SRET / SFENCE 未建模），
    但绝不能把测试带崩：在这里接住并返回已生成的记录。
    """
    iss = build([word])
    for idx, v in (regs or {}).items():
        iss.regs[idx] = v & MASK64
    try:
        return iss.step(), iss
    except NotImplementedError:
        return _dummy(word), iss


def _dummy(word: int):
    from vriss.trace import RetireRecord
    return RetireRecord(pc=BASE, instr=word, instr_str="<unimplemented>")


RESULTS: list[tuple[str, bool, str]] = []


def chk(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))


# --------------------------------------------------------------------------- #
def t_shifts() -> None:
    """Q18/Q19：SRA 系。"""
    neg = 0xFFFF_FFFF_8000_0000          # = -2**31
    r, _ = one(SRA(11, 9, 10), {9: neg, 10: 10})        # R 型移位量在 rs2，必须真赋 10
    want = MASK64 - ((1 << 21) - 1)                     # (-2**31) >> 10 的 64 位结果
    chk("SRA 是算术右移（Q18）", r.rd_data == want,
        f"x11=0x{r.rd_data:x} 期望 0x{want:x} mnem={r.instr_str!r}")

    r_srl, _ = one(SRLI(12, 9, 10), {9: neg})
    chk("SRA 结果必须不同于 SRL（Q18）", r.rd_data != r_srl.rd_data,
        f"SRA=0x{r.rd_data:x} SRL=0x{r_srl.rd_data:x}")

    r, _ = one(I_SRAI_LEGAL, {9: neg})
    chk("合法 SRAI 不再被判非法（Q19）", r.exc_v == 0 and r.instr_str == "srai",
        f"exc_v={r.exc_v} mnem={r.instr_str!r}")

    r, _ = one(I_RESERVED_SRAI, {9: neg})
    chk("保留 funct6=100000 必须非法（Q19）",
        r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR),
        f"exc_v={r.exc_v} cause={r.exc_cause}")

    r, _ = one(SRAIW(11, 9, 2), {9: 0xFFFF_FFFF_FFFF_F000})
    chk("合法 SRAIW 不再被判非法（Q19）", r.exc_v == 0, f"exc_v={r.exc_v}")


def t_loads() -> None:
    """Q17：LBU/LHU/LWU 的宽度与零扩展、天然对齐不得报未对齐。"""
    iss = build([LBU(10, 7, 0), LHU(11, 7, 2), LWU(12, 7, 4), LBU(13, 7, 1)])
    iss.regs[7] = DRAM
    iss.bus.write(DRAM, 8, 0x2221_20FF_EE01_00FF)     # 小端：FF 00 01 EE FF 01 21 22

    r = iss.step()
    chk("LBU 宽度=1 且零扩展（Q17）", r.mem_size == 1 and r.rd_data == 0xFF,
        f"size={r.mem_size} val=0x{r.rd_data:x}")
    r = iss.step()
    chk("LHU 宽度=2 且零扩展（Q17）", r.mem_size == 2 and r.rd_data == 0xEE01,
        f"size={r.mem_size} val=0x{r.rd_data:x}")
    r = iss.step()
    chk("LWU 宽度=4 且零扩展（Q17）", r.mem_size == 4 and r.rd_data == 0x2221_20FF,
        f"size={r.mem_size} val=0x{r.rd_data:x}")
    r = iss.step()
    chk("1 字节访问天然对齐，不得报 misaligned（Q17）", r.exc_v == 0,
        f"exc_v={r.exc_v} cause={r.exc_cause}")


def t_mulw() -> None:
    """Q20：MULW 族。低 32 位相乘后按 bit31 符号扩展。"""
    r, _ = one(MULW(11, 9, 10), {9: 0x1_0000_0002, 10: 0x1_0000_0003})
    chk("MULW 不再被判非法（Q20）", r.exc_v == 0 and r.instr_str == "mulw",
        f"exc_v={r.exc_v} mnem={r.instr_str!r}")
    chk("MULW 结果=低 32 位乘积再符号扩展（Q20）", r.rd_data == 6, f"got=0x{r.rd_data:x}")
    r, _ = one(MULW(11, 9, 10), {9: 0x8000_0000, 10: 2})
    chk("MULW 溢出按 32 位回绕（Q20）", r.rd_data == 0, f"got=0x{r.rd_data:x}")


def t_official_encodings() -> None:
    """Q27：官方指令字必须按官方语义解码。"""
    r, _ = one(I_MRET, {})
    chk("官方 MRET 解码为 mret，不得当 SRET/非法（Q27）",
        r.instr_str == "mret" and r.exc_v == 0, f"mnem={r.instr_str!r} exc_v={r.exc_v}")
    r, _ = one(I_WFI, {})
    chk("官方 WFI 不判非法且助记符正确（Q27）",
        r.exc_v == 0 and r.instr_str == "wfi", f"mnem={r.instr_str!r} exc_v={r.exc_v}")
    r, _ = one(I_FENCE_I, {})
    chk("FENCE.I 走 MISC-MEM 且助记符正确（Q8）", r.instr_str == "fence.i",
        f"mnem={r.instr_str!r}")
    r, _ = one(I_SRET, {})
    chk("官方 SRET 未被误认成 mret（Q27）", r.instr_str != "mret",
        f"mnem={r.instr_str!r}")


def t_reserved_and_spin() -> None:
    """Q6 / Q21：保留编码与自旋。"""
    r, _ = one(I_BR_F3_2, {})
    chk("BRANCH funct3=2 报非法而非 KeyError（Q6）",
        r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR),
        f"exc_v={r.exc_v} cause={r.exc_cause}")

    iss = build([JAL(0, 0), ADDI(9, 9, 1)])
    for _ in range(8):
        iss.step()
    chk("`jal x0,0` 自旋必须留在原地（Q21）",
        iss.regs[9] == 0 and iss.pc == BASE, f"x9={iss.regs[9]} pc=0x{iss.pc:x}")


def t_tohost_verdict() -> None:
    """Q12：riscv-tests 的 tohost 语义方向。"""
    for val, expect_pass in ((1, True), (3, False), (5, False)):
        iss = build([CSRRW(0, int(Csr.MSCRATCH), 9), SW(9, 8, 0)], tohost=TOHOST)
        iss.regs[8] = TOHOST
        iss.regs[9] = val
        iss.step()                    # 先给 CSRRW 一个 cs 源值
        iss.regs[9] = val
        iss.step()                    # store tohost
        got_pass = iss.halted and iss.halt_val == 1
        chk(f"tohost={val} 的判定方向正确（Q12，期望 PASS={expect_pass}）",
            got_pass == expect_pass,
            f"halted={iss.halted} halt_val={iss.halt_val}")


def t_mpp_reserved() -> None:
    """Q22/Q6：MPP 保留值不得让 MRET 崩在 Python 层。"""
    iss = build([I_MRET])
    iss.csr[int(Csr.MSTATUS)] = 2 << 11          # 直接造一个 MPP=保留值 2 的现场
    iss.csr[int(Csr.MEPC)] = 0x2000
    try:
        r = iss.step()
        ok, detail = True, f"mnem={r.instr_str!r} exc_v={r.exc_v}"
    except Exception as exc:                      # noqa: BLE001
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    chk("MPP=保留值 2 时 MRET 不得抛 Python 异常（Q22）", ok, detail)
    chk("MPP=2 经 MRET 后特权级落在合法模式（Q22）", ok and iss.priv in (0, 1, 3), detail)


KNOWN_OPEN = [
    "Q1  trace CSV 仍无 exc_v/exc_cause/mem_* 列 ⇒ 异常类别在比对链上**不可见**（最高优先）",
    "Q2  取指失败的退休记录被丢弃且 seq 不增 ⇒ 跑飞后 trace 冻结而 ISS 仍在跑",
    "Q3  mtval 合法为 0 时被兜底成指令字（`f.tval if... else instr`）",
    "Q4  注入中断会凭空多出一条伪退休记录（minstret 被抬）",
    "Q5  同步异常被算作退休并递增 minstret，规范明令禁止",
    "Q8  SFENCE.VMA / SRET 仍抛 NotImplementedError；MISC-MEM 其余 funct3 已补判",
    "Q9  跳转目标对齐判据是 `target & 1`；IALIGN=32 下应为 `& 3`，且 misaligned 的 mepc 归属错",
    "Q10/Q11  未实现的 CSR 静默可读写（影子寄存器）；mcycle 读值与 trace 新值互相矛盾",
    "Q13/Q14  signature 窗 PMA 无设备挂载；tohost 需精确地址匹配，且 `--tohost` 默认 None ⇒ 永不停机",
    "Q15  encode 的 R 型/CSR 地址域仍无范围检查（rs2=32 会溢出成 MUL）",
    "Q16  trace_compare 的『长度不等优先判环境/激励』引导语会误导归因",
    "Q22~Q26  mstatus/mip/mtvec/mepc/EBREAK 的 WARL 与只读语义基本未实现（本文件只测了不崩）",
    "Q31  RV64A / RV64C / S 态委托 / Sv39 / PMP 未建模，但 misa 已谎报 A 与 C",
]


# 本文件自身这一轮的返修记录（写测试时反而暴露了测试自写的错）：
#  • SRA 用例漏给 rs2=10 → 移位量为 0 的假失败；
#  • LWU 期望值把小端字节序算反——**ISS 本来就是对的**；
#  • MPP 用例多迈一步踩到镜像尾部，把测试结构错报成产品错。
# 这三条均不是 ISS 缺陷。→ 测试自己也需要被证伪，不能把“测试报 FAIL”直接当“产品有 bug”。


def main() -> int:
    t_shifts()
    t_loads()
    t_mulw()
    t_official_encodings()
    t_reserved_and_spin()
    t_tohost_verdict()
    t_mpp_reserved()

    bad = [r for r in RESULTS if not r[1]]
    for name, ok, detail in RESULTS:
        line = f"  {'OK  ' if ok else 'FAIL'}  {name}"
        if detail and (not ok or "tohost" in name):
            line += f"    [{detail}]"
        print(line)
    print(f"\n[semantics] 断言 {len(RESULTS)} 项，失败 {len(bad)} 项")
    print(f"[semantics] 本文件只覆盖**已修**部分；仍有 {len(KNOWN_OPEN)} 类已知未修问题：")
    for k in KNOWN_OPEN:
        print("   -", k)
    print("→ 上述项关闭前，ISS 不得作为 golden model 参与任何签核判定（doc/process/00 ISS-019）。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
