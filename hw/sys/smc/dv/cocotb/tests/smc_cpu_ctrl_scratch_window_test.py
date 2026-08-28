# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU-control scratch-window depth test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_ctrl_scratch_window_test_seq import (
    smc_cpu_ctrl_scratch_window_test_seq,
)
from seq_lib.smc_cpu_vip_utils import check_cpu_bfm_observability


@pyuvm.test()
class smc_cpu_ctrl_scratch_window_test(smc_base_test):
    """Run CPU scratch-window write/readback/restore checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_scratch_window_test_seq("cpu_ctrl_scratch_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # STIMULUS DECLARATION, NOT A CHECK -- stated plainly because a
            # this number records the intended stimulus and nothing more. The
            # scoreboard evaluates `csr_accesses >= min_csr_accesses`, and
            # `csr_accesses` is `seq.accesses`, which is exactly 39 whenever the
            # sequence completes, so the comparison is `39 >= 39` on every run
            # and cannot fail ([NO-ALWAYS-PASS-CHECKER]). Making the number
            # accurate does not make it fail-capable.
            #
            # The fail-capable reachability check for this scenario is
            # `assert_all_reachable(39, ...)` in the sequence, which compares
            # the same count against the SCOREBOARD's independently observed
            # tally rather than against the sequence's own counter, and the
            # DUMMY_ROM reset/readback compares, which the scoreboard enforces.
            # Composition: 3 scratch registers x 5 + 4 DUMMY_ROM x 5 + 4
            # DUMMY_ROM_NULL reset reads = 39.
            min_csr_accesses=39,
            csr_accesses=seq.accesses,
            proxy=False,
            details="SEP_IN AXI master-BFM CPU scratch write/read/restore checked",
        )
