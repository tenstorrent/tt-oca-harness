# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-lane, half-word and lane-strobed writes to the register blocks whose cpuif is 32 bits wide.

Each leg takes one register of a narrow-cpuif block, reads a neighbour register
and the target's saved word, writes a preload that sets the target's writable
fields, then complements the plain read-write bits of one lane at a time
through 1-byte writes at every lane, of two lanes through 2-byte writes at
offsets 0 and 2, and of three lanes through four 4-byte writes that each leave
one lane unstrobed while every lane of the beat carries the complemented
bits. After every write the target must read the expected image: the lanes
the write enabled carry the complement, every other lane the value it held,
so a dropped write, a write on the wrong lane, a zero-filled lane and a strobe
the block ignored each read back as a mismatch. The cpuif of the block sees,
for every plain field, a write with that field's lane off while its storage
holds a one, and a write whose unstrobed lane carries the opposite of the
storage. A full-width restore must read back the saved word over the plain
fields and the neighbour must read what it read before the leg. A target with
no plain field (write-only clears, self-clearing starts) must read the same
word after every write that it read before the leg, outside the field a
write-only register is declared to drive (`FCR` drives `IIR.FIFOS_ENABLED`). The UART's read-only LSR
and MSR take one byte write each and must not change.

The target of each block is a register whose preload has no effect on the bench
while the SMC is idle:

* reset unit `ISOLATE_REQ_FLR_COUNTER_VALUE`: the FLR sequencer reads it only
  during an FLR; no hold, lock or reset control register is written.
* GPIO interface 5 `DATA_CTRL`: pad 5 has no bench pull, probe or LSIO tie;
  `interrupt_enable` and `lsio_select` stay 0 through every write.
* AVSBus `AVS_CFG_1` divider fields with `FORCE_SLAVE_RESYNC_OPERATION` and
  `TURN_OFF_ALL_PREMUX_CLOCKS` 0 through every write, and
  `AVS_INTERRUPT_CLEAR` with every clear bit set while no AVSBus interrupt is
  pending.
* I2C control `I2C_CTRL[0]` enables (the I2C0 pads carry the bench pull-ups and
  no transaction is issued), I2C0 `INTR_TEST` read-write bits (restored to 0)
  and `FIFO_CTRL` FIFO resets on empty FIFOs.
* eFuse `EFUSE_PROGRAM_CTRL` address, data and read-back fields with
  `efuse_program_go` and `program_enable` 0 through every write, and the clear
  bits of `EFUSE_INTERFACE_CTRL_STATUS` with no error pending.
* UART0 `SCR`, `LCR` with `DLAB` and `SET_BREAK` 0 through every write, `FCR` with the FIFOs
  enabled (`IIR.FIFOS_ENABLED` reads 3 after every write and 0 after the
  restore), and the wrapper `CTRL.UART_EN` restored to 0.
* log engine `INTR_TEST`, whose `INTR_STATUS` bits read set after the writes
  and 0 after the clear.
* telemetry receiver 1 `CTRL` threshold and flush bits, and `INTR_TEST`.
* system timer `TIMER_START`, written back to 0.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import CLOCK_GATE_CONTROL, TELEMETRY_CG_EN, UART_CG_EN
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    FCR_FIFO_ENABLE,
    FCR_OFFSET,
    FCR_RCVR_TRIGGER_SHIFT,
    IIR_FIFOS_ENABLED,
    IIR_FIFOS_SHIFT,
    uart_base,
)
from .smc_rdl_regmap import RdlReg, rdl_register
from .smc_regblock_subword_strobe_sweep_test_seq import FUSE_BOUND

LANES = (0, 1, 2, 3)
HALVES = (0, 2)
STROBES = (0xE, 0xD, 0xB, 0x7)
# Writes of one leg: the preload, one per lane, half-word and strobe, the restore.
WRITES_PER_LEG = 1 + len(LANES) + len(HALVES) + len(STROBES) + 1
# Accesses of one leg: two reads before the writes, a readback per write, the neighbour read.
LEG_ACCESSES = 2 + 2 * WRITES_PER_LEG + 1
# An `after` entry reads the register, writes the clear and reads it again.
AFTER_ACCESSES = 3
UART_RO_ACCESSES = 6
CG_ACCESSES = 5

_UART = "smc_uart_wrap/uart_log_engine_wrap[0]/uart"
_LOG = "smc_uart_wrap/uart_log_engine_wrap[0]/log_engine"
_I2C0 = "smc_i2c_wrap/i2c[0]"
_TEL1 = "smc_telemetry_receiver_wrap/telemetry_receiver[1]"
_EFUSE = "efuse_interface_ctrl"
_AVS = "smc_avsbus_controller"
_GPIO5 = "gpio_intf_wrap/gpio_intf[5]"


