# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""STAP/3DCR reference model of the DTP testbench.

The model covers the IEEE 1838 configuration chain and, per STAP host port,
an optionally attached downstream IEEE 1149.1 TAP (the ``ocah_jtag_vip``
slave device ``tb_top`` splices behind the port, ``DtpStapDsState``). It
predicts the downstream contribution independently from the VIP's device
engine: its IR and selected data register are chain segments whose captures
are the IDCODE, the value the model latched, or the IEEE 1149.1 IR capture.
It also covers the host segment ``tb_top`` can place behind the extended
STAP host scan interface, the chain return while ``stap_host`` is enabled,
and the chain a data scan passes through under ZERO_LENGTH_BYPASS or BYPASS
while the PTAP 3DCR select is set. The SV-UVM twin is
``uvm/env/dtp_stap_3dcr_model.svh``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ocah_jtag_vip import OcahJtagDevice

from .dtp_dbg_disable import STAP_DISABLE
from .dtp_stap_ds_state import DtpStapDsState
from .dtp_types import DTP_IR_WIDTH, DtpScanKind

__all__ = [
    "PTAP_3DCR_WIDTH",
    "STAP_3DCR_WIDTH",
    "STAP_HOST_SEGMENT_WIDTH",
    "STAP_ORDER",
    "STAP_SIB_COUNT",
    "DtpStap3dcrModel",
    "DtpStap3dcrState",
    "DtpStapChainFlop",
]

STAP_ORDER = ("io", "smc", "sep", "extra0")
STAP_SIB_COUNT = len(STAP_ORDER)
PTAP_3DCR_WIDTH = 2
STAP_3DCR_WIDTH = 3
# Host segment behind the extended STAP host scan interface (tb_top): a scan
# register that captures its own update register.
STAP_HOST_SEGMENT_WIDTH = 7


