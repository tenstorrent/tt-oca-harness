# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_boundary_lane_sweep_test. No Force.

``smu_smc_boundary_io_test`` proves the contract of each SMC-facing wrapper
signal on one or two lanes. This leaf takes the same contracts across every
lane of the six buses that have more than one, so each lane is driven both
ways and each aggregate names the number of lanes it expects:

* ``smc_ext_interrupts_i`` -> ``cpu_interrupts_o[NUM_INT_TO_SMC-1:0]``, the
  external-interrupt slice ``hw/sys/smc/doc/interrupts.adoc`` defines, over
  all 256 lanes for all-ones, all-zeros and both alternating patterns.
* ``RESET_UNIT.ISOLATE_REQ_REG`` -> ``isolate_req_o``, and
  ``RESET_UNIT.SS_CONFIG`` -> ``ss_config_o`` with ``SS_CONFIG_LOCK`` open,
  over the register width the reset-unit header reports.
* ``smc_ext_mailbox_interrupts_o``, one lane at a time: each outbound mailbox
  raises its own bit through ``IRQEN.WTIRQ`` plus an outbound push, and
  clearing ``IRQEN`` retires that bit alone.
* ``gpio_pad_io`` -> ``gpio_interrupt_o`` and ``GPIO_INTF.DATA_CTRL.PAD2CORE``,
  every pad taken from its LSIO owner and armed as an active-high level.
* ``uart_interrupt_o``, each UART instance raising and retiring its own lane
  through ``IER.ETBEI`` and the ``IIR`` read.

Every lane count comes from the generated SMC register header or from the
DV-owned port table in ``seq_lib.smu_compose_helpers``, and every compare
reads a DUT-produced value -- an SMC CSR read-back or a wrapper output --
never the value the bench drove.

``smc_global_base_o`` and ``smc_region_size_o`` are out of scope: the SMC
aperture routes the bench's own JTAG2AXI accesses, and
``smc_base_config.rdl`` constrains ``REGION_SIZE.size`` to a non-zero power of
two that ``LOCAL_BASE`` is aligned to, so no all-lanes sweep of either port is
a legal stimulus.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import mailbox_u32, reset_unit_u32, smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import (
    gpio_intf_u32,
    smc_base_config_u32,
    smc_outbound_mailbox_count,
    uart_iir_interrupt_id,
    uart_main_u32,
)
from seq_lib.smu_compose_helpers import NUM_INT_TO_SMC, hier, sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smu_scope, tb_pin

SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_CONFIG_LOCK = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR")
ISOLATE_REQ_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
GPIO_DATA_CTRL_SYM = "SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR"
UART_BASE_SYM = "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR"
SMC_BASE_PATH = "u_smc.u_smc_base"
MBX_PORT = "smc_ext_mailbox_interrupts_o"

ISOLATE_REQ_WIDTH = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_REG__ISOLATE_REQ_REG_bw")
SS_CONFIG_WIDTH = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_bw")
SS_CONFIG_RESET = reset_unit_u32("RESET_UNIT__SS_CONFIG__SS_CONFIG_reset")
MBX_LANES = smc_outbound_mailbox_count()
GPIO_LANES = smc_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_NUM")
UART_LANES = smc_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_NUM")

IRQEN_WTIRQ = mailbox_u32("AXIL_MAILBOX__IRQEN__WTIRQ_bm")
# One push takes the outbound write FIFO above the WIRQT reset threshold.
MBX_PUSH_PATTERN = 0x5A5A_5A5A

ENABLE_RX_TX_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
INTERFACE_ENABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
INTERRUPT_ENABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
LSIO_DISABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
INTERRUPT_TYPE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bm")
PAD2CORE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
# gpio_intf.rdl DATA_CTRL.ENABLE_RX_TX: 2'b10 is "RX enabled". INTERRUPT_TYPE
# stays at its reset encoding, an active-high level, so a CSR poll cannot miss
# the assertion the way it can miss an edge type's one-cycle pulse.
GPIO_ARM = (0b10 << ENABLE_RX_TX_BP) | INTERFACE_ENABLE_BM | INTERRUPT_ENABLE_BM | LSIO_DISABLE_BM

