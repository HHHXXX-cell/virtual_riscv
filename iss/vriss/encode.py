"""指令位级编码与镜像输出（"最小汇编器"）。

为什么存在：本机没有 RISC-V 工具链（doc/00 ISS-002），而 `doc/spec/02` 的逐指令行为表
需要**立刻**能被定向程序验证。本模块用纯标准库给出：
  1) 六种指令格式的位域编码（严格按非特权卷 I §2.2/§2.3~2.8）；
  2) 常用指令的具名构造器；
  3) 同一份镜像同时产出 `.bin`（RTL 存储器加载）与 `$readmemh` `.hex`（ModelSim）
     ——这是 AGENTS.md §3.4 坑 2「一份产物喂两边」的落地。

未覆盖：RV64C 压缩指令编码（TODO 见 iss/README.md §5，等 doc/spec/02 §5 展开表冻结后补）。
"""
from __future__ import annotations

from dataclasses import dataclass

from .consts import u64

# 操作码（卷 I §2.2 Table 6.1 之子集）
OP_LUI, OP_AUIPC, OP_JAL, OP_JALR = 0x37, 0x17, 0x6F, 0x67
OP_BR, OP_LOAD, OP_STORE, OP_OP_IMM = 0x63, 0x03, 0x23, 0x13
OP_OP = 0x33
OP_MISC_MEM, OP_AMO, OP_OP_IMM32, OP_OP32 = 0x0F, 0x2F, 0x1B, 0x3B
OP_SYSTEM = 0x73

_HOLE = 0xFFFF_FFFF    # link() 空洞填充：保证是非法指令，而不是低 2 位=00 的“未实现压缩”


def _bits(val: int, lo: int, width: int) -> int:
    """取 val 的 [lo, lo+width) 位放到位置 0。"""
    return (val >> lo) & ((1 << width) - 1)


def _chk(val: int, bits: int, name: str) -> int:
    """立即数范围检查。

    为什么必须有：本模块早期版本对超范围立即数做 `& mask` 静默截断，
    结果 `ADDI(rd, rs1, 0x1000)` 编成了 +0（12 位字段只存得下 0），
    定向测试里表现为“程序不停机”这类难查的假故障。宁可报错，不可静默截断。
    """
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if not lo <= val <= hi:
        raise ValueError(f"{name} 立即数 {val:#x} 超出 {bits} 位有符号范围 [{lo:#x},{hi:#x}]")
    return val


