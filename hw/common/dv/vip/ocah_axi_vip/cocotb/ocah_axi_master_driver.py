# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 master driver: the cocotbext-axi engine binding.

`OcahAxiMasterDriver` owns the bus/clock/reset resolution and the underlying
``cocotbext.axi.AxiMaster`` instance, and exposes the event-level
``init_write``/``init_read`` transaction starters. The blocking, checked,
result-returning API lives in `OcahAxiMasterSequence` — the VIP's test-facing
surface — which wraps one driver.
"""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiBus, AxiMaster
from cocotbext.axi.constants import AxiBurstType, AxiLockType, AxiProt

__all__ = ["OcahAxiMasterDriver"]


class OcahAxiMasterDriver:
    """cocotbext-backed AXI4 initiator engine for one bus connection."""

    def __init__(
        self,
        axi4_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiMaster",
        addr_width: int = 32,
        data_width: int = 32,
        reset_active_level: bool = False,
        max_burst_len: int = 256,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.addr_width = addr_width
        self.data_width = data_width
        self._bytes_per_beat = data_width // 8
        self._full_strb = (1 << self._bytes_per_beat) - 1

        self.log = logging.getLogger(name)
        self._bus, self._clock, self._reset = self._resolve_bus_clock_reset(axi4_intf, clock, reset)
        self._master = AxiMaster(
            self._bus,
            self._clock,
            self._reset,
            reset_active_level=reset_active_level,
            max_burst_len=max_burst_len,
            **kwargs,
        )

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, reset=None, **kwargs: Any) -> "OcahAxiMasterDriver":
        """Construct from flattened AXI4 signals using ``AxiBus``."""
        return cls(AxiBus.from_prefix(dut, prefix), clock, reset, **kwargs)

    @staticmethod
    def _resolve_bus_clock_reset(axi4_intf, clock, reset):
        if isinstance(axi4_intf, AxiBus):
            bus = axi4_intf
        else:
            bus = AxiBus.from_entity(axi4_intf)

        resolved_clock = clock
        if resolved_clock is None:
            resolved_clock = getattr(axi4_intf, "aclk", None)
        if resolved_clock is None:
            resolved_clock = getattr(axi4_intf, "clk", None)
        if resolved_clock is None:
            raise ValueError("OcahAxiMasterDriver requires a clock or an interface with aclk/clk")

        resolved_reset = reset
        if resolved_reset is None:
            resolved_reset = getattr(axi4_intf, "aresetn", None)
        if resolved_reset is None:
            resolved_reset = getattr(axi4_intf, "rst_ni", None)
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
        """Return the underlying cocotbext ``AxiMaster`` for debug only."""
        return self._master

    def init_write(
        self,
        address: int | None = None,
        data: int | bytes | bytearray = 0,
        *,
        addr: int | None = None,
        awid: int | None = None,
        id: int | None = None,
        burst: int = int(AxiBurstType.INCR),
        size: int | None = None,
        lock: int = int(AxiLockType.NORMAL),
        cache: int = 0b0011,
        prot: int = int(AxiProt.NONSECURE),
        qos: int = 0,
        region: int = 0,
        user: int = 0,
        wuser=None,
        event=None,
    ):
        """Start a write and return the cocotb event."""
        target = self._coalesce_addr(address, addr)
        return self._master.init_write(
            target,
            self.data_bytes(data, size=size),
            awid=self._coalesce_id(awid, id),
            burst=AxiBurstType(int(burst)),
            size=size,
            lock=AxiLockType(int(lock)),
            cache=cache,
            prot=AxiProt(int(prot)),
            qos=qos,
            region=region,
            user=user,
            wuser=wuser,
            event=event,
        )

    def init_read(
        self,
        address: int | None = None,
        length: int | None = None,
        *,
        addr: int | None = None,
        arid: int | None = None,
        id: int | None = None,
        burst: int = int(AxiBurstType.INCR),
        size: int | None = None,
        lock: int = int(AxiLockType.NORMAL),
        cache: int = 0b0011,
        prot: int = int(AxiProt.NONSECURE),
        qos: int = 0,
        region: int = 0,
        user: int = 0,
        event=None,
    ):
        """Start a read and return the cocotb event."""
        target = self._coalesce_addr(address, addr)
        transfer_length = self.bytes_for_beats(1, size) if length is None else int(length)
        return self._master.init_read(
            target,
            transfer_length,
            arid=self._coalesce_id(arid, id),
            burst=AxiBurstType(int(burst)),
            size=size,
            lock=AxiLockType(int(lock)),
            cache=cache,
            prot=AxiProt(int(prot)),
            qos=qos,
            region=region,
            user=user,
            event=event,
        )

    def data_bytes(self, data: int | bytes | bytearray, *, size: int | None) -> bytes:
        """Encode an integer beat as little-endian bytes (bytes pass through)."""
        if isinstance(data, int):
            beat_bytes = self.bytes_for_beats(1, size)
            return (data & ((1 << (8 * beat_bytes)) - 1)).to_bytes(beat_bytes, "little")
        return bytes(data)

    def bytes_for_beats(self, beats: int, size: int | None) -> int:
        """Total transfer bytes for ``beats`` beats at AxSIZE ``size``."""
        beat_bytes = self._bytes_per_beat if size is None else 2 ** int(size)
        return beats * beat_bytes

    def check_strb(self, strb: int | None, size: int | None) -> None:
        """Reject partial strobes the cocotbext backend cannot honor."""
        beat_bytes = self.bytes_for_beats(1, size)
        full_strb = (1 << beat_bytes) - 1
        if strb is not None and int(strb) != full_strb:
            raise ValueError(
                f"{self.name}: cocotbext AXI master supports contiguous writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{full_strb:X}"
            )

    @staticmethod
    def _coalesce_addr(address: int | None, addr: int | None) -> int:
        if address is None and addr is None:
            raise TypeError("address or addr is required")
        if address is not None and addr is not None and int(address) != int(addr):
            raise ValueError(f"conflicting address={address} and addr={addr}")
        return int(address if address is not None else addr)

    @staticmethod
    def _coalesce_id(primary: int | None, alias: int | None) -> int | None:
        if primary is not None and alias is not None and int(primary) != int(alias):
            raise ValueError(f"conflicting AXI IDs {primary} and {alias}")
        value = primary if primary is not None else alias
        return None if value is None else int(value)
