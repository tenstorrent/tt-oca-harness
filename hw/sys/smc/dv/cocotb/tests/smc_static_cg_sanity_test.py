# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_002 ANCHOR: smc_static_cg_sanity_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_static_cg_sanity_test_seq import smc_static_cg_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_static_cg_sanity_test(smc_base_test):
    """P0 bring-up LIVE gate-disabled free-run plus the P1 module-gating thresholds."""

    required_evidence = (
        "CHK-DMA-GATE-DISABLED-FREE-RUN",
        "CHK-ENABLE-THRESHOLD",
        "CHK-MODULE-GATING",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-ZEROER-GATE-DISABLED-FREE-RUN",
    )
    min_evidence = 6

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_static_cg_sanity_test_seq("static_cg_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-DMA-GATE-DISABLED-FREE-RUN",
            "CHK-ZEROER-GATE-DISABLED-FREE-RUN",
            "CHK-NONVAC",
            # P1 tokens (see smc_static_cg_sanity_test_seq).
            "CHK-MODULE-GATING",
            "CHK-ENABLE-THRESHOLD",
            "CHK-TIMEOUT-PATHS",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            # Structural CSR-access floor for this scenario's stimulus, written
            # out here as an independent constant rather than read back from
            # `seq.accesses`. `body()` is straight-line and issues exactly 52
            # compulsory accesses: 6 output-fabric pass-all writes + 4x3
            # `_program_cg` + 2x14 `_program_dma_descriptors` + 2 DONE-baseline
            # reads + 2 `_start_dma` reads + at least 2 `_wait_dma_done` polls.
            # The completion polls are the only variable part and they can only
            # add, so a sequence that stops short of the declared stimulus
            # fails the record.
            min_csr_accesses=52,
            csr_accesses=seq.accesses,
            # Two JTAG-AXI payload writes (`_write_bytes` in the sequence body) seed
            # the DMA source and destination. Declaring both the floor and the
            # exact count makes the scoreboard compare its own per-bus tally
            # against a number this call site did not measure.
            min_fabric_accesses=2,
            fabric_accesses=2,
            fabric_access_label="JTAG AXI DMA payload write",
            # No bounded-CSR helper runs on this path (`csr_read_bounded` and
            # `csr_short_timeout` are the only two that can move the counter),
            # so there is no measured timeout figure to report and the record
            # prints `n/a` rather than a manufactured 0.
            timeouts=None,
            proxy=False,
            details=(
                f"STATIC_CG P0+P1 LIVE: measured={seq.measured} "
                f"cells={seq.required_cells_hit}. Enable-threshold coverage is "
                f"hysteresis 9 and 63 only; the CG_HYSTERESIS 0..8 band is "
                f"not exercised and is not claimed here."
            ),
        )
