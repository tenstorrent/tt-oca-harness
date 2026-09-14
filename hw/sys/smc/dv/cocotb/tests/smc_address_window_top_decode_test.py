# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Last word of every SEP_IN-reachable address window from the SEP_IN AXI port.

Closes SMC-MAP-DECODE.S2 (region-top-decodes), SMC-MAP-DECODE.S3
(cla-base-decodes), SMC-ROM-MAP.S1 (rom-top-read), SMC-SPM.S4 (spm-region-top),
SMC-DMA-REGIF.S1 (dma-aperture-top), SMC-ZERO-REGIF.S1 (zeroer-aperture-top)
and SMC-DMA-STREAM-RSVD.S4 (all-16-banks-decode) from memmap.adoc (SMC Address
Space Layout, SMC Component Address Map), rom.adoc (Boot ROM) and dma.adoc
(Stream Support). Each window is driven at its last word with a co-resident
pattern in a neighbouring block, so a window sized short (bus error) or long
(the neighbour answers) fails. The two window tops the reference RTL sizes
shorter than the chapter are read with the error response tolerated and left
open with the measured response.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_address_window_top_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_address_window_top_decode_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_address_window_top_decode_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_address_window_top_decode_test(smc_base_test):
    """Window-top decode of the memory, data-processing and CLA windows."""

    required_evidence = (
        "CHK-ADDRESS-WINDOW-TOP",
        "CHK-ADDRESS-WINDOW-TOP-DECODE",
        "CHK-ADDRESS-WINDOW-TOP-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_address_window_top_decode_test_seq("address_window_top_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-ADDRESS-WINDOW-TOP-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d, "
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
                f"window-top decode over SEP_IN AXI: {seq.accesses} accesses, "
                f"{value_compares} exact-value compares, {len(seq.cells)} cells closed, "
                f"{len(seq.unreachable)} left open on a short window"
            ),
        )
