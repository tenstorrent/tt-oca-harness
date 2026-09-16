# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C INTR_ENABLE output-mask reproducer.

Fails against the RTL as shipped: the interrupt enable gates the set path
instead of masking the output, so an interrupt that arrives while disabled
never latches. gpio.sv and log_engine.sv share the same shape. Enrolled in the
`rtl_issue` group.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_intr_mask_test_seq import smc_i2c_intr_mask_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_intr_mask_test(smc_base_test):
    """INTR_ENABLE must mask the I2C interrupt output, not its set path."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_intr_mask_test_seq("i2c_intr_mask_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached.
        required = (
            "CHK-I2C-INTR-MASK-ARM",
            "CHK-I2C-INTR-MASK-DEASSERT",
            "CHK-I2C-INTR-MASK-LATCH",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
