# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Peripheral block and instance-stride decode from the SEP_IN AXI port.

Closes SMC-PERIPH-DECODE.S1, SMC-PERIPH-DECODE.S2, SMC-PERIPH-PARAM.S3,
SMC-LOGENG.S1, SMC-EXTWIN-MAND.S4 and SMC-PVT.S1 (periphs.adoc: SMC
Peripheral Summary, SMC Peripheral Parameter Overrides; memmap.adoc: SMC
Component Address Map, AXI-Lite External Window - Mandatory Region): every
peripheral block reads a register with a non-zero generated reset, the six I3C
windows, the 65 GPIO interfaces, the 32 mailbox pairs and the four log engines
are proven at their first and last instance by distinct co-resident
write/readback patterns, and the PVT wrapper is proven at the adopter external
AXI-Lite port. The DTP control window (idle response in this bench) and the
bus error units (behind the local-fabric address fold) are left open.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_peripheral_instance_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_peripheral_instance_decode_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_peripheral_instance_decode_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_peripheral_instance_decode_test(smc_base_test):
    """Block decode and first/last-instance decode of every SMC peripheral."""

    required_evidence = (
        "CHK-PERIPHERAL-INSTANCE",
        "CHK-PERIPHERAL-INSTANCE-DECODE",
        "CHK-PERIPHERAL-INSTANCE-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_peripheral_instance_decode_test_seq("peripheral_instance_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-PERIPHERAL-INSTANCE-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d, "
            "accesses=%d",
            value_compares,
            EXPECTED_VALUE_CHECKS,
            seq.accesses,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_ACCESSES,
            proxy=False,
            details=(
                f"peripheral block and instance decode over SEP_IN AXI: {seq.accesses} accesses, "
                f"{value_compares} exact-value compares, {len(seq.cells)} cells closed, "
                f"{len(seq.unreachable)} left open"
            ),
        )
