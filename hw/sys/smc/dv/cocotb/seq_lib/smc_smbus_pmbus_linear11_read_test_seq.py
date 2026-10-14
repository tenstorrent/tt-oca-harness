# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller read-word transfers with SMBus field variations.

Sources: hw/ip/i2c/regs/i2c.rdl (FDATA, RDATA, SMBUS_CTRL.SMBSUS), hw/ip/i2c/regs/i2c_ctrl.rdl
(I2C_CONTROLLER_MODE_EN), hw/ip/i2c/doc/memmap.adoc (Endianness).

The word is a data pattern: the two RDATA bytes are compared in the order the bench target
sent them, and the Linear11 decode is logged and not compared (owner value pending).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_SMBUS_CTRL_SMBSUS,
    I2C_STATUS_RXEMPTY,
    I2C_WRAP_CTRL_HOST_SMBUS,
    I2C_WRAP_EN,
    I2C_WRAP_SMBUS_EN,
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

I2C0_SMBUS_CTRL = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_SMBUS_CTRL_BASE_ADDR", 0)

EEPROM = 0x50
WR = EEPROM << 1
RD = (EEPROM << 1) | 1
POS_CMD = 0x88
POS_WORD = bytes([0xF4, 0xF1])
NEG_CMD = 0x8B
NEG_WORD = bytes([0xD4, 0xEE])

DONE_POLLS = 2000
DONE_STEP = 200
WIRE_POLLS = 4000
WIRE_STEP = 16
PROBE_POLLS = 4000
PROBE_STEP = 16
BUS_POLLS = 2000
BUS_STEP = 16

FENCE_ORDER = [
    "TARGET_ARMED",
    "WORD_READ",
    "NEG_WORD_READ",
    "SUS_DURING_XFER",
    "FIELD_CLEARED",
    "TEARDOWN",
]
CHECKER_AFTER = {
    "CHK-PMBUS-WORD-BYTES": "WORD_READ",
    "CHK-PMBUS-NEG-WORD-BYTES": "NEG_WORD_READ",
    "CHK-PMBUS-DECODE-LOG": "NEG_WORD_READ",
    "CHK-SUS-DURING-XFER": "SUS_DURING_XFER",
    "CHK-SCL-SDA-FIELD-INVARIANT": "FIELD_CLEARED",
}


def _linear11(word: bytes) -> str:
    """Decode two bytes (first byte low) as Linear11: signed 5-bit [15:11], signed 11-bit [10:0]."""
    raw = word[0] | (word[1] << 8)
    exp = raw >> 11
    exp -= 32 if exp & 0x10 else 0
    man = raw & 0x7FF
    man -= 2048 if man & 0x400 else 0
    return f"word=0x{raw:04x} exponent={exp} mantissa={man} value={man * 2.0**exp}"


