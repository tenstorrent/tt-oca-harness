# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PLIC, CLINT and bus-error-unit decode from SEP_IN with a widened REGION_SIZE.

Closes SMC-MAP-DECODE.S1 (plic-region, timer-buserror-region),
SMC-INT-PLICID.S3, SMC-CLINT.S1, SMC-BEU.S1, SMC-PERIPH-DECODE.S2
(beu-instance-3) and SMC-PLIC-INIT.S1 (memmap.adoc: SMC Address Space Layout,
SMC Component Address Map; interrupts.adoc: Interrupt Controller Address Map,
PLIC initialisation; fabric.adoc: Local and Remote Resource Access). What the
PLIC address answers above the 16 MiB reset aperture is reported, not claimed
(the specification leaves it undefined); REGION_SIZE is then programmed to
256 MiB -- the smallest legal power of two that contains the whole documented
map -- and the three windows are driven at their base, their spec top and one
word beyond with co-resident patterns that fail on an alias. REGION_SIZE is
restored before the test ends.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_region_size_plic_clint_beu_decode_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_region_size_plic_clint_beu_decode_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_region_size_plic_clint_beu_decode_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_region_size_plic_clint_beu_decode_test(smc_base_test):
    """PLIC / CLINT / BEU decode above the reset aperture, and the fold below it."""

    required_evidence = (
        "CHK-REGION-SIZE-PLIC-CLINT-BEU",
        "CHK-REGION-SIZE-PLIC-CLINT-BEU-DECODE",
        "CHK-REGION-SIZE-PLIC-CLINT-BEU-FLOOR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_region_size_plic_clint_beu_decode_test_seq("region_size_plic_clint_beu_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        cocotb.log.info(
            "CHK-REGION-SIZE-PLIC-CLINT-BEU-FLOOR: scoreboard sys_axi_value_checks_seen=%d >= %d, "
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
                f"PLIC / CLINT / BEU decode over SEP_IN AXI with REGION_SIZE widened to 256 MiB: "
                f"{seq.accesses} accesses, {value_compares} exact-value compares, "
                f"{len(seq.cells)} cells closed"
            ),
        )
