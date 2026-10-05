# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_i2c_cg_sanity_test.

Dispatches one SmcI2cItem SAMPLE. The agent driver reads ``tb_i2c_cg_en`` /
``tb_i2c_debug_lo`` and broadcasts the result; the scoreboard exact-compares the
post-reset clock-gate default ``tb_i2c_cg_en == 0``.

That compare is a negative check, and the scoreboard *silently* downgrades it to
``OBSERVED-ONLY (NOT checked evidence)`` when the run holds no liveness credit
for ``tb_i2c_cg_en`` -- it does not fail. The sequence-side gate below therefore
consumes the retained sample into the property that makes the run evidence at
all: the probe carries a same-run credit (so a stuck-at-0 / mis-bound net is
excluded) **and** the sample read the gated default. The credit is fed by the
passive ledger in ``env/smc_probe_liveness.py`` from a DUT observation of the
probe at 1, produced here by the test's
``probe_positive_controls = ("i2c_cg_en",)``
([NEGATIVE-NEEDS-POSITIVE-CONTROL]).

``tb_i2c_debug_lo`` stays observed-only: it has no SPEC/RDL-sourced reset value
in this environment, so this sequence states no expectation for it.
"""

from __future__ import annotations

import cocotb
from env.smc_i2c_item import SmcI2cItem, SmcI2cOp
from env.smc_probe_liveness import probe_alive, probe_evidence

from .smc_base_test_seq import smc_base_test_seq

# Post-reset default of CLOCK_GATE_CONTROL.i2c_cg_en, the same value
# `SmcI2cItem.expected_cg_en()` applies when no expectation is stated.
I2C_CG_EN_RESET = 0


class smc_i2c_cg_sanity_test_seq(smc_base_test_seq):
    """Run the SMC OSS I2C clock-gate sanity scenario."""

    async def body(self) -> None:
        sb = self.env.scoreboard
        seen_before = sb.i2c_samples_seen

        item = SmcI2cItem("sample")
        item.op = SmcI2cOp.SAMPLE
        await self.start_item(item)
        await self.finish_item(item)

        booked = sb.i2c_samples_seen - seen_before
        assert booked == 1, (
            f"I2C CG sanity: scoreboard booked {booked} SAMPLE item(s), "
            f"expected 1 (a mis-bound analysis port would make the clock-gate "
            f"compare vacuous): {item}"
        )
        assert probe_alive("i2c_cg_en"), (
            "I2C CG sanity: no same-run liveness credit for tb_i2c_cg_en "
            f"({probe_evidence('i2c_cg_en')}) -- the scoreboard books the "
            "cg_en == 0 leg OBSERVED-ONLY, so this run would present an "
            "all-zero read from a possibly dead probe as evidence. The "
            "producing control is declared by the test as "
            'probe_positive_controls = ("i2c_cg_en",).'
        )
        assert item.cg_en == I2C_CG_EN_RESET, (
            f"tb_i2c_cg_en read {item.cg_en}, expected the post-reset default "
            f"{I2C_CG_EN_RESET} (probe liveness: "
            f"{probe_evidence('i2c_cg_en')}): {item}"
        )
        cocotb.log.info(
            "CHK-I2C-CG-SANITY-GATED: tb_i2c_cg_en read the post-reset default "
            "%d on a scoreboard-booked SAMPLE, and the probe carries a same-run "
            "liveness credit (%s), so the leg was exact-compared rather than "
            "OBSERVED-ONLY",
            I2C_CG_EN_RESET,
            probe_evidence("i2c_cg_en"),
        )
