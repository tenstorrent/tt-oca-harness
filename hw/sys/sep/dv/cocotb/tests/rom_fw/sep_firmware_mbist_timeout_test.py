# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""MBIST never done, no bypass strap: the bounded poll ends in the terminal gate failure.

``+sep_dft_status=00000002`` passes the repair arm and leaves mbist_done, mbist_pass and
mbist_abort clear, so the MBIST poll can leave only by exhausting its bound (``SEP-ROM-SMC-030``).
The terminal evidence is graded by ``sep_firmware_mbist_fail_test``. The SMC port must see the gate
read plus ``MBIST_DONE_WAIT_ITERS`` wait reads, the bound SEP-ROM-SMC-030 names, so the halt comes
from the exhausted wait and not from an early exit. The bound is an implementation limit, so no
time is graded.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_dft_gate_base import (
    MBIST_ABORT_BIT,
    MBIST_DONE_BIT,
    MBIST_PASS_BIT,
    MEM_REPAIR_SUCCESS_BIT,
    assert_no_bypass_strapped,
    mbist_done_wait_iters,
)
from rom_fw.sep_firmware_mbist_fail_test import sep_firmware_mbist_fail_test


@pyuvm.test()
class sep_firmware_mbist_timeout_test(sep_firmware_mbist_fail_test):
    """Repair passed, MBIST never finishes, nothing bypassed: the ROM halts before C."""

    dft_status_injected = 1 << MEM_REPAIR_SUCCESS_BIT
    # Backstop only: the loop stops at the terminal status. The poll is one SMC round trip per
    # iteration, so it outlasts the repair-arm budget.
    max_run_cycles = 4_000_000
    expected_dft_reads = 1 + mbist_done_wait_iters()

    def check_stimulus_shape(self) -> None:
        word = self.dft_status_injected
        assert (word >> MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success clear; the repair arm "
            f"would halt before the MBIST poll starts"
        )
        for name, bit in (
            ("mbist_done", MBIST_DONE_BIT),
            ("mbist_pass", MBIST_PASS_BIT),
            ("mbist_abort", MBIST_ABORT_BIT),
        ):
            assert not (word >> bit) & 1, (
                f"injected DFT status 0x{word:08x} sets {name}; the poll would leave before "
                f"its bound and the timeout would not be under test"
            )
        assert word == 1 << MEM_REPAIR_SUCCESS_BIT, (
            f"injected DFT status 0x{word:08x} must be mem_repair_success alone"
        )
        self.logger.info(
            "CHK-DFT-MBIST-TIMEOUT-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(repair_success=1, mbist_done/pass/abort=0)",
            word,
        )

    async def run_scenario(self) -> None:
        await super().run_scenario()
        assert_no_bypass_strapped(self, "CHK-DFT-MBIST-TIMEOUT-STIMULUS")
        self.logger.info(
            "CHK-DFT-MBIST-TIMEOUT-STIMULUS PASS: not-done word read by the ROM with both "
            "bypass straps clear"
        )
