# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller interrupt write-one-clear lifecycle and enable gating.

Sources: hw/ip/i2c/regs/i2c.rdl (INTR_STATE, INTR_ENABLE), hw/sys/smc/doc/interrupts.adoc.

`INTR_STATE.CMD_COMPLETE` is read 0, reads 1 after the target frames the STOP of a write
transaction to the bench EEPROM, cleared by a written 1 and set again by a second identical
transaction. A write, repeated START, read transaction logs the wire monitor counts at the
first read that shows `CMD_COMPLETE` (the specification does not state the set point). A
second bench pad driver pulls SDA inside the ninth SCL high window to set `SDA_UNSTABLE` and
pulls SCL low after the ninth rise to set `SCL_INTERFERENCE`; each flag is read set before its
written 1 and read 0 after it. The SCL pull is repeated with the interrupt enable clear:
`tb_i2c_irq` stays 0b000 while the flag is set, reads 0b001 once the enable is written and
0b000 after the clear.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import SmcFwI2cWireMonitor
from .smc_i2c_field_masks import I2C_WRAP_CONTROLLER_MODE, I2C_WRAP_EN
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
    _fdata,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave, SmcI2cMasterVip


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_INTR_ENABLE = _i2c0("INTR_ENABLE")
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_SDA_UNSTABLE = _i2c_u32("I2C__INTR_STATE__SDA_UNSTABLE_bm")
INTR_SCL_INTERFERENCE = _i2c_u32("I2C__INTR_STATE__SCL_INTERFERENCE_bm")
ENABLE_SCL_INTERFERENCE = _i2c_u32("I2C__INTR_ENABLE__SCL_INTERFERENCE_bm")
WATCHED_FLAGS = INTR_CMD_COMPLETE | INTR_SDA_UNSTABLE | INTR_SCL_INTERFERENCE

EEPROM_ADDR = 0x50
ABSENT_ADDR = 0x51
OFFSET = 0x20
DATA_BYTE = 0x5C
READ_BYTES = 8
THIGH = 0x1A
TLOW = 0x32
SDA_PULL_DELAY_NS = 20
SCL_PULL_DELAY_NS = 60
SCL_PULL_NS = 100
ACK_RISE = 9
IRQ_SAMPLE_GAP_CYCLES = 200

EDGE_WAIT_CYCLES = 200_000
BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4
FLAG_POLLS = 3000
FLAG_STEP = 100
STOP_POLLS = 3000
STOP_STEP = 100
IDLE_POLLS = 3000
IDLE_STEP = 100
IRQ_POLLS = 500
IRQ_STEP = 4
RECOVER_CLOCKS = 18

FENCE_ORDER = [
    "BRINGUP",
    "CMDC_STOP",
    "CMDC_REASSERT",
    "CMDC_RS_OBS",
    "SDAU_W1C",
    "SCLI_W1C",
    "SCLI_GATE",
]
CHECKER_AFTER = {
    "CHK-CMDC-STOP": "CMDC_STOP",
    "CHK-CMDC-REASSERT": "CMDC_REASSERT",
    "CHK-CMDC-RS-OBS": "CMDC_RS_OBS",
    "CHK-SDAU-W1C": "SDAU_W1C",
    "CHK-SCLI-W1C": "SCLI_W1C",
    "CHK-SCLI-GATE": "SCLI_GATE",
}


