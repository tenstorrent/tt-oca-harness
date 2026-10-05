# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The STOP the I2C0 controller makes on its own when its enable is cleared.

A controller that has started a transaction owns the bus until it gives a
STOP. The OpenTitan I2C theory of operation, which `hw/ip/i2c/doc/index.adoc`
adopts for controller behaviour, states what clearing `CTRL.ENABLEHOST` does
to an open transaction: software may "end the current transaction by setting
CTRL.ENABLEHOST to 1'b0", and "if a NACK handling timeout occurs or
CTRL.ENABLEHOST is cleared, then the FSM will halt again after the STOP
condition is sent. The STOP condition terminates the transaction, leaving the
FSM halted in the 'bus idle' state, with SDA and SCL released." Two open
transactions are driven to that STOP:

* **Parked.** The format FIFO runs dry without a STOP: `STATUS.FMTEMPTY` sets,
  `STATUS.HOSTIDLE` stays clear and the controller holds SCL low. Clearing
  the enable there must make the STOP.
* **Halted on a NACK.** The address nobody on the bench bus answers is NACKed.
  The theory of operation says the controller then "stops immediately
  following the (N)ACK bit's hold time after the SCL falling edge, and SCL
  remains asserted low", with `CONTROLLER_EVENTS.NACK` set and
  `INTR_STATE.CONTROLLER_HALT` raised. Clearing the enable there is the case
  the specification describes.

`INTR_STATE.CMD_COMPLETE` is raised only when the controller finishes a STOP or
a repeated START (`i2c.rdl`), so it is the register witness that the STOP was
the controller's; the bench target counts the STOP on the pads, and both pads
must read released afterwards. The enable cleared between two format entries
of a transfer in flight is not driven: no document states whether a STOP
follows there.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import I2C_CONTROLLER_EVENTS_NACK, I2C_STATUS_FMTEMPTY
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_START,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_ENABLE_CONTROLLER,
    _fdata,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave

EEPROM_ADDR = 0x50
#: An address no device on the bench bus answers, so its acknowledge slot
#: carries a NACK and the controller halts.
ABSENT_ADDR = 0x51
EEPROM_OFFSET = 0x70

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
INTR_ALL = 0xFFFF_FFFF

POLL_CYCLES = 100
IDLE_POLLS = 2000
PARK_SETTLE_CYCLES = 400
STOP_WAIT_CYCLES = 20_000


class _PadWatch:
    """Counts STOPs on the `tb_i2c0_*` pads while it runs."""

    def __init__(self) -> None:
        self.stops = 0
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        scl_pad = cocotb.top.tb_i2c0_scl
        sda_pad = cocotb.top.tb_i2c0_sda
        prev_scl = int(scl_pad.value)
        prev_sda = int(sda_pad.value)
        while True:
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            scl = int(scl_pad.value)
            sda = int(sda_pad.value)
            if scl and prev_scl and sda and not prev_sda:
                self.stops += 1
            prev_scl = scl
            prev_sda = sda

    def stop(self) -> None:
        self._task.cancel()


