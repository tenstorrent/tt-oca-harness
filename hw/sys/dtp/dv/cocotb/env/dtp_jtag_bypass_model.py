# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frozen BYPASS cases and their pure one-bit-delay prediction.

``DtpBypassSuiteCfg`` draws the seeded cases of ``dtp_jtag_bypass_test`` once
per pass and ``DtpJtagBypassModel`` predicts each case's TDO, so stimulus and
prediction share one immutable case. The scoreboard's ``bypass`` feature is
``DtpBypassRefModel``.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from ocah_lib import OcahRng

from .dtp_types import DtpJtagInstr

__all__ = ["DtpBypassCaseCfg", "DtpBypassSuiteCfg", "DtpJtagBypassModel"]

BYPASS_00 = int(DtpJtagInstr.BYPASS_00)
BYPASS_3F = int(DtpJtagInstr.BYPASS_3F)
_BYPASS_OPCODES = (BYPASS_00, BYPASS_3F)


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
        if self.pattern < 0 or self.pattern > OcahRng.bit_mask(self.width):
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
        """Per BYPASS opcode: directed and seeded ``width``-bit patterns plus an 8-bit case."""
        if random_count < 0:
            raise ValueError(f"random_count must be non-negative, got {random_count}")

        cases: list[DtpBypassCaseCfg] = []
        for instruction in _BYPASS_OPCODES:
            patterns = OcahRng.directed_patterns(
                width,
                random_count,
                random.Random(OcahRng.salted_seed(seed, f"bypass_{instruction:02x}")),
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


class DtpJtagBypassModel:
    """Pure IEEE 1149.1 one-bit BYPASS prediction."""

    @staticmethod
    def predict(case: DtpBypassCaseCfg) -> int:
        shifted_input = case.pattern & OcahRng.bit_mask(max(case.width - 1, 0))
        return (case.capture_bit & 0x1) | (shifted_input << 1)

    @staticmethod
    def direct_passthrough(case: DtpBypassCaseCfg) -> int:
        """Return the non-delayed TDI value used only for non-vacuity checks."""
        return case.pattern & OcahRng.bit_mask(case.width)
