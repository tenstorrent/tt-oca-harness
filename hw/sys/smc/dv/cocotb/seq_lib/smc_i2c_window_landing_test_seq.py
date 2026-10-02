# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 CTRL writes landed on the cycle a bus-monitor or target event fires.

Some decisions in the I2C0 bus monitor and target state machine rest on a
condition that holds for one or two clocks, so only a write to `CTRL` that
takes effect on that clock, or a second event on that clock, exercises them:

* **Monitor disabled as a START or STOP is recognised.** `i2c_bus_monitor.sv`
  reports a START or STOP once `TIMING3.THD_DAT` clocks have passed with the
  condition still on the bus, and drops the pending condition on the next
  clock once the monitor is disabled. `CTRL` is cleared to take effect on the
  clock the report would fire.
* **Target disabled as a read ends with a STOP.** `INTR_STATE.UNEXP_STOP` is
  raised for a STOP before the target NACKs, "when the controller sends this
  target a STOP". A disabled target returns to idle on the next clock and
  forgets the transfer on the one after, so `CTRL.ENABLETARGET` is cleared to
  take effect on the clock the STOP is recognised, with the bus monitor kept
  running through `CTRL.MULTI_CONTROLLER_MONITOR_EN`. A target disabled before
  the STOP raises no `UNEXP_STOP`; one still enabled when it arrives does.
* **A NACK timeout and a bus timeout on the same clock.** With ACK Control
  Mode on and no bytes granted, the target stretches the clock after the first
  data byte until `TARGET_TIMEOUT_CTRL` expires and then NACKs it. The bus
  monitor times the same low SCL from the controller's falling edge, eight
  clocks earlier, so a bus timeout of the NACK timeout plus eight expires on
  the clock the target writes its NACK into the ACQ FIFO.

The register path from SEP_IN to I2C0 crosses into the peripheral clock, so
its length in I2C clocks depends on the run's clock periods. The leaf measures
it first: `OVRD` with `TXOVRDEN` set and `SCLVAL` clear drives the SCL pad low
on the clock it takes effect, and `OVRD` sits in the same register block as
`CTRL`. The bench drives the bus condition from a clock edge it picks, so the
report clock is `THD_DAT` plus the two-clock input synchroniser after it, and
the `CTRL` write is called that many clocks after the bus edge, less the
path's length. Each placement is swept over two clocks either side.

Every sweep point has to leave the block behaving as its registers describe:
the target, enabled again, acknowledges and delivers a write; `UNEXP_STOP` is
clear when the target was disabled two clocks or more before the STOP and
raised when it was disabled two clocks or more after; and a data byte the target was not allowed to
acknowledge is NACKed, with the ACQ FIFO holding the START and address first.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_i2c_bus_corners_test_seq import (
    I2C0_ACQDATA,
    I2C0_CTRL,
    I2C0_INTR_STATE,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TXDATA,
    INTR_UNEXP_STOP,
    TARGET_ADDR,
    TX_BYTES,
    smc_i2c_bus_corners_test_seq,
)
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_STATUS_ACQEMPTY,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_TARGET_ACK_CTRL,
    I2C0_TIMING3,
    I2C0_WRAP_CTRL,
    _pack_timing3,
)

I2C0_TARGET_TIMEOUT_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_TIMEOUT_CTRL_BASE_ADDR", 0
)
I2C0_TIMEOUT_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TIMEOUT_CTRL_BASE_ADDR", 0)
OVRD_EN = _i2c_u32("I2C__OVRD__TXOVRDEN_bm")
OVRD_SDA = _i2c_u32("I2C__OVRD__SDAVAL_bm")
ENABLETARGET = _i2c_u32("I2C__CTRL__ENABLETARGET_bm")
ACK_CTRL_EN = _i2c_u32("I2C__CTRL__ACK_CTRL_EN_bm")
MULTI = _i2c_u32("I2C__CTRL__MULTI_CONTROLLER_MONITOR_EN_bm")
ACQ_START_STOP_EN = _i2c_u32("I2C__CTRL__ACQ_START_STOP_EN_bm")
TTO_EN = _i2c_u32("I2C__TARGET_TIMEOUT_CTRL__EN_bm")
TO_EN = _i2c_u32("I2C__TIMEOUT_CTRL__EN_bm")
TO_MODE_BUS = _i2c_u32("I2C__TIMEOUT_CTRL__MODE_bm")
ACQ_START = 1
ACQ_NACK = 4

