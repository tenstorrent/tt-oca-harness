# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine INTR_ENABLE output-mask reproducer.

EXPECTED TO FAIL against current RTL. Enrolled in the `rtl_issue` group only --
no `ci` tag, not in `smoke`. Its purpose is to hold the evidence in a runnable
form; when the RTL is fixed it should move into the `uart` group.

Same defect as #1602 in a different IP: the interrupt enable gates the set path
instead of masking the output. log_engine.rdl:159-161 records the intended
`hwenable` binding as commented out.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_intr_mask_test_seq import (
    smc_log_engine_intr_mask_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_intr_mask_test(smc_base_test):
    """INTR_ENABLE must mask the log-engine interrupt output, not its set path."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_intr_mask_test_seq("log_engine_intr_mask_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached.
        required = (
            "CHK-LOG-ENGINE-INTR-MASK-ARM",
            "CHK-LOG-ENGINE-INTR-MASK-DEASSERT",
            "CHK-LOG-ENGINE-INTR-MASK-LATCH",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
