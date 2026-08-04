# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""OCAH-stable AXI4-Lite master wrapper backed by cocotbext-axi."""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from cocotbext.axi.constants import AxiProt

from .results import (
    RESP_OKAY,
    RESP_SLVERR,
    RESP_DECERR,
    OcahAxiReadResult,
    OcahAxiWriteResult,
    axi_resp_ok,
    bytes_to_int,
    normalize_resp_list,
    worst_resp,
)

__all__ = ["OcahAxiLiteMaster", "OcahAxiLiteMasterError"]


class OcahAxiLiteMasterError(RuntimeError):
    """Raised when an AXI4-Lite transaction returns a non-OKAY response."""


def _sim_timeout_error():
    try:
        from cocotb.result import SimTimeoutError  # type: ignore[attr-defined]
    except ImportError:
        from cocotb.triggers import SimTimeoutError  # type: ignore[no-redef]
    return SimTimeoutError


async def _wait_event(event, timeout_ns: int | None):
    if timeout_ns is None:
        await event.wait()
    else:
        from cocotb.triggers import with_timeout

        await with_timeout(event.wait(), timeout_ns, "ns")
    return event.data


class OcahAxiLiteMaster:
    """OCAH-stable AXI4-Lite master BFM.

    Existing convenience calls keep their historical return values:
    ``write()`` returns a response code and ``read()`` returns data. New
    ``write_result()`` and ``read_result()`` methods expose response codes,
    data, timeout state, and backend raw objects through plain dataclasses.
    """

    def __init__(
        self,
        axi4_lite_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiLiteMaster",
        timeout_cycles: int = 1000,
        timeout_ns: int | None = None,
        data_width: int = 32,
        reset_active_level: bool = False,
        raise_on_error: bool = True,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.data_width = data_width
        self.timeout_cycles = timeout_cycles
        self.timeout_ns = timeout_ns
        self.raise_on_error = raise_on_error
        self._bytes_per_beat = data_width // 8
        self._full_strb = (1 << self._bytes_per_beat) - 1
        self._read_count = 0
        self._write_count = 0

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
    ) -> "OcahAxiLiteMaster":
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
            raise ValueError("OcahAxiLiteMaster requires a clock or an interface with aclk/clk")

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
        return self._master.init_write(target, self._data_bytes(data), prot=AxiProt(int(prot)), event=event)

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
            self._bytes_per_beat if length is None else int(length),
            prot=AxiProt(int(prot)),
            event=event,
        )

    async def write_result(
        self,
        addr: int,
        data: int,
        *,
        strb: int | None = None,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a write and return a plain response object."""
        self._check_strb(strb)
        event = self.init_write(addr, data, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiWriteResult(addr, self._bytes_per_beat, -1, (), False, True, None)
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc

        result = OcahAxiWriteResult(
            address=int(getattr(raw, "address", addr)),
            length=int(getattr(raw, "length", self._bytes_per_beat)),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise_write(addr, result, check_response)
        return result

    async def write(self, addr: int, data: int, **kwargs: Any) -> int:
        """Issue an AXI4-Lite write and return the response code."""
        return (await self.write_result(addr, data, **kwargs)).resp

    async def read_result(
        self,
        addr: int,
        *,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a read and return data plus response information."""
        event = self.init_read(addr, self._bytes_per_beat, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiReadResult(addr, 0, b"", (), -1, (), False, True, None)
            raise AssertionError(f"{self.name}: read from 0x{addr:08X} timed out") from exc

        data_bytes = bytes(getattr(raw, "data", b""))
        result = OcahAxiReadResult(
            address=int(getattr(raw, "address", addr)),
            data=bytes_to_int(data_bytes),
            data_bytes=data_bytes,
            data_words=(bytes_to_int(data_bytes),),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._read_count += 1
        self._maybe_raise_read(addr, result, check_response)
        return result

    async def read(self, addr: int, **kwargs: Any) -> int:
        """Issue an AXI4-Lite read and return the data word."""
        return (await self.read_result(addr, **kwargs)).data

    def configure(self, **kwargs: Any) -> None:
        """Store wrapper configuration knobs accepted by earlier implementations."""
        if "timeout_cycles" in kwargs:
            self.timeout_cycles = int(kwargs["timeout_cycles"])
        if "timeout_ns" in kwargs:
            self.timeout_ns = int(kwargs["timeout_ns"])
        unsupported = set(kwargs) - {"timeout_cycles", "timeout_ns"}
        if unsupported:
            self.log.warning("%s: ignored unsupported cocotbext config keys %s", self.name, sorted(unsupported))

    def get_statistics(self) -> dict[str, int]:
        """Return wrapper-level transaction counters."""
        return {
            "write_transactions": self._write_count,
            "read_transactions": self._read_count,
            "timeout_cycles": self.timeout_cycles,
        }

    def reset_statistics(self) -> None:
        self._write_count = 0
        self._read_count = 0

    def _data_bytes(self, data: int | bytes | bytearray) -> bytes:
        if isinstance(data, int):
            mask = (1 << self.data_width) - 1
            return (data & mask).to_bytes(self._bytes_per_beat, "little")
        return bytes(data)

    @staticmethod
    def _coalesce_addr(address: int | None, addr: int | None) -> int:
        if address is None and addr is None:
            raise TypeError("address or addr is required")
        if address is not None and addr is not None and int(address) != int(addr):
            raise ValueError(f"conflicting address={address} and addr={addr}")
        return int(address if address is not None else addr)

    def _check_strb(self, strb: int | None) -> None:
        if strb is not None and int(strb) != self._full_strb:
            raise ValueError(
                f"{self.name}: cocotbext AXI-Lite master supports contiguous full-width writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{self._full_strb:X}"
            )

    def _maybe_raise_write(self, addr: int, result: OcahAxiWriteResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahAxiLiteMasterError(
                f"{self.name}: write to 0x{addr:08X} returned response=0x{result.resp:X}"
            )

    def _maybe_raise_read(self, addr: int, result: OcahAxiReadResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahAxiLiteMasterError(
                f"{self.name}: read from 0x{addr:08X} returned response=0x{result.resp:X}"
            )
