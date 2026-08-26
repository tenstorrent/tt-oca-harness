# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite master driver: the cocotbext-axi engine binding.

`OcahAxiLiteMasterDriver` owns the bus/clock/reset resolution and the
underlying ``cocotbext.axi.AxiLiteMaster`` instance, and exposes the
event-level ``init_write``/``init_read`` transaction starters. The blocking,
checked, result-returning API lives in `OcahAxiLiteMasterSequence`.
"""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from cocotbext.axi.constants import AxiProt

__all__ = ["OcahAxiLiteMasterDriver"]


class OcahAxiLiteMasterDriver:
    """cocotbext-backed AXI4-Lite initiator engine for one bus connection."""

    def __init__(
        self,
        axi4_lite_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiLiteMaster",
        data_width: int = 32,
        reset_active_level: bool = False,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.data_width = data_width
        self.bytes_per_beat = data_width // 8
        self.full_strb = (1 << self.bytes_per_beat) - 1

        self.log = logging.getLogger(name)
        self._bus, self._clock, self._reset = self._resolve_bus_clock_reset(
            axi4_lite_intf,
            clock,
            reset,
        )
        self._master = AxiLiteMaster(
            self._bus,
            self._clock,
            self._reset,
            reset_active_level=reset_active_level,
            **kwargs,
        )

    @classmethod
    def from_prefix(
        cls,
        dut,
        prefix: str,
        clock,
        reset=None,
        **kwargs: Any,
    ) -> "OcahAxiLiteMasterDriver":
        """Construct from flattened AXI4-Lite signals using ``AxiLiteBus``."""
        return cls(AxiLiteBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    @staticmethod
    def _resolve_bus_clock_reset(axi4_lite_intf, clock, reset):
        if isinstance(axi4_lite_intf, AxiLiteBus):
            bus = axi4_lite_intf
        else:
            bus = AxiLiteBus.from_entity(axi4_lite_intf)

        resolved_clock = clock
        if resolved_clock is None:
            resolved_clock = getattr(axi4_lite_intf, "aclk", None)
        if resolved_clock is None:
            resolved_clock = getattr(axi4_lite_intf, "clk", None)
        if resolved_clock is None:
            raise ValueError("OcahAxiLiteMasterDriver requires a clock or an interface with aclk/clk")

        resolved_reset = reset
        if resolved_reset is None:
            resolved_reset = getattr(axi4_lite_intf, "aresetn", None)
        if resolved_reset is None:
            resolved_reset = getattr(axi4_lite_intf, "rst_ni", None)
        return bus, resolved_clock, resolved_reset

    def init_signals(self) -> None:
        """Compatibility no-op; cocotbext-axi drives idle values at construction."""

    async def wait_for_reset(self) -> None:
        """Wait until reset deassertion if a reset signal was provided."""
        if self._reset is None:
            return
        from cocotb.triggers import RisingEdge

        while int(self._reset.value) == 0:
            await RisingEdge(self._clock)

    @property
    def backend(self):
        """Return the underlying cocotbext ``AxiLiteMaster`` for debug only."""
        return self._master

    def init_write(
        self,
        address: int | None = None,
        data: int | bytes | bytearray = 0,
        *,
        addr: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        event=None,
    ):
        """Start a write and return the cocotb event, matching cocotbext style."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_write(target, self.data_bytes(data), prot=AxiProt(int(prot)), event=event)

    def init_read(
        self,
        address: int | None = None,
        length: int | None = None,
        *,
        addr: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        event=None,
    ):
        """Start a read and return the cocotb event, matching cocotbext style."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_read(
            target,
            self.bytes_per_beat if length is None else int(length),
            prot=AxiProt(int(prot)),
            event=event,
        )

    def data_bytes(self, data: int | bytes | bytearray) -> bytes:
        """Encode an integer beat as little-endian bytes (bytes pass through)."""
        if isinstance(data, int):
            mask = (1 << self.data_width) - 1
            return (data & mask).to_bytes(self.bytes_per_beat, "little")
        return bytes(data)

    def check_strb(self, strb: int | None) -> None:
        """Reject partial strobes the cocotbext backend cannot honor."""
        if strb is not None and int(strb) != self.full_strb:
            raise ValueError(
                f"{self.name}: cocotbext AXI-Lite master supports contiguous full-width writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{self.full_strb:X}"
            )

    @staticmethod
    def _coalesce_addr(address: int | None, addr: int | None) -> int:
        if address is None and addr is None:
            raise TypeError("address or addr is required")
        if address is not None and addr is not None and int(address) != int(addr):
            raise ValueError(f"conflicting address={address} and addr={addr}")
        return int(address if address is not None else addr)
