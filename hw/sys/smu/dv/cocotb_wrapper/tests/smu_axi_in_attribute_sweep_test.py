# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_in_attribute_sweep_test - inbound AW/AR attributes and one outbound write.

Sweeps AxPROT, AxREGION, AxQOS, AxCACHE, AxLOCK, AxSIZE, AxLEN and AxBURST on
the wrapper's inbound SMN port against the response the AXI traffic filter
specification assigns to each, then makes the SMC write one word out of the
chiplet on smu_axi_out and checks the bench responder holds it.

AxATOP stays out: tb/tb_wrapper_top.sv ties smu_axi_in_req.aw.atop to '0.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_axi_in_attribute_sweep_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_in_attribute_sweep_test_seq import smu_axi_in_attribute_sweep_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_in_attribute_sweep_test(smu_base_test):
    """Inbound AXI attribute acceptance and one SMC write out of the chiplet; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_in_attribute_sweep_test AXI-ATTR")
        seq = smu_axi_in_attribute_sweep_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok and seq.s5_ok and seq.s6_ok, (
            f"attribute sweep incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} "
            f"s4={seq.s4_ok} s5={seq.s5_ok} s6={seq.s6_ok}"
        )
