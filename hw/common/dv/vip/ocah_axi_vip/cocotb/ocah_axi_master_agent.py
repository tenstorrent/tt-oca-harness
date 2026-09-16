# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed AXI4 master agent: driver + sequence API (+ optional monitor).

`OcahAxiMasterAgent` is the cocotb analogue of a UVM agent bundle: it builds
the active `OcahAxiMasterDriver` and the test-facing `OcahAxiMasterSequence`
from one interface handle and one `OcahAxiMasterConfig`. Tests consume the
VIP through ``agent.sequence`` (the mandated test-facing surface). The bus
monitor stays side-neutral (`OcahAxiMonitor`) and is wired in only on
request, since passive observation does not require a master agent.
"""

from __future__ import annotations

from typing import Any

from .ocah_axi_master_config import OcahAxiMasterConfig
from .ocah_axi_master_driver import OcahAxiMasterDriver
from .ocah_axi_master_sequence import OcahAxiMasterSequence

__all__ = ["OcahAxiMasterAgent"]

_SEQUENCE_KEYS = ("timeout_cycles", "timeout_ns", "raise_on_error")


class OcahAxiMasterAgent:
    """One AXI4 master connection's driver/sequence bundle."""

    def __init__(
        self,
        axi4_intf,
        clock=None,
        reset=None,
        *,
        config: OcahAxiMasterConfig | None = None,
        en_monitor: bool = False,
        **overrides: Any,
    ) -> None:
        self.config = config or OcahAxiMasterConfig()
        seq_kwargs = self.config.sequence_kwargs()
        drv_kwargs = self.config.driver_kwargs()
        for key in _SEQUENCE_KEYS:
            if key in overrides:
                seq_kwargs[key] = overrides.pop(key)
        drv_kwargs.update(overrides)
        self.driver = OcahAxiMasterDriver(axi4_intf, clock, reset, **drv_kwargs)
        self.sequence = OcahAxiMasterSequence(self.driver, **seq_kwargs)
        self.monitor = None
        if en_monitor:
            from .ocah_axi_monitor import OcahAxiMonitor

            self.monitor = OcahAxiMonitor(axi4_intf, clock, name=f"{self.driver.name}.monitor")

    @classmethod
    def from_prefix(
        cls, dut, prefix: str, clock, reset=None, **kwargs: Any
    ) -> "OcahAxiMasterAgent":
        """Construct from flattened AXI4 signals using ``AxiBus.from_prefix``."""
        from cocotbext.axi import AxiBus

        return cls(AxiBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    async def start(self) -> None:
        """Initialize driver pins and start passive monitoring when present."""
        self.driver.init_signals()
        if self.monitor is not None:
            await self.monitor.start()

    async def stop(self) -> None:
        """Stop passive monitoring when present."""
        if self.monitor is not None:
            await self.monitor.stop()
