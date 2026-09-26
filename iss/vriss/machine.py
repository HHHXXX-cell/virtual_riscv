"""VR1 golden ISS 主体：RV64IMAC 的 M/S/U 机器模型（骨架 = RV64I + RV64M + 机器态 CSR）。

设计约束（与规格同步，改一处必须同改两处）：
- `doc/spec/02` 逐指令行为表：本文件的 execute 分支是其可执行化身；
- `doc/spec/10` CSR 表与 trap 语义：本文件的 csr_read/csr_write/_take_trap 为其实现；
- `doc/spec/01` §3.21 `rt_t`：`trace.RetireRecord` 为其软件化身。

一期刻意**不实现**（每项都留了显式异常，绝不静默走偏）：
  RV64C（等 `doc/spec/02` §5 展开表）、RV64A（LR/SC/AMO）、Sv39 翻译（当前恒 Bare）、
  F/D（按 `doc/spec/00` §7 报 illegal）、S 态委托（medeleg/mideleg 恒 0）。
"""
from __future__ import annotations

from .consts import (
    INTR_BIT,
    MISA_RV64_IMAC,
    MPP_SHIFT,
    MSTATUS_WMASK,
    MSTATUS_WMASK_S,
    MTVEC_DIRECT,
    MTVEC_VECTORED,
    SPP_SHIFT,
    Csr,
    Exc,
    Intr,
    MStatus,
    M_INTR_PRIORITY,
    Priv,
    RESET_PC,
    sext,
    u64,
    sext32,
)
from .encode import (
    OP_AMO, OP_AUIPC, OP_JAL, OP_JALR, OP_LOAD, OP_LUI, OP_MISC_MEM, OP_OP,
    OP_OP32, OP_OP_IMM, OP_OP_IMM32, OP_STORE, OP_SYSTEM,
)
from .mem import Bus, Fault
from .trace import ABI_NAMES, RetireRecord

MASK64 = (1 << 64) - 1
READ_ONLY_CSR_MIN = 0xC00          # CSR[11:10] == 2'b11 → 只读


def _s(v: int) -> int:
    """64 位补码转 Python 有符号。"""
    return v - (1 << 64) if v >> 63 else v


def _u(v: int) -> int:
    return v & MASK64


def _shamt_i(instr: int) -> int:
    return (instr >> 20) & 0x3F


def _shamt_r(rs2: int) -> int:
    return rs2 & 0x3F


class TrapExit(Exception):
    """程序主动结束（用于 bare-metal 自检的 tohost 语义）。"""

    def __init__(self, code: int):
        super().__init__(f"halt code={code}")
        self.code = code