class smc_i2c_ctrl_intr_w1c_test_seq(SmcCsrSeq):
    """Write-one-clear lifecycle and enable gating of three I2C0 controller interrupts."""

    def __init__(self, name: str = "smc_i2c_ctrl_intr_w1c_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.other: SmcI2cMasterVip | None = None
        self.monitor: SmcFwI2cWireMonitor | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: dict[str, tuple[str, str]] = {}

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        cocotb.log.info("%s: %s", name, line)
        self.chk_lines.append((name, len(self.stamps)))

    @staticmethod
    def _bit(handle, name: str, index: int = 0) -> int:
        value = handle.value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return (int(value) >> index) & 1

    def _scl(self) -> int:
        return self._bit(cocotb.top.tb_i2c0_scl, "tb_i2c0_scl")

    def _sda(self) -> int:
        return self._bit(cocotb.top.tb_i2c0_sda, "tb_i2c0_sda")

    def _irq(self) -> int:
        value = cocotb.top.tb_i2c_irq.value
        assert value.is_resolvable, f"tb_i2c_irq sampled X/Z ({value})"
        return int(value)

    def _note(self, name: str, bound: str, state: str) -> None:
        self.waits[name] = (bound, state)

    async def _poll(self, name: str, polls: int, step: int, probe) -> int:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry."""
        bound = f"{polls}x{step}cyc"
        state = "never sampled"
        for waited in range(polls):
            done, state = await probe()
            if done:
                self._note(name, bound, state)
                return waited
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self._note(name, bound, f"EXPIRED {state}")
        raise AssertionError(f"{name}: not satisfied within {bound}; last {state}")

    async def _intr(self, label: str) -> int:
        return await self.csr_read(label, I2C0_INTR_STATE)

    async def _wait_flag(self, name: str, bit: int, what: str) -> tuple[int, int]:
        last = [0]

        async def probe() -> tuple[bool, str]:
            last[0] = await self._intr(f"{name}_POLL")
            return bool(last[0] & bit), f"INTR_STATE=0x{last[0]:08x} {what}"

        polls = await self._poll(name, FLAG_POLLS, FLAG_STEP, probe)
        return polls, last[0]

    async def _wait_hostidle(self, name: str) -> None:
        async def probe() -> tuple[bool, str]:
            status = await self.csr_read(f"{name}_STATUS", I2C0_STATUS)
            return bool(status & I2C_STATUS_HOSTIDLE), f"STATUS=0x{status:08x}"

        await self._poll(name, IDLE_POLLS, IDLE_STEP, probe)

    async def _wait_stops(self, name: str, target: int) -> None:
        slave = self.slave

        async def probe() -> tuple[bool, str]:
            return slave.stops >= target, f"starts={slave.starts} stops={slave.stops}"

        await self._poll(name, STOP_POLLS, STOP_STEP, probe)

    async def _clear_and_check(self, label: str, bit: int, what: str) -> tuple[int, int]:
        """Write 1 to one INTR_STATE bit; return the word before and after the write."""
        before = await self._intr(f"{label}_BEFORE_CLEAR")
        assert before & bit, f"{label}: {what} reads 0 before the clear (0x{before:08x})"
        await self.csr_write(f"{label}_W1C", I2C0_INTR_STATE, bit)
        after = await self._intr(f"{label}_AFTER_CLEAR")
        assert after & bit == 0, f"{label}: {what} still reads 1 after a written 1 (0x{after:08x})"
        return before, after

    async def _bring_up_i2c0(self) -> None:
        dut = cocotb.top
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write(
            "I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_EN | I2C_WRAP_CONTROLLER_MODE
        )
        await self.arm_i2c_gpio_lsio(0, "I2C0_INTR_W1C")

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            scl_i = self._bit(dut.tb_i2c0_scl_i, "tb_i2c0_scl_i")
            return (scl, sda, scl_i) == (1, 1, 1), f"scl={scl} sda={sda} scl_i={scl_i}"

        await self._poll("bus_released", BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(THIGH, TLOW))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_INTR_ENABLE_OFF", I2C0_INTR_ENABLE, 0)
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("I2C0_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        ctrl = await self.csr_read("I2C0_CTRL_ENTRY", I2C0_CTRL)
        assert ctrl & I2C_CTRL_ENABLEHOST == 0, f"CTRL reads 0x{ctrl:08x} after it was written to 0"
        intr = await self._intr("I2C0_INTR_ENTRY")
        enable = await self.csr_read("I2C0_INTR_ENABLE_ENTRY", I2C0_INTR_ENABLE)
        assert intr & WATCHED_FLAGS == 0 and enable == 0, (
            f"INTR_STATE=0x{intr:08x} INTR_ENABLE=0x{enable:08x} after the bring-up clears"
        )
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_intr_w1c_eeprom")
        self.other = SmcI2cMasterVip(speed=1_000_000, name="smc_i2c0_intr_w1c_injector")
        self.monitor = SmcFwI2cWireMonitor("smc_i2c0_intr_w1c_wire")
        await Timer(1, unit="us")
        self._stamp("BRINGUP")

    async def _enable_host(self, label: str) -> None:
        """Re-enable the controller from scratch with the interrupt enables clear."""
        await self.csr_write(f"{label}_DISABLE", I2C0_CTRL, 0)
        await self.csr_write(f"{label}_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(f"{label}_INTR_ENABLE_OFF", I2C0_INTR_ENABLE, 0)
        await self.csr_write(
            f"{label}_EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL
        )
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, 0xFFFF_FFFF)
        events = await self.csr_read(f"{label}_EVENTS_ENTRY", I2C0_CONTROLLER_EVENTS)
        intr = await self._intr(f"{label}_INTR_ENTRY")
        assert events == 0 and intr & WATCHED_FLAGS == 0, (
            f"{label}: CONTROLLER_EVENTS=0x{events:08x} INTR_STATE=0x{intr:08x} before the leg"
        )
        await self.csr_write(f"{label}_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)

    async def _queue_write(self, label: str, address: int, last_byte: int | None) -> None:
        await self.csr_write(f"{label}_ADDR_W", I2C0_FDATA, _fdata(address << 1, I2C_FDATA_START))
        await self.csr_write(f"{label}_OFFSET", I2C0_FDATA, _fdata(OFFSET))
        if last_byte is not None:
            await self.csr_write(f"{label}_DATA", I2C0_FDATA, _fdata(last_byte, I2C_FDATA_STOP))

    async def _edge_wait(self, name: str, probe_edge) -> None:
        """Bounded level-sampled wait on clk_smc_i; ``probe_edge`` sees (previous, now)."""
        bound = f"{EDGE_WAIT_CYCLES}cyc"
        prev = None
        for cycles in range(EDGE_WAIT_CYCLES):
            await ClockCycles(cocotb.top.clk_smc_i, 1)
            now = (self._scl(), self._sda())
            if prev is not None and probe_edge(prev, now):
                self._note(name, bound, f"edge after {cycles} cycles scl={now[0]} sda={now[1]}")
                return
            prev = now
        self._note(name, bound, f"EXPIRED scl={prev[0]} sda={prev[1]}")
        raise AssertionError(f"{name}: no edge within {bound}; last scl={prev[0]} sda={prev[1]}")

    async def _inject(self, name: str, delay_ns: int, action: str, hold_ns: int) -> None:
        """Pull SCL or SDA low ``delay_ns`` after the ninth SCL rise that follows a START."""
        await self._edge_wait(f"{name}_start", lambda p, n: p[0] and n[0] and p[1] and not n[1])
        seen = [0]

        def rise(prev, now) -> bool:
            seen[0] += int(not prev[0] and bool(now[0]))
            return seen[0] == ACK_RISE

        await self._edge_wait(f"{name}_rise{ACK_RISE}", rise)
        await Timer(delay_ns, unit="ns")
        pull = self.other._pull_scl if action == "scl" else self.other._pull_sda
        pull(True)
        await Timer(hold_ns, unit="ns")
        pull(False)

    async def _recover_bus(self, label: str) -> None:
        """Clock the bus back to idle: let a target release SDA, then issue a STOP."""
        half = self.other._half_ns
        for _ in range(RECOVER_CLOCKS):
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
        scl, sda = self._scl(), self._sda()
        state = f"scl={scl} sda={sda}"
        self._note(f"{label}_bus_idle", f"{RECOVER_CLOCKS}clocks", state)
        assert scl and sda, f"{label}: the bus did not return to idle ({state})"

    async def _stop_and_recover(self, label: str) -> None:
        await self.csr_write(f"{label}_HALT", I2C0_CTRL, 0)
        await self._recover_bus(label)

    async def _cmd_complete_stop(self) -> None:
        slave = self.slave
        await self._enable_host("S2")
        before = await self._intr("S2_PRE")
        assert before & INTR_CMD_COMPLETE == 0, (
            f"CMD_COMPLETE reads 1 before the transaction (INTR_STATE=0x{before:08x})"
        )
        stops = slave.stops
        await self._queue_write("S2", EEPROM_ADDR, DATA_BYTE)
        await self._wait_stops("S2_target_stop", stops + 1)
        polls, word = await self._wait_flag("S2_cmd_complete", INTR_CMD_COMPLETE, "CMD_COMPLETE")
        mem = slave.read_mem(OFFSET, 1)[0]
        self.first = {"pre": before, "word": word, "polls": polls, "stops": slave.stops}
        before_clear, after = await self._clear_and_check("S3", INTR_CMD_COMPLETE, "CMD_COMPLETE")
        self._stamp("CMDC_STOP")
        self._chk(
            "CHK-CMDC-STOP",
            f"set: STOP of the write to 0x{EEPROM_ADDR:02x}; CMD_COMPLETE=0 before the "
            f"transaction (INTR_STATE=0x{before:08x}); observed: CMD_COMPLETE=1 after "
            f"{polls} polls once the target framed STOP #{slave.stops} (INTR_STATE=0x{word:08x}, "
            f"mem[0x{OFFSET:02x}]=0x{mem:02x}); cleared: written 1 (INTR_STATE before "
            f"0x{before_clear:08x}); checked_cleared: INTR_STATE=0x{after:08x}",
        )

    async def _cmd_complete_reassert(self) -> None:
        slave = self.slave
        await self._enable_host("S3")
        before = await self._intr("S3_PRE")
        assert before & INTR_CMD_COMPLETE == 0, (
            f"CMD_COMPLETE reads 1 before the second transaction (0x{before:08x})"
        )
        stops = slave.stops
        await self._queue_write("S3", EEPROM_ADDR, DATA_BYTE)
        await self._wait_stops("S3_target_stop", stops + 1)
        polls, word = await self._wait_flag("S3_cmd_complete", INTR_CMD_COMPLETE, "CMD_COMPLETE")
        self.second = {"pre": before, "word": word, "polls": polls, "stops": slave.stops}

    async def _cmd_complete_restart(self) -> None:
        slave = self.slave
        monitor = self.monitor
        before_clear, after = await self._clear_and_check("S4", INTR_CMD_COMPLETE, "CMD_COMPLETE")
        self._stamp("CMDC_REASSERT")
        self._chk(
            "CHK-CMDC-REASSERT",
            f"set: the second identical write to 0x{EEPROM_ADDR:02x} ended with STOP "
            f"#{self.second['stops']}; CMD_COMPLETE=0 before it began (INTR_STATE="
            f"0x{self.second['pre']:08x}); observed: CMD_COMPLETE=1 again after "
            f"{self.second['polls']} polls (INTR_STATE=0x{self.second['word']:08x}); cleared: "
            f"written 1 at the start of S4 (INTR_STATE before 0x{before_clear:08x}); "
            f"checked_cleared: INTR_STATE=0x{after:08x}",
        )
        await self._enable_host("S4")
        starts0, stops0, frames0 = monitor.starts, monitor.stops, len(monitor.frames)
        tstops = slave.stops
        await self._queue_write("S4", EEPROM_ADDR, None)
        await self.csr_write(
            "S4_ADDR_R", I2C0_FDATA, _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START)
        )
        await self.csr_write(
            "S4_READ", I2C0_FDATA, _fdata(READ_BYTES, I2C_FDATA_READB | I2C_FDATA_STOP)
        )
        seen: dict[str, object] = {}

        async def probe() -> tuple[bool, str]:
            word = await self._intr("S4_POLL")
            if not word & INTR_CMD_COMPLETE:
                return False, f"INTR_STATE=0x{word:08x} wire starts={monitor.starts - starts0}"
            frames = monitor.frames[frames0:]
            seen.update(
                word=word,
                starts=monitor.starts - starts0,
                stops=monitor.stops - stops0,
                data=sum(len(f.data) for f in frames),
                frames=" ".join(str(f) for f in frames),
            )
            return True, f"INTR_STATE=0x{word:08x}"

        polls = await self._poll("S4_cmd_complete", FLAG_POLLS, FLAG_STEP, probe)
        await self._wait_stops("S4_target_stop", tstops + 1)
        await self._wait_hostidle("S4_idle")
        self._stamp("CMDC_RS_OBS")
        self._chk(
            "CHK-CMDC-RS-OBS",
            f"at the first read with CMD_COMPLETE=1 (poll {polls}, "
            f"INTR_STATE=0x{seen['word']:08x}) "
            f"the wire monitor counted starts={seen['starts']} stops={seen['stops']} "
            f"data_bytes={seen['data']} of the write-restart-read of {READ_BYTES} bytes; "
            f"frames {seen['frames']}; final starts={monitor.starts - starts0} "
            f"stops={monitor.stops - stops0}; no expected value (not specified, measured)",
        )

    async def _sda_unstable(self) -> None:
        cfg_ns = float(self.cfg.periph_clk_period_ns)
        hold_ns = max(1, int(THIGH * cfg_ns / 2))
        await self._enable_host("S5")
        pre = await self._intr("S5_PRE")
        assert pre & INTR_SDA_UNSTABLE == 0, f"SDA_UNSTABLE reads 1 before the leg (0x{pre:08x})"
        injector = cocotb.start_soon(self._inject("S5", SDA_PULL_DELAY_NS, "sda", hold_ns))
        await self._queue_write("S5", ABSENT_ADDR, None)
        await injector
        polls, word = await self._wait_flag("S5_sda_unstable", INTR_SDA_UNSTABLE, "SDA_UNSTABLE")
        before, after = await self._clear_and_check("S5", INTR_SDA_UNSTABLE, "SDA_UNSTABLE")
        await self._stop_and_recover("S5")
        self._stamp("SDAU_W1C")
        self._chk(
            "CHK-SDAU-W1C",
            f"set: SDA pulled low {SDA_PULL_DELAY_NS} ns into the SCL high window of rise "
            f"{ACK_RISE} for {hold_ns} ns (THIGH={THIGH} x {cfg_ns:g} ns / 2); SDA_UNSTABLE=0 "
            f"before (0x{pre:08x}); observed: SDA_UNSTABLE=1 after {polls} polls "
            f"(INTR_STATE=0x{word:08x}); cleared: written 1 (before 0x{before:08x}); "
            f"checked_cleared: INTR_STATE=0x{after:08x}; "
            f"detection window per RDL only (not specified, measured)",
        )

    async def _scl_interference_leg(self, label: str) -> tuple[int, int]:
        await self._enable_host(label)
        pre = await self._intr(f"{label}_PRE")
        assert pre & INTR_SCL_INTERFERENCE == 0, (
            f"{label}: SCL_INTERFERENCE reads 1 before the leg (0x{pre:08x})"
        )
        injector = cocotb.start_soon(self._inject(label, SCL_PULL_DELAY_NS, "scl", SCL_PULL_NS))
        await self._queue_write(label, EEPROM_ADDR, DATA_BYTE)
        await injector
        polls, word = await self._wait_flag(
            f"{label}_scl_interference", INTR_SCL_INTERFERENCE, "SCL_INTERFERENCE"
        )
        return polls, word

    async def _scl_interference_clear(self) -> None:
        polls, word = await self._scl_interference_leg("S6")
        await self._wait_hostidle("S6_idle")
        before, after = await self._clear_and_check("S6", INTR_SCL_INTERFERENCE, "SCL_INTERFERENCE")
        await self._stop_and_recover("S6")
        self._stamp("SCLI_W1C")
        self._chk(
            "CHK-SCLI-W1C",
            f"set: SCL pulled low {SCL_PULL_NS} ns, {SCL_PULL_DELAY_NS} ns after rise "
            f"{ACK_RISE}, INTR_ENABLE=0; observed: SCL_INTERFERENCE=1 after {polls} polls "
            f"(INTR_STATE=0x{word:08x}); cleared: written 1 (before 0x{before:08x}); "
            f"checked_cleared: INTR_STATE=0x{after:08x}; "
            f"detection window per RDL only (not specified, measured)",
        )

    async def _scl_interference_gate(self) -> None:
        polls, word = await self._scl_interference_leg("S7")
        await self._wait_hostidle("S7_idle")
        held = await self._intr("S7_HELD")
        assert held & INTR_SCL_INTERFERENCE, f"SCL_INTERFERENCE dropped by itself (0x{held:08x})"
        first = self._irq()
        await ClockCycles(cocotb.top.clk_smc_i, IRQ_SAMPLE_GAP_CYCLES)
        second = self._irq()
        assert (first, second) == (0, 0), (
            f"tb_i2c_irq reads 0b{first:03b} then 0b{second:03b} with INTR_ENABLE.SCL_INTERFERENCE "
            f"clear and INTR_STATE=0x{held:08x}"
        )
        await self.csr_write("S7_ENABLE", I2C0_INTR_ENABLE, ENABLE_SCL_INTERFERENCE)
        enable_rb = await self.csr_read("S7_ENABLE_RB", I2C0_INTR_ENABLE)
        assert enable_rb & ENABLE_SCL_INTERFERENCE, f"INTR_ENABLE reads 0x{enable_rb:08x}"

        async def raised() -> tuple[bool, str]:
            irq = self._irq()
            assert irq & 0b110 == 0, f"tb_i2c_irq reads 0b{irq:03b}; [2:1] must stay 0"
            return bool(irq & 1), f"tb_i2c_irq=0b{irq:03b}"

        raise_polls = await self._poll("S7_irq_raised", IRQ_POLLS, IRQ_STEP, raised)
        raised_irq = self._irq()
        before, after = await self._clear_and_check("S7", INTR_SCL_INTERFERENCE, "SCL_INTERFERENCE")

        async def dropped() -> tuple[bool, str]:
            irq = self._irq()
            return irq == 0, f"tb_i2c_irq=0b{irq:03b}"

        drop_polls = await self._poll("S7_irq_dropped", IRQ_POLLS, IRQ_STEP, dropped)
        await self._stop_and_recover("S7")
        self._stamp("SCLI_GATE")
        self._chk(
            "CHK-SCLI-GATE",
            f"set: the SCL pull with INTR_ENABLE=0 (INTR_STATE=0x{held:08x} after {polls} "
            f"polls); observed: tb_i2c_irq=0b{first:03b} and 0b{second:03b} "
            f"{IRQ_SAMPLE_GAP_CYCLES} cycles apart, then 0b{raised_irq:03b} {raise_polls} polls "
            f"after INTR_ENABLE=0x{enable_rb:08x} with [2:1]=0; cleared: written 1 (before "
            f"0x{before:08x}); checked_cleared: tb_i2c_irq=0b000 after {drop_polls} polls, "
            f"INTR_STATE=0x{after:08x}",
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
        own = [(name, bound, state) for name, (bound, state) in self.waits.items()]
        waits = inherited + own + [axi]
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
        await self._bring_up_i2c0()
        await self._cmd_complete_stop()
        await self._cmd_complete_reassert()
        await self._cmd_complete_restart()
        await self._sda_unstable()
        await self._scl_interference_clear()
        await self._scl_interference_gate()
        self._emit_timeout_paths()
        self._emit_nonvac()
