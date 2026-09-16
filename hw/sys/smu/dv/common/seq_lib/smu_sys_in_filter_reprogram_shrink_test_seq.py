# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_IN inbound0 wide then shrink then clear. SEP=0, no Force."""

from __future__ import annotations

import cocotb
from ocah_axi_vip import RESP_DECERR, RESP_OKAY
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_CHIP_ID,
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    WDT_CTRL_ADDR,
    await_smn_resp,
    clear_inbound0_config,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
NARROW_START = VERSION_LO
NARROW_END = SMC_CHIP_CONFIG_CHIP_ID


class smu_sys_in_filter_reprogram_shrink_test_seq:
    """Wide -> shrink -> clear restores selective / BlockByDefault deny."""

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

        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        _, pre = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label="pre-program VERSION_LO DECERR",
        )
        self.s1_ok = True
        sb.expect_eq("CHK-FILTER-SHRINK-PRE-DECERR", pre, RESP_DECERR)

        await program_inbound0_window(jtag, 0, PASS_ALL_END, scoreboard=sb, tag="WIDE")
        data_w, resp_w = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="wide VERSION_LO OKAY",
        )
        if (int(data_w) & 0xFFFF_FFFF) != VERSION_LO_RESET:
            raise AssertionError(
                f"wide VERSION_LO data=0x{int(data_w) & 0xFFFF_FFFF:08x} "
                f"want 0x{VERSION_LO_RESET:08x}"
            )
        _, resp_wdt = await await_smn_resp(
            master,
            WDT_CTRL_ADDR,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="wide WDT OKAY",
        )
        self.s2_ok = True
        self._log("CHK-FILTER-SHRINK-WIDE VERSION_LO+WDT OKAY")
        sb.expect_eq("CHK-FILTER-SHRINK-WIDE-VER", resp_w, RESP_OKAY)
        sb.expect_eq("CHK-FILTER-SHRINK-WIDE-WDT", resp_wdt, RESP_OKAY)

        await program_inbound0_window(jtag, NARROW_START, NARROW_END, scoreboard=sb, tag="NARROW")
        _, resp_n = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_OKAY,
            clk=dut.clk_smu_i,
            label="narrow VERSION_LO OKAY",
        )
        wdt_data, resp_wdt2 = await await_smn_resp(
            master,
            WDT_CTRL_ADDR,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label="narrow WDT DECERR",
        )
        self.s3_ok = True
        self._log(
            "CHK-FILTER-SHRINK-NARROW VERSION_LO OKAY WDT DECERR "
            f"data=0x{int(wdt_data) & 0xFFFF_FFFF:08x}"
        )
        sb.expect_eq("CHK-FILTER-SHRINK-NARROW-VER", resp_n, RESP_OKAY)
        sb.expect_eq("CHK-FILTER-SHRINK-NARROW-WDT", resp_wdt2, RESP_DECERR)

        await clear_inbound0_config(jtag, scoreboard=sb)
        clr_data, resp_clr = await await_smn_resp(
            master,
            VERSION_LO,
            RESP_DECERR,
            clk=dut.clk_smu_i,
            label="cleared VERSION_LO DECERR",
        )
        self.s4_ok = True
        self._log(
            "AXI_FILTER_OKAY shrink clear restores BlockByDefault "
            f"data=0x{int(clr_data) & 0xFFFF_FFFF:08x}"
        )
        sb.expect_eq(
            "CHK-AXI-FILTER-OKAY cleared VERSION_LO DECERR",
            resp_clr,
            RESP_DECERR,
            evidence="AXI_FILTER_OKAY",
        )