class smc_smbus_pmbus_linear11_read_test_seq(SmcCsrSeq):
    """Read a two-byte word through the DUT I2C0 controller under SMBus field variations."""

    def __init__(self, name: str = "smc_smbus_pmbus_linear11_read_test_seq") -> None:
        super().__init__(name)
        self.slave: SmcI2cEepromSlave | None = None
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []
        self.waits: list[tuple[str, str, str]] = []
        self.cg = 0
        self.pos_decode = ""

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

    def _counters(self) -> tuple[int, int, int]:
        return self.slave.starts, self.slave.stops, self.slave.acks

    def _wire_state(self) -> str:
        dut = cocotb.top
        return (
            f"starts={self.slave.starts} stops={self.slave.stops} acks={self.slave.acks} "
            f"scl={self._bit(dut.tb_i2c0_scl, 'tb_i2c0_scl')} "
            f"sda={self._bit(dut.tb_i2c0_sda, 'tb_i2c0_sda')} "
            f"smbsus_dut_low={self._bit(dut.tb_i2c0_smbsus_dut_low, 'tb_i2c0_smbsus_dut_low')}"
        )

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

    async def _bring_up(self) -> None:
        self.slave = SmcI2cEepromSlave(addr=EEPROM, name="smc_i2c0_pmbus_eeprom")
        self.slave.write_mem(POS_CMD, POS_WORD)
        self.slave.write_mem(NEG_CMD, NEG_WORD)
        self.cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, self.cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST_SMBUS", I2C0_WRAP_CTRL, I2C_WRAP_CTRL_HOST_SMBUS)
        await self.wait_i2c0_lsio_ready("I2C0_PMBUS")
        await self.csr_write("I2C0_OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("I2C0_TIMING0", I2C0_TIMING0, _pack_timing0(0x1A, 0x32))
        await self.csr_write("I2C0_TIMING1", I2C0_TIMING1, _pack_timing1(2, 2))
        await self.csr_write("I2C0_TIMING2", I2C0_TIMING2, _pack_timing2(5, 4))
        await self.csr_write("I2C0_TIMING3", I2C0_TIMING3, _pack_timing3(2, 5))
        await self.csr_write("I2C0_TIMING4", I2C0_TIMING4, _pack_timing4(4, 5))
        await self.csr_write("I2C0_FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("I2C0_CTRL_ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        self._stamp("TARGET_ARMED")

    async def _queue_read(self, label: str, cmd: int) -> None:
        await self.csr_write(f"{label}_ADDR_W", I2C0_FDATA, _fdata(WR, I2C_FDATA_START))
        await self.csr_write(f"{label}_CMD", I2C0_FDATA, _fdata(cmd))
        await self.csr_write(f"{label}_ADDR_R", I2C0_FDATA, _fdata(RD, I2C_FDATA_START))
        await self.csr_write(
            f"{label}_READ", I2C0_FDATA, _fdata(2, I2C_FDATA_READB | I2C_FDATA_STOP)
        )

    async def _wait_done(self, label: str) -> None:
        """Poll STATUS until HOSTIDLE is set and RXEMPTY is clear."""

        async def probe() -> tuple[bool, str]:
            status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
            return (
                bool(status & I2C_STATUS_HOSTIDLE) and not status & I2C_STATUS_RXEMPTY,
                f"STATUS=0x{status:08x}",
            )

        await self._poll(f"{label}_done", DONE_POLLS, DONE_STEP, probe)

    async def _collect(self, label: str, base: tuple[int, int, int]) -> tuple[bytes, str]:
        """Read two RDATA bytes and check the target counter deltas against ``base``."""
        got = bytes(
            [(await self.csr_read(f"{label}_RDATA{i}", I2C0_RDATA)) & 0xFF for i in range(2)]
        )
        want = (base[0] + 2, base[1] + 1, base[2] + 2)

        async def probe() -> tuple[bool, str]:
            return self._counters() == want, f"want starts,stops,acks={want} {self._wire_state()}"

        await self._poll(f"{label}_counters", WIRE_POLLS, WIRE_STEP, probe)
        delta = tuple(a - b for a, b in zip(self._counters(), base))
        assert delta == (2, 1, 2), f"{label}: counter deltas {delta}, expected (2, 1, 2)"
        return got, f"counter deltas starts={delta[0]} stops={delta[1]} acks={delta[2]}"

    async def _word_read(self, label: str, cmd: int, word: bytes) -> tuple[bytes, str]:
        base = self._counters()
        await self._queue_read(label, cmd)
        await self._wait_done(label)
        got, deltas = await self._collect(label, base)
        assert got == word, f"{label}: RDATA bytes {got.hex()}, expected {word.hex()}"
        return got, deltas

    async def _s2(self) -> None:
        got, deltas = await self._word_read("S2", POS_CMD, POS_WORD)
        self._stamp("WORD_READ")
        self._chk(
            "CHK-PMBUS-WORD-BYTES",
            f"RDATA {got[0]:02x} then {got[1]:02x} in wire order from command 0x{POS_CMD:02x}; "
            f"{deltas}",
        )
        self.pos_decode = _linear11(got)

    async def _s3(self) -> None:
        got, deltas = await self._word_read("S3", NEG_CMD, NEG_WORD)
        self._stamp("NEG_WORD_READ")
        self._chk(
            "CHK-PMBUS-NEG-WORD-BYTES",
            f"RDATA {got[0]:02x} then {got[1]:02x} in wire order from command 0x{NEG_CMD:02x}; "
            f"{deltas}",
        )
        self._chk(
            "CHK-PMBUS-DECODE-LOG",
            f"command 0x{POS_CMD:02x} {self.pos_decode}; command 0x{NEG_CMD:02x} "
            f"{_linear11(got)}; logged, no value compared (owner value pending)",
        )

    def _sus_low(self) -> int:
        return self._bit(cocotb.top.tb_i2c0_smbsus_dut_low, "tb_i2c0_smbsus_dut_low")

    async def _s4(self) -> None:
        dut = cocotb.top
        base = self._counters()
        pre = self._sus_low()
        await self._queue_read("S4", POS_CMD)

        async def on_wire() -> tuple[bool, str]:
            return self.slave.starts > base[0], f"want starts>{base[0]} {self._wire_state()}"

        await self._poll("S4_transfer_on_wire", WIRE_POLLS, WIRE_STEP, on_wire)
        stops_open = self.slave.stops
        assert stops_open == base[1], (
            f"S4: transfer already stopped before the SMBSUS write ({self._wire_state()})"
        )
        await self.csr_write("S4_SMBSUS_SET", I2C0_SMBUS_CTRL, I2C_SMBUS_CTRL_SMBSUS)
        seen: list[int] = []

        async def differs() -> tuple[bool, str]:
            seen.append(self._sus_low())
            return seen[-1] != pre, f"pre={pre} sample={seen[-1]} {self._wire_state()}"

        await self._poll("S4_smbsus_differs", PROBE_POLLS, PROBE_STEP, differs)
        observed = seen[-1]
        await self._wait_done("S4")
        got, deltas = await self._collect("S4", base)
        assert got == POS_WORD, f"S4: RDATA bytes {got.hex()}, expected {POS_WORD.hex()}"
        await self.csr_write("S4_SMBSUS_CLR", I2C0_SMBUS_CTRL, 0)

        async def restored() -> tuple[bool, str]:
            cur = self._sus_low()
            return cur == pre, f"pre={pre} sample={cur} {self._wire_state()}"

        await self._poll("S4_smbsus_restored", PROBE_POLLS, PROBE_STEP, restored)
        after = self._sus_low()
        assert self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl") == 1
        self._stamp("SUS_DURING_XFER")
        self._chk(
            "CHK-SUS-DURING-XFER",
            f"set: SMBUS_CTRL.SMBSUS written 1 with the transfer on the wire (starts "
            f"{self.slave.starts - base[0]} of 2, stops {stops_open - base[1]} before the "
            f"write); observed: tb_i2c0_smbsus_dut_low {observed} against pre-write sample "
            f"{pre}; transfer completed RDATA {got[0]:02x} {got[1]:02x}, {deltas}; cleared: "
            f"SMBSUS written 0; checked_cleared: tb_i2c0_smbsus_dut_low {after} equals {pre}",
        )

    async def _s5(self) -> None:
        dut = cocotb.top
        base = self._counters()
        await self.csr_write("S5_WRAP_FIELD_CLEAR", I2C0_WRAP_CTRL, I2C_WRAP_EN | I2C_WRAP_SMBUS_EN)
        await self._queue_read("S5", POS_CMD)
        await self._wait_done("S5")
        got, deltas = await self._collect("S5", base)
        assert got == POS_WORD, f"S5: RDATA bytes {got.hex()}, expected {POS_WORD.hex()}"

        async def released() -> tuple[bool, str]:
            scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
            sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
            return (scl, sda) == (1, 1), f"scl={scl} sda={sda}"

        await self._poll("S5_bus_released", BUS_POLLS, BUS_STEP, released)
        scl = self._bit(dut.tb_i2c0_scl, "tb_i2c0_scl")
        sda = self._bit(dut.tb_i2c0_sda, "tb_i2c0_sda")
        self._stamp("FIELD_CLEARED")
        self._chk(
            "CHK-SCL-SDA-FIELD-INVARIANT",
            f"I2C_CTRL[0]=I2C_EN|SMBUS_EN (I2C_CONTROLLER_MODE_EN clear): RDATA {got[0]:02x} "
            f"then {got[1]:02x}, {deltas}; after the stop tb_i2c0_scl={scl} tb_i2c0_sda={sda}",
        )

    async def _teardown(self) -> None:
        await self.csr_write("I2C0_CTRL_ENABLEHOST_OFF", I2C0_CTRL, 0)
        await self.csr_write("I2C0_WRAP_OFF", I2C0_WRAP_CTRL, 0)
        await self.csr_write("CLOCK_GATE_RESTORE", CLOCK_GATE_CONTROL, self.cg)
        self._stamp("TEARDOWN")

    def _emit_timeout_paths(self) -> None:
        cfg = self.cfg
        inherited = [
            (
                "cold_reset_release",
                f"{max(cfg.post_reset_settle_cycles, 2000)} clk_ref_i cycles",
                "chain released before bring-up returned",
            ),
            ("pll_period_measure", "5 rising edges per clock", "periods within tolerance"),
            ("i2c0_lsio_ready", "2000x4cyc", "bus_scl=1 scl_i=1"),
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
        await self._bring_up()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._teardown()
        self._emit_timeout_paths()
        self._emit_nonvac()
