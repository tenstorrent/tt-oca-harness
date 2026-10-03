# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ctm_p2p_cla_to_ctp_test`."""

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq


@pyuvm.test()
class dtp_ctm_p2p_cla_to_ctp_test(dtp_xtrig_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_base_test_seq,
            "ctm_p2p_cla_to_ctp",
            scenario="ctm_p2p_cla_to_ctp",
            specific_knob="DTP_CTM_P2P_CLA_TO_CTP_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
