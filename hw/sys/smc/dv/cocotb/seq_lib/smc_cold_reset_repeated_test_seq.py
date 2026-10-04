# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_cold_reset_repeated_test (3 re-asserts).

Each re-assert is proven at both ends, so a DUT that never takes the cold or
cool reset fails instead of coasting to the post-release SAMPLE gates
([NO-ALWAYS-PASS-CHECKER]):

* assert half: a bounded ``WAIT_STATE`` on the asserted levels. It doubles as
  the stimulus hold -- ``smc_reset_ctrl`` de-glitches ``rst_cold_ni`` /
  ``rst_cool_ni`` over 32 ``clk_ref_i`` samples, so a fixed hold shorter than
  that window is silently rejected and resets nothing. Holding until the reset
  is *observed* cannot be short.
* hold half: after the wait matched, the pin stays low across a further
  ``MID_ASSERT_HOLD_REF_CYCLES`` ``clk_ref_i`` edges and EVERY one of those
  samples must still read the asserted levels. This is a separate observation
  in time from the wait (the wait's match and a RAW_SAMPLE dispatched straight
  after it land in the same delta region, so such a snapshot could not fail
  unless the wait already had -- [NO-ALWAYS-PASS-CHECKER]). A DUT that releases
  the cold/cool path early, anywhere inside the window, fails here.
* release half: a bounded ``WAIT_STATE`` on the released levels followed by the
  post-release ``SAMPLE`` (the checked_cleared leg); no fixed ``ClockCycles``
  completion sync ([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]).

Expected levels come from ``hw/sys/smc/doc/clk_rst.adoc``: cold reset drives the
cold-stable and primary paths, cool reset is a primary-level reset that leaves
the cold-stable path released.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetOp

from .smc_isolate_pin_utils import await_skip_mem_repair, drive_isolate_pin, skip_mem_repair
from .smc_reset_seq_base import SmcResetSeqBase

# The isolate-request pin is the pad the DV-owned pad table
# (`doc/integrator/meta/ocah_gpio_table.csv`) names "Isolate Request";
# `smc_isolate_pin_utils` reads the index from that table. `clk_rst.adoc`
# ("Function Level Reset") defines pin-based isolation as `isolate_req_pin_i`
# gated by `ISOLATE_REQ_PINEN_REG` and makes it one of the three isolation
# sources; under "Memory Test Bypass" it activates `skip_mem_repair_o`
# automatically when either FLR-triggered or pin-based isolation is asserted.
# The testcase module programs `ISOLATE_REQ_PINEN_REG` to all ones over SEP_IN
# before this sequence starts, so the pin is an enabled isolation source; with
# no FLR signalled and ISOLATE_REQ_SMC_REG at its reset 0 it is the only one,
# and `skip_mem_repair_o` must follow it: 0 with the pin low, 1 with the pin
# high. The bench leaves the pad undriven by default and it then reads 1; that
# undriven sample, and what the output does before the enable is written, are
# reported and not asserted. A board idles the pin low, which is what the two
# legs below drive and observe. The cold resets that follow return
# `ISOLATE_REQ_PINEN_REG` to 0, so the post-reset leg holds the pin low, where
# the spec predicts no pin isolation whatever the enable.
# Ceiling on the fuse-sense re-run after the last reset release, matching the
# package-wide `wait_fuse_sense_done` bound. Expiry is a FAILURE.
_SENSE_BOUND = 200_000


