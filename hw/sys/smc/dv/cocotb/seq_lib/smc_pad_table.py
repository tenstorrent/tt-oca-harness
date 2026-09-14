# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DV-owned GPIO pad lookup over the Integrator Guide's GPIO requirements table.

``doc/integrator/meta/ocah_gpio_table.csv`` is the source of the "OCAH GPIO
Requirements" table in the Integrator Guide (``doc/integrator/doc.mk`` renders
it to ``ocah_gpio_table.adoc``): one row per pad with its index, wrapper signal,
function and recommended pull. Sequences look pads up here by function name
instead of carrying a pad number, so a pad reassignment in the document moves
every stimulus with it, and a function the table does not name fails loudly.

The pad count is cross-checked against the RDL ``gpio_intf`` instance count in
the generated ``smc_addr.h``: a GPIO_PAD index the register map has no
interface for is not a pad this bench can drive.
"""

from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from .smc_addr_map import smc_addr

_GPIO_TABLE_CSV = (
    Path(__file__).resolve().parents[6] / "doc" / "integrator" / "meta" / "ocah_gpio_table.csv"
)
_GPIO_PAD_SIGNAL_RE = re.compile(r"^smc_wrapper\.GPIO_PAD\[(\d+)\]$")


@lru_cache(maxsize=1)
def _gpio_pad_rows() -> dict[str, int]:
    """Function name -> ``smc_wrapper.GPIO_PAD`` index; functions used twice are dropped."""
    seen: dict[str, int] = {}
    ambiguous: set[str] = set()
    with _GPIO_TABLE_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            m = _GPIO_PAD_SIGNAL_RE.match(row["Signal"].strip())
            if m is None:
                continue
            function = row["Function"].strip()
            if function in seen:
                ambiguous.add(function)
            seen[function] = int(m.group(1))
    for function in ambiguous:
        del seen[function]
    if not seen:
        raise RuntimeError(f"no GPIO_PAD rows parsed from {_GPIO_TABLE_CSV}")
    return seen


def gpio_pad_count() -> int:
    """Number of GPIO interfaces the RDL declares (``gpio_intf[N]`` in ``smc.rdl``)."""
    return smc_addr("SMC_TOP_GPIO_INTF_NUM")


def pad_index(function: str) -> int:
    """``smc_wrapper.GPIO_PAD`` index of the pad the Integrator Guide assigns ``function``."""
    try:
        idx = _gpio_pad_rows()[function]
    except KeyError as exc:
        raise KeyError(
            f"{function!r} is not a unique GPIO_PAD function in {_GPIO_TABLE_CSV}"
        ) from exc
    assert idx < gpio_pad_count(), (
        f"{function} is GPIO_PAD[{idx}] but the RDL declares only {gpio_pad_count()} gpio_intf"
    )
    return idx


BOOT_STALL_PAD = pad_index("Boot Stall")
AVS_CLOCK_PAD = pad_index("AVS.CLOCK")
AVS_MDATA_PAD = pad_index("AVS.MDATA")
AVS_SDATA_PAD = pad_index("AVS.SDATA")
