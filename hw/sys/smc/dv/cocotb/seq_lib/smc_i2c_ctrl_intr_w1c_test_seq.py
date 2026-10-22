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

Instances 1 and 2 then join the same open-drain bus (`+smc_i2c_shared_bus`), which also joins the
SMBus alert and suspend lines of all three instances. On each of them `INTR_TEST` sets every write
1 pulse field of `INTR_STATE` and a partial write 1 clears only the written bits; each RW
`INTR_TEST` field holds its status bit through a written 1 until `INTR_TEST` is written 0; and
`CMD_COMPLETE` reaches `tb_i2c_irq` bit k only while `INTR_ENABLE` is set. As controller each
instance halts on an absent-address NACK, passes it with `FDATA.NAKOK`, and after an unserviced
NACK times out clears `CONTROLLER_EVENTS` one flag at a time. As target, with the software TX
stretch enabled, each instance raises `TX_PENDING` and `START_DETECT` on a READ from the other
instance, sends its byte only after the written 1, and records the STOP. A bench SCL hold sets the
target bus timeout; a simultaneous READ from I2C0 and the other instance logs the target
`ARBITRATION_LOST` flag, and a STOP sent before the target NACK logs `UNEXP_STOP` (neither value is
specified, both measured). I2C0 is the second party on the shared SMBus lines: it holds the
suspend line as a controller and the alert line as a target, since the bench drives those pads
only from the three instances' own outputs.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_TX_STRETCH_CTRL_EN,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_STATE_SMBALERT,
    I2C_INTR_STATE_TX_STRETCH,
    I2C_NACK_HANDLER_TIMEOUT_EN,
    I2C_SMBUS_CTRL_SMBALERT,
    I2C_SMBUS_CTRL_SMBSUS,
    I2C_SMBUS_STATUS_SMBALERT,
    I2C_SMBUS_STATUS_SMBSUS,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_RXEMPTY,
    I2C_TIMEOUT_CTRL_EN,
    I2C_TIMEOUT_MODE_BUS,
    I2C_WRAP_CONTROLLER_MODE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_HOST_SMBUS,
    I2C_WRAP_CTRL_TARGET,
    I2C_WRAP_EN,
    acq_abyte,
    acq_signal,
)
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
from .smc_i2c_target_smbus_test_seq import _pack_target_id


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

INSTANCES12 = (1, 2)
TARGET_ADDR = {1: 0x3D, 2: 0x3E}
ARB_ADDR = {1: 0x3C, 2: 0x3F}
HOLDER_TARGET_ADDR = 0x2A
TX_BYTE = 0xA7
TX_FILL_BYTE = 0xFF
ALERT_WRITE_BYTE = 0xC5
NACK_DATA_BYTE = 0x5A

INTR_TEST_W1P = 0x000FE3E8
INTR_CLEAR_A = 0x000AA2A0
INTR_CLEAR_B = 0x00054148
INTR_TEST_RW_FIELDS = (
    (0, "FMT_THRESHOLD"),
    (1, "RX_THRESHOLD"),
    (2, "ACQ_THRESHOLD"),
    (4, "CONTROLLER_HALT"),
    (10, "TX_STRETCH"),
    (11, "TX_THRESHOLD"),
    (12, "ACQ_STRETCH"),
)
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
INTR_UNEXP_STOP = _i2c_u32("I2C__INTR_STATE__UNEXP_STOP_bm")
ENABLE_CMD_COMPLETE = _i2c_u32("I2C__INTR_ENABLE__CMD_COMPLETE_bm")
FDATA_NAKOK = _i2c_u32("I2C__FDATA__NAKOK_bm")
FDATA_RCONT = _i2c_u32("I2C__FDATA__RCONT_bm")
EV_NACK = I2C_CONTROLLER_EVENTS_NACK
EV_UNHANDLED = I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT
EV_ARB_LOST = _i2c_u32("I2C__CONTROLLER_EVENTS__ARBITRATION_LOST_bm")
TGT_TX_PENDING = _i2c_u32("I2C__TARGET_EVENTS__TX_PENDING_bm")
TGT_BUS_TIMEOUT = _i2c_u32("I2C__TARGET_EVENTS__BUS_TIMEOUT_bm")
TGT_ARB_LOST = _i2c_u32("I2C__TARGET_EVENTS__ARBITRATION_LOST_bm")
TGT_START = _i2c_u32("I2C__TARGET_EVENTS__START_DETECT_bm")
TGT_STOP = _i2c_u32("I2C__TARGET_EVENTS__STOP_DETECT_bm")
TGT_EVENTS_ALL = TGT_TX_PENDING | TGT_BUS_TIMEOUT | TGT_ARB_LOST | TGT_START | TGT_STOP
FIFO_CTRL_ALL = I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST

NACK_TIMEOUT_VAL = 256
NACK_STOP_ALLOWANCE_NS = 5_000
BUS_TIMEOUT_NS = 8_000
VIP_SPEED = 1_000_000
VIP_SCL_TIMEOUT_NS = 200_000

EVENT_POLLS = 600
EVENT_STEP = 25
DONE_POLLS = 600
DONE_STEP = 25
RX_POLLS = 600
RX_STEP = 25
PAD_POLLS = 400
PAD_STEP = 4
SMBUS_POLLS = 400
SMBUS_STEP = 25
ACQ_DRAIN_MAX = 16

