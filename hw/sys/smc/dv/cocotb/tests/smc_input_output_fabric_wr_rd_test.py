# SPDX-License-Identifier: Apache-2.0
"""SMC OSS input/output fabric CSR precheck."""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ALT_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    check_output_responder_delta,
    expect_output_fabric_value,
    jtag_axi_read,
    jtag_axi_write,
    model_output_fabric_write,
    output_fabric_pass_all_cfg_seq,
)


@pyuvm.test()
class smc_input_output_fabric_wr_rd_test(smc_base_test):
    """Run output-fabric write/read through JTAG AXI with responder checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)

        cfg_seq = output_fabric_pass_all_cfg_seq("input_output_fabric_cfg_seq")
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

        await jtag_axi_write(self, OUTPUT_FABRIC_ALT_ADDR, OUTPUT_FABRIC_ALT_DATA)
        model_output_fabric_write(self, OUTPUT_FABRIC_ALT_ADDR, OUTPUT_FABRIC_ALT_DATA)
        await jtag_axi_read(self, OUTPUT_FABRIC_ALT_ADDR, expected=OUTPUT_FABRIC_ALT_DATA)
        expect_output_fabric_value(self, OUTPUT_FABRIC_ALT_ADDR, OUTPUT_FABRIC_ALT_DATA)
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=1,
            last_addr=OUTPUT_FABRIC_ALT_ADDR,
            last_wdata=OUTPUT_FABRIC_ALT_DATA,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=cfg_seq.accesses + 2,
            proxy=False,
            details="JTAG AXI output-fabric write/read with responder counters",
        )
