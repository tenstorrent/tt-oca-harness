# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense fidelity and sense-done timing of one SMC_EFUSE_MAP image after a cold reset.

Contract SMC_EFUSE_MAP_009, anchor smc_efuse_map_sense_image_test.
Scenarios EMAP-SENSE-IMAGE.S1-S3, EMAP-SENSE-DONE.S1/S2, EMAP-SHADOW-OUT.S1.
Sources: smu-smc.adoc (eFuse Interface), port_table.adoc (smc_fuse_sense_done_o, shadow_regs_o).

A sampler records (rst_primary, sense_done) on every clk_smc_i rising edge and captures
``efuse_shadow_probe_o`` on every 0-to-1 edge of sense done; every check is made over that
record. Every expected word is ``image.words[n]`` of the image file the run senses.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp

from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import EFUSE_MAP_WORDS, EfuseImage, word_addr
from .smc_reset_seq_base import SmcResetSeqBase

_MASK32 = 0xFFFF_FFFF
_SENSE_BOUND_CYCLES = 200_000
_RESET_BOUND_CYCLES = 2_000
_RELEASE_BOUND_CYCLES = 20_000
_WINDOW_EDGES = 2_000
_WINDOW_READS = 64
_HOLD_SAMPLES = 8
_WINDOW_BOUND_CYCLES = 20_000
_SIGNALS = ("rst_primary_smc_clk_no", "tb_fuse_sense_done")
_TERMS = {
    "S1": "IMAGE NAME",
    "S2": "FIRST DONE",
    "S3": "SENSE-IMAGE",
    "S4": "UNIQUE",
    "S5": "DONE-ONCE",
    "S6": "SHADOW-OUT",
}


