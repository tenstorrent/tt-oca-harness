# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""iJTAG SIB reference model of the DTP testbench.

Behind each iJTAG SIB the bench places one instrument stub (``tb_top``): a
scan register of a per-SIB width that captures its own update register, so
the SIB model predicts the chain layout, the capture stream, and the
instrument values a scan latches, alongside routing, security gating, and
the observable control signals. The SV-UVM twin is
``uvm/env/dtp_ijtag_sib_model.svh``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .dtp_dbg_disable import IJTAG_SIB_DISABLE

__all__ = [
    "IJTAG_CHAIN_LEN_MAX",
    "IJTAG_INSTRUMENT_WIDTHS",
    "IJTAG_OBSERVE_SCAN_WIDTH",
    "IJTAG_SIB_COUNT",
    "IJTAG_SIB_ORDER",
    "SCAN_MARKER_WIDTH",
    "DtpIjtagChainFlop",
    "DtpIjtagSibModel",
    "DtpIjtagSibState",
]

IJTAG_SIB_ORDER = ("dft_secure", "dft", "dfd")
IJTAG_SIB_COUNT = len(IJTAG_SIB_ORDER)
# Instrument stub widths behind each SIB (tb_top): every subset of open SIBs
# sums to a distinct chain length.
IJTAG_INSTRUMENT_WIDTHS = {
    "dft_secure": 4,
    "dft": 5,
    "dfd": 6,
}
IJTAG_CHAIN_LEN_MAX = IJTAG_SIB_COUNT + sum(IJTAG_INSTRUMENT_WIDTHS.values())
# A latency-measuring scan shifts a marker word ahead of the chain's maintain
# image; the marker's MSB is set, so the stream's highest set bit lands at
# chain_len + SCAN_MARKER_WIDTH - 1.
SCAN_MARKER_WIDTH = 16
IJTAG_OBSERVE_SCAN_WIDTH = 40


@dataclass(frozen=True)
class DtpIjtagSibState:
    """Predicted outcome of programming one SIB pattern under a disable mask."""

    requested: dict[str, int]
    effective: dict[str, int]
    gated: dict[str, int]
    chain_len: int


@dataclass(frozen=True)
class DtpIjtagChainFlop:
    """One flop of the SELECT_IJTAG scan chain in TDI-to-TDO order."""

    owner: str
    field: str
    bit: int = 0


