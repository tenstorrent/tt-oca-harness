# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller transactions framed on the wire.

Contract SMC_I2C_CTRL_005, anchor smc_i2c_ctrl_wire_frames_test.
Scenarios: I2CC-START-STOP.S3, I2CC-START-STOP.S4, I2CC-ADDR-BYTE.S1, I2CC-WRITE-XFER.S2,
I2CC-READ-XFER.S1, I2CC-READ-XFER.S2, I2CC-READ-CONTINUE.S1, I2CC-BACK-TO-BACK.S3,
I2CC-STATUS-FLAGS.S2, I2CC-STATUS-FLAGS.S4.
Sources: hw/ip/i2c/regs/i2c.rdl (FDATA.START, FDATA.STOP, FDATA.FBYTE, FDATA.READB,
FDATA.RCONT, RDATA.DATA, STATUS.RXEMPTY, STATUS.FMTEMPTY, STATUS.HOSTIDLE).

Three bench EEPROM targets (0x50, 0x29, 0x6B) answer on the I2C0 pads and a passive wire
monitor decodes every frame. Every transaction is queued with CTRL cleared and executed by
setting ENABLEHOST. STATUS.HOSTIDLE during and after a transaction is logged and not
compared (SF-015).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import I2cWireFrame, SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CONTROLLER_MODE,
    I2C_WRAP_EN,
)
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
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
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    _fdata,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave

EEPROM_ADDRS = (0x50, 0x29, 0x6B)
EEPROM = 0x50
WR = EEPROM << 1
RD = (EEPROM << 1) | 1
READ_OFFSET = 0x40
READ_PATTERN = bytes([0xF1, 0xF2, 0xF3, 0xF4])
WRITE_PATTERN = [0x00, 0xFF, 0x55, 0xAA, 0x01, 0x80]

BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
WIRE_POLLS = 4000
WIRE_STEP = 16
OPEN_POLLS = 4000
OPEN_STEP = 4
RXEMPTY_POLLS = 200
RXEMPTY_STEP = 32

FENCE_ORDER = [
    "BRINGUP",
    "ONE_START_PER_STOP",
    "STOP_POSITION",
    "ADDR_VALUES",
    "WRITE_PATTERN",
    "READ_LAST_NACK",
    "READ_COUNTS",
    "RX_POP",
    "QUEUE_WHILE_BUSY",
]
CHECKER_AFTER = {
    "CHK-ONE-START-PER-STOP": "ONE_START_PER_STOP",
    "CHK-STOP-POSITION": "STOP_POSITION",
    "CHK-ADDR-VALUES": "ADDR_VALUES",
    "CHK-WRITE-PATTERN": "WRITE_PATTERN",
    "CHK-READ-LAST-NACK": "READ_LAST_NACK",
    "CHK-READ-COUNTS": "READ_COUNTS",
    "CHK-RX-POP": "RX_POP",
    "CHK-QUEUE-WHILE-BUSY": "QUEUE_WHILE_BUSY",
    "CHK-HOSTIDLE-OBS": "QUEUE_WHILE_BUSY",
}


