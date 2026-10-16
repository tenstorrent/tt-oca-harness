# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller wire timing on the instance-0 SCL/SDA pads as a function of TIMING0-TIMING4.

Spec sources: hw/ip/i2c/regs/i2c.rdl (TIMING0-TIMING4 field descriptions, which cite Table 11 of
the I2C-bus specification UM10204), hw/ip/i2c/doc/index.adoc (single clock `clk_i`).

The controller runs two transfers back to back under each programming set. Transfer X is a
write of one byte, a repeated START, a read of one byte that the controller not-acknowledges,
and a STOP. Transfer Y, queued behind X so that the gap between them is the controller's own, is
a START, an address write and a STOP. A clock-sampled measurer on `tb_i2c0_scl` and
`tb_i2c0_sda` timestamps every pad edge in `clk_periph_i` cycles, the clock `clk_i` is gated
from. The sources state no pad-path latency. Only differences between programming sets are
compared; absolute values are printed as measured.

* Set A: the Fast-mode-plus minimums of UM10204 Table 11 converted to whole cycles upward.
* Set B: set A with THIGH, TLOW, TSU_DAT and THD_DAT scaled by 4.
* Set C: set A with the same four fields scaled by `SCALE_C`.
* Set A2: set A with T_R and T_F raised. Set A3: set A with TSU_STA, THD_STA and TSU_STO
  raised. Set A4: set A with only T_BUF raised.

