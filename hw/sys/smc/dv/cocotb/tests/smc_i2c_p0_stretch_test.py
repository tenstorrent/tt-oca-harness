# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target clock-stretch; I2C1 host waits."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_stretch_test_seq import smc_i2c_p0_stretch_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_stretch_test(smc_base_test):
    """I2C0 target TX clock stretch and recovery on the shared I2C pads: an I2C1
    host READ stalls on the target's TX_PENDING until TXDATA is supplied, then
    completes with that byte and returns to host idle."""

    required_evidence = (
        "CHK-I2C-P0-HOST-SETTLED",
        "CHK-I2C-P0-STRETCH",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_stretch_test_seq("i2c_p0_stretch_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.stretch_ok and seq.read_ok, (
            f"stretch incomplete stretch={seq.stretch_ok} read={seq.read_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # The straight-line count the body must reach: every unconditional
            # access plus one iteration of each of the three polling loops
            # (TX_PENDING, RX_STATUS, HOST_IDLE); anything above it is poll
            # iterations that vary with timing.
            min_csr_accesses=30,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"I2C0 target stretched TX_PENDING until the host read it back; "
                f"host received 0x{seq.rx_byte:02X} over {seq.accesses} accesses"
            ),
        )
