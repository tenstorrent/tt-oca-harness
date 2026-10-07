# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU-control scratch-window depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cpu_ctrl_scratch_window_test_seq import (
    DUMMY_ROM_RESETS,
    smc_cpu_ctrl_scratch_window_test_seq,
)
from seq_lib.smc_cpu_vip_utils import check_cpu_bfm_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_scratch_window_test(smc_base_test):
    """Run CPU scratch-window write/readback/restore checks."""

    required_evidence = (
        "CHK-CPU-BFM-OBSERVABILITY",
        "CHK-CPU-CTRL-DUMMY-ROM",
        "CHK-CPU-CTRL-SCRATCH",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_scratch_window_test_seq("cpu_ctrl_scratch_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        # `record_protocol_vip` requires a scenario-recorded item to declare its
        # stimulus floor; the sequence pins `seq.accesses` to 39 itself, so this
        # record's fail-capability is the byte golden below.
        #
        # `expected_bytes` is DUMMY_ROM_0's reset word read by symbol from the
        # generated `cpu_ctrl.h`; `observed_bytes` is the word the DUT returned
        # from that register after the write probe was restored. The scoreboard
        # compares them, so a register that does not come back to its reset
        # fails the record itself.
        assert seq.rom0_restored is not None, "DUMMY_ROM_0 restore readback missing"
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Stimulus composition: 3 scratch registers x 5 + 4 DUMMY_ROM x 5
            # + 4 DUMMY_ROM_NULL reset reads = 39.
            min_csr_accesses=39,
            csr_accesses=seq.accesses,
            proxy=False,
            expected_bytes=DUMMY_ROM_RESETS[0].to_bytes(8, "big"),
            observed_bytes=seq.rom0_restored.to_bytes(8, "big"),
            details=(
                "SEP_IN AXI master-BFM CPU scratch write/read/restore checked "
                f"({len(seq.scratch_proven)} SCRATCH registers) plus the "
                f"DUMMY_ROM reset/probe/restore sweep"
            ),
        )
