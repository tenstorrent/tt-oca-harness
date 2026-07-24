# SPDX-License-Identifier: Apache-2.0
"""smc_mailbox_int_test - SMC mailbox CSR + IRQ enable path under SMU SEP=0.

Via JTAG2AXI (local fabric):
  1. Enable mailbox clock gate (readback proves side-effect)
  2. Read STATUS / ERROR_FLAGS (decode alive)
  3. Program IRQEN and WRITE_DATA; require STATUS and/or IRQS change
  4. Restore IRQEN and CG

Refuses vacuous PASS: CG bit must stick and mailbox activity must change state.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles

from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    force_jtag2axi_lifecycle_enable,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    release_forced,
)
from smu_base_test import smu_base_test

from env import cocotb_compat as _cocotb_compat

_cocotb_compat.apply()

CLOCK_GATE_CONTROL = 0xC001_0018
MAILBOX_CG_EN = 1 << 1
MAILBOX_WRITE_DATA = 0xC001_8000
MAILBOX_STATUS = 0xC001_8010
MAILBOX_ERROR_FLAGS = 0xC001_8018
MAILBOX_IRQS = 0xC001_8030
MAILBOX_IRQEN = 0xC001_8038
MAILBOX_PATTERN = 0xA5A5_5A5A_1234_5678


@pyuvm.test()
class smc_mailbox_int_test(smu_base_test):
    """Mailbox CG + IRQEN + WRITE_DATA with STATUS/IRQS evidence."""

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard

        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.cfg.reset_done.wait()
        await jtag.reset_tap()
        forced = force_jtag2axi_lifecycle_enable(dut, self.logger)
        try:
            await ClockCycles(dut.clk_smu_i, 16)
            for _ in range(8):
                await jtag.step_tms(0)

            st, cg0 = await jtag2axi_single_read(jtag, CLOCK_GATE_CONTROL)
            sb.expect_eq("CG read status", st, J2A_STATUS_SUCCESS)
            cg_en = int(cg0) | MAILBOX_CG_EN
            st, _ = await jtag2axi_single_write(jtag, CLOCK_GATE_CONTROL, cg_en)
            sb.expect_eq("CG enable write status", st, J2A_STATUS_SUCCESS)
            st, cg1 = await jtag2axi_single_read(jtag, CLOCK_GATE_CONTROL)
            sb.expect_eq("CG enable readback status", st, J2A_STATUS_SUCCESS)
            sb.expect_eq("CG mailbox bit set", int(cg1) & MAILBOX_CG_EN, MAILBOX_CG_EN)

            st, status0 = await jtag2axi_single_read(jtag, MAILBOX_STATUS)
            sb.expect_eq("MAILBOX_STATUS read status", st, J2A_STATUS_SUCCESS)
            st, err = await jtag2axi_single_read(jtag, MAILBOX_ERROR_FLAGS)
            sb.expect_eq("MAILBOX_ERROR_FLAGS read status", st, J2A_STATUS_SUCCESS)
            sb.expect_eq("MAILBOX_ERROR_FLAGS idle", int(err) & 0xFFFF_FFFF, 0)

            irq_pin0 = int(dut.ext_mailbox_interrupts.value)
            st, irqs0 = await jtag2axi_single_read(jtag, MAILBOX_IRQS)
            sb.expect_eq("MAILBOX_IRQS baseline status", st, J2A_STATUS_SUCCESS)

            st, _ = await jtag2axi_single_write(jtag, MAILBOX_IRQEN, 0xF)
            sb.expect_eq("MAILBOX_IRQEN write status", st, J2A_STATUS_SUCCESS)
            st, _ = await jtag2axi_single_write(jtag, MAILBOX_WRITE_DATA, MAILBOX_PATTERN)
            sb.expect_eq("MAILBOX_WRITE_DATA write status", st, J2A_STATUS_SUCCESS)
            await ClockCycles(dut.clk_smu_i, 32)

            st, irqs1 = await jtag2axi_single_read(jtag, MAILBOX_IRQS)
            sb.expect_eq("MAILBOX_IRQS after write status", st, J2A_STATUS_SUCCESS)
            st, status1 = await jtag2axi_single_read(jtag, MAILBOX_STATUS)
            sb.expect_eq("MAILBOX_STATUS after write status", st, J2A_STATUS_SUCCESS)
            irq_pin1 = int(dut.ext_mailbox_interrupts.value)

            sb.expect_true(
                "mailbox activity evidence (STATUS/IRQS/irq pin change)",
                (int(status1) != int(status0))
                or (int(irqs1) != int(irqs0))
                or (irq_pin1 != irq_pin0),
            )

            st, _ = await jtag2axi_single_write(jtag, MAILBOX_IRQEN, 0)
            sb.expect_eq("MAILBOX_IRQEN clear status", st, J2A_STATUS_SUCCESS)
            st, _ = await jtag2axi_single_write(jtag, CLOCK_GATE_CONTROL, int(cg0))
            sb.expect_eq("CG restore status", st, J2A_STATUS_SUCCESS)
        finally:
            release_forced(forced)

        self.logger.info(
            "smc_mailbox_int_test: STATUS 0x%x->0x%x IRQS 0x%x->0x%x irq_pin 0x%x->0x%x",
            int(status0),
            int(status1),
            int(irqs0),
            int(irqs1),
            irq_pin0,
            irq_pin1,
        )