#: `TIMING3.THD_DAT` for the monitor and target legs, in I2C clocks.
THD = 12
#: The pads reach the bus monitor through a two-clock synchroniser.
SYNC = 2
#: Target NACK timeout, and how many clocks earlier the bus monitor starts
#: timing the same low SCL: the controller's fall reaches the monitor, and the
#: target enters its stretch after its `THD_DAT` hold.
NACK_TIMEOUT = 100
BUS_TIMEOUT_LEAD = 8
OFFSETS = (-2, -1, 0, 1, 2)
DATA_BYTE = 0x5A
POLL_LIMIT = 400


class smc_i2c_window_landing_test_seq(smc_i2c_bus_corners_test_seq):
    """Land CTRL writes and a second timeout on one-clock I2C0 windows."""

    def __init__(self, name: str = "smc_i2c_window_landing_test_seq") -> None:
        super().__init__(name)
        self.path = -1
        self.nack_acq: dict[int, list[int]] = {}
        self.unexp: dict[int, bool] = {}

    async def _measure_path(self) -> int:
        """Clocks from a register write's call to its effect in I2C0."""
        dut = cocotb.top
        await self.csr_write("PATH_CTRL_OFF", I2C0_CTRL, 0)
        await RisingEdge(dut.clk_periph_i)
        write = cocotb.start_soon(self.csr_write("PATH_OVRD", I2C0_OVRD, OVRD_EN | OVRD_SDA))
        edges = 0
        while True:
            await RisingEdge(dut.clk_periph_i)
            edges += 1
            await ReadOnly()
            if int(dut.tb_i2c0_scl_dut_low.value):
                break
        await write
        await self.csr_write("PATH_OVRD_OFF", I2C0_OVRD, 0)
        return edges

    async def _land(self, label: str, value: int, delta: int, bus_edge) -> None:
        """Change the bus `delta` clocks after calling a CTRL write (or before, if negative)."""
        dut = cocotb.top
        await RisingEdge(dut.clk_periph_i)
        if delta >= 0:
            write = cocotb.start_soon(self.csr_write(label, I2C0_CTRL, value))
            for _ in range(delta):
                await RisingEdge(dut.clk_periph_i)
            await FallingEdge(dut.clk_periph_i)
            bus_edge()
        else:
            await FallingEdge(dut.clk_periph_i)
            bus_edge()
            for _ in range(-delta):
                await RisingEdge(dut.clk_periph_i)
            write = cocotb.start_soon(self.csr_write(label, I2C0_CTRL, value))
        await write

    def _delta(self, offset: int) -> int:
        return self.path - (THD + SYNC) - offset

    async def _target_answers(self, label: str) -> None:
        """The target, enabled again, acknowledges a one-byte write and delivers it."""
        master = self.master
        assert master is not None
        await self._target_up(f"{label}_AGAIN")
        await master.write(TARGET_ADDR, TX_BYTES[:1])
        got = []
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_AGAIN_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                break
            word = await self.csr_read(f"{label}_AGAIN_ACQ", I2C0_ACQDATA)
            if (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP == I2C_ACQ_SIGNAL_NONE:
                got.append(word & 0xFF)
        assert got == list(TX_BYTES[:1]), (
            f"{label}: after the landed CTRL write the target, enabled again, delivered "
            f"{[hex(b) for b in got]} for a write of {TX_BYTES[:1].hex()}"
        )
        await self.csr_write(f"{label}_AGAIN_OFF", I2C0_CTRL, 0)

    async def _monitor_leg(self, label: str, stop: bool, offset: int) -> None:
        dut = cocotb.top
        master = self.master
        assert master is not None
        await self._target_up(label)
        await self.csr_write(f"{label}_T3", I2C0_TIMING3, _pack_timing3(2, THD))
        if stop:
            master._pull_sda(True)
            await ClockCycles(dut.clk_periph_i, 200)
        await self._land(
            f"{label}_CTRL_OFF", 0, self._delta(offset), lambda: master._pull_sda(not stop)
        )
        await ClockCycles(dut.clk_periph_i, 50)
        master._pull_sda(False)
        await ClockCycles(dut.clk_periph_i, 200)
        await self._target_answers(label)

    async def _unexp_leg(self, label: str, offset: int) -> None:
        dut = cocotb.top
        master = self.master
        assert master is not None
        await self._target_up(label)
        await self.csr_write(f"{label}_T3", I2C0_TIMING3, _pack_timing3(2, THD))
        await self.csr_write(f"{label}_CTRL", I2C0_CTRL, ENABLETARGET | MULTI)
        for index, byte in enumerate(TX_BYTES):
            await self.csr_write(f"{label}_TXDATA{index}", I2C0_TXDATA, byte)
        await master.send_start()
        nack = await master.send_byte(((TARGET_ADDR & 0x7F) << 1) | 1)
        assert not nack, f"{label}: the target did not acknowledge its read address"
        got = 0
        for _ in range(8):
            got = (got << 1) | await master.recv_bit()
        assert got == TX_BYTES[0], f"{label}: read 0x{got:02x}, not 0x{TX_BYTES[0]:02x}"
        # The STOP takes the acknowledge slot: SDA low, SCL released, then SDA
        # released from a chosen clock edge.
        master._pull_sda(True)
        await Timer(master._half_ns, unit="ns")
        master._pull_scl(False)
        await master._wait_scl_high()
        await Timer(master._half_ns, unit="ns")
        await self._land(
            f"{label}_TARGET_OFF", MULTI, self._delta(offset), lambda: master._pull_sda(False)
        )
        master._active = False
        await ClockCycles(dut.clk_periph_i, 200)
        intr = await self.csr_read(f"{label}_INTR", I2C0_INTR_STATE)
        raised = bool(intr & INTR_UNEXP_STOP)
        # Two clocks or more before the STOP is recognised the target is already
        # disabled; two clocks or more after, it is still enabled when the STOP
        # arrives. The two points between are recorded.
        if offset <= -1:
            assert not raised, (
                f"{label}: INTR_STATE=0x{intr:08x}; ENABLETARGET cleared {-offset} clock(s) "
                f"before the STOP was recognised left UNEXP_STOP raised, which a disabled "
                f"target does not do"
            )
        elif offset >= 2:
            assert raised, (
                f"{label}: INTR_STATE=0x{intr:08x}; ENABLETARGET cleared {offset} clocks after "
                f"the STOP was recognised, so the target was enabled for it and UNEXP_STOP "
                f"has to be raised"
            )
        self.unexp[offset] = raised
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, 0)

    async def _timeout_leg(self, label: str, offset: int) -> list[int]:
        dut = cocotb.top
        master = self.master
        assert master is not None
        await self._target_up(label)
        await self.csr_write(
            f"{label}_CTRL", I2C0_CTRL, ENABLETARGET | ACK_CTRL_EN | ACQ_START_STOP_EN
        )
        await self.csr_write(f"{label}_NBYTES", I2C0_TARGET_ACK_CTRL, 0)
        await self.csr_write(f"{label}_TTO", I2C0_TARGET_TIMEOUT_CTRL, TTO_EN | NACK_TIMEOUT)
        await self.csr_write(
            f"{label}_BTO",
            I2C0_TIMEOUT_CTRL,
            TO_EN | TO_MODE_BUS | (NACK_TIMEOUT + BUS_TIMEOUT_LEAD + offset),
        )
        await master.send_start()
        nack_addr = await master.send_byte((TARGET_ADDR & 0x7F) << 1)
        nack_data = await master.send_byte(DATA_BYTE)
        await master.send_stop()
        await ClockCycles(dut.clk_periph_i, 200)
        acq = []
        for _ in range(8):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if status & I2C_STATUS_ACQEMPTY:
                break
            acq.append(await self.csr_read(f"{label}_ACQ", I2C0_ACQDATA))
        assert not nack_addr and nack_data, (
            f"{label}: address {'NACKed' if nack_addr else 'acknowledged'}, data "
            f"{'NACKed' if nack_data else 'acknowledged'}; with ACK Control Mode on, no bytes "
            f"granted and a NACK timeout, the address is acknowledged and the data byte NACKed"
        )
        first = acq[0] if acq else -1
        assert (first & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP == ACQ_START and (
            first & 0xFF
        ) == (TARGET_ADDR << 1), (
            f"{label}: the ACQ FIFO starts with 0x{first & 0xFFFF:04x}, not the START entry for "
            f"a write to 0x{TARGET_ADDR:02x}"
        )
        await self.csr_write(f"{label}_TTO_OFF", I2C0_TARGET_TIMEOUT_CTRL, 0)
        await self.csr_write(f"{label}_BTO_OFF", I2C0_TIMEOUT_CTRL, 0)
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, 0)
        return [a & 0xFFFF for a in acq]

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_WINDOW_LANDING")
        self.master = SmcI2cMasterVip(speed=2_000_000, name="smc_i2c0_window_master")
        self.path = await self._measure_path()

        for offset in OFFSETS:
            await self._monitor_leg(f"START{offset + 2}", False, offset)
        for offset in OFFSETS:
            await self._monitor_leg(f"STOP{offset + 2}", True, offset)
        cocotb.log.info(
            "CHK-I2C-MONITOR-DISABLE-AT-DETECT: with the register path measured at %d clocks, "
            "CTRL was cleared %s clocks from the bus monitor recognising a START and a STOP "
            "(THD_DAT %d), and after each the target, enabled again, delivered a write",
            self.path,
            list(OFFSETS),
            THD,
        )

        for offset in OFFSETS:
            await self._unexp_leg(f"UNEXP{offset + 2}", offset)
        cocotb.log.info(
            "CHK-I2C-TARGET-DISABLE-AT-STOP: ENABLETARGET was cleared %s clocks from a STOP in "
            "a read byte's acknowledge slot being recognised, with the bus monitor kept "
            "running; UNEXP_STOP stayed clear with the target disabled before the STOP and "
            "was raised with it disabled after (raised per offset: %s)",
            list(OFFSETS),
            self.unexp,
        )

        for offset in OFFSETS:
            self.nack_acq[offset] = await self._timeout_leg(f"TIMEOUTS{offset + 2}", offset)
        cocotb.log.info(
            "CHK-I2C-NACK-AND-BUS-TIMEOUT: a NACK timeout of %d and bus timeouts of %s clocks "
            "left the address acknowledged, the data byte NACKed and the START entry first in "
            "the ACQ FIFO at every point; ACQ contents per bus timeout: %s",
            NACK_TIMEOUT,
            [NACK_TIMEOUT + BUS_TIMEOUT_LEAD + o for o in OFFSETS],
            {
                NACK_TIMEOUT + BUS_TIMEOUT_LEAD + o: [hex(a) for a in v]
                for o, v in self.nack_acq.items()
            },
        )
        await self.csr_write("CLOCK_GATE_RESTORE", CLOCK_GATE_CONTROL, cg)
