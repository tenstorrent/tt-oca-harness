# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded I2C bus matrix on the shared three-instance bus.

Sources: hw/ip/i2c/regs/i2c.rdl (CTRL, TARGET_ID, TARGET_ACK_CTRL, STATUS, FDATA, RDATA, ACQDATA,
CONTROLLER_EVENTS, FIFO_CTRL).

`+smc_i2c_shared_bus` joins I2C0, I2C1 and I2C2 on one open-drain bus that the bench observes on
the I2C0 pads. The seed draws the target address pair, the target instance of the address and
role legs, three ordered instance pairs with their lengths and read and write mixes, the NACK
controller, the lengths and positions of the two NACK writes, and the ACK-control pair, length and
held byte. Pinned on every seed beside the draw: the four slot and mask cells of `TARGET_ID` (each
address under a full mask and under a mask of 0), an address matching neither slot, the three
`CTRL` role settings, one write pair and one read pair, a NACK on a non-zero data byte with a
later byte after it, with `NAKOK` clear and set, and an ACK-control hold on data byte 0 beside the
drawn later byte.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, reg_reset_word, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_fw_i2c_wire_monitor import I2cWireFrame, SmcFwI2cWireMonitor
from .smc_i2c_ctrl_nack_modes_test_seq import _NthDataNackTarget
from .smc_i2c_field_masks import (
    _I2C_H,
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_RESTART,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ACK_CTRL_EN,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_STATUS_ACK_CTRL_STRETCH,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_TARGET_ACK_CTRL_NACK,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
    acq_abyte,
    acq_signal,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_u32
from .smc_i2c_protocol_vip import SmcI2cMasterVip
from .smc_i2c_target_smbus_test_seq import (
    _pack_target_id,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
FDATA_NAKOK = _i2c_u32("I2C__FDATA__NAKOK_bm")
EV_NACK = I2C_CONTROLLER_EVENTS_NACK
TARGET_ID_RESET = reg_reset_word(_I2C_H, "I2C", "TARGET_ID")
CTRL_RESET = reg_reset_word(_I2C_H, "I2C", "CTRL")
FIFO_ALL = I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST | I2C_FIFO_CTRL_RXRST_FMTRST

INSTANCES = (0, 1, 2)
ORDERED_PAIRS = tuple((c, t) for c in INSTANCES for t in INSTANCES if c != t)
FULL_MASK = _i2c_u32("I2C__TARGET_ID__MASK0_bm") >> _i2c_u32("I2C__TARGET_ID__MASK0_bp")
# i2c.rdl TARGET_ID: a full mask makes ADDRESSn the only match; a mask of 0 disables the slot.
MASK_CELLS = ((FULL_MASK, FULL_MASK), (FULL_MASK, 0), (0, FULL_MASK), (0, 0))
CTRL_TARGET = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN
CTRL_ACK_CONTROL = CTRL_TARGET | I2C_CTRL_ACK_CTRL_EN
ROLE_CELLS = (("CTRL 0", 0, 1), ("ENABLEHOST", I2C_CTRL_ENABLEHOST, 1), ("ENABLETARGET", None, 0))
# Bench write target of the NACK leg; the drawn addresses exclude it.
BENCH_NACK_ADDR = 0x12
# 7-bit addresses outside the reserved 0x00-0x07 and 0x78-0x7F groups.
ADDR_POOL = tuple(a for a in range(0x08, 0x78) if a != BENCH_NACK_ADDR)
MIXES = ("write", "read", "mixed")
PINNED_MIXES = ("write", "read")
LEN_MIN, LEN_MAX = 1, 4
NACK_LEN_MIN = 2
# The pinned NACK write NACKs a byte with a byte before it and a byte after it.
PIN_NACK_LEN_MIN = 3
VIP_SPEED = 2_000_000
VIP_SCL_BOUND_NS = 2_000_000

FUSE_SENSE_BOUND = 200_000
BUS_POLLS, BUS_STEP = 2000, 4
ACQ_POLLS, ACQ_STEP = 200, 50
ACQ_POP_LIMIT = 80
FLAT_READS, FLAT_GAP = 5, 100
IDLE_POLLS, IDLE_STEP = 800, 100
RX_POLLS, RX_STEP = 400, 50
EVENT_POLLS, EVENT_STEP = 800, 50
HOLD_POLLS, HOLD_STEP = 2000, 4

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_STEPS = (
    ("CHK-IBM-ADDR", "S2"),
    ("CHK-IBM-ROLE", "S3"),
    ("CHK-IBM-PAIR", "S4"),
    ("CHK-IBM-NAKOK", "S5"),
    ("CHK-IBM-ACKCTRL", "S6"),
)

Entry = tuple[int, int]


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _fmt(entries: list[Entry]) -> str:
    return "[" + " ".join(f"({s},0x{b:02x})" for s, b in entries) + "]"


def _hex(data: list[int]) -> str:
    return " ".join(f"{b:02x}" for b in data)


def draw(seed: int) -> dict:
    """Every drawn cell of one seed; the pinned cells are fixed around it."""
    rng = random.Random(seed)
    a0, a1, nomatch = rng.sample(ADDR_POOL, 3)
    passes = []
    for mix in PINNED_MIXES + (rng.choice(MIXES),):
        c, t = rng.choice(ORDERED_PAIRS)
        length = rng.randint(LEN_MIN, LEN_MAX)
        passes.append(
            {
                "c": c,
                "t": t,
                "mix": mix,
                "len": length,
                "wdata": [rng.randrange(256) for _ in range(length)],
                "tdata": [rng.randrange(256) for _ in range(length)],
            }
        )
    nack_len = rng.randint(NACK_LEN_MIN, LEN_MAX)
    pin_len = rng.randint(PIN_NACK_LEN_MIN, LEN_MAX)
    ack_pair = rng.choice(ORDERED_PAIRS)
    ack_len = rng.randint(NACK_LEN_MIN, LEN_MAX)
    return {
        "a0": a0,
        "a1": a1,
        "nomatch": nomatch,
        "addr_target": rng.choice(INSTANCES),
        "mask_order": rng.sample(MASK_CELLS, len(MASK_CELLS)),
        "addr_bytes": [rng.randrange(256) for _ in range(len(MASK_CELLS) * 3 + len(ROLE_CELLS))],
        "passes": passes,
        "nack_ctl": rng.choice(INSTANCES),
        "nack_len": nack_len,
        "pin_len": pin_len,
        "nack_pin": rng.randint(1, pin_len - 2),
        "pin_data": [rng.randrange(256) for _ in range(pin_len)],
        "nack_draw": rng.randint(0, nack_len - 1),
        "nack_data": [rng.randrange(256) for _ in range(nack_len)],
        "ack_ctl": ack_pair[0],
        "ack_tgt": ack_pair[1],
        "ack_len": ack_len,
        "ack_draw": rng.randint(1, ack_len - 1),
        "ack_data": [rng.randrange(256) for _ in range(ack_len)],
    }


def check_draw(d: dict) -> None:
    """The filters and the pinned cells the grading relies on."""
    used = {d["a0"], d["a1"], d["nomatch"], BENCH_NACK_ADDR}
    assert len(used) == 4, f"addresses not distinct: {d}"
    assert all(0x08 <= a <= 0x77 for a in (d["a0"], d["a1"], d["nomatch"])), d
    assert sorted(d["mask_order"]) == sorted(MASK_CELLS), d["mask_order"]
    mixes = [p["mix"] for p in d["passes"]]
    assert mixes[:2] == list(PINNED_MIXES) and mixes[2] in MIXES, mixes
    for p in d["passes"]:
        assert p["c"] != p["t"] and LEN_MIN <= p["len"] <= LEN_MAX, p
    assert NACK_LEN_MIN <= d["nack_len"] <= LEN_MAX and 0 <= d["nack_draw"] < d["nack_len"]
    assert PIN_NACK_LEN_MIN <= d["pin_len"] <= LEN_MAX, d["pin_len"]
    assert 1 <= d["nack_pin"] <= d["pin_len"] - 2, "pinned NACK byte without a later byte"
    assert d["ack_ctl"] != d["ack_tgt"] and 1 <= d["ack_draw"] < d["ack_len"]


class smc_i2c_bus_matrix_rand_test_seq(SmcCsrSeq):
    """Address, role, pair, NACK and ACK-control legs of one seed on the shared bus."""

    def __init__(self, name: str = "smc_i2c_bus_matrix_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.d: dict = {}
        self.wire: SmcFwI2cWireMonitor | None = None
        self.nack_target: _NthDataNackTarget | None = None
        self.vip: SmcI2cMasterVip | None = None
        self.frame_base = 0
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.byte_i = 0
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    @staticmethod
    def _bit(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} sampled X/Z ({value})"
        return int(value) & 1

    def _next_byte(self) -> int:
        byte = self.d["addr_bytes"][self.byte_i]
        self.byte_i += 1
        return byte

    def _frames(self, addr7: int) -> list[I2cWireFrame]:
        return [f for f in self.wire.frames[self.frame_base :] if f.addr7 == addr7]

    def _mark_frames(self) -> None:
        self.frame_base = len(self.wire.frames)

    async def _poll(self, name: str, polls: int, step: int, probe) -> None:
        """Run ``probe`` up to ``polls`` times ``step`` cycles apart; expiry fails the leaf."""
        state = "never sampled"
        bound = f"{polls}x{step} clk_smc_i"
        for _ in range(polls):
            done, state = await probe()
            if done:
                self.waits.append((name, bound, state))
                return
            await ClockCycles(cocotb.top.clk_smc_i, step)
        self.waits.append((name, bound, f"EXPIRED {state}"))
        raise AssertionError(f"{name}: not satisfied within {bound}; last {state}")

    async def _wait_bus_released(self, name: str) -> None:
        async def probe() -> tuple[bool, str]:
            scl, sda = self._bit("tb_i2c0_scl"), self._bit("tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll(name, BUS_POLLS, BUS_STEP, probe)

    # -- instance control -------------------------------------------------

    async def _disable(self, idx: int, label: str) -> None:
        await self.csr_write(f"{label}_I2C{idx}_CTRL_OFF", _reg("CTRL", idx), 0)

    async def _disable_all(self, label: str) -> None:
        for idx in INSTANCES:
            await self._disable(idx, label)

    async def _enable_target(
        self, idx: int, label: str, target_id: int, ctrl: int = CTRL_TARGET
    ) -> None:
        await self._disable(idx, label)
        await self.csr_write(f"{label}_TGT{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_TARGET)
        await self.csr_write(f"{label}_TGT{idx}_TARGET_ID", _reg("TARGET_ID", idx), target_id)
        await self.csr_write(f"{label}_TGT{idx}_FIFO", _reg("FIFO_CTRL", idx), FIFO_ALL)
        await self.csr_write(f"{label}_TGT{idx}_CTRL", _reg("CTRL", idx), ctrl)

    async def _enable_controller(self, idx: int, label: str) -> None:
        await self._disable(idx, label)
        await self.csr_write(f"{label}_CTL{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_HOST)
        await self.csr_write(
            f"{label}_CTL{idx}_FIFO", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(
            f"{label}_CTL{idx}_EVENTS_CLR",
            _reg("CONTROLLER_EVENTS", idx),
            I2C_CONTROLLER_EVENTS_ALL,
        )
        await self.csr_write(f"{label}_CTL{idx}_INTR_CLR", _reg("INTR_STATE", idx), 0xFFFF_FFFF)
        await self.csr_write(f"{label}_CTL{idx}_CTRL", _reg("CTRL", idx), I2C_CTRL_ENABLEHOST)

    async def _queue(self, idx: int, words: list[int], label: str) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", _reg("FDATA", idx), word)

    async def _controller_off(self, idx: int, label: str) -> None:
        """CTRL first, the bus released, then the events and the format FIFO cleared."""
        await self._disable(idx, label)
        await self._wait_bus_released(f"{label}_bus_released")
        await self.csr_write(
            f"{label}_CTL{idx}_EVENTS_CLR",
            _reg("CONTROLLER_EVENTS", idx),
            I2C_CONTROLLER_EVENTS_ALL,
        )
        await self.csr_write(
            f"{label}_CTL{idx}_FMTRST", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )

    async def _wait_host_done(self, idx: int, label: str, stops_base: int) -> int:
        status = [0]

        async def probe() -> tuple[bool, str]:
            status[0] = await self.csr_read(f"{label}_CTL_STATUS", _reg("STATUS", idx))
            want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            done = status[0] & want == want and self.wire.stops > stops_base
            return done, f"I2C{idx} STATUS=0x{status[0]:08x} {self.wire.summary()}"

        await self._poll(f"{label}_i{idx}_host_done", IDLE_POLLS, IDLE_STEP, probe)
        return status[0]

    # -- ACQ FIFO ---------------------------------------------------------

    async def _pop_acq(self, idx: int, label: str) -> list[Entry]:
        entries: list[Entry] = []
        for _ in range(ACQ_POP_LIMIT):
            status = await self.csr_read(f"{label}_ACQ_STATUS{idx}", _reg("STATUS", idx))
            if status & I2C_STATUS_ACQEMPTY:
                return entries
            word = await self.csr_read(f"{label}_ACQDATA{idx}", _reg("ACQDATA", idx))
            entries.append((acq_signal(word), acq_abyte(word)))
        raise AssertionError(f"{label}: I2C{idx} ACQ FIFO never emptied ({_fmt(entries)})")

    async def _collect(self, idx: int, label: str, entries: list[Entry]) -> list[Entry]:
        """Pop until a STOP entry; ``entries`` carries what was popped before."""

        async def probe() -> tuple[bool, str]:
            entries.extend(await self._pop_acq(idx, label))
            stop = any(s == I2C_ACQ_SIGNAL_STOP for s, _ in entries)
            return stop, f"I2C{idx} entries={_fmt(entries)}"

        await self._poll(f"{label}_i{idx}_acq_stop", ACQ_POLLS, ACQ_STEP, probe)
        return entries

    async def _flat_acq(self, idx: int, label: str) -> list[int]:
        """``FLAT_READS`` ACQEMPTY reads ``FLAT_GAP`` cycles apart."""
        empties = []
        for i in range(FLAT_READS):
            await ClockCycles(cocotb.top.clk_smc_i, FLAT_GAP)
            status = await self.csr_read(f"{label}_FLAT{i}_I2C{idx}", _reg("STATUS", idx))
            empties.append(int(bool(status & I2C_STATUS_ACQEMPTY)))
        return empties

    # -- bench controller -------------------------------------------------

    async def _vip_write(self, addr7: int, byte: int) -> list[int]:
        """START, address (write), one byte while ACKed, STOP; returns every ACK bit."""
        vip = self.vip
        await vip.send_start()
        acks = [await vip.send_byte((addr7 & 0x7F) << 1)]
        if acks[0] == 0:
            acks.append(await vip.send_byte(byte))
        await vip.send_stop()
        return acks

    async def _probe_addr(self, label: str, tgt: int, addr7: int, want_ack: bool) -> str:
        """Bench write to ``addr7``; ACK and ACQ entries graded against ``want_ack``."""
        for idx in INSTANCES:
            await self.csr_write(
                f"{label}_ACQRST{idx}", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_ACQRST
            )
        self._mark_frames()
        byte = self._next_byte()
        acks = await self._vip_write(addr7, byte)
        frames = self._frames(addr7)
        assert len(frames) == 1, f"{label}: wire frames to 0x{addr7:02x}: {frames}"
        if want_ack:
            entries = await self._collect(tgt, label, [])
            assert acks == [0, 0], f"{label}: 0x{addr7:02x} ACK bits {acks}, expected [0, 0]"
            assert frames[0].addr_acked is True, f"{label}: wire frame {frames[0]}"
            assert len(entries) == 3 and entries[:2] == [
                (I2C_ACQ_SIGNAL_START, addr7 << 1),
                (I2C_ACQ_SIGNAL_NONE, byte),
            ], f"{label}: I2C{tgt} entries {_fmt(entries)}"
            assert entries[2][0] == I2C_ACQ_SIGNAL_STOP, f"{label}: entries {_fmt(entries)}"
            text = f"ACK, entries {_fmt(entries)}"
        else:
            empties = await self._flat_acq(tgt, label)
            assert acks == [1], f"{label}: 0x{addr7:02x} ACK bits {acks}, expected NACK"
            assert frames[0].addr_acked is False, f"{label}: wire frame {frames[0]}"
            assert empties == [1] * FLAT_READS, f"{label}: I2C{tgt} ACQEMPTY reads {empties}"
            text = f"NACK, ACQEMPTY {empties}"
        for idx in INSTANCES:
            if idx != tgt:
                left = await self._pop_acq(idx, f"{label}_OTHER")
                assert not left, f"{label}: I2C{idx} acquired {_fmt(left)} for 0x{addr7:02x}"
        return f"0x{addr7:02x} {text}"

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        assert "smc_i2c_shared_bus" in cocotb.plusargs, (
            "smc_i2c_bus_matrix_rand_test needs +smc_i2c_shared_bus"
        )
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(("fuse_sense_done", f"{FUSE_SENSE_BOUND} clk_smc_i", "seen"))
        for name in ("tb_i2c0_scl", "tb_i2c0_sda", "tb_i2c0_scl_dut_low", "tb_i2c0_sda_dut_low"):
            assert hasattr(cocotb.top, name), f"tb_top has no {name}"
        self.d = draw(self.seed)
        check_draw(self.d)
        d = self.d
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: ADDRESS0 0x%02x, ADDRESS1 0x%02x, no-match 0x%02x, "
            "address target I2C%d, mask order %s; pairs %s; NACK controller I2C%d pinned length %d "
            "index %d data %s, drawn length %d index %d data %s; ACK control I2C%d->I2C%d "
            "length %d held bytes 0 (pinned) and %d data %s",
            self.seed,
            d["a0"],
            d["a1"],
            d["nomatch"],
            d["addr_target"],
            [(hex(m0), hex(m1)) for m0, m1 in d["mask_order"]],
            [
                f"I2C{p['c']}->I2C{p['t']} {p['mix']} len {p['len']} w[{_hex(p['wdata'])}] "
                f"t[{_hex(p['tdata'])}]"
                for p in d["passes"]
            ],
            d["nack_ctl"],
            d["pin_len"],
            d["nack_pin"],
            _hex(d["pin_data"]),
            d["nack_len"],
            d["nack_draw"],
            _hex(d["nack_data"]),
            d["ack_ctl"],
            d["ack_tgt"],
            d["ack_len"],
            d["ack_draw"],
            _hex(d["ack_data"]),
        )
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        for idx in INSTANCES:
            await self.arm_i2c_gpio_lsio(idx, f"I2C{idx}_IBM")
        for idx in INSTANCES:
            await self._disable(idx, "S1")
            await self.csr_write(f"I2C{idx}_WRAP", _wrap(idx), I2C_WRAP_CTRL_TARGET)
            for reg, value in (
                ("TIMING0", _pack_timing0(0x1A, 0x32)),
                ("TIMING1", _pack_timing1(2, 2)),
                ("TIMING2", _pack_timing2(5, 4)),
                ("TIMING3", _pack_timing3(2, 5)),
                ("TIMING4", _pack_timing4(4, 5)),
            ):
                await self.csr_write(f"I2C{idx}_{reg}", _reg(reg, idx), value)
            await self.csr_write(f"I2C{idx}_INTR_ENABLE_OFF", _reg("INTR_ENABLE", idx), 0)
            await self.csr_write(f"I2C{idx}_OVRD_OFF", _reg("OVRD", idx), 0)
            await self.csr_write(f"I2C{idx}_FIFO_RST", _reg("FIFO_CTRL", idx), FIFO_ALL)
        await self._wait_bus_released("bus_released_bringup")
        self.wire = SmcFwI2cWireMonitor(name="smc_i2c_bus_matrix_wire")
        self.vip = SmcI2cMasterVip(
            speed=VIP_SPEED, name="smc_i2c_bus_matrix_master", scl_timeout_ns=VIP_SCL_BOUND_NS
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._mark("S1")

    async def _s2(self) -> None:
        d = self.d
        tgt = d["addr_target"]
        await self._enable_target(
            tgt, "S2", _pack_target_id(d["a0"], FULL_MASK, d["a1"], FULL_MASK)
        )
        rows = []
        acked = nacked = 0
        for n, (m0, m1) in enumerate(d["mask_order"]):
            label = f"S2_{n}"
            await self.csr_write(
                f"{label}_TARGET_ID",
                _reg("TARGET_ID", tgt),
                _pack_target_id(d["a0"], m0, d["a1"], m1),
            )
            parts = []
            for addr7, want in ((d["a0"], m0 != 0), (d["a1"], m1 != 0), (d["nomatch"], False)):
                parts.append(await self._probe_addr(f"{label}_{addr7:02X}", tgt, addr7, want))
                acked += int(want)
                nacked += int(not want)
            rows.append(f"MASK0=0x{m0:02x} MASK1=0x{m1:02x}: " + ", ".join(parts))
        await self._disable(tgt, "S2_END")
        assert acked == 4 and nacked == 8, f"S2: {acked} ACK and {nacked} NACK cells"
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-IBM-ADDR",
            f"target I2C{tgt} with ENABLETARGET, every slot and mask cell pinned in the drawn "
            f"order: {'; '.join(rows)}; each address acknowledged and recorded in the target's "
            f"ACQDATA exactly when its mask was full, the no-match address 0x{d['nomatch']:02x} "
            f"never, no entry in the other instances; drawn=ADDRESS0 0x{d['a0']:02x} ADDRESS1 "
            f"0x{d['a1']:02x} no-match 0x{d['nomatch']:02x} target I2C{tgt}",
        )

    async def _s3(self) -> None:
        d = self.d
        tgt = d["addr_target"]
        await self._enable_target(tgt, "S3", _pack_target_id(d["a0"], FULL_MASK, 0, 0), 0)
        parts = []
        for name, ctrl, want_nack in ROLE_CELLS:
            value = CTRL_TARGET if ctrl is None else ctrl
            await self.csr_write(f"S3_{name}_CTRL", _reg("CTRL", tgt), value)
            text = await self._probe_addr(
                f"S3_{name.replace(' ', '_')}", tgt, d["a0"], not want_nack
            )
            parts.append(f"CTRL=0x{value:x} ({name}): {text}")
        await self._disable(tgt, "S3_END")
        self._mark("S3")
        self._chk(
            "S3",
            "CHK-IBM-ROLE",
            f"{'; '.join(parts)}; the address acknowledged only with ENABLETARGET set; "
            f"drawn=target I2C{tgt} address 0x{d['a0']:02x}",
        )

    async def _pass(self, n: int, p: dict) -> str:
        d = self.d
        c, t, mix, length = p["c"], p["t"], p["mix"], p["len"]
        bystander = next(i for i in INSTANCES if i not in (c, t))
        label = f"S4_P{n}"
        a = d["a0"]
        await self._disable_all(label)
        await self._enable_target(t, label, _pack_target_id(a, FULL_MASK, 0, 0))
        await self._enable_target(
            bystander, f"{label}_BY", _pack_target_id(d["a1"], FULL_MASK, 0, 0)
        )
        if mix != "write":
            for i, byte in enumerate(p["tdata"]):
                await self.csr_write(f"{label}_TXDATA{i}", _reg("TXDATA", t), byte)
        await self._enable_controller(c, label)
        words: list[int] = []
        want: list[Entry] = []
        if mix != "read":
            last = mix == "write"
            words.append(_fdata(a << 1, I2C_FDATA_START))
            words += [
                _fdata(b, I2C_FDATA_STOP if last and i == length - 1 else 0)
                for i, b in enumerate(p["wdata"])
            ]
            want.append((I2C_ACQ_SIGNAL_START, a << 1))
            want += [(I2C_ACQ_SIGNAL_NONE, b) for b in p["wdata"]]
        if mix != "write":
            words.append(_fdata((a << 1) | 1, I2C_FDATA_START))
            words.append(_fdata(length, I2C_FDATA_READB | I2C_FDATA_STOP))
            signal = I2C_ACQ_SIGNAL_START if mix == "read" else I2C_ACQ_SIGNAL_RESTART
            want.append((signal, (a << 1) | 1))
        self._mark_frames()
        stops_base = self.wire.stops
        await self._queue(c, words, label)
        entries: list[Entry] = []
        status = [0]

        async def drain() -> tuple[bool, str]:
            entries.extend(await self._pop_acq(t, label))
            status[0] = await self.csr_read(f"{label}_CTL_STATUS", _reg("STATUS", c))
            done = status[0] & (I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY) == (
                I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
            )
            done = done and self.wire.stops > stops_base
            return done, f"I2C{c} STATUS=0x{status[0]:08x} I2C{t} entries={_fmt(entries)}"

        await self._poll(f"{label}_i{c}_done", IDLE_POLLS, IDLE_STEP, drain)
        got: list[int] = []
        if mix != "write":

            async def rx() -> tuple[bool, str]:
                st = await self.csr_read(f"{label}_RX_STATUS", _reg("STATUS", c))
                if not st & I2C_STATUS_RXEMPTY:
                    got.append(await self.csr_read(f"{label}_RDATA", _reg("RDATA", c)) & 0xFF)
                return len(got) == length, f"popped=[{_hex(got)}]"

            await self._poll(f"{label}_rdata", RX_POLLS, RX_STEP, rx)
        events = await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", c))
        if not any(s == I2C_ACQ_SIGNAL_STOP for s, _ in entries):
            await self._collect(t, label, entries)
        by_entries = await self._pop_acq(bystander, f"{label}_BY")
        frames = self._frames(a)
        assert entries[: len(want)] == want, (
            f"{label}: I2C{t} entries {_fmt(entries)}, expected prefix {_fmt(want)}"
        )
        assert any(s == I2C_ACQ_SIGNAL_STOP for s, _ in entries[len(want) :]), (
            f"{label}: no STOP entry after {_fmt(want)} in {_fmt(entries)}"
        )
        assert not by_entries, f"{label}: bystander I2C{bystander} acquired {_fmt(by_entries)}"
        assert got == (p["tdata"] if mix != "write" else []), (
            f"{label}: RDATA [{_hex(got)}], target TXDATA [{_hex(p['tdata'])}]"
        )
        assert not events & EV_NACK, f"{label}: I2C{c} CONTROLLER_EVENTS=0x{events:08x}"
        assert frames and all(f.addr_acked is True for f in frames), f"{label}: frames {frames}"
        if mix != "read":
            wframe = frames[0]
            assert wframe.read is False and wframe.data == [(b, True) for b in p["wdata"]], (
                f"{label}: write frame {wframe}, expected [{_hex(p['wdata'])}] all ACKed"
            )
        if mix != "write":
            rframe = frames[-1]
            assert rframe.read is True and [b for b, _ in rframe.data] == p["tdata"], (
                f"{label}: read frame {rframe}, expected [{_hex(p['tdata'])}]"
            )
        await self._controller_off(c, label)
        await self._disable_all(f"{label}_END")
        return (
            f"P{n} I2C{c}->I2C{t} ({mix}, len {length}): wire {' '.join(str(f) for f in frames)}, "
            f"I2C{t} entries {_fmt(entries)}, bystander I2C{bystander} at 0x{d['a1']:02x} "
            f"entries {_fmt(by_entries)}, RDATA [{_hex(got)}], events 0x{events:08x}"
        )

    async def _s4(self) -> None:
        rows = [await self._pass(n, p) for n, p in enumerate(self.d["passes"])]
        self._mark("S4")
        mixes = ",".join(p["mix"] for p in self.d["passes"])
        self._chk(
            "S4",
            "CHK-IBM-PAIR",
            f"{'; '.join(rows)}; every pass acknowledged and recorded in the target instance "
            f"only, every read returned its bytes through RDATA; pinned write and read passes, "
            f"drawn=pairs {[(p['c'], p['t']) for p in self.d['passes']]} mixes {mixes}",
        )

    async def _nack_leg(self, data: list[int], k: int, nakok: bool) -> tuple[str, int]:
        """One NACK write of ``data`` with byte ``k`` NACKed; the bytes after it with NAKOK set."""
        c, length = self.d["nack_ctl"], len(data)
        label = f"S5_L{length}_K{k}_{'NAKOK' if nakok else 'NONAKOK'}"
        await self._enable_controller(c, label)
        self.nack_target.nack_index = k
        nacks_before = self.nack_target.data_nacks
        words = [_fdata(BENCH_NACK_ADDR << 1, I2C_FDATA_START)]
        for i, b in enumerate(data):
            flags = (I2C_FDATA_STOP if i == length - 1 else 0) | (
                FDATA_NAKOK if nakok and i == k else 0
            )
            words.append(_fdata(b, flags))
        self._mark_frames()
        stops_base = self.wire.stops
        await self._queue(c, words, label)
        if nakok:
            status = await self._wait_host_done(c, label, stops_base)
            events = await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", c))
            frames = self._frames(BENCH_NACK_ADDR)
            want = [(b, i != k) for i, b in enumerate(data)]
            assert not events & EV_NACK, f"{label}: CONTROLLER_EVENTS=0x{events:08x} with NAKOK"
            assert len(frames) == 1 and frames[0].addr_acked and frames[0].data == want, (
                f"{label}: wire {frames}, expected every byte of [{_hex(data)}] with byte {k} "
                f"NACKed"
            )
            after = len(frames[0].data[k + 1 :])
            text = (
                f"NAKOK on byte {k}: events 0x{events:08x} NACK 0, STATUS 0x{status:08x}, "
                f"wire {frames[0]}, {after} byte(s) after the NACKed one on the wire"
            )
        else:
            after = 0
            seen = [0]

            async def probe() -> tuple[bool, str]:
                seen[0] = await self.csr_read(f"{label}_EVENTS", _reg("CONTROLLER_EVENTS", c))
                return bool(seen[0] & EV_NACK), f"CONTROLLER_EVENTS=0x{seen[0]:08x}"

            await self._poll(f"{label}_nack_event", EVENT_POLLS, EVENT_STEP, probe)
            frames = self._frames(BENCH_NACK_ADDR)
            want = [(b, True) for b in data[:k]] + [(data[k], False)]
            assert len(frames) == 1 and frames[0].addr_acked, f"{label}: wire {frames}"
            assert frames[0].data[: k + 1] == want, (
                f"{label}: wire {frames[0]}, expected [{_hex(data[: k + 1])}] with byte {k} NACKed"
            )
            text = (
                f"NAKOK clear: events 0x{seen[0]:08x} NACK 1, wire {frames[0]} "
                f"({len(frames[0].data)} data byte(s) on the wire, printed)"
            )
        assert self.nack_target.data_nacks == nacks_before + 1, (
            f"{label}: bench target NACKed {self.nack_target.data_nacks - nacks_before} bytes"
        )
        await self._controller_off(c, label)
        events = await self.csr_read(f"{label}_EVENTS_CLEARED", _reg("CONTROLLER_EVENTS", c))
        assert not events & EV_NACK, f"{label}: NACK still set after the clear (0x{events:08x})"
        return f"length {length} index {k}: {text}", after

    async def _s5(self) -> None:
        d = self.d
        await self._disable_all("S5")
        self.nack_target = _NthDataNackTarget(BENCH_NACK_ADDR, "smc_i2c_bus_matrix_nack_target")
        try:
            rows = []
            later = 0
            for data, k in ((d["pin_data"], d["nack_pin"]), (d["nack_data"], d["nack_draw"])):
                for nakok in (False, True):
                    row, after = await self._nack_leg(data, k, nakok)
                    rows.append(row)
                    later += int(nakok and after > 0)
        finally:
            self.nack_target.stop()
        assert later >= 1, f"S5: no NAKOK-set write had a byte after the NACKed one ({rows})"
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-IBM-NAKOK",
            f"controller I2C{d['nack_ctl']} writing to the bench target 0x{BENCH_NACK_ADDR:02x}: "
            f"{'; '.join(rows)}; a NACK set CONTROLLER_EVENTS.NACK with NAKOK clear, and with "
            f"NAKOK set the transfer completed with every remaining byte on the wire and NACK "
            f"clear, {later} of 2 NAKOK-set writes with a byte after the NACKed one on the wire "
            f"(the pinned one on every seed); pinned non-zero index {d['nack_pin']} of length "
            f"{d['pin_len']} [{_hex(d['pin_data'])}], drawn=length {d['nack_len']} index "
            f"{d['nack_draw']} [{_hex(d['nack_data'])}] controller I2C{d['nack_ctl']}",
        )

    def _acked(self, addr7: int) -> tuple[int, int]:
        frames = self._frames(addr7)
        if not frames:
            return 0, 0
        return frames[0].data_bytes(acked_only=True), len(frames[0].data)

    async def _wait_hold(self, label: str, tgt: int, after: int, stops_base: int) -> int:
        a = self.d["a0"]
        state = [""]

        async def probe() -> tuple[bool, str]:
            before = self._acked(a)
            status = await self.csr_read(f"{label}_TGT_STATUS", _reg("STATUS", tgt))
            now = self._acked(a)
            state[0] = f"STATUS=0x{status:08x} acked/total={now} {self.wire.summary()}"
            assert self.wire.stops == stops_base, f"{label}: STOP before the hold; {state[0]}"
            held = status & I2C_STATUS_ACK_CTRL_STRETCH and now == before and now[0] > after
            return bool(held), state[0]

        await self._poll(f"{label}_hold", HOLD_POLLS, HOLD_STEP, probe)
        return self._acked(a)[0]

    async def _ack_leg(self, j: int) -> str:
        d = self.d
        c, t, length, data, a = d["ack_ctl"], d["ack_tgt"], d["ack_len"], d["ack_data"], d["a0"]
        label = f"S6_J{j}"
        await self._disable_all(label)
        await self._enable_target(t, label, _pack_target_id(a, FULL_MASK, 0, 0), CTRL_ACK_CONTROL)
        ctrl = await self.csr_read(f"{label}_TGT_CTRL_RB", _reg("CTRL", t))
        assert ctrl & I2C_CTRL_ACK_CTRL_EN, f"{label}: CTRL.ACK_CTRL_EN did not take (0x{ctrl:x})"
        await self._enable_controller(c, label)
        self._mark_frames()
        stops_base = self.wire.stops
        words = [_fdata(a << 1, I2C_FDATA_START)]
        words += [_fdata(b, I2C_FDATA_STOP if i == length - 1 else 0) for i, b in enumerate(data)]
        await self._queue(c, words, label)
        first = await self._wait_hold(f"{label}_first", t, -1, stops_base)
        # i2c.rdl TARGET_ACK_CTRL.NBYTES resets to 0: the first data byte is held.
        assert first == 0, f"{label}: {first} byte(s) ACKed before the first hold"
        held = first
        if j:
            await self.csr_write(f"{label}_NBYTES", _reg("TARGET_ACK_CTRL", t), j)
            held = await self._wait_hold(f"{label}_held", t, first, stops_base)
            assert held == j, f"{label}: {held} byte(s) ACKed after NBYTES={j}"
        await self.csr_write(f"{label}_NACK", _reg("TARGET_ACK_CTRL", t), I2C_TARGET_ACK_CTRL_NACK)

        async def probe() -> tuple[bool, str]:
            _, total = self._acked(a)
            return total > j, f"{self.wire.summary()}"

        await self._poll(f"{label}_held_byte_on_wire", EVENT_POLLS, EVENT_STEP, probe)
        frame = self._frames(a)[0]
        want = [(b, True) for b in data[:j]] + [(data[j], False)]
        assert frame.addr_acked and frame.data[: j + 1] == want, (
            f"{label}: wire {frame}, expected [{_hex(data[: j + 1])}] with byte {j} NACKed"
        )
        events = await self.csr_read(f"{label}_CTL_EVENTS", _reg("CONTROLLER_EVENTS", c))
        await self._controller_off(c, label)
        await self._disable(t, f"{label}_TGT")
        await self.csr_write(f"{label}_TGT_FIFO", _reg("FIFO_CTRL", t), FIFO_ALL)
        return (
            f"held byte {j}: {j} byte(s) ACKed before the hold, wire {frame}, controller "
            f"CONTROLLER_EVENTS 0x{events:08x} (printed)"
        )

    async def _s6(self) -> None:
        d = self.d
        rows = [await self._ack_leg(j) for j in (0, d["ack_draw"])]
        self._mark("S6")
        self._chk(
            "S6",
            "CHK-IBM-ACKCTRL",
            f"target I2C{d['ack_tgt']} in ACK Control Mode, controller I2C{d['ack_ctl']} writing "
            f"[{_hex(d['ack_data'])}]: {'; '.join(rows)}; the held byte was not acknowledged on "
            f"the wire after TARGET_ACK_CTRL.NACK was written; pinned byte 0, drawn=pair "
            f"I2C{d['ack_ctl']}->I2C{d['ack_tgt']} length {d['ack_len']} byte {d['ack_draw']}",
        )

    async def _s7(self) -> None:
        rows = []
        for idx in INSTANCES:
            await self.csr_write(f"S7_I2C{idx}_CTRL", _reg("CTRL", idx), CTRL_RESET)
            await self.csr_write(f"S7_I2C{idx}_TARGET_ID", _reg("TARGET_ID", idx), TARGET_ID_RESET)
            await self.csr_write(f"S7_I2C{idx}_FIFO", _reg("FIFO_CTRL", idx), FIFO_ALL)
            ctrl = await self.csr_read(f"S7_I2C{idx}_CTRL_RB", _reg("CTRL", idx))
            tid = await self.csr_read(f"S7_I2C{idx}_TARGET_ID_RB", _reg("TARGET_ID", idx))
            assert (ctrl, tid) == (CTRL_RESET, TARGET_ID_RESET), (
                f"S7: I2C{idx} CTRL 0x{ctrl:x} TARGET_ID 0x{tid:x} after the restore"
            )
            rows.append(f"I2C{idx} CTRL 0x{ctrl:x} TARGET_ID 0x{tid:x}")
        await self._wait_bus_released("restore_bus_released")
        self.wire.stop()
        self._mark("S7")
        cfg = self.cfg
        waits = list(self.waits)
        waits.append(("vip_scl_release", f"{self.vip.scl_timeout_ns}ns", "per bench bit"))
        waits.append(("sep_in_access", f"{cfg.axi_timeout_ns}ns", f"{self.accesses} accesses"))
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with its last "
            "state on expiry; %s; restore %s",
            len(waits),
            "; ".join(f"{n} bound={b} last={s}" for n, b, s in waits),
            ", ".join(rows),
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        acked = sum(1 for f in self.wire.frames if f.addr_acked is True)
        nacked = sum(1 for f in self.wire.frames if f.addr_acked is False)
        assert acked >= 1 and nacked >= 1, f"address bytes ACKed {acked}, NACKed {nacked}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; wire address bytes "
            "ACKed %d, NACKed %d over %d frames; seed %d",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            acked,
            nacked,
            len(self.wire.frames),
            self.seed,
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        self.done = True
