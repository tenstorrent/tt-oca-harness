# SPDX-License-Identifier: Apache-2.0
"""SMC OSS U1-2/U1-3/U6-2: SYS_OUT SLVERR inject + golden + resp monitor."""

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
    OUTPUT_FABRIC_SLVERR_POISON,
    RESP_OKAY,
    RESP_SLVERR,
    check_output_responder_delta,
    jtag_axi_read,
    jtag_axi_write,
    output_fabric_model,
    output_fabric_pass_all_cfg_seq,
)


@pyuvm.test()
class smc_output_fabric_slverr_inject_test(smc_base_test):
    """OKAY WR/RD, SLVERR inject, OKAY readback; SYS_OUT monitor tallies."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_output_force_slverr"), (
            "tb_output_force_slverr missing; rebuild after U1-2 SLVERR knob"
        )
        assert hasattr(dut, "tb_output_axi_bresp"), (
            "tb_output_axi_bresp missing; rebuild after U6-2 SYS_OUT lift"
        )
        dut.tb_output_force_slverr.value = 0
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

        # Phase B: slave SLVERR — must NOT update golden.
        dut.tb_output_force_slverr.value = 1
        wr_err = await jtag_axi_write(
            self,
            OUTPUT_FABRIC_ADDR,
            OUTPUT_FABRIC_ALT_DATA,
            allow_error=True,
            expected_resp=RESP_SLVERR,
            update_golden=False,
            memory_region=OUTPUT_FABRIC_MODEL_REGION,
        )
        assert wr_err.resp_code == RESP_SLVERR, (
            f"injected write resp={wr_err.resp_code}, expected SLVERR"
        )
        rd_err = await jtag_axi_read(
            self,
            OUTPUT_FABRIC_ADDR,
            allow_error=True,
            expected_resp=RESP_SLVERR,
        )
        assert rd_err.resp_code == RESP_SLVERR, (
            f"injected read resp={rd_err.resp_code}, expected SLVERR"
        )
        assert rd_err.rdata == OUTPUT_FABRIC_SLVERR_POISON, (
            f"SLVERR poison rdata=0x{rd_err.rdata:x}, "
            f"expected 0x{OUTPUT_FABRIC_SLVERR_POISON:x}"
        )
        snap_b = mon.snapshot()
        assert snap_b["b_slverr"] >= snap_a["b_slverr"] + 1, snap_b
        assert snap_b["r_slverr"] >= snap_a["r_slverr"] + 1, snap_b

        # Phase C: clear inject; golden still holds original DATA.
        dut.tb_output_force_slverr.value = 0
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
            write_delta=2,
            read_delta=3,
            last_addr=OUTPUT_FABRIC_ADDR,
            last_wdata=OUTPUT_FABRIC_ALT_DATA,
        )
        assert sb.memory_model_updates_seen == updates0 + 1, (
            f"SLVERR path must not update golden: updates={sb.memory_model_updates_seen}"
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
            csr_accesses=cfg_seq.accesses + 5,
            proxy=False,
            details=(
                "SYS_OUT SLVERR inject + SmcMemoryModel + U6-2 output AXI "
                f"monitor tallies {snap_c}"
            ),
        )
