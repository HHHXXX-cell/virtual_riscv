"""存储器/总线模型：稀疏页 + PMA 区域表 + MMIO 设备 + signature 握手截获。

对应规格：`doc/spec/00` §4.6/§4.7（PMA 与总线）、`doc/spec/09`（缓存与总线，待成稿）。
非对齐**不建模成硬件拆包**——一期 `MISALIGNED_EN=0`，直接抛 `Fault`（doc/process/00 ISS-010）。
"""
from __future__ import annotations

from collections.abc import Callable

from .consts import (
    CLK_BASE,
    DRAM_BASE,
    Pma,
    PMA_TABLE,
    SIGNATURE_ADDR_DEFAULT,
    Exc,
    u64,
)

PAGE = 4096


class Fault(Exception):
    """访存/指令异常。cause 用 `Exc`，tval 语义按特权规范 §3.1.16。"""

    def __init__(self, cause: Exc, tval: int = 0):
        super().__init__(f"{cause.name} @0x{tval:x}")
        self.cause = cause
        self.tval = tval


def pma_of(addr: int) -> Pma:
    """返回区域属性；未声明区域返回 Pma(0)，由读/写入口按 fetch/方向分别报 fault。"""
    for base, size, attr in PMA_TABLE:
        if base <= addr < base + size:
            return attr
    return Pma(0)


def _mask_width(size: int) -> int:
    return (1 << (size * 8)) - 1


