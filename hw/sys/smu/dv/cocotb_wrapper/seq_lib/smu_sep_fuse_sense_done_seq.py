# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_sep_fuse_sense_done_test.

SMU-FUSE-SENSE.S2 on the SEP=1 wrapper, with the run mode leaving
+skip_fuse_sense unset so the SEP eFuse bank model supplies the sensed data.
sep_fuse_sense_skipped_o -- the testbench's view of the SEP shadow registers'
own skip flag -- is required to read 0, so the rising edge this sequence times
is a completed sense and not the plusarg path's forced value.

The observers are armed before bring-up; this sequence scores what they
recorded. Only the ordering is asserted: the sense duration is unstated, so it
is logged rather than compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from seq_lib.smu_compose_helpers import sample

SENSE_BOUND_CYCLES = 200_000
POLL_CYCLES = 64
SETTLE_CYCLES = 8


class smu_sep_fuse_sense_done_seq:
    """SEP fuse-sense completion at the sep_fuse_sense_done_o boundary port."""

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
        sb.expect_eq(
            "the SEP shadow registers are not on the skip-fuse-sense path",
            sample(dut.sep_fuse_sense_skipped_o, "sep_fuse_sense_skipped_o"),
            0,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
        sb.expect_eq(
            "sep_fuse_sense_done_o is low while cold reset is asserted",
            self.test.pre_release_sep_fuse,
            0,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )

        t_done = await probe.wait_for_rise(
            "sep_fuse_sense_done_o",
            dut.clk_smu_i,
            timeout_cycles=SENSE_BOUND_CYCLES,
            step_cycles=POLL_CYCLES,
        )
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        probe.stop()

        t_cold = probe.last_rise("rst_cold_n_o")
        first_req = probe.first_req_ps["sep_efuse_shim"]
        req_pulses = probe.req_pulses["sep_efuse_shim"]
        resp_words = probe.resp_words["sep_efuse_shim"]
        self.log.info(
            "rst_cold_n_o rose at %d ps, sep_reset_n_o rises %s, sep_fuse_sense_done_o at %d ps",
            t_cold,
            probe.rises["sep_reset_n_o"],
            t_done,
        )
        self.log.info(
            "SEP eFuse shim boundary traffic: %d read command(s) from %s ps, "
            "%d response word(s); rises sep_fuse_sense_done_o=%s",
            req_pulses,
            first_req,
            resp_words,
            probe.rises["sep_fuse_sense_done_o"],
        )

        sb.expect_eq(
            "sep_fuse_sense_done_o rises once and stays asserted",
            len(probe.rises["sep_fuse_sense_done_o"]),
            1,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
        sb.expect_true(
            "sep_fuse_sense_done_o asserts after the cold reset released",
            t_done > t_cold,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
        sb.expect_true(
            "a SEP eFuse read command reached the SMU boundary before the done edge",
            first_req is not None and first_req < t_done,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
        sb.expect_true(
            "SEP eFuse response words streamed back before the done edge",
            resp_words > 0,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
        sb.expect_eq(
            "sep_fuse_sense_done_o is asserted at the end of the sense",
            sample(dut.sep_fuse_sense_done_o, "sep_fuse_sense_done_o"),
            1,
            evidence="CHK-SMU-FUSE-SENSE-S2",
        )
