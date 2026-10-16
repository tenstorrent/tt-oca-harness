# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Two I2C controllers transferring at the same time on separate pad pairs.

Spec sources: hw/ip/i2c/regs/i2c.rdl (TIMING0-TIMING4, FDATA, STATUS, HOST_FIFO_STATUS,
INTR_STATE.CMD_COMPLETE, CONTROLLER_EVENTS.NACK), hw/ip/i2c/regs/i2c_ctrl.rdl (I2C_CTRL.I2C_EN
routes an instance to its pads), hw/ip/i2c/regs/i2c_wrap.rdl (instance i at offset i * 0x200),
hw/ip/i2c/doc/index.adoc (single clock `clk_i`).

Instance 0 runs on `tb_i2c0_scl` / `tb_i2c0_sda` and instance 1 on `tb_i2c1_scl` / `tb_i2c1_sda`,
each with its own EEPROM target and bus monitor. The bench resolves the instance-1 pair onto
pads 41 and 42 only under `+smc_i2c1_pads`, which the testlist entry passes; `tb_i2c1_*` read the
padring outputs, so they follow `I2C_CTRL[1].I2C_EN` alone, before any GPIO LSIO select. A
clock-sampled recorder timestamps every pad edge of both pairs in `clk_periph_i` cycles, the
clock `clk_i` is gated from. The sources state no fixed pad-path latency and no completion time:
absolute durations and the overlap are printed as measured, and only the difference between the
two instances' programmed timing is compared, on the SCL pulses both instances drive while both
are transferring.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import I2C_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_i2c_field_masks import (
    I2C_CONTROLLER_EVENTS_NACK,
    I2C_CTRL_ENABLEHOST,
    I2C_FDATA_START,
    I2C_FDATA_STOP,
    I2C_FIFO_CTRL_RXRST_FMTRST,
    I2C_HOST_FIFO_STATUS_FMTLVL_BM,
    I2C_HOST_FIFO_STATUS_RXLVL_BM,
    I2C_HOST_FIFO_STATUS_RXLVL_BP,
    I2C_STATUS_FMTEMPTY,
    I2C_STATUS_FMTFULL,
    I2C_STATUS_HOSTIDLE,
    I2C_WRAP_CTRL_HOST,
    I2C_WRAP_EN,
)
from .smc_i2c_master_target_test_seq import (
    _fdata,
    _i2c_u32,
    _pack_timing0,
    _pack_timing1,
    _pack_timing2,
    _pack_timing3,
    _pack_timing4,
)
from .smc_i2c_protocol_vip import SmcI2cBusMonitor, SmcI2cEepromSlave
from .smc_i2c_target_smbus_test_seq import _pack_target_id
from .smc_i2c_wire_timing_test_seq import FM_PLUS_NS, THD_DAT_MIN, _cycles_up

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

INTR_CMD_COMPLETE = _i2c_u32("I2C__INTR_STATE__CMD_COMPLETE_bm")
INTR_CONTROLLER_HALT = _i2c_u32("I2C__INTR_STATE__CONTROLLER_HALT_bm")
FMTLVL_BP = _i2c_u32("I2C__HOST_FIFO_STATUS__FMTLVL_bp")
ALL_ONES = 0xFFFF_FFFF

INSTANCES = (0, 1)
TARGET_ADDR = {0: 0x50, 1: 0x2A}
ABSENT_ADDR = 0x3C

#: Write payloads, pointer byte first. S1 is the pad-route leg, S4 the overlapped transfers and
#: S6 the leg in which instance 1 addresses nobody.
ROUTE_DATA = {0: (0x10, 0x5A), 1: (0x20, 0xA5)}
OVERLAP_DATA = {0: (0x30, 0x11, 0x22, 0x33, 0x44), 1: (0x40, 0x99, 0x88)}
NACK_LEG_DATA = {0: (0x50, 0x6B), 1: (0x60,)}

#: TARGET_ID is a plain read-write register with no host-side effect.
WINDOW_VALUES = {
    0: _pack_target_id(0x21, 0x7F, 0x22, 0x7F),
    1: _pack_target_id(0x35, 0x7F, 0x36, 0x7F),
}

#: Instance 1 runs FM_PLUS_NS (the wire-timing leaf's set A) with THIGH and TLOW scaled.
SLOW_FACTOR = 4

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_ORDER = (
    "CHK-I2C-DUAL-PAD-ROUTE",
    "CHK-I2C-DUAL-REG-WINDOW",
    "CHK-I2C-DUAL-WIRE-ORDER",
    "CHK-I2C-DUAL-LIVENESS",
    "CHK-I2C-DUAL-TIMING-DIFF",
    "CHK-I2C-DUAL-FIFO-LEVELS",
    "CHK-I2C-DUAL-CMD-COMPLETE",
    "CHK-I2C-DUAL-STOP-COUNT",
    "CHK-I2C-DUAL-NACK-ISOLATION",
)
CHK_BY_STEP = {
    "CHK-I2C-DUAL-PAD-ROUTE": "S1",
    "CHK-I2C-DUAL-REG-WINDOW": "S2",
    "CHK-I2C-DUAL-WIRE-ORDER": "S4",
    "CHK-I2C-DUAL-LIVENESS": "S5",
    "CHK-I2C-DUAL-TIMING-DIFF": "S7",
    "CHK-I2C-DUAL-FIFO-LEVELS": "S5",
    "CHK-I2C-DUAL-CMD-COMPLETE": "S5",
    "CHK-I2C-DUAL-STOP-COUNT": "S5",
    "CHK-I2C-DUAL-NACK-ISOLATION": "S6",
}
FENCE_TERMS = {
    "S1": "PAD_ROUTE_RUN",
    "S2": "WINDOWS_WRITTEN",
    "S3": "TIMING_PROGRAMMED",
    "S4": "TRANSFERS_OVERLAPPING",
    "S5": "TRANSFERS_ENDED",
    "S6": "NACK_LEG_RUN",
    "S7": "SCL_PHASES_MEASURED",
}

