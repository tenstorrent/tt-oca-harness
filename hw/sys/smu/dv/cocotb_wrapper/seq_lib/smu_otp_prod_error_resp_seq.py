# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OTP bridges under the PROD lifecycle state, where the eFuse JTAG policy refuses them.

In PROD the eFuse JTAG policy blocks every JTAG write and every JTAG read
except the chiplet identity, and a blocked request gets an error response
whose read data is 0xbadcab1e (``hw/ip/efuse/doc/architecture.adoc``, "eFuse
lifecycle-based JTAG permissions"). On the SMC the admitted read range is
JTAG_PUBLIC_IDENTITY, "the JTAG-public exception window" (``smc_efuse_map.rdl``;
``hw/sys/sep/doc/lifecycle_controller.adoc``: in PROD the SMC wrapper "admits
no writes at all"). On the SEP, JTAG may reach only the eFuse MMR token block
-- the token-input arrays, TOKEN_EOP and the match-status registers -- and
every other access completes with an error response
(``hw/sys/sep/doc/otp_fuse_controller.adoc``). Neither chapter names the AXI
response code, so a refusal is checked as SLVERR or DECERR, and the code is
recorded.

S1: an SMC OTP read and write of MAP SPARE[0] are refused, the read with
    0xBADCAB1E, and a read of JTAG_PUBLIC_IDENTITY word 0 returns SUCCESS.
S2: a SEP OTP read and write of MAP SPARE0 are refused, the read with
    0xBADCAB1E, and a write of a security-disable token word and a read of the
    token match status, both in the eFuse MMR token block, return SUCCESS.
S3: the cool reset pin holds the SMC in reset while it is asserted, and after
    the release an SMC OTP read of JTAG_PUBLIC_IDENTITY word 0 again returns
    SUCCESS.
S4: an SMC OTP series read of JTAG_PUBLIC_IDENTITY word 0 with pipeline depth
    3, so the bridge issues three reads ahead of the data shifts, completes
    with SUCCESS.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, smc_addr
from seq_lib.smu_dtp_sep_dm_sba_test_seq import _indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    SMC_OTP_AXSIZE_4B,
    SMC_OTP_ERR_DECODE_DATA,
    make_smu_jtag_tap,
    otp_jtag2axi_series_no_incr_read,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
)
from seq_lib.smu_lifecycle_table import lc_raw_from_shadow_preload, lc_state_name
from seq_lib.smu_otp_bridges_under_dbg_disable_seq import (
    _SEP_ADDR_H,
    OTP_POLL,
    SEP_EFUSE_SPARE0,
    SMC_EFUSE_SPARE0,
    SmuOtpBridgesUnderDbgDisableSeq,
)

SMC_PUBLIC_IDENTITY = smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR")
SEP_MMR_WORD = _indexed_addr("SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_I_BASE_ADDR", 0)
SEP_MMR_STATUS = c_header_u32(_SEP_ADDR_H, "SEP_TOP_EFUSE_MMR_SEC_DISABLE_TOKEN_MATCH_BASE_ADDR")
PATTERN = 0x0BAD_F00D
SERIES_DEPTH = 3
COOL_RESET_HOLD_REF_CYCLES = 256
SMC_RESET_BOUND_REF_CYCLES = 8192
REFUSED = "refused"


def _verdict(status: int) -> int | str:
    """Fold the two AXI error responses into one verdict; keep every other status."""
    return REFUSED if status in (J2A_STATUS_SLVERR, J2A_STATUS_DECERR) else status


class smu_otp_prod_error_resp_seq(SmuOtpBridgesUnderDbgDisableSeq):
    """SMC and SEP OTP bridge error responses under PROD, and the accesses PROD keeps."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"S1": False, "S2": False, "S3": False, "S4": False}

    async def _otp_op(self, jtag, reg: str, op: int, addr: int, data: int = 0):
        raw = pack_otp_single_op(op, addr, data, wstrb=0xF, size=SMC_OTP_AXSIZE_4B)
        await jtag.write(reg, raw)
        require_jtag_tdo_resolved(f"{reg} issue @0x{addr:08x}")
        await ClockCycles(self.dut.clk_smu_i, 32)
        status, rdata = J2A_STATUS_BUSY, 0
        for _ in range(OTP_POLL):
            capt = await jtag.read(reg, shift_value=0)
            require_jtag_tdo_resolved(f"{reg} poll @0x{addr:08x}")
            status, rdata = unpack_otp_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 16)
        return status, int(rdata) & 0xFFFF_FFFF

    async def _smc_reset(self) -> int:
        """Hold the cool reset pin; return the SMC reset seen while it is held."""
        dut = self.dut
        dut.tb_cool_reset_pin.value = 1
        await ClockCycles(dut.clk_ref_i, COOL_RESET_HOLD_REF_CYCLES)
        held = int(dut.obs_smc_rst_n_o.value)
        dut.tb_cool_reset_pin.value = 0
        for _ in range(SMC_RESET_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            if int(dut.obs_smc_rst_n_o.value) == 1:
                return held
        raise AssertionError("SMC never left the cool reset")

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        state = lc_state_name(lc_raw_from_shadow_preload(str(preload)))
        assert state == "PROD", f"this leaf needs the PROD shadow image, got {state}"
        await self._await_posture_settled()

        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"TAP not answering: IDCODE 0x{idcode:08x}")

        smc = "SMC_OTP_AXI_SINGLE_OP"
        raw = (
            await self._otp_op(jtag, smc, J2A_OP_READ, SMC_EFUSE_SPARE0),
            (await self._otp_op(jtag, smc, J2A_OP_WRITE, SMC_EFUSE_SPARE0, PATTERN))[0],
            (await self._otp_op(jtag, smc, J2A_OP_READ, SMC_PUBLIC_IDENTITY))[0],
        )
        self._log_chk("OBSERVATION CHK-OTP-PROD-SMC-REFUSED status", raw)
        observed = ((_verdict(raw[0][0]), raw[0][1]), _verdict(raw[1]), _verdict(raw[2]))
        sb.expect_eq(
            "CHK-OTP-PROD-SMC-REFUSED",
            observed,
            ((REFUSED, SMC_OTP_ERR_DECODE_DATA), REFUSED, J2A_STATUS_SUCCESS),
            evidence="CHK-OTP-PROD-SMC-REFUSED",
        )
        self.steps["S1"] = True

        sep = "SEP_OTP_AXI_SINGLE_OP"
        raw = (
            await self._otp_op(jtag, sep, J2A_OP_READ, SEP_EFUSE_SPARE0),
            (await self._otp_op(jtag, sep, J2A_OP_WRITE, SEP_EFUSE_SPARE0, PATTERN))[0],
            (await self._otp_op(jtag, sep, J2A_OP_WRITE, SEP_MMR_WORD, PATTERN))[0],
            (await self._otp_op(jtag, sep, J2A_OP_READ, SEP_MMR_STATUS))[0],
        )
        await self._otp_op(jtag, sep, J2A_OP_WRITE, SEP_MMR_WORD, 0)
        self._log_chk("OBSERVATION CHK-OTP-PROD-SEP-REFUSED status", raw)
        observed = (
            (_verdict(raw[0][0]), raw[0][1]),
            _verdict(raw[1]),
            _verdict(raw[2]),
            _verdict(raw[3]),
        )
        sb.expect_eq(
            "CHK-OTP-PROD-SEP-REFUSED",
            observed,
            (
                (REFUSED, SMC_OTP_ERR_DECODE_DATA),
                REFUSED,
                J2A_STATUS_SUCCESS,
                J2A_STATUS_SUCCESS,
            ),
            evidence="CHK-OTP-PROD-SEP-REFUSED",
        )
        self.steps["S2"] = True

        held = await self._smc_reset()
        await ClockCycles(self.dut.clk_smu_i, 200)
        after = (await self._otp_op(jtag, smc, J2A_OP_READ, SMC_PUBLIC_IDENTITY))[0]
        self._log_chk("CHK-OTP-PROD-SMC-RESET", (held, after))
        sb.expect_eq(
            "CHK-OTP-PROD-SMC-RESET",
            (held, after),
            (0, J2A_STATUS_SUCCESS),
            evidence="CHK-OTP-PROD-SMC-RESET",
        )
        self.steps["S3"] = True

        series = await otp_jtag2axi_series_no_incr_read(
            jtag, SMC_PUBLIC_IDENTITY, pipeline_depth=SERIES_DEPTH
        )
        self._log_chk("CHK-OTP-PROD-SMC-SERIES", series)
        sb.expect_eq(
            "CHK-OTP-PROD-SMC-SERIES",
            series[0],
            J2A_STATUS_SUCCESS,
            evidence="CHK-OTP-PROD-SMC-SERIES",
        )
        self.steps["S4"] = True

    def _log_chk(self, name: str, observed) -> None:
        self.log.info("%s %s", name, observed)
