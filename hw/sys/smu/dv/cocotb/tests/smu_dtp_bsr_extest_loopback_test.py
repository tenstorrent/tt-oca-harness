# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_bsr_extest_loopback_test - P4 EXTEST BSR scan loopback.

Loads IR=EXTEST, shifts compact 8-bit patterns through the TB scan_in<-scan_out
loopback, and checks TDO matches. Also checks one-hot EXTEST decode.

Does NOT claim functional pad BSR or SEP STAP.

Pattern 0x00 is omitted: OcahJtagTap._logic_int maps X/Z TDO to 0, which would
make an all-zero expect can't-fail. Nonzero patterns remain sensitive to stuck-0
/ unresolved TDO (captured 0 != pattern).
"""

from __future__ import annotations

import cocotb
import pyuvm
from ocah_jtag_vip import OcahJtagDevice, OcahJtagTap
from cocotb.triggers import ClockCycles

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


def _make_ptap(dut, period_ns: float, *, regs: tuple[str, ...] = ("DEBUG_CONTROL",)) -> OcahJtagTap:
    """Build OcahJtagTap against real TB JTAG pins (no Force / no fake DUT)."""
    device = OcahJtagDevice(
        name="smu_ptap",
        idcode=0x0000_0001,
        ir_width=6,
        idle_delay=2,
        add_bypass=True,
    )
    device.add_reg("IDCODE", 32, 0x01)
    if "DEBUG_CONTROL" in regs:
        device.add_reg("DEBUG_CONTROL", 5, 0x18, write=True)
    if "IC_RESET" in regs:
        # SMU SEP=0: 69 ports * 2 + hold = 139
        device.add_reg("IC_RESET", 139, 0x0D, write=True)
    if "EXTEST" in regs:
        device.add_reg("EXTEST", 8, 0x04, write=True)
    jtag = OcahJtagTap(
        dut,
        name="smu_ptap",
        tck_period_ns=period_ns,
        ir_width=6,
        tap_type="ptap",
        signal_map={
            "tck": "jtag_tck",
            "tms": "jtag_tms",
            "tdi": "jtag_tdi",
            "tdo": "jtag_tdo",
            "trst": "jtag_trst",
            "tdo_oen": "jtag_tdo_oen",
        },
    )
    jtag.add_device(device)
    jtag.init_signals()
    return jtag

@pyuvm.test()
class smu_dtp_bsr_extest_loopback_test(smu_base_test):
    """EXTEST DR loopback + instruction decode."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = _make_ptap(dut, self.cfg.jtag_period_ns, regs=("EXTEST",))
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 8)

        await jtag.shift_ir(0x04)
        await ClockCycles(dut.clk_smu_i, 4)

        decoded = _sample(dut.jtag_ptap_inst_decoded, "jtag_ptap_inst_decoded")
        expect_onehot = 1 << DTP_EXTEST_DECODED_BIT
        sb.expect_eq(
            "EXTEST decode one-hot",
            decoded,
            expect_onehot,
            evidence="BSR_EXTEST_DECODE",
        )

        mask = (1 << 8) - 1
        for pattern in _PATTERNS:
            if (pattern & mask) == 0:
                raise AssertionError("zero pattern forbidden (X/Z->0 can't-fail)")
            captured = await jtag.shift_dr(
                pattern & mask,
                width=8,
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