UART_IER_OFF = uart_main_u32("UART_16550_MAIN_IER_BASE_ADDR")
UART_IIR_OFF = uart_main_u32("UART_16550_MAIN_IIR_BASE_ADDR")
IER_ETBEI_BM = uart_main_u32("UART_16550_MAIN__IER__ETBEI_bm")
IIR_PENDING_BM = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_ID_BM = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_ID_BP = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
# uart_16550_main.rdl IIR.INTERRUPT_ID field description.
IIR_ID_THRE = uart_iir_interrupt_id("Transmitter Holding Register Empty")
UART_CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__UART_CG_EN_bm")

SYNC_CYCLES = 32
CSR_SETTLE_CYCLES = 4


def _mask(width: int) -> int:
    return (1 << width) - 1


def _alternating(width: int) -> tuple[int, int]:
    """The two half-populated patterns that separate neighbouring lanes."""
    lo = int("01" * width, 2) & _mask(width)
    return lo, ~lo & _mask(width)


class smu_smc_boundary_lane_sweep_seq:
    """Every lane of the multi-lane SMC-facing wrapper buses, both directions."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _sample(self, name: str) -> int:
        return sample(tb_pin(self.dut, name), name)

    def _lane_count(self, name: str, expect: int, what: str) -> int:
        """Bench-side lane count, required to match the specified one."""
        got = len(tb_pin(self.dut, name))
        if got != expect:
            raise AssertionError(
                f"{what}: bench sees {got} lanes on {name}, contract says {expect}"
            )
        return got

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        self.reads += 1
        return axi64_unpack32(addr, rdata)

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag, addr, beat, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def run(self) -> None:
        dut = self.dut
        self.reads = 0
        await self.cfg.reset_done.wait()

        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._sample("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._ext_interrupt_lanes()
        await self._isolate_req_lanes()
        await self._ss_config_lanes()
        await self._mailbox_interrupt_lanes()
        await self._gpio_lanes()
        await self._uart_interrupt_lanes()

    # ------------------------------------------------------------------
    # S1: every external interrupt lane on the SMC CPU interrupt vector.
    # ------------------------------------------------------------------
    async def _ext_interrupt_lanes(self) -> None:
        dut = self.dut
        lanes = self._lane_count("tb_smc_ext_interrupts", NUM_INT_TO_SMC, "smc_ext_interrupts_i")
        full = _mask(lanes)
        lo, hi = _alternating(lanes)
        received = hier(smu_scope(dut), f"{SMC_BASE_PATH}.cpu_interrupts_o")
        rose = 0
        fell = 0

        idle = sample(received, "cpu_interrupts_o") & full
        self.sb.expect_eq(
            f"cpu_interrupts_o[{lanes - 1}:0] clear while all {lanes} pins are idle",
            idle,
            0,
            evidence="CHK-SMU-LANE-EXT-IRQ",
        )
        fell |= full
        for pattern in (full, 0, lo, hi, 0):
            dut.tb_smc_ext_interrupts.value = pattern
            await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
            got = sample(received, "cpu_interrupts_o") & full
            self.sb.expect_eq(
                f"smc_ext_interrupts_i=0x{pattern:x} appears bit for bit on "
                f"cpu_interrupts_o[{lanes - 1}:0]",
                got,
                pattern,
                evidence="CHK-SMU-LANE-EXT-IRQ",
            )
            rose |= got
            fell |= ~got & full

        self.sb.expect_eq(
            f"every one of the {lanes} external interrupt lanes was seen high",
            bin(rose).count("1"),
            lanes,
            evidence="CHK-SMU-LANE-EXT-IRQ",
        )
        self.sb.expect_eq(
            f"every one of the {lanes} external interrupt lanes was seen low",
            bin(fell).count("1"),
            lanes,
            evidence="CHK-SMU-LANE-EXT-IRQ",
        )

    # ------------------------------------------------------------------
    # S2: every isolation-request lane from its software term.
    # ------------------------------------------------------------------
    async def _isolate_req_lanes(self) -> None:
        dut = self.dut
        lanes = self._lane_count("tb_isolate_req", ISOLATE_REQ_WIDTH, "isolate_req_o")
        full = _mask(lanes)
        lo, hi = _alternating(lanes)
        rose = 0
        fell = 0

        self.sb.expect_eq(
            f"isolate_req_o[{lanes - 1}:0] clear at the ISOLATE_REQ_REG reset value",
            self._sample("tb_isolate_req"),
            0,
            evidence="CHK-SMU-LANE-ISOLATE-REQ",
        )
        fell |= full
        for pattern in (full, lo, hi, 0):
            await self._wr32(ISOLATE_REQ_REG, pattern, "ISOLATE_REQ_REG")
            await ClockCycles(dut.clk_smu_i, CSR_SETTLE_CYCLES)
            readback = await self._rd32(ISOLATE_REQ_REG, "ISOLATE_REQ_REG")
            self.sb.expect_eq(
                f"ISOLATE_REQ_REG holds 0x{pattern:08x}",
                readback,
                pattern,
                evidence="CHK-SMU-LANE-ISOLATE-REQ",
            )
            got = self._sample("tb_isolate_req")
            self.sb.expect_eq(
                f"isolate_req_o carries the ISOLATE_REQ_REG software term 0x{pattern:08x} "
                f"on all {lanes} lanes",
                got,
                pattern,
                evidence="CHK-SMU-LANE-ISOLATE-REQ",
            )
            rose |= got
            fell |= ~got & full

        self.sb.expect_eq(
            f"every one of the {lanes} isolation-request lanes was seen set and cleared",
            (bin(rose).count("1"), bin(fell).count("1")),
            (lanes, lanes),
            evidence="CHK-SMU-LANE-ISOLATE-REQ",
        )

    # ------------------------------------------------------------------
    # S3: every subsystem-configuration lane with the lock open.
    # ------------------------------------------------------------------
    async def _ss_config_lanes(self) -> None:
        dut = self.dut
        lanes = self._lane_count("tb_ss_config", SS_CONFIG_WIDTH, "ss_config_o")
        full = _mask(lanes)
        lo, hi = _alternating(lanes)
        rose = 0
        fell = 0

        lock = await self._rd32(SS_CONFIG_LOCK, "SS_CONFIG_LOCK")
        self.sb.expect_eq(
            f"SS_CONFIG_LOCK open at reset, so all {lanes} SS_CONFIG lanes are writable",
            lock,
            0,
            evidence="CHK-SMU-LANE-SS-CONFIG",
        )
        for pattern in (full, lo, hi, SS_CONFIG_RESET):
            await self._wr32(SS_CONFIG, pattern, "SS_CONFIG")
            await ClockCycles(dut.clk_smu_i, CSR_SETTLE_CYCLES)
            readback = await self._rd32(SS_CONFIG, "SS_CONFIG")
            self.sb.expect_eq(
                f"SS_CONFIG holds 0x{pattern:08x}",
                readback,
                pattern,
                evidence="CHK-SMU-LANE-SS-CONFIG",
            )
            got = self._sample("tb_ss_config")
            self.sb.expect_eq(
                f"ss_config_o carries SS_CONFIG=0x{pattern:08x} on all {lanes} lanes",
                got,
                pattern,
                evidence="CHK-SMU-LANE-SS-CONFIG",
            )
            rose |= got
            fell |= ~got & full

        self.sb.expect_eq(
            f"every one of the {lanes} SS_CONFIG lanes was seen set and cleared",
            (bin(rose).count("1"), bin(fell).count("1")),
            (lanes, lanes),
            evidence="CHK-SMU-LANE-SS-CONFIG",
        )

    # ------------------------------------------------------------------
    # S4: every outbound mailbox interrupt lane, one lane at a time.
    # ------------------------------------------------------------------
    async def _mailbox_interrupt_lanes(self) -> None:
        dut = self.dut
        mbx = tb_pin(smu_scope(dut), MBX_PORT)
        lanes = len(mbx)
        if lanes != MBX_LANES:
            raise AssertionError(
                f"smc_ext_mailbox_interrupts_o is {lanes} lanes, but smc_addr.h enumerates "
                f"{MBX_LANES} outbound mailboxes"
            )
        full = _mask(lanes)

        self.sb.expect_eq(
            f"smc_ext_mailbox_interrupts_o[{lanes - 1}:0] clear before any mailbox is armed",
            sample(mbx, MBX_PORT),
            0,
            evidence="CHK-SMU-LANE-MBX-IRQ",
        )

        expected = 0
        for idx in range(lanes):
            await self._wr32(self._mbx_addr(idx, "IRQEN"), IRQEN_WTIRQ, f"MBX{idx}-IRQEN")
            await self._wr32(
                self._mbx_addr(idx, "WRITE_DATA"), MBX_PUSH_PATTERN, f"MBX{idx}-WRITE_DATA"
            )
            await ClockCycles(dut.clk_smu_i, CSR_SETTLE_CYCLES)
            expected |= 1 << idx
            self.sb.expect_eq(
                f"the outbound write-threshold IRQ of mailbox {idx} raises bit {idx} alone",
                sample(mbx, MBX_PORT),
                expected,
                evidence="CHK-SMU-LANE-MBX-IRQ",
            )
        self.sb.expect_eq(
            f"all {lanes} mailbox interrupt lanes are asserted together",
            expected,
            full,
            evidence="CHK-SMU-LANE-MBX-IRQ",
        )

        for idx in range(lanes):
            await self._wr32(self._mbx_addr(idx, "IRQEN"), 0, f"MBX{idx}-IRQEN-CLR")
            await ClockCycles(dut.clk_smu_i, CSR_SETTLE_CYCLES)
            expected &= ~(1 << idx)
            self.sb.expect_eq(
                f"clearing IRQEN of mailbox {idx} retires bit {idx} alone",
                sample(mbx, MBX_PORT),
                expected,
                evidence="CHK-SMU-LANE-MBX-IRQ",
            )
        self.sb.expect_eq(
            f"all {lanes} mailbox interrupt lanes are released together",
            expected,
            0,
            evidence="CHK-SMU-LANE-MBX-IRQ",
        )

    @staticmethod
    def _mbx_addr(idx: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_MAILBOX_OUTBOUND_MAILBOX_{idx}_{reg}_BASE_ADDR")

    # ------------------------------------------------------------------
    # S5: every GPIO pad on its interrupt lane and its DATA_CTRL mirror.
    # ------------------------------------------------------------------
    async def _gpio_lanes(self) -> None:
        dut = self.dut
        lanes = self._lane_count("tb_gpio_interrupt", GPIO_LANES, "gpio_interrupt_o")
        self._lane_count("tb_gpio_drive_en", GPIO_LANES, "gpio_pad_io")
        full = _mask(lanes)

        self.sb.expect_eq(
            f"gpio_interrupt_o[{lanes - 1}:0] clear before any pad is armed",
            self._sample("tb_gpio_interrupt"),
            0,
            evidence="CHK-SMU-LANE-GPIO",
        )
        for pin in range(lanes):
            await self._wr32(
                smc_indexed_addr(GPIO_DATA_CTRL_SYM, pin), GPIO_ARM, f"GPIO_INTF[{pin}] DATA_CTRL"
            )
        armed = await self._rd32(smc_indexed_addr(GPIO_DATA_CTRL_SYM, 0), "GPIO_INTF[0] DATA_CTRL")
        self.sb.expect_eq(
            "the pads are armed as active-high levels",
            armed & (INTERRUPT_ENABLE_BM | INTERRUPT_TYPE_BM),
            INTERRUPT_ENABLE_BM,
            evidence="CHK-SMU-LANE-GPIO",
        )

        dut.tb_gpio_drive_val.value = full
        dut.tb_gpio_drive_en.value = full
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            f"driving all {lanes} pads high raises every gpio_interrupt_o lane",
            self._sample("tb_gpio_interrupt"),
            full,
            evidence="CHK-SMU-LANE-GPIO",
        )
        self.sb.expect_eq(
            f"DATA_CTRL.PAD2CORE mirrors the driven pad on all {lanes} interfaces",
            await self._pad2core_vector(lanes),
            full,
            evidence="CHK-SMU-LANE-GPIO",
        )

        dut.tb_gpio_drive_val.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            f"the level interrupt releases with the pad on all {lanes} lanes",
            self._sample("tb_gpio_interrupt"),
            0,
            evidence="CHK-SMU-LANE-GPIO",
        )
        self.sb.expect_eq(
            f"DATA_CTRL.PAD2CORE follows all {lanes} pads back down",
            await self._pad2core_vector(lanes),
            0,
            evidence="CHK-SMU-LANE-GPIO",
        )

        dut.tb_gpio_drive_en.value = 0

    async def _pad2core_vector(self, lanes: int) -> int:
        """DATA_CTRL.PAD2CORE of every GPIO interface, packed by pin index."""
        before = self.reads
        vector = 0
        for pin in range(lanes):
            data_ctrl = await self._rd32(
                smc_indexed_addr(GPIO_DATA_CTRL_SYM, pin), f"GPIO_INTF[{pin}] DATA_CTRL"
            )
            if data_ctrl & PAD2CORE_BM:
                vector |= 1 << pin
        if self.reads - before != lanes:
            raise AssertionError(
                f"PAD2CORE sweep took {self.reads - before} reads, expected one per {lanes} pads"
            )
        return vector

    # ------------------------------------------------------------------
    # S6: every UART instance on its own interrupt lane.
    # ------------------------------------------------------------------
    async def _uart_interrupt_lanes(self) -> None:
        dut = self.dut
        lanes = self._lane_count("tb_uart_interrupt", UART_LANES, "uart_interrupt_o")
        rose = 0
        fell = 0

        # CLOCK_GATE_CONTROL.UART_CG_EN is enable-high gating and resets clear,
        # so the peripheral clock is already running; read it rather than
        # assume it.
        cg = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        self.sb.expect_eq(
            "the UART clock gate is open",
            cg & UART_CG_EN_BM,
            0,
            evidence="CHK-SMU-LANE-UART-IRQ",
        )
        self.sb.expect_eq(
            f"uart_interrupt_o[{lanes - 1}:0] clear before any instance is enabled",
            self._sample("tb_uart_interrupt"),
            0,
            evidence="CHK-SMU-LANE-UART-IRQ",
        )

        for idx in range(lanes):
            bit = 1 << idx
            base = smc_indexed_addr(UART_BASE_SYM, idx)
            await self._wr32(base + UART_IER_OFF, IER_ETBEI_BM, f"UART{idx} IER")
            await ClockCycles(dut.clk_periph_i, SYNC_CYCLES)
            self.sb.expect_eq(
                f"enabling the transmitter-empty source raises uart_interrupt_o[{idx}] alone",
                self._sample("tb_uart_interrupt"),
                bit,
                evidence="CHK-SMU-LANE-UART-IRQ",
            )
            rose |= bit
            iir = await self._rd32(base + UART_IIR_OFF, f"UART{idx} IIR")
            self.sb.expect_eq(
                f"UART{idx} IIR reports pending (active low) with the "
                "transmitter-holding-register-empty code",
                (iir & IIR_PENDING_BM, (iir & IIR_ID_BM) >> IIR_ID_BP),
                (0, IIR_ID_THRE),
                evidence="CHK-SMU-LANE-UART-IRQ",
            )
            # Reading IIR is what clears this source, so the pin has to fall.
            await ClockCycles(dut.clk_periph_i, SYNC_CYCLES)
            self.sb.expect_eq(
                f"the IIR read retires uart_interrupt_o[{idx}]",
                self._sample("tb_uart_interrupt"),
                0,
                evidence="CHK-SMU-LANE-UART-IRQ",
            )
            fell |= bit
            await self._wr32(base + UART_IER_OFF, 0, f"UART{idx} IER")

        self.sb.expect_eq(
            f"every one of the {lanes} UART interrupt lanes was raised and retired on its own",
            (bin(rose).count("1"), bin(fell).count("1")),
            (lanes, lanes),
            evidence="CHK-SMU-LANE-UART-IRQ",
        )
