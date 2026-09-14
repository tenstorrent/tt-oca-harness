# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive OCAH AXI4 and AXI4-Lite monitors."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from cocotbext.axi import AxiBus, AxiLiteBus

from .ocah_axi_item import OcahAxiItem
from .ocah_axi_types import RESP_OKAY

__all__ = ["OcahAxiMonitor", "OcahAxiLiteMonitor"]

_TRANSACTION_HISTORY_MAX = 2000


def _sig_int(obj, name: str, default: int = 0) -> int:
    sig = getattr(obj, name, None)
    if sig is None:
        return default
    try:
        return int(sig.value)
    except Exception:  # noqa: BLE001 - simulator handles may be unresolved
        return default


def _handshake(obj, valid_name: str, ready_name: str) -> bool:
    return bool(_sig_int(obj, valid_name) and _sig_int(obj, ready_name))


def _now_ns() -> int:
    return int(get_sim_time("ns"))


class _BaseMonitor:
    def __init__(self, *, name: str, max_history: int) -> None:
        self.name = name
        self.log = logging.getLogger(name)
        self._max_history = max_history
        self._history: list[OcahAxiItem] = []
        self._write_callbacks: list[Callable[[OcahAxiItem], None]] = []
        self._read_callbacks: list[Callable[[OcahAxiItem], None]] = []
        self._item_callbacks: list[Callable[[OcahAxiItem], None]] = []
        self._task = None
        self._running = False
        self._activity = {"aw": 0, "w": 0, "ar": 0}
        self._resp_credits: list[dict[str, Any]] = []
        self.expected_resp_seen = 0
        self.unexpected_error_count = 0
        # Responses that completed with no matching request phase. These are
        # protocol-integrity findings, never published as transactions; the
        # owning scoreboard fails them at drain (CHK-AXI-DRAIN).
        self.orphan_responses = 0
        # Non-assertion exceptions swallowed from callbacks (assertion
        # failures re-raise and kill the sampling task loudly instead); also
        # enforced at drain.
        self.callback_errors = 0

    def add_write_callback(self, fn: Callable[[OcahAxiItem], None]) -> None:
        """Register a callback for completed write items."""
        self._write_callbacks.append(fn)

    def add_read_callback(self, fn: Callable[[OcahAxiItem], None]) -> None:
        """Register a callback for completed read items."""
        self._read_callbacks.append(fn)

    def add_item_callback(self, fn: Callable[[OcahAxiItem], None]) -> None:
        """Register a callback for every completed item."""
        self._item_callbacks.append(fn)

    async def start(self) -> None:
        """Start passive monitoring."""
        if self._running:
            return
        self._running = True
        self._task = cocotb.start_soon(self._run())
        self.log.info("%s: monitoring started", self.name)

    def halt(self) -> None:
        """Synchronously stop sampling; in-flight state is retained.

        Callable from synchronous phases (e.g. a scoreboard's check_phase)
        so no callback can arrive after finalization. Drain checks still see
        requests that never completed.
        """
        self._running = False
        if self._task is not None:
            self._task.kill()
            self._task = None
        pending = self.pending_transactions()
        if any(pending.values()):
            self.log.warning("%s: halted with in-flight transactions %s", self.name, pending)
        self.log.info("%s: monitoring stopped", self.name)

    async def stop(self) -> None:
        """Stop passive monitoring (async wrapper around halt())."""
        self.halt()

    def get_items(self) -> list[OcahAxiItem]:
        """Return all retained items."""
        return list(self._history)

    def get_write_transactions(self) -> list[OcahAxiItem]:
        """Return retained write items."""
        return [item for item in self._history if item.is_write]

    def get_read_transactions(self) -> list[OcahAxiItem]:
        """Return retained read items."""
        return [item for item in self._history if item.is_read]

    def clear_history(self) -> None:
        """Discard retained item history."""
        self._history.clear()

    def get_statistics(self) -> dict[str, int]:
        """Return monitor transaction counts."""
        writes = sum(1 for item in self._history if item.is_write)
        reads = sum(1 for item in self._history if item.is_read)
        return {
            "items": len(self._history),
            "write_transactions": writes,
            "read_transactions": reads,
            "callback_errors": self.callback_errors,
        }

    def get_request_activity(self) -> dict[str, int]:
        """Return request-channel VALID-high CYCLE counts since start.

        Per-cycle counting (matching the DTP tb pulse counters): back-to-back
        requests with VALID held continuously are still counted every cycle,
        so no-activity windows cannot be fooled by a merged VALID pulse.
        """
        return dict(self._activity)

    def pending_transactions(self) -> dict[str, int]:
        """Return in-flight request counts awaiting their completion phase.

        Nonzero after traffic stops means an accepted request never received
        its B/R completion; the scoreboard fails this at drain.
        """
        raise NotImplementedError

    def arm_expected_resp(
        self,
        resp: int,
        count: int = 1,
        *,
        direction: str | None = None,
    ) -> None:
        """Mark the next ``count`` matching non-OKAY completions as expected.

        Monitor-local tally only (``expected_resp_seen`` /
        ``unexpected_error_count``); scoreboard classification authority comes
        exclusively from the scoreboard's own credits and reference model.
        """
        self._resp_credits.append(
            {"resp": int(resp), "remaining": int(count), "direction": direction}
        )
        self.log.info(
            "%s: armed expected resp=%d count=%d direction=%s",
            self.name,
            int(resp),
            count,
            direction or "-",
        )

    def _track_activity(self, channel: str, valid: int) -> None:
        if valid:
            self._activity[channel] += 1

    def _classify_resp(self, item: OcahAxiItem) -> None:
        if item.resp == RESP_OKAY:
            return
        for credit in self._resp_credits:
            if credit["remaining"] <= 0:
                continue
            if credit["resp"] != item.resp:
                continue
            if credit["direction"] is not None and credit["direction"] != item.direction:
                continue
            credit["remaining"] -= 1
            item.metadata["expected_resp"] = credit["resp"]
            self.expected_resp_seen += 1
            return
        self.unexpected_error_count += 1

    def _record_orphan(self, channel: str, detail: str) -> None:
        self.orphan_responses += 1
        self.log.error(
            "%s: orphan %s response (no matching request phase): %s",
            self.name,
            channel,
            detail,
        )

    def _publish(self, item: OcahAxiItem) -> None:
        self._classify_resp(item)
        self._history.append(item)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        callbacks = list(self._item_callbacks)
        callbacks += self._write_callbacks if item.is_write else self._read_callbacks
        for callback in callbacks:
            try:
                callback(item)
            except AssertionError:
                # A checker/scoreboard assertion is a test verdict, never
                # something to swallow: re-raise so the failure is loud
                # (retained findings still exist for aggregate mode).
                raise
            except Exception as exc:  # noqa: BLE001
                self.callback_errors += 1
                self.log.error("Exception in monitor callback %s: %s", callback, exc)

    async def _run(self) -> None:
        raise NotImplementedError


