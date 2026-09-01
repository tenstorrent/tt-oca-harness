# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite master sequence API: the VIP's test-facing stimulus surface.

`OcahAxiLiteMasterSequence` wraps one `OcahAxiLiteMasterDriver` and provides
the blocking, checked transaction API tests consume. Compatibility calls keep
their historical return values: ``write()`` returns a response code and
``read()`` returns data; ``write_result()``/``read_result()`` expose response
codes, data, and timeout state through plain dataclasses. Tests drive the VIP
through this class (or the agent's ``sequence``), never through the raw
driver; missing operations get added here first.
"""

from __future__ import annotations

from typing import Any

from .ocah_axi_item import OcahAxiReadResult, OcahAxiWriteResult
from .ocah_axi_lite_master_driver import OcahAxiLiteMasterDriver
from .ocah_axi_types import (
    axi_resp_ok,
    bytes_to_int,
    normalize_resp_list,
    worst_resp,
)

__all__ = ["OcahAxiLiteMasterSequence", "OcahAxiLiteMasterError"]


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


class OcahAxiLiteMasterSequence:
    """Checked AXI4-Lite transaction operations over one master driver."""

    def __init__(
        self,
        driver: OcahAxiLiteMasterDriver,
        *,
        timeout_cycles: int = 1000,
        timeout_ns: int | None = None,
        raise_on_error: bool = True,
    ) -> None:
        self.driver = driver
        self.timeout_cycles = timeout_cycles
        self.timeout_ns = timeout_ns
        self.raise_on_error = raise_on_error
        self._read_count = 0
        self._write_count = 0

    @property
    def name(self) -> str:
        return self.driver.name

    @property
    def log(self):
        return self.driver.log

    @property
    def backend(self):
        """Return the underlying cocotbext ``AxiLiteMaster`` for debug only."""
        return self.driver.backend

    # ------------------------------------------------------------------
    # Driver pass-throughs (pin/bus management and event-style access).
    # ------------------------------------------------------------------

    def init_signals(self) -> None:
        self.driver.init_signals()

    async def wait_for_reset(self) -> None:
        await self.driver.wait_for_reset()

    def init_write(self, *args: Any, **kwargs: Any):
        """Start a write and return the cocotb event (see the driver)."""
        return self.driver.init_write(*args, **kwargs)

    def init_read(self, *args: Any, **kwargs: Any):
        """Start a read and return the cocotb event (see the driver)."""
        return self.driver.init_read(*args, **kwargs)

    # ------------------------------------------------------------------
    # Blocking checked transactions.
    # ------------------------------------------------------------------

    async def write_result(
        self,
        addr: int,
        data: int,
        *,
        strb: int | None = None,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a write and return a plain response object."""
        self.driver.check_strb(strb)
        event = self.driver.init_write(addr, data, **self._axkwargs(prot))
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiWriteResult(
                    address=addr,
                    length=self.driver.bytes_per_beat,
                    resp=-1,
                    resp_list=(),
                    ok=False,
                    timed_out=True,
                )
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc

        result = OcahAxiWriteResult(
            address=int(getattr(raw, "address", addr)),
            length=int(getattr(raw, "length", self.driver.bytes_per_beat)),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise("write to", addr, result.ok, result.resp, check_response)
        return result

    async def write(self, addr: int, data: int, **kwargs: Any) -> int:
        """Issue an AXI4-Lite write and return the response code."""
        return (await self.write_result(addr, data, **kwargs)).resp

    async def read_result(
        self,
        addr: int,
        *,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a read and return data plus response information."""
        event = self.driver.init_read(addr, self.driver.bytes_per_beat, **self._axkwargs(prot))
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return OcahAxiReadResult(
                    address=addr,
                    data=0,
                    data_bytes=b"",
                    data_words=(),
                    resp=-1,
                    resp_list=(),
                    ok=False,
                    timed_out=True,
                )
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
        self._maybe_raise("read from", addr, result.ok, result.resp, check_response)
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
            raise ValueError(
                f"{self.name}: unsupported cocotbext config keys {sorted(unsupported)}"
            )

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

    @staticmethod
    def _axkwargs(prot: int | None) -> dict[str, int]:
        return {} if prot is None else {"prot": prot}

    def _maybe_raise(self, verb: str, addr: int, ok: bool, resp: int, check_response: bool) -> None:
        if check_response and self.raise_on_error and not ok:
            raise OcahAxiLiteMasterError(
                f"{self.name}: {verb} 0x{addr:08X} returned response=0x{resp:X}"
            )
