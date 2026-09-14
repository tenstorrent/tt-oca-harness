# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse sense + backdoor shadow-readout test (OSS).

Selects an OTP image through the shared eFuse image policy and senses it through
the behavioral OTP responder. The common sense-done helper compares the sensed
shadow registers against the golden via the backdoor probe.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test

_MAX_SENSE_CYCLES = 20_000


@pyuvm.test()
class sep_efuse_sense_test(sep_base_test):
    """Fuse-sense with backdoor shadow comparison."""

    # Backdoor-only: no AXI sequencer/scoreboard needed (the shadow probe is
    # read directly), so skip the AXI env -- otherwise its check_phase fails the
    # test for "no AXI transactions".
    build_env = False

    async def run_scenario(self) -> None:
        img = self.select_efuse_image()
        self.write_efuse_image(img)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