class smc_cold_reset_repeated_test_seq(SmcResetSeqBase):
    REPEATS = 3
    # Ceilings for the bounded waits, never the checked quantity: the assert
    # bound must exceed the 32-sample de-glitch window plus the 4-stage output
    # synchronizers, the release bound the cold-reset extender.
    ASSERT_BOUND_REF_CYCLES = 400
    RELEASE_BOUND_REF_CYCLES = 2000
    # Mid-assert hold window, in clk_ref_i edges: as wide as smc_reset_ctrl's
    # 32-sample de-glitch window, so an incorrect release that took a full
    # de-glitch to appear is still inside the checked window.
    MID_ASSERT_HOLD_REF_CYCLES = 32

    # `_send` (with its `expect_*` keyword guard), `_hold_raw` and
    # `_wait_released` come from SmcResetSeqBase so the guard is defined once
    # for the whole reset family ([REUSE-AND-LAYERING]).

    def __init__(self, name: str = "smc_cold_reset_repeated_test_seq") -> None:
        super().__init__(name)
        #: `skip_mem_repair_o` sampled with the isolate pin left undriven.
        self.skip_pin_floating = -1
        #: `skip_mem_repair_o` sampled with the isolate pin driven low.
        self.skip_pin_low = -1
        #: `skip_mem_repair_o` sampled with the isolate pin driven high.
        self.skip_pin_high = -1
        #: `skip_mem_repair_o` at the post-reset fuse-sense completion.
        self.skip_at_sense_done = -1

    def _skip_mem_repair(self, dut) -> int:
        return skip_mem_repair(dut)

    async def _await_skip_mem_repair(self, dut, want: int, label: str) -> int:
        return await await_skip_mem_repair(dut, want, label)

    def _drive_isolate_pin(self, dut, level: int | None) -> None:
        drive_isolate_pin(dut, level)

    async def _prove_skip_mem_repair_tracks_isolate_pin(self, dut) -> None:
        """Both polarities of the isolate pin on one `skip_mem_repair_o` probe.

        ISOLATE_REQ_PINEN_REG has been programmed to all ones by the testcase
        module, no FLR has been signalled and ISOLATE_REQ_SMC_REG resets to 0,
        so of the isolation sources `clk_rst.adoc` names the enabled pin is the
        only one that moves between the three samples below. Driving the pin low
        is also what lets the fuse-sense edges of the reset cycles that follow
        happen with the repair path enabled at all -- with the pin floating,
        every sense edge in this package is a bypassed one.
        """
        self.skip_pin_floating = self._skip_mem_repair(dut)
        self._drive_isolate_pin(dut, 0)
        low_cycles = await self._await_skip_mem_repair(dut, 0, "isolate pin low")
        self.skip_pin_low = self._skip_mem_repair(dut)
        self._drive_isolate_pin(dut, 1)
        high_cycles = await self._await_skip_mem_repair(dut, 1, "isolate pin high")
        self.skip_pin_high = self._skip_mem_repair(dut)
        # Back to low for the reset cycles below, so their fuse-sense edges are
        # taken with the repair path enabled.
        self._drive_isolate_pin(dut, 0)
        await self._await_skip_mem_repair(dut, 0, "isolate pin low again")
        assert self.skip_pin_low == 0 and self.skip_pin_high == 1, (
            f"skip_mem_repair_o did not follow the isolate-request pin: "
            f"low->{self.skip_pin_low} high->{self.skip_pin_high}"
        )
        cocotb.log.info(
            "CHK-SKIP-MEM-REPAIR-PIN: tb_skip_mem_repair_o read %d with the "
            "isolate-request pad undriven, %d within %d clk_smc_i cycles of "
            "driving it low, and %d within %d cycles of driving it high, with "
            "ISOLATE_REQ_PINEN_REG at all ones, no FLR signalled and "
            "ISOLATE_REQ_SMC_REG at its reset 0",
            self.skip_pin_floating,
            self.skip_pin_low,
            low_cycles,
            self.skip_pin_high,
            high_cycles,
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self._prove_skip_mem_repair_tracks_isolate_pin(dut)
        await self._send(SmcResetOp.SAMPLE)
        for _ in range(self.REPEATS):
            await self._send(SmcResetOp.COLD_RST_LO)
            # Cold assert observed: cold-stable and both primary resets low
            # while power-good stays qualified.
            await self._send(
                SmcResetOp.WAIT_STATE,
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=0,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
                timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
            )
            # Still asserted while rst_cold_ni is held low, at every sample of a
            # real (time-advancing) window: a DUT that releases the cold path
            # early fails inside the hold.
            await self._hold_raw(
                "cold assert",
                expect_powergood_stable=1,
                expect_rst_cold_stable_ref_clk_n=0,
                expect_rst_primary_ref_clk_n=0,
                expect_rst_primary_smc_clk_n=0,
                expect_left_stable=True,
            )
            await self._send(SmcResetOp.COLD_RST_HI)
            await self._wait_released()
            await self._send(SmcResetOp.SAMPLE)
        # Exercise the cool-reset op set so the scoreboard sees the full
        # reset_op range -- with the same assert/release proof as the cold legs.
        await self._send(SmcResetOp.COOL_RST_LO)
        await self._send(
            SmcResetOp.WAIT_STATE,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
            timeout_ref_cycles=self.ASSERT_BOUND_REF_CYCLES,
        )
        await self._hold_raw(
            "cool assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._wait_released()
        await self._send(SmcResetOp.SAMPLE)
        # Activity gate on the fail-capable legs: one assert + one release wait
        # per cold repeat plus the cool pair, and a full checked mid-assert hold
        # window each ([NO-ZERO-ACTIVITY-PASS]). The raw floor counts the
        # samples taken *after* the assert handshake, so it cannot be satisfied
        # by snapshots that shared the wait's timestamp.
        sb = self.env.scoreboard
        expected_waits = 2 * (self.REPEATS + 1)
        assert sb.reset_wait_checks_seen >= expected_waits, (
            f"expected {expected_waits} bounded reset WAIT_STATE checks, "
            f"scoreboard saw {sb.reset_wait_checks_seen}"
        )
        expected_raw = (self.REPEATS + 1) * self.MID_ASSERT_HOLD_REF_CYCLES
        assert sb.reset_raw_checks_seen >= expected_raw, (
            f"expected {expected_raw} checked mid-assert hold samples "
            f"({self.REPEATS + 1} legs x {self.MID_ASSERT_HOLD_REF_CYCLES} "
            f"clk_ref_i edges), scoreboard saw {sb.reset_raw_checks_seen}"
        )
        await self._prove_fuse_sense_completes_with_repair_enabled(dut)
        # Release the pad override so nothing after this sequence inherits it.
        self._drive_isolate_pin(dut, None)

    async def _prove_fuse_sense_completes_with_repair_enabled(self, dut) -> None:
        """Fuse sense finishes again after the resets, repair path enabled.

        `fuse_sense_done` is cleared by `rst_primary_smc_clk_no`, which every
        cold assert above drives low, so the sense FSM has to re-run and
        re-complete after the last release. Nothing in this package observed
        that re-completion, and nothing observed it with the repair path
        enabled -- the isolate pin is still held low here, so
        `skip_mem_repair_o` must read 0 at the moment sense completes rather
        than the 1 the floating pad produces.
        """
        last = -1
        low_samples = 0
        for cycle in range(1, _SENSE_BOUND + 1):
            await ClockCycles(dut.clk_smc_i, 1)
            raw = dut.tb_fuse_sense_done.value
            assert raw.is_resolvable, f"tb_fuse_sense_done is X/Z: {raw}"
            last = int(raw) & 1
            if last == 1:
                break
            low_samples += 1
        else:
            raise AssertionError(
                f"tb_fuse_sense_done never rose within {_SENSE_BOUND} clk_smc_i "
                f"cycles of the last reset release (last={last}): fuse sense "
                f"did not re-complete after the repeated cold resets"
            )
        assert low_samples, (
            "tb_fuse_sense_done already read 1 on the first clk_smc_i sample after the last "
            "reset release, so it was not seen low and its rise is not a re-completion of "
            "fuse sense"
        )
        self.skip_at_sense_done = self._skip_mem_repair(dut)
        assert self.skip_at_sense_done == 0, (
            f"skip_mem_repair_o read {self.skip_at_sense_done} when fuse sense "
            f"completed while the isolate-request pin was held low; the repair "
            f"path was bypassed with nothing requesting isolation"
        )
        cocotb.log.info(
            "CHK-SENSE-DONE-REPAIR-ENABLED: tb_fuse_sense_done read 0 for %d "
            "clk_smc_i samples and rose %d cycles after the last reset release with "
            "tb_skip_mem_repair_o reading %d (isolate pin held low), against "
            "the %d it reads with the pad undriven",
            low_samples,
            cycle,
            self.skip_at_sense_done,
            self.skip_pin_floating,
        )
