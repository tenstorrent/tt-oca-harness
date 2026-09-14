# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 FMT_THRESHOLD after FMT FIFO reset."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_p0_cfifo_test_seq import smc_i2c_p0_cfifo_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p0_cfifo_test(smc_base_test):
    """Controller FMT FIFO empty-threshold interrupt."""

    required_evidence = ("CHK-I2C-P0-CFIFO",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_cfifo_test_seq("i2c_p0_cfifo_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fmt_ok, "FMT_THRESHOLD not observed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the FMT_THRESHOLD status poll is timing-dependent.
            min_csr_accesses=7,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"FMT_THRESHOLD fmt_ok={seq.fmt_ok}",
        )
