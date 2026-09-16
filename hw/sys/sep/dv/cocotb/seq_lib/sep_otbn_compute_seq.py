# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTBN compute RANDCFG: IMEM program, ERR_BITS==0, DMEM == golden.

SepOtbnComputeCfg is the single source of truth for the walked ops and the
seeded DMEM operands. Each cell loads a tiny RV32I program that reads two
DMEM words, applies ADD/XOR/AND, and writes the result. The golden is the
same Python operator -- independent of DUT output.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_otbn_seq import SepOtbn

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
        rng = SepSeededRng(seed)
        a = rng.getrandbits(32)
        b = rng.getrandbits(32)
        if a == 0 and b == 0:
            b = 1
        return cls(seed=seed, a=a, b=b)

    def cells(self):
        for op in OPS:
            yield op, self.a, self.b, golden_result(op, self.a, self.b)

    def n_cells(self) -> int:
        return len(OPS)

    def summary(self) -> str:
        return f"seed={self.seed} a=0x{self.a:08x} b=0x{self.b:08x} ops={list(OPS)}"


class SepOtbnCompute(SepOtbn):
    """Load a compute program, stage DMEM operands, execute, read the result."""

    async def run_cell(self, op: str, a: int, b: int, expect: int) -> tuple[int, int]:
        await self.load_program(otbn_compute_prog(op))
        await self.write_dmem(0, a)
        await self.write_dmem(4, b)
        # Seed the result word with the golden's exact complement rather than 0.
        # An `and`/`xor` golden can legitimately be 0, so a zero seed lets a
        # program that never stores its result pass the comparison. The
        # complement can never equal the golden, so the sentinel readback below
        # is a real missing-store detector.
        sentinel = expect ^ 0xFFFF_FFFF
        await self.write_dmem(8, sentinel)
        await self.execute()
        err = await self.read_errbits()
        result = await self.read_dmem(8)
        assert result != sentinel, (
            f"OTBN {op} left DMEM[8] at the sentinel 0x{sentinel:08x}: no result stored"
        )
        return err, result
