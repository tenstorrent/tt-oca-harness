# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Local alias base, alias-remap ends, spare blocks and both mailbox halves over SEP_IN.

Closes SMC-FAB-ALIAS.S1 (alias-region-0-configured, alias-region-7-configured),
SMC-FAB-ALIAS.S5 (local-alias-base-reaches-local-resource, transparent-at-reset),
SMC-MAP-SPARE.S1 (chip-config-write), SMC-MAP-SPARE.S2 (scratch-all-ones) and
SMC-MBX.S1 (inbound/outbound pair 0 and 31) from fabric.adoc (Local and Remote
Resource Access) and memmap.adoc (SMC Component Address Map, Spare SMC Register
Blocks). The run's first access is a read at LOCAL_BASE taken before any
alias-remap write, so it carries the transparent-at-reset claim; the alias
regions, the spare blocks and the four end mailbox halves are then proven with
co-resident patterns that fail on an aliased decode, and everything is restored
to its generated reset.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_alias_remap_spare_block_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_alias_remap_spare_block_decode_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_alias_remap_spare_block_decode_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_alias_remap_spare_block_decode_test(smc_base_test):
    """LOCAL_BASE, the alias-remap array ends, the spare blocks and the mailbox halves."""

    required_evidence = (
        "CHK-ALIAS-REMAP-SPARE-BLOCK",
        "CHK-ALIAS-REMAP-SPARE-BLOCK-DECODE",
        "CHK-ALIAS-REMAP-SPARE-BLOCK-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_alias_remap_spare_block_decode_test_seq("alias_remap_spare_block_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-ALIAS-REMAP-SPARE-BLOCK-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d, "
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
                f"alias-remap, spare-block and mailbox-half decode over SEP_IN AXI: "
                f"{seq.accesses} accesses, {value_compares} exact-value compares, "
                f"{len(seq.cells)} cells closed"
            ),
        )
