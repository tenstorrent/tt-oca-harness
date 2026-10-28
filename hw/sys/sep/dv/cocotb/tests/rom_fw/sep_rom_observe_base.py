# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base of the ROM leaves that run the Boot ROM until a condition and grade the record.

The ROM takes its SMC-SRAM manifest path unless the testlist adds +sep_boot_from_spi.
A leaf sets the eFuse image, an optional runtime stimulus, the stop condition and
the grading; the base owns bring-up, the observer and the verdict call.
"""

from __future__ import annotations

import cocotb
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import LC_TEST_DEV, SepEfuseImage
from env.sep_rom_observer import SepRomObserver
from sep_base_test import sep_base_test
from sep_reg_meta import sym

ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
RUN_PULSE_CYCLES = 40


class sep_rom_observe_base(sep_base_test):
    build_env = False
    verdict_source = "scratch0"
    lc_state = LC_TEST_DEV
    max_run_cycles = 4_000_000
    observer_kwargs: dict = {}

    def build_efuse_image(self) -> SepEfuseImage:
        img = SepEfuseImage()
        img.set_lc_state(self.lc_state)
        return img

    async def stimulus(self, obs: SepRomObserver) -> None:
        """Runtime stimulus that reacts to the record; none by default.

        It starts before bring-up, which drives every TB input to its idle default, so it
        waits on the record before it drives anything. It is cancelled once the stop
        condition holds, so a leaf whose grade needs the stimulus logs its own CTRL.
        """

    def done(self, obs: SepRomObserver) -> bool:
        return obs.verdict_pass() is not None

    async def before_grade(self, obs: SepRomObserver) -> None:
        """Hook to stop the leaf's own monitors (fabric taps) after the run; none by default."""

    def grade(self, obs: SepRomObserver, chk: SepChkLog) -> None:
        raise NotImplementedError(f"{self.get_type_name()} must grade its record")

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.write_efuse_image(self.build_efuse_image())
        self.obs = SepRomObserver(self, **self.observer_kwargs).start()
        stim = cocotb.start_soon(self.stimulus(self.obs))
        await self.bring_up_cpu_boot(ROM_BASE >> 1, run_pulse_cycles=RUN_PULSE_CYCLES)
        reached = await self.obs.run_until(self.done, self.max_run_cycles)
        stim.cancel()
        await self.obs.stop()
        await self.before_grade(self.obs)
        # A record cut off before the stop condition would let absence checks pass for free.
        self.chk.ctrl("RUN-REACHED", reached, cycles=self.obs.cycle, retired=self.obs.retired)
        self.grade(self.obs, self.chk)
        self.chk.finish()
