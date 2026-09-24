# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Edges on the I2C0 bus that land together, or after a stretch, inside a controller transfer.

`smc_i2c_controller_scl_events_test` moves one line at a time. The controller
samples SCL and SDA through matching synchronisers and decides on the pair,
so some of its decisions only arise when both lines move on the same clock,
or when SCL falls after the controller has already seen a stretch. This leaf
drives those, anchored on edges counted from the START on the pads as the
sibling leaf does, with a second bench pad driver as the other device:

* **SCL falling as SDA changes**, in the four pulses where the controller
  holds SCL released with SDA high: a bit it transmits, the acknowledge of an
  address nobody answers, a one bit the target returns, and the
  not-acknowledge the controller drives after a read. Both lines are pulled
  low at the same instant, a fixed delay into the high window. The fall is
  clock synchronisation, reported as `INTR_STATE.SCL_INTERFERENCE`; the SDA
  change lands on the same sample, so it is not a control symbol.
* **SCL rising as SDA changes**, in the pulse of the not-acknowledge: both
  lines are held low from the low phase before it, which stretches the pulse,
  then released together. SDA rises with SCL, before any sample of SCL high,
  so the transfer completes as though nothing happened.
* **SCL falling after a stretch**, in the same four pulses and in the setups
  of a repeated START and of the STOP: SCL is held low across the rise the
  controller expects, released, and pulled low again inside the high window.
  In a pulse that is clock synchronisation; in a setup the controller could
  not issue its control symbol and reports `CONTROLLER_EVENTS.ARBITRATION_LOST`.
* **SDA rising as SCL falls, in the STOP hold**: SDA is held low through the
  STOP's setup, so the controller waits in the hold; SDA is then released as
  SCL is pulled low. The controller sees SDA high and finishes its STOP,
  raising `INTR_STATE.CMD_COMPLETE`.
* **Another device in the setup of a first START.** `TIMING2.TSU_STA` is
  lengthened so the setup is long enough to hit from a time offset after the
  queue. SCL pulled low there means another device took the bus first; the
  controller goes back to wait for it and the transfer still completes. SDA
  pulled low there is interference with the controller's released line,
  reported as `INTR_STATE.SDA_INTERFERENCE`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN
from .smc_i2c_controller_scl_events_test_seq import (
    CLOCK_GATE_CONTROL,
    EEPROM_ADDR,
    EVENTS_ARBITRATION_LOST,
    I2C0_INTR_STATE,
    I2C0_WRAP_CTRL,
    I2C_WRAP_ENABLE_CONTROLLER,
    INTR_SCL_INTERFERENCE,
    PULL_NS,
    STRETCH_NS,
    SmcI2cEepromSlave,
    SmcI2cMasterVip,
    smc_i2c_controller_scl_events_test_seq,
)
from .smc_i2c_field_masks import I2C_INTR_SDA_INTERFERENCE
from .smc_i2c_master_target_test_seq import (
    I2C0_CONTROLLER_EVENTS,
    I2C0_CTRL,
    I2C0_FDATA,
    I2C0_TIMING2,
    I2C0_TIMING4,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    _fdata,
    _i2c_u32,
    _pack_timing2,
    _pack_timing4,
)

INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
ABSENT_ADDR = 0x51

#: How far into a high window the lines are moved: past the two samples of
#: SCL high the controller's checks need.
INTO_HIGH_NS = 60
#: How long SDA is held low into the STOP hold before it is released as SCL is
#: pulled low.
STOP_HOLD_NS = 2_000
#: `TIMING2.TSU_STA` for the first-START legs, in controller clocks, and when
#: the line is pulled after the queue: well inside that setup.
LONG_TSU_STA = 3_000
SETUP_PULL_AFTER_NS = 5_000
SETUP_PULL_NS = 400
#: `TSU_STA` or `TSU_STO` for the legs that pull SCL inside a setup after a
#: stretch: long enough that the setup outlasts the pull's delay.
LONG_SETUP = 60

