# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_AXI hang detector threshold updates, threshold 0x1000 and small values on live stalls."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_sep_threshold_test_seq import smc_hang_sep_threshold_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_sep_threshold_test(smc_base_test):
    """A threshold written during a held SEP_IN read, then new thresholds on later stalls."""

    required_evidence = (
        "CHK-THR-RAISE-DURING",
        "CHK-THR-LOWER-DURING",
        "CHK-THR-AFTER-COMPLETION",
        "CHK-THR-AFTER-ENABLE-CLEAR-LOG",
        "CHK-THR-DEFAULT-BEYOND",
        "CHK-THR-DEFAULT-EXACT-LOG",
        "CHK-THR-SMALL-RISE",
        "CHK-THR-SMALL-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_sep_threshold_test_seq("hang_sep_threshold_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 8, f"phases {seq.phases}, want 8"
        assert seq.accesses >= 40, f"only {seq.accesses} SEP_IN accesses issued, want >= 40"
