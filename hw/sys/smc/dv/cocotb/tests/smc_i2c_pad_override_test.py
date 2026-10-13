# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OVRD pull control sampled on the I2C0 pads and the per-instance pull probes, and VAL."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_pad_override_test_seq import smc_i2c_pad_override_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_pad_override_test(smc_base_test):
    """Writes OVRD words on the frontdoor and logs the pad, probe and VAL levels."""

    required_evidence = (
        "CHK-I2C-OVRD-DISABLED-OBS",
        "CHK-I2C-OVRD-PULL-OBS",
        "CHK-I2C-OVRD-RELEASE-OBS",
        "CHK-I2C-OVRD-INSTANCE-ISOLATION",
        "CHK-I2C-VAL-SENSE-OBS",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_pad_override_test_seq("i2c_pad_override_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