class DtpIjtagSibModel:
    """Reference state of the three SIBs and the instrument stubs behind them.

    The SELECT_IJTAG data register is, TDI to TDO, one SIB flop per SIB with
    the SIB's instrument spliced TDO-side of its flop while the SIB is open.
    Scan registers shift MSB-first, so an instrument's MSB is TDI-nearest.
    A SIB's update register holds the sanctioned open bit through a gate:
    the gate masks the effective state to closed and blocks Update-DR, and
    the stored bit takes effect again when the gate clears. Test-Logic-Reset
    clears the SIB and instrument update registers. A scan's chain layout is
    the effective state before its Update-DR.
    """

    def __init__(self) -> None:
        self.stored = {name: 0 for name in IJTAG_SIB_ORDER}
        self.instruments = {name: 0 for name in IJTAG_SIB_ORDER}

    def reset(self) -> None:
        """Test-Logic-Reset: every SIB closed, every instrument register zero."""
        for name in IJTAG_SIB_ORDER:
            self.stored[name] = 0
            self.instruments[name] = 0

    @staticmethod
    def gates(dbg_disable: Mapping[str, int] | None = None) -> dict[str, int]:
        """Per-SIB gate state from the direct disables (1 = SIB gated)."""
        dbg = dict(dbg_disable or {})
        return {name: int(dbg.get(IJTAG_SIB_DISABLE[name], 0)) & 1 for name in IJTAG_SIB_ORDER}

    @staticmethod
    def pattern_dict(pattern: int) -> dict[str, int]:
        # Bits are shifted LSB-first through a serial chain. After a full update,
        # the first scanned bit is resident in the final SIB and the last scanned
        # bit is resident in the first SIB.
        return {
            name: (pattern >> (IJTAG_SIB_COUNT - 1 - idx)) & 0x1
            for idx, name in enumerate(IJTAG_SIB_ORDER)
        }

    def effective(self, dbg_disable: Mapping[str, int] | None = None) -> dict[str, int]:
        """Stored SIB state masked by the gates: the chain as it shifts."""
        gated = self.gates(dbg_disable)
        return {name: self.stored[name] & (gated[name] ^ 1) for name in IJTAG_SIB_ORDER}

    def state(self, pattern: int, dbg_disable: Mapping[str, int] | None = None) -> DtpIjtagSibState:
        """Outcome of programming ``pattern`` under ``dbg_disable``: a gated
        SIB reads closed whatever it stores, so the effective state and the
        chain length after Update-DR follow the request masked by the gates."""
        requested = self.pattern_dict(pattern)
        gated = self.gates(dbg_disable)
        effective = {name: requested[name] & (gated[name] ^ 1) for name in IJTAG_SIB_ORDER}
        chain_len = IJTAG_SIB_COUNT + sum(
            IJTAG_INSTRUMENT_WIDTHS[name] for name in IJTAG_SIB_ORDER if effective[name]
        )
        return DtpIjtagSibState(
            requested=requested, effective=effective, gated=gated, chain_len=chain_len
        )

    @staticmethod
    def pattern_value(bits: Mapping[str, int]) -> int:
        """Inverse of ``pattern_dict``: the scan value that stores ``bits``."""
        return sum(
            (bits[name] & 0x1) << (IJTAG_SIB_COUNT - 1 - idx)
            for idx, name in enumerate(IJTAG_SIB_ORDER)
        )

    def chain_layout(self, dbg_disable: Mapping[str, int] | None = None) -> list[DtpIjtagChainFlop]:
        """Chain flops in TDI-to-TDO order for the current effective state."""
        effective = self.effective(dbg_disable)
        flops: list[DtpIjtagChainFlop] = []
        for name in IJTAG_SIB_ORDER:
            flops.append(DtpIjtagChainFlop(name, "sib"))
            if effective[name]:
                width = IJTAG_INSTRUMENT_WIDTHS[name]
                flops.extend(
                    DtpIjtagChainFlop(name, "inst", bit) for bit in range(width - 1, -1, -1)
                )
        return flops

    def chain_len(self, dbg_disable: Mapping[str, int] | None = None) -> int:
        return len(self.chain_layout(dbg_disable))

    def compose_scan(
        self,
        width: int,
        *,
        pattern: int | None = None,
        inst_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
    ) -> int:
        """SELECT_IJTAG scan value that writes ``pattern`` into the SIBs and
        ``inst_values`` into the open instruments through the current chain;
        unspecified fields keep their stored values (a maintain scan)."""
        layout = self.chain_layout(dbg_disable)
        if width < len(layout):
            raise ValueError(f"scan width {width} < chain length {len(layout)}")
        sib_bits = self.pattern_dict(pattern) if pattern is not None else self.stored
        values = dict(inst_values or {})
        value = 0
        for depth, flop in enumerate(layout):
            if flop.field == "sib":
                bit = sib_bits[flop.owner]
            else:
                bit = (values.get(flop.owner, self.instruments[flop.owner]) >> flop.bit) & 1
            if bit:
                value |= 1 << (width - 1 - depth)
        return value

    def apply_scan(
        self,
        *,
        pattern: int | None = None,
        inst_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
    ) -> None:
        """Commit a composed scan's Update-DR: an ungated SIB stores its
        requested bit; an instrument that was in the chain latches its
        segment; a gated SIB and its instrument ignore the update."""
        gated = self.gates(dbg_disable)
        in_chain = self.effective(dbg_disable)
        sib_bits = self.pattern_dict(pattern) if pattern is not None else dict(self.stored)
        for name in IJTAG_SIB_ORDER:
            if in_chain[name] and inst_values is not None and name in inst_values:
                mask = (1 << IJTAG_INSTRUMENT_WIDTHS[name]) - 1
                self.instruments[name] = int(inst_values[name]) & mask
            if not gated[name]:
                self.stored[name] = sib_bits[name]

    def apply_raw_scan(
        self, value: int, width: int, dbg_disable: Mapping[str, int] | None = None
    ) -> None:
        """Commit the Update-DR of a ``width``-bit scan of ``value`` through the current chain.

        Shift-DR moves the Capture-DR contents ``width`` flops toward TDO while the
        value enters at TDI, so a scan narrower than the chain leaves the deeper
        flops holding what shallower flops captured; a gated SIB and its
        instrument ignore the update.
        """
        layout = self.chain_layout(dbg_disable)
        capture, length = self.expected_capture(dbg_disable)
        gated = self.gates(dbg_disable)
        sib_bits = dict(self.stored)
        instruments: dict[str, int] = {}
        for depth, flop in enumerate(layout):
            if depth < width:
                bit = (value >> (width - 1 - depth)) & 1
            else:
                bit = (capture >> (length - 1 - (depth - width))) & 1
            if flop.field == "sib":
                sib_bits[flop.owner] = bit
            else:
                instruments[flop.owner] = instruments.get(flop.owner, 0) | (bit << flop.bit)
        for name in IJTAG_SIB_ORDER:
            if name in instruments:
                self.instruments[name] = instruments[name]
            if not gated[name]:
                self.stored[name] = sib_bits[name]

    def expected_scan_tdo(
        self, value: int, width: int, dbg_disable: Mapping[str, int] | None = None
    ) -> int:
        """TDO of a ``width``-bit scan, LSB first: the chain's capture bits nearest TDO,
        then the scanned value one TCK per chain flop behind TDI."""
        capture, length = self.expected_capture(dbg_disable)
        return ((value << length) | capture) & ((1 << width) - 1)

    def expected_capture(self, dbg_disable: Mapping[str, int] | None = None) -> tuple[int, int]:
        """(expected, chain_len) of a scan's captured TDO bits: captured bit j
        is the flop at depth chain_len-1-j; a SIB captures its effective
        state and an instrument its stored register."""
        layout = self.chain_layout(dbg_disable)
        effective = self.effective(dbg_disable)
        length = len(layout)
        expected = 0
        for depth, flop in enumerate(layout):
            if flop.field == "sib":
                bit = effective[flop.owner]
            else:
                bit = (self.instruments[flop.owner] >> flop.bit) & 1
            if bit:
                expected |= 1 << (length - 1 - depth)
        return expected, length
