# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the boot gate's MBIST arm rejects a part that failed MBIST.

0x00000012 sets mem_repair_success and mbist_done with mbist_pass clear, so the repair
arm passes and the gate halts on the MBIST verdict rather than on the poll timeout.
"""

from __future__ import annotations

import pyuvm

from rom_fw.sep_firmware_mbist_fail_test import sep_firmware_mbist_fail_test

_MEM_REPAIR_SUCCESS_BIT = 1
_MBIST_DONE_BIT = 4
_MBIST_PASS_BIT = 8

_DFT_STATUS_MBIST_FAIL = (1 << _MEM_REPAIR_SUCCESS_BIT) | (1 << _MBIST_DONE_BIT)


@pyuvm.test()
class sep_firmware_mbist_only_fail_test(sep_firmware_mbist_fail_test):
    """MBIST reports a completed FAILURE; the ROM must refuse to boot."""

    dft_status_injected = _DFT_STATUS_MBIST_FAIL

    def check_stimulus_shape(self) -> None:
        word = self.dft_status_injected

        assert (word >> _MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success "
            f"(bit {_MEM_REPAIR_SUCCESS_BIT}) CLEAR. The gate would then stop on "
            f"the REPAIR arm and never evaluate MBIST, which is precisely the "
            f"coverage hole this test exists to close"
        )
        assert (word >> _MBIST_DONE_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mbist_done "
            f"(bit {_MBIST_DONE_BIT}) CLEAR. The gate would poll for completion "
            f"and reach the handler by TIMEOUT, not by reading a failed verdict; "
            f"the test would pass while proving something else"
        )
        assert not (word >> _MBIST_PASS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mbist_pass "
            f"(bit {_MBIST_PASS_BIT}) SET -- that is the pass arm, and the ROM "
            f"would boot"
        )
