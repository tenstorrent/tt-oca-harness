# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain APB transaction items for monitors, checkers, and scoreboards."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

OcahApbDirection = Literal["read", "write"]


@dataclass(frozen=True)
class OcahApbItem:
    """Generic immutable APB transaction record."""

    direction: OcahApbDirection
    address: int
    data: int = 0
    data_bytes: bytes = b""
    strobe: int | None = None
    prot: int = 0
    pslverr: bool = False
    ok: bool = True
    timed_out: bool = False
    start_time_ns: int | None = None
    end_time_ns: int | None = None
    wait_cycles: int = 0
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def resp(self) -> int:
        """Return APB response code: 0 for OKAY, 2 for PSLVERR, -1 for timeout."""
        if self.timed_out:
            return -1
        return 2 if self.pslverr else 0

    @property
    def is_read(self) -> bool:
        return self.direction == "read"

    @property
    def is_write(self) -> bool:
        return self.direction == "write"

    @classmethod
    def write(
        cls,
        *,
        address: int,
        data: int = 0,
        data_bytes: bytes | bytearray = b"",
        strobe: int | None = None,
        prot: int = 0,
        pslverr: bool = False,
        source: str = "",
        **kwargs: Any,
    ) -> "OcahApbItem":
        return cls(
            direction="write",
            address=int(address),
            data=int(data),
            data_bytes=bytes(data_bytes),
            strobe=strobe,
            prot=int(prot),
            pslverr=bool(pslverr),
            ok=not bool(pslverr),
            source=source,
            **kwargs,
        )

    @classmethod
    def read(
        cls,
        *,
        address: int,
        data: int = 0,
        data_bytes: bytes | bytearray = b"",
        prot: int = 0,
        pslverr: bool = False,
        source: str = "",
        **kwargs: Any,
    ) -> "OcahApbItem":
        return cls(
            direction="read",
            address=int(address),
            data=int(data),
            data_bytes=bytes(data_bytes),
            prot=int(prot),
            pslverr=bool(pslverr),
            ok=not bool(pslverr),
            source=source,
            **kwargs,
        )
