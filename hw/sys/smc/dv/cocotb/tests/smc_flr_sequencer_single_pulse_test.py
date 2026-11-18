# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The FLR cool pulse on the BP_COOL_RESET_N_O pad and the ISOLATE_REQ_VIS levels.

Source: ``hw/sys/smc/doc/clk_rst.adoc`` "Isolation Connections" and "Timing and Recovery".
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_flr_sequencer_single_pulse_test_seq import (
    smc_flr_sequencer_single_pulse_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   idle reads of ISOLATE_REQ_PINEN_REG and ISOLATE_REQ_SMC_REG              2
#   ISOLATE_REQ_VIS pin low, high, low again, after the legs                 4
#   two counter programmings, each two writes and two readbacks              8
#   two latch clears, each a write and at least one readback                 4
#   the bounded read during the long hold                                    1
#   both counters cleared and read back                                      4
FLR_SEQUENCER_MIN_CSR_ACCESSES = 23


@pyuvm.test()
class smc_flr_sequencer_single_pulse_test(smc_base_test):
    """Pad 62 follows the FLR cool reset open-drain; ISOLATE_REQ_VIS follows the pin."""

    required_evidence = (
        "CHK-COOL-RESET-PAD62-OPEN-DRAIN",
        "CHK-ISOLATE-VIS-LIVE-LEVELS",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_flr_sequencer_single_pulse_test_seq("smc_flr_sequencer_single_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=FLR_SEQUENCER_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{len(seq.rows)} FLR legs sampled on clk_ref_i",
        )
