# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN compute RANDCFG: IMEM program, ERR_BITS==0, DMEM == golden.

SepOtbnComputeCfg is the single source of truth for the walked ops and the
seeded DMEM operands. Each cell loads a tiny RV32I program that reads two
DMEM words, applies ADD/XOR/AND, and writes the result. The golden is the
same Python operator -- independent of DUT output.

SepOtbnCapPlan holds the five capability programs (loop, branch, call and
return, ``bn.addc`` carry, ``bn.addm`` reduction) and their goldens. The
goldens follow the ISA text of
``vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/base-insns.yml`` and
``bignum-insns.yml``; they never read a DUT value. The OTBN-only encoders
(``loopi``, ``bn.add``, ``bn.addc``, ``bn.addm``, ``bn.lid``, ``bn.sid``)
follow the schemes of ``.../otbn/data/enc-schemes.yml``; the RV32I words come
from ``env/sep_rv32_asm.py``.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_rv32_asm import ECALL, ZERO, addi, branch, csrr, csrw, jal, jalr, lw, sw
from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_otbn_seq import (
    OTBN_ADDR_STATUS,
    OTBN_STATUS_IDLE,
    OTBN_STATUS_LOCK,
    SepOtbn,
)

# DMEM: [0]=a, [4]=b, [8]=result. Base in x6.
_LUI_X6 = 0x00000337
_ADDI_X6 = 0x00030313
_LW_A = 0x00032503  # lw x10, 0(x6)
_LW_B = 0x00432583  # lw x11, 4(x6)
_SW_R = 0x00C32423  # sw x12, 8(x6)
_ECALL = 0x00000073
# add/xor/and x12, x10, x11
_ADD = 0x00B50633
_XOR = 0x00B54633
_AND = 0x00B57633

OPS = ("add", "xor", "and")
_ALU = {"add": _ADD, "xor": _XOR, "and": _AND}


def otbn_compute_prog(op: str) -> tuple[int, ...]:
    try:
        alu = _ALU[op]
    except KeyError as exc:
        raise ValueError(f"unsupported OTBN compute op {op!r}") from exc
    return (_LUI_X6, _ADDI_X6, _LW_A, _LW_B, alu, _SW_R, _ECALL)


def golden_result(op: str, a: int, b: int) -> int:
    a &= 0xFFFF_FFFF
    b &= 0xFFFF_FFFF
    if op == "add":
        return (a + b) & 0xFFFF_FFFF
    if op == "xor":
        return a ^ b
    if op == "and":
        return a & b
    raise ValueError(f"unsupported OTBN compute op {op!r}")


def _draw_cell_operands(rng: SepSeededRng) -> tuple[int, int]:
    """The ADD/XOR/AND operands: the first two draws of the leaf seed."""
    a = rng.getrandbits(32)
    b = rng.getrandbits(32)
    if a == 0 and b == 0:
        b = 1
    return a, b


@dataclass(frozen=True)
class SepOtbnComputeCfg:
    """Single source of truth for OTBN compute RANDCFG.

    Discrete cells (walked every seed): ADD, XOR, AND. Continuous knobs
    (operands a, b) come from the run seed.
    """

    seed: int
    a: int
    b: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepOtbnComputeCfg":
        a, b = _draw_cell_operands(SepSeededRng(seed))
        return cls(seed=seed, a=a, b=b)

    def cells(self):
        for op in OPS:
            yield op, self.a, self.b, golden_result(op, self.a, self.b)

    def n_cells(self) -> int:
        return len(OPS)

    def summary(self) -> str:
        return f"seed={self.seed} a=0x{self.a:08x} b=0x{self.b:08x} ops={list(OPS)}"


# ---------------------------------------------------------------------------
# OTBN-only encoders. Field layouts from the schemes of
# vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/enc-schemes.yml; a field
# split over several bit ranges takes its most significant bits first
# (vendor/lowRISC/opentitan/upstream/hw/ip/otbn/util/shared/bit_ranges.py:87-101).
# ---------------------------------------------------------------------------
_OP_CUSTOM0 = (0b00010 << 2) | 0b11  # bn.lid, bn.sid (enc-schemes.yml custom0)
_OP_CUSTOM1 = (0b01010 << 2) | 0b11  # bn.add, bn.addc, bn.addm (custom1)
_OP_CUSTOM3 = (0b11110 << 2) | 0b11  # loopi (custom3)

# OTBN CSR addresses (vendor/lowRISC/opentitan/upstream/hw/ip/otbn/data/csr.yml:5-6, :48-49).
OTBN_CSR_FG0 = 0x7C0
OTBN_CSR_MOD0 = 0x7D0
OTBN_MOD_WORDS = 8

