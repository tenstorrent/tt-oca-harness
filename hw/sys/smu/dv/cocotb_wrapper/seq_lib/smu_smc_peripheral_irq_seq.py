# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_peripheral_irq_test. SEP=1, no Force.

The two raw peripheral interrupt vectors port_table.adoc brings out of the
wrapper, each raised through the SMC register that owns its source.

S1  GPIO. The GPIO programming guide (``hw/ip/gpio/doc/programming.adoc``,
    "LSIO Interface Operation") gives a hardware LSIO peripheral first claim
    on a pad while its interface select is asserted and ``DATA_CTRL.LSIO_DISABLE``
    is clear, and the pad table (``doc/integrator/meta/ocah_gpio_table.csv``)
    assigns pad 0 to ``SPI.DATA[0]``, so the pad starts under LSIO ownership and
    ``DATA_CTRL.LSIO_ENABLE`` reads back that state. The interrupt is captured
    only while ``DATA_CTRL.INTERRUPT_ENABLE`` is set and the pad level is
    mirrored in ``DATA_CTRL.PAD2CORE`` (``gpio_intf`` RDL field descriptions).
    The leaf takes the pin away from the LSIO first -- which
    ``DATA_CTRL.LSIO_ENABLE`` reads back -- then drives the pad and requires
    both the interrupt output and the ``DATA_CTRL.PAD2CORE`` mirror to follow
    it up and down.

    The interrupt flop only updates while the enable is set, so the pad is
    released before the enable is cleared.

S2  UART. ``IER.ETBEI`` enables the transmitter-holding-register-empty
    interrupt (``uart_16550_main.rdl``), and the transmitter holds nothing out
    of reset, so one register write has to raise ``uart_interrupt_o[0]``.
    ``IIR.INTERRUPT_PENDING`` is active low and ``IIR.INTERRUPT_ID`` has to
    carry the code the same RDL's field description assigns to that source;
    reading IIR is also what clears the request, so the read is followed by a
    check that the pin has fallen.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_boundary_regs import (
    gpio_intf_u32,
    smc_base_config_u32,
    uart_iir_interrupt_id,
    uart_main_u32,
)
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

GPIO_PIN = 0
GPIO_DATA_CTRL = smc_indexed_addr("SMC_TOP_GPIO_INTF_DATA_CTRL_BASE_ADDR", GPIO_PIN)
ENABLE_RX_TX_BP = gpio_intf_u32("GPIO_INTF__DATA_CTRL__ENABLE_RX_TX_bp")
INTERFACE_ENABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERFACE_ENABLE_bm")
INTERRUPT_ENABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_ENABLE_bm")
LSIO_DISABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_DISABLE_bm")
LSIO_ENABLE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm")
INTERRUPT_TYPE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bm")
PAD2CORE_BM = gpio_intf_u32("GPIO_INTF__DATA_CTRL__PAD2CORE_bm")
# gpio_intf.rdl DATA_CTRL.ENABLE_RX_TX: 2'b10 is "RX enabled".
GPIO_RX_ENABLE = 0b10 << ENABLE_RX_TX_BP
# gpio_intf.rdl DATA_CTRL.INTERRUPT_TYPE: 0 is an active-high level, so the
# reset encoding stays. A level, not an edge: an edge type gives a one-cycle
# pulse a CSR poll can miss.
GPIO_ARM = GPIO_RX_ENABLE | INTERFACE_ENABLE_BM | INTERRUPT_ENABLE_BM | LSIO_DISABLE_BM

