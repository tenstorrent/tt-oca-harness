# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PTAP OTP instruction IR/DR scan (SEP=0, no Force).

S1: After TCK sync, OTP gate is open; ``SMC_OTP_JTAG2AXI_CAPS`` matches the
    14-bit AXI4-Lite packing.
S2: ``SEP_OTP_JTAG2AXI_CAPS`` matches the same packing (CAPS TDR is present
    even when the SEP AXI bridge is not).
S3: ``JTAG_CAPS`` bit 42 ``sep_dbg_en`` is 0 (SEP debug bridges absent).
S4: SMC OTP ``SINGLE_OP`` NO_OP TDR echoes a non-zero probe (chain live).
    SEP OTP ``SINGLE_OP`` IR selects 1-bit BYPASS: 2-bit scan TDI=0b01
    returns 0b10 (capture-0 then shift-echo-1).

Opcodes from ``seq_lib.smu_jtag_helpers.dtp_ir_opcode``, i.e. ``DtpJtagInstr``
transcribed from the "Instruction Encodings" table of
``hw/ip/jtag/jtag_intf_unit/doc/interface.adoc``. No MAP R/W (that is map_rw /
complete_rw). Not claimed: Force-closed OTP gate; SECURE_TM; SEP=1 bridge.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS,
    DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS,
    DTP_IR_SEP_OTP_AXI_SINGLE_OP,
    DTP_IR_WIDTH,
    DTP_JTAG_CAPS_SEP_DBG_EN_BIT,
    J2A_OP_NOP,
    SMC_OTP_SINGLE_OP_LEN,
    make_smu_jtag_tap,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
)

LIVENESS_ADDR = 0xA5C3_1E96
LIVENESS_DATA = 0x5A3C_E169
CAPS_MASK = (1 << 14) - 1
JTAG_CAPS_MASK = (1 << 60) - 1


class smu_dtp_ptap_otp_instr_scan_test_seq:
    """PTAP OTP CAPS + SINGLE_OP chain liveness; SEP bridge absent."""

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
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-PTAP-OTP-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_otp_jtag2axi_security_disable") & 1
        if gate != 0:
            raise AssertionError(f"OTP J2A still gated after TCK sync: security_disable={gate}")
        smc_caps = int(await jtag.read("SMC_OTP_JTAG2AXI_CAPS")) & CAPS_MASK
        require_jtag_tdo_resolved("SMC OTP CAPS")
        if smc_caps != DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC OTP CAPS=0x{smc_caps:04x} want 0x{DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-PTAP-SMC-OTP-CAPS caps=0x{smc_caps:04x}")
        sb.expect_eq(
            "CHK-PTAP-SMC-OTP-CAPS",
            smc_caps,
            DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS,
            evidence="PTAP_SMC_OTP_CAPS_OK",
        )

        sep_caps = int(await jtag.read("SEP_OTP_JTAG2AXI_CAPS")) & CAPS_MASK
        require_jtag_tdo_resolved("SEP OTP CAPS")
        if sep_caps != DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SEP OTP CAPS=0x{sep_caps:04x} want 0x{DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS:04x}"
            )
        self.s2_ok = True
        self._log(f"CHK-PTAP-SEP-OTP-CAPS caps=0x{sep_caps:04x}")
        sb.expect_eq(
            "CHK-PTAP-SEP-OTP-CAPS",
            sep_caps,
            DTP_EXPECTED_SEP_OTP_JTAG2AXI_CAPS,
            evidence="PTAP_SEP_OTP_CAPS_OK",
        )

        jcaps = int(await jtag.read("JTAG_CAPS")) & JTAG_CAPS_MASK
        require_jtag_tdo_resolved("JTAG_CAPS")
        sep_dbg = (jcaps >> DTP_JTAG_CAPS_SEP_DBG_EN_BIT) & 1
        if sep_dbg != 0:
            raise AssertionError(
                f"JTAG_CAPS sep_dbg_en={sep_dbg} want 0 on SEP=0 (caps=0x{jcaps:015x})"
            )
        self.s3_ok = True
        self._log(f"CHK-PTAP-JTAG-CAPS-SEP-DBG caps=0x{jcaps:015x} sep_dbg_en=0")
        sb.expect_eq(
            "CHK-PTAP-JTAG-CAPS-SEP-DBG",
            sep_dbg,
            0,
            evidence="PTAP_SEP_DBG_EN_0",
        )

        probe = pack_otp_single_op(J2A_OP_NOP, LIVENESS_ADDR, LIVENESS_DATA)
        await jtag.write("SMC_OTP_AXI_SINGLE_OP", probe)
        require_jtag_tdo_resolved("SMC OTP SINGLE_OP probe")
        echo = int(await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0))
        require_jtag_tdo_resolved("SMC OTP SINGLE_OP echo")
        echo_mask = (1 << SMC_OTP_SINGLE_OP_LEN) - 1
        # Status bits of this echo ARE the OP field (NOP=0=SUCCESS). The
        # non-zero addr/data echo is the liveness proof; all-zero would
        # fake OKAY.
        if (echo & echo_mask) != (probe & echo_mask):
            raise AssertionError(
                f"SMC OTP SINGLE_OP TDR did not echo probe in=0x{probe:x} out=0x{echo:x}"
            )

        await jtag.shift_ir(DTP_IR_SEP_OTP_AXI_SINGLE_OP, width=DTP_IR_WIDTH, back_to_rti=False)
        byp = int(await jtag.shift_dr(0b01, 2, back_to_rti=True)) & 0x3
        require_jtag_tdo_resolved("SEP OTP SINGLE_OP BYPASS")
        if byp != 0b10:
            raise AssertionError(
                f"SEP OTP SINGLE_OP IR must select 1-bit BYPASS on SEP=0: "
                f"2-bit TDI=0b01 got 0b{byp:02b} want 0b10 "
                "(stuck-0 chain returns 0b00)"
            )
        self.s4_ok = True
        self._log(f"CHK-PTAP-OTP-SINGLE-OP-IRDR smc_echo=0x{echo:x} sep_bypass=0b{byp:02b}")
        sb.expect_eq(
            "CHK-PTAP-OTP-SINGLE-OP-IRDR",
            (echo & echo_mask, byp),
            (probe & echo_mask, 0b10),
            evidence="PTAP_OTP_SINGLE_OP_IRDR_OK",
        )

        self._log(
            f"PASS DTP-PTAP-OTP-INSTR-SCAN s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} sep_dbg_en=0"
        )
