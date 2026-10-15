# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_ctm_reset_wire_or_mode_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_ctm_route_test_seq import dtp_ctm_route_test_seq


@pyuvm.test()
class dtp_ctm_reset_wire_or_mode_test(dtp_xtrig_base_test):
    """A system reset on live wire-OR routes, then fresh routes recover."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_ctm_route_test_seq,
            "ctm_reset_wire_or_mode",
            scenario="ctm_reset_wire_or_mode",
            specific_knob="DTP_CTM_RESET_WIRE_OR_MODE_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
