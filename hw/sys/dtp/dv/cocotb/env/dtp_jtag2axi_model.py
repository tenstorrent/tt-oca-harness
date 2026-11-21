# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI bridge model: the JTAG-visible state of the three tdr2axi bridges.

Each bridge is a DTMCS TDR and a DMI TDR in front of a RISC-V Debug Module
whose System Bus Access drives the bridge port
(`hw/ip/jtag/jtag_ptap/doc/architecture.adoc`, "PTAP JTAG2AXI Support"). The
model rebuilds every bridge from the decoded DR scans on the primary TAP and
the transactions the passive monitors observe on its port:

  DMI update   Without a sticky error, an update loads the scanned address and
               data; op 1 reads and op 2 writes that Debug Module register.
               Op 3 clears the sticky error; while the error is set the bridge
               ignores every other update.
  DMI capture  {address, data, status}: the last loaded address, the last
               loaded data or the read response, and the sticky status. A busy
               response from the Debug Module sets the status to BUSY and, for
               a read, the data to 0xB051B051.
  operation    A read or write is in progress from its Update-DR until the
               Debug Module's response returns. A DMI capture during a read
               sets the status to BUSY and returns the operation's own address
               and data; an update during either sets the status to BUSY, or
               to 0 for op 3, and loads nothing.
  DTMCS        Capture: version 1, abits 7, idle 7, and the DMI sticky status
               in dmistat. An update with dmireset gives the DMI an op-3 update
               carrying its own address and data.
  dmcontrol    While dmactive is 0 the Debug Module holds sbcs at its reset
               value (sbaccess 2, sbversion and sbasize 0) and sbaddress and
               sbdata at 0; a write of sbdata0 in that state starts a bus
               write of 0 at address 0.
  sbcs         A write sets sbreadonaddr, sbaccess, sbautoincrement and
               sbreadondata and clears sbbusyerror and sberror where it writes
               1. sbversion, sbasize and the sbaccess* bits publish the
               bridge's geometry. A write while a bus access is outstanding is
               a busy response that sets sbbusyerror and writes nothing.
  sbaddress    An sbaddress0 write with sbreadonaddr starts a read. The
               address holds sbasize bits; the bits above it read 0.
  sbdata       An sbdata0 write starts a write; an sbdata0 read returns the
               data and, with sbreadondata, then starts a read. An sbaddress or
               sbdata access while a bus access is outstanding or sbbusyerror
               is set is a busy response that sets sbbusyerror and leaves the
               register unchanged.
  bus access   Starts only while sberror is 0. An sbaccess above the beat width
               sets sberror 4 and an address not aligned to it sets 3, without
               a transaction. Otherwise one beat of 2**sbaccess bytes on the
               lanes the address selects; SLVERR or DECERR set sberror 2. A
               completed read loads sbdata with the beat shifted down to the
               address; a completed write loads it with the read-data lanes,
               which carry no contract. sbautoincrement advances the address
               by the size on every completion. With the bridge's lifecycle
               disable asserted the access completes as DECERR without
               reaching the port, and a read returns 0xBADCAB1E per word.

A system reset returns every bridge to its reset state; a TAP reset leaves
them unchanged. Captures and updates come from the TCK steps, so a DR scan of
any length counts: its update loads the captured value shifted by the bits
the scan shifted, and only those bits of its capture are compared. A DMI
operation is applied on the TCK cycle that leaves its Update-DR, and a bus
completion at the first update at least one TCK cycle after the port
handshake. A capture or update within DTP_DMI_BUSY_TCK TCK cycles of the last
read or write update finds that operation in progress, and one
DTP_DMI_SETTLE_TCK cycles or more after it finds it complete; between the two
the clock ratio decides, and the model has no prediction. While a bus access
is outstanding only sbcs is read, unless the bridge's response hold for that
access is set, which keeps the access outstanding until the hold releases.
``DtpJtag2AxiScopeError`` reports a scan outside that scope.
Plain classes held by the JTAG2AXI reference models; no reporting. The SV-UVM
twin is ``dtp_jtag2axi_model``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from ocah_axi_vip import OcahAxiItem, OcahAxiProtocol
from ocah_jtag_vip import OcahJtagEvent, OcahJtagScanItem, OcahJtagState

