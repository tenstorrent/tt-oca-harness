# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Plain OCAH AXI response/result objects.

The wrapper layer keeps cocotbext transaction objects behind this boundary.
Tests may assert on these dataclasses without importing backend-specific enums.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

RESP_OKAY = 0
RESP_EXOKAY = 1
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_TIMEOUT = -1


def normalize_resp_list(resp: Any) -> tuple[int, ...]:
    """Return a tuple of plain response codes from scalar/list/backend enums."""
    if resp is None:
        return ()
    if isinstance(resp, (list, tuple)):
        return tuple(int(code) for code in resp)
    return (int(resp),)


def worst_resp(resp: Any) -> int:
    """Return the worst response code, or -1 if no response is readable."""
    codes = normalize_resp_list(resp)
    return max(codes) if codes else RESP_TIMEOUT


def axi_resp_ok(resp: Any) -> bool:
    """True when every response beat is OKAY or EXOKAY."""
    codes = normalize_resp_list(resp)
    return bool(codes) and all(code in (RESP_OKAY, RESP_EXOKAY) for code in codes)


def bytes_to_int(data: bytes | bytearray, *, byteorder: str = "little") -> int:
    """Convert backend byte payloads to a plain integer."""
    return int.from_bytes(bytes(data), byteorder)


def words_from_bytes(data: bytes | bytearray, beat_bytes: int, *, byteorder: str = "little") -> tuple[int, ...]:
    """Split backend byte payloads into one integer per AXI beat."""
    payload = bytes(data)
    if beat_bytes <= 0:
        raise ValueError(f"beat_bytes must be positive, got {beat_bytes}")
    return tuple(
        int.from_bytes(payload[offset:offset + beat_bytes], byteorder)
        for offset in range(0, len(payload), beat_bytes)
    )


@dataclass(frozen=True)
class OcahAxiWriteResult:
    """Plain AXI write result returned by OCAH wrapper result APIs."""

    address: int
    length: int
    resp: int
    resp_list: tuple[int, ...]
    ok: bool
    timed_out: bool = False
    raw: Any = None

    def to_item(self, *, protocol: str = "axi4", source: str = "master"):
        """Convert this result into an OCAH transaction item."""
        from .ocah_axi_item import OcahAxiItem

        return OcahAxiItem.write(
            protocol=protocol,
            address=self.address,
            resp_list=self.resp_list,
            source=source,
            timed_out=self.timed_out,
            metadata={"length": self.length},
        )


@dataclass(frozen=True)
class OcahAxiReadResult:
    """Plain AXI read result returned by OCAH wrapper result APIs."""

    address: int
    data: int
    data_bytes: bytes
    data_words: tuple[int, ...]
    resp: int
    resp_list: tuple[int, ...]
    ok: bool
    timed_out: bool = False
    raw: Any = None

    def to_item(self, *, protocol: str = "axi4", source: str = "master"):
        """Convert this result into an OCAH transaction item."""
        from .ocah_axi_item import OcahAxiItem

        return OcahAxiItem.read(
            protocol=protocol,
            address=self.address,
            data_bytes=self.data_bytes,
            data_words=self.data_words,
            resp_list=self.resp_list,
            source=source,
            timed_out=self.timed_out,
            metadata={"data": self.data},
        )
