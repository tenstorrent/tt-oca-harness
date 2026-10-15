# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS timer started as PRIMARY from reset, and started again during its own sync pulse.

This leaf keeps the bench strap at PRIMARY and starts a timer that has never
run:

* **Programmed before it runs.** `CTRL` is written while the timer is idle
  with the setting it runs on: `CREDIT_VAL` 0xFF and `PULSE_WIDTH` 0xF0, which
  keeps the RDL's rule that the credit value exceed the pulse width.
  `STATUS.RUNNING` must read clear.
* **A first start from zero.** `TIMER_PRESET` is 0, so the count starts at
  zero. After `TIMER_START` `STATUS.RUNNING` must set and `TIMER_COUNT` must
  advance.
* **A start during the sync pulse.** `TIMER_START` "asserts the sync_load
  signal"; a pulse lasts `PULSE_WIDTH` cycles. A second start written while
  the first one's pulse is still out must reload the preset: the count read
  right after it has to be below the count read twice after the first start.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_octs_dual_sync_test_seq import (
    _OCTS_COUNT_HI,
    _OCTS_COUNT_LO,
    _OCTS_CTRL,
    _OCTS_PRESET_HI,
    _OCTS_PRESET_LO,
    _OCTS_STATUS,
    _OCTS_STATUS_MODE,
    _OCTS_STATUS_RUNNING,
    _OCTS_TIMER_START,
)


def _ctrl(credit: int, pulse: int, step: int = 1) -> int:
    return (credit & 0xFF) | ((pulse & 0xFF) << 8) | ((step & 0xFF) << 16)


#: The credit value above the pulse width, as the RDL requires, and the pulse
#: long enough to still be out when a second start lands.
RUN_CTRL = _ctrl(0xFF, 0xF0)
RUN_CYCLES = 400


class smc_octs_primary_start_test_seq(SmcCsrSeq):
    """Start a never-run PRIMARY OCTS timer from zero, then again during its sync pulse."""

    async def _count(self, label: str) -> int:
        lo = await self.csr_read(f"{label}_LO", _OCTS_COUNT_LO)
        hi = await self.csr_read(f"{label}_HI", _OCTS_COUNT_HI)
        return (hi << 32) | lo

    async def body(self) -> None:
        clk = cocotb.top.clk_smc_i
        status = await self.csr_read("STATUS_ENTRY", _OCTS_STATUS)
        assert not status & (_OCTS_STATUS_MODE | _OCTS_STATUS_RUNNING), (
            f"STATUS=0x{status:08x} before anything is written; the timer is PRIMARY and idle"
        )
        await self.csr_write("CTRL_RUN", _OCTS_CTRL, RUN_CTRL)
        await self.csr_read("CTRL_RUN_RB", _OCTS_CTRL, expected=RUN_CTRL)
        await self.csr_write("PRESET_LO", _OCTS_PRESET_LO, 0)
        await self.csr_write("PRESET_HI", _OCTS_PRESET_HI, 0)
        status = await self.csr_read("STATUS_IDLE", _OCTS_STATUS)
        assert not status & _OCTS_STATUS_RUNNING, (
            f"STATUS.RUNNING set before TIMER_START (0x{status:08x})"
        )

        await self.csr_write("START", _OCTS_TIMER_START, 1)
        first = await self.csr_read("COUNT_FIRST", _OCTS_COUNT_LO)
        second = await self.csr_read("COUNT_SECOND", _OCTS_COUNT_LO)
        await self.csr_write("START_AGAIN", _OCTS_TIMER_START, 1)
        again = await self.csr_read("COUNT_AGAIN", _OCTS_COUNT_LO)
        await ClockCycles(clk, RUN_CYCLES)
        later = await self._count("COUNT_LATER")
        status = await self.csr_read("STATUS_RUN", _OCTS_STATUS)
        assert status & _OCTS_STATUS_RUNNING, (
            f"STATUS.RUNNING clear after TIMER_START (0x{status:08x})"
        )
        assert first < second, f"TIMER_COUNT did not advance after the start ({first}, {second})"
        assert again < second, (
            f"TIMER_COUNT read {first} and then {second} after the first start, and {again} "
            f"after the second; a start reloads the preset of 0, so the read after it, taken "
            f"as soon after it as the first read was after the first start, is below the "
            f"second read"
        )
        assert later > again, f"TIMER_COUNT did not advance after the second start ({later})"
        cocotb.log.info(
            "CHK-OCTS-PRIMARY-START: a never-run PRIMARY timer programmed while idle started "
            "from a preset of 0 with STATUS.RUNNING set; a second TIMER_START written during "
            "the first one's sync pulse brought the count back to 0x%x after it had reached "
            "0x%x, and it advanced to 0x%x",
            again,
            second,
            later,
        )
