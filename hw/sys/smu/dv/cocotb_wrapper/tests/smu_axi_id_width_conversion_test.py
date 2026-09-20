# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_id_width_conversion_test - the external-port ID round trip, on the wrapper.

The wrapper elaborates SEP=1, so a read entering on the `ext_in_*` pins (8-bit
ID, the smu_axi_in_req_i / smu_axi_in_resp_o pair on smu_wrapper.sv) is routed
by the SMU crossbar to the SMC system input, whose transaction IDs are 6 bits
wide. The RID that comes back on ext_in_rid has therefore crossed the fabric's
ID handling in both directions. The SMC reset observable is
rst_primary_smc_clk_n_o.

SYS_IN blocks by default, so a probe issued without programming lands on the
error slave, which also answers with RID == ARID; a RID compare alone cannot
tell the fabric route from that slave. The sequence therefore first routes the
local SMC aperture and opens an INBOUND0 window over the probed page through
JTAG2AXI, then requires every probe to complete OKAY with RID == ARID and the
VERSION_LO probe to return its RDL reset value: only a read that reached the
SMC register can do that.

The SEP=0 direct ID converter (the gen_no_sep arm) is not elaborated on this
bench; it is proved on --dut smu_block by smu_axi_external_port_connectivity_test.
"""

from __future__ import annotations

import random

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_OKAY
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
)
from seq_lib.smu_axi_helpers import axi_read32_resp_ids_bounded, make_smu_axi_master, resp_name
from seq_lib.smu_filter_helpers import (
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test

# Three probes on one register page, so a single INBOUND0 window admits them.
PROBE_ADDRS = (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO + 8,
)
WINDOW_START = min(PROBE_ADDRS)
WINDOW_END = max(PROBE_ADDRS) + 4


@pyuvm.test()
class smu_axi_id_width_conversion_test(smu_base_test):
    """ext_in -> SEP=1 crossbar -> SMC SYS_IN completes OKAY with RID == ARID on smu_wrapper."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()
        rng = random.Random(seed ^ 0xFAB_1D00)
        arids: list[int] = []
        while len(arids) < len(PROBE_ADDRS):
            arid = rng.randint(1, 0xFF)
            if arid not in arids:
                arids.append(arid)
        self.logger.info("SEED: %d id_width arids=%s", seed, [f"0x{a:x}" for a in arids])

        sb = self.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)
        await program_inbound0_window(jtag, WINDOW_START, WINDOW_END, scoreboard=sb, tag="IDW")

        # bring_up has already blocked until rst_primary_smc_clk_n_o released.
        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        for idx, addr in enumerate(PROBE_ADDRS):
            value, resp, issued, rid = await axi_read32_resp_ids_bounded(
                master, addr, arid=arids[idx], label=f"id_width_rd@{idx}"
            )
            self.logger.info(
                "id_width probe @0x%08x resp=%s arid=0x%02x rid=0x%02x data=0x%08x",
                addr,
                resp_name(resp),
                issued,
                rid,
                int(value) & 0xFFFF_FFFF,
            )
            sb.expect_eq(
                f"OKAY through the SEP=1 crossbar to SYS_IN @0x{addr:08x}",
                resp,
                RESP_OKAY,
                evidence="AXI_ID_WIDTH_OK",
            )
            sb.expect_eq(
                f"RID match through the SEP=1 crossbar to SYS_IN @0x{addr:08x}",
                rid,
                issued,
                evidence="AXI_ID_WIDTH_OK",
            )
        # The first probe is VERSION_LO: the value can only be the RDL reset if the
        # read reached the SMC register and not the error slave.
        first_value, _resp, _issued, _rid = await axi_read32_resp_ids_bounded(
            master, SMC_CHIP_CONFIG_VERSION_LO, arid=arids[0], label="id_width_rd@version_lo"
        )
        sb.expect_eq(
            "VERSION_LO through the SEP=1 crossbar to SYS_IN reads its RDL reset value",
            int(first_value) & 0xFFFF_FFFF,
            SMC_CHIP_CONFIG_VERSION_LO_RESET,
            evidence="AXI_ID_WIDTH_OK",
        )

        self.logger.info(
            "smu_axi_id_width_conversion_test: %d ID round-trip probes OKAY through the SEP=1 "
            "crossbar on smu_wrapper",
            len(PROBE_ADDRS),
        )
