# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Constants and helpers shared by the SEP fabric and remap tests.

* AXI response codes (IHI 0022 A3.4.4) and their names, with -1 for a
  response that never arrived.
* ``granule8``: the 8-byte filter granule that holds an address, as a
  ``(start, end)`` pair inside the filter address field.
* ``OUTBOUND_MBX_MAGIC``: the console and verdict magic words that the bench
  outbound responder decodes, read from ``tb/sep_outbound_mbx.sv`` so the two
  cannot drift.
"""

from __future__ import annotations

import re
from pathlib import Path

from sep_reg_meta import INBOUND_FILTER_CTRL_0

RESP_OKAY = 0
RESP_EXOKAY = 1
RESP_SLVERR = 2
RESP_DECERR = 3
RESP_NAME = {-1: "TIMEOUT", 0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR"}

# START_ADDR / END_ADDR field of a filter entry (the same in both banks).
FILTER_ADDR_MASK: int = INBOUND_FILTER_CTRL_0.field_mask("START_ADDR", "start_addr")


def resp_name(code: int) -> str:
    """Name of an AXI response code; ``none(<code>)`` for any other value."""
    return RESP_NAME.get(code, f"none({code})")


def granule8(addr: int) -> tuple[int, int]:
    """The 8-byte granule that holds ``addr``, inside the filter address field."""
    return addr & ~0x7 & FILTER_ADDR_MASK, addr | 0x7


def _outbound_mbx_magic() -> tuple[int, ...]:
    sv = Path(__file__).resolve().parents[2] / "tb" / "sep_outbound_mbx.sv"
    text = sv.read_text()
    words = []
    for name in ("Magic0", "MagicPass", "MagicFail"):
        m = re.search(
            rf"localparam\s+logic\s*\[31:0\]\s*{name}\s*=\s*32'h([0-9A-Fa-f_]+)\s*;", text
        )
        if m is None:
            raise RuntimeError(f"{sv}: localparam {name} not found")
        words.append(int(m.group(1).replace("_", ""), 16))
    return tuple(words)


OUTBOUND_MBX_MAGIC: tuple[int, ...] = _outbound_mbx_magic()