from .dtp_jtag2axi_status_item import DtpJtag2AxiStatusItem
from .dtp_jtag_ir_model import DtpJtagIrModel
from .dtp_types import (
    DMI_LEN,
    DTMCS_LEN,
    DTP_DMI_BUSY_TCK,
    DTP_DMI_SETTLE_TCK,
    DTP_EXPECTED_DTMCS,
    JTAG2AXI_TARGETS,
    DtpDmiOp,
    DtpDmiStatus,
    DtpDmReg,
    DtpJtag2AxiTargetCfg,
    pack_dmi,
    pack_sbcs,
    unpack_dmi,
)

__all__ = [
    "DtpJ2aHolds",
    "DtpJ2aScanKind",
    "DtpJtag2AxiModel",
    "DtpJtag2AxiScopeError",
    "DtpJtag2AxiTracker",
    "strobe_lanes",
]

_AXI_RESP_SLVERR = 2
_DATA_BUSY = 0xB051_B051
_ERR_SLAVE_WORD = 0xBADC_AB1E
_DTMCS_DMIRESET_BIT = 16
_SBERROR_BUS = 2
_SBERROR_ALIGN = 3
_SBERROR_SIZE = 4
_SBCS_RESET_SBACCESS = 2
_WORD = 0xFFFF_FFFF
_DWORD = (1 << 64) - 1


class DtpJtag2AxiScopeError(RuntimeError):
    """A bridge scan outside the scope the module docstring states."""


class DtpJ2aScanKind(Enum):
    """Which JTAG2AXI register a DR scan addressed, from the active instruction."""

    NONE = "none"
    DTMCS = "dtmcs"
    DMI = "dmi"


_CLASSIFY: dict[int, tuple[DtpJ2aScanKind, DtpJtag2AxiTargetCfg]] = {
    **{int(t.dtmcs_instr): (DtpJ2aScanKind.DTMCS, t) for t in JTAG2AXI_TARGETS.values()},
    **{int(t.dmi_instr): (DtpJ2aScanKind.DMI, t) for t in JTAG2AXI_TARGETS.values()},
}
_SCAN_LEN = {DtpJ2aScanKind.DTMCS: DTMCS_LEN, DtpJ2aScanKind.DMI: DMI_LEN}


def _mask(width: int) -> int:
    return (1 << width) - 1


def strobe_lanes(strb: int) -> int:
    """The data bits of the byte lanes a strobe enables."""
    return sum(0xFF << (8 * lane) for lane in range(8) if (strb >> lane) & 0x1)


@dataclass(frozen=True)
class _Access:
    is_read: bool
    size: int
    offset: int


@dataclass(frozen=True)
class DtpJ2aHolds:
    """A bridge's response holds: ``b`` keeps write responses from it, ``r`` read responses."""

    b: bool = False
    r: bool = False

    def keep(self, access: _Access | None) -> bool:
        """Whether the hold of ``access``'s direction keeps it outstanding."""
        return access is not None and (self.r if access.is_read else self.b)


@dataclass(frozen=True)
class _DmResponse:
    data: int = 0
    data_mask: int = 0
    busy: bool = False


@dataclass
class _Bridge:
    # DMI TDR bridge.
    address: int = 0
    data: int = 0
    data_mask: int = _WORD
    error: int = int(DtpDmiStatus.SUCCESS)
    last_op_tck: int = 0
    op_read: bool = False
    # The Debug Module's response to the read or write in progress, applied when it returns.
    pending: _DmResponse | None = None
    # Debug Module.
    dmactive: bool = False
    ndmreset: int = 0
    sbreadonaddr: int = 0
    sbaccess: int = _SBCS_RESET_SBACCESS
    sbautoincrement: int = 0
    sbreadondata: int = 0
    sbbusyerror: int = 0
    sberror: int = 0
    sbaddr: int = 0
    sbdata: int = 0
    sbdata_mask: int = _DWORD
    inflight: _Access | None = None
    completed: deque[OcahAxiItem] = field(default_factory=deque)
    # Completions due for accesses a system reset discarded.
    orphans: int = 0

    def reset_dm(self) -> None:
        """The Debug Module's synchronous reset while dmactive is 0."""
        self.ndmreset = 0
        self.sbreadonaddr = 0
        self.sbaccess = _SBCS_RESET_SBACCESS
        self.sbautoincrement = 0
        self.sbreadondata = 0
        self.sbbusyerror = 0
        self.sberror = 0
        self.sbaddr = 0
        self.sbdata = 0
        self.sbdata_mask = _DWORD