class smc_efuse_map_sense_image_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Cold reset, first sense done, image compare, sense-done stability, shadow port."""

    def __init__(self, name: str = "smc_efuse_map_sense_image_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.kind = "default"
        self.seed = 1
        self.dispatch_reset = None
        self.access_floor = 0
        self._calls = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._rec: list[tuple[int, int]] = []
        self._probes: dict[int, int] = {}

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _last(self) -> str:
        if not self._rec:
            return "no sample"
        rst, done = self._rec[-1]
        return f"(edge={len(self._rec) - 1},rst={rst},done={done})"

    async def _sampler(self) -> None:
        clk = cocotb.top.clk_smc_i
        while True:
            await RisingEdge(clk)
            sample = tuple(self._sig(name) for name in _SIGNALS)
            if self._rec and self._rec[-1][1] == 0 and sample[1] == 1:
                self._probes[len(self._rec)] = self._sig("efuse_shadow_probe_o")
            self._rec.append(sample)

    # --- waits ----------------------------------------------------------
    async def _wait_find(self, name: str, bound: int, start: int, test) -> int:
        """First sampled edge at or after `start` where test(sample, edge) holds."""
        index = start
        waited = 0
        while True:
            while index < len(self._rec):
                if test(self._rec[index], index):
                    self._waits.append(
                        (name, f"{bound}smc_clk", f"hit={index},last={self._last()}")
                    )
                    return index
                index += 1
            if waited >= bound:
                raise AssertionError(
                    f"{name}: not satisfied within {bound} smc clocks; last={self._last()}"
                )
            waited += 1
            await RisingEdge(cocotb.top.clk_smc_i)
            await ReadOnly()
            await NextTimeStep()

    async def _wait_edges(self, name: str, bound: int, count: int) -> None:
        await self._wait_find(name, bound, count - 1, lambda _t, _i: True)

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; last={self._last()}") from exc
        self._waits.append(
            (
                label,
                f"{_SENSE_BOUND_CYCLES}smc_clk",
                f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')}",
            )
        )

    # --- compares -------------------------------------------------------
    def _compare_probe(self, label: str, probe: int) -> None:
        words = self.image.words
        for n in range(EFUSE_MAP_WORDS):
            got = (probe >> (32 * n)) & _MASK32
            assert got == words[n], (
                f"{label}: efuse_shadow_probe_o word {n} (0x{4 * n:03x}) is 0x{got:08x}, "
                f"image {self.image.path.name} 0x{words[n]:08x}"
            )

    async def _rd(self, label: str, word: int) -> int:
        self._calls += 1
        return await self.csr_read(label, word_addr(word), expected=self.image.words[word])

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        assert len(image.words) == EFUSE_MAP_WORDS
        distinct = len(set(image.words))
        if self.kind == "unique":
            assert distinct == EFUSE_MAP_WORDS, (
                f"{image.path.name}: {distinct}/{EFUSE_MAP_WORDS} pairwise distinct words"
            )
        await self._sense_wait("bringup_sense")
        sampler = cocotb.start_soon(self._sampler())
        try:
            await self._wait_edges("sampler_start", 16, 4)
            await self._scenario()
        finally:
            sampler.cancel()

    async def _scenario(self) -> None:
        image = self.image
        rec = self._rec
        unique = self.kind == "unique"
        distinct = len(set(image.words))
        assert rec[-1][1] == 1, f"sense not done before the cold reset: {self._last()}"

        # S1
        cocotb.log.info(
            "S1 image=%s kind=%s seed=%d locks=0x%016x",
            image.path.name,
            self.kind,
            self.seed,
            image.locks,
        )
        assert_edge = len(rec)
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        low = await self._wait_find(
            "reset_asserted", _RESET_BOUND_CYCLES, assert_edge, lambda t, _i: t[0] == 0
        )
        await self._wait_edges("reset_hold_samples", _RESET_BOUND_CYCLES, low + _HOLD_SAMPLES)
        held = rec[low : low + _HOLD_SAMPLES]
        assert all(t[0] == 0 and t[1] == 0 for t in held), (
            f"tb_fuse_sense_done or the primary reset moved under the held cold reset: {held}"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("cold release")
        rel = await self._wait_find(
            "reset_release", _RELEASE_BOUND_CYCLES, low, lambda t, _i: t[0] == 1
        )
        self._done("S1")

        # S2
        first = await self._wait_find(
            "first_sense_done", _SENSE_BOUND_CYCLES, rel, lambda t, _i: t[1] == 1
        )
        assert all(t[1] == 0 for t in rec[low:first]), (
            f"tb_fuse_sense_done read 1 between the cold reset (edge {low}) and edge {first}"
        )
        assert first in self._probes, f"no probe capture on the rise edge {first}"
        self._compare_probe("S2", self._probes[first])
        self._done("S2")
        self._chk(
            "CHK-EMAP-SENSE-FIRST-DONE",
            "tb_fuse_sense_done 0 on every sample from the cold reset (edge %d) to edge %d, "
            "read 1 on the first edge %d after the release at edge %d (%d clk_smc_i cycles); all "
            "%d words of efuse_shadow_probe_o captured on that edge equal %s",
            low,
            first - 1,
            first,
            rel,
            first - rel,
            EFUSE_MAP_WORDS,
            image.path.name,
        )
        await self._sense_wait("warm_domain_released")

        # S3
        skipped = [w for w in range(EFUSE_MAP_WORDS) if image.read_locked(w)]
        for word in range(EFUSE_MAP_WORDS):
            if word not in skipped:
                await self._rd(f"S3_{word}", word)
        assert 0 not in skipped and EFUSE_MAP_WORDS - 1 not in skipped, (
            f"word 0 or word 255 is read-locked: {skipped}"
        )
        read = EFUSE_MAP_WORDS - len(skipped)
        self._compare_probe("S3", self._sig("efuse_shadow_probe_o"))
        self._done("S3")
        if skipped:
            locked_note = (
                f"{len(skipped)} read-locked words {skipped} skipped (LOCKS 0x{image.locks:x}), "
                f"2-state: {image.words.count(0)} zero words"
            )
        else:
            locked_note = (
                f"LOCKS 0x{image.locks:x} (write-lock bits only, no read-lock bit), LOCKS words "
                f"0x{image.words[0]:08x}/0x{image.words[1]:08x} included, none skipped"
            )
        if not unique:
            chk_id = (
                "CHK-EMAP-SENSE-DEFAULT" if self.kind == "default" else "CHK-EMAP-SENSE-PATTERNS"
            )
            self._chk(
                chk_id,
                "image %s (%s, seed %d): %d SEP_IN reads equal the image words, word 0 0x%08x and "
                "word 255 0x%08x included; %s; all %d efuse_shadow_probe_o words equal the image "
                "again after the sweep",
                image.path.name,
                self.kind,
                self.seed,
                read,
                image.words[0],
                image.words[EFUSE_MAP_WORDS - 1],
                locked_note,
                EFUSE_MAP_WORDS,
            )

        # S4
        if unique:
            await self._wait_edges("unique_probe_edge", _RESET_BOUND_CYCLES, len(rec) + 1)
            probe = self._sig("efuse_shadow_probe_o")
            for n in range(EFUSE_MAP_WORDS):
                got = (probe >> (32 * n)) & _MASK32
                assert got == image.words[n], (
                    f"S4: probe word {n} is 0x{got:08x}, image word {n} is 0x{image.words[n]:08x}"
                )
            last = (probe >> (32 * 255)) & _MASK32
            assert last == image.words[255], f"S4: probe word 255 0x{last:08x}"
            self._done("S4")
            self._chk(
                "CHK-EMAP-SENSE-UNIQUE",
                "image %s: distinct=%d/%d asserted before sensing, LOCKS words 0x%08x/0x%08x "
                "included; probe word i equals image word i for all 256 i, word 255 0x%08x",
                image.path.name,
                distinct,
                EFUSE_MAP_WORDS,
                image.words[0],
                image.words[1],
                last,
            )

        # S5
        unlocked = [w for w in range(EFUSE_MAP_WORDS) if w not in skipped]
        picks = [unlocked[k * len(unlocked) // _WINDOW_READS] for k in range(_WINDOW_READS)]
        start = len(rec)
        for k, word in enumerate(picks):
            await self._rd(f"S5_{k}_{word}", word)
        last_issue = len(rec) - 1
        assert last_issue < start + _WINDOW_EDGES, (
            f"the {_WINDOW_READS} reads ran past the {_WINDOW_EDGES}-edge window: edges "
            f"{start}..{last_issue}"
        )
        await self._wait_edges("window_edges", _WINDOW_BOUND_CYCLES, start + _WINDOW_EDGES)
        window = rec[start : start + _WINDOW_EDGES]
        assert len(window) == _WINDOW_EDGES and all(t[1] == 1 for t in window), (
            f"tb_fuse_sense_done dropped inside edges {start}..{start + _WINDOW_EDGES - 1}"
        )
        assert all(t[1] == 1 for t in rec[first:]), (
            f"tb_fuse_sense_done dropped between the first rise (edge {first}) and edge {len(rec)}"
        )
        rises = [i for i in range(rel + 1, len(rec)) if rec[i][1] == 1 and rec[i - 1][1] == 0]
        assert rises == [first], (
            f"0-to-1 transitions of tb_fuse_sense_done since the release: {rises}"
        )
        self._done("S5")
        self._chk(
            "CHK-EMAP-SENSE-DONE-ONCE",
            "tb_fuse_sense_done read 1 on all %d samples of edges %d..%d with %d SEP_IN reads of "
            "unlocked words issued at edges %d..%d, and on every sample from the first rise (edge "
            "%d) to edge %d; exactly one 0-to-1 transition since the release (edge %d)",
            _WINDOW_EDGES,
            start,
            start + _WINDOW_EDGES - 1,
            _WINDOW_READS,
            start,
            last_issue,
            first,
            len(rec) - 1,
            first,
        )

        # S6
        await self._wait_edges("shadow_port_edge", _RESET_BOUND_CYCLES, len(rec) + 1)
        port = self._sig("shadow_regs")
        expected = sum(image.words[n] << (32 * n) for n in range(EFUSE_MAP_WORDS))
        assert self.kind == "default" or not skipped, f"generated image read-locks {skipped}"
        compared = [n for n in range(EFUSE_MAP_WORDS) if n not in skipped]
        for n in compared:
            got = (port >> (32 * n)) & _MASK32
            assert got == image.words[n], (
                f"S6: shadow_regs port word {n} is 0x{got:08x}, image 0x{image.words[n]:08x}"
            )
        if skipped:
            hidden = ", ".join(f"{n}=0x{(port >> (32 * n)) & _MASK32:08x}" for n in skipped)
            observed = (
                f"{len(compared)} words not read-locked equal the image; port value of the "
                f"{len(skipped)} read-locked words (observation only) {hidden}"
            )
        else:
            assert port == expected, "S6: shadow_regs differs from the packed image"
            observed = f"all {EFUSE_MAP_WORDS} port words equal the image (port == packed image)"
        self._done("S6")
        self._chk(
            "CHK-EMAP-SHADOW-OUT-SENSED",
            "shadow_regs read as one %d-bit integer, word n at bits [32n+31:32n], image %s with "
            "LOCKS 0x%x: %s (port semantics SF-018 open)",
            32 * EFUSE_MAP_WORDS,
            image.path.name,
            image.locks,
            observed,
        )
        self.access_floor = self._calls
        self._finish()

    def _finish(self) -> None:
        steps = ["S1", "S2", "S3"] + (["S4"] if self.kind == "unique" else []) + ["S5", "S6"]
        assert [s for s, _t in self._stamps] == steps, (
            f"steps completed {[s for s, _t in self._stamps]}, expected {steps}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        sense = {
            "default": "CHK-EMAP-SENSE-DEFAULT",
            "unique": "CHK-EMAP-SENSE-UNIQUE",
        }.get(self.kind, "CHK-EMAP-SENSE-PATTERNS")
        order = [
            "CHK-EMAP-SENSE-FIRST-DONE",
            sense,
            "CHK-EMAP-SENSE-DONE-ONCE",
            "CHK-EMAP-SHADOW-OUT-SENSED",
        ]
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == order, f"checker lines printed {printed}, expected {order}"
        chk_step = dict(zip(order, ("S2", "S4" if self.kind == "unique" else "S3", "S5", "S6")))
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", chk_step[ident]) in self._events[:index], (
                    f"{ident} printed before step {chk_step[ident]} completed"
                )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s ps",
            " < ".join(_TERMS[s] for s in steps),
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        bounds = list(self._waits) + [
            (
                "sep_in_read",
                f"{self.cfg.axi_timeout_ns}ns",
                f"{self._calls} reads completed, last={self._last()}",
            )
        ]
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(bounds),
            " ".join(
                f"{name}={bound}(fails with AssertionError on expiry) last={state}"
                for name, bound, state in bounds
            ),
        )
