# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag_smoke_test - real IDCODE checker via OcahJtagTap.

DTP cocotb helpers live under ``dtp/dv/cocotb/env/``, which collides with SMU's
own ``env`` package on PYTHONPATH. Keep DTP constants local here (same values as
``dtp_tap_device.DTP_DEFAULT_IDCODE`` / ``dtp_types``) and drive the TAP through
the shared OcahJtagTap VIP only.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from ocah_jtag_vip import OcahJtagTap
from smu_base_test import smu_base_test

# Ensure Trigger.__del__ shim is applied even if import order skips env/__init__.
from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

# Mirrors dv/oss/hw/sys/dtp/dv/cocotb/env/{dtp_tap_device,dtp_types}.py
DTP_DEFAULT_IDCODE = 0x0000_0001
DTP_IR_WIDTH = 6
DTP_IR_BYPASS = 0x3F


@pyuvm.test()
class smu_dtp_jtag_smoke_test(smu_base_test):
    """Drive SMU-wrapped DTP TAP; assert IDCODE matches expected value."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = OcahJtagTap(
            dut,
            name="smu_ptap",
            tck_period_ns=self.cfg.jtag_period_ns,
            ir_width=DTP_IR_WIDTH,
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
        jtag.init_signals()
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        await ClockCycles(dut.clk_smu_i, 5)

        idcode = await jtag.read_idcode()
        sb.expect_eq("DTP IDCODE", int(idcode), DTP_DEFAULT_IDCODE)
        sb.expect_eq("IDCODE marker lsb", int(idcode) & 0x1, 1)

        # BYPASS: one-bit DR delays TDI->TDO by 1 TCK (capture_bit=0 after reset).
        await jtag.shift_ir(DTP_IR_BYPASS)
        pattern = 0xA5A5_A5A5
        captured = await jtag.shift_dr(pattern, width=32, back_to_rti=True)
        expected = (pattern & 0x7FFF_FFFF) << 1
        sb.expect_eq("BYPASS 1-TCK delay", int(captured) & 0xFFFF_FFFF, expected)

        self.logger.info(
            "smu_dtp_jtag_smoke_test: IDCODE=0x%08x BYPASS=0x%08x",
            int(idcode),
            int(captured),
        )
