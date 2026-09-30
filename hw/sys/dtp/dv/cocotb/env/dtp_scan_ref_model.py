# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP-local iJTAG and STAP/3DCR reference models.

These models describe the public OSS DTP testbench shape. Behind each iJTAG
SIB the bench places one instrument stub (``tb_top``): a scan register of a
per-SIB width that captures its own update register, so the SIB model
predicts the chain layout, the capture stream, and the instrument values a
scan latches, alongside routing, security gating, and the observable control
signals.

The STAP/3DCR model covers the IEEE 1838 configuration chain and, per STAP
host port, an optionally attached downstream IEEE 1149.1 TAP (the
``ocah_jtag_vip`` slave device ``tb_top`` splices behind the port). The model
predicts the downstream contribution independently from the VIP's device
engine: its IR and selected data register are chain segments whose captures
are the IDCODE, the value the model latched, or the IEEE 1149.1 IR capture.
It also covers the host segment ``tb_top`` can place behind the extended STAP
host scan interface, the chain return while ``stap_host`` is enabled, and the
chain a data scan passes through under ZERO_LENGTH_BYPASS or BYPASS while the
PTAP 3DCR select is set.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from env.dtp_dbg_disable import IJTAG_SIB_DISABLE, STAP_DISABLE
from env.dtp_types import DTP_IR_WIDTH

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

STAP_ORDER = ("io", "smc", "sep", "extra0")
STAP_SIB_COUNT = len(STAP_ORDER)
PTAP_3DCR_WIDTH = 2
STAP_3DCR_WIDTH = 3
# Host segment behind the extended STAP host scan interface (tb_top): a scan
# register that captures its own update register.
STAP_HOST_SEGMENT_WIDTH = 7
# IEEE 1149.1: a TAP's IR capture presents 01 in its two LSBs.
STAP_DS_IR_CAPTURE = 0b01


@dataclass(frozen=True)
class IjtagSibState:
    """Predicted outcome of programming one SIB pattern under a disable mask."""

    requested: dict[str, int]
    effective: dict[str, int]
    gated: dict[str, int]
    chain_len: int


@dataclass(frozen=True)
class IjtagChainFlop:
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

    def state(self, pattern: int, dbg_disable: Mapping[str, int] | None = None) -> IjtagSibState:
        """Outcome of programming ``pattern`` under ``dbg_disable``: a gated
        SIB reads closed whatever it stores, so the effective state and the
        chain length after Update-DR follow the request masked by the gates."""
        requested = self.pattern_dict(pattern)
        gated = self.gates(dbg_disable)
        effective = {name: requested[name] & (gated[name] ^ 1) for name in IJTAG_SIB_ORDER}
        chain_len = IJTAG_SIB_COUNT + sum(
            IJTAG_INSTRUMENT_WIDTHS[name] for name in IJTAG_SIB_ORDER if effective[name]
        )
        return IjtagSibState(
            requested=requested, effective=effective, gated=gated, chain_len=chain_len
        )

    @staticmethod
    def pattern_value(bits: Mapping[str, int]) -> int:
        """Inverse of ``pattern_dict``: the scan value that stores ``bits``."""
        return sum(
            (bits[name] & 0x1) << (IJTAG_SIB_COUNT - 1 - idx)
            for idx, name in enumerate(IJTAG_SIB_ORDER)
        )

    def chain_layout(self, dbg_disable: Mapping[str, int] | None = None) -> list[IjtagChainFlop]:
        """Chain flops in TDI-to-TDO order for the current effective state."""
        effective = self.effective(dbg_disable)
        flops: list[IjtagChainFlop] = []
        for name in IJTAG_SIB_ORDER:
            flops.append(IjtagChainFlop(name, "sib"))
            if effective[name]:
                width = IJTAG_INSTRUMENT_WIDTHS[name]
                flops.extend(IjtagChainFlop(name, "inst", bit) for bit in range(width - 1, -1, -1))
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
        return (
            (self.config_hold & 0x1) | ((self.stap_sel & 0x1) << 1) | ((self.tms_hold & 0x1) << 2)
        )


@dataclass(frozen=True)
class StapDownstreamReg:
    """One data register of a downstream TAP."""

    name: str
    opcode: int
    width: int
    writable: bool


