# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The rst_cool_ni de-glitch window and the pin's collision with the FLR hold."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cool_reset_deglitch_window_test_seq import (
    smc_cool_reset_deglitch_window_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor: the two counter writes and readbacks, the latch clear and at least
# one poll after each of the three FLR legs, and the final hold counter clear and readback.
COOL_RESET_DEGLITCH_WINDOW_MIN_CSR_ACCESSES = 12


@pyuvm.test()
class smc_cool_reset_deglitch_window_test(smc_base_test):
    """Pin lows below 32 samples are rejected, restart on a high and do not extend the release."""

    required_evidence = (
        "CHK-COOLRST-GLITCH-REJECT",
        "CHK-COOLRST-REASSERT-IN-HOLD",
        "CHK-COOLRST-REASSERT-RESTART",
        "CHK-COOLRST-RELEASE-NO-EXTENSION",
        "CHK-COOLRST-RELEASE-REASSERT-HOLD",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_deglitch_window_test_seq("smc_cool_reset_deglitch_window_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.window_ok, "rst_cool_ni de-glitch window scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=COOL_RESET_DEGLITCH_WINDOW_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="rst_cool_ni de-glitch window and FLR hold collision",
        )
