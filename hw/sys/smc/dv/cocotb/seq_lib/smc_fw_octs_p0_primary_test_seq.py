# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS PRIMARY preset sweep from the CPU; the bench watches the timer and its pad.

`fw/tests/octs_p0_primary_test` probes CTRL writability, programs CTRL and
TIMER_GPIO_ENABLE, sweeps PRESET (including a 64-bit value only a working HI
half can return), starts the timer and checks COUNT is monotonic across three
reads. All of that is CPU-side CSR work graded by the firmware.

The image parks with the timer running and the pad output enabled, so after
the PASS word the bench reads STATUS.RUNNING, reads TIMER_COUNT_LO twice and
requires it to have advanced, and counts rising edges on
tb_octs_cnt_credit_from_dut (pad 56): in PRIMARY mode (tb_chiplet_is_primary
defaults to 1) the running timer emits credit pulses, the same PRIMARY outbound
proof smc_octs_dual_sync_test uses. Two edges in the window is that test's
floor; with the image's CREDIT_VAL of 0xA the pulses come more often than
under its 0x10.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import smc_addr
from .smc_fw_image_boot_seq import smc_fw_image_boot_seq
from .smc_octs_sync_bfm import count_rising_edges

OCTS_STATUS = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_STATUS_BASE_ADDR")
OCTS_COUNT_LO = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_COUNT_LO_BASE_ADDR")
OCTS_GPIO_ENABLE = smc_addr("SMC_TOP_SMC_SYSTEM_TIMER_OCTS_TIMER_GPIO_ENABLE_BASE_ADDR")
# STATUS bit 4, "running" -- the bit the image and smc_octs_dual_sync_test_seq
# both read for the same purpose.
OCTS_STATUS_RUNNING = 0x10

COUNT_GAP_CYCLES = 256
CREDIT_WINDOW_CYCLES = 1024
MIN_CREDIT_EDGES = 2


class smc_fw_octs_p0_primary_test_seq(smc_fw_image_boot_seq):
    """Boot the OCTS preset image, then watch the timer keep running."""

    tag = "OCTS-PRIMARY"
    # The image reaches PASS ~122 us after release, ~245 polls at a 5 ns
    # clk_smc_i; 2500 is ~10x that.
    poll_iterations = 2500

    def __init__(self, name: str = "smc_fw_octs_p0_primary_test_seq") -> None:
        super().__init__(name)
        self.count_advance = 0
        self.credit_edges = 0
        self.timer_ok = False

    async def after_pass(self) -> None:
        dut = cocotb.top
        status = await self.csr_read("OCTS_STATUS", OCTS_STATUS)
        assert status & OCTS_STATUS_RUNNING, (
            f"OCTS STATUS=0x{status:08x}: timer not running after the image's TIMER_START"
        )
        gpio_en = await self.csr_read("OCTS_GPIO_ENABLE", OCTS_GPIO_ENABLE)
        assert gpio_en & 1, f"TIMER_GPIO_ENABLE=0x{gpio_en:08x}: pad output not enabled"

        first = await self.csr_read("OCTS_COUNT_LO_1", OCTS_COUNT_LO)
        await ClockCycles(dut.clk_smc_i, COUNT_GAP_CYCLES)
        second = await self.csr_read("OCTS_COUNT_LO_2", OCTS_COUNT_LO)
        self.count_advance = (second - first) & 0xFFFF_FFFF
        assert self.count_advance > 0, (
            f"TIMER_COUNT_LO did not advance across {COUNT_GAP_CYCLES} clk_smc_i: "
            f"0x{first:08x} -> 0x{second:08x}"
        )
        cocotb.log.info(
            "CHK-FW-OCTS-COUNT-ADVANCES: COUNT_LO 0x%08x -> 0x%08x (+%d) over %d clk_smc_i, "
            "STATUS=0x%08x TIMER_GPIO_ENABLE=0x%08x",
            first,
            second,
            self.count_advance,
            COUNT_GAP_CYCLES,
            status,
            gpio_en,
        )

        self.credit_edges = await count_rising_edges(
            dut.tb_octs_cnt_credit_from_dut, dut.clk_smc_i, CREDIT_WINDOW_CYCLES
        )
        assert self.credit_edges >= MIN_CREDIT_EDGES, (
            f"tb_octs_cnt_credit_from_dut rose {self.credit_edges} times in "
            f"{CREDIT_WINDOW_CYCLES} clk_smc_i, need >= {MIN_CREDIT_EDGES}: the PRIMARY "
            f"timer is running but its credit pulses are not reaching pad 56"
        )
        self.timer_ok = True
        cocotb.log.info(
            "CHK-FW-OCTS-CREDIT-PAD: %d rising edges on tb_octs_cnt_credit_from_dut in %d "
            "clk_smc_i (>= %d) with the firmware parked and the timer running",
            self.credit_edges,
            CREDIT_WINDOW_CYCLES,
            MIN_CREDIT_EDGES,
        )
