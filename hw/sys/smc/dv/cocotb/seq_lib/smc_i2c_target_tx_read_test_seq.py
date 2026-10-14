# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target transmit path: TXDATA to SDA, automatic and software TX stretch.

Sources: hw/ip/i2c/regs/i2c.rdl (TXDATA, CTRL.TX_STRETCH_CTRL_EN, TARGET_EVENTS.TX_PENDING,
INTR_STATE.TX_STRETCH, FIFO_CTRL.TXRST, STATUS.TXEMPTY, TARGET_FIFO_STATUS.TXLVL).

Software loads TXDATA on I2C0 and the bench controller on the I2C0 pads reads from the
target at 0x23 (and 0x35 for pair 1). A monitor counts the clk_smc_i cycles in which SCL is
low while the bench has released it, which only the DUT can cause. The mid-read empty FIFO,
FIFO_CTRL.TXRST during a hold and the repeated-READ clear sweep are owner value pending:
they are measured and logged, not compared.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLETARGET,
    I2C_CTRL_TX_STRETCH_CTRL_EN,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_INTR_ENABLE_TX_STRETCH,
    I2C_INTR_STATE_TX_STRETCH,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_TXEMPTY,
    I2C_TARGET_EVENTS_TX_PENDING,
    I2C_TARGET_FIFO_STATUS_TXLVL_BM,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_slot_utils import drive_to_slot, release_bus
from .smc_i2c_target_acq_stretch_test_seq import SclStretchMonitor
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

I2C0 = 0
ADDR0 = 0x23
ADDR1 = 0x35
VIP_SPEED = 2_000_000
EVENTS_BITS_2_0 = 0x7

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
_REGS = {
    "wrap": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR",
    "ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_BASE_ADDR",
    "status": "SMC_TOP_SMC_I2C_WRAP_I2C_STATUS_BASE_ADDR",
    "fifo_ctrl": "SMC_TOP_SMC_I2C_WRAP_I2C_FIFO_CTRL_BASE_ADDR",
    "target_id": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_ID_BASE_ADDR",
    "txdata": "SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR",
    "fifo_status": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_FIFO_STATUS_BASE_ADDR",
    "events": "SMC_TOP_SMC_I2C_WRAP_I2C_TARGET_EVENTS_BASE_ADDR",
    "intr_state": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR",
    "intr_enable": "SMC_TOP_SMC_I2C_WRAP_I2C_INTR_ENABLE_BASE_ADDR",
    "timing0": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING0_BASE_ADDR",
    "timing1": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING1_BASE_ADDR",
    "timing2": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING2_BASE_ADDR",
    "timing3": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING3_BASE_ADDR",
    "timing4": "SMC_TOP_SMC_I2C_WRAP_I2C_TIMING4_BASE_ADDR",
}
R = {key: smc_indexed_addr(sym, I2C0) for key, sym in _REGS.items()}

CTRL_AUTO = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
CTRL_SOFT = CTRL_AUTO | I2C_CTRL_TX_STRETCH_CTRL_EN

MIN_HOLD_SAMPLES = 16
HOLD_WINDOWS = 64
HOLD_WINDOW_CYCLES = 200
READ_WINDOWS = 400
READ_WINDOW_CYCLES = 500
POLL_LIMIT = 600
POLL_GAP_CYCLES = 20
BUS_RELEASE_POLLS = 2000
BUS_RELEASE_STEP = 4

