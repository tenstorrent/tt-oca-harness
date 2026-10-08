# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS output-fabric responder-backed protocol test."""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_output_fabric_wr_rd_responder_test(smc_base_test):
    """Drive JTAG AXI through output fabric; scoreboard checks memory golden."""

    required_evidence = ("CHK-OUTPUT-FABRIC-WR-RD-GOLDEN",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)
        output_fabric_model(self)

        cfg_seq = output_fabric_pass_all_cfg_seq()
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

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
        assert self.env.scoreboard.memory_model_updates_seen >= 1
        assert self.env.scoreboard.memory_model_checks_seen >= 1
        end_writes, end_reads = output_responder_counts(dut)
        cocotb.log.info(
            "CHK-OUTPUT-FABRIC-WR-RD-GOLDEN: JTAG AXI write 0x%016x @ 0x%x then read "
            "back through the output fabric; SYS_OUT responder write_count %d -> %d "
            "(exactly +1), read_count %d -> %d (>= +1), last_addr/last_wdata matched "
            "the write; scoreboard memory-model updates=%d, golden read checks=%d",
            OUTPUT_FABRIC_DATA,
            OUTPUT_FABRIC_ADDR,
            start_writes,
            end_writes,
            start_reads,
            end_reads,
            self.env.scoreboard.memory_model_updates_seen,
            self.env.scoreboard.memory_model_checks_seen,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=cfg_seq.accesses,
            # Directed stimulus floor: 3 inbound + 3 outbound pass-all filter
            # CSR writes (output_fabric_pass_all_cfg_seq); a floor taken from
            # `cfg_seq.accesses` would shrink with a sequence that stopped
            # issuing them.
            min_csr_accesses=6,
            # The two JTAG-AXI accesses are fabric traffic and are reported in
            # their own field; csr_accesses counts CSR traffic only.
            fabric_accesses=2,
            min_fabric_accesses=2,
            fabric_access_label="jtag_axi_accesses",
            proxy=False,
            details=(
                "JTAG AXI WR/RD + U1-3 scoreboard SmcMemoryModel golden "
                f"(updates={self.env.scoreboard.memory_model_updates_seen} "
                f"checks={self.env.scoreboard.memory_model_checks_seen})"
            ),
        )
