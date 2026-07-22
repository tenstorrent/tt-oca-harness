# SPDX-License-Identifier: Apache-2.0
"""DTP VPLAN scenario `dtp_xtrig_wire_or_test`."""

import pyuvm

from dtp_base_test import dtp_base_test
from seq_lib.dtp_xtrig_base_test_seq import dtp_xtrig_base_test_seq


@pyuvm.test()
class dtp_xtrig_wire_or_test(dtp_base_test):
    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_xtrig_base_test_seq,
            "wire_or",
            scenario="wire_or",
            specific_env="DTP_XTRIG_WIRE_OR_TEST_LOOPS",
            group_env="DTP_XTRIG_TEST_LOOPS",
        )
