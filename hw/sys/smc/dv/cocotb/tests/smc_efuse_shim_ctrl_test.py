# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: EFUSE_INTERFACE + SHIM_CTRL probe."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_shim_ctrl_test_seq import smc_efuse_shim_ctrl_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_shim_ctrl_test(smc_base_test):
    """P1 coverage-gap depth: EFUSE_INTERFACE + SHIM_CTRL probe."""

    required_evidence = ("CHK-EFUSE-SHIM-CTRL",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_shim_ctrl_test_seq("smc_efuse_shim_ctrl_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Both probes are strict reads and the SHIM_CTRL one carries an expected
        # value, so require the scoreboard to have compared it. Without this the
        # value check could silently not run and the test would still pass.
        assert self.env.scoreboard.sys_axi_value_checks_seen >= 1, (
            "no SEP_IN AXI value compare reached the scoreboard: the "
            "EFUSE_SHIM_CTRL EFUSE_BANK_INIT_TIME expectation was never checked"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: 2 SEP_IN AXI EFUSE_INTERFACE/SHIM_CTRL
            # probe accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=2,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                "P1 coverage-gap: EFUSE_INTERFACE_CTRL_STATUS and EFUSE_SHIM_CTRL "
                "EFUSE_BANK_INIT_TIME both read OKAY, the latter compared against "
                "its generated reset value"
            ),
        )
