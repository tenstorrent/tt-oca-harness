# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Six shapes of the I2C0 controller's format queue.

Six shapes, each a register sequence against the bench EEPROM target:

* **A NACK allowed.** `FDATA.NAKOK` on an address nobody answers: `i2c.rdl`
  says the controller then "will not halt, set the `CONTROLLER_EVENTS.NACK`
  flag, or assert the `CONTROLLER_HALT` interrupt", so the transfer runs on
  to its STOP.
* **Two transactions queued together.** Each with its own START and STOP, so
  the controller leaves the first one's STOP for the format FIFO with the
  second already waiting, and the target must see two of each.
* **A park that continues.** A transaction queued without its last entry
  runs dry and waits holding SCL low; the entry queued afterwards must finish
  it as one transaction. `CTRL.MULTI_CONTROLLER_MONITOR_EN` is on, so the
  controller sees the bus it parked on as busy and continues on the strength
  of its own open transaction. `TIMEOUT_CTRL` is set to bus mode with `EN`
  clear across the park: SCL is held low far longer than `VAL`, and with the
  timeout disabled no `BUS_TIMEOUT` may result.
* **A NACK outliving a disable.** `HOST_NACK_HANDLER_TIMEOUT` is armed, the
  controller NACKed, and `CTRL.ENABLEHOST` cleared before the timeout runs
  out. The controller closes the transaction with its own STOP, and the
  handler timeout must not run while the controller is disabled. With the
  NACK still uncleared the controller is enabled again: the timeout now runs
  out, but there is no transaction left to stop, so nothing reaches the bus.
* **Controller-mode loopback.** `i2c.rdl` limits `CTRL.LLPBK` in controller
  mode to the SMBus alert input, so a transfer made with it set must reach the
  target unchanged.
* **A receive FIFO nobody drains.** A read longer than the receive FIFO with
  no `RDATA` reads until it ends: `INTR_STATE.RX_OVERFLOW` must be raised, and
  the FIFO must then hold the first bytes read, as many as it holds.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_i2c_controller_disable_stop_test_seq import _PadWatch
from .smc_i2c_controller_exits_test_seq import (
    ABSENT_ADDR,
    EEPROM_ADDR,
    EVENTS_NACK,
    EVENTS_UNHANDLED_NACK_TIMEOUT,
    I2C0_HOST_NACK_HANDLER_TIMEOUT,
    NACK_TIMEOUT_EN,
    STATUS_RXEMPTY,
    smc_i2c_controller_exits_test_seq,
)
from .smc_i2c_field_masks import (
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_RXFULL,
    I2C_TIMEOUT_MODE_BUS,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_RDATA,
    I2C0_STATUS,
    I2C0_WRAP_CTRL,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_ENABLE_CONTROLLER,
    _fdata,
    _i2c_u32,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
I2C0_TIMEOUT_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 0)
I2C0_HOST_TIMEOUT_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_TIMEOUT_CTRL_BASE_ADDR", 0)
I2C0_HOST_FIFO_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", 0)

FDATA_NAKOK = _i2c_u32("I2C__FDATA__NAKOK_bm")
CTRL_LLPBK = _i2c_u32("I2C__CTRL__LLPBK_bm")
CTRL_MULTI_CONTROLLER = _i2c_u32("I2C__CTRL__MULTI_CONTROLLER_MONITOR_EN_bm")
INTR_RX_OVERFLOW = _i2c_u32("I2C__INTR_STATE__RX_OVERFLOW_bm")
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
EVENTS_BUS_TIMEOUT = _i2c_u32("I2C__CONTROLLER_EVENTS__BUS_TIMEOUT_bm")
RXLVL_BM = _i2c_u32("I2C__HOST_FIFO_STATUS__RXLVL_bm")
RXLVL_BP = _i2c_u32("I2C__HOST_FIFO_STATUS__RXLVL_bp")

