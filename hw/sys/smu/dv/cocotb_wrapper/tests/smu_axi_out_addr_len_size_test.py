# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_out_addr_len_size_test - outbound address, AxSIZE and AxLEN on smu_axi_out.

JTAG2AXI writes and reads every AxSIZE at two 56-bit addresses outside the SMC
and SEP apertures, and the iDMA copies a 2 KiB block between two more, once through a stalling
responder; each transfer is compared at the outbound boundary and in the bench
responder, and responder SLVERR and DECERR reach JTAG2AXI as that status.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_out_addr_len_size_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_out_addr_len_size_test_seq import smu_axi_out_addr_len_size_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_out_addr_len_size_test(smu_base_test):
    """Outbound address, size and burst length from the SMC masters; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_out_addr_len_size_test AXI-OUT")
        seq = smu_axi_out_addr_len_size_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, seq.s4_ok, seq.s5_ok, seq.s6_ok)
        assert all(steps), f"outbound sweep incomplete s1..s6={steps}"