class OcahAxiMonitor(_BaseMonitor):
    """Passive AXI4 monitor that emits `OcahAxiItem` objects.

    Outstanding transactions are paired by ID: read data beats accumulate per
    RID against per-ARID address queues, and completed write bursts are matched
    to BID responses. Single-ID traffic behaves identically to FIFO pairing.
    A completion with no matching request phase is retained as an orphan
    finding (never published as a transaction).
    """

    def __init__(
        self,
        axi4_intf,
        clock,
        *,
        name: str = "OcahAxiMonitor",
        max_history: int = _TRANSACTION_HISTORY_MAX,
        prefix: str | None = None,
    ) -> None:
        super().__init__(name=name, max_history=max_history)
        self.clock = clock
        self.bus = self._coerce_bus(axi4_intf, prefix)
        self._pending_aw: deque[dict[str, int]] = deque()
        self._pending_wburst: deque[list[dict[str, int]]] = deque()
        self._paired_wr: dict[int, deque[tuple[dict[str, int], list[dict[str, int]]]]] = {}
        self._pending_ar: dict[int, deque[dict[str, int]]] = {}
        self._current_w: list[dict[str, int]] = []
        self._current_r: dict[int, list[dict[str, int]]] = {}
        # Read bursts whose first data beat arrived BEFORE any AR for that ID:
        # a protocol violation retained as an orphan even if an AR shows up
        # before RLAST.
        self._r_no_ar: dict[int, bool] = {}
        # Responder-processing order: writes take their slot when the data
        # burst completes (pairing), reads when RLAST arrives. Lets the
        # scoreboard replay shadow-memory commits in data order even when B
        # responses legally reorder across IDs.
        self._commit_seq = 0

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, **kwargs: Any) -> "OcahAxiMonitor":
        """Construct from flattened AXI signals."""
        return cls(dut, clock, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(axi4_intf, prefix: str | None):
        if isinstance(axi4_intf, AxiBus):
            return axi4_intf
        if prefix is not None:
            return AxiBus.from_prefix(axi4_intf, prefix)
        return AxiBus.from_entity(axi4_intf)

    def pending_transactions(self) -> dict[str, int]:
        return {
            "write": (
                len(self._pending_aw)
                + len(self._pending_wburst)
                + (1 if self._current_w else 0)
                + sum(len(queue) for queue in self._paired_wr.values())
            ),
            "read": (
                sum(len(queue) for queue in self._pending_ar.values())
                + sum(1 for beats in self._current_r.values() if beats)
            ),
        }

    async def _run(self) -> None:
        while self._running:
            await RisingEdge(self.clock)
            await ReadOnly()

            aw = self.bus.write.aw
            w = self.bus.write.w
            b = self.bus.write.b
            ar = self.bus.read.ar
            r = self.bus.read.r

            self._track_activity("aw", _sig_int(aw, "awvalid"))
            self._track_activity("w", _sig_int(w, "wvalid"))
            self._track_activity("ar", _sig_int(ar, "arvalid"))

            if _handshake(aw, "awvalid", "awready"):
                self._pending_aw.append(
                    {
                        "address": _sig_int(aw, "awaddr"),
                        "id": _sig_int(aw, "awid"),
                        "size": _sig_int(aw, "awsize"),
                        "burst": _sig_int(aw, "awburst"),
                        "prot": _sig_int(aw, "awprot"),
                        "length": _sig_int(aw, "awlen") + 1,
                        "start_ns": _now_ns(),
                    }
                )

            if _handshake(w, "wvalid", "wready"):
                self._current_w.append(
                    {
                        "data": _sig_int(w, "wdata"),
                        "strb": _sig_int(w, "wstrb", -1),
                        "last": _sig_int(w, "wlast", 1),
                    }
                )
                if self._current_w[-1]["last"]:
                    self._pending_wburst.append(self._current_w)
                    self._current_w = []

            # AXI4 mandates W-burst order matches AW order, so pair the oldest
            # accepted AW with the oldest completed W burst; the pair then waits
            # keyed by AWID for its B response (which may complete out of order).
            while self._pending_aw and self._pending_wburst:
                aw_info = self._pending_aw.popleft()
                beats = self._pending_wburst.popleft()
                aw_info["order"] = self._commit_seq
                self._commit_seq += 1
                self._paired_wr.setdefault(aw_info["id"], deque()).append((aw_info, beats))

            if _handshake(b, "bvalid", "bready"):
                bid = _sig_int(b, "bid", 0)
                per_id = self._paired_wr.get(bid)
                if per_id:
                    aw_info, beats = per_id.popleft()
                    item = OcahAxiItem.write(
                        protocol="axi4",
                        address=aw_info["address"],
                        data_words=[beat["data"] for beat in beats],
                        strobes=[beat["strb"] for beat in beats if beat["strb"] >= 0],
                        resp_list=(_sig_int(b, "bresp", RESP_OKAY),),
                        source=self.name,
                        transaction_id=bid,
                        size=aw_info["size"],
                        burst=aw_info["burst"],
                        prot=aw_info["prot"],
                        start_time_ns=aw_info["start_ns"],
                        end_time_ns=_now_ns(),
                        metadata={
                            "expected_beats": aw_info["length"],
                            "commit_order": aw_info["order"],
                        },
                    )
                    self._publish(item)
                else:
                    self._record_orphan(
                        "B",
                        f"bid=0x{bid:x} bresp={_sig_int(b, 'bresp', RESP_OKAY)} time={_now_ns()}ns",
                    )

            if _handshake(ar, "arvalid", "arready"):
                ar_info = {
                    "address": _sig_int(ar, "araddr"),
                    "id": _sig_int(ar, "arid"),
                    "size": _sig_int(ar, "arsize"),
                    "burst": _sig_int(ar, "arburst"),
                    "prot": _sig_int(ar, "arprot"),
                    "length": _sig_int(ar, "arlen") + 1,
                    "start_ns": _now_ns(),
                }
                self._pending_ar.setdefault(ar_info["id"], deque()).append(ar_info)

            if _handshake(r, "rvalid", "rready"):
                rid = _sig_int(r, "rid", 0)
                beats = self._current_r.setdefault(rid, [])
                beats.append(
                    {
                        "data": _sig_int(r, "rdata"),
                        "resp": _sig_int(r, "rresp", RESP_OKAY),
                        "last": _sig_int(r, "rlast", 1),
                    }
                )
                if len(beats) == 1 and not self._pending_ar.get(rid):
                    # Read DATA began before any AR for this ID: protocol
                    # violation. The burst stays tainted even if an AR
                    # arrives before RLAST.
                    self._r_no_ar[rid] = True
                if beats[-1]["last"]:
                    per_id = self._pending_ar.get(rid)
                    tainted = self._r_no_ar.pop(rid, False)
                    if tainted:
                        # The late AR (if any) stays pending so the drain
                        # check also flags the never-served request.
                        self._record_orphan(
                            "R",
                            f"rid=0x{rid:x} beats={len(beats)} data began "
                            f"before AR time={_now_ns()}ns",
                        )
                    elif per_id:
                        ar_info = per_id.popleft()
                        item = OcahAxiItem.read(
                            protocol="axi4",
                            address=ar_info["address"],
                            data_words=[beat["data"] for beat in beats],
                            resp_list=[beat["resp"] for beat in beats],
                            source=self.name,
                            transaction_id=rid,
                            size=ar_info["size"],
                            burst=ar_info["burst"],
                            prot=ar_info["prot"],
                            start_time_ns=ar_info["start_ns"],
                            end_time_ns=_now_ns(),
                            metadata={
                                "expected_beats": ar_info["length"],
                                "commit_order": self._commit_seq,
                            },
                        )
                        self._commit_seq += 1
                        self._publish(item)
                    else:
                        self._record_orphan(
                            "R",
                            f"rid=0x{rid:x} beats={len(beats)} time={_now_ns()}ns",
                        )
                    self._current_r[rid] = []


class OcahAxiLiteMonitor(_BaseMonitor):
    """Passive AXI4-Lite monitor that emits `OcahAxiItem` objects."""

    def __init__(
        self,
        axi4_lite_intf,
        clock,
        *,
        name: str = "OcahAxiLiteMonitor",
        max_history: int = _TRANSACTION_HISTORY_MAX,
        prefix: str | None = None,
    ) -> None:
        super().__init__(name=name, max_history=max_history)
        self.clock = clock
        self.bus = self._coerce_bus(axi4_lite_intf, prefix)
        self._pending_aw: deque[dict[str, int]] = deque()
        self._pending_w: deque[dict[str, int]] = deque()
        self._pending_ar: deque[dict[str, int]] = deque()
        # In-order protocol: sequential commit slot assigned at publish.
        self._commit_seq = 0

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, **kwargs: Any) -> "OcahAxiLiteMonitor":
        """Construct from flattened AXI4-Lite signals."""
        return cls(dut, clock, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(axi4_lite_intf, prefix: str | None):
        if isinstance(axi4_lite_intf, AxiLiteBus):
            return axi4_lite_intf
        if prefix is not None:
            return AxiLiteBus.from_prefix(axi4_lite_intf, prefix)
        return AxiLiteBus.from_entity(axi4_lite_intf)

    def pending_transactions(self) -> dict[str, int]:
        return {
            "write": max(len(self._pending_aw), len(self._pending_w)),
            "read": len(self._pending_ar),
        }

    async def _run(self) -> None:
        while self._running:
            await RisingEdge(self.clock)
            await ReadOnly()

            aw = self.bus.write.aw
            w = self.bus.write.w
            b = self.bus.write.b
            ar = self.bus.read.ar
            r = self.bus.read.r

            self._track_activity("aw", _sig_int(aw, "awvalid"))
            self._track_activity("w", _sig_int(w, "wvalid"))
            self._track_activity("ar", _sig_int(ar, "arvalid"))

            if _handshake(aw, "awvalid", "awready"):
                self._pending_aw.append(
                    {
                        "address": _sig_int(aw, "awaddr"),
                        "prot": _sig_int(aw, "awprot"),
                        "start_ns": _now_ns(),
                    }
                )

            if _handshake(w, "wvalid", "wready"):
                # A write takes its commit slot when its DATA is accepted:
                # that is the responder's processing order.
                self._pending_w.append(
                    {
                        "data": _sig_int(w, "wdata"),
                        "strb": _sig_int(w, "wstrb", -1),
                        "order": self._commit_seq,
                    }
                )
                self._commit_seq += 1

            if _handshake(b, "bvalid", "bready"):
                if self._pending_aw and self._pending_w:
                    aw_info = self._pending_aw.popleft()
                    w_info = self._pending_w.popleft()
                    item = OcahAxiItem.write(
                        protocol="axi4-lite",
                        address=aw_info["address"],
                        data_words=(w_info["data"],),
                        strobes=() if w_info["strb"] < 0 else (w_info["strb"],),
                        resp_list=(_sig_int(b, "bresp", RESP_OKAY),),
                        source=self.name,
                        prot=aw_info["prot"],
                        start_time_ns=aw_info["start_ns"],
                        end_time_ns=_now_ns(),
                        metadata={"commit_order": w_info["order"]},
                    )
                    self._publish(item)
                else:
                    self._record_orphan(
                        "B",
                        f"bresp={_sig_int(b, 'bresp', RESP_OKAY)} "
                        f"aw_pending={len(self._pending_aw)} "
                        f"w_pending={len(self._pending_w)} time={_now_ns()}ns",
                    )

            if _handshake(ar, "arvalid", "arready"):
                # A read takes its commit slot when the ADDRESS is accepted:
                # that is when the responder processes it.
                self._pending_ar.append(
                    {
                        "address": _sig_int(ar, "araddr"),
                        "prot": _sig_int(ar, "arprot"),
                        "start_ns": _now_ns(),
                        "order": self._commit_seq,
                    }
                )
                self._commit_seq += 1

            if _handshake(r, "rvalid", "rready"):
                if self._pending_ar:
                    ar_info = self._pending_ar.popleft()
                    item = OcahAxiItem.read(
                        protocol="axi4-lite",
                        address=ar_info["address"],
                        data_words=(_sig_int(r, "rdata"),),
                        resp_list=(_sig_int(r, "rresp", RESP_OKAY),),
                        source=self.name,
                        prot=ar_info["prot"],
                        start_time_ns=ar_info["start_ns"],
                        end_time_ns=_now_ns(),
                        metadata={"commit_order": ar_info["order"]},
                    )
                    self._publish(item)
                else:
                    self._record_orphan(
                        "R",
                        f"rresp={_sig_int(r, 'rresp', RESP_OKAY)} time={_now_ns()}ns",
                    )
