# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target-mode line loopback, against a transmit FIFO that is already full.

`i2c.rdl` describes `CTRL.LLPBK` in target mode as a target that "sends all
received SDA data back out": what an external controller writes to it comes
back on the next read.

The loopback is driven against back-pressure. The transmit FIFO's depth is
measured by filling it through `TXDATA` until `STATUS.TXFULL` sets; it is then
reset and loaded with one entry fewer, `LLPBK` is set with
`ACQ_START_STOP_EN`, so the START and STOP are acquisition entries too, and a
two-byte write is made to the target. The first written byte takes the last free entry; the
second has nowhere to go and must wait in the acquisition FIFO, with the STOP
entry behind it, while the START entry with the address, which carries no
payload, must not wait. `TARGET_FIFO_STATUS.ACQLVL` shows exactly those two.

A read cannot unblock it: the target holds a read until the acquisition FIFO
is empty, and the acquisition FIFO cannot empty into a full transmit FIFO.
Software breaks the tie by reading `ACQDATA`, which must return the waiting
byte as a data entry; the STOP entry behind it then leaves on its own. A read
of the whole transmit FIFO has to return the bytes loaded through `TXDATA`, in
order, followed by the first written byte, and leave the acquisition FIFO
empty.

The legs after those run on I2C instance 1 through its own pads, which the bench
resolves onto `tb_i2c1_scl` / `tb_i2c1_sda` under `+smc_i2c1_pads`. A bench
controller, an EEPROM target at 0x50 preset to 0x00..0xFF and a pad injector share
that pair. Expected values come from the generated `i2c.adoc` field text and from
the stimulus:

* `CTRL.LLPBK` in target mode: every SDA level sampled at the SCL high of each
  written data bit equals the bit driven; with `LLPBK` clear the acquisition FIFO
  holds the START with the address, both bytes and the STOP.
* `OVRD.TXOVRDEN` with each `SCLVAL` / `SDAVAL` pair: the pads follow the values
  (0 pulls low, 1 releases) and `VAL` bit 0 (`SCL_RX`) and bit 16 (`SDA_RX`) follow
  the pads, also while the bench pulls each line low; an ordinary write then lands.
* A 256-byte `READB` with no `RDATA` pops sets `STATUS.RXFULL`; the popped bytes are
  one in-order run of consecutive EEPROM bytes, and a written 1 clears
  `INTR_STATE.RX_OVERFLOW`; `FIFO_CTRL.RXRST` empties the refilled FIFO.
* An external pull of SCL inside a controller-driven SCL high raises
  `INTR_STATE.SCL_INTERFERENCE`, and an SDA edge inside the SCL high of a read data
  bit raises `INTR_STATE.SDA_UNSTABLE`; a clean transfer raises neither and a
  written 1 clears each.

The controller-mode half of `LLPBK`, which masks `smbalert_ni`, is not exercised:
under `+smc_i2c1_pads` the bench has no driver for the I2C1 alert pad.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, Timer
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_ACQ_SIGNAL_NONE,
    I2C_ACQ_SIGNAL_START,
    I2C_ACQ_SIGNAL_STOP,
    I2C_ACQDATA_ABYTE,
    I2C_ACQDATA_SIGNAL,
    I2C_ACQDATA_SIGNAL_BP,
    I2C_CTRL_ACQ_START_STOP_EN,
    I2C_CTRL_ENABLEHOST,
    I2C_CTRL_ENABLETARGET,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_ACQRST,
    I2C_FIFO_CTRL_RXRST,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_FIFO_CTRL_TXRST,
    I2C_HOST_FIFO_STATUS_RXLVL_BM,
    I2C_HOST_FIFO_STATUS_RXLVL_BP,
    I2C_INTR_SDA_UNSTABLE,
    I2C_STATUS_ACQEMPTY,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_HOSTIDLE,
    I2C_STATUS_RXEMPTY,
    I2C_STATUS_RXFULL,
    I2C_STATUS_TARGETIDLE,
    I2C_STATUS_TXFULL,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BM,
    I2C_TARGET_FIFO_STATUS_ACQLVL_BP,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_CTRL_TARGET,
)
from .smc_i2c_master_target_test_seq import _fdata, _i2c_u32
from .smc_i2c_protocol_vip import (
    _SCL_LOW,
    _SDA_LOW,
    SmcI2cEepromSlave,
    SmcI2cMasterVip,
    _pads,
    _set_ext_low,
)
from .smc_i2c_target_ack_ctrl_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_ACQDATA,
    I2C0_CTRL,
    I2C0_FIFO_CTRL,
    I2C0_OVRD,
    I2C0_STATUS,
    I2C0_TARGET_FIFO_STATUS,
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

I2C0_TXDATA = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_TXDATA_BASE_ADDR", 0)
CTRL_LLPBK = _i2c_u32("I2C__CTRL__LLPBK_bm")

TARGET_ADDR = 0x2A
VIP_SPEED = 2_000_000
ECHO = bytes((0xC5, 0x3A))
#: Upper bound on the transmit FIFO depth; the fill stops at STATUS.TXFULL.
MAX_TX_DEPTH = 512
SETTLE_CYCLES = 200