class DtpJtag2AxiModel:
    """JTAG-visible state of the three bridges, from decoded scans and observed completions.

    ``negative`` leaves the status at 0 where a capture or update finds an
    operation in progress, so the captures that follow must disagree with the
    bridge.
    """

    def __init__(self, *, negative: bool = False) -> None:
        self.negative = negative
        self._bridges: dict[str, _Bridge] = {}
        self.reset()

    def reset(self) -> None:
        """System reset: every bridge back to its reset state; accesses in flight are discarded."""
        prior = self._bridges
        self._bridges = {name: _Bridge() for name in JTAG2AXI_TARGETS}
        for name, old in prior.items():
            outstanding = old.inflight is not None and not old.completed
            self._bridges[name].orphans = old.orphans + int(outstanding)

    @staticmethod
    def classify(ir: int) -> tuple[DtpJ2aScanKind, DtpJtag2AxiTargetCfg | None]:
        """Which bridge register a DR scan under ``ir`` addresses."""
        return _CLASSIFY.get(ir, (DtpJ2aScanKind.NONE, None))

    def capture(
        self, target: DtpJtag2AxiTargetCfg, kind: DtpJ2aScanKind, tck: int
    ) -> tuple[int, int]:
        """The value a Capture-DR on TCK cycle ``tck`` loads, and the mask of its known bits."""
        bridge = self._bridges[target.name]
        in_progress = self._in_progress(target, bridge, tck, "capture")
        if kind is DtpJ2aScanKind.DTMCS:
            return DTP_EXPECTED_DTMCS | (bridge.error << 10), _WORD
        if in_progress and bridge.op_read and not self.negative:
            self._set_busy(bridge)
        return (
            pack_dmi(bridge.address, bridge.data, bridge.error),
            pack_dmi(0x7F, bridge.data_mask, 0x3),
        )

    def update(
        self,
        target: DtpJtag2AxiTargetCfg,
        kind: DtpJ2aScanKind,
        value: int,
        known: int,
        tck: int,
        visible_ns: float,
        *,
        gated: bool,
        held: DtpJ2aHolds,
    ) -> OcahAxiItem | None:
        """Update-DR of a DTMCS or DMI register on TCK cycle ``tck``; the bus transaction it
        launches, if any.

        ``value`` is the update stage's content and ``known`` the mask of its bits the model
        knows. ``visible_ns``: completions at or before it have reached the Debug Module.
        ``gated``: the bridge's lifecycle disable is asserted. ``held``: the bridge's
        response holds.
        """
        bridge = self._bridges[target.name]
        if kind is DtpJ2aScanKind.DTMCS:
            self._require_known(target, known, 1 << _DTMCS_DMIRESET_BIT, "dmireset")
            if not (value >> _DTMCS_DMIRESET_BIT) & 0x1:
                return None
            address, data, op = bridge.address, bridge.data, int(DtpDmiOp.CLEAR)
            data_mask = bridge.data_mask
        else:
            self._require_known(target, known, 0x3, "op")
            address, data, op = unpack_dmi(value)
            data_mask = unpack_dmi(known)[1]
        if self._in_progress(target, bridge, tck, "update"):
            if op == DtpDmiOp.CLEAR:
                bridge.error = int(DtpDmiStatus.SUCCESS)
            elif not self.negative:
                self._set_busy(bridge)
            return None
        self._apply_completions(target, bridge, visible_ns)
        if bridge.error != DtpDmiStatus.SUCCESS:
            if op == DtpDmiOp.CLEAR:
                bridge.error = int(DtpDmiStatus.SUCCESS)
            return None
        bridge.address, bridge.data, bridge.data_mask = address, data, data_mask
        if op not in (DtpDmiOp.READ, DtpDmiOp.WRITE):
            return None
        if op == DtpDmiOp.WRITE:
            self._require_known(target, data_mask, _WORD, "write data")
        bridge.last_op_tck = tck
        bridge.op_read = op == DtpDmiOp.READ
        if bridge.op_read:
            bridge.pending, launched = self._dm_read(target, bridge, address, gated, held)
        else:
            bridge.pending, launched = self._dm_write(target, bridge, address, data, gated, held)
        return launched

    def complete(self, target: str, observed: OcahAxiItem) -> None:
        """A transaction observed on a bridge port, applied at a later update."""
        bridge = self._bridges[target]
        if bridge.orphans:
            bridge.orphans -= 1
            return
        bridge.completed.append(observed)

    # --- DMI operation -----------------------------------------------------------
    def _in_progress(
        self, target: DtpJtag2AxiTargetCfg, bridge: _Bridge, tck: int, what: str
    ) -> bool:
        """Whether the read or write of the last update is in progress on TCK cycle ``tck``.

        An operation found complete has its response applied first.
        """
        if bridge.pending is None:
            return False
        elapsed = tck - bridge.last_op_tck
        if elapsed <= DTP_DMI_BUSY_TCK:
            return True
        if elapsed < DTP_DMI_SETTLE_TCK:
            raise DtpJtag2AxiScopeError(
                f"{target.name}: {what} {elapsed} TCK after a DMI read or write update, "
                f"between the {DTP_DMI_BUSY_TCK}-TCK busy and {DTP_DMI_SETTLE_TCK}-TCK settle "
                "bounds"
            )
        response, bridge.pending = bridge.pending, None
        if bridge.op_read:
            bridge.data, bridge.data_mask = (
                (_DATA_BUSY, _WORD) if response.busy else (response.data, response.data_mask)
            )
        if response.busy:
            self._set_busy(bridge)
        return False

    @staticmethod
    def _set_busy(bridge: _Bridge) -> None:
        if bridge.error == DtpDmiStatus.SUCCESS:
            bridge.error = int(DtpDmiStatus.BUSY)

    @staticmethod
    def _require_known(target: DtpJtag2AxiTargetCfg, known: int, bits: int, field: str) -> None:
        if known & bits != bits:
            raise DtpJtag2AxiScopeError(
                f"{target.name}: Update-DR {field} comes from captured bits without a contract"
            )

    # --- Debug Module ------------------------------------------------------------
    def _sbcs(self, target: DtpJtag2AxiTargetCfg, bridge: _Bridge) -> int:
        if not bridge.dmactive:
            return pack_sbcs(sbaccess=_SBCS_RESET_SBACCESS)
        return pack_sbcs(
            sbversion=1,
            sbbusyerror=bridge.sbbusyerror,
            sbbusy=int(bridge.inflight is not None),
            sbreadonaddr=bridge.sbreadonaddr,
            sbaccess=bridge.sbaccess,
            sbautoincrement=bridge.sbautoincrement,
            sbreadondata=bridge.sbreadondata,
            sberror=bridge.sberror,
            sbasize=target.addr_width,
            sbaccess64=int(target.data_width >= 64),
            sbaccess32=1,
            sbaccess16=1,
            sbaccess8=1,
        )

    @staticmethod
    def _require_held(
        target: DtpJtag2AxiTargetCfg, bridge: _Bridge, held: DtpJ2aHolds, what: str
    ) -> None:
        """An outstanding access may complete before a DMI access reaches the Debug Module
        unless a response hold keeps it outstanding."""
        if bridge.inflight is not None and not held.keep(bridge.inflight):
            raise DtpJtag2AxiScopeError(f"{target.name}: {what} while a bus access is outstanding")

    def _sba_register(
        self, target: DtpJtag2AxiTargetCfg, bridge: _Bridge, address: int, held: DtpJ2aHolds
    ) -> _DmResponse | None:
        """The busy response of an sbaddress or sbdata access, or None when it proceeds."""
        self._require_held(target, bridge, held, f"Debug Module register 0x{address:02x} accessed")
        if bridge.inflight is not None or bridge.sbbusyerror:
            bridge.sbbusyerror = 1
            return _DmResponse(busy=True)
        return None

    def _dm_read(
        self,
        target: DtpJtag2AxiTargetCfg,
        bridge: _Bridge,
        address: int,
        gated: bool,
        held: DtpJ2aHolds,
    ) -> tuple[_DmResponse, OcahAxiItem | None]:
        if address == DtpDmReg.DMCONTROL:
            return _DmResponse(int(bridge.dmactive) | (bridge.ndmreset << 1), 0x3), None
        if address == DtpDmReg.SBCS:
            racing = (
                bridge.dmactive and bridge.inflight is not None and not held.keep(bridge.inflight)
            )
            unknown = pack_sbcs(sbbusy=1, sberror=0x7) if racing else 0
            return _DmResponse(self._sbcs(target, bridge), _WORD & ~unknown), None
        if address in (DtpDmReg.SBADDRESS0, DtpDmReg.SBADDRESS1):
            self._require_held(target, bridge, held, "sbaddress read")
            shift = 0 if address == DtpDmReg.SBADDRESS0 else 32
            return _DmResponse((bridge.sbaddr >> shift) & _WORD, _WORD), None
        if address in (DtpDmReg.SBDATA0, DtpDmReg.SBDATA1):
            busy = self._sba_register(target, bridge, address, held)
            if busy is not None:
                return busy, None
            shift = 0 if address == DtpDmReg.SBDATA0 else 32
            response = _DmResponse(
                (bridge.sbdata >> shift) & _WORD, (bridge.sbdata_mask >> shift) & _WORD
            )
            launched = None
            if address == DtpDmReg.SBDATA0 and bridge.sbreadondata and not bridge.sberror:
                launched = self._launch(target, bridge, is_read=True, gated=gated)
            return response, launched
        return _DmResponse(), None

    def _dm_write(
        self,
        target: DtpJtag2AxiTargetCfg,
        bridge: _Bridge,
        address: int,
        data: int,
        gated: bool,
        held: DtpJ2aHolds,
    ) -> tuple[_DmResponse, OcahAxiItem | None]:
        if address == DtpDmReg.DMCONTROL:
            bridge.ndmreset = (data >> 1) & 0x1 if bridge.dmactive else 0
            bridge.dmactive = bool(data & 0x1)
            if not bridge.dmactive:
                bridge.reset_dm()
            return _DmResponse(), None
        if address == DtpDmReg.SBCS:
            self._require_held(target, bridge, held, "sbcs written")
            if bridge.inflight is not None:
                bridge.sbbusyerror = 1
                return _DmResponse(busy=True), None
            if bridge.dmactive:
                written = {
                    "sbreadonaddr": (data >> 20) & 0x1,
                    "sbaccess": (data >> 17) & 0x7,
                    "sbautoincrement": (data >> 16) & 0x1,
                    "sbreadondata": (data >> 15) & 0x1,
                }
                for name, value in written.items():
                    setattr(bridge, name, value)
                if (data >> 22) & 0x1:
                    bridge.sbbusyerror = 0
                if (data >> 12) & 0x7:
                    bridge.sberror = 0
            return _DmResponse(), None
        if address not in (
            DtpDmReg.SBADDRESS0,
            DtpDmReg.SBADDRESS1,
            DtpDmReg.SBDATA0,
            DtpDmReg.SBDATA1,
        ):
            return _DmResponse(), None
        busy = self._sba_register(target, bridge, address, held)
        if busy is not None:
            return busy, None
        launched = None
        if address in (DtpDmReg.SBADDRESS0, DtpDmReg.SBADDRESS1):
            if bridge.dmactive:
                shift = 0 if address == DtpDmReg.SBADDRESS0 else 32
                sbaddr = (bridge.sbaddr & ~(_WORD << shift)) | (data << shift)
                bridge.sbaddr = sbaddr & _mask(target.addr_width)
                if address == DtpDmReg.SBADDRESS0 and bridge.sbreadonaddr and not bridge.sberror:
                    launched = self._launch(target, bridge, is_read=True, gated=gated)
            return _DmResponse(), launched
        shift = 0 if address == DtpDmReg.SBDATA0 else 32
        if bridge.dmactive:
            bridge.sbdata = (bridge.sbdata & ~(_WORD << shift)) | (data << shift)
            bridge.sbdata_mask |= _WORD << shift
        if address == DtpDmReg.SBDATA0 and not bridge.sberror:
            launched = self._launch(target, bridge, is_read=False, gated=gated)
        return _DmResponse(), launched

    # --- system bus access -------------------------------------------------------
    def _launch(
        self, target: DtpJtag2AxiTargetCfg, bridge: _Bridge, *, is_read: bool, gated: bool
    ) -> OcahAxiItem | None:
        size = bridge.sbaccess
        # The alignment error takes precedence over the size error.
        if bridge.sbaddr & _mask(size):
            bridge.sberror = _SBERROR_ALIGN
            return None
        if size > target.data_size:
            bridge.sberror = _SBERROR_SIZE
            return None
        offset = bridge.sbaddr & (target.beat_bytes - 1)
        access = _Access(is_read, size, offset)
        if gated:
            self._finish(
                target, bridge, access, resp_error=True, rdata=self._err_slave_beat(target)
            )
            return None
        lanes = _mask(1 << size) << offset
        written = strobe_lanes(lanes)
        if not is_read and (bridge.sbdata_mask << (8 * offset)) & written != written:
            raise DtpJtag2AxiScopeError(
                f"{target.name}: bus write of sbdata bits without a contract"
            )
        bus_data = (bridge.sbdata << (8 * offset)) & _mask(target.data_width)
        protocol = OcahAxiProtocol.AXI4 if target.bus_type == 0 else OcahAxiProtocol.AXI4_LITE
        bridge.inflight = access
        return OcahAxiItem(
            protocol=protocol,
            direction="read" if is_read else "write",
            address=bridge.sbaddr,
            size=size,
            data_words=() if is_read else (bus_data,),
            strobes=() if is_read else (lanes,),
        )

    @staticmethod
    def _err_slave_beat(target: DtpJtag2AxiTargetCfg) -> int:
        return sum(_ERR_SLAVE_WORD << (32 * w) for w in range(target.data_width // 32))

    def _finish(
        self,
        target: DtpJtag2AxiTargetCfg,
        bridge: _Bridge,
        access: _Access,
        *,
        resp_error: bool,
        rdata: int,
    ) -> None:
        bridge.inflight = None
        if not bridge.dmactive:
            return
        if resp_error:
            bridge.sberror = _SBERROR_BUS
        bridge.sbdata = (rdata >> (8 * access.offset)) & _mask(target.data_width)
        bridge.sbdata_mask = _mask(target.data_width) if access.is_read else 0
        if bridge.sbautoincrement:
            bridge.sbaddr = (bridge.sbaddr + (1 << access.size)) & _mask(target.addr_width)

    def _apply_completions(
        self, target: DtpJtag2AxiTargetCfg, bridge: _Bridge, visible_ns: float
    ) -> None:
        while bridge.completed and (bridge.completed[0].end_time_ns or 0) <= visible_ns:
            observed = bridge.completed.popleft()
            # A transaction nothing launched: the scoreboard reports it as unpredicted.
            if bridge.inflight is None:
                continue
            self._finish(
                target,
                bridge,
                bridge.inflight,
                resp_error=observed.resp >= _AXI_RESP_SLVERR,
                rdata=observed.first_data if observed.is_read else 0,
            )


class DtpJtag2AxiTracker:
    """The scan, TCK-event and port streams applied to one ``DtpJtag2AxiModel``.

    Shared by the two JTAG2AXI reference models. A bridge register captures on
    the TCK cycle that leaves Capture-DR and updates on the one that leaves
    Update-DR, whatever the scan shifted in between, and the transaction an
    update launches is returned from ``on_event`` with the bridge's name. Each
    reconstructed scan of a bridge register yields its expected capture on the
    bits it shifted out when the PTAP 3DCR select is clear. The debug disable
    and the response holds of the bridge are read from the TB interface on the
    update cycle.
    """

    def __init__(self, tb_if, *, negative: bool = False) -> None:
        self.tb_if = tb_if
        self.ir = DtpJtagIrModel()
        self.bridges = DtpJtag2AxiModel(negative=negative)
        self._target_by_source: dict[str, str] = {}
        self._sys_rst_seen = 0
        self._tck = 0
        self._prev_step_ns = 0.0
        # The bridge register captured in the DR scan in progress: its value and known bits.
        self._captured: tuple[DtpJtag2AxiTargetCfg, DtpJ2aScanKind, int, int] | None = None
        # (bits, tdi) the scan in progress has shifted so far.
        self._shifted = (0, 0)

    def bind_port(self, target: str, source: str) -> None:
        """Name the monitor whose items carry a bridge's transactions."""
        self._target_by_source[source] = target

    def on_scan(self, item: OcahJtagScanItem) -> DtpJtag2AxiStatusItem:
        """One reconstructed scan; its expected capture, or no contract."""
        expected = DtpJtag2AxiStatusItem(compare=False, time_ns=item.end_time_ns)
        self._sync_reset()
        if item.is_ir:
            self.ir.on_ir_scan(item)
            return expected
        self.ir.on_dr_scan(item)
        if self._captured is None:
            return expected
        target, kind, value, known = self._captured
        self._shifted = (item.bit_count, item.tdi_value)
        if not self.ir.ptap_select_clear():
            return expected
        return DtpJtag2AxiStatusItem(
            target=target.name,
            kind=kind.value,
            expected=value,
            mask=known & _mask(min(item.bit_count, _SCAN_LEN[kind])),
            context=f"{target.name} {kind.name} bits={item.bit_count} tdi=0x{item.tdi_value:x}",
            time_ns=item.end_time_ns,
        )

    def on_event(self, item: OcahJtagEvent) -> tuple[str, OcahAxiItem] | None:
        """One TCK event; the bridge and transaction an update on it launches, if any."""
        self._sync_reset()
        launched = None
        if item.kind == "STEP" and item.trst_n:
            self._tck += 1
            state = self.ir.tap_state()
            if state is OcahJtagState.CAPTURE_DR:
                self._capture()
            elif state is OcahJtagState.UPDATE_DR and self._captured is not None:
                launched = self._update()
            self._prev_step_ns = item.time_ns or 0.0
        self.ir.on_event(item)
        if self.ir.take_tap_reset():
            self._captured = None
        return launched

    def _capture(self) -> None:
        self._captured = None
        self._shifted = (0, 0)
        if not self.ir.ir_known():
            return
        kind, target = self.bridges.classify(self.ir.ir())
        if target is None:
            return
        value, known = self.bridges.capture(target, kind, self._tck)
        self._captured = (target, kind, value, known)

    def _update(self) -> tuple[str, OcahAxiItem] | None:
        """The update stage loads the shift register: the captured value moved down by the
        bits shifted, with the shifted TDI above it."""
        target, kind, captured, known = self._captured
        self._captured = None
        width = _SCAN_LEN[kind]
        bits, tdi = self._shifted
        if bits >= width:
            value, known = (tdi >> (bits - width)) & _mask(width), _mask(width)
        else:
            value = ((captured >> bits) | (tdi << (width - bits))) & _mask(width)
            known = ((known >> bits) | (_mask(bits) << (width - bits))) & _mask(width)
        holds = DtpJ2aHolds(
            b=bool((self.tb_if.sample("j2a_b_hold") >> target.reset_arm_bit) & 0x1),
            r=bool((self.tb_if.sample("j2a_r_hold") >> target.reset_arm_bit) & 0x1),
        )
        access = self.bridges.update(
            target,
            kind,
            value,
            known,
            self._tck,
            self._prev_step_ns,
            gated=bool(self.tb_if.dbg_field(target.dbg_disable_bit)),
            held=holds,
        )
        return None if access is None else (target.name, access)

    def on_axi(self, item: OcahAxiItem) -> None:
        target = self._target_by_source.get(item.source)
        if target is None:
            raise RuntimeError(f"AXI item from unbound port `{item.source}`")
        self.bridges.complete(target, item)

    def _sync_reset(self) -> None:
        """Power-on reset resets the TAP; a system reset resets every bridge."""
        self.ir.sync_power_on_reset(self.tb_if.sample("por_assert_count"))
        if self.ir.take_tap_reset():
            self._captured = None
        sys_rst = self.tb_if.sample("sys_rst_assert_count")
        if sys_rst != self._sys_rst_seen:
            self._sys_rst_seen = sys_rst
            self.bridges.reset()
