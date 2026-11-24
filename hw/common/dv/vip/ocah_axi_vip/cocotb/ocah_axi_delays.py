# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded cycle-count stream for responder READY stalls and response delays.

`OcahAxiDelays` is an endless iterator of cycle counts drawn from a 32-bit
xorshift generator. With ``long_percent`` set, each count comes from
``[long_min, long_max]`` with that percentage and from
``[short_min, short_max]`` otherwise. The SV-UVM ``ocah_axi_delays`` runs the
same generator, so one seed gives the same stream in both realizations.
"""

from __future__ import annotations

__all__ = ["OcahAxiDelays"]

_MASK32 = 0xFFFFFFFF
_SEED_MIX = 0x9E3779B9
_ZERO_STATE = 0x6D2B79F5


class OcahAxiDelays:
    """Endless seeded stream of cycle counts, one per stall window or response."""

    def __init__(
        self,
        seed: int,
        *,
        short_min: int = 0,
        short_max: int = 0,
        long_percent: int = 0,
        long_min: int = 0,
        long_max: int = 0,
    ) -> None:
        if min(short_min, short_max, long_min, long_max) < 0:
            raise ValueError("OcahAxiDelays bounds must be non-negative")
        if short_min > short_max:
            raise ValueError(f"short_min {short_min} > short_max {short_max}")
        if not 0 <= long_percent <= 100:
            raise ValueError(f"long_percent {long_percent} outside 0..100")
        if long_percent and long_min > long_max:
            raise ValueError(f"long_min {long_min} > long_max {long_max}")
        self.short_min = int(short_min)
        self.short_max = int(short_max)
        self.long_percent = int(long_percent)
        self.long_min = int(long_min)
        self.long_max = int(long_max)
        self._state = ((int(seed) & _MASK32) ^ _SEED_MIX) or _ZERO_STATE

    @property
    def max_value(self) -> int:
        """Largest count a draw can return."""
        return max(self.short_max, self.long_max) if self.long_percent else self.short_max

    def __iter__(self) -> OcahAxiDelays:
        return self

    def __next__(self) -> int:
        lo, hi = self.short_min, self.short_max
        if self.long_percent and self._u32() % 100 < self.long_percent:
            lo, hi = self.long_min, self.long_max
        return lo + self._u32() % (hi - lo + 1)

    def _u32(self) -> int:
        x = self._state
        x ^= (x << 13) & _MASK32
        x ^= x >> 17
        x ^= (x << 5) & _MASK32
        self._state = x
        return x
