"""VR1 golden ISS —— 常量与编码定义（唯一权威源：doc/spec/10 与 RISC-V 规范）。

口径来源：
- 异常/中断编码：特权规范卷 II §3.1.15 Table 105/106（本地 `_tools\\extracted\\riscv_spec\\riscv_spec_full.txt`）
- signature 握手：`_tools\\riscv-dv-master\\src\\riscv_signature_pkg.sv`（逐值照抄语义，未自创）
- CSR 地址：特权规范卷 II §2.2 Table 96 之 M/S 子集
- 非对齐一律报 fault：`doc/spec/00` §2 与 `MISALIGNED_EN=0`（doc/process/00 ISS-010）
"""
from __future__ import annotations

from enum import IntEnum, IntFlag

XLEN = 64
VA_BITS = 40          # doc/spec/00 §4.1：内部 VA/PC 存 40 bit（Sv39 的 39 位 + 规范检测位）
PA_BITS = 44
MASK64 = (1 << 64) - 1
MASK32 = (1 << 32) - 1


def sext(val: int, bits: int) -> int:
    """按 bits 位符号扩展到 Python 无限精度（可为负）。"""
    val &= (1 << bits) - 1
    return val - (1 << bits) if val >> (bits - 1) else val


def u64(val: int) -> int:
    return val & MASK64


def sext32(val: int) -> int:
    """W 型指令结果：按 bit31 符号扩展至 64 位（doc/spec/01 §3.4 的 is_w/sext 语义）。"""
    return sext(val, 32)


# --------------------------------------------------------------------------- #
# 特权模式（特权规范 §1.2 编码表）
# --------------------------------------------------------------------------- #
class Priv(IntEnum):
    USER = 0
    SUPERVISOR = 1
    MACHINE = 3


USER_MODE, SUP_MODE, MK_MODE = Priv.USER, Priv.SUPERVISOR, Priv.MACHINE


# --------------------------------------------------------------------------- #
# 异常与中断原因码（mcause：bit63=Interrupt，[62:0]=Exception Code）
# --------------------------------------------------------------------------- #
class Exc(IntEnum):
    """同步异常码。多条并发时的优先序见 doc/spec/02 §7（不允许"或"起来当一个）。"""
    INSTR_ADDR_MISALIGNED = 0
    INSTR_ACCESS_FAULT = 1
    ILLEGAL_INSTR = 2
    BREAKPOINT = 3
    LOAD_ADDR_MISALIGNED = 4
    LOAD_ACCESS_FAULT = 5
    STORE_ADDR_MISALIGNED = 6
    STORE_ACCESS_FAULT = 7
    ECALL_U = 8
    ECALL_S = 9
    ECALL_M = 11
    INSTR_PAGE_FAULT = 12
    LOAD_PAGE_FAULT = 13
    STORE_PAGE_FAULT = 15


class Intr(IntEnum):
    """中断码（mcause 高位为 1）。进 M 模式的固定优先序见 doc/spec/00 §4.7。"""
    SSI = 1
    STI = 5
    SEI = 9
    MSI = 3
    MTI = 7
    MEI = 11
    LCOFI = 13


# 进 M 模式时的仲裁顺序（特权规范 §3.1.9），优先级从高到低
M_INTR_PRIORITY: tuple[Intr, ...] = (
    Intr.MEI, Intr.MSI, Intr.MTI, Intr.SEI, Intr.SSI, Intr.STI, Intr.LCOFI,
)

INTR_BIT = 1 << 63


# --------------------------------------------------------------------------- #
# CSR 地址（一期实现的子集；全表与复位值/WARL 位在 doc/spec/10）
# --------------------------------------------------------------------------- #
class Csr(IntEnum):
    # M 模式读写
    MSTATUS = 0x300
    MISA = 0x301
    MEDELEG = 0x302
    MIDELEG = 0x303
    MIE = 0x304
    MTVEC = 0x305
    MCOUNTEREN = 0x306
    MSTATUSH = 0x310
    MENVCFG = 0x30A
    MSCRATCH = 0x340
    MEPC = 0x341
    MCAUSE = 0x342
    MTVAL = 0x343
    MIP = 0x344
    MCOUNTINHIBIT = 0x320
    # S 模式读写
    SSTATUS = 0x100
    SIE = 0x104
    STVEC = 0x105
    SCOUNTEREN = 0x106
    SSCRATCH = 0x140
    SEPC = 0x141
    SCAUSE = 0x142
    STVAL = 0x143
    SIP = 0x144
    SATP = 0x180
    # 只读
    VENDORID = 0xF11
    MARCHID = 0xF12
    MIMPID = 0xF13
    MHARTID = 0xF14
    MCYCLE = 0xB00
    MINSTRET = 0xB02
    TIME = 0xC01


