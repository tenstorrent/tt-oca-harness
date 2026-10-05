# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Executable test programs deposited before SEP simulation starts."""

import re
from dataclasses import dataclass
from pathlib import Path

from warm_fault_words import WARM_FAULT_LOAD_ADDRESS, WARM_FAULT_WORDS
from warm_handler_words import WARM_HANDLER_LOAD_ADDRESS, WARM_HANDLER_WORDS


@dataclass(frozen=True)
class PreloadedTestProgram:
    load_address: int
    words: tuple[int, ...]
    source: str = ""

    def printed_tokens(self) -> set[str]:
        """Console tokens the stub source writes to the UART, one per output line."""
        text = Path(__file__).with_name(self.source).read_text()
        chars = b"".join(
            int(m, 16).to_bytes(4, "little").replace(b"\0", b"")
            for m in re.findall(r"li\s+t1,\s*(0x[0-9a-fA-F]+)", text)
        )
        return {line for line in chars.decode().splitlines() if line}

    def init_writes(self) -> list[tuple[int, int]]:
        return [(self.load_address + 4 * index, word) for index, word in enumerate(self.words)]


PROGRAMS = {
    "warm_jump": PreloadedTestProgram(
        load_address=WARM_HANDLER_LOAD_ADDRESS,
        words=WARM_HANDLER_WORDS,
        source="warm_handler_stub.S",
    ),
    "warm_jump_relocated": PreloadedTestProgram(
        load_address=0xC0038000,
        words=WARM_HANDLER_WORDS,
        source="warm_handler_stub.S",
    ),
    "warm_fault": PreloadedTestProgram(
        load_address=WARM_FAULT_LOAD_ADDRESS,
        words=WARM_FAULT_WORDS,
        source="warm_fault_stub.S",
    ),
}