UART_IDX = 0
UART_BASE = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_BASE_ADDR", UART_IDX)
UART_IER = UART_BASE + uart_main_u32("UART_16550_MAIN_IER_BASE_ADDR")
UART_IIR = UART_BASE + uart_main_u32("UART_16550_MAIN_IIR_BASE_ADDR")
IER_ETBEI_BM = uart_main_u32("UART_16550_MAIN__IER__ETBEI_bm")
IIR_PENDING_BM = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_ID_BM = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_ID_BP = uart_main_u32("UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
# uart_16550_main.rdl IIR.INTERRUPT_ID field description.
IIR_ID_THRE = uart_iir_interrupt_id("Transmitter Holding Register Empty")

SYNC_CYCLES = 32
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
UART_CG_EN_BM = smc_base_config_u32("SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__UART_CG_EN_bm")


class smu_smc_peripheral_irq_seq:
    """GPIO and UART raw interrupt outputs at the SMU boundary."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _vec(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=SMC_DBG_AXSIZE_4B, require_complete=True
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
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
        await self.cfg.reset_done.wait()
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._vec("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._gpio_interrupt()
        await self._uart_interrupt()

    async def _gpio_interrupt(self) -> None:
        dut = self.dut
        bit = 1 << GPIO_PIN
        self.sb.expect_eq(
            f"no GPIO interrupt on pin {GPIO_PIN} before it is armed",
            self._vec("tb_gpio_interrupt") & bit,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        before = await self._rd32(GPIO_DATA_CTRL, "GPIO_INTF[0] DATA_CTRL")
        self.sb.expect_eq(
            "the pin starts under LSIO ownership",
            before & LSIO_ENABLE_BM,
            LSIO_ENABLE_BM,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        # INTERRUPT_TYPE stays at its active-high-level reset encoding.
        await self._wr32(GPIO_DATA_CTRL, GPIO_ARM, "GPIO_INTF[0] DATA_CTRL")
        armed = await self._rd32(GPIO_DATA_CTRL, "GPIO_INTF[0] DATA_CTRL")
        self.sb.expect_eq(
            "the write takes the pin away from the LSIO owner",
            armed & LSIO_ENABLE_BM,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        self.sb.expect_eq(
            "the interrupt is armed as an active-high level",
            armed & (INTERRUPT_ENABLE_BM | INTERRUPT_TYPE_BM),
            INTERRUPT_ENABLE_BM,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        self.sb.expect_eq(
            "the pad still reads low with the buffer open",
            armed & PAD2CORE_BM,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )

        dut.tb_gpio0_drive_val.value = 1
        dut.tb_gpio0_drive_en.value = 1
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            f"driving the pad raises gpio_interrupt_o[{GPIO_PIN}]",
            self._vec("tb_gpio_interrupt") & bit,
            bit,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        driven = await self._rd32(GPIO_DATA_CTRL, "GPIO_INTF[0] DATA_CTRL")
        self.sb.expect_eq(
            "DATA_CTRL.PAD2CORE mirrors the driven pad",
            driven & PAD2CORE_BM,
            PAD2CORE_BM,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        self.sb.expect_eq(
            "no other GPIO lane moved",
            self._vec("tb_gpio_interrupt") & ~bit,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )

        dut.tb_gpio0_drive_val.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "the level interrupt releases with the pad",
            self._vec("tb_gpio_interrupt") & bit,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        released = await self._rd32(GPIO_DATA_CTRL, "GPIO_INTF[0] DATA_CTRL")
        self.sb.expect_eq(
            "DATA_CTRL.PAD2CORE follows the pad back down",
            released & PAD2CORE_BM,
            0,
            evidence="CHK-SMU-GPIO-IRQ",
        )
        dut.tb_gpio0_drive_en.value = 0
        await self._wr32(GPIO_DATA_CTRL, 0, "GPIO_INTF[0] DATA_CTRL")

    async def _uart_interrupt(self) -> None:
        dut = self.dut
        bit = 1 << UART_IDX
        # CLOCK_GATE_CONTROL.UART_CG_EN is enable-high gating and resets clear,
        # so the peripheral clock is already running; read it rather than
        # assume it.
        cg = await self._rd32(CLOCK_GATE_CONTROL, "CLOCK_GATE_CONTROL")
        uart_cg = UART_CG_EN_BM
        self.sb.expect_eq(
            "the UART clock gate is open",
            cg & uart_cg,
            0,
            evidence="CHK-SMU-UART-IRQ",
        )
        self.sb.expect_eq(
            f"no UART interrupt on instance {UART_IDX} before it is enabled",
            self._vec("tb_uart_interrupt") & bit,
            0,
            evidence="CHK-SMU-UART-IRQ",
        )
        idle_iir = await self._rd32(UART_IIR, "UART0 IIR")
        self.sb.expect_eq(
            "IIR reports no pending interrupt while none is enabled",
            idle_iir & IIR_PENDING_BM,
            IIR_PENDING_BM,
            evidence="CHK-SMU-UART-IRQ",
        )

        await self._wr32(UART_IER, IER_ETBEI_BM, "UART0 IER")
        await ClockCycles(dut.clk_periph_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "enabling the transmitter-empty source raises uart_interrupt_o[0]",
            self._vec("tb_uart_interrupt") & bit,
            bit,
            evidence="CHK-SMU-UART-IRQ",
        )
        self.sb.expect_eq(
            "no other UART instance moved",
            self._vec("tb_uart_interrupt") & ~bit,
            0,
            evidence="CHK-SMU-UART-IRQ",
        )
        iir = await self._rd32(UART_IIR, "UART0 IIR")
        self.sb.expect_eq(
            "IIR reports a pending interrupt (the field is active low)",
            iir & IIR_PENDING_BM,
            0,
            evidence="CHK-SMU-UART-IRQ",
        )
        self.sb.expect_eq(
            "IIR identifies the transmitter-holding-register-empty source",
            (iir & IIR_ID_BM) >> IIR_ID_BP,
            IIR_ID_THRE,
            evidence="CHK-SMU-UART-IRQ",
        )
        # Reading IIR is what clears this source, so the pin has to fall.
        await ClockCycles(dut.clk_periph_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "the IIR read retires the request at the pin",
            self._vec("tb_uart_interrupt") & bit,
            0,
            evidence="CHK-SMU-UART-IRQ",
        )
        await self._wr32(UART_IER, 0, "UART0 IER")
