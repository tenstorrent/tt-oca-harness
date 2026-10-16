# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_external_irq_pins_test - SEP external interrupt pins to PIC pending sources.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_external_irq_pins_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_external_irq_pins_test_seq import smu_sep_external_irq_pins_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_external_irq_pins_test(smu_base_test):
    """One external SEP interrupt pin at a time raises and clears its own PIC pending source."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEP-EXTIRQ-CORE-PORT",
        "CHK-SEP-EXTIRQ-FALL",
        "CHK-SEP-EXTIRQ-ONEHOT",
        "CHK-SEP-EXTIRQ-RISE",
        "CHK-SEP-EXTIRQ-WALK",
        "CHK-SEP-EXTIRQ-WIDTH",
        "CHK-SEP-EXTIRQ-ZERO",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_external_irq_pins_test SEP=1 JTAG")
        seq = smu_sep_external_irq_pins_test_seq(self)
        await seq.run()
        assert seq.done, "SEP external interrupt walk incomplete"
