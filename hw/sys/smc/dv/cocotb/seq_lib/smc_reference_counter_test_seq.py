# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_003 ANCHOR: smc_reference_counter_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: 31bb60a38828f335ba0f376099bb58de13c3ac556b44ca2cedc2e5e850f347fa
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 6 ENV: cocotb
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

Load protocol, EXPECT-SOURCE ``hw/sys/smc/regs/gen/adoc/blocks/cpu_ctrl.adoc:118-128``
(``rc``, 63:0, RW): software writes the counter once, then polls until the readback
reflects the written value, at or just above it, before writing again. Every load
is a full-strobe 64-bit write and every poll a 64-bit read answering OKAY. A poll
has converged when the readback has crossed the load: at or above the written value
for a load above the previous readback, below the previous readback for a load
under it, so a readback that only kept counting from the old value never converges.
The convergence bound is a TB poll count; no spec bound exists (SF-019), so the
poll count and time are logged, and so is the post-load excess (SF-020). A lower
value loads rather than being ignored (SF-022, waived by proxy on that reading).
V7 and V8 have the Gray images all ones and all zeros, so every bit of the
Gray-coded count crossing sees both edges; that is a stimulus purpose, not an
expected value.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

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

OKAY = 0
_MASK32 = 0xFFFF_FFFF
V1 = 0x0000_0000_0010_0000
V2 = 0x0000_0001_0000_0000
V3 = 0xFFFF_FFFF_0000_0000
V4 = 0x5A5A_5A5A_A5A5_A5A5
V5 = 0x0000_0000_0000_1000
V6 = 0x0000_0002_0000_0000
V7 = 0xAAAA_AAAA_AAAA_AAAA
V8 = 0x0000_0000_0000_0000
UPPER_HALF_LOADS = (("V2", V2), ("V3", V3), ("V4", V4))
POST_LOAD_READS = 8
# Reads allowed per convergence poll before the poll fails.
CONVERGE_POLL_BOUND = 256

