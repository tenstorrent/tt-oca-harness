# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every DMA stream bank decodes regardless of the configured stream count.

Closes SMC-DMA-STREAM-RSVD.S4 (dma.adoc: Stream Support, Detailed Register
Map): STATUS_0..15, DONE_0..15 and NEXT_ID_1..15 are read over SEP_IN and each
completes OKAY with the value the specification gives a reserved bank, a
write/readback in the same block proves the register file is answering, and
``tb_dma_busy`` sampled on every clock edge proves no reserved NEXT_ID read
launched a transfer.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_dma_reserved_stream_banks_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dma_reserved_stream_banks_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_dma_reserved_stream_banks_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dma_reserved_stream_banks_test(smc_base_test):
    """Sixteen-bank DMA stream register decode with a single functional stream."""

    required_evidence = (
        "CHK-DMA-RESERVED-STREAM-BANKS",
        "CHK-DMA-STREAM-BANKS",
        "CHK-DMA-STREAM-BANKS-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_reserved_stream_banks_test_seq("dma_reserved_stream_banks_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-DMA-STREAM-BANKS-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d",
            value_compares,
            EXPECTED_VALUE_CHECKS,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_ACCESSES,
            proxy=False,
            details=(
                f"16 DMA stream banks decoded over SEP_IN AXI: {seq.accesses} accesses, "
                f"{value_compares} exact-value compares, tb_dma_busy high "
                f"{seq.busy_cycles}/{seq.sampled_cycles} cycles"
            ),
        )
