# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The STOP the I2C0 controller makes on its own when its enable is cleared.

A controller that has started a transaction owns the bus until it gives a
STOP. If software clears `CTRL.ENABLEHOST` with the transaction still open,
`i2c_controller_fsm.sv` generates that STOP itself, from two states:

* **Idle, parked.** When the format FIFO runs dry without a STOP, the
  controller waits in `Idle` holding SCL low, with `STATUS.HOSTIDLE` clear.
  Clearing the enable there makes the STOP.
* **PopFmtFifo.** Between two entries the controller passes through
  `PopFmtFifo` for exactly one cycle of its clock. The enable has to be seen
  low on that cycle.

Both arms test `trans_started && !host_enable_i`, and `trans_started` is a
flop that clears on the cycle after the enable is seen low. In `Idle` the
controller stays put, so a parked controller always takes the arm. Anywhere
else in a transfer the flop is already clear by the time the controller
reaches either arm, and it returns to idle without a STOP. So in the
`PopFmtFifo` leg a STOP on the pads is proof the enable fell on that one
cycle; no other disable time produces one.

The `PopFmtFifo` cycle is found on the bus. The transfer is a START and
address, an offset byte and a data byte with a STOP, so the controller goes
from the address acknowledge through `PopFmtFifo` into the offset byte.
Counting from the eighth SCL rise after the START, the disable is written a
chosen number of SMC clock cycles later, and each try ends one of three ways:
a STOP (the disable was seen in `PopFmtFifo`); SCL released after the
acknowledge with no STOP (seen before it, so the address byte was the last);
or the whole offset byte clocked out first (seen after it). Bisection on the offset between an
early and a late try closes on the cycle between them. The write crosses from
the SMC clock into the I2C clock, whose phases are not locked, so the landing
cycle of one offset can differ by one between tries; the offsets either side
of where the bisection closes are therefore tried again until one lands.

`INTR_STATE.CMD_COMPLETE` is raised only when the controller finishes a STOP
or a repeated START (`i2c.rdl`), so it is the register witness that the STOP
was the controller's; the bench target counts the STOP on the pads.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import I2C_STATUS_FMTEMPTY
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
EEPROM_OFFSET = 0x70
DATA_BYTE = 0x3C

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_ALL = 0xFFFF_FFFF

#: The SCL rise the disable offset counts from: the last address bit. The
#: acknowledge follows, then `PopFmtFifo`.
ANCHOR_RISE = 8
#: SCL rises after the anchor when the address byte was the last: the
#: acknowledge, and the release when the controller returns to idle with no
#: transaction open. The offset byte adds nine more.
EARLY_RISES = 2
LATE_RISES = EARLY_RISES + 9
#: The offset search range, in SMC clock cycles after the anchor. The upper
#: end is past the offset byte's first bit at this leaf's timing, which the
#: search checks rather than assumes.
OFFSET_LATE = 1024
#: How many times the offsets either side of where the bisection closes are
#: tried again, and how far either side.
DITHER_PASSES = 4
DITHER_SPAN = 3

POLL_CYCLES = 100
IDLE_POLLS = 2000
PARK_SETTLE_CYCLES = 400
STOP_WAIT_CYCLES = 20_000
EDGE_WAIT_CYCLES = 200_000


class _PadWatch:
    """Counts SCL rises and STOPs on the `tb_i2c0_*` pads while it runs."""

    def __init__(self) -> None:
        self.rises = 0
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
            if scl and not prev_scl:
                self.rises += 1
            if scl and prev_scl and sda and not prev_sda:
                self.stops += 1
            prev_scl = scl
            prev_sda = sda

    def stop(self) -> None:
        self._task.cancel()


