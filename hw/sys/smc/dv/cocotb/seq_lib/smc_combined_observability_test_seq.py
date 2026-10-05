# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_combined_observability_test.

Cross-agent sequence: samples both the reset observables and the I2C
observables from the same scenario. Uses dual-sequencer dispatch via the
respective agent sequencers, demonstrating the multi-agent env pattern
end-to-end within a single test scenario.

Dispatching the two items and returning would leave the retained evidence as
scoreboard prose only, with nothing asserted locally. The body therefore
restates both expectations -- the five reset observables at 1
(released) and ``tb_i2c_cg_en == 0``, whose same-run positive control is the
test's declared ``probe_positive_controls = ("i2c_cg_en",)`` -- reconciles both
dispatched items against the scoreboard's typed counters, and only then emits
one ``CHK-COMBINED-*`` token per leg (`[EVIDENCE-TOKEN-CONDITIONAL]`).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp

from .smc_base_test_seq import smc_base_test_seq


class smc_combined_observability_test_seq(smc_base_test_seq):
    GAP_REF_CYCLES = 50

    # Exact per-type item counts this body dispatches; the end gate compares the
    # scoreboard's typed counters against them (the declared probe positive
    # control dispatches no agent SAMPLE items).
    EXPECTED_SAMPLES = {
        "reset_samples_seen": 1,
        "i2c_samples_seen": 1,
    }

    def __init__(self, name: str = "smc_combined_observability_test_seq") -> None:
        super().__init__(name)
        self.reset_sample: SmcResetItem | None = None
        self.i2c_sample: SmcI2cItem | None = None
        # The reset and i2c sequencers are wired in body() via the dispatcher
        # hook supplied by smc_combined_observability_test.
        self.dispatch_reset = None
        self.dispatch_i2c = None

    def _resolve_env(self):
        """The env this sequence runs in (the test starts it directly)."""
        if self.env is not None:
            return self.env
        node = self.sequencer
        while node is not None:
            if hasattr(node, "scoreboard"):
                return node
            node = node.get_parent()
        raise AssertionError(
            f"{self.get_name()}: could not resolve SmcEnv from sequencer "
            f"{self.sequencer}; the per-type end gate needs the scoreboard"
        )

    async def body(self) -> None:
        dut = cocotb.top
        env = self._resolve_env()
        before = {name: getattr(env.scoreboard, name) for name in self.EXPECTED_SAMPLES}

        reset_item = SmcResetItem("reset_sample")
        reset_item.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(reset_item)
        self.reset_sample = reset_item
        assert reset_item.resolvable, f"reset sample is X/Z: {reset_item}"
        for field in RESET_SAMPLE_FIELDS:
            got = getattr(reset_item, field)
            assert got == 1, (
                f"reset {field} = {got}, expected 1 (released) after bring-up ({reset_item})"
            )
        cocotb.log.info(
            "CHK-COMBINED-RESET: all %d reset observables read 1 (released) after bring-up: %s",
            len(RESET_SAMPLE_FIELDS),
            reset_item,
        )

        await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)

        i2c_item = SmcI2cItem("i2c_sample")
        i2c_item.op = SmcI2cOp.SAMPLE
        await self.dispatch_i2c(i2c_item)
        self.i2c_sample = i2c_item
        assert i2c_item.resolvable, f"I2C sample is X/Z: {i2c_item}"
        assert i2c_item.cg_en == 0, (
            f"tb_i2c_cg_en = {i2c_item.cg_en}, expected 0 with no I2C clock "
            f"gate programmed in this scenario ({i2c_item})"
        )
        cocotb.log.info(
            "CHK-COMBINED-I2C: tb_i2c_cg_en == 0 on a resolved sample taken "
            "%d clk_ref_i cycles after the reset sample -- backed in this same "
            "run by the declared i2c_cg_en positive control "
            "(CHK-PROBE-I2C-CG-EN-ALIVE): %s",
            self.GAP_REF_CYCLES,
            i2c_item,
        )

        # End gate: both dispatched items reached the type-dispatched
        # scoreboard, exactly once each. Consumes the two retained handles, so
        # neither is stored-but-unread ([NO-ZERO-ACTIVITY-PASS]).
        sb = env.scoreboard
        observed = {name: getattr(sb, name) - before[name] for name in self.EXPECTED_SAMPLES}
        assert observed == self.EXPECTED_SAMPLES, (
            f"combined composition mismatch: scoreboard booked {observed}, "
            f"expected {self.EXPECTED_SAMPLES}"
        )
        assert self.reset_sample is reset_item and self.i2c_sample is i2c_item, (
            "the sequence did not retain the two dispatched samples: "
            f"reset={self.reset_sample} i2c={self.i2c_sample}"
        )
        cocotb.log.info(
            "CHK-COMBINED-COMPOSITION: both item types reached the "
            "type-dispatched scoreboard with the exact counts this sequence "
            "dispatched: %s (reset=%s, i2c=%s)",
            observed,
            self.reset_sample,
            self.i2c_sample,
        )
