# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_cool_reset_pin_test - the cool reset pin and the DFT status straps.

Drives rst_cool_n_from_pin_i at the wrapper and observes the SMC primary reset
it owns: a 28-clk_ref pulse is filtered, a hold past that pulse resets the
SMC, and the SMC returns when the pin releases. The four DFT
done/pass straps are held low across that reset so DFX_CTRL.STATUS_SMU is read
at its reset value and each set-only field is then paired with the strap that
sets it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_cool_reset_pin_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_cool_reset_pin_seq import smu_smc_cool_reset_pin_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_cool_reset_pin_test(smu_base_test):
    """Cool reset pin to SMC primary reset, and the DFT status straps through that reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_cool_reset_pin_seq(self).run()
