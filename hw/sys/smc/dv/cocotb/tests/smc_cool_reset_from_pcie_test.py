# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PCIe cfg_flr_pf_active_i cool-reset. Not rst_cool_ni."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_cool_reset_from_pcie_test_seq import (
    smc_cool_reset_from_pcie_test_seq,
)


@pyuvm.test()
class smc_cool_reset_from_pcie_test(smc_base_test):
    """FLR pin → skip_mem_repair / rst_cool_no / isolate_req_o."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_from_pcie_test_seq("flr_pcie_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.zero_cnt_ok and seq.cool_ok and seq.iso_ok, (
            f"FLR incomplete zero={seq.zero_cnt_ok} "
            f"cool={seq.cool_ok} iso={seq.iso_ok}"
        )
