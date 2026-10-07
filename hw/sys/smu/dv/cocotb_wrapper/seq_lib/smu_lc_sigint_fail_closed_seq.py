# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A broken LC_STATE pair at the SMU raises lc_sigint_err_o and closes the SMC OTP bridge.

The SEP exports LC_STATE as the differential pair ``{~raw, raw}``; the SMC eFuse wrapper
decodes it, and ``lc_sigint_err_o`` is "the decode integrity error (fail-closed)"
(``doc/integrator/src/smu-sep.adoc``), the OR of the SEP and SMC eFuse decode errors
(``hw/sys/smu/doc/port_table.adoc``, ``doc/integrator/src/smu-composition.adoc``). The SMC
OTP JTAG2AXIL path "decodes the state forwarded from SEP" and "on an integrity error it admits
nothing" (``hw/sys/sep/doc/lifecycle_controller.adoc``, debug-path table); a refused request
answers with the data word 0xbadcab1e (``hw/ip/efuse/doc/architecture.adoc``). The SEP OTP
path applies the SEP wrapper's policy, which decodes the SEP's own shadow registers, so a pair
broken after it leaves the SEP does not reach it.

No eFuse image presents a broken pair, so this leaf runs with ``+lc_sigint_inject`` and raises
``lc_sigint_inject_i``: the bench then holds the pair the SEP exports at its pre-inject value
with the n rail of bit 0 inverted (``tb/tb_wrapper_top.sv``, "LC_STATE pair fault inject").
The p rails keep the TEST_DEV state, which admits every access below, so a refusal can come
only from the integrity error.

S1, legal pair: ``lc_sigint_err_o`` is 0 and ``lc_state_o`` carries the TEST_DEV word; an SMC
    OTP write of MAP SPARE[0], its readback and a read of JTAG_PUBLIC_IDENTITY word 0 return
    SUCCESS, and a SEP OTP write of a non-zero pattern to MAP SPARE0 reads back that pattern.
S2, broken pair: once ``lc_state_o`` and the SMC's LC_STATE input -- the forced net, so a
    precondition rather than a check -- carry the broken pair, ``lc_sigint_err_o`` is 1; an
    SMC OTP read of SPARE[0] is refused with 0xBADCAB1E, a write of a second pattern to it is
    refused, and the JTAG_PUBLIC_IDENTITY read that PROD still admits is refused; a SEP OTP
    read of SPARE0 returns SUCCESS with the S1 pattern, so the SEP bridge is live and not
    answering zeros.
S3, pair released: ``lc_sigint_err_o`` is 0 and ``lc_state_o`` carries the TEST_DEV word
    again; SPARE[0] reads back the S1 pattern, so the refused write did not land, the
    JTAG_PUBLIC_IDENTITY read returns SUCCESS, and SEP SPARE0 still reads the S1 pattern.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_SUCCESS,
    SMC_OTP_ERR_DECODE_DATA,
    make_smu_jtag_tap,
)
from seq_lib.smu_lifecycle_table import LC_RAW, lc_raw_from_shadow_preload, lc_state_word
from seq_lib.smu_otp_bridges_under_dbg_disable_seq import SEP_EFUSE_SPARE0, SMC_EFUSE_SPARE0
from seq_lib.smu_otp_prod_error_resp_seq import (
    REFUSED,
    SMC_PUBLIC_IDENTITY,
    _verdict,
    smu_otp_prod_error_resp_seq,
)

LC_TEST_DEV = lc_state_word(LC_RAW["TEST_DEV"])
#: The n rail of bit 0, the rail tb_wrapper_top.sv inverts.
LC_PAIR_FLIP = 0x10
LC_BROKEN = LC_TEST_DEV ^ LC_PAIR_FLIP
PATTERN_KEEP = 0x5EC1_0A7E
PATTERN_REFUSED = 0x0BAD_F00D
SEP_PATTERN = 0x3C5A_A5C3
INJECT_TAKE_CYCLES = 16


