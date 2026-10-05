# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the boot gate's MBIST arm rejects a part that failed MBIST.

``sep_firmware_mbist_fail_test`` injects 0xFFFFFFFD, so it fails the gate's first arm, memory
repair, and the MBIST check never runs. This test reaches the MBIST arm. The injection is
0x00000012:

    bit 1  mem_repair_success  SET    -> the repair arm passes, so control
                                         reaches the MBIST arm at all
    bit 4  mbist_done          SET    -> MBIST finished, so the gate stops
                                         polling and the verdict is valid
    bit 8  mbist_pass          CLEAR  -> and the verdict is FAIL

The shape check enforces all three: a clear mem_repair_success fails on the repair arm, and a
clear mbist_done exercises the poll timeout instead. A pass means the MBIST verdict alone can stop
the boot. It does not cover the poll timeout, the abort bit or either bypass strap, which reach
the same handler (``dft_gate_failed`` in ``bootrom/prod/src/vector.S``).
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_firmware_mbist_fail_test import sep_firmware_mbist_fail_test

# bootrom/prod/include/sep_smc_interface.h and
# hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl.
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

        The repair-arm base requires ``mem_repair_success`` clear; this arm
        requires it set.
        """
        word = self.dft_status_injected

        assert (word >> _MEM_REPAIR_SUCCESS_BIT) & 1, (
            f"injected DFT status 0x{word:08x} has mem_repair_success "
            f"(bit {_MEM_REPAIR_SUCCESS_BIT}) CLEAR. The gate would then stop on "
            f"the REPAIR arm and never evaluate MBIST, so the MBIST verdict would "
            f"not be under test"
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
