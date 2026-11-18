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

``doc/integrator/src/smu-sep.adoc`` ("eFuse and Lifecycle") has the SMU wire
``smc_fuse_sense_done_o`` into the SEP's ``smc_fuse_sense_done_i``, and
("Bring-Up Considerations") starts the SEP boot sequence after the SMC
completes fuse sensing and releases the SEP reset. The wire monitor armed with
the observers compares the two on every ``clk_smu_i`` sample from before the
cold reset to the SEP sense, and the rises recorded after the cold release
order ``sep_reset_n_o`` after ``smc_fuse_sense_done_o``.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from seq_lib.smu_compose_helpers import sample

SENSE_BOUND_CYCLES = 200_000
POLL_CYCLES = 64
SETTLE_CYCLES = 8


class SmuSenseWireMonitor:
    """``obs_sep_smc_fuse_sense_done_i_o`` against ``smc_fuse_sense_done_o`` on every clk_smu_i."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.samples = 0
        self.done_low = 0
        self.done_high = 0
        self.mismatches = 0
        self._task = None

    def arm(self) -> None:
        self._task = cocotb.start_soon(self._watch())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _watch(self) -> None:
        dut = self.dut
        while True:
            await RisingEdge(dut.clk_smu_i)
            smc = sample(dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o", allow_xz=True)
            sep = sample(
                dut.obs_sep_smc_fuse_sense_done_i_o,
                "obs_sep_smc_fuse_sense_done_i_o",
                allow_xz=True,
            )
            self.samples += 1
            self.done_high += smc
            self.done_low += 1 - smc
            self.mismatches += smc != sep


class smu_sep_fuse_sense_done_seq:
    """SEP fuse-sense completion at the sep_fuse_sense_done_o boundary port."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.log = test.logger
        self.sb = test.env.scoreboard
        self.probe = test.fuse_probe
        self.wire = test.sense_wire

    async def _wait_rise_after(self, name: str, after_ps: int) -> int:
        """Block until ``name`` has a recorded rise later than ``after_ps``; return its time."""
        for _ in range(max(1, SENSE_BOUND_CYCLES // POLL_CYCLES)):
            later = [t for t in self.probe.rises[name] if t > after_ps]
            if later:
                return later[0]
            await ClockCycles(self.dut.clk_smu_i, POLL_CYCLES)
        raise AssertionError(
            f"TIMEOUT {name} never rose after {after_ps} ps within {SENSE_BOUND_CYCLES} cycles"
        )

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
        t_cold = probe.last_rise("rst_cold_n_o")
        t_sep_reset = await self._wait_rise_after("sep_reset_n_o", t_cold)
        await ClockCycles(dut.clk_smu_i, SETTLE_CYCLES)
        probe.stop()
        self.wire.stop()
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

        wire = self.wire
        smc_done_rises = [t for t in probe.rises["smc_fuse_sense_done_o"] if t > t_cold]
        sep_reset_rises = [t for t in probe.rises["sep_reset_n_o"] if t > t_cold]
        self.log.info(
            "CHK-SMU-SMC-SENSE-TO-SEP: %d clk_smu_i samples, smc_fuse_sense_done_o low in %d and "
            "high in %d, SEP input differs in %d; after the cold release at %d ps "
            "smc_fuse_sense_done_o rises %s and sep_reset_n_o rises %s",
            wire.samples,
            wire.done_low,
            wire.done_high,
            wire.mismatches,
            t_cold,
            smc_done_rises,
            sep_reset_rises,
        )
        sb.expect_eq(
            "CHK-SMU-SMC-SENSE-TO-SEP the SEP's smc_fuse_sense_done_i equals smc_fuse_sense_done_o "
            "on every clk_smu_i sample, with the wire seen low and high; after the cold release "
            "smc_fuse_sense_done_o rises once and every sep_reset_n_o rise comes after it",
            (
                wire.mismatches,
                wire.done_low >= 1,
                wire.done_high >= 1,
                len(smc_done_rises),
                len(sep_reset_rises) >= 1,
                all(t > smc_done_rises[0] for t in sep_reset_rises) if smc_done_rises else False,
            ),
            (0, True, True, 1, True, True),
            evidence="CHK-SMU-SMC-SENSE-TO-SEP",
        )
        self.log.info(
            "OBSERVATION sep_reset_n_o rose at %d ps, %d ps after smc_fuse_sense_done_o",
            t_sep_reset,
            t_sep_reset - (smc_done_rises[0] if smc_done_rises else t_cold),
        )
