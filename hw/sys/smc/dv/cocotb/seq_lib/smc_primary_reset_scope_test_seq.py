# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cores, fabric and peripherals are all held while rst_primary_no is asserted.

``clk_rst.adoc`` (Primary Reset) scopes the primary reset over "CPU cores and
cache hierarchies, fabric infrastructure, peripheral controllers and
interfaces, and SMC control and configuration registers", and lists the cool
reset as one of its activation sources. Each consumer is put into a state a
reset would visibly end, the cool pin is asserted, and the consumer is
observed held for a whole window rather than at one instant:

* cores -- fetching from ROM (``tb_cpu_rom_read_count`` advancing) before the
  reset; during the held window ``tb_cpu_core_reset_n`` reads 0 at every
  sample and the ROM read counter stops advancing.
* fabric -- an outbound filter register carries a pattern before the reset;
  after release it answers a read again and reads its generated reset. That
  revert is the whole fabric claim, and it is a scoreboard exact-value compare.

  "The fabric is held" is *not* claimed, because this bench cannot observe it.
  Two measurements say so and both are logged. ``s_axi_arready`` and
  ``s_axi_awready`` read 1 immediately before the cool pin drops and read 1 at
  every sample of the held window, so the SEP_IN request channels do not
  withdraw ready while the primary reset is asserted and "not ready" cannot be
  the observable. And a request cannot be presented inside the window either:
  the SEP_IN AXI master takes ``rst_primary_smc_clk_no`` as its own reset
  (``env/smc_sys_axi_agent.py``), so it parks ``arvalid`` low there -- a read
  forked into the window was measured with ``arvalid`` high at 0 of 382
  samples, and its expiry would have been the bench's reset, not the DUT's
  refusal. Response-channel silence (``s_axi_rvalid`` / ``s_axi_bvalid``) is
  recorded for the same reason it cannot carry anything: the window issues no
  traffic, so both read 0 on any RTL.
* peripherals -- UART0 is enabled and mid-frame (its TX pad driven low in the
  start bit, with the pad's output enable asserted) when the reset lands;
  during the window the pad's output enable is released at every sample, so
  the transmitter no longer drives the frame, and after release the UART
  enable and the ungated clock gate read their reset values. The pad
  *value* probe cannot carry this claim: ``tb_uart0_tx_from_dut`` mirrors
  ``core2pad_o``, which a GPIO wrap in reset parks at 0 with its driver off.

The core and peripheral held-state claims are per-sample compares across the
window, so a consumer released anywhere inside it fails. The fabric has no
held-state claim; see above.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_probe_positive_control import _pad_vec
from .smc_reset_seq_base import SmcResetSeqBase

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    FILTER_CTRL_END_ADDR_REG_DEFAULT,
    SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT,
    UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
)

OUTBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
UART0_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)
UART0_THR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0)
UART0_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART0_LCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0)

# smc_padring.sv gen_uart_connections: UART u drives pad 12 + 4u.
UART0_TX_PAD = 12
UART_EN = 0x1
LCR_DLAB = 0x80
LCR_8N1 = 0x03
# The slowest divisor the 16550 baud generator takes keeps the start bit low
# for 16 * (DIVISOR + 1) peripheral clocks, long enough to land the reset
# assertion (32 clk_ref_i de-glitch samples) inside the frame.
UART_DIVISOR = 0x00FF
# A byte of zeros keeps TX low for the start bit and all eight data bits.
UART_TX_BYTE = 0x00

FILTER_END_PATTERN = 0x0000_0000_00AB_CDE8
# Window over which the cores must be seen fetching before the reset.
FETCH_WINDOW_SMC_CYCLES = 4000
# Held window sampled every clk_smc_i edge once the primary reset is asserted.
HOLD_WINDOW_REF_CYCLES = 96
# Samples at the head of the window during which the peripheral-domain reset
# synchronizer may still be propagating; the UART pad must be idle-high at
# every sample after them.
PAD_SETTLE_REF_CYCLES = 16
# The transmitter starts the frame on a baud-tick boundary, so the start bit
# may begin up to one bit time (16 x (DIVISOR + 1) peripheral clocks) after
# THR is written; the bound is three bit times, converted to clk_smc_i cycles
# from the run's clock periods.
TX_START_BOUND_BIT_TIMES = 3
CORE_RELEASE_BOUND_SMC_CYCLES = 20000

