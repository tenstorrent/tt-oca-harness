# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS output filter/remap security CSR smoke.

DV-CARD:          SMC_005   ANCHOR: smc_output_filter_remap_security_test
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_output_fabric_vip_utils import (
    BLOCKED_WRITE_HOLD_CYCLES,
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_ALT_DATA,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    PASS_ALL_CONFIG,
    READ_ONLY_CONFIG,
    RESP_DECERR,
    check_output_responder_delta,
    hold_output_responder_writes,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_block_write_cfg_seq,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from smc_base_test import smc_base_test

# Fail-capable stimulus floors, written out here rather than derived from the
# two config sequences' own counters: a floor that shrinks with the sequence
# cannot catch a sequence that silently stops short.
# Composition (both directed, no polling):
#   output_fabric_pass_all_cfg_seq       6 filter CSR writes
# + output_fabric_block_write_cfg_seq    6 filter CSR writes
OUTPUT_FILTER_MIN_CSR_ACCESSES = 12
# Floor for the JTAG-AXI fabric traffic: pass-phase write + read, block-phase
# blocked write + follow-up read. record_protocol_vip measures the observed count
# from the scoreboard's per-bus tally (driver-stamped, one per completed access).
OUTPUT_FILTER_MIN_JTAG_AXI_ACCESSES = 4


@pyuvm.test()
class smc_output_filter_remap_security_test(smc_base_test):
    """Verify output filter allows reads and blocks writes at protocol level."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-NONVAC-PHASE-FENCE",
        "CHK-OUTBOUND-BLOCK-WRITE",
        "CHK-OUTBOUND-PASS-ALL",
    )
    min_evidence = 4

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

        # Phase-boundary snapshot, X-aware: the pass-phase write must have
        # advanced the responder write counter by exactly one; it is the positive
        # control for the "blocked write produces no beat" leg below.
        mid_writes, mid_reads = output_responder_counts()
        assert mid_writes == start_writes + 1, (
            f"pass-phase output-fabric write did not advance the SYS_OUT "
            f"responder write counter by exactly one: {start_writes} -> "
            f"{mid_writes}. Without that advance the block-phase 'counter did "
            f"not move' leg below would have no positive control"
        )
        assert mid_reads > start_reads, (
            f"pass-phase output-fabric read did not advance the SYS_OUT "
            f"responder read counter: {start_reads} -> {mid_reads}"
        )
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
        # The blocked write must not produce an output-fabric write beat. Held
        # against the phase-boundary snapshot for a bounded window, sampled every
        # cycle; the pass-phase advance asserted above is this leg's positive
        # control.
        blocked_writes = await hold_output_responder_writes(
            expected_writes=mid_writes,
            label="output_filter_blocked_write",
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
        end_writes, end_reads = output_responder_counts()
        cocotb.log.info(
            "CHK-NONVAC-PHASE-FENCE: ordered SETUP<ACTION<EFFECT fence on the "
            f"SYS_OUT responder write counter: start={start_writes} -> "
            f"mid={mid_writes} (pass-phase write advanced it by exactly one: the "
            f"positive control) -> {blocked_writes} held for "
            f"{BLOCKED_WRITE_HOLD_CYCLES} clk_smc_i cycles across the "
            f"FILTER_CONFIG={READ_ONLY_CONFIG:#x} blocked write (no beat "
            f"reached the output fabric) -> end={end_writes}; reads "
            f"{start_reads} -> {mid_reads} -> {end_reads}; the four tb_output "
            f"observability nets are resolvable and output_fabric_model region "
            f"registered"
        )
        cocotb.log.info("SMC_005 scenario PASS")
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=pass_seq.accesses + block_seq.accesses,
            min_csr_accesses=OUTPUT_FILTER_MIN_CSR_ACCESSES,
            # The four JTAG-AXI accesses are fabric traffic and are reported in
            # their own field; record_protocol_vip measures the observed count
            # from the scoreboard's JTAG AXI tally, so only the floor is given.
            min_fabric_accesses=OUTPUT_FILTER_MIN_JTAG_AXI_ACCESSES,
            fabric_access_label="jtag_axi_accesses",
            fabric_bus="JTAG AXI",
            # No access on this path runs with allow_timeout, so an expiry raises
            # in SmcSysAxiAgent._timed_event and control cannot reach this record
            # with a timeout counted: nothing here measures timeouts, and `None`
            # renders `n/a`.
            timeouts=None,
            proxy=False,
            details="Output filter pass/read-only behavior checked with responder counters",
        )
        cocotb.log.info(
            "CHK-NONVAC: protocol-VIP record accepted with csr_accesses=%d against "
            "floor %d and jtag_axi_accesses=%d against floor %d; the scoreboard "
            "rejects the record, and the run fails, below either floor",
            pass_seq.accesses + block_seq.accesses,
            OUTPUT_FILTER_MIN_CSR_ACCESSES,
            self.env.scoreboard.axi_accesses_by_bus.get("JTAG AXI", 0),
            OUTPUT_FILTER_MIN_JTAG_AXI_ACCESSES,
        )
