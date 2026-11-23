# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""``MBIST_BYPASS`` (``STRAPS_HI[22]``) skips only the gate's MBIST check.

``+sep_dft_status=00001002`` passes the repair arm (mem_repair_success) and sets mbist_abort with
mbist_done and mbist_pass clear, the word the MBIST arm rejects first (``SEP-ROM-SMC-030``). With
the strap set the ROM must skip the MBIST arm and complete the boot;
``sep_firmware_mbist_abort_test`` injects the same word without the strap and must halt. One
abort word is the minimum stimulus that proves the bypass; fail and timeout variants add nothing
the branch does not already skip.

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
    STRAP_MBIST_BYPASS_HI,
    sep_dft_gate_boot_base,
)


@pyuvm.test()
class sep_firmware_mbist_bypass_test(sep_dft_gate_boot_base):
    """Repair passed, MBIST aborted, MBIST bypass strapped: the ROM boots."""

    expected_dft_status = (1 << MEM_REPAIR_SUCCESS_BIT) | (1 << MBIST_ABORT_BIT)
    required_straps_hi = STRAP_MBIST_BYPASS_HI

    def check_stimulus_shape(self) -> None:
        word = self.expected_dft_status
        assert (word >> MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success clear; the repair arm "
            f"would halt before the MBIST bypass is read"
        )
        assert (word >> MBIST_ABORT_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mbist_abort clear; without a word the MBIST "
            f"arm rejects, the bypass would not be under test"
        )
        assert not (word >> MBIST_DONE_BIT) & 1 and not (word >> MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} sets mbist_done or mbist_pass; a passing verdict "
            f"would let the MBIST arm continue without the bypass"
        )
        self.logger.info(
            "CHK-DFT-MBIST-BYPASS-STIMULUS: launch injects DFX_CTRL_STATUS_SMU = 0x%08x "
            "(mbist_abort set, done/pass clear) with STRAPS_HI[22] strapped",
            word,
        )

    def check_gate_outcome(self, console: list[str]) -> None:
        self.assert_dft_injected("CHK-DFT-MBIST-BYPASS-STIMULUS")
        self.assert_straps_captured("CHK-DFT-MBIST-BYPASS-STIMULUS", console)
        self.logger.info(
            "CHK-DFT-MBIST-BYPASS-STIMULUS PASS: aborted-MBIST word and STRAPS_HI[22] both "
            "measured at the SMC"
        )
        self.assert_gate_reached("CHK-DFT-MBIST-BYPASS-CONTINUE")
        self.logger.info(
            "CHK-DFT-MBIST-BYPASS-CONTINUE PASS: past the gate to SMC_MEM_CHK/CHIP_ID= and BL1 PASS"
        )
        self.assert_no_failure_arm("CHK-DFT-MBIST-BYPASS-NO-FAIL", "CHK-DFT-MBIST-BYPASS-NO-FAIL")
        self.logger.info("CHK-DFT-MBIST-BYPASS-NO-FAIL PASS")
