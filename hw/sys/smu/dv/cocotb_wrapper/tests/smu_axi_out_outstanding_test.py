# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_out_outstanding_test - several transactions in flight on smu_axi_out.

The outbound responder holds up to eight writes and eight reads and delays
every response; an iDMA copy outside both apertures keeps more than three of
each in flight at once, completes intact, and every response pairs with the
oldest outstanding request of its ID.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_out_outstanding_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_out_outstanding_test_seq import DEPTH, smu_axi_out_outstanding_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_out_outstanding_test(smu_base_test):
    """Outbound outstanding depth from the SMC iDMA; no Force."""

    use_shared_env = True

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.axi_out_max_outstanding = DEPTH

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_out_outstanding_test AXI-OUT")
        seq = smu_axi_out_outstanding_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok)
        assert all(steps), f"outbound outstanding scenario incomplete s1..s2={steps}"