Standard-mode full-rate SCL is not run. The minimum set (THIGH = TLOW = 2, every other field 1)
is a liveness run of transfer Y.
"""

from __future__ import annotations

import time

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_master_target_test_seq import (
    CLOCK_GATE_CONTROL,
    I2C0_CONTROLLER_EVENTS,
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
    I2C_CONTROLLER_EVENTS_ALL,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_READB,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_OVRD_OFF,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_ENABLE_CONTROLLER,
    _fdata,
    _i2c_field,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cEepromSlave

I2C0_INTR_STATE = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_INTR_STATE_BASE_ADDR", 0)
I2C0_HOST_FIFO_STATUS = smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_HOST_FIFO_STATUS_BASE_ADDR", 0)
INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")

EEPROM_ADDR = 0x50
POINTER_BYTE = 0xA5
READ_BYTE = 0x61
ALL_ONES = 0xFFFF_FFFF

#: Fast-mode-plus minimums of UM10204 Table 11, in ns, and the smallest nonzero THD_DAT.
FM_PLUS_NS = {
    "thigh": 260,
    "tlow": 500,
    "t_r": 120,
    "t_f": 120,
    "tsu_sta": 260,
    "thd_sta": 260,
    "tsu_dat": 50,
    "tsu_sto": 260,
    "t_buf": 500,
}
THD_DAT_MIN = 1
FAST_RATIO = 4
SCALE_C = 10
RISE_FALL_RAISE = 6
START_STOP_RAISE = 8
SCALED_FIELDS = ("thigh", "tlow", "tsu_dat", "thd_dat")
FIELDS = (
    "thigh",
    "tlow",
    "t_r",
    "t_f",
    "tsu_sta",
    "thd_sta",
    "tsu_dat",
    "thd_dat",
    "tsu_sto",
    "t_buf",
)

#: Rises of SCL in transfer X counted from its START: address byte 1-8 and its acknowledge 9,
#: the data byte 10-17 and 18, the repeated START's setup rise 19, the read address 20-27 and
#: 28, the read byte 29-36, the controller's not-acknowledge 37 and the STOP's setup rise 38.
X_RISES = 38
Y_RISES = 10
NACK_PULSE = 37
RSTART_RISE = 19
STOP_RISE = 38
CLOCK_PULSES = tuple(n for n in range(1, NACK_PULSE + 1) if n != RSTART_RISE)
LOW_PHASES = tuple(range(1, 18)) + tuple(range(20, 37))
TX_FALLS = tuple(range(1, 8)) + tuple(range(10, 17)) + tuple(range(20, 27))

#: TIMING registers: address, low field, high field, and a distinct value for each at its width.
TIMING_LAYOUT = (
    ("TIMING0", I2C0_TIMING0, "THIGH", 0x1A55, "TLOW", 0x1F33),
    ("TIMING1", I2C0_TIMING1, "T_R", 0x2A5, "T_F", 0x15A),
    ("TIMING2", I2C0_TIMING2, "TSU_STA", 0x1B6D, "THD_STA", 0x1C9A),
    ("TIMING3", I2C0_TIMING3, "TSU_DAT", 0x1A7, "THD_DAT", 0x1235),
    ("TIMING4", I2C0_TIMING4, "TSU_STO", 0x1AE1, "T_BUF", 0x1D2B),
)
FIELD_REWRITE_XOR = 0x0155
LOW_HALF_LANES = 0b0011
HIGH_HALF_LANES = 0b1100

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_BY_STEP = {
    "CHK-I2C-WIRE-TIMING-FIELDS": "S1",
    "CHK-I2C-WIRE-SCL-HIGH-DELTA": "S4",
    "CHK-I2C-WIRE-SCL-LOW-DELTA": "S4",
    "CHK-I2C-WIRE-SCL-PERIOD-DELTA": "S4",
    "CHK-I2C-WIRE-MEASURED-ONLY": "S6",
    "CHK-I2C-WIRE-DATA-SETUP-MEASURED": "S4",
    "CHK-I2C-WIRE-DATA-HOLD-DELTA": "S4",
    "CHK-I2C-WIRE-NACK-HOLD-DELTA": "S4",
    "CHK-I2C-WIRE-RSTART-DELTA": "S6",
    "CHK-I2C-WIRE-STOP-SETUP-DELTA": "S6",
    "CHK-I2C-WIRE-BUS-FREE-DELTA": "S6",
    "CHK-I2C-WIRE-MIN-SET-RUN": "S7",
}
FENCE_TERMS = {
    "S1": "TIMING_FIELDS_PROGRAMMED",
    "S2": "SET_A_MEASURED",
    "S3": "SET_B_MEASURED",
    "S4": "SET_C_MEASURED",
    "S5": "SET_A2_MEASURED",
    "S6": "SET_A3_A4_MEASURED",
    "S7": "MIN_SET_RUN",
}

EDGE_POLL_CYCLES = 64
BOUND_PER_SPAN = 120
BOUND_FLOOR_CYCLES = 4096
HOSTIDLE_POLLS = 100
HOSTIDLE_POLL_CYCLES = 100


def _cycles_up(ns: int, period_ps: int) -> int:
    """Whole clock cycles that cover `ns`, never fewer."""
    return -(-ns * 1000 // period_ps)


def _span(prog: dict[str, int]) -> int:
    return sum(prog.values())


def _timing_words(prog: dict[str, int]) -> tuple[int, int, int, int, int]:
    return (
        _pack_timing0(prog["thigh"], prog["tlow"]),
        _pack_timing1(prog["t_r"], prog["t_f"]),
        _pack_timing2(prog["tsu_sta"], prog["thd_sta"]),
        _pack_timing3(prog["tsu_dat"], prog["thd_dat"]),
        _pack_timing4(prog["tsu_sto"], prog["t_buf"]),
    )


class WireRecorder:
    """Samples both pad lines on every `clk_periph_i` rising edge and keeps the edges."""

    def __init__(self) -> None:
        dut = cocotb.top
        self._clk = dut.clk_periph_i
        self._scl = dut.tb_i2c0_scl
        self._sda = dut.tb_i2c0_sda
        self.events: list[tuple[int, str, int]] = []
        self.cycle = 0
        self.starts = 0
        self.stops = 0
        self._task = None

    @staticmethod
    def _level(handle) -> int:
        raw = handle.value
        assert raw.is_resolvable, f"{handle._name} is not resolvable: {raw}"
        return int(raw)

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        assert self._task is not None
        self._task.cancel()
        self._task = None

    def state(self) -> str:
        return (
            f"cycle={self.cycle} edges={len(self.events)} starts={self.starts} "
            f"stops={self.stops} scl={self._level(self._scl)} sda={self._level(self._sda)}"
        )

    async def _run(self) -> None:
        scl = self._level(self._scl)
        sda = self._level(self._sda)
        while True:
            await RisingEdge(self._clk)
            self.cycle += 1
            new_scl = self._level(self._scl)
            new_sda = self._level(self._sda)
            if new_scl != scl:
                self.events.append((self.cycle, "scl", new_scl))
            if new_sda != sda:
                self.events.append((self.cycle, "sda", new_sda))
                if new_scl and scl:
                    if new_sda:
                        self.stops += 1
                    else:
                        self.starts += 1
            scl, sda = new_scl, new_sda


def _sda_level_before(events: list[tuple[int, str, int]], cycle: int) -> int:
    level = 1
    for t, line, lvl in events:
        if t >= cycle:
            break
        if line == "sda":
            level = lvl
    return level


def parse_edges(label: str, events: list[tuple[int, str, int]], with_x: bool) -> dict:
    """Reduce the edge list of one set to the named intervals, in cycles."""
    scl = 1
    starts: list[int] = []
    stops: list[int] = []
    rises: list[int] = []
    falls: list[int] = []
    sda_edges: list[tuple[int, int]] = []
    for t, line, lvl in events:
        if line == "scl":
            (rises if lvl else falls).append(t)
            scl = lvl
        else:
            sda_edges.append((t, lvl))
            if scl:
                (stops if lvl else starts).append(t)
    n_start, n_stop, n_rise = (3, 2, X_RISES + Y_RISES) if with_x else (1, 1, Y_RISES)
    assert len(starts) == n_start and len(stops) == n_stop, (
        f"{label}: {len(starts)} START and {len(stops)} STOP edges on the pads, expected "
        f"{n_start} and {n_stop}"
    )
    assert len(rises) == n_rise and len(falls) == n_rise, (
        f"{label}: {len(rises)} SCL rises and {len(falls)} falls, expected {n_rise} of each"
    )
    out: dict = {"events": len(events)}
    y_start, y_stop = starts[-1], stops[-1]
    y_rise = rises[-Y_RISES:]
    y_fall = falls[-Y_RISES:]
    assert y_start < y_fall[0] < y_rise[0] and y_rise[-1] < y_stop, (
        f"{label}: transfer Y edges out of order {y_start} {y_fall[0]} {y_rise[0]} {y_stop}"
    )
    out["y_start_hold"] = y_fall[0] - y_start
    out["y_stop_setup"] = y_stop - y_rise[-1]
    if not with_x:
        return out
    rise = {n: rises[n - 1] for n in range(1, X_RISES + 1)}
    fall = {n: falls[n] for n in range(0, NACK_PULSE + 1)}
    assert starts[0] < fall[0] < rise[1], f"{label}: first START hold edges out of order"
    assert rise[RSTART_RISE] < starts[1] < fall[RSTART_RISE], (
        f"{label}: repeated START not between SCL rise {RSTART_RISE} and the next fall"
    )
    assert rise[STOP_RISE] < stops[0] < starts[2], f"{label}: STOP edges out of order"
    assert all(fall[n] > rise[n] for n in range(1, NACK_PULSE + 1)), (
        f"{label}: an SCL fall precedes its rise"
    )
    out["first_hold"] = fall[0] - starts[0]
    out["high"] = {n: fall[n] - rise[n] for n in CLOCK_PULSES}
    out["low"] = {n: rise[n + 1] - fall[n] for n in LOW_PHASES}
    out["period"] = {n: rise[n + 1] - rise[n] for n in LOW_PHASES}
    out["other_low"] = {n: rise[n + 1] - fall[n] for n in (0, 18, 19, 37)}
    hold: dict[int, int] = {}
    setup: dict[int, int] = {}
    for n in TX_FALLS:
        inside = [t for t, _ in sda_edges if fall[n] < t < rise[n + 1]]
        assert len(inside) <= 1, f"{label}: {len(inside)} SDA edges in the low phase after fall {n}"
        if inside:
            hold[n] = inside[0] - fall[n]
            setup[n + 1] = rise[n + 1] - inside[0]
    out["hold"] = hold
    out["setup"] = setup
    nack_level = _sda_level_before(events, fall[NACK_PULSE])
    assert nack_level == 1, f"{label}: SDA was {nack_level} in the not-acknowledge pulse, not high"
    after_nack = [t for t, _ in sda_edges if fall[NACK_PULSE] < t < rise[STOP_RISE]]
    assert len(after_nack) == 1, (
        f"{label}: {len(after_nack)} SDA edges between the not-acknowledge fall and the STOP rise"
    )
    out["nack_hold"] = after_nack[0] - fall[NACK_PULSE]
    out["rs_setup"] = starts[1] - rise[RSTART_RISE]
    out["rs_hold"] = fall[RSTART_RISE] - starts[1]
    out["stop_setup"] = stops[0] - rise[STOP_RISE]
    out["bus_free"] = starts[2] - stops[0]
    return out


class smc_i2c_wire_timing_test_seq(SmcCsrSeq):
    """Programs the five TIMING registers and measures the pad edges of two transfers per set."""

    def __init__(self, name: str = "smc_i2c_wire_timing_test_seq") -> None:
        super().__init__(name)
        self.wire_ok = False
        self.slave: SmcI2cEepromSlave | None = None
        self._events: list[tuple[str, str, int]] = []
        self._bounds: dict[str, int] = {}
        self._last_state = "no wait entered"
        self._reset_words: list[int] = []
        self._field_lines: list[str] = []
        self.sets: dict[str, dict[str, int]] = {}
        self.meas: dict[str, dict] = {}

    def _step_done(self, step: str) -> None:
        self._events.append(("step", step, int(get_sim_time("ps"))))

    def _chk(self, cid: str, text: str) -> None:
        cocotb.log.info("%s: %s", cid, text)
        self._events.append(("chk", cid, int(get_sim_time("ps"))))

    def _assert_fence(self) -> None:
        steps = [e for e in self._events if e[0] == "step"]
        assert [e[1] for e in steps] == list(STEPS), f"step order {[e[1] for e in steps]}"
        stamps = {e[1]: e[2] for e in steps}
        values = list(stamps.values())
        assert all(b > a for a, b in zip(values, values[1:])), f"stamps not increasing {values}"
        chks = [e for e in self._events if e[0] == "chk"]
        assert [c[1] for c in chks] == list(CHK_BY_STEP), f"checker order {[c[1] for c in chks]}"
        last_step = max(i for i, e in enumerate(self._events) if e[0] == "step")
        for idx, (kind, cid, t) in enumerate(self._events):
            if kind == "chk":
                assert t >= stamps[CHK_BY_STEP[cid]], f"{cid} printed before {CHK_BY_STEP[cid]}"
                assert idx > last_step, f"{cid} printed before the last step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in STEPS),
            ", ".join(c[1] for c in chks),
            ",".join(str(stamps[s]) for s in STEPS),
        )

    def _set_a(self) -> dict[str, int]:
        period_ps = int(float(self.cfg.periph_clk_period_ns) * 1000 + 0.5)
        prog = {k: _cycles_up(ns, period_ps) for k, ns in FM_PLUS_NS.items()}
        prog["thd_dat"] = THD_DAT_MIN
        return prog

    def _build_sets(self) -> None:
        a = self._set_a()

        def scaled(factor: int) -> dict[str, int]:
            return {k: v * factor if k in SCALED_FIELDS else v for k, v in a.items()}

        self.sets = {
            "A": a,
            "B": scaled(FAST_RATIO),
            "C": scaled(SCALE_C),
            "A2": {k: v + RISE_FALL_RAISE if k in ("t_r", "t_f") else v for k, v in a.items()},
            "A3": {
                k: v + START_STOP_RAISE if k in ("tsu_sta", "thd_sta", "tsu_sto") else v
                for k, v in a.items()
            },
            "A4": {k: v + START_STOP_RAISE if k == "t_buf" else v for k, v in a.items()},
            "MIN": {**dict.fromkeys(FIELDS, 1), "thigh": 2, "tlow": 2},
        }
        for name, prog in self.sets.items():
            cocotb.log.info(
                "SET %s (clk_i cycles): %s",
                name,
                " ".join(f"{k}={prog[k]}" for k in FIELDS),
            )
        cocotb.log.info(
            "SET C scale factor %d (A scaled by %d, A scaled by %d); "
            "standard-mode-100kHz-full-rate: NOT RUN",
            SCALE_C,
            FAST_RATIO,
            SCALE_C,
        )

    async def _status(self, label: str) -> str:
        status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
        fifo = await self.csr_read(f"{label}_HOST_FIFO_STATUS", I2C0_HOST_FIFO_STATUS)
        return f"STATUS=0x{status:08x} HOST_FIFO_STATUS=0x{fifo:08x}"

    async def _wait_stops(self, label: str, rec: WireRecorder, stops: int, prog: dict) -> None:
        bound = BOUND_PER_SPAN * _span(prog) + BOUND_FLOOR_CYCLES
        self._bounds["edge_wait"] = max(self._bounds.get("edge_wait", 0), bound)
        clk = cocotb.top.clk_periph_i
        for _ in range(bound // EDGE_POLL_CYCLES):
            if rec.stops >= stops:
                return
            await ClockCycles(clk, EDGE_POLL_CYCLES)
        self._last_state = f"{await self._status(label)} monitor: {rec.state()}"
        raise AssertionError(
            f"{label}: {rec.stops} of {stops} STOP edges within {bound} clk_periph_i cycles; "
            f"{self._last_state}"
        )

    async def _wait_hostidle(self, label: str, rec: WireRecorder) -> None:
        clk = cocotb.top.clk_periph_i
        for _ in range(HOSTIDLE_POLLS):
            status = await self.csr_read(f"{label}_IDLE", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(clk, HOSTIDLE_POLL_CYCLES)
        self._last_state = f"{await self._status(label)} monitor: {rec.state()}"
        raise AssertionError(f"{label}: HOSTIDLE never set; {self._last_state}")

    async def _program(self, label: str, prog: dict[str, int]) -> None:
        regs = (I2C0_TIMING0, I2C0_TIMING1, I2C0_TIMING2, I2C0_TIMING3, I2C0_TIMING4)
        for i, (addr, word) in enumerate(zip(regs, _timing_words(prog))):
            await self.csr_write(f"{label}_TIMING{i}", addr, word)
            await ClockCycles(cocotb.top.clk_smc_i, 2)
        for i, (addr, word) in enumerate(zip(regs, _timing_words(prog))):
            await self.csr_read(f"{label}_TIMING{i}_RB", addr, expected=word)

    async def _queue(self, label: str, with_x: bool) -> None:
        clk = cocotb.top.clk_smc_i
        words = []
        if with_x:
            words += [
                _fdata(EEPROM_ADDR << 1, I2C_FDATA_START),
                _fdata(POINTER_BYTE),
                _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START),
                _fdata(1, I2C_FDATA_READB | I2C_FDATA_STOP),
            ]
        words.append(_fdata(EEPROM_ADDR << 1, I2C_FDATA_START | I2C_FDATA_STOP))
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", I2C0_FDATA, word)
            await ClockCycles(clk, 2)

    async def _bring_up(self) -> None:
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_WIRE_TIMING")
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_wire_timing_eeprom")
        self.slave.write_mem(POINTER_BYTE, bytes((READ_BYTE,)))
        await self.csr_write("OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("INTR_CLR", I2C0_INTR_STATE, ALL_ONES)
        await self.csr_write("ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _field_check(self) -> None:
        for name, addr, _, _, _, _ in TIMING_LAYOUT:
            self._reset_words.append(await self.csr_read(f"{name}_RESET", addr))
        for name, addr, lo, lo_val, hi, hi_val in TIMING_LAYOUT:
            lo_word = _i2c_field(name, lo, lo_val)
            hi_word = _i2c_field(name, hi, hi_val)
            await self.csr_write(f"{name}_FIELDS", addr, lo_word | hi_word)
            await self.csr_read(f"{name}_FIELDS_RB", addr, expected=lo_word | hi_word)
            lo_new = _i2c_field(name, lo, lo_val ^ FIELD_REWRITE_XOR)
            hi_new = _i2c_field(name, hi, hi_val ^ FIELD_REWRITE_XOR)
            await self.csr_write_strobed(
                f"{name}_LOW_REWRITE", addr, lo_new | hi_new, wstrb=LOW_HALF_LANES
            )
            await self.csr_read(f"{name}_LOW_REWRITE_RB", addr, expected=lo_new | hi_word)
            await self.csr_write_strobed(
                f"{name}_HIGH_REWRITE", addr, lo_word | hi_new, wstrb=HIGH_HALF_LANES
            )
            await self.csr_read(f"{name}_HIGH_REWRITE_RB", addr, expected=lo_new | hi_new)
            self._field_lines.append(
                f"{lo}=0x{lo_val:x}->0x{lo_val ^ FIELD_REWRITE_XOR:x} "
                f"{hi}=0x{hi_val:x}->0x{hi_val ^ FIELD_REWRITE_XOR:x}"
            )

    async def _run_set(self, tag: str) -> None:
        prog = self.sets[tag]
        assert self.slave is not None
        started = time.monotonic()
        await self._program(tag, prog)
        await self.csr_write(f"{tag}_INTR_CLR", I2C0_INTR_STATE, ALL_ONES)
        base = (self.slave.starts, self.slave.stops, self.slave.acks)
        rec = WireRecorder()
        rec.start()
        await self._queue(tag, True)
        await self._wait_stops(tag, rec, 2, prog)
        await self._wait_hostidle(tag, rec)
        rec.stop()
        got = await self.csr_read(f"{tag}_RDATA", I2C0_RDATA)
        assert got & 0xFF == READ_BYTE, (
            f"{tag}: read byte 0x{got & 0xFF:02x}, not 0x{READ_BYTE:02x}"
        )
        seen = (
            self.slave.starts - base[0],
            self.slave.stops - base[1],
            self.slave.acks - base[2],
        )
        assert seen == (3, 2, 3), f"{tag}: target counted starts/stops/acks {seen}, expected 3/2/3"
        self.meas[tag] = parse_edges(tag, rec.events, True)
        m = self.meas[tag]
        cocotb.log.info(
            "MEAS %s (clk_i cycles, measured): first_hold=%d high=%s low=%s period=%s setup=%s "
            "hold=%s nack_hold=%d rs_setup=%d rs_hold=%d stop_setup=%d bus_free=%d "
            "other_low=%s wall_s=%.1f",
            tag,
            m["first_hold"],
            sorted(set(m["high"].values())),
            sorted(set(m["low"].values())),
            sorted(set(m["period"].values())),
            sorted(set(m["setup"].values())),
            sorted(set(m["hold"].values())),
            m["nack_hold"],
            m["rs_setup"],
            m["rs_hold"],
            m["stop_setup"],
            m["bus_free"],
            m["other_low"],
            time.monotonic() - started,
        )

    async def _min_run(self) -> str:
        prog = self.sets["MIN"]
        assert self.slave is not None
        await self._program("MIN", prog)
        await self.csr_write("MIN_INTR_CLR", I2C0_INTR_STATE, ALL_ONES)
        before = await self.csr_read("MIN_INTR_BEFORE", I2C0_INTR_STATE)
        assert before & INTR_CMD_COMPLETE == 0, f"CMD_COMPLETE set before the run (0x{before:08x})"
        base = (self.slave.starts, self.slave.stops, self.slave.acks)
        rec = WireRecorder()
        rec.start()
        await self._queue("MIN", False)
        await self._wait_stops("MIN", rec, 1, prog)
        await self._wait_hostidle("MIN", rec)
        rec.stop()
        intr = await self.csr_read("MIN_INTR_AFTER", I2C0_INTR_STATE)
        status = await self.csr_read("MIN_STATUS_AFTER", I2C0_STATUS)
        seen = (
            self.slave.starts - base[0],
            self.slave.stops - base[1],
            self.slave.acks - base[2],
        )
        assert rec.starts == 1 and rec.stops == 1, (
            f"MIN: {rec.starts} START and {rec.stops} STOP on the pads; {rec.state()}"
        )
        assert seen == (1, 1, 1), f"MIN: target counted starts/stops/acks {seen}, expected 1/1/1"
        assert intr & INTR_CMD_COMPLETE, f"MIN: CMD_COMPLETE not set (INTR_STATE=0x{intr:08x})"
        assert status & I2C_STATUS_HOSTIDLE, f"MIN: HOSTIDLE not set (STATUS=0x{status:08x})"
        parse_edges("MIN", rec.events, False)
        return (
            f"THIGH=2 TLOW=2 and every other field 1: START, address write acknowledged "
            f"(target acks={seen[2]}), exactly {rec.stops} STOP on the pads, STATUS=0x{status:08x} "
            f"HOSTIDLE set, INTR_STATE=0x{intr:08x} CMD_COMPLETE set again after being "
            f"0x{before:08x}"
        )

    def _delta(self, metric: str, tag: str, key: int | None = None) -> int:
        def pick(t: str) -> int:
            m = self.meas[t][metric]
            return m if key is None else m[key]

        return pick(tag) - pick("A")

    def _compare(
        self, name: str, metric: str, expected: dict[str, int], pairs: tuple[str, ...], keyed=True
    ) -> str:
        """Require measured delta == programmed delta of each set in `pairs` against set A."""
        for tag in pairs:
            assert expected[tag] != 0, f"{name}: programmed delta of {tag} minus A is 0"
        bad = []
        count = 0
        if keyed:
            keys = sorted(set.intersection(*(set(self.meas[t][metric]) for t in ("A",) + pairs)))
            assert keys, f"{name}: no {metric} samples common to all sets"
        else:
            keys = [None]
        for key in keys:
            for tag in pairs:
                got = self._delta(metric, tag, key)
                count += 1
                if got != expected[tag]:
                    bad.append(f"{metric}[{key}] {tag}-A measured {got} programmed {expected[tag]}")
        assert not bad, f"{name}: {len(bad)} of {count} deltas differ: {'; '.join(bad[:12])}"
        return f"{len(keys)} sample(s) per set, {count} deltas equal"

    def _absolutes(self, metric: str, tags: tuple[str, ...], floors: dict[str, int]) -> str:
        parts = []
        for tag in tags:
            m = self.meas[tag][metric]
            vals = list(m.values()) if isinstance(m, dict) else [m]
            below = sum(1 for v in vals if v < floors[tag])
            parts.append(f"{tag}: min={min(vals)} max={max(vals)} below_programmed={below}")
        return "; ".join(parts)

    def _bus_free_below(self) -> str:
        below = [
            f"{t} measured {self.meas[t]['bus_free']} programmed {self.sets[t]['t_buf']}"
            for t in ("A", "B", "C", "A2", "A3", "A4")
            if self.meas[t]["bus_free"] < self.sets[t]["t_buf"]
        ]
        return "; ".join(below) or "none"

    async def body(self) -> None:
        self._build_sets()
        await self._bring_up()
        await self._field_check()
        self._step_done("S1")

        await self._run_set("A")
        self._step_done("S2")
        await self._run_set("B")
        self._step_done("S3")
        await self._run_set("C")
        self._step_done("S4")
        await self._run_set("A2")
        self._step_done("S5")
        await self._run_set("A3")
        await self._run_set("A4")
        self._step_done("S6")
        min_text = await self._min_run()
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._step_done("S7")

        s = self.sets
        d = {t: {f: s[t][f] - s["A"][f] for f in FIELDS} for t in ("B", "C", "A3", "A4")}
        bc = ("B", "C")

        self._chk(
            "CHK-I2C-WIRE-TIMING-FIELDS",
            "reset-value leg on a two-state bench, nothing compared: TIMING0-4 read "
            + ",".join(f"0x{w:08x}" for w in self._reset_words)
            + " before any write; each field read back the distinct value written at its width "
            "and a halfword-strobed rewrite of each low field then each high field left its "
            "neighbour unchanged: " + "; ".join(self._field_lines),
        )

        thigh_note = self._compare(
            "CHK-I2C-WIRE-SCL-HIGH-DELTA",
            "high",
            {t: d[t]["thigh"] for t in bc},
            bc,
        )
        floors = {t: s[t]["thigh"] for t in ("A",) + bc}
        self._chk(
            "CHK-I2C-WIRE-SCL-HIGH-DELTA",
            f"delta(SCL high) B-A={d['B']['thigh']} C-A={d['C']['thigh']} equal delta(THIGH) on "
            f"{thigh_note}; absolute highs measured: "
            + self._absolutes("high", ("A", "B", "C"), floors),
        )

        tlow_note = self._compare(
            "CHK-I2C-WIRE-SCL-LOW-DELTA", "low", {t: d[t]["tlow"] for t in bc}, bc
        )
        floors = {t: s[t]["tlow"] for t in ("A",) + bc}
        self._chk(
            "CHK-I2C-WIRE-SCL-LOW-DELTA",
            f"delta(SCL low) B-A={d['B']['tlow']} C-A={d['C']['tlow']} equal delta(TLOW) on "
            f"{tlow_note}; absolute lows measured: "
            + self._absolutes("low", ("A", "B", "C"), floors),
        )

        same_rf = all(s[t]["t_r"] == s["A"]["t_r"] and s[t]["t_f"] == s["A"]["t_f"] for t in bc)
        assert same_rf, "T_R or T_F differs between sets A, B and C"
        period_note = self._compare(
            "CHK-I2C-WIRE-SCL-PERIOD-DELTA",
            "period",
            {t: d[t]["thigh"] + d[t]["tlow"] for t in bc},
            bc,
        )
        floors = {t: s[t]["thigh"] + s[t]["tlow"] for t in ("A",) + bc}
        self._chk(
            "CHK-I2C-WIRE-SCL-PERIOD-DELTA",
            f"delta(SCL period) B-A={d['B']['thigh'] + d['B']['tlow']} "
            f"C-A={d['C']['thigh'] + d['C']['tlow']} equal delta(THIGH+TLOW) on {period_note} "
            f"with T_R={s['A']['t_r']} T_F={s['A']['t_f']} in A, B and C; absolute periods "
            "measured: " + self._absolutes("period", ("A", "B", "C"), floors) + "; "
            "standard-mode-100kHz-full-rate: NOT RUN",
        )

        a, a2, a3 = self.meas["A"], self.meas["A2"], self.meas["A3"]
        period_a2 = sorted({a2["period"][n] - a["period"][n] for n in LOW_PHASES})
        self._chk(
            "CHK-I2C-WIRE-MEASURED-ONLY",
            f"measured only, nothing compared: SCL period change with T_R and T_F raised by "
            f"{RISE_FALL_RAISE} (A2 minus A) = {period_a2} cycles per pulse; first-START hold "
            f"(SDA fall to next SCL fall) A={a['first_hold']} A3={a3['first_hold']} with "
            f"THD_STA {s['A']['thd_sta']}->{s['A3']['thd_sta']}, TSU_STA "
            f"{s['A']['tsu_sta']}->{s['A3']['tsu_sta']}, T_BUF {s['A']['t_buf']}->"
            f"{s['A3']['t_buf']}; STOP SDA rise to the next controller action (START of Y) "
            f"A={a['bus_free']} A3={a3['bus_free']}",
        )

        setup_parts = []
        for tag in ("A", "B", "C"):
            seen = self.meas[tag]["setup"]
            assert seen, f"{tag}: no transmitted-bit SDA setup sample"
            setup_parts.append(
                f"{tag}: measured setup min={min(seen.values())} max={max(seen.values())} over "
                f"{len(seen)} bits, programmed TSU_DAT={s[tag]['tsu_dat']} "
                f"TLOW-THD_DAT={s[tag]['tlow'] - s[tag]['thd_dat']}"
            )
        self._chk(
            "CHK-I2C-WIRE-DATA-SETUP-MEASURED",
            "measured only, nothing compared: SDA setup before the SCL rising edge of a "
            "transmitted data bit in cycles, " + "; ".join(setup_parts),
        )

        hold_note = self._compare(
            "CHK-I2C-WIRE-DATA-HOLD-DELTA",
            "hold",
            {t: d[t]["thd_dat"] for t in bc},
            bc,
        )
        self._chk(
            "CHK-I2C-WIRE-DATA-HOLD-DELTA",
            f"delta(SDA hold after SCL fall) B-A={d['B']['thd_dat']} C-A={d['C']['thd_dat']} "
            f"equal delta(THD_DAT) on {hold_note}; absolute holds measured: "
            + self._absolutes("hold", ("A", "B", "C"), {t: s[t]["thd_dat"] for t in ("A",) + bc}),
        )

        self._compare(
            "CHK-I2C-WIRE-NACK-HOLD-DELTA",
            "nack_hold",
            {t: d[t]["thd_dat"] for t in bc},
            bc,
            keyed=False,
        )
        self._chk(
            "CHK-I2C-WIRE-NACK-HOLD-DELTA",
            f"SDA high during SCL pulse {NACK_PULSE}, the controller not-acknowledge; delta(SDA "
            f"hold after its SCL fall) B-A={self._delta('nack_hold', 'B')} "
            f"C-A={self._delta('nack_hold', 'C')} equal delta(THD_DAT) "
            f"B-A={d['B']['thd_dat']} C-A={d['C']['thd_dat']}; absolute holds measured "
            f"A={self.meas['A']['nack_hold']} B={self.meas['B']['nack_hold']} "
            f"C={self.meas['C']['nack_hold']}",
        )

        exp_rs_setup = {"A3": d["A3"]["tsu_sta"]}
        exp_rs_hold = {"A3": d["A3"]["thd_sta"]}
        self._compare("CHK-I2C-WIRE-RSTART-DELTA", "rs_setup", exp_rs_setup, ("A3",), keyed=False)
        self._compare("CHK-I2C-WIRE-RSTART-DELTA", "rs_hold", exp_rs_hold, ("A3",), keyed=False)
        self._chk(
            "CHK-I2C-WIRE-RSTART-DELTA",
            f"delta(repeated-START setup, SCL rise to SDA fall) "
            f"A3-A={self._delta('rs_setup', 'A3')} equals delta(TSU_STA)={d['A3']['tsu_sta']}; "
            f"delta(repeated-START hold, SDA fall to the next SCL fall) "
            f"A3-A={self._delta('rs_hold', 'A3')} equals "
            f"delta(THD_STA)={d['A3']['thd_sta']}; absolutes measured setup A={a['rs_setup']} "
            f"A3={a3['rs_setup']} hold A={a['rs_hold']} A3={a3['rs_hold']}",
        )

        self._compare(
            "CHK-I2C-WIRE-STOP-SETUP-DELTA",
            "stop_setup",
            {"A3": d["A3"]["tsu_sto"]},
            ("A3",),
            keyed=False,
        )
        self._chk(
            "CHK-I2C-WIRE-STOP-SETUP-DELTA",
            f"delta(STOP setup, SCL rise to SDA rise) A3-A={self._delta('stop_setup', 'A3')} "
            f"equals delta(TSU_STO)={d['A3']['tsu_sto']}; absolute setup measured "
            f"A={a['stop_setup']} A3={a3['stop_setup']}",
        )

        self._compare(
            "CHK-I2C-WIRE-BUS-FREE-DELTA",
            "bus_free",
            {"A4": d["A4"]["t_buf"]},
            ("A4",),
            keyed=False,
        )
        self._chk(
            "CHK-I2C-WIRE-BUS-FREE-DELTA",
            f"delta(bus free, STOP SDA rise of X to START SDA fall of Y) A4-A="
            f"{self._delta('bus_free', 'A4')} equals delta(T_BUF)={d['A4']['t_buf']}; absolute "
            f"bus free measured A={a['bus_free']} A4={self.meas['A4']['bus_free']} against "
            f"programmed T_BUF A={s['A']['t_buf']} A4={s['A4']['t_buf']}; "
            f"defect candidate (below programmed T_BUF, not compared): {self._bus_free_below()}",
        )

        self._chk("CHK-I2C-WIRE-MIN-SET-RUN", min_text)

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 4 bounded waits: edge_wait=%d clk_periph_i cycles (largest, "
            "%d x sum of the programmed counts + %d, polled every %d) "
            "fail-on-expiry=AssertionError last=STATUS, HOST_FIFO_STATUS and monitor state; "
            "hostidle_poll=%d polls %d cycles apart fail-on-expiry=AssertionError "
            "last=STATUS, HOST_FIFO_STATUS and monitor state; "
            "i2c0_lsio_ready=2000 polls enforced-by=smc_csr_seq_utils.py "
            "fail-on-expiry=AssertionError last=bus and pad-sense levels; "
            "axi_access=%d ns enforced-by=the AXI driver fail-on-expiry=AssertionError "
            "last=access address; last diagnostic=%s",
            self._bounds["edge_wait"],
            BOUND_PER_SPAN,
            BOUND_FLOOR_CYCLES,
            EDGE_POLL_CYCLES,
            HOSTIDLE_POLLS,
            HOSTIDLE_POLL_CYCLES,
            self.cfg.axi_timeout_ns,
            self._last_state,
        )
        self.wire_ok = True
