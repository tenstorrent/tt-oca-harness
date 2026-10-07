# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DTP VPLAN scenario `dtp_3dcr_stap_sel_ds_test`.

I/O (die-stack) STAP selection, gating, isolation, and recovery through composed
TAP_3DCR chain scans, with a downstream ocah_jtag_vip TAP behind every STAP
host port so the primary evidence is end-to-end: downstream IDCODE and
DS_TDR readback through the selected STAP, the downstream register frozen
in Test-Logic-Reset while the port is gated, and recovery against real
downstream state. The host-port temporal windows corroborate that evidence.
"""

from __future__ import annotations

import pyuvm
from dtp_base_test import dtp_base_test
from env.dtp_stap_3dcr_model import STAP_ORDER
from seq_lib.dtp_stap_scan_test_seq import dtp_stap_scan_test_seq


@pyuvm.test()
class dtp_3dcr_stap_sel_ds_test(dtp_base_test):
    """I/O STAP selection, gating, isolation, and recovery, end to end through a downstream TAP."""

    # Every port carries a downstream TAP so the isolation neighbor has one too.
    stap_ds_attach = STAP_ORDER

    async def run_scenario(self) -> None:
        await self.start_looped_seq(
            dtp_stap_scan_test_seq,
            "stap_sel_ds",
            scenario="stap_sel_ds",
            specific_knob="DTP_3DCR_STAP_SEL_DS_TEST_LOOPS",
            group_knob="DTP_SCAN_TEST_LOOPS",
        )
