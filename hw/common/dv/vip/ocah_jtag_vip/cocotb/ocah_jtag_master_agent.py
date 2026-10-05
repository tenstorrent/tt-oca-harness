# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed JTAG agent: active driver + passive monitor + checker.

`OcahJtagMasterAgent` is the cocotb analogue of a UVM agent bundle: it builds the
active TAP driver, the passive monitor, and the item-level checker from one
DUT handle and one `OcahJtagMasterConfig`, and wires the checker to the monitor's
item stream. Tests that want the pieces individually keep constructing them
directly; the agent removes the wiring boilerplate for the common case.
"""

from __future__ import annotations

from .ocah_jtag_checker import OcahJtagChecker
from .ocah_jtag_master_config import OcahJtagMasterConfig
from .ocah_jtag_master_driver import OcahJtagMasterDriver
from .ocah_jtag_master_monitor import OcahJtagMasterMonitor

__all__ = ["OcahJtagMasterAgent"]


class OcahJtagMasterAgent:
    """One TAP connection's driver/monitor/checker bundle."""

    def __init__(
        self,
        jtag_intf,
        *,
        config: OcahJtagMasterConfig | None = None,
        active: bool = True,
        en_monitor: bool = True,
        attach_checker: bool = True,
        checker: OcahJtagChecker | None = None,
    ) -> None:
        self.config = config or OcahJtagMasterConfig()
        self.driver: OcahJtagMasterDriver | None = (
            OcahJtagMasterDriver(jtag_intf, **self.config.driver_kwargs()) if active else None
        )
        self.monitor: OcahJtagMasterMonitor | None = (
            OcahJtagMasterMonitor(jtag_intf, **self.config.monitor_kwargs()) if en_monitor else None
        )
        self.checker = checker or OcahJtagChecker(
            name=f"{self.config.name}.checker", ir_width=self.config.ir_width
        )
        if attach_checker and self.monitor is not None:
            self.checker.attach_monitor(self.monitor)

    @property
    def tap(self) -> OcahJtagMasterDriver:
        """The active driver (raises when the agent was built passive)."""
        if self.driver is None:
            raise RuntimeError(f"{self.config.name}: agent was built passive")
        return self.driver

    async def start(self) -> None:
        """Initialize driver pins and start passive monitoring."""
        if self.driver is not None:
            self.driver.init_signals()
        if self.monitor is not None:
            await self.monitor.start()

    async def stop(self) -> None:
        """Stop passive monitoring (driver pins stay at their last values)."""
        if self.monitor is not None:
            await self.monitor.stop()

    def finalize(self) -> None:
        """Finalize the checker's retained findings and named evidence."""
        self.checker.finalize()
