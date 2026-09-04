# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 host to I2C1 target on shared pads (+smc_i2c_shared_bus)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_rdwr_test_seq import smc_i2c_p0_rdwr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_rdwr_test(smc_base_test):
    """Commercial P0 intent: internal dual-controller write/read proof."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_rdwr_test_seq("i2c_p0_rdwr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.transfer_ok, "I2C0→I2C1 P0 transfer did not complete"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Conservative stimulus floor: 41-42 accesses observed across the
            # retained regression runs (ACQ drain polls vary with timing), so
            # the floor is set below the minimum observed. Literal here, not
            # read from `seq.accesses`.
            min_csr_accesses=33,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 host write to I2C1 target on shared pads; "
                f"ACQ_words={[hex(w) for w in seq.acq_words[:5]]} "
                f"ok={seq.transfer_ok}"
            ),
        )