@dataclass
class StapDownstream:
    """Tracked state of the downstream TAP spliced behind one STAP host port.

    Seeded from the attached device's map (IR width, IDCODE, registers); the
    behavior is predicted here from IEEE 1149.1, not read back from the VIP
    engine: Test-Logic-Reset selects IDCODE, an unknown instruction selects
    the one-bit BYPASS, Capture-IR presents ``01`` in the IR LSBs, and a
    writable register latches the shifted-in value on Update-DR.
    """

    ir_width: int
    idcode: int
    idcode_opcode: int
    regs: dict[int, StapDownstreamReg]
    active_ir: int = 0
    values: dict[str, int] = field(default_factory=dict)

    @classmethod
    def from_device(cls, device) -> "StapDownstream":
        """Build from an ``OcahJtagDevice``-shaped map (``ir_width``, ``idcode``, ``regs``)."""
        regs = {
            int(reg.opcode): StapDownstreamReg(
                reg.name, int(reg.opcode), int(reg.width), bool(reg.write)
            )
            for reg in device.regs.values()
        }
        idcode_reg = next((r for r in regs.values() if r.name == "IDCODE"), None)
        if idcode_reg is None:
            raise ValueError(f"downstream device {device.name!r} has no IDCODE register")
        bypass = (1 << int(device.ir_width)) - 1
        regs.setdefault(bypass, StapDownstreamReg("BYPASS", bypass, 1, False))
        ds = cls(
            ir_width=int(device.ir_width),
            idcode=int(device.idcode),
            idcode_opcode=idcode_reg.opcode,
            regs=regs,
            values={r.name: 0 for r in regs.values() if r.writable},
        )
        ds.reset_instruction()
        return ds

    @property
    def bypass_opcode(self) -> int:
        return (1 << self.ir_width) - 1

    def opcode_of(self, name: str) -> int:
        for reg in self.regs.values():
            if reg.name == name:
                return reg.opcode
        raise KeyError(f"downstream register {name!r} unknown; known: {sorted(self.values)}")

    def reg(self, name: str) -> StapDownstreamReg:
        return self.regs[self.opcode_of(name)]

    def selected(self) -> StapDownstreamReg | None:
        """The register the active instruction selects (None = BYPASS behavior)."""
        reg = self.regs.get(self.active_ir & self.bypass_opcode)
        if reg is None or reg.name == "BYPASS":
            return None
        return reg

    def selected_width(self, scan_kind: str = "dr") -> int:
        """Chain segment width the downstream contributes to a composed scan."""
        if scan_kind == "ir":
            return self.ir_width
        reg = self.selected()
        return reg.width if reg is not None and reg.width > 0 else 1

    def shift_default(self, scan_kind: str = "dr") -> int:
        """Segment value a maintain scan shifts in: the stored value of a
        writable register (re-latched unchanged), the active IR for an IR
        scan, zero otherwise."""
        if scan_kind == "ir":
            return self.active_ir
        reg = self.selected()
        if reg is not None and reg.writable:
            return self.values[reg.name]
        return 0

    def capture(self, scan_kind: str = "dr") -> int:
        """Segment value the downstream captures at Capture-IR / Capture-DR."""
        if scan_kind == "ir":
            return STAP_DS_IR_CAPTURE & ((1 << self.ir_width) - 1)
        reg = self.selected()
        if reg is None:
            return 0
        if reg.name == "IDCODE":
            return self.idcode
        return self.values.get(reg.name, 0)

    def latch(self, value: int) -> None:
        """Update-DR: a writable selected register takes the shifted value."""
        reg = self.selected()
        if reg is not None and reg.writable:
            self.values[reg.name] = int(value) & ((1 << reg.width) - 1)

    def update_ir(self, opcode: int) -> None:
        self.active_ir = int(opcode) & self.bypass_opcode

    def reset_instruction(self) -> None:
        """Test-Logic-Reset (TRST, or five parked TMS=1 cycles) selects IDCODE."""
        self.active_ir = self.idcode_opcode


@dataclass(frozen=True)
class ChainFlop:
    """One flop of the composed scan chain in TDI-to-TDO order."""

    owner: str
    field: str
    bit: int = 0


