# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS P1 coverage-gap: EFUSE_INTERFACE + SHIM_CTRL probe."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_shim_ctrl_test_seq import smc_efuse_shim_ctrl_test_seq


@pyuvm.test()
class smc_efuse_shim_ctrl_test(smc_base_test):
    """P1 coverage-gap depth: EFUSE_INTERFACE + SHIM_CTRL probe."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_shim_ctrl_test_seq("smc_efuse_shim_ctrl_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: 2 SEP_IN AXI EFUSE_INTERFACE/SHIM_CTRL
            # probe accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=2,
            csr_accesses=seq.accesses,
            proxy=False,
            details="P1 coverage-gap: EFUSE_INTERFACE + SHIM_CTRL probe",
        )
