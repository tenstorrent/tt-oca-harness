# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two ways an I2C controller transaction ends that no leaf had produced.

Every controller leaf in the package queues a transfer that runs to the STOP
it was given, and clears a NACK as soon as it sees one. Two other endings:

* **A read that continues.** When the last byte of a read carries no STOP, the
  controller goes back to the format FIFO for the next entry instead of
  stopping, which is the only way it leaves the read acknowledge into
  `PopFmtFifo`.
* **A NACK left unhandled.** `i2c.rdl` describes `HOST_NACK_HANDLER_TIMEOUT`
  as the limit on how long software may leave the controller halted on an
  unexpected NACK; past it the controller raises
  `CONTROLLER_EVENTS.UNHANDLED_NACK_TIMEOUT` as well. Leaves so far clear a
  NACK as soon as they see it, so the timeout had never run out.

The last leg is also where `CONTROLLER_EVENTS` is checked as a register rather
than as a flag. Its fields clear on a written one, so two writes that must
*not* clear them are made first: a word of zeros over a set bit, and a
byte-sized write to the far end of the register, which leaves the lane that
carries the bit disabled. The bit is read back set after each, and only a
written one clears it.

The bench EEPROM target answers the first leg; the second addresses a device
that is not there.

The controller's third ending, the automatic stop it makes when
`CTRL.ENABLEHOST` is cleared with a transaction still open, is not driven
here. `i2c_controller_fsm.sv:291` clears `trans_started` in the same cycle the
enable drops, so the `trans_started && !host_enable_i` arms in `Idle` and in
`PopFmtFifo` are each one cycle wide; with the controller parked
mid-transaction and the queue spent, clearing the enable returned it to idle
without the bench target seeing a stop.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
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
from .smc_i2c_protocol_vip import SmcI2cEepromSlave

EEPROM_ADDR = 0x50
#: An address no device on the bench bus answers.
ABSENT_ADDR = 0x51
EEPROM_OFFSET = 0x60
READ_BACK_BYTE = 0xC3
WRITE_BYTE = 0xD4

I2C0_HOST_NACK_HANDLER_TIMEOUT = smc_indexed_addr(
    "SMC_TOP_SMC_I2C_WRAP_I2C_HOST_NACK_HANDLER_TIMEOUT_BASE_ADDR", 0
)

EVENTS_NACK = _i2c_u32("I2C__CONTROLLER_EVENTS__NACK_bm")
FDATA_RCONT = _i2c_u32("I2C__FDATA__RCONT_bm")
STATUS_RXEMPTY = _i2c_u32("I2C__STATUS__RXEMPTY_bm")
#: A read count of zero in `FDATA.FBYTE` asks for 256 bytes (`i2c.rdl`), one more
#: than any nonzero count can express, and four times the depth of the
#: controller's receive FIFO, so software has to drain while it runs.
FULL_READ_BYTES = 256
#: Read lengths for the read that continues across two format entries: the
#: first entry's last byte is acknowledged because it carries `RCONT`.
RCONT_FIRST = 2
RCONT_SECOND = 1
#: A controller bit period short enough that the 256-byte read costs a few
#: hundred microseconds of simulation. The bench target samples on the SMC
#: clock, far faster than this.
FAST_TIMING0 = (4, 6)
EVENTS_UNHANDLED_NACK_TIMEOUT = _i2c_u32("I2C__CONTROLLER_EVENTS__UNHANDLED_NACK_TIMEOUT_bm")
NACK_TIMEOUT_VAL = _i2c_u32("I2C__HOST_NACK_HANDLER_TIMEOUT__VAL_bm")
NACK_TIMEOUT_EN = _i2c_u32("I2C__HOST_NACK_HANDLER_TIMEOUT__EN_bm")

#: Cycles of the controller's own clock that software is given to handle a
#: NACK. Short, so the leg does not wait on it.
NACK_HANDLER_CYCLES = 256

