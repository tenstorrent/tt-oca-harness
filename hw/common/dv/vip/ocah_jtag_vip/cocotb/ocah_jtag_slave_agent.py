# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed slave-side agent: reactive device driver + passive monitor + checker.

`OcahJtagSlaveAgent` is the device-side counterpart of
`OcahJtagMasterAgent`: it builds the reactive TAP device, the passive
monitor, and the item-level checker from one DUT handle and one
`OcahJtagSlaveConfig`, wiring the checker to the monitor's item stream.
"""

from __future__ import annotations

from .ocah_jtag_checker import OcahJtagChecker
from .ocah_jtag_slave_config import OcahJtagSlaveConfig
from .ocah_jtag_slave_driver import OcahJtagSlaveDriver
from .ocah_jtag_slave_monitor import OcahJtagSlaveMonitor

__all__ = ["OcahJtagSlaveAgent"]


class OcahJtagSlaveAgent:
    """One TAP device connection's driver/monitor/checker bundle."""

    def __init__(
        self,
        jtag_intf,
        *,
        config: OcahJtagSlaveConfig | None = None,
        active: bool = True,
        en_monitor: bool = True,
        attach_checker: bool = True,
        checker: OcahJtagChecker | None = None,
    ) -> None:
        self.config = config or OcahJtagSlaveConfig()
        self.device = self.config.build_device()
        self.driver: OcahJtagSlaveDriver | None = (
            OcahJtagSlaveDriver(jtag_intf, self.device, **self.config.driver_kwargs())
            if active
            else None
        )
        self.monitor: OcahJtagSlaveMonitor | None = (
            OcahJtagSlaveMonitor(jtag_intf, **self.config.monitor_kwargs()) if en_monitor else None
        )
        self.checker = checker or OcahJtagChecker(
            name=f"{self.config.name}.checker", ir_width=self.config.ir_width
        )
        if attach_checker and self.monitor is not None:
            self.checker.attach_monitor(self.monitor)

    @property
    def responder(self) -> OcahJtagSlaveDriver:
        """The reactive device (raises when the agent was built passive)."""
        if self.driver is None:
            raise RuntimeError(f"{self.config.name}: agent was built passive")
        return self.driver

    async def start(self) -> None:
        """Start responding on TDO and start passive monitoring."""
        if self.driver is not None:
            await self.driver.start()
        if self.monitor is not None:
            await self.monitor.start()

    async def stop(self) -> None:
        """Stop the responder and passive monitoring."""
        if self.driver is not None:
            await self.driver.stop()
        if self.monitor is not None:
            await self.monitor.stop()

    def finalize(self) -> None:
        """Finalize the checker's retained findings and named evidence."""
        self.checker.finalize()
