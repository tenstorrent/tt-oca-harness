# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A read the I2C peripheral has accepted completes once when its clock-gate enable is set.

Source: ``hw/sys/smc/doc/clk_rst.adoc`` "Subsystem Controls and Clock Gating".
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_clock_gate_inflight_completes_test_seq import (
    _OFFSETS,
    smc_clock_gate_inflight_completes_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor on SEP_IN:
#   CLOCK_GATE_CONTROL saved, the ungated I2C read                           2
#   arm leg: enable set, one SLVERR poll, the clear and its readback, one
#   OKAY poll                                                                5
#   per trial: the enable write, at least one SLVERR poll, the clear write
#   and its readback, at least one OKAY poll                                 5
#   CLOCK_GATE_CONTROL restored and read back                                2
CLOCK_GATE_INFLIGHT_MIN_CSR_ACCESSES = 9 + 5 * len(_OFFSETS)


@pyuvm.test()
class smc_clock_gate_inflight_completes_test(smc_base_test):
    """Sweep a JTAG I2C read against the I2C_CG_EN write; accepted reads complete OKAY."""

    required_evidence = (
        "CHK-ACCEPTED-ACCESS-COMPLETES-ACROSS-GATE",
        "CHK-CG-INFLIGHT-ARM",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clock_gate_inflight_completes_test_seq(
            "smc_clock_gate_inflight_completes_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=CLOCK_GATE_INFLIGHT_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"{len(seq.trials)} launch offsets, {seq.jtag_accesses} JTAG reads",
        )
