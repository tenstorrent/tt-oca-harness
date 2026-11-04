# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS system timer advances at the clk_smc_i rate.

``clk_rst.adoc`` (Timer and Debug Timebases) states "OCTS uses ``clk_smc_i``";
the OCTS architecture describes a "continuously incrementing 64-bit counter"
that, in PRIMARY mode, advances by ``CREDIT_VAL`` every ``CREDIT_VAL`` cycles of
that clock. Two reads of ``TIMER_COUNT`` bracket an interval whose ``clk_smc_i``
rising edges the bench counts independently; the count delta must lie within
the edge count widened only by the ``CREDIT_VAL`` credit granularity and a
count-latch allowance. The bench counts ``clk_ref_i`` edges over the same
window and requires that count to fall outside the window, so a counter clocked
from the reference clock would fail the bracket.

The CLINT ``mtime`` half of the scenario is not reachable from SEP_IN in this
bench (at the reset REGION_SIZE the cluster-local window lies outside the local
and global apertures and answers DECERR) and is not covered here.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT  # noqa: E402

OCTS_TIMER_START = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_START_BASE_ADDR")
OCTS_CTRL = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_CTRL_BASE_ADDR")
OCTS_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
OCTS_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
OCTS_COUNT_HI = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_HI_BASE_ADDR")

_REPO = Path(__file__).resolve().parents[6]
_OCTS_H = _REPO / "hw" / "ip" / "system_timer_octs" / "regs" / "gen" / "c" / "system_timer_octs.h"


def _octs_field(symbol: str) -> int:
    for line in _OCTS_H.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0] == "#define" and parts[1] == symbol:
            return int(parts[2], 0)
    raise KeyError(f"{symbol} not in {_OCTS_H}")


CREDIT_VAL_BM = _octs_field("SYSTEM_TIMER_OCTS__CTRL__CREDIT_VAL_bm")
CREDIT_VAL_BP = _octs_field("SYSTEM_TIMER_OCTS__CTRL__CREDIT_VAL_bp")
STATUS_RUNNING_BM = _octs_field("SYSTEM_TIMER_OCTS__STATUS__RUNNING_bm")
STATUS_MODE_BM = _octs_field("SYSTEM_TIMER_OCTS__STATUS__MODE_bm")
TIMER_START_BM = _octs_field("SYSTEM_TIMER_OCTS__TIMER_START__START_bm")
CREDIT_VAL_RESET = (SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT & CREDIT_VAL_BM) >> CREDIT_VAL_BP
assert CREDIT_VAL_RESET > 0

# clk_smc_i edges awaited between the two samples; long enough that a counter
# on the wrong clock lands far outside the credit-granularity tolerance.
WINDOW_EDGES = 3200
# A few clk_smc_i periods between the count advancing and a register read
# returning it, on top of the credit granularity.
LATCH_SKEW_SMC = 4
START_BOUND_READS = 32
# Accesses the body issues outside the STATUS poll: the CTRL reset read, the
# TIMER_START write, and two TIMER_COUNT reads of a LO and a HI register each.
# The poll count is only known at run time and is added at the call site.
EXPECTED_ACCESSES = 6


