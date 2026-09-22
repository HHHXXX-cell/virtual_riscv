"""命令行入口：跑一个镜像并输出 trace CSV。

用法（在 `iss/` 目录下）：
    python -m vriss run --bin prog.bin --base 0x40000000 --csv prog.csv --max 100000
    python -m vriss run --hex prog.hex   --csv prog.csv            # $readmemh，与 RTL 同一份镜像
    python -m vriss dump  --bin prog.bin --base 0x40000000 --hex-out prog.hex
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .consts import DRAM_BASE
from .machine import VrIss
from .mem import Bus
from .trace import TraceWriter


def _build_bus(args: argparse.Namespace) -> tuple[Bus, int]:
    bus = Bus(signature_addr=args.sig_addr)
    reset = args.reset_pc
    if args.hex:
        bus.load_readmemh(args.hex)
    elif args.bin:
        bus.load_bin(args.bin, base=args.base)
    else:
        raise SystemExit("必须给 --bin 或 --hex")
    if args.with_clint:
        from .mem import ClintLite
        bus.attach(0x0200_0000, 0x0001_0000, ClintLite())
    return bus, reset


def cmd_run(args: argparse.Namespace) -> int:
    bus, reset = _build_bus(args)
    iss = VrIss(bus=bus, reset_pc=reset, tohost_addr=args.tohost)
    with TraceWriter(args.csv, debug=args.debug) as tw:
        n, recs = iss.run(max_instr=args.max)
        for r in recs:
            tw.write(r)
    print(f"[vriss] retired={n} cycles={iss.cycle} halted={iss.halted} "
          f"halt_val={_hex(iss.halt_val)} trace={args.csv}")
    if not iss.halted:
        print("[vriss] 未看到 tohost 写，很可能在 watchdog 上限处被截断（红线 R9）", file=sys.stderr)
        return 2
    # riscv-tests 语义：**tohost == 1 才是 PASS**；(testnum<<1)|1 是对应编号的 FAIL。
    # 旧判据 `data >> 1 == 1` 会把“test 1 失败”当成整体成功（评审 ISS-019 Q12）。
    return 0 if iss.halt_val == 1 else 1


def _hex(v):
    return "None" if v is None else f"0x{v:x}"


def cmd_dump(args: argparse.Namespace) -> int:
    bus, _ = _build_bus(args)
    data = bus.dump_region(args.base, args.length)
    words = [int.from_bytes(data[i:i + 4], "little") for i in range(0, len(data), 4)]
    from .encode import Image
    Path(args.hex_out).write_text(Image(args.base, words).to_readmemh(), encoding="utf-8")
    print(f"[vriss] {args.base:#x}+{args.length}B -> {args.hex_out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vriss", description="VR1 golden ISS")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--bin", help="裸二进制镜像路径")
        sp.add_argument("--hex", help="$readmemh 镜像路径（与 RTL 共用同一份）")
        sp.add_argument("--base", type=lambda s: int(s, 0), default=DRAM_BASE)
        sp.add_argument("--reset-pc", dest="reset_pc", type=lambda s: int(s, 0), default=0x1000)
        sp.add_argument("--sig-addr", dest="sig_addr", type=lambda s: int(s, 0),
                        default=0x2000_0000)
        sp.add_argument("--with-clint", action="store_true")

    sp = sub.add_parser("run", help="执行并出 trace CSV")
    common(sp)
    sp.add_argument("--csv", default="vriss_trace.csv")
    sp.add_argument("--debug", action="store_true", help="附非比对列（cycle/seq/...）")
    sp.add_argument("--max", type=int, default=1_000_000, help="watchdog 指令数上限（R9）")
    sp.add_argument("--tohost", type=lambda s: int(s, 0), default=None,
                    help="写此地址即停机；riscv-tests 语义：**值==1 为 PASS**，"
                         "值==(testnum<<1)|1 为对应编号的 FAIL")
    sp.set_defaults(func=cmd_run)

    sp = sub.add_parser("dump", help="把 bin 转成 $readmemh（一份产物喂两边）")
    common(sp)
    sp.add_argument("--length", type=lambda s: int(s, 0), default=4096)
    sp.add_argument("--hex-out", dest="hex_out", required=True)
    sp.set_defaults(func=cmd_dump)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