# Rises are counted from the START as in the sibling leaf. "W" is a write of
# an offset and a byte, "A" the same write to an address nobody answers, and
# "WRR" a write, a repeated START and a two-byte read: rise 30 is a one bit of
# the first byte returned, 45 the last bit of the second, and 46 the
# not-acknowledge the controller drives. "fall" anchors on the fall after rise
# `nth` (0: the START's own fall).
#
# (name, transfer, anchor, nth, action, outcome)
LEGS = (
    ("CLOCK_PULSE_FALL_CHANGE", "W", "rise", 1, "fall_change", "scl_interference"),
    ("ADDR_ACK_FALL_CHANGE", "A", "rise", 9, "fall_change", "scl_interference"),
    ("READ_BIT_FALL_CHANGE", "WRR", "rise", 30, "fall_change", "scl_interference"),
    ("HOST_NACK_FALL_CHANGE", "WRR", "rise", 46, "fall_change", "scl_interference"),
    ("HOST_NACK_RISE_CHANGE", "WRR", "fall", 45, "rise_change", "completes"),
    ("CLOCK_PULSE_STRETCH_FALL", "W", "fall", 0, "stretch_fall", "scl_interference"),
    ("ADDR_ACK_STRETCH_FALL", "A", "fall", 8, "stretch_fall", "scl_interference"),
    ("READ_BIT_STRETCH_FALL", "WRR", "fall", 29, "stretch_fall", "scl_interference"),
    ("HOST_NACK_STRETCH_FALL", "WRR", "fall", 45, "stretch_fall", "scl_interference"),
    ("RESTART_STRETCH_FALL", "WRR", "fall", 18, "stretch_fall", "arbitration_lost"),
    ("STOP_STRETCH_FALL", "W", "fall", 27, "stretch_fall", "arbitration_lost"),
    ("STOP_HOLD_RELEASE", "W", "rise", 28, "stop_release", "cmd_complete"),
    ("FIRST_START_SCL", "W", "setup", 0, "scl", "completes"),
    ("FIRST_START_SDA", "W", "setup", 0, "sda", "sda_interference"),
)


