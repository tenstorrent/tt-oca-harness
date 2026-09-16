# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 program via J2A then SMN admit; outside page still DECERR. SEP=0, no Force."""

from __future__ import annotations

import cocotb
from ocah_axi_vip import RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND0_END,
    INBOUND0_START,
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    PASS_RW_CONFIG,
    WDT_CTRL_ADDR,
    await_smn_resp,
    inbound0_config_readback,
    page_align_window,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
WINDOW_START = VERSION_LO
WINDOW_END = SMC_CHIP_CONFIG_CHIP_ID


class smu_sys_in_filter_program_jtag_test_seq:
    """Program inbound0 via J2A; SMN OKAY inside, DECERR outside."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s1_ok = False
        self.s2_ok = False
        self.s3_ok = False
        self.s4_ok = False
        self.s5_ok = False

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
        self._log(f"CHK-FILTER-PROG-GATE-OPEN disable={gate}")
        sb.expect_eq("CHK-FILTER-PROG-GATE-OPEN", gate, 0)

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        pre_data, pre_resp = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label="pre-program VERSION_LO DECERR",
        )
        self.s2_ok = True
        self._log(f"CHK-FILTER-PROG-PRE-DECERR data=0x{int(pre_data) & 0xFFFF_FFFF:08x}")
        sb.expect_eq("CHK-FILTER-PROG-PRE-DECERR", pre_resp, RESP_DECERR)

        await program_inbound0_window(jtag, WINDOW_START, WINDOW_END, scoreboard=sb, tag="PROG")
        cfg_rb = await inbound0_config_readback(jtag)
        if cfg_rb != (PASS_RW_CONFIG & 0xFFFF_FFFF):
            raise AssertionError(
                f"INBOUND0_CONFIG readback want 0x{PASS_RW_CONFIG:x} got 0x{cfg_rb:x}"
            )
        st_s, start_rb = await jtag2axi_single_read(jtag, INBOUND0_START, require_complete=True)
        require_jtag_tdo_resolved("INBOUND0_START readback")
        st_e, end_rb = await jtag2axi_single_read(jtag, INBOUND0_END, require_complete=True)
        require_jtag_tdo_resolved("INBOUND0_END readback")
        if st_s != J2A_STATUS_SUCCESS or int(start_rb) != page_lo:
            raise AssertionError(
                f"START rb status={st_s} data=0x{int(start_rb):x} want 0x{page_lo:x}"
            )
        if st_e != J2A_STATUS_SUCCESS or int(end_rb) != page_hi:
            raise AssertionError(f"END rb status={st_e} data=0x{int(end_rb):x} want 0x{page_hi:x}")
        self.s3_ok = True
        self._log(f"CHK-FILTER-PROG-WINDOW cfg=0x{cfg_rb:x} page=[0x{page_lo:08x},0x{page_hi:08x}]")
        sb.expect_eq("CHK-FILTER-PROG-WINDOW", cfg_rb, PASS_RW_CONFIG & 0xFFFF_FFFF)

        post_data, post_resp = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="post-program VERSION_LO OKAY",
        )
        if (int(post_data) & 0xFFFF_FFFF) != VERSION_LO_RESET:
            raise AssertionError(
                f"post-program VERSION_LO data=0x{int(post_data) & 0xFFFF_FFFF:08x} "
                f"want 0x{VERSION_LO_RESET:08x}"
            )
        self.s4_ok = True
        self._log(f"AXI_FILTER_OKAY post VERSION_LO data=0x{int(post_data) & 0xFFFF_FFFF:08x}")
        sb.expect_eq(
            "CHK-AXI-FILTER-OKAY post VERSION_LO",
            post_resp,
            RESP_OKAY,
            evidence="AXI_FILTER_OKAY",
        )

        out_data, out_resp = await await_smn_resp(
            master,
            WDT_CTRL_ADDR,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label="WDT outside window DECERR",
        )
        self.s5_ok = True
        self._log(f"CHK-FILTER-PROG-OUT-DECERR WDT data=0x{int(out_data) & 0xFFFF_FFFF:08x}")
        sb.expect_eq("CHK-FILTER-PROG-OUT-DECERR", out_resp, RESP_DECERR)
