# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI bridge model: the JTAG-visible state of the three bridges.

The SMC OTP, SEP OTP and SMC fabric bridges are rebuilt from the decoded DR
scans on the primary TAP and the AXI completions the passive monitors
observed, after the jtag2axi update, capture, and completion rules:

  SINGLE_OP    Update-DR with op READ/WRITE launches one transaction with the
               host-packed address, strobes, and data, and the size limited
               to one full beat, unless an operation is pending (then
               it is rejected: status BUSY_OR_FULL, sticky full). Capture-DR
               presents BUSY_OR_FULL while pending, else the last completion
               status, and the last read data after a read.
  SERIES_CTRL  Update-DR with op != NOP latches op, size (limited to one full
               beat), pipeline depth and address and restarts the read
               budget; the reset bit clears the sticky status. Capture-DR
               presents the sticky status: BUSY_OR_FULL while full, else the
               first series error since the reset bit, else SUCCESS; a system
               reset that discarded a series operation counts as a DECERR
               error. SINGLE_OP completions do not reach it.
  SERIES_DATA  Update-DR launches one transaction at the series address on the
               byte lanes that address selects; a read is issued only within
               the budget of pipeline_depth + 1 per CTRL programming. INCR (or
               the with-status increment bit) advances the address by the
               transfer size on completion.

A gated update (the lifecycle disable of the bridge asserted) changes nothing
but clears the read budget, and a completion while the disable is asserted
leaves the bridge idle and disabled, which drops every request queued behind
it (DTP JTAG document, "Debug Disable": buffered requests are dropped).
A TAP reset resets the JTAG-visible state and leaves the bridge's AXI side
running: every request launched before it and not yet completed stays on the
fabric, and the AXI side consumes its response, so that completion changes no
state and pairs with no later request.
Completions are applied at the capture or update time that follows them, so a
capture during a shift sees the state of its own Capture-DR. Plain class held
by the JTAG2AXI reference models; no reporting. Not modelled: the series
read-data FIFO a SERIES_DATA capture returns (and so the DECERR a system reset
reports for its unread entries), and true request-FIFO backpressure. The
SV-UVM twin is ``dtp_jtag2axi_model``.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from enum import Enum

from ocah_axi_vip import OcahAxiItem, OcahAxiProtocol
from ocah_jtag_vip import OcahJtagScanItem

from .dtp_jtag2axi_status_item import DtpJtag2AxiStatusItem
from .dtp_types import (
    JTAG2AXI_TARGETS,
    DtpJtag2AxiOp,
    DtpJtag2AxiStatus,
    DtpJtag2AxiTargetCfg,
    DtpJtagInstr,
    unpack_series_ctrl,
    unpack_single_op_fields,
)

__all__ = ["DtpJ2aRequest", "DtpJ2aScanKind", "DtpJtag2AxiModel"]

_AXI_RESP_SLVERR = 2
_AXI_RESP_DECERR = 3


class DtpJ2aScanKind(Enum):
    """Which JTAG2AXI register a DR scan addressed, from the active instruction."""

    NONE = "none"
    SINGLE_OP = "single_op"
    SERIES_CTRL = "series_ctrl"
    SERIES_DATA_INCR = "series_data_incr"
    SERIES_DATA_NO_INCR = "series_data_no_incr"
    SERIES_DATA_WITH_STATUS = "series_data_with_status"


_SERIES_DATA = (
    DtpJ2aScanKind.SERIES_DATA_INCR,
    DtpJ2aScanKind.SERIES_DATA_NO_INCR,
    DtpJ2aScanKind.SERIES_DATA_WITH_STATUS,
)


@dataclass(frozen=True)
class DtpJ2aRequest:
    """One decoded JTAG2AXI request: a DR scan's TDI image as the bridge latches it."""

    kind: DtpJ2aScanKind
    op: int = 0
    addr: int = 0
    data: int = 0
    wstrb: int = 0
    size: int = 0
    pipeline_depth: int = 0
    series_reset: bool = False
    incr: bool = False


def _mask(width: int) -> int:
    return (1 << width) - 1


