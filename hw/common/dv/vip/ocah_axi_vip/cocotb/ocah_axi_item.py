# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain AXI transaction dataclasses (side-neutral).

Transaction items for monitors, checkers, and scoreboards, plus the
write/read result objects the wrapper result APIs return. The wrapper layer
keeps cocotbext transaction objects behind this boundary; tests assert on
these dataclasses without importing backend-specific types.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from .ocah_axi_types import RESP_EXOKAY, RESP_OKAY, RESP_TIMEOUT, axi_resp_ok, worst_resp

OcahAxiProtocol = Literal["axi4", "axi4-lite"]
OcahAxiDirection = Literal["read", "write"]


def _tuple_int(values: tuple[int, ...] | list[int] | None) -> tuple[int, ...]:
    if values is None:
        return ()
    return tuple(int(value) for value in values)


def _pop_fixed_fields(
    kwargs: dict[str, Any],
    *,
    protocol: OcahAxiProtocol,
    direction: OcahAxiDirection,
) -> None:
    requested_protocol = kwargs.pop("protocol", protocol)
    requested_direction = kwargs.pop("direction", direction)
    if requested_protocol != protocol or requested_direction != direction:
        raise ValueError(
            f"expected {protocol} {direction} item, got {requested_protocol} {requested_direction}"
        )


