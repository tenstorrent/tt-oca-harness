# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI type constants and value-conversion helpers (side-neutral).

Response and protection codes as plain integers, the bus-protocol ``Enum``,
and the conversions between backend payloads and plain Python values. The
wrapper layer keeps cocotbext transaction objects and enums behind this
boundary; tests assert on these names without importing backend-specific
types. The SV-UVM flow carries the same role as ``uvm/ocah_axi_types.svh``.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

__all__ = [
    "PROT_INSTRUCTION",
    "PROT_NONSECURE",
    "PROT_PRIVILEGED",
    "RESP_DECERR",
    "RESP_EXOKAY",
    "RESP_OKAY",
    "RESP_SLVERR",
    "RESP_TIMEOUT",
    "OcahAxiProtocol",
    "axi_resp_ok",
    "bytes_to_int",
    "normalize_resp_list",
    "resp_name",
    "words_from_bytes",
    "worst_resp",
]

RESP_OKAY = 0
RESP_EXOKAY = 1
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_TIMEOUT = -1

# AxPROT bit values (IHI 0022 A4.7): OR them into the `prot` argument.
PROT_PRIVILEGED = 1
PROT_NONSECURE = 2
PROT_INSTRUCTION = 4


class OcahAxiProtocol(Enum):
    """Bus protocol of one connection; twin of ``ocah_axi_protocol_e``."""

    AXI4 = "axi4"
    AXI4_LITE = "axi4_lite"


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
