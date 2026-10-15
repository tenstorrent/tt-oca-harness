# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_axil_burst_idle_test.

The eight idle SAMPLEs are a negative claim, so they run *after* a positive
control: :func:`smc_axil_idle_test_seq.prove_axil_probe_alive` drives a real
frontdoor SEP_IN AXI request that makes ``tb_axil_any_master_active`` (via its
``tb_axil_efuse_bank_active`` term) observe 1, and the test declares
``probe_positive_controls = ("axil_external_active",)`` for the third backable
probe. Without those legs a stuck-at-0 / undriven / mis-tied probe passes all
eight asserts identically (`[NEGATIVE-NEEDS-POSITIVE-CONTROL]`).

``dtp_csr_active`` is never exact-compared here: no positive control for it can
exist in this TB (``tb_top.sv`` ties ``axil_dtp_csr_resp = '0'``), so the
shared :func:`smc_axil_idle_test_seq.assert_axil_idle` iterates
``AXIL_CHECKABLE_FIELDS`` and returns that field as OBSERVED-ONLY text.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_axil_item import AXIL_CHECKABLE_FIELDS, SmcAxilItem, SmcAxilOp

from .smc_axil_idle_test_seq import assert_axil_idle, prove_axil_probe_alive
from .smc_base_test_seq import smc_base_test_seq


class smc_axil_burst_idle_test_seq(smc_base_test_seq):
    # One smc clock between SAMPLE items so the eight idle asserts span
    # distinct cycles (observation validity for "across the burst").
    GAP_SMC_CYCLES = 1
    BURST_SAMPLES = 8

    def __init__(self, name: str = "smc_axil_burst_idle_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcAxilItem] = []

    async def body(self) -> None:
        dut = cocotb.top
        assert self.env is not None, (
            f"{self.get_name()}: env is not wired, so the typed scoreboard "
            "counter gate cannot run (start via smc_base_test.start_seq)"
        )
        sb = self.env.scoreboard
        booked_before = sb.axil_samples_seen
        cocotb.log.info(
            "STEP S1: POSITIVE CONTROL — real frontdoor SEP_IN AXI request "
            "drives tb_axil_any_master_active to 1"
        )
        await prove_axil_probe_alive(self)
        cocotb.log.info(
            "STEP S2: %dx SmcAxilItem SAMPLE (all activity bits == 0)",
            self.BURST_SAMPLES,
        )
        for i in range(self.BURST_SAMPLES):
            it = SmcAxilItem(f"s{i}")
            it.op = SmcAxilOp.SAMPLE
            await self.start_item(it)
            await self.finish_item(it)
            self.samples.append(it)
            if i < self.BURST_SAMPLES - 1:
                await ClockCycles(dut.clk_smc_i, self.GAP_SMC_CYCLES)
        assert len(self.samples) == self.BURST_SAMPLES, (
            f"expected {self.BURST_SAMPLES} AXI-Lite SAMPLE items, got {len(self.samples)}"
        )
        # One OBSERVED-ONLY string per sample, so the burst-wide token quotes
        # each sample's own unbackable-probe value ([NO-DUMMY-DEAD-CODE]).
        observed_only_per_sample = [assert_axil_idle(s) for s in self.samples]
        distinct_observed_only = sorted(set(observed_only_per_sample))
        observed_only = "; ".join(
            f"{text} x{observed_only_per_sample.count(text)}" for text in distinct_observed_only
        )
        # Typed-counter end gate: every dispatched SAMPLE reached the
        # type-dispatched scoreboard. A mis-bound agent or a dropped item would
        # otherwise leave the burst claim resting on items nothing booked
        # ([NO-ZERO-ACTIVITY-PASS]).
        booked = sb.axil_samples_seen - booked_before
        assert booked == self.BURST_SAMPLES, (
            f"scoreboard booked {booked} AXI-Lite SAMPLE items, expected "
            f"{self.BURST_SAMPLES} dispatched by this burst"
        )
        cocotb.log.info(
            "CHK-NONVAC: probe proven able to read 1 under real AXI-Lite master "
            "traffic (CHK-DIAG-AXIL-ACTIVE / CHK-PROBE-AXIL-EXTERNAL-ALIVE "
            "above), then all %d SmcAxilItem SAMPLE ops (s0..s%d), all %d "
            "booked by the scoreboard, read %s == 0 across the burst "
            "[OBSERVED-ONLY, NOT checked evidence, all %d samples: %s]",
            self.BURST_SAMPLES,
            self.BURST_SAMPLES - 1,
            booked,
            "/".join(f"tb_axil_{f}" for f in AXIL_CHECKABLE_FIELDS),
            len(observed_only_per_sample),
            observed_only,
        )
        cocotb.log.info(
            "smc_axil_burst_idle_test_seq PASS: %d idle samples, %d booked",
            self.BURST_SAMPLES,
            booked,
        )