class smc_i2c_ctrl_wire_frames_test_seq(SmcCsrSeq):
    """Queue I2C0 transactions and compare the decoded wire frames with the queued entries."""

    def __init__(self, name: str = "smc_i2c_ctrl_wire_frames_test_seq") -> None:
        super().__init__(name)
        self.monitor: SmcFwI2cWireMonitor | None = None
        self.eeproms: dict[int, SmcI2cEepromSlave] = {}
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.read_last_nack = ""
        self.read_counts = ""

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _bit(handle, name: str) -> int:
        value = handle.value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value) & 1

    def _pad_levels(self) -> str:
        dut = cocotb.top
        return " ".join(
            f"{n}={self._bit(getattr(dut, f'tb_i2c0_{n}'), f'tb_i2c0_{n}')}"
            for n in ("scl", "sda", "scl_dut_low", "sda_dut_low")
        )

    def _wire_state(self) -> str:
        return f"{self.monitor.summary()} {self._pad_levels()}"

    async def _poll(self, name: str, polls: int, step: int, probe) -> None:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry."""
        state = "never sampled"
        for _ in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, f"{polls}x{step}cyc", state))
                return
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self.waits.append((name, f"{polls}x{step}cyc", f"EXPIRED {state}"))
        raise AssertionError(f"{name}: not satisfied within {polls}x{step} cycles; last {state}")

    async def _wait_stops(self, name: str, stops: int) -> None:
        async def probe() -> tuple[bool, str]:
            return self.monitor.stops >= stops, f"want stops>={stops} {self._wire_state()}"

        await self._poll(name, WIRE_POLLS, WIRE_STEP, probe)

    async def _bring_up(self) -> None:
        dut = cocotb.top
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write(
            "I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_EN | I2C_WRAP_CONTROLLER_MODE
        )
        await self.arm_i2c_gpio_lsio(0, "I2C0_WIRE_FRAMES")

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            scl_i = self._bit(dut.tb_i2c0_scl_i, "tb_i2c0_scl_i")
            return (scl, sda, scl_i) == (1, 1, 1), f"scl={scl} sda={sda} scl_i={scl_i}"

        await self._poll("bus_released", BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        self.monitor = SmcFwI2cWireMonitor(name="smc_i2c0_wire_frames_wire")
        for addr in EEPROM_ADDRS:
            self.eeproms[addr] = SmcI2cEepromSlave(addr=addr, name=f"smc_i2c0_eeprom_{addr:02x}")
        self._stamp("BRINGUP")

    async def _queue(self, label: str, words: list[int]) -> None:
        await self.csr_write(f"{label}_CTRL_OFF", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", I2C0_FDATA, word)

    async def _txn(self, label: str, words: list[int]) -> list[I2cWireFrame]:
        """Queue ``words`` with CTRL cleared, enable, wait for the STOP; return its frames."""
        await self._queue(label, words)
        frame_base = len(self.monitor.frames)
        stops = self.monitor.stops
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self._wait_stops(f"{label}_wire_end", stops + 1)
        assert self.monitor.stops == stops + 1, (
            f"{label}: {self.monitor.stops - stops} STOPs for one queued transaction; "
            f"{self._wire_state()}"
        )
        return self.monitor.frames[frame_base:]

    @staticmethod
    def _write_frame(label: str, frame: I2cWireFrame, addr7: int, data: list[int]) -> None:
        got = [b for b, _ in frame.data]
        assert frame.addr7 == addr7 and frame.read is False and frame.addr_acked is True, (
            f"{label}: frame {frame}, expected an acknowledged write to 0x{addr7:02x}"
        )
        assert got == data and all(a for _, a in frame.data), (
            f"{label}: frame {frame}, expected acknowledged data {[hex(d) for d in data]}"
        )

    async def _s2_start_stop(self) -> None:
        rows = []
        for n, value in enumerate((0x11, 0x22), start=1):
            frames = await self._txn(
                f"S2_{n}",
                [_fdata(WR, I2C_FDATA_START), _fdata(0x30), _fdata(value, I2C_FDATA_STOP)],
            )
            starts, stops, count = self.monitor.starts, self.monitor.stops, len(self.monitor.frames)
            assert (starts, stops, count) == (n, n, n), (
                f"S2_{n}: wire counts starts={starts} stops={stops} frames={count}, "
                f"expected {n} {n} {n}"
            )
            self._write_frame(f"S2_{n}", frames[-1], EEPROM, [0x30, value])
            rows.append(f"after txn {n}: starts={starts} stops={stops} frames={count}")
        assert len(self.monitor.frames) == 2, f"S2: {len(self.monitor.frames)} frames, expected 2"
        self._stamp("ONE_START_PER_STOP")
        self._chk(
            "CHK-ONE-START-PER-STOP",
            f"{'; '.join(rows)}; monitor holds {len(self.monitor.frames)} frames "
            f"{[str(f) for f in self.monitor.frames]}",
        )

    async def _s3_stop_position(self) -> None:
        stops = self.monitor.stops
        a = await self._txn("S3A", [_fdata(WR, I2C_FDATA_START), _fdata(0x20, I2C_FDATA_STOP)])
        assert self.monitor.stops == stops + 1
        self._write_frame("S3A", a[-1], EEPROM, [0x20])
        b = await self._txn(
            "S3B",
            [_fdata(WR, I2C_FDATA_START), _fdata(0x21), _fdata(0x5C, I2C_FDATA_STOP)],
        )
        assert self.monitor.stops == stops + 2, f"S3: STOPs {self.monitor.stops - stops}, want 2"
        self._write_frame("S3B", b[-1], EEPROM, [0x21, 0x5C])
        self._stamp("STOP_POSITION")
        self._chk(
            "CHK-STOP-POSITION",
            f"shape A frame {a[-1]} (one data byte 0x20, 1 STOP); shape B frame {b[-1]} "
            f"(data 0x21 0x5C, 1 STOP); STOP count +{self.monitor.stops - stops} over both",
        )

    async def _s4_addr_values(self) -> None:
        frames = []
        for addr in EEPROM_ADDRS:
            got = await self._txn(
                f"S4_{addr:02x}",
                [_fdata(addr << 1, I2C_FDATA_START), _fdata(0x77, I2C_FDATA_STOP)],
            )
            frame = got[-1]
            self._write_frame(f"S4_{addr:02x}", frame, addr, [0x77])
            wire_byte = (frame.addr7 << 1) | int(frame.read)
            assert wire_byte == addr << 1, (
                f"S4_{addr:02x}: wire byte 0x{wire_byte:02x}, FBYTE written 0x{addr << 1:02x}"
            )
            frames.append(frame)
        self._stamp("ADDR_VALUES")
        self._chk(
            "CHK-ADDR-VALUES",
            f"frames in order {[str(f) for f in frames]}; wire bytes "
            f"{[hex((f.addr7 << 1) | int(f.read)) for f in frames]} equal FBYTE written "
            f"{[hex(a << 1) for a in EEPROM_ADDRS]}",
        )

    async def _s5_write_pattern(self) -> None:
        words = [_fdata(WR, I2C_FDATA_START), _fdata(0x30)]
        words += [_fdata(b) for b in WRITE_PATTERN[:-1]]
        words.append(_fdata(WRITE_PATTERN[-1], I2C_FDATA_STOP))
        frames = await self._txn("S5", words)
        self._write_frame("S5", frames[-1], EEPROM, [0x30] + WRITE_PATTERN)
        mem = list(self.eeproms[EEPROM].read_mem(0x30, len(WRITE_PATTERN)))
        assert mem == WRITE_PATTERN, f"S5: target memory 0x30.. {mem}, expected {WRITE_PATTERN}"
        self._stamp("WRITE_PATTERN")
        self._chk(
            "CHK-WRITE-PATTERN",
            f"frame {frames[-1]}; target memory 0x30..0x35 = {' '.join(f'{b:02x}' for b in mem)}",
        )

    def _read_frame(self, label: str, frames: list[I2cWireFrame], count: int) -> I2cWireFrame:
        assert len(frames) == 2, f"{label}: {len(frames)} frames, expected write + read"
        self._write_frame(f"{label}_ptr", frames[0], EEPROM, [READ_OFFSET])
        frame = frames[1]
        assert frame.addr7 == EEPROM and frame.read is True and frame.addr_acked is True, (
            f"{label}: read frame {frame}, expected an acknowledged read of 0x{EEPROM:02x}"
        )
        want = [(b, i < count - 1) for i, b in enumerate(READ_PATTERN[:count])]
        assert frame.data == want, (
            f"{label}: read frame data {frame.data}, expected {want} "
            f"(every byte acknowledged but the last)"
        )
        return frame

    def _read_words(self, count: int) -> list[int]:
        return [
            _fdata(WR, I2C_FDATA_START),
            _fdata(READ_OFFSET),
            _fdata(RD, I2C_FDATA_START),
            _fdata(count, I2C_FDATA_READB | I2C_FDATA_STOP),
        ]

    async def _status(self, label: str) -> int:
        return await self.csr_read(label, I2C0_STATUS)

    async def _s6_read_one(self) -> str:
        self.eeproms[EEPROM].write_mem(READ_OFFSET, READ_PATTERN)
        frames = await self._txn("S6", self._read_words(1))
        frame = self._read_frame("S6", frames, 1)
        pop = await self.csr_read("S6_RDATA", I2C0_RDATA) & 0xFF
        assert pop == READ_PATTERN[0], f"S6: RDATA popped 0x{pop:02x}, expected 0xf1"
        self.read_counts = f"count one popped 0x{pop:02x}"
        return f"count one frame {frame}"

    async def _s7_read_four(self, s6_frame: str) -> None:
        await self._queue("S7", [])
        empty_before = await self._status("S7_STATUS_BEFORE") & I2C_STATUS_RXEMPTY
        assert empty_before, "S7: STATUS.RXEMPTY reads 0 before the read after RXRST"
        for i, word in enumerate(self._read_words(4)):
            await self.csr_write(f"S7_FDATA{i}", I2C0_FDATA, word)
        frame_base = len(self.monitor.frames)
        stops = self.monitor.stops
        await self.csr_write("S7_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await self._wait_stops("S7_wire_end", stops + 1)
        seen = [0]

        async def rx_filled() -> tuple[bool, str]:
            status = await self._status("S7_STATUS_POLL")
            seen[0] = status
            return not status & I2C_STATUS_RXEMPTY, f"STATUS=0x{status:08x}"

        await self._poll("S7_rxempty_deassert", RXEMPTY_POLLS, RXEMPTY_STEP, rx_filled)
        frame = self._read_frame("S7", self.monitor.frames[frame_base:], 4)
        self._stamp("READ_LAST_NACK")
        self._chk(
            "CHK-READ-LAST-NACK",
            f"{s6_frame}: single byte 0xf1 not acknowledged; count four frame {frame}: "
            f"0xf1 0xf2 0xf3 acknowledged, 0xf4 not acknowledged",
        )
        pops, empties = [], []
        for i in range(4):
            pops.append(await self.csr_read(f"S7_RDATA{i}", I2C0_RDATA) & 0xFF)
            status = await self._status(f"S7_STATUS_POP{i}")
            empties.append(int(bool(status & I2C_STATUS_RXEMPTY)))
        assert bytes(pops) == READ_PATTERN, f"S7: pops {bytes(pops).hex()}, want f1f2f3f4"
        self._stamp("READ_COUNTS")
        self._chk(
            "CHK-READ-COUNTS",
            f"{self.read_counts}; count four pops {' '.join(f'{p:02x}' for p in pops)} "
            f"in order from target memory 0x40",
        )
        final = await self._status("S7_STATUS_AFTER_POPS")
        assert empties == [0, 0, 0, 1], f"S7: RXEMPTY after pops 1..4 reads {empties}"
        assert final & I2C_STATUS_RXEMPTY, (
            f"S7: RXEMPTY reads 0 after the fourth pop (0x{final:08x})"
        )
        self._stamp("RX_POP")
        self._chk(
            "CHK-RX-POP",
            f"set: RXEMPTY=1 before the read (STATUS before) and deasserted on the first read "
            f"byte; observed: bounded poll read STATUS=0x{seen[0]:08x} (RXEMPTY=0) with four "
            f"data bytes on the wire; cleared: four RDATA reads; RXEMPTY after pops 1..4 = "
            f"{empties}; checked_cleared: STATUS after the fourth pop RXEMPTY=1",
        )

    async def _s8_queue_while_busy(self) -> None:
        txn1 = [
            _fdata(WR, I2C_FDATA_START),
            _fdata(0x50),
            _fdata(0x61),
            _fdata(0x62, I2C_FDATA_STOP),
        ]
        txn2 = [_fdata(WR, I2C_FDATA_START), _fdata(0x58), _fdata(0x63, I2C_FDATA_STOP)]
        await self._queue("S8", txn1)
        frame_base = len(self.monitor.frames)
        starts, stops = self.monitor.starts, self.monitor.stops
        await self.csr_write("S8_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)

        async def open_txn() -> tuple[bool, str]:
            done = self.monitor.starts == starts + 1 and self.monitor.stops == stops
            return done, f"want one START and no STOP {self._wire_state()}"

        await self._poll("S8_start_open", OPEN_POLLS, OPEN_STEP, open_txn)
        for i, word in enumerate(txn2):
            await self.csr_write(f"S8_PUSH{i}", I2C0_FDATA, word)
        open_before = self.monitor.stops == stops and self.monitor.starts == starts + 1
        status = await self._status("S8_STATUS_PUSH")
        open_after = self.monitor.stops == stops and self.monitor.starts == starts + 1
        assert open_before and open_after, (
            f"S8: transaction 1 not open at the push: {self._wire_state()}"
        )
        assert not status & I2C_STATUS_FMTEMPTY, (
            f"S8: STATUS.FMTEMPTY reads 1 (0x{status:08x}) right after transaction 2 was pushed"
        )
        reads = [("after push", status, self._wire_state())]
        await self._wait_stops("S8_stop1", stops + 1)
        reads.append(("after STOP 1", await self._status("S8_STATUS_STOP1"), self._wire_state()))
        await self._wait_stops("S8_stop2", stops + 2)
        reads.append(("after STOP 2", await self._status("S8_STATUS_STOP2"), self._wire_state()))
        frames = self.monitor.frames[frame_base:]
        assert len(frames) == 2, f"S8: {len(frames)} frames, expected 2; {self._wire_state()}"
        self._write_frame("S8_1", frames[0], EEPROM, [0x50, 0x61, 0x62])
        self._write_frame("S8_2", frames[1], EEPROM, [0x58, 0x63])
        got = (self.monitor.starts - starts, self.monitor.stops - stops)
        assert got == (2, 2), f"S8: starts/stops {got}, expected (2, 2)"
        self._stamp("QUEUE_WHILE_BUSY")
        self._chk(
            "CHK-QUEUE-WHILE-BUSY",
            f"STATUS=0x{status:08x} FMTEMPTY=0 right after the push with transaction 1 open "
            f"({open_before}, {open_after}); frame 1 {frames[0]}, frame 2 {frames[1]}; "
            f"starts={got[0]} stops={got[1]}",
        )
        self._chk(
            "CHK-HOSTIDLE-OBS",
            "; ".join(
                f"{when}: STATUS=0x{st:08x} HOSTIDLE={int(bool(st & I2C_STATUS_HOSTIDLE))} "
                f"FMTEMPTY={int(bool(st & I2C_STATUS_FMTEMPTY))} wire [{wire}]"
                for when, st, wire in reads
            )
            + "; no compare (SF-015)",
        )

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry; %s",
            len(waits),
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )
        self.chk_lines.append(("CHK-TIMEOUT-PATHS", len(self.stamps)))

    def _emit_nonvac(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = dict(self.chk_lines)
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never printed"
            assert printed[name] > order.index(term), f"{name} printed before {term}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        try:
            await self._bring_up()
            await self._s2_start_stop()
            await self._s3_stop_position()
            await self._s4_addr_values()
            await self._s5_write_pattern()
            s6 = await self._s6_read_one()
            await self._s7_read_four(s6)
            await self._s8_queue_while_busy()
        finally:
            self.monitor.stop()
        self._emit_timeout_paths()
        self._emit_nonvac()
