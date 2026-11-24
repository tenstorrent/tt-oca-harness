# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``BYPASS_SRAM_REPAIR`` (``STRAPS_LO[13]``) skips only the gate's memory-repair check.

``+sep_dft_status=00000110`` sets mbist_done and mbist_pass but leaves mem_repair_success clear,
the word the repair arm rejects (``SEP-ROM-SMC-030``). With the strap set the ROM must skip that
check, still pass the MBIST arm and complete the boot. Removing the strap from this entry makes
the same word halt on ROM_ERR_DFT_GATE_BLOCKED, so the boot result is attributable to the strap.

Scope: the captured strap word at the SMC model to the ROM branch. The physical GPIO-to-strap
capture is not modelled in the ``rom_boot`` target.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_dft_gate_base import (
    MBIST_ABORT_BIT,
    MBIST_DONE_BIT,
    MBIST_PASS_BIT,
    MEM_REPAIR_SUCCESS_BIT,
    STRAP_BYPASS_SRAM_REPAIR_LO,
    sep_dft_gate_boot_base,
)


@pyuvm.test()
class sep_firmware_repair_bypass_test(sep_dft_gate_boot_base):
    """Repair failed, repair bypass strapped, MBIST passed: the ROM boots."""

    expected_dft_status = (1 << MBIST_DONE_BIT) | (1 << MBIST_PASS_BIT)
    required_straps_lo = STRAP_BYPASS_SRAM_REPAIR_LO

    def check_stimulus_shape(self) -> None:
        word = self.expected_dft_status
        assert not (word >> MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success set; the repair arm would "
            f"pass without the bypass and the strap would not be under test"
        )
        assert (word >> MBIST_DONE_BIT) & 1 and (word >> MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} must set mbist_done and mbist_pass; this test "
            f"bypasses only the repair arm, so the MBIST arm has to pass on its own"
        )
        assert not (word >> MBIST_ABORT_BIT) & 1, (
            f"injected DFT status 0x{word:08x} sets mbist_abort, which halts the MBIST arm"
        )
        self.logger.info(
            "CHK-DFT-REPAIR-BYPASS-STIMULUS: launch injects DFX_CTRL_STATUS_SMU = 0x%08x "
            "(mem_repair_success clear) with STRAPS_LO[13] strapped",
            word,
        )

    def check_gate_outcome(self, console: list[str]) -> None:
        self.assert_dft_injected("CHK-DFT-REPAIR-BYPASS-STIMULUS")
        self.assert_straps_captured("CHK-DFT-REPAIR-BYPASS-STIMULUS", console)
        self.logger.info(
            "CHK-DFT-REPAIR-BYPASS-STIMULUS PASS: repair-failed word and STRAPS_LO[13] both "
            "measured at the SMC"
        )
        self.assert_gate_reached("CHK-DFT-REPAIR-BYPASS-CONTINUE")
        # The base already required the post-gate markers and the BL1 PASS verdict.
        self.logger.info(
            "CHK-DFT-REPAIR-BYPASS-CONTINUE PASS: past the gate to SMC_MEM_CHK/CHIP_ID= and "
            "BL1 PASS"
        )
        self.assert_no_failure_arm("CHK-DFT-REPAIR-BYPASS-NO-FAIL", "CHK-DFT-REPAIR-BYPASS-NO-FAIL")
        self.logger.info("CHK-DFT-REPAIR-BYPASS-NO-FAIL PASS")
