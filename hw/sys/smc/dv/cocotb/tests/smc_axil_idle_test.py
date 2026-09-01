# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM AXI-Lite master idle test.

Samples the OR of all SMC AXI-Lite downstream master *_valid signals
(dtp_csr, pll, pvt, extension, efuse). With no CPU stimulus, the master
busses must stay idle after cold reset release.
"""

import pyuvm
from seq_lib.smc_axil_idle_test_seq import smc_axil_idle_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_axil_idle_test(smc_base_test):
    # `tb_axil_efuse_bank_active` and `tb_axil_any_master_active` already get a
    # same-run positive control from the sequence's `prove_axil_probe_alive`.
    # `tb_axil_external_active` did not: this control drives a frontdoor CSR
    # read into the adopter external window (which HAS a real responder inside
    # smc_ip_integration), samples the probe at 1 while the request is in
    # flight, and requires it back at 0 -- crediting the liveness ledger the
    # scoreboard consults ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
    #
    # `tb_axil_dtp_csr_active` deliberately has NO control and is never
    # exact-compared: tb_top.sv:1151 ties `axil_dtp_csr_resp = '0'`, so an
    # access there would wedge, and the DTP CSR boundary is a recorded TB-policy
    # deferral. The scoreboard books it OBSERVED-ONLY / not closure evidence.
    probe_positive_controls = ("axil_external_active",)

    async def run_scenario(self) -> None:
        seq = smc_axil_idle_test_seq("axil_idle_seq")
        await self.start_seq(seq, self.env.axil_agent.sequencer)
