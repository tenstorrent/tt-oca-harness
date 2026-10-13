# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 TARGET_EVENTS START_DETECT and STOP_DETECT against CTRL.ENABLETARGET.

Contract SMC_I2C_CSR_IRQ_015, anchor smc_i2c_target_event_flags_test.
Allocated scenarios: I2C-TARGET-EVENTS-RECORD.S2, I2C-TARGET-EVENTS-RECORD.S4.
Spec sources: hw/ip/i2c/regs/i2c.rdl TARGET_EVENTS and CTRL.ENABLETARGET; SF-016 open.

`TARGET_EVENTS.START_DETECT` and `STOP_DETECT` are set by hardware "while
CTRL.ENABLETARGET = 1" and are `woclr`. A bench controller drives one START,
address 0x2C, one data byte and STOP on the instance 0 pads, first with the
target disabled (the flags stay clear) and then enabled (both set). The flags
read set on repeated reads, and each clears only on its own written one. Which
disable the record survives is SF-016: the values after `CTRL = 0` are logged
and never compared.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ENABLETARGET,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CTRL,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_TARGET_ID,
    I2C0_TIMING0,
    I2C0_TIMING1,
    I2C0_TIMING2,
    I2C0_TIMING3,
    I2C0_TIMING4,
    I2C0_WRAP_CTRL,
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)


def _i2c0(register: str) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", 0)


I2C0_INTR_STATE = _i2c0("INTR_STATE")
I2C0_TARGET_EVENTS = _i2c0("TARGET_EVENTS")

START_DETECT = _i2c_u32("I2C__TARGET_EVENTS__START_DETECT_bm")
STOP_DETECT = _i2c_u32("I2C__TARGET_EVENTS__STOP_DETECT_bm")
BOTH = START_DETECT | STOP_DETECT
TX_STRETCH = _i2c_u32("I2C__INTR_STATE__TX_STRETCH_bm")
ACQRST = _i2c_u32("I2C__FIFO_CTRL__ACQRST_bm")

TARGET_ADDR = 0x2C
PAYLOAD = bytes((0x4D,))
VIP_SPEED = 2_000_000
RETAIN_WAIT_CYCLES = 256
FLAG_POLL_READS = 40
FENCE_TERMS = ["S1", "S2", "S3", "S4", "S5"]
FENCE_CHECKERS = {
    "S2": "CHK-I2C-TGT-FLAG-DISABLED-NOSET",
    "S3": "CHK-I2C-TGT-FLAG-SET",
    "S4": "CHK-I2C-TGT-FLAG-STICKY-W1C",
    "S5": "CHK-I2C-TGT-FLAG-DISABLE-RETAIN-OBS",
}