class DtpStap3dcrModel:
    """Reference state for the PTAP 3DCR, the STAP 3DCRs, and downstream TAPs.

    The TAP_3DCR data register is the 2-bit PTAP 3DCR followed serially by
    the STAP configuration chain (IEEE 1838 Section 5.4): one SIB flop per
    STAP, with the STAP's 3-bit 3DCR spliced TDI-side of its SIB while the
    SIB is open. Scan registers shift MSB-first (scan-in enters the MSB), so
    within each register the MSB field is TDI-nearest. A selected STAP
    splices its host port into the chain: the downstream TAP's IR (IR scans)
    or selected data register (DR scans) when a device is attached, and one
    extra full-cycle flop on ports with a TDI lockup latch (the I/O STAP).
    An attached host segment follows the last STAP, at the TDO end of every
    scan, while ``stap_host`` is enabled; with ``stap_host`` disabled the
    last STAP's scan-out is the chain return and the segment holds its value.

    The PTAP forwards its scan controls to the STAP chain on every IR and DR
    scan and, with the PTAP 3DCR select set, routes the instruction
    register's scan-out into the chain: an IR scan is then the 6-bit PTAP IR
    followed by the STAP chain (the PTAP 3DCR itself is a data register and
    stays out of IR scans), and Update-IR commits SIB/3DCR fields and the
    downstream IRs exactly as Update-DR does. Every scan issued while a STAP
    is selected must therefore be composed over the full network.

    A data scan under any other PTAP instruction runs through the STAP chain
    as well while the PTAP 3DCR select is set, and its Update-DR commits the
    chain fields without reaching the PTAP 3DCR. Under ZERO_LENGTH_BYPASS TDI
    enters the chain directly, so the scan is the STAP chain alone
    (``"zlb"``); under BYPASS the one-bit bypass register, which captures 0,
    precedes the chain (``"bypass"``).
    """

    # Extra full-cycle flops a STAP's selected splice inserts into the chain.
    SPLICE_EXTRA = {"io": 1, "smc": 0, "sep": 0, "extra0": 0}

    def __init__(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        self.staps = {name: Stap3dcrState() for name in STAP_ORDER}
        self.sib_en = {name: 0 for name in STAP_ORDER}
        self.downstream: dict[str, StapDownstream] = {}
        self.host_segment_attached = False
        # The host segment's update register; every capture presents it.
        self.host_segment = 0

    # --- extended STAP host segment ---------------------------------------------
    def attach_host_segment(self) -> None:
        """Place the bench's host segment behind the extended STAP host scan interface."""
        self.host_segment_attached = True
        self.host_segment = 0

    def host_segment_in_chain(self, dbg_disable: Mapping[str, int] | None = None) -> bool:
        """True while the host segment is the chain return: attached, ``stap_host`` enabled."""
        return self.host_segment_attached and not self.gates(dbg_disable)["stap_host"]

    # --- downstream TAPs ------------------------------------------------------
    def attach(self, name: str, device) -> StapDownstream:
        """Seed the downstream TAP behind STAP ``name`` from its device map."""
        if name not in STAP_ORDER:
            raise ValueError(f"unknown STAP {name!r}")
        ds = StapDownstream.from_device(device)
        self.downstream[name] = ds
        return ds

    def attached(self, name: str) -> bool:
        return name in self.downstream

    def spliced(self, name: str, dbg_disable: Mapping[str, int] | None = None) -> bool:
        """True while STAP ``name`` is selected and ungated (its host port is in the chain)."""
        return bool(self.staps[name].stap_sel) and not self.gates(dbg_disable)[name]

    def spliced_downstream(self, dbg_disable: Mapping[str, int] | None = None) -> list[str]:
        """Attached STAPs whose downstream TAP is currently in the chain."""
        return [
            name for name in STAP_ORDER if self.attached(name) and self.spliced(name, dbg_disable)
        ]

    def _park_downstream(self, gates: Mapping[str, int]) -> None:
        """A deselected or gated STAP parks its host TMS at the stored
        tms_hold: parked high, the downstream TAP walks into Test-Logic-Reset
        (IDCODE selected) within five TCKs; parked low it idles in
        Run-Test/Idle and keeps its instruction."""
        for name, ds in self.downstream.items():
            state = self.staps[name]
            if (gates[name] or not state.stap_sel) and state.tms_hold:
                ds.reset_instruction()

    # --- composed-chain scans -------------------------------------------------
    def chain_layout(
        self, dbg_disable: Mapping[str, int] | None = None, scan_kind: str = "dr"
    ) -> list[ChainFlop]:
        """Chain flops in TDI-to-TDO order for the current state.

        ``scan_kind`` is ``"dr"`` (TAP_3DCR data scan: PTAP 3DCR first),
        ``"ir"`` (instruction scan: PTAP IR first, PTAP 3DCR absent),
        ``"zlb"`` (data scan under ZERO_LENGTH_BYPASS: no PTAP flop), or
        ``"bypass"`` (data scan under BYPASS: the PTAP bypass register first).
        """
        gates = self.gates(dbg_disable)
        flops: list[ChainFlop] = []
        if scan_kind == "ir":
            flops.extend(ChainFlop("ptap", "ir", bit) for bit in range(DTP_IR_WIDTH - 1, -1, -1))
        elif scan_kind == "dr":
            flops.extend((ChainFlop("ptap", "stap_sel"), ChainFlop("ptap", "config_hold")))
        elif scan_kind == "bypass":
            flops.append(ChainFlop("ptap", "bypass"))
        elif scan_kind != "zlb":
            raise ValueError(f"unknown scan kind {scan_kind!r}")
        for name in STAP_ORDER:
            if self.staps[name].stap_sel and not gates[name]:
                if self.attached(name):
                    width = self.downstream[name].selected_width(scan_kind)
                    flops.extend(ChainFlop(name, "ds", bit) for bit in range(width - 1, -1, -1))
                flops.extend(ChainFlop(name, "splice") for _ in range(self.SPLICE_EXTRA[name]))
            if self.sib_en[name]:
                flops.extend(
                    (
                        ChainFlop(name, "tms_hold"),
                        ChainFlop(name, "stap_sel"),
                        ChainFlop(name, "config_hold"),
                    )
                )
            flops.append(ChainFlop(name, "sib"))
        if self.host_segment_in_chain(dbg_disable):
            flops.extend(
                ChainFlop("stap_host", "segment", bit)
                for bit in range(STAP_HOST_SEGMENT_WIDTH - 1, -1, -1)
            )
        return flops

    def _field_value(
        self,
        flop: ChainFlop,
        *,
        scan_kind: str,
        ptap_select: int,
        ptap_config_hold: int,
        ptap_instr: int,
        sib_en: Mapping[str, int],
        payloads: Mapping[str, Stap3dcrState],
        ds_values: Mapping[str, int],
        host_segment: int | None,
    ) -> int:
        if flop.owner == "ptap":
            if flop.field == "ir":
                return (ptap_instr >> flop.bit) & 1
            if flop.field == "bypass":
                return 0
            return ptap_select if flop.field == "stap_sel" else ptap_config_hold
        if flop.field == "segment":
            value = self.host_segment if host_segment is None else host_segment
            return (int(value) >> flop.bit) & 1
        if flop.field == "sib":
            return sib_en.get(flop.owner, self.sib_en[flop.owner])
        if flop.field == "splice":
            return 0
        if flop.field == "ds":
            ds = self.downstream[flop.owner]
            value = ds_values.get(flop.owner, ds.shift_default(scan_kind))
            return (int(value) >> flop.bit) & 1
        payload = payloads.get(flop.owner, self.staps[flop.owner])
        return getattr(payload, flop.field)

    def _compose(self, layout: list[ChainFlop], width: int, **args) -> int:
        if width < len(layout):
            raise ValueError(f"scan width {width} < chain length {len(layout)}")
        value = 0
        for depth, flop in enumerate(layout):
            if self._field_value(flop, **args):
                value |= 1 << (width - 1 - depth)
        return value

    def compose_scan(
        self,
        width: int,
        *,
        ptap_select: int | None = None,
        ptap_config_hold: int | None = None,
        sib_en: Mapping[str, int] | None = None,
        payloads: Mapping[str, Stap3dcrState] | None = None,
        ds_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
        scan_kind: str = "dr",
    ) -> int:
        """Data scan value that writes the given end-state through the
        current chain: a TAP_3DCR scan, or with ``scan_kind`` ``"zlb"`` or
        ``"bypass"`` a scan under that PTAP instruction, whose layout holds
        no PTAP 3DCR field. Unspecified fields keep their stored values; a
        spliced downstream register re-latches its stored value unless
        ``ds_values`` names a new one, and the host segment its value unless
        ``host_segment`` does. The layout is the chain as it exists during
        the scan (updates land at Update-DR)."""
        return self._compose(
            self.chain_layout(dbg_disable, scan_kind),
            width,
            scan_kind=scan_kind,
            ptap_select=self.ptap_select if ptap_select is None else ptap_select,
            ptap_config_hold=self.ptap_config_hold
            if ptap_config_hold is None
            else ptap_config_hold,
            ptap_instr=0,
            sib_en=dict(sib_en or {}),
            payloads=dict(payloads or {}),
            ds_values=dict(ds_values or {}),
            host_segment=host_segment,
        )

    def compose_ir_scan(
        self,
        width: int,
        ptap_instr: int,
        *,
        ds_ir: Mapping[str, int] | None = None,
        sib_en: Mapping[str, int] | None = None,
        payloads: Mapping[str, Stap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> int:
        """Instruction scan value over the full network: the PTAP IR segment
        first, then the STAP chain with each spliced downstream TAP's IR
        (``ds_ir`` names new instructions; others keep the active one)."""
        return self._compose(
            self.chain_layout(dbg_disable, "ir"),
            width,
            scan_kind="ir",
            ptap_select=self.ptap_select,
            ptap_config_hold=self.ptap_config_hold,
            ptap_instr=int(ptap_instr),
            sib_en=dict(sib_en or {}),
            payloads=dict(payloads or {}),
            ds_values=dict(ds_ir or {}),
            host_segment=host_segment,
        )

    def _apply_chain_update(
        self,
        *,
        gates: Mapping[str, int],
        in_chain: Mapping[str, int],
        sib_en: Mapping[str, int] | None,
        payloads: Mapping[str, Stap3dcrState] | None,
    ) -> None:
        """Update-x for the STAP fields: a gated STAP ignores its 3DCR payload
        write; SIB bits always update; payload flops were in the chain only if
        the SIB was open during the scan (pre-update state)."""
        for name, value in (sib_en or {}).items():
            self.sib_en[name] = int(value) & 1
        for name, payload in (payloads or {}).items():
            if not gates[name] and in_chain[name]:
                self.staps[name] = Stap3dcrState(
                    payload.config_hold & 1, payload.stap_sel & 1, payload.tms_hold & 1
                )

    def _latch_host_segment(self, in_chain: bool, host_segment: int | None) -> None:
        """Update-x for the host segment: a new value lands only when the
        segment was in the chain during the scan."""
        if in_chain and host_segment is not None:
            self.host_segment = int(host_segment) & ((1 << STAP_HOST_SEGMENT_WIDTH) - 1)

    def apply_scan(
        self,
        *,
        ptap_select: int | None = None,
        ptap_config_hold: int | None = None,
        sib_en: Mapping[str, int] | None = None,
        payloads: Mapping[str, Stap3dcrState] | None = None,
        ds_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> None:
        """Commit a composed data scan's Update-DR: a TAP_3DCR scan updates
        the PTAP 3DCR, and a scan under another instruction leaves
        ``ptap_select`` and ``ptap_config_hold`` None and the PTAP 3DCR as
        it is; SIB/3DCR fields per the gating rules; a spliced downstream
        TAP latches its (writable) selected register, and the host segment
        its value; deselected or gated ports park their downstream TAP."""
        gates = self.gates(dbg_disable)
        in_chain = dict(self.sib_en)
        spliced = self.spliced_downstream(dbg_disable)
        segment_in_chain = self.host_segment_in_chain(dbg_disable)
        if ptap_select is not None:
            self.ptap_select = ptap_select & 1
        if ptap_config_hold is not None:
            self.ptap_config_hold = ptap_config_hold & 1
        self._apply_chain_update(gates=gates, in_chain=in_chain, sib_en=sib_en, payloads=payloads)
        for name in spliced:
            ds = self.downstream[name]
            ds.latch((ds_values or {}).get(name, ds.shift_default("dr")))
        self._latch_host_segment(segment_in_chain, host_segment)
        self._park_downstream(gates)

    def apply_ir_scan(
        self,
        ptap_instr: int,
        *,
        ds_ir: Mapping[str, int] | None = None,
        sib_en: Mapping[str, int] | None = None,
        payloads: Mapping[str, Stap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> None:
        """Commit a composed instruction scan's Update-IR: SIB/3DCR fields per
        the gating rules (the PTAP 3DCR is untouched), each spliced downstream
        TAP takes its new instruction, the host segment latches as for a data
        scan, then parking as for a data scan."""
        del ptap_instr  # the PTAP instruction is tracked by the sequence's driver
        gates = self.gates(dbg_disable)
        in_chain = dict(self.sib_en)
        spliced = self.spliced_downstream(dbg_disable)
        segment_in_chain = self.host_segment_in_chain(dbg_disable)
        self._apply_chain_update(gates=gates, in_chain=in_chain, sib_en=sib_en, payloads=payloads)
        for name in spliced:
            if ds_ir and name in ds_ir:
                self.downstream[name].update_ir(ds_ir[name])
        self._latch_host_segment(segment_in_chain, host_segment)
        self._park_downstream(gates)

    def flush_scan(self, dbg_disable: Mapping[str, int] | None = None) -> None:
        """Commit an all-zero over-length data scan: every in-chain field
        cleared, a spliced downstream's writable register latched to zero."""
        for name in self.spliced_downstream(dbg_disable):
            self.downstream[name].latch(0)
        self._latch_host_segment(self.host_segment_in_chain(dbg_disable), 0)
        self.ptap_select = 0
        self.ptap_config_hold = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            self.staps[name] = Stap3dcrState()

    def expected_capture(
        self, dbg_disable: Mapping[str, int] | None = None, scan_kind: str = "dr"
    ) -> tuple[int, int, int]:
        """(expected, care_mask, chain_len) for a readback with PTAP select=1.

        Captured bit j of the TDO stream is the flop at depth chain_len-1-j.
        Splice flops capture unknown data and the PTAP IR capture is
        design-specific: both are masked out. A downstream segment captures
        the device's IDCODE, its stored register, zero for BYPASS, or the
        IEEE 1149.1 IR capture on an IR scan; the host segment captures its
        update register, and the PTAP bypass register 0.
        """
        gates = self.gates(dbg_disable)
        layout = self.chain_layout(dbg_disable, scan_kind)
        length = len(layout)
        expected = 0
        care = 0
        ds_capture = {name: ds.capture(scan_kind) for name, ds in self.downstream.items()}
        for depth, flop in enumerate(layout):
            bit = length - 1 - depth
            if flop.field == "splice" or (flop.owner == "ptap" and flop.field == "ir"):
                continue
            care |= 1 << bit
            if flop.field == "ds":
                value = (ds_capture[flop.owner] >> flop.bit) & 1
            else:
                value = self._field_value(
                    flop,
                    scan_kind=scan_kind,
                    ptap_select=self.ptap_select,
                    ptap_config_hold=self.ptap_config_hold,
                    ptap_instr=0,
                    sib_en={},
                    payloads={},
                    ds_values={},
                    host_segment=None,
                )
                # A STAP captures its masked stap_sel: 0 while its disable is
                # asserted, even though the stored bit survives the gate.
                if flop.owner != "ptap" and flop.field == "stap_sel" and gates[flop.owner]:
                    value = 0
            if value:
                expected |= 1 << bit
        return expected, care, length

    def ds_capture_slice(
        self, name: str, dbg_disable: Mapping[str, int] | None = None, scan_kind: str = "dr"
    ) -> tuple[int, int]:
        """(lsb, width) of STAP ``name``'s downstream segment inside a capture
        of the current chain, so ``(captured >> lsb) & mask`` is the register
        value in natural bit order."""
        layout = self.chain_layout(dbg_disable, scan_kind)
        depths = [d for d, flop in enumerate(layout) if flop.owner == name and flop.field == "ds"]
        if not depths:
            raise ValueError(f"STAP {name!r} has no downstream TAP in the chain")
        return len(layout) - 1 - max(depths), len(depths)

    @staticmethod
    def gates(dbg_disable: Mapping[str, int] | None = None) -> dict[str, int]:
        """Per-STAP gate state from the direct disables (1 = STAP gated)."""
        dbg = dict(dbg_disable or {})
        return {name: int(dbg.get(field, 0)) & 1 for name, field in STAP_DISABLE.items()}

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
        # a 3DCR survives when its config_hold is set. A downstream TAP that
        # follows the live TMS (selected) or is parked high reaches
        # Test-Logic-Reset as well and re-selects IDCODE. The host segment's
        # update register resets on the host scan control's rst_n, which
        # the stap_host gate leaves live.
        for name, ds in self.downstream.items():
            if self.staps[name].stap_sel or self.staps[name].tms_hold:
                ds.reset_instruction()
        if not self.ptap_config_hold:
            self.ptap_select = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            if not self.staps[name].config_hold:
                self.staps[name].stap_sel = 0
                self.staps[name].tms_hold = 0
        self.host_segment = 0

    def trst(self) -> None:
        # TRST is forwarded to every STAP host port: the downstream TAPs reset
        # too (IDCODE selected; their data registers keep their values).
        self.ptap_config_hold = 0
        self.ptap_select = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            self.staps[name] = Stap3dcrState()
        for ds in self.downstream.values():
            ds.reset_instruction()
        self.host_segment = 0


def _selftest_ijtag() -> None:
    """Round-trip the SIB model: open a pattern with instrument values,
    predict the next capture, gate one SIB and prove its stored bit
    re-arms on release, and check the marker placement of an observe scan."""
    model = DtpIjtagSibModel()
    assert model.chain_len() == IJTAG_SIB_COUNT
    values = {"dft_secure": 0xA, "dft": 0x15, "dfd": 0x2A}
    # Opening scan: the instruments join the chain after its Update-DR, so
    # the values shifted for them are dropped.
    model.apply_scan(pattern=0b111, inst_values=values)
    assert model.chain_len() == IJTAG_CHAIN_LEN_MAX
    assert all(v == 0 for v in model.instruments.values())
    # Maintain scan with values: every instrument latches its segment.
    width = model.chain_len()
    composed = model.compose_scan(width, inst_values=values)
    assert (composed >> (width - 1)) & 1 == 1  # dft_secure SIB, TDI-nearest
    assert (composed >> (width - 5)) & 0xF == 0xA  # its 4-bit instrument
    model.apply_scan(inst_values=values)
    expected, length = model.expected_capture()
    assert length == width and expected == composed
    # Gate dfd: it captures closed and leaves the chain; the stored bit
    # survives a gated close attempt and re-arms on release.
    gate = {"dfd": 1}
    assert model.chain_len(gate) == IJTAG_CHAIN_LEN_MAX - IJTAG_INSTRUMENT_WIDTHS["dfd"]
    model.apply_scan(pattern=0b110, dbg_disable=gate)
    assert model.stored["dfd"] == 1 and model.effective(gate)["dfd"] == 0
    assert model.effective()["dfd"] == 1
    model.apply_scan(pattern=0)
    assert model.chain_len() == IJTAG_SIB_COUNT
    # Observe-scan marker placement: the chain image sits above the marker.
    marker = 0x8001
    value = (model.compose_scan(IJTAG_SIB_COUNT) << (IJTAG_OBSERVE_SCAN_WIDTH - 3)) | marker
    assert value & ((1 << SCAN_MARKER_WIDTH) - 1) == marker


def _selftest() -> None:
    """Round-trip the composed-chain model with and without downstream TAPs.

    Runs without a simulator (``python -m env.dtp_scan_ref_model`` from
    ``hw/sys/dtp/dv/cocotb``): for every STAP, select it, compose a
    maintain scan, and check that the layout, the capture prediction, and
    the downstream segment slice agree, both as a wire loopback and with a
    device attached (IDCODE, a written register, an IR scan, gating, and
    parking). The iJTAG model round-trips first, then the host segment and
    the ZERO_LENGTH_BYPASS and BYPASS layouts.
    """
    from dataclasses import dataclass as _dataclass

    _selftest_ijtag()

    @_dataclass(frozen=True)
    class _Reg:
        name: str
        opcode: int
        width: int
        write: bool

    class _Device:
        def __init__(self, name: str, idcode: int, tdr_width: int) -> None:
            self.name = name
            self.idcode = idcode
            self.ir_width = 5
            self.regs = {
                "BYPASS": _Reg("BYPASS", 0x1F, 1, False),
                "IDCODE": _Reg("IDCODE", 0x01, 32, False),
                "DS_TDR": _Reg("DS_TDR", 0x02, tdr_width, True),
            }

    width = 64
    for stap in STAP_ORDER:
        for attached in (False, True):
            model = DtpStap3dcrModel()
            if attached:
                model.attach(
                    stap, _Device(f"{stap}_ds", 0x1D51_0001 | (STAP_ORDER.index(stap) << 8), 12)
                )
            # Select the STAP: PTAP select, open its SIB, write the payload.
            model.apply_scan(ptap_select=1, ptap_config_hold=1, sib_en={stap: 1})
            model.apply_scan(payloads={stap: Stap3dcrState(1, 1, 1)})
            layout = model.chain_layout()
            expect_len = 2 + 4 + STAP_3DCR_WIDTH + DtpStap3dcrModel.SPLICE_EXTRA[stap]
            if attached:
                expect_len += 32  # IDCODE selected after reset
            assert len(layout) == expect_len, (stap, attached, len(layout), expect_len)
            expected, care, chain_len = model.expected_capture()
            assert chain_len == len(layout)
            if attached:
                lsb, seg = model.ds_capture_slice(stap)
                assert (
                    seg == 32 and (expected >> lsb) & 0xFFFF_FFFF == model.downstream[stap].idcode
                )
                # IR scan: PTAP IR + chain with the downstream IR segment.
                ir_layout = model.chain_layout(scan_kind="ir")
                assert (
                    len(ir_layout)
                    == DTP_IR_WIDTH + 4 + STAP_3DCR_WIDTH + 5 + DtpStap3dcrModel.SPLICE_EXTRA[stap]
                )
                value = model.compose_ir_scan(width, 0x0E, ds_ir={stap: 0x02})
                assert (value >> (width - DTP_IR_WIDTH)) == 0x0E
                model.apply_ir_scan(0x0E, ds_ir={stap: 0x02})
                assert model.downstream[stap].active_ir == 0x02
                # DR write of the 12-bit register round-trips through the slice.
                lsb, seg = model.ds_capture_slice(stap)
                assert seg == 12
                composed = model.compose_scan(width, ds_values={stap: 0xABC})
                layout = model.chain_layout()
                depth0 = next(  # TDI-nearest downstream flop = register MSB
                    d for d, f in enumerate(layout) if f.owner == stap and f.field == "ds"
                )
                assert (composed >> (width - depth0 - 12)) & 0xFFF == 0xABC
                model.apply_scan(ds_values={stap: 0xABC})
                expected, care, chain_len = model.expected_capture()
                assert (expected >> lsb) & 0xFFF == 0xABC
                # Gating parks the downstream (tms_hold=1) on IDCODE and drops it from the chain.
                gate = {STAP_DISABLE[stap]: 1}
                assert not model.spliced_downstream(gate)
                model.apply_scan(dbg_disable=gate)
                assert model.downstream[stap].active_ir == 0x01
                assert model.downstream[stap].values["DS_TDR"] == 0xABC
                # Release: IDCODE is back in the chain.
                lsb, seg = model.ds_capture_slice(stap)
                assert seg == 32
            # Composed maintain scan carries the stored state (MSB TDI-nearest).
            composed = model.compose_scan(width)
            assert (composed >> (width - 1)) & 1 == 1  # PTAP stap_sel
            model.flush_scan()
            assert len(model.chain_layout()) == 2 + 4
    _selftest_host_segment(width)
    _selftest_zlb_bypass(width, _Device("smc_ds", 0x1D51_0101, 12))
    print("DTP_SCAN_REF_MODEL SELFTEST PASS")


def _selftest_host_segment(width: int) -> None:
    """The host segment sits at the TDO end while ``stap_host`` is enabled,
    keeps its value through a gated scan, and clears in Test-Logic-Reset."""
    model = DtpStap3dcrModel()
    model.attach_host_segment()
    gate = {STAP_DISABLE["stap_host"]: 1}
    seg_len = STAP_HOST_SEGMENT_WIDTH
    assert len(model.chain_layout()) == PTAP_3DCR_WIDTH + STAP_SIB_COUNT + seg_len
    assert len(model.chain_layout(gate)) == PTAP_3DCR_WIDTH + STAP_SIB_COUNT
    assert len(model.chain_layout(scan_kind="ir")) == DTP_IR_WIDTH + STAP_SIB_COUNT + seg_len
    composed = model.compose_scan(width, ptap_select=1, host_segment=0x5A)
    assert (composed >> (width - PTAP_3DCR_WIDTH - STAP_SIB_COUNT - seg_len)) & 0x7F == 0x5A
    model.apply_scan(ptap_select=1, host_segment=0x5A)
    expected, care, chain_len = model.expected_capture()
    assert chain_len == PTAP_3DCR_WIDTH + STAP_SIB_COUNT + seg_len
    assert expected & 0x7F == 0x5A and care & 0x7F == 0x7F
    model.apply_scan(dbg_disable=gate, host_segment=0x11)
    assert model.host_segment == 0x5A
    model.apply_ir_scan(0x0E, host_segment=0x33)
    assert model.host_segment == 0x33
    model.tlr()
    assert model.host_segment == 0


def _selftest_zlb_bypass(width: int, device) -> None:
    """A data scan under ZERO_LENGTH_BYPASS is the STAP chain alone and one
    under BYPASS starts with the bypass register's captured 0; neither
    reaches the PTAP 3DCR, and the spliced downstream register latches the
    value composed for it."""
    model = DtpStap3dcrModel()
    model.attach("smc", device)
    model.apply_scan(ptap_select=1, ptap_config_hold=1, sib_en={"smc": 1})
    model.apply_scan(payloads={"smc": Stap3dcrState(0, 1, 0)})
    model.apply_ir_scan(0x3D, ds_ir={"smc": 0x02})
    zlb = model.chain_layout(scan_kind="zlb")
    assert model.chain_layout(scan_kind="dr")[PTAP_3DCR_WIDTH:] == zlb
    assert model.chain_layout(scan_kind="bypass") == [ChainFlop("ptap", "bypass"), *zlb]
    composed = model.compose_scan(width, ds_values={"smc": 0xABC}, scan_kind="zlb")
    depth0 = next(d for d, f in enumerate(zlb) if f.owner == "smc" and f.field == "ds")
    assert (composed >> (width - depth0 - 12)) & 0xFFF == 0xABC
    model.apply_scan(ds_values={"smc": 0xABC})
    assert model.ptap_select == 1 and model.ptap_config_hold == 1
    lsb, seg = model.ds_capture_slice("smc", scan_kind="zlb")
    expected, care, chain_len = model.expected_capture(scan_kind="zlb")
    assert chain_len == len(zlb) and seg == 12 and (expected >> lsb) & 0xFFF == 0xABC
    expected, care, chain_len = model.expected_capture(scan_kind="bypass")
    assert chain_len == len(zlb) + 1
    assert (care >> len(zlb)) & 1 == 1 and (expected >> len(zlb)) & 1 == 0


if __name__ == "__main__":
    _selftest()
