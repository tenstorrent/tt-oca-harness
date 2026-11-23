# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP Boot ROM MEM_REPAIR / MBIST boot gate, PASS arm.

The pass-side partner of ``sep_firmware_mbist_fail_test``, whose comment above
``_DFT_STATUS_FAIL`` lists the gate in ``bootrom/prod/src/vector.S``.
``hw/sys/smc/regs/blocks/dfx_ctrl_status/dfx_ctrl_status.rdl`` declares ``mem_repair_done[0]``,
``mem_repair_success[1]``, ``mem_repair_abort[2]``, ``mbist_done[4]``, ``mbist_pass[8]`` and
``mbist_abort[12]``. The gate keys on ``mem_repair_success`` and ``mbist_pass``, after it waits
for ``mbist_done``. ``hw/sys/smc/regs/gen/c/smc_addr.h`` places
``SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR`` at 0xC000_B800, seen from SEP as 0x4000_B800. The SMC
responder is a flat memory, so this test cannot fail on the address; ``tb_top.sv`` flags an access
outside a declared window through ``smc_addr_violations_o``.

The gate runs before the C runtime starts and its pass arm prints nothing, so the checks assert
that execution reached the C runtime and that no failure-arm observable appeared.
``+sep_dft_status=00000112`` is exactly bits 1, 4 and 8. The testbench default 0x113 also boots, so
the injection is what makes the run a test. 0x112 hangs a gate on ``mem_repair_done``, on the whole
word equal to 0x113, or on a required abort bit. "Any bit set" is ruled out by the fail tests:
0xFFFFFFFD must block on repair and 0x12 must block on MBIST.

The bypass straps, the ``mbist_abort`` branch and the poll timeout are covered by the
``sep_firmware_repair_bypass_test``, ``sep_firmware_mbist_bypass_test``,
``sep_firmware_mbist_abort_test`` and ``sep_firmware_mbist_timeout_test`` siblings.
"""

from __future__ import annotations

import pyuvm
from rom_fw.sep_dft_gate_base import (
    MBIST_ABORT_BIT,
    MBIST_DONE_BIT,
    MBIST_PASS_BIT,
    MEM_REPAIR_ABORT_BIT,
    MEM_REPAIR_DONE_BIT,
    MEM_REPAIR_SUCCESS_BIT,
    sep_dft_gate_boot_base,
)

# Exactly the three bits the gate requires: mem_repair_success for the repair arm, and mbist_done
# plus mbist_pass for the MBIST arm. Must match +sep_dft_status in the testlist entry.
_DFT_STATUS_PASS = 0x0000_0112


@pyuvm.test()
class sep_firmware_mbist_pass_test(sep_dft_gate_boot_base):
    """Exactly mem_repair_success, mbist_done and mbist_pass set: the ROM boots straight through."""

    expected_dft_status = _DFT_STATUS_PASS

    def check_stimulus_shape(self) -> None:
        word = self.expected_dft_status
        for name, bit in (
            ("mem_repair_success", MEM_REPAIR_SUCCESS_BIT),
            ("mbist_done", MBIST_DONE_BIT),
            ("mbist_pass", MBIST_PASS_BIT),
        ):
            assert (word >> bit) & 1, (
                f"injected DFT status 0x{word:08x} has {name} (bit {bit}) CLEAR -- the gate "
                f"requires all three, so this is a failure-arm injection"
            )
        required = (1 << MEM_REPAIR_SUCCESS_BIT) | (1 << MBIST_DONE_BIT) | (1 << MBIST_PASS_BIT)
        assert word == required, (
            f"injected DFT status must be exactly the three required bits and nothing else; "
            f"0x{word:08x} != 0x{required:08x}. Leaving mem_repair_done (bit "
            f"{MEM_REPAIR_DONE_BIT}), mem_repair_abort (bit {MEM_REPAIR_ABORT_BIT}) and "
            f"mbist_abort (bit {MBIST_ABORT_BIT}) clear is what makes this discriminating"
        )
        self.logger.info(
            "CHK-DFT-PASS-STIMULUS: DFX_CTRL_STATUS_SMU = 0x%08x "
            "(mem_repair_success + mbist_done + mbist_pass; repair_done=%d "
            "repair_abort=%d mbist_abort=%d -- all clear)",
            word,
            (word >> MEM_REPAIR_DONE_BIT) & 1,
            (word >> MEM_REPAIR_ABORT_BIT) & 1,
            (word >> MBIST_ABORT_BIT) & 1,
        )

    def check_gate_outcome(self, console: list[str]) -> None:
        self.assert_dft_injected("CHK-DFT-INJECTED")
        self.assert_gate_reached("CHK-DFT-REACHED")
        self.assert_no_failure_arm("CHK-DFT-NO-WARN", "CHK-DFT-NO-PUBLISH")
