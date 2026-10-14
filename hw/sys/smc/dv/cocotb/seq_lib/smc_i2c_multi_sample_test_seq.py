# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_multi_sample_test.

Three back-to-back I2C observation samples at fixed cycle intervals to
verify the clock-gate enable and i2c_debug bus stay stable over time
post-reset.

Two gates make those stability legs evidence rather than bookkeeping:
the scoreboard's typed ``i2c_samples_seen`` delta must equal the number of
SAMPLEs dispatched (a mis-bound analysis port would otherwise leave every
scoreboard compare vacuous), and ``tb_i2c_cg_en`` must carry a same-run liveness
credit (a dead net is perfectly stable, which is exactly the property the
stability legs claim to catch).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_probe_liveness import probe_alive, probe_evidence

from .smc_base_test_seq import smc_base_test_seq


class smc_i2c_multi_sample_test_seq(smc_base_test_seq):
    GAP_REF_CYCLES = 100

    def __init__(self, name: str = "smc_i2c_multi_sample_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcI2cItem] = []

    NUM_SAMPLES = 3

    async def body(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        seen_before = sb.i2c_samples_seen
        for i in range(self.NUM_SAMPLES):
            item = SmcI2cItem(f"sample_{i}")
            item.op = SmcI2cOp.SAMPLE
            await self.start_item(item)
            await self.finish_item(item)
            self.samples.append(item)
            if i < self.NUM_SAMPLES - 1:
                await ClockCycles(dut.clk_ref_i, self.GAP_REF_CYCLES)

        # The scoreboard counter is incremented by `_check_i2c` on the analysis
        # path, so a mis-bound analysis port -- which would leave every
        # scoreboard compare below vacuous -- fails here. Same gate the sibling
        # `smc_i2c_cg_sanity_test_seq` carries
        # ([NO-DUMMY-DEAD-CODE] / [NO-ZERO-ACTIVITY-PASS]).
        booked = sb.i2c_samples_seen - seen_before
        assert booked == self.NUM_SAMPLES, (
            f"I2C multi-sample: scoreboard booked {booked} SAMPLE item(s), "
            f"expected {self.NUM_SAMPLES} (a mis-bound analysis port would make "
            f"the clock-gate and stability compares vacuous)"
        )

        # A dead net is perfectly stable, so the stability legs below are only
        # evidence when the same run proved tb_i2c_cg_en able to read 1. The
        # credit is fed by the passive ledger in `env/smc_probe_liveness.py`
        # from a DUT observation of the probe at 1, produced by the test's
        # `probe_positive_controls = ("i2c_cg_en",)`
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        assert probe_alive("i2c_cg_en"), (
            "I2C multi-sample: no same-run liveness credit for tb_i2c_cg_en "
            f"({probe_evidence('i2c_cg_en')}) -- the scoreboard books the "
            "cg_en == 0 leg OBSERVED-ONLY, so this run would present a stable "
            "all-zero read from a possibly dead probe as stability evidence. "
            "The producing control is declared by the test as "
            'probe_positive_controls = ("i2c_cg_en",).'
        )

        # Stability over the spaced gaps: every sample must be resolvable and
        # report the same cg_en / i2c_debug_lo as the first one.
        first = self.samples[0]
        for i, item in enumerate(self.samples):
            assert item.resolvable, (
                f"I2C multi-sample {i}: tb_i2c_cg_en / tb_i2c_debug_lo unresolvable (X/Z) -> {item}"
            )
            assert item.cg_en == first.cg_en, (
                f"I2C multi-sample {i}: cg_en={item.cg_en} drifted from "
                f"sample 0 cg_en={first.cg_en} over "
                f"{i * self.GAP_REF_CYCLES} clk_ref_i cycles"
            )
            assert item.debug_lo == first.debug_lo, (
                f"I2C multi-sample {i}: debug_lo=0x{item.debug_lo:x} drifted "
                f"from sample 0 debug_lo=0x{first.debug_lo:x} over "
                f"{i * self.GAP_REF_CYCLES} clk_ref_i cycles"
            )
        cocotb.log.info(
            "CHK-I2C-MULTI-SAMPLE-STABLE: %d samples spaced %d clk_ref_i "
            "cycles apart, all %d booked by the scoreboard, all held "
            "cg_en=%d debug_lo=0x%x; tb_i2c_cg_en liveness credit: %s",
            len(self.samples),
            self.GAP_REF_CYCLES,
            booked,
            first.cg_en,
            first.debug_lo,
            probe_evidence("i2c_cg_en"),
        )
