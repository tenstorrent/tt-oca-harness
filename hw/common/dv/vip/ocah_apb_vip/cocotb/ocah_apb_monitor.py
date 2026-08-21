# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive OCAH APB monitor."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

import cocotb
from cocotb.triggers import ReadOnly, RisingEdge
from cocotbext.axi import ApbBus

from .ocah_apb_item import OcahApbItem

_TRANSACTION_HISTORY_MAX = 2000


def _sig_int(obj, name: str, default: int = 0) -> int:
    sig = getattr(obj, name, None)
    if sig is None:
        return default
    try:
        return int(sig.value)
    except Exception:  # noqa: BLE001
        return default


class OcahApbMonitor:
    """Passive APB monitor that emits `OcahApbItem` objects."""

    def __init__(
        self,
        apb_intf,
        clock,
        *,
        name: str = "OcahApbMonitor",
        max_history: int = _TRANSACTION_HISTORY_MAX,
        prefix: str | None = None,
    ) -> None:
        self.name = name
        self.clock = clock
        self.bus = self._coerce_bus(apb_intf, prefix)
        self.log = logging.getLogger(name)
        self._max_history = max_history
        self._history: list[OcahApbItem] = []
        self._callbacks: list[Callable[[OcahApbItem], None]] = []
        self._read_callbacks: list[Callable[[OcahApbItem], None]] = []
        self._write_callbacks: list[Callable[[OcahApbItem], None]] = []
        self._task = None
        self._running = False

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, **kwargs: Any) -> "OcahApbMonitor":
        """Construct from flattened APB signals."""
        return cls(dut, clock, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(apb_intf, prefix: str | None):
        if isinstance(apb_intf, ApbBus):
            return apb_intf
        if prefix is not None:
            return ApbBus.from_prefix(apb_intf, prefix)
        return ApbBus.from_entity(apb_intf)

    def add_item_callback(self, fn: Callable[[OcahApbItem], None]) -> None:
        self._callbacks.append(fn)

    def add_read_callback(self, fn: Callable[[OcahApbItem], None]) -> None:
        self._read_callbacks.append(fn)

    def add_write_callback(self, fn: Callable[[OcahApbItem], None]) -> None:
        self._write_callbacks.append(fn)

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

    def get_items(self) -> list[OcahApbItem]:
        return list(self._history)

    def get_read_transactions(self) -> list[OcahApbItem]:
        return [item for item in self._history if item.is_read]

    def get_write_transactions(self) -> list[OcahApbItem]:
        return [item for item in self._history if item.is_write]

    def clear_history(self) -> None:
        self._history.clear()

    def get_statistics(self) -> dict[str, int]:
        writes = sum(1 for item in self._history if item.is_write)
        reads = sum(1 for item in self._history if item.is_read)
        return {"items": len(self._history), "write_transactions": writes, "read_transactions": reads}

    async def _run(self) -> None:
        wait_cycles = 0
        in_access = False

        while self._running:
            await RisingEdge(self.clock)
            await ReadOnly()

            psel = _sig_int(self.bus, "psel")
            penable = _sig_int(self.bus, "penable")
            pready = _sig_int(self.bus, "pready")

            if psel and penable and not pready:
                wait_cycles += 1
                in_access = True
                continue

            if psel and penable and pready:
                is_write = bool(_sig_int(self.bus, "pwrite"))
                pslverr = bool(_sig_int(self.bus, "pslverr"))
                address = _sig_int(self.bus, "paddr")
                prot = _sig_int(self.bus, "pprot")
                if is_write:
                    data = _sig_int(self.bus, "pwdata")
                    item = OcahApbItem.write(
                        address=address,
                        data=data,
                        strobe=_sig_int(self.bus, "pstrb", -1),
                        prot=prot,
                        pslverr=pslverr,
                        wait_cycles=wait_cycles,
                        source=self.name,
                    )
                else:
                    data = _sig_int(self.bus, "prdata")
                    item = OcahApbItem.read(
                        address=address,
                        data=data,
                        prot=prot,
                        pslverr=pslverr,
                        wait_cycles=wait_cycles,
                        source=self.name,
                    )
                wait_cycles = 0
                in_access = False
                self._publish(item)
                continue

            if not in_access:
                wait_cycles = 0

    def _publish(self, item: OcahApbItem) -> None:
        self._history.append(item)
        if len(self._history) > self._max_history:
            self._history.pop(0)
        callbacks = list(self._callbacks)
        callbacks += self._write_callbacks if item.is_write else self._read_callbacks
        for callback in callbacks:
            try:
                callback(item)
            except Exception as exc:  # noqa: BLE001
                self.log.error("Exception in monitor callback %s: %s", callback, exc)
