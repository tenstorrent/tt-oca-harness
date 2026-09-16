# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse ext_boot_seq_done / fuse_reset_n interlock (G6)."""

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
        # Gate on the sequence's own recorded evidence tokens, not on relayed
        # booleans: `hold_ok`/`map_ok`/`release_ok` are literal `True`
        # assignments on lines unreachable unless the real compares already
        # passed, so asserting on them resembles a final gate while carrying
        # no fail capability of its own ([NO-DUMMY-DEAD-CODE]). Each token below
        # is added only after that leg's compares passed.
        required = (
            "CHK-EFUSE-BND-HOLD",
            "CHK-EFUSE-BND-STAY",
            "CHK-EFUSE-BND-MAP",
            "CHK-EFUSE-BND-REL",
            "CHK-EFUSE-BND-BASIC",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
