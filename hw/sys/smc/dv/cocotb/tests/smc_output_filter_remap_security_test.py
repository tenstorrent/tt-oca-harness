# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS output filter/remap security CSR smoke.

DV-CARD:          SMC_005   ANCHOR: smc_output_filter_remap_security_test
DV-CARD-REVISION: 2   RECORD-SHA256: 742cda4faa03574c91d3166fdb9ce3c9b231242b544d248b14cbc297d56b1745
DV-CARD-SOURCE:   hw/sys/smc/dv/tb/SMC_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    PASS_ALL_CONFIG,
    READ_ONLY_CONFIG,
    RESP_DECERR,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_block_write_cfg_seq,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
)


@pyuvm.test()
class smc_output_filter_remap_security_test(smc_base_test):
    """Verify output filter allows reads and blocks writes at protocol level."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        cocotb.log.info("STEP S1: SETUP inbound/outbound pass-all programming")
        output_fabric_model(self)
        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)

        pass_seq = output_fabric_pass_all_cfg_seq("output_filter_pass_all_seq")
        await self.start_seq(pass_seq, self.env.sys_axi_agent.sequencer)
        cocotb.log.info(
            "STEP S2: SMC-OUTBOUND-FILTER.S1 PASS_ALL_CONFIG "
            f"{PASS_ALL_CONFIG:#x} write+read {OUTPUT_FABRIC_DATA:#x}"
        )
        await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_DATA,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected=OUTPUT_FABRIC_DATA,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=1,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        cocotb.log.info(
            "CHK-OUTBOUND-PASS-ALL: OUTBOUND0_FILTER_CONFIG="
            f"{PASS_ALL_CONFIG:#x}; jtag write+read at {OUTPUT_FABRIC_ADDR:#x} "
            f"data={OUTPUT_FABRIC_DATA:#x} OKAY; responder deltas advanced; "
            f"last_addr/last_wdata match"
        )

        mid_writes = int(dut.tb_output_axi_write_count.value)
        mid_reads = int(dut.tb_output_axi_read_count.value)
        cocotb.log.info(
            "STEP S3: SMC-OUTBOUND-FILTER.S2 READ_ONLY_CONFIG "
            f"{READ_ONLY_CONFIG:#x} block write {OUTPUT_FABRIC_ALT_DATA:#x}"
        )
        block_seq = output_fabric_block_write_cfg_seq("output_filter_block_write_seq")
        await self.start_seq(block_seq, self.env.sys_axi_agent.sequencer)
        blocked_write = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_ALT_DATA,
            allow_error=True,
            expect_error=True,
            expected_resp=RESP_DECERR,
        )
        assert blocked_write.resp_code == RESP_DECERR, (
            f"blocked output-fabric write resp {blocked_write.resp_code}, expected DECERR"
        )
        await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected=OUTPUT_FABRIC_DATA,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        cocotb.log.info(
            "CHK-OUTBOUND-BLOCK-WRITE: after FILTER_CONFIG="
            f"{READ_ONLY_CONFIG:#x}, jtag write resp_code=={blocked_write.resp_code} "
            f"(RESP_DECERR={RESP_DECERR}); follow-up read still "
            f"{OUTPUT_FABRIC_DATA:#x}"
        )

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=2,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        for sig in (
            dut.tb_output_axi_write_count,
            dut.tb_output_axi_read_count,
            dut.tb_output_axi_last_addr,
            dut.tb_output_axi_last_wdata,
        ):
            assert sig.value.is_resolvable, f"{sig._name} X/Z"
        cocotb.log.info(
            "CHK-NONVAC: output_fabric_model region registered; "
            f"tb_output counters resolvable "
            f"(writes={int(dut.tb_output_axi_write_count.value)} "
            f"reads={int(dut.tb_output_axi_read_count.value)}; "
            f"mid={mid_writes}/{mid_reads})"
        )
        cocotb.log.info("SMC_005 scenario PASS")
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=pass_seq.accesses + block_seq.accesses + 4,
            proxy=False,
            details="Output filter pass/read-only behavior checked with responder counters",
        )
