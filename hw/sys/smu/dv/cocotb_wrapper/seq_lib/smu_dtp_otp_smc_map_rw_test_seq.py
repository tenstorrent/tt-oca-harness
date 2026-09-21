# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OTP JTAG2AXI write/readback of eFuse MAP SPARE[0] (SEP=1, no Force).

S1: After TCK sync, ``tb_otp_jtag2axi_security_disable`` reads 0 -- the OTP
    J2A gate is open in this configuration. ``lc_state_o`` is the no-LCC
    word of ``seq_lib.smu_lifecycle_table`` (not PROD), so the eFuse JTAG
    demux stays off err_slv.
S2: ``SMC_OTP_JTAG2AXI_CAPS`` matches the 14-bit packing of
    ``hw/ip/jtag/jtag_ptap/doc/architecture.adoc``.
S3: Write PATTERN_A to MAP SPARE[0], readback OKAY + data match.
S4: Write PATTERN_C (distinct) and readback — proves the write path is live.

Address from ``smc_addr.h`` ``SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR(0)``.

Not claimed: Force-closed OTP gate / PATTERN_B no-stick (needs LCC or Force);
SEP OTP; series NO_INCR.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS,
    J2A_STATUS_SUCCESS,
    make_smu_jtag_tap,
    otp_jtag2axi_single_read,
    otp_jtag2axi_single_write,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_lifecycle_table import LC_STATE_NO_LCC

SPARE0 = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
PATTERN_A = 0xA5A5_5A5A
PATTERN_C = 0x3C3C_C3C3
OTP_POLL = 128


class smu_dtp_otp_smc_map_rw_test_seq:
    """OTP J2A MAP SPARE[0] allow-path R/W; gate open on the SEP=1 wrapper."""

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

    async def _otp_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await otp_jtag2axi_single_write(
            jtag, addr, data, poll_limit=OTP_POLL, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP J2A WR {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"OTP J2A WR {name} @0x{addr:08x} data=0x{data:08x} status=SUCCESS")

    async def _otp_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await otp_jtag2axi_single_read(
            jtag, addr, poll_limit=OTP_POLL, require_complete=True
        )
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(
                f"OTP J2A RD {name} @0x{addr:08x} status={st} want SUCCESS={J2A_STATUS_SUCCESS}"
            )
        self._log(f"OTP J2A RD {name} @0x{addr:08x} data=0x{int(rdata):08x} status=SUCCESS")
        return int(rdata) & 0xFFFF_FFFF

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        # feat_ctrl is 2-flop synced on TCK (ResetValue=0). Idle TMS opens the gate.
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        sb.expect_eq("CHK-OTP-SMC-MAP-JTAG-READY", idcode, DTP_DEFAULT_IDCODE)

        gate = self._sample_int("tb_otp_jtag2axi_security_disable") & 1
        lc = self._sample_int("lc_state_o") & 0xFF
        sigint = self._sample_int("lc_sigint_err_o") & 1
        if gate != 0:
            raise AssertionError(f"OTP J2A still gated after TCK sync: security_disable={gate}")
        if lc != LC_STATE_NO_LCC:
            raise AssertionError(
                f"lc_state_o=0x{lc:02x} want 0x{LC_STATE_NO_LCC:02x} "
                "(PROD would steer eFuse JTAG demux to err_slv)"
            )
        if sigint != 0:
            raise AssertionError(f"lc_sigint_err_o={sigint} want 0 (demux err_slv)")
        self.s1_ok = True
        self._log(f"CHK-OTP-SMC-MAP-GATE-OPEN disable={gate} lc=0x{lc:02x} sigint={sigint}")
        sb.expect_eq("CHK-OTP-SMC-MAP-GATE-OPEN", gate, 0)

        caps = int(await jtag.read("SMC_OTP_JTAG2AXI_CAPS")) & ((1 << 14) - 1)
        require_jtag_tdo_resolved("OTP CAPS")
        if caps != DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS:
            raise AssertionError(
                f"OTP CAPS=0x{caps:04x} want 0x{DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS:04x}"
            )
        self.s2_ok = True
        self._log(f"CHK-OTP-SMC-MAP-CAPS caps=0x{caps:04x} spare0=0x{SPARE0:08x}")
        sb.expect_eq("CHK-OTP-SMC-MAP-CAPS", caps, DTP_EXPECTED_SMC_OTP_JTAG2AXI_CAPS)

        await self._otp_wr(jtag, SPARE0, PATTERN_A, "SPARE0-A")
        got_a = await self._otp_rd(jtag, SPARE0, "SPARE0-A")
        if got_a != PATTERN_A:
            raise AssertionError(
                f"SPARE[0] readback after A want 0x{PATTERN_A:08x} got 0x{got_a:08x}"
            )
        self.s3_ok = True
        sb.expect_eq("CHK-OTP-SMC-MAP-RW", got_a, PATTERN_A, evidence="CHK-OTP-SMC-MAP-RW")

        await self._otp_wr(jtag, SPARE0, PATTERN_C, "SPARE0-C")
        got_c = await self._otp_rd(jtag, SPARE0, "SPARE0-C")
        if got_c != PATTERN_C:
            raise AssertionError(
                f"SPARE[0] readback after C want 0x{PATTERN_C:08x} got 0x{got_c:08x}"
            )
        if got_c == PATTERN_A:
            raise AssertionError("SPARE[0] still holds PATTERN_A; write path is dead")
        self.s4_ok = True
        sb.expect_eq("CHK-OTP-SMC-MAP-ALLOW-PATH", got_c, PATTERN_C)

        self._log(
            f"PASS DTP-OTP-SMC-MAP-RW s1={self.s1_ok} s2={self.s2_ok} "
            f"s3={self.s3_ok} s4={self.s4_ok} spare0=0x{SPARE0:08x}"
        )
