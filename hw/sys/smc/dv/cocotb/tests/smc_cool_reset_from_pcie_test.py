# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PCIe cfg_flr_pf_active_i cool-reset. Not rst_cool_ni."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cool_reset_from_pcie_test_seq import (
    smc_cool_reset_from_pcie_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cool_reset_from_pcie_test(smc_base_test):
    """FLR pin → skip_mem_repair / rst_cool_no / isolate_req_o."""

    required_evidence = (
        "CHK-FLR-BASIC",
        "CHK-FLR-COOL",
        "CHK-FLR-IDLE",
        "CHK-FLR-ISO",
        "CHK-FLR-WARM",
        "CHK-FLR-ZERO-CNT",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_from_pcie_test_seq("flr_pcie_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.zero_cnt_ok and seq.cool_ok and seq.iso_ok, (
            f"FLR incomplete zero={seq.zero_cnt_ok} cool={seq.cool_ok} iso={seq.iso_ok}"
        )
