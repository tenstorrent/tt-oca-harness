# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_reg_stall_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_csr_test_seq import dtp_xtrig_csr_test_seq


@pyuvm.test()
class dtp_xtrig_reg_stall_test(dtp_xtrig_base_test):
    """Accepted-path CSR accesses with the cross-trigger pins quiet."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_csr_test_seq,
            "reg_stall",
            scenario="reg_stall",
            specific_knob="DTP_XTRIG_REG_STALL_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