class smc_i2c_controller_disable_stop_test_seq(SmcCsrSeq):
    """Clear the enable with a transaction open, parked and halted on a NACK."""

    def __init__(self, name: str = "smc_i2c_controller_disable_stop_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None

    @staticmethod
    def _pads() -> tuple[int, int]:
        return int(cocotb.top.tb_i2c0_scl.value), int(cocotb.top.tb_i2c0_sda.value)

    async def _configure(self, label: str) -> None:
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write(f"{label}_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"{label}_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write(f"{label}_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write(f"{label}_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write(f"{label}_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, INTR_ALL)
        intr = await self.csr_read(f"{label}_INTR_ENTRY", I2C0_INTR_STATE)
        assert intr & INTR_CMD_COMPLETE == 0, (
            f"{label}: INTR_STATE.CMD_COMPLETE is still set before the leg starts (0x{intr:08x})"
        )

    async def _poll_status(self, label: str, want_set: int, message: str) -> int:
        status = 0
        for _ in range(IDLE_POLLS):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if status & want_set:
                return status
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: {message} (STATUS=0x{status:08x})")

    async def _wait_hostidle(self, label: str) -> int:
        return await self._poll_status(
            label, I2C_STATUS_HOSTIDLE, "STATUS.HOSTIDLE never set after the enable was cleared"
        )

    async def _wait_stop(self, watch: _PadWatch) -> bool:
        for _ in range(STOP_WAIT_CYCLES):
            if watch.stops > 0:
                return True
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        return False

    async def _clear_enable_for_stop(self, label: str, where: str) -> None:
        """Clear `CTRL.ENABLEHOST` and require one controller STOP on the pads."""
        assert self.slave is not None
        intr = await self.csr_read(f"{label}_INTR_OPEN", I2C0_INTR_STATE)
        assert intr & INTR_CMD_COMPLETE == 0, (
            f"{label}: INTR_STATE.CMD_COMPLETE is set before any STOP (0x{intr:08x})"
        )
        stops_before = self.slave.stops
        watch = _PadWatch()
        await self.csr_write(f"{label}_CLEAR_ENABLE", I2C0_CTRL, 0)
        stopped = await self._wait_stop(watch)
        watch.stop()
        assert stopped, (
            f"{label}: no STOP appeared on the pads within {STOP_WAIT_CYCLES} cycles of "
            f"CTRL.ENABLEHOST being cleared with the controller {where}"
        )
        intr = await self.csr_read(f"{label}_INTR_STOP", I2C0_INTR_STATE)
        assert intr & INTR_CMD_COMPLETE, (
            f"{label}: a STOP appeared on the pads but INTR_STATE.CMD_COMPLETE is clear "
            f"(0x{intr:08x}); the STOP was not the controller's"
        )
        assert self.slave.stops == stops_before + 1, (
            f"{label}: the bench target counted {self.slave.stops - stops_before} STOPs "
            f"after the enable was cleared, not 1"
        )
        await ClockCycles(cocotb.top.clk_smc_i, PARK_SETTLE_CYCLES)
        assert self._pads() == (1, 1), (
            f"{label}: the pads read {self._pads()} after the STOP; SDA and SCL are released "
            f"once the STOP terminates the transaction"
        )

    async def _parked_leg(self) -> None:
        """Let the format FIFO run dry mid-transaction, then clear the enable."""
        label = "PARKED"
        await self._configure(label)
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET))
        await self._poll_status(label, I2C_STATUS_FMTEMPTY, "the format FIFO never drained")
        await ClockCycles(cocotb.top.clk_smc_i, PARK_SETTLE_CYCLES)
        status = await self.csr_read(f"{label}_PARKED_STATUS", I2C0_STATUS)
        assert not status & I2C_STATUS_HOSTIDLE, (
            f"{label}: STATUS.HOSTIDLE is set with the transaction still open "
            f"(0x{status:08x}); the controller is not parked"
        )
        scl, _ = self._pads()
        assert scl == 0, f"{label}: SCL is released while the controller is parked"
        await self._clear_enable_for_stop(label, "parked with its format FIFO empty")
        await self._wait_hostidle(label)
        cocotb.log.info(
            "CHK-I2C-CTRL-DISABLE-STOP-IDLE: with the controller parked mid-transaction, "
            "holding SCL low with STATUS.FMTEMPTY set and STATUS.HOSTIDLE clear, clearing "
            "CTRL.ENABLEHOST made one STOP on the pads, raised INTR_STATE.CMD_COMPLETE, "
            "released both pads and returned the controller to idle"
        )

    async def _halted_leg(self) -> None:
        """Halt the controller on a NACKed address, then clear the enable."""
        label = "HALTED"
        await self._configure(label)
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(ABSENT_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET))
        events = 0
        for _ in range(IDLE_POLLS):
            events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
            if events & I2C_CONTROLLER_EVENTS_NACK:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: CONTROLLER_EVENTS.NACK never set after the address nobody answers "
                f"(CONTROLLER_EVENTS=0x{events:08x})"
            )
        await ClockCycles(cocotb.top.clk_smc_i, PARK_SETTLE_CYCLES)
        status = await self.csr_read(f"{label}_HALTED_STATUS", I2C0_STATUS)
        assert not status & I2C_STATUS_HOSTIDLE, (
            f"{label}: STATUS.HOSTIDLE is set while the controller is halted on the NACK "
            f"(0x{status:08x})"
        )
        assert not status & I2C_STATUS_FMTEMPTY, (
            f"{label}: the format FIFO is empty (0x{status:08x}); the halted controller still "
            f"holds the byte queued behind the address, so this is a halt and not a park"
        )
        intr = await self.csr_read(f"{label}_INTR_HALTED", I2C0_INTR_STATE)
        assert intr & INTR_CONTROLLER_HALT, (
            f"{label}: INTR_STATE.CONTROLLER_HALT is clear with CONTROLLER_EVENTS.NACK set "
            f"(0x{intr:08x})"
        )
        scl, _ = self._pads()
        assert scl == 0, f"{label}: SCL is released while the controller is halted on the NACK"
        await self._clear_enable_for_stop(label, "halted on a NACKed address")
        await self.csr_write(
            f"{label}_EVENTS_RELEASE", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self._wait_hostidle(label)
        cocotb.log.info(
            "CHK-I2C-CTRL-DISABLE-STOP-HALTED: with the controller halted on a NACKed "
            "address, holding SCL low with CONTROLLER_EVENTS.NACK set, STATUS.HOSTIDLE clear "
            "and a byte still queued, clearing CTRL.ENABLEHOST made one STOP on the pads, "
            "raised INTR_STATE.CMD_COMPLETE and released both pads; the controller returned "
            "to idle once the halt events were cleared"
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_DISABLE_STOP")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_disable_stop_eeprom")
        await Timer(1, unit="us")

        await self._parked_leg()
        await self._halted_leg()
