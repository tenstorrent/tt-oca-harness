# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed AXI4-Lite master agent: driver + sequence API (+ optional monitor).

`OcahAxiLiteMasterAgent` builds the active `OcahAxiLiteMasterDriver` and the
test-facing `OcahAxiLiteMasterSequence` from one interface handle and one
`OcahAxiLiteMasterConfig`. Tests consume the VIP through ``agent.sequence``
(the mandated test-facing surface). The bus monitor stays side-neutral
(`OcahAxiLiteMonitor`) and is wired in only on request.
"""

from __future__ import annotations

from typing import Any

from .ocah_axi_lite_master_config import OcahAxiLiteMasterConfig
from .ocah_axi_lite_master_driver import OcahAxiLiteMasterDriver
from .ocah_axi_lite_master_sequence import OcahAxiLiteMasterSequence

__all__ = ["OcahAxiLiteMasterAgent"]

_SEQUENCE_KEYS = ("timeout_cycles", "timeout_ns", "raise_on_error")


class OcahAxiLiteMasterAgent:
    """One AXI4-Lite master connection's driver/sequence bundle."""

    def __init__(
        self,
        axi4_lite_intf,
        clock=None,
        reset=None,
        *,
        config: OcahAxiLiteMasterConfig | None = None,
        en_monitor: bool = False,
        **overrides: Any,
    ) -> None:
        self.config = config or OcahAxiLiteMasterConfig()
        seq_kwargs = self.config.sequence_kwargs()
        drv_kwargs = self.config.driver_kwargs()
        for key in _SEQUENCE_KEYS:
            if key in overrides:
                seq_kwargs[key] = overrides.pop(key)
        drv_kwargs.update(overrides)
        self.driver = OcahAxiLiteMasterDriver(axi4_lite_intf, clock, reset, **drv_kwargs)
        self.sequence = OcahAxiLiteMasterSequence(self.driver, **seq_kwargs)
        self.monitor = None
        if en_monitor:
            from .ocah_axi_monitor import OcahAxiLiteMonitor

            self.monitor = OcahAxiLiteMonitor(
                axi4_lite_intf, clock, name=f"{self.driver.name}.monitor"
            )

    @classmethod
    def from_prefix(
        cls, dut, prefix: str, clock, reset=None, **kwargs: Any
    ) -> "OcahAxiLiteMasterAgent":
        """Construct from flattened AXI4-Lite signals using ``AxiLiteBus.from_prefix``."""
        from cocotbext.axi import AxiLiteBus

        return cls(AxiLiteBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    async def start(self) -> None:
        """Initialize driver pins and start passive monitoring when present."""
        self.driver.init_signals()
        if self.monitor is not None:
            await self.monitor.start()

    async def stop(self) -> None:
        """Stop passive monitoring when present."""
        if self.monitor is not None:
            await self.monitor.stop()
