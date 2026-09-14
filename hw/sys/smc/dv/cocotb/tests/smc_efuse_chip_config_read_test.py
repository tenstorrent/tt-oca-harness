# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS eFuse-derived chip-config read test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_chip_config_read_test_seq import smc_efuse_chip_config_read_test_seq
from seq_lib.smc_efuse_vip_utils import check_efuse_otp_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_chip_config_read_test(smc_base_test):
    """Run eFuse-derived chip-config read checks."""

    required_evidence = (
        "CHK-EFUSE-BANK-AXIL-ACTIVE",
        "CHK-EFUSE-BANK-IDLE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_chip_config_read_test_seq("efuse_chip_config_read_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Backed by the positive control the sequence takes first.
        await check_efuse_otp_observability()
        # Three chip-config reset-value expectations plus the eFuse-shim
        # expectation the positive control carries.
        assert self.env.scoreboard.sys_axi_value_checks_seen >= 4, (
            "fewer than 4 SEP_IN AXI value compares reached the scoreboard: the "
            "chip-config reset-value expectations were not checked"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: 4 SEP_IN AXI chip-config CSR reads plus
            # 1 eFuse-shim positive-control read. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=5,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                "eFuse-derived chip-config version/LC/RAS surface checked, with "
                "the eFuse-bank activity positive control and idle leg"
            ),
        )
