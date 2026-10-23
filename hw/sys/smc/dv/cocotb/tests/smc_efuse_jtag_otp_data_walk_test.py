# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse interface control written from the JTAG eFuse port, read back over SEP_IN.

Contract: ``SMC_COV_W2T_009`` revision 1
(``hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md``).

The ``ej_axi`` AXI-Lite manager drives ``axil_smc_otp_jtag_req_i``; the sequence runs on
the SEP_IN agent for every readback and poll.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.smc_protocol_vip_item import SmcProtocolVipKind
from env.smc_sys_axi_agent import idle_axil_master_inputs
from ocah_axi_vip import OcahAxiLiteMasterAgent
from seq_lib.smc_efuse_jtag_otp_data_walk_test_seq import smc_efuse_jtag_otp_data_walk_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_jtag_otp_data_walk_test(smc_base_test):
    """JTAG-port data walk, partial strobe, program, read-back and data-0 program."""

    required_evidence = (
        "CHK-EFUSE-JTAG-DATA0",
        "CHK-EFUSE-JTAG-PARTIAL-STRB",
        "CHK-EFUSE-JTAG-PROGRAM",
        "CHK-EFUSE-JTAG-READBACK",
        "CHK-EFUSE-JTAG-WALK",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        idle_axil_master_inputs(dut, "ej_axi")
        jtag = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        ).sequence
        await ClockCycles(dut.clk_smc_i, 5)

        seq = smc_efuse_jtag_otp_data_walk_test_seq("smc_efuse_jtag_otp_data_walk_test_seq")
        seq.jtag = jtag
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.chk_seen == [
            "CHK-EFUSE-JTAG-WALK",
            "CHK-EFUSE-JTAG-PARTIAL-STRB",
            "CHK-EFUSE-JTAG-PROGRAM",
            "CHK-EFUSE-JTAG-READBACK",
            "CHK-EFUSE-JTAG-DATA0",
            "CHK-TIMEOUT-PATHS",
            "CHK-NONVAC",
        ], f"checker lines printed {seq.chk_seen}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            # Directed SEP_IN reads without the polls: 1 status, 104 walk readbacks,
            # 3 partial-strobe readbacks, 1 program-interface read, 4 dout reads and
            # 4 restore readbacks.
            min_csr_accesses=117,
            csr_accesses=self.env.scoreboard.axi_accesses_by_bus.get("SEP_IN AXI", 0),
            proxy=False,
            details=(
                f"eFuse interface control written through the JTAG eFuse port "
                f"({seq.jtag_writes} writes, {seq.jtag_reads} reads) and read back over "
                f"SEP_IN; program and read of one fuse bit and a data-0 program "
                f"(eFuse bank is the DV model)"
            ),
        )
