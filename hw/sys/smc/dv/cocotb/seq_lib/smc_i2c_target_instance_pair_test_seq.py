# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Instance pairs on the shared I2C bus: isolation, interrupts, clock gate and NACK handler.

Sources: hw/ip/i2c/regs/i2c.rdl (INTR_TEST, TARGET_ID, ACQDATA, FDATA, RDATA, CONTROLLER_EVENTS,
HOST_NACK_HANDLER_TIMEOUT), hw/sys/smc/doc/interrupts.adoc, clk_rst.adoc, memmap.adoc.

Three wrapper instances share one open-drain bus (+smc_i2c_shared_bus). The same-address and
contending-controller legs, the gated-bus legs and the NACK handler timing legs are owner
value pending: they print measured values and compare nothing.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import SmcFwI2cWireMonitor
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_CONTROLLER_EVENTS_ARBITRATION_LOST,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_ENABLE_TX_STRETCH,
    I2C_INTR_STATE_TX_STRETCH,
    I2C_NACK_HANDLER_TIMEOUT_EN,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_field, _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cBusMonitor, SmcI2cMasterVip
from .smc_i2c_slot_utils import drive_to_slot, release_bus
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INTR_TEST_TX_STRETCH = _i2c_u32("I2C__INTR_TEST__TX_STRETCH_bm")
EV_NACK = I2C_CONTROLLER_EVENTS_NACK
EV_UNHANDLED = I2C_CONTROLLER_EVENTS_UNHANDLED_NACK_TIMEOUT
EV_ARB_LOST = I2C_CONTROLLER_EVENTS_ARBITRATION_LOST
EV_FLAGS = EV_NACK | EV_UNHANDLED

INSTANCES = (0, 1, 2)
AXI_SLVERR = 2
CPU_IRQ_LSB = 279
VIP_SPEED = 2_000_000
VIP_SCL_BOUND_NS = 2_000_000
VIP_BYTE = 0x77
RECOVERY_BYTE = 0x44
ABSENT_ADDR = 0x2A
ISOLATION_ADDR = {0: 0x23, 1: 0x35, 2: 0x40}
SAME_ADDR = 0x23
CONTROLLER_PAIR_TARGET_ADDR = 0x40
PAIR_ADDR_BASE = 0x50
PAIR_TX = (0x71, 0x72)
PAIR_TX_DATA = (0x61, 0x62)
NACK_VAL_SHORT = 4000
NACK_VAL_LONG = 20000
SWEEP_OFFSETS = (-8, -2, 0, 2, 8)
GATED_DWELL_CHUNKS = 64
GATED_DWELL_CYCLES = 200
TARGET_TIMEOUT_PATTERN = 0x1234
MONITOR_IDLE_CYCLES = 1000

IRQ_POLLS = 400
IRQ_STEP = 4
IRQ_HOLD_CYCLES = 200
BUS_POLLS = 2000
BUS_STEP = 4
TASK_POLLS = 2000
TASK_STEP = 400
ACQ_POLLS = 200
ACQ_STEP = 50
ACQ_OBS_POLLS = 60
ACQ_POP_LIMIT = 80
IDLE_POLLS = 800
IDLE_STEP = 100
EVENT_POLLS = 800
EVENT_STEP = 50
RX_POLLS = 400
RX_STEP = 50
GATE_POLLS = 2000
GATE_STEP = 4
NACK_POLL_CYCLES = 20
EXPIRY_POLLS = 800
EXPIRY_STEP = 200

FENCE_ORDER = [f"S{n}" for n in range(1, 12)]
CHECKER_AFTER = {
    "CHK-I2C-TGT-INSTANCE-IRQ": "S2",
    "CHK-I2C-TGT-INSTANCE-ISOLATION": "S3",
    "CHK-I2C-TGT-INSTANCE-CONTENTION-LOG": "S5",
    "CHK-I2C-TGT-LOOP-PAIRS": "S6",
    "CHK-I2C-TGT-CG-GATED": "S7",
    "CHK-I2C-TGT-CG-UNGATE": "S8",
    "CHK-I2C-TGT-CG-MIDXFER": "S9",
    "CHK-I2C-TGT-NACKH-STOP": "S10",
    "CHK-I2C-TGT-NACKH-LOG": "S11",
}


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _fmt(entries: list[tuple[int, int]]) -> str:
    return "[" + " ".join(f"({s},0x{b:02x})" for s, b in entries) + "]"


def _now_ns() -> float:
    return float(get_sim_time("ns"))