#: I2C instance 1 legs.
I2C1 = 1
I2C1_TARGET_ADDR = 0x26
I2C1_EEPROM_ADDR = 0x50
LLPBK_DATA = bytes((0x5A, 0xC3))
OVRD_TXOVRDEN = _i2c_u32("I2C__OVRD__TXOVRDEN_bm")
OVRD_SCLVAL = _i2c_u32("I2C__OVRD__SCLVAL_bm")
OVRD_SDAVAL = _i2c_u32("I2C__OVRD__SDAVAL_bm")
VAL_SCL_RX_BIT0 = 1 << _i2c_u32("I2C__VAL__SCL_RX_bp")
VAL_SDA_RX_BIT0 = 1 << _i2c_u32("I2C__VAL__SDA_RX_bp")
OVRD_PAIRS = ((0, 0), (0, 1), (1, 0), (1, 1))
OVRD_WRITE = (0x20, 0x5C)
INTR_RX_OVERFLOW = _i2c_u32("I2C__INTR_STATE__RX_OVERFLOW_bm")
INTR_SCL_INTERFERENCE = _i2c_u32("I2C__INTR_STATE__SCL_INTERFERENCE_bm")
ALL_ONES = 0xFFFF_FFFF
#: Bench bring-up timing (clk_i cycles) for every I2C1 leg but the 256-byte read.
BASE_TIMING = (0x1A, 0x32, 2, 2, 5, 4, 2, 5, 4, 5)
#: The 256-byte read: THIGH and TLOW a few cycles above the documented minimum of 2.
FAST_TIMING = (6, 8, 1, 1, 6, 6, 1, 1, 6, 8)
REFILL_BYTES = 4
SCL_WRITE = (0x30, 0xA7)
#: SCL rise 9 of a write is the address acknowledge pulse, which the controller clocks.
SCL_PULL_RISE = 9
SCL_PULL_DELAY_NS = 10
SCL_PULL_NS = 100
SDA_READ_OFFSET = 0x4C
SDA_READ_BYTES = 4
#: SCL rise 30 of a write, repeated START and read is bit 6 of the first read byte;
#: 0x4C carries a 1 there, so the line is released and a pull makes an edge.
SDA_PULL_RISE = 30
SDA_PULL_HIGH_FRACTION = 0.5
I2C1_VIP_SPEED = 2_000_000
I2C1_VIP_SCL_TIMEOUT_NS = 50_000
INJECTOR_SPEED = 1_000_000

PAD_POLLS = 400
PAD_GAP_CYCLES = 4
POLL_GAP_CYCLES = 50
IDLE_POLLS = 2000
ACQ_POLLS = 400
RXFULL_POLLS = 3000
RXFULL_GAP_CYCLES = 100
INTR_POLLS = 400
DRAIN_LIMIT = 1200
EDGE_WAIT_CYCLES = 200_000

STEPS = ("S1", "S2", "S4", "S5", "S6", "S7")
FENCE_TERMS = {
    "S1": "BRINGUP",
    "S2": "I2C1_LLPBK_TGT",
    "S4": "I2C1_OVRD",
    "S5": "I2C1_RX_OVERFLOW",
    "S6": "I2C1_SCL_INTERFERENCE",
    "S7": "I2C1_SDA_UNSTABLE",
}


def _reg(register: str, idx: int = I2C1) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int = I2C1) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _timing_words(t: tuple[int, ...]) -> tuple[int, int, int, int, int]:
    return (
        _pack_timing0(t[0], t[1]),
        _pack_timing1(t[2], t[3]),
        _pack_timing2(t[4], t[5]),
        _pack_timing3(t[6], t[7]),
        _pack_timing4(t[8], t[9]),
    )


def _rxlvl(word: int) -> int:
    return (word & I2C_HOST_FIFO_STATUS_RXLVL_BM) >> I2C_HOST_FIFO_STATUS_RXLVL_BP


def _level(handle) -> int:
    raw = handle.value
    assert raw.is_resolvable, f"{handle._name} is not resolvable: {raw}"
    return int(raw)


class SmcI2c1PadVip(SmcI2cMasterVip):
    """`SmcI2cMasterVip` on the `tb_i2c1_*` pads that samples SDA at each SCL high it drives."""

    def __init__(self, *, speed: int, name: str, scl_timeout_ns: int | None = None) -> None:
        super().__init__(speed=speed, name=name, scl_timeout_ns=scl_timeout_ns)
        self._sda, self._sda_ext, self._scl, self._scl_ext, _ = _pads(I2C1)
        _set_ext_low(self._sda_ext, _SDA_LOW, self._id, False)
        _set_ext_low(self._scl_ext, _SCL_LOW, self._id, False)
        #: (driven bit, SDA level sampled in the SCL high) for every bit sent.
        self.samples: list[tuple[int, int]] = []

    async def send_bit(self, bit: int) -> None:
        self._pull_sda(not bool(bit))
        await Timer(self._half_ns, unit="ns")
        self._pull_scl(False)
        await self._wait_scl_high()
        await Timer(self._half_ns, unit="ns")
        self.samples.append((bit, _level(self._sda)))
        await Timer(self._bit_ns - self._half_ns, unit="ns")
        self._pull_scl(True)
        await Timer(self._half_ns, unit="ns")

    async def write_sampled(self, addr: int, data: bytes) -> tuple[list[int], list[tuple]]:
        """Write without stopping on a NACK; return the acknowledge bits and data-bit samples."""
        await self.send_start()
        acks = [await self.send_byte((addr & 0x7F) << 1)]
        data_samples = []
        for b in data:
            mark = len(self.samples)
            acks.append(await self.send_byte(b))
            data_samples.extend(self.samples[mark : mark + 8])
        await self.send_stop()
        return acks, data_samples


def _preload(index: int) -> int:
    return (0x11 + 3 * index) & 0xFF


