# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DV-owned GPIO pad lookup over the Integrator Guide's GPIO requirements table.

``doc/integrator/meta/ocah_gpio_table.csv`` is the source of the "OCAH GPIO
Requirements" table in the Integrator Guide (``doc/integrator/doc.mk`` renders
it to ``ocah_gpio_table.adoc``): one row per pad with its index, function,
recommended pull and notes. Sequences look pads up here by function name
instead of carrying a pad number, so a pad reassignment in the document moves
every stimulus with it, and a function the table does not name fails loudly.

The table also lists the JTAG, reference clock, reset and powergood pads, which
have no GPIO interface. Only rows whose index is below the RDL ``gpio_intf``
instance count in the generated ``smc_addr.h`` are pads this bench can drive.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from .smc_addr_map import smc_addr

_GPIO_TABLE_CSV = (
    Path(__file__).resolve().parents[6] / "doc" / "integrator" / "meta" / "ocah_gpio_table.csv"
)


@lru_cache(maxsize=1)
def _gpio_pad_rows() -> dict[str, int]:
    """Function name -> GPIO pad index; functions used twice are dropped."""
    count = gpio_pad_count()
    seen: dict[str, int] = {}
    ambiguous: set[str] = set()
    with _GPIO_TABLE_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            idx = int(row["Index"].strip())
            if idx >= count:
                continue
            function = row["Function"].strip()
            if function in seen:
                ambiguous.add(function)
            seen[function] = idx
    for function in ambiguous:
        del seen[function]
    if not seen:
        raise RuntimeError(f"no GPIO pad rows parsed from {_GPIO_TABLE_CSV}")
    return seen


def gpio_pad_count() -> int:
    """Number of GPIO interfaces the RDL declares (``gpio_intf[N]`` in ``smc.rdl``)."""
    return smc_addr("SMC_TOP_GPIO_INTF_NUM")


def pad_index(function: str) -> int:
    """GPIO pad index of the pad the Integrator Guide assigns ``function``."""
    try:
        return _gpio_pad_rows()[function]
    except KeyError as exc:
        raise KeyError(
            f"{function!r} is not a unique GPIO pad function in {_GPIO_TABLE_CSV}"
        ) from exc


def pad_function(index: int) -> str:
    """Function the Integrator Guide assigns GPIO pad ``index``."""
    assert 0 <= index < gpio_pad_count(), f"pad {index} is not a GPIO interface the RDL declares"
    with _GPIO_TABLE_CSV.open(encoding="utf-8", newline="") as fh:
        rows = [row for row in csv.DictReader(fh) if int(row["Index"].strip()) == index]
    assert len(rows) == 1, f"{_GPIO_TABLE_CSV}: expected one row for pad {index}, found {len(rows)}"
    return rows[0]["Function"].strip()


BOOT_STALL_PAD = pad_index("Boot Stall")
AVS_CLOCK_PAD = pad_index("AVS.CLOCK")
AVS_MDATA_PAD = pad_index("AVS.MDATA")
AVS_SDATA_PAD = pad_index("AVS.SDATA")