class smc_i2c_controller_edge_timing_test_seq(smc_i2c_controller_scl_events_test_seq):
    """Coincident edges and post-stretch falls at chosen points of a controller transfer."""

    def __init__(self, name: str = "smc_i2c_controller_edge_timing_test_seq") -> None:
        super().__init__(name)
        self.edge_outcomes: dict[str, str] = {}

    async def _queue(self, label: str, transfer: str) -> None:
        if transfer != "A":
            await super()._queue(label, transfer)
            return
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(ABSENT_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(0x3C, I2C_FDATA_STOP))

    async def _anchor(self, label: str, anchor: str, nth: int) -> None:
        if anchor == "setup":
            await Timer(SETUP_PULL_AFTER_NS, unit="ns")
            return
        await self._wait_start(label)
        if nth:
            await self._wait_rises(label, nth)
        if anchor == "fall":
            await self._wait_fall(label)

    async def _wait_high(self, label: str) -> None:
        for _ in range(20_000):
            if self._scl():
                return
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(f"{label}: SCL did not rise after the stretch was released")

    async def _edge(self, label: str, anchor: str, nth: int, action: str) -> None:
        other = self.other
        assert other is not None
        await self._anchor(label, anchor, nth)
        if action == "fall_change":
            await Timer(INTO_HIGH_NS, unit="ns")
            other._pull_scl(True)
            other._pull_sda(True)
            await Timer(PULL_NS, unit="ns")
            other._pull_scl(False)
            other._pull_sda(False)
        elif action == "rise_change":
            other._pull_scl(True)
            other._pull_sda(True)
            await Timer(STRETCH_NS, unit="ns")
            other._pull_scl(False)
            other._pull_sda(False)
        elif action == "stretch_fall":
            other._pull_scl(True)
            await Timer(STRETCH_NS, unit="ns")
            other._pull_scl(False)
            await self._wait_high(label)
            await Timer(INTO_HIGH_NS, unit="ns")
            other._pull_scl(True)
            await Timer(PULL_NS, unit="ns")
            other._pull_scl(False)
        elif action == "stop_release":
            await Timer(15, unit="ns")
            other._pull_sda(True)
            await Timer(STOP_HOLD_NS, unit="ns")
            other._pull_sda(False)
            other._pull_scl(True)
            await Timer(PULL_NS, unit="ns")
            other._pull_scl(False)
        elif action == "scl":
            other._pull_scl(True)
            await Timer(SETUP_PULL_NS, unit="ns")
            other._pull_scl(False)
        elif action == "sda":
            other._pull_sda(True)
            await Timer(SETUP_PULL_NS, unit="ns")
            other._pull_sda(False)
        else:
            raise AssertionError(f"{label}: unknown action {action}")

    async def _settle(self, label: str) -> None:
        """End a transfer the edge disturbed, whichever way the rest of it went.

        After clock synchronisation the controller carries on, and the rest of
        the transfer may end in a NACK that halts it; disabling the controller
        and clearing its events returns it to idle either way.
        """
        await self.csr_write(f"{label}_SETTLE_OFF", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_SETTLE_CLR", I2C0_CONTROLLER_EVENTS, 0xFFFF_FFFF)
        await self._wait_hostidle(label)

    async def _run_edge_leg(self, leg) -> None:
        assert self.slave is not None
        name, transfer, anchor, nth, action, outcome = leg
        await self._enable_host(name)
        await self.csr_write(f"{name}_INTR_CLR_ALL", I2C0_INTR_STATE, 0xFFFF_FFFF)
        if name == "RESTART_STRETCH_FALL":
            timing2 = _pack_timing2(LONG_SETUP, 4)
            await self.csr_write(f"{name}_TIMING2_SETUP", I2C0_TIMING2, timing2)
            await self.csr_read(f"{name}_TIMING2_SETUP_RB", I2C0_TIMING2, expected=timing2)
        if name == "STOP_STRETCH_FALL":
            timing4 = _pack_timing4(LONG_SETUP, 5)
            await self.csr_write(f"{name}_TIMING4_SETUP", I2C0_TIMING4, timing4)
            await self.csr_read(f"{name}_TIMING4_SETUP_RB", I2C0_TIMING4, expected=timing4)
        if anchor == "setup":
            timing2 = _pack_timing2(LONG_TSU_STA, 4)
            await self.csr_write(f"{name}_TIMING2_LONG", I2C0_TIMING2, timing2)
            await self.csr_read(f"{name}_TIMING2_LONG_RB", I2C0_TIMING2, expected=timing2)
        if transfer == "W":
            self.slave.write_mem(0x70, b"\x00")
        elif transfer == "WRR":
            self.slave.write_mem(0x70, bytes((0x61, 0x62)))
        edge = cocotb.start_soon(self._edge(name, anchor, nth, action))
        await self._queue(name, transfer)
        await edge
        if outcome == "scl_interference":
            await self._wait_flag(
                name, I2C0_INTR_STATE, INTR_SCL_INTERFERENCE, "INTR_STATE.SCL_INTERFERENCE"
            )
            await self._settle(name)
        elif outcome == "arbitration_lost":
            await self._wait_flag(
                name,
                I2C0_CONTROLLER_EVENTS,
                EVENTS_ARBITRATION_LOST,
                "CONTROLLER_EVENTS.ARBITRATION_LOST",
            )
            await self.csr_write(f"{name}_EVENTS_ZERO", I2C0_CONTROLLER_EVENTS, 0)
            kept = await self.csr_read(f"{name}_EVENTS_KEPT", I2C0_CONTROLLER_EVENTS)
            assert kept & EVENTS_ARBITRATION_LOST, (
                f"{name}: ARBITRATION_LOST cleared on a word of zeros (0x{kept:08x}); it "
                f"clears only on a written one"
            )
            await self.csr_write(f"{name}_HALT_OFF", I2C0_CTRL, 0)
        elif outcome == "cmd_complete":
            await self._wait_flag(name, I2C0_INTR_STATE, INTR_CMD_COMPLETE, "CMD_COMPLETE")
            await self._wait_hostidle(name)
            events = await self.csr_read(f"{name}_EVENTS_DONE", I2C0_CONTROLLER_EVENTS)
            assert events == 0, (
                f"{name}: CONTROLLER_EVENTS=0x{events:08x}; the controller saw SDA high in its "
                f"STOP hold and has nothing to report"
            )
        elif outcome == "sda_interference":
            await self._wait_flag(
                name, I2C0_INTR_STATE, I2C_INTR_SDA_INTERFERENCE, "INTR_STATE.SDA_INTERFERENCE"
            )
            await self._settle(name)
        else:
            await self._check_completed(name, "W" if transfer == "W" else "WRR")
        await self.csr_write(f"{name}_HOST_OFF", I2C0_CTRL, 0)
        await ClockCycles(cocotb.top.clk_smc_i, 20)
        await self._recover_bus(name)
        self.edge_outcomes[name] = outcome

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_EDGE_TIMING")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_edge_timing_eeprom")
        self.other = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_edge_timing_other")

        for leg in LEGS:
            await self._run_edge_leg(leg)

        def named(action: str) -> str:
            return ", ".join(leg[0] for leg in LEGS if leg[4] == action)

        cocotb.log.info(
            "CHK-I2C-CTRL-EDGE-FALL-CHANGE: SCL and SDA pulled low at the same instant %d ns "
            "into a high window raised INTR_STATE.SCL_INTERFERENCE at each of %s",
            INTO_HIGH_NS,
            named("fall_change"),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-EDGE-RISE-CHANGE: SCL and SDA held low across the not-acknowledge "
            "pulse and released together left the read to complete with the target's data "
            "intact and no event: %s",
            named("rise_change"),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-EDGE-STRETCH-FALL: SCL held for %d ns across an expected rise and "
            "pulled low again %d ns into the high window raised SCL_INTERFERENCE in a pulse and "
            "ARBITRATION_LOST in a setup, as each point specifies, and ARBITRATION_LOST "
            "survived a word of zeros written over CONTROLLER_EVENTS: %s",
            STRETCH_NS,
            INTO_HIGH_NS,
            named("stretch_fall"),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-EDGE-STOP-HOLD: SDA held low into the STOP hold and released as SCL "
            "was pulled low let the controller finish its STOP with CMD_COMPLETE and no event: %s",
            named("stop_release"),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-EDGE-FIRST-START: with TIMING2.TSU_STA at %d, SCL pulled low inside "
            "the setup of a first START left the transfer to complete intact, and SDA pulled "
            "low there raised INTR_STATE.SDA_INTERFERENCE: %s, %s",
            LONG_TSU_STA,
            named("scl"),
            named("sda"),
        )
