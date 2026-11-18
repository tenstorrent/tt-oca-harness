# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded I2C0 timing-set pairs: a larger TIMING field gives a longer measured pad interval.

Specs: hw/ip/i2c/regs/i2c.rdl (TIMING0 to TIMING4: each field in system clock cycles, `THIGH`
and `TLOW` each at least 2), hw/ip/i2c/doc/index.adoc (single clock `clk_i`, gated from
`clk_periph_i`).

The seed draws one base timing set and, for each of the seven parameters `THIGH`, `TLOW`,
`THD_DAT`, `TSU_STA`, `THD_STA`, `TSU_STO` and `T_BUF`, a second set that differs from the base
in that parameter only, by a drawn sign and size (1 to 24 cycles), with a drawn transfer shape
(a write, or a write then two repeated-START reads). `TSU_STA` and `THD_STA` take the
repeated-START shape. Every run queues transfer X of its shape and three transfers Y (START,
address write, STOP) behind it, so each of the three bus-free times, from a STOP to the START
queued behind it, is the controller's own. A measurer samples `tb_i2c0_scl` and `tb_i2c0_sda` on
every `clk_periph_i` rise, the clock `clk_i` is gated from, so a field change of one cycle is one
sample. Every timed interval occurs at least twice per run: two repeated-START setups, five START
holds (two repeated, three after a STOP), four STOP setups and three bus-free times. The base set
runs once per shape; each of the six graded pairs compares the drawn parameter's interval of its
second set with that of the base run of the same shape at every common sample. The `T_BUF` pair
runs and is printed, not compared: its bus-free times before and after the change beside both
programmed values, the programmed direction and the measured direction at each sample. Absolute
intervals and the measured differences are printed, not compared. A pair out of order fails the
test after the `THIGH` 2 run, so that leg still reports. A set with `THIGH` 2 and the other fields
of the base set runs one START, address-write and STOP transfer on every seed.