class smc_i2c_target_instance_pair_test_seq(SmcCsrSeq):
    """Run the instance-pair legs on the shared bus and print one line per checker."""

    def __init__(self, name: str = "smc_i2c_target_instance_pair_test_seq") -> None:
        super().__init__(name)
        self.monitor: SmcI2cBusMonitor | None = None
        self.wire: SmcFwI2cWireMonitor | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.contention_s4 = ""
        self.cg_entry = 0

    # ----- bookkeeping -------------------------------------------------------------------
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

    @staticmethod
    def _cpu_irq() -> int:
        value = cocotb.top.tb_cpu_interrupts.value
        assert value.is_resolvable, f"tb_cpu_interrupts sampled X/Z ({value})"
        return (int(value) >> CPU_IRQ_LSB) & 0x7

    def _stops(self) -> int:
        return sum(1 for t in self.monitor.transactions if t["ev"] == "STOP")

    async def _diag(self) -> str:
        parts = []
        for idx in INSTANCES:
            status = await self.csr_read(f"DIAG_STATUS{idx}", _reg("STATUS", idx))
            events = await self.csr_read(f"DIAG_EVENTS{idx}", _reg("CONTROLLER_EVENTS", idx))
            tevents = await self.csr_read(f"DIAG_TEVENTS{idx}", _reg("TARGET_EVENTS", idx))
            parts.append(
                f"I2C{idx} STATUS=0x{status:08x} CONTROLLER_EVENTS=0x{events:08x} "
                f"TARGET_EVENTS=0x{tevents:08x}"
            )
        frames = " ".join(str(f) for f in self.wire.frames[-4:])
        scl, sda = (
            self._bit(cocotb.top.tb_i2c0_scl, "scl"),
            self._bit(cocotb.top.tb_i2c0_sda, "sda"),
        )
        return "; ".join(parts) + f"; bus scl={scl} sda={sda}; {self.wire.summary()} {frames}"

    async def _poll(self, name: str, polls: int, step: int, probe, strict: bool = True) -> bool:
        """Run ``probe`` up to ``polls`` times, ``step`` cycles apart; raise on expiry if strict."""
        state = "never sampled"
        bound = f"{polls}x{step}cyc"
        for _ in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, bound, state))
                return True
            await ClockCycles(cocotb.top.clk_smc_i, step)
        if not strict:
            self.waits.append((name, bound, f"observation window elapsed, {state}"))
            return False
        self.waits.append((name, bound, f"EXPIRED {state}"))
        diag = await self._diag()
        raise AssertionError(f"{name}: not satisfied within {bound}; last {state}; {diag}")

    async def _wait_eq(self, name: str, getter, want: int) -> int:
        seen = [0]

        async def probe() -> tuple[bool, str]:
            seen[0] = getter()
            return seen[0] == want, f"value=0b{seen[0]:03b} want=0b{want:03b}"

        await self._poll(name, IRQ_POLLS, IRQ_STEP, probe)
        return seen[0]

    async def _wait_bus_released(self, name: str) -> None:
        dut = cocotb.top

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_POLLS, BUS_STEP, released)

    async def _wait_task(self, name: str, task) -> None:
        async def probe() -> tuple[bool, str]:
            return task.done(), "VIP transaction running" if not task.done() else "VIP done"

        await self._poll(name, TASK_POLLS, TASK_STEP, probe)
        task.result()

    # ----- instance setup ----------------------------------------------------------------
    async def _program_timing(self, idx: int) -> None:
        for reg, value in (
            ("TIMING0", _pack_timing0(0x1A, 0x32)),
            ("TIMING1", _pack_timing1(2, 2)),
            ("TIMING2", _pack_timing2(5, 4)),
            ("TIMING3", _pack_timing3(2, 5)),
            ("TIMING4", _pack_timing4(4, 5)),
        ):
            await self.csr_write(f"I2C{idx}_{reg}", _reg(reg, idx), value)

    async def _acq_reset(self, idx: int, label: str) -> None:
        await self.csr_write(f"{label}_ACQRST{idx}", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_ACQRST)

    async def _disable(self, idx: int) -> None:
        await self.csr_write(f"I2C{idx}_CTRL_OFF", _reg("CTRL", idx), 0)

    async def _enable_target(self, idx: int, addr: int, ctrl: int | None = None) -> None:
        if ctrl is None:
            ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        await self._disable(idx)
        await self.csr_write(f"TGT{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_TARGET)
        await self.csr_write(f"TGT{idx}_TEVENTS_CLR", _reg("TARGET_EVENTS", idx), 0xFFFF_FFFF)
        await self.csr_write(
            f"TGT{idx}_TARGET_ID", _reg("TARGET_ID", idx), _pack_target_id(addr, 0x7F, 0, 0)
        )
        await self.csr_write(
            f"TGT{idx}_FIFO",
            _reg("FIFO_CTRL", idx),
            I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_RXRST_FMTRST,
        )
        await self.csr_write(f"TGT{idx}_CTRL", _reg("CTRL", idx), ctrl)

    async def _enable_controller(
        self,
        idx: int,
        label: str,
        ctrl: int = I2C_CTRL_ENABLEHOST,
        nack: int = 0,
        host_timeout: int = 0,
    ) -> None:
        await self._disable(idx)
        await self.csr_write(f"{label}_WRAP", _wrap(idx), I2C_WRAP_CTRL_HOST)
        await self.csr_write(f"{label}_FIFO", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_NACK_HANDLER", _reg("HOST_NACK_HANDLER_TIMEOUT", idx), nack)
        await self.csr_write(f"{label}_HOST_TIMEOUT", _reg("HOST_TIMEOUT_CTRL", idx), host_timeout)
        await self.csr_write(f"{label}_CTRL", _reg("CTRL", idx), ctrl)

    async def _leg_end(self, idx: int, label: str) -> None:
        await self._disable(idx)
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_FMTRST", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(f"{label}_NACK_OFF", _reg("HOST_NACK_HANDLER_TIMEOUT", idx), 0)
        await self.csr_write(f"{label}_HOST_TIMEOUT_OFF", _reg("HOST_TIMEOUT_CTRL", idx), 0)
        await self._wait_bus_released(f"{label}_bus_released")

    async def _queue(self, idx: int, words: list[int], label: str) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", _reg("FDATA", idx), word)

    # ----- ACQ FIFO helpers --------------------------------------------------------------
    async def _pop_acq(self, idx: int, label: str) -> list[tuple[int, int]]:
        entries: list[tuple[int, int]] = []
        for _ in range(ACQ_POP_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_STATUS{idx}", _reg("STATUS", idx))
            if status & I2C_STATUS_ACQEMPTY:
                return entries
            word = await self.csr_read(f"{label}_ACQDATA{idx}", _reg("ACQDATA", idx))
            entries.append((acq_signal(word), acq_abyte(word)))
        raise AssertionError(f"{label}: I2C{idx} ACQ FIFO never emptied ({_fmt(entries)})")

    async def _collect(self, idx: int, label: str, strict: bool = True) -> list[tuple[int, int]]:
        entries: list[tuple[int, int]] = []

        async def probe() -> tuple[bool, str]:
            entries.extend(await self._pop_acq(idx, label))
            stop = any(s == I2C_ACQ_SIGNAL_STOP for s, _ in entries)
            return stop, f"I2C{idx} entries={_fmt(entries)}"

        polls = ACQ_POLLS if strict else ACQ_OBS_POLLS
        await self._poll(f"{label}_i{idx}_acq_stop", polls, ACQ_STEP, probe, strict)
        return entries

    # ----- VIP transactions --------------------------------------------------------------
    @staticmethod
    def _new_vip(name: str) -> SmcI2cMasterVip:
        return SmcI2cMasterVip(speed=VIP_SPEED, name=name, scl_timeout_ns=VIP_SCL_BOUND_NS)

    @staticmethod
    async def _vip_write(vip: SmcI2cMasterVip, addr7: int, data: bytes) -> list[int]:
        acks = []
        await vip.send_start()
        acks.append(await vip.send_byte((addr7 & 0x7F) << 1))
        for byte in data:
            acks.append(await vip.send_byte(byte))
        await vip.send_stop()
        return acks

    @staticmethod
    async def _vip_read(vip: SmcI2cMasterVip, addr7: int, count: int) -> tuple[int, bytes]:
        await vip.send_start()
        ack = await vip.send_byte(((addr7 & 0x7F) << 1) | 1)
        out = bytearray()
        if ack == 0:
            for i in range(count):
                out.append(await vip.recv_byte(ack=(i != count - 1)))
        await vip.send_stop()
        return ack, bytes(out)

    async def _vip_run(self, name: str, coro) -> object:
        task = cocotb.start_soon(coro)
        await self._wait_task(name, task)
        return task.result()

    # ----- S1 ---------------------------------------------------------------------------
    async def _s1_setup(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_target_instance_pair_test needs +smc_i2c_shared_bus"
        )
        self.cg_entry = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write(
            "CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, self.cg_entry & ~I2C_CG_EN
        )
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_PAIR")
        for idx in INSTANCES:
            await self._disable(idx)
            await self.csr_write(f"I2C{idx}_WRAP_EN", _wrap(idx), I2C_WRAP_CTRL_TARGET)
            await self._program_timing(idx)
            await self.csr_write(f"I2C{idx}_INTR_ENABLE_OFF", _reg("INTR_ENABLE", idx), 0)
            await self.csr_write(f"I2C{idx}_OVRD_OFF", _reg("OVRD", idx), 0)
            await self.csr_write(
                f"I2C{idx}_FIFO_RST",
                _reg("FIFO_CTRL", idx),
                I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_RXRST_FMTRST,
            )
        await self._wait_bus_released("bus_released_bringup")
        for idx in INSTANCES:
            status = await self.csr_read(f"I2C{idx}_STATUS_ENTRY", _reg("STATUS", idx))
            assert status & I2C_STATUS_ACQEMPTY, f"I2C{idx} STATUS=0x{status:08x}: ACQEMPTY=0"
        self.monitor = SmcI2cBusMonitor("smc_i2c_pair_monitor")
        self.wire = SmcFwI2cWireMonitor(name="smc_i2c_pair_wire")
        self._stamp("S1")

    # ----- S2 ---------------------------------------------------------------------------
    async def _s2_interrupts(self) -> None:
        rows = []
        for i in INSTANCES:
            enable, test = _reg("INTR_ENABLE", i), _reg("INTR_TEST", i)
            irq0, cpu0 = self._irq(), self._cpu_irq()
            assert irq0 == 0 and cpu0 == 0, f"I2C{i}: lines 0b{irq0:03b}/0b{cpu0:03b} before"
            await self.csr_write(f"I2C{i}_ENABLE", enable, I2C_INTR_ENABLE_TX_STRETCH)
            await self.csr_write(f"I2C{i}_TEST_SET", test, INTR_TEST_TX_STRETCH)
            irq1 = await self._wait_eq(f"s2_i{i}_irq_high", self._irq, 1 << i)
            cpu1 = await self._wait_eq(f"s2_i{i}_cpu_high", self._cpu_irq, 1 << i)
            state = await self.csr_read(f"I2C{i}_STATE_SET", _reg("INTR_STATE", i))
            assert state & I2C_INTR_STATE_TX_STRETCH, f"I2C{i}: INTR_STATE=0x{state:08x}"
            await ClockCycles(cocotb.top.clk_smc_i, IRQ_HOLD_CYCLES)
            held = (self._irq(), self._cpu_irq())
            assert held == (1 << i, 1 << i), (
                f"I2C{i}: lines drifted to {held} while the test bit is 1"
            )
            await self.csr_write(f"I2C{i}_TEST_CLR", test, 0)
            irq2 = await self._wait_eq(f"s2_i{i}_irq_low", self._irq, 0)
            cpu2 = await self._wait_eq(f"s2_i{i}_cpu_low", self._cpu_irq, 0)
            await self.csr_write(f"I2C{i}_ENABLE_OFF", enable, 0)
            rows.append(
                f"inst{i}: before 0b{irq0:03b}/0b{cpu0:03b} -> test=1 tb_i2c_irq=0b{irq1:03b} "
                f"cpu[281:279]=0b{cpu1:03b} -> test=0 0b{irq2:03b}/0b{cpu2:03b}"
            )
        self._stamp("S2")
        self._chk("CHK-I2C-TGT-INSTANCE-IRQ", "; ".join(rows))

    # ----- S3 ---------------------------------------------------------------------------
    async def _write_txn(self, label, vip, addr7, owner):
        for idx in INSTANCES:
            await self._acq_reset(idx, label)
        acks = await self._vip_run(f"{label}_vip", self._vip_write(vip, addr7, bytes((VIP_BYTE,))))
        entries = {}
        if owner is not None:
            entries[owner] = await self._collect(owner, label)
        for idx in INSTANCES:
            if idx != owner:
                entries[idx] = await self._pop_acq(idx, label)
        return acks, entries

    async def _isolation_round(self, label: str, vip, enabled: set[int]) -> dict[int, tuple]:
        owners = {addr: idx for idx, addr in ISOLATION_ADDR.items()}
        out = {}
        for addr in (0x23, 0x35, 0x40):
            owner = owners[addr] if owners[addr] in enabled else None
            acks, entries = await self._write_txn(f"{label}_{addr:02x}", vip, addr, owner)
            out[addr] = (acks, entries)
        return out

    def _check_isolation(self, round_name: str, result: dict, enabled: set[int]) -> str:
        parts = []
        for addr, (acks, entries) in result.items():
            owner = {a: i for i, a in ISOLATION_ADDR.items()}[addr]
            if owner in enabled:
                assert acks == [0, 0], f"{round_name} 0x{addr:02x}: ACK bits {acks}"
                got = entries[owner]
                assert got[:2] == [
                    (I2C_ACQ_SIGNAL_START, addr << 1),
                    (I2C_ACQ_SIGNAL_NONE, VIP_BYTE),
                ]
                assert len(got) >= 3 and got[2][0] == I2C_ACQ_SIGNAL_STOP, (
                    f"{round_name} 0x{addr:02x}: entries {_fmt(got)}"
                )
                others = {i: e for i, e in entries.items() if i != owner}
                assert all(not e for e in others.values()), (
                    f"{round_name} 0x{addr:02x}: entries outside I2C{owner}: {others}"
                )
            else:
                assert acks[0] == 1, f"{round_name} 0x{addr:02x}: ACK bits {acks}, expected NACK"
                assert all(not e for e in entries.values()), (
                    f"{round_name} 0x{addr:02x}: entries {entries}"
                )
            parts.append(
                f"0x{addr:02x} acks={acks} entries "
                + " ".join(f"I2C{i}={_fmt(e)}" for i, e in sorted(entries.items()))
            )
        return f"{round_name}: " + "; ".join(parts)

    async def _s3_isolation(self) -> None:
        for idx in (0, 1):
            await self._enable_target(idx, ISOLATION_ADDR[idx])
        await self._enable_target(2, ISOLATION_ADDR[2], I2C_CTRL_ACQ_START_STOP_EN)
        vip = self._new_vip("smc_i2c_pair_isolation")
        first = await self._isolation_round("I2C2 disabled", vip, {0, 1})
        line1 = self._check_isolation("I2C2 disabled", first, {0, 1})
        await self._enable_target(2, ISOLATION_ADDR[2])
        second = await self._isolation_round("I2C2 enabled", vip, {0, 1, 2})
        line2 = self._check_isolation("I2C2 enabled", second, {0, 1, 2})
        for addr in (0x23, 0x35):
            assert second[addr] == first[addr], (
                f"0x{addr:02x} changed after I2C2 was enabled: {first[addr]} -> {second[addr]}"
            )
        for idx in INSTANCES:
            await self._disable(idx)
        self._stamp("S3")
        self._chk("CHK-I2C-TGT-INSTANCE-ISOLATION", f"{line1}; {line2}; 0x23 and 0x35 unchanged")

    # ----- S4 ---------------------------------------------------------------------------
    async def _s4_same_address(self) -> None:
        for idx in (0, 1):
            await self._enable_target(idx, SAME_ADDR)
        await self._disable(2)
        vip = self._new_vip("smc_i2c_pair_same_addr")
        for idx in (0, 1):
            await self._acq_reset(idx, "S4_W")
        w_acks = await self._vip_run(
            "s4_write_vip", self._vip_write(vip, SAME_ADDR, bytes((0x71,)))
        )
        w_entries = {i: await self._collect(i, "S4_W", strict=False) for i in (0, 1)}
        for idx, tx in ((0, 0x91), (1, 0x92)):
            await self.csr_write(
                f"S4_RST{idx}",
                _reg("FIFO_CTRL", idx),
                I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST,
            )
            await self.csr_write(f"S4_TXDATA{idx}", _reg("TXDATA", idx), tx)
        r_ack, r_bytes = await self._vip_run("s4_read_vip", self._vip_read(vip, SAME_ADDR, 1))
        r_entries = {i: await self._collect(i, "S4_R", strict=False) for i in (0, 1)}
        t_events = {
            idx: await self.csr_read(f"S4_TEVENTS{idx}", _reg("TARGET_EVENTS", idx))
            for idx in (0, 1)
        }
        for idx in (0, 1):
            await self.csr_write(
                f"S4_CLEAN{idx}",
                _reg("FIFO_CTRL", idx),
                I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST,
            )
            await self._disable(idx)
        self._stamp("S4")
        self.contention_s4 = (
            f"same address 0x{SAME_ADDR:02x} on I2C0 and I2C1 (TXDATA 0x91/0x92): write acks="
            f"{w_acks} entries I2C0={_fmt(w_entries[0])} I2C1={_fmt(w_entries[1])}; read ack="
            f"{r_ack} byte={r_bytes.hex()} entries I2C0={_fmt(r_entries[0])} "
            f"I2C1={_fmt(r_entries[1])}; TARGET_EVENTS I2C0=0x{t_events[0]:08x} "
            f"I2C1=0x{t_events[1]:08x}; both transactions completed (not specified, measured)"
        )

    # ----- S5 ---------------------------------------------------------------------------
    async def _s5_two_controllers(self) -> None:
        await self._enable_target(2, CONTROLLER_PAIR_TARGET_ADDR)
        ctrl = I2C_CTRL_ENABLEHOST | I2C_CTRL_MULTI_CONTROLLER_MONITOR_EN
        for idx in (0, 1):
            await self._enable_controller(
                idx,
                f"S5_I{idx}",
                ctrl,
                host_timeout=_i2c_field("HOST_TIMEOUT_CTRL", "VAL", MONITOR_IDLE_CYCLES),
            )
        base = self._stops()
        for idx, data in ((0, 0x91), (1, 0x92)):
            await self._queue(
                idx,
                [
                    _fdata(CONTROLLER_PAIR_TARGET_ADDR << 1, I2C_FDATA_START),
                    _fdata(data),
                    _fdata(0, I2C_FDATA_STOP),
                ],
                f"S5_I{idx}",
            )
        last = {}

        async def probe() -> tuple[bool, str]:
            done = True
            for idx in (0, 1):
                status = await self.csr_read(f"S5_STATUS{idx}", _reg("STATUS", idx))
                events = await self.csr_read(f"S5_EVENTS{idx}", _reg("CONTROLLER_EVENTS", idx))
                last[idx] = (status, events)
                idle = status & I2C_STATUS_HOSTIDLE and status & I2C_STATUS_FMTEMPTY
                done = done and bool(idle or events & (EV_NACK | EV_ARB_LOST))
            return done, " ".join(
                f"I2C{i} STATUS=0x{s:08x} EVENTS=0x{e:08x}" for i, (s, e) in last.items()
            )

        await self._poll("s5_controllers_done", EVENT_POLLS, EVENT_STEP, probe)
        stops = self._stops() - base
        entries = await self._collect(2, "S5", strict=False)
        for idx in (0, 1):
            await self._leg_end(idx, f"S5_I{idx}")
        await self._disable(2)
        self._stamp("S5")
        rows = " ".join(
            f"I2C{i}: STATUS=0x{s:08x} CONTROLLER_EVENTS=0x{e:08x} NACK={int(bool(e & EV_NACK))} "
            f"ARBITRATION_LOST={int(bool(e & EV_ARB_LOST))}"
            for i, (s, e) in sorted(last.items())
        )
        self._chk(
            "CHK-I2C-TGT-INSTANCE-CONTENTION-LOG",
            f"{self.contention_s4}; two controllers to I2C2 0x{CONTROLLER_PAIR_TARGET_ADDR:02x} "
            f"with MULTI_CONTROLLER_MONITOR_EN: {rows}; I2C2 entries {_fmt(entries)}; bus STOPs "
            f"{stops}; both controllers completed within the bound (not specified, measured)",
        )

    # ----- S6 ---------------------------------------------------------------------------
    async def _wait_idle(self, idx: int, label: str) -> int:
        status = [0]

        async def probe() -> tuple[bool, str]:
            status[0] = await self.csr_read(f"{label}_IDLE_STATUS", _reg("STATUS", idx))
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            return status[0] & want == want, f"I2C{idx} STATUS=0x{status[0]:08x}"

        await self._poll(f"{label}_i{idx}_idle", IDLE_POLLS, IDLE_STEP, probe)
        return status[0]

    async def _pair(self, c: int, t: int) -> str:
        label = f"S6_{c}{t}"
        addr = PAIR_ADDR_BASE + t
        for idx in INSTANCES:
            if idx not in (c, t):
                await self._disable(idx)
        await self._enable_target(t, addr)
        for i, byte in enumerate(PAIR_TX):
            await self.csr_write(f"{label}_TXDATA{i}", _reg("TXDATA", t), byte)
        await self._enable_controller(c, label)
        await self._queue(
            c,
            [
                _fdata(addr << 1, I2C_FDATA_START),
                _fdata(PAIR_TX_DATA[0]),
                _fdata(PAIR_TX_DATA[1]),
                _fdata((addr << 1) | 1, I2C_FDATA_START),
                _fdata(2, I2C_FDATA_READB | I2C_FDATA_STOP),
            ],
            label,
        )
        entries: list[tuple[int, int]] = []
        status = [0]

        async def drain_probe() -> tuple[bool, str]:
            entries.extend(await self._pop_acq(t, label))
            status[0] = await self.csr_read(f"{label}_IDLE_STATUS", _reg("STATUS", c))
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            return (
                status[0] & want == want,
                f"I2C{c} STATUS=0x{status[0]:08x} I2C{t} entries={_fmt(entries)}",
            )

        await self._poll(f"{label}_i{c}_idle_draining_i{t}", IDLE_POLLS, IDLE_STEP, drain_probe)
        got: list[int] = []

        async def rx_probe() -> tuple[bool, str]:
            st = await self.csr_read(f"{label}_RX_STATUS", _reg("STATUS", c))
            if not st & I2C_STATUS_RXEMPTY:
                got.append(await self.csr_read(f"{label}_RDATA", _reg("RDATA", c)) & 0xFF)
            return len(got) == len(PAIR_TX), f"popped={[hex(b) for b in got]}"

        await self._poll(f"{label}_rdata", RX_POLLS, RX_STEP, rx_probe)
        events = await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", c))
        if not any(sig == I2C_ACQ_SIGNAL_STOP for sig, _ in entries):
            entries.extend(await self._collect(t, label))
        want = [
            (I2C_ACQ_SIGNAL_START, addr << 1),
            (I2C_ACQ_SIGNAL_NONE, PAIR_TX_DATA[0]),
            (I2C_ACQ_SIGNAL_NONE, PAIR_TX_DATA[1]),
            (I2C_ACQ_SIGNAL_RESTART, (addr << 1) | 1),
        ]
        assert entries[:4] == want, (
            f"pair ({c},{t}): entries {_fmt(entries)}, expected {_fmt(want)}"
        )
        assert got == list(PAIR_TX), f"pair ({c},{t}): RDATA {[hex(b) for b in got]}"
        assert not events & EV_NACK, f"pair ({c},{t}): CONTROLLER_EVENTS=0x{events:08x} (NACK)"
        await self._leg_end(c, label)
        await self._disable(t)
        return (
            f"({c},{t}) addr 0x{addr:02x}: first four {_fmt(entries[:4])} RDATA "
            f"{' '.join(f'0x{b:02x}' for b in got)} STATUS=0x{status[0]:08x} events=0x{events:08x}"
        )

    async def _s6_pairs(self) -> None:
        rows = []
        for c in INSTANCES:
            for t in INSTANCES:
                if c != t:
                    rows.append(await self._pair(c, t))
        self._stamp("S6")
        self._chk("CHK-I2C-TGT-LOOP-PAIRS", "; ".join(rows))

    # ----- S7 / S8 ----------------------------------------------------------------------
    async def _set_gate(self, on: bool) -> None:
        word = self.cg_entry | I2C_CG_EN if on else self.cg_entry & ~I2C_CG_EN
        await self.csr_write("CG_SET" if on else "CG_CLEAR", CLOCK_GATE_CONTROL, word)

        async def probe() -> tuple[bool, str]:
            level = self._bit(cocotb.top.tb_i2c_cg_en, "tb_i2c_cg_en")
            return level == int(on), f"tb_i2c_cg_en={level}"

        await self._poll(f"tb_i2c_cg_en_to_{int(on)}", GATE_POLLS, GATE_STEP, probe)

    async def _s7_gated(self) -> None:
        for idx in INSTANCES:
            await self._disable(idx)
        programmed = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        await self._enable_target(0, SAME_ADDR, programmed)
        self.timeout_pattern = _i2c_field("TARGET_TIMEOUT_CTRL", "VAL", TARGET_TIMEOUT_PATTERN)
        await self.csr_write("I2C0_TTC_SET", _reg("TARGET_TIMEOUT_CTRL", 0), self.timeout_pattern)
        self.programmed = {
            "TARGET_ID": await self.csr_read("I2C0_TID_PROG", _reg("TARGET_ID", 0)),
            "CTRL": await self.csr_read("I2C0_CTRL_PROG", _reg("CTRL", 0)),
            "TARGET_TIMEOUT_CTRL": await self.csr_read(
                "I2C0_TTC_PROG", _reg("TARGET_TIMEOUT_CTRL", 0)
            ),
        }
        await self._set_gate(True)
        reads = []
        windows = [(f"I2C{i}_CTRL", _reg("CTRL", i)) for i in INSTANCES]
        windows.append(("i2c_ctrl_regs_I2C_CTRL0", _wrap(0)))
        for name, addr in windows:
            data = await self.csr_read_err_signature(f"GATED_RD_{name}", addr, resp=AXI_SLVERR)
            reads.append(f"{name} rd resp={AXI_SLVERR} data=0x{data:08x}")
        writes = []
        values = (programmed, 0, 0, I2C_WRAP_CTRL_TARGET)
        for (name, addr), value in zip(windows, values):
            resp = await self.csr_write_expect_error(
                f"GATED_WR_{name}", addr, value, resp=AXI_SLVERR
            )
            writes.append(f"{name} wr resp={resp}")
        self._stamp("S7")
        self._chk(
            "CHK-I2C-TGT-CG-GATED",
            f"tb_i2c_cg_en=1; {'; '.join(reads)}; {'; '.join(writes)}",
        )

    async def _s8_ungated(self) -> None:
        await self._set_gate(False)
        regs = (
            ("TARGET_ID", _reg("TARGET_ID", 0)),
            ("CTRL", _reg("CTRL", 0)),
            ("TARGET_TIMEOUT_CTRL", _reg("TARGET_TIMEOUT_CTRL", 0)),
        )
        read = {}
        for name, addr in regs:
            read[name] = await self.csr_read(f"UNGATED_{name}", addr)
            assert read[name] != self.ERR_SLAVE_SIGNATURE, f"{name} read the error signature"
        kept = {name: read[name] == self.programmed[name] for name, _ in regs}
        assert all(kept.values()), (
            f"registers lost across the clock gate: {[n for n, ok in kept.items() if not ok]}"
        )
        await self._acq_reset(0, "S8")
        await self._wait_bus_released("s8_bus_released")
        vip = self._new_vip("smc_i2c_pair_ungate")
        acks = await self._vip_run("s8_vip", self._vip_write(vip, SAME_ADDR, bytes((0x41,))))
        entries = await self._collect(0, "S8", strict=False)
        self._stamp("S8")
        self._chk(
            "CHK-I2C-TGT-CG-UNGATE",
            "tb_i2c_cg_en=0; reads OKAY "
            + " ".join(
                f"{n}=0x{read[n]:08x}(programmed 0x{self.programmed[n]:08x} kept={int(kept[n])})"
                for n, _ in regs
            )
            + f"; write 0x{SAME_ADDR:02x} acks={acks} entries {_fmt(entries)} "
            "(not specified, measured)",
        )

    # ----- S9 ---------------------------------------------------------------------------
    async def _s9_mid_transfer(self) -> None:
        dut = cocotb.top
        await self._enable_target(0, SAME_ADDR)
        await self._wait_bus_released("s9_bus_released_pre")
        vip = self._new_vip("smc_i2c_pair_midxfer")
        await self._vip_run("s9_park_vip", drive_to_slot(vip, SAME_ADDR, RECOVERY_BYTE, "data", 4))
        parked = (self._bit(dut.tb_i2c0_scl, "scl"), self._bit(dut.tb_i2c0_sda, "sda"))
        await self._set_gate(True)
        gated_start = (self._bit(dut.tb_i2c0_scl, "scl"), self._bit(dut.tb_i2c0_sda, "sda"))
        await release_bus(vip)
        samples = []
        for _ in range(GATED_DWELL_CHUNKS):
            await ClockCycles(dut.clk_smc_i, GATED_DWELL_CYCLES)
            samples.append((self._bit(dut.tb_i2c0_scl, "scl"), self._bit(dut.tb_i2c0_sda, "sda")))
        self.waits.append(
            (
                "s9_gated_dwell",
                f"{GATED_DWELL_CHUNKS}x{GATED_DWELL_CYCLES}cyc",
                f"ran full, last scl={samples[-1][0]} sda={samples[-1][1]}",
            )
        )
        cg_level = self._bit(dut.tb_i2c_cg_en, "tb_i2c_cg_en")
        await self._set_gate(False)
        after_ungate = (self._bit(dut.tb_i2c0_scl, "scl"), self._bit(dut.tb_i2c0_sda, "sda"))
        await self._disable(0)
        await self.csr_write(
            "S9_FIFO", _reg("FIFO_CTRL", 0), I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "S9_TARGET_ID", _reg("TARGET_ID", 0), _pack_target_id(SAME_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write(
            "S9_CTRL", _reg("CTRL", 0), I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
        )
        await self._wait_bus_released("s9_bus_released_recovery")
        recovery = self._new_vip("smc_i2c_pair_recovery")
        acks = await self._vip_run(
            "s9_recovery_vip", self._vip_write(recovery, SAME_ADDR, bytes((RECOVERY_BYTE,)))
        )
        entries = await self._collect(0, "S9")
        assert acks == [0, 0], f"recovery write ACK bits {acks}"
        assert entries[:2] == [
            (I2C_ACQ_SIGNAL_START, SAME_ADDR << 1),
            (I2C_ACQ_SIGNAL_NONE, RECOVERY_BYTE),
        ], f"recovery entries {_fmt(entries)}"
        assert len(entries) >= 3 and entries[2][0] == I2C_ACQ_SIGNAL_STOP, _fmt(entries)
        await self._disable(0)
        self._stamp("S9")
        low_scl = sum(1 for s, _ in samples if s == 0)
        low_sda = sum(1 for _, d in samples if d == 0)
        self._chk(
            "CHK-I2C-TGT-CG-MIDXFER",
            f"parked scl/sda={parked}; gate set tb_i2c_cg_en={cg_level} scl/sda={gated_start}; "
            f"after release {GATED_DWELL_CHUNKS}x{GATED_DWELL_CYCLES} cycles: scl low in "
            f"{low_scl} samples, sda low in {low_sda}, last {samples[-1]}; after ungate "
            f"{after_ungate}; recovery write acks={acks} entries {_fmt(entries)} "
            "(not specified, measured)",
        )

    # ----- S10 / S11 --------------------------------------------------------------------
    def _nack_word(self, val: int, en: bool) -> int:
        word = _i2c_field("HOST_NACK_HANDLER_TIMEOUT", "VAL", val)
        return word | (I2C_NACK_HANDLER_TIMEOUT_EN if en else 0)

    async def _nack_events(self, label: str) -> int:
        return await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", 1))

    async def _nack_run(self, label: str, en: bool) -> str:
        period = self.cfg.periph_clk_period_ns
        window_ns = 8 * NACK_VAL_SHORT * period
        await self._enable_controller(1, label, nack=self._nack_word(NACK_VAL_SHORT, en))
        base = self._stops()
        t_q = _now_ns()
        await self._queue(
            1,
            [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START), _fdata(0, I2C_FDATA_STOP)],
            label,
        )
        seen: dict[str, float] = {}
        events = 0
        while _now_ns() < t_q + window_ns:
            events = await self._nack_events(label)
            now = _now_ns()
            if events & EV_NACK:
                seen.setdefault("nack", now)
            if events & EV_UNHANDLED:
                seen.setdefault("unhandled", now)
            if self._stops() > base:
                seen.setdefault("stop", now)
            if en and {"nack", "unhandled", "stop"} <= seen.keys():
                break
            await ClockCycles(cocotb.top.clk_smc_i, NACK_POLL_CYCLES)
        stops = self._stops() - base
        events = await self._nack_events(f"{label}_FINAL")
        state = f"seen={seen} events=0x{events:08x} stops={stops}"
        bound = f"{int(window_ns)}ns"
        if en:
            if not {"nack", "unhandled", "stop"} <= seen.keys():
                self.waits.append((f"{label}_window", bound, f"EXPIRED {state}"))
                raise AssertionError(f"{label}: EN=1 window expired; {state}; {await self._diag()}")
            assert events & EV_FLAGS == EV_FLAGS, f"{label}: events 0x{events:08x}"
            await self.csr_write(f"{label}_CLEAR", _reg("CONTROLLER_EVENTS", 1), EV_FLAGS)
            after = await self._nack_events(f"{label}_CLEARED")
            assert after & EV_FLAGS == 0, f"{label}: events 0x{after:08x} after the written 1s"
            delay = seen["stop"] - seen["nack"]
            result = (
                f"EN=1 VAL={NACK_VAL_SHORT}: NACK=1 UNHANDLED_NACK_TIMEOUT=1 STOP count {stops}; "
                f"events after the written 1s 0x{after:08x}; STOP seen {delay:.0f} ns after the "
                f"NACK at poll resolution (window {bound})"
            )
        else:
            assert seen.get("nack") is not None, f"{label}: NACK never reported; {state}"
            assert stops == 0 and not events & EV_UNHANDLED, f"{label}: {state}"
            result = (
                f"EN=0: NACK=1 UNHANDLED_NACK_TIMEOUT=0 STOP count {stops} over the full "
                f"{bound} window (events 0x{events:08x})"
            )
        self.waits.append((f"{label}_window", bound, state))
        await self._leg_end(1, label)
        return result

    async def _s10_stop_handler(self) -> None:
        await self._enable_target(0, SAME_ADDR)
        await self._disable(2)
        enabled = await self._nack_run("S10_EN1", True)
        disabled = await self._nack_run("S10_EN0", False)
        await self._disable(0)
        self._stamp("S10")
        self._chk("CHK-I2C-TGT-NACKH-STOP", f"{enabled}; {disabled}")

    async def _wait_handler_expiry(self, label: str, base: int) -> int:
        """Wait for the NACK handler to expire: UNHANDLED_NACK_TIMEOUT set and a bus STOP."""
        status = [0]

        async def probe() -> tuple[bool, str]:
            events = await self._nack_events(f"{label}_EXPIRY")
            status[0] = await self.csr_read(f"{label}_EXPIRY_STATUS", _reg("STATUS", 1))
            done = bool(events & EV_UNHANDLED) and self._stops() > base
            return (
                done,
                f"events=0x{events:08x} STATUS=0x{status[0]:08x} stops={self._stops() - base}",
            )

        await self._poll(f"{label}_handler_expiry", EXPIRY_POLLS, EXPIRY_STEP, probe)
        return status[0]

    async def _timed_case(self, label: str, offset: int | None) -> str:
        period = self.cfg.periph_clk_period_ns
        val = NACK_VAL_LONG
        await self._enable_controller(1, label, nack=self._nack_word(val, True))
        base = self._stops()
        words = [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START)]
        if offset is None:
            words.append(_fdata(0, I2C_FDATA_STOP))
        await self._queue(1, words, label)
        t_nack = [0.0]

        async def probe() -> tuple[bool, str]:
            events = await self._nack_events(f"{label}_WAIT")
            t_nack[0] = _now_ns()
            return bool(events & EV_NACK), f"events=0x{events:08x}"

        await self._poll(f"{label}_nack", EVENT_POLLS, 1, probe)
        if offset is None:
            await self.csr_write(f"{label}_NACK_CLR", _reg("CONTROLLER_EVENTS", 1), EV_NACK)
            t_issue = _now_ns()
            await Timer(int(1.5 * val * period), unit="ns")
            note = f"NACK cleared at +{t_issue - t_nack[0]:.0f} ns, waited 1.5xVAL"
        else:
            target = t_nack[0] + (val + offset) * period
            if target > _now_ns():
                await Timer(int(target - _now_ns()), unit="ns")
            t_issue = _now_ns()
            await self.csr_write(f"{label}_STOP", _reg("FDATA", 1), _fdata(0, I2C_FDATA_STOP))
            note = (
                f"software STOP at {offset:+d} cycles requested at +{target - t_nack[0]:.0f} ns, "
                f"write began +{t_issue - t_nack[0]:.0f} ns, ended +{_now_ns() - t_nack[0]:.0f} ns"
            )
        stops_mid = self._stops() - base
        events_mid = await self._nack_events(f"{label}_MID")
        if offset is None:
            status = await self._wait_idle(1, label)
        else:
            status = await self._wait_handler_expiry(label, base)
        stops = self._stops() - base
        events = await self._nack_events(f"{label}_END")
        await self._leg_end(1, label)
        return (
            f"{label}: {note}; STOP count {stops_mid} then {stops}; CONTROLLER_EVENTS[1:0] "
            f"{events_mid & EV_FLAGS} then {events & EV_FLAGS}; completed STATUS=0x{status:08x}"
        )

    async def _s11_nack_log(self) -> None:
        await self._enable_target(0, SAME_ADDR)
        rows = [await self._timed_case("S11_CLEARED", None)]
        for offset in SWEEP_OFFSETS:
            rows.append(await self._timed_case(f"S11_STOP{offset:+d}".replace("+", "P"), offset))
        await self._disable(0)
        self._stamp("S11")
        self._chk(
            "CHK-I2C-TGT-NACKH-LOG",
            f"VAL={NACK_VAL_LONG}; "
            + "; ".join(rows)
            + "; no coincidence compared (not specified, measured)",
        )

    # ----- evidence ---------------------------------------------------------------------
    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
            (
                "vip_scl_release",
                f"{VIP_SCL_BOUND_NS} ns per wait",
                "raises SmcI2cVipError with the hold time",
            ),
        ]
        axi = ("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses completed")
        waits = inherited + self.waits + [axi]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry except the listed observation windows; %s",
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
        await self._s1_setup()
        await self._s2_interrupts()
        await self._s3_isolation()
        await self._s4_same_address()
        await self._s5_two_controllers()
        await self._s6_pairs()
        await self._s7_gated()
        await self._s8_ungated()
        await self._s9_mid_transfer()
        await self._s10_stop_handler()
        await self._s11_nack_log()
        self._emit_timeout_paths()
        self._emit_nonvac()
