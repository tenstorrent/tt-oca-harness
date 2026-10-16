# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP external interrupt pins to the PIC pending sources, walked one lane at a time.

PIC slots 44-255 are the chip-level external inputs; slot N is bit ``N % 32`` of
``meip[N / 32]`` and bit ``N - 1`` of the vector driven to the core
(``hw/sys/sep/doc/interrupts.adoc``, "Sources and Routing" and "Software
Handling"). The level gateway at its reset configuration (polarity 0, level type,
``el2_pic.rdl`` MEIGWCTRL) makes the pending bit follow the pin. The bench drives
``tb_sep_ext_interrupts``; the pending vector and the core request port are read
by passive probe on ``obs_sep_clk_o``.
"""

from __future__ import annotations

from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_tb_pins import smu_scope

# interrupts.adoc "SEP CPU Interrupt Vector Map": slots 1-43 are assigned, slots 44-255 are the
# external band.
EXT_FIRST_SOURCE = 44
EXT_LAST_SOURCE = 255
EXT_LANES = EXT_LAST_SOURCE - EXT_FIRST_SOURCE + 1
EXT_BAND_MASK = (1 << EXT_LANES) - 1
# interrupts.adoc "Sources and Routing": bit i of the driven vector is PIC source i + 1.
CORE_PORT_SOURCE_BASE = 1
# interrupts.adoc "Software Handling": source N is bit N % 32 of meip[N / 32].
MEIP_WORD_BITS = 32

PENDING_PATH = "gen_sep.u_sep.u_sep_cpu.u_el2_veer_wrapper.veer.pic_ctrl_inst.extintsrc_req_gw"
CORE_PORT_PATH = "gen_sep.u_sep.u_sep_cpu.extintsrc_req_i"
PIN_NAME = "tb_sep_ext_interrupts"

# Bounds of the bounded waits, in obs_sep_clk_o cycles.
RISE_BOUND_CYCLES = 64
FALL_BOUND_CYCLES = 64
STEP_CLOCK_GAP = 2

# Wait sites per kind: one rise wait and one fall wait per external lane.
EXPECTED_SITE_KINDS = {"pending_rise": EXT_LANES, "pending_fall": EXT_LANES}

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8")


def _meip_bit(vector: int, source: int) -> int:
    word = (vector >> (MEIP_WORD_BITS * (source // MEIP_WORD_BITS))) & ((1 << MEIP_WORD_BITS) - 1)
    return (word >> (source % MEIP_WORD_BITS)) & 1


def _band_shape(band: int) -> tuple[int, int]:
    """(number of set bits, index of the highest set bit or -1)."""
    return band.bit_count(), band.bit_length() - 1


class smu_sep_external_irq_pins_test_seq:
    """Each external SEP interrupt pin raises its own PIC pending source and nothing else."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.pin = getattr(self.dut, PIN_NAME)
        self.smu = smu_scope(self.dut)
        self.pending = hier(self.smu, PENDING_PATH)
        self.port = hier(self.smu, CORE_PORT_PATH)
        self.clk = self.dut.obs_sep_clk_o
        self.sites: list[dict] = []
        self.step_ns: dict[str, float] = {}
        self.max_high = 0
        self.done = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    def _now(self) -> float:
        return float(get_sim_time(unit="ns"))

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.dut.clk_smu_i)
        self.step_ns[step] = self._now()
        self._log(f"STEP {step} @{self.step_ns[step]:.3f}ns: {text}")

    def _pending_vector(self) -> int:
        return sample(self.pending, PENDING_PATH)

    def _port_vector(self) -> int:
        return sample(self.port, CORE_PORT_PATH)

    def _pins(self) -> int:
        return sample(self.pin, PIN_NAME)

    def _site(self, kind: str, lane: int, bound: int, used: int, last: str, expired: bool) -> None:
        self.sites.append(
            {
                "kind": kind,
                "lane": lane,
                "bound": bound,
                "used": used,
                "last": last,
                "expired": int(expired),
            }
        )
        if expired:
            raise AssertionError(
                f"TIMEOUT {kind} lane={lane}: bound={bound} used={used} last_state={last}"
            )

    async def _wait_pending(self, kind: str, lane: int, level: int, bound: int) -> tuple[int, int]:
        """(cycles of obs_sep_clk_o, pending bit) once the bit of ``lane`` reads ``level``."""
        source = EXT_FIRST_SOURCE + lane
        used = 0
        bit = _meip_bit(self._pending_vector(), source)
        while bit != level and used < bound:
            await RisingEdge(self.clk)
            used += 1
            bit = _meip_bit(self._pending_vector(), source)
        self._site(kind, lane, bound, used, f"pending[{source}]={bit}", bit != level)
        return used, bit

    async def _drive(self, value: int) -> None:
        self.pin.value = value
        await RisingEdge(self.clk)
        high = self._pins().bit_count()
        self.max_high = max(self.max_high, high)

    async def _walk_lane(self, lane: int, results: dict) -> None:
        source = EXT_FIRST_SOURCE + lane
        port_bit = source - CORE_PORT_SOURCE_BASE
        before = _meip_bit(self._pending_vector(), source)
        if lane == 0:
            await self._mark("S3", f"lane {lane} first drive, wait for pending source {source}")
        await self._drive(1 << lane)
        rise_cycles, shown = await self._wait_pending("pending_rise", lane, 1, RISE_BOUND_CYCLES)
        results["rise"].append((lane, before, shown))
        self._log(f"OBSERVATION lane {lane} rise pin_to_pending_cycles={rise_cycles} measured")

        await RisingEdge(self.clk)
        if lane == 0:
            await self._mark("S4", f"lane {lane} one-hot and core request port compare")
        await RisingEdge(self.clk)
        vector = self._pending_vector()
        band = (vector >> EXT_FIRST_SOURCE) & EXT_BAND_MASK
        port = self._port_vector()
        port_band = (port >> (EXT_FIRST_SOURCE - CORE_PORT_SOURCE_BASE)) & EXT_BAND_MASK
        results["onehot"].append((lane, *_band_shape(band)))
        results["port"].append(
            (
                lane,
                (port >> port_bit) & 1,
                _meip_bit(vector, source),
                *_band_shape(port_band),
            )
        )

        await RisingEdge(self.clk)
        if lane == 0:
            await self._mark("S5", f"lane {lane} released, wait for pending source {source} low")
        held = _meip_bit(self._pending_vector(), source)
        await self._drive(0)
        fall_cycles, dropped = await self._wait_pending("pending_fall", lane, 0, FALL_BOUND_CYCLES)
        results["fall"].append((lane, held, dropped))
        self._log(f"OBSERVATION lane {lane} fall pending_to_zero_cycles={fall_cycles} measured")

        await RisingEdge(self.clk)
        if lane == 0:
            await self._mark("S6", f"lane {lane} external band all-zero compare")
        await RisingEdge(self.clk)
        band = (self._pending_vector() >> EXT_FIRST_SOURCE) & EXT_BAND_MASK
        results["zero"].append((lane, shown, band))

    async def run(self) -> None:
        sb = self.sb
        assert self.cfg.reset_done.is_set(), "bring-up has not released reset"

        await self._mark("S1", "reset released, default images, +skip_fuse_sense; pins low")
        width = len(self.pin)
        pins0 = self._pins()
        vector0 = self._pending_vector()
        port0 = self._port_vector()

        await self._mark("S2", "precondition: lane count and all-low baseline")
        base_band = (vector0 >> EXT_FIRST_SOURCE) & EXT_BAND_MASK
        port_band0 = (port0 >> (EXT_FIRST_SOURCE - CORE_PORT_SOURCE_BASE)) & EXT_BAND_MASK
        self._log(
            f"CHK-SEP-EXTIRQ-WIDTH: precondition W={width} expected={EXT_LANES} "
            f"pins=0x{pins0:x} probes resolved pending_band=0x{base_band:x} "
            f"port_band=0x{port_band0:x} (baseline logged only)"
        )
        sb.expect_eq(
            "CHK-SEP-EXTIRQ-WIDTH precondition lane count and idle pins",
            (width, pins0),
            (EXT_LANES, 0),
            evidence="CHK-SEP-EXTIRQ-WIDTH",
        )

        results: dict[str, list] = {k: [] for k in ("rise", "onehot", "port", "fall", "zero")}
        visited = []
        for lane in range(EXT_LANES):
            await self._walk_lane(lane, results)
            visited.append(lane)
        width_after = len(self.pin)
        self._log(
            f"STEP S3-S6 walked {len(visited)} lanes once each, max lanes high together "
            f"{self.max_high}"
        )

        expected = {
            "rise": [(i, 0, 1) for i in range(EXT_LANES)],
            "onehot": [(i, 1, i) for i in range(EXT_LANES)],
            "port": [(i, 1, 1, 1, i) for i in range(EXT_LANES)],
            "fall": [(i, 1, 0) for i in range(EXT_LANES)],
            "zero": [(i, 1, 0) for i in range(EXT_LANES)],
        }
        texts = {
            "rise": "pending bit before the drive 0 and within the bound 1, (lane, before, after)",
            "onehot": "external pending band one-hot at the lane, (lane, bits set, top bit)",
            "port": "core port bit equals pending bit, band one-hot, (lane, port, pending, n, top)",
            "fall": "pending 1 then 0 within the bound after the lane returns low, (lane, 1, 0)",
            "zero": "external band all-zero after the lane showed 1, (lane, showed 1, band)",
        }
        for key, chk in (
            ("rise", "CHK-SEP-EXTIRQ-RISE"),
            ("onehot", "CHK-SEP-EXTIRQ-ONEHOT"),
            ("port", "CHK-SEP-EXTIRQ-CORE-PORT"),
            ("fall", "CHK-SEP-EXTIRQ-FALL"),
            ("zero", "CHK-SEP-EXTIRQ-ZERO"),
        ):
            bad = [(o, e) for o, e in zip(results[key], expected[key]) if o != e]
            self._log(
                f"{chk}: lanes={len(results[key])} mismatches={len(bad)} {texts[key]}"
                + (f" first={bad[0]}" if bad else "")
            )
            sb.expect_eq(f"{chk} {texts[key]}", results[key], expected[key], evidence=chk)

        await self._mark("S7", "walk accounting")
        self._log(
            f"CHK-SEP-EXTIRQ-WALK: visited={len(visited)} first={visited[0]} last={visited[-1]} "
            f"max_high={self.max_high} width={width_after}"
        )
        sb.expect_eq(
            "CHK-SEP-EXTIRQ-WALK lanes ascending once each, one lane high at a time, W stable",
            (visited, self.max_high, width_after, len(results["rise"]), len(results["fall"])),
            (list(range(EXT_LANES)), 1, EXT_LANES, EXT_LANES, EXT_LANES),
            evidence="CHK-SEP-EXTIRQ-WALK",
        )

        await ClockCycles(self.dut.clk_smu_i, STEP_CLOCK_GAP)
        self.step_ns["S8"] = self._now()
        self._log(f"STEP S8 @{self.step_ns['S8']:.3f}ns: PASS stamp")

        for kind, bound in (
            ("pending_rise", RISE_BOUND_CYCLES),
            ("pending_fall", FALL_BOUND_CYCLES),
        ):
            recs = [r for r in self.sites if r["kind"] == kind]
            self._log(
                f"TIMEOUT-PATH {kind}: sites={len(recs)} bound={bound} "
                f"max_used={max(r['used'] for r in recs)} "
                f"expired={sum(r['expired'] for r in recs)} last={recs[-1]['last']}"
            )
        expired = sum(rec["expired"] for rec in self.sites)
        kinds = dict(Counter(rec["kind"] for rec in self.sites))
        self._log(f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} kinds={kinds} expired={expired}")
        sb.expect_eq("expired TIMEOUT-PATH records", expired, 0, evidence="CHK-TIMEOUT-PATHS")
        sb.expect_eq(
            "bounded wait sites per kind", kinds, EXPECTED_SITE_KINDS, evidence="CHK-TIMEOUT-PATHS"
        )

        stamps = [self.step_ns[s] for s in STEPS]
        fence = "<".join(f"{s}@{t:.1f}" for s, t in zip(STEPS, stamps))
        gap_cycles = round((self.step_ns["S8"] - self.step_ns["S7"]) / self.cfg.smu_clk_period_ns)
        self._log(f"CHK-NONVAC: ordered sim-time fence {fence} s8_gap_cycles={gap_cycles}")
        sb.expect_eq(
            "CHK-NONVAC ordered sim-time fence",
            (
                all(b > a for a, b in zip(stamps, stamps[1:])),
                gap_cycles,
            ),
            (True, STEP_CLOCK_GAP),
            evidence="CHK-NONVAC",
        )
        self.done = True
