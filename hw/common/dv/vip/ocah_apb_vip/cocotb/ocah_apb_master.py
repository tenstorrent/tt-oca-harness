# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCAH-stable APB master wrapper backed by cocotbext-axi."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from cocotbext.axi import ApbBus, ApbMaster
from cocotbext.axi.constants import AxiProt

__all__ = ["OcahApbMaster", "OcahApbMasterError", "OcahApbReadResult", "OcahApbWriteResult"]

RESP_OKAY = 0
RESP_SLVERR = 2


@dataclass(frozen=True)
class OcahApbWriteResult:
    """Plain APB write result."""

    address: int
    length: int
    pslverr: bool
    ok: bool
    resp: int
    timed_out: bool = False
    raw: Any = None

    def to_item(self, *, source: str = "master"):
        """Convert this result into an OCAH APB transaction item."""
        from .ocah_apb_item import OcahApbItem

        return OcahApbItem.write(
            address=self.address,
            pslverr=self.pslverr,
            source=source,
            timed_out=self.timed_out,
            metadata={"length": self.length},
        )


@dataclass(frozen=True)
class OcahApbReadResult:
    """Plain APB read result."""

    address: int
    data: int
    data_bytes: bytes
    pslverr: bool
    ok: bool
    resp: int
    timed_out: bool = False
    raw: Any = None

    def to_item(self, *, source: str = "master"):
        """Convert this result into an OCAH APB transaction item."""
        from .ocah_apb_item import OcahApbItem

        return OcahApbItem.read(
            address=self.address,
            data=self.data,
            data_bytes=self.data_bytes,
            pslverr=self.pslverr,
            source=source,
            timed_out=self.timed_out,
        )


class OcahApbMasterError(RuntimeError):
    """Raised when an APB transaction returns PSLVERR=1."""


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


class OcahApbMaster:
    """OCAH-stable APB master BFM."""

    def __init__(
        self,
        apb_intf,
        clock=None,
        reset=None,
        *,
        name: str = "OcahApbMaster",
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

        self._bus = apb_intf if isinstance(apb_intf, ApbBus) else ApbBus.from_entity(apb_intf)
        self._clock = clock if clock is not None else getattr(apb_intf, "pclk", None)
        if self._clock is None:
            self._clock = getattr(apb_intf, "clk", None)
        if self._clock is None:
            raise ValueError("OcahApbMaster requires a clock or an interface with pclk/clk")
        self._reset = reset if reset is not None else getattr(apb_intf, "presetn", None)
        self._master = ApbMaster(
            self._bus,
            self._clock,
            self._reset,
            reset_active_level=reset_active_level,
            **kwargs,
        )

    @classmethod
    def from_prefix(cls, dut, prefix: str, clock, reset=None, **kwargs: Any) -> "OcahApbMaster":
        """Construct from flattened APB signals using ``ApbBus``."""
        return cls(ApbBus.from_prefix(dut, prefix), clock, reset, **kwargs)

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
        """Return the underlying cocotbext ``ApbMaster`` for debug only."""
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
    ) -> OcahApbWriteResult:
        """Issue an APB write and return a plain result object."""
        self._check_strb(strb)
        event = self.init_write(addr, data, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahApbWriteResult(addr, self._bytes_per_beat, True, False, -1, True, None)
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc
        result = OcahApbWriteResult(
            address=int(getattr(raw, "address", addr)),
            length=int(getattr(raw, "length", self._bytes_per_beat)),
            pslverr=int(getattr(raw, "resp", RESP_OKAY)) != RESP_OKAY,
            ok=int(getattr(raw, "resp", RESP_OKAY)) == RESP_OKAY,
            resp=int(getattr(raw, "resp", RESP_OKAY)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise_write(addr, result, check_response)
        return result

    async def write(self, addr: int, data: int, **kwargs: Any) -> bool:
        """Issue an APB write and return True when PSLVERR was not asserted."""
        return (await self.write_result(addr, data, **kwargs)).ok

    async def read_result(
        self,
        addr: int,
        *,
        prot: int = int(AxiProt.NONSECURE),
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahApbReadResult:
        """Issue an APB read and return data plus PSLVERR information."""
        event = self.init_read(addr, self._bytes_per_beat, prot=prot)
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahApbReadResult(addr, 0, b"", True, False, -1, True, None)
            raise AssertionError(f"{self.name}: read from 0x{addr:08X} timed out") from exc
        data_bytes = bytes(getattr(raw, "data", b""))
        result = OcahApbReadResult(
            address=int(getattr(raw, "address", addr)),
            data=int.from_bytes(data_bytes, "little"),
            data_bytes=data_bytes,
            pslverr=int(getattr(raw, "resp", RESP_OKAY)) != RESP_OKAY,
            ok=int(getattr(raw, "resp", RESP_OKAY)) == RESP_OKAY,
            resp=int(getattr(raw, "resp", RESP_OKAY)),
            raw=raw,
        )
        self._read_count += 1
        self._maybe_raise_read(addr, result, check_response)
        return result

    async def read(self, addr: int, **kwargs: Any) -> int:
        """Issue an APB read and return PRDATA."""
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
                f"{self.name}: cocotbext APB master supports full-width writes only; "
                f"got strb=0x{int(strb):X}, expected 0x{self._full_strb:X}"
            )

    def _maybe_raise_write(self, addr: int, result: OcahApbWriteResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahApbMasterError(f"{self.name}: write to 0x{addr:08X} returned PSLVERR")

    def _maybe_raise_read(self, addr: int, result: OcahApbReadResult, check_response: bool) -> None:
        if check_response and self.raise_on_error and not result.ok:
            raise OcahApbMasterError(f"{self.name}: read from 0x{addr:08X} returned PSLVERR")
