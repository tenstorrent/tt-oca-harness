# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP open-source JTAG IDCODE field test.

Reads and verifies the IEEE 1149.1 IDCODE register on the primary TAP through
the shared ocah_jtag_vip BFM.
"""

import pyuvm
from dtp_base_test import dtp_base_test
from ocah_lib import OcahKnobs
from seq_lib.dtp_jtag_idcode_test_seq import dtp_jtag_idcode_test_seq


@pyuvm.test()
class dtp_jtag_idcode_test(dtp_base_test):
    """Run looped IDCODE scenarios with deterministic random preconditioning."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_idcode_test_seq,
            "jtag_idcode_seq",
            specific_knob="DTP_IDCODE_TEST_LOOPS",
            default_loops=16,
            read_loops=OcahKnobs.get_int_min("DTP_IDCODE_READS_PER_LOOP", 4, 1),
        )