With `grade_tbuf_bus_free` (the `smc_i2c_tbuf_bus_free_test` reproducer) the same draw runs and,
once the six pairs are in order, the `T_BUF` pair is graded under `CHK-ITS-TBUF-BUS-FREE`: every
bus-free time of each run is at least that run's programmed `T_BUF` and the second run's moved the
way `T_BUF` moved at every common sample (i2c.rdl TIMING4.T_BUF: "specifies the time between a
STOP and START condition (t_BUF) in system clock cycles"); a fault raises
`CHK-ITS-TBUF-BUS-FREE FAIL`.
"""

from __future__ import annotations

import random

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
TIMING_REGS = (I2C0_TIMING0, I2C0_TIMING1, I2C0_TIMING2, I2C0_TIMING3, I2C0_TIMING4)

EEPROM_ADDR = 0x50
POINTER_BYTE = 0xA5
READ_BYTE = 0x3C
ALL_ONES = 0xFFFF_FFFF

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
#: (register, field) of each parameter in i2c.rdl, for the width read from the generated map.
FIELD_REG = {
    "thigh": ("TIMING0", "THIGH"),
    "tlow": ("TIMING0", "TLOW"),
    "t_r": ("TIMING1", "T_R"),
    "t_f": ("TIMING1", "T_F"),
    "tsu_sta": ("TIMING2", "TSU_STA"),
    "thd_sta": ("TIMING2", "THD_STA"),
    "tsu_dat": ("TIMING3", "TSU_DAT"),
    "thd_dat": ("TIMING3", "THD_DAT"),
    "tsu_sto": ("TIMING4", "TSU_STO"),
    "t_buf": ("TIMING4", "T_BUF"),
}
PARAMS = ("thigh", "tlow", "thd_dat", "tsu_sta", "thd_sta", "tsu_sto", "t_buf")
RSTART_PARAMS = ("tsu_sta", "thd_sta")
#: Pairs measured and printed, not graded.
PRINTED_PARAMS = ("t_buf",)
GRADED_PARAMS = tuple(p for p in PARAMS if p not in PRINTED_PARAMS)
GRADED_PAIR_NOTE = "absolutes and differences printed, not compared; order graded by CHK-ITS-ORDER"

#: Base-set ranges. Every drawn change of up to CHANGE_MAX in either direction keeps each field
#: at or above 1, and `THIGH` and `TLOW` at or above 2 (i2c.rdl TIMING0); `THD_DAT` plus
#: `TSU_DAT`, `T_R` and `T_F` stays below `TLOW` in every set, so the SDA change of a bit falls
#: inside the SCL low phase.
BASE_RANGE = {
    "thigh": (30, 60),
    "tlow": (110, 150),
    "t_r": (1, 8),
    "t_f": (1, 8),
    "tsu_sta": (30, 60),
    "thd_sta": (30, 60),
    "tsu_dat": (1, 8),
    "thd_dat": (25, 32),
    "tsu_sto": (30, 60),
    "t_buf": (30, 60),
}
CHANGE_MIN, CHANGE_MAX = 1, 24
RDL_MIN_THIGH = 2
REDRAW_BOUND = 64

#: Transfers Y (START, address write, STOP) queued behind transfer X in every measured run, so
#: the run has Y_COUNT bus-free times and Y_COUNT + 1 STOP setups.
Y_COUNT = 3
#: SCL rises of one transfer Y: address 1-8 and its acknowledge 9, the STOP's setup rise 10.
Y_RISES = 10


def _shape(x_rises: int, rstarts: tuple[int, ...], x_tx_falls: tuple[int, ...]) -> dict:
    """Rise indices of a run of transfer X and Y_COUNT transfers Y, counted from the first START.

    A STOP's setup rise and a repeated START's setup rise are not clock pulses; fall n is the SCL
    fall after rise n (fall 0 the hold fall of the first START, the fall after a STOP's setup
    rise the hold fall of the next START)."""
    stop_rises = tuple(x_rises + Y_RISES * j for j in range(Y_COUNT + 1))
    special = set(rstarts) | set(stop_rises)
    last = stop_rises[-1]
    y_tx = tuple(b + n for b in stop_rises[:-1] for n in range(1, 8))
    return {
        "rstarts": rstarts,
        "stop_rises": stop_rises,
        "clock_pulses": tuple(n for n in range(1, last) if n not in special),
        "low_phases": tuple(n for n in range(1, last) if n not in special and n + 1 not in special),
        "tx_falls": x_tx_falls + y_tx,
        "starts": 1 + len(rstarts) + Y_COUNT,
        "stops": 1 + Y_COUNT,
        "target": (1 + len(rstarts) + Y_COUNT, 1 + Y_COUNT, 1 + len(rstarts) + Y_COUNT),
    }


#: Transfer X per shape, counted in SCL rises from its START. Write: address 1-8 and its
#: acknowledge 9, the data byte 10-17 and 18, the STOP's setup rise 19. Repeated START: the
#: write as above to 18; a repeated START (setup rise 19), the read address 20-27 and 28, the read
#: byte 29-36 and the controller's not-acknowledge 37; a second repeated START (setup rise 38),
#: the read address 39-46 and 47, the read byte 48-55 and the not-acknowledge 56; the STOP's setup
#: rise 57. The target counts every START and the acknowledge of every address.
SHAPES = {
    "write": _shape(19, (), tuple(range(1, 8)) + tuple(range(10, 17))),
    "rstart": _shape(
        57,
        (19, 38),
        tuple(range(1, 8)) + tuple(range(10, 17)) + tuple(range(20, 27)) + tuple(range(39, 46)),
    ),
}
READS = {"write": 0, "rstart": 2}

FUSE_SENSE_BOUND = 200_000
EDGE_POLL_CYCLES = 64
BOUND_PER_SPAN = 120
BOUND_FLOOR_CYCLES = 4096
HOSTIDLE_POLLS = 100
HOSTIDLE_POLL_CYCLES = 100

#: Step 4 grades the record step 3 closed and takes no simulation time: its checker line is
#: printed after the S3 stamp and S4 is not stamped.
STEPS = ("S1", "S2", "S3", "S5", "S6")
CHK_STEPS = (
    ("CHK-ITS-ORDER", "S3"),
    ("CHK-ITS-MIN-THIGH", "S5"),
    ("CHK-ITS-COMPLETE", "S6"),
)
#: The `T_BUF` grade of the reproducer; its line follows `CHK-ITS-ORDER` after the S3 stamp.
TBUF_CHK = "CHK-ITS-TBUF-BUS-FREE"


def field_width(param: str) -> int:
    reg, field = FIELD_REG[param]
    mask = _i2c_u32(f"I2C__{reg}__{field}_bm")
    pos = _i2c_u32(f"I2C__{reg}__{field}_bp")
    return (mask >> pos).bit_length()


def draw_plan(rng: random.Random, widths: dict[str, int] | None = None) -> tuple[dict, dict, int]:
    """Base set and one (sign, size, shape) per parameter; redrawn until both signs and both
    shapes occur among the graded pairs. Returns (base, pairs, attempts)."""
    for attempt in range(1, REDRAW_BOUND + 1):
        base = {f: rng.randint(*BASE_RANGE[f]) for f in FIELDS}
        pairs = {}
        for p in PARAMS:
            sign = rng.choice((1, -1))
            size = rng.randint(CHANGE_MIN, CHANGE_MAX)
            shape = "rstart" if p in RSTART_PARAMS else rng.choice(("write", "rstart"))
            pairs[p] = {"sign": sign, "size": size, "shape": shape}
        signs = {pairs[p]["sign"] for p in GRADED_PARAMS}
        free_shapes = {pairs[p]["shape"] for p in GRADED_PARAMS if p not in RSTART_PARAMS}
        if signs == {1, -1} and "write" in free_shapes:
            break
    else:
        raise AssertionError(
            f"no draw with both signs and a write shape among the graded pairs in {REDRAW_BOUND}"
        )
    for p, v in pairs.items():
        second = dict(base)
        second[p] = base[p] + v["sign"] * v["size"]
        v["set"] = second
        check_set(f"pair {p}", second, widths)
        assert [f for f in FIELDS if second[f] != base[f]] == [p], f"pair {p} differs elsewhere"
    check_set("base", base, widths)
    return base, pairs, attempt


def grade_tbuf_bus_free(
    m0: dict[int, int], m1: dict[int, int], expected0: int, expected1: int
) -> list[str]:
    """Faults of the `T_BUF` pair: a bus-free time of the base run (`m0`) or the second run
    (`m1`) below that run's expected time, fewer than two common samples, or a common sample
    where the second run's time did not move the way the expected time moved."""
    faults = []
    for label, m, expected in (("base", m0, expected0), ("second", m1, expected1)):
        short = [(k, x) for k, x in sorted(m.items()) if x < expected]
        if short:
            faults.append(
                f"{label} run bus-free time below its T_BUF {expected} at {len(short)} of "
                f"{len(m)} samples {short}"
            )
    keys = sorted(set(m0) & set(m1))
    if len(keys) < 2:
        faults.append(f"{len(keys)} bus-free sample(s) common to the two runs, want 2")
    if expected1 != expected0:
        way = "longer" if expected1 > expected0 else "shorter"
        wrong = [
            (k, m0[k], m1[k])
            for k in keys
            if not (m1[k] > m0[k] if expected1 > expected0 else m1[k] < m0[k])
        ]
        if wrong:
            faults.append(
                f"T_BUF {expected0} -> {expected1} but the bus-free time was not {way} at "
                f"{len(wrong)} of {len(keys)} samples {wrong}"
            )
    return faults


def check_set(label: str, prog: dict[str, int], widths: dict[str, int] | None) -> None:
    for f in FIELDS:
        assert prog[f] >= 1, f"{label}: {f}={prog[f]} is zero or negative"
        if widths is not None:
            assert prog[f] < (1 << widths[f]), f"{label}: {f}={prog[f]} exceeds its width"
    assert prog["thigh"] >= RDL_MIN_THIGH and prog["tlow"] >= RDL_MIN_THIGH, (
        f"{label}: THIGH {prog['thigh']} or TLOW {prog['tlow']} below 2"
    )
    assert prog["thd_dat"] + prog["tsu_dat"] + prog["t_r"] + prog["t_f"] < prog["tlow"], (
        f"{label}: THD_DAT+TSU_DAT+T_R+T_F not below TLOW ({prog})"
    )


def _timing_words(prog: dict[str, int]) -> tuple[int, int, int, int, int]:
    return (
        _pack_timing0(prog["thigh"], prog["tlow"]),
        _pack_timing1(prog["t_r"], prog["t_f"]),
        _pack_timing2(prog["tsu_sta"], prog["thd_sta"]),
        _pack_timing3(prog["tsu_dat"], prog["thd_dat"]),
        _pack_timing4(prog["tsu_sto"], prog["t_buf"]),
    )


class _PadRecorder:
    """Samples both I2C0 pad nets on every `clk_periph_i` rise and keeps the edges."""

    def __init__(self) -> None:
        dut = cocotb.top
        self._clk = dut.clk_periph_i
        self._scl = dut.tb_i2c0_scl
        self._sda = dut.tb_i2c0_sda
        self.events: list[tuple[int, str, int]] = []
        self.cycle = 0
        self.starts = 0
        self.stops = 0
        self.running = True

    @staticmethod
    def _level(handle) -> int:
        raw = handle.value
        assert raw.is_resolvable, f"{handle._name} is not resolvable: {raw}"
        return int(raw)

    def state(self) -> str:
        return (
            f"cycle={self.cycle} edges={len(self.events)} starts={self.starts} "
            f"stops={self.stops} scl={self._level(self._scl)} sda={self._level(self._sda)}"
        )

    async def run(self) -> None:
        scl = self._level(self._scl)
        sda = self._level(self._sda)
        assert scl == 1 and sda == 1, f"bus not idle when the measurer started: {self.state()}"
        while self.running:
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


def parse_edges(label: str, events: list[tuple[int, str, int]], shape: str) -> dict:
    """Reduce the pad edges of transfer X and the transfers Y of one run to the intervals, in
    cycles, keyed by sample (pulse, phase, rise or STOP index)."""
    sh = SHAPES[shape]
    stop_rises = sh["stop_rises"]
    rs = sh["rstarts"]
    n_rise = stop_rises[-1]
    scl = 1
    starts: list[int] = []
    stops: list[int] = []
    rises: list[int] = []
    falls: list[int] = []
    sda_edges: list[int] = []
    for t, line, lvl in events:
        if line == "scl":
            (rises if lvl else falls).append(t)
            scl = lvl
        else:
            sda_edges.append(t)
            if scl:
                (stops if lvl else starts).append(t)
    assert len(starts) == sh["starts"] and len(stops) == sh["stops"], (
        f"{label}: {len(starts)} START and {len(stops)} STOP edges on the pads, expected "
        f"{sh['starts']} and {sh['stops']}"
    )
    assert len(rises) == n_rise and len(falls) == n_rise, (
        f"{label}: {len(rises)} SCL rises and {len(falls)} falls, expected {n_rise} of each"
    )
    rise = {n: rises[n - 1] for n in range(1, n_rise + 1)}
    fall = {n: falls[n] for n in range(0, n_rise)}
    rs_starts = starts[1 : 1 + len(rs)]
    y_starts = starts[1 + len(rs) :]
    assert starts[0] < fall[0] < rise[1], f"{label}: first START hold edges out of order"
    for j, sr in enumerate(stop_rises):
        assert rise[sr] < stops[j], f"{label}: STOP {j} before its setup rise"
        if j < Y_COUNT:
            assert stops[j] < y_starts[j] < fall[sr] < rise[sr + 1], (
                f"{label}: START of transfer Y{j} out of order after STOP {j}"
            )
    assert all(fall[n] > rise[n] for n in range(1, n_rise)), f"{label}: a fall precedes its rise"
    for r, t in zip(rs, rs_starts):
        assert rise[r] < t < fall[r], f"{label}: repeated START not inside pulse {r}"
    out: dict = {"events": len(events), "scl_edges": len(rises) + len(falls)}
    out["high"] = {n: fall[n] - rise[n] for n in sh["clock_pulses"]}
    out["low"] = {n: rise[n + 1] - fall[n] for n in sh["low_phases"]}
    hold: dict[int, int] = {}
    for n in sh["tx_falls"]:
        inside = [t for t in sda_edges if fall[n] < t < rise[n + 1]]
        assert len(inside) <= 1, f"{label}: {len(inside)} SDA edges in the low phase after fall {n}"
        if inside:
            hold[n] = inside[0] - fall[n]
    out["hold"] = hold
    out["stop_setup"] = {j: stops[j] - rise[sr] for j, sr in enumerate(stop_rises)}
    out["bus_free"] = {j: y_starts[j] - stops[j] for j in range(Y_COUNT)}
    out["rs_setup"] = {r: t - rise[r] for r, t in zip(rs, rs_starts)}
    start_hold = {r: fall[r] - t for r, t in zip(rs, rs_starts)}
    start_hold.update({sr: fall[sr] - t for sr, t in zip(stop_rises, y_starts)})
    out["start_hold"] = start_hold
    out["first_start_hold"] = fall[0] - starts[0]
    return out


def metric(meas: dict, param: str) -> dict[int, int]:
    """The measured interval(s) the parameter sets, keyed by pulse or phase index."""
    if param == "thigh":
        return meas["high"]
    if param == "tlow":
        return meas["low"]
    if param == "thd_dat":
        return meas["hold"]
    key = {
        "tsu_sta": "rs_setup",
        "thd_sta": "start_hold",
        "tsu_sto": "stop_setup",
        "t_buf": "bus_free",
    }[param]
    return meas[key]


def _samples(m: dict[int, int]) -> list[int]:
    """Every sample of a short interval list in order; the distinct values of a long one."""
    return list(m.values()) if len(m) <= 8 else sorted(set(m.values()))


class smc_i2c_timing_set_rand_test_seq(SmcCsrSeq):
    """Drawn base set and seven one-parameter pairs on I2C0; strict order of six intervals."""

    def __init__(
        self,
        name: str = "smc_i2c_timing_set_rand_test_seq",
        *,
        seed: int,
        grade_tbuf_bus_free: bool = False,
    ) -> None:
        super().__init__(name)
        self.grade_tbuf_bus_free = grade_tbuf_bus_free
        self.chk_steps = list(CHK_STEPS)
        if grade_tbuf_bus_free:
            self.chk_steps.insert(1, (TBUF_CHK, "S3"))
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.base: dict[str, int] = {}
        self.pairs: dict[str, dict] = {}
        self.attempts = 0
        self.slave: SmcI2cEepromSlave | None = None
        self.base_meas: dict[str, dict] = {}
        self.pair_meas: dict[str, dict] = {}
        self.runs: list[str] = []
        self.run_edges: list[tuple[str, int, int]] = []
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.bounds: dict[str, int] = {}
        self.last_state = "no wait entered"
        self.min_text = ""
        self.order_fail: list[str] = []
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _drawn(self) -> str:
        pairs = ", ".join(
            f"{p} {'+' if v['sign'] > 0 else '-'}{v['size']} {v['shape']}"
            for p, v in self.pairs.items()
        )
        base = " ".join(f"{f}={self.base[f]}" for f in FIELDS)
        return f"drawn=base [{base}]; pairs [{pairs}]"

    async def _status(self, label: str) -> str:
        status = await self.csr_read(f"{label}_STATUS", I2C0_STATUS)
        fifo = await self.csr_read(f"{label}_HOST_FIFO_STATUS", I2C0_HOST_FIFO_STATUS)
        return f"STATUS=0x{status:08x} HOST_FIFO_STATUS=0x{fifo:08x}"

    async def _program(self, label: str, prog: dict[str, int]) -> None:
        words = _timing_words(prog)
        for i, (addr, word) in enumerate(zip(TIMING_REGS, words)):
            await self.csr_write(f"{label}_TIMING{i}", addr, word)
        for i, (addr, word) in enumerate(zip(TIMING_REGS, words)):
            await self.csr_read(f"{label}_TIMING{i}_RB", addr, expected=word)

    async def _queue(self, label: str, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", I2C0_FDATA, word)
            await ClockCycles(cocotb.top.clk_smc_i, 2)

    @staticmethod
    def _words(shape: str | None) -> list[int]:
        y = [_fdata(EEPROM_ADDR << 1, I2C_FDATA_START | I2C_FDATA_STOP)]
        if shape is None:
            return y
        x = [_fdata(EEPROM_ADDR << 1, I2C_FDATA_START), _fdata(POINTER_BYTE)]
        for _ in range(READS[shape]):
            x += [
                _fdata((EEPROM_ADDR << 1) | 1, I2C_FDATA_START),
                _fdata(1, I2C_FDATA_READB),
            ]
        x[-1] |= I2C_FDATA_STOP
        return x + y * Y_COUNT

    async def _wait_stops(self, label: str, rec: _PadRecorder, stops: int, prog: dict) -> None:
        bound = BOUND_PER_SPAN * sum(prog.values()) + BOUND_FLOOR_CYCLES
        self.bounds["edge_wait"] = max(self.bounds.get("edge_wait", 0), bound)
        clk = cocotb.top.clk_periph_i
        for _ in range(bound // EDGE_POLL_CYCLES):
            if rec.stops >= stops:
                return
            await ClockCycles(clk, EDGE_POLL_CYCLES)
        self.last_state = f"{await self._status(label)} measurer: {rec.state()}"
        raise AssertionError(
            f"{label}: {rec.stops} of {stops} STOP edges within {bound} clk_periph_i cycles; "
            f"{self.last_state}; {self._drawn()}"
        )

    async def _wait_hostidle(self, label: str, rec: _PadRecorder) -> None:
        for _ in range(HOSTIDLE_POLLS):
            status = await self.csr_read(f"{label}_IDLE", I2C0_STATUS)
            if status & I2C_STATUS_HOSTIDLE:
                return
            await ClockCycles(cocotb.top.clk_periph_i, HOSTIDLE_POLL_CYCLES)
        self.last_state = f"{await self._status(label)} measurer: {rec.state()}"
        raise AssertionError(f"{label}: HOSTIDLE never set; {self.last_state}; {self._drawn()}")

    async def _run(
        self, label: str, prog: dict[str, int], shape: str | None
    ) -> tuple[_PadRecorder, tuple[int, int, int]]:
        """Program `prog`, run transfer X of `shape` (if any) and Y, return the edges and the
        target's START, STOP and acknowledge counts of the run."""
        assert self.slave is not None
        await self._program(label, prog)
        await self.csr_write(f"{label}_INTR_CLR", I2C0_INTR_STATE, ALL_ONES)
        base = (self.slave.starts, self.slave.stops, self.slave.acks)
        rec = _PadRecorder()
        cocotb.start_soon(rec.run())
        await RisingEdge(cocotb.top.clk_periph_i)
        stops = 1 if shape is None else SHAPES[shape]["stops"]
        await self._queue(label, self._words(shape))
        await self._wait_stops(label, rec, stops, prog)
        await self._wait_hostidle(label, rec)
        rec.running = False
        await RisingEdge(cocotb.top.clk_periph_i)
        seen = (
            self.slave.starts - base[0],
            self.slave.stops - base[1],
            self.slave.acks - base[2],
        )
        scl_edges = sum(1 for e in rec.events if e[1] == "scl")
        self.run_edges.append((label, scl_edges, rec.stops))
        return rec, seen

    async def _measured_run(self, label: str, prog: dict[str, int], shape: str) -> dict:
        rec, seen = await self._run(label, prog, shape)
        want = SHAPES[shape]["target"]
        assert seen == want, (
            f"{label}: target counted starts/stops/acks {seen}, queued {want}; {self._drawn()}"
        )
        rbytes = []
        for i in range(READS[shape]):
            rbytes.append(await self.csr_read(f"{label}_RDATA{i}", I2C0_RDATA) & 0xFF)
        rdata = ",".join(f"0x{b:02x}" for b in rbytes) or "none"
        meas = parse_edges(label, rec.events, shape)
        self.runs.append(f"{label}({shape}) target {seen[0]}/{seen[1]}/{seen[2]} rdata {rdata}")
        cocotb.log.info(
            "MEAS %s %s (clk_periph_i cycles, measured): high=%s low=%s hold=%s "
            "stop_setup=%s bus_free=%s (T_BUF %d) rs_setup=%s start_hold=%s "
            "first_start_hold=%d; RDATA %s (target preload 0x%02x at the pointer, printed)",
            label,
            shape,
            sorted(set(meas["high"].values())),
            sorted(set(meas["low"].values())),
            sorted(set(meas["hold"].values())),
            list(meas["stop_setup"].values()),
            list(meas["bus_free"].values()),
            prog["t_buf"],
            list(meas["rs_setup"].values()),
            list(meas["start_hold"].values()),
            meas["first_start_hold"],
            rdata,
            READ_BYTE,
        )
        return meas

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        for name in ("tb_i2c0_scl", "tb_i2c0_sda", "clk_periph_i"):
            assert hasattr(dut, name), f"tb_top has no {name}"
        widths = {f: field_width(f) for f in FIELDS}
        self.base, self.pairs, self.attempts = draw_plan(self.rng, widths)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: base set %s; per parameter sign, size (%d to %d) and "
            "shape: %s; draw attempt %d of %d (both signs and a write shape required)",
            self.seed,
            " ".join(f"{f}={self.base[f]}" for f in FIELDS),
            CHANGE_MIN,
            CHANGE_MAX,
            ", ".join(
                f"{p} {'+' if v['sign'] > 0 else '-'}{v['size']} {v['shape']}"
                for p, v in self.pairs.items()
            ),
            self.attempts,
            REDRAW_BOUND,
        )
        await self.prove_dut_i2c0_pins()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", I2C0_WRAP_CTRL, I2C_WRAP_ENABLE_CONTROLLER)
        await self.wait_i2c0_lsio_ready("I2C0_TIMING_SET")
        assert int(dut.tb_i2c0_scl.value) == 1 and int(dut.tb_i2c0_sda.value) == 1, (
            "I2C0 pads not idle high after the pad arming"
        )
        await self.csr_write("OVRD_OFF", I2C0_OVRD, I2C_OVRD_OFF)
        await self.csr_write("CTRL_OFF", I2C0_CTRL, 0)
        self.slave = SmcI2cEepromSlave(addr=EEPROM_ADDR, name="smc_i2c0_timing_set_eeprom")
        self.slave.write_mem(POINTER_BYTE, bytes((READ_BYTE,)))
        await self.csr_write("FIFO_RST", I2C0_FIFO_CTRL, I2C_FIFO_CTRL_RXRST_FMTRST)
        await self.csr_write("EVENTS_CLR", I2C0_CONTROLLER_EVENTS, I2C_CONTROLLER_EVENTS_ALL)
        await self.csr_write("INTR_CLR", I2C0_INTR_STATE, ALL_ONES)
        await self.csr_write("ENABLEHOST", I2C0_CTRL, I2C_CTRL_ENABLEHOST)
        await ClockCycles(dut.clk_smc_i, 20)
        self._mark("S1")

    async def _s2(self) -> None:
        for shape in ("write", "rstart"):
            self.base_meas[shape] = await self._measured_run(f"BASE_{shape}", self.base, shape)
        self._mark("S2")

    async def _s3(self) -> None:
        for p, v in self.pairs.items():
            meas = await self._measured_run(f"PAIR_{p}", v["set"], v["shape"])
            self.pair_meas[p] = meas
            m0 = metric(self.base_meas[v["shape"]], p)
            m1 = metric(meas, p)
            diffs = sorted({m1[k] - m0[k] for k in set(m0) & set(m1)})
            printed = p in PRINTED_PARAMS
            extra = self._tbuf_observation(m0, m1, v) if printed else ""
            cocotb.log.info(
                "PAIR %s %s: %s %d -> %d (programmed difference %+d); measured base %s second "
                "%s, differences %s; %s%s",
                p,
                v["shape"],
                p,
                self.base[p],
                v["set"][p],
                v["sign"] * v["size"],
                _samples(m0),
                _samples(m1),
                diffs,
                ("compared" if self.grade_tbuf_bus_free else "printed, not compared")
                if printed
                else GRADED_PAIR_NOTE,
                extra,
            )
        self._mark("S3")
        parts = []
        for p in GRADED_PARAMS:
            v = self.pairs[p]
            m0 = metric(self.base_meas[v["shape"]], p)
            m1 = metric(self.pair_meas[p], p)
            keys = sorted(set(m0) & set(m1))
            assert len(keys) >= 2, f"{p}: {len(keys)} interval(s) common to the two runs, want 2"
            if v["sign"] > 0:
                bad = [k for k in keys if not m1[k] > m0[k]]
            else:
                bad = [k for k in keys if not m1[k] < m0[k]]
            if bad:
                msg = (
                    f"CHK-ITS-ORDER {p}: {p} {self.base[p]} -> {v['set'][p]} but the measured "
                    f"interval did not move that way at {len(bad)} of {len(keys)} samples "
                    f"({[(k, m0[k], m1[k]) for k in bad[:6]]}); {self._drawn()}"
                )
                self.order_fail.append(msg)
                cocotb.log.error("ORDER-PAIR %s out of order: %s", p, msg)
                continue
            larger = "second" if v["sign"] > 0 else "base"
            parts.append(
                f"{p} {self.base[p]}->{v['set'][p]} ({v['shape']}): {len(keys)} samples, the "
                f"{larger} set (larger field) longer at every one"
            )
            cocotb.log.info("ORDER-PAIR %s in order: %s", p, parts[-1])
        signs = sorted({self.pairs[p]["sign"] for p in GRADED_PARAMS})
        assert signs == [-1, 1], f"graded pairs hold one sign only {signs}"
        if self.order_fail:
            return
        self._chk(
            "S3",
            "CHK-ITS-ORDER",
            f"for each of the {len(GRADED_PARAMS)} graded pairs the interval measured with the "
            f"larger field value is longer: "
            + "; ".join(parts)
            + f"; both signs graded; the {', '.join(PRINTED_PARAMS)} pair "
            + (f"graded by {TBUF_CHK}; " if self.grade_tbuf_bus_free else "printed, not graded; ")
            + self._drawn(),
        )
        if self.grade_tbuf_bus_free:
            self._grade_tbuf()

    def _grade_tbuf(self) -> None:
        """The reproducer's compare: the `T_BUF` pair's bus-free times against both programmed
        values and the programmed direction."""
        v = self.pairs["t_buf"]
        m0 = metric(self.base_meas[v["shape"]], "t_buf")
        m1 = metric(self.pair_meas["t_buf"], "t_buf")
        t0, t1 = self.base["t_buf"], v["set"]["t_buf"]
        faults = grade_tbuf_bus_free(m0, m1, t0, t1)
        seen = (
            f"T_BUF {t0} -> {t1} ({v['shape']}), bus-free time {list(m0.values())} -> "
            f"{list(m1.values())} clk_periph_i cycles (THD_DAT {self.base['thd_dat']}, T_R "
            f"{self.base['t_r']}, TSU_STA {self.base['tsu_sta']})"
        )
        assert not faults, f"{TBUF_CHK} FAIL: {seen}: " + "; ".join(faults) + f"; {self._drawn()}"
        self._chk(
            "S3",
            TBUF_CHK,
            f"{seen}: every bus-free time at least its programmed T_BUF and the second run's "
            f"{'longer' if t1 > t0 else 'shorter'} at every common sample (i2c.rdl "
            f"TIMING4.T_BUF: the time between a STOP and START condition); {self._drawn()}",
        )

    def _tbuf_observation(self, m0: dict[int, int], m1: dict[int, int], v: dict) -> str:
        """The bus-free times of the `T_BUF` pair beside both programmed values and directions."""
        t0, t1 = self.base["t_buf"], v["set"]["t_buf"]
        keys = sorted(set(m0) & set(m1))
        moved = {"longer": 0, "shorter": 0, "equal": 0}
        for k in keys:
            d = m1[k] - m0[k]
            moved["longer" if d > 0 else "shorter" if d < 0 else "equal"] += 1
        below = sum(1 for x in m0.values() if x < t0) + sum(1 for x in m1.values() if x < t1)
        return (
            f"; T_BUF-OBS programmed T_BUF {t0} -> {t1} "
            f"({'longer' if t1 > t0 else 'shorter'} by {abs(t1 - t0)}), bus-free time "
            f"{list(m0.values())} -> {list(m1.values())} (THD_DAT {self.base['thd_dat']}): "
            f"longer at {moved['longer']}, shorter at {moved['shorter']}, equal at "
            f"{moved['equal']} of {len(keys)} samples, below the programmed T_BUF at {below} of "
            f"{len(m0) + len(m1)} (i2c.rdl TIMING4.T_BUF: the time between a STOP and START "
            f"condition; "
            + (
                f"compared by {TBUF_CHK})"
                if self.grade_tbuf_bus_free
                else "printed, not compared under CHK-ITS-ORDER)"
            )
        )

    async def _s5(self) -> None:
        prog = dict(self.base)
        prog["thigh"] = RDL_MIN_THIGH
        check_set("min THIGH", prog, None)
        rec, seen = await self._run("MIN_THIGH", prog, None)
        status = await self.csr_read("MIN_THIGH_STATUS", I2C0_STATUS)
        self._mark("S5")
        assert rec.starts == 1 and rec.stops == 1, (
            f"MIN_THIGH: {rec.starts} START and {rec.stops} STOP on the pads; {rec.state()}"
        )
        assert seen == (1, 1, 1), (
            f"MIN_THIGH: target counted starts/stops/acks {seen}, expected 1/1/1; {self._drawn()}"
        )
        assert status & I2C_STATUS_HOSTIDLE, f"MIN_THIGH: HOSTIDLE clear (STATUS=0x{status:08x})"
        self.runs.append(f"MIN_THIGH(address write) target {seen[0]}/{seen[1]}/{seen[2]}")
        self._chk(
            "S5",
            "CHK-ITS-MIN-THIGH",
            f"THIGH {RDL_MIN_THIGH} (i2c.rdl TIMING0 lowest legal value) with every other field "
            f"of the base set: START, address write and STOP completed, target counted "
            f"{seen[0]} START, {seen[2]} acknowledge and {seen[1]} STOP, the pads showed "
            f"{rec.starts} START and {rec.stops} STOP, STATUS 0x{status:08x} HOSTIDLE set; "
            f"{self._drawn()}",
        )

    async def _s6(self) -> None:
        await self._program("RESTORE", self.base)
        self._mark("S6")
        expected_runs = 2 + len(PARAMS) + 1
        assert len(self.runs) == expected_runs, f"{len(self.runs)} runs, expected {expected_runs}"
        self._chk(
            "S6",
            "CHK-ITS-COMPLETE",
            f"all {len(self.runs)} transfer runs completed within their bounds with the "
            f"target's START, STOP and acknowledge counts as queued: "
            + "; ".join(self.runs)
            + f"; TIMING0 to TIMING4 restored to the base set; {self._drawn()}",
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: bounded waits: fuse_sense_done<=%d clk_smc_i; "
            "i2c0_lsio_ready=2000 polls 4 clk_smc_i apart (smc_csr_seq_utils.py); "
            "i2c0_pad_settle<=%d clk_smc_i polled every %d, then stable %d, at each of the 5 "
            "pin checks (smc_csr_seq_utils.py); edge_wait<=%d clk_periph_i "
            "(largest; %d x sum of the programmed counts + %d, polled every %d) per run; "
            "hostidle_poll=%d polls %d clk_periph_i apart per run; axi_access<=%d ns per access "
            "(%d accesses, the driver guard); expiry raises AssertionError with STATUS, "
            "HOST_FIFO_STATUS and the measurer state; last diagnostic=%s",
            FUSE_SENSE_BOUND,
            self._I2C0_PAD_SETTLE_TIMEOUT_CYCLES,
            self._I2C0_PAD_POLL_CYCLES,
            self._I2C0_PAD_STABLE_CYCLES,
            self.bounds["edge_wait"],
            BOUND_PER_SPAN,
            BOUND_FLOOR_CYCLES,
            EDGE_POLL_CYCLES,
            HOSTIDLE_POLLS,
            HOSTIDLE_POLL_CYCLES,
            self.cfg.axi_timeout_ns,
            self.accesses,
            self.last_state,
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == self.chk_steps, f"checker lines {self.chk_lines}"
        measured = [r for r in self.run_edges if not r[0].startswith("MIN")]
        assert len(measured) == 2 + len(PARAMS), f"measured runs {measured}"
        empty = [r for r in measured if r[1] < 1 or r[2] < 1]
        assert not empty, f"runs with no SCL edge or no STOP kept: {empty}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; SCL edges and STOPs "
            "kept per run %s; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            ", ".join(f"{label} {edges}/{stops}" for label, edges, stops in self.run_edges),
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s5()
        assert not self.order_fail, (
            f"{len(self.order_fail)} of {len(GRADED_PARAMS)} graded pairs out of order (graded "
            f"at S3; the THIGH 2 run of S5 ran after it): " + " | ".join(self.order_fail)
        )
        await self._s6()
        self.done = True
