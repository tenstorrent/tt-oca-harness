# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frozen BYPASS scenarios and a pure one-bit-delay reference model."""

from __future__ import annotations

import random
from dataclasses import dataclass

from .dtp_types import DtpJtagInstr

__all__ = ["DtpBypassCaseCfg", "DtpBypassRefModel", "DtpBypassSuiteCfg"]

BYPASS_00 = int(DtpJtagInstr.BYPASS_00)
BYPASS_3F = int(DtpJtagInstr.BYPASS_3F)
_BYPASS_OPCODES = (BYPASS_00, BYPASS_3F)


def _bit_mask(width: int) -> int:
    return (1 << width) - 1


def _salted_rng(seed: int, label: str) -> random.Random:
    salt = sum((index + 1) * ord(char) for index, char in enumerate(label))
    return random.Random(seed ^ salt)


def _directed_patterns(width: int, *, seed: int, label: str, random_count: int) -> tuple[int, ...]:
    mask = _bit_mask(width)
    patterns = [
        0,
        mask,
        0xAAAA_AAAA_AAAA_AAAA & mask,
        0x5555_5555_5555_5555 & mask,
        0xA5A5_5A5A_C3C3_3C3C & mask,
        0x0123_4567_89AB_CDEF & mask,
    ]
    for bit_pos in sorted({0, width // 4, width // 2, (3 * width) // 4, width - 1}):
        patterns.append(1 << bit_pos)
        patterns.append(mask ^ (1 << bit_pos))
    rng = _salted_rng(seed, label)
    for _ in range(random_count):
        patterns.append(rng.getrandbits(width) & mask)
    return tuple(dict.fromkeys(patterns))


@dataclass(frozen=True)
class DtpBypassCaseCfg:
    """One immutable BYPASS transaction shared by stimulus and prediction."""

    instruction: int
    width: int
    pattern: int
    capture_bit: int = 0
    label: str = ""

    def __post_init__(self) -> None:
        if self.instruction not in _BYPASS_OPCODES:
            raise ValueError(f"unsupported DTP BYPASS opcode 0x{self.instruction:02x}")
        if self.width <= 0:
            raise ValueError(f"BYPASS width must be positive, got {self.width}")
        if self.pattern < 0 or self.pattern > _bit_mask(self.width):
            raise ValueError(f"BYPASS pattern 0x{self.pattern:x} does not fit width {self.width}")
        if self.capture_bit not in (0, 1):
            raise ValueError(f"BYPASS capture_bit must be 0 or 1, got {self.capture_bit}")

    @property
    def check_id(self) -> str:
        return f"CHK-BYPASS-{self.instruction:02X}"

    @property
    def context(self) -> str:
        digits = (self.width + 3) // 4
        return (
            f"case={self.label or '-'} opcode=0x{self.instruction:02x} "
            f"width={self.width} pattern=0x{self.pattern:0{digits}x} "
            f"capture={self.capture_bit}"
        )


@dataclass(frozen=True)
class DtpBypassSuiteCfg:
    """Seeded ordered BYPASS cases used by both DUT stimulus and the model."""

    seed: int
    cases: tuple[DtpBypassCaseCfg, ...]

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("DTP BYPASS suite must contain at least one case")

    @classmethod
    def from_seed(
        cls,
        seed: int,
        *,
        width: int = 64,
        random_count: int = 5,
    ) -> DtpBypassSuiteCfg:
        if random_count < 0:
            raise ValueError(f"random_count must be non-negative, got {random_count}")

        cases: list[DtpBypassCaseCfg] = []
        for instruction in _BYPASS_OPCODES:
            patterns = _directed_patterns(
                width,
                seed=seed,
                label=f"bypass_{instruction:02x}",
                random_count=random_count,
            )
            for index, pattern in enumerate(patterns):
                cases.append(
                    DtpBypassCaseCfg(
                        instruction=instruction,
                        width=width,
                        pattern=pattern,
                        label=f"opcode_{instruction:02x}_{index:02d}",
                    )
                )
            cases.append(
                DtpBypassCaseCfg(
                    instruction=instruction,
                    width=8,
                    pattern=0x5A,
                    label=f"opcode_{instruction:02x}_focused",
                )
            )
        return cls(seed=seed, cases=tuple(cases))


class DtpBypassRefModel:
    """Pure IEEE 1149.1 one-bit BYPASS prediction."""

    @staticmethod
    def predict(case: DtpBypassCaseCfg) -> int:
        shifted_input = case.pattern & _bit_mask(max(case.width - 1, 0))
        return (case.capture_bit & 0x1) | (shifted_input << 1)

    @staticmethod
    def direct_passthrough(case: DtpBypassCaseCfg) -> int:
        """Return the non-delayed TDI value used only for non-vacuity checks."""
        return case.pattern & _bit_mask(case.width)
