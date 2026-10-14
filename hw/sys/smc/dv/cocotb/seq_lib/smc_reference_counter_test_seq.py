# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL REFERENCE_COUNTER is a refclk CDC counter, not the OCTS timer.

EXPECT-SOURCE (SPEC, not RTL): ``doc/trm/src/clock_domains.adoc`` (Reference Counter) --
the ``REFERENCE_COUNTER`` CSR is a free-running 64-bit counter "clocked by the
always-on reference clock (``clk_ref_i``)", advancing "continuously from reset,
independent of the system clock (``clk_smu_i``) frequency or PLL state",
synchronised into the CPU clock domain for software reads.

One count per ``clk_ref_i`` rising edge is therefore a SPEC-derived rate, not a
transcription of ``smc_cpu_ctrl_wrap.sv`` / ``prim_refclk_count_w_cdc``
([INDEPENDENT-EXPECTED-MODEL]).  The check below turns that rate into a
two-sided bound on the observed delta, measured over the very interval the two
CSR samples bracket -- so a counter clocked by ``clk_smc_i`` (faster), by
``clk_periph_i``, or at half rate fails.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

REF_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_REFERENCE_COUNTER_BASE_ADDR")
_REF_WAIT = 32

# The DUT latches each sample somewhere inside its own CSR access window, and
# the count crosses a CDC synchroniser on its way to the CPU domain.  The
# bracketing counts below already absorb the whole duration of both accesses;
# this allowance only covers the synchroniser depth (a couple of refclk
# periods).
_CDC_SKEW_REF = 4

EXPECTED_ACCESSES = 2
EXPECTED_VALUE_CHECKS = 0


class smc_reference_counter_test_seq(SmcCsrSeq):
    """REFERENCE_COUNTER advances at exactly one count per clk_ref_i edge."""

    def __init__(self, name: str = "smc_reference_counter_test_seq") -> None:
        super().__init__(name)
        # Measured quantities published for the testcase-level gate. `None`
        # means "never sampled" -- the gate fails rather than passing.
        self.c0 = None
        self.c1 = None
        self.delta = None
        self.ref_edges_lo = None  # edges strictly between the two accesses
        self.ref_edges_hi = None  # edges over the whole bracketing window
        self.cdc_skew = _CDC_SKEW_REF

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        # Independent measurement of clk_ref_i rising edges, running for the
        # whole interval the two CSR samples bracket.  This is the reference
        # side of the compare; the DUT never feeds it.
        edges = {"n": 0}
        stop = {"done": False}

        async def _ref_edge_counter() -> None:
            while not stop["done"]:
                await RisingEdge(dut.clk_ref_i)
                edges["n"] += 1

        counter = cocotb.start_soon(_ref_edge_counter())
        try:
            self.c0 = await self.csr_read("REF_COUNT_0", REF_COUNT, length=8)
            # Edges elapsed by the time the first sample was certainly latched.
            n_after_c0 = edges["n"]
            for _ in range(_REF_WAIT):
                await RisingEdge(dut.clk_ref_i)
            # Edges elapsed before the second access could possibly be latched.
            n_before_c1 = edges["n"]
            self.c1 = await self.csr_read("REF_COUNT_1", REF_COUNT, length=8)
            n_end = edges["n"]
        finally:
            stop["done"] = True
            counter.cancel()

        # c0 was latched somewhere in [0, n_after_c0]; c1 somewhere in
        # [n_before_c1, n_end].  At one count per refclk edge the delta is
        # therefore bounded on both sides by real measurements.
        self.delta = self.c1 - self.c0
        self.ref_edges_lo = n_before_c1 - n_after_c0
        self.ref_edges_hi = n_end

        assert self.delta >= self.ref_edges_lo - _CDC_SKEW_REF, (
            f"REFERENCE_COUNTER advanced too slowly for clk_ref_i: "
            f"0x{self.c0:x} -> 0x{self.c1:x} (delta={self.delta}) while at "
            f"least {self.ref_edges_lo} clk_ref_i edge(s) elapsed strictly "
            f"between the two CSR accesses (CDC allowance {_CDC_SKEW_REF}). "
            f"A half-rate or non-refclk source produces exactly this."
        )
        assert self.delta <= self.ref_edges_hi + _CDC_SKEW_REF, (
            f"REFERENCE_COUNTER advanced faster than clk_ref_i: "
            f"0x{self.c0:x} -> 0x{self.c1:x} (delta={self.delta}) while only "
            f"{self.ref_edges_hi} clk_ref_i edge(s) elapsed over the whole "
            f"window the two CSR accesses bracket (CDC allowance "
            f"{_CDC_SKEW_REF}). A clk_smc_i-clocked counter produces exactly "
            f"this."
        )

        # Loop integrity + scoreboard cross-check: the two reads must have
        # reached the checker at all ([NO-ZERO-ACTIVITY-PASS]).  No bounded
        # read runs here, so `timeouts == 0` is not asserted.
        self.assert_all_reachable(EXPECTED_ACCESSES, "REFERENCE_COUNTER")

        cocotb.log.info(
            "CHK-REF-COUNT: 0x%x -> 0x%x delta=%d, clk_ref_i edges measured "
            "in the same window: %d <= delta <= %d (+/- %d CDC skew), "
            "%d edges awaited between the accesses",
            self.c0,
            self.c1,
            self.delta,
            self.ref_edges_lo,
            self.ref_edges_hi,
            _CDC_SKEW_REF,
            _REF_WAIT,
        )
        cocotb.log.info(
            "CHK-REF-COUNT-BASIC: delta=%d within the measured refclk-edge "
            "bounds [%d, %d] (one count per clk_ref_i edge, "
            "doc/trm/src/architecture.adoc:256-265)",
            self.delta,
            self.ref_edges_lo - _CDC_SKEW_REF,
            self.ref_edges_hi + _CDC_SKEW_REF,
        )