@dataclass(frozen=True)
class Observe:
    """A read-only register whose field follows the target's writes."""

    label: str
    addr: int
    mask: int
    while_set: int
    after_restore: int


@dataclass(frozen=True)
class Leg:
    block: str
    label: str
    addr: int
    plain_mask: int
    flip_mask: int
    preload: int
    neighbour: int
    restore: int | None
    after: tuple[tuple[str, int, int], ...] = ()
    observe: Observe | None = None


def _word(reg: RdlReg, **values: int) -> int:
    """The register word with each named field at its value and every other bit 0."""
    fields = {f.name: f for f in reg.fields}
    word = 0
    for name, value in values.items():
        field = fields[name]
        assert value & ~((1 << field.width) - 1) == 0, f"{reg.path}.{name}: {value:#x} too wide"
        word |= value << field.offset
    return word


def _mask(reg: RdlReg, *names: str) -> int:
    fields = {f.name: f for f in reg.fields}
    return sum(fields[name].mask for name in names)


def _leg(
    block: str,
    label: str,
    path: str,
    preload: dict[str, int],
    neighbour: str,
    hold: tuple[str, ...] = (),
    restore: int | None = None,
    after: tuple[tuple[str, str, int], ...] = (),
) -> Leg:
    reg = rdl_register(path)
    assert reg.width_bytes == 4, f"{path} is {reg.width_bytes} bytes wide, the legs take 4"
    held = _mask(reg, *hold)
    word = _word(reg, **preload)
    assert word & held == 0, f"{path}: preload {word:#x} sets a held field {held:#x}"
    return Leg(
        block,
        label,
        reg.addr,
        reg.rw_mask,
        reg.rw_mask & ~held,
        word,
        rdl_register(neighbour).addr,
        restore,
        tuple((lbl, rdl_register(p).addr, v) for lbl, p, v in after),
    )