class smc_i2c_target_event_flags_test_seq(SmcCsrSeq):
    """Drive a bench transfer at I2C0 with the target off and on and read TARGET_EVENTS."""

    def __init__(self, name: str = "smc_i2c_target_event_flags_test_seq") -> None:
        super().__init__(name)
        self.fence: list[tuple[str, int]] = []
        self.printed: list[str] = []
        self.master: SmcI2cMasterVip | None = None

    def _step_done(self, step: str) -> None:
        self.fence.append((step, int(get_sim_time(unit="ps"))))

    def _chk(self, step: str, text: str) -> None:
        assert self.fence and self.fence[-1][0] == step, (
            f"{FENCE_CHECKERS[step]} would print before step {step} completed"
        )
        cocotb.log.info("%s: %s", FENCE_CHECKERS[step], text)
        self.printed.append(FENCE_CHECKERS[step])

    async def _events(self, label: str) -> int:
        value = await self.csr_read(label, I2C0_TARGET_EVENTS)
        assert 0 <= value <= 0xFFFF_FFFF, f"{label}: TARGET_EVENTS read 0x{value:x}"
        return value

    async def _bring_up(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_EVENT_FLAGS")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, 0)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "I2C0_TARGET_ID", I2C0_TARGET_ID, _pack_target_id(TARGET_ADDR, 0x7F, 0, 0)
        )
        await self.csr_write("EVENTS_CLR", I2C0_TARGET_EVENTS, BOTH)
        events = await self._events("EVENTS_ENTRY")
        assert not events & BOTH, f"TARGET_EVENTS=0x{events:08x} after clearing both flags"
        self.master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_event_flags_master")

    async def _transfer(self) -> None:
        await self.master.write(TARGET_ADDR, PAYLOAD)
        await self.wait_i2c_bus_released("I2C0_EVENT_FLAGS_IDLE")

    async def _wait_both_set(self, label: str) -> int:
        events = 0
        for n in range(FLAG_POLL_READS):
            events = await self._events(f"{label}_{n}")
            if events & BOTH == BOTH:
                return events
        raise AssertionError(
            f"{label}: TARGET_EVENTS=0x{events:08x} after {FLAG_POLL_READS} reads following "
            f"a transfer to 0x{TARGET_ADDR:02x} with ENABLETARGET set; both flags must be set"
        )

    async def _unrelated_reads(self, label: str) -> None:
        for n, addr in enumerate((I2C0_INTR_STATE, I2C0_CTRL, I2C0_TARGET_ID, I2C0_TIMING0) * 2):
            await self.csr_read(f"{label}_{n}", addr)

    async def _s2(self) -> None:
        nacked = False
        try:
            await self.master.write(TARGET_ADDR, PAYLOAD)
        except RuntimeError as exc:
            assert "NACK" in str(exc), f"bench write failed for a reason other than NACK: {exc}"
            nacked = True
        assert nacked, "the bench write was acknowledged with the target disabled"
        await self.wait_i2c_bus_released("I2C0_EVENT_FLAGS_IDLE_OFF")
        first = await self._events("DISABLED_EVENTS_0")
        await self._unrelated_reads("DISABLED_UNREL")
        second = await self._events("DISABLED_EVENTS_1")
        assert not (first | second) & BOTH, (
            f"TARGET_EVENTS read 0x{first:08x} and 0x{second:08x} after a transfer with "
            f"ENABLETARGET clear; START_DETECT and STOP_DETECT set only while it is 1"
        )
        self._step_done("S2")
        self._chk(
            "S2",
            f"address 0x{TARGET_ADDR:02x} NACKed with ENABLETARGET clear; TARGET_EVENTS "
            f"read 0x{first:08x} then 0x{second:08x}, START_DETECT and STOP_DETECT both 0",
        )

    async def _s3(self) -> None:
        await self.csr_write("I2C0_CTRL_TARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)
        await self._transfer()
        events = await self._wait_both_set("SET_EVENTS")
        self._step_done("S3")
        self._chk(
            "S3",
            f"transfer to 0x{TARGET_ADDR:02x} data 0x{PAYLOAD[0]:02x} with ENABLETARGET set; "
            f"TARGET_EVENTS=0x{events:08x} START_DETECT=1 STOP_DETECT=1 "
            f"(lifecycle set=transfer observed=both-1)",
        )

    async def _s4(self) -> None:
        first = await self._events("STICKY_READ_0")
        await self._unrelated_reads("STICKY_UNREL")
        second = await self._events("STICKY_READ_1")
        assert first & BOTH == BOTH and second & BOTH == BOTH, (
            f"TARGET_EVENTS read 0x{first:08x} then 0x{second:08x}; reads must not clear "
            f"START_DETECT or STOP_DETECT"
        )
        await self.csr_write("START_W1C", I2C0_TARGET_EVENTS, START_DETECT)
        after_start = await self._events("AFTER_START_W1C")
        assert not after_start & START_DETECT and after_start & STOP_DETECT, (
            f"after START_DETECT's written one TARGET_EVENTS reads 0x{after_start:08x}; "
            f"START_DETECT must clear and STOP_DETECT stay set"
        )
        await self.csr_write("STOP_W1C", I2C0_TARGET_EVENTS, STOP_DETECT)
        after_stop = await self._events("AFTER_STOP_W1C")
        assert not after_stop & BOTH, (
            f"after STOP_DETECT's written one TARGET_EVENTS reads 0x{after_stop:08x}"
        )
        self._step_done("S4")
        self._chk(
            "S4",
            f"reads 0x{first:08x} and 0x{second:08x} around 8 unrelated reads both set; "
            f"START_DETECT written one -> 0x{after_start:08x}; STOP_DETECT written one -> "
            f"0x{after_stop:08x} (lifecycle set/observed/cleared/checked_cleared)",
        )

    async def _s5(self) -> None:
        await self._transfer()
        await self._wait_both_set("RETAIN_SET")
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        ev0 = await self._events("RETAIN_EVENTS_0")
        st0 = await self.csr_read("RETAIN_INTR_STATE_0", I2C0_INTR_STATE)
        await ClockCycles(cocotb.top.clk_smc_i, RETAIN_WAIT_CYCLES)
        ev1 = await self._events("RETAIN_EVENTS_1")
        st1 = await self.csr_read("RETAIN_INTR_STATE_1", I2C0_INTR_STATE)
        await self.csr_write("RETAIN_W1C", I2C0_TARGET_EVENTS, BOTH)
        ev2 = await self._events("RETAIN_EVENTS_2")
        await self.csr_write("ACQ_RESET", I2C0_FIFO_CTRL, ACQRST)
        self._step_done("S5")
        self._chk(
            "S5",
            f"after CTRL=0 TARGET_EVENTS=0x{ev0:08x} TX_STRETCH={int(bool(st0 & TX_STRETCH))}; "
            f"{RETAIN_WAIT_CYCLES} clk_smc_i cycles later TARGET_EVENTS=0x{ev1:08x} "
            f"TX_STRETCH={int(bool(st1 & TX_STRETCH))}; after both written ones "
            f"TARGET_EVENTS=0x{ev2:08x}; observed, none compared (SF-016)",
        )

    async def body(self) -> None:
        await self._bring_up()
        self._step_done("S1")
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        order = [t for t, _ in self.fence]
        stamps = [s for _, s in self.fence]
        assert order == FENCE_TERMS, f"fence order {order}, expected {FENCE_TERMS}"
        assert all(a < b for a, b in zip(stamps, stamps[1:])), f"fence stamps {stamps}"
        assert self.printed == [FENCE_CHECKERS[s] for s in FENCE_TERMS[1:]], self.printed
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(order),
            ",".join(self.printed),
            stamps,
        )
