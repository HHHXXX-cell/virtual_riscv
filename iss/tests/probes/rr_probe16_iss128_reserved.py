#!/usr/bin/env python3
"""探针 16：**ISS-128 五组「保留编码/RTL 与 ISS 检查面不对称」的逐组对账与消解复现**
（2026-09-26 心跳第 15 轮）。

背景（原条目＝`doc/process/ledger.json` 的 `ISS-128`，心跳第 14 轮发现）：同一编码出现
"RTL 判 illegal／ISS 按合法执行" 的 5 组差异。本件做两件事：

  ① **两组真保留编码的 ISS 侧补齐**（本次实修，落 `iss/vriss/machine.py` 两处检查）：
     - 组 1 `JALR funct3≠000`：规范只为 JALR 定义 f3=000（提取件行 2686–2698 编码表逐字段值
       rd=dest／**funct3=0**／rs1=base／imm=offset[11:0]）⇒ f3≠0 不映射任何合法指令；保留编码的
       译码行为 **UNSPECIFIED**（行 2026–2029），本项目取「RES 编码点一律非法化」为平台选择
       （`doc/spec/02` §9.3 依据句）⇒ 必须 illegal。RTL 合规范（`vr1_decode.sv` 515–526），
       **ISS 侧原缺检查**（旧 `_exec` 直接算目标并写 link）。
     - 组 2 `MRET 且 rs1≠0 或 rd≠0`：MRET 的 rs1／rd 在特权指令表里**固定 00000**
       （提取件行 55952–55964：0011000／00010／00000(rs1)／000／00000(rd)／1110011；同表
       SRET 行 55945–55951、WFI 行 55967–55973 同为 rs1=rd=00000）⇒ 非零组合是保留编码点，
       平台选择同上 ⇒ 必须 illegal。RTL 合规范（`vr1_decode.sv` 613），**ISS 侧原缺检查**
       （旧 `_sys_op` 只查 funct7＋low5）。
     ⇒ 两组修完**两侧同为非法**，故该两族编码可进 `sw/tests/direct/dec_probe.S` 的定向激励
       （进 `MANIFEST.tests` ⇒ 同受 `m2-rv64ui` 的 ISS↔RTL 逐条比对，**不设免判通道**）。

  ② **三组「定义成员未实现」的反向裁决**（组 3/4/5：MULH 族／OP-32 的 f7=1 族／SYSTEM 的
     CSRRC·CSRRWI·CSRRSI·CSRRCI）：这三组**不是保留编码**，而是 `doc/spec/02` §9.1.6／§9.1.7
     在册的**合法成员**（编码 0x201–0x203／0x210／0x290–0x293／0x302–0x305），RISC-V 亦定义为
     M 扩展与 Zicsr 的指令（提取件行 5455–5469、5591；Zicsr f3 表）。故 **ISS 侧是对的**，
     差异的真实来源是 **RTL 首版实现子集**（`rtl/vr1/ctrl/vr1_decode.sv` 文件头 53–63 行自述：
     "§9.1 其余 30 个成员……是 **G1-F 后才入面的合法 RV64 指令**"，非"保留段"；`doc/decisions/
     G1-I-最小冻结清单.md` §1.1 的 14 条 ＋ M2/M3-(d) 增补 ＝ 57 条）。**本件据此不改 ISS**：
     把 ISS 收窄成 illegal ＝ 与 `doc/spec/02` §9.1 的成员表相抵，且会**抹掉 DUT 的真实缺口**
     （R6/R8 精神：不得把已知 DUT 缺口写成 golden），并使既有语义回归
     `iss/tests/test_isa_semantics.py:t_mulw`（"MULW 不再被判非法（Q20）"）失去意义。
     归属改为 **G1-F／T-2／T-3 的实现面增量批**（与 `doc/verify/02` §7 的 CC-4／CC-15 归属一致）。

规范锚（提取件 `_tools\\extracted\\riscv_spec\\riscv_spec_full.txt`，行＝该文件行号）：
- 行 2686–2698  JALR 编码表逐字段值（funct3=0 为定义值）
- 行 2026–2029  保留编码译码行为 UNSPECIFIED；平台可选非法化（本项目平台选择＝RES 一律非法化）
- 行 44835–44839 "when a feature is not implemented, the corresponding opcodes ... become
                 reserved, **not necessarily illegal**"（组 3/4/5 的"未实现"面判据）
- 行 55945–55964／55967–55973  特权指令表：SRET／MRET／WFI 的 rs1=rd=00000
- 行 5455–5469／5591  M 扩展成员表（MUL/MULH/MULHSU/MULHU/MULW 均为**定义成员**）
- 行 3174–3180／46895–46909  ECALL/EBREAK 正文与 listing（rd=rs1=0；**本次未动 ISS 此面**，
                 归 `doc/spec/02` §16.3.1 的 D-4「待口径」，回看点见该节）

纪律：前门观察＋状态零变更检查；不改判据本体、不改断言以求通过（红线 R6）。
**预期失效点**：组 1／组 2 的 ISS 检查若被回退（或未来按别口径收窄），P16-1／P16-2 会报 FAIL；
组 3/4/5 若未来被"收窄成非法"，P16-3 会报 FAIL——两者都是**有意留的反证面**，不得为让其通过而改断言。

跑法（仓库根，UTF-8 输出）：
    set PYTHONIOENCODING=utf-8 （bash: PYTHONIOENCODING=utf-8）
    python iss/tests/probes/rr_probe16_iss128_reserved.py
    python iss/tests/probes/rr_probe16_iss128_reserved.py --self-falsify
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]            # probes/ -> tests/ -> iss/ -> 仓库根
sys.path.insert(0, str(ROOT / "iss"))

from vriss import Bus, VrIss, link                     # noqa: E402
from vriss.consts import Csr, Exc                      # noqa: E402
from vriss.encode import MULH, MULW, CSRRC, CSRRWI, enc_i, enc_r   # noqa: E402

OP_JALR = 0x67
OP_SYSTEM = 0x73
OP_OP = 0x33
OP_OP32 = 0x3B

# ---- 官方/位级指令字常量（**写死**；下方 field_decomp() 独立复算位域，防"常量写错却自洽"）---- #
I_JALR_F3_1 = 0x000312E7      # jalr x5, 0(x6) 的位型但 funct3=001（保留）——组 1 主项
I_JALR_F3_7 = 0x000372E7      # 同型、funct3=111（保留）
I_JALR_F3_0 = 0x000302E7      # 同型、funct3=000（**对照**：合法 JALR）
I_MRET = 0x30200073           # 官方 MRET（rs1=x0, rd=x0）
I_MRET_RS1_3 = 0x30218073     # MRET 的 rs1=3（保留字段组合）——组 2 主项
I_MRET_RD_2 = 0x30200173      # MRET 的 rd=2（保留字段组合）——组 2 主项
I_MRET_RS1_3_RD_2 = 0x30218173
I_MRET_RS2_0 = 0x30000073     # f7=MRET 但 rs2=0（dec_probe A18 已覆盖的邻项，对照）
# 组 3/4/5 的**合法**成员编码（对照面；ISS 必须照规范语义执行）
I_MULH = 0x02B090B3           # mulh x1, x1, x11（enc_r(0x01, 11, 1, 1, 1, OP_OP)）
I_CSRRC_MSCRATCH = 0x3400B073  # csrrc x0, mscratch(0x340), x1
I_CSRRWI_MSCRATCH = 0x3400D073  # csrrwi x0, mscratch, 0

CODE = 0x1000
HANDLER = 0x3000               # 本探针的 mtvec 值（trap 落点断言用）
MASK64 = (1 << 64) - 1

FAILS: list[str] = []
_COUNT = [0]


def chk(cid: str, expect: str, ok: bool, got: str) -> None:
    _COUNT[0] += 1
    print("  [%s] %s  expect: %s | got: %s" % (cid, "PASS" if ok else "FAIL", expect, got))
    if not ok:
        FAILS.append(cid)


def field_decomp(word: int) -> dict:
    """**独立**位域复算（不走 machine.py／encode.py 的解码路径）。"""
    return {
        "opcode": word & 0x7F,
        "rd": (word >> 7) & 0x1F,
        "funct3": (word >> 12) & 0b111,
        "rs1": (word >> 15) & 0x1F,
        "rs2": (word >> 20) & 0x1F,
        "funct7": (word >> 25) & 0x7F,
    }


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


def illegal(r) -> bool:
    return r.exc_v == 1 and r.exc_cause == int(Exc.ILLEGAL_INSTR)


def main() -> int:
    print("== rr_probe16: ISS-128 五组保留编码对账（组 1/2 实修 ISS；组 3/4/5 反向裁决=ISS 对） ==")
    print("CMD: python iss/tests/probes/rr_probe16_iss128_reserved.py   (cwd = 仓库根；PYTHONIOENCODING=utf-8)")
    m5 = hashlib.md5((ROOT / "iss" / "vriss" / "machine.py").read_bytes()).hexdigest()
    print("machine.py md5 = %s" % m5)
    print("spec anchors = lines 2686-2698 / 2026-2029 / 44835-44839 / 55945-55973 / 5455-5469+5591")

    print("-- P16-0 常量自检：位域独立复算（防常量写错自洽） --")
    d = field_decomp(I_JALR_F3_1)
    chk("P16-0a", "JALR 常量位域 = opcode 0x67 / f3=1 / rs1=6 / rd=5",
        d["opcode"] == OP_JALR and d["funct3"] == 1 and d["rs1"] == 6 and d["rd"] == 5,
        "op=0x%x f3=%d rs1=%d rd=%d" % (d["opcode"], d["funct3"], d["rs1"], d["rd"]))
    d = field_decomp(I_JALR_F3_7)
    chk("P16-0b", "JALR 变体位域 = opcode 0x67 / f3=7 / rs1=6 / rd=5",
        d["opcode"] == OP_JALR and d["funct3"] == 7 and d["rs1"] == 6 and d["rd"] == 5,
        "op=0x%x f3=%d rs1=%d rd=%d" % (d["opcode"], d["funct3"], d["rs1"], d["rd"]))
    d = field_decomp(I_JALR_F3_0)
    chk("P16-0c", "对照 JALR 位域 = opcode 0x67 / f3=0 / rs1=6 / rd=5",
        d["opcode"] == OP_JALR and d["funct3"] == 0 and d["rs1"] == 6 and d["rd"] == 5,
        "op=0x%x f3=%d rs1=%d rd=%d" % (d["opcode"], d["funct3"], d["rs1"], d["rd"]))
    for cid, w, rs1, rd in (("P16-0d", I_MRET, 0, 0),
                            ("P16-0e", I_MRET_RS1_3, 3, 0),
                            ("P16-0f", I_MRET_RD_2, 0, 2),
                            ("P16-0g", I_MRET_RS1_3_RD_2, 3, 2)):
        d = field_decomp(w)
        chk(cid, "MRET 族位域 = opcode 0x73 / f3=0 / f7=0x18 / rs2=2 / rs1=%d / rd=%d" % (rs1, rd),
            d["opcode"] == OP_SYSTEM and d["funct3"] == 0 and d["funct7"] == 0x18
            and d["rs2"] == 2 and d["rs1"] == rs1 and d["rd"] == rd,
            "op=0x%x f3=%d f7=0x%x rs2=%d rs1=%d rd=%d"
            % (d["opcode"], d["funct3"], d["funct7"], d["rs2"], d["rs1"], d["rd"]))
    d = field_decomp(I_MULH)
    chk("P16-0h", "对照 MULH 位域 = opcode 0x33 / f7=1 / f3=1（§9.1.6 在册成员）",
        d["opcode"] == OP_OP and d["funct7"] == 1 and d["funct3"] == 1,
        "op=0x%x f7=0x%x f3=%d" % (d["opcode"], d["funct7"], d["funct3"]))
    chk("P16-0i", "encode.py 的构造器与写死常量同源（JALR f3=0／MRET／MULH）",
        enc_i(0, 6, 0, 5, OP_JALR) == I_JALR_F3_0 and enc_r(0x18, 2, 0, 0, 0, OP_SYSTEM) == I_MRET
        and MULH(1, 1, 11) == I_MULH,
        "jalr=0x%08x mret=0x%08x mulh=0x%08x" % (enc_i(0, 6, 0, 5, OP_JALR),
                                                 enc_r(0x18, 2, 0, 0, 0, OP_SYSTEM), MULH(1, 1, 11)))

    print("-- P16-1  组 1：JALR funct3≠000（保留）⇒ illegal；对照 f3=000 合法且 link=pc+4 --")
    for cid, w, f3 in (("P16-1a", I_JALR_F3_1, 1), ("P16-1b", I_JALR_F3_7, 7)):
        r, iss = single(w, regs={6: 0x2000}, csrs={int(Csr.MTVEC): HANDLER})
        chk(cid, "f3=%d：illegal（cause=2，mepc=故障指令 pc，落 mtvec）／不写 link／无跳转" % f3,
            illegal(r) and iss.regs[5] == 0 and iss.pc == HANDLER
            and iss.csr.get(Csr.MEPC) == CODE and r.rd_wb_en == 0,
            "exc_v=%d cause=%d x5=0x%x mepc=0x%x pc=0x%x rd_wb=%d"
            % (r.exc_v, r.exc_cause, iss.regs[5], iss.csr.get(Csr.MEPC, 0), iss.pc, r.rd_wb_en))
    r, iss = single(I_JALR_F3_0, regs={6: 0x2002})
    chk("P16-1c", "对照 f3=0：合法 jalr，link=pc+4=0x1004，目标=0x2002（bit0 清零）",
        r.exc_v == 0 and iss.regs[5] == CODE + 4 and iss.pc == 0x2002,
        "exc_v=%d x5=0x%x pc=0x%x mnem=%r" % (r.exc_v, iss.regs[5], iss.pc, r.instr_str))
    print("  [P16-1] INFO  观察（**本次不改**，仅登记）：ISS 的 JALR 记录 `instr_str` 由 `_branch()`")
    print("                 统一写成 'jal'（machine.py `_branch` 尾行；JAL/JALR 同源）——该列**不进**")
    print("                 比对列集（`iss/README.md` §3：instr_str/operand 默认关）⇒ 无可观测分叉，")
    print("                 属可读性面；如要收口归 ISS 侧独立小片（本件只落盘观察）。")

    print("-- P16-2  组 2：MRET 的 rs1≠0 / rd≠0（保留字段）⇒ illegal；对照规范形合法 --")
    for cid, w, note in (("P16-2a", I_MRET_RS1_3, "rs1=3"),
                         ("P16-2b", I_MRET_RD_2, "rd=2"),
                         ("P16-2c", I_MRET_RS1_3_RD_2, "rs1=3 且 rd=2")):
        r, iss = single(w, csrs={int(Csr.MSTATUS): (3 << 11),
                                 int(Csr.MEPC): 0x2000, int(Csr.MTVEC): HANDLER})
        chk(cid, "%s：illegal／未执行 _xret（mstatus 保持 MPP=M、priv 仍 M、未跳 mepc）／落 mtvec" % note,
            illegal(r) and iss.csr[int(Csr.MSTATUS)] == (3 << 11) and iss.pc == HANDLER
            and iss.csr.get(Csr.MEPC) == CODE and r.rd_wb_en == 0,
            "exc_v=%d cause=%d mstatus=0x%x mepc=0x%x pc=0x%x rd_wb=%d"
            % (r.exc_v, r.exc_cause, iss.csr[int(Csr.MSTATUS)], iss.csr.get(Csr.MEPC, 0),
               iss.pc, r.rd_wb_en))
    r, iss = single(I_MRET, csrs={int(Csr.MSTATUS): (3 << 11) | (1 << 7),
                                  int(Csr.MEPC): 0x2000})
    chk("P16-2d", "对照规范形 MRET（rs1=rd=0）：合法，pc=mepc=0x2000，MPP→U、MPIE→1、MIE←MPIE=1",
        r.exc_v == 0 and iss.pc == 0x2000 and r.instr_str == "mret"
        and (iss.csr[int(Csr.MSTATUS)] >> 11) & 3 == 0
        and (iss.csr[int(Csr.MSTATUS)] >> 7) & 1 == 1,
        "exc_v=%d pc=0x%x mstatus=0x%x mnem=%r"
        % (r.exc_v, iss.pc, iss.csr[int(Csr.MSTATUS)], r.instr_str))
    r, iss = single(I_MRET_RS2_0, csrs={int(Csr.MTVEC): HANDLER})
    chk("P16-2e", "邻项对照：f7=MRET 但 rs2=0 ⇒ illegal（原有检查未受影响）",
        illegal(r) and iss.pc == HANDLER, "exc_v=%d cause=%d pc=0x%x"
        % (r.exc_v, r.exc_cause, iss.pc))

    print("-- P16-3  组 3/4/5（**不是保留编码**）：ISS 照 `doc/spec/02` §9.1 成员表合法执行 = 正确 --")
    r, iss = single(I_MULH, regs={1: -3 & MASK64, 11: 5})
    chk("P16-3a", "组 3：MULH（0x201，§9.1.6 在册成员）合法且语义正确：(-3)×5 高 64 位 = -1",
        r.exc_v == 0 and iss.regs[1] == MASK64 and r.instr_str == "mulh",
        "exc_v=%d x1=0x%x mnem=%r" % (r.exc_v, iss.regs[1], r.instr_str))
    r, iss = single(MULW(1, 1, 11), regs={1: 0x1_0000_0002, 11: 3})
    chk("P16-3b", "组 4：MULW（0x210）合法且按 bit31 符号扩展（既有语义回归 t_mulw 同口径）",
        r.exc_v == 0 and iss.regs[1] == 6 and r.instr_str == "mulw",
        "exc_v=%d x1=0x%x mnem=%r" % (r.exc_v, iss.regs[1], r.instr_str))
    r, iss = single(CSRRC(0, int(Csr.MSCRATCH), 1), regs={1: 0b1010},
                    csrs={int(Csr.MSCRATCH): 0b1111})
    chk("P16-3c", "组 5：CSRRC（0x302，§9.1.7 在册成员）合法且清位语义正确（0b1111 & ~0b1010 = 0b0101）",
        r.exc_v == 0 and iss.csr[int(Csr.MSCRATCH)] == 0b0101 and r.instr_str == "csrrc",
        "exc_v=%d mscratch=0x%x mnem=%r" % (r.exc_v, iss.csr[int(Csr.MSCRATCH)], r.instr_str))
    r, iss = single(CSRRWI(0, int(Csr.MSCRATCH), 3))
    chk("P16-3d", "组 5：CSRRWI（0x303）合法且 uimm 语义正确（写 3）",
        r.exc_v == 0 and iss.csr[int(Csr.MSCRATCH)] == 3 and r.instr_str == "csrrwi",
        "exc_v=%d mscratch=0x%x mnem=%r" % (r.exc_v, iss.csr[int(Csr.MSCRATCH)], r.instr_str))
    print("  [P16-3] INFO  裁决：组 3/4/5 的差异源＝**RTL 首版实现子集**（`vr1_decode.sv` 头 53–63 行")
    print("                 自述这 30 个成员是'G1-F 后才入面的合法 RV64 指令'，非保留段）＋")
    print("                 `doc/spec/02` §9.3 只在**保留段**上取'一律非法化'的平台选择 ⇒")
    print("                 **ISS 侧不改**（收窄＝与 §9.1 成员表相抵＋抹掉 DUT 真实缺口）；")
    print("                 归属＝G1-F／T-2／T-3 实现面增量批（同 `doc/verify/02` §7 CC-4/CC-15 行）。")

    n_fail = len(FAILS)
    print("== probe16 summary: checks=%d fail=%d %s =="
          % (_COUNT[0], n_fail, ("| FAIL ids: " + ",".join(FAILS)) if FAILS else ""))
    return 1 if FAILS else 0


def self_falsify() -> int:
    """自证伪（负控）：三处单点注入，验证各检查点的谓词确实**会翻假**（即检查器有效）。

    注入 A（换回规范形）：组 2 的 MRET rs1=3 -> 官方 MRET（rs1=rd=0）⇒ "illegal" 谓词应翻假；
    注入 B（把 f3 拨回 0）：组 1 的 JALR f3=1 -> f3=0 ⇒ "illegal" 谓词应翻假（含 link 写回）；
    注入 C（跨类注入）：把"保留编码"换成**在册合法成员** MULH ⇒ "illegal" 谓词应翻假
            （证明本探针的"保留"判据不是无差别拒绝）。
    谓词未翻假者报 MISS（该检查点无鉴别力）。
    """
    print("== rr_probe16 [SELF-FALSIFY]：单点注入负控（每个检查点配一次反证） ==")
    print("CMD: python iss/tests/probes/rr_probe16_iss128_reserved.py --self-falsify")
    m5 = hashlib.md5((ROOT / "iss" / "vriss" / "machine.py").read_bytes()).hexdigest()
    print("machine.py md5 = %s" % m5)
    missed: list[str] = []

    def red(cid: str, inject: str, pred_ok: bool, got: str) -> None:
        print("  [%s] %s  inject: %s | pred=%s got: %s"
              % (cid, "RED-CAUGHT" if not pred_ok else "MISS", inject,
                 "False（主运行该点将报 FAIL）" if not pred_ok else "True（未翻假！）", got))
        if pred_ok:
            missed.append(cid)

    r, iss = single(I_MRET, csrs={int(Csr.MSTATUS): (3 << 11), int(Csr.MEPC): 0x2000,
                                  int(Csr.MTVEC): HANDLER})
    red("FS-A", "P16-2a 的 MRET rs1=3 -> 官方 MRET（rs1=rd=0）",
        illegal(r), "exc_v=%d cause=%d pc=0x%x mnem=%r"
        % (r.exc_v, r.exc_cause, iss.pc, r.instr_str))

    r, iss = single(I_JALR_F3_0, regs={6: 0x2000})
    red("FS-B", "P16-1a 的 JALR f3=1 -> f3=0（拨回规范形）",
        illegal(r), "exc_v=%d cause=%d x5=0x%x pc=0x%x"
        % (r.exc_v, r.exc_cause, iss.regs[5], iss.pc))

    r, iss = single(I_MULH, regs={1: 1, 11: 1})
    red("FS-C", "P16-1/2 的保留编码 -> 在册合法成员 MULH（跨类注入）",
        illegal(r), "exc_v=%d cause=%d mnem=%r" % (r.exc_v, r.exc_cause, r.instr_str))

    print("== falsify summary: injections=3 %s =="
          % ("red caught=3（检查器有效：主运行会报红）" if not missed
             else "MISS ids: " + ",".join(missed)))
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(self_falsify() if "--self-falsify" in sys.argv else main())
