# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ISOLATE_REQ_PINEN_REG across a cold reset with the isolation pin high and with it low.

Source: ``hw/sys/smc/doc/clk_rst.adoc`` "Isolation Controls" and "Isolation Connections".
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_isolate_pinen_cold_test_seq import smc_isolate_pinen_cold_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor:
#   idle reads of ISOLATE_REQ_REG and ISOLATE_REQ_PINEN_REG                  2
#   PINEN set and read back                                                  2
#   readback after each of the two cold pulses and one before the second     3
#   restore write and read                                                   2
ISOLATE_PINEN_COLD_MIN_CSR_ACCESSES = 9


@pyuvm.test()
class smc_isolate_pinen_cold_test(smc_base_test):
    """PINEN[3] holds across a cold pulse with the pin high and clears across one with it low."""

    required_evidence = (
        "CHK-PINEN-CLEARS-COLD-PIN-LOW",
        "CHK-PINEN-SURVIVES-COLD-PIN-HIGH",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_isolate_pinen_cold_test_seq("smc_isolate_pinen_cold_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=ISOLATE_PINEN_COLD_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{seq.legs} cold pulses against ISOLATE_REQ_PINEN_REG",
        )