WLEN = 256
_WMASK = (1 << WLEN) - 1
_W32 = 0xFFFF_FFFF


def _rng_chk(v: int, lo: int, hi: int, what: str) -> None:
    if not lo <= v <= hi:
        raise ValueError(f"{what} {v} outside [{lo}, {hi}]")


def loopi(iterations: int, bodysize: int) -> int:
    """``loopi iterations, bodysize`` (scheme ``loopi``, enc-schemes.yml:208).

    ``bodysize`` is a ``uimm+1`` operand (base-insns.yml:581): the field holds
    bodysize - 1. ``iterations`` 0 encodes; at execution it raises the LOOP
    software error (base-insns.yml:636).
    """
    _rng_chk(iterations, 0, 1023, "loopi iterations")
    _rng_chk(bodysize, 1, 4096, "loopi bodysize")
    return (
        ((bodysize - 1) << 20)
        | (((iterations >> 5) & 0x1F) << 15)
        | (0b001 << 12)
        | ((iterations & 0x1F) << 7)
        | _OP_CUSTOM3
    )


def _bnaf(funct3: int, wrd: int, wrs1: int, wrs2: int, fg: int) -> int:
    # Scheme bnaf (enc-schemes.yml:240), no shift of wrs2.
    for v, what in ((wrd, "wrd"), (wrs1, "wrs1"), (wrs2, "wrs2")):
        _rng_chk(v, 0, 31, what)
    _rng_chk(fg, 0, 1, "flag group")
    return (fg << 31) | (wrs2 << 20) | (wrs1 << 15) | (funct3 << 12) | (wrd << 7) | _OP_CUSTOM1


def bn_add(wrd: int, wrs1: int, wrs2: int, fg: int = 0) -> int:
    """``bn.add wrd, wrs1, wrs2, FG<fg>`` (bignum-insns.yml:8, funct3 b000)."""
    return _bnaf(0b000, wrd, wrs1, wrs2, fg)


def bn_addc(wrd: int, wrs1: int, wrs2: int, fg: int = 0) -> int:
    """``bn.addc wrd, wrs1, wrs2, FG<fg>`` (bignum-insns.yml:55, funct3 b010)."""
    return _bnaf(0b010, wrd, wrs1, wrs2, fg)


def bn_addm(wrd: int, wrs1: int, wrs2: int) -> int:
    """``bn.addm wrd, wrs1, wrs2`` (bignum-insns.yml:109; scheme bnam, sub 0, funct3 b101)."""
    for v, what in ((wrd, "wrd"), (wrs1, "wrs1"), (wrs2, "wrs2")):
        _rng_chk(v, 0, 31, what)
    return (wrs2 << 20) | (wrs1 << 15) | (0b101 << 12) | (wrd << 7) | _OP_CUSTOM1


