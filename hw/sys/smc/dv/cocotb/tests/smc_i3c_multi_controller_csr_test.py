# SPDX-License-Identifier: Apache-2.0
"""SMC OSS I3C multi-controller CSR depth test."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_i3c_multi_controller_csr_test_seq import (
    smc_i3c_multi_controller_csr_test_seq,
)
from seq_lib.smc_i3c_vip_utils import (
    get_or_bind_i3c_slave,
    i3c_directed_sdr_write_proof,
)


@pyuvm.test()
class smc_i3c_multi_controller_csr_test(smc_base_test):
    """Run I3C multi-controller CSR decode checks."""

    async def run_scenario(self) -> None:
        get_or_bind_i3c_slave()
        seq = smc_i3c_multi_controller_csr_test_seq("i3c_multi_controller_csr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Emit one real SDR write so this test also carries per-test
        # evidence that the cocotbext-i3c controller path drove the
        # tb_i3c0_* pins.
        await i3c_directed_sdr_write_proof()
