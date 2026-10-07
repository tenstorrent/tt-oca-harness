# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ctm_p2p_ctp_to_ctp_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_ctm_route_test_seq import dtp_ctm_route_test_seq


@pyuvm.test()
class dtp_ctm_p2p_ctp_to_ctp_test(dtp_xtrig_base_test):
    """Seeded CTP-to-CTP point-to-point routes with full request/acknowledge handshakes."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_ctm_route_test_seq,
            "ctm_p2p_ctp_to_ctp",
            scenario="ctm_p2p_ctp_to_ctp",
            specific_knob="DTP_CTM_P2P_CTP_TO_CTP_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