class smc_i2c_controller_disable_stop_test_seq(SmcCsrSeq):
    """Clear the enable with a transaction open, in `Idle` and in `PopFmtFifo`."""

    def __init__(self, name: str = "smc_i2c_controller_disable_stop_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.injector: SmcI2cMasterVip | None = None
        self.tries: list[tuple[int, str]] = []

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

    async def _wait_hostidle(self, label: str) -> int:
        status = 0
        for _ in range(IDLE_POLLS):
            status = await self.csr_read(f"{label}_IDLE", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return status
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: STATUS.HOSTIDLE never set after the enable was cleared "
            f"(STATUS=0x{status:08x})"
        )

    async def _wait_stop(self, label: str, watch: _PadWatch, before: int) -> bool:
        for _ in range(STOP_WAIT_CYCLES):
            if watch.stops > before:
                return True
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        return False

    async def _recover_bus(self, label: str) -> None:
        """Return the bus and the bench target to idle.

        A transfer that ends without a STOP leaves the target part-way through
        a byte. Clocking SCL until it releases SDA, then a START and a STOP,
        returns it to idle whatever phase it was in.
        """
        assert self.injector is not None
        half = self.injector._half_ns
        for _ in range(18):
            if int(cocotb.top.tb_i2c0_sda.value):
                break
            self.injector._pull_scl(True)
            await Timer(half, unit="ns")
            self.injector._pull_scl(False)
            await Timer(half, unit="ns")
        self.injector._pull_sda(True)
        await Timer(half, unit="ns")
        self.injector._pull_sda(False)
        await Timer(4 * half, unit="ns")
        assert self._pads() == (1, 1), f"{label}: the bus did not return to idle"

    async def _check_stop_witness(self, label: str, stops_before: int) -> None:
        assert self.slave is not None
        intr = await self.csr_read(f"{label}_INTR_STOP", I2C0_INTR_STATE)
        assert intr & INTR_CMD_COMPLETE, (
            f"{label}: a STOP appeared on the pads but INTR_STATE.CMD_COMPLETE is clear "
            f"(0x{intr:08x}); the STOP was not the controller's"
        )
        assert self.slave.stops == stops_before + 1, (
            f"{label}: the bench target counted {self.slave.stops - stops_before} STOPs "
            f"after the enable was cleared, not 1"
        )
        await self._wait_hostidle(label)
        assert self._pads() == (1, 1), f"{label}: the bus is not idle after the STOP"

    async def _idle_leg(self) -> None:
        """Park the controller in `Idle` mid-transaction, then clear the enable."""
        assert self.slave is not None
        label = "PARKED"
        await self._configure(label)
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET))
        status = 0
        for _ in range(IDLE_POLLS):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_FMTEMPTY:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(f"{label}: the format FIFO never drained (0x{status:08x})")
        await ClockCycles(cocotb.top.clk_smc_i, PARK_SETTLE_CYCLES)
        status = await self.csr_read(f"{label}_PARKED_STATUS", I2C0_STATUS)
        assert not status & I2C_STATUS_HOSTIDLE, (
            f"{label}: STATUS.HOSTIDLE is set with the transaction still open "
            f"(0x{status:08x}); the controller is not parked"
        )
        scl, _ = self._pads()
        assert scl == 0, f"{label}: SCL is released while the controller is parked"
        intr = await self.csr_read(f"{label}_INTR_PARKED", I2C0_INTR_STATE)
        assert intr & INTR_CMD_COMPLETE == 0, (
            f"{label}: INTR_STATE.CMD_COMPLETE is set before any STOP (0x{intr:08x})"
        )
        stops_before = self.slave.stops
        watch = _PadWatch()
        await self.csr_write(f"{label}_CLEAR_ENABLE", I2C0_CTRL, 0)
        stopped = await self._wait_stop(label, watch, 0)
        watch.stop()
        assert stopped, (
            f"{label}: no STOP appeared on the pads within {STOP_WAIT_CYCLES} cycles of "
            f"CTRL.ENABLEHOST being cleared with the controller parked mid-transaction"
        )
        await self._check_stop_witness(label, stops_before)
        cocotb.log.info(
            "CHK-I2C-CTRL-DISABLE-STOP-IDLE: with the controller parked in Idle holding SCL "
            "low and STATUS.HOSTIDLE clear, clearing CTRL.ENABLEHOST made one STOP on the "
            "pads, raised INTR_STATE.CMD_COMPLETE and returned the controller to idle"
        )

    async def _try(self, offset: int) -> str:
        """One transfer, with the enable cleared `offset` cycles after the anchor."""
        assert self.slave is not None
        label = f"POP_{offset}"
        await self._configure(label)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET))
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(DATA_BYTE, I2C_FDATA_STOP))
        stops_before = self.slave.stops
        watch = _PadWatch()
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        for _ in range(EDGE_WAIT_CYCLES):
            if watch.rises >= ANCHOR_RISE:
                break
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        else:
            raise AssertionError(f"{label}: SCL rise {ANCHOR_RISE} never appeared")
        at_anchor = watch.rises
        await ClockCycles(cocotb.top.clk_smc_i, offset)
        await self.csr_write(f"{label}_CLEAR_ENABLE", I2C0_CTRL, 0)
        stopped = await self._wait_stop(label, watch, 0)
        after = watch.rises - at_anchor
        if stopped:
            watch.stop()
            await self._check_stop_witness(label, stops_before)
            outcome = "stop"
        else:
            await self._wait_hostidle(label)
            await ClockCycles(cocotb.top.clk_smc_i, PARK_SETTLE_CYCLES)
            after = watch.rises - at_anchor
            watch.stop()
            intr = await self.csr_read(f"{label}_INTR_NOSTOP", I2C0_INTR_STATE)
            assert intr & INTR_CMD_COMPLETE == 0, (
                f"{label}: INTR_STATE.CMD_COMPLETE is set with no STOP on the pads (0x{intr:08x})"
            )
            if after == EARLY_RISES:
                outcome = "early"
            elif after == LATE_RISES:
                outcome = "late"
            else:
                raise AssertionError(
                    f"{label}: {after} SCL rises followed the anchor with no STOP; a disable "
                    f"before PopFmtFifo leaves {EARLY_RISES}, one after it {LATE_RISES}"
                )
            await self._recover_bus(label)
        self.tries.append((offset, outcome))
        cocotb.log.info("%s: %s after %d SCL rises past the anchor", label, outcome, after)
        return outcome

    async def _pop_leg(self) -> int:
        """Find the `PopFmtFifo` cycle by bisection on the disable offset."""
        lo, hi = 0, OFFSET_LATE
        first = await self._try(lo)
        if first == "stop":
            return lo
        assert first == "early", (
            f"offset {lo}: the disable already landed after PopFmtFifo; the anchor is too late"
        )
        last = await self._try(hi)
        if last == "stop":
            return hi
        assert last == "late", f"offset {hi}: the disable still landed before PopFmtFifo"
        while hi - lo > 1:
            mid = (lo + hi) // 2
            got = await self._try(mid)
            if got == "stop":
                return mid
            if got == "early":
                lo = mid
            else:
                hi = mid
        for _ in range(DITHER_PASSES):
            for offset in range(max(0, lo - DITHER_SPAN), hi + DITHER_SPAN + 1):
                if await self._try(offset) == "stop":
                    return offset
        raise AssertionError(
            f"no disable offset produced a STOP: offset {lo} landed before PopFmtFifo and "
            f"{hi} after it, and {DITHER_PASSES} passes over offsets {lo - DITHER_SPAN}.."
            f"{hi + DITHER_SPAN} never landed on it; tries: {self.tries}"
        )

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_DISABLE_STOP")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_disable_stop_eeprom")
        self.injector = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_disable_stop_recovery")
        await Timer(1, unit="us")

        await self._idle_leg()
        hit = await self._pop_leg()
        early = sum(1 for _, o in self.tries if o == "early")
        late = sum(1 for _, o in self.tries if o == "late")
        assert early >= 1 and late >= 1, (
            f"the search saw {early} early and {late} late tries; both sides of PopFmtFifo "
            f"have to be seen for the STOP to single it out"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-DISABLE-STOP-POP: clearing CTRL.ENABLEHOST %d cycles after the last "
            "address bit made one STOP on the pads and raised INTR_STATE.CMD_COMPLETE; %d tries "
            "at smaller offsets ended after the address byte and %d at larger ones clocked "
            "out the offset byte, all without a STOP (%d tries)",
            hit,
            early,
            late,
            len(self.tries),
        )
