# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS CPU sanity master-BFM substitute test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_ctrl_map_depth_test_seq import smc_cpu_ctrl_map_depth_test_seq
from seq_lib.smc_cpu_vip_utils import (
    check_cpu_bfm_observability,
    check_cpu_firmware_boot_contract,
)


@pyuvm.test()
class smc_cpu_sanity_test(smc_base_test):
    """Run CPU-control CSR map coverage and optional firmware boot contract."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_map_depth_test_seq("cpu_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_cpu_bfm_observability()
        boot = await check_cpu_firmware_boot_contract(seq, require_image=False)
        boot_checked = bool(boot["boot_checked"])
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=not boot_checked,
            details=(
                "CPU firmware boot PASS contract checked"
                if boot_checked else
                f"CPU firmware boot infra armed but not promoted ({boot['reason']})"
            ),
        )