class smc_octs_timer_rate_test_seq(SmcCsrSeq):
    """TIMER_COUNT delta bracketed by an independent clk_smc_i edge count."""

    def __init__(self, name: str = "smc_octs_timer_rate_test_seq") -> None:
        super().__init__(name)
        self.c0: int | None = None
        self.c1: int | None = None
        self.delta: int | None = None
        self.smc_edges_lo: int | None = None
        self.smc_edges_hi: int | None = None
        self.ref_edges_hi: int | None = None
        self.tolerance = CREDIT_VAL_RESET + LATCH_SKEW_SMC

    async def _read_count(self, label: str) -> int:
        lo = await self.csr_read(f"{label}_LO", OCTS_COUNT_LO)
        hi = await self.csr_read(f"{label}_HI", OCTS_COUNT_HI)
        return (hi << 32) | lo

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert int(dut.tb_chiplet_is_primary.value) == 1, "this bench must be the PRIMARY chiplet"

        await self.csr_read(
            "OCTS_CTRL_RESET", OCTS_CTRL, expected=SYSTEM_TIMER_OCTS_CTRL_REG_DEFAULT
        )
        await self.csr_write("OCTS_TIMER_START", OCTS_TIMER_START, TIMER_START_BM)
        status = None
        for _ in range(START_BOUND_READS):
            status = await self.csr_read("OCTS_STATUS", OCTS_STATUS)
            if status & STATUS_RUNNING_BM:
                break
            await RisingEdge(dut.clk_smc_i)
        assert status is not None and status & STATUS_RUNNING_BM, (
            f"OCTS STATUS.RUNNING never rose after TIMER_START (STATUS=0x{status:x})"
        )
        assert (status & STATUS_MODE_BM) == 0, f"OCTS STATUS reports SECONDARY mode: 0x{status:x}"
        status_reads = self.accesses - 2

        edges = {"ref": 0, "smc": 0}
        stop = {"done": False}

        async def _count(clk, key: str) -> None:
            while not stop["done"]:
                await RisingEdge(clk)
                edges[key] += 1

        ref_task = cocotb.start_soon(_count(dut.clk_ref_i, "ref"))
        smc_task = cocotb.start_soon(_count(dut.clk_smc_i, "smc"))
        try:
            self.c0 = await self._read_count("OCTS_COUNT_0")
            n_after_c0 = edges["smc"]
            for _ in range(WINDOW_EDGES):
                await RisingEdge(dut.clk_smc_i)
            n_before_c1 = edges["smc"]
            self.c1 = await self._read_count("OCTS_COUNT_1")
            n_end = edges["smc"]
            self.ref_edges_hi = edges["ref"]
        finally:
            stop["done"] = True
            ref_task.cancel()
            smc_task.cancel()

        self.delta = self.c1 - self.c0
        self.smc_edges_lo = n_before_c1 - n_after_c0
        self.smc_edges_hi = n_end
        lower = self.smc_edges_lo - self.tolerance
        upper = self.smc_edges_hi + self.tolerance
        assert self.delta >= lower, (
            f"OCTS TIMER_COUNT advanced too slowly for clk_smc_i: 0x{self.c0:x} -> 0x{self.c1:x} "
            f"(delta={self.delta}) while at least {self.smc_edges_lo} clk_smc_i edges elapsed "
            f"between the two reads (tolerance {self.tolerance})"
        )
        assert self.delta <= upper, (
            f"OCTS TIMER_COUNT advanced faster than clk_smc_i: 0x{self.c0:x} -> 0x{self.c1:x} "
            f"(delta={self.delta}) while only {self.smc_edges_hi} clk_smc_i edges elapsed over "
            f"the whole window (tolerance {self.tolerance}); clk_ref_i had {self.ref_edges_hi}"
        )
        # The bracket only tells the clocks apart when the other clock's edge
        # count over the same window lies outside it.
        assert not lower <= self.ref_edges_hi <= upper, (
            f"clk_ref_i ({self.ref_edges_hi} edges) is not distinguishable from clk_smc_i "
            f"([{self.smc_edges_lo}, {self.smc_edges_hi}] edges) within the tolerance in this run"
        )
        self.assert_all_reachable(EXPECTED_ACCESSES + status_reads, "OCTS_SMC_RATE")
        cocotb.log.info(
            "CHK-OCTS-TICK-ON-CLK-SMC: TIMER_COUNT 0x%x -> 0x%x delta=%d; clk_smc_i edges "
            "between the reads %d, over the whole window %d; clk_ref_i had %d, outside "
            "[%d, %d]; tolerance CREDIT_VAL %d + latch %d",
            self.c0,
            self.c1,
            self.delta,
            self.smc_edges_lo,
            self.smc_edges_hi,
            self.ref_edges_hi,
            lower,
            upper,
            CREDIT_VAL_RESET,
            LATCH_SKEW_SMC,
        )
        cocotb.log.info(
            "CHK-CLINT-TICK-NOT-CLOSED: CLINT mtime is in the cluster-local window, which lies "
            "outside the local and global apertures at the reset REGION_SIZE and answers "
            "DECERR; not reachable from SEP_IN"
        )