FENCE_ORDER = [
    "BRINGUP",
    "CMDC_STOP",
    "CMDC_REASSERT",
    "CMDC_RS_OBS",
    "SDAU_W1C",
    "SCLI_W1C",
    "SCLI_GATE",
    "I2C12_INTR_TEST_W1C",
    "I2C12_RW_HOLD",
    "I2C12_IRQ_GATE",
    "I2C12_CTRL_NACK",
    "I2C12_CTRL_PARTIAL",
    "I2C12_TGT_TX_PENDING",
    "I2C12_TGT_ABNORMAL",
    "I2C12_UNEXP_STOP",
    "I2C12_SMBSUS",
    "I2C12_SMBALERT",
]
CHECKER_AFTER = {
    "CHK-CMDC-STOP": "CMDC_STOP",
    "CHK-CMDC-REASSERT": "CMDC_REASSERT",
    "CHK-CMDC-RS-OBS": "CMDC_RS_OBS",
    "CHK-SDAU-W1C": "SDAU_W1C",
    "CHK-SCLI-W1C": "SCLI_W1C",
    "CHK-SCLI-GATE": "SCLI_GATE",
    "CHK-I2C12-INTR-TEST-W1C": "I2C12_INTR_TEST_W1C",
    "CHK-I2C12-INTR-TEST-RW-HOLD": "I2C12_RW_HOLD",
    "CHK-I2C12-IRQ-LINE-GATE": "I2C12_IRQ_GATE",
    "CHK-I2C12-CTRL-NACK-HALT": "I2C12_CTRL_NACK",
    "CHK-I2C12-CTRL-EVENTS-PARTIAL": "I2C12_CTRL_PARTIAL",
    "CHK-I2C12-TGT-TX-PENDING": "I2C12_TGT_TX_PENDING",
    "CHK-I2C12-TGT-ABNORMAL-END": "I2C12_TGT_ABNORMAL",
    "CHK-I2C12-UNEXP-STOP": "I2C12_UNEXP_STOP",
    "CHK-I2C12-SMBSUS": "I2C12_SMBSUS",
    "CHK-I2C12-SMBALERT": "I2C12_SMBALERT",
}


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


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
        self.bench: SmcI2cMasterVip | None = None
        self.setup_row = ""

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

    async def _recover_bus(self, label: str, vip: SmcI2cMasterVip | None = None) -> None:
        """Clock the bus back to idle: let a target release SDA, then issue a STOP."""
        vip = vip or self.other
        half = vip._half_ns
        for _ in range(RECOVER_CLOCKS):
            if self._sda():
                break
            vip._pull_scl(True)
            await Timer(half, unit="ns")
            vip._pull_scl(False)
            await Timer(half, unit="ns")
        vip._pull_sda(True)
        await Timer(half, unit="ns")
        vip._pull_scl(False)
        await Timer(half, unit="ns")
        vip._pull_sda(False)
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

    # ---- I2C1 / I2C2 legs on the shared bus -------------------------------------------

    async def _rd(self, label: str, register: str, idx: int) -> int:
        return await self.csr_read(f"I2C{idx}_{label}", _reg(register, idx))

    async def _wr(self, label: str, register: str, idx: int, value: int) -> None:
        await self.csr_write(f"I2C{idx}_{label}", _reg(register, idx), value)

    def _pad(self, name: str) -> int:
        return self._bit(getattr(cocotb.top, name), name)

    def _pulls(self, line: str) -> str:
        """The three instances' open-drain pull nets of one SMBus line, as ``i0i1i2``."""
        return "".join(str(self._pad(f"tb_i2c{i}_{line}_dut_low")) for i in (0, 1, 2))

    async def _wait_pad(self, name: str, line: str, want: int) -> str:
        """Bounded poll of the shared SMBus ``line`` pad net until it reads ``want``."""
        net = f"tb_i2c_{line}"

        async def probe() -> tuple[bool, str]:
            level = self._pad(net)
            return level == want, f"{net}={level} pulls(i0i1i2)={self._pulls(line)}"

        await self._poll(name, PAD_POLLS, PAD_STEP, probe)
        return f"{net}={self._pad(net)} pulls(i0i1i2)={self._pulls(line)}"

    async def _wait_field(
        self, name: str, register: str, idx: int, mask: int, want: int, polls: int, step: int
    ) -> int:
        """Bounded poll until ``register`` of instance ``idx`` masked by ``mask`` reads ``want``."""
        last = [0]

        async def probe() -> tuple[bool, str]:
            last[0] = await self._rd(f"{name}_POLL", register, idx)
            return last[0] & mask == want, f"{register}=0x{last[0]:08x}"

        await self._poll(name, polls, step, probe)
        return last[0]

    async def _wait_until(self, name: str, bound_ns: int, step: int, probe) -> int:
        """Run ``probe`` until it holds or ``bound_ns`` of sim time passed; return elapsed ns."""
        start = int(get_sim_time("ns"))
        bound = f"{bound_ns}ns"
        while True:
            done, state = await probe()
            elapsed = int(get_sim_time("ns")) - start
            if done:
                self._note(name, bound, f"{state} after {elapsed}ns")
                return elapsed
            if elapsed >= bound_ns:
                self._note(name, bound, f"EXPIRED {state}")
                raise AssertionError(f"{name}: not satisfied within {bound}; last {state}")
            await ClockCycles(cocotb.top.clk_smc_i, step)

    async def _wait_bus_idle(self, name: str) -> None:
        async def probe() -> tuple[bool, str]:
            scl, sda = self._scl(), self._sda()
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_RELEASE_POLLS, BUS_RELEASE_STEP, probe)

    async def _program_timing(self, idx: int) -> None:
        for register, value in (
            ("TIMING0", _pack_timing0(THIGH, TLOW)),
            ("TIMING1", _pack_timing1(2, 2)),
            ("TIMING2", _pack_timing2(5, 4)),
            ("TIMING3", _pack_timing3(2, 5)),
            ("TIMING4", _pack_timing4(4, 5)),
        ):
            await self._wr(register, register, idx, value)

    async def _off(self, idx: int, label: str) -> None:
        """Disable the core of instance ``idx`` and clear its FIFOs, events and interrupts."""
        await self._wr(f"{label}_CTRL_OFF", "CTRL", idx, 0)
        await self._wr(f"{label}_SMBUS_CTRL_OFF", "SMBUS_CTRL", idx, 0)
        await self._wr(f"{label}_TIMEOUT_OFF", "TIMEOUT_CTRL", idx, 0)
        await self._wr(f"{label}_FIFO_RST", "FIFO_CTRL", idx, FIFO_CTRL_ALL)
        await self._wr(f"{label}_EVENTS_CLR", "CONTROLLER_EVENTS", idx, I2C_CONTROLLER_EVENTS_ALL)
        await self._wr(f"{label}_TGT_EVENTS_CLR", "TARGET_EVENTS", idx, TGT_EVENTS_ALL)
        await self._wr(f"{label}_INTR_CLR", "INTR_STATE", idx, 0xFFFF_FFFF)

    async def _controller(self, idx: int, label: str, enable: bool = True) -> None:
        """Make instance ``idx`` a controller with clean FIFOs, events and interrupts."""
        await self._off(idx, label)
        await self.csr_write(f"I2C{idx}_{label}_WRAP_HOST", _wrap(idx), I2C_WRAP_CTRL_HOST)
        if enable:
            await self._wr(f"{label}_ENABLEHOST", "CTRL", idx, I2C_CTRL_ENABLEHOST)

    async def _target(self, idx: int, label: str, ctrl: int, tx: tuple[int, ...] = ()) -> None:
        """Make instance ``idx`` a target at TARGET_ADDR / ARB_ADDR with ``tx`` in its TX FIFO."""
        await self._off(idx, label)
        await self.csr_write(f"I2C{idx}_{label}_WRAP_TGT", _wrap(idx), I2C_WRAP_CTRL_TARGET)
        await self._wr(
            f"{label}_TARGET_ID",
            "TARGET_ID",
            idx,
            _pack_target_id(TARGET_ADDR[idx], 0x7F, ARB_ADDR[idx], 0x7F),
        )
        await self._wr(f"{label}_CTRL_TGT", "CTRL", idx, I2C_CTRL_ENABLETARGET | ctrl)
        for i, byte in enumerate(tx):
            await self._wr(f"{label}_TXDATA{i}", "TXDATA", idx, byte)
        await self._wr(f"{label}_TGT_EVENTS_CLR2", "TARGET_EVENTS", idx, TGT_EVENTS_ALL)
        await self._wr(f"{label}_INTR_CLR2", "INTR_STATE", idx, 0xFFFF_FFFF)

    async def _queue(self, idx: int, label: str, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self._wr(f"{label}_FDATA{i}", "FDATA", idx, word)

    def _frames(self, base: int) -> str:
        return " ".join(str(f) for f in self.monitor.frames[base:]) or "none"

    async def _wait_done(self, idx: int, label: str, stops_base: int) -> str:
        """Bounded poll until controller ``idx`` is idle with an empty FIFO after a wire STOP."""
        status = [0]
        want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY

        async def probe() -> tuple[bool, str]:
            status[0] = await self._rd(f"{label}_STATUS", "STATUS", idx)
            done = status[0] & want == want and self.monitor.stops > stops_base
            return done, f"STATUS=0x{status[0]:08x} wire stops={self.monitor.stops - stops_base}"

        await self._poll(f"{label}_done", DONE_POLLS, DONE_STEP, probe)
        return f"STATUS=0x{status[0]:08x}"

    async def _drain_acq(self, idx: int, label: str) -> str:
        """Pop the target ACQ FIFO until ACQEMPTY; return the entries as ``abyte/signal``."""
        rows = []
        for i in range(ACQ_DRAIN_MAX + 1):
            status = await self._rd(f"{label}_ACQ_STATUS{i}", "STATUS", idx)
            if status & I2C_STATUS_ACQEMPTY:
                self._note(f"{label}_acq_drain", f"{ACQ_DRAIN_MAX} pops", f"{len(rows)} popped")
                return " ".join(rows) or "empty"
            word = await self._rd(f"{label}_ACQDATA{i}", "ACQDATA", idx)
            rows.append(f"0x{acq_abyte(word):02x}/{acq_signal(word)}")
        self._note(f"{label}_acq_drain", f"{ACQ_DRAIN_MAX} pops", f"EXPIRED {rows}")
        raise AssertionError(f"{label}: ACQ FIFO not empty after {ACQ_DRAIN_MAX} pops ({rows})")

    async def _leg_end(self, label: str, instances: tuple[int, ...]) -> None:
        for idx in instances:
            await self._off(idx, label)
        await self._wait_bus_idle(f"{label}_bus_released")

    async def _i2c12_setup(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "the I2C1/I2C2 legs of smc_i2c_ctrl_intr_w1c_test need +smc_i2c_shared_bus"
        )
        await self.csr_write("I2C0_INTR_ENABLE_OFF_S1", I2C0_INTR_ENABLE, 0)
        for idx in INSTANCES12:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_INTR_W1C")
        await self._wait_bus_idle("S1_bus_released")
        for idx in INSTANCES12:
            await self._program_timing(idx)
            await self._wr("S1_OVRD_OFF", "OVRD", idx, I2C_OVRD_OFF)
            await self._wr("S1_INTR_ENABLE_OFF", "INTR_ENABLE", idx, 0)
            await self.csr_write(f"I2C{idx}_S1_WRAP_OFF", _wrap(idx), 0)
            await self._off(idx, "S1")
        rows = []
        for idx in INSTANCES12:
            intr = await self._rd("S1_INTR_ENTRY", "INTR_STATE", idx)
            assert intr == 0, f"S1: I2C{idx} INTR_STATE=0x{intr:08x} after the clears"
            rows.append(f"I2C{idx} INTR_STATE=0x{intr:08x}")
        irq = self._irq()
        assert irq & 0b110 == 0, f"S1: tb_i2c_irq=0b{irq:03b}, bits 2:1 must read 0"
        self.bench = SmcI2cMasterVip(
            speed=VIP_SPEED, name="smc_i2c12_intr_w1c_bench", scl_timeout_ns=VIP_SCL_TIMEOUT_NS
        )
        self.setup_row = f"{'; '.join(rows)}; tb_i2c_irq=0b{irq:03b}"

    async def _s2_intr_test_w1c(self) -> None:
        rows = []
        for k in INSTANCES12:
            other = 3 - k
            await self._wr("S2_INTR_TEST", "INTR_TEST", k, INTR_TEST_W1P)
            forced = await self._rd("S2_FORCED", "INTR_STATE", k)
            other_word = await self._rd("S2_OTHER", "INTR_STATE", other)
            assert forced & INTR_TEST_W1P == INTR_TEST_W1P, (
                f"S2 I2C{k}: INTR_STATE=0x{forced:08x} after INTR_TEST=0x{INTR_TEST_W1P:08x}"
            )
            assert other_word & INTR_TEST_W1P == 0, (
                f"S2 I2C{k}: I2C{other} INTR_STATE=0x{other_word:08x} after the I2C{k} INTR_TEST"
            )
            await self._wr("S2_CLEAR_A", "INTR_STATE", k, INTR_CLEAR_A)
            part = await self._rd("S2_PART", "INTR_STATE", k)
            assert part & INTR_TEST_W1P == INTR_CLEAR_B, (
                f"S2 I2C{k}: INTR_STATE=0x{part:08x} after the written 0x{INTR_CLEAR_A:08x}"
            )
            await self._wr("S2_CLEAR_B", "INTR_STATE", k, INTR_CLEAR_B)
            final = await self._rd("S2_FINAL", "INTR_STATE", k)
            assert final & INTR_TEST_W1P == 0, (
                f"S2 I2C{k}: INTR_STATE=0x{final:08x} after the written 0x{INTR_CLEAR_B:08x}"
            )
            rows.append(
                f"I2C{k}: forced 0x{forced:08x} (I2C{other} 0x{other_word:08x}) -> "
                f"0x{part:08x} -> 0x{final:08x}"
            )
        self._stamp("I2C12_INTR_TEST_W1C")
        self._chk(
            "CHK-I2C12-INTR-TEST-W1C",
            f"set: INTR_TEST=0x{INTR_TEST_W1P:08x} with INTR_ENABLE=0; observed: INTR_STATE & "
            f"0x{INTR_TEST_W1P:05x} == 0x{INTR_TEST_W1P:05x} and the other instance 0; cleared: "
            f"0x{INTR_CLEAR_A:08x} then 0x{INTR_CLEAR_B:08x}; checked_cleared: masked reads "
            f"0x{INTR_CLEAR_B:05x} then 0x00000; entry {self.setup_row}; {'; '.join(rows)}",
        )

    async def _s3_rw_hold(self) -> None:
        rows = []
        for k in INSTANCES12:
            for bit, field in INTR_TEST_RW_FIELDS:
                mask = 1 << bit
                await self._wr(f"S3_{field}_TEST", "INTR_TEST", k, mask)
                forced = await self._rd(f"S3_{field}_FORCED", "INTR_STATE", k)
                await self._wr(f"S3_{field}_W1", "INTR_STATE", k, mask)
                held = await self._rd(f"S3_{field}_HELD", "INTR_STATE", k)
                await self._wr(f"S3_{field}_RELEASE", "INTR_TEST", k, 0)
                released = await self._rd(f"S3_{field}_RELEASED", "INTR_STATE", k)
                got = tuple(int(bool(w & mask)) for w in (forced, held, released))
                assert got == (1, 1, 0), (
                    f"S3 I2C{k} {field}: INTR_STATE bit {bit} reads {got} after INTR_TEST=1, a "
                    f"written 1 and INTR_TEST=0 (0x{forced:08x} 0x{held:08x} 0x{released:08x})"
                )
                rows.append(f"I2C{k}.{field}[{bit}]=1,1,0")
        self._stamp("I2C12_RW_HOLD")
        self._chk(
            "CHK-I2C12-INTR-TEST-RW-HOLD",
            f"set: INTR_TEST=1<<f; observed: INTR_STATE bit f reads 1 and still 1 after the "
            f"written 1<<f; cleared: INTR_TEST=0; checked_cleared: bit f reads 0; {' '.join(rows)}",
        )

    async def _s4_irq_gate(self) -> None:
        rows = []
        for k in INSTANCES12:
            await self._wr("S4_INTR_TEST", "INTR_TEST", k, INTR_CMD_COMPLETE)
            word = await self._rd("S4_FORCED", "INTR_STATE", k)
            assert word & INTR_CMD_COMPLETE, f"S4 I2C{k}: CMD_COMPLETE reads 0 (0x{word:08x})"
            first = self._irq()
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SAMPLE_GAP_CYCLES)
            second = self._irq()
            assert (first, second) == (0, 0), (
                f"S4 I2C{k}: tb_i2c_irq 0b{first:03b} then 0b{second:03b} with INTR_ENABLE=0"
            )
            await self._wr("S4_ENABLE", "INTR_ENABLE", k, ENABLE_CMD_COMPLETE)
            want = 1 << k

            async def raised(want=want) -> tuple[bool, str]:
                irq = self._irq()
                assert irq & ~want == 0, f"tb_i2c_irq=0b{irq:03b}; only bit {want:03b} may rise"
                return irq == want, f"tb_i2c_irq=0b{irq:03b}"

            up = await self._poll(f"S4_I{k}_irq_raised", IRQ_POLLS, IRQ_STEP, raised)
            high = self._irq()
            await self._wr("S4_CLEAR", "INTR_STATE", k, INTR_CMD_COMPLETE)

            async def dropped() -> tuple[bool, str]:
                irq = self._irq()
                return irq == 0, f"tb_i2c_irq=0b{irq:03b}"

            down = await self._poll(f"S4_I{k}_irq_dropped", IRQ_POLLS, IRQ_STEP, dropped)
            await self._wr("S4_DISABLE", "INTR_ENABLE", k, 0)
            rows.append(
                f"I2C{k}: 0b{first:03b} 0b{second:03b} -> enable -> 0b{high:03b} after {up} "
                f"polls -> clear -> 0b000 after {down} polls"
            )
        self._stamp("I2C12_IRQ_GATE")
        self._chk(
            "CHK-I2C12-IRQ-LINE-GATE",
            f"set: INTR_TEST=0x{INTR_CMD_COMPLETE:x}; observed: tb_i2c_irq 0b000 at two samples "
            f"{IRQ_SAMPLE_GAP_CYCLES} cycles apart with INTR_ENABLE=0, then exactly 1<<k after "
            f"INTR_ENABLE=0x{ENABLE_CMD_COMPLETE:x}; cleared: INTR_STATE written "
            f"0x{INTR_CMD_COMPLETE:x}; checked_cleared: 0b000; {'; '.join(rows)}",
        )

    async def _s5_ctrl_nack(self) -> None:
        rows = []
        for k in INSTANCES12:
            label = f"S5_I{k}"
            await self._controller(k, label)
            base = len(self.monitor.frames)
            await self._queue(
                k,
                label,
                [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START), _fdata(NACK_DATA_BYTE, I2C_FDATA_STOP)],
            )
            events = await self._wait_field(
                f"{label}_nack", "CONTROLLER_EVENTS", k, EV_NACK, EV_NACK, EVENT_POLLS, EVENT_STEP
            )
            intr = await self._rd(f"{label}_INTR", "INTR_STATE", k)
            status = await self._rd(f"{label}_STATUS", "STATUS", k)
            assert events == EV_NACK and intr & INTR_CONTROLLER_HALT, (
                f"{label}: CONTROLLER_EVENTS=0x{events:08x} INTR_STATE=0x{intr:08x}"
            )
            assert status & I2C_STATUS_FMTEMPTY == 0, (
                f"{label}: STATUS=0x{status:08x}; the second entry was issued after the NACK"
            )
            await self._wr(f"{label}_FMTRST", "FIFO_CTRL", k, I2C_FIFO_CTRL_RXRST_FMTRST)
            await self._wr(f"{label}_NACK_W1C", "CONTROLLER_EVENTS", k, EV_NACK)
            ev_clr = await self._rd(f"{label}_EVENTS_CLR", "CONTROLLER_EVENTS", k)
            intr_clr = await self._rd(f"{label}_INTR_CLR", "INTR_STATE", k)
            assert ev_clr == 0 and intr_clr & INTR_CONTROLLER_HALT == 0, (
                f"{label}: after the written 0x1 CONTROLLER_EVENTS=0x{ev_clr:08x} "
                f"INTR_STATE=0x{intr_clr:08x}"
            )
            await self._wr(f"{label}_CMDC_W1C", "INTR_STATE", k, INTR_CMD_COMPLETE)
            await self._queue(
                k,
                f"{label}_NAKOK",
                [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START | I2C_FDATA_STOP | FDATA_NAKOK)],
            )
            done = await self._wait_field(
                f"{label}_cmd_complete",
                "INTR_STATE",
                k,
                INTR_CMD_COMPLETE,
                INTR_CMD_COMPLETE,
                EVENT_POLLS,
                EVENT_STEP,
            )
            idle = await self._wait_field(
                f"{label}_hostidle",
                "STATUS",
                k,
                I2C_STATUS_HOSTIDLE,
                I2C_STATUS_HOSTIDLE,
                EVENT_POLLS,
                EVENT_STEP,
            )
            ev_ok = await self._rd(f"{label}_NAKOK_EVENTS", "CONTROLLER_EVENTS", k)
            intr_ok = await self._rd(f"{label}_NAKOK_INTR", "INTR_STATE", k)
            assert ev_ok == 0 and intr_ok & INTR_CONTROLLER_HALT == 0, (
                f"{label}: NAKOK byte left CONTROLLER_EVENTS=0x{ev_ok:08x} INTR_STATE=0x{intr_ok:08x}"
            )
            frames = self._frames(base)
            await self._leg_end(label, (k,))
            rows.append(
                f"I2C{k}: events=0x{events:08x} INTR_STATE=0x{intr:08x} STATUS=0x{status:08x} -> "
                f"written 0x1 after FMTRST -> events=0x{ev_clr:08x} INTR_STATE=0x{intr_clr:08x}; "
                f"NAKOK -> INTR_STATE=0x{done:08x} STATUS=0x{idle:08x} events=0x{ev_ok:08x}; "
                f"wire {frames}"
            )
        self._stamp("I2C12_CTRL_NACK")
        self._chk(
            "CHK-I2C12-CTRL-NACK-HALT",
            f"set: target NACK of 0x{ABSENT_ADDR:02x}; observed: CONTROLLER_EVENTS=0x1, "
            f"CONTROLLER_HALT=1, FMTEMPTY=0; cleared: CONTROLLER_EVENTS written 0x1; "
            f"checked_cleared: 0x0 and CONTROLLER_HALT=0; NAKOK leaves 0x0 with CMD_COMPLETE=1 "
            f"and HOSTIDLE=1; {'; '.join(rows)}",
        )

    async def _s6_ctrl_partial(self) -> None:
        rows = []
        periph_ns = float(self.cfg.periph_clk_period_ns)
        bound_ns = int(NACK_TIMEOUT_VAL * periph_ns) + NACK_STOP_ALLOWANCE_NS
        smc_ns = float(self.cfg.smc_clk_period_ns)
        for k in INSTANCES12:
            label = f"S6_I{k}"
            await self._controller(k, label)
            await self._wr(
                f"{label}_NACK_TIMEOUT",
                "HOST_NACK_HANDLER_TIMEOUT",
                k,
                I2C_NACK_HANDLER_TIMEOUT_EN | NACK_TIMEOUT_VAL,
            )
            stops = self.monitor.stops
            await self._queue(
                k,
                label,
                [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START), _fdata(NACK_DATA_BYTE, I2C_FDATA_STOP)],
            )
            await self._wait_field(
                f"{label}_nack", "CONTROLLER_EVENTS", k, EV_NACK, EV_NACK, EVENT_POLLS, 1
            )
            seen = {"events": 0}

            async def probe(k=k, label=label, stops=stops, seen=seen) -> tuple[bool, str]:
                seen["events"] = await self._rd(f"{label}_EVENTS_POLL", "CONTROLLER_EVENTS", k)
                wire = self.monitor.stops - stops
                done = bool(seen["events"] & EV_UNHANDLED) and wire > 0
                return done, f"CONTROLLER_EVENTS=0x{seen['events']:08x} wire stops={wire}"

            elapsed = await self._wait_until(f"{label}_timeout_stop", bound_ns, 8, probe)
            events = await self._rd(f"{label}_EVENTS", "CONTROLLER_EVENTS", k)
            assert events == EV_NACK | EV_UNHANDLED, (
                f"{label}: CONTROLLER_EVENTS=0x{events:08x} after the unserviced NACK"
            )
            await self._wr(f"{label}_FMTRST", "FIFO_CTRL", k, I2C_FIFO_CTRL_RXRST_FMTRST)
            await self._wr(f"{label}_W1C_NACK", "CONTROLLER_EVENTS", k, EV_NACK)
            ev1 = await self._rd(f"{label}_EVENTS_1", "CONTROLLER_EVENTS", k)
            intr1 = await self._rd(f"{label}_INTR_1", "INTR_STATE", k)
            assert ev1 == EV_UNHANDLED and intr1 & INTR_CONTROLLER_HALT, (
                f"{label}: after the written 0x1 CONTROLLER_EVENTS=0x{ev1:08x} "
                f"INTR_STATE=0x{intr1:08x}"
            )
            await self._wr(f"{label}_W1C_UNHANDLED", "CONTROLLER_EVENTS", k, EV_UNHANDLED)
            ev2 = await self._rd(f"{label}_EVENTS_2", "CONTROLLER_EVENTS", k)
            intr2 = await self._rd(f"{label}_INTR_2", "INTR_STATE", k)
            assert ev2 == 0 and intr2 & INTR_CONTROLLER_HALT == 0, (
                f"{label}: after the written 0x2 CONTROLLER_EVENTS=0x{ev2:08x} "
                f"INTR_STATE=0x{intr2:08x}"
            )
            await self._wr(f"{label}_NACK_TIMEOUT_OFF", "HOST_NACK_HANDLER_TIMEOUT", k, 0)
            await self._leg_end(label, (k,))
            rows.append(
                f"I2C{k}: events=0x{events:08x} with the wire STOP {elapsed} ns "
                f"({int(elapsed / smc_ns)} clk_smc_i cycles) after the NACK read, bound "
                f"{bound_ns} ns; written 0x1 -> events=0x{ev1:08x} INTR_STATE=0x{intr1:08x}; "
                f"written 0x2 -> events=0x{ev2:08x} INTR_STATE=0x{intr2:08x}"
            )
        self._stamp("I2C12_CTRL_PARTIAL")
        self._chk(
            "CHK-I2C12-CTRL-EVENTS-PARTIAL",
            f"set: HOST_NACK_HANDLER_TIMEOUT EN=1 VAL={NACK_TIMEOUT_VAL} and the NACK of "
            f"0x{ABSENT_ADDR:02x} unserviced; observed: CONTROLLER_EVENTS=0x3 and a wire STOP "
            f"within V x {periph_ns:g} ns + {NACK_STOP_ALLOWANCE_NS} ns; cleared: 0x1 then 0x2; "
            f"checked_cleared: 0x2 with CONTROLLER_HALT=1, then 0x0 with CONTROLLER_HALT=0; "
            f"{'; '.join(rows)}",
        )

    async def _s7_tgt_tx_pending(self) -> None:
        rows = []
        for k in INSTANCES12:
            c = 3 - k
            label = f"S7_T{k}"
            await self._target(k, label, I2C_CTRL_TX_STRETCH_CTRL_EN, (TX_BYTE,))
            await self._controller(c, f"{label}_C{c}")
            stops = self.monitor.stops
            base = len(self.monitor.frames)
            await self._queue(
                c,
                label,
                [
                    _fdata((TARGET_ADDR[k] << 1) | 1, I2C_FDATA_START),
                    _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP),
                ],
            )
            events = await self._wait_field(
                f"{label}_tx_pending",
                "TARGET_EVENTS",
                k,
                TGT_TX_PENDING,
                TGT_TX_PENDING,
                EVENT_POLLS,
                EVENT_STEP,
            )
            intr = await self._rd(f"{label}_INTR", "INTR_STATE", k)
            rx = await self._rd(f"{label}_C_STATUS", "STATUS", c)
            assert events == TGT_TX_PENDING | TGT_START, (
                f"{label}: TARGET_EVENTS=0x{events:08x} on the READ address"
            )
            assert intr & I2C_INTR_STATE_TX_STRETCH, f"{label}: TX_STRETCH reads 0 (0x{intr:08x})"
            assert rx & I2C_STATUS_RXEMPTY, (
                f"{label}: controller STATUS=0x{rx:08x}; RDATA filled before TX_PENDING cleared"
            )
            await self._wr(f"{label}_W1C_TX_PENDING", "TARGET_EVENTS", k, TGT_TX_PENDING)
            await self._wait_field(
                f"{label}_rdata", "STATUS", c, I2C_STATUS_RXEMPTY, 0, RX_POLLS, RX_STEP
            )
            rdata = (await self._rd(f"{label}_RDATA", "RDATA", c)) & 0xFF
            assert rdata == TX_BYTE, f"{label}: RDATA=0x{rdata:02x}, expected 0x{TX_BYTE:02x}"

            async def stopped(stops=stops) -> tuple[bool, str]:
                return self.monitor.stops > stops, self.monitor.summary()

            await self._poll(f"{label}_wire_stop", STOP_POLLS, STOP_STEP // 4, stopped)
            after_stop = await self._rd(f"{label}_EVENTS_STOP", "TARGET_EVENTS", k)
            assert after_stop & TGT_STOP and after_stop & TGT_TX_PENDING == 0, (
                f"{label}: TARGET_EVENTS=0x{after_stop:08x} after the STOP"
            )
            await self._wr(f"{label}_W1C_START_STOP", "TARGET_EVENTS", k, TGT_START | TGT_STOP)
            final = await self._rd(f"{label}_EVENTS_FINAL", "TARGET_EVENTS", k)
            final_intr = await self._rd(f"{label}_INTR_FINAL", "INTR_STATE", k)
            assert final == 0 and final_intr & I2C_INTR_STATE_TX_STRETCH == 0, (
                f"{label}: after the written 0x18 TARGET_EVENTS=0x{final:08x} "
                f"INTR_STATE=0x{final_intr:08x}"
            )
            frames = self._frames(base)
            await self._leg_end(label, (c, k))
            rows.append(
                f"target I2C{k} / controller I2C{c}: TARGET_EVENTS=0x{events:08x} INTR_STATE="
                f"0x{intr:08x} controller STATUS=0x{rx:08x}; written 0x1 -> RDATA=0x{rdata:02x}; "
                f"after STOP 0x{after_stop:08x}; written 0x18 -> 0x{final:08x} INTR_STATE="
                f"0x{final_intr:08x}; wire {frames}"
            )
        self._stamp("I2C12_TGT_TX_PENDING")
        self._chk(
            "CHK-I2C12-TGT-TX-PENDING",
            f"set: READ address with TX_STRETCH_CTRL_EN=1 and TXDATA 0x{TX_BYTE:02x}; observed: "
            f"TARGET_EVENTS=0x09 and TX_STRETCH=1 with the controller RX FIFO empty; cleared: "
            f"0x1, then 0x18 after the STOP; checked_cleared: TARGET_EVENTS=0x00 and TX_STRETCH=0; "
            f"{'; '.join(rows)}",
        )

    async def _bus_timeout(self, k: int) -> str:
        label = f"S8_T{k}"
        bench = self.bench
        val = int(BUS_TIMEOUT_NS / float(self.cfg.periph_clk_period_ns))
        await self._target(k, label, I2C_CTRL_TX_STRETCH_CTRL_EN, (TX_BYTE,))
        await self._wr(
            f"{label}_TIMEOUT", "TIMEOUT_CTRL", k, I2C_TIMEOUT_CTRL_EN | I2C_TIMEOUT_MODE_BUS | val
        )
        await bench.send_start()
        nack = await bench.send_byte((TARGET_ADDR[k] << 1) | 1)
        assert nack == 0, f"{label}: target I2C{k} did not acknowledge its READ address"
        await self._wait_field(
            f"{label}_tx_pending",
            "TARGET_EVENTS",
            k,
            TGT_TX_PENDING,
            TGT_TX_PENDING,
            EVENT_POLLS,
            1,
        )
        await self._wr(f"{label}_W1C_PENDING", "TARGET_EVENTS", k, TGT_TX_PENDING | TGT_START)
        bit7 = await bench.recv_bit()
        hold_ns = 2 * BUS_TIMEOUT_NS
        hold_start = int(get_sim_time("ns"))
        seen = [0]

        async def probe() -> tuple[bool, str]:
            seen[0] = await self._rd(f"{label}_EVENTS_POLL", "TARGET_EVENTS", k)
            return bool(seen[0] & TGT_BUS_TIMEOUT), f"TARGET_EVENTS=0x{seen[0]:08x}"

        fired = await self._wait_until(f"{label}_bus_timeout", hold_ns, 16, probe)
        intr = await self._rd(f"{label}_INTR", "INTR_STATE", k)
        held = int(get_sim_time("ns")) - hold_start
        if held < hold_ns:
            await Timer(hold_ns - held, unit="ns")
        bench._pull_scl(False)
        bench._pull_sda(False)
        await self._wr(f"{label}_W1C_BUS_TIMEOUT", "TARGET_EVENTS", k, TGT_BUS_TIMEOUT)
        after = await self._rd(f"{label}_EVENTS_AFTER", "TARGET_EVENTS", k)
        after_intr = await self._rd(f"{label}_INTR_AFTER", "INTR_STATE", k)
        assert after & TGT_BUS_TIMEOUT == 0, (
            f"{label}: after the written 0x2 TARGET_EVENTS=0x{after:08x}"
        )
        await self._recover_bus(label, bench)
        bench._active = False
        await self._leg_end(label, (k,))
        return (
            f"target I2C{k} TIMEOUT_CTRL VAL={val}: bench held SCL low {hold_ns} ns after data "
            f"bit 7 (read {bit7}); TARGET_EVENTS=0x{seen[0]:08x} {fired} ns into the hold; "
            f"written 0x2 -> TARGET_EVENTS=0x{after:08x}; TX_STRETCH logged, not compared "
            f"(LINKED-ISSUE gate T_impl_i2c_w1c-s8-dut, SF-040): with BUS_TIMEOUT set "
            f"INTR_STATE=0x{intr:08x} TX_STRETCH={int(bool(intr & I2C_INTR_STATE_TX_STRETCH))}, "
            f"after the written 0x2 INTR_STATE=0x{after_intr:08x} TX_STRETCH="
            f"{int(bool(after_intr & I2C_INTR_STATE_TX_STRETCH))}"
        )

    async def _arbitration(self, k: int) -> str:
        c = 3 - k
        label = f"S8_A{k}"
        await self._target(k, label, I2C_CTRL_TX_STRETCH_CTRL_EN, (TX_BYTE,))
        for idx, addr in ((0, TARGET_ADDR[k]), (c, ARB_ADDR[k])):
            await self._controller(idx, f"{label}_C{idx}", enable=False)
            await self._queue(
                idx,
                f"{label}_C{idx}",
                [
                    _fdata((addr << 1) | 1, I2C_FDATA_START),
                    _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP),
                ],
            )
        base = len(self.monitor.frames)
        await self._wr(f"{label}_C0_GO", "CTRL", 0, I2C_CTRL_ENABLEHOST)
        await self._wr(f"{label}_C{c}_GO", "CTRL", c, I2C_CTRL_ENABLEHOST)
        state: dict[str, int] = {}
        idle = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY

        async def settled() -> tuple[bool, str]:
            state["tgt"] = await self._rd(f"{label}_TGT_POLL", "TARGET_EVENTS", k)
            if state["tgt"] & TGT_TX_PENDING:
                await self._wr(f"{label}_W1C_PENDING", "TARGET_EVENTS", k, TGT_TX_PENDING)
            done = True
            for idx in (0, c):
                state[f"ev{idx}"] = await self._rd(f"{label}_EV_POLL", "CONTROLLER_EVENTS", idx)
                state[f"st{idx}"] = await self._rd(f"{label}_ST_POLL", "STATUS", idx)
                finished = state[f"st{idx}"] & idle == idle
                done = done and (finished or state[f"ev{idx}"] != 0)
            return done, " ".join(f"{n}=0x{v:08x}" for n, v in state.items())

        await self._poll(f"{label}_settled", DONE_POLLS, DONE_STEP, settled)
        tgt = await self._rd(f"{label}_TGT_EVENTS", "TARGET_EVENTS", k)
        lost = [idx for idx in (0, c) if state[f"ev{idx}"] & EV_ARB_LOST] or "none"
        cleared = "not written (bit 2 read 0)"
        if tgt & TGT_ARB_LOST:
            await self._wr(f"{label}_W1C_ARB", "TARGET_EVENTS", k, TGT_ARB_LOST)
            after = await self._rd(f"{label}_TGT_AFTER", "TARGET_EVENTS", k)
            assert after & TGT_ARB_LOST == 0, (
                f"{label}: TARGET_EVENTS=0x{after:08x} after the written 0x4"
            )
            cleared = f"written 0x4 -> 0x{after:08x}"
        frames = self._frames(base)
        for idx in (0, c, k):
            await self._wr(f"{label}_CTRL_OFF", "CTRL", idx, 0)
        if not (self._scl() and self._sda()):
            await self._recover_bus(label, self.bench)
        await self._leg_end(label, (0, c, k))
        return (
            f"target I2C{k}: I2C0 read 0x{TARGET_ADDR[k]:02x}, I2C{c} read "
            f"0x{ARB_ADDR[k]:02x}; ARBITRATION_LOST controller(s) {lost}; I2C0 events="
            f"0x{state['ev0']:08x} I2C{c} events=0x{state[f'ev{c}']:08x}; target "
            f"TARGET_EVENTS=0x{tgt:08x} ARBITRATION_LOST={int(bool(tgt & TGT_ARB_LOST))} "
            f"(not specified, measured, SF-017); {cleared}; wire {frames}"
        )

    async def _s8_tgt_abnormal(self) -> None:
        timeouts = [await self._bus_timeout(k) for k in INSTANCES12]
        arbitration = [await self._arbitration(k) for k in INSTANCES12]
        self._stamp("I2C12_TGT_ABNORMAL")
        self._chk(
            "CHK-I2C12-TGT-ABNORMAL-END",
            f"set: SCL held low for 2V during a READ; observed: TARGET_EVENTS bit 1 BUS_TIMEOUT=1, "
            f"TX_STRETCH logged; cleared: TARGET_EVENTS written 0x2; checked_cleared: bit 1 reads "
            f"0, TX_STRETCH logged; {'; '.join(timeouts)}; lost arbitration: "
            f"{'; '.join(arbitration)}",
        )

    async def _unexp_read(self, k: int, label: str, last: int) -> tuple[str, int]:
        c = 3 - k
        await self._controller(c, f"{label}_C{c}")
        stops = self.monitor.stops
        base = len(self.monitor.frames)
        await self._queue(
            c,
            label,
            [
                _fdata((TARGET_ADDR[k] << 1) | 1, I2C_FDATA_START),
                _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP | last),
            ],
        )
        done = await self._wait_done(c, label, stops)
        await self._wait_field(f"{label}_rdata", "STATUS", c, I2C_STATUS_RXEMPTY, 0, RX_POLLS, 1)
        rdata = (await self._rd(f"{label}_RDATA", "RDATA", c)) & 0xFF
        intr = await self._rd(f"{label}_TGT_INTR", "INTR_STATE", k)
        return f"{done} RDATA=0x{rdata:02x} wire {self._frames(base)}", intr

    async def _s9_unexp_stop(self) -> None:
        rows = []
        for k in INSTANCES12:
            c = 3 - k
            label = f"S9_T{k}"
            await self._target(k, label, I2C_CTRL_ACQ_START_STOP_EN, (TX_BYTE, TX_FILL_BYTE))
            early, intr = await self._unexp_read(k, f"{label}_EARLY", FDATA_RCONT)
            bit = int(bool(intr & INTR_UNEXP_STOP))
            acq = await self._drain_acq(k, f"{label}_EARLY")
            await self._wr(f"{label}_W1C_UNEXP", "INTR_STATE", k, INTR_UNEXP_STOP)
            after = await self._rd(f"{label}_INTR_AFTER", "INTR_STATE", k)
            if bit:
                assert after & INTR_UNEXP_STOP == 0, (
                    f"{label}: UNEXP_STOP survives the written 0x2000 (0x{after:08x})"
                )
            await self._leg_end(f"{label}_EARLY_END", (c,))
            await self._target(k, f"{label}_N", I2C_CTRL_ACQ_START_STOP_EN, (TX_BYTE,))
            pre = await self._rd(f"{label}_INTR_PRE", "INTR_STATE", k)
            assert pre & INTR_UNEXP_STOP == 0, f"{label}: UNEXP_STOP reads 1 before (0x{pre:08x})"
            normal, intr_n = await self._unexp_read(k, f"{label}_NORMAL", 0)
            assert intr_n & INTR_UNEXP_STOP == 0, (
                f"{label}: UNEXP_STOP set by a normally terminated read (0x{intr_n:08x})"
            )
            acq_n = await self._drain_acq(k, f"{label}_NORMAL")
            await self._leg_end(f"{label}_END", (c, k))
            rows.append(
                f"target I2C{k} / controller I2C{c}: RCONT=1 STOP=1 read {early}; INTR_STATE="
                f"0x{intr:08x} UNEXP_STOP={bit} (not specified, measured, SF-007); ACQDATA {acq}; "
                f"written 0x2000 -> 0x{after:08x}; normal read {normal}; INTR_STATE=0x{intr_n:08x} "
                f"UNEXP_STOP=0; ACQDATA {acq_n}"
            )
        self._stamp("I2C12_UNEXP_STOP")
        self._chk(
            "CHK-I2C12-UNEXP-STOP",
            f"set: STOP before the target NACK handshake; observed: UNEXP_STOP and ACQDATA logged; "
            f"cleared: INTR_STATE written 0x2000 (compared 0 when the bit read 1); "
            f"checked_cleared: UNEXP_STOP=0 after a normally terminated read; {'; '.join(rows)}",
        )

    async def _s10_smbsus(self) -> None:
        await self._controller(1, "S10_C1")
        await self._wr("S10_SMBSUS_SET", "SMBUS_CTRL", 1, I2C_SMBUS_CTRL_SMBSUS)
        c1_low = await self._wait_pad("S10_I1_pad_low", "smbsus", 0)
        assert self._pulls("smbsus") == "010", f"S10: suspend pulls {self._pulls('smbsus')}"
        await self._wr("S10_SMBSUS_CLR", "SMBUS_CTRL", 1, 0)
        c1_high = await self._wait_pad("S10_I1_pad_high", "smbsus", 1)

        await self._off(1, "S10_T1")
        await self.csr_write("I2C1_S10_WRAP_TGT", _wrap(1), I2C_WRAP_CTRL_TARGET)
        await self._wr("S10_T1_TARGET_ID", "TARGET_ID", 1, _pack_target_id(TARGET_ADDR[1]))
        await self._wr("S10_T1_CTRL", "CTRL", 1, I2C_CTRL_ENABLETARGET)
        await self._controller(0, "S10_H0")
        await self._wr("S10_H0_SMBSUS_SET", "SMBUS_CTRL", 0, I2C_SMBUS_CTRL_SMBSUS)
        held = await self._wait_pad("S10_held_low", "smbsus", 0)
        sus_set = await self._wait_field(
            "S10_T1_smbsus_set",
            "SMBUS_STATUS",
            1,
            I2C_SMBUS_STATUS_SMBSUS,
            I2C_SMBUS_STATUS_SMBSUS,
            SMBUS_POLLS,
            SMBUS_STEP,
        )
        await self._wr("S10_H0_SMBSUS_CLR", "SMBUS_CTRL", 0, 0)
        released = await self._wait_pad("S10_released", "smbsus", 1)
        sus_clr = await self._wait_field(
            "S10_T1_smbsus_clr",
            "SMBUS_STATUS",
            1,
            I2C_SMBUS_STATUS_SMBSUS,
            0,
            SMBUS_POLLS,
            SMBUS_STEP,
        )
        await self._off(0, "S10_H0_END")
        await self._off(1, "S10_T1_END")

        await self._controller(2, "S10_C2")
        await self._wr("S10_C2_SMBSUS_SET", "SMBUS_CTRL", 2, I2C_SMBUS_CTRL_SMBSUS)
        rb1 = await self._rd("S10_C2_RB1", "SMBUS_CTRL", 2)
        c2_low = await self._wait_pad("S10_I2_pad_low", "smbsus", 0)
        assert rb1 & I2C_SMBUS_CTRL_SMBSUS, f"S10: I2C2 SMBUS_CTRL reads 0x{rb1:08x}"
        assert self._pulls("smbsus") == "001", f"S10: suspend pulls {self._pulls('smbsus')}"
        await self._wr("S10_C2_SMBSUS_CLR", "SMBUS_CTRL", 2, 0)
        rb0 = await self._rd("S10_C2_RB0", "SMBUS_CTRL", 2)
        c2_high = await self._wait_pad("S10_I2_pad_high", "smbsus", 1)
        assert rb0 & I2C_SMBUS_CTRL_SMBSUS == 0, f"S10: I2C2 SMBUS_CTRL reads 0x{rb0:08x}"
        await self._off(2, "S10_C2_END")
        await self._controller(0, "S10_I0_RESTORE", enable=False)
        self._stamp("I2C12_SMBSUS")
        self._chk(
            "CHK-I2C12-SMBSUS",
            f"I2C1 controller direction: SMBSUS=1 -> {c1_low}, written 0 -> {c1_high}; I2C1 "
            f"target direction with I2C0 holding the shared suspend line: {held} -> SMBUS_STATUS="
            f"0x{sus_set:08x} (SMBSUS=1), released {released} -> SMBUS_STATUS=0x{sus_clr:08x} "
            f"(SMBSUS=0); I2C2: SMBUS_CTRL reads 0x{rb1:08x} -> {c2_low}, then 0x{rb0:08x} -> "
            f"{c2_high}",
        )

    async def _address_target(self, c: int, addr: int, label: str, configure: bool = True) -> str:
        """Controller ``c`` writes one byte to ``addr``; ``configure`` re-initialises ``c``."""
        if configure:
            await self._controller(c, f"{label}_C{c}")
        stops = self.monitor.stops
        base = len(self.monitor.frames)
        await self._queue(
            c,
            label,
            [
                _fdata(addr << 1, I2C_FDATA_START),
                _fdata(ALERT_WRITE_BYTE, I2C_FDATA_STOP),
            ],
        )
        done = await self._wait_done(c, label, stops)
        return f"{done} wire {self._frames(base)}"

    async def _alert_target_leg(self, k: int, c: int) -> str:
        label = f"S11_T{k}"
        await self._target(k, label, 0)
        await self._wr(f"{label}_SMBALERT", "SMBUS_CTRL", k, I2C_SMBUS_CTRL_SMBALERT)
        low = await self._wait_pad(f"{label}_alert_low", "smbalert", 0)
        pulls = self._pulls("smbalert")
        assert pulls == "".join("1" if i == k else "0" for i in (0, 1, 2)), (
            f"{label}: alert pulls(i0i1i2)={pulls}"
        )
        wire = await self._address_target(c, TARGET_ADDR[k], label)
        ctrl = await self._rd(f"{label}_SMBUS_CTRL", "SMBUS_CTRL", k)
        assert ctrl & I2C_SMBUS_CTRL_SMBALERT == 0, (
            f"{label}: SMBUS_CTRL=0x{ctrl:08x} after I2C{c} addressed I2C{k}"
        )
        high = await self._wait_pad(f"{label}_alert_high", "smbalert", 1)
        acq = await self._drain_acq(k, label)
        await self._leg_end(label, (c, k))
        return (
            f"I2C{k} target SMBALERT=1 -> {low}; I2C{c} addressed it ({wire}) -> SMBUS_CTRL="
            f"0x{ctrl:08x}, {high}; ACQDATA {acq}"
        )

    async def _alert_host_leg(self, smbus_en: bool) -> str:
        label = f"S11_H{int(smbus_en)}"
        await self._controller(1, label)
        wrap = I2C_WRAP_CTRL_HOST_SMBUS if smbus_en else I2C_WRAP_CTRL_HOST
        await self.csr_write(f"I2C1_{label}_WRAP", _wrap(1), wrap)
        pre = await self._rd(f"{label}_INTR_PRE", "INTR_STATE", 1)
        assert pre & I2C_INTR_STATE_SMBALERT == 0, f"{label}: SMBALERT reads 1 before (0x{pre:08x})"
        await self._off(0, f"{label}_H0")
        await self.csr_write(f"I2C0_{label}_WRAP_TGT", _wrap(0), I2C_WRAP_CTRL_TARGET)
        await self._wr(f"{label}_H0_TARGET_ID", "TARGET_ID", 0, _pack_target_id(HOLDER_TARGET_ADDR))
        await self._wr(f"{label}_H0_CTRL", "CTRL", 0, I2C_CTRL_ENABLETARGET)
        await self._wr(f"{label}_H0_SMBALERT", "SMBUS_CTRL", 0, I2C_SMBUS_CTRL_SMBALERT)
        held = await self._wait_pad(f"{label}_held_low", "smbalert", 0)
        if smbus_en:
            status = await self._wait_field(
                f"{label}_status_set",
                "SMBUS_STATUS",
                1,
                I2C_SMBUS_STATUS_SMBALERT,
                I2C_SMBUS_STATUS_SMBALERT,
                SMBUS_POLLS,
                SMBUS_STEP,
            )
            intr = await self._wait_field(
                f"{label}_intr_set",
                "INTR_STATE",
                1,
                I2C_INTR_STATE_SMBALERT,
                I2C_INTR_STATE_SMBALERT,
                SMBUS_POLLS,
                SMBUS_STEP,
            )
            observed = f"SMBUS_STATUS=0x{status:08x} INTR_STATE=0x{intr:08x}"
        else:
            status = await self._rd(f"{label}_STATUS", "SMBUS_STATUS", 1)
            first = await self._rd(f"{label}_INTR_A", "INTR_STATE", 1)
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_SAMPLE_GAP_CYCLES)
            second = await self._rd(f"{label}_INTR_B", "INTR_STATE", 1)
            assert (first | second) & I2C_INTR_STATE_SMBALERT == 0, (
                f"{label}: INTR_STATE.SMBALERT set with SMBUS_EN=0 (0x{first:08x} 0x{second:08x})"
            )
            observed = (
                f"INTR_STATE=0x{first:08x} and 0x{second:08x} {IRQ_SAMPLE_GAP_CYCLES} cycles "
                f"apart (SMBALERT=0); SMBUS_STATUS=0x{status:08x} SMBALERT="
                f"{int(bool(status & I2C_SMBUS_STATUS_SMBALERT))} (not specified, measured, SF-012)"
            )
        wire = await self._address_target(1, HOLDER_TARGET_ADDR, label, configure=False)
        holder = await self._rd(f"{label}_H0_SMBUS_CTRL", "SMBUS_CTRL", 0)
        released = await self._wait_pad(f"{label}_released", "smbalert", 1)
        await self._wr(f"{label}_W1C_SMBALERT", "INTR_STATE", 1, I2C_INTR_STATE_SMBALERT)
        after = await self._rd(f"{label}_INTR_AFTER", "INTR_STATE", 1)
        assert after & I2C_INTR_STATE_SMBALERT == 0, (
            f"{label}: INTR_STATE=0x{after:08x} after the written 0x8000"
        )
        await self._leg_end(label, (0, 1))
        await self._controller(0, f"{label}_I0_RESTORE", enable=False)
        await self.csr_write(f"I2C1_{label}_WRAP_OFF", _wrap(1), 0)
        return (
            f"I2C1 controller SMBUS_EN={int(smbus_en)}, I2C0 holds the shared alert line "
            f"{held}: {observed}; released by I2C1 addressing 0x{HOLDER_TARGET_ADDR:02x} ({wire}, "
            f"I2C0 SMBUS_CTRL=0x{holder:08x}) {released}, written 0x8000 -> "
            f"INTR_STATE=0x{after:08x}"
        )

    async def _s11_smbalert(self) -> None:
        tgt1 = await self._alert_target_leg(1, 2)
        host_on = await self._alert_host_leg(True)
        host_off = await self._alert_host_leg(False)
        tgt2 = await self._alert_target_leg(2, 1)
        self._stamp("I2C12_SMBALERT")
        self._chk(
            "CHK-I2C12-SMBALERT",
            f"{tgt1}; {host_on}; {host_off}; {tgt2}",
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
        await self._i2c12_setup()
        await self._s2_intr_test_w1c()
        await self._s3_rw_hold()
        await self._s4_irq_gate()
        await self._s5_ctrl_nack()
        await self._s6_ctrl_partial()
        await self._s7_tgt_tx_pending()
        await self._s8_tgt_abnormal()
        await self._s9_unexp_stop()
        await self._s10_smbsus()
        await self._s11_smbalert()
        self._emit_timeout_paths()
        self._emit_nonvac()