FENCE_TERMS = (
    "RATE-LEGS",
    "LOAD-V1",
    "POST-LOAD-READS",
    "UPPER-HALF-V2-V3-V4",
    "RELOAD-LOWER",
    "RELOAD-HIGHER",
    "LOAD-V7",
    "LOAD-V8",
)


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
        # (term, sim time in ps, compares) per CHK-NONVAC fence term, in the
        # order the terms completed.
        self.fence: list[tuple[str, int, int]] = []
        self._waits: list[str] = []
        self._polls = 0

    def _term(self, term: str, count: int) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count))
        cocotb.log.info("STEP %s: done at %d ps with %d compares", term, now, count)

    async def _read_okay(self, name: str) -> int:
        """64-bit REFERENCE_COUNTER read held to an OKAY response."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = REF_COUNT
        item.length = 8
        item.expected_resp = OKAY
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, (
            f"{name}: REFERENCE_COUNTER read answered resp={item.resp_code}, want OKAY"
        )
        return item.rdata

    @staticmethod
    def _check_upper_half(label: str, value: int, r: int) -> None:
        v_hi, v_lo = value >> 32, value & _MASK32
        r_hi, r_lo = r >> 32, r & _MASK32
        assert r >= value, f"{label} converged readback 0x{r:016x} is below 0x{value:016x}"
        assert r_hi == v_hi or (r_hi == v_hi + 1 and r_lo < v_lo), (
            f"{label} converged readback 0x{r:016x}: upper half 0x{r_hi:08x} differs "
            f"from the written 0x{v_hi:08x} other than by a carry"
        )

    async def _load_and_converge(self, label: str, value: int, prev: int) -> tuple[int, int, int]:
        """Load `value` and poll until the readback has crossed the load.

        Returns (converged readback, polls, ns from the write response to the
        converging read).
        """
        downward = value <= prev
        await self.csr_write(f"{label}_LOAD", REF_COUNT, value, length=8)
        t0 = int(get_sim_time("ns"))
        last = None
        for n in range(1, CONVERGE_POLL_BOUND + 1):
            last = await self._read_okay(f"{label}_POLL{n}")
            self._polls += 1
            if (last < prev) if downward else (last >= value):
                t = int(get_sim_time("ns")) - t0
                self._waits.append(
                    f"{label} converge: bound={CONVERGE_POLL_BOUND} polls, fail path="
                    f"AssertionError with the last readback, converged after {n} polls "
                    f"{t} ns R=0x{last:016x}"
                )
                return last, n, t
        raise AssertionError(
            f"{label}: REFERENCE_COUNTER did not converge on 0x{value:016x} within "
            f"{CONVERGE_POLL_BOUND} polls ({'below' if downward else 'at or above'} "
            f"the previous readback 0x{prev:016x}); last readback 0x{last:016x}"
        )

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
        self._term("RATE-LEGS", 2)

        total = EXPECTED_ACCESSES
        cocotb.log.info("STEP S2: load V1=0x%016x and poll until R >= V1", V1)
        r1, n1, t1 = await self._load_and_converge("V1", V1, self.c1)
        total += 1 + n1
        assert r1 >= V1, f"V1 converged readback 0x{r1:016x} is below V1=0x{V1:016x}"
        cocotb.log.info(
            "CHK-REFCNT-LOAD: V1=0x%016x R=0x%016x polls=%d t=%dns, all OKAY, LINKED-ISSUE SF-019",
            V1,
            r1,
            n1,
            t1,
        )
        self._term("LOAD-V1", 1)

        cocotb.log.info("STEP S3: %d post-load reads", POST_LOAD_READS)
        post = [await self._read_okay(f"V1_POST{i}") for i in range(POST_LOAD_READS)]
        total += POST_LOAD_READS
        for i, r in enumerate(post):
            assert r >= V1, f"post-load read {i} 0x{r:016x} is below V1=0x{V1:016x}"
        for i, (a, b) in enumerate(zip(post, post[1:])):
            assert b >= a, f"post-load reads {i}->{i + 1} decreased: 0x{a:016x} -> 0x{b:016x}"
        excess = [r - V1 for r in post]
        cocotb.log.info(
            "CHK-REFCNT-MONOTONIC: %d reads non-decreasing, min excess=%d max excess=%d, "
            "LINKED-ISSUE SF-020 (reads: %s)",
            POST_LOAD_READS,
            min(excess),
            max(excess),
            " ".join(f"0x{r:016x}" for r in post),
        )
        self._term("POST-LOAD-READS", 2 * POST_LOAD_READS - 1)

        cocotb.log.info("STEP S4: upper-half loads V2, V3, V4")
        prev = post[-1]
        upper = []
        for label, value in UPPER_HALF_LOADS:
            r, n, t = await self._load_and_converge(label, value, prev)
            total += 1 + n
            self._check_upper_half(label, value, r)
            upper.append((label, value >> 32, r, n, t))
            prev = r
        self._term("UPPER-HALF-V2-V3-V4", 2 * len(upper))

        cocotb.log.info("STEP S5: reload V5 below the readback, then V6 above")
        r5, n5, t5 = await self._load_and_converge("V5", V5, prev)
        total += 1 + n5
        assert V5 <= r5 < prev, (
            f"V5 converged readback 0x{r5:016x} outside [0x{V5:016x}, previous 0x{prev:016x})"
        )
        self._term("RELOAD-LOWER", 1)
        r6, n6, t6 = await self._load_and_converge("V6", V6, r5)
        total += 1 + n6
        assert r6 >= V6, f"V6 converged readback 0x{r6:016x} is below 0x{V6:016x}"
        self._term("RELOAD-HIGHER", 1)

        cocotb.log.info("STEP S7: load V7 above the readback, then V8 below it")
        r7, n7, t7 = await self._load_and_converge("V7", V7, r6)
        total += 1 + n7
        self._check_upper_half("V7", V7, r7)
        upper.append(("V7", V7 >> 32, r7, n7, t7))
        self._term("LOAD-V7", 2)
        r8, n8, t8 = await self._load_and_converge("V8", V8, r7)
        total += 1 + n8
        assert V8 <= r8 < r7, (
            f"V8 converged readback 0x{r8:016x} outside [0x{V8:016x}, R7 0x{r7:016x})"
        )
        self._term("LOAD-V8", 1)

        cocotb.log.info(
            "upper-half converged readbacks (LINKED-ISSUE SF-019): %s",
            ", ".join(f"{lbl} R=0x{r:016x} polls={n} t={t}ns" for lbl, _, r, n, t in upper),
        )
        cocotb.log.info(
            "CHK-REFCNT-UPPER-HALF: %s, readback hi matches x%d, V7 polls=%d t=%dns",
            " ".join(f"{lbl} hi=0x{v_hi:08X}" for lbl, v_hi, _, _, _ in upper),
            len(upper),
            n7,
            t7,
        )
        cocotb.log.info(
            "reload previous readbacks (LINKED-ISSUE SF-019): V5 prev=0x%016x, V8 prev R7=0x%016x",
            prev,
            r7,
        )
        cocotb.log.info(
            "CHK-REFCNT-RELOAD: V5=0x%016x R5=0x%016x (< prev), V6=0x%016x R6=0x%016x, "
            "V8=0x%016x R8=0x%016x (< R7=0x%016x), polls/t per reload=%d/%dns,%d/%dns,%d/%dns",
            V5,
            r5,
            V6,
            r6,
            V8,
            r8,
            r7,
            n5,
            t5,
            n6,
            t6,
            n8,
            t8,
        )

        self.assert_all_reachable(total, "REFERENCE_COUNTER load legs")
        names = tuple(t for t, _, _ in self.fence)
        assert names == FENCE_TERMS, f"fence terms {names}, want {FENCE_TERMS}"
        times = [t for _, t, _ in self.fence]
        assert all(a < b for a, b in zip(times, times[1:])), f"fence out of order: {self.fence}"
        assert all(c > 0 for _, _, c in self.fence), f"zero-count fence term: {self.fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: %s)",
            " < ".join(FENCE_TERMS),
            ", ".join(f"{t}={c}@{ps}ps" for t, ps, c in self.fence),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired: %s",
            len(self._waits),
            " | ".join(self._waits),
        )
