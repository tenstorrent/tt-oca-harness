# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_gpio_pad_output_test - every GPIO pad driven from the SMC and looped back.

The GPIO interface CSRs are written and read over the inbound SMN port, with
the SMC aperture routed to its local alias and SYS_IN entry 0 opened over the
GPIO_INTF block, so the 65-pad walk costs AXI transfers rather than JTAG scans.

With the bench's pad drivers off, each pad's DATA_CTRL takes the pad from its
LSIO owner (INTERFACE_ENABLE, LSIO_DISABLE) with INTERRUPT_ENABLE at its reset
type (active-high level) (hw/ip/gpio register description). The walk gives
every pad a code of its own: in phase k a pad's field is set when bit k of
(pad index + 1) is 1, which over seven phases is a distinct, nonzero,
not-all-ones word for each of the 65 pads. In the seven receive phases each
pad has both ENABLE_RX_TX enables and CORE2PAD from its code, so the pads and
gpio_interrupt_o must both equal the phase mask bit for bit: a pad answering
another pad's DATA_CTRL, or an interrupt lane taken from another pad, reads a
different code. In the seven transmit phases every pad has CORE2PAD at 1 and
ENABLE_RX_TX at 2'b01, "TX enabled" alone, where its code bit is set and
2'b11 elsewhere, so every pad is driven high while exactly the lanes outside
the mask raise their interrupt: the receive enable of each pad crosses the SMU
apart from its transmit enable and apart from every other pad's. The DATA_CTRL
reset value is written back last; the pads it leaves are recorded, since which
LSIO function owns each pad then is not a register fact. The interrupt vector
is read on the wrapper pin rather than through DATA_CTRL, whose 32-bit read
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
# Bits of (pad index + 1) give each pad a code no other pad has.
CODE_BITS = LANES.bit_length()


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
        written: dict[int, int] = {}

        async def write_lanes(values: list[int]) -> None:
            for pin, value in enumerate(values):
                if written.get(pin) == value:
                    continue
                addr = smc_indexed_addr(DATA_CTRL_SYM, pin)
                resp = await axi_write32_resp_bounded(master, addr, value, label=f"gpio{pin}")
                if resp != RESP_OKAY:
                    bad.append((pin, "wr", resp))
                written[pin] = value

        full = (1 << LANES) - 1
        masks = [
            sum(1 << pin for pin in range(LANES) if ((pin + 1) >> k) & 1) for k in range(CODE_BITS)
        ]
        phases = [
            (
                f"rx{k}",
                [
                    BASE | RX_TX | INTERRUPT_ENABLE | (CORE2PAD if (mask >> pin) & 1 else 0)
                    for pin in range(LANES)
                ],
                (mask, mask),
            )
            for k, mask in enumerate(masks)
        ] + [
            (
                f"tx{k}",
                [
                    BASE | INTERRUPT_ENABLE | CORE2PAD | (TX_ONLY if (mask >> pin) & 1 else RX_TX)
                    for pin in range(LANES)
                ],
                (full, full & ~mask),
            )
            for k, mask in enumerate(masks)
        ]
        if len(set(masks)) != CODE_BITS or any(m in (0, full) for m in masks):
            raise AssertionError(f"pad codes are not distinct per phase: {[hex(m) for m in masks]}")
        observed = []
        want = []
        for _name, values, expect in phases:
            await write_lanes(values)
            await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
            observed.append(
                (
                    sample(dut.gpio_pad_io, "gpio_pad_io"),
                    sample(dut.tb_gpio_interrupt, "tb_gpio_interrupt"),
                )
            )
            want.append(expect)
        await write_lanes([RESET] * LANES)
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.logger.info(
            f"OBSERVATION pads after the DATA_CTRL reset value "
            f"{sample(dut.gpio_pad_io, 'gpio_pad_io'):#x}"
        )
        self.logger.info(
            "pad walk (phase, pads, gpio_interrupt)="
            f"{[(p[0], hex(o[0]), hex(o[1])) for p, o in zip(phases, observed)]} errors={bad}"
        )
        sb.expect_eq(
            f"each of the {LANES} pads follows its own DATA_CTRL.CORE2PAD and loops back to its "
            "own interrupt lane, and transmit alone on a pad drives it with that lane low",
            (observed, bad),
            (want, []),
            evidence="CHK-SMU-LANE-GPIO-OUT",
        )
