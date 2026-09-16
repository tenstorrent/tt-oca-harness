# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 page-edge: interior OKAY, outside mapped CSRs DECERR. SEP=0, no Force.

With ALLOW_BURST set the filter compares page indices and ignores addr[11:0], so one page is
the finest START/END step it resolves. The START edge is probed by re-programming the window
one page up and re-reading VERSION_LO, which then sits one page below START; its OKAY leg
under the first window is the live control that makes the DECERR a filter refusal rather than
an unmapped-address response.
"""

from __future__ import annotations

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
    WDT_CTRL_ADDR,
    await_smn_resp,
    page_align_window,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
WINDOW_START = VERSION_LO
WINDOW_END = SMC_CHIP_CONFIG_CHIP_ID
# Mapped CSRs outside the VERSION_LO page.
BELOW_CSR = WDT_CTRL_ADDR
ABOVE_CSR = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", 0)
# Second window: the page starting at ABOVE_CSR, one page above the first window.
ADJ_WINDOW_START = ABOVE_CSR
ADJ_WINDOW_END = ABOVE_CSR


class smu_sys_in_filter_window_edge_test_seq:
    """SMN OKAY on filter page interior; DECERR one page either side of the window."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False

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
        adj_lo, adj_hi = page_align_window(ADJ_WINDOW_START, ADJ_WINDOW_END)
        page_bytes = page_hi - page_lo + 1
        below = BELOW_CSR
        above = ABOVE_CSR
        if below >= page_lo or above <= page_hi:
            raise AssertionError(
                f"edge CSRs are inside programmed page "
                f"[0x{page_lo:08x},0x{page_hi:08x}] "
                f"below=0x{below:08x} above=0x{above:08x}"
            )
        if above != page_hi + 1:
            raise AssertionError(
                f"above CSR 0x{above:08x} is not page_hi+1 0x{page_hi + 1:08x} "
                f"for page [0x{page_lo:08x},0x{page_hi:08x}]"
            )
        if adj_lo != page_lo + page_bytes or adj_hi != page_hi + page_bytes:
            raise AssertionError(
                f"adjacent window [0x{adj_lo:08x},0x{adj_hi:08x}] is not the page "
                f"immediately above [0x{page_lo:08x},0x{page_hi:08x}]"
            )
        if not (page_lo <= VERSION_LO <= page_hi):
            raise AssertionError(
                f"VERSION_LO 0x{VERSION_LO:08x} is not inside page "
                f"[0x{page_lo:08x},0x{page_hi:08x}], so it is not one page below "
                f"START 0x{adj_lo:08x}"
            )

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        # SEP=1 wrapper: route ext_in local addresses through the crossbar.
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)

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
        lo_word = int(lo_data) & 0xFFFF_FFFF
        hi_word = int(hi_data) & 0xFFFF_FFFF
        self.s3_ok = True
        self._log(
            f"CHK-FILTER-EDGE-OUT below=0x{below:08x} (-{(page_lo - below) // page_bytes} pages) "
            f"data=0x{lo_word:08x} above=0x{above:08x} (+1 page) "
            f"data=0x{hi_word:08x} DECERR"
        )
        sb.expect_eq("CHK-FILTER-EDGE-BELOW", resp_lo, RESP_DECERR)
        sb.expect_eq("CHK-FILTER-EDGE-ABOVE", resp_hi, RESP_DECERR)

        await program_inbound0_window(
            jtag, ADJ_WINDOW_START, ADJ_WINDOW_END, scoreboard=sb, tag="EDGE_ADJ"
        )
        adj_data, resp_adj = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label=f"edge one page below START 0x{VERSION_LO:08x}",
        )
        adj_word = int(adj_data) & 0xFFFF_FFFF
        self.s4_ok = True
        self._log(
            f"CHK-FILTER-EDGE-START-ADJ addr=0x{VERSION_LO:08x} OKAY under "
            f"[0x{page_lo:08x},0x{page_hi:08x}] then DECERR data=0x{adj_word:08x} under "
            f"[0x{adj_lo:08x},0x{adj_hi:08x}]; START resolved to {page_bytes} bytes"
        )
        sb.expect_eq("CHK-FILTER-EDGE-START-ADJ", resp_adj, RESP_DECERR)
