# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stands in for the BISR/MBIST engines that report into the ROM's boot sequencer.

There is no DFT engine in this bench, so the six `mem_repair_*` / `mbist_*` lines are
driven from here. Every other test leaves them at the idle posture
SmcDualHarness.idle_pins() sets -- done/success/pass high, abort low.

**The result must be on the lines before the target's boot_stall drops.** The ROM does not
wait for `done`: `memory_repair_check_override.S` and `mbist_check_override.S` both branch
on `beqz done -> assume not required` and record MBIST_STATUS_PASSED. Reporting after the
cores start is therefore indistinguishable from reporting nothing, and holding the lines
low is worse than leaving them idle -- it is what makes the ROM skip the check.

Contracts with hw/sys/smc/bootrom/prod:
    smc_rom_defs.h   SMC_SCRATCH_MBIST_STATUS = 15, where the ROM records the outcome
    smc_rom_defs.h   DFT_STATUS_*_MASK_VAL, the DFX_CTRL_STATUS masks the ROM reads

The status codes below are the ROM's, not this driver's: it only decides which failure to
report and then checks what the ROM wrote.
"""

from __future__ import annotations

import logging

from cocotb.triggers import ClockCycles

# Written by the ROM into scratch 15 while the check is still running.
MBIST_STATUS_IN_PROGRESS = 0x1234_5678

# Final scratch 15 values, one per failure mode.
MBIST_STATUS_MEM_REPAIR_FAIL = 0xBADC_0FFE
MBIST_STATUS_MBIST_FAIL = 0xDEAD_BEEF
MBIST_STATUS_MBIST_TIMEOUT = 0xDEAD_C0DE

EXPECTED_STATUS = {
    "mem_repair_fail": MBIST_STATUS_MEM_REPAIR_FAIL,
    "mbist_fail": MBIST_STATUS_MBIST_FAIL,
    "mbist_timeout": MBIST_STATUS_MBIST_TIMEOUT,
}


class SmcDftStatusDriver:
    """Reports one BISR/MBIST outcome to one instance and reads back what the ROM made of it."""

    def __init__(self, harness, instance: str, csr, clk) -> None:
        self.harness = harness
        self.instance = instance
        self.csr = csr
        self.clk = clk
        self.log = logging.getLogger("cocotb.dft_status")

    def report(self, scenario: str) -> None:
        """Drive the line pattern for one scenario, in the ROM's read order.

        Call after bring_up() and before the target's release_cpu(): the lines have to
        carry the result when the ROM first reads DFX_CTRL_STATUS, which is early in its
        boot.

        mem repair reports first because the ROM reads it first; a mem-repair failure is
        expected to stop the boot before MBIST matters, but MBIST is still reported so the
        ROM's second check sees a real result rather than the skip path.
        """
        if scenario not in EXPECTED_STATUS:
            raise AssertionError(
                f"unknown DFT scenario {scenario!r}; expected one of "
                f"{', '.join(sorted(EXPECTED_STATUS))}"
            )

        self.harness.set_dft_result(
            self.instance,
            mem_repair_done=1,
            mem_repair_success=0 if scenario == "mem_repair_fail" else 1,
        )

        if scenario == "mbist_timeout":
            # There is no separate timeout input. The ROM's timeout branch is entered on
            # done with pass low and abort high.
            self.harness.set_dft_result(self.instance, mbist_pass=0, mbist_abort=1, mbist_done=1)
        else:
            self.harness.set_dft_result(
                self.instance,
                mbist_abort=0,
                mbist_pass=0 if scenario == "mbist_fail" else 1,
                mbist_done=1,
            )

        self.log.info("%s reported DFT scenario %s", self.instance, scenario)

    async def wait_for_status(
        self, scenario: str, scratch_addr: int, poll_iters: int, poll_cycles: int
    ) -> int:
        """Poll scratch 15 until the ROM records a final value, and check which one."""
        expected = EXPECTED_STATUS[scenario]
        observed = 0
        for _ in range(poll_iters):
            observed = await self.csr.read("MBIST_STATUS", scratch_addr)
            if observed not in (0, MBIST_STATUS_IN_PROGRESS):
                break
            await ClockCycles(self.clk, poll_cycles)
        else:
            raise AssertionError(
                f"{self.instance}: ROM never recorded a DFT outcome for {scenario}.\n"
                f"  scratch 15 = {observed:#010x} "
                f"({'in progress' if observed == MBIST_STATUS_IN_PROGRESS else 'never written'})\n"
                f"  expected {expected:#010x} after {poll_iters}x{poll_cycles} cycles"
            )

        if observed != expected:
            raise AssertionError(
                f"{self.instance}: ROM recorded {observed:#010x} for {scenario}, "
                f"expected {expected:#010x}"
            )
        self.log.info("%s scratch 15 = %#010x, as %s requires", self.instance, observed, scenario)
        return observed
