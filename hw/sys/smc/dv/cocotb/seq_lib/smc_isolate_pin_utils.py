# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Isolate-request pad and ``skip_mem_repair_o`` helpers shared by the reset family.

The pad index comes from the DV-owned pad table
``doc/integrator/meta/ocah_gpio_table.csv`` (the row whose Function is
"Isolate Request"), read at import so a table change moves the stimulus with
it. The behaviour proven against it is the one ``clk_rst.adoc`` states under
"Function Level Reset": pin-based isolation is ``isolate_req_pin_i`` gated by
``ISOLATE_REQ_PINEN_REG`` (reset 0, so the pin has no effect until software
enables it), it is one of the three isolation sources, and "Memory Test
Bypass" activates ``skip_mem_repair_o`` automatically when either
FLR-triggered or pin-based isolation is asserted. A leaf that wants the pin to
count as an isolation source therefore programs ``ISOLATE_REQ_PINEN_REG``
first (``smc_isolate_req_pinen_seq``); what the output does with the pin high
and the enable at 0 is reported, never asserted.

``skip_mem_repair_o`` is sampled on ``tb_skip_mem_repair_o``, a passive mirror
of the wrapper output. The pin crosses a synchroniser into ``clk_smc_i``, so
every wait on the output is bounded and fails on expiry with the last level.
"""

from __future__ import annotations

import csv

from cocotb.triggers import ClockCycles

from .smc_addr_map import _REPO, reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_PAD_TABLE = _REPO / "doc" / "integrator" / "meta" / "ocah_gpio_table.csv"
_ISOLATE_REQ_FUNCTION = "Isolate Request"


def _isolate_req_pad() -> int:
    with _PAD_TABLE.open(newline="", encoding="utf-8") as handle:
        rows = [
            row for row in csv.DictReader(handle) if row.get("Function") == _ISOLATE_REQ_FUNCTION
        ]
    if len(rows) != 1:
        raise AssertionError(
            f"{_PAD_TABLE}: expected exactly one pad with Function "
            f"{_ISOLATE_REQ_FUNCTION!r}, found {len(rows)}"
        )
    return int(rows[0]["Index"])


#: GPIO pad index of the isolate-request pin, from the pad table.
ISOLATE_REQ_PAD = _isolate_req_pad()
ISOLATE_REQ_PINEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_PINEN_REG_BASE_ADDR")
#: Every subsystem's pin enable, from the generated field mask.
ISOLATE_REQ_PINEN_ALL = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_PINEN_REG__ISOLATE_REQ_PINEN_REG_bm"
)
#: Ceiling, in ``clk_smc_i`` cycles, for ``skip_mem_repair_o`` to follow a change
#: of its inputs through the pin synchroniser. A liveness bound, never a checked
#: quantity: expiry fails.
SKIP_SYNC_BOUND = 32


def drive_isolate_pin(dut, level: int | None) -> None:
    """Drive the isolate-request pad to ``level``, or release it when ``None``."""
    mask = 1 << ISOLATE_REQ_PAD
    en = int(dut.tb_gpio_ext_drive_en.value)
    val = int(dut.tb_gpio_ext_drive_value.value)
    if level is None:
        dut.tb_gpio_ext_drive_en.value = en & ~mask
        return
    if level:
        val |= mask
    else:
        val &= ~mask
    dut.tb_gpio_ext_drive_value.value = val
    dut.tb_gpio_ext_drive_en.value = en | mask


def skip_mem_repair(dut) -> int:
    raw = dut.tb_skip_mem_repair_o.value
    assert raw.is_resolvable, f"tb_skip_mem_repair_o is X/Z: {raw}"
    return int(raw) & 1


async def await_skip_mem_repair(dut, want: int, label: str, bound: int = SKIP_SYNC_BOUND) -> int:
    """Return the cycle on which ``skip_mem_repair_o`` first reads ``want``; fail on expiry."""
    last = -1
    for cycle in range(1, bound + 1):
        await ClockCycles(dut.clk_smc_i, 1)
        last = skip_mem_repair(dut)
        if last == want:
            return cycle
    raise AssertionError(
        f"{label}: tb_skip_mem_repair_o stayed {last} for {bound} clk_smc_i cycles, want {want}"
    )


class smc_isolate_req_pinen_seq(SmcCsrSeq):
    """Program ``ISOLATE_REQ_PINEN_REG`` over SEP_IN so the isolate pin is an isolation source.

    ``clk_rst.adoc`` defines pin-based isolation as the pin gated by this
    register, which resets to 0. The write is read back exactly (``sw = rw;
    hw = r``), so a register that did not take the enable fails here rather
    than leaving the pin legs to measure an ungated path.
    """

    def __init__(self, name: str = "smc_isolate_req_pinen_seq", enable: bool = True) -> None:
        super().__init__(name)
        self.value = ISOLATE_REQ_PINEN_ALL if enable else 0

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        await self.csr_read("ISOLATE_REQ_PINEN_RESET", ISOLATE_REQ_PINEN_REG, expected=0)
        await self.csr_write("ISOLATE_REQ_PINEN_WR", ISOLATE_REQ_PINEN_REG, self.value)
        await self.csr_read("ISOLATE_REQ_PINEN_RB", ISOLATE_REQ_PINEN_REG, expected=self.value)
