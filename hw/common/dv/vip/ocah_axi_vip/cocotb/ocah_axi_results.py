# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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

# AxPROT bit values (IHI 0022 A4.7): OR them into the `prot` argument.
PROT_PRIVILEGED = 1
PROT_NONSECURE = 2
PROT_INSTRUCTION = 4

_RESP_NAMES = {
    RESP_OKAY: "OKAY",
    RESP_EXOKAY: "EXOKAY",
    RESP_SLVERR: "SLVERR",
    RESP_DECERR: "DECERR",
    RESP_TIMEOUT: "TIMEOUT",
}


def resp_name(resp: Any) -> str:
    """Human-readable name for a response code (worst beat of a list)."""
    code = worst_resp(resp)
    return _RESP_NAMES.get(code, str(resp))


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


def words_from_bytes(
    data: bytes | bytearray, beat_bytes: int, *, byteorder: str = "little"
) -> tuple[int, ...]:
    """Split backend byte payloads into one integer per AXI beat."""
    payload = bytes(data)
    if beat_bytes <= 0:
        raise ValueError(f"beat_bytes must be positive, got {beat_bytes}")
    return tuple(
        int.from_bytes(payload[offset : offset + beat_bytes], byteorder)
        for offset in range(0, len(payload), beat_bytes)
    )


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

    def to_item(self, *, protocol: str = "axi4", source: str = "master"):
        """Convert this result into an OCAH transaction item."""
        from .ocah_axi_item import OcahAxiItem

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
    raw: Any = None

    @property
    def id_match(self) -> bool | None:
        """True/False when both IDs are known; ``None`` when either is not."""
        if self.issued_id is None or self.observed_id is None:
            return None
        return int(self.issued_id) == int(self.observed_id)

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
            transaction_id=self.issued_id,
            metadata={"data": self.data, "observed_id": self.observed_id},
        )