class VrIss:
    """RV64IM 退休级机器模型。逐指令 `step()` 产 `RetireRecord`。"""

    def __init__(self, bus: Bus | None = None, reset_pc: int = RESET_PC,
                 tohost_addr: int | None = None):
        self.bus = bus or Bus()
        self.pc = reset_pc & MASK64
        self.priv = Priv.MACHINE
        self.regs = [0] * 32
        self.csr: dict[int, int] = {
            Csr.MISA: MISA_RV64_IMAC,
            Csr.VENDORID: 0, Csr.MARCHID: 0, Csr.MIMPID: 0, Csr.MHARTID: 0,
            Csr.MCYCLE: 0, Csr.MINSTRET: 0,
        }
        self.seq = 0
        self.cycle = 0
        self.halted = False
        self.halt_val: int | None = None
        self.tohost_addr = tohost_addr
        self.pending_intr: int | None = None
        self.records: list[RetireRecord] = []

    # ------------------------------------------------------------------ #
    # CSR
    # ------------------------------------------------------------------ #
    def csr_read(self, addr: int) -> int:
        if addr == Csr.MSTATUS:
            return self.csr.get(Csr.MSTATUS, 0)
        if addr == Csr.SSTATUS:
            # sstatus 是 mstatus 的受限视图（特权规范 §4.1.1）
            m = self.csr.get(Csr.MSTATUS, 0)
            return m & (MStatus.SIE | MStatus.SPIE | MStatus.SPP | MStatus.SUM
                        | MStatus.MXR | (3 << 13))
        if addr == Csr.MCYCLE:
            return u64(self.cycle)
        if addr == Csr.MINSTRET:
            return u64(self.seq)
        return self.csr.get(addr, 0)

    def csr_write(self, addr: int, val: int) -> None:
        val = u64(val)
        if (addr >> 10) & 0b11 == 0b11:            # CSR[11:10]==2'b11 → 只读，写即 illegal（§2.1）
            raise Fault(Exc.ILLEGAL_INSTR, 0)
        if addr == Csr.MSTATUS:
            self.csr[addr] = val & MSTATUS_WMASK   # 其余位 WARL 忽略（doc/spec/10）
        elif addr == Csr.SSTATUS:
            m = self.csr.get(Csr.MSTATUS, 0) & ~MSTATUS_WMASK_S
            self.csr[Csr.MSTATUS] = u64(m | (val & MSTATUS_WMASK_S))
        elif addr == Csr.MISA:
            pass                                   # 一期只报告不开关（§3.1.1 允许）
        else:
            self.csr[addr] = val

    # ------------------------------------------------------------------ #
    # 取指 / 单步
    # ------------------------------------------------------------------ #
    def fetch(self, addr: int) -> int:
        return self.bus.read(addr, 4, signed=False, fetch=True)

    def step(self) -> RetireRecord:
        """执行一条指令并产出退休记录（含异常退休）。"""
        rec = RetireRecord(pc=self.pc & MASK64, priv=int(self.priv),
                           seq=self.seq, cycle=self.cycle)
        self.cycle += 1
        try:
            instr = self.fetch(self.pc)
        except Fault as f:
            rec.instr = 0
            self._retire_trap(rec, f.cause, f.tval)
            return rec
        rec.instr = instr
        rec.is_c = 0 if (instr & 0b11) == 0b11 else 1
        if rec.is_c:
            rec.instr_str = "c.???"
            raise NotImplementedError(
                "RV64C 展开表未实现：等 doc/spec/02 §5 冻结后补（见 iss/README.md §5）")
        try:
            self._exec(rec, instr)
        except Fault as f:
            self._retire_trap(rec, f.cause, f.tval if f.tval else instr)
        self.seq += 1
        self.records.append(rec)
        return rec

    def run(self, max_instr: int = 1_000_000) -> tuple[int, list[RetireRecord]]:
        """跑到 halt 或 watchdog 上限。上限值来自 `AGENTS.md` §5.2 规则 9 的拍预算。"""
        n = 0
        while not self.halted and n < max_instr:
            self.step()
            n += 1
        return n, self.records

    # ------------------------------------------------------------------ #
    # trap
    # ------------------------------------------------------------------ #
    def _retire_trap(self, rec: RetireRecord, cause: Exc | Intr, tval: int,
                     is_intr: int = 0) -> None:
        rec.exc_v, rec.exc_cause, rec.is_intr = 1, int(cause), is_intr
        self._take_trap(cause, tval, rec, is_intr)

    def _take_trap(self, cause: Exc | Intr, tval: int, rec: RetireRecord,
                   is_intr: int = 0) -> None:
        """trap 进入的 6 个硬件动作（特权规范 §3.1.6.1/§3.1.7/§3.1.14~16）。
        一期无委托：一律进 M 模式，写 M 组寄存器。"""
        self.csr[Csr.MCAUSE] = u64((INTR_BIT if is_intr else 0) | int(cause))
        self.csr[Csr.MTVAL] = u64(tval)
        self.csr[Csr.MEPC] = u64(rec.pc)
        m = self.csr.get(Csr.MSTATUS, 0)
        m = (m & ~MStatus.MPIE) | ((m & MStatus.MIE) << 4)
        m = (m & ~(MStatus.MIE))
        m = (m & ~(3 << MPP_SHIFT)) | (int(self.priv) << MPP_SHIFT)
        self.csr[Csr.MSTATUS] = u64(m)
        self.priv = Priv.MACHINE
        base = self.csr.get(Csr.MTVEC, 0)
        mode = base & 0b11
        target = (base & ~0b11) if (mode == MTVEC_DIRECT or not is_intr) \
            else u64((base & ~0b11) + 4 * int(cause))
        self.pc = u64(target)

    def _xret(self, rec: RetireRecord) -> None:
        """xRET 语义（§3.3.2）：MIE←MPIE；模式←MPP；MPIE←1；MPP←最低可用模式；若 MPP≠M 则 MPRV←0。"""
        m = self.csr.get(Csr.MSTATUS, 0)
        mpp = (m >> MPP_SHIFT) & 0b11
        if mpp == 0b10:                        # 保留值：按规范写不进，回退为 M
            mpp = int(Priv.MACHINE)
        new = m & ~MStatus.MIE & ~MStatus.MPIE & ~MStatus.MPP
        new |= ((m & MStatus.MPIE) >> 4)                    # MIE ← MPIE
        new |= int(MStatus.MPIE)                            # MPIE ← 1
        new |= int(Priv.USER) << MPP_SHIFT                  # MPP ← 最低可用模式（U 已实现）
        if mpp != int(Priv.MACHINE):
            new &= ~int(MStatus.MPRV)                       # 仅 y≠M 时清 MPRV（行 45130，ISS-064）
        self.csr[Csr.MSTATUS] = u64(new)
        self.priv = Priv(mpp)
        self.pc = u64(self.csr.get(Csr.MEPC, 0))
        rec.instr_str, rec.operand = "mret", ""

    def inject_interrupt(self, intr: Intr, source: int = 0) -> None:
        """外部置 mip 位（平台侧只读位由 CLINT/PLIC 驱动，见 doc/spec/10）。"""
        self.csr[Csr.MIP] = u64(self.csr.get(Csr.MIP, 0) | (1 << int(intr)))

    def _pending_m_intr(self) -> Intr | None:
        """中断进 M 的三条件（§3.1.9）：(a) M 且 MIE，或低于 M；(b) mip&mie；(c) 未委托。"""
        mip = self.csr.get(Csr.MIP, 0)
        mie = self.csr.get(Csr.MIE, 0)
        m = self.csr.get(Csr.MSTATUS, 0)
        glob = bool(m & MStatus.MIE) if self.priv == Priv.MACHINE else True
        if not glob:
            return None
        for code in M_INTR_PRIORITY:
            if (mip & (1 << int(code))) and (mie & (1 << int(code))):
                return code
        return None

    # ------------------------------------------------------------------ #
    # 译码 + 执行（doc/spec/02 的可执行化身）
    # ------------------------------------------------------------------ #
    def _rd(self, rec: RetireRecord, instr: int, val: int) -> None:
        rd = (instr >> 7) & 0x1F
        val = u64(val)
        if rd:
            self.regs[rd] = val
            rec.rd_idx, rec.rd_wb_en, rec.rd_data = rd, 1, val

    def _rs1(self, instr: int) -> int:
        idx = (instr >> 15) & 0x1F
        return u64(self.regs[idx]) if idx else 0

    def _rs2(self, instr: int) -> int:
        idx = (instr >> 20) & 0x1F
        return u64(self.regs[idx]) if idx else 0

    def _exec(self, rec: RetireRecord, instr: int) -> None:
        op = instr & 0x7F
        rd_f = (instr >> 7) & 0x1F
        f3 = (instr >> 12) & 0b111
        rs1_f = (instr >> 15) & 0x1F
        funct7 = (instr >> 25) & 0x7F
        # 立即数必须按**自身位宽**符号扩展（不是按 bit63）——12/13/21 位各自不同
        imm_i = sext((instr >> 20) & 0xFFF, 12)
        next_pc = u64(self.pc + 4)

        # 中断：指令边界采样（不晚于该指令进入，doc/spec/01 §5.1）
        pend = self._pending_m_intr()
        if pend is not None:
            self._retire_trap(rec, pend, 0, is_intr=1)
            return

        if op == OP_LUI:
            # LUI: rd = sext32({imm[31:12], 12'b0})——不是 20 位立即数本身
            self._rd(rec, instr, sext32(instr & 0xFFFFF000))
            rec.instr_str, rec.operand = "lui", f"x{rd_f},0x{(instr >> 12) & 0xFFFFF:x}"
        elif op == OP_AUIPC:
            self._rd(rec, instr, u64(self.pc + sext32(instr & 0xFFFFF000)))
            rec.instr_str, rec.operand = "auipc", f"x{rd_f},0x{(instr >> 12) & 0xFFFFF:x}"
        elif op == OP_JAL:
            imm = _j_imm(instr)
            self._rd(rec, instr, next_pc)
            self._branch(rec, u64(self.pc + imm), taken=True)
        elif op == OP_JALR:
            # funct3≠000 是**保留编码**：规范只为 JALR 定义 f3=000（提取件行 2686–2698 编码表
            # 逐字段值：rd=dest／**funct3=0**／rs1=base／imm=offset[11:0]）⇒ f3≠0 的字不映射任何
            # 合法指令；保留编码的译码行为 **UNSPECIFIED**（行 2026–2029），本项目取
            # 「RES 编码点一律非法化」为平台选择（`doc/spec/02` §9.3 依据句）⇒ 必须 illegal，
            # 不得按 f3=000 的语义执行（ISS-128 ①；与同族 ISS-063 的 SLLI/SRLI funct6 保留位
            # 检查同一口径）。检查置于一切状态变更之前（不写 link、不跳转）。
            if f3 != 0:
                raise Fault(Exc.ILLEGAL_INSTR, instr)
            tgt = u64((self._rs1(instr) + imm_i) & ~1)
            self._rd(rec, instr, next_pc)
            self._branch(rec, tgt, taken=True)
        elif op == 0x63:                                   # BRANCH
            a, b = self._rs1(instr), self._rs2(instr)
            sa, sb = _s(a), _s(b)
            if f3 not in _BR_CMP:
                raise Fault(Exc.ILLEGAL_INSTR, instr)     # funct3=2/3 为保留编码，不得 KeyError
            taken = _BR_CMP[f3](sa, sb, a, b)
            rec.is_br = 1
            if taken:
                self._branch(rec, u64(self.pc + _b_imm(instr)), taken=True)
                rec.instr_str = _BR_MNEM[f3]
            else:
                self.pc = next_pc
                rec.instr_str, rec.operand = _BR_MNEM[f3], f"x{rs1_f},x{(instr >> 20) & 0x1F},nt"
        elif op == OP_LOAD:
            if f3 == 7:
                raise Fault(Exc.ILLEGAL_INSTR, instr)
            addr = u64(self._rs1(instr) + imm_i)
            signed = f3 in (0, 1, 2, 3)                 # f3[2] 为无符号位，不是宽度位
            size = _LOAD_SIZE[f3]                        # LB/LBU=1 LH/LHU=2 LW/LWU=4 LD=8
            val = self.bus.read(addr, size, signed=signed)
            self._rd(rec, instr, val)
            rec.mem_v, rec.mem_addr, rec.mem_rdata, rec.mem_size = 1, addr, u64(val), size
            rec.mem_kind = "load"
        elif op == OP_STORE:
            if f3 > 3:
                raise Fault(Exc.ILLEGAL_INSTR, instr)
            addr = u64(self._rs1(instr) + _s_imm(instr))
            size = 1 << f3
            data = self._rs2(instr)
            self.bus.write(addr, size, data)
            if self.tohost_addr is not None and addr == self.tohost_addr:
                # riscv-tests 语义：**写 1 为 PASS；写 (testnum<<1)|1 为 FAIL**。
                # 故直接存原始值，判据在顶层应写 `halt_val == 1`，不得先 `>>1`。
                self.halted, self.halt_val = True, data
            rec.mem_v, rec.mem_addr, rec.mem_wdata, rec.mem_size, rec.mem_wr = 1, addr, data, size, 1
            rec.mem_kind = "store"
        elif op == OP_OP_IMM:
            self._op_imm(rec, instr, f3, imm_i, rd_f, funct7)
        elif op == OP_OP_IMM32:
            self._op_imm32(rec, instr, f3, imm_i, rd_f, funct7)
        elif op == OP_OP:
            self._op(rec, instr, f3, funct7, rd_f)
        elif op == OP_OP32:
            self._op32(rec, instr, f3, funct7, rd_f)
        elif op == OP_MISC_MEM:
            if f3 not in (0, 1):
                raise Fault(Exc.ILLEGAL_INSTR, instr)          # 只允许 FENCE(0) / FENCE.I(1)
            rec.instr_str = "fence" if f3 == 0 else "fence.i"
            self.pc = next_pc
        elif op == OP_AMO:
            raise NotImplementedError("RV64A：等 doc/spec/02 §6 冻结后补（LR/SC 见 spec/07）")
        elif op == 0x73:                                    # SYSTEM
            self._system(rec, instr, f3, imm_i, rd_f, funct7)
        else:
            raise Fault(Exc.ILLEGAL_INSTR, instr)

        # JAL/JALR/分支的目标一律由 handler 已设；不得再用“pc 有没有变”当作已跳转的判据：
        # `jal x0,0`（自旋）把 pc 设回原值，会被该启发误推一条（评审 ISS-019 Q21）。
        if not rec.exc_v and op not in (0x63, OP_JAL, OP_JALR) and rec.pc == self.pc:
            self.pc = next_pc

    # ---- ALU 立即数 / 寄存器型 ---------------------------------------- #
    def _op_imm(self, rec: RetireRecord, instr: int, f3: int, imm: int,
                rd: int, funct7: int) -> None:
        x = self._rs1(instr)
        hi6 = (instr >> 26) & 0x3F
        # 移位合法值域（规范提取件行 3459–3462）：SLLI imm[11:6]=000000；SRLI=000000；SRAI=010000。
        # 右移类型位在 **instr[30]**（hi6==0x10）——对 SLLI(f3=1) 属保留编码，必须非法（ISS-063）；
        # funct6=100000（hi6==0x20）等其余值一律保留。
        if (f3 == 1 and hi6 != 0x00) or (f3 == 5 and hi6 not in (0x00, 0x10)):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        sh = (instr >> 20) & 0x3F
        # SLTI（f3=2，ISS-124 修复）：`imm` 由 `_exec` 经 `sext(...,12)` **已是 Python 有符号**值，
        # 不得再送 `_s()`（`_s` 是 u64→有符号；对已是负数的 Python 整数会再减 2**64 ⇒ 比较恒错）。
        # 权（一级依据）：riscv_spec_full.txt 行 2382-2383「SLTI … rs1 is less than the sign-extended
        # immediate when both are treated as signed numbers」。
        val = {
            0: x + imm, 2: int(_s(x) < imm), 3: int(x < u64(imm)),
            4: x ^ u64(imm), 6: x | u64(imm), 7: x & u64(imm),
            1: u64(x << sh),
            5: self._shift_r(x, sh, hi6 & 0x10, 64),
        }[f3]
        self._rd(rec, instr, val)
        rec.instr_str = _mnemonic("i", f3, hi6)

    def _op_imm32(self, rec: RetireRecord, instr: int, f3: int, imm: int,
                  rd: int, funct7: int) -> None:
        x = self._rs1(instr)
        hi6 = (instr >> 26) & 0x3F
        if f3 not in (0, 1, 5):
            raise Fault(Exc.ILLEGAL_INSTR, instr)      # ADDIW/SLLIW/SRLIW/SRAIW 之外的 funct3 保留
        # 32 位移位：imm[11:5] 必须为 0（SLLIW/SRLIW）或 0100000（SRAIW）——
        # imm[5]≠0 是保留编码（规范提取件行 3516–3518）。ADDIW(f3=0) 的 imm 是普通 12 位
        # 立即数（行 3417），无保留构型，不得按移位域过滤（原实现过拒绝，同片修复）。
        if f3 in (1, 5) and (hi6 not in (0x00, 0x10) or (hi6 == 0x10 and f3 != 5)
                             or (instr >> 25) & 1):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        sh = (instr >> 20) & 0x1F
        val = {
            0: sext32(x + imm), 1: sext32(u64((x & MASK32LOCAL) << sh)),
            5: self._shift_r32(x, sh, hi6 & 0x10),
        }[f3]
        self._rd(rec, instr, val)
        rec.instr_str = _mnemonic("iw", f3, hi6)

    def _op(self, rec: RetireRecord, instr: int, f3: int, funct7: int, rd: int) -> None:
        x, y = self._rs1(instr), self._rs2(instr)
        if funct7 == 0x01:
            self._m(rec, instr, f3, x, y)
            return
        if funct7 not in (0x00, 0x20) or (funct7 == 0x20 and f3 not in (0, 5)):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        val = {
            0: x + y if funct7 != 0x20 else x - y,
            2: int(_s(x) < _s(y)), 3: int(x < y),
            4: x ^ y, 6: x | y, 7: x & y,
            1: u64(x << (y & 63)),
            5: self._shift_r(x, y & 63, funct7 & 0x20, 64),   # SRA 的 funct7=0100000
        }[f3]
        self._rd(rec, instr, val)
        rec.instr_str = _mnemonic("r", f3, funct7)

    def _op32(self, rec: RetireRecord, instr: int, f3: int, funct7: int, rd: int) -> None:
        x, y = self._rs1(instr), self._rs2(instr)
        if funct7 == 0x01:
            self._mw(rec, instr, f3, x, y)                    # MULW/DIVW/DIVUW/REMW/REMUW
            return
        if funct7 not in (0x00, 0x20) or (funct7 == 0x20 and f3 not in (0, 5)) \
                or f3 not in (0, 1, 5):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        w = x & MASK32LOCAL
        wy = y & MASK32LOCAL
        # f3=000：ADDW／SUBW 由 **funct7** 分流（ISS-125 修复）——原式只做 `w + y` ⇒ SUBW（funct7=0x20）
        # 被当 ADDW 执行（同函数 f3=5 分支已按 funct7 分 SRLW/SRAW，仅此支漏）。
        # 权（一级依据）：riscv_spec_full.txt 行 3609-3611「ADDW and SUBW … defined analogously to ADD
        # and SUB but operate on 32-bit values and produce signed 32-bit results」。
        val = {
            0: sext32(u64(((w + wy) if funct7 != 0x20 else (w - wy)) & MASK32LOCAL)),
            1: sext32(u64((w << (y & 31)) & MASK32LOCAL)),
            5: (sext32(u64((w >> (y & 31)) & MASK32LOCAL)) if funct7 != 0x20
                else sext32(_s32(w) >> (y & 31) & MASK32LOCAL)),
        }[f3]
        self._rd(rec, instr, val)
        rec.instr_str = _mnemonic("rw", f3, funct7)

    def _shift_r(self, x: int, sh: int, arith: int, bits: int) -> int:
        sh &= bits - 1
        return u64((x >> sh) | (~0 << (bits - sh))) if arith and (x >> (bits - 1)) else u64(x >> sh)

    def _shift_r32(self, x: int, sh: int, arith: int) -> int:
        sh &= 31
        v = x & MASK32LOCAL
        if arith:
            return sext32(_s32(v) >> sh)
        return sext32(v >> sh)

    def _m(self, rec: RetireRecord, instr: int, f3: int, x: int, y: int) -> None:
        sx, sy = _s(x), _s(y)
        if y == 0:                                          # 除零：RV64 定义商全 1、余=被除数
            val = {4: MASK64, 5: MASK64, 6: x, 7: x}[f3] if f3 in (4, 5, 6, 7) else 0
        else:
            over = (sx == -(1 << 63) and sy == -1)
            if f3 == 0:
                val = u64(sx * sy)
            elif f3 == 1:
                val = u64((sx * sy) >> 64)
            elif f3 == 2:
                val = u64((sx * u64(y)) >> 64)
            elif f3 == 3:
                val = u64((x * y) >> 64)
            elif f3 == 4:
                val = u64(-(1 << 63)) if over else _trunc_div(sx, sy)
            elif f3 == 5:
                val = u64(x // y) if x >= 0 and y >= 0 else _trunc_div(x, y)
            elif f3 == 6:
                val = 0 if over else _rem(sx, sy)
            else:
                val = _rem(x, y)
        self._rd(rec, instr, val)
        rec.instr_str = _mnemonic("m", f3, 0x01)

    def _mw(self, rec: RetireRecord, instr: int, f3: int, x: int, y: int) -> None:
        """RV64 M 的 W 型：低 32 位运算后按 bit31 符号扩展。"""
        if f3 not in (0, 4, 5, 6, 7):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        xw, yw = x & MASK32LOCAL, y & MASK32LOCAL
        sx, sy = _s32(xw), _s32(yw)
        rec.instr_str = {0: "mulw", 4: "divw", 5: "divuw", 6: "remw", 7: "remuw"}[f3]
        if f3 == 0:
            self._rd(rec, instr, sext32(u64(sx * sy)))
            return
        zero = (yw == 0)
        over = (sx == -(1 << 31) and sy == -1)
        if f3 == 4:                                            # DIVW
            val = MASK32LOCAL if zero else (1 << 31) if over else _trunc_div(sx, sy) & MASK32LOCAL
        elif f3 == 5:                                          # DIVUW
            val = MASK32LOCAL if zero else _trunc_div(xw, yw) & MASK32LOCAL
        elif f3 == 6:                                          # REMW
            val = xw if zero else (0 if over else _rem(sx, sy) & MASK32LOCAL)
        else:                                                  # REMUW
            val = xw if zero else _rem(xw, yw) & MASK32LOCAL
        self._rd(rec, instr, sext32(val & MASK32LOCAL))

    # ---- 分支 / 系统 ----------------------------------------------- #
    def _branch(self, rec: RetireRecord, target: int, taken: bool) -> None:
        if target & 1:
            raise Fault(Exc.INSTR_ADDR_MISALIGNED, target)
        self.pc = u64(target)
        rec.instr_str, rec.operand = "jal", f"->0x{target:x}" if taken else ""

    def _system(self, rec: RetireRecord, instr: int, f3: int, imm_i: int,
                rd: int, funct7: int) -> None:
        if f3 == 0:
            self._sys_op(rec, instr, funct7)
            return
        if f3 not in (1, 2, 3, 5, 6, 7):
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        csr = imm_i & 0xFFF
        _csr_priv_check(csr, self.priv, instr)
        imm_form = f3 >= 5                          # CSR*I 的 uimm 放 rs1 域
        src = self._rs2_shamt(instr) if imm_form else self._rs1(instr)
        op = f3 - 4 if imm_form else f3             # 1=RW 2=RS 3=RC
        # 写使能判据（§2.1）：CSRRW 恒写；CSRRS/CSRRC 仅源非 0 时写
        writes = (op == 1) or (src != 0)
        if ((csr >> 10) & 0b11) == 0b11 and writes:
            raise Fault(Exc.ILLEGAL_INSTR, instr)    # 写只读 CSR → illegal
        self.csr.setdefault(csr, 0)
        old = self.csr_read(csr)
        new = u64(src) if op == 1 else (
            u64(old | src) if op == 2 else u64(old & ~u64(src)))
        if writes:
            self.csr_write(csr, new)
        rec.csr_addr, rec.csr_old, rec.csr_new = csr, old, new
        rec.csr_wr_en = 1 if writes else 0
        rec.instr_str = {1: "csrrw", 2: "csrrs", 3: "csrrc",
                         5: "csrrwi", 6: "csrrsi", 7: "csrrci"}[f3]
        rec.operand = f"0x{csr:03x},x{rd}"
        if rd:
            self._rd(rec, instr, old)

    def _sys_op(self, rec: RetireRecord, instr: int, funct7: int) -> None:
        low5 = (instr >> 20) & 0x1F
        if funct7 == 0x00:
            if low5 == 0:                                     # ECALL
                cause = {Priv.USER: Exc.ECALL_U, Priv.SUPERVISOR: Exc.ECALL_S,
                         Priv.MACHINE: Exc.ECALL_M}[self.priv]
                self.pc = u64(self.pc + 4)
                self._retire_trap(rec, cause, 0)
                return
            if low5 == 1:                                     # EBREAK  0x00100073
                self.pc = u64(self.pc + 4)
                # mtval：本指令地址或 0（不得用 pc+4）
                self._retire_trap(rec, Exc.BREAKPOINT, rec.pc)
                return
            raise Fault(Exc.ILLEGAL_INSTR, instr)
        if funct7 == 0x18 and low5 == 2:                       # MRET  0x30200073
            # MRET 的 rs1／rd 在特权指令表里是**固定 00000**（提取件行 55952–55964 的六字段表：
            # 0011000／00010／**00000(rs1)**／000／**00000(rd)**／1110011）⇒ 非零组合是保留编码点
            # （同表 SRET 行 55945–55951、WFI 行 55967–55973 同为 rs1=rd=00000）；
            # 平台选择同 ①（`doc/spec/02` §9.3 依据句）⇒ 报 illegal，不得当 MRET 执行
            # （ISS-128 ②）。检查置于 `_xret` 之前（不改 mstatus／mepc／priv／pc）。
            if ((instr >> 15) & 0x1F) != 0 or ((instr >> 7) & 0x1F) != 0:
                raise Fault(Exc.ILLEGAL_INSTR, instr)
            self._xret(rec)
            return
        if funct7 == 0x08:
            if low5 == 2:                                       # SRET  0x10200073
                raise NotImplementedError("SRET：等 doc/spec/10 的 S 态委托冻结后补")
            if low5 == 5:                                       # WFI   0x10500073
                rec.instr_str = "wfi"                           # 一期当 NOP（允许，【权】§3.3.3）
                return
        if funct7 == 0x09:                                      # SFENCE.VMA funct6=000100
            raise NotImplementedError("SFENCE.VMA：等 doc/spec/08 MMU 冻结后补")
        raise Fault(Exc.ILLEGAL_INSTR, instr)

    def _rs2_shamt(self, instr: int) -> int:
        return (instr >> 15) & 0x1F                            # CSR*I 的 uimm 放 rs1 域


# --------------------------------------------------------------------------- #
# 立即数抽取
# --------------------------------------------------------------------------- #
def _s_imm(instr: int) -> int:
    return sext(((instr >> 25) & 0x7F) << 5 | ((instr >> 7) & 0x1F), 12)


def _b_imm(instr: int) -> int:
    return sext((((instr >> 31) & 1) << 12) | (((instr >> 7) & 1) << 11)
                | (((instr >> 25) & 0x3F) << 5) | (((instr >> 8) & 0xF) << 1), 13)


def _j_imm(instr: int) -> int:
    return sext((((instr >> 31) & 1) << 20) | (((instr >> 12) & 0xFF) << 12)
                | (((instr >> 20) & 1) << 11) | (((instr >> 21) & 0x3FF) << 1), 21)


MASK32LOCAL = (1 << 32) - 1


def _s32(v: int) -> int:
    return v - (1 << 32) if v >> 31 else v


def _trunc_div(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return u64(-q if (a < 0) != (b < 0) else q)


def _rem(a: int, b: int) -> int:
    return u64(a - b * (abs(a) // abs(b) * (-1 if (a < 0) != (b < 0) else 1)))


def _csr_priv_check(csr: int, priv: int, instr: int) -> None:
    """CSR 访问权限按地址位 [9:8] 检查（特权规范 §2.1）。"""
    need = (csr >> 8) & 0b11
    if need > priv:
        raise Fault(Exc.ILLEGAL_INSTR, instr)


_BR_MNEM = {0: "beq", 1: "bne", 4: "blt", 5: "bge", 6: "bltu", 7: "bgeu"}

_MNEM_I = {0: "addi", 2: "slti", 3: "sltiu", 4: "xori", 6: "ori", 7: "andi", 1: "slli", 5: "srli"}
_MNEM_IW = {0: "addiw", 1: "slliw", 5: "srliw"}
_MNEM_R = {0: "add", 2: "slt", 3: "sltu", 4: "xor", 6: "or", 7: "and", 1: "sll", 5: "srl"}
_MNEM_RW = {0: "addw", 1: "sllw", 5: "srlw"}
_MNEM_M = {0: "mul", 1: "mulh", 2: "mulhsu", 3: "mulhu", 4: "div", 5: "divu", 6: "rem", 7: "remu"}


_LOAD_SIZE = {0: 1, 1: 2, 2: 4, 3: 8, 4: 1, 5: 2, 6: 4}   # funct3 → 字节数（f3[2]=无符号位）

_BR_CMP = {
    0: lambda sa, sb, a, b: sa == sb, 1: lambda sa, sb, a, b: sa != sb,
    4: lambda sa, sb, a, b: sa < sb, 5: lambda sa, sb, a, b: sa >= sb,
    6: lambda sa, sb, a, b: a < b, 7: lambda sa, sb, a, b: a >= b,
}


def _mnemonic(kind: str, f3: int, funct7: int) -> str:
    table = {"i": _MNEM_I, "iw": _MNEM_IW, "r": _MNEM_R, "rw": _MNEM_RW, "m": _MNEM_M}[kind]
    base = table.get(f3, f"op{kind}{f3:x}")
    if kind in ("r", "rw") and funct7 == 0x20:
        base = {"add": "sub", "srl": "sra", "addw": "subw", "srlw": "sraw"}.get(base, base)
    if kind == "i" and funct7 == 0x10 and f3 == 5:
        base = "srai"
    if kind == "iw" and funct7 == 0x10 and f3 == 5:
        base = "sraiw"
    if kind == "mw":
        base = {0: "mulw", 4: "divw", 5: "divuw", 6: "remw", 7: "remuw"}.get(f3, base)
    return base
