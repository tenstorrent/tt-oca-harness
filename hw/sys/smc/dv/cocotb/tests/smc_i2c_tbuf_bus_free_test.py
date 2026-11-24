# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C0 bus-free time before a queued START follows TIMING1.T_R + TIMING2.TSU_STA + 7.

`i2c.rdl` TIMING4.T_BUF: outside multi-controller monitoring, with `TIMING3.THD_DAT` of 2 or more
and the next FMT entry already queued, "the START follows the STOP's SDA rise after
`TIMING1.T_R + TIMING2.TSU_STA + 7` cycles whatever this field holds". With `THD_DAT` 25 to 32 and
transfers queued behind the STOP, every bus-free time, from the STOP SDA rise to the START SDA
fall of the transfer queued behind it, equals `T_R + TSU_STA + 7` in both runs of the `T_BUF`
pair, and does not move when `T_BUF` moves. The `smc_i2c_timing_set_rand_test` draw runs first:
its six graded pairs, in order, are the arm leg that shows the measurer follows a field change
before the `T_BUF` pair is graded.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_timing_set_rand_test_seq import smc_i2c_timing_set_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_tbuf_bus_free_test(smc_base_test):
    """The I2C timing-set draw with the queued-START bus-free time of the T_BUF pair graded."""

    required_evidence = (
        "CHK-ITS-COMPLETE",
        "CHK-ITS-MIN-THIGH",
        "CHK-ITS-ORDER",
        "CHK-ITS-TBUF-BUS-FREE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_timing_set_rand_test_seq(
            "smc_i2c_timing_set_rand_test_seq",
            seed=self.random_seed(),
            grade_tbuf_bus_free=True,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "I2C timing set sequence did not complete"
