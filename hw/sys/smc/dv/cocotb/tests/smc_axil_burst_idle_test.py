# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM 8-sample AXI-Lite burst idle test.

After base bring-up, a positive control drives `tb_axil_any_master_active` to 1
over the real SEP_IN AXI frontdoor, then an eight-sample burst is dispatched on
the AXI-Lite agent. `CHK-NONVAC` is gated on all eight samples' exact idle
compares over `AXIL_CHECKABLE_FIELDS` plus a typed scoreboard-counter gate
requiring all eight to have been booked on the analysis path;
`tb_axil_dtp_csr_active` is reported OBSERVED-ONLY and never exact-compared.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_axil_burst_idle_test_seq import smc_axil_burst_idle_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axil_burst_idle_test(smc_base_test):
    """Run the SMC OSS AXI-Lite burst idle scenario."""

    required_evidence = (
        "CHK-DIAG-AXIL-ACTIVE",
        "CHK-EFUSE-BANK-AXIL-ACTIVE",
        "CHK-NONVAC",
        "CHK-PROBE-AXIL-EXTERNAL-ALIVE",
    )
    min_evidence = 3

    # Positive control for `tb_axil_external_active`, the one AXI-Lite activity
    # probe on this burst's proof path without one elsewhere (the eFuse-bank and
    # any-master probes are covered by the sequence's own prover, and
    # `tb_axil_dtp_csr_active` is unbackable in this TB -- tb_top.sv:1119 ties
    # `axil_dtp_csr_resp = '0'` -- so the scoreboard books it OBSERVED-ONLY and
    # never exact-compares it) ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    probe_positive_controls = ("axil_external_active",)

    async def run_scenario(self) -> None:
        seq = smc_axil_burst_idle_test_seq("axil_burst_idle_seq")
        await self.start_seq(seq, self.env.axil_agent.sequencer)
