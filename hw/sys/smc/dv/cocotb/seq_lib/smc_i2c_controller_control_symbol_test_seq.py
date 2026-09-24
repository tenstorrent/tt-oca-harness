# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A control symbol appearing under the I2C0 controller mid-transfer.

An SDA edge while SCL is high is a START or a STOP, so one that appears in the
middle of somebody else's transfer is a protocol violation the controller has
to notice. `i2c_controller_fsm.sv` checks for it in every state where it holds
SCL released, names it "Unexpected Stop / Start", raises
`INTR_STATE.SDA_UNSTABLE` and abandons the transfer.

`smc_i2c_controller_sda_interference_test` pulls SDA low at time offsets
measured in bit periods, which lands the edge wherever it falls -- and with
this controller's timing that is usually while SCL is low, where it is a
different event (`SDA_INTERFERENCE`, another device driving against the
controller). This leaf synchronises instead: it counts SCL rising edges and
pulls SDA low inside the high window of a chosen one, so the edge is a control
symbol by construction and lands in a chosen part of the bit loop.

Two points are driven, which are the two slots where the line is high because
it is released rather than driven: the acknowledge of an address nobody
answers, and a one bit of a byte the target is returning. The read point needs
a device that answers, so the bench EEPROM target is on the pads throughout.

The other two slots where the controller holds SCL released -- a bit it is
transmitting, and the not-acknowledge it drives at the end of a read -- are
high only because the controller is driving them. An external pull there is
interference, which the design detects from the level alone and acts on a
cycle before the control-symbol check, which needs the line sampled on two
consecutive cycles; both versions of this leaf that tried those slots measured
`SDA_INTERFERENCE` and no control symbol. They are left uncovered rather than
claimed.

The pull is released inside the same SCL high window. A longer one reaches the
next state, where the controller is driving the line, and there the same pull
is interference rather than a control symbol -- `SDA_INTERFERENCE`, which a
first version of this leaf measured instead.

A clean transfer runs first, so the abandons are the difference the injection
makes. Nothing is asserted about the transfer after an injection: on this DUT
the next transaction from the same controller is NACKed even once the events
are cleared, so each leg re-enables the controller from scratch instead.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import I2C_INTR_SDA_UNSTABLE
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
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_ENABLE_CONTROLLER,
    _fdata,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

EEPROM_ADDR = 0x50
#: An address no device on the bench bus answers, so the acknowledge slot
#: carries a NACK -- SDA high -- and an injected pull makes an edge there.
ABSENT_ADDR = 0x51
EEPROM_OFFSET = 0x40
CLEAN_BYTE = 0x5A

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)

#: Which SCL rising edge of the transfer the edge is injected on, counted
#: from the START. SDA is open-drain, so a pull only makes an edge where the
#: line is already high, and it is only a control symbol where the controller
#: is not the one holding it high -- where it is, the same pull is
#: interference, which the design acts on a cycle earlier. That leaves the
#: acknowledge of an address nobody answers, and a one bit of a byte the
#: target is returning: rise 9 of a write to `ABSENT_ADDR`, and rise 30 of the
#: read, which sits after nine rises for the address byte, nine for the offset
#: byte, ten for the repeated start and read address, and one more for the
#: second bit of `CLEAN_BYTE`.
INJECTIONS = (
    ("ADDR_ACK", ABSENT_ADDR, False, 9),
    ("READ_BIT", EEPROM_ADDR, True, 30),
)
#: How long SDA is held low once the edge has been made. Long enough for the
#: core to sample the change on two consecutive cycles of its own clock, and
#: short enough to be released inside the same SCL high window: a pull that
#: outlasted the slot would reach a state where the controller is driving the
#: line, where it is interference rather than a control symbol.
HOLD_NS = 150
EDGE_WAIT_CYCLES = 200_000
POLL_CYCLES = 200
IDLE_POLLS = 2000
INTR_POLLS = 200


