# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed AXI4-Lite slave agent: responder driver + sequence API.

`OcahAxiLiteSlaveAgent` builds the memory-backed `OcahAxiLiteSlaveDriver` and
the test-facing `OcahAxiLiteSlaveSequence` from one interface handle and one
`OcahAxiLiteSlaveConfig`. Tests configure and inspect the responder through
``agent.sequence`` (the mandated test-facing surface). The agent is reactive:
the driver answers bus traffic on its own from construction.
"""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiLiteBus

from .ocah_axi_lite_slave_config import OcahAxiLiteSlaveConfig
from .ocah_axi_lite_slave_driver import OcahAxiLiteSlaveDriver
from .ocah_axi_lite_slave_sequence import OcahAxiLiteSlaveSequence

__all__ = ["OcahAxiLiteSlaveAgent"]

# Accepted and ignored for signature compatibility; geometry is taken from
# the bus signals themselves.
_INFORMATIONAL_KEYS = ("data_width", "strb_width", "start")


class OcahAxiLiteSlaveAgent:
    """One AXI4-Lite memory-backed responder's driver/sequence bundle."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        *,
        config: OcahAxiLiteSlaveConfig | None = None,
        prefix: str | None = None,
        **overrides: Any,
    ) -> None:
        for key in _INFORMATIONAL_KEYS:
            overrides.pop(key, None)
        self.config = config or OcahAxiLiteSlaveConfig()
        drv_kwargs = self.config.driver_kwargs()
        drv_kwargs.update(overrides)
        name = drv_kwargs.get("name", self.config.name)
        size = drv_kwargs.get("size", self.config.size)
        self.log = logging.getLogger(name)
        axil_bus = AxiLiteBus.from_prefix(bus, prefix) if prefix else self._coerce_bus(bus)
        self.driver = OcahAxiLiteSlaveDriver(axil_bus, clock, reset, **drv_kwargs)
        self.sequence = OcahAxiLiteSlaveSequence(self.driver, name=name)
        self.log.info("%s: AXI-Lite RAM responder ready (%d bytes)", name, size)

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        **kwargs: Any,
    ) -> "OcahAxiLiteSlaveAgent":
        """Construct from flattened AXI4-Lite signals using ``AxiLiteBus.from_prefix``."""
        return cls(dut, clock, reset, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(bus):
        if isinstance(bus, AxiLiteBus):
            return bus
        return AxiLiteBus.from_entity(bus)
