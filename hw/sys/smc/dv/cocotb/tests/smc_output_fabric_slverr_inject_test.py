# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS U1-2/U1-3/U6-2: SYS_OUT SLVERR via axi_sim_mem werr/rerr (SEP pulp API)."""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_DATA,
    OUTPUT_FABRIC_MODEL_REGION,
    RESP_OKAY,
    RESP_SLVERR,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
)


async def _program_sys_out_err(dut, addr: int, resp: int) -> None:
    """Write TB-owned axi_sim_mem.werr/rerr (not a DUT Force)."""
    assert hasattr(dut, "tb_output_err_we"), "tb_output_err_we missing"
    dut.tb_output_err_addr.value = addr
    dut.tb_output_err_resp.value = resp
    dut.tb_output_err_we.value = 1
    await RisingEdge(dut.clk_smc_i)
    dut.tb_output_err_we.value = 0
    await RisingEdge(dut.clk_smc_i)


@pyuvm.test()
class smc_output_fabric_slverr_inject_test(smc_base_test):
    """OKAY WR/RD, axi_sim_mem rerr SLVERR read, OKAY readback; SYS_OUT monitor."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_output_axi_bresp"), (
            "tb_output_axi_bresp missing; rebuild after U6-2 SYS_OUT lift"
        )
        output_fabric_model(self)

        start_writes = int(dut.tb_output_axi_write_count.value)
        start_reads = int(dut.tb_output_axi_read_count.value)
        sb = self.env.scoreboard
        mon = self.env.output_axi_monitor
        mon.allow_slverr = True
        updates0 = sb.memory_model_updates_seen
        checks0 = sb.memory_model_checks_seen
        snap0 = mon.snapshot()

        cfg_seq = output_fabric_pass_all_cfg_seq("slverr_inject_pass_all_seq")
        await self.start_seq(cfg_seq, self.env.sys_axi_agent.sequencer)

        # Phase A: OKAY path.
        wr_ok = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_DATA,
            expected_resp=RESP_OKAY,
            update_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert wr_ok.resp_code == RESP_OKAY, wr_ok.resp_code
        rd_ok = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected_resp=RESP_OKAY,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert rd_ok.resp_code == RESP_OKAY, rd_ok.resp_code
        snap_a = mon.snapshot()
        assert snap_a["b_okay"] >= snap0["b_okay"] + 1, snap_a
        assert snap_a["r_okay"] >= snap0["r_okay"] + 1, snap_a

        # Phase B: pulp axi_sim_mem rerr inject (TB model API). Read returns
        # stored DATA with SLVERR; ClearErrOnAccess clears after the beat.
        await _program_sys_out_err(dut, OUTPUT_FABRIC_ADDR, RESP_SLVERR)
        rd_err = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            allow_error=True,
            expected_resp=RESP_SLVERR,
        )
        assert rd_err.resp_code == RESP_SLVERR, (
            f"injected read resp={rd_err.resp_code}, expected SLVERR"
        )
        assert rd_err.rdata == OUTPUT_FABRIC_DATA, (
            f"SLVERR rdata=0x{rd_err.rdata:x}, expected stored 0x{OUTPUT_FABRIC_DATA:x}"
        )
        snap_b = mon.snapshot()
        assert snap_b["r_slverr"] >= snap_a["r_slverr"] + 1, snap_b

        # Explicitly clear TB error maps (do not rely solely on ClearErrOnAccess).
        await _program_sys_out_err(dut, OUTPUT_FABRIC_ADDR, RESP_OKAY)

        # Phase C: error cleared; golden still holds original DATA.
        rd_again = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            expected_resp=RESP_OKAY,
            check_golden=True,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert rd_again.resp_code == RESP_OKAY, rd_again.resp_code

        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=3,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_DATA,
        )
        assert sb.memory_model_updates_seen == updates0 + 1, (
            f"unexpected golden updates={sb.memory_model_updates_seen}"
        )
        assert sb.memory_model_checks_seen == checks0 + 2
        snap_c = mon.snapshot()
        assert snap_c["r_okay"] >= snap_b["r_okay"] + 1, snap_c
        assert snap_c["b_decerr"] == 0 and snap_c["r_decerr"] == 0, snap_c
        cocotb.log.info(
            "U6-2 SYS_OUT monitor PASS: snap=%s updates=%d checks=%d",
            snap_c,
            sb.memory_model_updates_seen,
            sb.memory_model_checks_seen,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.OUTPUT_FABRIC,
            type(self).__name__,
            csr_accesses=cfg_seq.accesses,
            # Directed stimulus floor: 3 inbound + 3 outbound pass-all filter
            # CSR writes (output_fabric_pass_all_cfg_seq). Literal here, not
            # read from `cfg_seq.accesses`.
            min_csr_accesses=6,
            # The four JTAG-AXI accesses are reported in their own field rather
            # than folded into csr_accesses, which labelled fabric traffic as
            # CSR traffic.
            fabric_accesses=4,
            min_fabric_accesses=4,
            fabric_access_label="jtag_axi_accesses",
            proxy=False,
            details=(
                "SYS_OUT axi_sim_mem rerr SLVERR + SmcMemoryModel + U6-2 "
                f"output AXI monitor tallies {snap_c}"
            ),
        )
