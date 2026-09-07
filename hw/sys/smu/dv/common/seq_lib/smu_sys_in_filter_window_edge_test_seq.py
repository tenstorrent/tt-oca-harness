# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 page-edge: interior OKAY, outside mapped CSRs DECERR. SEP=0, no Force."""

from __future__ import annotations

from seq_lib.smu_tb_pins import smc_primary_reset

import cocotb
from ocah_axi_vip import RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    SCRATCH_COLD_ADDR,
    SMC_FILTER_POISON_LO,
    WDT_CTRL_ADDR,
    await_smn_resp,
    page_align_window,
    program_inbound0_window,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
WINDOW_START = VERSION_LO
WINDOW_END = SMC_CHIP_CONFIG_CHIP_ID
# Mapped CSRs outside the VERSION_LO page (page_lo-4 is the local-xbar hole).
BELOW_CSR = WDT_CTRL_ADDR
ABOVE_CSR = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)


class smu_sys_in_filter_window_edge_test_seq:
    """SMN OKAY on filter page interior; DECERR on mapped CSRs outside."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _sample_int(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on OSS tb_top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        dut = self.dut
        page_lo, page_hi = page_align_window(WINDOW_START, WINDOW_END)
        below = BELOW_CSR
        above = ABOVE_CSR
        if not (below < page_lo or above > page_hi):
            raise AssertionError(
                f"edge CSRs are inside programmed page "
                f"[0x{page_lo:08x},0x{page_hi:08x}] "
                f"below=0x{below:08x} above=0x{above:08x}"
            )

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        self.s1_ok = True
        sb.expect_eq("CHK-FILTER-EDGE-GATE-OPEN", gate, 0)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        await program_inbound0_window(jtag, WINDOW_START, WINDOW_END, scoreboard=sb, tag="EDGE")

        data_v, resp_v = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="edge VERSION_LO OKAY",
        )
        if (int(data_v) & 0xFFFF_FFFF) != VERSION_LO_RESET:
            raise AssertionError(
                f"edge VERSION_LO data=0x{int(data_v) & 0xFFFF_FFFF:08x} "
                f"want 0x{VERSION_LO_RESET:08x}"
            )
        _, resp_s = await await_smn_resp(
            master,
            SCRATCH_COLD_ADDR,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="edge SCRATCH_COLD OKAY",
        )
        self.s2_ok = True
        self._log(
            f"AXI_FILTER_OKAY edge inside page=[0x{page_lo:08x},0x{page_hi:08x}] "
            f"VERSION_LO+SCRATCH_COLD OKAY"
        )
        sb.expect_eq(
            "CHK-AXI-FILTER-OKAY edge VERSION_LO",
            resp_v,
            RESP_OKAY,
            evidence="AXI_FILTER_OKAY",
        )
        sb.expect_eq("CHK-FILTER-EDGE-SCRATCH", resp_s, RESP_OKAY)

        lo_data, resp_lo = await await_smn_resp(
            master,
            below,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label=f"edge below WDT 0x{below:08x}",
        )
        hi_data, resp_hi = await await_smn_resp(
            master,
            above,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label=f"edge above GPIO 0x{above:08x}",
        )
        lo_poison = int(lo_data) & 0xFFFF_FFFF
        hi_poison = int(hi_data) & 0xFFFF_FFFF
        if lo_poison != SMC_FILTER_POISON_LO:
            raise AssertionError(
                f"below-edge poison want 0x{SMC_FILTER_POISON_LO:08x} "
                f"got 0x{lo_poison:08x} (xbar-hole is not the page edge)"
            )
        if hi_poison != SMC_FILTER_POISON_LO:
            raise AssertionError(
                f"above-edge poison want 0x{SMC_FILTER_POISON_LO:08x} got 0x{hi_poison:08x}"
            )
        self.s3_ok = True
        self._log(
            f"CHK-FILTER-EDGE-OUT below=0x{below:08x} data=0x{lo_poison:08x} "
            f"above=0x{above:08x} data=0x{hi_poison:08x} DECERR+filter-poison"
        )
        sb.expect_eq("CHK-FILTER-EDGE-BELOW", resp_lo, RESP_DECERR)
        sb.expect_eq("CHK-FILTER-EDGE-ABOVE", resp_hi, RESP_DECERR)
