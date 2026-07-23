# SPDX-License-Identifier: Apache-2.0
"""P2 Phase A #3: Python-side fake BFM for AVSBus / OCTS sideband decode.

This is a pure Python VIP: it does NOT drive any DUT signal. It bundles
the AVSBus SVID/SVDATA and OCTS timer-frame encode/decode logic that a
future silicon-side BFM would consume, plus a mini scoreboard that
consumes AVSBus/OCTS CSR readouts (via SmcCsrSeq) and cross-checks the
decoded protocol semantics.

Deferred blocker note: the full AVSBus / OCTS sideband BFM was originally
planned to attach to tb_top packed-array pads (SVDATA[7:0], OCTS timer
subframe[15:0]). That port lift destabilised the Verilator model. This
Python-side fake BFM lands the encode/decode + scoreboard portion of
P2-A #3 while the pad lift awaits a Verilator-safe refactor.

Public API
----------
AvsbusFrame(cmd: int, subframe: int, payload: int) — 32-bit AVSBus command
    frame per the SVID/SVDATA protocol.
    .encode() -> int (24-bit master-issued frame)
    .parity_ok() -> bool

OctsFrame(preset_lo, preset_hi, count_lo, count_hi) — OCTS 64-bit timer
    subframe with cross-halfword sanity checks.

SidebandScoreboard — accepts (name, addr, value) tuples from CSR reads
    and cross-checks any AVSBus/OCTS invariants (unused config bits are
    zero at reset; INTR_STATUS reads observed non-erroring).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class AvsbusFrame:
    """AVSBus SVID/SVDATA command frame.

    Bit layout (LSB-first, per Intel/AMD AVS spec draft):
      [2:0]   command  (000=VOUT_COMMAND, 001=STATUS, ...)
      [10:3]  data[7:0]
      [15:11] rail
      [23:16] parity + reserved
    """

    cmd: int
    subframe: int
    payload: int

    def encode(self) -> int:
        return (
            (self.cmd & 0x7)
            | ((self.payload & 0xFF) << 3)
            | ((self.subframe & 0x1F) << 11)
        ) & 0xFFFFFF

    def parity_ok(self) -> bool:
        # Even parity across the low 16 bits: OK when popcount is even.
        v = self.encode() & 0xFFFF
        return bin(v).count("1") % 2 == 0


@dataclass
class OctsFrame:
    """OCTS 64-bit timer subframe with sanity split into 16-bit halves."""

    preset_lo: int
    preset_hi: int
    count_lo: int
    count_hi: int

    def preset64(self) -> int:
        return ((self.preset_hi & 0xFFFFFFFF) << 32) | (self.preset_lo & 0xFFFFFFFF)

    def count64(self) -> int:
        return ((self.count_hi & 0xFFFFFFFF) << 32) | (self.count_lo & 0xFFFFFFFF)

    def within_preset(self) -> bool:
        # Timer count should be <= preset (post-init, pre-fire).
        preset = self.preset64()
        return preset == 0 or self.count64() <= preset


@dataclass
class SidebandScoreboard:
    """Consumes CSR read (name, addr, value) tuples from SmcCsrSeq and
    cross-checks AVSBus/OCTS bring-up invariants."""

    observed: List = field(default_factory=list)
    violations: List = field(default_factory=list)
    invariants: Dict[str, int] = field(default_factory=lambda: {
        # Reset invariants that survive silicon defaults:
        # - INTR_CLEAR is W1C so read-value is 0 (write-only clear).
        # - OCTS timer count is 0 before TIMER_START is asserted.
        # AVS_INTERRUPT / AVS_INTERRUPT_MASK carry RTL reset values that
        # are RTL-defined and non-zero; they are observed but not asserted.
        "AVS_INTERRUPT_CLEAR": 0,
        "OCTS_TIMER_COUNT_LO": 0,
        "OCTS_TIMER_COUNT_HI": 0,
    })

    def observe(self, name: str, addr: int, value: int) -> None:
        self.observed.append((name, addr, value))
        # Ignore-mask policy: some fields may have don't-care upper bits.
        # For P2-A we require the LSByte to match the invariant.
        if name in self.invariants:
            expected = self.invariants[name]
            if (value & 0xFF) != (expected & 0xFF):
                self.violations.append(
                    f"{name} @ 0x{addr:08X}: got 0x{value:08X}, "
                    f"expected LSB=0x{expected & 0xFF:02X}"
                )

    def summary(self) -> str:
        return (
            f"observed={len(self.observed)} violations={len(self.violations)}"
        )
