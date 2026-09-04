# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP POR/TRST independence test."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_trst_por_independence_test_seq import (
    dtp_jtag_trst_por_independence_test_seq,
)


@pyuvm.test()
class dtp_jtag_trst_por_independence_test(dtp_base_test):
    """Run the DTP VPLAN POR-only TAP reset scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_trst_por_independence_test_seq,
            "jtag_trst_por_independence_seq",
            specific_knob="DTP_JTAG_TRST_POR_INDEPENDENCE_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