def _instrs(target: DtpJtag2AxiTargetCfg) -> dict[int, DtpJ2aScanKind]:
    return {
        int(DtpJtagInstr[target.single_op_reg]): DtpJ2aScanKind.SINGLE_OP,
        int(DtpJtagInstr[target.series_ctrl_reg]): DtpJ2aScanKind.SERIES_CTRL,
        int(target.series_data_incr_instr): DtpJ2aScanKind.SERIES_DATA_INCR,
        int(target.series_data_no_incr_instr): DtpJ2aScanKind.SERIES_DATA_NO_INCR,
        int(target.series_data_with_status_instr): DtpJ2aScanKind.SERIES_DATA_WITH_STATUS,
    }


_CLASSIFY: dict[int, tuple[DtpJ2aScanKind, DtpJtag2AxiTargetCfg]] = {
    instr: (kind, target)
    for target in JTAG2AXI_TARGETS.values()
    for instr, kind in _instrs(target).items()
}


def classify_instr(ir: int) -> tuple[DtpJ2aScanKind, DtpJtag2AxiTargetCfg | None]:
    """The bridge and register a 6-bit instruction selects; NONE for any other instruction."""
    return _CLASSIFY.get(ir, (DtpJ2aScanKind.NONE, None))


def series_data_bits(kind: DtpJ2aScanKind, size: int) -> int:
    """Shift-register length of a series-data scan under the latched size."""
    return 8 * (1 << size) + (1 if kind is DtpJ2aScanKind.SERIES_DATA_WITH_STATUS else 0)


def container_lane(target: DtpJtag2AxiTargetCfg, addr: int, size: int) -> int:
    """First byte lane of the 2**size-aligned container a narrow transfer at ``addr`` uses.

    Series data rides the AXI byte lanes the current address and
    AXI_SERIES_CTRL.size select (AMBA AXI protocol specification, "Narrow
    transfers"). SINGLE_OP keeps the host-packed strobes and data.
    """
    nbytes = 1 << size
    if nbytes >= target.beat_bytes:
        return 0
    return (addr & ~(nbytes - 1)) % target.beat_bytes


def series_wstrb(target: DtpJtag2AxiTargetCfg, addr: int, size: int) -> int:
    nbytes = 1 << size
    lower = addr % target.beat_bytes
    upper = container_lane(target, addr, size) + min(nbytes, target.beat_bytes) - 1
    return sum(1 << lane for lane in range(lower, upper + 1))


def series_wdata(target: DtpJtag2AxiTargetCfg, data: int, addr: int, size: int) -> int:
    return (data << (8 * container_lane(target, addr, size))) & _mask(target.data_width)


def series_rdata(target: DtpJtag2AxiTargetCfg, word: int, addr: int, size: int) -> int:
    return (
        (word >> (8 * container_lane(target, addr, size)))
        & _mask(8 * (1 << size))
        & _mask(target.data_width)
    )


def strobe_lanes(strb: int) -> int:
    """The data bits of the byte lanes a strobe enables."""
    return sum(0xFF << (8 * lane) for lane in range(8) if (strb >> lane) & 0x1)


def resp_to_status(resp: int) -> DtpJtag2AxiStatus:
    if resp == _AXI_RESP_SLVERR:
        return DtpJtag2AxiStatus.SLVERR
    if resp == _AXI_RESP_DECERR:
        return DtpJtag2AxiStatus.DECERR
    return DtpJtag2AxiStatus.SUCCESS


@dataclass(frozen=True)
class _Issued:
    single: bool
    is_read: bool
    incr: bool
    with_status: bool
    size: int


@dataclass
class _Bridge:
    single_pending: bool = False
    last_single_status: DtpJtag2AxiStatus = DtpJtag2AxiStatus.SUCCESS
    last_single_was_read: bool = False
    last_read_data: int = 0
    series_op: int = int(DtpJtag2AxiOp.NOP)
    series_size: int = 0
    series_pipeline_depth: int = 0
    series_addr: int = 0
    series_reads_pushed: int = 0
    sticky_status: DtpJtag2AxiStatus = DtpJtag2AxiStatus.SUCCESS
    sticky_full: bool = False
    completion_seen: bool = False
    last_completion: float = 0.0
    issued: deque[_Issued] = field(default_factory=deque)
    completed: deque[OcahAxiItem] = field(default_factory=deque)
    # Completions the AXI side consumes after a TAP reset, indexed by is_read.
    orphans: list[int] = field(default_factory=lambda: [0, 0])


