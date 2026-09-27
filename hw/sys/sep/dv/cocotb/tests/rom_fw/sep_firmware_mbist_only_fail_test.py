# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the boot gate's MBIST arm rejects a part that failed MBIST.

WHY THIS EXISTS SEPARATELY FROM sep_firmware_mbist_fail_test.

That test injects 0xFFFFFFFD -- every bit except mem_repair_success -- so it
fails the gate's FIRST arm, memory repair, and returns without the MBIST check
ever running. It proves the repair arm rejects; it says nothing about MBIST.
Without this test the MBIST arm (`sep-boot-flow.puml:58-67`) is code no testcase
reaches: a gate shown to ACCEPT a healthy part and never shown to REJECT an
unhealthy one.

THE INJECTION IS THE WHOLE POINT. 0x00000012 is:

    bit 1  mem_repair_success  SET    -> the repair arm passes, so control
                                         reaches the MBIST arm at all
    bit 4  mbist_done          SET    -> MBIST finished, so the gate stops
                                         polling and the verdict is valid
    bit 8  mbist_pass          CLEAR  -> and the verdict is FAIL

Every one of those three is load-bearing and the shape check below enforces all
three. Clearing mem_repair_success would fail on the repair arm and prove
nothing new; leaving mbist_done clear would exercise the poll timeout instead,
which is a different path reaching the same handler.

WHAT A PASS HERE MEANS, AND WHAT IT DOES NOT. It means the MBIST verdict alone
can stop the boot. It does not cover the poll timeout, the abort bit, or either
bypass strap -- those are separate injections against the same shared failure
handler (`dft_gate_failed` in bootrom/prod/src/vector.S).
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_firmware_mbist_fail_test import sep_firmware_mbist_fail_test

# bootrom/prod/include/sep_smc_interface.h and dfx_ctrl_status.rdl.
_MEM_REPAIR_SUCCESS_BIT = 1
_MBIST_DONE_BIT = 4
_MBIST_PASS_BIT = 8

_DFT_STATUS_MBIST_FAIL = (1 << _MEM_REPAIR_SUCCESS_BIT) | (1 << _MBIST_DONE_BIT)


@pyuvm.test()
class sep_firmware_mbist_only_fail_test(sep_firmware_mbist_fail_test):
    """MBIST reports a completed FAILURE; the ROM must refuse to boot.

    Inherits every check from the repair-arm sibling -- terminal status word in
    cold_scratch[1], raw DFT status published to SMC scratch 10, empty console
    (the gate is pre-C assembly), and the quiescence check that the PC really is
    spinning rather than making slow forward progress. Only the stimulus and its
    shape contract differ.
    """

    dft_status_injected = _DFT_STATUS_MBIST_FAIL

    def check_stimulus_shape(self) -> None:
        """Enforce this arm's contract, replacing the repair arm's.

        The base class asserts mem_repair_success is CLEAR, which is the exact
        opposite of what this test needs, so overriding is mandatory rather than
        cosmetic.
        """
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
