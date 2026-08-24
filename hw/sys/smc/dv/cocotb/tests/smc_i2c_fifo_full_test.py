# SPDX-License-Identifier: Apache-2.0
"""CSR-only FMT/TX full and RX/ACQ empty."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_fifo_full_test_seq import smc_i2c_fifo_full_test_seq


@pyuvm.test()
class smc_i2c_fifo_full_test(smc_base_test):
    """FMT/TX full+empty and RX/ACQ empty STATUS (CSR-only)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_fifo_full_test_seq("i2c_fifo_full_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fmt_ok and seq.rx_ok and seq.tx_ok and seq.acq_ok, (
            f"fifo_full incomplete fmt={seq.fmt_ok} rx={seq.rx_ok} "
            f"tx={seq.tx_ok} acq={seq.acq_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"FMT/TX full+empty RX/ACQ empty "
                f"fmt={seq.fmt_ok} tx={seq.tx_ok}"
            ),
        )