POLL_CYCLES = 200
IDLE_POLLS = 2000
EVENT_POLLS = 2000


class smc_i2c_controller_exits_test_seq(SmcCsrSeq):
    """A read that continues, an automatic stop, and a NACK left unhandled."""

    def __init__(self, name: str = "smc_i2c_controller_exits_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.retained: list[str] = []
        self.rcont = b""
        self.full_read = 0

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

    async def _enable_host(
        self, label: str, nack_timeout: bool = False, timing0: tuple[int, int] = (0x1A, 0x32)
    ) -> None:
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write(f"{label}_TIMING0", I2C0_TIMING0, _pack_timing0(*timing0))
        await self.csr_write(f"{label}_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write(f"{label}_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write(f"{label}_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write(f"{label}_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        want = (NACK_TIMEOUT_EN | NACK_HANDLER_CYCLES) if nack_timeout else 0
        await self.csr_write(f"{label}_NACK_TIMEOUT", I2C0_HOST_NACK_HANDLER_TIMEOUT, want)
        await self.csr_read(
            f"{label}_NACK_TIMEOUT_RB", I2C0_HOST_NACK_HANDLER_TIMEOUT, expected=want
        )
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        events = await self.csr_read(f"{label}_EVENTS_ENTRY", I2C0_CONTROLLER_EVENTS)
        assert events == 0, f"{label}: CONTROLLER_EVENTS reads 0x{events:08x} before the leg starts"
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _read_continues_leg(self) -> None:
        """A read whose last byte carries no STOP, followed by another entry."""
        label = "READCONT"
        await self._enable_host(label)
        self.slave.write_mem(EEPROM_OFFSET, bytes([READ_BACK_BYTE]))
        stops = self.slave.stops
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET))
        await self.csr_write(
            f"{label}_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        # No STOP on the read: the controller has to return to the format FIFO
        # for the entries that follow.
        await self.csr_write(f"{label}_READ", I2C0_FDATA, _fdata(1, I2C_FDATA_READB))
        await self.csr_write(
            f"{label}_ADDR_W2", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET2", I2C0_FDATA, _fdata(EEPROM_OFFSET + 1))
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(WRITE_BYTE, I2C_FDATA_STOP))
        await self._wait_hostidle(label)

        got = await self.csr_read(f"{label}_RDATA", I2C0_RDATA)
        assert got & 0xFF == READ_BACK_BYTE, (
            f"{label}: the controller read back 0x{got & 0xFF:02x} where the target holds "
            f"0x{READ_BACK_BYTE:02x}"
        )
        wrote = self.slave.read_mem(EEPROM_OFFSET + 1, 1)
        assert wrote == bytes([WRITE_BYTE]), (
            f"{label}: the entry queued after the read left 0x{wrote.hex()} at the target, not "
            f"0x{WRITE_BYTE:02x}; the controller has to come back to the format FIFO for it"
        )
        assert self.slave.stops == stops + 1, (
            f"{label}: the target saw {self.slave.stops - stops} stops; the read carried none, "
            f"so the whole sequence is one transaction ending in the write's stop"
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-READ-CONTINUES: a read whose last byte carried no stop returned to "
            "the format FIFO instead of stopping: the byte read back was 0x%02x, the entry "
            "queued behind it reached the target, and the target saw a single stop",
            READ_BACK_BYTE,
        )

    async def _read_continue_leg(self) -> None:
        """A read split across two format entries, the first carrying RCONT."""
        label = "RCONT"
        await self._enable_host(label)
        pattern = bytes((0xE0 + i) & 0xFF for i in range(RCONT_FIRST + RCONT_SECOND))
        self.slave.write_mem(EEPROM_OFFSET + 8, pattern)
        starts, stops = self.slave.starts, self.slave.stops
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(EEPROM_OFFSET + 8))
        await self.csr_write(
            f"{label}_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        await self.csr_write(
            f"{label}_READ1", I2C0_FDATA, _fdata(RCONT_FIRST, I2C_FDATA_READB | FDATA_RCONT)
        )
        await self.csr_write(
            f"{label}_READ2", I2C0_FDATA, _fdata(RCONT_SECOND, I2C_FDATA_READB | I2C_FDATA_STOP)
        )
        await self._wait_hostidle(label)
        got = bytes(
            [
                (await self.csr_read(f"{label}_RDATA{i}", I2C0_RDATA)) & 0xFF
                for i in range(RCONT_FIRST + RCONT_SECOND)
            ]
        )
        assert got == pattern, (
            f"{label}: the read split across two format entries returned {got.hex()}, not "
            f"the {pattern.hex()} the target holds; RCONT makes the controller acknowledge the "
            f"first entry's last byte and carry on reading"
        )
        assert self.slave.starts == starts + 2 and self.slave.stops == stops + 1, (
            f"{label}: the target saw {self.slave.starts - starts} starts and "
            f"{self.slave.stops - stops} stops; the write, the restart and the continued read "
            f"are one transaction"
        )
        self.rcont = got

    async def _full_read_leg(self) -> None:
        """A read count of zero reads 256 bytes."""
        label = "READ256"
        await self._enable_host(label, timing0=FAST_TIMING0)
        pattern = bytes((0x3C + 7 * i) & 0xFF for i in range(FULL_READ_BYTES))
        self.slave.write_mem(0, pattern)
        await self.csr_write(
            f"{label}_ADDR_W", I2C0_FDATA, _fdata(EEPROM_ADDR << 1, I2C_FDATA_START)
        )
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(0))
        await self.csr_write(
            f"{label}_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        await self.csr_write(
            f"{label}_READ", I2C0_FDATA, _fdata(0, I2C_FDATA_READB | I2C_FDATA_STOP)
        )
        got = bytearray()
        for _ in range(IDLE_POLLS * 8):
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            if not status & STATUS_RXEMPTY:
                got.append((await self.csr_read(f"{label}_RDATA", I2C0_RDATA)) & 0xFF)
                continue
            if status & I2C_STATUS_HOSTIDLE and len(got) >= FULL_READ_BYTES:
                break
            if status & I2C_STATUS_HOSTIDLE:
                # Idle with the receive FIFO empty: the read has ended.
                break
            await ClockCycles(cocotb.top.clk_smc_i, 10)
        events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
        assert len(got) == FULL_READ_BYTES, (
            f"{label}: a read with a count of zero returned {len(got)} bytes, not "
            f"{FULL_READ_BYTES} (CONTROLLER_EVENTS=0x{events:08x})"
        )
        assert bytes(got) == pattern, (
            f"{label}: the 256 bytes read back differ from the target's memory; first "
            f"difference at {next(i for i, (a, b) in enumerate(zip(got, pattern)) if a != b)}"
        )
        self.full_read = len(got)

    async def _retain_checks(self, label: str, bit: int, name: str) -> None:
        """A set event must survive both writes that are not a written one."""
        zero = await self.csr_read(f"{label}_{name}_BEFORE", I2C0_CONTROLLER_EVENTS)
        assert zero & bit, f"{label}: {name} is not set before the retain checks (0x{zero:08x})"
        await self.csr_write(f"{label}_{name}_ZERO", I2C0_CONTROLLER_EVENTS, 0)
        after_zero = await self.csr_read(f"{label}_{name}_AFTER_ZERO", I2C0_CONTROLLER_EVENTS)
        assert after_zero & bit, (
            f"{label}: {name} cleared on a word of zeros (0x{after_zero:08x}); the field "
            f"clears on a written one"
        )
        # A byte-sized write to the top byte: the lane carrying the event bits
        # is not enabled, so the register must not change at all.
        await self.csr_write(f"{label}_{name}_LANE", I2C0_CONTROLLER_EVENTS + 3, 0xFF, length=1)
        after_lane = await self.csr_read(f"{label}_{name}_AFTER_LANE", I2C0_CONTROLLER_EVENTS)
        assert after_lane & bit, (
            f"{label}: {name} cleared on a byte write to the far end of the register "
            f"(0x{after_lane:08x}); that write leaves its lane disabled"
        )
        await self.csr_write(f"{label}_{name}_CLEAR", I2C0_CONTROLLER_EVENTS, bit)
        cleared = await self.csr_read(f"{label}_{name}_CLEARED", I2C0_CONTROLLER_EVENTS)
        assert cleared & bit == 0, f"{label}: {name} survived a written one (0x{cleared:08x})"
        self.retained.append(name)

    async def _unhandled_nack_leg(self) -> None:
        """A NACK software does not clear must raise the handler timeout too."""
        label = "NACKTIMEOUT"
        await self._enable_host(label, nack_timeout=True)
        await self.csr_write(f"{label}_ADDR", I2C0_FDATA, _fdata(ABSENT_ADDR << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(WRITE_BYTE, I2C_FDATA_STOP))

        events = 0
        for _ in range(EVENT_POLLS):
            events = await self.csr_read(f"{label}_EVENTS", I2C0_CONTROLLER_EVENTS)
            if events & EVENTS_NACK:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: CONTROLLER_EVENTS.NACK never set for a write to an address no "
                f"device answers (0x{events:08x})"
            )

        for _ in range(EVENT_POLLS):
            events = await self.csr_read(f"{label}_EVENTS_TIMEOUT", I2C0_CONTROLLER_EVENTS)
            if events & EVENTS_UNHANDLED_NACK_TIMEOUT:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: CONTROLLER_EVENTS.UNHANDLED_NACK_TIMEOUT never set although the "
                f"NACK was left unhandled for far longer than the {NACK_HANDLER_CYCLES} "
                f"cycles programmed (0x{events:08x})"
            )
        cocotb.log.info(
            "CHK-I2C-CTRL-NACK-TIMEOUT: a write to an address no device answers halted the "
            "controller with CONTROLLER_EVENTS.NACK, and leaving it unhandled past the %d "
            "cycles programmed in HOST_NACK_HANDLER_TIMEOUT raised UNHANDLED_NACK_TIMEOUT "
            "beside it (CONTROLLER_EVENTS=0x%08x)",
            NACK_HANDLER_CYCLES,
            events,
        )

        await self._retain_checks(label, EVENTS_UNHANDLED_NACK_TIMEOUT, "UNHANDLED_NACK_TIMEOUT")
        await self._retain_checks(label, EVENTS_NACK, "NACK")
        cocotb.log.info(
            "CHK-I2C-CTRL-EVENTS-RETAIN: each of %s survived a word of zeros written over it "
            "and a byte write that left its lane disabled, and cleared only on a written one",
            " and ".join(self.retained),
        )
        await self.csr_write(
            f"{label}_EVENTS_CLR_FINAL", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self._wait_hostidle(label)

    async def body(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_CONTROLLER_EXITS")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_exits_eeprom")
        await Timer(1, unit="us")

        await self._read_continues_leg()
        await self._read_continue_leg()
        await self._full_read_leg()
        cocotb.log.info(
            "CHK-I2C-CTRL-READ-RCONT: a read split across two format entries, the first "
            "carrying RCONT, came back as one continuous read of %d bytes (%s) inside a single "
            "transaction: the controller acknowledged the first entry's last byte and carried "
            "on",
            len(self.rcont),
            self.rcont.hex(),
        )
        cocotb.log.info(
            "CHK-I2C-CTRL-READ-256: a read with a count of zero returned %d bytes, the whole "
            "of the target's memory in order, drained from a receive FIFO a quarter that deep",
            self.full_read,
        )
        await self._unhandled_nack_leg()
