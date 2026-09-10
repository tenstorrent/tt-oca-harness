# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP undefined JTAG instruction fallback test."""

import pyuvm
from dtp_base_test import dtp_base_test
from seq_lib.dtp_jtag_undef_instr_test_seq import dtp_jtag_undef_instr_test_seq


@pyuvm.test()
class dtp_jtag_undef_instr_test(dtp_base_test):
    """Run the DTP VPLAN undefined-instruction scenario."""

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_jtag_undef_instr_test_seq,
            "jtag_undef_instr_seq",
            specific_knob="DTP_JTAG_UNDEF_INSTR_TEST_LOOPS",
            default_loops=16,
            group_knob="DTP_BASIC_JTAG_TEST_LOOPS",
        )
