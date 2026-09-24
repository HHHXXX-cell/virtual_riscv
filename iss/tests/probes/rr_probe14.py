#!/usr/bin/env python3
"""探针 14：附 Z 澄-1 落盘件 —— R-096 互校口径注 D-3／D-4 的实跑复现（前门观察，不改 ISS）。

背景（`doc/review/01-评审记录.md` 附 Z 澄-1；回收行 `doc/verify/05` R-098）：
- R-096 行的 ISS 互校清单含 D-3／D-4 两条"口径注"，但**无落盘用例**，且其行文 P 编号与
  落盘件 `rr_probe13.py` 的文件内编号**同号不同物**。本件把 D-3／D-4 两条观察值补成
  可回查证据（本文件＋实跑重定向输出 `rr_out14.txt`，不得手写结果），并给出三方编号对照。

三方 P 编号对照表（逐行一一对应；"无对应"＝该命名空间内不存在同物编号）：

| 主题（发现/条目，出处） | R-096 行文 P# | rr_probe13 文件 P# | rr_probe14 P14-# |
|---|---|---|---|
| SLLI 保留编码（D-1 主项；`spec/02` §16.3.1 D-1） | P1 | P1（SLLI 保留） | —（R-097 已落盘） |
| W 型移位保留对照（D-1 对照；同出处"对照 P2"） | P2 | P2（SLLIW/SRLIW/SRAIW） | —（R-097 已落盘） |
| ADDIW 立即数域（同族附项） | —（R-096 未单列） | P3（ADDIW） | —（R-097 已落盘） |
| MRET/MPRV（D-2；`spec/02` §16.3.1 D-2） | P3（=MRET） | P4（=MRET） | —（R-097 已落盘） |
| SRET 未实现记录 | —（R-096 未单列） | P5（SRET） | — |
| CSRRW rd=x0（D-3；`spec/02` §16.3.1 D-3） | P4（=CSRRW） | 无对应（P1~P5 均非此用例） | **P14-1**（本件落盘） |
| ECALL rd=2（D-4；`spec/02` §16.3.1 D-4） | P7（=ECALL） | 无对应 | **P14-2**（本件落盘） |
| CSRRS rs1=x0 于只读 CSR 不报错（`spec/02` §16.3.4） | P5 | 无对应 | — |
| CSRRW 写只读 CSR 报 illegal（`spec/02` §16.3.4） | P6 | 无对应 | — |
| JALR 目标 bit1≠0 不报（IALIGN=16；`spec/02` §16.3.4） | P8 | 无对应 | — |
| rd=x0 不写回（SI-1；`spec/02` §16.3.4） | P9 | 无对应 | — |

编号冲突实录（澄-1 原文）：R-096 行文"P4"指 CSRRW、"P7"指 ECALL；而 `rr_probe13.py` 文件内
"P4"指 MRET。R-096 行文 P1~P9 系内联探针（无落盘件），本表据 `spec/02` §16.3.1／§16.3.4
的记载复原；本件起用 **P14-#** 命名空间（避免第三次撞号）。

D-3 现象与口径（**口径注·低烈度**；`spec/02` §16.3.1 D-3 行同口径）：
- 现象：CSRRW 且 rd=x0 时 ISS **仍执行 `csr_read`** 并把读值回填 `rec.csr_old`／`csr_new`
  （`machine.py` `_system`：`old = self.csr_read(csr)` 在 `if rd:` 写回判定之前无条件执行；
  rd=x0 ⇒ `rd_wb_en=0` 不写回）。规范口径（提取件行 5049–5052，AN-06）："If rd=x0, then the
  instruction shall not read the CSR and shall not cause any of the side effects that might
  occur on a CSR read."
- **无可观测分叉**：一期 CSR 集无读副作用；`csr_old` **不进 trace 比对列**（`iss/README.md`
  §3 映射表：csr 列只取 `csr_addr`／`csr_new`／`csr_wr_en`）⇒ D-3 不构成可观测分叉；
  ISS 侧记录字段是否按 rd=x0 置空＝verifier 自定（本件维持现状、不改 ISS，`doc/verify/05` R-100）。
- 关于 R-096 观察值"cold=0x88"：实读 `machine.py.__init__` 初值表不含 mstatus（缺省经
  `csr_read` 得 0）⇒ **0x88 不是复位值/初值**（P14-1a 实测 fresh 初值＝0x0，与 R-096 行文
  "0x88 为复位值"不符，以实测为准）。0x88＝MIE|MPIE（bit3|bit7），可由"MIE=1 时发生陷阱
  （MPIE←MIE=1、MIE←0、MPP←M）再 MRET（MIE←MPIE、MPIE←1、MPP→最低可用模式）"自然产生；
  本件以 P14-1b（显式前置态注入，与 `rr_probe13` `single(csrs=...)` 同法）与 P14-1c
  （前门指令序，无 CSR 注入）两种方式复现 `cold=0x88`。

D-4 现象与口径（**边界注；不判缺陷**）：
- 现象：`ECALL` 且 rd=2（SYSTEM 组保留字段）→ ISS 按字面接受、照常进入正常环境陷阱
  `cause=11`（ECALL_M），**非非法指令**（`machine.py` `_sys_op` 只按 funct7[31:25]／
  low5[24:20] 分派，rd/rs1 字段不参与判定；同族 rs1≠0 组合同）。
- 口径归 `doc/spec/10` 的 T-9（保留编码口径；依据句＝`spec/02` §9.3，提取件行 2026–2029
  "保留译码行为 UNSPECIFIED、平台可选非法化"）；本件只落盘观察，不改 ISS（`doc/verify/05` R-100）。

规范锚（提取件 `_tools\\extracted\\riscv_spec\\riscv_spec_full.txt`，行＝该文件行号）：
- 行 5049–5052  CSRRW 且 rd=x0 不读、无读副作用（AN-06）
- 行 3174–3180  ECALL/EBREAK 正文（"cause a precise requested trap"）
- 行 46915 起   ECALL 按起源特权级生成对应异常（M 态＝environment-call-from-M＝11）
- 行 2026–2029  保留编码译码行为 UNSPECIFIED（平台可选非法化）→ D-4 口径归 T-9

自证伪（负控；每个检查点配一次反证）：
- `--self-falsify` 模式对"检查点所观察的态势"做单点注入，验证主运行的同一断言谓词确实翻假
  （即主运行会报 FAIL——只有能报红的检查器才算存在）：
    注入 A（翻一位 CSR）：P14-1b 前置态 0x88 -> 0x89 -> cold 谓词应翻假；
    注入 B（换一个编码点）：P14-2b 指令 0x00000173 -> 0x00200073 -> cause=11 谓词应翻假；
    注入 C（改一个操作数）：前门序 x5 初值 0x8 -> 0x0 -> MRET 后 mstatus 谓词应翻假。
- 负控谓词未翻假者报 MISS（该检查器无效）；输出块 2 随附于 `rr_out14.txt`。

跑法（仓库根，UTF-8 输出）：
    set PYTHONIOENCODING=utf-8 （bash: PYTHONIOENCODING=utf-8）
    python iss/tests/probes/rr_probe14.py
    python iss/tests/probes/rr_probe14.py --self-falsify

纪律：前门观察；不改 ISS、不改断言以求通过（红线 R6）。断言口径＝复现 R-096／`spec/02`
§16.3.1 记载的现状观察（D-3：rd_wb=0 但已读回填；D-4：按字面接受）——若 T-9 口径裁定后
ISS 行为变更，本件对应断言会报 FAIL（预期失效点，须随口径更新，回看点已在 §16.3.1 登记）。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]            # probes/ -> tests/ -> iss/ -> 仓库根
sys.path.insert(0, str(ROOT / "iss"))

from vriss import Bus, VrIss, link                     # noqa: E402
from vriss.consts import Csr, Exc, Priv                # noqa: E402

# ---- 官方指令字（常量写死，不经 iss 自己的 encode.py；与 encode.py 构造器已交叉核对） ---- #
I_CSRRW_X0_MSTATUS_X1 = 0x30009073    # csrrw x0, mstatus(0x300), x1
I_CSRRS_X0_MSTATUS_X5 = 0x3002A073    # csrrs x0, mstatus, x5（前置序：置 MIE）
I_ECALL = 0x00000073                  # ecall（rd=x0 规范形）
I_ECALL_RD2 = 0x00000173              # ecall，rd=2（SYSTEM 保留字段组合，D-4 主项）
I_ECALL_RS1_3 = 0x00018073            # ecall，rs1=3
I_ECALL_RD2_RS1_3 = 0x00018173        # ecall，rd=2 且 rs1=3
I_SYSTEM_LOW5_2 = 0x00200073          # SYSTEM funct7=0、low5=2：未定义点（对照项）
# 陷阱 handler（前门序用；HANDLER=0x1100）
I_CSRRS_X5_MEPC_X0 = 0x341022F3       # csrrs x5, mepc(0x341), x0
I_ADDI_X5_X5_4 = 0x00428293           # addi x5, x5, 4
I_CSRRW_X0_MEPC_X5 = 0x34129073       # csrrw x0, mepc, x5
I_MRET = 0x30200073

MSTATUS_MIE = 1 << 3
MSTATUS_MPIE = 1 << 7
MS_0X88 = MSTATUS_MIE | MSTATUS_MPIE  # = 0x88（R-096 行文观察值；MIE|MPIE 组合）
SRC_X1 = 0x2_0008                     # csrrw 源值：MPRV(bit17)|MIE(bit3)，均在 mstatus 写掩码内

CODE = 0x1000
HANDLER = 0x1100
MTVEC_VAL = 0x2000

FAILS: list[str] = []
_COUNT = [0]


def chk(cid: str, expect: str, ok: bool, got: str) -> None:
    _COUNT[0] += 1
    print("  [%s] %s  expect: %s | got: %s" % (cid, "PASS" if ok else "FAIL", expect, got))
    if not ok:
        FAILS.append(cid)


def single(word: int, regs: dict[int, int] | None = None,
           csrs: dict[int, int] | None = None):
    img = link([(CODE, [word])])
    bus = Bus()
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE)
    for i, v in (regs or {}).items():
        iss.regs[i] = v
    for a, v in (csrs or {}).items():
        iss.csr[a] = v
    return iss.step(), iss


def prologue(x5_init: int = MSTATUS_MIE):
    """前门序（无 CSR 注入；仅初始化 x5/x1/mtvec 三个初值）：

        CODE+0  csrrs x0, mstatus, x5      # MIE=1
        CODE+4  ecall                      # MPIE←MIE=1, MIE←0, MPP←M；mepc=CODE+4
        HANDLER csrrs x5, mepc, x0 / addi x5,x5,4 / csrrw x0, mepc, x5 / mret
                                           # 返回 mstatus=0x88（MIE|MPIE）、MPP→U
        CODE+8  csrrw x0, mstatus, x1      # 末步＝D-3 指令（此时 cold 应为 0x88）

    `x5_init` 供自证伪注入 C 使用（0x0 时 MPIE 不置位，MRET 后 mstatus=0x80 而非 0x88）。
    返回 (mret 后 mstatus, mret 后 pc, 末步记录, iss)。
    """
    img = link([(CODE, [I_CSRRS_X0_MSTATUS_X5, I_ECALL, I_CSRRW_X0_MSTATUS_X1]),
                (HANDLER, [I_CSRRS_X5_MEPC_X0, I_ADDI_X5_X5_4,
                           I_CSRRW_X0_MEPC_X5, I_MRET])])
    bus = Bus()
    bus.load_image(img.start, img.to_bytes())
    iss = VrIss(bus=bus, reset_pc=CODE)
    iss.regs[5] = x5_init
    iss.regs[1] = SRC_X1
    iss.csr[int(Csr.MTVEC)] = HANDLER
    for _ in range(6):
        iss.step()                                     # csrrs / ecall / handler×3 / mret
    m_mid = iss.csr[int(Csr.MSTATUS)]
    pc_back = iss.pc
    r = iss.step()                                     # 末步：csrrw x0, mstatus, x1
    return m_mid, pc_back, r, iss


def main() -> int:
    print("== rr_probe14: 附 Z 澄-1 落盘件 —— D-3（CSRRW rd=x0 回填 csr_old）／D-4（ECALL rd=2）实跑复现 ==")
    print("CMD: python iss/tests/probes/rr_probe14.py   (cwd = 仓库根；PYTHONIOENCODING=utf-8)")
    m5 = hashlib.md5((ROOT / "iss" / "vriss" / "machine.py").read_bytes()).hexdigest()
    print("machine.py md5 = %s" % m5)
    print("spec anchors = lines 5049-5052 / 3174-3180 / 46915+ / 2026-2029")

    print("-- P14-1  D-3: CSRRW rd=x0 的 csr_old 回填（口径注·低烈度；spec/02 §16.3.1 D-3） --")
    r, iss = single(I_CSRRW_X0_MSTATUS_X1, regs={1: SRC_X1})
    chk("P14-1a", "实读初值：rd_wb=0 且 cold=0x0（mstatus 不在初值表，非 0x88；以实测为准）",
        r.rd_wb_en == 0 and r.csr_old == 0x0 and r.csr_new == SRC_X1
        and r.csr_wr_en == 1 and iss.csr[int(Csr.MSTATUS)] == SRC_X1,
        "rd_wb=%d cold=0x%x cnew=0x%x cwr=%d mstatus=0x%x"
        % (r.rd_wb_en, r.csr_old, r.csr_new, r.csr_wr_en, iss.csr[int(Csr.MSTATUS)]))

    r_b, iss_b = single(I_CSRRW_X0_MSTATUS_X1, regs={1: SRC_X1},
                        csrs={int(Csr.MSTATUS): MS_0X88})
    chk("P14-1b", "R-096 观察逐位复现（前置态 0x88）：rd_wb=0 但 cold=0x88（已读回填）",
        r_b.rd_wb_en == 0 and r_b.csr_old == 0x88 and r_b.csr_new == SRC_X1
        and iss_b.csr[int(Csr.MSTATUS)] == SRC_X1,
        "rd_wb=%d cold=0x%x cnew=0x%x cwr=%d mstatus=0x%x"
        % (r_b.rd_wb_en, r_b.csr_old, r_b.csr_new, r_b.csr_wr_en,
           iss_b.csr[int(Csr.MSTATUS)]))

    m_mid, pc_back, r_c, iss_c = prologue()
    chk("P14-1c", "前门序自然可达（无 CSR 注入）：MRET 后 mstatus=0x88，末步 csrrw 记录 cold=0x88 且 rd_wb=0",
        m_mid == 0x88 and pc_back == CODE + 8 and r_c.rd_wb_en == 0
        and r_c.csr_old == 0x88 and r_c.csr_new == SRC_X1,
        "mstatus(mret后)=0x%x pc=0x%x rd_wb=%d cold=0x%x cnew=0x%x"
        % (m_mid, pc_back, r_c.rd_wb_en, r_c.csr_old, r_c.csr_new))

    chk("P14-1d", "trace 列面：gpr 列=''（rd=x0）；csr 列只含新值 0x300:0x…2008（csr_old 不在列内）；x1 无副作用",
        r_b.gpr_field() == "" and r_b.csr_field() == "0x300:0x0000000000020008"
        and iss_b.regs[1] == SRC_X1 and iss_b.regs[0] == 0,
        "gpr=%r csr=%r x1=0x%x x0=%d"
        % (r_b.gpr_field(), r_b.csr_field(), iss_b.regs[1], iss_b.regs[0]))

    print("  [P14-1] INFO  口径注（低）：一期 CSR 集无读副作用 + csr_old 不进 trace 比对列（iss/README §3 映射表）")
    print("                  ==> 无可观测分叉；ISS 记录字段是否按 rd=x0 置空=verifier 自定；本件维持现状（不改 ISS）。")

    print("-- P14-2  D-4: ECALL rd=2（SYSTEM 保留字段）-> 正常陷阱（口径归 spec/10 T-9） --")
    for cid, w, note in (
            ("P14-2a", I_ECALL, "ECALL rd=x0（规范形，对照）"),
            ("P14-2b", I_ECALL_RD2, "ECALL rd=2（R-096 P7 观察复现：按字面接受）"),
            ("P14-2c", I_ECALL_RS1_3, "ECALL rs1=3（同 'rd/rs1 非零组合' 面）"),
            ("P14-2d", I_ECALL_RD2_RS1_3, "ECALL rd=2 且 rs1=3（组合面）")):
        r, iss = single(w, csrs={int(Csr.MTVEC): MTVEC_VAL})
        chk(cid, "%s -> 正常陷阱 cause=11（ECALL_M；非 illegal=2）" % note,
            r.exc_v == 1 and r.exc_cause == int(Exc.ECALL_M)
            and iss.csr.get(Csr.MCAUSE) == int(Exc.ECALL_M)
            and iss.csr.get(Csr.MEPC) == CODE and iss.pc == MTVEC_VAL
            and iss.priv == int(Priv.MACHINE),
            "exc_v=%d cause=%d mcause=%d mepc=0x%x mtval=0x%x pc=0x%x priv=%d"
            % (r.exc_v, r.exc_cause, iss.csr.get(Csr.MCAUSE, 0),
               iss.csr.get(Csr.MEPC, 0), iss.csr.get(Csr.MTVAL, 0), iss.pc, iss.priv))

    r, iss = single(I_SYSTEM_LOW5_2, csrs={int(Csr.MTVEC): MTVEC_VAL})
    chk("P14-2e", "对照：SYSTEM funct7=0 low5=2 未定义点 -> illegal（cause=2；非全盘接受）",
        r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR),
        "exc_v=%d cause=%d mcause=%d pc=0x%x"
        % (r.exc_v, r.exc_cause, iss.csr.get(Csr.MCAUSE, 0), iss.pc))

    print("  [P14-2] INFO  D-4 不判缺陷：SYSTEM 保留字段口径归 spec/10 T-9（保留!=非法依据句=spec/02 §9.3）；")
    print("                 本件只落盘现状观察（ISS 侧未加保留化检查），不改 ISS。")

    n_fail = len(FAILS)
    print("== probe14 summary: checks=%d fail=%d %s =="
          % (_COUNT[0], n_fail, ("| FAIL ids: " + ",".join(FAILS)) if FAILS else ""))
    return 1 if FAILS else 0


def self_falsify() -> int:
    """自证伪（负控）：三处单点注入，验证主运行对应断言的谓词确实会翻假（会报红）。

    注入 A（翻一位 CSR）：P14-1b 前置态 0x88 -> 0x89；谓词 cold=0x88 应翻假。
    注入 B（换一个编码点）：P14-2b 指令 0x00000173 -> 0x00200073（ECALL rd=2 -> SYSTEM
            未定义点）；谓词 cause=11（ECALL_M）应翻假。
    注入 C（改一个操作数）：前门序 x5 初值 MIE -> 0x0；谓词 MRET 后 mstatus=0x88 应翻假。
    谓词未翻假者报 MISS（该检查器无效）。
    """
    print("== rr_probe14 [SELF-FALSIFY]：单点注入负控（每个检查点配一次反证） ==")
    print("CMD: python iss/tests/probes/rr_probe14.py --self-falsify   (cwd = 仓库根；PYTHONIOENCODING=utf-8)")
    m5 = hashlib.md5((ROOT / "iss" / "vriss" / "machine.py").read_bytes()).hexdigest()
    print("machine.py md5 = %s" % m5)
    missed: list[str] = []

    def red(cid: str, inject: str, pred_ok: bool, got: str) -> None:
        print("  [%s] %s  inject: %s | pred=%s got: %s"
              % (cid, "RED-CAUGHT" if not pred_ok else "MISS", inject,
                 "False（主运行该点将报 FAIL）" if not pred_ok else "True（未翻假！）", got))
        if pred_ok:
            missed.append(cid)

    r, iss = single(I_CSRRW_X0_MSTATUS_X1, regs={1: SRC_X1},
                    csrs={int(Csr.MSTATUS): 0x89})
    red("FS-A", "P14-1b 前置态 0x88 -> 0x89（翻一位 CSR）",
        r.rd_wb_en == 0 and r.csr_old == 0x88 and r.csr_new == SRC_X1,
        "rd_wb=%d cold=0x%x cnew=0x%x" % (r.rd_wb_en, r.csr_old, r.csr_new))

    r, iss = single(I_SYSTEM_LOW5_2, csrs={int(Csr.MTVEC): MTVEC_VAL})
    red("FS-B", "P14-2b 指令 0x00000173 -> 0x00200073（换编码点）",
        r.exc_v == 1 and r.exc_cause == int(Exc.ECALL_M)
        and iss.csr.get(Csr.MCAUSE) == int(Exc.ECALL_M)
        and iss.csr.get(Csr.MEPC) == CODE and iss.pc == MTVEC_VAL
        and iss.priv == int(Priv.MACHINE),
        "exc_v=%d cause=%d mcause=%d pc=0x%x" % (r.exc_v, r.exc_cause,
                                                 iss.csr.get(Csr.MCAUSE, 0), iss.pc))

    m_mid, pc_back, r, iss = prologue(x5_init=0x0)
    red("FS-C", "前门序 x5 初值 0x8 -> 0x0（改一个操作数）",
        m_mid == 0x88 and pc_back == CODE + 8 and r.rd_wb_en == 0
        and r.csr_old == 0x88 and r.csr_new == SRC_X1,
        "mstatus(mret后)=0x%x pc=0x%x cold=0x%x" % (m_mid, pc_back, r.csr_old))

    print("== falsify summary: injections=3 %s =="
          % ("red caught=3（检查器有效：主运行会报红）" if not missed
             else "MISS ids: " + ",".join(missed)))
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(self_falsify() if "--self-falsify" in sys.argv else main())
