# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Load SMC CSR addresses from the generated PeakRDL C header (authoritative map)."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_SMC_ADDR_H = (
    Path(__file__).resolve().parents[6]
    / "hw"
    / "sys"
    / "smc"
    / "regs"
    / "gen"
    / "c"
    / "smc_addr.h"
)

_DEFINE_RE = re.compile(
    r"^\s*#define\s+(SMC_TOP_\w+)\s+(0x[0-9A-Fa-f]+|\d+)\s*$"
)


@lru_cache(maxsize=1)
def _smc_addr_table() -> dict[str, int]:
    text = _SMC_ADDR_H.read_text(encoding="utf-8")
    out: dict[str, int] = {}
    for line in text.splitlines():
        m = _DEFINE_RE.match(line)
        if m:
            out[m.group(1)] = int(m.group(2), 0)
    if not out:
        raise RuntimeError(f"no SMC_TOP_* defines parsed from {_SMC_ADDR_H}")
    return out


def smc_addr(symbol: str) -> int:
    """Return address for a ``SMC_TOP_*`` symbol from ``smc_addr.h``."""
    table = _smc_addr_table()
    try:
        return table[symbol]
    except KeyError as exc:
        raise KeyError(f"{symbol} not in {_SMC_ADDR_H}") from exc


# Canonical smoke probe: CHIP_CONFIG.VERSION_LO
SMC_CHIP_CONFIG_VERSION_LO = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"
)
