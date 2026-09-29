# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI unmapped DECERR then VERSION_LO + SPM series recovery. SEP=1, no Force."""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
    SMC_LOCAL_XBAR_UNMAPPED_GAP,
    smc_addr,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_series_incr_read,
    jtag2axi_series_incr_write,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
    smc_series_data_mask,
)

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
UNMAPPED = SMC_LOCAL_XBAR_UNMAPPED_GAP
SPM = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SERIES_ADDR = SPM + 0x40
SERIES_PAT = 0x0102_0304_0506_0708
OTP_POLL = 128


class smu_dtp_jtag2axi_smc_error_path_test_seq:
    """SMC fabric J2A unmapped DECERR + recovery; gate open on the SEP=1 wrapper."""

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

    async def _rd32(self, jtag, addr: int, name: str) -> tuple[int, int]:
        st, rdata = await jtag2axi_single_read(
            jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            poll_limit=OTP_POLL,
            require_complete=True,
        )
        return st, int(rdata) & 0xFFFF_FFFF

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-J2A-ERROR-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"SMC J2A still gated after TCK sync: security_disable={gate}")
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-J2A-ERROR-GATE-OPEN disable={gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-J2A-ERROR-GATE-OPEN",
            (gate, caps),
            (0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        allow_st, allow_data = await self._rd32(jtag, VERSION_LO, "VERSION_LO-ALLOW")
        if allow_st != J2A_STATUS_SUCCESS or allow_data != VERSION_LO_RESET:
            raise AssertionError(
                f"VERSION_LO allow @0x{VERSION_LO:08x} status={allow_st} "
                f"data=0x{allow_data:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s2_ok = True
        self._log(f"CHK-J2A-ERROR-ALLOW @0x{VERSION_LO:08x} data=0x{allow_data:08x} status=SUCCESS")
        sb.expect_eq("CHK-J2A-ERROR-ALLOW", allow_data, VERSION_LO_RESET)

        hole_st, hole_data = await self._rd32(jtag, UNMAPPED, "UNMAPPED")
        if hole_st == J2A_STATUS_SUCCESS:
            raise AssertionError(f"unmapped @0x{UNMAPPED:08x} returned OKAY data=0x{hole_data:08x}")
        if hole_st != J2A_STATUS_DECERR:
            raise AssertionError(
                f"unmapped @0x{UNMAPPED:08x} status={hole_st} want DECERR={J2A_STATUS_DECERR}"
            )
        self.s3_ok = True
        self._log(f"CHK-J2A-DECERR @0x{UNMAPPED:08x} status=DECERR data=0x{hole_data:08x}")
        sb.expect_eq("CHK-J2A-DECERR", hole_st, J2A_STATUS_DECERR, evidence="J2A_DECERR_POISON")

        rec_st, rec_data = await self._rd32(jtag, VERSION_LO, "VERSION_LO-RECOVERY")
        if rec_st != J2A_STATUS_SUCCESS or rec_data != VERSION_LO_RESET:
            raise AssertionError(
                f"VERSION_LO recovery @0x{VERSION_LO:08x} status={rec_st} "
                f"data=0x{rec_data:08x} want SUCCESS+0x{VERSION_LO_RESET:08x}"
            )
        self.s4_ok = True
        self._log(
            f"CHK-J2A-RECOVERY @0x{VERSION_LO:08x} data=0x{rec_data:08x} "
            f"status=SUCCESS after unmapped=0x{UNMAPPED:08x}"
        )
        sb.expect_eq("CHK-J2A-RECOVERY", rec_data, VERSION_LO_RESET, evidence="J2A_RECOVERY_OK")

        mask = smc_series_data_mask(SMC_DBG_AXSIZE_8B)
        want = SERIES_PAT & mask
        wr_st = await jtag2axi_series_incr_write(jtag, SERIES_ADDR, want, poll_limit=OTP_POLL)
        if wr_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC series INCR WR after DECERR @0x{SERIES_ADDR:08x} "
                f"status={wr_st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        rd_st, got_ser = await jtag2axi_series_incr_read(jtag, SERIES_ADDR, poll_limit=OTP_POLL)
        got_ser &= mask
        if rd_st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"SMC series INCR RD after DECERR @0x{SERIES_ADDR:08x} "
                f"status={rd_st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        if got_ser != want:
            raise AssertionError(
                f"SMC series INCR after DECERR @0x{SERIES_ADDR:08x}: "
                f"want 0x{want:016x} got 0x{got_ser:016x}"
            )
        self.s5_ok = True
        self._log(
            f"CHK-J2A-ERROR-SERIES-INCR @0x{SERIES_ADDR:08x} data=0x{got_ser:016x} status=SUCCESS"
        )
        sb.expect_eq("CHK-J2A-ERROR-SERIES-INCR", got_ser, want)

        self._log(
            f"PASS JTAG2AXI-SMC-ERROR s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} s5={self.s5_ok} "
            f"unmapped=0x{UNMAPPED:08x} version_lo=0x{VERSION_LO:08x}"
        )