@dataclass
class DtpStap3dcrState:
    """One STAP's 3DCR fields."""

    config_hold: int = 0
    stap_sel: int = 0
    tms_hold: int = 0

    @classmethod
    def from_value(cls, value: int) -> "DtpStap3dcrState":
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
class DtpStapChainFlop:
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
    scan only while the PTAP 3DCR select is set, and then routes the
    instruction register's scan-out into the chain: an IR scan is the 6-bit
    PTAP IR followed by the STAP chain (the PTAP 3DCR itself is a data
    register and stays out of IR scans), and Update-IR commits SIB/3DCR
    fields and the downstream IRs exactly as Update-DR does. Every scan
    issued while the select is set must therefore be composed over the full
    network. While the select is clear the chain, host segment included,
    holds through every scan and a scan covers only the PTAP segment, so the
    select must be set by a scan of its own before a scan can write the
    chain.

    A data scan under any other PTAP instruction runs through the STAP chain
    as well while the PTAP 3DCR select is set, and its Update-DR commits the
    chain fields without reaching the PTAP 3DCR. Under BYPASS the one-bit
    bypass register, which captures 0, precedes the chain (``DtpScanKind.BYPASS``).
    ZERO_LENGTH_BYPASS (``DtpScanKind.ZLB``) is BYPASS while the PTAP 3DCR select is
    set, and the zero-length TDI-to-TDO path, with no chain, while it is
    clear.
    """

    # Extra full-cycle flops a STAP's selected splice inserts into the chain.
    SPLICE_EXTRA = {"io": 1, "smc": 0, "sep": 0, "extra0": 0}

    def __init__(self) -> None:
        self.ptap_config_hold = 0
        self.ptap_select = 0
        self.staps = {name: DtpStap3dcrState() for name in STAP_ORDER}
        self.sib_en = {name: 0 for name in STAP_ORDER}
        self.downstream: dict[str, DtpStapDsState] = {}
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
    def attach(self, name: str, device: OcahJtagDevice) -> DtpStapDsState:
        """Seed the downstream TAP behind STAP ``name`` from its device map."""
        if name not in STAP_ORDER:
            raise ValueError(f"unknown STAP {name!r}")
        ds = DtpStapDsState.from_device(device)
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
        self, dbg_disable: Mapping[str, int] | None = None, scan_kind: DtpScanKind = DtpScanKind.DR
    ) -> list[DtpStapChainFlop]:
        """Chain flops in TDI-to-TDO order for the current state.

        ``scan_kind`` is ``DR`` (TAP_3DCR data scan: PTAP 3DCR first),
        ``IR`` (instruction scan: PTAP IR first, PTAP 3DCR absent),
        ``ZLB`` (data scan under ZERO_LENGTH_BYPASS: the ``BYPASS`` layout
        while the PTAP select is set, no PTAP flop while it is clear), or
        ``BYPASS`` (data scan under BYPASS: the PTAP bypass register first).
        With the PTAP select clear the chain is out of the scan path.
        """
        gates = self.gates(dbg_disable)
        flops: list[DtpStapChainFlop] = []
        if scan_kind == DtpScanKind.IR:
            flops.extend(
                DtpStapChainFlop("ptap", "ir", bit) for bit in range(DTP_IR_WIDTH - 1, -1, -1)
            )
        elif scan_kind == DtpScanKind.DR:
            flops.extend(
                (DtpStapChainFlop("ptap", "stap_sel"), DtpStapChainFlop("ptap", "config_hold"))
            )
        elif scan_kind == DtpScanKind.BYPASS or (scan_kind == DtpScanKind.ZLB and self.ptap_select):
            flops.append(DtpStapChainFlop("ptap", "bypass"))
        elif scan_kind != DtpScanKind.ZLB:
            raise ValueError(f"unknown scan kind {scan_kind!r}")
        if not self.ptap_select:
            return flops
        for name in STAP_ORDER:
            if self.staps[name].stap_sel and not gates[name]:
                if self.attached(name):
                    width = self.downstream[name].selected_width(scan_kind)
                    flops.extend(
                        DtpStapChainFlop(name, "ds", bit) for bit in range(width - 1, -1, -1)
                    )
                flops.extend(
                    DtpStapChainFlop(name, "splice") for _ in range(self.SPLICE_EXTRA[name])
                )
            if self.sib_en[name]:
                flops.extend(
                    (
                        DtpStapChainFlop(name, "tms_hold"),
                        DtpStapChainFlop(name, "stap_sel"),
                        DtpStapChainFlop(name, "config_hold"),
                    )
                )
            flops.append(DtpStapChainFlop(name, "sib"))
        if self.host_segment_in_chain(dbg_disable):
            flops.extend(
                DtpStapChainFlop("stap_host", "segment", bit)
                for bit in range(STAP_HOST_SEGMENT_WIDTH - 1, -1, -1)
            )
        return flops

    def _field_value(
        self,
        flop: DtpStapChainFlop,
        *,
        scan_kind: DtpScanKind,
        ptap_select: int,
        ptap_config_hold: int,
        ptap_instr: int,
        sib_en: Mapping[str, int],
        payloads: Mapping[str, DtpStap3dcrState],
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

    def _compose(self, layout: list[DtpStapChainFlop], width: int, **args) -> int:
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
        payloads: Mapping[str, DtpStap3dcrState] | None = None,
        ds_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
        scan_kind: DtpScanKind = DtpScanKind.DR,
    ) -> int:
        """Data scan value that writes the given end-state through the
        current chain: a TAP_3DCR scan, or with ``scan_kind`` ``ZLB`` or
        ``BYPASS`` a scan under that PTAP instruction, whose layout holds
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
        payloads: Mapping[str, DtpStap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> int:
        """Instruction scan value over the full network: the PTAP IR segment
        first, then the STAP chain with each spliced downstream TAP's IR
        (``ds_ir`` names new instructions; others keep the active one)."""
        return self._compose(
            self.chain_layout(dbg_disable, DtpScanKind.IR),
            width,
            scan_kind=DtpScanKind.IR,
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
        payloads: Mapping[str, DtpStap3dcrState] | None,
    ) -> None:
        """Update-x for the STAP fields: a gated STAP ignores its 3DCR payload
        write; SIB bits always update; payload flops were in the chain only if
        the SIB was open during the scan (pre-update state)."""
        for name, value in (sib_en or {}).items():
            self.sib_en[name] = int(value) & 1
        for name, payload in (payloads or {}).items():
            if not gates[name] and in_chain[name]:
                self.staps[name] = DtpStap3dcrState(
                    payload.config_hold & 1, payload.stap_sel & 1, payload.tms_hold & 1
                )

    def _latch_host_segment(self, host_segment: int | None, *, in_chain: bool) -> None:
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
        payloads: Mapping[str, DtpStap3dcrState] | None = None,
        ds_values: Mapping[str, int] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> None:
        """Commit a composed data scan's Update-DR: a TAP_3DCR scan updates
        the PTAP 3DCR, and a scan under another instruction leaves
        ``ptap_select`` and ``ptap_config_hold`` None and the PTAP 3DCR as
        it is; SIB/3DCR fields per the gating rules; a spliced downstream
        TAP latches its (writable) selected register, and the host segment
        its value; deselected or gated ports park their downstream TAP. The
        chain fields, downstream TAPs and host segment take part only when
        the PTAP select was set before the scan."""
        gates = self.gates(dbg_disable)
        chain_live = self._chain_live(dbg_disable)
        in_chain = dict(self.sib_en)
        spliced = self.spliced_downstream(dbg_disable)
        segment_in_chain = self.host_segment_in_chain(dbg_disable)
        if ptap_select is not None:
            self.ptap_select = ptap_select & 1
        if ptap_config_hold is not None:
            self.ptap_config_hold = ptap_config_hold & 1
        if chain_live:
            self._apply_chain_update(
                gates=gates, in_chain=in_chain, sib_en=sib_en, payloads=payloads
            )
            for name in spliced:
                ds = self.downstream[name]
                ds.latch((ds_values or {}).get(name, ds.shift_default(DtpScanKind.DR)))
            self._latch_host_segment(host_segment, in_chain=segment_in_chain)
        self._park_downstream(gates)

    def apply_ir_scan(
        self,
        ptap_instr: int,
        *,
        ds_ir: Mapping[str, int] | None = None,
        sib_en: Mapping[str, int] | None = None,
        payloads: Mapping[str, DtpStap3dcrState] | None = None,
        dbg_disable: Mapping[str, int] | None = None,
        host_segment: int | None = None,
    ) -> None:
        """Commit a composed instruction scan's Update-IR: SIB/3DCR fields per
        the gating rules (the PTAP 3DCR is untouched), each spliced downstream
        TAP takes its new instruction, the host segment latches as for a data
        scan, then parking as for a data scan."""
        del ptap_instr  # the PTAP instruction is tracked by the sequence's driver
        gates = self.gates(dbg_disable)
        if self._chain_live(dbg_disable):
            in_chain = dict(self.sib_en)
            spliced = self.spliced_downstream(dbg_disable)
            segment_in_chain = self.host_segment_in_chain(dbg_disable)
            self._apply_chain_update(
                gates=gates, in_chain=in_chain, sib_en=sib_en, payloads=payloads
            )
            for name in spliced:
                if ds_ir and name in ds_ir:
                    self.downstream[name].update_ir(ds_ir[name])
            self._latch_host_segment(host_segment, in_chain=segment_in_chain)
        self._park_downstream(gates)

    def flush_scan(self, dbg_disable: Mapping[str, int] | None = None) -> None:
        """Commit an all-zero over-length data scan: the PTAP 3DCR cleared
        and, when the PTAP select was set before the scan, every in-chain
        field cleared and a spliced downstream's writable register and the
        host segment latched to zero."""
        if self._chain_live(dbg_disable):
            for name in self.spliced_downstream(dbg_disable):
                self.downstream[name].latch(0)
            self._latch_host_segment(0, in_chain=self.host_segment_in_chain(dbg_disable))
            for name in STAP_ORDER:
                self.sib_en[name] = 0
                self.staps[name] = DtpStap3dcrState()
        self.ptap_select = 0
        self.ptap_config_hold = 0

    def _chain_live(self, dbg_disable: Mapping[str, int] | None) -> bool:
        """True when the next scan moves the STAP chain (PTAP select set).

        A STAP left selected while the PTAP select is clear still forwards
        the live TMS and scan data to its downstream TAP, whose registers the
        model does not predict, so such a scan is rejected.
        """
        if self.ptap_select:
            return True
        spliced = self.spliced_downstream(dbg_disable)
        if spliced:
            raise ValueError(
                f"scan with the PTAP select clear while downstream TAPs {spliced} are "
                "spliced: their register contents are not modelled"
            )
        return False

    def expected_capture(
        self, dbg_disable: Mapping[str, int] | None = None, scan_kind: DtpScanKind = DtpScanKind.DR
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
        self,
        name: str,
        dbg_disable: Mapping[str, int] | None = None,
        scan_kind: DtpScanKind = DtpScanKind.DR,
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

    def update_ptap(self, value: int) -> None:
        self.ptap_config_hold = value & 0x1
        self.ptap_select = (value >> 1) & 0x1

    def tlr(self) -> None:
        """Test-Logic-Reset by TMS.

        SIB bits have no config_hold protection and clear; a 3DCR survives
        when its config_hold is set. A downstream TAP that follows the live
        TMS (selected) or is parked high reaches Test-Logic-Reset as well and
        re-selects IDCODE. The host segment's update register resets on the
        host scan control's rst_n, which the stap_host gate leaves live.
        """
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
        """TRST, forwarded to every STAP host port: the downstream TAPs reset too.

        They select IDCODE and their data registers keep their values.
        """
        self.ptap_config_hold = 0
        self.ptap_select = 0
        for name in STAP_ORDER:
            self.sib_en[name] = 0
            self.staps[name] = DtpStap3dcrState()
        for ds in self.downstream.values():
            ds.reset_instruction()
        self.host_segment = 0
