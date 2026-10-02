# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Component address-map region decode from the SEP_IN AXI port.

Closes SMC-MAP-DECODE.S1, SMC-MAP-DECODE.S2, SMC-MAP-SPARE.S3, SMC-MAP-IFSTD.S2,
SMC-EXTWIN-MAND.S1 and SMC-EXTWIN-SUPP.S1 (memmap.adoc: Address Space
Organization, SMC Component Address Map, AXI-Lite External Window, Register
Interface Standards, Spare SMC Register Blocks) for every region an inbound
master can reach: each region is read at a base-side register and at the last
register of its extent against the generated map's reset value or a
co-resident write/readback pattern, three addresses no block declares must be
answered DECERR by the fabric error slave, and the external window is proven
at its AXI-Lite port. The PLIC, CLINT/BEU, debug and remap regions are named
in the log and left open because SEP_IN cannot reach them in this bench.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_address_map_region_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_address_map_region_decode_test_seq import (
    EXPECTED_VALUE_CHECKS,
    smc_address_map_region_decode_test_seq,
)
from smc_base_test import smc_base_test

# Reads plus writes the sequence issues; a literal, not read from the sequence.
EXPECTED_ACCESSES = 102


@pyuvm.test()
class smc_address_map_region_decode_test(smc_base_test):
    """Base/top/beyond decode of every SEP_IN-reachable address-map region."""

    required_evidence = (
        "CHK-ADDRESS-MAP-REGION",
        "CHK-ADDRESS-MAP-REGION-DECODE",
        "CHK-ADDRESS-MAP-REGION-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_address_map_region_decode_test_seq("address_map_region_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(EXPECTED_ACCESSES, "ADDRESS_MAP_REGION_DECODE")
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-ADDRESS-MAP-REGION-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d, "
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
                f"address-map region decode over SEP_IN AXI: {seq.accesses} accesses, "
                f"{value_compares} exact-value compares, {len(seq.cells)} cells closed, "
                f"{len(seq.unreachable)} left open"
            ),
        )
