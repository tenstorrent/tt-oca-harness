# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Another device on SCL at each point of an I2C controller transfer.

A multi-master bus lets any device pull SCL low. `i2c_controller_fsm` checks
for it in every state where it has released SCL, and what it concludes depends
on where it is:

* **SCL pulled low early**, while the controller holds a clock pulse high, is
  clock synchronisation: the controller raises `INTR_STATE.SCL_INTERFERENCE`
  and carries on. It is checked in the START hold, the acknowledge pulse, a
  read data pulse and the pulse of the acknowledge the controller drives
  itself.
* **SCL falling while a repeated START or the STOP is being set up**, or
  **both lines low while the STOP is held**, means the controller could not
  issue its control symbol before another device took the bus. The STOP hold
  lasts only until the controller sees SDA rise, so that leg takes SDA on the
  STOP's setup rise and keeps it low when the controller releases it, which
  holds the controller in the hold long enough to take SCL as well. The design reports that as
  arbitration loss (`CONTROLLER_EVENTS.ARBITRATION_LOST`, through
  `ctrl_symbol_failed`).
* **SCL held low across a rise the controller expects** is a stretch. The
  controller waits, in the setup of a first START, the setup of a repeated
  START, its own acknowledge pulse and the setup of the STOP, and the transfer
  then completes.

Two further legs use the same hold: one long enough to expire `TIMEOUT_CTRL`
in bus mode, which halts the controller with `CONTROLLER_EVENTS.BUS_TIMEOUT`,
and one during the setup of a repeated START that disables the controller
while the restart it was about to issue is still pending.

Every point is placed by counting edges on the pads -- the START, the Nth SCL
rise or the fall after it, or the STOP -- so each lands in the same state on
every run. The pull is made by a second bench driver on the same open-drain
line. Each leg re-enables the controller from scratch, since an arbitration
loss or a timeout halts it.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_MODE_BUS,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_RDATA,
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
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

EEPROM_ADDR = 0x50
OFFSET = 0x70
WRITE_BYTE = 0xA7
READ_PATTERN = bytes((0x61, 0x62))

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
I2C0_TIMEOUT_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 0)
INTR_SCL_INTERFERENCE = _i2c_u32("I2C__INTR_STATE__SCL_INTERFERENCE_bm")
EVENTS_ARBITRATION_LOST = _i2c_u32("I2C__CONTROLLER_EVENTS__ARBITRATION_LOST_bm")
EVENTS_BUS_TIMEOUT = _i2c_u32("I2C__CONTROLLER_EVENTS__BUS_TIMEOUT_bm")

# SCL rises from the START. A write ("W") clocks the address byte (1-8) and
# its acknowledge (9), the offset (10-17, ack 18), the data byte (19-26, ack
# 27), and rise 28 is the STOP's setup. A write, repeated START and two-byte
# read ("WRR") clocks the address and offset as before, rise 19 sets up the
# repeated START, 20-27 and 28 are the read address and its acknowledge, 29-36
# and 37 the first byte and the acknowledge the controller drives, 38-45 and
# 46 the second byte and its not-acknowledge.
#
# Each leg: (name, transfer, anchor, nth, delay_ns, action, hold_ns, outcome).
# ``anchor`` is "start", "rise", "fall" (the fall after rise ``nth``), or "now".
# ``action`` pulls SCL briefly, holds SCL, or -- for the STOP hold -- takes SDA
# on the STOP's setup rise, so the line stays low when the controller lets it
# go and the controller stays in the hold, and then takes SCL too.
#: How far into the STOP hold the second line is taken: past the STOP's setup,
#: which a pull on SCL would otherwise end as a failed setup instead.
STOP_HOLD_SCL_DELAY_NS = 150
PULL_NS = 100
STRETCH_NS = 5_000
LEGS = (
    ("HOLD_START", "W", "start", 0, 10, "scl", PULL_NS, "scl_interference"),
    ("ACK_PULSE", "W", "rise", 9, 60, "scl", PULL_NS, "scl_interference"),
    ("STOP_SETUP", "W", "rise", 28, 15, "scl", PULL_NS, "arbitration_lost"),
    ("READ_PULSE", "WRR", "rise", 30, 60, "scl", PULL_NS, "scl_interference"),
    ("HOST_ACK_PULSE", "WRR", "rise", 37, 60, "scl", PULL_NS, "scl_interference"),
    ("RESTART_SETUP", "WRR", "rise", 19, 15, "scl", PULL_NS, "arbitration_lost"),
    ("STOP_HOLD", "W", "rise", 28, 0, "hold_stop", 200, "arbitration_lost"),
    ("START_STRETCH", "W", "now", 0, 0, "hold", STRETCH_NS, "completes"),
    ("RESTART_STRETCH", "WRR", "fall", 18, 0, "hold", STRETCH_NS, "completes"),
    ("HOST_ACK_STRETCH", "WRR", "fall", 36, 0, "hold", STRETCH_NS, "completes"),
    ("STOP_STRETCH", "W", "fall", 27, 0, "hold", STRETCH_NS, "completes"),
)
#: Bus timeout for the timeout leg, in core clocks, and the hold that expires
#: it: several times the limit.
BUS_TIMEOUT_CYCLES = 200
BUS_TIMEOUT_HOLD_NS = 10_000

