"""退休 trace 记录与 CSV 读写。

字段一一对应 `doc/spec/01` §3.21 的 `rt_t`（RTL 侧唯一真值接口），
CSV 列名与顺序对齐 riscv-dv（`scripts/riscv_trace_csv.py` 的
`["pc","instr","gpr","csr","binary","mode","instr_str","operand"]`），
以便复用其现成脚本。

不参与比对的成员（`doc/spec/01` §7 明确要求显式列出）：
  - `cycle`：周期数，仅性能统计
  - `mispred`：投机信息，ISS 无对应物
二者只进 debug 列（`DEBUG_CSV_FIELDS`），绝不混进标准列——混了会把
"两边都有但值不同"误判成 mismatch。
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field

TRACE_CSV_FIELDS = [
    "pc", "instr", "gpr", "csr", "binary", "mode", "instr_str", "operand",
]
DEBUG_CSV_FIELDS = TRACE_CSV_FIELDS + [
    "seq", "cycle", "mispred", "mem_addr", "mem_kind", "priv", "halted",
]
NON_COMPARED = ("cycle", "mispred", "seq")

# 整型 ABI 名（riscv-dv 的 gpr 字段用 abi 名而非 xN，见 spike_log_to_trace_csv.py）
ABI_NAMES = [
    "zero", "ra", "sp", "gp", "tp", "t0", "t1", "t2",
    "s0", "s1", "a0", "a1", "a2", "a3", "a4", "a5",
    "a6", "a7", "s2", "s3", "s4", "s5", "s6", "s7",
    "s8", "s9", "s10", "s11", "t3", "t4", "t5", "t6",
]


@dataclass(slots=True)
class RetireRecord:
    """一条退休指令的全部可观测信息（`rt_t` 的软件化身）。"""

    valid: int = 1
    pc: int = 0
    instr: int = 0
    is_c: int = 0
    rd_idx: int = 0
    rd_wb_en: int = 0
    rd_data: int = 0
    priv: int = 3
    csr_addr: int = 0
    csr_old: int = 0
    csr_new: int = 0
    csr_wr_en: int = 0
    exc_v: int = 0
    exc_cause: int = 0
    is_intr: int = 0
    mispred: int = 0
    is_br: int = 0
    mem_v: int = 0
    mem_addr: int = 0
    mem_wdata: int = 0
    mem_rdata: int = 0
    mem_size: int = 0
    mem_wr: int = 0
    seq: int = 0
    cycle: int = 0
    # 反汇编文本（比对的 instr_str/operand 列来源）
    instr_str: str = ""
    operand: str = ""
    mem_kind: str = ""
    halted: int = 0
    extra: dict = field(default_factory=dict)

    # ---- 标准 trace CSV（与 Spike/riscv-dv 可比） -------------------- #
    def gpr_field(self) -> str:
        if not self.rd_wb_en or self.rd_idx == 0:
            return ""
        return f"{ABI_NAMES[self.rd_idx]}:0x{self.rd_data:016x}"

    def csr_field(self) -> str:
        """与 Spike commit log 同口径：报**写入后的新值**（doc/00 ISS-013）。"""
        if not self.csr_wr_en:
            return ""
        return f"0x{self.csr_addr:03x}:0x{self.csr_new:016x}"

    def to_trace_row(self) -> dict[str, str]:
        return {
            "pc": f"{self.pc:08x}",
            "instr": self.instr_str,
            "gpr": self.gpr_field(),
            "csr": self.csr_field(),
            "binary": f"{self.instr:08x}",
            "mode": _mode_str(self.priv),
            "instr_str": self.instr_str,
            "operand": self.operand,
        }

    def to_debug_row(self) -> dict[str, str]:
        row = self.to_trace_row()
        row.update({
            "seq": str(self.seq),
            "cycle": str(self.cycle),
            "mispred": str(self.mispred),
            "mem_addr": f"{self.mem_addr:010x}",
            "mem_kind": self.mem_kind,
            "priv": _mode_str(self.priv),
            "halted": str(self.halted),
        })
        return row


def _mode_str(priv: int) -> str:
    return {0: "PRV_U", 1: "PRV_S", 3: "PRV_M"}.get(priv, f"PRV_?{priv}")


class TraceWriter:
    """写 trace CSV。`debug=True` 时附非比对列（文件名建议加 `.dbg`）。"""

    def __init__(self, path: str, debug: bool = False):
        self.fields = DEBUG_CSV_FIELDS if debug else TRACE_CSV_FIELDS
        self._fd = open(path, "w", newline="", encoding="utf-8")
        self.w = csv.DictWriter(self._fd, fieldnames=self.fields, extrasaction="ignore")
        self.w.writeheader()
        self.n = 0

    def write(self, rec: RetireRecord) -> None:
        self.w.writerow(rec.to_debug_row() if self.fields == DEBUG_CSV_FIELDS
                        else rec.to_trace_row())
        self.n += 1

    def close(self) -> None:
        self._fd.close()

    def __enter__(self) -> "TraceWriter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_trace_csv(path: str) -> list[dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def normalize_row(row: dict[str, str], compare_csr: bool = True) -> dict[str, str]:
    """把一行 trace 归一到"可判等"形式：十六进制列统一位宽与前缀。

    riscv-dv 自带的 `instr_trace_compare.py` 做的是**字符串全等**，因此两侧必须由同一套
    格式化规则产出；本函数给自研比对器用，容错更好（数值等价即等价）。
    """
    def _hex(v: str) -> str:
        v = (v or "").strip()
        if not v:
            return ""
        try:
            return f"0x{int(v, 16):016x}"
        except ValueError:
            return v.lower()

    out = dict(row)
    for key in ("pc", "binary"):
        if key in out:
            out[key] = _hex(out[key])
    for key in ("gpr", "csr"):
        if key in out and out[key]:
            parts = []
            for item in out[key].replace(";", ",").split(","):
                name, _, val = item.partition(":")
                parts.append(f"{name.strip().lower()}:{_hex(val)}")
            out[key] = ",".join(parts)
    if not compare_csr:
        out["csr"] = ""
    return out