def build_legs() -> tuple[Leg, ...]:
    iir = rdl_register(f"{_UART}/IIR")
    fcr = uart_base(0) + FCR_OFFSET
    assert fcr == iir.addr, f"FCR {fcr:#x} is not the write-only alias of IIR {iir.addr:#x}"
    log_status = rdl_register(f"{_LOG}/INTR_STATUS")
    return (
        _leg(
            "RESET-UNIT",
            "FLR_COUNT",
            "smc_reset_unit/ISOLATE_REQ_FLR_COUNTER_VALUE",
            {"isolate_req_flr_counter_value": 0x0403_0201},
            "smc_reset_unit/ISOLATE_REQ_FLR_RESET_COUNTER_VALUE",
        ),
        _leg(
            "GPIO",
            "GPIO5_DATA_CTRL",
            f"{_GPIO5}/DATA_CTRL",
            {
                "core2pad": 1,
                "enable_rx_tx": 3,
                "interface_enable": 1,
                "lsio_disable": 1,
                "interrupt_type": 2,
            },
            f"{_GPIO5}/DATA_CTRL_ENABLE",
            hold=("interrupt_enable", "lsio_select"),
        ),
        _leg(
            "AVSBUS",
            "AVS_CFG_1",
            f"{_AVS}/AVS_CFG_1",
            {
                "AVS_CLOCK_SELECT": 3,
                "STOP_AVS_CLOCK_ON_IDLE": 1,
                "CLK_DIVIDER_VALUE": 0x5A,
                "CLK_DIVIDER_DUTY_CYCLE_NUMERATOR": 0xA5,
            },
            f"{_AVS}/AVS_CFG_0",
            hold=("TURN_OFF_ALL_PREMUX_CLOCKS",),
        ),
        _leg(
            "AVSBUS",
            "AVS_INTR_CLEAR",
            f"{_AVS}/AVS_INTERRUPT_CLEAR",
            {
                "CLEAR_AVS_SLAVE_ISSUED_INTERRUPT": 1,
                "CLEAR_CMD_FIFO_FULL_INT": 1,
                "CLEAR_READBACK_FIFO_FULL_INT": 1,
                "CLEAR_READBACK_HAS_DATA_INT": 1,
                "CLEAR_SLAVE_UNRESPONSIVE_INT": 1,
                "CLEAR_MAX_RETRIES_ATTEMPTED_INT": 1,
                "CLEAR_CMD_FIFO_OVERFLOW_INT": 1,
                "CLEAR_READBACK_UNDERFLOW_INT": 1,
                "CLEAR_READBACK_OVERFLOW_INT": 1,
            },
            f"{_AVS}/AVS_INTERRUPT",
            restore=0,
        ),
        _leg(
            "I2C-CTRL",
            "I2C_CTRL0",
            "smc_i2c_wrap/i2c_ctrl_regs/I2C_CTRL[0]",
            {"I2C_EN": 1, "I2C_CONTROLLER_MODE_EN": 1, "SMBUS_EN": 1},
            "smc_i2c_wrap/i2c_ctrl_regs/I2C_CTRL[1]",
        ),
        _leg(
            "I2C",
            "I2C0_INTR_TEST",
            f"{_I2C0}/INTR_TEST",
            {
                "FMT_THRESHOLD": 1,
                "RX_THRESHOLD": 1,
                "ACQ_THRESHOLD": 1,
                "CONTROLLER_HALT": 1,
                "TX_STRETCH": 1,
                "TX_THRESHOLD": 1,
                "ACQ_STRETCH": 1,
            },
            f"{_I2C0}/INTR_ENABLE",
        ),
        _leg(
            "I2C",
            "I2C0_FIFO_CTRL",
            f"{_I2C0}/FIFO_CTRL",
            {"RXRST": 1, "FMTRST": 1, "ACQRST": 1, "TXRST": 1},
            f"{_I2C0}/CTRL",
            restore=0,
        ),
        _leg(
            "EFUSE-CTRL",
            "EFUSE_PROGRAM_CTRL",
            f"{_EFUSE}/EFUSE_PROGRAM_CTRL",
            {"efuse_addr": 0x5A5A, "efuse_data": 1, "efuse_program_read_back": 1},
            f"{_EFUSE}/EFUSE_READ_CTRL",
            hold=("program_enable",),
        ),
        _leg(
            "EFUSE-CTRL",
            "EFUSE_CTRL_STATUS",
            f"{_EFUSE}/EFUSE_INTERFACE_CTRL_STATUS",
            {
                "efuse_req_error_clear": 1,
                "efuse_program_addr_error_clear": 1,
                "efuse_read_addr_error_clear": 1,
            },
            f"{_EFUSE}/EFUSE_READ_REQ_TIMEOUT",
            restore=0,
        ),
        _leg("UART", "UART0_SCR", f"{_UART}/SCR", {"SCR": 0xA5}, f"{_UART}/MCR"),
        _leg(
            "UART",
            "UART0_LCR",
            f"{_UART}/LCR",
            {"WLS": 3, "STB": 1, "PEN": 1, "EPS": 1},
            f"{_UART}/SCR",
            hold=("DLAB", "SET_BREAK"),
        ),
        Leg(
            "UART-WO",
            "UART0_FCR",
            fcr,
            0,
            0,
            FCR_FIFO_ENABLE | (3 << FCR_RCVR_TRIGGER_SHIFT),
            rdl_register(f"{_UART}/MCR").addr,
            0,
            observe=Observe(
                "UART0_IIR_FIFOS", iir.addr, IIR_FIFOS_ENABLED, 3 << IIR_FIFOS_SHIFT, 0
            ),
        ),
        _leg(
            "UART-CTRL",
            "UART0_EN",
            "smc_uart_wrap/uart_log_engine_wrap[0]/uart_log_engine_ctrl/CTRL",
            {"UART_EN": 1},
            f"{_LOG}/CTRL",
        ),
        _leg(
            "LOG-ENGINE",
            "LOG0_INTR_TEST",
            f"{_LOG}/INTR_TEST",
            {"LOG_FETCH_ERR": 1, "LOG_WRITE_ERR": 1},
            f"{_LOG}/INTR_ENABLE",
            restore=0,
            after=(
                (
                    "LOG0_INTR_STATUS_CLEAR",
                    f"{_LOG}/INTR_STATUS",
                    _word(log_status, LOG_FETCH_ERR=1, LOG_WRITE_ERR=1),
                ),
            ),
        ),
        _leg(
            "TELEMETRY",
            "TEL1_CTRL",
            f"{_TEL1}/CTRL",
            {"TELEMETRY_RX_FLUSH": 1, "TELEMETRY_TX_FLUSH": 1, "BUFFER_THRESHOLD": 0xABC},
            f"{_TEL1}/INTR_ENABLE",
        ),
        _leg(
            "TELEMETRY",
            "TEL1_INTR_TEST",
            f"{_TEL1}/INTR_TEST",
            {"BUFFER_THRESHOLD": 1},
            f"{_TEL1}/INTR_ENABLE",
        ),
        _leg(
            "TIMER",
            "TIMER_START",
            "smc_system_timer_octs/TIMER_START",
            {"START": 1},
            "smc_system_timer_octs/CTRL",
            restore=0,
        ),
    )