EDGE_WAIT_CYCLES = 200_000
POLL_CYCLES = 100
IDLE_POLLS = 3000


class smc_i2c_controller_scl_events_test_seq(SmcCsrSeq):
    """Another device on SCL, at each point of a controller transfer."""

    def __init__(self, name: str = "smc_i2c_controller_scl_events_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.other: SmcI2cMasterVip | None = None
        self.outcomes: dict[str, str] = {}
        self.retained: list[str] = []

    @staticmethod
    def _scl() -> int:
        raw = cocotb.top.tb_i2c0_scl.value
        assert raw.is_resolvable, f"tb_i2c0_scl is not resolvable: {raw}"
        return int(raw)

    @staticmethod
    def _sda() -> int:
        raw = cocotb.top.tb_i2c0_sda.value
        assert raw.is_resolvable, f"tb_i2c0_sda is not resolvable: {raw}"
        return int(raw)

    async def _enable_host(self, label: str, bus_timeout: bool = False) -> None:
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write(f"{label}_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write(f"{label}_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write(f"{label}_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write(f"{label}_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write(f"{label}_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        timeout = (
            (I2C_TIMEOUT_CTRL_EN | I2C_TIMEOUT_MODE_BUS | BUS_TIMEOUT_CYCLES) if bus_timeout else 0
        )
        await self.csr_write(f"{label}_TIMEOUT", I2C0_TIMEOUT_CTRL, timeout)
        await self.csr_read(f"{label}_TIMEOUT_RB", I2C0_TIMEOUT_CTRL, expected=timeout)
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, INTR_SCL_INTERFERENCE)
        events = await self.csr_read(f"{label}_EVENTS_ENTRY", I2C0_CONTROLLER_EVENTS)
        intr = await self.csr_read(f"{label}_INTR_ENTRY", I2C0_INTR_STATE)
        assert events == 0 and intr & INTR_SCL_INTERFERENCE == 0, (
            f"{label}: CONTROLLER_EVENTS=0x{events:08x} INTR_STATE=0x{intr:08x} before the leg"
        )
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _queue(self, label: str, transfer: str) -> None:
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(OFFSET))
        if transfer == "W":
            await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(WRITE_BYTE, I2C_FDATA_STOP))
            return
        await self.csr_write(
            f"{label}_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        await self.csr_write(
            f"{label}_READ", I2C0_FDATA, _fdata(len(READ_PATTERN), I2C_FDATA_READB | I2C_FDATA_STOP)
        )

    async def _wait_start(self, label: str) -> None:
        prev = self._sda()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._sda()
            if self._scl() and prev and not now:
                return
            prev = now
        raise AssertionError(f"{label}: no START appeared on the bus")

    async def _wait_rises(self, label: str, nth: int) -> None:
        seen = 0
        prev = self._scl()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._scl()
            if now and not prev:
                seen += 1
                if seen == nth:
                    return
            prev = now
        raise AssertionError(f"{label}: only {seen} of {nth} SCL rises appeared")

    async def _wait_fall(self, label: str) -> None:
        prev = self._scl()
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = self._scl()
            if prev and not now:
                return
            prev = now
        raise AssertionError(f"{label}: SCL never fell")

    async def _inject(self, label, anchor, nth, delay_ns, action, hold_ns, during=None) -> None:
        assert self.other is not None
        if anchor != "now":
            await self._wait_start(label)
        if anchor == "rise":
            await self._wait_rises(label, nth)
        elif anchor == "fall":
            await self._wait_rises(label, nth)
            await self._wait_fall(label)
        if delay_ns:
            await Timer(delay_ns, unit="ns")
        if action == "hold_stop":
            self.other._pull_sda(True)
            await Timer(STOP_HOLD_SCL_DELAY_NS, unit="ns")
        self.other._pull_scl(True)
        if during is not None:
            await during()
        await Timer(hold_ns, unit="ns")
        self.other._pull_scl(False)
        self.other._pull_sda(False)

    async def _recover_bus(self, label: str) -> None:
        """Return the bus to idle after a leg the controller did not finish.

        A leg that halts the controller can leave the bench target part-way
        through a byte, holding SDA low for an acknowledge. Clocking SCL until
        the target lets go and then issuing a STOP is the standard recovery;
        the next leg's START needs an idle bus.
        """
        assert self.other is not None
        half = self.other._half_ns
        for _ in range(18):
            if self._sda():
                break
            self.other._pull_scl(True)
            await Timer(half, unit="ns")
            self.other._pull_scl(False)
            await Timer(half, unit="ns")
        self.other._pull_sda(True)
        await Timer(half, unit="ns")
        self.other._pull_scl(False)
        await Timer(half, unit="ns")
        self.other._pull_sda(False)
        await Timer(4 * half, unit="ns")
        assert self._scl() and self._sda(), (
            f"{label}: the bus did not return to idle after the leg (SCL={self._scl()} "
            f"SDA={self._sda()})"
        )

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

    async def _wait_flag(self, label: str, addr: int, bit: int, what: str) -> int:
        value = 0
        for _ in range(IDLE_POLLS):
            value = await self.csr_read(f"{label}_FLAG", addr)
            if value & bit:
                return value
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(f"{label}: {what} never set (read 0x{value:08x})")

    async def _check_completed(self, label: str, transfer: str) -> None:
        await self._wait_hostidle(label)
        if transfer == "W":
            got = self.slave.read_mem(OFFSET, 1)
            assert got == bytes([WRITE_BYTE]), (
                f"{label}: the target holds 0x{got.hex()} at the offset, not the "
                f"0x{WRITE_BYTE:02x} written; the controller has to wait out the hold and "
                f"finish the transfer"
            )
        else:
            got = bytes(
                [
                    (await self.csr_read(f"{label}_RDATA{i}", I2C0_RDATA)) & 0xFF
                    for i in range(len(READ_PATTERN))
                ]
            )
            assert got == READ_PATTERN, (
                f"{label}: the controller read back {got.hex()}, not the "
                f"{READ_PATTERN.hex()} the target holds, after waiting out the hold"
            )
        events = await self.csr_read(f"{label}_EVENTS_DONE", I2C0_CONTROLLER_EVENTS)
        assert events == 0, (
            f"{label}: CONTROLLER_EVENTS reads 0x{events:08x} after a transfer whose clock was "
            f"only held; no timeout is armed"
        )

    async def _run_leg(self, leg) -> None:
        name, transfer, anchor, nth, delay_ns, action, hold_ns, outcome = leg
        await self._enable_host(name)
        if transfer == "W":
            self.slave.write_mem(OFFSET, b"\x00")
        else:
            self.slave.write_mem(OFFSET, READ_PATTERN)
        injector = cocotb.start_soon(self._inject(name, anchor, nth, delay_ns, action, hold_ns))
        await self._queue(name, transfer)
        await injector
        if outcome == "scl_interference":
            await self._wait_flag(
                name, I2C0_INTR_STATE, INTR_SCL_INTERFERENCE, "INTR_STATE.SCL_INTERFERENCE"
            )
            await self._wait_hostidle(name)
        elif outcome == "arbitration_lost":
            await self._wait_flag(
                name,
                I2C0_CONTROLLER_EVENTS,
                EVENTS_ARBITRATION_LOST,
                "CONTROLLER_EVENTS.ARBITRATION_LOST",
            )
            await self.csr_write(f"{name}_HALT_OFF", I2C0_CTRL, 0)
        else:
            await self._check_completed(name, transfer)
        await self._recover_bus(name)
        self.outcomes[name] = outcome

    async def _retain(self, bit: int, name: str) -> None:
        before = await self.csr_read(f"{name}_BEFORE", I2C0_CONTROLLER_EVENTS)
        assert before & bit, f"{name}: not set before the retain checks (0x{before:08x})"
        await self.csr_write(f"{name}_ZERO", I2C0_CONTROLLER_EVENTS, 0)
        after_zero = await self.csr_read(f"{name}_AFTER_ZERO", I2C0_CONTROLLER_EVENTS)
        assert after_zero & bit, f"{name}: cleared on a word of zeros (0x{after_zero:08x})"
        await self.csr_write(f"{name}_LANE", I2C0_CONTROLLER_EVENTS + 3, 0xFF, length=1)
        after_lane = await self.csr_read(f"{name}_AFTER_LANE", I2C0_CONTROLLER_EVENTS)
        assert after_lane & bit, (
            f"{name}: cleared on a byte write that left its lane disabled (0x{after_lane:08x})"
        )
        await self.csr_write(f"{name}_CLEAR", I2C0_CONTROLLER_EVENTS, bit)
        cleared = await self.csr_read(f"{name}_CLEARED", I2C0_CONTROLLER_EVENTS)
        assert cleared & bit == 0, f"{name}: survived a written one (0x{cleared:08x})"
        self.retained.append(name)

    async def _bus_timeout_leg(self) -> None:
        name = "BUS_TIMEOUT"
        await self._enable_host(name, bus_timeout=True)
        injector = cocotb.start_soon(self._inject(name, "fall", 5, 0, "hold", BUS_TIMEOUT_HOLD_NS))
        await self._queue(name, "W")
        await injector
        await self._wait_flag(
            name, I2C0_CONTROLLER_EVENTS, EVENTS_BUS_TIMEOUT, "CONTROLLER_EVENTS.BUS_TIMEOUT"
        )
        await self._retain(EVENTS_BUS_TIMEOUT, "BUS_TIMEOUT")
        await self.csr_write(f"{name}_TIMEOUT_OFF", I2C0_TIMEOUT_CTRL, 0)
        await self.csr_write(f"{name}_HALT_OFF", I2C0_CTRL, 0)
        await self._recover_bus(name)

    async def _pending_restart_leg(self) -> None:
        """Disable the controller while the restart it was about to issue is pending."""
        name = "PENDING_RESTART"
        await self._enable_host(name)
        self.slave.write_mem(OFFSET, READ_PATTERN)
        starts = self.slave.starts

        async def disable() -> None:
            await self.csr_write(f"{name}_DISABLE_MID", I2C0_CTRL, 0)

        injector = cocotb.start_soon(
            self._inject(name, "fall", 18, 0, "hold", STRETCH_NS, during=disable)
        )
        await self._queue(name, "WRR")
        await injector
        await self._wait_hostidle(name)
        await ClockCycles(cocotb.top.clk_smc_i, 2000)
        assert self.slave.starts == starts + 1, (
            f"{name}: the target saw {self.slave.starts - starts} starts; the controller was "
            f"disabled while its repeated START was still pending, so it must not issue it"
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_SCL_EVENTS")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_scl_events_eeprom")
        self.other = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_scl_events_other")

        for leg in LEGS:
            await self._run_leg(leg)
        await self._bus_timeout_leg()
        await self._pending_restart_leg()

        by = {
            k: [n for n, o in self.outcomes.items() if o == k] for k in set(self.outcomes.values())
        }
        cocotb.log.info(
            "CHK-I2C-CTRL-SCL-INTERFERENCE: SCL pulled low while the controller held a pulse "
            "high raised INTR_STATE.SCL_INTERFERENCE at each of %s",
            ", ".join(by.get("scl_interference", [])),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-SYMBOL-FAILED: SCL falling during the setup of a repeated START or "
            "of the STOP, and both lines pulled low while the STOP was held, each raised "
            "CONTROLLER_EVENTS.ARBITRATION_LOST: %s",
            ", ".join(by.get("arbitration_lost", [])),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-STRETCH-POINTS: SCL held low for %d ns across the rise the controller "
            "expected at each of %s, and each transfer then completed with the target's data "
            "intact and no event raised",
            STRETCH_NS,
            ", ".join(by.get("completes", [])),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-BUS-TIMEOUT: SCL held low for %d ns against a bus timeout of %d core "
            "clocks raised CONTROLLER_EVENTS.BUS_TIMEOUT, which survived a word of zeros and a "
            "byte write that left its lane disabled, and cleared only on a written one",
            BUS_TIMEOUT_HOLD_NS,
            BUS_TIMEOUT_CYCLES,
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-PENDING-RESTART: the controller was disabled while held in the setup "
            "of a repeated START, and returned to idle without issuing it"
        )
