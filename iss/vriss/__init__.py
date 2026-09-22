"""VR1 golden ISS（`vriss`）——RV64IMAC 退休级机器模型。

规格权威源：`doc/spec/00`（参数）、`doc/spec/02`（逐指令行为）、`doc/spec/10`（CSR/trap）。
本包是那三份规格的**可执行化身**：任何行为分歧都必须先判"是 ISS 错还是 spec 错"，
再按红线 R6 处理，禁止改检查器让结果变绿。
"""
from .consts import (
    Csr,
    Exc,
    Intr,
    MStatus,
    Priv,
    RESET_PC,
    SigResult,
    SigStatus,
    SigType,
    sig_word,
)
from .encode import Image, link
from .machine import TrapExit, VrIss
from .mem import Bus, ClintLite, Fault
from .trace import (
    DEBUG_CSV_FIELDS,
    NON_COMPARED,
    TRACE_CSV_FIELDS,
    RetireRecord,
    TraceWriter,
    normalize_row,
    read_trace_csv,
)

__all__ = [
    "Bus", "Csr", "DEBUG_CSV_FIELDS", "Exc", "Fault", "Image", "Intr",
    "MStatus", "NON_COMPARED", "Priv", "RESET_PC", "RetireRecord", "SigResult",
    "SigStatus", "SigType", "TRACE_CSV_FIELDS", "TrapExit", "VrIss", "ClintLite",
    "TraceWriter", "link", "normalize_row", "read_trace_csv", "sig_word",
]

__version__ = "0.1.0"
