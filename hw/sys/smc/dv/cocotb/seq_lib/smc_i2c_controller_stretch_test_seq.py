# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C0 controller waiting out a target that holds the clock.

Clock stretching is the one thing an I2C target can do to a controller, and
`hw/ip/i2c/doc/architecture.adoc` describes the controller side of it: the
controller releases SCL and waits for the line to actually rise before it
counts the bit as clocked. Every controller leaf in the package talks to a
device that never holds the clock, so that wait has never been taken.

The DUT's I2C0 host writes to the bench's EEPROM target, and another device on
the same open-drain bus -- a second bench pad driver -- holds SCL low for a
fixed span part-way through. Because SCL is open-drain, the controller's own
release cannot lift the line while the hold lasts, which is exactly what a
stretching target does.

Where the hold lands decides which part of the controller's bit loop takes the
wait -- the address byte, a payload byte, the acknowledge -- so the hold is
swept across the transfer rather than applied once.

Two measurements carry each leg, both produced by the DUT. The transfer takes
at least the hold longer than the same transfer with nothing holding the line,
so the controller waited rather than carried on; and the bytes the EEPROM
received afterwards are the ones that were queued, so it waited in the right
place. `TIMEOUT_CTRL` is left disabled throughout: a controller that gave up
would show as a missing byte, not as a timeout the leaf could mistake for
success.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
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
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip

EEPROM_ADDR = 0x50
EEPROM_OFFSET = 0x30
PAYLOAD = bytes((0x90 + i) & 0xFF for i in range(2))

#: How long the other device holds SCL low. Several bit periods of the
#: controller's programmed timing, so the wait is unmistakable in the transfer
#: time, and far short of any timeout -- none is enabled.
HOLD_NS = 20_000
#: Where the hold starts, measured from the moment the transfer is queued.
#: The spread walks it across the address byte, its acknowledge and the
#: payload bytes rather than landing in one place; the last one is still
#: inside the unheld transfer, whose length the leaf measures first.
HOLD_OFFSETS_NS = (2_000, 6_000, 10_000, 14_000, 18_000, 22_000)
#: The held transfer must be longer than the clean one by at least this much
#: of the hold. It cannot be the whole hold, because the clean transfer's own
#: length varies with where the controller was when the hold began.
MIN_EXTENSION_NS = HOLD_NS * 3 // 4

POLL_CYCLES = 200
IDLE_POLLS = 2000


class smc_i2c_controller_stretch_test_seq(SmcCsrSeq):
    """The controller must wait out a held clock and finish the transfer."""

    def __init__(self, name: str = "smc_i2c_controller_stretch_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.holder: SmcI2cMasterVip | None = None
        self.clean_ns = 0.0
        self.held: list[tuple[int, float]] = []

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

    async def _bring_up(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_CONTROLLER_STRETCH")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("I2C0_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _queue_write(self, label: str, offset: int) -> None:
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(offset))
        for i, value in enumerate(PAYLOAD):
            flags = I2C_FDATA_STOP if i == len(PAYLOAD) - 1 else 0
            await self.csr_write(f"{label}_DATA{i}", I2C0_FDATA, _fdata(value, flags))

    async def _hold_after(self, delay_ns: int) -> None:
        """Hold SCL low for HOLD_NS, starting delay_ns from now."""
        assert self.holder is not None
        await Timer(delay_ns, unit="ns")
        self.holder._pull_scl(True)
        await Timer(HOLD_NS, unit="ns")
        self.holder._pull_scl(False)

    async def _transfer(self, label: str, offset: int, hold_delay_ns: int | None) -> float:
        """One queued write, optionally with the clock held; returns its length."""
        self.slave.write_mem(offset, bytes(len(PAYLOAD)))
        start = get_sim_time("ns")
        await self._queue_write(label, offset)
        task = None
        if hold_delay_ns is not None:
            task = cocotb.start_soon(self._hold_after(hold_delay_ns))
        await self._wait_hostidle(label)
        elapsed = get_sim_time("ns") - start
        if task is not None:
            await task
        got = self.slave.read_mem(offset, len(PAYLOAD))
        assert got == PAYLOAD, (
            f"{label}: the target received {got.hex()} at offset 0x{offset:02x}, not the "
            f"{PAYLOAD.hex()} that was queued"
        )
        events = await self.csr_read(f"{label}_EVENTS_DONE", I2C0_CONTROLLER_EVENTS)
        assert events == 0, (
            f"{label}: CONTROLLER_EVENTS reads 0x{events:08x} after a transfer that only had "
            f"its clock held; no timeout is enabled and the target acknowledged every byte"
        )
        return elapsed

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        await self._bring_up()
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_stretch_eeprom")
        self.holder = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_stretch_holder")

        self.clean_ns = await self._transfer("CLEAN", EEPROM_OFFSET, None)
        cocotb.log.info(
            "CHK-I2C-CTRL-STRETCH-CLEAN: with nothing holding the line the controller wrote "
            "%d bytes to the target in %.0f ns, which is the length the held transfers below "
            "are measured against",
            len(PAYLOAD),
            self.clean_ns,
        )

        for i, delay in enumerate(HOLD_OFFSETS_NS):
            elapsed = await self._transfer(f"HELD{i}", EEPROM_OFFSET + 1 + i, delay)
            extension = elapsed - self.clean_ns
            assert extension >= MIN_EXTENSION_NS, (
                f"HELD{i}: a {HOLD_NS} ns hold starting {delay} ns into the transfer extended "
                f"it by only {extension:.0f} ns against the clean {self.clean_ns:.0f} ns; the "
                f"controller has to wait for SCL to rise before it clocks the next bit"
            )
            self.held.append((delay, extension))

        cocotb.log.info(
            "CHK-I2C-CTRL-STRETCH-HELD: at %d points across the transfer another device held "
            "SCL low for %d ns, and each time the controller's transfer ran at least %d ns "
            "longer than the clean one and still delivered every byte: %s",
            len(self.held),
            HOLD_NS,
            MIN_EXTENSION_NS,
            ", ".join(f"{d} ns -> +{e:.0f} ns" for d, e in self.held),
        )
