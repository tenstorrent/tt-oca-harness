# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_wire_or_test`."""

from __future__ import annotations

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_route_test_seq import dtp_xtrig_route_test_seq


@pyuvm.test()
class dtp_xtrig_wire_or_test(dtp_xtrig_base_test):
    """CTP wire-OR pulse stretching, BUSY status, and external-to-internal synchronization."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_route_test_seq,
            "wire_or",
            scenario="wire_or",
            specific_knob="DTP_XTRIG_WIRE_OR_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
