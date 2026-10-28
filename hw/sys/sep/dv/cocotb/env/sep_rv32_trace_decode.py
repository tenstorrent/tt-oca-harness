# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RV32 retirement-trace decoding for Boot ROM ordering and CSR-value checks.

The EL2 trace carries the PC and the instruction word of each retirement, not
register values. RegTracker recovers the constants the ROM builds with lui and
immediate ALU instructions, so a leaf can grade a CSR write on the value written.
A register written by any other instruction becomes unknown.

The module has no simulator import, so its self-check runs without cocotb::

    python3 sep_rv32_trace_decode.py
"""

from __future__ import annotations

from dataclasses import dataclass

MASK32 = 0xFFFF_FFFF

OP_LOAD = 0x03
OP_MISC_MEM = 0x0F
OP_OP_IMM = 0x13
OP_AUIPC = 0x17
OP_STORE = 0x23
OP_OP = 0x33
OP_LUI = 0x37
OP_JALR = 0x67
OP_JAL = 0x6F
OP_SYSTEM = 0x73

CSR_MSTATUS = 0x300
CSR_MIE = 0x304
CSR_MTVEC = 0x305
CSR_MEPC = 0x341
CSR_PMPCFG0 = 0x3A0
CSR_PMPADDR0 = 0x3B0
CSR_MSECCFG = 0x747
CSR_MRAC = 0x7C0
CSR_MHARTID = 0xF14

MSTATUS_MIE = 1 << 3
# Smepmp mseccfg fields.
MSECCFG_MML = 1 << 0
MSECCFG_MMWP = 1 << 1
MSECCFG_RLB = 1 << 2
# pmpNcfg fields (RISC-V privileged spec, PMP configuration register format).
PMPCFG_R = 1 << 0
PMPCFG_W = 1 << 1
PMPCFG_X = 1 << 2
PMPCFG_A_MASK = 0x3 << 3
PMPCFG_A_NAPOT = 0x3 << 3
PMPCFG_L = 1 << 7

INSN_MRET = 0x3020_0073
INSN_FENCE_I = 0x0000_100F

_WRITES_RD = frozenset({OP_LUI, OP_AUIPC, OP_OP_IMM, OP_OP, OP_LOAD, OP_JAL, OP_JALR})
_CSR_KIND = {
    1: ("rw", False),
    2: ("rs", False),
    3: ("rc", False),
    5: ("rw", True),
    6: ("rs", True),
    7: ("rc", True),
}


def opcode(insn: int) -> int:
    return insn & 0x7F


def funct3(insn: int) -> int:
    return (insn >> 12) & 0x7


def rd_of(insn: int) -> int:
    return (insn >> 7) & 0x1F


def rs1_of(insn: int) -> int:
    return (insn >> 15) & 0x1F


def imm_i(insn: int) -> int:
    v = (insn >> 20) & 0xFFF
    return v - 0x1000 if v & 0x800 else v


def is_load(insn: int) -> bool:
    return opcode(insn) == OP_LOAD


def is_store(insn: int) -> bool:
    return opcode(insn) == OP_STORE


def is_fence(insn: int) -> bool:
    return opcode(insn) == OP_MISC_MEM and funct3(insn) == 0


def is_fence_i(insn: int) -> bool:
    return opcode(insn) == OP_MISC_MEM and funct3(insn) == 1


@dataclass(frozen=True)
class CsrOp:
    """One Zicsr instruction: kind is rw, rs or rc; src is rs1 or the 5-bit immediate."""

    kind: str
    csr: int
    rd: int
    src: int
    imm: bool

    @property
    def writes(self) -> bool:
        # csrrs and csrrc with x0 or a zero immediate only read the CSR.
        return self.kind == "rw" or self.src != 0


def decode_csr(insn: int) -> CsrOp | None:
    if opcode(insn) != OP_SYSTEM:
        return None
    kind = _CSR_KIND.get(funct3(insn))
    if kind is None:
        return None
    return CsrOp(kind[0], (insn >> 20) & 0xFFF, rd_of(insn), rs1_of(insn), kind[1])


def writes_rd(insn: int) -> int | None:
    """The destination register an instruction writes, or None."""
    op = opcode(insn)
    if op == OP_SYSTEM:
        csr = decode_csr(insn)
        return csr.rd if csr is not None and csr.rd else None
    if op in _WRITES_RD and rd_of(insn):
        return rd_of(insn)
    return None


def pmp_napot(addr_reg: int) -> tuple[int, int]:
    """Base byte address and size of a NAPOT pmpaddr value."""
    ones = 0
    while (addr_reg >> ones) & 1:
        ones += 1
    size = 1 << (ones + 3)
    base = (addr_reg & ~((1 << ones) - 1)) << 2
    return base, size


class RegTracker:
    """Constant propagation over lui, auipc and the immediate ALU instructions."""

    def __init__(self) -> None:
        self._v: dict[int, int] = {0: 0}

    def value(self, reg: int) -> int | None:
        return self._v.get(reg)

    def csr_operand(self, insn: int) -> int | None:
        """The rs1 or immediate operand of a CSR instruction; for csrrs and csrrc it is the set or clear mask."""
        op = decode_csr(insn)
        if op is None:
            return None
        return op.src if op.imm else self._v.get(op.src)

    def step(self, insn: int, pc: int = 0) -> None:
        dest = writes_rd(insn)
        if dest is None:
            return
        op = opcode(insn)
        new: int | None = None
        if op == OP_LUI:
            new = insn & 0xFFFF_F000
        elif op == OP_AUIPC:
            new = (pc + (insn & 0xFFFF_F000)) & MASK32
        elif op == OP_OP_IMM:
            a = self._v.get(rs1_of(insn))
            imm = imm_i(insn)
            f3 = funct3(insn)
            if a is not None:
                if f3 == 0:
                    new = (a + imm) & MASK32
                elif f3 == 4:
                    new = (a ^ imm) & MASK32
                elif f3 == 6:
                    new = (a | imm) & MASK32
                elif f3 == 7:
                    new = (a & imm) & MASK32
                elif f3 == 1:
                    new = (a << (imm & 0x1F)) & MASK32
                elif f3 == 5 and not (insn >> 30) & 1:
                    new = a >> (imm & 0x1F)
        if new is None:
            self._v.pop(dest, None)
        else:
            self._v[dest] = new


def _selftest() -> None:
    import sep_rv32_asm as asm

    tracker = RegTracker()
    prog = asm.li(asm.T0, 0xAAAA_AAA8) + [asm.csrw(CSR_MRAC, asm.T0)]
    for word in prog[:-1]:
        tracker.step(word)
    op = decode_csr(prog[-1])
    assert op == CsrOp("rw", CSR_MRAC, 0, asm.T0, False) and op.writes, op
    assert tracker.csr_operand(prog[-1]) == 0xAAAA_AAA8, hex(tracker.csr_operand(prog[-1]) or 0)
    assert prog[-1] == 0x7C02_9073, hex(prog[-1])

    read = decode_csr(asm.csrr(asm.T1, CSR_MHARTID))
    assert read is not None and read.kind == "rs" and not read.writes, read
    tracker.step(asm.csrr(asm.T0, CSR_MHARTID))
    assert tracker.value(asm.T0) is None, "a CSR read must make its rd unknown"

    tracker.step(asm.lw(asm.T0, asm.SP, 0))
    assert tracker.value(asm.T0) is None, "a load must make its rd unknown"
    assert writes_rd(asm.lw(asm.T0, asm.SP, 0)) == asm.T0
    assert writes_rd(asm.sw(asm.T0, asm.SP, 0)) is None

    base, size = 0x1004_0000, 0x1_0000
    reg = (base >> 2) | ((size >> 3) - 1)
    assert pmp_napot(reg) == (base, size), pmp_napot(reg)

    assert is_fence_i(INSN_FENCE_I) and not is_fence(INSN_FENCE_I)
    assert is_fence(0x0FF0_000F)
    assert decode_csr(INSN_MRET) is None
    assert is_load(asm.lw(asm.T0, asm.SP, 0)) and is_store(asm.sw(asm.T0, asm.SP, 0))

    # Immediate ALU paths, with expected values from the RISC-V encoding.
    def imm_op(f3: int, rd: int, rs1: int, imm12: int) -> int:
        return asm.i_type(0x13, f3, rd, rs1, imm12)

    t = RegTracker()
    t.step(asm.addi(asm.T0, asm.ZERO, -1))
    assert t.value(asm.T0) == 0xFFFF_FFFF, "addi must sign-extend a negative immediate"
    t.step(imm_op(5, asm.T1, asm.T0, 4))
    assert t.value(asm.T1) == 0x0FFF_FFFF, "srli is a logical shift"
    t.step(imm_op(5, asm.T2, asm.T0, 0x400 | 4))
    assert t.value(asm.T2) is None, "srai is not tracked"
    t.step(imm_op(4, asm.T1, asm.T0, 0x0F0))
    assert t.value(asm.T1) == 0xFFFF_FF0F, "xori"
    t.step(imm_op(7, asm.T1, asm.T0, 0x0FF))
    assert t.value(asm.T1) == 0x0000_00FF, "andi"
    t.step(asm.lui(asm.T0, 0x12345))
    t.step(asm.ori(asm.T1, asm.T0, 0x67))
    assert t.value(asm.T1) == 0x1234_5067, "ori"
    t.step(asm.slli(asm.T1, asm.T0, 4))
    assert t.value(asm.T1) == 0x2345_0000, "slli drops the bits above 32"

    # auipc adds the pc to the upper immediate.
    t.step(0x17 | (asm.T0 << 7) | (0x1 << 12), pc=0x1000_0000)
    assert t.value(asm.T0) == 0x1000_1000, "auipc"

    # Zicsr immediate forms and the read-only cases.
    def csr_imm(f3: int, csr: int, uimm: int) -> int:
        return (csr << 20) | (uimm << 15) | (f3 << 12) | 0x73

    t = RegTracker()
    for f3, kind in ((5, "rw"), (6, "rs"), (7, "rc")):
        insn = csr_imm(f3, CSR_MTVEC, 5)
        op = decode_csr(insn)
        assert op == CsrOp(kind, CSR_MTVEC, 0, 5, True) and op.writes, op
        assert t.csr_operand(insn) == 5
    assert decode_csr(csr_imm(5, CSR_MTVEC, 0)).writes, "csrrwi with 0 still writes"
    assert not decode_csr(csr_imm(6, CSR_MTVEC, 0)).writes, "csrrsi 0 only reads"
    assert not decode_csr(csr_imm(7, CSR_MTVEC, 0)).writes, "csrrci 0 only reads"
    csrrc_x0 = (CSR_MTVEC << 20) | (3 << 12) | 0x73
    assert not decode_csr(csrrc_x0).writes, "csrrc with x0 only reads"
    assert decode_csr(asm.csrw(CSR_MTVEC, asm.ZERO)).writes, "csrrw x0 still writes"

    # NAPOT: 8-byte region (no trailing ones) and a 4 KiB region.
    assert pmp_napot(0x1000 >> 2) == (0x1000, 8)
    assert pmp_napot(0x8000400 | 0x1FF) == (0x2000_1000, 0x1000)
    print("sep_rv32_trace_decode self-test PASS")


if __name__ == "__main__":
    _selftest()
