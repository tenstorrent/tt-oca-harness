# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RV32 instruction model for the M, Zba, Zbb and Zbc extensions.

Each function returns the 32-bit ``rd`` value of one instruction for 32-bit
operands, as the ratified RISC-V Unprivileged ISA states it (M extension:
"M" Extension for Integer Multiplication and Division, including the
division-by-zero and overflow table; Zba, Zbb, Zbc: the Bit-Manipulation
specification, version 1.0.0). The model is written from that text only; a
leaf builds its expected-result table with it and never from a DUT read.

``OPS`` maps the mnemonic to ``(function, kind)``. ``kind`` is ``"rr"`` for
two register operands, ``"r"`` for one, and ``"ri"`` for a register and a
5-bit shift amount (``rori``).

Self-test: ``python3 sep_rv_isa_golden.py`` checks hand vectors taken from the
specification text (registered in ``run_golden_selftests.py``).
"""

from __future__ import annotations

from typing import Callable

XLEN = 32
_M = (1 << XLEN) - 1


def _u(x: int) -> int:
    return x & _M


def _s(x: int) -> int:
    x &= _M
    return x - (1 << XLEN) if x >> (XLEN - 1) else x


# M extension
def mul(a: int, b: int) -> int:
    return _u(_s(a) * _s(b))


def mulh(a: int, b: int) -> int:
    return _u((_s(a) * _s(b)) >> XLEN)


def mulhsu(a: int, b: int) -> int:
    return _u((_s(a) * _u(b)) >> XLEN)


def mulhu(a: int, b: int) -> int:
    return _u((_u(a) * _u(b)) >> XLEN)


def div(a: int, b: int) -> int:
    sa, sb = _s(a), _s(b)
    if sb == 0:
        return _M
    if sa == -(1 << (XLEN - 1)) and sb == -1:
        return _u(sa)
    q = abs(sa) // abs(sb)
    return _u(-q if (sa < 0) != (sb < 0) else q)


def divu(a: int, b: int) -> int:
    return _M if _u(b) == 0 else _u(a) // _u(b)


def rem(a: int, b: int) -> int:
    sa, sb = _s(a), _s(b)
    if sb == 0:
        return _u(sa)
    if sa == -(1 << (XLEN - 1)) and sb == -1:
        return 0
    r = abs(sa) % abs(sb)
    return _u(-r if sa < 0 else r)


def remu(a: int, b: int) -> int:
    return _u(a) if _u(b) == 0 else _u(a) % _u(b)


# Zba
def sh1add(a: int, b: int) -> int:
    return _u(b + (_u(a) << 1))


def sh2add(a: int, b: int) -> int:
    return _u(b + (_u(a) << 2))


def sh3add(a: int, b: int) -> int:
    return _u(b + (_u(a) << 3))


# Zbb
def andn(a: int, b: int) -> int:
    return _u(a & ~b)


def orn(a: int, b: int) -> int:
    return _u(a | ~b)


def xnor(a: int, b: int) -> int:
    return _u(~(a ^ b))


def clz(a: int) -> int:
    a = _u(a)
    return XLEN - a.bit_length()


def ctz(a: int) -> int:
    a = _u(a)
    return XLEN if a == 0 else (a & -a).bit_length() - 1


def cpop(a: int) -> int:
    return bin(_u(a)).count("1")


def max_(a: int, b: int) -> int:
    return _u(max(_s(a), _s(b)))


def maxu(a: int, b: int) -> int:
    return max(_u(a), _u(b))


def min_(a: int, b: int) -> int:
    return _u(min(_s(a), _s(b)))


def minu(a: int, b: int) -> int:
    return min(_u(a), _u(b))


def sext_b(a: int) -> int:
    v = a & 0xFF
    return _u(v - 0x100 if v & 0x80 else v)


def sext_h(a: int) -> int:
    v = a & 0xFFFF
    return _u(v - 0x10000 if v & 0x8000 else v)


def zext_h(a: int) -> int:
    return a & 0xFFFF


def rol(a: int, b: int) -> int:
    sh = b & (XLEN - 1)
    a = _u(a)
    return _u((a << sh) | (a >> ((XLEN - sh) & (XLEN - 1)))) if sh else a


def ror(a: int, b: int) -> int:
    sh = b & (XLEN - 1)
    a = _u(a)
    return _u((a >> sh) | (a << ((XLEN - sh) & (XLEN - 1)))) if sh else a


def rori(a: int, shamt: int) -> int:
    return ror(a, shamt & (XLEN - 1))


def orc_b(a: int) -> int:
    a = _u(a)
    return sum((0xFF << (8 * i)) for i in range(XLEN // 8) if (a >> (8 * i)) & 0xFF)


def rev8(a: int) -> int:
    return int.from_bytes(_u(a).to_bytes(XLEN // 8, "little"), "big")


# Zbc
def _clmul_full(a: int, b: int) -> int:
    a, b = _u(a), _u(b)
    out = 0
    for i in range(XLEN):
        if (b >> i) & 1:
            out ^= a << i
    return out


def clmul(a: int, b: int) -> int:
    return _u(_clmul_full(a, b))


def clmulh(a: int, b: int) -> int:
    return _u(_clmul_full(a, b) >> XLEN)


def clmulr(a: int, b: int) -> int:
    return _u(_clmul_full(a, b) >> (XLEN - 1))


OPS: dict[str, tuple[Callable[..., int], str]] = {
    "mul": (mul, "rr"),
    "mulh": (mulh, "rr"),
    "mulhsu": (mulhsu, "rr"),
    "mulhu": (mulhu, "rr"),
    "div": (div, "rr"),
    "divu": (divu, "rr"),
    "rem": (rem, "rr"),
    "remu": (remu, "rr"),
    "sh1add": (sh1add, "rr"),
    "sh2add": (sh2add, "rr"),
    "sh3add": (sh3add, "rr"),
    "andn": (andn, "rr"),
    "orn": (orn, "rr"),
    "xnor": (xnor, "rr"),
    "clz": (clz, "r"),
    "ctz": (ctz, "r"),
    "cpop": (cpop, "r"),
    "max": (max_, "rr"),
    "maxu": (maxu, "rr"),
    "min": (min_, "rr"),
    "minu": (minu, "rr"),
    "sext.b": (sext_b, "r"),
    "sext.h": (sext_h, "r"),
    "zext.h": (zext_h, "r"),
    "rol": (rol, "rr"),
    "ror": (ror, "rr"),
    "rori": (rori, "ri"),
    "orc.b": (orc_b, "r"),
    "rev8": (rev8, "r"),
    "clmul": (clmul, "rr"),
    "clmulh": (clmulh, "rr"),
    "clmulr": (clmulr, "rr"),
}


def evaluate(op: str, a: int, b: int = 0) -> int:
    """The ``rd`` value of ``op`` for ``rs1 = a`` and ``rs2 = b`` (or the shift amount)."""
    fn, kind = OPS[op]
    return fn(a) if kind == "r" else fn(a, b)


# Hand vectors from the specification text: (op, rs1, rs2/shamt, rd).
_VECTORS: tuple[tuple[str, int, int, int], ...] = (
    # M: division-by-zero and overflow table.
    ("div", 7, 0, 0xFFFF_FFFF),
    ("divu", 7, 0, 0xFFFF_FFFF),
    ("rem", 7, 0, 7),
    ("remu", 7, 0, 7),
    ("div", 0x8000_0000, 0xFFFF_FFFF, 0x8000_0000),
    ("rem", 0x8000_0000, 0xFFFF_FFFF, 0),
    # M: rounding toward zero, remainder takes the dividend sign.
    ("div", 0xFFFF_FFF9, 2, 0xFFFF_FFFD),
    ("rem", 0xFFFF_FFF9, 2, 0xFFFF_FFFF),
    ("divu", 0xFFFF_FFF9, 2, 0x7FFF_FFFC),
    ("mul", 0xFFFF_FFFF, 0xFFFF_FFFF, 1),
    ("mulh", 0xFFFF_FFFF, 0xFFFF_FFFF, 0),
    ("mulhu", 0xFFFF_FFFF, 0xFFFF_FFFF, 0xFFFF_FFFE),
    ("mulhsu", 0xFFFF_FFFF, 0xFFFF_FFFF, 0xFFFF_FFFF),
    ("mulh", 0x8000_0000, 0x8000_0000, 0x4000_0000),
    # Zba: rd = rs2 + (rs1 << n).
    ("sh1add", 1, 2, 4),
    ("sh2add", 1, 2, 6),
    ("sh3add", 1, 2, 10),
    # Zbb.
    ("andn", 0xF0F0, 0x00FF, 0xF000),
    ("orn", 0, 0xFFFF_FFF0, 0xF),
    ("xnor", 0xFFFF_0000, 0xFF00_FF00, 0xFF00_00FF),
    ("clz", 0, 0, 32),
    ("clz", 0x0001_0000, 0, 15),
    ("ctz", 0, 0, 32),
    ("ctz", 0x8000_0000, 0, 31),
    ("cpop", 0xFFFF_FFFF, 0, 32),
    ("cpop", 0x8000_0001, 0, 2),
    ("max", 0xFFFF_FFFF, 1, 1),
    ("maxu", 0xFFFF_FFFF, 1, 0xFFFF_FFFF),
    ("min", 0xFFFF_FFFF, 1, 0xFFFF_FFFF),
    ("minu", 0xFFFF_FFFF, 1, 1),
    ("sext.b", 0x80, 0, 0xFFFF_FF80),
    ("sext.b", 0x1234_567F, 0, 0x7F),
    ("sext.h", 0x8000, 0, 0xFFFF_8000),
    ("zext.h", 0xFFFF_1234, 0, 0x1234),
    ("rol", 0x8000_0001, 1, 3),
    ("rol", 0x1234_5678, 32, 0x1234_5678),
    ("ror", 1, 1, 0x8000_0000),
    ("rori", 0x0000_00F0, 4, 0x0000_000F),
    ("orc.b", 0x0001_0200, 0, 0x00FF_FF00),
    ("rev8", 0x1234_5678, 0, 0x7856_3412),
    # Zbc: carry-less product bits 31:0, 63:32 and 62:31.
    ("clmul", 3, 3, 5),
    ("clmul", 0x8000_0000, 0x8000_0000, 0),
    ("clmulh", 0x8000_0000, 0x8000_0000, 0x4000_0000),
    ("clmulr", 0x8000_0000, 0x8000_0000, 0x8000_0000),
    ("clmulh", 3, 3, 0),
)


def _selftest() -> int:
    bad = 0
    for op, a, b, want in _VECTORS:
        got = evaluate(op, a, b)
        if got != want:
            print(f"FAIL {op}(0x{a:08x}, 0x{b:08x}) = 0x{got:08x}, want 0x{want:08x}")
            bad += 1
    print(f"sep_rv_isa_golden: {len(_VECTORS) - bad}/{len(_VECTORS)} vectors pass")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