BLOCKS = (
    "RESET-UNIT",
    "GPIO",
    "AVSBUS",
    "I2C-CTRL",
    "I2C",
    "EFUSE-CTRL",
    "UART",
    "UART-WO",
    "UART-CTRL",
    "LOG-ENGINE",
    "TELEMETRY",
    "TIMER",
)
TERMS = ("SETUP", *BLOCKS, "RESTORE")
CHECKERS = tuple(sorted(f"CHK-LANE-{b}" for b in BLOCKS)) + ("CHK-LANE-RESTORE", "CHK-NONVAC")


def leg_accesses(leg: Leg) -> int:
    observed = WRITES_PER_LEG if leg.observe is not None else 0
    return LEG_ACCESSES + AFTER_ACCESSES * len(leg.after) + observed


def planned_accesses(legs: tuple[Leg, ...]) -> int:
    return CG_ACCESSES + sum(leg_accesses(leg) for leg in legs) + UART_RO_ACCESSES


def _lane_mask(lane: int, width: int = 1) -> int:
    return ((1 << (8 * width)) - 1) << (8 * lane)


def _strobe_mask(wstrb: int) -> int:
    return sum(_lane_mask(lane) for lane in LANES if (wstrb >> lane) & 1)


class smc_regblock_byte_lane_write_sweep_test_seq(SmcCsrSeq):
    """Lane-off writes to one register of every narrow-cpuif register block."""

    def __init__(self, name: str = "smc_regblock_byte_lane_write_sweep_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self.legs: tuple[Leg, ...] = ()
        self.restores_ok = 0
        self.neighbours_ok = 0
        self._stamps: list[tuple[str, int, int]] = []
        self._results: dict[str, list[str]] = {}

    def _mark(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} did nothing"
        self._stamps.append((term, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    async def _compare(self, leg: Leg, label: str, image: int, saved: int) -> int:
        got = await self.csr_read(f"{leg.label}_{label}_RB", leg.addr)
        if leg.plain_mask:
            assert (got ^ image) & leg.plain_mask == 0, (
                f"{leg.label} at {leg.addr:#x} after {label}: read {got:#x}, expected "
                f"{image:#x} over the plain read-write fields {leg.plain_mask:#x}"
            )
        else:
            obs = leg.observe
            follows = obs.mask if obs is not None and obs.addr == leg.addr else 0
            assert (got ^ saved) & ~follows == 0, (
                f"{leg.label} at {leg.addr:#x} after {label}: read {got:#x}, the register "
                f"read {saved:#x} before the leg and has no plain read-write field"
            )
        if leg.observe is not None:
            obs = leg.observe
            want = obs.after_restore if label == "RESTORE" else obs.while_set
            seen = await self.csr_read(f"{obs.label}_{label}", obs.addr)
            assert seen & obs.mask == want, (
                f"{obs.label} at {obs.addr:#x} after {label}: read {seen:#x}, expected "
                f"{want:#x} over {obs.mask:#x}"
            )
        return got

    async def _run_leg(self, leg: Leg) -> None:
        nb = await self.csr_read(f"{leg.label}_NB_PRE", leg.neighbour)
        saved = await self.csr_read(f"{leg.label}_SAVE", leg.addr)
        image = leg.preload
        await self.csr_write(f"{leg.label}_PRELOAD", leg.addr, image)
        await self._compare(leg, "PRELOAD", image, saved)
        reads: list[str] = []
        for lane in LANES:
            image ^= leg.flip_mask & _lane_mask(lane)
            byte = (image >> (8 * lane)) & 0xFF
            await self.csr_write(f"{leg.label}_L{lane}", leg.addr + lane, byte, length=1)
            got = await self._compare(leg, f"L{lane}", image, saved)
            reads.append(f"L{lane}={got:#x}")
        for off in HALVES:
            image ^= leg.flip_mask & _lane_mask(off, 2)
            half = (image >> (8 * off)) & 0xFFFF
            await self.csr_write(f"{leg.label}_H{off}", leg.addr + off, half, length=2)
            got = await self._compare(leg, f"H{off}", image, saved)
            reads.append(f"H{off}={got:#x}")
        for wstrb in STROBES:
            data = image ^ leg.flip_mask
            image ^= leg.flip_mask & _strobe_mask(wstrb)
            await self.csr_write_strobed(f"{leg.label}_S{wstrb:X}", leg.addr, data, wstrb)
            got = await self._compare(leg, f"S{wstrb:X}", image, saved)
            reads.append(f"S{wstrb:X}={got:#x}")
        restore = saved if leg.restore is None else leg.restore
        await self.csr_write(f"{leg.label}_RESTORE", leg.addr, restore)
        back = await self._compare(leg, "RESTORE", restore, saved)
        for label, addr, value in leg.after:
            pending = await self.csr_read(f"{label}_PRE", addr)
            assert pending & value == value, (
                f"{label} at {addr:#x} reads {pending:#x} before the clear, the writes set "
                f"{value:#x}"
            )
            await self.csr_write(label, addr, value)
            cleared = await self.csr_read(f"{label}_RB", addr)
            assert cleared & value == 0, (
                f"{label} at {addr:#x} still reads {cleared:#x} after the clear write"
            )
        self.restores_ok += 1
        nb_post = await self.csr_read(f"{leg.label}_NB_POST", leg.neighbour)
        assert nb_post == nb, (
            f"{leg.label}: neighbour {leg.neighbour:#x} read {nb:#x} before the leg and "
            f"{nb_post:#x} after it"
        )
        self.neighbours_ok += 1
        self._results.setdefault(leg.block, []).append(
            f"{leg.label} saved={saved:#x} preload={leg.preload:#x} "
            f"plain={leg.plain_mask:#x} flip={leg.flip_mask:#x} [{' '.join(reads)}] "
            f"restore={back:#x}"
        )

    async def _uart_ro_writes(self) -> None:
        regs = tuple(rdl_register(f"{_UART}/{r}") for r in ("LSR", "MSR"))
        pre = [await self.csr_read(f"UART0_{r.base_path}_PRE", r.addr) for r in regs]
        for r in regs:
            await self.csr_write(f"UART0_{r.base_path}_WR", r.addr, 0, length=1)
        for r, before in zip(regs, pre):
            after = await self.csr_read(f"UART0_{r.base_path}_POST", r.addr)
            assert after == before, (
                f"UART0 {r.path} read {before:#x} before and {after:#x} after a byte write"
            )
        self._results.setdefault("UART", []).append(
            "LSR/MSR byte writes answered OKAY and left "
            + ", ".join(f"{r.base_path}={v:#x}" for r, v in zip(regs, pre))
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_BOUND)
        self.legs = build_legs()
        cg_saved = await self.csr_read("CG_SAVE", CLOCK_GATE_CONTROL, length=8)
        cg = cg_saved & ~(UART_CG_EN | TELEMETRY_CG_EN)
        await self.csr_write("CG_UNGATE", CLOCK_GATE_CONTROL, cg, length=8)
        cg_rb = await self.csr_read("CG_UNGATE_RB", CLOCK_GATE_CONTROL, length=8)
        assert cg_rb == cg, f"CLOCK_GATE_CONTROL wrote {cg:#x}, read {cg_rb:#x}"
        self._mark("SETUP", 3)

        for block in BLOCKS:
            legs = [leg for leg in self.legs if leg.block == block]
            for leg in legs:
                await self._run_leg(leg)
            if block == "UART":
                await self._uart_ro_writes()
            self._mark(block, sum(leg_accesses(leg) for leg in legs))
            self._chk(
                f"CHK-LANE-{block}",
                f"{len(legs)} leg(s), every lane, half-word and lane-strobed write read back "
                f"its lane image; " + "; ".join(self._results[block]),
            )

        await self.csr_write("CG_RESTORE", CLOCK_GATE_CONTROL, cg_saved, length=8)
        cg_back = await self.csr_read("CG_RESTORE_RB", CLOCK_GATE_CONTROL, length=8)
        assert cg_back == cg_saved, (
            f"CLOCK_GATE_CONTROL restore wrote {cg_saved:#x}, read {cg_back:#x}"
        )
        self._mark("RESTORE", 2)
        self._chk(
            "CHK-LANE-RESTORE",
            f"{self.restores_ok}/{len(self.legs)} targets restored and read back, "
            f"{self.neighbours_ok}/{len(self.legs)} neighbours unchanged, "
            f"CLOCK_GATE_CONTROL back at {cg_saved:#x}",
        )
        assert tuple(t for t, _c, _s in self._stamps) == TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert sorted(self.chk_seen) == sorted(CHECKERS[:-1]), f"checker set {self.chk_seen}"
        self._chk(
            "CHK-NONVAC",
            " < ".join(TERMS)
            + "; terms "
            + ", ".join(f"{t}(n={c})@{s}ns" for t, c, s in self._stamps)
            + f"; SEP_IN accesses {self.accesses}",
        )