OFFSET_BASE = 0x20
#: `TIMEOUT_CTRL.VAL` across the park, in system clock cycles; the park holds
#: SCL low for many times this.
PARK_TIMEOUT_CYCLES = 100
PARK_CYCLES = 3000
#: HOST_TIMEOUT_CTRL.VAL for the park: how long the bus must idle high before
#: the multi-controller monitor calls it free.
BUS_IDLE_CYCLES = 50
#: `HOST_NACK_HANDLER_TIMEOUT.VAL`, and how long the controller is left
#: disabled with the NACK pending: several times the timeout.
NACK_HANDLER_CYCLES = 2000
DISABLED_CYCLES = 4 * NACK_HANDLER_CYCLES
#: A read longer than the receive FIFO, whose depth is read off
#: `HOST_FIFO_STATUS.RXLVL` once it overflows.
OVERFLOW_READ = 96
POLL_CYCLES = 100
SETTLE_CYCLES = 500
POLLS = 2000


class smc_i2c_controller_queue_shapes_test_seq(smc_i2c_controller_exits_test_seq):
    """NAKOK, two queued transactions, a park that continues, a NACK across a disable,
    controller loopback and an undrained receive FIFO."""

    def __init__(self, name: str = "smc_i2c_controller_queue_shapes_test_seq") -> None:
        super().__init__(name)
        self.rx_depth = 0

    async def _poll(self, label: str, addr: int, mask: int, want: bool) -> int:
        value = 0
        for _ in range(POLLS):
            value = await self.csr_read(label, addr)
            if bool(value & mask) == want:
                return value
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: bit 0x{mask:x} never reached {int(want)} (0x{value:08x})")

    async def _clear_intr(self, label: str) -> None:
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)

    async def _nakok_leg(self) -> None:
        assert self.slave is not None
        label = "NAKOK"
        await self._enable_host(label)
        await self._clear_intr(label)
        stops = self.slave.stops
        await self.csr_write(
            f"{label}_ADDR", I2C0_FDATA, _fdata(ABSENT_ADDR << 1, I2C_FDATA_START | FDATA_NAKOK)
        )
        await self.csr_write(
            f"{label}_DATA", I2C0_FDATA, _fdata(0x5A, I2C_FDATA_STOP | FDATA_NAKOK)
        )
        await self._wait_hostidle(label)
        events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
        intr = await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE)
        assert events == 0, (
            f"{label}: CONTROLLER_EVENTS reads 0x{events:08x} after NACKs the entries allowed"
        )
        assert not intr & INTR_CONTROLLER_HALT and intr & INTR_CMD_COMPLETE, (
            f"{label}: INTR_STATE=0x{intr:08x}; want CONTROLLER_HALT clear and CMD_COMPLETE set"
        )
        assert self.slave.stops == stops + 1, f"{label}: the transfer did not end in one STOP"
        cocotb.log.info(
            "CHK-I2C-CTRL-NAKOK: a write to an address nobody answers, both entries carrying "
            "FDATA.NAKOK, ran to its STOP with CONTROLLER_EVENTS at 0, CONTROLLER_HALT clear "
            "and CMD_COMPLETE set"
        )

    async def _back_to_back_leg(self) -> None:
        assert self.slave is not None
        label = "TWO"
        await self._enable_host(label)
        starts, stops = self.slave.starts, self.slave.stops
        payload = (0xA1, 0xB2)
        for index, byte in enumerate(payload):
            await self.csr_write(
                f"{label}_ADDR{index}", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
            )
            await self.csr_write(f"{label}_OFFSET{index}", I2C0_FDATA, _fdata(OFFSET_BASE + index))
            await self.csr_write(f"{label}_DATA{index}", I2C0_FDATA, _fdata(byte, I2C_FDATA_STOP))
        await self._wait_hostidle(label)
        got = self.slave.read_mem(OFFSET_BASE, len(payload))
        assert got == bytes(payload), (
            f"{label}: the target holds {got.hex()} after two queued writes of "
            f"{bytes(payload).hex()}"
        )
        assert (self.slave.starts - starts, self.slave.stops - stops) == (2, 2), (
            f"{label}: the target saw {self.slave.starts - starts} STARTs and "
            f"{self.slave.stops - stops} STOPs for two queued transactions"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-BACK-TO-BACK: two transactions queued together, each with its own "
            "START and STOP, both reached the target (%s) as two STARTs and two STOPs",
            got.hex(),
        )

    async def _park_continue_leg(self) -> None:
        assert self.slave is not None
        label = "PARK"
        await self._enable_host(label)
        # CTRL.MULTI_CONTROLLER_MONITOR_EN is set with ENABLEHOST, as i2c.rdl requires, so
        # the controller tracks the bus it parks on as busy rather than free.
        await self.csr_write(f"{label}_HOST_OFF", I2C0_CTRL, 0)
        # With the monitor on, the bus counts as free only after it has idled high for
        # HOST_TIMEOUT_CTRL.VAL; zero would never free it.
        await self.csr_write(f"{label}_HOST_TIMEOUT", I2C0_HOST_TIMEOUT_CTRL, BUS_IDLE_CYCLES)
        ctrl = I2C_CTRL_ENABLEHOST | CTRL_MULTI_CONTROLLER
        await self.csr_write(f"{label}_CTRL_MCM", I2C0_CTRL, ctrl)
        await self.csr_read(f"{label}_CTRL_MCM_RB", I2C0_CTRL, expected=ctrl)
        timeout = I2C_TIMEOUT_MODE_BUS | PARK_TIMEOUT_CYCLES
        await self.csr_write(f"{label}_TIMEOUT", I2C0_TIMEOUT_CTRL, timeout)
        await self.csr_read(f"{label}_TIMEOUT_RB", I2C0_TIMEOUT_CTRL, expected=timeout)
        starts, stops = self.slave.starts, self.slave.stops
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(OFFSET_BASE + 4))
        await self._poll(f"{label}_DRAINED", I2C0_STATUS, I2C_STATUS_FMTEMPTY, True)
        await ClockCycles(cocotb.top.clk_smc_i, PARK_CYCLES)
        status = await self.csr_read(f"{label}_PARKED", I2C0_STATUS)
        assert not status & I2C_STATUS_HOSTIDLE, (
            f"{label}: STATUS.HOSTIDLE is set with the transaction open (0x{status:08x})"
        )
        assert int(cocotb.top.tb_i2c0_scl.value) == 0, f"{label}: SCL is not held low"
        events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
        assert events & EVENTS_BUS_TIMEOUT == 0, (
            f"{label}: CONTROLLER_EVENTS.BUS_TIMEOUT set across a park of {PARK_CYCLES} cycles "
            f"with TIMEOUT_CTRL in bus mode but EN clear (0x{events:08x})"
        )
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(0xC3, I2C_FDATA_STOP))
        await self._wait_hostidle(label)
        await self.csr_write(f"{label}_TIMEOUT_OFF", I2C0_TIMEOUT_CTRL, 0)
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self.csr_write(f"{label}_HOST_TIMEOUT_OFF", I2C0_HOST_TIMEOUT_CTRL, 0)
        got = self.slave.read_mem(OFFSET_BASE + 4, 1)
        assert got == b"\xc3", f"{label}: the target holds {got.hex()}, not c3"
        assert (self.slave.starts - starts, self.slave.stops - stops) == (1, 1), (
            f"{label}: the target saw {self.slave.starts - starts} STARTs and "
            f"{self.slave.stops - stops} STOPs; the park and the entry after it are one "
            f"transaction"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-PARK-CONTINUE: with the multi-controller monitor on, a transaction "
            "that ran dry parked holding SCL low with STATUS.HOSTIDLE clear, raised no "
            "BUS_TIMEOUT over %d cycles with TIMEOUT_CTRL in bus mode and EN clear, and the "
            "entry queued afterwards finished it as one transaction",
            PARK_CYCLES,
        )

    async def _nack_across_disable_leg(self) -> None:
        assert self.slave is not None
        label = "NACKOFF"
        await self._enable_host(label)
        want = NACK_TIMEOUT_EN | NACK_HANDLER_CYCLES
        await self.csr_write(f"{label}_NACK_TIMEOUT", I2C0_HOST_NACK_HANDLER_TIMEOUT, want)
        await self.csr_read(
            f"{label}_NACK_TIMEOUT_RB", I2C0_HOST_NACK_HANDLER_TIMEOUT, expected=want
        )
        stops = self.slave.stops
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(ABSENT_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(0x11, I2C_FDATA_STOP))
        events = await self._poll(f"{label}_NACK", I2C0_CONTROLLER_EVENTS, EVENTS_NACK, True)
        assert not events & EVENTS_UNHANDLED_NACK_TIMEOUT, (
            f"{label}: the handler timeout ran out before the disable (0x{events:08x})"
        )
        # The NACK is flagged on the acknowledge pulse; the controller reaches IDLE,
        # where the disable closes the transaction, only after the hold that follows.
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        assert int(cocotb.top.tb_i2c0_scl.value) == 0, (
            f"{label}: SCL is not held low with the NACKed transaction open"
        )
        watch = _PadWatch()
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await ClockCycles(cocotb.top.clk_smc_i, DISABLED_CYCLES)
        stopped = watch.stops
        watch.stop()
        events = await self.csr_read(f"{label}_DISABLED_EVENTS", I2C0_CONTROLLER_EVENTS)
        assert stopped == 1 and self.slave.stops == stops + 1, (
            f"{label}: clearing ENABLEHOST with the NACKed transaction open made {stopped} STOPs "
            f"on the pads, not 1"
        )
        assert events & EVENTS_NACK and not events & EVENTS_UNHANDLED_NACK_TIMEOUT, (
            f"{label}: CONTROLLER_EVENTS=0x{events:08x} after {DISABLED_CYCLES} cycles disabled; "
            f"the NACK stays and the {NACK_HANDLER_CYCLES}-cycle handler timeout must not run "
            f"while the controller is disabled"
        )

        watch = _PadWatch()
        await self.csr_write(f"{label}_REENABLE", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        events = await self._poll(
            f"{label}_TIMEOUT", I2C0_CONTROLLER_EVENTS, EVENTS_UNHANDLED_NACK_TIMEOUT, True
        )
        await ClockCycles(cocotb.top.clk_smc_i, NACK_HANDLER_CYCLES)
        edges = (watch.rises, watch.stops)
        watch.stop()
        assert edges == (0, 0), (
            f"{label}: after the handler timeout ran out with no transaction open, "
            f"{edges[0]} SCL rises and {edges[1]} STOPs reached the pads"
        )
        await self.csr_write(f"{label}_CLEAR_NACK", I2C0_CONTROLLER_EVENTS, EVENTS_NACK)
        alone = await self.csr_read(f"{label}_TIMEOUT_ALONE", I2C0_CONTROLLER_EVENTS)
        assert alone == EVENTS_UNHANDLED_NACK_TIMEOUT, (
            f"{label}: clearing NACK alone left CONTROLLER_EVENTS=0x{alone:08x}; "
            f"UNHANDLED_NACK_TIMEOUT clears only on its own written one"
        )
        await self.csr_write(f"{label}_CLEAR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write(f"{label}_NACK_TIMEOUT_OFF", I2C0_HOST_NACK_HANDLER_TIMEOUT, 0)
        await self._wait_hostidle(label)
        cocotb.log.info(
            "CHK-I2C-CTRL-NACK-DISABLED: with HOST_NACK_HANDLER_TIMEOUT armed, a NACKed "
            "transaction closed with one STOP when ENABLEHOST was cleared, the handler timeout "
            "did not run over %d disabled cycles, and once re-enabled it ran out "
            "(CONTROLLER_EVENTS=0x%08x) with nothing reaching the pads; clearing NACK alone "
            "left UNHANDLED_NACK_TIMEOUT set on its own",
            DISABLED_CYCLES,
            events,
        )

    async def _loopback_leg(self) -> None:
        assert self.slave is not None
        label = "LLPBK"
        await self._enable_host(label)
        ctrl = I2C_CTRL_ENABLEHOST | CTRL_LLPBK
        await self.csr_write(f"{label}_CTRL", I2C0_CTRL, ctrl)
        await self.csr_read(f"{label}_CTRL_RB", I2C0_CTRL, expected=ctrl)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(OFFSET_BASE + 8))
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(0x6E, I2C_FDATA_STOP))
        await self._wait_hostidle(label)
        events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
        got = self.slave.read_mem(OFFSET_BASE + 8, 1)
        assert got == b"\x6e" and events == 0, (
            f"{label}: with CTRL.LLPBK set in controller mode the target holds {got.hex()} "
            f"(want 6e) and CONTROLLER_EVENTS=0x{events:08x}"
        )
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        cocotb.log.info(
            "CHK-I2C-CTRL-LOOPBACK-HOST: a write made with CTRL.LLPBK set in controller mode "
            "reached the target unchanged with no controller event"
        )

    async def _rx_overflow_leg(self) -> None:
        assert self.slave is not None
        label = "RXOVF"
        await self._enable_host(label, timing0=(4, 6))
        await self._clear_intr(label)
        pattern = bytes((0x71 + 5 * i) & 0xFF for i in range(OVERFLOW_READ))
        self.slave.write_mem(0x80, pattern)
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(0x80))
        await self.csr_write(
            f"{label}_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        await self.csr_write(
            f"{label}_READ", I2C0_FDATA, _fdata(OVERFLOW_READ, I2C_FDATA_READB | I2C_FDATA_STOP)
        )
        await self._wait_hostidle(label)
        intr = await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE)
        status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
        level = await self.csr_read(f"{label}_LEVEL", I2C0_HOST_FIFO_STATUS)
        self.rx_depth = (level & RXLVL_BM) >> RXLVL_BP
        assert intr & INTR_RX_OVERFLOW, (
            f"{label}: a {OVERFLOW_READ}-byte read with nothing drained left "
            f"INTR_STATE.RX_OVERFLOW clear (0x{intr:08x})"
        )
        assert status & I2C_STATUS_RXFULL and 0 < self.rx_depth < OVERFLOW_READ, (
            f"{label}: STATUS=0x{status:08x}, RXLVL={self.rx_depth} after the read overflowed"
        )
        got = bytearray()
        for index in range(OVERFLOW_READ):
            status = await self.csr_read(f"{label}_DRAIN_STATUS{index}", I2C0_STATUS)
            if status & STATUS_RXEMPTY:
                break
            got.append((await self.csr_read(f"{label}_RDATA{index}", I2C0_RDATA)) & 0xFF)
        assert bytes(got) == pattern[: self.rx_depth], (
            f"{label}: the {len(got)} bytes drained, {bytes(got).hex()}, are not the first "
            f"{self.rx_depth} bytes read, {pattern[: self.rx_depth].hex()}"
        )
        await self.csr_write(f"{label}_INTR_W1C", I2C0_INTR_STATE, INTR_RX_OVERFLOW)
        intr = await self.csr_read(f"{label}_INTR_CLEARED", I2C0_INTR_STATE)
        assert not intr & INTR_RX_OVERFLOW, (
            f"{label}: RX_OVERFLOW survived a written one with the FIFO drained (0x{intr:08x})"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-RX-OVERFLOW: a %d-byte read with the receive FIFO left undrained "
            "raised INTR_STATE.RX_OVERFLOW and STATUS.RXFULL; the FIFO held %d bytes, the "
            "first %d read, in order, and RX_OVERFLOW cleared on a written one",
            OVERFLOW_READ,
            self.rx_depth,
            self.rx_depth,
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_QUEUE_SHAPES")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_queue_shapes_eeprom")
        await Timer(1, unit="us")

        await self._nakok_leg()
        await self._back_to_back_leg()
        await self._park_continue_leg()
        await self._nack_across_disable_leg()
        await self._loopback_leg()
        await self._rx_overflow_leg()
