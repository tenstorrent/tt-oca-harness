# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C instance-to-instance read, target-side STOP interrupt and per-instance interrupt lines.

Sources: hw/ip/i2c/regs/i2c.rdl (FDATA.READB, RDATA.DATA, CONTROLLER_EVENTS.NACK,
INTR_STATE.UNEXP_STOP, INTR_ENABLE), hw/sys/smc/doc/interrupts.adoc (I2C interrupts 0-2).

Three instances share one open-drain bus (+smc_i2c_shared_bus) and one is the controller
at a time. The unconfigured-address NACK and every UNEXP_STOP leg: the specification does not
state the value; they are logged and not compared. Each interrupt-line leg checks the line
low while the enable is clear, then 1 << k after the enable, then low after the clear.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import I2cWireFrame, SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cEepromSlave
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
ENABLE_CMD_COMPLETE = _i2c_u32("I2C__INTR_ENABLE__CMD_COMPLETE_bm")
ENABLE_CONTROLLER_HALT = _i2c_u32("I2C__INTR_ENABLE__CONTROLLER_HALT_bm")
INTR_UNEXP_STOP = _i2c_u32("I2C__INTR_STATE__UNEXP_STOP_bm")
EV_NACK = I2C_CONTROLLER_EVENTS_NACK

INSTANCES = (0, 1, 2)
EEPROM_ADDR = 0x50
ABSENT_ADDR = 0x51
UNCONFIGURED_ADDR = 0x6E
XINST_TARGET_ADDR = 0x36
STOP_TARGET_ADDR = 0x44
TX_BYTES = (0x9E, 0x71)

UNEXP_WINDOW_CYCLES = 4000
UNEXP_POLL_GAP_CYCLES = 100
IRQ_SAMPLE_GAP_CYCLES = 200

BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
RX_POLLS = 400
RX_STEP = 50
IDLE_POLLS = 400
IDLE_STEP = 50
EVENT_POLLS = 600
EVENT_STEP = 25
INTR_POLLS = 600
INTR_STEP = 25
IRQ_POLLS = 400
IRQ_STEP = 4
QUIET_POLLS = 24
QUIET_SAMPLES = 64
QUIET_STEP = 4

FENCE_ORDER = [
    "BRINGUP",
    "XINST_READ_1_2",
    "XINST_UNCFG_OBS",
    "UNEXP_STOP_OBS",
    "UNEXP_CLEAR_OBS",
    "UNEXP_NORMAL_OBS",
    "IRQ_CMDC_LINES",
    "IRQ_HALT_LINES",
]
CHECKER_AFTER = {
    "CHK-XINST-READ-1-2": "XINST_READ_1_2",
    "CHK-XINST-UNCFG-OBS": "XINST_UNCFG_OBS",
    "CHK-UNEXP-STOP-OBS": "UNEXP_STOP_OBS",
    "CHK-UNEXP-CLEAR-OBS": "UNEXP_CLEAR_OBS",
    "CHK-UNEXP-NORMAL-OBS": "UNEXP_NORMAL_OBS",
    "CHK-IRQ-CMDC-LINES": "IRQ_CMDC_LINES",
    "CHK-IRQ-HALT-LINES": "IRQ_HALT_LINES",
}


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


