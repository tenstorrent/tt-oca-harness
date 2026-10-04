# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AXI4-Lite master sequence API: the VIP's test-facing stimulus surface.

`OcahAxiLiteMasterSequence` wraps one `OcahAxiLiteMasterDriver` and provides
the blocking, checked transaction API tests consume. ``write()`` returns a
response code and ``read()`` returns data as plain values;
``write_result()``/``read_result()`` expose response codes, data, and timeout
state through plain dataclasses.
``write_skewed_result()`` and ``read_hold_result()`` are the SV-UVM parity
protocol-control operations (independent AW/W launch skew, deferred
BREADY/RREADY with a response-stability check); ``write_pair_skewed_result()``
and ``read_pair_hold_result()`` are their two-outstanding forms, which queue a
second transaction behind the first before its response is accepted and
report the address channel's stall cycles and stability.
``pipeline_result()`` keeps any number of single-beat reads and writes in
flight together, each beat launched on its own cycle, with BREADY and RREADY
held after the first response. Tests drive the VIP
through this class (or the agent's ``sequence``), never through the raw
driver; missing operations get added here first.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from .ocah_axi_item import (
    OcahAxiPipelineOp,
    OcahAxiPipelineResult,
    OcahAxiReadPairResult,
    OcahAxiReadResult,
    OcahAxiWritePairResult,
    OcahAxiWriteResult,
)
from .ocah_axi_lite_master_driver import OcahAxiLiteMasterDriver, OcahAxiPipelineTimeoutError
from .ocah_axi_types import (
    axi_resp_ok,
    bytes_to_int,
    default_timeout_ns,
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


async def _wait_event(event, timeout_ns: int):
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
        """Issue a write and return a plain response object.

        A contiguous partial ``strb`` writes only the selected bytes of
        ``data`` (mapped onto a sub-word access); non-contiguous patterns are
        rejected by the backend mapping.
        """
        offset, payload = self.driver.strb_payload(data, strb)
        event = self.driver.init_write(int(addr) + offset, payload, **self._axkwargs(prot))
        try:
            raw = await _wait_event(event, self.timeout_ns if timeout_ns is None else timeout_ns)
        except _sim_timeout_error() as exc:
            if allow_timeout:
                return self._timed_out_write(addr, data, strb)
            raise AssertionError(f"{self.name}: write to 0x{addr:08X} timed out") from exc

        result = OcahAxiWriteResult(
            address=int(addr),
            length=int(getattr(raw, "length", len(payload))),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise("write to", addr, result.ok, result.resp, check_response)
        return result

    async def write_skewed_result(
        self,
        addr: int,
        data: int,
        *,
        aw_valid_delay: int = 0,
        w_valid_delay: int = 0,
        b_ready_delay: int = 0,
        strb: int | None = None,
        prot: int | None = None,
        check_response: bool = True,
        timeout_cycles: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWriteResult:
        """Issue a single-beat write with explicit channel skew (UVM parity op).

        ``aw_valid_delay``/``w_valid_delay`` hold that channel's VALID low for
        N cycles before it launches — AXI permits either arrival order, so
        demux and channel-ordering paths are exercised — and
        ``b_ready_delay`` defers the BREADY assert after the request phase.
        """
        cycles = self.timeout_cycles if timeout_cycles is None else int(timeout_cycles)
        try:
            raw = await self.driver.write_skewed(
                addr,
                data,
                strb=strb,
                aw_valid_delay=aw_valid_delay,
                w_valid_delay=w_valid_delay,
                b_ready_delay=b_ready_delay,
                timeout_cycles=cycles,
                **self._axkwargs(prot),
            )
        except TimeoutError as exc:
            if allow_timeout:
                return self._timed_out_write(addr, data, strb)
            raise AssertionError(f"{self.name}: skewed write to 0x{addr:08X} timed out") from exc

        result = OcahAxiWriteResult(
            address=int(addr),
            length=int(getattr(raw, "length", self.driver.bytes_per_beat)),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )
        self._write_count += 1
        self._maybe_raise("skewed write to", addr, result.ok, result.resp, check_response)
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

    async def read_hold_result(
        self,
        addr: int,
        hold_cycles: int,
        *,
        prot: int | None = None,
        check_response: bool = True,
        timeout_cycles: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadResult:
        """Issue a read holding RREADY low for ``hold_cycles`` (UVM parity op).

        RREADY stays low for ``hold_cycles`` after RVALID asserts; the result's
        ``hold_stable`` reports that RVALID stayed asserted with RDATA/RRESP
        unchanged across the window, as AXI requires of the responder.
        """
        cycles = self.timeout_cycles if timeout_cycles is None else int(timeout_cycles)
        try:
            raw, hold_stable = await self.driver.read_hold(
                addr,
                hold_cycles=hold_cycles,
                timeout_cycles=cycles,
                **self._axkwargs(prot),
            )
        except TimeoutError as exc:
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
            raise AssertionError(f"{self.name}: held read from 0x{addr:08X} timed out") from exc

        data_bytes = bytes(getattr(raw, "data", b""))
        result = OcahAxiReadResult(
            address=int(getattr(raw, "address", addr)),
            data=bytes_to_int(data_bytes),
            data_bytes=data_bytes,
            data_words=(bytes_to_int(data_bytes),),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            hold_stable=hold_stable,
            raw=raw,
        )
        self._read_count += 1
        self._maybe_raise("held read from", addr, result.ok, result.resp, check_response)
        return result

    async def write_pair_skewed_result(
        self,
        addr_a: int,
        data_a: int,
        addr_b: int,
        data_b: int,
        *,
        aw_valid_delay: int = 0,
        w_valid_delay: int = 0,
        b_ready_delay: int = 0,
        strb_a: int | None = None,
        strb_b: int | None = None,
        prot: int | None = None,
        check_response: bool = True,
        timeout_cycles: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiWritePairResult:
        """Issue two single-beat writes back to back with channel skew (UVM parity op).

        The second write's AW and W queue behind the first on their channels,
        so under a W launch delay the second AW meets the responder while the
        first W is pending; BREADY is deferred ``b_ready_delay`` cycles
        after the first write's request phase and both B responses are then
        accepted in order. The skew knobs are those of
        ``write_skewed_result``; the result adds the AW channel's stall
        cycles and stability across the pair.
        """
        cycles = self.timeout_cycles if timeout_cycles is None else int(timeout_cycles)
        try:
            raw_a, raw_b, stall_cycles, stable = await self.driver.write_pair_skewed(
                addr_a,
                data_a,
                addr_b,
                data_b,
                strb_a=strb_a,
                strb_b=strb_b,
                aw_valid_delay=aw_valid_delay,
                w_valid_delay=w_valid_delay,
                b_ready_delay=b_ready_delay,
                timeout_cycles=cycles,
                **self._axkwargs(prot),
            )
        except TimeoutError as exc:
            if allow_timeout:
                return OcahAxiWritePairResult(
                    first=self._timed_out_write(addr_a, data_a, strb_a),
                    second=self._timed_out_write(addr_b, data_b, strb_b),
                    aw_stall_cycles=0,
                    aw_stable=False,
                )
            raise AssertionError(
                f"{self.name}: paired write to 0x{addr_a:08X}/0x{addr_b:08X} timed out"
            ) from exc
        first = self._write_result_from_raw(addr_a, raw_a)
        second = self._write_result_from_raw(addr_b, raw_b)
        self._write_count += 2
        self._maybe_raise("paired write to", addr_a, first.ok, first.resp, check_response)
        self._maybe_raise("paired write to", addr_b, second.ok, second.resp, check_response)
        return OcahAxiWritePairResult(
            first=first, second=second, aw_stall_cycles=stall_cycles, aw_stable=stable
        )

    async def read_pair_hold_result(
        self,
        addr_a: int,
        addr_b: int,
        hold_cycles: int,
        *,
        prot: int | None = None,
        check_response: bool = True,
        timeout_cycles: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiReadPairResult:
        """Issue two reads, the second AR presented under an RREADY hold (UVM parity op).

        AR(b) queues behind AR(a) and RREADY stays low for ``hold_cycles``
        after the first RVALID, so a responder that admits one read at a
        time holds AR(b) with ARREADY low until the first beat is accepted.
        ``first.hold_stable`` reports the hold window's stability; the result
        adds the AR channel's stall cycles and stability across the pair.
        """
        cycles = self.timeout_cycles if timeout_cycles is None else int(timeout_cycles)
        try:
            raw_a, raw_b, hold_stable, stall_cycles, stable = await self.driver.read_pair_hold(
                addr_a,
                addr_b,
                hold_cycles=hold_cycles,
                timeout_cycles=cycles,
                **self._axkwargs(prot),
            )
        except TimeoutError as exc:
            if allow_timeout:
                return OcahAxiReadPairResult(
                    first=self._timed_out_read(addr_a),
                    second=self._timed_out_read(addr_b),
                    ar_stall_cycles=0,
                    ar_stable=False,
                )
            raise AssertionError(
                f"{self.name}: paired read from 0x{addr_a:08X}/0x{addr_b:08X} timed out"
            ) from exc
        first = self._read_result_from_raw(addr_a, raw_a, hold_stable=hold_stable)
        second = self._read_result_from_raw(addr_b, raw_b)
        self._read_count += 2
        self._maybe_raise("paired read from", addr_a, first.ok, first.resp, check_response)
        self._maybe_raise("paired read from", addr_b, second.ok, second.resp, check_response)
        return OcahAxiReadPairResult(
            first=first, second=second, ar_stall_cycles=stall_cycles, ar_stable=stable
        )

    async def pipeline_result(
        self,
        ops: Iterable[OcahAxiPipelineOp],
        *,
        b_hold_cycles: int = 0,
        r_hold_cycles: int = 0,
        check_response: bool = True,
        timeout_cycles: int | None = None,
        allow_timeout: bool = False,
    ) -> OcahAxiPipelineResult:
        """Issue single-beat reads and writes with several in flight (UVM parity op).

        Each ``OcahAxiPipelineOp`` launches its beats no earlier than its
        channel delays, counted in cycles from the start, and no earlier than
        the acceptance of the previous beat on the same channel, so reads and
        writes overlap and a responder meets as many requests as it accepts.
        BREADY and RREADY stay low until ``b_hold_cycles`` and
        ``r_hold_cycles`` cycles after the first BVALID and RVALID. The result
        lists one write or read result per access, in list order, with the
        stall cycles of each request channel. Every access is validated
        before any is issued, so an invalid one raises ``ValueError`` with no
        bus activity. When ``allow_timeout`` turns an expiry into a result,
        each access whose response arrived keeps its result, the others
        report ``timed_out``, and the stall cycles run up to the expiry;
        ``check_response`` covers the completed accesses only. The statistics
        count every completed access, including when an expiry raises.
        """
        ops = tuple(ops)
        cycles = self.timeout_cycles if timeout_cycles is None else int(timeout_cycles)
        expiry = None
        try:
            outcome = await self.driver.pipeline(
                ops,
                b_hold_cycles=b_hold_cycles,
                r_hold_cycles=r_hold_cycles,
                timeout_cycles=cycles,
            )
        except OcahAxiPipelineTimeoutError as exc:
            expiry = exc
            outcome = (exc.raws, exc.aw_stall_cycles, exc.w_stall_cycles, exc.ar_stall_cycles)
        raws, aw_stall, w_stall, ar_stall = outcome
        results = []
        for op, raw in zip(ops, raws):
            if raw is None:
                result = (
                    self._timed_out_write(op.address, op.data, op.strb)
                    if op.direction == "write"
                    else self._timed_out_read(op.address)
                )
            elif op.direction == "write":
                result = self._write_result_from_raw(op.address, raw)
                self._write_count += 1
            else:
                result = self._read_result_from_raw(op.address, raw)
                self._read_count += 1
            results.append(result)
        if expiry is not None and not allow_timeout:
            raise AssertionError(
                f"{self.name}: pipeline of {len(ops)} accesses timed out"
            ) from expiry
        for op, result in zip(ops, results):
            if not result.timed_out:
                self._maybe_raise(
                    f"pipelined {op.direction} at",
                    op.address,
                    result.ok,
                    result.resp,
                    check_response,
                )
        return OcahAxiPipelineResult(
            results=tuple(results),
            aw_stall_cycles=aw_stall,
            w_stall_cycles=w_stall,
            ar_stall_cycles=ar_stall,
        )

    def configure(self, **kwargs: Any) -> None:
        """Apply the supported knobs (timeout_cycles, timeout_ns); any other key is rejected."""
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
            "timeout_ns": self.timeout_ns,
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

    def _write_result_from_raw(self, addr: int, raw: Any) -> OcahAxiWriteResult:
        return OcahAxiWriteResult(
            address=int(addr),
            length=int(getattr(raw, "length", self.driver.bytes_per_beat)),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            raw=raw,
        )

    def _read_result_from_raw(
        self, addr: int, raw: Any, *, hold_stable: bool | None = None
    ) -> OcahAxiReadResult:
        data_bytes = bytes(getattr(raw, "data", b""))
        return OcahAxiReadResult(
            address=int(getattr(raw, "address", addr)),
            data=bytes_to_int(data_bytes),
            data_bytes=data_bytes,
            data_words=(bytes_to_int(data_bytes),),
            resp=worst_resp(getattr(raw, "resp", None)),
            resp_list=normalize_resp_list(getattr(raw, "resp", None)),
            ok=axi_resp_ok(getattr(raw, "resp", None)),
            hold_stable=hold_stable,
            raw=raw,
        )

    def _timed_out_write(self, addr: int, data: int, strb: int | None) -> OcahAxiWriteResult:
        _, payload = self.driver.strb_payload(data, strb)
        return OcahAxiWriteResult(
            address=int(addr),
            length=len(payload),
            resp=-1,
            resp_list=(),
            ok=False,
            timed_out=True,
        )

    @staticmethod
    def _timed_out_read(addr: int) -> OcahAxiReadResult:
        return OcahAxiReadResult(
            address=int(addr),
            data=0,
            data_bytes=b"",
            data_words=(),
            resp=-1,
            resp_list=(),
            ok=False,
            timed_out=True,
        )