class smc_i2c_controller_control_symbol_test_seq(SmcCsrSeq):
    """An unexpected START or STOP must be reported and the transfer dropped."""

    def __init__(self, name: str = "smc_i2c_controller_control_symbol_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.injector: SmcI2cMasterVip | None = None
        self.hits: list[tuple[str, int]] = []

    @staticmethod
    def _scl() -> int:
        raw = cocotb.top.tb_i2c0_scl.value
        assert raw.is_resolvable, f"tb_i2c0_scl is not resolvable: {raw}"
        return int(raw)

    async def _wait_hostidle(self, label: str) -> None:
        for _ in range(IDLE_POLLS):
            status = await self.csr_read(f"{label}_IDLE", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
        raise AssertionError(
            f"{label}: the controller never returned to idle (CONTROLLER_EVENTS=0x{events:08x})"
        )

    async def _wait_busy(self, label: str) -> None:
        for _ in range(IDLE_POLLS):
            status = await self.csr_read(f"{label}_BUSY", I2C0_STATUS)
            if not status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_smc_i, 20)
        raise AssertionError(f"{label}: the controller never left idle after the queue")

    async def _enable_host(self, label: str) -> None:
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
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, I2C_INTR_SDA_UNSTABLE)
        intr = await self.csr_read(f"{label}_INTR_ENTRY", I2C0_INTR_STATE)
        assert intr & I2C_INTR_SDA_UNSTABLE == 0, (
            f"{label}: INTR_STATE.SDA_UNSTABLE is still set before the leg starts (0x{intr:08x})"
        )
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _queue(self, label: str, addr7: int, read: bool, offset: int, value: int) -> None:
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(addr7 << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(offset))
        if read:
            await self.csr_write(
                f"{label}_RESTART", I2C0_FDATA, _fdata((addr7 << 1) | 1, I2C_FDATA_START)
            )
            await self.csr_write(
                f"{label}_READ", I2C0_FDATA, _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP)
            )
        else:
            await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(value, I2C_FDATA_STOP))

    async def _wait_start(self, label: str) -> None:
        """Wait for the START: SDA falling while SCL is high.

        Anchoring on the bus rather than on a status read is what makes the
        slot numbering below exact -- a poll of STATUS returns some cycles
        after the controller left idle, by which time it has already clocked
        bits.
        """
        sda = cocotb.top.tb_i2c0_sda
        prev = int(sda.value)
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = int(sda.value)
            if self._scl() and prev and not now:
                return
            prev = now
        raise AssertionError(f"{label}: no START appeared on the bus after the queue")

    async def _inject_on_rise(self, label: str, nth: int) -> None:
        """Pull SDA low inside the high window of the nth SCL rise of the transfer."""
        assert self.injector is not None
        await self._wait_start(label)
        seen = 0
        prev = self._scl()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._scl()
            if now and not prev:
                seen += 1
                if seen == nth:
                    sda_before = int(cocotb.top.tb_i2c0_sda.value)
                    cocotb.log.info(
                        "%s: injecting on SCL rise %d, SDA reads %d beforehand",
                        label,
                        nth,
                        sda_before,
                    )
                    self.injector._pull_sda(True)
                    await Timer(HOLD_NS, unit="ns")
                    self.injector._pull_sda(False)
                    return
            prev = now
        raise AssertionError(
            f"{label}: only {seen} of {nth} SCL rising edges appeared; the controller stopped "
            f"clocking before the injection point"
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_CONTROL_SYMBOL")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_symbol_eeprom")
        self.injector = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_symbol_injector")

        await self._enable_host("CLEAN")
        self.slave.write_mem(EEPROM_OFFSET, b"\x00")
        await self._queue("CLEAN", EEPROM_ADDR, False, EEPROM_OFFSET, CLEAN_BYTE)
        await self._wait_hostidle("CLEAN")
        got = self.slave.read_mem(EEPROM_OFFSET, 1)
        assert got == bytes([CLEAN_BYTE]), (
            f"the control transfer left 0x{got.hex()} at the target, not 0x{CLEAN_BYTE:02x}; "
            f"the injected legs below are the difference the edge makes"
        )
        intr = await self.csr_read("CLEAN_INTR", I2C0_INTR_STATE)
        assert intr & I2C_INTR_SDA_UNSTABLE == 0, (
            f"INTR_STATE.SDA_UNSTABLE is set after a transfer nobody interfered with (0x{intr:08x})"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-SYMBOL-CLEAN: an uninterrupted write reached the target and left "
            "INTR_STATE.SDA_UNSTABLE clear"
        )

        for label, addr7, read, nth in INJECTIONS:
            await self._enable_host(label)
            injector = cocotb.start_soon(self._inject_on_rise(label, nth))
            await self._queue(label, addr7, read, EEPROM_OFFSET, CLEAN_BYTE)
            await injector
            seen = 0
            for _ in range(INTR_POLLS):
                seen = await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE)
                if seen & I2C_INTR_SDA_UNSTABLE:
                    break
                await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            else:
                raise AssertionError(
                    f"{label}: the controller reported no SDA_UNSTABLE after SDA was pulled "
                    f"low inside the high window of SCL rise {nth} (INTR_STATE=0x{seen:08x}); "
                    f"an SDA edge while SCL is high is a START or a STOP, not data"
                )
            await self._wait_hostidle(label)
            self.hits.append((label, nth))

        cocotb.log.info(
            "CHK-I2C-CTRL-SYMBOL-UNSTABLE: an SDA edge made inside the high window of a chosen "
            "SCL pulse raised INTR_STATE.SDA_UNSTABLE and returned the controller to idle at "
            "all %d points of the bit loop it was injected into: %s",
            len(self.hits),
            ", ".join(f"{name} (SCL rise {n})" for name, n in self.hits),
        )
