# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP J2A mid-BUSY abort, observed on the aborted op, then fabric VERSION_LO recovery.

The abort is proven on the thing that was aborted: after the TAP reset the OTP
SINGLE_OP DR is captured again and must no longer report BUSY. The fabric
VERSION_LO reads that follow show the bridge is usable afterwards. Requires
+skip_fuse_sense. SEP=1, no Force.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    SMC_CHIP_CONFIG_VERSION_LO,
    SMC_CHIP_CONFIG_VERSION_LO_RESET,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_JTAG2AXI_CAPS,
    J2A_OP_READ,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_OTP_AXSIZE_4B,
    SMC_OTP_DEFAULT_PROBE_ADDR,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    pack_otp_single_op,
    require_jtag_tdo_resolved,
    unpack_otp_single_op,
)

VERSION_LO = SMC_CHIP_CONFIG_VERSION_LO
VERSION_LO_RESET = SMC_CHIP_CONFIG_VERSION_LO_RESET
OTP_POLL = 128


class smu_dtp_jtag2axi_abort_mid_op_test_seq:
    """IR+TRST abort of a hung OTP SINGLE_OP, seen on its status; fabric J2A recovers."""

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
        sb.expect_eq("CHK-ABORT-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        otp_gate = self._sample_int("tb_otp_jtag2axi_security_disable") & 1
        fab_gate = self._sample_int("tb_smc_jtag2axi_security_disable") & 1
        if otp_gate != 0 or fab_gate != 0:
            raise AssertionError(
                f"J2A gated after TCK sync: otp_disable={otp_gate} smc_disable={fab_gate}"
            )
        caps = int(await jtag.read("SMC_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("SMC J2A CAPS")
        if caps != DTP_EXPECTED_SMC_JTAG2AXI_CAPS:
            raise AssertionError(
                f"SMC J2A CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_JTAG2AXI_CAPS:04x}"
            )
        self.s1_ok = True
        self._log(f"CHK-ABORT-GATE-OPEN otp={otp_gate} smc={fab_gate} caps=0x{caps:04x}")
        sb.expect_eq(
            "CHK-ABORT-GATE-OPEN",
            (otp_gate, fab_gate, caps),
            (0, 0, DTP_EXPECTED_SMC_JTAG2AXI_CAPS),
        )

        raw = pack_otp_single_op(
            J2A_OP_READ,
            SMC_OTP_DEFAULT_PROBE_ADDR,
            0,
            wstrb=0,
            size=SMC_OTP_AXSIZE_4B,
        )
        await jtag.write("SMC_OTP_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved("OTP SINGLE_OP issue +0x80")
        await ClockCycles(self.dut.clk_smu_i, 32)

        busy_st = None
        for poll in range(8):
            capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"OTP SINGLE_OP BUSY poll {poll}")
            busy_st, _ = unpack_otp_single_op(capt)
            if busy_st == J2A_STATUS_BUSY:
                break
            await ClockCycles(self.dut.clk_smu_i, 8)
        if busy_st != J2A_STATUS_BUSY:
            raise AssertionError(
                f"OTP +0x80 status={busy_st} want BUSY={J2A_STATUS_BUSY} "
                "(abort needs an outstanding op)"
            )
        self.s2_ok = True
        self._log(f"CHK-ABORT-BUSY OTP +0x80 status=BUSY probe=0x{SMC_OTP_DEFAULT_PROBE_ADDR:x}")
        sb.expect_eq("CHK-ABORT-BUSY", busy_st, J2A_STATUS_BUSY)

        idc = int(await jtag.read("IDCODE", shift_value=0)) & 0xFFFF_FFFF
        require_jtag_tdo_resolved("IDCODE mid-BUSY")
        if idc != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE mid-BUSY want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idc:08x}")
        # MUTATION-ANCHOR abort-trst -- the TAP reset this test is about. The
        # recheck recipe in the plan entry deletes the call on the next line and
        # no other: run() opens with a bring-up reset_tap() whose four following
        # lines are textually identical, and deleting that one runs a different
        # experiment than the one documented. Grep this label, not the call.
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        self.s3_ok = True
        self._log("CHK-ABORT-IR-TRST IDCODE mid-BUSY then TAP reset")
        sb.expect_eq("CHK-ABORT-IR-TRST", idc, DTP_DEFAULT_IDCODE)

        # The op that was hung: its status after the reset is the abort evidence.
        # A bridge that kept the AXI state machine waiting would still say BUSY.
        await ClockCycles(self.dut.clk_smu_i, 32)
        capt = await jtag.read("SMC_OTP_AXI_SINGLE_OP", shift_value=0)
        require_jtag_tdo_resolved("OTP SINGLE_OP status after TAP reset")
        otp_st_after, _ = unpack_otp_single_op(capt)
        if otp_st_after == J2A_STATUS_BUSY:
            raise AssertionError(
                "OTP SINGLE_OP still BUSY after the TAP reset: the outstanding op was not aborted"
            )
        self._log(f"CHK-J2A-ABORT OTP SINGLE_OP status after TAP reset={otp_st_after} (not BUSY)")

        recovered = []
        for i in range(2):
            st, rdata = await jtag2axi_single_read(
                jtag,
                VERSION_LO,
                size=SMC_DBG_AXSIZE_4B,
                poll_limit=OTP_POLL,
                require_complete=True,
            )
            data = int(rdata) & 0xFFFF_FFFF
            if st != J2A_STATUS_SUCCESS or data != VERSION_LO_RESET:
                raise AssertionError(
                    f"post-abort VERSION_LO[{i}] @0x{VERSION_LO:08x} "
                    f"status={st} data=0x{data:08x} "
                    f"want SUCCESS+0x{VERSION_LO_RESET:08x}"
                )
            recovered.append(data)
            self._log(f"CHK-J2A-ABORT VERSION_LO[{i}]=0x{data:08x} status=SUCCESS")
        self.s4_ok = True
        sb.expect_eq(
            "CHK-J2A-ABORT",
            (otp_st_after != J2A_STATUS_BUSY, *recovered),
            (True, VERSION_LO_RESET, VERSION_LO_RESET),
        )

        self._log(
            f"PASS JTAG2AXI-ABORT s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} probe=+0x{SMC_OTP_DEFAULT_PROBE_ADDR:x}"
        )