class Bus:
    """字节寻址、小端、稀疏 4 KiB 页。设备经 `attach()` 注册后优先于 RAM。"""

    def __init__(self, signature_addr: int = SIGNATURE_ADDR_DEFAULT):
        self.pages: dict[int, bytearray] = {}
        self.devices: list[tuple[int, int, "Device"]] = []
        self.signature_addr = signature_addr
        self.signature_writes: list[int] = []      # 供 ISS 侧核对握手
        self.mem_writes: list[tuple[int, int, int]] = []   # (addr, size, data) 供 trace/调试

    # ---- 基本读写 ------------------------------------------------------- #
    def _page(self, addr: int, alloc: bool) -> bytearray | None:
        idx = addr & ~0xFFF
        pg = self.pages.get(idx)
        if pg is None and alloc:
            pg = bytearray(PAGE)
            self.pages[idx] = pg
        return pg

    def _dev(self, addr: int):
        for base, size, dev in self.devices:
            if base <= addr < base + size:
                return dev, addr - base
        return None, 0

    def read(self, addr: int, size: int, signed: bool, *, fetch: bool = False) -> int:
        addr = u64(addr)
        if addr % size:
            raise Fault(Exc.INSTR_ADDR_MISALIGNED if fetch else Exc.LOAD_ADDR_MISALIGNED, addr)
        attr = pma_of(addr)
        dev, off = self._dev(addr)
        if fetch:
            bad = Exc.INSTR_ACCESS_FAULT
        else:
            bad = Exc.LOAD_ACCESS_FAULT
        if dev is not None:
            if attr & Pma.DEVICE and size > 8:
                raise Fault(bad, addr)
            return u64(dev.read(off, size))
        if not (attr & (Pma.CACHEABLE | Pma.DEVICE)):
            raise Fault(bad, addr)
        val = 0
        for i in range(size):
            pg = self._page(addr + i, alloc=False)
            if pg is None:
                raise Fault(bad, addr)
            val |= pg[(addr + i) & 0xFFF] << (8 * i)
        return sext_val(val, size, signed)

    def write(self, addr: int, size: int, data: int) -> None:
        addr = u64(addr)
        if addr % size:
            raise Fault(Exc.STORE_ADDR_MISALIGNED, addr)
        attr = pma_of(addr)
        if addr == self.signature_addr and size == 8:
            # signature 握手：程序向 signature_addr 写 64bit，类型/载荷见 consts.SigType
            self.signature_writes.append(u64(data))
            self.mem_writes.append((addr, size, u64(data)))
            return
        dev, off = self._dev(addr)
        if dev is not None:
            dev.write(off, size, u64(data))
            return
        if not attr & Pma.CACHEABLE and not attr & Pma.DEVICE:
            raise Fault(Exc.STORE_ACCESS_FAULT, addr)
        data = u64(data)
        for i in range(size):
            pg = self._page(addr + i, alloc=True)
            assert pg is not None
            pg[(addr + i) & 0xFFF] = (data >> (8 * i)) & 0xFF
        self.mem_writes.append((addr, size, data))

    # ---- 设备与镜像 ----------------------------------------------------- #
    def attach(self, base: int, size: int, dev: "Device") -> None:
        self.devices.append((base, size, dev))

    def load_image(self, start: int, data: bytes) -> None:
        for i, b in enumerate(data):
            pg = self._page(start + i, alloc=True)
            assert pg is not None
            pg[(start + i) & 0xFFF] = b

    def load_bin(self, path: str, base: int = DRAM_BASE) -> None:
        with open(path, "rb") as f:
            self.load_image(base, f.read())

    def load_readmemh(self, path: str) -> None:
        """$readmemh：`@<字地址>` 切段，其余按行给 32bit 字（与 RTL 侧同一份文件）。"""
        addr = None
        buf = bytearray()
        with open(path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.split("//")[0].strip()
                if not line:
                    continue
                if line.startswith("@"):
                    if buf and addr is not None:
                        self.load_image(addr, bytes(buf))
                    buf = bytearray()
                    addr = int(line[1:], 16) * 4
                    continue
                for tok in line.split():
                    buf += int(tok, 16).to_bytes(4, "little")
        if buf and addr is not None:
            self.load_image(addr, bytes(buf))

    def dump_region(self, start: int, size: int) -> bytes:
        out = bytearray()
        for i in range(size):
            pg = self._page(start + i, alloc=False)
            out.append(pg[(start + i) & 0xFFF] if pg else 0)
        return bytes(out)


def sext_val(val: int, size: int, signed: bool) -> int:
    if not signed:
        return val & _mask_width(size)
    return val - (1 << (size * 8)) if (val >> (size * 8 - 1)) & 1 else val & _mask_width(size)


class Device:
    """MMIO 设备基类：偏移读写，宽度以字节计。"""

    base: int = 0

    def read(self, off: int, size: int) -> int:
        raise NotImplementedError

    def write(self, off: int, size: int, data: int) -> None:
        raise NotImplementedError


class SigSink(Device):
    """把 signature 窗口做成设备（RTL 侧对应 non-cacheable 区）；Bus 已内建截获，本类供 SoC 级测试复用。"""

    def __init__(self) -> None:
        self.received: list[int] = []

    def read(self, off: int, size: int) -> int:
        return 0

    def write(self, off: int, size: int, data: int) -> None:
        self.received.append(data)


class ClintLite(Device):
    """CLINT-lite：mtime / mtimecmp / msip（doc/spec/00 §4.7）。

    偏移表（与 sw/env 与 doc/spec/10 保持一致）：
      0x0000 msip        0x4000 mtimecmp     0xBFF8 mtime
    """

    base = CLK_BASE

    def __init__(self) -> None:
        self.msip = 0
        self.mtimecmp = (1 << 64) - 1
        self.mtime = 0

    def tick(self, n: int = 1) -> None:
        self.mtime = u64(self.mtime + n)

    def read(self, off: int, size: int) -> int:
        if off < 0x4000:
            return self.msip
        if off < 0xBFF8:
            return self._slice(self.mtimecmp, off - 0x4000, size)
        return self._slice(self.mtime, off - 0xBFF8, size)

    @staticmethod
    def _slice(val: int, off: int, size: int) -> int:
        return (val >> (8 * (off % 8))) & _mask_width(size)

    def write(self, off: int, size: int, data: int) -> None:
        if off < 0x4000:
            self.msip = data & 1
        elif off < 0xBFF8:
            self.mtimecmp = self._poke(self.mtimecmp, off - 0x4000, size, data)
        else:
            self.mtime = self._poke(self.mtime, off - 0xBFF8, size, data)

    @staticmethod
    def _poke(val: int, off: int, size: int, data: int) -> int:
        shift = 8 * (off % 8)
        mask = _mask_width(size) << shift
        return u64((val & ~mask) | ((data & _mask_width(size)) << shift))
