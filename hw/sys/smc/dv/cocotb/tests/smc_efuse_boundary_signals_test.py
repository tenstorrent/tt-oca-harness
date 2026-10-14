# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse ext_boot_seq_done / fuse_reset_n interlock."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_efuse_boundary_signals_test_seq import (
    smc_efuse_boundary_signals_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_boundary_signals_test(smc_base_test):
    """Sense completes under ext_boot hold; delayed fuse_reset_n waits release."""

    required_evidence = (
        "CHK-EFUSE-BND-BASIC",
        "CHK-EFUSE-BND-HOLD",
        "CHK-EFUSE-BND-MAP",
        "CHK-EFUSE-BND-REL",
        "CHK-EFUSE-BND-STAY",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_boundary_signals_test_seq("efuse_bnd_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The sequence records each token only after that leg's compares
        # passed, so a missing token means the compare never ran or failed.
        required = (
            "CHK-EFUSE-BND-HOLD",
            "CHK-EFUSE-BND-STAY",
            "CHK-EFUSE-BND-MAP",
            "CHK-EFUSE-BND-REL",
            "CHK-EFUSE-BND-BASIC",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
