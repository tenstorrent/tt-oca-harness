# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frame format, timing, and record types shared by every ocah_uart_vip component.

A frame is one start bit (low), ``bits`` data bits LSB first, an optional
parity bit, and ``stop_bits`` periods of the idle level (high). The bit period
is ``round(1e9 / baud)`` ns on both the driving and the sampling side, and the
sampler resynchronizes on every start edge, so the rounding error never
accumulates across frames.

``OcahUartFrame`` is the record both sides keep: the driver records what it
put on the wire, the sampler what it reconstructed, and the checker compares
the two. A frame with a low stop bit is a framing error; a framing error whose
data and parity bits are all low is a break; a parity bit that disagrees with
the data is a parity error.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass

__all__ = [
    "DEFAULT_BAUD",
    "DEFAULT_TIMEOUT_US",
    "OcahUartFrame",
    "OcahUartParity",
    "bit_period_ns",
    "check_format",
    "frame_periods",
    "parity_bit",
]

DEFAULT_BAUD = 115200
DEFAULT_TIMEOUT_US = 1_000
_MIN_BITS = 5
_MAX_BITS = 9


class OcahUartParity(str, enum.Enum):
    """Parity bit rule of a frame."""

    NONE = "none"
    EVEN = "even"
    ODD = "odd"

    @classmethod
    def coerce(cls, value: OcahUartParity | str) -> OcahUartParity:
        """The enum member for ``value``; a string is matched by name or value."""
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower()
        for member in cls:
            if text in (member.value, member.name.lower()):
                return member
        raise ValueError(f"parity must be one of {[m.value for m in cls]}, got {value!r}")


def bit_period_ns(baud: int) -> int:
    """Bit period of ``baud`` in whole nanoseconds, never below 1."""
    if baud <= 0:
        raise ValueError(f"baud must be positive, got {baud}")
    return max(1, round(1e9 / baud))


def parity_bit(data: int, bits: int, parity: OcahUartParity) -> int | None:
    """The parity bit a frame of ``data`` carries; ``None`` when the format has none."""
    if parity is OcahUartParity.NONE:
        return None
    ones = bin(data & ((1 << bits) - 1)).count("1")
    if parity is OcahUartParity.EVEN:
        return ones & 1
    return (ones & 1) ^ 1


def frame_periods(bits: int, parity: OcahUartParity, stop_bits: float) -> float:
    """Bit periods one frame occupies, start bit included."""
    return 1 + bits + (0 if parity is OcahUartParity.NONE else 1) + stop_bits


def check_format(bits: int, parity: OcahUartParity, stop_bits: float) -> None:
    """Reject a frame format outside the 5..9 data bits and 1, 1.5, or 2 stop bits the engines model."""
    if not _MIN_BITS <= bits <= _MAX_BITS:
        raise ValueError(f"bits must be within {_MIN_BITS}..{_MAX_BITS}, got {bits}")
    if stop_bits not in (1, 1.5, 2):
        raise ValueError(f"stop_bits must be 1, 1.5, or 2, got {stop_bits}")
    OcahUartParity.coerce(parity)


@dataclass(frozen=True)
class OcahUartFrame:
    """One frame as driven onto, or reconstructed from, one serial line.

    ``start_ns`` is the simulation time of the start edge; ``end_ns`` the time
    the stop bit was sampled (sampler) or released (driver), or the time the
    line returned high for a break. ``first_rise_ns`` is the sampler's record of
    the first rising edge after the start edge; the driver leaves it ``None``.
    """

    data: int
    bits: int = 8
    parity: OcahUartParity = OcahUartParity.NONE
    stop_bits: float = 1
    framing_error: bool = False
    parity_error: bool = False
    is_break: bool = False
    start_ns: int = 0
    end_ns: int = 0
    first_rise_ns: int | None = None
    line: str = ""

    @property
    def clean(self) -> bool:
        """No framing, parity, or break flag."""
        return not (self.framing_error or self.parity_error or self.is_break)

    @property
    def flags(self) -> tuple[bool, bool, bool]:
        """``(framing_error, parity_error, is_break)``."""
        return (self.framing_error, self.parity_error, self.is_break)

    @property
    def measured_bit_ns(self) -> int | None:
        """Wire bit period from the start edge to the first rising edge.

        The start bit and the trailing zero data bits form one low run, so the
        run length in bit periods is one plus the number of trailing zeros of
        ``data``. Undefined (``None``) without a recorded rising edge, for a
        break, and for all-zero data, whose first rising edge depends on the
        parity rule.
        """
        if self.first_rise_ns is None or self.is_break or self.data == 0:
            return None
        low_run = 1 + ((self.data & -self.data).bit_length() - 1)
        return round((self.first_rise_ns - self.start_ns) / low_run)

    def to_record(self) -> dict[str, object]:
        """Plain-value view for logging and dict-shaped callbacks."""
        return {
            "data": self.data,
            "bits": self.bits,
            "parity": self.parity.value,
            "stop_bits": self.stop_bits,
            "framing_error": self.framing_error,
            "parity_error": self.parity_error,
            "is_break": self.is_break,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "first_rise_ns": self.first_rise_ns,
            "line": self.line,
        }
