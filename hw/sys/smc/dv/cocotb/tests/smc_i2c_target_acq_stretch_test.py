# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target clock stretch on a full acquisition FIFO."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_target_acq_stretch_test_seq import smc_i2c_target_acq_stretch_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_acq_stretch_test(smc_base_test):
    """Fill the I2C0 target acquisition FIFO and prove the target holds SCL low."""

    required_evidence = (
        "CHK-I2C-TGT-ACQ-DRAIN",
        "CHK-I2C-TGT-ACQ-STRETCH",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_acq_stretch_test_seq("smc_i2c_target_acq_stretch_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the pad-proof and target bring-up CSR
            # writes, plus one ACQDATA read per acquired entry. Literal here,
            # not read from `seq.accesses`.
            min_csr_accesses=120,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C0 target acquisition-FIFO clock stretch driven from the pads",
        )