def _bnxid(funct3: int, rs2: int, rs1: int, offset: int) -> int:
    # Scheme bnxid (enc-schemes.yml:319): imm is offset >> 5 (simm<<5) on bits
    # 11-9 (imm[9:7]) and 31-25 (imm[6:0]); no increment.
    if offset % (WLEN // 8):
        raise ValueError(f"bn.lid/bn.sid offset {offset} is not WLEN-aligned")
    _rng_chk(offset >> 5, -512, 511, "bn.lid/bn.sid offset / 32")
    _rng_chk(rs2, 0, 31, "rs2")
    _rng_chk(rs1, 0, 31, "rs1")
    imm = (offset >> 5) & 0x3FF
    return (
        (((imm >> 7) & 0x7) << 9)
        | ((imm & 0x7F) << 25)
        | (rs2 << 20)
        | (rs1 << 15)
        | (funct3 << 12)
        | _OP_CUSTOM0
    )


def bn_lid(grd: int, grs1: int, offset: int = 0) -> int:
    """``bn.lid grd, offset(grs1)`` (bignum-insns.yml:673, funct3 b100)."""
    return _bnxid(0b100, grd, grs1, offset)


def bn_sid(grs2: int, grs1: int, offset: int = 0) -> int:
    """``bn.sid grs2, offset(grs1)`` (bignum-insns.yml:752, funct3 b101)."""
    return _bnxid(0b101, grs2, grs1, offset)


def csrw_mod(i: int, rs1: int) -> int:
    """``csrrw x0, mod<i>, rs1``: bits [32i+31:32i] of MOD (csr.yml:48-90)."""
    _rng_chk(i, 0, OTBN_MOD_WORDS - 1, "MOD word")
    return csrw(OTBN_CSR_MOD0 + i, rs1)


def wide_words(v: int) -> list[int]:
    """A WLEN value as the 8 little-endian DMEM words bn.lid / bn.sid use."""
    return [(v >> (32 * i)) & _W32 for i in range(WLEN // 32)]


# ---------------------------------------------------------------------------
# Capability programs. Label value (otbn_cap_kind) = index in CAP_KINDS + 1.
# ---------------------------------------------------------------------------
CAP_KINDS = ("loop", "branch", "call_return", "bn_addc_carry", "bn_addm_reduce")

# DMEM byte offsets. The WLEN operands and results are 32-byte aligned
# (bignum-insns.yml:673-750: bn.lid / bn.sid need a WLEN-aligned address).
CAP_DMEM_X = 0x000
CAP_DMEM_Y = 0x020
CAP_DMEM_U = 0x040
CAP_DMEM_V = 0x060
CAP_DMEM_SUM = 0x080
CAP_DMEM_ADDC = 0x0A0
CAP_DMEM_FG0 = 0x0C0
CAP_DMEM_MOD = 0x0E0
CAP_DMEM_ADDM = 0x100
CAP_DMEM_GPR = 0x120  # two 32-bit result words of the base-ISA programs

# Branch path markers: each branch skips the addi of its marker when taken.
_BR_MARK = (1, 2, 4, 8)


@dataclass(frozen=True)
class SepOtbnCapPlan:
    """Seeded operands of the five capability programs.

    The draws follow the two ADD/XOR/AND operand draws of the same seed, so
    the cell operands do not move. The bignum operands are built so the
    graded event occurs: x + y >= 2^256 (carry out of ``bn.add``) and
    a, b < MOD with a + b > MOD (``bn.addm`` subtracts MOD).
    """

    seed: int
    loop_n: int
    loop_step: int
    br_eq: int
    br_ne: int
    call_m1: int
    call_m2: int
    addc_x: int
    addc_y: int
    addc_u: int
    addc_v: int
    mod: int
    addm_a: int
    addm_b: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepOtbnCapPlan":
        rng = SepSeededRng(seed)
        _draw_cell_operands(rng)
        loop_n = rng.randrange(2, 32)
        loop_step = rng.randrange(1, 2048)
        br_eq = rng.randrange(1, 2048)
        br_ne = br_eq ^ (1 << rng.randrange(11))
        call_m1 = rng.randrange(1, 2048)
        call_m2 = rng.randrange(1, 2048)
        addc_x = rng.getrandbits(WLEN) | (1 << (WLEN - 1))
        addc_y = rng.randrange((1 << WLEN) - addc_x, 1 << WLEN)
        addc_u = rng.getrandbits(WLEN)
        addc_v = rng.getrandbits(WLEN)
        mod = rng.getrandbits(WLEN) | (1 << (WLEN - 1))
        addm_a = rng.randrange(mod // 2 + 1, mod)
        addm_b = rng.randrange(mod - addm_a + 1, mod)
        return cls(
            seed=seed,
            loop_n=loop_n,
            loop_step=loop_step,
            br_eq=br_eq,
            br_ne=br_ne,
            call_m1=call_m1,
            call_m2=call_m2,
            addc_x=addc_x,
            addc_y=addc_y,
            addc_u=addc_u,
            addc_v=addc_v,
            mod=mod,
            addm_a=addm_a,
            addm_b=addm_b,
        )

    def carry(self) -> int:
        """Carry out of x + y (the bn.add step of the bn_addc_carry program)."""
        return (self.addc_x + self.addc_y) >> WLEN

    def sum_gt_mod(self) -> bool:
        """a + b > MOD with a, b < MOD (the bn_addm_reduce operands)."""
        return (
            self.addm_a < self.mod
            and self.addm_b < self.mod
            and (self.addm_a + self.addm_b > self.mod)
        )

    def summary(self) -> str:
        return (
            f"seed={self.seed} loop_n={self.loop_n} loop_step={self.loop_step} "
            f"br_eq={self.br_eq} br_ne={self.br_ne} call_m1={self.call_m1} "
            f"call_m2={self.call_m2} addc_x=0x{self.addc_x:064x} addc_y=0x{self.addc_y:064x} "
            f"addc_u=0x{self.addc_u:064x} addc_v=0x{self.addc_v:064x} mod=0x{self.mod:064x} "
            f"addm_a=0x{self.addm_a:064x} addm_b=0x{self.addm_b:064x}"
        )


def cap_prog(plan: SepOtbnCapPlan, kind: str) -> tuple[int, ...]:
    """The IMEM image of one capability program. Every program ends ``ecall``."""
    gpr0, gpr1 = CAP_DMEM_GPR, CAP_DMEM_GPR + 4
    if kind == "loop":
        # x10 += step and x11 += 1 on each of loop_n iterations of a 2-insn body.
        return (
            addi(10, ZERO, 0),
            addi(11, ZERO, 0),
            loopi(plan.loop_n, 2),
            addi(10, 10, plan.loop_step),
            addi(11, 11, 1),
            sw(10, ZERO, gpr0),
            sw(11, ZERO, gpr1),
            ECALL,
        )
    if kind == "branch":
        # x10 == x11 (beq taken, bne not taken); x10 != x13 (beq not taken,
        # bne taken). A taken branch skips the addi of its marker (+8).
        return (
            addi(10, ZERO, plan.br_eq),
            addi(11, ZERO, plan.br_eq),
            addi(13, ZERO, plan.br_ne),
            addi(12, ZERO, 0),
            branch("beq", 10, 11, 8),
            addi(12, 12, _BR_MARK[0]),
            branch("bne", 10, 11, 8),
            addi(12, 12, _BR_MARK[1]),
            branch("beq", 10, 13, 8),
            addi(12, 12, _BR_MARK[2]),
            branch("bne", 10, 13, 8),
            addi(12, 12, _BR_MARK[3]),
            sw(12, ZERO, gpr0),
            ECALL,
        )
    if kind == "call_return":
        # jal x1 pushes the return address on the call stack; f sets x12 and
        # jalr x0, x1, 0 pops it (base-insns.yml:376, :397). The insn after the
        # call reads x12, so it must run after f.
        return (
            addi(12, ZERO, 0),
            jal(1, 20),  # call f (index 6)
            addi(13, 12, plan.call_m2),
            sw(12, ZERO, gpr0),
            sw(13, ZERO, gpr1),
            ECALL,
            addi(12, ZERO, plan.call_m1),  # f
            jalr(ZERO, 1, 0),  # return
        )
    if kind == "bn_addc_carry":
        return (
            addi(2, ZERO, 0),
            addi(3, ZERO, 1),
            addi(4, ZERO, 2),
            addi(5, ZERO, 3),
            bn_lid(2, ZERO, CAP_DMEM_X),
            bn_lid(3, ZERO, CAP_DMEM_Y),
            bn_lid(4, ZERO, CAP_DMEM_U),
            bn_lid(5, ZERO, CAP_DMEM_V),
            bn_add(4, 0, 1),  # w4 = x + y, FG0 from the result
            csrr(10, OTBN_CSR_FG0),  # FG0 after bn.add
            bn_addc(5, 2, 3),  # w5 = u + v + FG0.C
            addi(6, ZERO, 4),
            addi(7, ZERO, 5),
            bn_sid(6, ZERO, CAP_DMEM_SUM),
            bn_sid(7, ZERO, CAP_DMEM_ADDC),
            sw(10, ZERO, CAP_DMEM_FG0),
            ECALL,
        )
    if kind == "bn_addm_reduce":
        mod_load: list[int] = []
        for i in range(OTBN_MOD_WORDS):
            mod_load += [lw(10, ZERO, CAP_DMEM_MOD + 4 * i), csrw_mod(i, 10)]
        return (
            *mod_load,
            addi(2, ZERO, 0),
            addi(3, ZERO, 1),
            addi(4, ZERO, 2),
            bn_lid(2, ZERO, CAP_DMEM_X),
            bn_lid(3, ZERO, CAP_DMEM_Y),
            bn_addm(2, 0, 1),  # w2 = a + b, minus MOD when a + b > MOD
            bn_sid(4, ZERO, CAP_DMEM_ADDM),
            ECALL,
        )
    raise ValueError(f"unknown OTBN capability {kind!r}")


def cap_stage(plan: SepOtbnCapPlan, kind: str) -> dict[int, int]:
    """DMEM input words of one capability program (byte offset -> word)."""
    out: dict[int, int] = {}

    def put(base: int, v: int) -> None:
        for i, w in enumerate(wide_words(v)):
            out[base + 4 * i] = w

    if kind == "bn_addc_carry":
        put(CAP_DMEM_X, plan.addc_x)
        put(CAP_DMEM_Y, plan.addc_y)
        put(CAP_DMEM_U, plan.addc_u)
        put(CAP_DMEM_V, plan.addc_v)
    elif kind == "bn_addm_reduce":
        put(CAP_DMEM_X, plan.addm_a)
        put(CAP_DMEM_Y, plan.addm_b)
        put(CAP_DMEM_MOD, plan.mod)
    return out


def fg_word(c: int, result: int) -> int:
    """FG0 after a WLEN add (csr.yml:5-15; otbn/README.md:911-921).

    Bit 0 C (overflow), 1 M (MSb of the written result), 2 L (LSb), 3 Z
    (result zero); bits 31-4 read as 0.
    """
    result &= _WMASK
    return (
        (c & 1)
        | (((result >> (WLEN - 1)) & 1) << 1)
        | ((result & 1) << 2)
        | (int(result == 0) << 3)
    )


def cap_golden(plan: SepOtbnCapPlan, kind: str) -> dict[int, int]:
    """ISA golden of one capability program: DMEM byte offset -> 32-bit word."""
    gpr0, gpr1 = CAP_DMEM_GPR, CAP_DMEM_GPR + 4
    if kind == "loop":
        # loopi repeats its body loop_n times (base-insns.yml:608-621).
        return {
            gpr0: (plan.loop_n * plan.loop_step) & _W32,
            gpr1: plan.loop_n,
        }
    if kind == "branch":
        # beq is taken when rs1 == rs2, bne when rs1 != rs2 (base-insns.yml:326, :351).
        taken = (
            plan.br_eq == plan.br_eq,
            plan.br_eq != plan.br_eq,
            plan.br_eq == plan.br_ne,
            plan.br_eq != plan.br_ne,
        )
        return {gpr0: sum(m for m, t in zip(_BR_MARK, taken) if not t)}
    if kind == "call_return":
        return {gpr0: plan.call_m1, gpr1: (plan.call_m1 + plan.call_m2) & _W32}
    if kind == "bn_addc_carry":
        s = plan.addc_x + plan.addc_y
        c = s >> WLEN
        w4 = s & _WMASK
        # bn.addc adds the carry flag (bignum-insns.yml:55-62).
        w5 = (plan.addc_u + plan.addc_v + c) & _WMASK
        out = {CAP_DMEM_SUM + 4 * i: w for i, w in enumerate(wide_words(w4))}
        out.update({CAP_DMEM_ADDC + 4 * i: w for i, w in enumerate(wide_words(w5))})
        out[CAP_DMEM_FG0] = fg_word(c, w4)
        return out
    if kind == "bn_addm_reduce":
        # "If this result is greater than MOD then MOD is subtracted from it.
        # The result is then truncated to 256 bits" (bignum-insns.yml:115-117).
        s = plan.addm_a + plan.addm_b
        r = (s - plan.mod if s > plan.mod else s) & _WMASK
        return {CAP_DMEM_ADDM + 4 * i: w for i, w in enumerate(wide_words(r))}
    raise ValueError(f"unknown OTBN capability {kind!r}")


# STATUS polls after EXECUTE before the end wait FAILs (same bound as SepOtbn.wait_idle).
CAP_POLL_BOUND = 4_000
CAP_POLL_CYCLES = 20


class SepOtbnCompute(SepOtbn):
    """Load a compute program, stage DMEM operands, execute, read the result."""

    async def run_cell(self, op: str, a: int, b: int, expect: int) -> tuple[int, int]:
        await self.load_program(otbn_compute_prog(op))
        await self.write_dmem(0, a)
        await self.write_dmem(4, b)
        # Seed the result word with the complement of the golden: it can never
        # equal the golden, so the readback below detects a missing store even
        # when the golden is 0.
        sentinel = expect ^ 0xFFFF_FFFF
        await self.write_dmem(8, sentinel)
        await self.execute()
        err = await self.read_errbits()
        result = await self.read_dmem(8)
        assert result != sentinel, (
            f"OTBN {op} left DMEM[8] at the sentinel 0x{sentinel:08x}: no result stored"
        )
        return err, result

    async def stage_program(self, prog: tuple[int, ...], words: dict[int, int]) -> None:
        """Load ``prog`` into IMEM (at IDLE) and write each DMEM word of ``words``."""
        await self.load_program(prog)
        for off, w in words.items():
            await self.write_dmem(off, w)

    async def execute_to_end(
        self, *, bound: int = CAP_POLL_BOUND, poll_cycles: int = CAP_POLL_CYCLES
    ) -> tuple[int, int]:
        """Issue EXECUTE and poll STATUS until IDLE or LOCKED.

        Returns (last STATUS, polls). It never raises on the outcome: a STATUS
        other than IDLE after ``bound`` polls is for the caller to grade.
        """
        await self.start_execute()
        st = -1
        for i in range(bound):
            st = await self._rd(OTBN_ADDR_STATUS)
            if st in (OTBN_STATUS_IDLE, OTBN_STATUS_LOCK):
                return st, i
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        return st, bound
