# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register compare on the RDL field bits only.

The shared reserved-bit rule of the Phase 3 VPLAN (``[[sep-vplan-reserved-bits]]``):
a graded register compare uses the RDL field bits of the register, and the bits
that the RDL marks Reserved with no reset value are masked out of the compare
and logged in the same line. Bits [63:32] of an AxSIZE 3 read of a 32-bit
register are Reserved in this sense and are logged, never graded.

The field mask comes from the generated register metadata
(``env.sep_reg_meta.RegBlock.mask32``) or is passed by the caller when the
register is outside that metadata (a vendored block named by the VPLAN).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldCompare:
    got: int
    expect: int
    mask: int

    def __post_init__(self) -> None:
        # A compare on no field bits cannot fail, so it is a test error.
        if self.mask == 0:
            raise ValueError("field_compare: field mask is 0, the compare cannot fail")

    @property
    def ok(self) -> bool:
        return (self.got & self.mask) == (self.expect & self.mask)

    @property
    def rsvd(self) -> int:
        """The bits outside the field mask, as read. Logged, never graded."""
        return self.got & ~self.mask & 0xFFFF_FFFF_FFFF_FFFF

    def fields(self) -> str:
        """``value= expect= field_mask= rsvd=`` for a CHK line."""
        return (
            f"value=0x{self.got & self.mask:x} expect=0x{self.expect & self.mask:x} "
            f"field_mask=0x{self.mask:x} rsvd=0x{self.rsvd:x}"
        )


def field_compare(got: int, expect: int, mask: int) -> FieldCompare:
    """Compare ``got`` with ``expect`` on ``mask``; the rest is logged only."""
    return FieldCompare(got, expect, mask)


def lane32(data64: int, addr: int) -> int:
    """The 32-bit lane of a 64-bit beat that a 4-byte access at ``addr`` uses."""
    return (data64 >> 32) & 0xFFFF_FFFF if addr & 0x4 else data64 & 0xFFFF_FFFF