class DtpJtag2AxiModel:
    """JTAG-visible state of the three bridges, from decoded scans and observed completions."""

    def __init__(self, settle_window_ns: float = 0.0) -> None:
        # CDC window after a completion during which a capture carries no contract.
        self.settle_window_ns = settle_window_ns
        self._bridges: dict[str, _Bridge] = {}
        self.reset()

    def reset(self) -> None:
        """TAP reset: every bridge back to its TCK-domain reset state.

        The requests launched and not yet completed become orphans of their
        direction: the AXI side consumes their completions.
        """
        prior = self._bridges
        self._bridges = {name: _Bridge() for name in JTAG2AXI_TARGETS}
        for name, old in prior.items():
            for read in (False, True):
                launched = sum(e.is_read == read for e in old.issued)
                landed = sum(c.is_read == read for c in old.completed)
                self._bridges[name].orphans[read] = old.orphans[read] + max(0, launched - landed)

    def abort_in_flight(self, now_ns: float) -> None:
        """System reset: every operation launched and not yet completed is discarded.

        A discarded single or with-status operation reads DECERR on SINGLE_OP;
        a discarded series operation reads DECERR on the sticky status unless
        it already holds a series error. Every other status and the
        SERIES_CTRL configuration keep their values. The reset also clears the
        AXI side, so no orphan of an earlier TAP reset remains. Called at the
        first scan or TAP event after the reset, so every queued completion
        precedes it.
        """
        for name, bridge in self._bridges.items():
            self._apply_completions(name, now_ns)
            single_lost = bridge.single_pending or any(e.with_status for e in bridge.issued)
            series_lost = any(not e.single for e in bridge.issued)
            bridge.issued.clear()
            bridge.orphans = [0, 0]
            bridge.single_pending = False
            bridge.series_reads_pushed = 0
            if single_lost:
                bridge.last_single_status = DtpJtag2AxiStatus.DECERR
                bridge.last_read_data = 0
            if series_lost and bridge.sticky_status is DtpJtag2AxiStatus.SUCCESS:
                bridge.sticky_status = DtpJtag2AxiStatus.DECERR

    def gated(self, target: str) -> None:
        """A gated update changes nothing; the idle, disabled bridge clears its read budget."""
        self._bridges[target].series_reads_pushed = 0

    def decode(
        self, ir: int, scan: OcahJtagScanItem
    ) -> tuple[DtpJ2aScanKind, DtpJtag2AxiTargetCfg | None, DtpJ2aRequest | None]:
        """Which bridge register a DR scan under ``ir`` addressed, and its decoded request.

        NONE when it is none of them or the scan length does not fit the register.
        """
        kind, target = classify_instr(ir)
        none = (DtpJ2aScanKind.NONE, None, None)
        if target is None:
            return none
        tdi = scan.tdi_value
        if kind is DtpJ2aScanKind.SINGLE_OP:
            if scan.bit_count != target.single_op_len:
                return none
            op, size, wstrb, data, addr = unpack_single_op_fields(tdi, target=target)
            return kind, target, DtpJ2aRequest(kind, op, addr, data, wstrb, size)
        if kind is DtpJ2aScanKind.SERIES_CTRL:
            if scan.bit_count != target.series_ctrl_len:
                return none
            series_reset, addr, pipeline_depth, size, op = unpack_series_ctrl(tdi, target=target)
            request = DtpJ2aRequest(
                kind,
                op=op,
                addr=addr,
                size=size,
                pipeline_depth=pipeline_depth,
                series_reset=bool(series_reset),
            )
            return kind, target, request
        size = self._bridges[target.name].series_size
        if scan.bit_count != series_data_bits(kind, size):
            return none
        payload_bits = 8 * (1 << size)
        incr = kind is DtpJ2aScanKind.SERIES_DATA_INCR or (
            kind is DtpJ2aScanKind.SERIES_DATA_WITH_STATUS and bool((tdi >> payload_bits) & 0x1)
        )
        return (
            kind,
            target,
            DtpJ2aRequest(kind, data=tdi & _mask(payload_bits), size=size, incr=incr),
        )

    def update(
        self, target: DtpJtag2AxiTargetCfg, request: DtpJ2aRequest, update_time_ns: float
    ) -> OcahAxiItem | None:
        """Update-DR of a decoded request; the AXI transaction it launches, if any."""
        self._apply_completions(target.name, update_time_ns)
        if request.kind is DtpJ2aScanKind.SINGLE_OP:
            return self._update_single_op(target, request)
        if request.kind is DtpJ2aScanKind.SERIES_CTRL:
            self._update_series_ctrl(target, request)
            return None
        if request.kind in _SERIES_DATA:
            return self._update_series_data(target, request)
        return None

    def complete(self, target: str, observed: OcahAxiItem, *, disabled: bool = False) -> None:
        """An AXI completion on a bridge port, applied at the next capture or update after it.

        An orphan of a TAP reset is consumed and changes nothing. ``disabled``:
        the bridge's lifecycle disable is asserted, so the requests issued
        behind the observed completions are dropped.
        """
        bridge = self._bridges[target]
        if bridge.orphans[observed.is_read]:
            bridge.orphans[observed.is_read] -= 1
            return
        bridge.completed.append(observed)
        if not disabled:
            return
        while len(bridge.issued) > len(bridge.completed):
            bridge.issued.pop()

    def predict_capture(
        self,
        target: DtpJtag2AxiTargetCfg,
        kind: DtpJ2aScanKind,
        capture_time_ns: float,
        context: str,
    ) -> DtpJtag2AxiStatusItem:
        """Expected capture of a SINGLE_OP or SERIES_CTRL scan whose Capture-DR was at
        ``capture_time_ns``.

        A completion inside the settle window before it has not crossed into
        the TCK domain yet, so the capture carries no contract.
        """
        name = target.name
        self._apply_completions(name, capture_time_ns)
        bridge = self._bridges[name]
        compare = not (
            bridge.completion_seen
            and capture_time_ns - bridge.last_completion < self.settle_window_ns
        )
        if kind is DtpJ2aScanKind.SINGLE_OP:
            status = (
                DtpJtag2AxiStatus.BUSY_OR_FULL
                if bridge.single_pending
                else bridge.last_single_status
            )
            compare_rdata = (
                not bridge.single_pending
                and bridge.last_single_was_read
                and bridge.last_single_status is DtpJtag2AxiStatus.SUCCESS
            )
            mask = _mask(target.data_width)
            return DtpJtag2AxiStatusItem(
                compare=compare,
                target=name,
                kind=kind.name,
                status=status,
                compare_rdata=compare_rdata,
                rdata=bridge.last_read_data & mask,
                rdata_mask=mask,
                context=context,
                time_ns=capture_time_ns,
            )
        status = DtpJtag2AxiStatus.BUSY_OR_FULL if bridge.sticky_full else bridge.sticky_status
        return DtpJtag2AxiStatusItem(
            compare=compare,
            target=name,
            kind=kind.name,
            status=status,
            context=context,
            time_ns=capture_time_ns,
        )

    # --- update rules -------------------------------------------------------------
    def _update_single_op(
        self, target: DtpJtag2AxiTargetCfg, request: DtpJ2aRequest
    ) -> OcahAxiItem | None:
        bridge = self._bridges[target.name]
        if request.op not in (int(DtpJtag2AxiOp.READ), int(DtpJtag2AxiOp.WRITE)):
            return None
        if bridge.single_pending:
            # Rejected: the prior operation completes regardless and then
            # overwrites this status.
            bridge.sticky_full = True
            bridge.last_single_status = DtpJtag2AxiStatus.BUSY_OR_FULL
            bridge.single_pending = False
            return None
        is_read = request.op == int(DtpJtag2AxiOp.READ)
        size = target.axsize(request.size)
        bridge.single_pending = True
        bridge.last_single_was_read = is_read
        bridge.issued.append(_Issued(True, is_read, False, False, size))
        if is_read:
            return self._make_item(target, "read", request.addr, size)
        return self._make_item(
            target,
            "write",
            request.addr,
            size,
            data=request.data & _mask(target.data_width),
            wstrb=request.wstrb & _mask(target.wstrb_bits),
        )

    def _update_series_ctrl(self, target: DtpJtag2AxiTargetCfg, request: DtpJ2aRequest) -> None:
        bridge = self._bridges[target.name]
        if request.op != int(DtpJtag2AxiOp.NOP):
            bridge.series_op = request.op
            bridge.series_size = target.axsize(request.size)
            # Series read requests one CTRL programming may enqueue: pl_depth
            # + 1, where pl_depth ranges up to the bridge's rd_pl_depth (PTAP
            # document, "*_AXI_SERIES_CTRL").
            bridge.series_pipeline_depth = min(request.pipeline_depth, target.rd_pl_depth)
            bridge.series_addr = request.addr & _mask(target.addr_width)
            bridge.series_reads_pushed = 0
        if request.series_reset:
            bridge.sticky_status = DtpJtag2AxiStatus.SUCCESS
            bridge.sticky_full = False

    def _update_series_data(
        self, target: DtpJtag2AxiTargetCfg, request: DtpJ2aRequest
    ) -> OcahAxiItem | None:
        bridge = self._bridges[target.name]
        size = bridge.series_size
        addr = bridge.series_addr
        with_status = request.kind is DtpJ2aScanKind.SERIES_DATA_WITH_STATUS
        if bridge.series_op == int(DtpJtag2AxiOp.WRITE):
            bridge.issued.append(_Issued(False, False, request.incr, with_status, size))
            return self._make_item(
                target,
                "write",
                addr,
                size,
                data=series_wdata(target, request.data, addr, size),
                wstrb=series_wstrb(target, addr, size),
            )
        if bridge.series_op == int(DtpJtag2AxiOp.READ):
            # Past the budget the bridge drops the push silently.
            if bridge.series_reads_pushed >= bridge.series_pipeline_depth + 1:
                return None
            if not with_status:
                bridge.series_reads_pushed += 1
            bridge.issued.append(_Issued(False, True, request.incr, with_status, size))
            return self._make_item(target, "read", addr, size)
        return None

    @staticmethod
    def _make_item(
        target: DtpJtag2AxiTargetCfg,
        direction: str,
        addr: int,
        size: int,
        *,
        data: int | None = None,
        wstrb: int | None = None,
    ) -> OcahAxiItem:
        """One single-beat expected transaction."""
        protocol = OcahAxiProtocol.AXI4 if target.bus_type == 0 else OcahAxiProtocol.AXI4_LITE
        return OcahAxiItem(
            protocol=protocol,
            direction=direction,
            address=addr & _mask(target.addr_width),
            size=size,
            data_words=() if data is None else (data,),
            strobes=() if wstrb is None else (wstrb,),
        )

    # --- completion rules ---------------------------------------------------------
    def _apply_completions(self, name: str, before_ns: float) -> None:
        bridge = self._bridges[name]
        while bridge.completed and (bridge.completed[0].end_time_ns or 0) <= before_ns:
            self._apply_completion(name, bridge.completed.popleft())

    def _apply_completion(self, name: str, observed: OcahAxiItem) -> None:
        target = JTAG2AXI_TARGETS[name]
        bridge = self._bridges[name]
        status = resp_to_status(observed.resp)
        bridge.completion_seen = True
        bridge.last_completion = float(observed.end_time_ns or 0)
        # A completion nothing launched: the scoreboard reports it as an
        # unpredicted transaction; the bridge state has no entry to update.
        if not bridge.issued:
            return
        issued = bridge.issued.popleft()
        if not issued.single and bridge.sticky_status is DtpJtag2AxiStatus.SUCCESS:
            bridge.sticky_status = status
        if issued.single or issued.with_status:
            bridge.last_single_status = status
        if issued.single:
            bridge.single_pending = False
            if issued.is_read:
                bridge.last_read_data = observed.first_data & _mask(target.data_width)
        elif issued.with_status and issued.is_read:
            bridge.last_read_data = series_rdata(
                target, observed.first_data, observed.address, issued.size
            )
        if not issued.single and issued.incr:
            bridge.series_addr = (bridge.series_addr + (1 << issued.size)) & _mask(
                target.addr_width
            )
