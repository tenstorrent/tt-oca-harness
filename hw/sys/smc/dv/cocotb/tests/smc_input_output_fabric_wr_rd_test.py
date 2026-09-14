# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS input/output fabric CSR precheck."""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ALT_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from smc_base_test import smc_base_test

# Fail-capable stimulus floors, written out here rather than derived from the
# config sequence's own counter: a floor that shrinks with the sequence cannot
# catch a sequence that silently stops short.
# Composition (output_fabric_pass_all_cfg_seq, directed, no polling):
#   3 inbound filter CSR writes (START, END, FILTER_CONFIG)
# + 3 outbound filter CSR writes (START, END, FILTER_CONFIG)
INPUT_OUTPUT_FABRIC_MIN_CSR_ACCESSES = 6
# Independent literal floor for the non-CSR fabric traffic this scenario issues:
# one JTAG-AXI write and one JTAG-AXI read of the output-fabric window. The
# OBSERVED count is measured by the scoreboard's per-bus tally inside
# record_protocol_vip (driver-stamped, one per completed access), never passed in
# from here -- a constant used as both observation and floor would make the
# scoreboard assert `2 >= 2` ([NO-ALWAYS-PASS-CHECKER]).
MIN_JTAG_AXI_ACCESSES = 2


@pyuvm.test()
class smc_input_output_fabric_wr_rd_test(smc_base_test):
    """Run output-fabric write/read through JTAG AXI with responder checks."""

    required_evidence = (
        "CHK-INPUT-OUTPUT-FABRIC-WR-RD",
        "CHK-NONVAC",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        # X-aware baseline sample (shared helper: fails naming the signal if a
        # SYS_OUT observability counter is X/Z instead of resolving it blindly).
        start_writes, start_reads = output_responder_counts()
        output_fabric_model(self)

        cfg_seq = output_fabric_pass_all_cfg_seq("input_output_fabric_cfg_seq")
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

        await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ALT_ADDR,
            OUTPUT_FABRIC_ALT_DATA,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ALT_ADDR,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=1,
            last_addr=OUTPUT_FABRIC_ALT_ADDR,
            last_wdata=OUTPUT_FABRIC_ALT_DATA,
        )
        assert self.env.scoreboard.memory_model_updates_seen >= 1
        assert self.env.scoreboard.memory_model_checks_seen >= 1
        end_writes, end_reads = output_responder_counts()
        # Emitted only here: the responder last_addr/last_wdata compare above
        # and both memory-model golden gates have already passed.
        cocotb.log.info(
            "CHK-INPUT-OUTPUT-FABRIC-WR-RD: JTAG AXI write+read at "
            f"{OUTPUT_FABRIC_ALT_ADDR:#x} data={OUTPUT_FABRIC_ALT_DATA:#x} "
            f"OKAY; SYS_OUT responder last_addr/last_wdata match that "
            f"addr/data and counters advanced {start_writes}->{end_writes} "
            f"writes / {start_reads}->{end_reads} reads; scoreboard "
            f"SmcMemoryModel golden updates="
            f"{self.env.scoreboard.memory_model_updates_seen} checks="
            f"{self.env.scoreboard.memory_model_checks_seen}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=cfg_seq.accesses,
            min_csr_accesses=INPUT_OUTPUT_FABRIC_MIN_CSR_ACCESSES,
            # The two JTAG-AXI fabric accesses are reported in their own field:
            # folded into csr_accesses they would make the record state a count
            # of CSR traffic that never happened. The observed count is MEASURED by
            # record_protocol_vip from the scoreboard's JTAG AXI tally; only the
            # floor is written here, so the scoreboard's
            # `fabric_accesses >= min_fabric_accesses` compares a measurement
            # against an independent literal.
            min_fabric_accesses=MIN_JTAG_AXI_ACCESSES,
            fabric_access_label="jtag_axi_accesses",
            fabric_bus="JTAG AXI",
            # Nothing on this path measures a timeout: every access runs with
            # allow_timeout False, so SmcSysAxiAgent._timed_event raises on expiry
            # and control cannot reach this record with a timeout counted.
            # `None` renders `n/a`; printing 0 would state an unmeasured
            # statistic in the shape of a measured one ([EXACT-EXPECTATION]).
            timeouts=None,
            proxy=False,
            details=(
                "JTAG AXI WR/RD + U1-3 scoreboard SmcMemoryModel golden "
                f"(updates={self.env.scoreboard.memory_model_updates_seen} "
                f"checks={self.env.scoreboard.memory_model_checks_seen})"
            ),
        )
        cocotb.log.info(
            "CHK-NONVAC: protocol-VIP record accepted with csr_accesses=%d against "
            "floor %d and jtag_axi_accesses=%d against floor %d; the scoreboard "
            "rejects the record, and the run fails, below either floor",
            cfg_seq.accesses,
            INPUT_OUTPUT_FABRIC_MIN_CSR_ACCESSES,
            self.env.scoreboard.axi_accesses_by_bus.get("JTAG AXI", 0),
            MIN_JTAG_AXI_ACCESSES,
        )
