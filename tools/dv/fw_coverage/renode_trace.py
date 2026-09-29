# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Writer for Renode execution-tracer PC-only streams."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import BinaryIO

_SIGNATURE = b"ReTrace"
_FORMAT_VERSION = 4
_NO_OPCODE = 0
_NO_ADDITIONAL_DATA = 0
TRACE_NAME = "sep_rom_pc_trace.bin.gz"


class RenodeTraceWriter:
    """Write each observed PC once to a gzip-compressed Renode trace."""

    def __init__(self, path: Path | str, pc_width_bytes: int = 4):
        if not 1 <= pc_width_bytes <= 8:
            raise ValueError("pc_width_bytes must be between 1 and 8")
        self.path = Path(path)
        self.pc_width_bytes = pc_width_bytes
        self._seen: set[int] = set()
        self._stream: BinaryIO | None = gzip.open(self.path, "wb")
        self._stream.write(_SIGNATURE + bytes((_FORMAT_VERSION, self.pc_width_bytes, _NO_OPCODE)))

    @property
    def count(self) -> int:
        return len(self._seen)

    def log_pc(self, pc: int) -> None:
        """Record ``pc`` unless it has already appeared in this trace."""
        if not 0 <= pc < (1 << (8 * self.pc_width_bytes)):
            raise ValueError(f"PC 0x{pc:x} does not fit in {self.pc_width_bytes} bytes")
        if pc in self._seen:
            return
        if self._stream is None:
            raise ValueError("trace is closed")
        self._seen.add(pc)
        self._stream.write(
            pc.to_bytes(self.pc_width_bytes, byteorder="little") + bytes((_NO_ADDITIONAL_DATA,))
        )

    def close(self) -> None:
        if self._stream is not None:
            self._stream.close()
            self._stream = None

    def __enter__(self) -> "RenodeTraceWriter":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()
