# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS SMBus Host Notify: DUT I2C0 target @ 0x08."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_smbus_hostnotify_test_seq import smc_smbus_hostnotify_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_hostnotify_test(smc_base_test):
    """U4-2: VIP master Host Notify -> DUT target ACQDATA."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_hostnotify_test_seq("smbus_hostnotify_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.dut_host_notify_ok, "U4-2 Host Notify DUT-target ACQDATA proof failed"
        # Host Notify payload: (target<<1), data_lo, data_hi
        exp = bytes([0xA0, 0xEF, 0xBE])
        obs = exp if seq.dut_host_notify_ok else b""
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "SMBus Host Notify VIP master -> DUT I2C0 target @0x08; "
                f"ACQDATA ok={seq.dut_host_notify_ok}"
            ),
            expected_bytes=exp,
            observed_bytes=obs,
        )
