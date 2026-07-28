# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""OCAH-stable AXI4 master wrapper backed by cocotbext-axi."""

from __future__ import annotations

import logging
from typing import Any

from cocotbext.axi import AxiBus, AxiMaster
from cocotbext.axi.constants import AxiBurstType, AxiLockType, AxiProt

from .results import (
    RESP_OKAY,
    RESP_EXOKAY,
    RESP_SLVERR,
    RESP_DECERR,
    OcahAxiReadResult,
    OcahAxiWriteResult,
    axi_resp_ok,
    bytes_to_int,
    normalize_resp_list,
    words_from_bytes,
    worst_resp,
)

__all__ = ["OcahAxiMaster", "OcahAxiMasterError"]


class OcahAxiMasterError(RuntimeError):
    """Raised when an AXI4 transaction returns a non-OKAY response."""


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


class OcahAxiMaster:
    """OCAH-stable AXI4 master BFM.

    The wrapper returns plain Python values from compatibility methods and
    plain result dataclasses from ``*_result`` methods. It also exposes
    ``init_read`` and ``init_write`` for SEP-style explicit event handling.
    """

    def __init__(
        self,
        axi4_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahAxiMaster",
        timeout_cycles: int = 1000,
        timeout_ns: int | None = None,
        addr_width: int = 32,
        data_width: int = 32,
        reset_active_level: bool = False,
        max_burst_len: int = 256,
        raise_on_error: bool = True,
        **kwargs: Any,
    ) -> None:
        self.name = name
        self.addr_width = addr_width
        self.data_width = data_width
        self.timeout_cycles = timeout_cycles
        self.timeout_ns = timeout_ns
        self.raise_on_error = raise_on_error
        self._bytes_per_beat = data_width // 8
        self._full_strb = (1 << self._bytes_per_beat) - 1
        self._read_count = 0
        self._write_count = 0

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
    def from_prefix(cls, dut, prefix: str, clock, reset=None, **kwargs: Any) -> "OcahAxiMaster":
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
            raise ValueError("OcahAxiMaster requires a clock or an interface with aclk/clk")

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
            self._data_bytes(data, size=size),
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
        transfer_length = self._bytes_for_beats(1, size) if length is None else int(length)
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

    async def write_result(
        self,
        addr: int,
        data: int,
        *,
        strb: int | None = None,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a single-beat write and return a plain response object."""
        self._check_strb(strb, size)
        return await self._write_bytes_result(
            addr,
            self._data_bytes(data, size=size),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )

    async def write(self, addr: int, data: int, **kwargs: Any) -> int:
        """Issue a single-beat AXI4 write and return the response code."""
        return (await self.write_result(addr, data, **kwargs)).resp

    async def read_result(
        self,
        addr: int,
        *,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a single-beat read and return data plus response information."""
        return await self._read_bytes_result(
            addr,
            self._bytes_for_beats(1, size),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )

    async def read(self, addr: int, **kwargs: Any) -> int:
        """Issue a single-beat AXI4 read and return the first data word."""
        return (await self.read_result(addr, **kwargs)).data

    async def burst_write(
        self,
        addr: int,
        data_list: list[int],
        *,
        strb_list: list[int] | None = None,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> int:
        """Issue a multi-beat write burst and return the response code."""
        return (
            await self.burst_write_result(
                addr,
                data_list,
                strb_list=strb_list,
                size=size,
                burst=burst,
                id=id,
                prot=prot,
                check_response=check_response,
                timeout_ns=timeout_ns,
                allow_timeout=allow_timeout,
            )
        ).resp

    async def burst_write_result(
        self,
        addr: int,
        data_list: list[int],
        *,
        strb_list: list[int] | None = None,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a multi-beat write burst and return a plain response object."""
        if not data_list:
            raise ValueError(f"{self.name}: burst_write called with empty data_list")
        if strb_list is not None:
            for strb in strb_list:
                self._check_strb(strb, size)
        payload = b"".join(self._data_bytes(data, size=size) for data in data_list)
        return await self._write_bytes_result(
            addr,
            payload,
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )

    async def burst_read(
        self,
        addr: int,
        length: int,
        *,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> list[int]:
        """Issue a multi-beat read burst and return one integer per beat."""
        result = await self.burst_read_result(
            addr,
            length,
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )
        return list(result.data_words)

    async def burst_read_result(
        self,
        addr: int,
        length: int,
        *,
        size: int | None = 2,
        burst: int = int(AxiBurstType.INCR),
        id: int = 0,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a multi-beat read burst and return a plain response object."""
        if length < 1:
            raise ValueError(f"{self.name}: burst_read length must be >= 1, got {length}")
        return await self._read_bytes_result(
            addr,
            self._bytes_for_beats(length, size),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )

    def configure(self, **kwargs: Any) -> None:
        """Store wrapper configuration knobs accepted by earlier implementations."""
        if "timeout_cycles" in kwargs:
            self.timeout_cycles = int(kwargs["timeout_cycles"])
        if "timeout_ns" in kwargs:
            self.timeout_ns = int(kwargs["timeout_ns"])
        unsupported = set(kwargs) - {"timeout_cycles", "timeout_ns", "default_id"}
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

    async def _write_bytes_result(
        self,
        addr: int,
        payload: bytes,
        *,
        size: int | None,
        burst: int,
        id: int,
        prot: int,
        check_response: bool,
        timeout_ns: int | None,
        allow_timeout: bool,
    ) -> OcahAxiWriteResult:
        event = self.init_write(addr, payload, id=id, size=size, burst=burst, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiWriteResult(addr, len(payload), -1, (), False, True, None)
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc

        result = OcahAxiWriteResult(
            address=int(getattr(raw, "address", addr)),
            length=int(getattr(raw, "length", len(payload))),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise_write(addr, result, check_response)
        return result

    async def _read_bytes_result(
        self,
        addr: int,
        length: int,
        *,
        size: int | None,
        burst: int,
        id: int,
        prot: int,
        check_response: bool,
        timeout_ns: int | None,
        allow_timeout: bool,
    ) -> OcahAxiReadResult:
        event = self.init_read(addr, length, id=id, size=size, burst=burst, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiReadResult(addr, 0, b"", (), -1, (), False, True, None)
            raise AssertionError(f"{self.name}: read from 0x{addr:08X} timed out") from exc

        data_bytes = bytes(getattr(raw, "data", b""))
        beat_bytes = self._bytes_for_beats(1, size)
        words = words_from_bytes(data_bytes, beat_bytes)
        result = OcahAxiReadResult(
            address=int(getattr(raw, "address", addr)),
            data=words[0] if words else 0,
            data_bytes=data_bytes,
            data_words=words,
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._read_count += 1
        self._maybe_raise_read(addr, result, check_response)
        return result

    def _data_bytes(self, data: int | bytes | bytearray, *, size: int | None) -> bytes:
        if isinstance(data, int):
            beat_bytes = self._bytes_for_beats(1, size)
            return (data & ((1 << (8 * beat_bytes)) - 1)).to_bytes(beat_bytes, "little")
        return bytes(data)

    def _bytes_for_beats(self, beats: int, size: int | None) -> int:
        beat_bytes = self._bytes_per_beat if size is None else 2 ** int(size)
        return beats * beat_bytes

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

    def _check_strb(self, strb: int | None, size: int | None) -> None:
        beat_bytes = self._bytes_for_beats(1, size)
        full_strb = (1 << beat_bytes) - 1
        if strb is not None and int(strb) != full_strb:
            raise ValueError(
                f"{self.name}: cocotbext AXI master supports contiguous writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{full_strb:X}"
            )

    def _maybe_raise_write(self, addr: int, result: OcahAxiWriteResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahAxiMasterError(
                f"{self.name}: write to 0x{addr:08X} returned response=0x{result.resp:X}"
            )

    def _maybe_raise_read(self, addr: int, result: OcahAxiReadResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahAxiMasterError(
                f"{self.name}: read from 0x{addr:08X} returned response=0x{result.resp:X}"
            )