POLL_GAP_CYCLES = 50
BOUND_PER_SPAN = 400
BOUND_FLOOR_CYCLES = 8192
START_POLLS = 400
NACK_POLLS = 600
NACK_POLL_GAP_CYCLES = 25
CLEAR_WINDOW_CYCLES = 4000
EN_WINDOW_CYCLES = 4000
PAD_RELEASE_POLLS = 400
PAD_RELEASE_GAP_CYCLES = 4
PUSH_GAP_CYCLES = 2
HOST_START_GAP_CYCLES = 2


def _reg(register: str, idx: int) -> int:
    return smc_indexed_addr(f"SMC_TOP_SMC_I2C_WRAP_I2C_{register}_BASE_ADDR", idx)


def _wrap(idx: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_I2C_WRAP_I2C_CTRL_REGS_I2C_CTRL_BASE_ADDR", idx)


def _timing_words(prog: dict[str, int]) -> tuple[int, int, int, int, int]:
    return (
        _pack_timing0(prog["thigh"], prog["tlow"]),
        _pack_timing1(prog["t_r"], prog["t_f"]),
        _pack_timing2(prog["tsu_sta"], prog["thd_sta"]),
        _pack_timing3(prog["tsu_dat"], prog["thd_dat"]),
        _pack_timing4(prog["tsu_sto"], prog["t_buf"]),
    )


def _write_words(addr7: int, data: tuple[int, ...]) -> list[int]:
    """START and address write, then the payload with a STOP on the last byte."""
    words = [_fdata(addr7 << 1, I2C_FDATA_START)]
    last = len(data) - 1
    words += [_fdata(b, I2C_FDATA_STOP if i == last else 0) for i, b in enumerate(data)]
    return words


def _fifo_levels(word: int) -> tuple[int, int]:
    fmt = (word & I2C_HOST_FIFO_STATUS_FMTLVL_BM) >> FMTLVL_BP
    rx = (word & I2C_HOST_FIFO_STATUS_RXLVL_BM) >> I2C_HOST_FIFO_STATUS_RXLVL_BP
    return fmt, rx


class DualWireRecorder:
    """Samples both pad pairs on every `clk_periph_i` rising edge and keeps the edges."""

    def __init__(self) -> None:
        dut = cocotb.top
        self._clk = dut.clk_periph_i
        self._pads = {
            i: (getattr(dut, f"tb_i2c{i}_scl"), getattr(dut, f"tb_i2c{i}_sda")) for i in INSTANCES
        }
        self.events: dict[int, list[tuple[int, str, int]]] = {i: [] for i in INSTANCES}
        self.starts = dict.fromkeys(INSTANCES, 0)
        self.stops = dict.fromkeys(INSTANCES, 0)
        self.cycle = 0
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
        parts = []
        for i, (scl, sda) in self._pads.items():
            parts.append(
                f"i2c{i}: edges={len(self.events[i])} starts={self.starts[i]} "
                f"stops={self.stops[i]} scl={self._level(scl)} sda={self._level(sda)}"
            )
        return f"cycle={self.cycle} " + "; ".join(parts)

    async def _run(self) -> None:
        level = {i: tuple(self._level(h) for h in pads) for i, pads in self._pads.items()}
        while True:
            await RisingEdge(self._clk)
            self.cycle += 1
            for i, pads in self._pads.items():
                scl, sda = level[i]
                new_scl, new_sda = (self._level(h) for h in pads)
                if new_scl != scl:
                    self.events[i].append((self.cycle, "scl", new_scl))
                if new_sda != sda:
                    self.events[i].append((self.cycle, "sda", new_sda))
                    if new_scl and scl:
                        if new_sda:
                            self.stops[i] += 1
                        else:
                            self.starts[i] += 1
                level[i] = (new_scl, new_sda)


def decode_write(label: str, events: list[tuple[int, str, int]], n_bytes: int) -> dict:
    """Reduce the edges of one write transfer to its bytes, acknowledges and SCL phases."""
    scl = sda = 1
    starts: list[int] = []
    stops: list[int] = []
    rises: list[int] = []
    falls: list[int] = []
    bits: list[int] = []
    for t, line, lvl in events:
        if line == "scl":
            (rises if lvl else falls).append(t)
            if lvl:
                bits.append(sda)
            scl = lvl
        else:
            sda = lvl
            if scl:
                (stops if lvl else starts).append(t)
    assert len(starts) == 1 and len(stops) == 1, (
        f"{label}: {len(starts)} START and {len(stops)} STOP edges on the pads, expected 1 and 1"
    )
    pulses = 9 * n_bytes
    assert len(rises) == pulses + 1 and len(falls) == pulses + 1, (
        f"{label}: {len(rises)} SCL rises and {len(falls)} falls, expected {pulses + 1} of each"
    )
    assert starts[0] < falls[0] < rises[0] and rises[-1] < stops[0], (
        f"{label}: edges out of order START={starts[0]} first fall={falls[0]} "
        f"first rise={rises[0]} last rise={rises[-1]} STOP={stops[0]}"
    )
    frames = []
    for k in range(n_bytes):
        field = bits[9 * k : 9 * k + 9]
        frames.append((int("".join(str(b) for b in field[:8]), 2), field[8]))
    return {
        "start": starts[0],
        "stop": stops[0],
        "frames": frames,
        "edges": len(events),
        "high": {n: falls[n] - rises[n - 1] for n in range(1, pulses + 1)},
        "low": {n: rises[n] - falls[n] for n in range(1, pulses)},
        "rises": rises,
        "falls": falls,
    }


class smc_i2c_dual_concurrent_transfer_test_seq(SmcCsrSeq):
    """Runs a write on each of two I2C controllers at the same time and measures both pad pairs."""

    def __init__(self, name: str = "smc_i2c_dual_concurrent_transfer_test_seq") -> None:
        super().__init__(name)
        self.dual_ok = False
        self.rec: DualWireRecorder | None = None
        self.eeprom: dict[int, SmcI2cEepromSlave] = {}
        self.monitor: dict[int, SmcI2cBusMonitor] = {}
        self.sets: dict[int, dict[str, int]] = {}
        self._events: list[tuple[str, str, int]] = []
        self._waits: list[str] = []
        self._bounds: dict[str, int] = {}
        self._last_state = "no wait entered"
        self.fifo_samples: list[tuple[int, int, int, int]] = []
        self.d: dict = {}

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
        assert [c[1] for c in chks] == list(CHK_ORDER), f"checker order {[c[1] for c in chks]}"
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

    def _build_sets(self) -> None:
        period_ps = int(float(self.cfg.periph_clk_period_ns) * 1000 + 0.5)
        a = {k: _cycles_up(ns, period_ps) for k, ns in FM_PLUS_NS.items()}
        a["thd_dat"] = THD_DAT_MIN
        slow = {k: v * SLOW_FACTOR if k in ("thigh", "tlow") else v for k, v in a.items()}
        self.sets = {0: a, 1: slow}
        assert all(v >= 1 for s in self.sets.values() for v in s.values()), "a TIMING field is 0"
        assert all(s["thigh"] >= 2 and s["tlow"] >= 2 for s in self.sets.values()), (
            "THIGH or TLOW below 2"
        )
        for idx, prog in self.sets.items():
            cocotb.log.info(
                "SET i2c%d (clk_i cycles): %s", idx, " ".join(f"{k}={v}" for k, v in prog.items())
            )
        span = max(sum(p.values()) for p in self.sets.values())
        self._bounds["transfer_done"] = BOUND_PER_SPAN * span + BOUND_FLOOR_CYCLES

    async def _poll_level(self, name: str, polls: int, gap: int, probe) -> None:
        """Run `probe` up to `polls` times, `gap` clk_periph_i cycles apart; raise on expiry."""
        state = "never sampled"
        for _ in range(polls):
            done, state = probe()
            if done:
                return
            await ClockCycles(cocotb.top.clk_periph_i, gap)
        self._last_state = f"{name}: {state}"
        raise AssertionError(f"{name}: not satisfied within {polls}x{gap} cycles; last {state}")

    async def _wait_pair_released(self, name: str, idx: int) -> None:
        dut = cocotb.top
        scl = getattr(dut, f"tb_i2c{idx}_scl")
        sda = getattr(dut, f"tb_i2c{idx}_sda")

        def probe() -> tuple[bool, str]:
            levels = (scl.value, sda.value)
            ok = all(v.is_resolvable for v in levels) and all(int(v) == 1 for v in levels)
            return ok, f"scl={levels[0]} sda={levels[1]}"

        await self._poll_level(name, PAD_RELEASE_POLLS, PAD_RELEASE_GAP_CYCLES, probe)

    async def _read_all(self, label: str, register: str) -> dict[int, int]:
        return {
            i: await self.csr_read(f"{label}_{register}{i}", _reg(register, i)) for i in INSTANCES
        }

    async def _levels(self, label: str) -> dict[int, tuple[int, int]]:
        words = await self._read_all(label, "HOST_FIFO_STATUS")
        return {i: _fifo_levels(w) for i, w in words.items()}

    async def _program(self, idx: int, label: str) -> None:
        regs = ("TIMING0", "TIMING1", "TIMING2", "TIMING3", "TIMING4")
        words = _timing_words(self.sets[idx])
        for reg, word in zip(regs, words):
            await self.csr_write(f"{label}_{reg}", _reg(reg, idx), word)
            await ClockCycles(cocotb.top.clk_smc_i, PUSH_GAP_CYCLES)
        for reg, word in zip(regs, words):
            await self.csr_read(f"{label}_{reg}_RB", _reg(reg, idx), expected=word)

    async def _prepare_host(self, idx: int, label: str) -> None:
        """Clean FIFOs, events and interrupts with the host disabled."""
        await self.csr_write(f"{label}_CTRL_OFF", _reg("CTRL", idx), 0)
        await self.csr_write(f"{label}_OVRD_OFF", _reg("OVRD", idx), 0)
        await self.csr_write(
            f"{label}_FIFO_RST", _reg("FIFO_CTRL", idx), I2C_FIFO_CTRL_RXRST_FMTRST
        )
        await self.csr_write(f"{label}_EVENTS_CLR", _reg("CONTROLLER_EVENTS", idx), ALL_ONES)
        await self.csr_write(f"{label}_INTR_CLR", _reg("INTR_STATE", idx), ALL_ONES)

    async def _enable_host(self, idx: int, label: str) -> int:
        await self.csr_write(f"{label}_ENABLEHOST", _reg("CTRL", idx), I2C_CTRL_ENABLEHOST)
        return self.rec.cycle

    async def _push(self, idx: int, label: str, words: list[int]) -> None:
        for i, word in enumerate(words):
            await self.csr_write(f"{label}_FDATA{i}", _reg("FDATA", idx), word)
            await ClockCycles(cocotb.top.clk_smc_i, PUSH_GAP_CYCLES)

    def _counts(self) -> dict[str, dict[int, int]]:
        return {
            "starts": {i: self.rec.starts[i] for i in INSTANCES},
            "stops": {i: self.rec.stops[i] for i in INSTANCES},
            "mon_starts": {
                i: sum(1 for t in self.monitor[i].transactions if t["ev"] == "START")
                for i in INSTANCES
            },
            "mon_stops": {
                i: sum(1 for t in self.monitor[i].transactions if t["ev"] == "STOP")
                for i in INSTANCES
            },
            "edges": {i: len(self.rec.events[i]) for i in INSTANCES},
        }

    async def _wait_done(self, label: str, pending: dict[int, int], began: dict[int, int]) -> dict:
        """Poll until each instance in `pending` (index -> STOP count before) has finished.

        Finished means HOSTIDLE and FMTEMPTY, CMD_COMPLETE set and the pad pair has shown one more
        STOP. Both instances' FIFO levels are sampled on every poll.
        """
        bound = self._bounds["transfer_done"]
        t0 = self.rec.cycle
        finished: dict[int, int] = {}
        last = "never sampled"
        while self.rec.cycle - t0 <= bound:
            fifo = await self._read_all(label, "HOST_FIFO_STATUS")
            self.fifo_samples.append((self.rec.cycle, fifo[0], fifo[1], len(finished)))
            for idx, base in pending.items():
                if idx in finished:
                    continue
                status = await self.csr_read(f"{label}_STATUS{idx}", _reg("STATUS", idx))
                intr = await self.csr_read(f"{label}_INTR{idx}", _reg("INTR_STATE", idx))
                want = I2C_STATUS_HOSTIDLE | I2C_STATUS_FMTEMPTY
                last = (
                    f"i2c{idx} STATUS=0x{status:08x} INTR_STATE=0x{intr:08x} "
                    f"stops={self.rec.stops[idx]} base={base}"
                )
                if (
                    status & want == want
                    and intr & INTR_CMD_COMPLETE
                    and self.rec.stops[idx] > base
                ):
                    finished[idx] = self.rec.cycle - began[idx]
            if len(finished) == len(pending):
                return finished
            await ClockCycles(cocotb.top.clk_periph_i, POLL_GAP_CYCLES)
        self._last_state = f"{last}; recorder {self.rec.state()}"
        raise AssertionError(
            f"{label}: transfers not finished within {bound} clk_periph_i cycles; "
            f"{self._last_state}"
        )

    async def _wait_started(self, label: str, base: dict[int, int], began: int) -> None:
        """Poll both instances' FIFO levels until each pad pair has shown a new START."""
        bound = self._bounds["transfer_done"]
        while self.rec.cycle - began <= bound:
            fifo = await self._read_all(label, "HOST_FIFO_STATUS")
            self.fifo_samples.append((self.rec.cycle, fifo[0], fifo[1], 0))
            if all(self.rec.starts[i] > base[i] for i in INSTANCES):
                return
            await ClockCycles(cocotb.top.clk_periph_i, POLL_GAP_CYCLES)
        self._last_state = f"{label}_start: {self.rec.state()}"
        raise AssertionError(
            f"{label}: both STARTs not seen within {bound} clk_periph_i cycles; {self.rec.state()}"
        )

    async def _bring_up(self) -> None:
        self._build_sets()
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_UNGATE_I2C", CLOCK_GATE_CONTROL, cg & ~I2C_CG_EN)
        await self.csr_write("I2C0_WRAP_HOST", _wrap(0), I2C_WRAP_CTRL_HOST)
        await self.wait_i2c0_lsio_ready("I2C0_DUAL")
        for idx in INSTANCES:
            self.eeprom[idx] = SmcI2cEepromSlave(
                addr=TARGET_ADDR[idx], name=f"smc_i2c{idx}_dual_eeprom", instance=idx
            )
            self.monitor[idx] = SmcI2cBusMonitor(name=f"smc_i2c{idx}_dual_monitor", instance=idx)
        self.rec = DualWireRecorder()
        self.rec.start()
        await self.csr_write("I2C1_WRAP_OFF", _wrap(1), 0)
        wrap1 = await self.csr_read("I2C1_WRAP_RB", _wrap(1), expected=0)
        assert wrap1 & I2C_WRAP_EN == 0, f"I2C_CTRL[1].I2C_EN is set (0x{wrap1:08x})"
        for idx in INSTANCES:
            await self._program(idx, f"BRINGUP{idx}")
        await self._prepare_host(0, "BRINGUP0")
        await ClockCycles(cocotb.top.clk_smc_i, 20)

    async def _s1_pad_route(self) -> None:
        pre = self._counts()
        base0 = pre["stops"][0]
        begin = await self._enable_host(0, "ROUTE0")
        await self._push(0, "ROUTE0", _write_words(TARGET_ADDR[0], ROUTE_DATA[0]))
        await self._wait_done("ROUTE0", {0: base0}, {0: begin})
        mid = self._counts()
        # Instance 1 is commanded while I2C_CTRL[1].I2C_EN is clear.
        await self._prepare_host(1, "ROUTE1")
        await self._enable_host(1, "ROUTE1")
        await self._push(1, "ROUTE1", _write_words(TARGET_ADDR[1], ROUTE_DATA[1]))
        clear_fifo = 0
        clear_status = 0
        for _ in range(CLEAR_WINDOW_CYCLES // POLL_GAP_CYCLES):
            clear_fifo = await self.csr_read("ROUTE1_CLEAR_FIFO", _reg("HOST_FIFO_STATUS", 1))
            clear_status = await self.csr_read("ROUTE1_CLEAR_STATUS", _reg("STATUS", 1))
            await ClockCycles(cocotb.top.clk_periph_i, POLL_GAP_CYCLES)
        clear = self._counts()
        await self.csr_write("I2C1_WRAP_HOST", _wrap(1), I2C_WRAP_CTRL_HOST)
        wrap1 = await self.csr_read("I2C1_WRAP_HOST_RB", _wrap(1), expected=I2C_WRAP_CTRL_HOST)
        base1 = clear["starts"][1]
        enabled_at = self.rec.cycle
        for _ in range(EN_WINDOW_CYCLES // POLL_GAP_CYCLES):
            if self.rec.starts[1] > base1:
                break
            await ClockCycles(cocotb.top.clk_periph_i, POLL_GAP_CYCLES)
        en_only = self._counts()
        assert en_only["starts"][1] > base1, (
            f"no START on the instance-1 padring outputs within {EN_WINDOW_CYCLES} cycles of "
            f"I2C_EN[1] alone: I2C_CTRL[1]=0x{wrap1:08x} edges with I2C_EN clear="
            f"{clear['edges'][1]} edges after I2C_EN={en_only['edges'][1]}; {self.rec.state()}"
        )
        await self._wait_done("ROUTE1", {1: clear["stops"][1]}, {1: enabled_at})
        await self.arm_i2c_gpio_lsio(1, "I2C1_DUAL")
        await self._wait_pair_released("i2c1_pads_released", 1)
        post = self._counts()
        self.d["route"] = {
            "pre": pre,
            "mid": mid,
            "clear": clear,
            "clear_fifo": clear_fifo,
            "clear_status": clear_status,
            "en_only": en_only,
            "post": post,
            "wrap1": wrap1,
        }

    async def _s2_windows(self) -> None:
        reg = "TARGET_ID"
        before = {i: await self.csr_read(f"WIN_BEFORE{i}", _reg(reg, i)) for i in INSTANCES}
        await self.csr_write("WIN1_WRITE", _reg(reg, 1), WINDOW_VALUES[1])
        await ClockCycles(cocotb.top.clk_smc_i, PUSH_GAP_CYCLES)
        win0_after_w1 = await self.csr_read("WIN0_AFTER_W1", _reg(reg, 0))
        win1_after_w1 = await self.csr_read("WIN1_AFTER_W1", _reg(reg, 1))
        await self.csr_write("WIN0_WRITE", _reg(reg, 0), WINDOW_VALUES[0])
        await ClockCycles(cocotb.top.clk_smc_i, PUSH_GAP_CYCLES)
        win0_final = await self.csr_read("WIN0_FINAL", _reg(reg, 0))
        win1_final = await self.csr_read("WIN1_FINAL", _reg(reg, 1))
        self.d["window"] = {
            "before": before,
            "w1": (win0_after_w1, win1_after_w1),
            "final": (win0_final, win1_final),
            "addr": {i: _reg(reg, i) for i in INSTANCES},
        }

    async def _s3_timing(self) -> None:
        for idx in INSTANCES:
            await self._program(idx, f"SET{idx}")

    async def _s4_overlap(self) -> None:
        for idx in INSTANCES:
            await self._prepare_host(idx, f"OVERLAP{idx}")
        self.eeprom_base = {
            i: (self.eeprom[i].starts, self.eeprom[i].stops, self.eeprom[i].acks) for i in INSTANCES
        }
        self.mem_base = {i: self.eeprom[i].bytes for i in INSTANCES}
        base_levels = await self._levels("LVL_BASE")
        pushed = {}
        for idx in INSTANCES:
            await self._push(
                idx, f"OVERLAP{idx}", _write_words(TARGET_ADDR[idx], OVERLAP_DATA[idx])
            )
            pushed[idx] = await self._levels(f"LVL_PUSH{idx}")
        status = await self._read_all("LVL_STATUS", "STATUS")
        self.window_mark = {i: len(self.rec.events[i]) for i in INSTANCES}
        pre = self._counts()
        began = {}
        began[0] = await self._enable_host(0, "OVERLAP0")
        await ClockCycles(cocotb.top.clk_smc_i, HOST_START_GAP_CYCLES)
        began[1] = await self._enable_host(1, "OVERLAP1")

        await self._wait_started("OVERLAP", pre["starts"], began[1])
        self.d["overlap"] = {
            "base_levels": base_levels,
            "pushed": pushed,
            "status": status,
            "pre": pre,
            "began": began,
        }

    async def _s5_end(self) -> None:
        ov = self.d["overlap"]
        stops = {i: ov["pre"]["stops"][i] for i in INSTANCES}
        finished = await self._wait_done("OVERLAP_END", stops, ov["began"])
        self.window_end = {i: len(self.rec.events[i]) for i in INSTANCES}
        counts = self._counts()
        status = await self._read_all("END_STATUS", "STATUS")
        levels = await self._levels("END_LEVELS")
        intr = await self._read_all("END_INTR", "INTR_STATE")
        await self.csr_write("CMD_COMPLETE_CLR0", _reg("INTR_STATE", 0), INTR_CMD_COMPLETE)
        after_clear0 = await self._read_all("CMD_COMPLETE_AFTER_CLR0", "INTR_STATE")
        await self.csr_write("CMD_COMPLETE_CLR1", _reg("INTR_STATE", 1), INTR_CMD_COMPLETE)
        after_clear1 = await self._read_all("CMD_COMPLETE_AFTER_CLR1", "INTR_STATE")
        self.d["end"] = {
            "finished": finished,
            "counts": counts,
            "status": status,
            "levels": levels,
            "intr": intr,
            "after_clear0": after_clear0,
            "after_clear1": after_clear1,
            "mem": {
                i: self.eeprom[i].read_mem(OVERLAP_DATA[i][0], len(OVERLAP_DATA[i]) - 1)
                for i in INSTANCES
            },
            "eeprom": {
                i: (
                    self.eeprom[i].starts - self.eeprom_base[i][0],
                    self.eeprom[i].stops - self.eeprom_base[i][1],
                    self.eeprom[i].acks - self.eeprom_base[i][2],
                    self.eeprom[i].bytes - self.mem_base[i],
                )
                for i in INSTANCES
            },
        }

    async def _wait_nack(self, idx: int) -> int:
        events = 0
        for _ in range(NACK_POLLS):
            events = await self.csr_read(f"NACK_WAIT{idx}", _reg("CONTROLLER_EVENTS", idx))
            if events & I2C_CONTROLLER_EVENTS_NACK:
                return events
            await ClockCycles(cocotb.top.clk_periph_i, NACK_POLL_GAP_CYCLES)
        self._last_state = f"i2c{idx} CONTROLLER_EVENTS=0x{events:08x}; {self.rec.state()}"
        raise AssertionError(
            f"nack_wait: no NACK event within {NACK_POLLS}x{NACK_POLL_GAP_CYCLES} cycles; "
            f"{self._last_state}"
        )

    async def _read_event_state(self, label: str) -> dict[str, dict[int, int]]:
        events = await self._read_all(f"{label}_EVENTS", "CONTROLLER_EVENTS")
        intr = await self._read_all(f"{label}_INTR", "INTR_STATE")
        return {"events": events, "intr": intr}

    async def _s6_nack(self) -> None:
        pre = self._counts()
        eeprom_base = {i: (self.eeprom[i].starts, self.eeprom[i].acks) for i in INSTANCES}
        began = {i: self.rec.cycle for i in INSTANCES}
        await self._push(0, "NACK0", _write_words(TARGET_ADDR[0], NACK_LEG_DATA[0]))
        await self._push(1, "NACK1", [_fdata(ABSENT_ADDR << 1, I2C_FDATA_START | I2C_FDATA_STOP)])
        finished = await self._wait_done("NACK_LEG0", {0: pre["stops"][0]}, began)
        await self._wait_nack(1)
        nack_cycles = self.rec.cycle - began[1]
        observed = await self._read_event_state("NACK_OBS")
        await self.csr_write("NACK1_CLR", _reg("CONTROLLER_EVENTS", 1), I2C_CONTROLLER_EVENTS_NACK)
        await ClockCycles(cocotb.top.clk_smc_i, PUSH_GAP_CYCLES)
        cleared = await self._read_event_state("NACK_CLR")
        self.d["nack"] = {
            "observed": observed,
            "cleared": cleared,
            "finished": finished,
            "nack_cycles": nack_cycles,
            "counts": {"pre": pre, "post": self._counts()},
            "mem0": self.eeprom[0].read_mem(NACK_LEG_DATA[0][0], len(NACK_LEG_DATA[0]) - 1),
            "eeprom": {
                i: (
                    self.eeprom[i].starts - eeprom_base[i][0],
                    self.eeprom[i].acks - eeprom_base[i][1],
                )
                for i in INSTANCES
            },
        }

    def _s7_measure(self) -> None:
        self.d["wire"] = {}
        for i in INSTANCES:
            window = self.rec.events[i][self.window_mark[i] : self.window_end[i]]
            assert window, f"i2c{i}: no pad edges in the overlapped transfer"
            assert window[0][1:] == ("sda", 0), f"i2c{i}: first edge is not a START: {window[0]}"
            assert window[-1][1:] == ("sda", 1), f"i2c{i}: last edge is not a STOP: {window[-1]}"
            self.d["wire"][i] = decode_write(f"i2c{i}", window, 1 + len(OVERLAP_DATA[i]))

    def _frames_expected(self, idx: int) -> list[tuple[int, int]]:
        return [(TARGET_ADDR[idx] << 1, 0)] + [(b, 0) for b in OVERLAP_DATA[idx]]

    def _chk_pad_route(self) -> str:
        r = self.d["route"]
        pre, mid, clear, en, post = r["pre"], r["mid"], r["clear"], r["en_only"], r["post"]
        assert r["wrap1"] & I2C_WRAP_EN, f"I2C_CTRL[1] I2C_EN not set (0x{r['wrap1']:08x})"
        assert mid["starts"][0] - pre["starts"][0] == 1 and mid["mon_starts"][0] == 1, (
            f"instance-0 START not seen once on the instance-0 pads: pre={pre} mid={mid}"
        )
        added0 = mid["edges"][0] - pre["edges"][0]
        assert added0 > 0, "no edge on the instance-0 pads"
        clear_edges = clear["edges"][1]
        assert clear_edges == 0 and clear["mon_starts"][1] == 0, (
            f"{clear_edges} edges on the instance-1 padring outputs with I2C_EN clear: {clear}"
        )
        assert post["starts"][1] - clear["starts"][1] == 1 and post["mon_starts"][1] == 1, (
            f"instance-1 START after I2C_EN set: clear={clear} post={post}"
        )
        assert post["edges"][0] == mid["edges"][0], (
            f"instance-0 pads moved during the instance-1 transfer: {mid['edges'][0]} -> "
            f"{post['edges'][0]}"
        )
        set_edges = post["edges"][1]
        assert set_edges > 0, "no edge on the instance-1 padring outputs after I2C_EN was set"
        fmtlvl = _fifo_levels(r["clear_fifo"])[0]
        return (
            f"padring outputs of pads I2c1SclPad/I2c1SdaPad observed: with I2C_EN[1] clear and an "
            f"instance-1 write queued and its host enabled (FMTLVL {fmtlvl}, STATUS "
            f"0x{r['clear_status']:08x}) the instance-1 pads showed {clear_edges} edges over "
            f"{CLEAR_WINDOW_CYCLES} cycles while the instance-0 write gave {added0} edges and 1 "
            f"START on the instance-0 pads; after setting I2C_EN[1] (I2C_CTRL[1]="
            f"0x{r['wrap1']:08x}) the instance-1 pads showed {set_edges} edges and 1 START, "
            f"{en['edges'][1]} edges within {EN_WINDOW_CYCLES} cycles of I2C_EN alone, "
            f"before any LSIO select; "
            f"instance-0 pad edge count unchanged at {post['edges'][0]}"
        )

    def _chk_reg_window(self) -> str:
        w = self.d["window"]
        before, (w0_a, w1_a), (w0_f, w1_f) = w["before"], w["w1"], w["final"]
        v0, v1 = WINDOW_VALUES[0], WINDOW_VALUES[1]
        assert v0 != v1 and v1 != before[1] and v0 != before[0], "window values not distinct"
        assert w1_a == v1, f"instance-1 window read 0x{w1_a:08x} after writing 0x{v1:08x}"
        assert w0_a == before[0], f"instance-0 window moved 0x{before[0]:08x} -> 0x{w0_a:08x}"
        assert w0_f == v0, f"instance-0 window read 0x{w0_f:08x} after writing 0x{v0:08x}"
        assert w1_f == v1, f"instance-1 window moved 0x{v1:08x} -> 0x{w1_f:08x}"
        return (
            f"TARGET_ID at 0x{w['addr'][0]:08x} (instance 0) and "
            f"0x{w['addr'][1]:08x} (instance 1): "
            f"before 0x{before[0]:08x}/0x{before[1]:08x}; write 0x{v1:08x} to instance 1 -> "
            f"instance 0 reads 0x{w0_a:08x} unchanged, instance 1 reads 0x{w1_a:08x}; write "
            f"0x{v0:08x} to instance 0 -> instance 0 reads 0x{w0_f:08x}, instance 1 reads "
            f"0x{w1_f:08x}"
        )

    def _chk_wire_order(self) -> str:
        wire, end = self.d["wire"], self.d["end"]
        parts = []
        for i in INSTANCES:
            exp = self._frames_expected(i)
            assert wire[i]["frames"] == exp, (
                f"i2c{i} pad bytes (value, ack) {wire[i]['frames']} differ from pushed {exp}"
            )
            starts, stops, acks, written = end["eeprom"][i]
            assert (starts, stops, acks) == (1, 1, 1), (
                f"i2c{i} target counted starts/stops/acks {(starts, stops, acks)}, expected 1/1/1"
            )
            data = OVERLAP_DATA[i][1:]
            assert end["mem"][i] == bytes(data) and written == len(data), (
                f"i2c{i} target memory {end['mem'][i].hex()} written {written}, "
                f"expected {bytes(data).hex()}"
            )
            frames = " ".join(
                f"0x{v:02x}/{'ACK' if a == 0 else 'NACK'}" for v, a in wire[i]["frames"]
            )
            parts.append(f"i2c{i}: START@{wire[i]['start']} bytes {frames} STOP@{wire[i]['stop']}")
        assert wire[0]["start"] < wire[1]["start"] < wire[0]["stop"], (
            f"instance-1 START {wire[1]['start']} not inside the instance-0 transfer "
            f"{wire[0]['start']}..{wire[0]['stop']}"
        )
        overlap = wire[0]["stop"] - wire[1]["start"]
        assert overlap > 0, f"overlap {overlap}"
        return (
            "; ".join(parts) + f"; instance-1 START after instance-0 START and before its STOP, "
            f"overlap {overlap} clk_periph_i cycles (measured), each pad pair shows only its own "
            "bytes and every edge between its own START and STOP"
        )

    def _chk_liveness(self) -> str:
        end, nack = self.d["end"], self.d["nack"]
        bound = self._bounds["transfer_done"]
        for i in INSTANCES:
            assert end["finished"][i] <= bound, f"i2c{i} took {end['finished'][i]} cycles"
        assert nack["nack_cycles"] <= bound and nack["finished"][0] <= bound
        return (
            f"both transfers reached CMD_COMPLETE: instance 0 in {end['finished'][0]} and "
            f"instance 1 in {end['finished'][1]} clk_periph_i cycles from its host enable; "
            f"NACK leg: instance 0 CMD_COMPLETE in {nack['finished'][0]} cycles and the instance-1 "
            f"NACK event in {nack['nack_cycles']} cycles; bench bound {bound} clk_periph_i cycles "
            "(harness limit, not a specification value)"
        )

    @staticmethod
    def _phase_span(wire: dict, phase: str, n: int) -> tuple[int, int]:
        """First and last edge cycle of SCL pulse `n`'s high phase or of low phase `n`."""
        if phase == "high":
            return wire["rises"][n - 1], wire["falls"][n]
        return wire["falls"][n], wire["rises"][n]

    def _chk_timing_diff(self) -> str:
        wire = self.d["wire"]
        # Only phases that both instances drive while both are transferring: from the
        # instance-1 START to the instance-0 STOP.
        lo, hi = wire[1]["start"], wire[0]["stop"]
        assert lo < hi, f"no overlap: instance-1 START {lo} instance-0 STOP {hi}"
        parts = []
        for phase, field in (("high", "thigh"), ("low", "tlow")):
            exp = self.sets[1][field] - self.sets[0][field]
            assert exp != 0, f"programmed {field} delta is 0"
            common = sorted(set(wire[0][phase]) & set(wire[1][phase]))
            keys = [
                n
                for n in common
                if all(
                    lo <= self._phase_span(wire[i], phase, n)[0]
                    and self._phase_span(wire[i], phase, n)[1] <= hi
                    for i in INSTANCES
                )
            ]
            assert keys, f"no common {phase} phase inside the overlap window {lo}..{hi}"
            bad = [
                f"{phase}[{n}] measured {wire[1][phase][n] - wire[0][phase][n]}"
                for n in keys
                if wire[1][phase][n] - wire[0][phase][n] != exp
            ]
            assert not bad, f"{len(bad)} of {len(keys)} {phase} deltas differ from {exp}: {bad[:8]}"
            parts.append(
                f"delta(SCL {phase}) instance 1 minus instance 0 = {exp} equals "
                f"delta({field.upper()}) on {len(keys)} phases inside the overlap window "
                f"{lo}..{hi} ({len(common)} phase indices in common)"
            )
        absolutes = "; ".join(
            f"i2c{i}: high {min(wire[i]['high'].values())}..{max(wire[i]['high'].values())} "
            f"low {min(wire[i]['low'].values())}..{max(wire[i]['low'].values())}"
            for i in INSTANCES
        )
        return "; ".join(parts) + f"; absolute phases measured clk_periph_i cycles: {absolutes}"

    def _chk_fifo_levels(self) -> str:
        ov, end = self.d["overlap"], self.d["end"]
        base, pushed, status = ov["base_levels"], ov["pushed"], ov["status"]
        assert pushed[0][0][0] > base[0][0], f"instance-0 FMTLVL did not rise: {base} {pushed}"
        assert pushed[0][0][1] == base[0][1] and pushed[0][1] == base[1], (
            f"instance 1 or RXLVL moved while instance 0 was pushed: {base} {pushed[0]}"
        )
        assert pushed[1][1][0] > pushed[0][1][0], f"instance-1 FMTLVL did not rise: {pushed}"
        assert pushed[1][0] == pushed[0][0], (
            f"instance-0 levels moved while instance 1 was pushed: {pushed[0][0]} -> {pushed[1][0]}"
        )
        for i in INSTANCES:
            assert status[i] & I2C_STATUS_FMTFULL == 0, f"i2c{i} FMTFULL set 0x{status[i]:08x}"
            assert end["levels"][i][0] == 0, f"i2c{i} FMTLVL {end['levels'][i][0]} after the end"
            want = I2C_STATUS_FMTEMPTY | I2C_STATUS_HOSTIDLE
            assert end["status"][i] & want == want, (
                f"i2c{i} STATUS 0x{end['status'][i]:08x} lacks FMTEMPTY and HOSTIDLE"
            )
        peak = {
            i: max(_fifo_levels(sample[1 + i])[0] for sample in self.fifo_samples)
            for i in INSTANCES
        }
        return (
            f"FMTLVL before pushes i2c0={base[0][0]} i2c1={base[1][0]}; "
            f"after the instance-0 pushes "
            f"i2c0={pushed[0][0][0]} i2c1={pushed[0][1][0]} (instance 1 and both RXLVL unchanged); "
            f"after the instance-1 pushes i2c0={pushed[1][0][0]} (unchanged) "
            f"i2c1={pushed[1][1][0]}; "
            f"FMTFULL clear on both; peak FMTLVL while running i2c0={peak[0]} i2c1={peak[1]} "
            f"measured over {len(self.fifo_samples)} polls; at the end FMTLVL i2c0="
            f"{end['levels'][0][0]} i2c1={end['levels'][1][0]} with STATUS "
            f"0x{end['status'][0]:08x}/0x{end['status'][1]:08x} FMTEMPTY and HOSTIDLE set"
        )

    def _chk_cmd_complete(self) -> str:
        end = self.d["end"]
        intr, a0, a1 = end["intr"], end["after_clear0"], end["after_clear1"]
        bit = INTR_CMD_COMPLETE
        assert all(intr[i] & bit for i in INSTANCES), f"CMD_COMPLETE after the STOPs: {intr}"
        assert a0[0] & bit == 0 and a0[1] & bit, f"after the instance-0 clear: {a0}"
        assert a1[0] & bit == 0 and a1[1] & bit == 0, f"after the instance-1 clear: {a1}"
        return (
            f"INTR_STATE after the STOPs i2c0=0x{intr[0]:08x} i2c1=0x{intr[1]:08x} both "
            f"CMD_COMPLETE set; after writing 1 to instance 0 i2c0=0x{a0[0]:08x} clear, "
            f"i2c1=0x{a0[1]:08x} still "
            f"set; after writing 1 to instance 1 i2c0=0x{a1[0]:08x} i2c1=0x{a1[1]:08x} both clear"
        )

    def _chk_stop_count(self) -> str:
        pre, post = self.d["overlap"]["pre"], self.d["end"]["counts"]
        stops = {i: post["mon_stops"][i] - pre["mon_stops"][i] for i in INSTANCES}
        wire_stops = {i: post["stops"][i] - pre["stops"][i] for i in INSTANCES}
        assert stops == {0: 1, 1: 1}, f"bus monitor STOP counts {stops}, expected 1 on each pair"
        assert wire_stops == {0: 1, 1: 1}, f"recorder STOP counts {wire_stops}, expected 1 each"
        return (
            f"bus monitor STOP count in the overlapped transfers: instance-0 pads {stops[0]}, "
            f"instance-1 pads {stops[1]}; edge recorder STOP count {wire_stops[0]} and "
            f"{wire_stops[1]}; each pair carries only its own instance's bytes"
        )

    def _chk_nack_isolation(self) -> str:
        n = self.d["nack"]
        obs, clr = n["observed"], n["cleared"]
        nack, halt, done = I2C_CONTROLLER_EVENTS_NACK, INTR_CONTROLLER_HALT, INTR_CMD_COMPLETE
        assert obs["events"][1] & nack and obs["intr"][1] & halt, f"instance-1 not halted: {obs}"
        assert obs["events"][0] & nack == 0 and obs["intr"][0] & halt == 0, (
            f"instance 0 reports an event: {obs}"
        )
        assert obs["intr"][0] & done, f"instance-0 CMD_COMPLETE not set: {obs}"
        assert n["mem0"] == bytes(NACK_LEG_DATA[0][1:]), (
            f"instance-0 target memory {n['mem0'].hex()}"
        )
        starts1, acks1 = n["eeprom"][1]
        assert acks1 == 0, f"the instance-1 target acknowledged 0x{ABSENT_ADDR:02x}"
        assert clr["events"][1] & nack == 0 and clr["intr"][1] & halt == 0, (
            f"instance-1 NACK or CONTROLLER_HALT still set after the clear: {clr}"
        )
        return (
            f"instance 1 addressed absent 0x{ABSENT_ADDR:02x} (target acks {acks1}): "
            f"CONTROLLER_EVENTS i2c0=0x{obs['events'][0]:08x} i2c1=0x{obs['events'][1]:08x}, "
            f"INTR_STATE i2c0=0x{obs['intr'][0]:08x} i2c1=0x{obs['intr'][1]:08x}: NACK and "
            f"CONTROLLER_HALT set on instance 1 only, instance 0 finished its write with "
            f"CMD_COMPLETE and no event; after writing 1 to the instance-1 NACK event "
            f"CONTROLLER_EVENTS i2c1=0x{clr['events'][1]:08x} INTR_STATE "
            f"i2c1=0x{clr['intr'][1]:08x} NACK and CONTROLLER_HALT clear"
        )

    async def body(self) -> None:
        await self._bring_up()
        await self._s1_pad_route()
        self._step_done("S1")
        await self._s2_windows()
        self._step_done("S2")
        await self._s3_timing()
        self._step_done("S3")
        await self._s4_overlap()
        self._step_done("S4")
        await self._s5_end()
        self._step_done("S5")
        await self._s6_nack()
        self._step_done("S6")
        self._s7_measure()
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._step_done("S7")
        self.rec.stop()

        self._chk("CHK-I2C-DUAL-PAD-ROUTE", self._chk_pad_route())
        self._chk("CHK-I2C-DUAL-REG-WINDOW", self._chk_reg_window())
        self._chk("CHK-I2C-DUAL-WIRE-ORDER", self._chk_wire_order())
        self._chk("CHK-I2C-DUAL-LIVENESS", self._chk_liveness())
        self._chk("CHK-I2C-DUAL-TIMING-DIFF", self._chk_timing_diff())
        self._chk("CHK-I2C-DUAL-FIFO-LEVELS", self._chk_fifo_levels())
        self._chk("CHK-I2C-DUAL-CMD-COMPLETE", self._chk_cmd_complete())
        self._chk("CHK-I2C-DUAL-STOP-COUNT", self._chk_stop_count())
        self._chk("CHK-I2C-DUAL-NACK-ISOLATION", self._chk_nack_isolation())

        self._assert_fence()
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: 6 bounded waits: transfer_done=%d clk_periph_i cycles (%d x the "
            "largest sum of the programmed counts + %d, polled every %d) "
            "fail-on-expiry=AssertionError last=STATUS, INTR_STATE and pad-pair monitor state; "
            "overlap_start=%d clk_periph_i cycles (the transfer_done bound) fail-on-expiry="
            "AssertionError last=pad-pair monitor state; nack_wait=%d polls %d cycles apart "
            "fail-on-expiry=AssertionError last=CONTROLLER_EVENTS and monitor state; "
            "pad_release=%d polls %d cycles apart fail-on-expiry=AssertionError last=pad levels; "
            "i2c0_lsio_ready=2000 polls enforced-by=smc_csr_seq_utils.py fail-on-expiry="
            "AssertionError last=bus and pad-sense levels; axi_access=%d ns enforced-by=the AXI "
            "driver fail-on-expiry=AssertionError last=access address; last diagnostic=%s",
            self._bounds["transfer_done"],
            BOUND_PER_SPAN,
            BOUND_FLOOR_CYCLES,
            POLL_GAP_CYCLES,
            self._bounds["transfer_done"],
            NACK_POLLS,
            NACK_POLL_GAP_CYCLES,
            PAD_RELEASE_POLLS,
            PAD_RELEASE_GAP_CYCLES,
            self.cfg.axi_timeout_ns,
            self._last_state,
        )
        self.dual_ok = True
