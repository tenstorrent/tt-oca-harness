# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS eFuse chip-config read proxy, standing in for raw OTP permission paths.

PROXY, not a permission/boundary test. This module runs the same
``smc_efuse_chip_config_read_test_seq`` body as ``smc_efuse_chip_config_read_test``:
four eFuse-derived chip-config reads plus the eFuse-bank positive control and
idle leg. It does NOT program a lock, drive a lifecycle transition, attempt a
denied access, or touch the raw OTP window -- the SMC CSR boundary exposes no
such surface in the OSS bench.

The residual gap -- raw OTP permission-path coverage -- is recorded under DOES
NOT DEFEND in this testcase's VPLAN entry.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_chip_config_read_test_seq import smc_efuse_chip_config_read_test_seq
from seq_lib.smc_efuse_vip_utils import check_efuse_otp_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_permission_boundary_test(smc_base_test):
    """Run eFuse-derived chip-config reads as the proxy for raw OTP permission paths."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_chip_config_read_test_seq("efuse_permission_boundary_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Backed by the positive control the sequence takes first, so the idle
        # observation is evidence rather than a warning.
        await check_efuse_otp_observability()
        # The three value expectations live in the scoreboard; require it to have
        # compared them, or a lost analysis path would skip every one and the
        # test would still pass.
        # Three chip-config reset-value expectations plus the eFuse-shim
        # expectation the positive control carries.
        assert self.env.scoreboard.sys_axi_value_checks_seen >= 4, (
            "fewer than 4 SEP_IN AXI value compares reached the scoreboard: the "
            "chip-config reset-value expectations were not checked"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed stimulus floor: 4 chip-config reads + 1 eFuse-shim
            # positive-control read. Literal here, not read from `seq.accesses`.
            min_csr_accesses=5,
            # The scoreboard's own per-bus tally, stamped by the driver that
            # completed each access, rather than `seq.accesses`, which the
            # sequence increments on dispatch regardless of what came back.
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            # This IS a proxy: it stands in for the raw OTP permission paths.
            proxy=True,
            details=(
                "PROXY for raw OTP permission paths: eFuse-derived chip-config "
                "reset-value reads plus eFuse-bank activity positive control "
                "and idle leg. No lock programmed, no lifecycle transition, no "
                "denied access, no raw OTP window touched"
            ),
        )