class smc_i2c_ctrl_xinst_events_test_seq(SmcCsrSeq):
    """Run the instance-to-instance legs and the interrupt-line legs, logging every state."""

    def __init__(self, name: str = "smc_i2c_ctrl_xinst_events_test_seq") -> None:
        super().__init__(name)
        self.monitor: SmcFwI2cWireMonitor | None = None
        self.eeprom: SmcI2cEepromSlave | None = None
        self.cycle = 0
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.frame_start = 0

    async def _count_cycles(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            self.cycle += 1

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

    @staticmethod
    def _irq() -> int:
        value = cocotb.top.tb_i2c_irq.value
        assert value.is_resolvable, f"tb_i2c_irq sampled X/Z ({value})"
        return int(value) & 0x7

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

    async def _wait_irq(self, name: str, want: int) -> int:
        seen = [0]

        async def probe() -> tuple[bool, str]:
            seen[0] = self._irq()
            return seen[0] == want, f"tb_i2c_irq=0b{seen[0]:03b} want=0b{want:03b}"

        await self._poll(name, IRQ_POLLS, IRQ_STEP, probe)
        return seen[0]

    async def _wait_bus_released(self, name: str) -> None:
        dut = cocotb.top

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)

    async def _intr(self, idx: int, label: str) -> int:
        return await self.csr_read(label, _reg("INTR_STATE", idx))

    async def _events(self, idx: int, label: str) -> int:
        return await self.csr_read(label, _reg("CONTROLLER_EVENTS", idx))

    def _frame(self, addr7: int, label: str) -> I2cWireFrame:
        frames = [f for f in self.monitor.frames[self.frame_start :] if f.addr7 == addr7]
        assert frames, f"{label}: no wire frame for 0x{addr7:02x}; {self.monitor.summary()}"
        return frames[0]

    async def _program_timing(self, idx: int) -> None:
        for reg, value in (
            ("TIMING0", _pack_timing0(0x1A, 0x32)),
            ("TIMING1", _pack_timing1(2, 2)),
            ("TIMING2", _pack_timing2(5, 4)),
            ("TIMING3", _pack_timing3(2, 5)),
            ("TIMING4", _pack_timing4(4, 5)),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", _reg(reg, idx), value)

    async def _bring_up(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_ctrl_xinst_events_test needs +smc_i2c_shared_bus"
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_XINST")
        await self._wait_bus_released("bus_released_bringup")
        for idx in INSTANCES:
            await self._program_timing(idx)
            await self.csr_write(f"I2C{idx}_INTR_ENABLE_OFF", _reg("INTR_ENABLE", idx), 0)
            await self.csr_write(f"I2C{idx}_OVRD_OFF", _reg("OVRD", idx), 0)
            await self._disable(idx)
        self.monitor = SmcFwI2cWireMonitor(name="smc_i2c_xinst_wire")
        self.eeprom = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c_xinst_eeprom")
        self._stamp("BRINGUP")

    async def _disable(self, idx: int) -> None:
        await self.csr_write(f"I2C{idx}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"I2C{idx}_WRAP_OFF", _wrap(idx), 0)

    async def _enable_target(self, idx: int, addr: int) -> None:
        await self.csr_write(f"TGT{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_TARGET)
        await self.csr_write(
            f"TGT{idx}_TARGET_ID", _reg("TARGET_ID", idx), _pack_target_id(addr, 0x7F, 0, 0)
        )
        await self.csr_write(
            f"TGT{idx}_FIFO",
            _reg("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(
            f"TGT{idx}_CTRL",
            _reg("CTRL", idx),
            I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN,
        )

    async def _enable_controller(self, idx: int, label: str) -> None:
        """Enable instance ``idx`` as the controller with clean FIFOs, events and interrupts."""
        await self.csr_write(f"{label}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"{label}_WRAP", _wrap(idx), I2C_WRAP_CTRL_HOST)
        await self.csr_write(f"{label}_FIFO", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_ENABLEHOST", _reg("CTRL", idx), I2C_CTRL_ENABLEHOST)
        self.frame_start = len(self.monitor.frames)

    async def _queue(self, idx: int, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"I2C{idx}_FDATA_{i}", _reg("FDATA", idx), word)

    async def _wait_ctrl_done(self, idx: int, label: str, stops_base: int) -> str:
        """Wait for the controller to finish: idle with an empty format FIFO and a wire STOP."""
        status = [0]

        async def probe() -> tuple[bool, str]:
            status[0] = await self.csr_read(f"{label}_STATUS", _reg("STATUS", idx))
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            done = status[0] & want == want and self.monitor.stops > stops_base
            return done, f"STATUS=0x{status[0]:08x} {self.monitor.summary()}"

        await self._poll(f"{label}_ctrl_done", IDLE_POLLS, IDLE_STEP, probe)
        return f"STATUS=0x{status[0]:08x}"

    async def _wait_nack(self, idx: int, label: str) -> int:
        events = [0]

        async def probe() -> tuple[bool, str]:
            events[0] = await self._events(idx, f"{label}_EVENTS")
            return bool(events[0] & EV_NACK), f"events=0x{events[0]:08x}"

        await self._poll(f"{label}_nack", EVENT_POLLS, EVENT_STEP, probe)
        return events[0]

    async def _recover(self, idx: int, label: str) -> tuple[int, int]:
        """CTRL first, bounded wait for the clock to stop, clear, read events and halt back."""
        dut = cocotb.top
        await self.csr_write(f"{label}_CTRL_OFF", _reg("CTRL", idx), 0)

        async def quiet() -> tuple[bool, str]:
            prev = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            edges = 0
            for _ in range(QUIET_SAMPLES):
                await ClockCycles(dut.clk_smc_i, QUIET_STEP)
                cur = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
                edges += int(cur != prev)
                prev = cur
            return edges == 0, f"scl_edges={edges}"

        await self._poll(f"{label}_stop_clocking", QUIET_POLLS, 1, quiet)
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), EV_NACK)
        events = await self._events(idx, f"{label}_EVENTS_AFTER_CLR")
        halt = await self._intr(idx, f"{label}_INTR_AFTER_CLR")
        return events, int(bool(halt & INTR_CONTROLLER_HALT))

    async def _leg_end(self, idx: int, label: str) -> None:
        await self.csr_write(f"{label}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self._wait_bus_released(f"{label}_bus_released")

    async def _s2_xinst_read(self) -> None:
        await self._enable_target(2, XINST_TARGET_ADDR)
        for i, byte in enumerate(TX_BYTES):
            await self.csr_write(f"TGT2_TXDATA_{i}", _reg("TXDATA", 2), byte)
        await self._enable_controller(1, "S2")
        stops_base = self.monitor.stops
        await self._queue(
            1,
            [
                _fdata((XINST_TARGET_ADDR << 1) | 1, I2C_FDATA_START),
                _fdata(len(TX_BYTES), I2C_FDATA_READB | I2C_FDATA_STOP),
            ],
        )
        got: list[int] = []
        last = ["never sampled"]

        async def probe() -> tuple[bool, str]:
            status = await self.csr_read("S2_RX_STATUS", _reg("STATUS", 1))
            last[0] = f"STATUS=0x{status:08x} popped={[hex(b) for b in got]}"
            if not status & I2C_STATUS_RXEMPTY:
                rdata = await self.csr_read("S2_RDATA", _reg("RDATA", 1))
                got.append(int(rdata) & 0xFF)
            return len(got) == len(TX_BYTES), last[0]

        await self._poll("s2_rx_bytes", RX_POLLS, RX_STEP, probe)
        assert got == list(TX_BYTES), (
            f"S2: instance 1 popped {[hex(b) for b in got]}, expected {[hex(b) for b in TX_BYTES]}"
        )
        done = await self._wait_ctrl_done(1, "S2", stops_base)
        frame = self._frame(XINST_TARGET_ADDR, "S2")
        await self._leg_end(1, "S2")
        await self._disable(1)
        self._stamp("XINST_READ_1_2")
        self._chk(
            "CHK-XINST-READ-1-2",
            f"instance 1 read from instance 2 target 0x{XINST_TARGET_ADDR:02x}: RDATA pops "
            f"{[f'0x{b:02x}' for b in got]} equal TXDATA {[f'0x{b:02x}' for b in TX_BYTES]} "
            f"in order; wire frame {frame}; {done}",
        )

    async def _s3_unconfigured(self) -> None:
        await self._enable_controller(0, "S3")
        stops_base = self.monitor.stops
        await self._queue(
            0,
            [
                _fdata(UNCONFIGURED_ADDR << 1, I2C_FDATA_START),
                _fdata(0x11, I2C_FDATA_STOP),
            ],
        )
        events = [0]

        async def probe() -> tuple[bool, str]:
            events[0] = await self._events(0, "S3_EVENTS")
            done = bool(events[0] & EV_NACK) or self.monitor.stops > stops_base
            return done, f"events=0x{events[0]:08x} {self.monitor.summary()}"

        await self._poll("s3_nack_or_stop", EVENT_POLLS, EVENT_STEP, probe)
        intr = await self._intr(0, "S3_INTR_STATE")
        frame = self._frame(UNCONFIGURED_ADDR, "S3")
        ev_after, halt_after = await self._recover(0, "S3")
        await self._leg_end(0, "S3")
        self._stamp("XINST_UNCFG_OBS")
        self._chk(
            "CHK-XINST-UNCFG-OBS",
            f"wire frame for 0x{UNCONFIGURED_ADDR:02x} {frame} (address_acked="
            f"{frame.addr_acked}); instance 0 CONTROLLER_EVENTS=0x{events[0]:08x} "
            f"NACK={int(bool(events[0] & EV_NACK))}; INTR_STATE=0x{intr:08x} CONTROLLER_HALT="
            f"{int(bool(intr & INTR_CONTROLLER_HALT))}; recovery readback events="
            f"0x{ev_after:08x} halt={halt_after}; no compare (not specified, measured)",
        )

    async def _unexp_window(self, label: str) -> list[tuple[int, int]]:
        """Read instance 1 INTR_STATE.UNEXP_STOP for 4000 cycles; return (cycle offset, bit)."""
        start = self.cycle
        end = start + UNEXP_WINDOW_CYCLES
        rows: list[tuple[int, int]] = []
        while True:
            intr = await self._intr(1, f"{label}_INTR_STATE")
            rows.append((self.cycle - start, int(bool(intr & INTR_UNEXP_STOP))))
            if self.cycle >= end:
                break
            await ClockCycles(cocotb.top.clk_smc_i, UNEXP_POLL_GAP_CYCLES)
        observed = self.cycle - start
        assert observed >= UNEXP_WINDOW_CYCLES, f"{label}: window {observed} cycles"
        self.waits.append(
            (f"{label}_unexp_window", f"{UNEXP_WINDOW_CYCLES}cyc", f"{len(rows)} polls, ran full")
        )
        return rows

    @staticmethod
    def _rows(rows: list[tuple[int, int]]) -> str:
        return " ".join(f"t+{t}:{v}" for t, v in rows)

    async def _s4_unexp_stop_early(self) -> None:
        await self._disable(2)
        await self._enable_target(1, STOP_TARGET_ADDR)
        await self._enable_controller(0, "S4")
        stops_base = self.monitor.stops
        await self._queue(0, [_fdata(STOP_TARGET_ADDR << 1, I2C_FDATA_START | I2C_FDATA_STOP)])
        rows = await self._unexp_window("S4")
        done = await self._wait_ctrl_done(0, "S4", stops_base)
        frame = self._frame(STOP_TARGET_ADDR, "S4")
        await self._leg_end(0, "S4")
        self._stamp("UNEXP_STOP_OBS")
        self._chk(
            "CHK-UNEXP-STOP-OBS",
            f"instance 1 target 0x{STOP_TARGET_ADDR:02x}, controller STOP straight after the "
            f"address, wire frame {frame}, {done}; INTR_STATE.UNEXP_STOP per poll "
            f"({len(rows)} polls over {UNEXP_WINDOW_CYCLES} cycles): {self._rows(rows)}; "
            f"final={rows[-1][1]}; no compare (not specified, measured)",
        )

    async def _s5_unexp_clear(self) -> None:
        before = await self._intr(1, "S5_INTR_BEFORE")
        await self.csr_write("S5_UNEXP_CLR", _reg("INTR_STATE", 1), INTR_UNEXP_STOP)
        after = await self._intr(1, "S5_INTR_AFTER")
        self._stamp("UNEXP_CLEAR_OBS")
        self._chk(
            "CHK-UNEXP-CLEAR-OBS",
            f"instance 1 INTR_STATE before the written 1: 0x{before:08x} UNEXP_STOP="
            f"{int(bool(before & INTR_UNEXP_STOP))}; after: 0x{after:08x} UNEXP_STOP="
            f"{int(bool(after & INTR_UNEXP_STOP))}; no compare (not specified, measured)",
        )

    async def _s6_unexp_normal(self) -> None:
        pre = await self._intr(1, "S6_INTR_PRE")
        await self._enable_controller(0, "S6")
        stops_base = self.monitor.stops
        await self._queue(
            0,
            [
                _fdata(STOP_TARGET_ADDR << 1, I2C_FDATA_START),
                _fdata(0xA5),
                _fdata(0x5A, I2C_FDATA_STOP),
            ],
        )
        rows = await self._unexp_window("S6")
        done = await self._wait_ctrl_done(0, "S6", stops_base)
        frame = self._frame(STOP_TARGET_ADDR, "S6")
        await self._leg_end(0, "S6")
        await self._disable(0)
        await self._disable(1)
        self._stamp("UNEXP_NORMAL_OBS")
        self._chk(
            "CHK-UNEXP-NORMAL-OBS",
            f"instance 1 target 0x{STOP_TARGET_ADDR:02x}, normal write 0xA5 0x5A then STOP, "
            f"wire frame {frame}, {done}; INTR_STATE before the write 0x{pre:08x}; "
            f"UNEXP_STOP per poll ({len(rows)} polls over {UNEXP_WINDOW_CYCLES} cycles): "
            f"{self._rows(rows)}; final={rows[-1][1]}; no compare (not specified, measured)",
        )

    async def _irq_leg_setup(self, k: int, label: str) -> None:
        for idx in INSTANCES:
            if idx != k:
                await self._disable(idx)
        await self._enable_controller(k, label)

    async def _s7_cmd_complete(self) -> None:
        rows = []
        for k in INSTANCES:
            label = f"S7_I{k}"
            en_addr = _reg("INTR_ENABLE", k)
            await self._irq_leg_setup(k, label)
            stops_base = self.monitor.stops
            await self._queue(
                k,
                [
                    _fdata(EEPROM_ADDR << 1, I2C_FDATA_START),
                    _fdata(0x20),
                    _fdata(0x5C, I2C_FDATA_STOP),
                ],
            )
            intr = [0]

            async def probe(k=k, label=label, intr=intr) -> tuple[bool, str]:
                intr[0] = await self._intr(k, f"{label}_INTR_STATE")
                return bool(intr[0] & INTR_CMD_COMPLETE), f"INTR_STATE=0x{intr[0]:08x}"

            await self._poll(f"{label}_cmd_complete", INTR_POLLS, INTR_STEP, probe)
            await self._wait_ctrl_done(k, label, stops_base)
            frame = self._frame(EEPROM_ADDR, label)
            assert frame.addr_acked is True, f"{label}: EEPROM frame {frame}"
            intr_done = await self._intr(k, f"{label}_INTR_DONE")
            assert intr_done & INTR_CMD_COMPLETE, f"{label}: CMD_COMPLETE reads 0 ({intr_done:#x})"
            low0 = self._irq()
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SAMPLE_GAP_CYCLES)
            low1 = self._irq()
            assert low0 == 0 and low1 == 0, (
                f"{label}: tb_i2c_irq 0b{low0:03b}/0b{low1:03b} with INTR_ENABLE.CMD_COMPLETE=0"
            )
            await self.csr_write(f"{label}_ENABLE", en_addr, ENABLE_CMD_COMPLETE)
            high = await self._wait_irq(f"{label}_irq_high", 1 << k)
            await self.csr_write(f"{label}_CLEAR", _reg("INTR_STATE", k), INTR_CMD_COMPLETE)
            low = await self._wait_irq(f"{label}_irq_low", 0)
            await self.csr_write(f"{label}_DISABLE", en_addr, 0)
            await self._leg_end(k, label)
            rows.append(
                f"inst{k}: INTR_STATE=0x{intr_done:08x} CMD_COMPLETE=1 irq 0b{low0:03b}"
                f" 0b{low1:03b} "
                f"-> enable -> 0b{high:03b} -> clear -> 0b{low:03b}"
            )
        for k in INSTANCES:
            await self._disable(k)
        self._stamp("IRQ_CMDC_LINES")
        self._chk(
            "CHK-IRQ-CMDC-LINES",
            f"set: STOP of a write to 0x{EEPROM_ADDR:02x}; observed/cleared/checked_cleared: "
            f"{'; '.join(rows)}",
        )

    async def _s8_halt_lines(self) -> None:
        rows = []
        for k in INSTANCES:
            label = f"S8_I{k}"
            en_addr = _reg("INTR_ENABLE", k)
            await self._irq_leg_setup(k, label)
            await self._queue(
                k,
                [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START), _fdata(0x5A, I2C_FDATA_STOP)],
            )
            events = await self._wait_nack(k, label)
            intr = await self._intr(k, f"{label}_INTR_STATE")
            assert intr & INTR_CONTROLLER_HALT, f"{label}: CONTROLLER_HALT reads 0 ({intr:#x})"
            frame = self._frame(ABSENT_ADDR, label)
            assert frame.addr_acked is False, f"{label}: wire frame {frame} was acknowledged"
            low0 = self._irq()
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SAMPLE_GAP_CYCLES)
            low1 = self._irq()
            assert low0 == 0 and low1 == 0, (
                f"{label}: tb_i2c_irq 0b{low0:03b}/0b{low1:03b} with INTR_ENABLE.CONTROLLER_HALT=0"
            )
            await self.csr_write(f"{label}_ENABLE", en_addr, ENABLE_CONTROLLER_HALT)
            high = await self._wait_irq(f"{label}_irq_high", 1 << k)
            ev_after, halt_after = await self._recover(k, label)
            low = await self._wait_irq(f"{label}_irq_low", 0)
            await self.csr_write(f"{label}_DISABLE", en_addr, 0)
            assert ev_after & EV_NACK == 0 and halt_after == 0, (
                f"{label}: after CTRL=0 and the NACK clear events=0x{ev_after:08x} "
                f"halt={halt_after}"
            )
            await self._leg_end(k, label)
            rows.append(
                f"inst{k}: events=0x{events:08x} NACK=1 CONTROLLER_HALT=1 frame {frame} irq "
                f"0b{low0:03b} 0b{low1:03b} -> enable -> 0b{high:03b} -> CTRL=0 and NACK "
                f"written -> 0b{low:03b}, events=0x{ev_after:08x} halt={halt_after}"
            )
        for k in INSTANCES:
            await self._disable(k)
        self._stamp("IRQ_HALT_LINES")
        self._chk(
            "CHK-IRQ-HALT-LINES",
            f"set: NACKed address 0x{ABSENT_ADDR:02x}; observed/cleared/checked_cleared: "
            f"{'; '.join(rows)}",
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
        counter = cocotb.start_soon(self._count_cycles())
        try:
            await self._bring_up()
            await self._s2_xinst_read()
            await self._s3_unconfigured()
            await self._s4_unexp_stop_early()
            await self._s5_unexp_clear()
            await self._s6_unexp_normal()
            await self._s7_cmd_complete()
            await self._s8_halt_lines()
        finally:
            counter.cancel()
            if self.monitor is not None:
                self.monitor.stop()
        self._emit_timeout_paths()
        self._emit_nonvac()
