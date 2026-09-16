# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Composed AXI4 slave agent: responder driver + sequence API.

`OcahAxiSlaveAgent` builds the memory-backed `OcahAxiSlaveDriver` and the
test-facing `OcahAxiSlaveSequence` from one interface handle and one
`OcahAxiSlaveConfig`. Tests configure and inspect the responder through
``agent.sequence`` (the mandated test-facing surface). The agent is reactive:
the driver answers bus traffic on its own from construction.
"""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiBus

from .ocah_axi_slave_config import OcahAxiSlaveConfig
from .ocah_axi_slave_driver import OcahAxiSlaveDriver
from .ocah_axi_slave_sequence import OcahAxiSlaveSequence

__all__ = ["OcahAxiSlaveAgent"]

# Accepted and ignored for signature compatibility; geometry is taken from
# the bus signals themselves.
_INFORMATIONAL_KEYS = ("id_width", "addr_width", "data_width", "strb_width", "start")


class OcahAxiSlaveAgent:
    """One AXI4 memory-backed responder's driver/sequence bundle."""

    def __init__(
        self,
        bus,
        clock,
        reset=None,
        *,
        config: OcahAxiSlaveConfig | None = None,
        prefix: str | None = None,
        **overrides: Any,
    ) -> None:
        for key in _INFORMATIONAL_KEYS:
            overrides.pop(key, None)
        self.config = config or OcahAxiSlaveConfig()
        drv_kwargs = self.config.driver_kwargs()
        drv_kwargs.update(overrides)
        name = drv_kwargs.get("name", self.config.name)
        size = drv_kwargs.get("size", self.config.size)
        self.log = logging.getLogger(name)
        axi_bus = AxiBus.from_prefix(bus, prefix) if prefix else self._coerce_bus(bus)
        self.driver = OcahAxiSlaveDriver(axi_bus, clock, reset, **drv_kwargs)
        self.sequence = OcahAxiSlaveSequence(self.driver, name=name)
        self.log.info("%s: AXI RAM responder ready (%d bytes)", name, size)

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        **kwargs: Any,
    ) -> "OcahAxiSlaveAgent":
        """Construct from flattened AXI signals using ``AxiBus.from_prefix``."""
        return cls(dut, clock, reset, prefix=prefix, **kwargs)

    @staticmethod
    def _coerce_bus(bus):
        if isinstance(bus, AxiBus):
            return bus
        return AxiBus.from_entity(bus)
