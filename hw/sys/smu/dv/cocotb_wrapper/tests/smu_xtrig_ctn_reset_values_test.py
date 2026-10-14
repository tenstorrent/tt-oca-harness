# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_xtrig_ctn_reset_values_test - CTN register reset values behind the SMC DTP CSR window.

Contract: SMU_MISC_XTRIG_007, anchor smu_xtrig_ctn_reset_values_test.
Spec: cross_trigger_matrix.rdl (CT_SRC, CT_DST_SELECT reset 0x0), cross_trigger_port.rdl (CONFIG,
STATUS, STRETCH_MULT reset 0x0), cross_trigger_network.rdl, smc.rdl (dtp_ctrl_reg window).
The 26 CT_SRC registers and CONFIG, STATUS and STRETCH_MULT of the 16 CTPs read 0 after reset.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_xtrig_ctn_reset_values_test_seq import smu_xtrig_ctn_reset_values_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_xtrig_ctn_reset_values_test(smu_base_test):
    """CT_SRC and CTP reset values read through the SMC DTP CSR window."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_xtrig_ctn_reset_values_test_seq(self).run()
