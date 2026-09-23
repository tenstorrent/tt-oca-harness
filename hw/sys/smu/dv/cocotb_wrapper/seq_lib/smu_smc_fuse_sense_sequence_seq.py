# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_fuse_sense_sequence_test (SMU_108).

SMU-FUSE-SENSE.S1 and .S3 on the wrapper (its single profile elaborates SEP=1),
with the run mode leaving
+skip_fuse_sense unset so the SMC eFuse bank model supplies the sensed data.
The observers are armed before bring-up; this sequence scores what they
recorded: smc_fuse_sense_done_o rises once, after the SMC primary reset released
and after eFuse read traffic appeared at the SMU boundary, and
smc_fuse_reset_n_delayed_o releases after that rise rather than with the cold
reset.

Only the ordering is asserted. The delay on smc_fuse_reset_n_delayed_o is unstated
(SF-026) and so is the sense duration, so both are logged rather than
compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_compose_helpers import sample

SENSE_BOUND_CYCLES = 200_000
DELAY_BOUND_CYCLES = 20_000
POLL_CYCLES = 64
SETTLE_CYCLES = 8


class smu_smc_fuse_sense_sequence_seq:
    """SMC fuse-sense completion and the delayed fuse reset that follows it."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.probe = test.fuse_probe

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        probe = self.probe
        await self.test.cfg.reset_done.wait()
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)

        sb.expect_eq("SEP=1 build profile", sample(dut.sep_enabled_o, "sep_enabled_o"), 1)
        sb.expect_true(
            "this run mode leaves +skip_fuse_sense unset, so the sense is the DUT's",
            "skip_fuse_sense" not in cocotb.plusargs,
        )

        t_done = await probe.wait_for_rise(
            "smc_fuse_sense_done_o",
            dut.clk_smu_i,
            timeout_cycles=SENSE_BOUND_CYCLES,
            step_cycles=POLL_CYCLES,
        )
        t_delayed = await probe.wait_for_rise(
            "smc_fuse_reset_n_delayed_o",
            dut.clk_smu_i,
            timeout_cycles=DELAY_BOUND_CYCLES,
            step_cycles=POLL_CYCLES,
        )
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        probe.stop()

        t_smc_rst = probe.last_rise("rst_primary_smc_clk_n_o")
        t_cold = probe.last_rise("rst_cold_n_o")
        first_req = probe.first_req_ps["smc_efuse_shim"]
        req_pulses = probe.req_pulses["smc_efuse_shim"]
        resp_words = probe.resp_words["smc_efuse_shim"]
        self.log.info(
            "rst_cold_n_o rose at %d ps, rst_primary_smc_clk_n_o at %d ps, "
            "smc_fuse_sense_done_o at %d ps, smc_fuse_reset_n_delayed_o at %d ps",
            t_cold,
            t_smc_rst,
            t_done,
            t_delayed,
        )
        self.log.info(
            "SMC eFuse shim boundary traffic: %d read command(s) from %s ps, "
            "%d response word(s); rises smc_fuse_sense_done_o=%s smc_fuse_reset_n_delayed_o=%s",
            req_pulses,
            first_req,
            resp_words,
            probe.rises["smc_fuse_sense_done_o"],
            probe.rises["smc_fuse_reset_n_delayed_o"],
        )

        # SMU-FUSE-SENSE.S1
        sb.expect_eq(
            "smc_fuse_sense_done_o rises once and stays asserted",
            len(probe.rises["smc_fuse_sense_done_o"]),
            1,
            evidence="CHK-SMU-FUSE-SENSE-S1",
        )
        sb.expect_true(
            "smc_fuse_sense_done_o asserts after the SMC primary reset released",
            t_done > t_smc_rst,
            evidence="CHK-SMU-FUSE-SENSE-S1",
        )
        sb.expect_true(
            "an eFuse read command reached the SMU boundary before smc_fuse_sense_done_o",
            first_req is not None and first_req < t_done,
            evidence="CHK-SMU-FUSE-SENSE-S1",
        )
        sb.expect_true(
            "eFuse response words streamed back before smc_fuse_sense_done_o",
            resp_words > 0,
            evidence="CHK-SMU-FUSE-SENSE-S1",
        )
        sb.expect_eq(
            "smc_fuse_sense_done_o is asserted at the end of the sense",
            sample(dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o"),
            1,
            evidence="CHK-SMU-FUSE-SENSE-S1",
        )

        # SMU-FUSE-SENSE.S3
        sb.expect_eq(
            "smc_fuse_reset_n_delayed_o releases once",
            len(probe.rises["smc_fuse_reset_n_delayed_o"]),
            1,
            evidence="CHK-SMU-FUSE-SENSE-S3",
        )
        sb.expect_true(
            "smc_fuse_reset_n_delayed_o releases after smc_fuse_sense_done_o asserts",
            t_delayed > t_done,
            evidence="CHK-SMU-FUSE-SENSE-S3",
        )
        sb.expect_true(
            "smc_fuse_reset_n_delayed_o releases after the cold reset, not with it",
            t_delayed > t_cold,
            evidence="CHK-SMU-FUSE-SENSE-S3",
        )