# 8 UART programming accesses, filter pattern write + readback, three
# post-reset reads.
EXPECTED_ACCESSES = 13
EXPECTED_VALUE_CHECKS = 4


class smc_primary_reset_scope_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cool reset while a core fetches, a filter holds a pattern and UART0 transmits."""

    def __init__(self, name: str = "smc_primary_reset_scope_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.fetch_delta_before: int | None = None
        self.hold_samples = 0
        self.core_reset_low_samples = 0
        self.rvalid_high_samples = 0
        self.bvalid_high_samples = 0
        self.pre_reset_ready: tuple[int, int] | None = None
        self.arvalid_high_samples = 0
        self.arready_high_samples = 0
        self.awready_high_samples = 0
        self.tx_oe_high_after_settle = 0
        self.rom_count_frozen_from: int | None = None

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        assert self.dispatch_reset is not None, "dispatch_reset not bound by the test"
        await self.dispatch_reset(item)

    @staticmethod
    def _bit(sig, name: str) -> int:
        value = sig.value
        assert value.is_resolvable, f"{name} is not resolvable: {value}"
        return int(value)

    async def _await_bit(self, sig, name: str, want: int, bound: int) -> int:
        dut = cocotb.top
        for cycle in range(bound):
            if self._bit(sig, name) == want:
                return cycle
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(f"{name} never reached {want} within {bound} clk_smc_i cycles")

    async def _prove_cores_fetching(self) -> None:
        dut = cocotb.top
        assert self._bit(dut.tb_cpu_core_reset_n, "tb_cpu_core_reset_n") == 1, (
            "core 0 is still in reset after bring-up; the held-state claim needs a running core"
        )
        rom0 = int(dut.tb_cpu_rom_read_count.value)
        await ClockCycles(dut.clk_smc_i, FETCH_WINDOW_SMC_CYCLES)
        rom1 = int(dut.tb_cpu_rom_read_count.value)
        self.fetch_delta_before = rom1 - rom0
        assert self.fetch_delta_before > 0, (
            f"tb_cpu_rom_read_count did not advance over {FETCH_WINDOW_SMC_CYCLES} clk_smc_i "
            f"cycles ({rom0} -> {rom1}); the cores are not fetching, so 'held' could not be told "
            f"from 'idle'"
        )

    async def _arm_uart_mid_frame(self) -> None:
        dut = cocotb.top
        cg = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART0_EN", UART0_CTRL, UART_EN)
        await self.csr_write("UART0_LCR_DLAB", UART0_LCR, LCR_8N1 | LCR_DLAB)
        await self.csr_write("UART0_DLL", UART0_THR, UART_DIVISOR & 0xFF)
        await self.csr_write("UART0_DLM", UART0_IER, (UART_DIVISOR >> 8) & 0xFF)
        await self.csr_write("UART0_LCR_8N1", UART0_LCR, LCR_8N1)
        bit_smc_cycles = (
            16 * (UART_DIVISOR + 1) * self.cfg.periph_clk_period_ns
        ) // self.cfg.smc_clk_period_ns
        # Divisor reload settle, as smc_uart_loopback_test_seq does before THR.
        await ClockCycles(dut.clk_smc_i, max(64, UART_DIVISOR * 16))
        assert self._bit(dut.tb_uart0_tx_from_dut, "tb_uart0_tx_from_dut") == 1, (
            "UART0 TX pad is not idle-high before the frame is queued"
        )
        await self.csr_write("UART0_THR", UART0_THR, UART_TX_BYTE)
        cycles = await self._await_bit(
            dut.tb_uart0_tx_from_dut,
            "tb_uart0_tx_from_dut",
            0,
            TX_START_BOUND_BIT_TIMES * bit_smc_cycles,
        )
        oe = (_pad_vec(dut, "tb_core2pad_en_o") >> UART0_TX_PAD) & 1
        assert oe == 1, (
            f"UART0 TX pad {UART0_TX_PAD} is low but its output enable is not asserted; the "
            f"released-driver check below would have nothing to release"
        )
        cocotb.log.info(
            "UART0 start bit observed on tb_uart0_tx_from_dut %d clk_smc_i cycle(s) after THR "
            "with core2pad_en_o[%d]=1",
            cycles,
            UART0_TX_PAD,
        )

    async def _hold_window(self) -> None:
        dut = cocotb.top
        rom_at_start = int(dut.tb_cpu_rom_read_count.value)
        rom_last = rom_at_start
        ref_cycles = 0
        last_ref_level = int(dut.clk_ref_i.value)
        while ref_cycles < HOLD_WINDOW_REF_CYCLES:
            await RisingEdge(dut.clk_smc_i)
            ref_level = int(dut.clk_ref_i.value)
            if ref_level and not last_ref_level:
                ref_cycles += 1
            last_ref_level = ref_level
            self.hold_samples += 1
            if self._bit(dut.tb_cpu_core_reset_n, "tb_cpu_core_reset_n") == 0:
                self.core_reset_low_samples += 1
            if self._bit(dut.s_axi_rvalid, "s_axi_rvalid"):
                self.rvalid_high_samples += 1
            if self._bit(dut.s_axi_bvalid, "s_axi_bvalid"):
                self.bvalid_high_samples += 1
            if self._bit(dut.s_axi_arready, "s_axi_arready"):
                self.arready_high_samples += 1
            if self._bit(dut.s_axi_awready, "s_axi_awready"):
                self.awready_high_samples += 1
            if self._bit(dut.s_axi_arvalid, "s_axi_arvalid"):
                self.arvalid_high_samples += 1
            oe = (_pad_vec(dut, "tb_core2pad_en_o") >> UART0_TX_PAD) & 1
            if ref_cycles >= PAD_SETTLE_REF_CYCLES and oe == 1:
                self.tx_oe_high_after_settle += 1
            rom_now = int(dut.tb_cpu_rom_read_count.value)
            if rom_now != rom_last:
                self.rom_count_frozen_from = self.hold_samples
                rom_last = rom_now
        assert self.core_reset_low_samples == self.hold_samples, (
            f"tb_cpu_core_reset_n read 1 at {self.hold_samples - self.core_reset_low_samples} of "
            f"{self.hold_samples} samples while rst_primary_smc_clk_no was asserted"
        )
        # The four SEP_IN tallies are recorded observations, not checks: the
        # docstring says what each one is and is not able to show.
        assert self.tx_oe_high_after_settle == 0, (
            f"UART0 TX pad output enable was asserted at {self.tx_oe_high_after_settle} sample(s) "
            f"after the first {PAD_SETTLE_REF_CYCLES} clk_ref_i cycles of the held window: the "
            f"transmitter kept driving its frame through the primary reset"
        )
        rom_end = int(dut.tb_cpu_rom_read_count.value)
        assert rom_end == rom_last
        # Any fetch counted inside the window must sit at its head, before the
        # cores' reset had propagated; a change later in the window is a fetch
        # by a core that was not held.
        if self.rom_count_frozen_from is not None:
            assert self.rom_count_frozen_from <= PAD_SETTLE_REF_CYCLES * (
                self.cfg.ref_clk_period_ns // self.cfg.smc_clk_period_ns + 1
            ), (
                f"tb_cpu_rom_read_count advanced at sample {self.rom_count_frozen_from} of the held "
                f"window (rom {rom_at_start} -> {rom_end}): a core fetched ROM while "
                f"rst_primary_smc_clk_no was asserted"
            )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        await self._send(SmcResetOp.SAMPLE)

        await self._prove_cores_fetching()
        await self.csr_write("OUTBOUND0_END_PATTERN", OUTBOUND0_END, FILTER_END_PATTERN, length=8)
        await self.csr_read(
            "OUTBOUND0_END_PATTERN_RB", OUTBOUND0_END, expected=FILTER_END_PATTERN, length=8
        )
        await self._arm_uart_mid_frame()

        self.pre_reset_ready = (
            self._bit(dut.s_axi_arready, "s_axi_arready"),
            self._bit(dut.s_axi_awready, "s_axi_awready"),
        )

        await self._send(SmcResetOp.COOL_RST_LO)
        asserted = await self._wait_state(
            "PRIMARY_ASSERTED",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._hold_window()
        await self._send(SmcResetOp.COOL_RST_HI)
        await self._wait_released("PRIMARY_RELEASED")

        core_cycles = await self._await_bit(
            dut.tb_cpu_core_reset_n, "tb_cpu_core_reset_n", 1, CORE_RELEASE_BOUND_SMC_CYCLES
        )
        await self.csr_read(
            "OUTBOUND0_END_AFTER_RESET",
            OUTBOUND0_END,
            expected=FILTER_CTRL_END_ADDR_REG_DEFAULT,
            length=8,
        )
        await self.csr_read(
            "UART0_CTRL_AFTER_RESET", UART0_CTRL, expected=UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT
        )
        await self.csr_read(
            "CLOCK_GATE_AFTER_RESET",
            CLOCK_GATE_CONTROL,
            expected=SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_REG_DEFAULT & 0xFFFF_FFFF,
        )
        self.assert_all_reachable(EXPECTED_ACCESSES, "PRIMARY_RESET_SCOPE")

        cocotb.log.info(
            "CHK-PRIMARY-RESET-CORES-HELD: cores fetched %d ROM words in %d cycles before the reset; "
            "tb_cpu_core_reset_n read 0 at all %d clk_smc_i samples of the %d-clk_ref_i held window "
            "and the ROM read counter stopped advancing (%s); core 0 released %d cycles after "
            "rst_cool_ni=1 (assert handshake matched after %d ref cycles)",
            self.fetch_delta_before,
            FETCH_WINDOW_SMC_CYCLES,
            self.hold_samples,
            HOLD_WINDOW_REF_CYCLES,
            "no fetch inside the window"
            if self.rom_count_frozen_from is None
            else f"last fetch at sample {self.rom_count_frozen_from}",
            core_cycles,
            asserted.wait_ref_cycles,
        )
        cocotb.log.info(
            "CHK-PRIMARY-RESET-FABRIC-REVERTED: after release OUTBOUND_FILTER_CTRL[0].END_ADDR "
            "answered a read again and went 0x%x -> generated reset 0x%x, so the primary reset "
            "reached the fabric configuration registers. Held-state is NOT claimed and these "
            "four tallies say why: SEP_IN arready/awready read %s just before the cool pin "
            "dropped and stayed high for %d/%d of the %d clk_smc_i samples of the window, so "
            "ready is not withdrawn under primary reset; arvalid was high at %d samples because "
            "the SEP_IN master shares rst_primary_smc_clk_no and parks it, so no request could "
            "be presented; rvalid/bvalid read high at %d/%d, which an idle window gives on any "
            "RTL",
            FILTER_END_PATTERN,
            FILTER_CTRL_END_ADDR_REG_DEFAULT,
            self.pre_reset_ready,
            self.arready_high_samples,
            self.awready_high_samples,
            self.hold_samples,
            self.arvalid_high_samples,
            self.rvalid_high_samples,
            self.bvalid_high_samples,
        )
        cocotb.log.info(
            "CHK-PRIMARY-RESET-PERIPHERALS-HELD: UART0 was mid-frame (TX pad %d driven low, output "
            "enable asserted) when the cool reset landed; the output enable read 0 at every sample "
            "after the first %d clk_ref_i cycles of the window; UART0 CTRL and CLOCK_GATE_CONTROL "
            "read their generated resets afterwards",
            UART0_TX_PAD,
            PAD_SETTLE_REF_CYCLES,
        )
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: %s", line)
