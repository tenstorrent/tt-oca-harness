# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C DUT-host protocol test (U4-2)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_master_target_test_seq import smc_i2c_master_target_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_master_target_test(smc_base_test):
    """U4-2: OVRD + DUT host write + SMBus PEC write + ARA read on pads."""

    required_evidence = (
        "CHK-I2C0-HOST-WRITE",
        "CHK-I2C0-OVRD-PAD",
        "CHK-I2C0-SMBUS-ARA",
        "CHK-I2C0-SMBUS-PEC",
        "CHK-I2C0-U4-2-SMBUS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_master_target_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dut_host_write_ok and seq.dut_smbus_pec_ok and seq.dut_smbus_ara_ok, (
            "U4-2 SMBus gates failed: "
            f"write={seq.dut_host_write_ok} pec={seq.dut_smbus_pec_ok} "
            f"ara={seq.dut_smbus_ara_ok}"
        )
        # Byte verdict: owned solely by the sequence, where the bytes are
        # measured. `assert got == bytes([_I2C_WRITE_BYTE])` (EEPROM VIP
        # mem[0x10]) and `assert rdata == _SMBUS_ARA_REPLY` (I2C0_RDATA from the
        # ARA responder) both run *before* the sequence returns, so a test-level
        # `obs == exp` compare here would sit downstream of those asserts on the
        # same constants and could not fail on any RTL ([NO-DUMMY-DEAD-CODE]).
        # The measured values are reported below (and in `details=` on the
        # protocol-VIP record) so the kept log carries what was read.
        obs = seq.obs_host_write + seq.obs_smbus_ara
        self.logger.info(
            "I2C U4-2 measured bytes 0x%s (EEPROM VIP mem[0x10]=0x%s + "
            "I2C0_RDATA=0x%s); the byte verdict is owned by "
            "CHK-I2C0-HOST-WRITE / CHK-I2C0-SMBUS-ARA in the sequence",
            obs.hex(),
            seq.obs_host_write.hex(),
            seq.obs_smbus_ara.hex(),
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the I2C HOSTIDLE/RXEMPTY polls are timing-dependent.
            min_csr_accesses=50,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 OVRD + DUT host write 0xAB@0x10 + SMBus PEC "
                f"0xA5@0x20 + ARA@0x0C (pec={seq.dut_smbus_pec_ok} "
                f"ara={seq.dut_smbus_ara_ok}); measured bytes 0x{obs.hex()} "
                f"verdicted in-sequence"
            ),
        )
