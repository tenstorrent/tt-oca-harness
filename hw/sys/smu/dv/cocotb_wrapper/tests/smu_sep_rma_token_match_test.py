# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_rma_token_match_test - RMA SIP and chiplet token results from the SEP debug bus.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sep_rma_token_match_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_rma_token_match_test_seq import smu_sep_rma_token_match_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_rma_token_match_test(smu_base_test):
    """Each RMA lane reads idle, match or mismatch for its own token and no other."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-SEP-RMA-CHIP-MATCH",
        "CHK-SEP-RMA-CHIP-MISMATCH",
        "CHK-SEP-RMA-FAULT-LOG",
        "CHK-SEP-RMA-IDLE",
        "CHK-SEP-RMA-INDEP",
        "CHK-SEP-RMA-PRECOND",
        "CHK-SEP-RMA-SETTLE",
        "CHK-SEP-RMA-SIP-MATCH",
        "CHK-SEP-RMA-START",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_sep_rma_token_match_test SEP=1 JTAG")
        seq = smu_sep_rma_token_match_test_seq(self)
        await seq.run()
        assert seq.done, "RMA token match scenario incomplete"