FENCE_ORDER = [f"S{n}" for n in range(1, 11)]
CHECKER_AFTER = {
    "CHK-I2C-TGT-TX-READ-ORDER": "S4",
    "CHK-I2C-TGT-TX-READ-RESIDUE": "S3",
    "CHK-I2C-TGT-TX-AUTO-STRETCH": "S5",
    "CHK-I2C-TGT-TX-AUTO-MIDREAD-LOG": "S6",
    "CHK-I2C-TGT-TX-TXRST-STRETCH-LOG": "S7",
    "CHK-I2C-TGT-TX-TXRST-RECOVER": "S7",
    "CHK-I2C-TGT-TX-SW-STRETCH": "S8",
    "CHK-I2C-TGT-TX-SW-RESET-RELOAD": "S9",
    "CHK-I2C-TGT-TX-SW-RACE-LOG": "S10",
    "CHK-TIMEOUT-PATHS": "S10",
}
RACE_CASES = [("addr", 7), ("addrack", 0), ("data", 0)]


class _RunMonitor(SclStretchMonitor):
    """Hold monitor that counts a sample only when the previous sample was held too.

    The bench releases its SCL pull at a timer event that can share a timestep with a
    clk_smc_i edge, where the pull net already reads released while the resolved bus still
    reads low. That one-sample mismatch is not a DUT hold, so a run of n consecutive held
    samples counts n - 1 and the single-sample runs are tallied in ``glitches``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.runs: list[tuple[int, int]] = []
        self.glitches = 0

    async def _run(self) -> None:
        dut = cocotb.top
        streak = 0
        while True:
            await ClockCycles(dut.clk_smc_i, 1)
            bus = dut.tb_i2c0_scl.value
            pull = dut.tb_i2c0_scl_ext_low.value
            if not (bus.is_resolvable and pull.is_resolvable):
                continue
            self.samples += 1
            if int(bus) == 0 and int(pull) == 0:
                streak += 1
                if streak == 1:
                    self.runs.append((int(get_sim_time("ns")), 0))
                    self.glitches += 1
                else:
                    self.held += 1
                    if streak == 2:
                        self.glitches -= 1
                self.runs[-1] = (self.runs[-1][0], streak)
            else:
                streak = 0


class _Read:
    """Progress of one bench controller read."""

    def __init__(self) -> None:
        self.ack: int | None = None
        self.data: list[int] = []
        self.task = None

    @property
    def done(self) -> bool:
        return self.task is not None and self.task.done()


class smc_i2c_target_tx_read_test_seq(SmcCsrSeq):
    """Load the I2C0 target TX FIFO and read it from the bench controller."""

    def __init__(self, name: str = "smc_i2c_target_tx_read_test_seq") -> None:
        super().__init__(name)
        self.monitor: _RunMonitor | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.vips = 0

    # ------------------------------------------------------------ plumbing --
    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))
        cocotb.log.info("FENCE %s @ %dps", term, self.stamps[-1][1])

    def _chk(self, name: str, line: str) -> None:
        self.chk_lines.append((name, line, len(self.stamps)))

    @staticmethod
    async def _cycles(count: int) -> None:
        await ClockCycles(cocotb.top.clk_smc_i, count)

    @staticmethod
    def _probe(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value)

    def _irq0(self) -> int:
        return self._probe("tb_i2c_irq") & 1

    def _pad_levels(self) -> str:
        names = ("scl", "sda", "scl_dut_low", "sda_dut_low")
        return " ".join(f"{n}={self._probe(f'tb_i2c0_{n}')}" for n in names)

    def _held(self) -> int:
        return self.monitor.held if self.monitor else 0

    def _vip(self) -> SmcI2cMasterVip:
        self.vips += 1
        return SmcI2cMasterVip(speed=VIP_SPEED, name=f"smc_i2c0_tx_read_master{self.vips}")

    async def _diag(self) -> str:
        status = await self.csr_read("DIAG_STATUS", R["status"])
        events = await self.csr_read("DIAG_EVENTS", R["events"])
        fifo = await self.csr_read("DIAG_FIFO_STATUS", R["fifo_status"])
        intr = await self.csr_read("DIAG_INTR_STATE", R["intr_state"])
        mon = (
            f"hold={self.monitor.held} samples={self.monitor.samples} "
            f"single-sample glitches={self.monitor.glitches}"
            if self.monitor
            else "-"
        )
        return (
            f"STATUS=0x{status:08x} TARGET_EVENTS=0x{events:08x} TARGET_FIFO_STATUS=0x{fifo:08x} "
            f"INTR_STATE=0x{intr:08x} {self._pad_levels()} monitor {mon}"
        )

    async def _poll(self, name: str, windows: int, gap: int, probe) -> None:
        """Run ``probe`` up to ``windows`` times ``gap`` cycles apart; expiry fails the leaf."""
        bound = f"{windows}x{gap}cyc clk_smc_i"
        state = "never sampled"
        for _ in range(windows):
            done, state = await probe()
            if done:
                self.waits.append((name, bound, state))
                return
            await self._cycles(gap)
        self.waits.append((name, bound, f"EXPIRED {state}"))
        diag = await self._diag()
        raise AssertionError(f"{name}: not satisfied within {bound}; last {state}; {diag}")

    async def _wait_read(self, name: str, rd: _Read) -> None:
        async def probe() -> tuple[bool, str]:
            if rd.done:
                rd.task.result()
            return rd.done, f"ack={rd.ack} bytes={len(rd.data)} done={rd.done}"

        await self._poll(name, READ_WINDOWS, READ_WINDOW_CYCLES, probe)

    async def _wait_hold(self, name: str, rd: _Read, base: int) -> int:
        async def probe() -> tuple[bool, str]:
            held = self._held() - base
            assert not rd.done, (
                f"{name}: the read completed with {held} hold samples before the TX FIFO was "
                f"loaded; {await self._diag()}"
            )
            return held >= MIN_HOLD_SAMPLES, f"hold={held} bytes={len(rd.data)} done={rd.done}"

        await self._poll(name, HOLD_WINDOWS, HOLD_WINDOW_CYCLES, probe)
        return self._held() - base

    async def _run_read(self, rd: _Read, vip, addr7: int, count: int, stop: bool) -> None:
        await vip.send_start()
        rd.ack = await vip.send_byte(((addr7 & 0x7F) << 1) | 1)
        if rd.ack:
            await vip.send_stop()
            return
        for i in range(count):
            rd.data.append(await vip.recv_byte(ack=(i != count - 1)))
        if stop:
            await vip.send_stop()

    @staticmethod
    async def _finish_read(rd: _Read, vip: SmcI2cMasterVip) -> None:
        rd.data.append(await vip.recv_byte(ack=False))
        await vip.send_stop()

    def _start_read(
        self, addr7: int, count: int, stop: bool = True
    ) -> tuple[_Read, SmcI2cMasterVip]:
        rd = _Read()
        vip = self._vip()
        rd.task = cocotb.start_soon(self._run_read(rd, vip, addr7, count, stop))
        return rd, vip

    async def _acq_reset(self, label: str) -> None:
        await self.csr_write(f"{label}_ACQRST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST)

    async def _read(self, name: str, addr7: int, count: int) -> _Read:
        await self._acq_reset(name)
        rd, _ = self._start_read(addr7, count)
        await self._wait_read(name, rd)
        assert rd.ack == 0, f"{name}: the address 0x{addr7:02x} read was NACKed (ack={rd.ack})"
        return rd

    async def _load(self, label: str, data) -> None:
        for i, byte in enumerate(data):
            await self.csr_write(f"{label}_TXDATA{i}", R["txdata"], byte)

    async def _clean(self, label: str) -> None:
        await self.csr_write(
            f"{label}_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(f"{label}_PENDING_CLR", R["events"], I2C_TARGET_EVENTS_TX_PENDING)

    async def _fifo_state(self, label: str) -> tuple[int, int]:
        status = await self.csr_read(f"{label}_STATUS", R["status"])
        fifo = await self.csr_read(f"{label}_FIFO_STATUS", R["fifo_status"])
        return int(bool(status & I2C_STATUS_TXEMPTY)), fifo & I2C_TARGET_FIFO_STATUS_TXLVL_BM

    async def _pending(self, label: str) -> int:
        events = await self.csr_read(label, R["events"])
        return events & I2C_TARGET_EVENTS_TX_PENDING

    async def _wait_pending(self, name: str) -> None:
        async def probe() -> tuple[bool, str]:
            events = await self.csr_read(f"{name}_EVENTS", R["events"])
            return bool(events & I2C_TARGET_EVENTS_TX_PENDING), f"events=0x{events:08x}"

        await self._poll(name, POLL_LIMIT, POLL_GAP_CYCLES, probe)

    # ---------------------------------------------------------------- steps --
    async def _s1_setup(self) -> None:
        seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.rng = random.Random(seed)
        cocotb.log.info("S1: payload seed=%d", seed)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.arm_i2c_gpio_lsio(0, "I2C0_TX_READ")
        await self.csr_write("I2C0_WRAP_TARGET", R["wrap"], I2C_WRAP_CTRL_TARGET)

        async def released() -> tuple[bool, str]:
            scl = self._probe("tb_i2c0_scl")
            sda = self._probe("tb_i2c0_sda")
            scl_i = self._probe("tb_i2c0_scl_i")
            return (scl, sda, scl_i) == (1, 1, 1), f"scl={scl} sda={sda} scl_i={scl_i}"

        await self._poll("bus_released", BUS_RELEASE_POLLS, BUS_RELEASE_STEP, released)
        await self.csr_write("I2C0_TIMING0", R["timing0"], _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", R["timing1"], _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", R["timing2"], _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", R["timing3"], _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", R["timing4"], _pack_timing4(4, 5))
        await self.csr_write(
            "I2C0_FIFO_RST", R["fifo_ctrl"], I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "I2C0_TARGET_ID", R["target_id"], _pack_target_id(ADDR0, 0x7F, ADDR1, 0x7F)
        )
        await self.csr_write("I2C0_CTRL_AUTO", R["ctrl"], CTRL_AUTO)
        events = await self.csr_read("S1_EVENTS", R["events"])
        assert events & EVENTS_BITS_2_0 == 0, f"S1: TARGET_EVENTS bits 2:0 read 0x{events:08x}"
        status = await self.csr_read("S1_STATUS", R["status"])
        assert status & I2C_STATUS_ACQEMPTY, f"S1: STATUS.ACQEMPTY clear (0x{status:08x})"
        assert status & I2C_STATUS_TXEMPTY, f"S1: STATUS.TXEMPTY clear (0x{status:08x})"
        levels = self._pad_levels()
        assert self._probe("tb_i2c0_scl") == 1 and self._probe("tb_i2c0_sda") == 1, levels
        assert self._probe("tb_i2c0_sda_dut_low") == 0, f"S1: the DUT pulls SDA low; {levels}"
        cocotb.log.info("S1: instance 0 target enabled; STATUS=0x%08x %s", status, levels)
        self._stamp("S1")

    async def _s2_read_order(self) -> str:
        await self._clean("S2")
        await self.csr_write("S2A_TXDATA", R["txdata"], 0xA5)
        a = await self._read("s2a_read", ADDR0, 1)
        assert a.data == [0xA5], f"S2a: read {[hex(b) for b in a.data]}, wrote 0xa5"
        length = self.rng.randint(2, 12)
        payload = [self.rng.randrange(256) for _ in range(length)]
        await self._load("S2B", payload)
        b = await self._read("s2b_read", ADDR0, length)
        assert b.data == payload, (
            f"S2b: read {bytes(b.data).hex()} for payload {bytes(payload).hex()}"
        )
        await self.csr_write("S2C_TXDATA", R["txdata"], 0x3C)
        c = await self._read("s2c_read", ADDR1, 1)
        assert c.data == [0x3C], f"S2c: pair 1 read {[hex(x) for x in c.data]}, wrote 0x3c"
        self._stamp("S2")
        return (
            f"a=0x{a.data[0]:02x} ack={a.ack}; b length={length} bytes={bytes(b.data).hex()} "
            f"ack={b.ack}; c=0x{c.data[0]:02x} ack={c.ack}"
        )

    async def _s3_residue(self) -> None:
        await self._clean("S3")
        await self._load("S3", range(0x10, 0x16))
        rd = await self._read("s3_read", ADDR0, 2)
        assert rd.data == [0x10, 0x11], f"S3: read {[hex(b) for b in rd.data]}"
        empty, level = await self._fifo_state("S3_AFTER_READ")
        assert empty == 0, f"S3: STATUS.TXEMPTY=1 with six bytes loaded and two read (lvl={level})"
        assert level >= 1, f"S3: TXLVL={level} with six bytes loaded and two read"
        await self.csr_write("S3_TXRST", R["fifo_ctrl"], I2C_FIFO_CTRL_TXRST)
        empty_after, level_after = await self._fifo_state("S3_AFTER_TXRST")
        assert empty_after == 1, f"S3: STATUS.TXEMPTY={empty_after} after TXRST"
        assert level_after == 0, f"S3: TXLVL={level_after} after TXRST"
        self._stamp("S3")
        self._chk(
            "CHK-I2C-TGT-TX-READ-RESIDUE",
            f"bytes read {bytes(rd.data).hex()} == 1011; after the read TXEMPTY={empty} "
            f"TXLVL={level} (>=1, residue logged); after TXRST TXEMPTY={empty_after} "
            f"TXLVL={level_after}",
        )

    async def _s4_load_during_read(self, s2_text: str) -> None:
        await self._clean("S4")
        await self._load("S4A", [0x71, 0x72])
        rd, _ = self._start_read(ADDR0, 4)
        seen = [0]

        async def probe() -> tuple[bool, str]:
            fifo = await self.csr_read("S4_FIFO_STATUS", R["fifo_status"])
            seen[0] = fifo & I2C_TARGET_FIFO_STATUS_TXLVL_BM
            assert not rd.done, f"S4: the read finished before TXLVL fell below 2 (lvl={seen[0]})"
            return seen[0] < 2, f"txlvl={seen[0]} bytes={len(rd.data)}"

        await self._poll("s4_txlvl_below_2", POLL_LIMIT, POLL_GAP_CYCLES, probe)
        await self._load("S4B", [0x73, 0x74])
        await self._wait_read("s4_read", rd)
        assert rd.ack == 0, f"S4: the address was NACKed (ack={rd.ack})"
        assert rd.data == [0x71, 0x72, 0x73, 0x74], f"S4: read {bytes(rd.data).hex()}"
        self._stamp("S4")
        self._chk(
            "CHK-I2C-TGT-TX-READ-ORDER",
            f"S2 {s2_text}; S4 bytes read {bytes(rd.data).hex()} == 71727374 with TXDATA "
            f"73 74 written at TXLVL={seen[0]}; every address ack bit 0",
        )

    async def _s5_auto_stretch(self) -> None:
        await self._clean("S5")
        self.monitor = _RunMonitor()
        self.monitor.start()
        base = self._held()
        rd, _ = self._start_read(ADDR0, 1)
        held = await self._wait_hold("s5_empty_hold", rd, base)
        complete_before = int(rd.done)
        await self.csr_write("S5_TXDATA_3C", R["txdata"], 0x3C)
        await self._wait_read("s5_empty_read", rd)
        assert rd.ack == 0 and rd.data == [0x3C], f"S5: empty read {rd.ack} {rd.data}"
        await self.csr_write("S5_TXDATA_3D", R["txdata"], 0x3D)
        await self._acq_reset("S5_LOADED")
        base2 = self._held()
        runs2 = len(self.monitor.runs)
        rd2, _ = self._start_read(ADDR0, 1)
        await self._wait_read("s5_loaded_read", rd2)
        held2 = self._held() - base2
        assert rd2.ack == 0 and rd2.data == [0x3D], f"S5: loaded read {rd2.ack} {rd2.data}"
        assert held2 < MIN_HOLD_SAMPLES, (
            f"S5: loaded read showed {held2} hold samples; (start ns, length) runs "
            f"{self.monitor.runs[runs2:]}; read started near {int(get_sim_time('ns'))} ns end"
        )
        events = await self.csr_read("S5_EVENTS", R["events"])
        assert events & EVENTS_BITS_2_0 == 0, f"S5: TARGET_EVENTS=0x{events:08x} in automatic mode"
        self._stamp("S5")
        self._chk(
            "CHK-I2C-TGT-TX-AUTO-STRETCH",
            f"empty read hold samples {held} (>=16), complete before TXDATA={complete_before}, "
            f"byte 0x{rd.data[0]:02x}; loaded read hold samples {held2} (<16), byte "
            f"0x{rd2.data[0]:02x}; TARGET_EVENTS=0x{events:08x} bits 2:0 = {events & 7}",
        )

    async def _s6_midread(self) -> None:
        await self._clean("S6")
        await self.csr_write("S6_TXDATA_41", R["txdata"], 0x41)
        rd, _ = self._start_read(ADDR0, 2)

        async def probe() -> tuple[bool, str]:
            if rd.done:
                rd.task.result()
            return len(rd.data) >= 1 or rd.done, f"bytes={len(rd.data)} done={rd.done}"

        await self._poll("s6_first_byte", READ_WINDOWS, READ_WINDOW_CYCLES, probe)
        base = self._held()
        for _ in range(HOLD_WINDOWS):
            await self._cycles(HOLD_WINDOW_CYCLES)
        self.waits.append(
            ("s6_hold_windows", f"{HOLD_WINDOWS}x{HOLD_WINDOW_CYCLES}cyc clk_smc_i", "elapsed")
        )
        held = self._held() - base
        complete_before = int(rd.done)
        await self.csr_write("S6_TXDATA_42", R["txdata"], 0x42)
        await self._wait_read("s6_read", rd)
        self._stamp("S6")
        self._chk(
            "CHK-I2C-TGT-TX-AUTO-MIDREAD-LOG",
            f"hold samples after the first byte={held}; bytes read={bytes(rd.data).hex()}; "
            f"read complete before the second TXDATA write={complete_before}; ack={rd.ack}; "
            f"no compare (owner value pending)",
        )

    async def _s7_txrst_hold(self) -> None:
        await self._clean("S7")
        base = self._held()
        rd, _ = self._start_read(ADDR0, 1)
        held = await self._wait_hold("s7_empty_hold", rd, base)
        await self.csr_write("S7_TXRST_HOLD", R["fifo_ctrl"], I2C_FIFO_CTRL_TXRST)
        await self.csr_write("S7_TXDATA_55", R["txdata"], 0x55)
        await self._wait_read("s7_first_read", rd)
        levels = self._pad_levels()
        await self.csr_write("S7_TXRST_CLEAN", R["fifo_ctrl"], I2C_FIFO_CTRL_TXRST)
        await self.csr_write("S7_TXDATA_56", R["txdata"], 0x56)
        clean = await self._read("s7_clean_read", ADDR0, 1)
        assert clean.data == [0x56], f"S7: clean read {[hex(b) for b in clean.data]}"
        self._stamp("S7")
        self._chk(
            "CHK-I2C-TGT-TX-TXRST-STRETCH-LOG",
            f"TXRST written after {held} hold samples; read complete=1 ack={rd.ack} "
            f"bytes={bytes(rd.data).hex()}; final bus {levels}; no compare (owner value pending)",
        )
        self._chk(
            "CHK-I2C-TGT-TX-TXRST-RECOVER",
            f"after TXRST and TXDATA=56 a one-byte read returned 0x{clean.data[0]:02x} with "
            f"address ack={clean.ack}",
        )

    async def _s8_soft_stretch(self) -> None:
        await self._clean("S8")
        await self.csr_write("S8_CTRL_SOFT", R["ctrl"], CTRL_SOFT)
        await self.csr_write("S8_INTR_EN", R["intr_enable"], I2C_INTR_ENABLE_TX_STRETCH)
        await self.csr_write("S8_TXDATA", R["txdata"], 0x5D)
        base = self._held()
        rd, _ = self._start_read(ADDR0, 1)
        await self._wait_pending("s8_tx_pending")
        events = await self.csr_read("S8_EVENTS_HELD", R["events"])
        intr = await self.csr_read("S8_INTR_HELD", R["intr_state"])
        irq = self._irq0()
        assert events & I2C_TARGET_EVENTS_TX_PENDING, f"S8: TX_PENDING clear (0x{events:08x})"
        assert intr & I2C_INTR_STATE_TX_STRETCH, f"S8: INTR_STATE.TX_STRETCH clear (0x{intr:08x})"
        assert irq == 1, "S8: tb_i2c_irq[0] reads 0 with TX_STRETCH pending and enabled"
        held = await self._wait_hold("s8_hold", rd, base)
        assert not rd.done, "S8: the read completed before TX_PENDING was cleared"
        await self.csr_write("S8_PENDING_CLR", R["events"], I2C_TARGET_EVENTS_TX_PENDING)
        await self._wait_read("s8_read", rd)
        events2 = await self.csr_read("S8_EVENTS_CLR", R["events"])
        intr2 = await self.csr_read("S8_INTR_CLR", R["intr_state"])
        irq2 = self._irq0()
        assert rd.ack == 0 and rd.data == [0x5D], f"S8: read {rd.ack} {rd.data}"
        assert events2 & I2C_TARGET_EVENTS_TX_PENDING == 0, f"S8: TX_PENDING set 0x{events2:08x}"
        assert intr2 & I2C_INTR_STATE_TX_STRETCH == 0, f"S8: TX_STRETCH set 0x{intr2:08x}"
        assert irq2 == 0, "S8: tb_i2c_irq[0] reads 1 after the clear"
        self._stamp("S8")
        self._chk(
            "CHK-I2C-TGT-TX-SW-STRETCH",
            f"set: READ address with TX_STRETCH_CTRL_EN=1; observed: TX_PENDING=1 "
            f"INTR_STATE.TX_STRETCH=1 irq0={irq} hold samples {held} read incomplete; cleared: "
            f"W1 TX_PENDING; checked_cleared: TX_PENDING=0 TX_STRETCH=0 irq0={irq2}; byte "
            f"0x{rd.data[0]:02x}",
        )

    async def _s9_reset_reload(self) -> None:
        await self._clean("S9")
        await self.csr_write("S9_TXDATA_11", R["txdata"], 0x11)
        rd, _ = self._start_read(ADDR0, 1)
        await self._wait_pending("s9_tx_pending")
        await self.csr_write("S9_TXRST", R["fifo_ctrl"], I2C_FIFO_CTRL_TXRST)
        empty, level = await self._fifo_state("S9_AFTER_TXRST")
        assert empty == 1, f"S9: STATUS.TXEMPTY={empty} after TXRST"
        assert level == 0, f"S9: TXLVL={level} after TXRST"
        await self.csr_write("S9_TXDATA_22", R["txdata"], 0x22)
        await self.csr_write("S9_PENDING_CLR", R["events"], I2C_TARGET_EVENTS_TX_PENDING)
        await self._wait_read("s9_read", rd)
        assert rd.ack == 0 and rd.data == [0x22], f"S9: read {rd.ack} {rd.data}"
        self._stamp("S9")
        self._chk(
            "CHK-I2C-TGT-TX-SW-RESET-RELOAD",
            f"after TXRST while TX_PENDING set TXEMPTY={empty} TXLVL={level}; byte read "
            f"0x{rd.data[0]:02x} (not 0x11)",
        )

    async def _s10_race_sweep(self) -> None:
        rows = []
        for phase, k in RACE_CASES:
            case = f"{phase}{k}"
            await self._clean(f"S10_{case}")
            await self._load(f"S10_{case}", [0x61, 0x62])
            rd, vip = self._start_read(ADDR0, 1, stop=False)
            await self._wait_pending(f"s10_{case}_first_pending")
            await self.csr_write(f"S10_{case}_FIRST_CLR", R["events"], I2C_TARGET_EVENTS_TX_PENDING)
            await self._wait_read(f"s10_{case}_first_read", rd)
            park = cocotb.start_soon(drive_to_slot(vip, ADDR0, 0, phase, k, read=True))
            if phase == "addr":

                async def parked() -> tuple[bool, str]:
                    if park.done():
                        park.result()
                    return park.done(), f"parked={park.done()}"

                await self._poll(f"s10_{case}_parked", READ_WINDOWS, READ_WINDOW_CYCLES, parked)
                pending_seen = await self._pending(f"S10_{case}_PENDING_PARKED")
            else:
                await self._wait_pending(f"s10_{case}_pending")
                pending_seen = 1
            await self.csr_write(f"S10_{case}_CLR", R["events"], I2C_TARGET_EVENTS_TX_PENDING)
            bit0 = await self._pending(f"S10_{case}_EVENTS_AFTER")

            async def finished() -> tuple[bool, str]:
                if park.done():
                    park.result()
                return park.done(), f"done={park.done()}"

            await self._poll(f"s10_{case}_complete", READ_WINDOWS, READ_WINDOW_CYCLES, finished)
            tail = _Read()
            if phase != "addr":
                await self._acq_reset(f"S10_{case}_TAIL")
                tail.task = cocotb.start_soon(self._finish_read(tail, vip))
                await self._wait_read(f"s10_{case}_tail", tail)
            await release_bus(vip)
            rows.append(
                f"{case}: first byte {bytes(rd.data).hex()} ack={rd.ack}, TX_PENDING before "
                f"clear={pending_seen}, after clear={bit0}, parked read complete=1, byte after "
                f"release {bytes(tail.data).hex() or 'none'}"
            )
        self._stamp("S10")
        self._chk(
            "CHK-I2C-TGT-TX-SW-RACE-LOG",
            "; ".join(rows) + "; no same-cycle claim, no compare (owner value pending)",
        )

    # --------------------------------------------------------------- tokens --
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
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(waits)} bounded waits, each raising AssertionError with its last state on "
            f"expiry; " + "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
        )

    def _emit_checks(self) -> None:
        order = [term for term, _ in self.stamps]
        assert order == FENCE_ORDER, f"fence order {order}, expected {FENCE_ORDER}"
        times = [ps for _, ps in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = {name: idx for name, _, idx in self.chk_lines}
        for name, term in CHECKER_AFTER.items():
            assert name in printed, f"{name} never recorded"
            assert printed[name] > order.index(term), f"{name} recorded before {term}"
        for name, line, _ in self.chk_lines:
            cocotb.log.info("%s: %s", name, line)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(f"{t}={ps}" for t, ps in self.stamps),
            ",".join(name for name, _, _ in self.chk_lines),
            ",".join(str(ps) for ps in times),
        )

    async def body(self) -> None:
        try:
            await self._s1_setup()
            s2_text = await self._s2_read_order()
            await self._s3_residue()
            await self._s4_load_during_read(s2_text)
            await self._s5_auto_stretch()
            await self._s6_midread()
            await self._s7_txrst_hold()
            await self._s8_soft_stretch()
            await self._s9_reset_reload()
            await self._s10_race_sweep()
        finally:
            if self.monitor is not None:
                self.monitor.stop()
        self._emit_timeout_paths()
        self._emit_checks()
