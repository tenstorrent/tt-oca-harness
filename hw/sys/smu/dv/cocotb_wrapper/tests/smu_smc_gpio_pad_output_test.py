# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_gpio_pad_output_test - every GPIO pad driven from the SMC and looped back.

The GPIO interface CSRs are written and read over the inbound SMN port, with
the SMC aperture routed to its local alias and SYS_IN entry 0 opened over the
GPIO_INTF block, so the 65-pad walk costs AXI transfers rather than JTAG scans.

With the bench's pad drivers off, each pad's DATA_CTRL takes the pad from its
LSIO owner (INTERFACE_ENABLE, LSIO_DISABLE) with both ENABLE_RX_TX enables,
INTERRUPT_ENABLE at its reset type (active-high level) and CORE2PAD at 1, then
at 0 (hw/ip/gpio register description). Every pad follows CORE2PAD and loops
the value back to the receiver, so every lane of gpio_interrupt_o rises and
then falls. With ENABLE_RX_TX at 2'b01, "TX enabled" alone, and CORE2PAD at 1,
every pad is driven high while every interrupt lane stays low, so the receive
enable crosses the SMU apart from the transmit enable. The DATA_CTRL reset
value is written back last; the pads it leaves are recorded, since which LSIO
function owns each pad then is not a register fact. The interrupt vector is
read on the wrapper pin rather than through DATA_CTRL, whose 32-bit read
returns an undriven upper lane on the 64-bit inbound port; the pads are read
on the bench's pad nets, which a pulldown holds low when nothing drives them.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from ocah_axi_vip import RESP_OKAY
from ocah_jtag_vip import OcahJtagState
from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_axi_helpers import axi_write32_resp_bounded, make_smu_axi_master
from seq_lib.smu_boundary_regs import gpio_intf_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_filter_helpers import program_inbound0_window, program_smc_aperture_local_alias
from seq_lib.smu_jtag_helpers import make_smu_jtag_tap
from seq_lib.smu_tb_pins import smc_primary_reset
from smu_base_test import smu_base_test

DATA_CTRL_SYM = "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR"
LANES = smc_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_NUM")
BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
BASE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm") | gpio_intf_u32(
    "GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm"
)
CORE2PAD = gpio_intf_u32("GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
INTERRUPT_ENABLE = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
RESET = sum(
    gpio_intf_u32(f"GPIO_INTF__DATA_CTRL__{field}_reset")
    << gpio_intf_u32(f"GPIO_INTF__DATA_CTRL__{field}_bp")
    for field in (
        "CORE2PAD",
        "ENABLE_RX_TX",
        "INTERFACE_ENABLE",
        "LSIO_SELECT",
        "INTERRUPT_ENABLE",
        "LSIO_DISABLE",
        "INTERRUPT_TYPE",
    )
)
RX_TX = 0b11 << BP
TX_ONLY = 0b01 << BP
SYNC_CYCLES = 32


@pyuvm.test()
class smu_smc_gpio_pad_output_test(smu_base_test):
    """Every GPIO pad driven from its own DATA_CTRL and looped back to PAD2CORE."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        dut = cocotb.top
        sb = self.env.scoreboard
        jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        first = smc_indexed_addr(DATA_CTRL_SYM, 0)
        last = smc_indexed_addr(DATA_CTRL_SYM, LANES - 1)
        await program_smc_aperture_local_alias(jtag, scoreboard=sb)
        await program_inbound0_window(jtag, first, last + 4, scoreboard=sb, tag="GPIO")
        await ClockCycles(dut.clk_smu_i, 50)
        master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        dut.tb_gpio_drive_en.value = 0

        bad = []

        async def write_all(value: int) -> None:
            for pin in range(LANES):
                addr = smc_indexed_addr(DATA_CTRL_SYM, pin)
                resp = await axi_write32_resp_bounded(master, addr, value, label=f"gpio{pin}")
                if resp != RESP_OKAY:
                    bad.append((pin, "wr", resp))

        observed = []
        for value in (
            BASE | RX_TX | INTERRUPT_ENABLE | CORE2PAD,
            BASE | RX_TX | INTERRUPT_ENABLE,
            BASE | TX_ONLY | INTERRUPT_ENABLE | CORE2PAD,
        ):
            await write_all(value)
            await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
            observed.append(
                (
                    sample(dut.gpio_pad_io, "gpio_pad_io"),
                    sample(dut.tb_gpio_interrupt, "tb_gpio_interrupt"),
                )
            )
        await write_all(RESET)
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.logger.info(
            f"OBSERVATION pads after the DATA_CTRL reset value "
            f"{sample(dut.gpio_pad_io, 'gpio_pad_io'):#x}"
        )
        full = (1 << LANES) - 1
        self.logger.info(
            "CHK-SMU-LANE-GPIO-OUT (pads, gpio_interrupt)="
            f"{[(hex(p), hex(i)) for p, i in observed]} errors={bad}"
        )
        sb.expect_eq(
            f"CORE2PAD drives and loops back at 1 then 0 on all {LANES} pads, and transmit "
            "alone drives the pads with every interrupt lane low",
            (observed, bad),
            ([(full, full), (0, 0), (full, 0)], []),
            evidence="CHK-SMU-LANE-GPIO-OUT",
        )
