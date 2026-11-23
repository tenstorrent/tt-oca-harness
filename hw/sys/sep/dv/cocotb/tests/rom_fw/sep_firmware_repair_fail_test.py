# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Memory repair failed with no bypass strap is a terminal gate failure (``SEP-ROM-SMC-030``).

``+sep_dft_status=00000110`` is the word ``sep_firmware_repair_bypass_test`` boots on:
mbist_done and mbist_pass set, mem_repair_success clear. Without ``STRAPS_LO[13]`` the repair arm
must fail, so the ROM publishes the word to SMC scratch[10], writes the MBIST WARN word then
ROM_ERR_DFT_GATE_BLOCKED to cold_scratch[1], stays silent on the console and spins. That evidence is
graded by ``sep_firmware_mbist_fail_test``. This member adds the stimulus shape, the strap guard
and the read count: one DFX_CTRL_STATUS_SMU read, so the ROM left at the repair arm and never
entered the MBIST wait, which this word would pass.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_dft_gate_base import (
    MBIST_ABORT_BIT,
    MBIST_DONE_BIT,
    MBIST_PASS_BIT,
    MEM_REPAIR_SUCCESS_BIT,
    assert_no_bypass_strapped,
)
from rom_fw.sep_firmware_mbist_fail_test import sep_firmware_mbist_fail_test


@pyuvm.test()
class sep_firmware_repair_fail_test(sep_firmware_mbist_fail_test):
    """Repair failed, MBIST passed, nothing bypassed: the ROM halts before C."""

    dft_status_injected = (1 << MBIST_DONE_BIT) | (1 << MBIST_PASS_BIT)
    expected_dft_reads = 1

    def check_stimulus_shape(self) -> None:
        word = self.dft_status_injected
        assert not (word >> MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success set; the repair arm "
            f"would pass and the failure would not be under test"
        )
        assert (word >> MBIST_DONE_BIT) & 1 and (word >> MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} lacks mbist_done or mbist_pass; the MBIST arm "
            f"could then cause the halt instead of the repair arm"
        )
        assert not (word >> MBIST_ABORT_BIT) & 1, (
            f"injected DFT status 0x{word:08x} sets mbist_abort; the MBIST arm could then cause "
            f"the halt instead of the repair arm"
        )
        self.logger.info(
            "CHK-DFT-REPAIR-FAIL-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(repair_success=0 mbist_done=1 mbist_pass=1 mbist_abort=0)",
            word,
        )

    async def run_scenario(self) -> None:
        await super().run_scenario()
        assert_no_bypass_strapped(self, "CHK-DFT-REPAIR-FAIL-STIMULUS")
        self.logger.info(
            "CHK-DFT-REPAIR-FAIL-STIMULUS PASS: repair-failure word read by the ROM with both "
            "bypass straps clear"
        )