class smc_i2c_target_loopback_test_seq(SmcCsrSeq):
    """Write to a looped-back target whose transmit FIFO is full, then read it all back."""

    def __init__(self, name: str = "smc_i2c_target_loopback_test_seq") -> None:
        super().__init__(name)
        self.depth = 0
        self.eeprom: SmcI2cEepromSlave | None = None
        self.master: SmcI2c1PadVip | None = None
        self.injector: SmcI2c1PadVip | None = None
        self._events: list[tuple[str, str, int]] = []

    async def _acq_level(self, label: str) -> int:
        word = await self.csr_read(label, I2C0_TARGET_FIFO_STATUS)
        return (word & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_DISABLE", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_TARGET", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_TARGET)
        await self.wait_i2c0_lsio_ready("I2C0_TARGET_LOOPBACK")
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
        await self.csr_write("I2C0_CTRL_TARGET", I2C0_CTRL, I2C_CTRL_ENABLETARGET)

        for index in range(MAX_TX_DEPTH):
            status = await self.csr_read(f"FILL_STATUS_{index}", I2C0_STATUS)
            if status & I2C_STATUS_TXFULL:
                self.depth = index
                break
            await self.csr_write(f"FILL_TXDATA_{index}", I2C0_TXDATA, _preload(index))
        else:
            raise AssertionError(
                f"STATUS.TXFULL never set over {MAX_TX_DEPTH} TXDATA writes; last STATUS "
                f"0x{status:08x}"
            )
        assert self.depth > 1, f"STATUS.TXFULL was set after {self.depth} TXDATA writes"
        await self.csr_write("TX_RESET", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_TXRST)
        preload = self.depth - 1
        for index in range(preload):
            await self.csr_write(f"LOAD_TXDATA_{index}", I2C0_TXDATA, _preload(index))
        status = await self.csr_read("LOADED_STATUS", I2C0_STATUS)
        assert not status & I2C_STATUS_TXFULL, (
            f"STATUS.TXFULL is set with {preload} of {self.depth} entries loaded (0x{status:08x})"
        )

        ctrl = I2C_CTRL_ENABLETARGET | CTRL_LLPBK | I2C_CTRL_ACQ_START_STOP_EN
        await self.csr_write("I2C0_CTRL_LOOPBACK", I2C0_CTRL, ctrl)
        await self.csr_read("I2C0_CTRL_LOOPBACK_RB", I2C0_CTRL, expected=ctrl)

        master = SmcI2cMasterVip(speed=VIP_SPEED, name="smc_i2c0_loopback_master")
        await Timer(1, unit="us")
        await master.write(TARGET_ADDR, ECHO)
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        waiting = await self._acq_level("ACQ_BLOCKED")
        status = await self.csr_read("STATUS_BLOCKED", I2C0_STATUS)
        assert waiting == 2 and status & I2C_STATUS_TXFULL, (
            f"with one free transmit entry, a two-byte write left {waiting} acquisition entries "
            f"(STATUS=0x{status:08x}); the second byte and the STOP behind it must wait, and "
            f"the START entry must not"
        )
        word = await self.csr_read("ACQDATA_BLOCKED", I2C0_ACQDATA)
        signal = (word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP
        assert signal == I2C_ACQ_SIGNAL_NONE and word & 0xFF == ECHO[1], (
            f"ACQDATA returned 0x{word:08x}; the waiting entry is the data byte 0x{ECHO[1]:02x}"
        )
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        status = await self.csr_read("STATUS_UNBLOCKED", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"the STOP entry did not leave after the data byte was read (STATUS=0x{status:08x})"
        )
        cocotb.log.info(
            "CHK-I2C-TGT-LOOPBACK-BLOCKED: with CTRL.LLPBK set and one free entry in a "
            "transmit FIFO of %d, a two-byte write left the second byte and its STOP waiting "
            "in the acquisition FIFO; ACQDATA returned that byte, 0x%02x, as data, and the "
            "STOP entry then left on its own",
            self.depth,
            ECHO[1],
        )

        got = await master.read(TARGET_ADDR, self.depth)
        want = bytes(_preload(i) for i in range(preload)) + ECHO[:1]
        assert got == want, (
            f"the read returned {got.hex()}, not the {preload} bytes loaded through TXDATA "
            f"followed by the first byte written ({want.hex()})"
        )
        await ClockCycles(cocotb.top.clk_smc_i, SETTLE_CYCLES)
        status = await self.csr_read("STATUS_END", I2C0_STATUS)
        assert status & I2C_STATUS_ACQEMPTY, (
            f"the acquisition FIFO is not empty after the read (STATUS=0x{status:08x}); in "
            f"loopback nothing in it is left for software"
        )
        await self.csr_write("I2C0_CTRL_OFF", I2C0_CTRL, 0)
        cocotb.log.info(
            "CHK-I2C-TGT-LOOPBACK-ECHO: a %d-byte read returned the %d TXDATA bytes in order "
            "and then the first written byte 0x%02x, looped back, and left the acquisition "
            "FIFO empty",
            len(got),
            preload,
            ECHO[0],
        )
        await self._i2c1_legs()

    # ------------------------------------------------------------------
    # I2C instance 1 legs
    # ------------------------------------------------------------------

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, text: str) -> None:
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _pad_state(self) -> str:
        dut = cocotb.top
        return f"tb_i2c1_scl={dut.tb_i2c1_scl.value} tb_i2c1_sda={dut.tb_i2c1_sda.value}"

    async def _wait_pads(self, name: str, scl: int, sda: int) -> None:
        dut = cocotb.top
        for _ in range(PAD_POLLS):
            levels = (dut.tb_i2c1_scl.value, dut.tb_i2c1_sda.value)
            if all(v.is_resolvable for v in levels) and (int(levels[0]), int(levels[1])) == (
                scl,
                sda,
            ):
                return
            await ClockCycles(dut.clk_periph_i, PAD_GAP_CYCLES)
        raise AssertionError(
            f"{name}: pads not at SCL={scl} SDA={sda} within {PAD_POLLS}x{PAD_GAP_CYCLES} "
            f"cycles; last {self._pad_state()}"
        )

    async def _poll_reg(self, name: str, register: str, done, polls: int, gap: int) -> int:
        """Read `register` until `done(value)`; raise with the last value on expiry."""
        value = 0
        for i in range(polls):
            value = await self.csr_read(f"{name}_{register}{i}", _reg(register))
            if done(value):
                return value
            await ClockCycles(cocotb.top.clk_periph_i, gap)
        raise AssertionError(
            f"{name}: {register} not satisfied within {polls} polls {gap} cycles apart; last "
            f"0x{value:08x}; {self._pad_state()}"
        )

    async def _wait_hostidle(
        self, name: str, want: int = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
    ) -> int:
        return await self._poll_reg(
            name, "STATUS", lambda v: v & want == want, IDLE_POLLS, POLL_GAP_CYCLES
        )

    async def _wait_intr(self, name: str, bit: int) -> int:
        return await self._poll_reg(
            name, "INTR_STATE", lambda v: v & bit, INTR_POLLS, POLL_GAP_CYCLES
        )

    async def _program(self, name: str, timing: tuple[int, ...]) -> None:
        regs = ("TIMING0", "TIMING1", "TIMING2", "TIMING3", "TIMING4")
        for reg, word in zip(regs, _timing_words(timing)):
            await self.csr_write(f"{name}_{reg}", _reg(reg), word)
            await self.csr_read(f"{name}_{reg}_RB", _reg(reg), expected=word)

    async def _prepare_host(self, name: str, enable: bool = True) -> None:
        await self.csr_write(f"{name}_CTRL_OFF", _reg("CTRL"), 0)
        await self.csr_write(f"{name}_OVRD_OFF", _reg("OVRD"), 0)
        await self.csr_write(f"{name}_FIFO_RST", _reg("FIFO_CTRL"), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write(f"{name}_EVENTS_CLR", _reg("CONTROLLER_EVENTS"), ALL_ONES)
        await self.csr_write(f"{name}_INTR_CLR", _reg("INTR_STATE"), ALL_ONES)
        if enable:
            await self.csr_write(f"{name}_ENABLEHOST", _reg("CTRL"), I2C_CTRL_ENABLEHOST)

    async def _push(self, name: str, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{name}_FDATA{i}", _reg("FDATA"), word)

    @staticmethod
    def _write_words(offset: int, value: int) -> list[int]:
        return [
            _fdata(I2C1_EEPROM_ADDR << 1, I2C_FDATA_START),
            _fdata(offset),
            _fdata(value, I2C_FDATA_STOP),
        ]

    @staticmethod
    def _read_words(offset: int, count: int) -> list[int]:
        return [
            _fdata(I2C1_EEPROM_ADDR << 1, I2C_FDATA_START),
            _fdata(offset),
            _fdata((I2C1_EEPROM_ADDR << 1) | 1, I2C_FDATA_START),
            _fdata(count & 0xFF, I2C_FDATA_READB | I2C_FDATA_STOP),
        ]

    # Edge anchors on the I2C1 pads, sampled every clk_smc_i cycle.

    async def _wait_start(self, name: str) -> None:
        dut = cocotb.top
        prev = _level(dut.tb_i2c1_sda)
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(dut.clk_smc_i, 1)
            now = _level(dut.tb_i2c1_sda)
            if _level(dut.tb_i2c1_scl) and prev and not now:
                return
            prev = now
        raise AssertionError(f"{name}: no START on the I2C1 pads; {self._pad_state()}")

    async def _wait_rises(self, name: str, nth: int) -> None:
        dut = cocotb.top
        seen = 0
        prev = _level(dut.tb_i2c1_scl)
        for _ in range(EDGE_WAIT_CYCLES):
            await ClockCycles(dut.clk_smc_i, 1)
            now = _level(dut.tb_i2c1_scl)
            if now and not prev:
                seen += 1
                if seen == nth:
                    return
            prev = now
        raise AssertionError(
            f"{name}: only {seen} of {nth} SCL rises on the I2C1 pads; {self._pad_state()}"
        )

    async def _recover_bus(self, name: str) -> None:
        """Clock SCL until the target lets SDA go, then issue a STOP."""
        inj = self.injector
        half = inj._half_ns
        for _ in range(18):
            if _level(cocotb.top.tb_i2c1_sda):
                break
            inj._pull_scl(True)
            await Timer(half, unit="ns")
            inj._pull_scl(False)
            await Timer(half, unit="ns")
        inj._pull_sda(True)
        await Timer(half, unit="ns")
        inj._pull_scl(False)
        await Timer(half, unit="ns")
        inj._pull_sda(False)
        await self._wait_pads(f"{name}_RECOVERED", 1, 1)

    # S1

    async def _s1_bringup(self) -> None:
        await self.csr_write("I2C1_CTRL_OFF", _reg("CTRL"), 0)
        await self.csr_write("I2C1_WRAP_TARGET", _wrap(), I2C_WRAP_CTRL_TARGET)
        await self.csr_read("I2C1_WRAP_TARGET_RB", _wrap(), expected=I2C_WRAP_CTRL_TARGET)
        await self.arm_i2c_gpio_lsio(I2C1, "I2C1_LOOPBACK")
        self.eeprom = SmcI2cEepromSlave(
            addr=I2C1_EEPROM_ADDR, name="smc_i2c1_loopback_eeprom", instance=I2C1
        )
        self.eeprom.preload(bytes(range(256)))
        self.master = SmcI2c1PadVip(
            speed=I2C1_VIP_SPEED,
            name="smc_i2c1_loopback_master",
            scl_timeout_ns=I2C1_VIP_SCL_TIMEOUT_NS,
        )
        self.injector = SmcI2c1PadVip(
            speed=INJECTOR_SPEED,
            name="smc_i2c1_loopback_injector",
            scl_timeout_ns=I2C1_VIP_SCL_TIMEOUT_NS,
        )
        await self._wait_pads("I2C1_PADS_RELEASED", 1, 1)
        await self.csr_write("I2C1_OVRD_OFF", _reg("OVRD"), 0)
        await self._program("I2C1_BRINGUP", BASE_TIMING)
        self._step_done("S1")

    # S2

    async def _drain_acq(self, name: str) -> list[tuple[int, int]]:
        entries = []
        status = 0
        for i in range(ACQ_POLLS):
            status = await self.csr_read(f"{name}_STATUS{i}", _reg("STATUS"))
            if status & I2C_STATUS_ACQEMPTY:
                return entries
            word = await self.csr_read(f"{name}_ACQDATA{i}", _reg("ACQDATA"))
            entries.append(
                ((word & I2C_ACQDATA_SIGNAL) >> I2C_ACQDATA_SIGNAL_BP, word & I2C_ACQDATA_ABYTE)
            )
        raise AssertionError(
            f"{name}: ACQEMPTY not reached after {ACQ_POLLS} pops; last STATUS 0x{status:08x}, "
            f"last entry (SIGNAL, ABYTE) {entries[-1]}"
        )

    async def _target_write(self, name: str, llpbk: bool) -> dict:
        ctrl = I2C_CTRL_ENABLETARGET | I2C_CTRL_ACQ_START_STOP_EN | (CTRL_LLPBK if llpbk else 0)
        await self.csr_write(f"{name}_CTRL", _reg("CTRL"), ctrl)
        await self.csr_read(f"{name}_CTRL_RB", _reg("CTRL"), expected=ctrl)
        self.master.samples.clear()
        acks, samples = await self.master.write_sampled(I2C1_TARGET_ADDR, LLPBK_DATA)
        await self._poll_reg(
            f"{name}_TGT_IDLE",
            "STATUS",
            lambda v: v & I2C_STATUS_TARGETIDLE,
            IDLE_POLLS,
            POLL_GAP_CYCLES,
        )
        return {"acks": acks, "samples": samples}

    async def _s2_llpbk_target(self) -> None:
        await self.csr_write("S2_CTRL_OFF", _reg("CTRL"), 0)
        await self.csr_write(
            "S2_FIFO_RST", _reg("FIFO_CTRL"), I2C_FIFO_CTRL_ACQRST | I2C_FIFO_CTRL_TXRST
        )
        await self.csr_write(
            "S2_TARGET_ID", _reg("TARGET_ID"), _pack_target_id(I2C1_TARGET_ADDR, 0x7F, 0, 0)
        )
        on = await self._target_write("S2_LLPBK_ON", True)
        on_entries = await self._drain_acq("S2_LLPBK_ON")
        driven = [b for byte in LLPBK_DATA for b in ((byte >> (7 - i)) & 1 for i in range(8))]
        assert [d for d, _ in on["samples"]] == driven, f"bench drove {on['samples']}"
        mismatched = [i for i, (d, got) in enumerate(on["samples"]) if d != got]
        assert len(on["samples"]) == 16 and not mismatched, (
            f"with CTRL.LLPBK=1 the SDA pad differed from the driven data bit at bit(s) "
            f"{mismatched}: (driven, sampled) {on['samples']}"
        )
        self._chk(
            "CHK-I2C1-LLPBK-ECHO",
            f"with I2C1 CTRL.LLPBK=1 in target mode at 0x{I2C1_TARGET_ADDR:02x} the bench wrote "
            f"{LLPBK_DATA.hex()} and every tb_i2c1_sda level sampled at the SCL high of each data "
            f"bit equalled the driven bit (16 of 16); observed acknowledge bits {on['acks']} "
            f"(0 = ACK) and ACQ entries (SIGNAL, ABYTE) "
            f"{[(s, f'0x{b:02x}') for s, b in on_entries]} logged, not compared "
            f"(LINKED-ISSUE SF-013)",
        )

        off = await self._target_write("S2_LLPBK_OFF", False)
        acq_want = 4
        await self._poll_reg(
            "S2_LLPBK_OFF_ACQLVL",
            "TARGET_FIFO_STATUS",
            lambda v: (
                ((v & I2C_TARGET_FIFO_STATUS_ACQLVL_BM) >> I2C_TARGET_FIFO_STATUS_ACQLVL_BP)
                >= acq_want
            ),
            ACQ_POLLS,
            POLL_GAP_CYCLES,
        )
        off_entries = await self._drain_acq("S2_LLPBK_OFF")
        await self.csr_write("S2_CTRL_DONE", _reg("CTRL"), 0)
        got = [(s, b) for s, b in off_entries]
        want_head = [
            (I2C_ACQ_SIGNAL_START, I2C1_TARGET_ADDR << 1),
            (I2C_ACQ_SIGNAL_NONE, LLPBK_DATA[0]),
            (I2C_ACQ_SIGNAL_NONE, LLPBK_DATA[1]),
        ]
        assert off["acks"] == [0, 0, 0], (
            f"with LLPBK=0 the target acknowledged {off['acks']} (0 = ACK), expected address and "
            f"both bytes acknowledged"
        )
        assert len(got) == 4 and got[:3] == want_head and got[3][0] == I2C_ACQ_SIGNAL_STOP, (
            f"with LLPBK=0 ACQDATA returned (SIGNAL, ABYTE) {got}; expected START/0x"
            f"{I2C1_TARGET_ADDR << 1:02x}, 0x{LLPBK_DATA[0]:02x}, 0x{LLPBK_DATA[1]:02x}, STOP"
        )
        self._chk(
            "CHK-I2C1-LLPBK-OFF",
            f"with LLPBK=0 the target acknowledged the address and both bytes and ACQDATA held "
            f"(SIGNAL, ABYTE) {[(sig, f'0x{b:02x}') for sig, b in got]} = START/0x"
            f"{I2C1_TARGET_ADDR << 1:02x}, 0x{LLPBK_DATA[0]:02x}, 0x{LLPBK_DATA[1]:02x}, STOP "
            f"(SIGNAL 0x1, 0x0, 0x0, 0x2)",
        )
        self._step_done("S2")

    # S4

    async def _s4_ovrd(self) -> None:
        await self.csr_write("S4_WRAP_HOST", _wrap(), I2C_WRAP_CTRL_HOST)
        await self.csr_read("S4_WRAP_HOST_RB", _wrap(), expected=I2C_WRAP_CTRL_HOST)
        await self._wait_pads("S4_PADS_RELEASED", 1, 1)
        await self._prepare_host("S4")
        vals = []
        for scl, sda in OVRD_PAIRS:
            word = OVRD_TXOVRDEN | (OVRD_SCLVAL if scl else 0) | (OVRD_SDAVAL if sda else 0)
            await self.csr_write(f"S4_OVRD_{scl}{sda}", _reg("OVRD"), word)
            await self._wait_pads(f"S4_OVRD_{scl}{sda}", scl, sda)
            val = await self.csr_read(f"S4_VAL_{scl}{sda}", _reg("VAL"))
            vals.append(((scl, sda), "override", val))
        for line in ("scl", "sda"):
            pull = self.injector._pull_scl if line == "scl" else self.injector._pull_sda
            want = (0, 1) if line == "scl" else (1, 0)
            pull(True)
            await self._wait_pads(f"S4_BENCH_{line}", *want)
            val = await self.csr_read(f"S4_VAL_BENCH_{line}", _reg("VAL"))
            pull(False)
            await self._wait_pads(f"S4_BENCH_{line}_REL", 1, 1)
            vals.append((want, f"bench {line} low", val))
        bad = [
            (pads, how, f"0x{v:08x}")
            for pads, how, v in vals
            if (int(bool(v & VAL_SCL_RX_BIT0)), int(bool(v & VAL_SDA_RX_BIT0))) != pads
        ]
        await self.csr_write("S4_OVRD_OFF", _reg("OVRD"), 0)
        await self.csr_read("S4_OVRD_OFF_RB", _reg("OVRD"), expected=0)
        assert not bad, (
            f"VAL bit 0 / bit 16 disagree with the pad levels (SCL, SDA): {bad}; all {vals}"
        )
        offset, value = OVRD_WRITE
        self.eeprom.write_mem(offset, b"\x00")
        await self._push("S4_WRITE", self._write_words(offset, value))
        status = await self._wait_hostidle("S4_WRITE")
        got = self.eeprom.read_mem(offset, 1)
        assert got == bytes([value]), (
            f"after TXOVRDEN=0 the EEPROM holds 0x{got.hex()} at 0x{offset:02x}, not 0x{value:02x}"
        )
        self._chk(
            "CHK-I2C1-OVRD-PADS",
            "with OVRD.TXOVRDEN=1 the I2C1 pads read (SCL, SDA) = "
            + ", ".join(f"{p}" for p, how, _ in vals if how == "override")
            + f" for (SCLVAL, SDAVAL) = {', '.join(str(p) for p in OVRD_PAIRS)} (0 low, 1 "
            f"released); after TXOVRDEN=0 the EEPROM received 0x{offset:02x}, 0x{value:02x} and "
            f"STATUS=0x{status:08x} has HOSTIDLE=1",
        )
        self._chk(
            "CHK-I2C1-OVRD-VAL",
            "VAL bit 0 (SCL_RX) and bit 16 (SDA_RX) equalled the pad levels in every case: "
            + "; ".join(f"{how} {pads} VAL=0x{v:08x}" for pads, how, v in vals)
            + " (full VAL logged; sampling rate open, SF-014)",
        )
        self._step_done("S4")

    # S5

    async def _s5_rx_overflow(self) -> None:
        await self._prepare_host("S5", enable=False)
        await self._program("S5_FAST", FAST_TIMING)
        await self.csr_write("S5_ENABLEHOST", _reg("CTRL"), I2C_CTRL_ENABLEHOST)
        mem = self.eeprom.read_mem(0, 256)
        await self._push("S5_READ256", self._read_words(0, 0))
        full = await self._poll_reg(
            "S5_RXFULL", "STATUS", lambda v: v & I2C_STATUS_RXFULL, RXFULL_POLLS, RXFULL_GAP_CYCLES
        )
        level_at_full = _rxlvl(await self.csr_read("S5_LEVEL_FULL", _reg("HOST_FIFO_STATUS")))
        intr_full = await self.csr_read("S5_INTR_FULL", _reg("INTR_STATE"))
        popped: list[int] = []
        empty_status = 0
        for i in range(DRAIN_LIMIT):
            empty_status = await self.csr_read(f"S5_DRAIN_STATUS{i}", _reg("STATUS"))
            if empty_status & I2C_STATUS_RXEMPTY:
                break
            popped.append(await self.csr_read(f"S5_RDATA{i}", _reg("RDATA")) & 0xFF)
        else:
            raise AssertionError(
                f"S5: RXEMPTY not reached in {DRAIN_LIMIT} reads; popped {len(popped)}; last "
                f"STATUS 0x{empty_status:08x}"
            )
        late: list[int] = []
        status = 0
        for i in range(DRAIN_LIMIT):
            status = await self.csr_read(f"S5_LATE_STATUS{i}", _reg("STATUS"))
            done = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY | I2C_STATUS_RXEMPTY
            if status & done == done:
                break
            if status & I2C_STATUS_RXEMPTY:
                await ClockCycles(cocotb.top.clk_periph_i, POLL_GAP_CYCLES)
            else:
                late.append(await self.csr_read(f"S5_LATE_RDATA{i}", _reg("RDATA")) & 0xFF)
        else:
            raise AssertionError(
                f"S5: the controller did not return to idle with RX empty in {DRAIN_LIMIT} reads; "
                f"late bytes {len(late)}; last STATUS 0x{status:08x}"
            )
        assert popped, f"S5: RXFULL was set (STATUS=0x{full:08x}) but nothing was popped"
        starts = [
            k
            for k in range(256)
            if all(popped[j] == mem[(k + j) % 256] for j in range(len(popped)))
        ]
        assert starts, (
            f"S5: the {len(popped)} popped bytes are not one in-order run of consecutive EEPROM "
            f"bytes: {bytes(popped).hex()}"
        )
        intr_end = await self.csr_read("S5_INTR_END", _reg("INTR_STATE"))
        await self.csr_write("S5_INTR_CLR", _reg("INTR_STATE"), INTR_RX_OVERFLOW)
        intr_clr = await self.csr_read("S5_INTR_CLR_RB", _reg("INTR_STATE"))
        assert intr_clr & INTR_RX_OVERFLOW == 0, (
            f"S5: INTR_STATE.RX_OVERFLOW survived the written 0x8 (0x{intr_clr:08x})"
        )
        self._chk(
            "CHK-I2C1-RX-OVERFLOW",
            f"a READB of 256 bytes (FBYTE=0) with no RDATA pops set STATUS.RXFULL "
            f"(STATUS=0x{full:08x}); the {len(popped)} bytes popped until STATUS.RXEMPTY=1 "
            f"(STATUS=0x{empty_status:08x}) are one in-order run of consecutive EEPROM bytes "
            f"from offset 0x{starts[0]:02x}; writing 0x8 left INTR_STATE=0x{intr_clr:08x} with "
            f"RX_OVERFLOW=0. Measured, not compared (LINKED-ISSUE SF-004): RXLVL at RXFULL="
            f"{level_at_full}, INTR_STATE at RXFULL=0x{intr_full:08x} (RX_OVERFLOW="
            f"{int(bool(intr_full & INTR_RX_OVERFLOW))}), INTR_STATE before the clear=0x"
            f"{intr_end:08x}, {len(late)} further bytes popped after the first RXEMPTY until "
            f"HOSTIDLE ({bytes(late[:8]).hex()}{'...' if len(late) > 8 else ''})",
        )

        await self.csr_write("S5_CTRL_OFF2", _reg("CTRL"), 0)
        await self._program("S5_BASE", BASE_TIMING)
        await self.csr_write("S5_ENABLEHOST2", _reg("CTRL"), I2C_CTRL_ENABLEHOST)
        await self._push("S5_REFILL", self._read_words(0, REFILL_BYTES))
        await self._wait_hostidle("S5_REFILL")
        refill = _rxlvl(await self.csr_read("S5_REFILL_LEVEL", _reg("HOST_FIFO_STATUS")))
        assert refill == REFILL_BYTES, (
            f"S5: a {REFILL_BYTES}-byte read left RXLVL={refill}; RXRST needs a filled FIFO"
        )
        await self.csr_write("S5_RXRST", _reg("FIFO_CTRL"), I2C_FIFO_CTRL_RXRST)
        status = await self.csr_read("S5_RXRST_STATUS", _reg("STATUS"))
        level = _rxlvl(await self.csr_read("S5_RXRST_LEVEL", _reg("HOST_FIFO_STATUS")))
        assert status & I2C_STATUS_RXEMPTY and level == 0, (
            f"S5: after FIFO_CTRL.RXRST=1 STATUS=0x{status:08x} RXLVL={level}"
        )
        self._chk(
            "CHK-I2C1-RXRST",
            f"with RXLVL={refill} after a {REFILL_BYTES}-byte read, FIFO_CTRL.RXRST=1 left "
            f"STATUS=0x{status:08x} (RXEMPTY=1) and HOST_FIFO_STATUS.RXLVL=0",
        )
        self._step_done("S5")

    # S6

    async def _pull_scl_in_high(self, name: str) -> None:
        await self._wait_start(name)
        await self._wait_rises(name, SCL_PULL_RISE)
        await Timer(SCL_PULL_DELAY_NS, unit="ns")
        self.injector._pull_scl(True)
        await Timer(SCL_PULL_NS, unit="ns")
        self.injector._pull_scl(False)

    async def _s6_scl_interference(self) -> None:
        offset, value = SCL_WRITE
        await self._prepare_host("S6_CLEAN")
        self.eeprom.write_mem(offset, b"\x00")
        await self._push("S6_CLEAN", self._write_words(offset, value))
        await self._wait_hostidle("S6_CLEAN")
        got = self.eeprom.read_mem(offset, 1)
        assert got == bytes([value]), f"S6: the clean write left 0x{got.hex()} at the EEPROM"
        clean = await self.csr_read("S6_CLEAN_INTR", _reg("INTR_STATE"))
        assert clean & INTR_SCL_INTERFERENCE == 0, (
            f"S6: a clean write raised SCL_INTERFERENCE (INTR_STATE=0x{clean:08x})"
        )
        await self._prepare_host("S6_PULL")
        injector = cocotb.start_soon(self._pull_scl_in_high("S6_PULL"))
        await self._push("S6_PULL", self._write_words(offset, value))
        await injector
        seen = await self._wait_intr("S6_PULL", INTR_SCL_INTERFERENCE)
        idle = await self._wait_hostidle("S6_PULL", I2C_STATUS_HOSTIDLE)
        await self.csr_write("S6_CTRL_OFF", _reg("CTRL"), 0)
        await self._recover_bus("S6")
        await self.csr_write("S6_INTR_CLR", _reg("INTR_STATE"), INTR_SCL_INTERFERENCE)
        cleared = await self.csr_read("S6_INTR_CLR_RB", _reg("INTR_STATE"))
        assert cleared & INTR_SCL_INTERFERENCE == 0, (
            f"S6: SCL_INTERFERENCE survived the written 0x20 (INTR_STATE=0x{cleared:08x})"
        )
        self._chk(
            "CHK-I2C1-SCL-INTERFERENCE",
            f"a clean write left INTR_STATE=0x{clean:08x} (SCL_INTERFERENCE=0); tb_i2c1_scl "
            f"pulled low for {SCL_PULL_NS} ns from {SCL_PULL_DELAY_NS} ns after SCL rise "
            f"{SCL_PULL_RISE} (address acknowledge pulse) gave INTR_STATE=0x{seen:08x} "
            f"(SCL_INTERFERENCE=1), STATUS at HOSTIDLE 0x{idle:08x} logged; writing 0x20 left "
            f"INTR_STATE=0x{cleared:08x} (SCL_INTERFERENCE=0)",
        )
        self._step_done("S6")

    # S7

    async def _toggle_sda_in_high(self, name: str) -> None:
        await self._wait_start(name)
        await self._wait_rises(name, SDA_PULL_RISE)
        before = _level(cocotb.top.tb_i2c1_sda)
        self.injector._pull_sda(True)
        hold = int(BASE_TIMING[0] * float(self.cfg.periph_clk_period_ns) * SDA_PULL_HIGH_FRACTION)
        await Timer(hold, unit="ns")
        self.injector._pull_sda(False)
        self.sda_toggle = (before, hold)

    async def _s7_sda_unstable(self) -> None:
        await self._prepare_host("S7_CLEAN")
        await self._push("S7_CLEAN", self._read_words(SDA_READ_OFFSET, SDA_READ_BYTES))
        await self._wait_hostidle("S7_CLEAN")
        got = bytes(
            [
                (await self.csr_read(f"S7_CLEAN_RDATA{i}", _reg("RDATA"))) & 0xFF
                for i in range(SDA_READ_BYTES)
            ]
        )
        want = self.eeprom.read_mem(SDA_READ_OFFSET, SDA_READ_BYTES)
        assert got == want, f"S7: the clean read returned {got.hex()}, not {want.hex()}"
        clean = await self.csr_read("S7_CLEAN_INTR", _reg("INTR_STATE"))
        assert clean & I2C_INTR_SDA_UNSTABLE == 0, (
            f"S7: a clean read raised SDA_UNSTABLE (INTR_STATE=0x{clean:08x})"
        )
        await self._prepare_host("S7_TOGGLE")
        injector = cocotb.start_soon(self._toggle_sda_in_high("S7_TOGGLE"))
        await self._push("S7_TOGGLE", self._read_words(SDA_READ_OFFSET, SDA_READ_BYTES))
        await injector
        before, hold = self.sda_toggle
        assert before == 1, f"S7: SDA was {before} before the pull; no edge was made"
        seen = await self._wait_intr("S7_TOGGLE", I2C_INTR_SDA_UNSTABLE)
        idle = await self._wait_hostidle("S7_TOGGLE", I2C_STATUS_HOSTIDLE)
        await self.csr_write("S7_CTRL_OFF", _reg("CTRL"), 0)
        await self._recover_bus("S7")
        await self.csr_write("S7_FIFO_RST", _reg("FIFO_CTRL"), I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("S7_INTR_CLR", _reg("INTR_STATE"), I2C_INTR_SDA_UNSTABLE)
        cleared = await self.csr_read("S7_INTR_CLR_RB", _reg("INTR_STATE"))
        assert cleared & I2C_INTR_SDA_UNSTABLE == 0, (
            f"S7: SDA_UNSTABLE survived the written 0x100 (INTR_STATE=0x{cleared:08x})"
        )
        self._chk(
            "CHK-I2C1-SDA-UNSTABLE",
            f"a clean {SDA_READ_BYTES}-byte read returned {got.hex()} and left "
            f"INTR_STATE=0x{clean:08x} (SDA_UNSTABLE=0); tb_i2c1_sda pulled low for {hold} ns "
            f"at SCL rise {SDA_PULL_RISE} (bit 6 of the first read byte 0x{want[0]:02x}, SDA "
            f"high before) gave INTR_STATE=0x{seen:08x} (SDA_UNSTABLE=1), STATUS at HOSTIDLE "
            f"0x{idle:08x} logged; writing 0x100 left INTR_STATE=0x{cleared:08x} "
            f"(SDA_UNSTABLE=0)",
        )
        self._step_done("S7")

    def _fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        ran = [e[1] for e in steps]
        stamps = [e[2] for e in steps]
        assert ran == list(STEPS), f"steps run {ran}, expected {list(STEPS)}"
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        step_at = {e[1]: e[2] for e in steps}
        chk_step = {
            "CHK-I2C1-LLPBK-ECHO": "S2",
            "CHK-I2C1-LLPBK-OFF": "S2",
            "CHK-I2C1-OVRD-PADS": "S4",
            "CHK-I2C1-OVRD-VAL": "S4",
            "CHK-I2C1-RX-OVERFLOW": "S5",
            "CHK-I2C1-RXRST": "S5",
            "CHK-I2C1-SCL-INTERFERENCE": "S6",
            "CHK-I2C1-SDA-UNSTABLE": "S7",
        }
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == list(chk_step), f"checker order {[c[1] for c in chks]}"
        for _, cid, t in chks:
            step = chk_step[cid]
            prev = STEPS[STEPS.index(step) - 1]
            assert step_at[prev] <= t <= step_at[step], f"{cid} printed outside {step}"
        terms = " < ".join(f"{FENCE_TERMS[st]}@{step_at[st]}" for st in ran)
        cocotb.log.info(
            "CHK-NONVAC: ordered fence after CHK-I2C-TGT-LOOPBACK-BLOCKED, "
            "CHK-I2C-TGT-LOOPBACK-ECHO: %s; checker lines %s",
            terms,
            ", ".join(e[1] for e in self._events if e[0] == "chk"),
        )

    async def _i2c1_legs(self) -> None:
        await self._s1_bringup()
        await self._s2_llpbk_target()
        await self._s4_ovrd()
        await self._s5_rx_overflow()
        await self._s6_scl_interference()
        await self._s7_sda_unstable()
        self._fence()
        paths = self._timeout_paths()
        cocotb.log.info("CHK-TIMEOUT-PATHS: %d bounded waits: %s", len(paths), "; ".join(paths))

    def _timeout_paths(self) -> list[str]:
        """Every bounded wait of the leaf, its bound, its expiry path and the state it reports."""
        poll = "clk_periph_i cycles apart fail-on-expiry=AssertionError"
        return [
            f"axi_access (every SEP_IN read and write)={self.cfg.axi_timeout_ns} ns "
            f"enforced-by=smc_sys_axi_agent fail-on-expiry=AssertionError last=access address",
            "i2c0_lsio_ready (pre-existing I2C0 leg)=2000 polls 4 clk_smc_i cycles apart "
            "enforced-by=smc_csr_seq_utils.wait_i2c0_lsio_ready fail-on-expiry=AssertionError "
            "last=I2C0 enable, bus SCL and pad-sense SCL/SDA",
            f"i2c0_txfull_fill (pre-existing I2C0 leg)={MAX_TX_DEPTH} STATUS reads "
            f"fail-on-expiry=AssertionError last=STATUS",
            f"i2c0_vip_scl_release (pre-existing I2C0 leg)="
            f"{SmcI2cMasterVip.DEFAULT_SCL_TIMEOUT_HALF_PERIODS * (int(1e9 / VIP_SPEED) // 2)} ns "
            f"per SCL release enforced-by=smc_i2c_protocol_vip.SmcI2cMasterVip (outside the leaf) "
            f"fail-on-expiry=SmcI2cVipError last=hold time",
            f"i2c1_vip_scl_release={I2C1_VIP_SCL_TIMEOUT_NS} ns per SCL release "
            f"enforced-by=smc_i2c_protocol_vip.SmcI2cMasterVip (outside the leaf) "
            f"fail-on-expiry=SmcI2cVipError last=hold time",
            f"pad_level={PAD_POLLS} polls {PAD_GAP_CYCLES} {poll} last=tb_i2c1_scl/tb_i2c1_sda",
            f"pad_edge (START and SCL-rise anchors)={EDGE_WAIT_CYCLES} clk_smc_i cycles "
            f"fail-on-expiry=AssertionError last=tb_i2c1_scl/tb_i2c1_sda, plus the rises seen "
            f"for an SCL-rise anchor",
            f"target_idle={IDLE_POLLS} STATUS polls {POLL_GAP_CYCLES} {poll} last=STATUS and pads",
            f"acq_drain={ACQ_POLLS} STATUS reads / ACQDATA pops fail-on-expiry=AssertionError "
            f"last=STATUS and last ACQDATA entry",
            f"acq_level={ACQ_POLLS} TARGET_FIFO_STATUS polls {POLL_GAP_CYCLES} {poll} "
            f"last=TARGET_FIFO_STATUS and pads",
            f"transfer_done={IDLE_POLLS} STATUS polls {POLL_GAP_CYCLES} {poll} "
            f"last=STATUS and pads",
            f"rxfull={RXFULL_POLLS} STATUS polls {RXFULL_GAP_CYCLES} {poll} last=STATUS and pads",
            f"rx_drain={DRAIN_LIMIT} STATUS reads / RDATA pops fail-on-expiry=AssertionError "
            f"last=STATUS and pop count",
            f"rx_idle={DRAIN_LIMIT} STATUS reads / RDATA pops, {POLL_GAP_CYCLES} clk_periph_i "
            f"cycles apart while empty, fail-on-expiry=AssertionError last=STATUS and late "
            f"byte count",
            f"intr_state={INTR_POLLS} INTR_STATE polls {POLL_GAP_CYCLES} {poll} "
            f"last=INTR_STATE and pads",
            "bus_recover=at most 18 SCL pulses then pad_level last=tb_i2c1_scl/tb_i2c1_sda",
            f"fixed waits with no expiry (pre-existing I2C0 leg): 1 us before the VIP write and "
            f"{SETTLE_CYCLES} clk_smc_i cycles after the write, after the ACQDATA read and after "
            f"the read",
        ]
