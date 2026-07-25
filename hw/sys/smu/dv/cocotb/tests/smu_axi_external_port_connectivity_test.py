# SPDX-License-Identifier: Apache-2.0
"""smu_axi_external_port_connectivity_test - SMN port handshake + activity.

Proves the flattened ``s_axi_*`` port reaches the DUT (response returns) and
that inbound AW activity can be observed on the TB counter when a write is
issued (even if the filter returns DECERR/BRESP error).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotbext.axi import AxiResp

from seq_lib.smu_axi_helpers import (
    axi_read32_resp,
    axi_write32,
    make_smu_axi_master,
)
from smu_base_test import smu_base_test

PROBE = 0xC000_2900


@pyuvm.test()
class smu_axi_external_port_connectivity_test(smu_base_test):
    """External SMN port is live: read completes, write increments AW counter."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        await ClockCycles(dut.clk_smu_i, 50)
        aw0 = int(dut.smu_axi_in_awvalid_count.value)

        master = await make_smu_axi_master(
            dut, dut.clk_smu_i, dut.rst_primary_smc_clk_no
        )
        _, resp = await axi_read32_resp(master, PROBE)
        sb.expect_eq("SMN read completes with DECERR", resp, AxiResp.DECERR)

        # Write also completes (filter isolate -> BRESP DECERR inside master).
        try:
            await axi_write32(master, PROBE, 0xA5A5_5A5A)
        except Exception as exc:  # noqa: BLE001 - cocotbext may raise on DECERR
            self.logger.info("write returned %s (expected under BlockByDefault)", exc)

        await ClockCycles(dut.clk_smu_i, 20)
        aw1 = int(dut.smu_axi_in_awvalid_count.value)
        sb.expect_true(
            "smu_axi_in_awvalid_count advanced after SMN write",
            aw1 > aw0,
        )

        self.logger.info(
            "smu_axi_external_port_connectivity_test: aw_count %d->%d", aw0, aw1
        )
