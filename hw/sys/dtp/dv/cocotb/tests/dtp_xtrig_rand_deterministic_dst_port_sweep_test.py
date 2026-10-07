# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_xtrig_rand_deterministic_dst_port_sweep_test`."""

import pyuvm
from dtp_xtrig_base_test import dtp_xtrig_base_test
from seq_lib.dtp_xtrig_route_test_seq import dtp_xtrig_route_test_seq


@pyuvm.test()
class dtp_xtrig_rand_deterministic_dst_port_sweep_test(dtp_xtrig_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_route_test_seq,
            "dst_port_sweep",
            scenario="dst_port_sweep",
            specific_knob="DTP_XTRIG_RAND_DETERMINISTIC_DST_PORT_SWEEP_TEST_LOOPS",
            group_knob="DTP_XTRIG_TEST_LOOPS",
        )
