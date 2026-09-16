# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 NACK vs pad VIP; I2C1 allow-path needs +smc_i2c_shared_bus."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_nack_test_seq import smc_i2c_p0_nack_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_nack_test(smc_base_test):
    """Commercial P0 NACK: allow-path + address NACK + data NACK."""

    required_evidence = (
        "CHK-I2C-P0-NACK-ALLOW",
        "CHK-I2C-P0-NACK-TC1",
        "CHK-I2C-P0-NACK-TC2",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_nack_test_seq("i2c_p0_nack_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.allow_ok and seq.tc1_ok and seq.tc2_ok, (
            f"I2C P0 NACK incomplete: allow={seq.allow_ok} tc1={seq.tc1_ok} tc2={seq.tc2_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the NACK status polls are timing-dependent.
            min_csr_accesses=38,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 NACK proof: allow@0x20 + addr-NACK@0x10 + data-NACK@0x10; "
                f"allow={seq.allow_ok} tc1={seq.tc1_ok} tc2={seq.tc2_ok}"
            ),
        )
