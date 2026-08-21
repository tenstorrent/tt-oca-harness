# SPDX-License-Identifier: Apache-2.0
"""DTP-local iJTAG and STAP/3DCR reference models.

These models intentionally describe the public OSS DTP testbench shape. The
external instrument scan inputs are looped back from their scan outputs, so the
models check SIB/STAP routing, security gating, and observable control signals
without pretending there is a full downstream instrument VIP behind the loopback.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from env.dtp_dbg_disable import IJTAG_SIB_DISABLE, STAP_DISABLE

IJTAG_SIB_ORDER = ("dft_secure", "dft", "dfd")
IJTAG_SIB_COUNT = len(IJTAG_SIB_ORDER)
IJTAG_INSTRUMENT_WIDTHS = {
    # The OSS TB ties scan_in <- scan_out for each external iJTAG instrument.
    "dft_secure": 0,
    "dft": 0,
    "dfd": 0,
}

STAP_ORDER = ("io", "smc", "sep", "extra0")
STAP_SIB_COUNT = len(STAP_ORDER)
PTAP_3DCR_WIDTH = 2
STAP_3DCR_WIDTH = 3


@dataclass(frozen=True)
class IjtagSibState:
    requested: dict[str, int]
    effective: dict[str, int]
    gated: dict[str, int]
    chain_len: int


class DtpIjtagSibModel:
    """Predict iJTAG SIB state for the DTP public loopback environment."""

    @staticmethod
    def gates(dbg_disable: Mapping[str, int] | None = None) -> dict[str, int]:
        """Per-SIB gate state from the direct disables (1 = SIB gated)."""
        dbg = dict(dbg_disable or {})
        return {
            name: int(dbg.get(IJTAG_SIB_DISABLE[name], 0)) & 1
            for name in IJTAG_SIB_ORDER
        }

    @staticmethod
    def pattern_dict(pattern: int) -> dict[str, int]:
        # Bits are shifted LSB-first through a serial chain. After a full update,
        # the first scanned bit is resident in the final SIB and the last scanned
        # bit is resident in the first SIB.
        return {
            name: (pattern >> (IJTAG_SIB_COUNT - 1 - idx)) & 0x1
            for idx, name in enumerate(IJTAG_SIB_ORDER)
        }

    def state(self, pattern: int, dbg_disable: Mapping[str, int] | None = None) -> IjtagSibState:
        requested = self.pattern_dict(pattern)
        gated = self.gates(dbg_disable)
        effective = {name: requested[name] & (gated[name] ^ 1) for name in IJTAG_SIB_ORDER}
        chain_len = IJTAG_SIB_COUNT + sum(
            IJTAG_INSTRUMENT_WIDTHS[name] for name in IJTAG_SIB_ORDER if effective[name]
        )
        return IjtagSibState(requested=requested, effective=effective, gated=gated, chain_len=chain_len)

    @staticmethod
    def expected_tdo(pattern: int, width: int) -> int:
        # With zero-width looped instruments, the observable DR stream is the SIB chain itself.
        return pattern & ((1 << width) - 1)


@dataclass
class Stap3dcrState:
    config_hold: int = 0
    stap_sel: int = 0
    tms_hold: int = 0

    @classmethod
    def from_value(cls, value: int) -> "Stap3dcrState":
        # STAP 3DCR scan packing is LSB-first: config_hold, stap_sel, tms_hold.
        return cls(
            config_hold=value & 0x1,
            stap_sel=(value >> 1) & 0x1,
            tms_hold=(value >> 2) & 0x1,
        )

    def value(self) -> int:
        return (self.config_hold & 0x1) | ((self.stap_sel & 0x1) << 1) | ((self.tms_hold & 0x1) << 2)


class DtpStap3dcrModel:
    """Reference state for the PTAP 3DCR and downstream STAP 3DCRs.

    The TAP_3DCR data register is the 2-bit PTAP 3DCR followed serially by
    the STAP configuration chain (IEEE 1838 Section 5.4): one SIB flop per
    STAP, with the STAP's 3-bit 3DCR spliced TDI-side of its SIB while the
    SIB is open. Scan registers shift MSB-first (scan-in enters the MSB), so
    within each register the MSB field is TDI-nearest. A selected STAP
    splices its downstream loopback into the chain; ports with a TDI lockup
    latch (the I/O STAP) add one full extra flop while selected.
    """

    # Extra full-cycle flops a STAP's selected splice inserts into the chain.
    SPLICE_EXTRA = {"io": 1, "smc": 0, "sep": 0, "extra0": 0}

    def __init__(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        self.staps = {name: Stap3dcrState() for name in STAP_ORDER}
        self.sib_en = {name: 0 for name in STAP_ORDER}

    # --- composed-chain scans -------------------------------------------------
    def chain_layout(self, dbg_disable: Mapping[str, int] | None = None) -> list[tuple[str, str]]:
        """(owner, field) per chain flop in TDI-to-TDO order, current state."""
        gates = self.gates(dbg_disable)
        fields: list[tuple[str, str]] = [("ptap", "stap_sel"), ("ptap", "config_hold")]
        for name in STAP_ORDER:
            if self.staps[name].stap_sel and not gates[name]:
                fields.extend((name, "splice") for _ in range(self.SPLICE_EXTRA[name]))
            if self.sib_en[name]:
                fields.extend(((name, "tms_hold"), (name, "stap_sel"), (name, "config_hold")))
            fields.append((name, "sib"))
        return fields

    def _field_value(
        self,
        owner: str,
        field: str,
        *,
        ptap_select: int,
        ptap_config_hold: int,
        sib_en: dict[str, int],
        payloads: dict[str, Stap3dcrState],
    ) -> int:
        if owner == "ptap":
            return ptap_select if field == "stap_sel" else ptap_config_hold
        if field == "sib":
            return sib_en.get(owner, self.sib_en[owner])
        if field == "splice":
            return 0
        payload = payloads.get(owner, self.staps[owner])
        return getattr(payload, field)

    def compose_scan(
        self,
        width: int,
        *,
        ptap_select: int | None = None,
        ptap_config_hold: int | None = None,
        sib_en: dict[str, int] | None = None,
        payloads: dict[str, Stap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
    ) -> int:
        """Scan value that writes the given end-state through the current chain.

        Unspecified fields keep their current stored value. The layout is the
        chain as it exists during the scan (updates land at Update-DR).
        """
        layout = self.chain_layout(dbg_disable)
        if width < len(layout):
            raise ValueError(f"scan width {width} < chain length {len(layout)}")
        args = {
            "ptap_select": self.ptap_select if ptap_select is None else ptap_select,
            "ptap_config_hold": self.ptap_config_hold if ptap_config_hold is None else ptap_config_hold,
            "sib_en": dict(sib_en or {}),
            "payloads": dict(payloads or {}),
        }
        value = 0
        for depth, (owner, field) in enumerate(layout):
            if self._field_value(owner, field, **args):
                value |= 1 << (width - 1 - depth)
        return value

    def apply_scan(
        self,
        *,
        ptap_select: int | None = None,
        ptap_config_hold: int | None = None,
        sib_en: dict[str, int] | None = None,
        payloads: dict[str, Stap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
    ) -> None:
        """Commit a composed scan's Update-DR: a disabled STAP ignores its
        3DCR payload write; SIB bits and the PTAP 3DCR always update."""
        gates = self.gates(dbg_disable)
        # The payload flops are only in the chain if the SIB was open during
        # the scan, i.e. per the pre-update state.
        in_chain = dict(self.sib_en)
        if ptap_select is not None:
            self.ptap_select = ptap_select & 1
        if ptap_config_hold is not None:
            self.ptap_config_hold = ptap_config_hold & 1
        for name, value in (sib_en or {}).items():
            self.sib_en[name] = int(value) & 1
        for name, payload in (payloads or {}).items():
            if not gates[name] and in_chain[name]:
                self.staps[name] = Stap3dcrState(
                    payload.config_hold & 1, payload.stap_sel & 1, payload.tms_hold & 1
                )

    def flush_scan(self) -> None:
        """Commit an all-zero over-length scan: every in-chain field cleared."""
        self.ptap_select = 0
        self.ptap_config_hold = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            self.staps[name] = Stap3dcrState()

    def expected_capture(self, dbg_disable: Mapping[str, int] | None = None) -> tuple[int, int, int]:
        """(expected, care_mask, chain_len) for a readback with PTAP select=1.

        Captured bit j of the TDO stream is the flop at depth chain_len-1-j;
        splice flops capture unknown data and are masked out.
        """
        gates = self.gates(dbg_disable)
        layout = self.chain_layout(dbg_disable)
        length = len(layout)
        expected = 0
        care = 0
        for depth, (owner, field) in enumerate(layout):
            bit = length - 1 - depth
            if field == "splice":
                continue
            care |= 1 << bit
            value = self._field_value(owner, field, ptap_select=self.ptap_select,
                                      ptap_config_hold=self.ptap_config_hold,
                                      sib_en={}, payloads={})
            # A STAP captures its masked stap_sel: 0 while its disable is
            # asserted, even though the stored bit survives the gate.
            if owner != "ptap" and field == "stap_sel" and gates[owner]:
                value = 0
            if value:
                expected |= 1 << bit
        return expected, care, length

    @staticmethod
    def gates(dbg_disable: Mapping[str, int] | None = None) -> dict[str, int]:
        """Per-STAP gate state from the direct disables (1 = STAP gated)."""
        dbg = dict(dbg_disable or {})
        return {
            name: int(dbg.get(field, 0)) & 1 for name, field in STAP_DISABLE.items()
        }

    @staticmethod
    def ptap_3dcr_value(*, config_hold: int, select: int) -> int:
        # PTAP 3DCR is LSB-first: config_hold then stap_select.
        return (config_hold & 0x1) | ((select & 0x1) << 1)

    @staticmethod
    def stap_3dcr_value(*, config_hold: int, stap_sel: int, tms_hold: int) -> int:
        return Stap3dcrState(config_hold, stap_sel, tms_hold).value()

    def update_ptap(self, value: int) -> None:
        self.ptap_config_hold = value & 0x1
        self.ptap_select = (value >> 1) & 0x1

    def update_stap(self, name: str, value: int, *, gated: int = 0) -> None:
        if gated:
            # RTL blocks updates while security_disable_i is asserted.
            return
        self.staps[name] = Stap3dcrState.from_value(value)

    def tlr(self) -> None:
        # SIB bits have no config_hold protection and clear in Test-Logic-Reset;
        # a 3DCR survives when its config_hold is set.
        if not self.ptap_config_hold:
            self.ptap_select = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            if not self.staps[name].config_hold:
                self.staps[name].stap_sel = 0
                self.staps[name].tms_hold = 0

    def trst(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            self.staps[name] = Stap3dcrState()

