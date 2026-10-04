# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4 master sequence API: the VIP's test-facing stimulus surface.

`OcahAxiMasterSequence` wraps one `OcahAxiMasterDriver` and provides the
blocking, checked transaction API tests consume: plain-value helpers
(``write``/``read``), result helpers (``*_result``), burst variants, timeout
handling, and typed non-OKAY raising. Tests and DUT sequence layers drive the
VIP through this class (or the agent's ``sequence``), never through the raw
driver; missing operations get added here first.
"""

from __future__ import annotations

import warnings
from typing import Any

from .ocah_axi_item import OcahAxiReadResult, OcahAxiWriteResult
from .ocah_axi_master_driver import OcahAxiMasterDriver
from .ocah_axi_types import (
    axi_resp_ok,
    default_timeout_ns,
    normalize_resp_list,
    words_from_bytes,
    worst_resp,
)

__all__ = ["OcahAxiMasterSequence", "OcahAxiMasterError"]


class OcahAxiMasterError(RuntimeError):
    """Raised when an AXI4 transaction returns a non-OKAY response."""


def _sim_timeout_error():
    try:
        from cocotb.result import SimTimeoutError  # type: ignore[attr-defined]
    except ImportError:
        from cocotb.triggers import SimTimeoutError  # type: ignore[no-redef]
    return SimTimeoutError


async def _wait_event(event, timeout_ns: int):
    from cocotb.triggers import with_timeout

    await with_timeout(event.wait(), timeout_ns, "ns")
    return event.data


class OcahAxiMasterSequence:
    """Checked AXI4 transaction operations over one master driver.

    ``write``/``read`` return plain Python values and ``*_result`` methods
    return plain result dataclasses; ``init_read``/``init_write`` pass through
    to the driver for explicit event-style timeout flows.
    """

    def __init__(
        self,
        driver: OcahAxiMasterDriver,
        *,
        timeout_cycles: int | None = None,
        timeout_ns: int | None = None,
        raise_on_error: bool = True,
    ) -> None:
        self.driver = driver
        self._deprecations_logged: set[str] = set()
        self.timeout_cycles = 1000
        if timeout_cycles is not None:
            self._set_timeout_cycles(timeout_cycles)
        self.timeout_ns = default_timeout_ns() if timeout_ns is None else int(timeout_ns)
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
        """Return the underlying cocotbext ``AxiMaster`` for debug only."""
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
        size: int | None = 2,
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a single-beat write and return a plain response object."""
        self.driver.check_strb(strb, size)
        return await self._write_bytes_result(
            addr,
            self.driver.data_bytes(data, size=size),
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

    async def write_bytes_result(
        self,
        addr: int,
        payload: bytes,
        *,
        size: int | None = None,
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
        user: int = 0,
        attrs: dict[str, int] | None = None,
    ) -> OcahAxiWriteResult:
        """Issue a write of an explicit byte payload and return a plain result.

        Use this when the transfer length is not one beat at ``data_width`` /
        ``size`` (for example a 4-byte access on a 64-bit bus).

        ``attrs`` sets the AW attributes the other arguments do not name:
        ``lock``, ``cache``, ``qos``, ``region`` and ``wuser``. An absent key
        keeps the driver default.
        """
        return await self._write_bytes_result(
            addr,
            bytes(payload),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
            user=user,
            attrs=attrs,
        )

    async def read_result(
        self,
        addr: int,
        *,
        size: int | None = 2,
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a single-beat read and return data plus response information."""
        return await self._read_bytes_result(
            addr,
            self.driver.bytes_for_beats(1, size),
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

    async def read_bytes_result(
        self,
        addr: int,
        length: int,
        *,
        size: int | None = None,
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
        user: int = 0,
        attrs: dict[str, int] | None = None,
    ) -> OcahAxiReadResult:
        """Issue a read of ``length`` bytes and return a plain result.

        Use this when the transfer length is not one beat at ``data_width`` /
        ``size`` (for example a 4-byte access on a 64-bit bus).

        ``attrs`` sets the AR attributes the other arguments do not name:
        ``lock``, ``cache``, ``qos`` and ``region``. An absent key keeps the
        driver default.
        """
        return await self._read_bytes_result(
            addr,
            int(length),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
            user=user,
            attrs=attrs,
        )

    async def burst_write(
        self,
        addr: int,
        data_list: list[int],
        *,
        strb_list: list[int] | None = None,
        size: int | None = 2,
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
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
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a multi-beat write burst and return a plain response object."""
        if not data_list:
            raise ValueError(f"{self.name}: burst_write called with empty data_list")
        if strb_list is not None:
            for strb in strb_list:
                self.driver.check_strb(strb, size)
        payload = b"".join(self.driver.data_bytes(data, size=size) for data in data_list)
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
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
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
        burst: int | None = None,
        id: int = 0,
        prot: int | None = None,
        check_response: bool = True,
        timeout_ns: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a multi-beat read burst and return a plain response object."""
        if length < 1:
            raise ValueError(f"{self.name}: burst_read length must be >= 1, got {length}")
        return await self._read_bytes_result(
            addr,
            self.driver.bytes_for_beats(length, size),
            size=size,
            burst=burst,
            id=id,
            prot=prot,
            check_response=check_response,
            timeout_ns=timeout_ns,
            allow_timeout=allow_timeout,
        )

    def configure(self, **kwargs: Any) -> None:
        """Apply the supported knobs (timeout_cycles, timeout_ns, default_id); reject others."""
        if "timeout_cycles" in kwargs:
            self._set_timeout_cycles(kwargs["timeout_cycles"])
        if "timeout_ns" in kwargs:
            self.timeout_ns = int(kwargs["timeout_ns"])
        unsupported = set(kwargs) - {"timeout_cycles", "timeout_ns", "default_id"}
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
            "timeout_ns": self.timeout_ns,
        }

    def reset_statistics(self) -> None:
        self._write_count = 0
        self._read_count = 0

    def _set_timeout_cycles(self, value: int) -> None:
        """Deprecated knob: the AXI4 engine bounds a transaction with ``timeout_ns``."""
        self.timeout_cycles = int(value)
        if "timeout_cycles" in self._deprecations_logged:
            return
        self._deprecations_logged.add("timeout_cycles")
        message = (
            "timeout_cycles is deprecated: the AXI4 master bounds a transaction with timeout_ns"
        )
        self.log.warning("%s: %s", self.name, message)
        warnings.warn(message, DeprecationWarning, stacklevel=3)

    # ------------------------------------------------------------------
    # Completion, result packaging, and response checking.
    # ------------------------------------------------------------------

    async def _write_bytes_result(
        self,
        addr: int,
        payload: bytes,
        *,
        size: int | None,
        burst: int | None,
        id: int,
        prot: int | None,
        check_response: bool,
        timeout_ns: int | None,
        allow_timeout: bool,
        user: int = 0,
        attrs: dict[str, int] | None = None,
    ) -> OcahAxiWriteResult:
        capture = self.driver.start_response_id_capture("b")
        event = self.driver.init_write(
            addr,
            payload,
            id=id,
            size=size,
            **self._axkwargs(burst, prot, user, attrs, self._WRITE_ATTRS),
        )
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            capture.cancel()
            if allow_timeout:
                return OcahAxiWriteResult(
                    address=addr,
                    length=len(payload),
                    resp=-1,
                    resp_list=(),
                    ok=False,
                    timed_out=True,
                    issued_id=int(id),
                )
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc

        observed_id = await capture.finish()
        result = OcahAxiWriteResult(
            address=int(getattr(raw, "address", addr)),
            length=int(getattr(raw, "length", len(payload))),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            issued_id=int(id),
            observed_id=observed_id,
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise("write to", addr, result.ok, result.resp, check_response)
        return result

    async def _read_bytes_result(
        self,
        addr: int,
        length: int,
        *,
        size: int | None,
        burst: int | None,
        id: int,
        prot: int | None,
        check_response: bool,
        timeout_ns: int | None,
        allow_timeout: bool,
        user: int = 0,
        attrs: dict[str, int] | None = None,
    ) -> OcahAxiReadResult:
        capture = self.driver.start_response_id_capture("r")
        event = self.driver.init_read(
            addr,
            length,
            id=id,
            size=size,
            **self._axkwargs(burst, prot, user, attrs, self._READ_ATTRS),
        )
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            capture.cancel()
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
                    issued_id=int(id),
                )
            raise AssertionError(f"{self.name}: read from 0x{addr:08X} timed out") from exc

        observed_id = await capture.finish()
        data_bytes = bytes(getattr(raw, "data", b""))
        beat_bytes = self.driver.bytes_for_beats(1, size)
        words = words_from_bytes(data_bytes, beat_bytes)
        result = OcahAxiReadResult(
            address=int(getattr(raw, "address", addr)),
            data=words[0] if words else 0,
            data_bytes=data_bytes,
            data_words=words,
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            issued_id=int(id),
            observed_id=observed_id,
            raw=raw,
        )
        self._read_count += 1
        self._maybe_raise("read from", addr, result.ok, result.resp, check_response)
        return result

    _READ_ATTRS = frozenset({"lock", "cache", "qos", "region"})
    _WRITE_ATTRS = _READ_ATTRS | {"wuser"}

    @staticmethod
    def _axkwargs(
        burst: int | None,
        prot: int | None,
        user: int = 0,
        attrs: dict[str, int] | None = None,
        allowed: frozenset[str] = frozenset(),
    ) -> dict[str, int]:
        kwargs: dict[str, int] = {"user": user}
        if burst is not None:
            kwargs["burst"] = burst
        if prot is not None:
            kwargs["prot"] = prot
        for key, value in (attrs or {}).items():
            if key not in allowed:
                raise ValueError(
                    f"unknown AXI attribute {key!r}; expected one of {sorted(allowed)}"
                )
            kwargs[key] = int(value)
        return kwargs

    def _maybe_raise(self, verb: str, addr: int, ok: bool, resp: int, check_response: bool) -> None:
        if check_response and self.raise_on_error and not ok:
            raise OcahAxiMasterError(
                f"{self.name}: {verb} 0x{addr:08X} returned response=0x{resp:X}"
            )
