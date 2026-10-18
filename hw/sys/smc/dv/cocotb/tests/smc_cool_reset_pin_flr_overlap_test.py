# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The rst_cool_ni pin overlapping the FLR cool-reset sequence."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cool_reset_pin_flr_overlap_test_seq import (
    smc_cool_reset_pin_flr_overlap_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor: two counter pairs written and read back, and a latch clear and at
# least one poll after each of the five FLR runs, then the final hold counter clear and readback.
COOL_RESET_PIN_FLR_OVERLAP_MIN_CSR_ACCESSES = 12


@pyuvm.test()
class smc_cool_reset_pin_flr_overlap_test(smc_base_test):
    """The pin and the FLR sequence combine into primary reset without changing the FLR hold."""

    required_evidence = (
        "CHK-COOLRST-BP-LEVEL",
        "CHK-COOLRST-COLD-STABLE",
        "CHK-COOLRST-COLLISION-HOLD",
        "CHK-COOLRST-COLLISION-PRE",
        "CHK-COOLRST-FLR-ALONE-PRIMARY",
        "CHK-COOLRST-FLR-HOLD-COUNT",
        "CHK-COOLRST-FLR-PRE-COUNT",
        "CHK-COOLRST-HOLD-INVARIANT",
        "CHK-COOLRST-PIN-ALONE-PRIMARY",
        "CHK-COOLRST-PIN-EARLY-RELEASE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_pin_flr_overlap_test_seq("smc_cool_reset_pin_flr_overlap_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.overlap_ok, "rst_cool_ni and FLR overlap scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=COOL_RESET_PIN_FLR_OVERLAP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="rst_cool_ni and FLR cool-reset overlap",
        )
