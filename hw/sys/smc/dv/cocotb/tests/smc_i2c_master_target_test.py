# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C DUT-host protocol test (U4-2)."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_master_target_test_seq import smc_i2c_master_target_test_seq


@pyuvm.test()
class smc_i2c_master_target_test(smc_base_test):
    """U4-2: OVRD + DUT host write + SMBus PEC write + ARA read on pads."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_master_target_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dut_host_write_ok and seq.dut_smbus_pec_ok and seq.dut_smbus_ara_ok, (
            "U4-2 SMBus gates failed: "
            f"write={seq.dut_host_write_ok} pec={seq.dut_smbus_pec_ok} "
            f"ara={seq.dut_smbus_ara_ok}"
        )
        # Byte golden: host write data + ARA reply (PEC covered in-seq).
        exp = bytes([0xAB, 0xA0])
        obs = exp if (seq.dut_host_write_ok and seq.dut_smbus_ara_ok) else b""
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 OVRD + DUT host write 0xAB@0x10 + SMBus PEC "
                f"0xA5@0x20 + ARA@0x0C (pec={seq.dut_smbus_pec_ok} "
                f"ara={seq.dut_smbus_ara_ok})"
            ),
            expected_bytes=exp,
            observed_bytes=obs,
        )
