# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MBIST abort with no bypass strap is a terminal gate failure (``SEP-ROM-SMC-030``).

``+sep_dft_status=00001002`` passes the repair arm and sets mbist_abort with mbist_done and
mbist_pass clear, so the MBIST poll leaves on its first abort check. The ROM must publish the raw
word to SMC scratch[10], write the MBIST WARN word then ROM_ERR_DFT_GATE_BLOCKED to
cold_scratch[1], stay silent on the console and spin. All of that is graded by
``sep_firmware_mbist_fail_test``; this member adds the stimulus shape, the strap guard and the
read count. Two DFX_CTRL_STATUS_SMU reads, the gate read and the first wait read, separate the
abort exit from the exhausted wait that ``sep_firmware_mbist_timeout_test`` grades.
``sep_firmware_mbist_bypass_test`` boots on the same word with ``STRAPS_HI[22]`` set.
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
class sep_firmware_mbist_abort_test(sep_firmware_mbist_fail_test):
    """Repair passed, MBIST aborted, nothing bypassed: the ROM halts before C."""

    dft_status_injected = (1 << MEM_REPAIR_SUCCESS_BIT) | (1 << MBIST_ABORT_BIT)
    expected_dft_reads = 2

    def check_stimulus_shape(self) -> None:
        word = self.dft_status_injected
        assert (word >> MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success clear; the repair arm "
            f"would halt first and the abort branch would not be under test"
        )
        assert (word >> MBIST_ABORT_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mbist_abort clear; set bit {MBIST_ABORT_BIT}"
        )
        assert not (word >> MBIST_DONE_BIT) & 1 and not (word >> MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} sets mbist_done or mbist_pass; the halt could "
            f"then come from the completed-verdict branch instead of the abort check"
        )
        self.logger.info(
            "CHK-DFT-MBIST-ABORT-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(repair_success=1 mbist_abort=1 mbist_done=0 mbist_pass=0)",
            word,
        )

    async def run_scenario(self) -> None:
        await super().run_scenario()
        assert_no_bypass_strapped(self, "CHK-DFT-MBIST-ABORT-STIMULUS")
        self.logger.info(
            "CHK-DFT-MBIST-ABORT-STIMULUS PASS: abort word read by the ROM with both bypass "
            "straps clear"
        )
