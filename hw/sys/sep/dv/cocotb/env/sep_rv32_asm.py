# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RV32I encoder and a two-pass assembler for test-generated code images.

A leaf that stages its own code (boot ROM stub, SRAM or ICCM routine) through
the bench backdoor builds the words here. The encoders follow the RISC-V
unprivileged and privileged specifications (RV32I base, Zicsr, Zifencei).
Registers are numbers (``x0`` = 0 ... ``x31`` = 31); the ABI names below are
for readability only.

:class:`Asm` keeps labels, resolves branches and jumps on a second pass and
places the absolute address of a label with :meth:`Asm.la` (``lui`` plus
``addi``). The image base is fixed at construction, so a label address is
known before the code runs.

The module has no simulator import, so a self-check runs without cocotb::

    python3 sep_rv32_asm.py
"""

from __future__ import annotations

ZERO, RA, SP, GP, TP = 0, 1, 2, 3, 4
T0, T1, T2 = 5, 6, 7
S0, S1 = 8, 9
A0, A1, A2, A3, A4, A5, A6, A7 = 10, 11, 12, 13, 14, 15, 16, 17
S2, S3, S4, S5, S6, S7, S8, S9, S10, S11 = 18, 19, 20, 21, 22, 23, 24, 25, 26, 27
T3, T4, T5, T6 = 28, 29, 30, 31

FENCE = 0x0FF0_000F
FENCE_I = 0x0000_100F
ECALL = 0x0000_0073
MRET = 0x3020_0073

# Machine CSRs (privileged specification) and the VeeR EL2 D-bus error pair.
CSR_MSCRATCH = 0x340
CSR_MTVEC = 0x305
CSR_MEPC = 0x341
CSR_MCAUSE = 0x342
CSR_MTVAL = 0x343
CSR_MDSEAC = 0xFC0  # VeeR EL2 D-bus error address capture
CSR_MDEAU = 0xBC0  # VeeR EL2 D-bus error address unlock

# funct3 of the loads and stores by access size in bytes (unsigned loads).
LOAD_F3 = {1: 4, 2: 5, 4: 2}  # lbu, lhu, lw
STORE_F3 = {1: 0, 2: 1, 4: 2}  # sb, sh, sw


def _chk(v: int, lo: int, hi: int, what: str) -> None:
    if not lo <= v <= hi:
        raise ValueError(f"{what} {v} outside [{lo}, {hi}]")


def i_type(op: int, f3: int, rd: int, rs1: int, imm: int) -> int:
    _chk(imm, -2048, 2047, "I-type immediate")
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def s_type(f3: int, rs2: int, rs1: int, imm: int) -> int:
    _chk(imm, -2048, 2047, "S-type immediate")
    return (
        (((imm >> 5) & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (f3 << 12)
        | ((imm & 0x1F) << 7)
        | 0x23
    )


def r_type(f7: int, f3: int, rd: int, rs1: int, rs2: int) -> int:
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | 0x33


def lui(rd: int, imm20: int) -> int:
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | 0x37


def addi(rd: int, rs1: int, imm: int) -> int:
    return i_type(0x13, 0, rd, rs1, imm)


def andi(rd: int, rs1: int, imm: int) -> int:
    return i_type(0x13, 7, rd, rs1, imm)


def ori(rd: int, rs1: int, imm: int) -> int:
    return i_type(0x13, 6, rd, rs1, imm)


def slli(rd: int, rs1: int, sh: int) -> int:
    _chk(sh, 0, 31, "shift")
    return i_type(0x13, 1, rd, rs1, sh)


def add(rd: int, rs1: int, rs2: int) -> int:
    return r_type(0, 0, rd, rs1, rs2)


def sub(rd: int, rs1: int, rs2: int) -> int:
    return r_type(0x20, 0, rd, rs1, rs2)


def or_(rd: int, rs1: int, rs2: int) -> int:
    return r_type(0, 6, rd, rs1, rs2)


def and_(rd: int, rs1: int, rs2: int) -> int:
    return r_type(0, 7, rd, rs1, rs2)


def xor_(rd: int, rs1: int, rs2: int) -> int:
    return r_type(0, 4, rd, rs1, rs2)


def load(size: int, rd: int, rs1: int, off: int = 0) -> int:
    """Unsigned load of ``size`` bytes (lbu, lhu, lw)."""
    return i_type(0x03, LOAD_F3[size], rd, rs1, off)


def store(size: int, rs2: int, rs1: int, off: int = 0) -> int:
    """Store of ``size`` bytes (sb, sh, sw)."""
    return s_type(STORE_F3[size], rs2, rs1, off)


def lw(rd: int, rs1: int, off: int = 0) -> int:
    return load(4, rd, rs1, off)


def sw(rs2: int, rs1: int, off: int = 0) -> int:
    return store(4, rs2, rs1, off)


def jalr(rd: int, rs1: int, off: int = 0) -> int:
    return i_type(0x67, 0, rd, rs1, off)


def jal(rd: int, off: int) -> int:
    _chk(off, -(1 << 20), (1 << 20) - 2, "jal offset")
    return (
        (((off >> 20) & 1) << 31)
        | (((off >> 1) & 0x3FF) << 21)
        | (((off >> 11) & 1) << 20)
        | (((off >> 12) & 0xFF) << 12)
        | (rd << 7)
        | 0x6F
    )


BRANCH_F3 = {"beq": 0, "bne": 1, "blt": 4, "bge": 5, "bltu": 6, "bgeu": 7}


def branch(kind: str, rs1: int, rs2: int, off: int) -> int:
    _chk(off, -4096, 4094, "branch offset")
    return (
        (((off >> 12) & 1) << 31)
        | (((off >> 5) & 0x3F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (BRANCH_F3[kind] << 12)
        | (((off >> 1) & 0xF) << 8)
        | (((off >> 11) & 1) << 7)
        | 0x63
    )


def csrr(rd: int, csr: int) -> int:
    """csrrs rd, csr, x0."""
    return (csr << 20) | (2 << 12) | (rd << 7) | 0x73


def csrw(csr: int, rs1: int) -> int:
    """csrrw x0, csr, rs1."""
    return (csr << 20) | (rs1 << 15) | (1 << 12) | 0x73


def _hi_lo(v: int) -> tuple[int, int]:
    v &= 0xFFFF_FFFF
    hi = ((v + 0x800) >> 12) & 0xFFFFF
    lo = (v - (hi << 12)) & 0xFFF
    return hi, lo - 0x1000 if lo & 0x800 else lo


def li(rd: int, v: int) -> list[int]:
    """Load a 32-bit constant: ``lui`` then ``addi`` (always two words)."""
    hi, lo = _hi_lo(v)
    return [lui(rd, hi), addi(rd, rd, lo)]


class Asm:
    """Two-pass assembler: 32-bit words, labels, branches, jumps and label addresses."""

    def __init__(self, base: int) -> None:
        if base % 4:
            raise ValueError("the image base must be 4-byte aligned")
        self.base = base
        self.items: list = []
        self.labels: dict[str, int] = {}

    def op(self, *words: int) -> "Asm":
        self.items.extend(words)
        return self

    def li(self, rd: int, v: int) -> "Asm":
        return self.op(*li(rd, v))

    def label(self, name: str) -> "Asm":
        if name in self.labels:
            raise ValueError(f"label {name} defined twice")
        self.labels[name] = len(self.items)
        return self

    def align(self, nbytes: int) -> "Asm":
        """Pad with ``addi x0, x0, 0`` to a ``nbytes`` boundary of the absolute address."""
        while (self.base + 4 * len(self.items)) % nbytes:
            self.items.append(addi(ZERO, ZERO, 0))
        return self

    def br(self, kind: str, rs1: int, rs2: int, target: str) -> "Asm":
        self.items.append(("b", kind, rs1, rs2, target))
        return self

    def j(self, target: str, rd: int = ZERO) -> "Asm":
        self.items.append(("j", rd, target))
        return self

    def la(self, rd: int, target: str) -> "Asm":
        """Absolute address of ``target`` into ``rd`` (two words)."""
        self.items.append(("hi", rd, target))
        self.items.append(("lo", rd, target))
        return self

    def addr(self, name: str) -> int:
        return self.base + 4 * self.labels[name]

    @property
    def nbytes(self) -> int:
        return 4 * len(self.items)

    def words(self) -> list[int]:
        out = []
        for idx, it in enumerate(self.items):
            if isinstance(it, int):
                out.append(it & 0xFFFF_FFFF)
            elif it[0] == "b":
                out.append(branch(it[1], it[2], it[3], 4 * (self.labels[it[4]] - idx)))
            elif it[0] == "j":
                out.append(jal(it[1], 4 * (self.labels[it[2]] - idx)))
            else:
                hi, lo = _hi_lo(self.addr(it[2]))
                out.append(lui(it[1], hi) if it[0] == "hi" else addi(it[1], it[1], lo))
        return out

    def to_bytes(self) -> bytes:
        return words_to_bytes(self.words())


def words_to_bytes(words: list[int]) -> bytes:
    return b"".join((w & 0xFFFF_FFFF).to_bytes(4, "little") for w in words)


if __name__ == "__main__":
    # Hand vectors from the RISC-V encoding tables.
    assert addi(T0, ZERO, 1) == 0x0010_0293
    assert lui(T0, 0x10040) == 0x1004_02B7
    assert lw(A0, S0, 4) == 0x0044_2503
    assert load(1, A0, S0, 0) == 0x0004_4503  # lbu a0, 0(s0)
    assert load(2, A0, S0, 0) == 0x0004_5503  # lhu a0, 0(s0)
    assert sw(A0, GP, 0x40) == 0x04A1_A023
    assert store(1, A0, S0, 0) == 0x00A4_0023  # sb a0, 0(s0)
    assert store(2, A0, S0, 0) == 0x00A4_1023  # sh a0, 0(s0)
    assert jalr(ZERO, T0, 0) == 0x0002_8067
    assert jal(ZERO, 0) == 0x0000_006F
    assert csrr(T6, CSR_MCAUSE) == 0x3420_2FF3
    assert csrw(CSR_MTVEC, T0) == 0x3052_9073
    assert branch("bne", A1, ZERO, -8) == 0xFE05_9CE3
    for v in (0, 0x7FF, 0x800, 0xFFF, 0x8000_0000, 0x1004_FFF8, 0xFFFF_FFFF):
        hi, lo = _hi_lo(v)
        assert ((hi << 12) + lo) & 0xFFFF_FFFF == v, hex(v)
    a = Asm(0x1000_0000)
    a.la(T0, "x").label("top").br("bne", T0, ZERO, "top").label("x").j("top")
    w = a.words()
    assert a.addr("x") == 0x1000_000C and w[2] == branch("bne", T0, ZERO, 0)
    assert w[3] == jal(ZERO, -4)
    print("sep_rv32_asm self-check PASS")
