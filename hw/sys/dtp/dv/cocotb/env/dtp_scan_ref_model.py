# SPDX-License-Identifier: Apache-2.0
"""DTP-local iJTAG and STAP/3DCR reference models.

These models intentionally describe the public OSS DTP testbench shape. The
external instrument scan inputs are looped back from their scan outputs, so the
models check SIB/STAP routing, security gating, and observable control signals
without pretending there is a full downstream instrument VIP behind the loopback.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    def gates(*, soc_debug: int = 1, ap_debug: int = 1, sep_debug: int = 1, fuse_test: int = 1, **_) -> dict[str, int]:
        return {
            "dft_secure": int(not bool(fuse_test and sep_debug and soc_debug and ap_debug)),
            "dft": int(not bool(soc_debug and ap_debug)),
            "dfd": int(not bool(ap_debug)),
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

    def state(self, pattern: int, **feat_ctrl: int) -> IjtagSibState:
        requested = self.pattern_dict(pattern)
        gated = self.gates(**feat_ctrl)
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
    """Reference state for the PTAP 3DCR and downstream STAP 3DCRs."""

    def __init__(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        self.staps = {name: Stap3dcrState() for name in STAP_ORDER}

    @staticmethod
    def gates(*, sip_debug: int = 1, soc_debug: int = 1, ap_debug: int = 1, sep_debug: int = 1, **_) -> dict[str, int]:
        return {
            "io": int(not bool(sip_debug)),
            "smc": int(not bool(soc_debug and ap_debug)),
            "sep": int(not bool(sep_debug and soc_debug and ap_debug)),
            "extra0": int(not bool(ap_debug)),
            "stap_host": int(not bool(ap_debug)),
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
        if not self.ptap_config_hold:
            self.ptap_select = 0
        for state in self.staps.values():
            if not state.config_hold:
                state.stap_sel = 0
                state.tms_hold = 0

    def trst(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        for name in STAP_ORDER:
            self.staps[name] = Stap3dcrState()

    def effective_stap_sel(self, name: str, **feat_ctrl: int) -> int:
        return self.staps[name].stap_sel & (self.gates(**feat_ctrl)[name] ^ 1)

    def parked_tms(self, name: str, **feat_ctrl: int) -> int:
        return self.staps[name].tms_hold if not self.effective_stap_sel(name, **feat_ctrl) else 0

