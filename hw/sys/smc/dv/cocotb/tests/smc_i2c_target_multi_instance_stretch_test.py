# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C1/I2C2 target transmit, address mismatch and both stretch paths."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_target_multi_instance_stretch_test_seq import (
    smc_i2c_target_multi_instance_stretch_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_multi_instance_stretch_test(smc_base_test):
    """Close the target transmit, mismatch and stretch paths on I2C1 and I2C2."""

    required_evidence = (
        "CHK-I2C1-TGT-ACQ-DRAIN",
        "CHK-I2C1-TGT-ACQ-STRETCH",
        "CHK-I2C1-TGT-READ",
        "CHK-I2C1-TGT-TX-STRETCH",
        "CHK-I2C2-TGT-ACQ-DRAIN",
        "CHK-I2C2-TGT-ACQ-STRETCH",
        "CHK-I2C2-TGT-ADDR-MISMATCH",
        "CHK-I2C2-TGT-READ",
        "CHK-I2C2-TGT-TX-STRETCH",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_multi_instance_stretch_test_seq(
            "smc_i2c_target_multi_instance_stretch_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, the
            # bring-up writes for each leg, and one ACQDATA read per acquired
            # entry across two acquisition-stretch legs. Literal here, not read
            # from `seq.accesses`.
            min_csr_accesses=300,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C1/I2C2 target transmit, address mismatch and both stretch paths",
        )
