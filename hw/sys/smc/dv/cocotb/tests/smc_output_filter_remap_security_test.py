# SPDX-License-Identifier: Apache-2.0
"""SMC OSS output filter/remap security CSR smoke."""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    OUTPUT_FABRIC_DATA,
    check_output_responder_delta,
    expect_output_fabric_value,
    jtag_axi_read,
    jtag_axi_write,
    model_output_fabric_write,
    output_fabric_block_write_cfg_seq,
    output_fabric_pass_all_cfg_seq,
)


@pyuvm.test()
class smc_output_filter_remap_security_test(smc_base_test):
    """Verify output filter allows reads and blocks writes at protocol level."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)

        pass_seq = output_fabric_pass_all_cfg_seq("output_filter_pass_all_seq")
        await self.start_seq(pass_seq, self.env.sys_axi_agent.sequencer)
        await jtag_axi_write(self, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_DATA)
        model_output_fabric_write(self, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_DATA)
        await jtag_axi_read(self, OUTPUT_FABRIC_ADDR, expected=OUTPUT_FABRIC_DATA)
        expect_output_fabric_value(self, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_DATA)

        block_seq = output_fabric_block_write_cfg_seq("output_filter_block_write_seq")
        await self.start_seq(block_seq, self.env.sys_axi_agent.sequencer)
        blocked_write = await jtag_axi_write(
            self, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_ALT_DATA, allow_error=True
        )
        assert blocked_write.resp_code == 3, (
            f"blocked output-fabric write resp {blocked_write.resp_code}, expected DECERR"
        )
        await jtag_axi_read(self, OUTPUT_FABRIC_ADDR, expected=OUTPUT_FABRIC_DATA)
        expect_output_fabric_value(self, OUTPUT_FABRIC_ADDR, OUTPUT_FABRIC_DATA)

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=2,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=pass_seq.accesses + block_seq.accesses + 4,
            proxy=False,
            details="Output filter pass/read-only behavior checked with responder counters",
        )
