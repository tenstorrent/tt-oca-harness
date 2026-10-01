# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM FLR recovery-half sanity test.

This test covers only the *downstream* half of an FLR -- the cool reset itself
and the SEP_IN AXI CSR path across it -- and drives it from the ``rst_cool_ni``
pin, asserting ``tb_cfg_flr_pf_active`` stays inactive so the observed cool
reset is attributable to that pin. The FLR *trigger* path
(``cfg_flr_pf_active_i`` -> isolate-req CSR -> FLR delay/hold counters ->
``rst_cool_no``) is driven by the sibling ``smc_cool_reset_from_pcie_test``.

Proof: bounded assert/release handshakes on the cool reset, then
``SCRATCH_COLD_WARM_0`` read before any rewrite must equal its mapped reset
value, with the following write/read-back as the positive control that the CSR
path is alive again. See ``seq_lib/smc_flr_sanity_test_seq.py``.
"""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_flr_sanity_test_seq import smc_flr_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_flr_sanity_test(smc_base_test):
    """Run the SMC OSS FLR post-release sanity scenario."""

    required_evidence = ("CHK-FLR-COOL-CSR-RECOVERY",)
    min_evidence = 1

    async def run_scenario(self) -> None:
        seq = smc_flr_sanity_test_seq("flr_sanity_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