@dataclass(frozen=True, init=False)
class OcahAxiItem:
    """Generic immutable AXI transaction record."""

    protocol: OcahAxiProtocol
    direction: OcahAxiDirection
    address: int
    data_bytes: bytes = b""
    data_words: tuple[int, ...] = ()
    strobes: tuple[int, ...] = ()
    size: int | None = None
    burst: int | None = None
    transaction_id: int | None = None
    prot: int = 0
    resp_list: tuple[int, ...] = ()
    ok: bool = True
    timed_out: bool = False
    start_time_ns: int | None = None
    end_time_ns: int | None = None
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __init__(
        self,
        *,
        protocol: OcahAxiProtocol,
        direction: OcahAxiDirection,
        address: int,
        data_bytes: bytes = b"",
        data_words: tuple[int, ...] = (),
        strobes: tuple[int, ...] = (),
        size: int | None = None,
        burst: int | None = None,
        transaction_id: int | None = None,
        prot: int = 0,
        resp_list: tuple[int, ...] = (),
        ok: bool = True,
        timed_out: bool = False,
        start_time_ns: int | None = None,
        end_time_ns: int | None = None,
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Keyword-only initializer coercing every field to its plain frozen type."""
        object.__setattr__(self, "protocol", protocol)
        object.__setattr__(self, "direction", direction)
        object.__setattr__(self, "address", int(address))
        object.__setattr__(self, "data_bytes", bytes(data_bytes))
        object.__setattr__(self, "data_words", _tuple_int(data_words))
        object.__setattr__(self, "strobes", _tuple_int(strobes))
        object.__setattr__(self, "size", size)
        object.__setattr__(self, "burst", burst)
        object.__setattr__(self, "transaction_id", transaction_id)
        object.__setattr__(self, "prot", int(prot))
        object.__setattr__(self, "resp_list", _tuple_int(resp_list))
        object.__setattr__(self, "ok", bool(ok))
        object.__setattr__(self, "timed_out", bool(timed_out))
        object.__setattr__(self, "start_time_ns", start_time_ns)
        object.__setattr__(self, "end_time_ns", end_time_ns)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "metadata", dict(metadata or {}))

    @property
    def resp(self) -> int:
        """Return the worst response code for this transaction."""
        if self.timed_out:
            return RESP_TIMEOUT
        return worst_resp(self.resp_list)

    @property
    def is_read(self) -> bool:
        return self.direction == "read"

    @property
    def is_write(self) -> bool:
        return self.direction == "write"

    @property
    def beat_count(self) -> int:
        if self.data_words:
            return len(self.data_words)
        if self.resp_list:
            return len(self.resp_list)
        return 1

    @property
    def first_data(self) -> int:
        return self.data_words[0] if self.data_words else 0

    @classmethod
    def write(
        cls,
        *,
        protocol: OcahAxiProtocol,
        address: int,
        data_bytes: bytes | bytearray = b"",
        data_words: tuple[int, ...] | list[int] | None = None,
        strobes: tuple[int, ...] | list[int] | None = None,
        resp_list: tuple[int, ...] | list[int] | None = None,
        source: str = "",
        **kwargs: Any,
    ) -> "OcahAxiItem":
        responses = _tuple_int(resp_list)
        return cls(
            protocol=protocol,
            direction="write",
            address=int(address),
            data_bytes=bytes(data_bytes),
            data_words=_tuple_int(data_words),
            strobes=_tuple_int(strobes),
            resp_list=responses,
            ok=axi_resp_ok(responses) if responses else True,
            source=source,
            **kwargs,
        )

    @classmethod
    def read(
        cls,
        *,
        protocol: OcahAxiProtocol,
        address: int,
        data_bytes: bytes | bytearray = b"",
        data_words: tuple[int, ...] | list[int] | None = None,
        resp_list: tuple[int, ...] | list[int] | None = None,
        source: str = "",
        **kwargs: Any,
    ) -> "OcahAxiItem":
        responses = _tuple_int(resp_list)
        return cls(
            protocol=protocol,
            direction="read",
            address=int(address),
            data_bytes=bytes(data_bytes),
            data_words=_tuple_int(data_words),
            resp_list=responses,
            ok=axi_resp_ok(responses) if responses else True,
            source=source,
            **kwargs,
        )


@dataclass(frozen=True, init=False)
class OcahAxiWriteItem(OcahAxiItem):
    """AXI4 write transaction item."""

    protocol: OcahAxiProtocol = "axi4"
    direction: OcahAxiDirection = "write"

    def __init__(self, **kwargs: Any) -> None:
        _pop_fixed_fields(kwargs, protocol="axi4", direction="write")
        super().__init__(protocol="axi4", direction="write", **kwargs)


@dataclass(frozen=True, init=False)
class OcahAxiReadItem(OcahAxiItem):
    """AXI4 read transaction item."""

    protocol: OcahAxiProtocol = "axi4"
    direction: OcahAxiDirection = "read"

    def __init__(self, **kwargs: Any) -> None:
        _pop_fixed_fields(kwargs, protocol="axi4", direction="read")
        super().__init__(protocol="axi4", direction="read", **kwargs)


@dataclass(frozen=True, init=False)
class OcahAxiLiteWriteItem(OcahAxiItem):
    """AXI4-Lite write transaction item."""

    protocol: OcahAxiProtocol = "axi4-lite"
    direction: OcahAxiDirection = "write"

    def __init__(self, **kwargs: Any) -> None:
        _pop_fixed_fields(kwargs, protocol="axi4-lite", direction="write")
        super().__init__(protocol="axi4-lite", direction="write", **kwargs)


@dataclass(frozen=True, init=False)
class OcahAxiLiteReadItem(OcahAxiItem):
    """AXI4-Lite read transaction item."""

    protocol: OcahAxiProtocol = "axi4-lite"
    direction: OcahAxiDirection = "read"

    def __init__(self, **kwargs: Any) -> None:
        _pop_fixed_fields(kwargs, protocol="axi4-lite", direction="read")
        super().__init__(protocol="axi4-lite", direction="read", **kwargs)


def response_is_success(resp: int) -> bool:
    """True for AXI OKAY and EXOKAY response codes."""
    return int(resp) in (RESP_OKAY, RESP_EXOKAY)


@dataclass(frozen=True)
class OcahAxiWriteResult:
    """Plain AXI write result returned by OCAH wrapper result APIs.

    ``issued_id`` is the AWID the master drove; ``observed_id`` is the BID
    independently sampled from the live B-channel handshake — never a copy of
    the issued ID, so an ID-echo defect in the responder is distinguishable.
    ``observed_id`` is ``None`` when no ID was captured (AXI4-Lite buses,
    timeouts, or a capture miss).
    """

    address: int
    length: int
    resp: int
    resp_list: tuple[int, ...]
    ok: bool
    timed_out: bool = False
    issued_id: int | None = None
    observed_id: int | None = None
    raw: Any = None

    @property
    def id_match(self) -> bool | None:
        """True/False when both IDs are known; ``None`` when either is not."""
        if self.issued_id is None or self.observed_id is None:
            return None
        return int(self.issued_id) == int(self.observed_id)

    def to_item(self, *, protocol: str = "axi4", source: str = "master") -> OcahAxiItem:
        """Convert this result into an OCAH transaction item."""
        return OcahAxiItem.write(
            protocol=protocol,
            address=self.address,
            resp_list=self.resp_list,
            source=source,
            timed_out=self.timed_out,
            transaction_id=self.issued_id,
            metadata={"length": self.length, "observed_id": self.observed_id},
        )


@dataclass(frozen=True)
class OcahAxiReadResult:
    """Plain AXI read result returned by OCAH wrapper result APIs.

    ``issued_id`` is the ARID the master drove; ``observed_id`` is the RID
    independently sampled from the live R-channel handshake on the completing
    (RLAST) beat — never a copy of the issued ID.  ``observed_id`` is ``None``
    when no ID was captured (AXI4-Lite buses, timeouts, or a capture miss).

    ``hold_stable`` reports that RVALID stayed asserted with RDATA/RRESP
    unchanged across a requested RREADY-hold window (``read_hold_result``);
    it is ``None`` when no hold was requested.
    """

    address: int
    data: int
    data_bytes: bytes
    data_words: tuple[int, ...]
    resp: int
    resp_list: tuple[int, ...]
    ok: bool
    timed_out: bool = False
    issued_id: int | None = None
    observed_id: int | None = None
    hold_stable: bool | None = None
    raw: Any = None

    @property
    def id_match(self) -> bool | None:
        """True/False when both IDs are known; ``None`` when either is not."""
        if self.issued_id is None or self.observed_id is None:
            return None
        return int(self.issued_id) == int(self.observed_id)

    def to_item(self, *, protocol: str = "axi4", source: str = "master") -> OcahAxiItem:
        """Convert this result into an OCAH transaction item."""
        return OcahAxiItem.read(
            protocol=protocol,
            address=self.address,
            data_bytes=self.data_bytes,
            data_words=self.data_words,
            resp_list=self.resp_list,
            source=source,
            timed_out=self.timed_out,
            transaction_id=self.issued_id,
            metadata={
                "data": self.data,
                "observed_id": self.observed_id,
                "hold_stable": self.hold_stable,
            },
        )


@dataclass(frozen=True)
class OcahAxiWritePairResult:
    """Two single-beat writes issued back to back (``write_pair_skewed_result``).

    ``first`` and ``second`` are the per-transaction results in issue order.
    ``aw_stall_cycles`` counts the cycles AWVALID was held while AWREADY was
    low across the pair, and ``aw_stable`` reports that every such stalled
    beat kept AWVALID asserted with AWADDR unchanged until AWREADY
    (IHI 0022 A3.2.1).
    """

    first: OcahAxiWriteResult
    second: OcahAxiWriteResult
    aw_stall_cycles: int
    aw_stable: bool

    @property
    def ok(self) -> bool:
        return self.first.ok and self.second.ok

    @property
    def timed_out(self) -> bool:
        return self.first.timed_out or self.second.timed_out


@dataclass(frozen=True)
class OcahAxiReadPairResult:
    """Two single-beat reads with the second AR presented under an RREADY hold
    (``read_pair_hold_result``).

    ``first`` and ``second`` are the per-transaction results in issue order;
    ``first.hold_stable`` carries the hold window's RVALID/RDATA/RRESP
    stability. ``ar_stall_cycles`` counts the cycles ARVALID was held while
    ARREADY was low across the pair, and ``ar_stable`` reports that every such
    stalled beat kept ARVALID asserted with ARADDR unchanged until ARREADY
    (IHI 0022 A3.2.1).
    """

    first: OcahAxiReadResult
    second: OcahAxiReadResult
    ar_stall_cycles: int
    ar_stable: bool

    @property
    def ok(self) -> bool:
        return self.first.ok and self.second.ok

    @property
    def timed_out(self) -> bool:
        return self.first.timed_out or self.second.timed_out