# --------------------------------------------------------------------------- #
# 六种基本格式
# --------------------------------------------------------------------------- #
def enc_r(funct7: int, rs2: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    return (funct7 << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def enc_i(imm: int, rs1: int, funct3: int, rd: int, opcode: int) -> int:
    """I 型：imm[11:0] 放 [31:20]。CSR*I 时 imm 的低 5 位即 uimm（放 [19:15]）。"""
    if opcode != OP_SYSTEM:
        _chk(imm, 12, "I型")
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def enc_s(imm: int, rs2: int, rs1: int, funct3: int, opcode: int) -> int:
    """S 型：imm[11:5]→[31:25]，imm[4:0]→[11:7]。"""
    _chk(imm, 12, "S型")
    return ((_bits(imm, 5, 7) << 25) | (rs2 << 20) | (rs1 << 15)
            | (funct3 << 12) | (_bits(imm, 0, 5) << 7) | opcode)


def enc_b(imm: int, rs2: int, rs1: int, funct3: int, opcode: int) -> int:
    """B 型：imm[12]→31，imm[10:5]→30:25，imm[4:1]→11:8，imm[11]→7（恒偶数）。"""
    _chk(imm, 13, "B型")
    if imm & 1:
        raise ValueError(f"B 型分支偏移必须偶数，得到 {imm:#x}")
    return ((_bits(imm, 12, 1) << 31) | (_bits(imm, 5, 6) << 25) | (rs2 << 20)
            | (rs1 << 15) | (funct3 << 12) | (_bits(imm, 1, 4) << 8)
            | (_bits(imm, 11, 1) << 7) | opcode)


def enc_u(imm20: int, rd: int, opcode: int) -> int:
    """U 型：imm[31:12] → [31:12]。**参数给 20 位高位立即数**（与 LUI/AUIPC 习惯一致）。"""
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | opcode


def enc_j(imm: int, rd: int, opcode: int) -> int:
    """J 型：imm[20]→31，imm[10:1]→30:21，imm[11]→20，imm[19:12]→19:12。"""
    _chk(imm, 21, "J型")
    if imm & 1:
        raise ValueError(f"JAL 偏移必须偶数，得到 {imm:#x}")
    return ((_bits(imm, 20, 1) << 31) | (_bits(imm, 1, 10) << 21)
            | (_bits(imm, 11, 1) << 20) | (_bits(imm, 12, 8) << 12)
            | (rd << 7) | opcode)


# --------------------------------------------------------------------------- #
# 具名构造器（覆盖定向测试常用面；完整表由 doc/spec/02 驱动扩展）
# --------------------------------------------------------------------------- #
def LUI(rd, imm20):          return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | OP_LUI
def AUIPC(rd, imm20):        return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | OP_AUIPC
def JAL(rd, off):            return enc_j(off, rd, OP_JAL)
def JALR(rd, rs1, off):      return enc_i(off, rs1, 0, rd, OP_JALR)
def BEQ(rs1, rs2, off):      return enc_b(off, rs2, rs1, 0, OP_BR)
def BNE(rs1, rs2, off):      return enc_b(off, rs2, rs1, 1, OP_BR)
def BLT(rs1, rs2, off):      return enc_b(off, rs2, rs1, 4, OP_BR)
def BGE(rs1, rs2, off):      return enc_b(off, rs2, rs1, 5, OP_BR)
def BLTU(rs1, rs2, off):     return enc_b(off, rs2, rs1, 6, OP_BR)
def BGEU(rs1, rs2, off):     return enc_b(off, rs2, rs1, 7, OP_BR)
def LB(rd, rs1, off):        return enc_i(off, rs1, 0, rd, OP_LOAD)
def LH(rd, rs1, off):        return enc_i(off, rs1, 1, rd, OP_LOAD)
def LW(rd, rs1, off):        return enc_i(off, rs1, 2, rd, OP_LOAD)
def LD(rd, rs1, off):        return enc_i(off, rs1, 3, rd, OP_LOAD)
def LBU(rd, rs1, off):       return enc_i(off, rs1, 4, rd, OP_LOAD)
def LHU(rd, rs1, off):       return enc_i(off, rs1, 5, rd, OP_LOAD)
def LWU(rd, rs1, off):       return enc_i(off, rs1, 6, rd, OP_LOAD)
def SB(rs2, rs1, off):       return enc_s(off, rs2, rs1, 0, OP_STORE)
def SH(rs2, rs1, off):       return enc_s(off, rs2, rs1, 1, OP_STORE)
def SW(rs2, rs1, off):       return enc_s(off, rs2, rs1, 2, OP_STORE)
def SD(rs2, rs1, off):       return enc_s(off, rs2, rs1, 3, OP_STORE)
def ADDI(rd, rs1, imm):      return enc_i(imm, rs1, 0, rd, OP_OP_IMM)
def SLTI(rd, rs1, imm):      return enc_i(imm, rs1, 2, rd, OP_OP_IMM)
def SLTIU(rd, rs1, imm):     return enc_i(imm, rs1, 3, rd, OP_OP_IMM)
def XORI(rd, rs1, imm):      return enc_i(imm, rs1, 4, rd, OP_OP_IMM)
def ORI(rd, rs1, imm):       return enc_i(imm, rs1, 6, rd, OP_OP_IMM)
def ANDI(rd, rs1, imm):      return enc_i(imm, rs1, 7, rd, OP_OP_IMM)
# 注：右移类型位在 **instr[30]** ⇒ funct7（instr[31:25]）= 0b0100000 = **0x20**，
# 而 hi6（instr[31:26]）= 0x10。两者不要混淆（上一版把编码器改成 0x10 反而编错了）。
def SLLI(rd, rs1, sh):       return enc_r(0x00, sh & 0x3F, rs1, 1, rd, OP_OP_IMM)
def SRLI(rd, rs1, sh):       return enc_r(0x00, sh & 0x3F, rs1, 5, rd, OP_OP_IMM)
def SRAI(rd, rs1, sh):       return enc_r(0x20, sh & 0x3F, rs1, 5, rd, OP_OP_IMM)
def ADDIW(rd, rs1, imm):     return enc_i(imm, rs1, 0, rd, OP_OP_IMM32)
def SLLIW(rd, rs1, sh):      return enc_r(0x00, sh & 0x1F, rs1, 1, rd, OP_OP_IMM32)
def SRLIW(rd, rs1, sh):      return enc_r(0x00, sh & 0x1F, rs1, 5, rd, OP_OP_IMM32)
def SRAIW(rd, rs1, sh):      return enc_r(0x20, sh & 0x1F, rs1, 5, rd, OP_OP_IMM32)
def ADD(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 0, rd, OP_OP)
def SUB(rd, rs1, rs2):       return enc_r(0x20, rs2, rs1, 0, rd, OP_OP)
def SLL(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 1, rd, OP_OP)
def SLT(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 2, rd, OP_OP)
def SLTU(rd, rs1, rs2):      return enc_r(0x00, rs2, rs1, 3, rd, OP_OP)
def XOR(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 4, rd, OP_OP)
def SRL(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 5, rd, OP_OP)
def SRA(rd, rs1, rs2):       return enc_r(0x20, rs2, rs1, 5, rd, OP_OP)
def OR(rd, rs1, rs2):        return enc_r(0x00, rs2, rs1, 6, rd, OP_OP)
def AND(rd, rs1, rs2):       return enc_r(0x00, rs2, rs1, 7, rd, OP_OP)
def ADDW(rd, rs1, rs2):      return enc_r(0x00, rs2, rs1, 0, rd, OP_OP32)
def SUBW(rd, rs1, rs2):      return enc_r(0x20, rs2, rs1, 0, rd, OP_OP32)
def SLLW(rd, rs1, rs2):      return enc_r(0x00, rs2, rs1, 1, rd, OP_OP32)
def SRLW(rd, rs1, rs2):      return enc_r(0x00, rs2, rs1, 5, rd, OP_OP32)
def SRAW(rd, rs1, rs2):      return enc_r(0x20, rs2, rs1, 5, rd, OP_OP32)
def MUL(rd, rs1, rs2):       return enc_r(0x01, rs2, rs1, 0, rd, OP_OP)
def MULH(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 1, rd, OP_OP)
def MULHSU(rd, rs1, rs2):    return enc_r(0x01, rs2, rs1, 2, rd, OP_OP)
def MULHU(rd, rs1, rs2):     return enc_r(0x01, rs2, rs1, 3, rd, OP_OP)
def DIV(rd, rs1, rs2):       return enc_r(0x01, rs2, rs1, 4, rd, OP_OP)
def DIVU(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 5, rd, OP_OP)
def REM(rd, rs1, rs2):       return enc_r(0x01, rs2, rs1, 6, rd, OP_OP)
def REMU(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 7, rd, OP_OP)
def MULW(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 0, rd, OP_OP32)
def DIVW(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 4, rd, OP_OP32)
def DIVUW(rd, rs1, rs2):     return enc_r(0x01, rs2, rs1, 5, rd, OP_OP32)
def REMW(rd, rs1, rs2):      return enc_r(0x01, rs2, rs1, 6, rd, OP_OP32)
def REMUW(rd, rs1, rs2):     return enc_r(0x01, rs2, rs1, 7, rd, OP_OP32)
def FENCE():                 return enc_i(0, 0, 0, 0, OP_MISC_MEM)
def FENCE_I():               return enc_i(0, 0, 1, 0, OP_MISC_MEM)   # 0x0000100F
def ECALL():                 return enc_r(0, 0, 0, 0, 0, OP_SYSTEM)  # 0x00000073
def EBREAK():                return enc_r(0, 1, 0, 0, 0, OP_SYSTEM)  # 0x00100073
# 以下三条编码曾与官方 encoding.h 不一致（评审 ISS-019 Q27）：MRET 的 rs2 域=2、
# SRET/WFI 在 funct7=0x08。旧值 0x30000073 会被解码成“非法”，而官方 MRET 0x30200073
# 会被旧解码器误认成 SRET —— 用任何工具链编的测试程序都跑不通，而自造编码能跑。
def MRET():                  return enc_r(0x18, 2, 0, 0, 0, OP_SYSTEM)  # 0x30200073
def SRET():                  return enc_r(0x08, 2, 0, 0, 0, OP_SYSTEM)  # 0x10200073
def WFI():                   return enc_r(0x08, 5, 0, 0, 0, OP_SYSTEM)  # 0x10500073
def CSRRW(rd, csr, rs1):     return enc_i(csr, rs1, 1, rd, OP_SYSTEM)
def CSRRS(rd, csr, rs1):     return enc_i(csr, rs1, 2, rd, OP_SYSTEM)
def CSRRC(rd, csr, rs1):     return enc_i(csr, rs1, 3, rd, OP_SYSTEM)
def CSRRWI(rd, csr, uimm):   return enc_i(csr, uimm, 5, rd, OP_SYSTEM)
def CSRRSI(rd, csr, uimm):   return enc_i(csr, uimm, 6, rd, OP_SYSTEM)
def CSRRCI(rd, csr, uimm):   return enc_i(csr, uimm, 7, rd, OP_SYSTEM)
def SFENCE_VMA(rs1, rs2):    return enc_r(0x09, rs2, rs1, 0, 0, OP_SYSTEM)
def AMO(funct3, rd, rs2, rs1, funct5): return enc_r(funct5 << 2, rs2, rs1, funct3, rd, OP_AMO)


# --------------------------------------------------------------------------- #
# 程序镜像
# --------------------------------------------------------------------------- #
@dataclass
class Image:
    """一段从 `start` 地址开始的连续 32bit 指令/数据镜像。"""
    start: int
    words: list[int]

    @property
    def end(self) -> int:
        return self.start + 4 * len(self.words)

    def to_bytes(self) -> bytes:
        return b"".join(int(w & 0xFFFFFFFF).to_bytes(4, "little") for w in self.words)

    def to_readmemh(self, line_bytes: int = 16) -> str:
        """$readmemh 文本：@<字地址> 开头，每行 `line_bytes` 字节。"""
        per_line = max(1, line_bytes // 4)
        out = [f"@{(self.start // 4):08x}"]
        buf: list[str] = []
        for w in self.words:
            buf.append(f"{int(w & 0xFFFFFFFF):08x}")
            if len(buf) == per_line:
                out.append(" ".join(buf))
                buf = []
        if buf:
            out.append(" ".join(buf))
        return "\n".join(out) + "\n"

    def patch(self, index: int, word: int) -> None:
        self.words[index] = u64(word) & 0xFFFFFFFF


def link(parts: list[tuple[int, list[int]]]) -> Image:
    """把多个 (addr, words) 段拼成一个从最低地址起、空洞填 0 的镜像。"""
    if not parts:
        raise ValueError("空镜像")
    lo = min(a for a, _ in parts)
    hi = max(a + 4 * len(w) for a, w in parts)
    # 空洞填 0xFFFFFFFF（非法指令字）而不是 0：0 的低 2 位=00 会被当成压缩指令，
    # 导致“镜像有洞”以 NotImplementedError 而不是非法指令异常的方式暴露（评审 Q6）。
    words = [_HOLE] * ((hi - lo) // 4)
    for addr, ws in parts:
        base = (addr - lo) // 4
        for i, w in enumerate(ws):
            words[base + i] = int(w) & 0xFFFFFFFF
    return Image(lo, words)
