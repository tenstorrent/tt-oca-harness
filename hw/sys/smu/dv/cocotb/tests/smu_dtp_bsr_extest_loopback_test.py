# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_bsr_extest_loopback_test - P4 EXTEST BSR scan loopback.

Loads IR=EXTEST, shifts compact 8-bit patterns through the TB scan_in<-scan_out
loopback, and checks TDO matches. Also checks one-hot EXTEST decode.

STUB:DECLARED
  name: BSR_TB_SCAN_LOOPBACK
  site: tb_top jtag_bsr_host_scan_in_i <- jtag_bsr_host_scan_out_o
  length: DTP_BSR_MODEL_LEN (compact 8-bit model)
  scope: TB EXTEST DR path only — NOT LIVE pad BSR / SEP STAP proof
  real-path: deferred until a pad-BSR / STAP model is enrolled

Pattern 0x00 is omitted: OcahJtagTap._logic_int maps X/Z TDO to 0, which would
make an all-zero expect can't-fail. Nonzero patterns remain sensitive to stuck-0
/ unresolved TDO (captured 0 != pattern).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    DTP_BSR_MODEL_LEN,
    DTP_EXTEST_DECODED_BIT,
    DTP_IR_EXTEST,
    make_smu_jtag_tap,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# Nonzero-only: VIP X/Z->0 would false-pass an all-zero expect.
_PATTERNS = (0xFF, 0xA5, 0x5A, 0xC3, 0x3C, 0x01)


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


@pyuvm.test()
class smu_dtp_bsr_extest_loopback_test(smu_base_test):
    """EXTEST DR loopback + instruction decode."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        self.logger.info(
            "STUB:DECLARED BSR_TB_SCAN_LOOPBACK "
            "site=tb_top.scan_in<-scan_out len=%d "
            "scope=TB_EXTEST_DR_only (not LIVE pad BSR)",
            DTP_BSR_MODEL_LEN,
        )

        await jtag.shift_ir(DTP_IR_EXTEST)
        await ClockCycles(dut.clk_smu_i, 4)

        decoded = _sample(dut.jtag_ptap_inst_decoded, "jtag_ptap_inst_decoded")
        expect_onehot = 1 << DTP_EXTEST_DECODED_BIT
        sb.expect_eq(
            "EXTEST decode one-hot",
            decoded,
            expect_onehot,
            evidence="BSR_EXTEST_DECODE",
        )

        mask = (1 << DTP_BSR_MODEL_LEN) - 1
        for pattern in _PATTERNS:
            if (pattern & mask) == 0:
                raise AssertionError("zero pattern forbidden (X/Z->0 can't-fail)")
            captured = await jtag.shift_dr(
                pattern & mask,
                width=DTP_BSR_MODEL_LEN,
                back_to_rti=True,
            )
            # Fail-closed observation of TDO pin after VIP capture.
            _sample(dut.jtag_tdo, "jtag_tdo")
            sb.expect_eq(
                f"BSR_EXTEST_TDO_MATCH pat=0x{pattern:02x}",
                int(captured) & mask,
                pattern & mask,
                evidence="BSR_EXTEST_TDO_MATCH",
            )

        self.logger.info(
            "smu_dtp_bsr_extest_loopback_test: BSR_EXTEST_TDO_MATCH %d patterns",
            len(_PATTERNS),
        )
