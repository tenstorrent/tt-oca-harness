# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP JTAG IDCODE field test.

Reads and verifies the IEEE 1149.1 IDCODE register on the primary TAP through
the shared ocah_jtag_vip BFM.
"""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_types import DTP_FEATURE_IDCODE, DTP_FEATURE_IR_DECODE
from ocah_lib import OcahKnobs
from seq_lib.dtp_jtag_idcode_test_seq import dtp_jtag_idcode_test_seq


@pyuvm.test()
class dtp_jtag_idcode_test(dtp_base_test):
    """Run looped IDCODE scenarios with deterministic random preconditioning."""

    required_features = (DTP_FEATURE_IR_DECODE, DTP_FEATURE_IDCODE)

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_idcode_test_seq,
            "jtag_idcode_seq",
            specific_knob="DTP_JTAG_IDCODE_TEST_LOOPS",
            default_loops=16,
            read_loops=OcahKnobs.get_int_min("DTP_IDCODE_READS_PER_LOOP", 4, 1),
        )