# mstatus 位段（特权规范 §3.1.6；一期只用这些，位段与 doc/spec/10 同步）
class MStatus(IntFlag):
    SIE = 1 << 1
    MIE = 1 << 3
    SPIE = 1 << 5
    UBE = 1 << 6
    MPIE = 1 << 7
    SPP = 1 << 8
    VS = 0b11 << 9           # 一期恒 0（非目标：向量上下文）
    MPP = 0b11 << 11
    FS = 0b11 << 13          # 一期读回恒 0（doc/spec/00 §7 第 5 条）
    XS = 0b11 << 15
    MPRV = 1 << 17
    SUM = 1 << 18
    MXR = 1 << 19
    TVM = 1 << 20
    TW = 1 << 21
    TSR = 1 << 22
    SD = 1 << 63


# 一期允许写的 mstatus 位（其余位 WARL 忽略；不在此集里的写入一律丢弃）
MSTATUS_WMASK = int(MStatus.SIE | MStatus.MIE | MStatus.SPIE | MStatus.MPIE
                    | MStatus.SPP | MStatus.MPP | MStatus.MPRV | MStatus.SUM
                    | MStatus.MXR | MStatus.TVM | MStatus.TW | MStatus.TSR)

# sstatus 是 mstatus 的受限视图（§4.1.1）：只暴露 S 侧相关位
MSTATUS_WMASK_S = int(MStatus.SIE | MStatus.SPIE | MStatus.SPP | MStatus.SUM
                      | MStatus.MXR | MStatus.FS)

FS_SHIFT, FS_WIDTH = 13, 2
MPP_SHIFT, SPP_SHIFT = 11, 8

# mtvec.MODE
MTVEC_DIRECT, MTVEC_VECTORED = 0, 1

# satp.MODE（RV64）：0=Bare，8=Sv39（doc/spec/08）
SATP_MODE_BARE, SATP_MODE_SV39 = 0, 8

# misa：MXL=2（RV64）+ 扩展位 I(8) M(12) A(0) C(2)
MISA_RV64_IMAC = (2 << 62) | (1 << 8) | (1 << 12) | (1 << 0) | (1 << 2)


# --------------------------------------------------------------------------- #
# riscv-dv signature 握手（逐值对齐 riscv_signature_pkg.sv）
# --------------------------------------------------------------------------- #
SIGNATURE_ADDR_DEFAULT = 0x2000_0000     # 建议放随机 data page 之外；riscv-dv 文档给 0x8ffffffc
                                        # ——此处 VR1 的 PMA 把该窗设为 non-cacheable，见 doc/spec/09


class SigType(IntEnum):
    CORE_STATUS = 0
    TEST_RESULT = 1
    WRITE_GPR = 2
    WRITE_CSR = 3


class SigStatus(IntEnum):
    INITIALIZED = 0
    IN_DEBUG_MODE = 1
    IN_MACHINE_MODE = 2
    IN_HYPERVISOR_MODE = 3
    IN_SUPERVISOR_MODE = 4
    IN_USER_MODE = 5
    HANDLING_IRQ = 6
    FINISHED_IRQ = 7
    HANDLING_EXCEPTION = 8
    INSTR_FAULT_EXCEPTION = 9
    ILLEGAL_INSTR_EXCEPTION = 10
    LOAD_FAULT_EXCEPTION = 11
    STORE_FAULT_EXCEPTION = 12
    EBREAK_EXCEPTION = 13


class SigResult(IntEnum):
    TEST_PASS = 0
    TEST_FAIL = 1


SIG_TYPE_MASK = 0xFF
SIG_STATUS_SHIFT = 8                  # data[12:8] = core_status_t
SIG_CSR_ADDR_SHIFT = 8                # data[19:8] = CSR 地址
SIG_CSR_ADDR_MASK = 0xFFF


def sig_word(sig_type: SigType, payload: int = 0) -> int:
    """打包一个握手字：低 8 位为类型，其上按类型语义放 payload。"""
    return u64((int(payload) << 8) | int(sig_type))


# --------------------------------------------------------------------------- #
# 复位与内存图（doc/spec/00 §4.1、doc/spec/09 §PMA）
# --------------------------------------------------------------------------- #
RESET_PC = 0x1000                     # = 参数 RESET_PC；与 sw/env/link.ld 必须一致
CLK_BASE = 0x2000_0000                # signature 窗口（non-cacheable）
CLINT_BASE = 0x0200_0000
PLIC_BASE = 0x0C00_0000
DRAM_BASE = 0x4000_0000               # 一期默认代码/数据窗口

# PMA 属性位（doc/spec/01 §3.14 的 pma[3:0]）
class Pma(IntFlag):
    CACHEABLE = 1
    STRONG_ORDER = 2
    NO_PREFETCH = 4
    DEVICE = 8


PMA_TABLE: tuple[tuple[int, int, Pma], ...] = (
    (0x0000_0000, 0x0000_2000, Pma.STRONG_ORDER | Pma.DEVICE | Pma.NO_PREFETCH),   # reset/ROM 区
    (CLINT_BASE, 0x10000, Pma.STRONG_ORDER | Pma.DEVICE | Pma.NO_PREFETCH),
    (PLIC_BASE, 0x0400_0000, Pma.STRONG_ORDER | Pma.DEVICE | Pma.NO_PREFETCH),
    (CLK_BASE, 0x0010_0000, Pma.STRONG_ORDER | Pma.NO_PREFETCH),                    # signature
    (DRAM_BASE, 0x0800_0000, Pma.CACHEABLE),
)