class smu_lc_sigint_fail_closed_seq(smu_otp_prod_error_resp_seq):
    """lc_sigint_err_o and the SMC OTP refusal across a broken, then restored, LC_STATE pair."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.steps = {"S1": False, "S2": False, "S3": False}

    def _lc_pins(self) -> tuple[int, int, int]:
        return (
            self._rd("lc_sigint_err_o"),
            self._rd("lc_state_o"),
            self._rd("smc_lc_state_in_o"),
        )

    async def _set_inject(self, value: int, want_lc: int) -> None:
        """Drive the inject input; return once lc_state_o carries the expected word."""
        self.dut.lc_sigint_inject_i.value = value
        for _ in range(INJECT_TAKE_CYCLES):
            await ClockCycles(self.dut.clk_smu_i, 1)
            if self._rd("lc_state_o") == want_lc:
                return
        raise AssertionError(
            f"lc_sigint_inject_i={value}: lc_state_o=0x{self._rd('lc_state_o'):02x} "
            f"never reached 0x{want_lc:02x} within {INJECT_TAKE_CYCLES} clk_smu cycles"
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        if "lc_sigint_inject" not in cocotb.plusargs:
            raise AssertionError("this leaf needs +lc_sigint_inject to arm the bench fault inject")
        preload = cocotb.plusargs.get("sep_shadow_reg_preload")
        raw = lc_raw_from_shadow_preload(str(preload))
        if raw != LC_RAW["TEST_DEV"]:
            raise AssertionError(f"this leaf needs a TEST_DEV shadow image, got raw 0x{raw:x}")
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
        sep = "SEP_OTP_AXI_SINGLE_OP"

        pins = self._lc_pins()
        ops = (
            (await self._otp_op(jtag, smc, J2A_OP_WRITE, SMC_EFUSE_SPARE0, PATTERN_KEEP))[0],
            await self._otp_op(jtag, smc, J2A_OP_READ, SMC_EFUSE_SPARE0),
            (await self._otp_op(jtag, smc, J2A_OP_READ, SMC_PUBLIC_IDENTITY))[0],
            (await self._otp_op(jtag, sep, J2A_OP_WRITE, SEP_EFUSE_SPARE0, SEP_PATTERN))[0],
            await self._otp_op(jtag, sep, J2A_OP_READ, SEP_EFUSE_SPARE0),
        )
        self.log.info("OBSERVATION CHK-LC-SIGINT-LEGAL-PAIR pins=%s ops=%s", pins, ops)
        sb.expect_eq(
            "CHK-LC-SIGINT-LEGAL-PAIR",
            (pins, ops),
            (
                (0, LC_TEST_DEV, LC_TEST_DEV),
                (
                    J2A_STATUS_SUCCESS,
                    (J2A_STATUS_SUCCESS, PATTERN_KEEP),
                    J2A_STATUS_SUCCESS,
                    J2A_STATUS_SUCCESS,
                    (J2A_STATUS_SUCCESS, SEP_PATTERN),
                ),
            ),
            evidence="CHK-LC-SIGINT-LEGAL-PAIR",
        )
        self.steps["S1"] = True

        await self._set_inject(1, LC_BROKEN)
        sigint, lc_out, lc_smc = self._lc_pins()
        self.log.info(
            "OBSERVATION CHK-LC-SIGINT-RAISED sigint=%d lc_state_o=0x%02x smc_lc_state_in=0x%02x",
            sigint,
            lc_out,
            lc_smc,
        )
        # lc_state_o and the SMC input are the forced net itself, so they show
        # only that the inject took; the graded response is lc_sigint_err_o.
        if (lc_out, lc_smc) != (LC_BROKEN, LC_BROKEN):
            raise AssertionError(
                f"inject did not reach the SMC: lc_state_o=0x{lc_out:02x} "
                f"smc_lc_state_in=0x{lc_smc:02x} want 0x{LC_BROKEN:02x}"
            )
        sb.expect_eq("CHK-LC-SIGINT-RAISED", sigint, 1, evidence="CHK-LC-SIGINT-RAISED")
        ops = (
            await self._otp_op(jtag, smc, J2A_OP_READ, SMC_EFUSE_SPARE0),
            (await self._otp_op(jtag, smc, J2A_OP_WRITE, SMC_EFUSE_SPARE0, PATTERN_REFUSED))[0],
            (await self._otp_op(jtag, smc, J2A_OP_READ, SMC_PUBLIC_IDENTITY))[0],
        )
        self.log.info("OBSERVATION CHK-LC-SIGINT-SMC-OTP-CLOSED status %s", ops)
        sb.expect_eq(
            "CHK-LC-SIGINT-SMC-OTP-CLOSED",
            ((_verdict(ops[0][0]), ops[0][1]), _verdict(ops[1]), _verdict(ops[2])),
            ((REFUSED, SMC_OTP_ERR_DECODE_DATA), REFUSED, REFUSED),
            evidence="CHK-LC-SIGINT-SMC-OTP-CLOSED",
        )
        sep_rd = await self._otp_op(jtag, sep, J2A_OP_READ, SEP_EFUSE_SPARE0)
        held = self._rd("lc_sigint_err_o")
        self.log.info(
            "OBSERVATION CHK-LC-SIGINT-SEP-OTP-OPEN status=%d data=0x%08x sigint=%d",
            sep_rd[0],
            sep_rd[1],
            held,
        )
        sb.expect_eq(
            "CHK-LC-SIGINT-SEP-OTP-OPEN",
            (sep_rd, held),
            ((J2A_STATUS_SUCCESS, SEP_PATTERN), 1),
            evidence="CHK-LC-SIGINT-SEP-OTP-OPEN",
        )
        self.steps["S2"] = True

        await self._set_inject(0, LC_TEST_DEV)
        pins = self._lc_pins()
        ops = (
            await self._otp_op(jtag, smc, J2A_OP_READ, SMC_EFUSE_SPARE0),
            (await self._otp_op(jtag, smc, J2A_OP_READ, SMC_PUBLIC_IDENTITY))[0],
            await self._otp_op(jtag, sep, J2A_OP_READ, SEP_EFUSE_SPARE0),
        )
        self.log.info("OBSERVATION CHK-LC-SIGINT-RELEASED pins=%s ops=%s", pins, ops)
        sb.expect_eq(
            "CHK-LC-SIGINT-RELEASED",
            (pins, ops),
            (
                (0, LC_TEST_DEV, LC_TEST_DEV),
                (
                    (J2A_STATUS_SUCCESS, PATTERN_KEEP),
                    J2A_STATUS_SUCCESS,
                    (J2A_STATUS_SUCCESS, SEP_PATTERN),
                ),
            ),
            evidence="CHK-LC-SIGINT-RELEASED",
        )
        self.steps["S3"] = True
