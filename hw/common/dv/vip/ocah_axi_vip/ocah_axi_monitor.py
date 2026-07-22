# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Passive OCAH AXI4 and AXI4-Lite monitors."""

from __future__ import annotations

import logging
from collections import deque
from collections.abc import Callable
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotbext.axi import AxiBus, AxiLiteBus

from .ocah_axi_item import OcahAxiItem
from .results import RESP_OKAY

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

    async def stop(self) -> None:
        """Stop passive monitoring."""
        self._running = False
        if self._task is not None:
            self._task.kill()
            self._task = None
        self.log.info("%s: monitoring stopped", self.name)

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
        return {"items": len(self._history), "write_transactions": writes, "read_transactions": reads}

    def _publish(self, item: OcahAxiItem) -> None:
        self._history.append(item)
        if len(self._history) > self._max_history:
            self._history.pop(0)

        callbacks = list(self._item_callbacks)
        callbacks += self._write_callbacks if item.is_write else self._read_callbacks
        for callback in callbacks:
            try:
                callback(item)
            except Exception as exc:  # noqa: BLE001
                self.log.error("Exception in monitor callback %s: %s", callback, exc)

    async def _run(self) -> None:
        raise NotImplementedError


class OcahAxiMonitor(_BaseMonitor):
    """Passive AXI4 monitor that emits `OcahAxiItem` objects."""

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

    async def _run(self) -> None:
        pending_aw: deque[dict[str, int]] = deque()
        pending_w: deque[list[dict[str, int]]] = deque()
        pending_ar: deque[dict[str, int]] = deque()
        current_w: list[dict[str, int]] = []
        current_r: list[dict[str, int]] = []

        while self._running:
            await RisingEdge(self.clock)
            await ReadOnly()

            aw = self.bus.write.aw
            w = self.bus.write.w
            b = self.bus.write.b
            ar = self.bus.read.ar
            r = self.bus.read.r

            if _handshake(aw, "awvalid", "awready"):
                pending_aw.append(
                    {
                        "address": _sig_int(aw, "awaddr"),
                        "id": _sig_int(aw, "awid"),
                        "size": _sig_int(aw, "awsize"),
                        "burst": _sig_int(aw, "awburst"),
                        "prot": _sig_int(aw, "awprot"),
                        "length": _sig_int(aw, "awlen") + 1,
                    }
                )

            if _handshake(w, "wvalid", "wready"):
                current_w.append(
                    {
                        "data": _sig_int(w, "wdata"),
                        "strb": _sig_int(w, "wstrb", -1),
                        "last": _sig_int(w, "wlast", 1),
                    }
                )
                if current_w[-1]["last"]:
                    pending_w.append(current_w)
                    current_w = []

            if _handshake(b, "bvalid", "bready"):
                aw_info = pending_aw.popleft() if pending_aw else {}
                beats = pending_w.popleft() if pending_w else []
                item = OcahAxiItem.write(
                    protocol="axi4",
                    address=aw_info.get("address", 0),
                    data_words=[beat["data"] for beat in beats],
                    strobes=[beat["strb"] for beat in beats if beat["strb"] >= 0],
                    resp_list=(_sig_int(b, "bresp", RESP_OKAY),),
                    source=self.name,
                    transaction_id=_sig_int(b, "bid", aw_info.get("id", 0)),
                    size=aw_info.get("size"),
                    burst=aw_info.get("burst"),
                    prot=aw_info.get("prot", 0),
                    metadata={"expected_beats": aw_info.get("length", len(beats))},
                )
                self._publish(item)

            if _handshake(ar, "arvalid", "arready"):
                pending_ar.append(
                    {
                        "address": _sig_int(ar, "araddr"),
                        "id": _sig_int(ar, "arid"),
                        "size": _sig_int(ar, "arsize"),
                        "burst": _sig_int(ar, "arburst"),
                        "prot": _sig_int(ar, "arprot"),
                        "length": _sig_int(ar, "arlen") + 1,
                    }
                )

            if _handshake(r, "rvalid", "rready"):
                current_r.append(
                    {
                        "data": _sig_int(r, "rdata"),
                        "resp": _sig_int(r, "rresp", RESP_OKAY),
                        "last": _sig_int(r, "rlast", 1),
                    }
                )
                if current_r[-1]["last"]:
                    ar_info = pending_ar.popleft() if pending_ar else {}
                    item = OcahAxiItem.read(
                        protocol="axi4",
                        address=ar_info.get("address", 0),
                        data_words=[beat["data"] for beat in current_r],
                        resp_list=[beat["resp"] for beat in current_r],
                        source=self.name,
                        transaction_id=_sig_int(r, "rid", ar_info.get("id", 0)),
                        size=ar_info.get("size"),
                        burst=ar_info.get("burst"),
                        prot=ar_info.get("prot", 0),
                        metadata={"expected_beats": ar_info.get("length", len(current_r))},
                    )
                    current_r = []
                    self._publish(item)


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

    async def _run(self) -> None:
        pending_aw: deque[dict[str, int]] = deque()
        pending_w: deque[dict[str, int]] = deque()
        pending_ar: deque[dict[str, int]] = deque()

        while self._running:
            await RisingEdge(self.clock)
            await ReadOnly()

            aw = self.bus.write.aw
            w = self.bus.write.w
            b = self.bus.write.b
            ar = self.bus.read.ar
            r = self.bus.read.r

            if _handshake(aw, "awvalid", "awready"):
                pending_aw.append({"address": _sig_int(aw, "awaddr"), "prot": _sig_int(aw, "awprot")})

            if _handshake(w, "wvalid", "wready"):
                pending_w.append({"data": _sig_int(w, "wdata"), "strb": _sig_int(w, "wstrb", -1)})

            if _handshake(b, "bvalid", "bready"):
                aw_info = pending_aw.popleft() if pending_aw else {}
                w_info = pending_w.popleft() if pending_w else {}
                item = OcahAxiItem.write(
                    protocol="axi4-lite",
                    address=aw_info.get("address", 0),
                    data_words=(w_info.get("data", 0),),
                    strobes=() if w_info.get("strb", -1) < 0 else (w_info.get("strb", 0),),
                    resp_list=(_sig_int(b, "bresp", RESP_OKAY),),
                    source=self.name,
                    prot=aw_info.get("prot", 0),
                )
                self._publish(item)

            if _handshake(ar, "arvalid", "arready"):
                pending_ar.append({"address": _sig_int(ar, "araddr"), "prot": _sig_int(ar, "arprot")})

            if _handshake(r, "rvalid", "rready"):
                ar_info = pending_ar.popleft() if pending_ar else {}
                item = OcahAxiItem.read(
                    protocol="axi4-lite",
                    address=ar_info.get("address", 0),
                    data_words=(_sig_int(r, "rdata"),),
                    resp_list=(_sig_int(r, "rresp", RESP_OKAY),),
                    source=self.name,
                    prot=ar_info.get("prot", 0),
                )
                self._publish(item)
