# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 host alternating write/read to I2C1 target."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_conti_test_seq import smc_i2c_p0_conti_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_conti_test(smc_base_test):
    """Alternating I2C write/read pairs on shared pads."""

    required_evidence = (
        "CHK-I2C-P0-CONTI",
        "CHK-I2C-P0-CONTI-P0",
        "CHK-I2C-P0-CONTI-P1",
        "CHK-I2C-P0-CONTI-P2",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_conti_test_seq("i2c_p0_conti_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pairs_ok == 3, f"expected 3 pairs got {seq.pairs_ok}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the I2C status polls are timing-dependent.
            min_csr_accesses=80,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"alternating pairs_ok={seq.pairs_ok}",
        )
