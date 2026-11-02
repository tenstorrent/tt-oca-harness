# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP SRAM and ICCM are cleared before the ROM loads external content.

rom.adoc, Cold Boot Environment Setup and the SEP memory map:

* SEP-ROM-CPU-100: "The ROM shall clear SEP SRAM and ICCM before loading any external content,
  so that no stale or attacker-resident data can survive into the validated-boot environment."
* SEP SRAM: "Destination for the manifest and payload"

CPU-100 is covered in part, on the default SMC-SRAM manifest path only. The load of external
content starts at the first PR-SMC read beat inside [MANIFEST_SRC, MANIFEST_SRC + OCA_BODY),
the first read of the manifest from its source; the status-ring and SMC scratch reads are not
content that the ROM loads into SEP SRAM or ICCM. Before that beat every byte of SEP SRAM must
take a zero write on the SRAM request port, every ICCM bank row a zero write on the ICCM macro
port, and the seven SRAM words that tb_top probes must read zero. A CTRL proves each port map
against an independent view: the SRAM array probes, and the BL1 instructions that retire from
ICCM. SRAM residue comes from +sep_sram_hex; a CTRL reads back only the seven probed words
before the ROM runs, and the other planted words are not readable. ICCM residue is planted with
the TCM bit-flip hook while rst_ni is low but is not graded: the stored words are not readable
from cocotb, and the ICCM CHK grades the clear writes only. The SPI boot path is not graded.
The X checks of the taps are inert on 2-state Verilator.
"""

from __future__ import annotations

import re
from bisect import bisect_left, bisect_right
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_fabric_tap import SepFabricTap
from env.sep_rv32_trace_decode import INSN_MRET
from env.sep_seeded_rng import SepSeededRng
from env.sep_tcm_flip import DATA_BITS, ICCM_BASE, ICCM_BYTES, in_iccm, tcm_flip
from rom_fw.sep_rom_observe_base import sep_rom_observe_base
from sep_reg_meta import sym

SRAM_BYTES = sym("SEP_SRAM_MEM_SIZE")
_ICCM_END = ICCM_BASE + ICCM_BYTES
# PR-SRAM carries 64-bit data with one strobe per byte lane.
_LANES = 8
_WORD64 = (1 << 64) - 1
# PR-TCM ICCM geometry: 4 banks, bank = byte offset bits 3:2, row = byte offset bits 17:4.
_IBANKS = 4
_IAW = 14
# 64-bit SRAM array words behind sram_word0_probe_o and sram_payload_probe_o.
_PROBE_WORDS = (0, *range(0x200, 0x206))
# Clocks after an SRAM write beat in which the array probes are sampled.
_SNAP_CLKS = 3
_ICCM_FLIPS = 4
_MIN_SRAM_PROBES = 8
_MIN_ICCM_PROBES = 16
_SRC_MARKER = "MANIFEST_SRC="
_BODY_MARKER = "OCA_BODY="


def _islot(addr: int) -> tuple[int, int]:
    off = addr - ICCM_BASE
    return (off >> 2) & (_IBANKS - 1), off >> 4


def _iaddr(slot: tuple[int, int]) -> int:
    bank, row = slot
    return ICCM_BASE + (row << 4) + (bank << 2)


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _val(sig) -> int | None:
    v = sig.value
    return int(v) if v.is_resolvable else None


def _hi(sig) -> bool:
    return _val(sig) == 1


def read_residue(path: str | Path) -> dict[int, int]:
    """64-bit word index -> value of a $readmemh file with @ addresses and // comments."""
    words: dict[int, int] = {}
    idx = 0
    for line in Path(path).read_text().splitlines():
        for tok in line.split("//")[0].split():
            if tok.startswith("@"):
                idx = int(tok[1:], 16)
            else:
                words[idx] = int(tok, 16)
                idx += 1
    return words


def probe_words(word0: int | None, payload: int | None) -> list[int] | None:
    """The array words behind the probes, in _PROBE_WORDS order; None if any bit is unknown."""
    if word0 is None or payload is None:
        return None
    return [word0] + [(payload >> (64 * i)) & _WORD64 for i in range(len(_PROBE_WORDS) - 1)]


def lanes_match(strb: int, wdata: int, word: int) -> bool:
    """True when every strobed byte of wdata is in word; False when no lane is strobed."""
    lanes = [i for i in range(_LANES) if strb >> i & 1]
    return bool(lanes) and all((wdata >> 8 * i) & 0xFF == (word >> 8 * i) & 0xFF for i in lanes)


def zero_bytes(beats, t_end: int) -> bytearray:
    """Per SRAM byte offset, 1 when a write beat before t_end wrote zero to it."""
    covered = bytearray(SRAM_BYTES)
    for b in beats:
        if b.t_ps >= t_end:
            break
        if b.addr is None or b.strb is None or b.wdata is None:
            continue
        base = b.addr & ~(_LANES - 1)
        for i in range(_LANES):
            if b.strb >> i & 1 and (b.wdata >> 8 * i) & 0xFF == 0 and base + i < SRAM_BYTES:
                covered[base + i] = 1
    return covered


def missing_runs(covered: bytearray, limit: int = 4) -> list[str]:
    """The first byte-offset runs that no zero write covered, as [lo,hi) strings."""
    runs: list[str] = []
    lo = None
    for off in range(len(covered) + 1):
        hole = off < len(covered) and not covered[off]
        if hole and lo is None:
            lo = off
        elif not hole and lo is not None:
            runs.append(f"[0x{lo:05x},0x{off:05x})")
            lo = None
            if len(runs) == limit:
                break
    return runs


def _console_hex(obs, marker: str) -> int | None:
    pat = re.compile(re.escape(marker) + r"(0x[0-9a-fA-F]+)")
    for _, line in obs.console:
        m = pat.search(line)
        if m:
            return int(m.group(1), 16)
    return None


@pyuvm.test()
class sep_rom_sram_iccm_clear_test(sep_rom_observe_base):
    required_evidence = (
        "CHK-SRAM-CLEARED-BEFORE-LOAD",
        "CHK-SRAM-RESIDUE-CLEARED-AT-LOAD",
        "CHK-ICCM-CLEARED-BEFORE-LOAD",
    )

    def _draw_flips(self) -> dict[int, int]:
        """ICCM residue: byte address -> data-bit mask, in the half of ICCM above any BL1."""
        rng = SepSeededRng(self.random_seed())
        lo = ICCM_BASE + ICCM_BYTES // 2
        flips: dict[int, int] = {}
        while len(flips) < _ICCM_FLIPS:
            addr = lo + 4 * rng.randrange((_ICCM_END - lo) // 4)
            flips.setdefault(addr, rng.getrandbits(DATA_BITS) or 1)
        return flips

    async def run_scenario(self) -> None:
        path = cocotb.plusargs.get("sep_sram_hex")
        if not path:
            raise AssertionError(
                "sep_rom_sram_iccm_clear_test needs +sep_sram_hex=<residue hex>; "
                "add it to the testlist entry"
            )
        self.residue = read_residue(path)
        self.flips = self._draw_flips()
        self.flip_rst_low: list[bool] = []
        self.flip_end_ps: int | None = None
        # time -> (sram_word0_probe_o, sram_payload_probe_o)
        self.snaps: dict[int, tuple[int | None, int | None]] = {}
        self.first_snap: tuple[int, int | None, int | None] | None = None
        self.tap_start_ps = int(get_sim_time("ps"))
        self.sram = SepFabricTap("PR-SRAM").start()
        self.tcm = SepFabricTap("PR-TCM").start()
        self.smc = SepFabricTap("PR-SMC").start()
        self.m_sram, self.m_tcm, self.m_smc = self.sram.mark(), self.tcm.mark(), self.smc.mark()
        await super().run_scenario()

    async def stimulus(self, obs) -> None:
        # The clock starts with rst_ni low, so the flips land before reset release.
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        self.flip_rst_low.append(self.rd(dut.rst_ni) == 0)
        for addr, mask in self.flips.items():
            await tcm_flip(dut, addr, mask)
        self.flip_rst_low.append(self.rd(dut.rst_ni) == 0)
        self.flip_end_ps = int(get_sim_time("ps"))
        await self._snapshots(obs)

    async def _snapshots(self, obs) -> None:
        """Sample the SRAM array probes at the first retirement, after each SRAM write beat
        and at each PR-SMC read beat, until the stop condition cancels the stimulus."""
        dut = cocotb.top
        left = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            t = int(get_sim_time("ps"))
            first = self.first_snap is None and obs.retired > 0
            ar = _hi(dut.pr_smc_arvalid_o) and _hi(dut.pr_smc_arready_o)
            if left or ar or first:
                snap = (_val(dut.sram_word0_probe_o), _val(dut.sram_payload_probe_o))
                self.snaps[t] = snap
                if first:
                    self.first_snap = (t, *snap)
            write = _hi(dut.pr_sram_req_o) and _hi(dut.pr_sram_we_o)
            left = _SNAP_CLKS if write else max(left - 1, 0)

    async def before_grade(self, obs) -> None:
        self.tap_stop_ps = int(get_sim_time("ps"))
        await self.sram.stop()
        await self.tcm.stop()
        await self.smc.stop()

    def _sram_map(self, writes, word_of, clk_ps: int) -> tuple[int, int]:
        """(checked, matched): write beats that land on a probed word under word_of, and those
        whose strobed bytes a probe sample within _SNAP_CLKS clocks shows."""
        times = sorted(self.snaps)
        index = {w: i for i, w in enumerate(_PROBE_WORDS)}
        checked = matched = 0
        for b in writes:
            if b.has_unknown():
                continue
            slot = index.get(word_of(b.addr))
            if slot is None or not b.strb:
                continue
            checked += 1
            lo = bisect_right(times, b.t_ps)
            hi = bisect_right(times, b.t_ps + _SNAP_CLKS * clk_ps)
            for t in times[lo:hi]:
                words = probe_words(*self.snaps[t])
                if words is not None and lanes_match(b.strb, b.wdata, words[slot]):
                    matched += 1
                    break
        return checked, matched

    def grade(self, obs, chk) -> None:
        clk_ps = int(round(self.cfg.sys_clk_period_ns * 1000))
        mret = obs.pre_mret[-1] if obs.pre_mret else None
        end_t = mret.t_ps if mret is not None and mret.insn == INSN_MRET else None
        bl1_pc = obs.post_mret.pc if obs.post_mret else None
        live = end_t is not None and bl1_pc is not None and obs.verdict_pass() is True
        chk.ctrl(
            "HANDOFF",
            live,
            handoff_ps=end_t if end_t is not None else -1,
            bl1_pc=_hex(bl1_pc),
            verdict=obs.verdict_pass(),
        )

        # The external load starts at the first read of the manifest from the SMC.
        src = _console_hex(obs, _SRC_MARKER)
        body = _console_hex(obs, _BODY_MARKER)
        ars = self.smc.since(self.m_smc, "ar")
        hit = next(
            (
                b
                for b in ars
                if src is not None
                and body
                and b.addr is not None
                and src <= (b.addr & 0xFFFF_FFFF) < src + body
            ),
            None,
        )
        t_ext = hit.t_ps if hit is not None else None
        req = self.sram.since(self.m_sram, "req")
        writes = [b for b in req if b.we and (end_t is None or b.t_ps <= end_t)]
        landed = next(
            (
                b
                for b in writes
                if t_ext is not None and b.t_ps > t_ext and b.addr is not None and b.addr < _LANES
            ),
            None,
        )
        ext_ok = live and hit is not None and t_ext < end_t and landed is not None
        chk.ctrl(
            "EXTERNAL-LOAD",
            ext_ok,
            src=_hex(src),
            body=_hex(body),
            ext_ps=t_ext if t_ext is not None else -1,
            ext_addr=_hex(hit.addr if hit is not None else None),
            smc_ar=len(ars),
            body_write_ps=landed.t_ps if landed is not None else -1,
            src_line_ps=obs.line_t(_SRC_MARKER) or -1,
        )

        first_t = obs.first[0].t_ps if obs.first else None
        planted = [self.residue.get(w) for w in _PROBE_WORDS]
        fs = self.first_snap
        first_words = probe_words(fs[1], fs[2]) if fs is not None else None
        residue_ok = (
            ext_ok and fs is not None and all(planted) and first_words == planted and fs[0] < t_ext
        )
        chk.ctrl(
            "SRAM-RESIDUE",
            residue_ok,
            planted_words=len(self.residue),
            read_ps=fs[0] if fs is not None else -1,
            first_retire_ps=first_t if first_t is not None else -1,
            mismatched=[
                f"{w:#x}"
                for w, p, r in zip(_PROBE_WORDS, planted, first_words or [None] * len(planted))
                if p is None or p != r
            ],
        )
        chk.ctrl(
            "ICCM-RESIDUE",
            self.flip_rst_low == [True, True]
            and self.flip_end_ps is not None
            and first_t is not None
            and self.flip_end_ps < first_t,
            flips=len(self.flips),
            rst_low=self.flip_rst_low,
            flip_end_ps=self.flip_end_ps if self.flip_end_ps is not None else -1,
            first_retire_ps=first_t if first_t is not None else -1,
            planted=[f"{_hex(a)}^{_hex(m)}" for a, m in self.flips.items()],
        )

        unknown = sum(b.has_unknown() for b in req)
        outside = sum(b.addr is not None and b.addr >= SRAM_BYTES for b in req)
        sram_live = (
            ext_ok
            and first_t is not None
            and self.tap_start_ps <= first_t
            and self.tap_stop_ps >= end_t
            and unknown == 0
            and outside == 0
        )
        chk.ctrl(
            "SRAM-LIVE",
            sram_live,
            tap_ps=f"{self.tap_start_ps}..{self.tap_stop_ps}",
            req=len(req),
            writes=len(writes),
            unknown=unknown,
            outside=outside,
            snaps=len(self.snaps),
        )

        # A byte-offset address lands each write on the probed array word; a word index does not.
        checked, matched = self._sram_map(writes, lambda a: a >> 3, clk_ps)
        alt_checked, alt_matched = self._sram_map(writes, lambda a: a, clk_ps)
        sram_map = (
            checked >= _MIN_SRAM_PROBES
            and matched == checked
            and alt_checked > 0
            and alt_matched < alt_checked
        )
        chk.ctrl(
            "SRAM-MAP",
            sram_map,
            unit="byte_offset",
            checked=checked,
            matched=matched,
            word_index_checked=alt_checked,
            word_index_matched=alt_matched,
            window_clk=_SNAP_CLKS,
        )

        ready = sram_live and sram_map
        covered = zero_bytes(writes, t_ext) if t_ext is not None else bytearray(SRAM_BYTES)
        zeroed = sum(covered)
        chk.ok(
            "SRAM-CLEARED-BEFORE-LOAD",
            ready and zeroed == SRAM_BYTES,
            zeroed_bytes=zeroed,
            need=SRAM_BYTES,
            writes_before_load=sum(t_ext is not None and b.t_ps < t_ext for b in writes),
            first_missing=missing_runs(covered),
        )
        at = self.snaps.get(t_ext) if t_ext is not None else None
        at_words = probe_words(*at) if at is not None else None
        chk.ok(
            "SRAM-RESIDUE-CLEARED-AT-LOAD",
            ready and residue_ok and at_words is not None and not any(at_words),
            read_ps=t_ext if at is not None else -1,
            nonzero=sum(bool(w) for w in at_words or []),
            still_planted=sum(w == p for w, p in zip(at_words or [], planted)),
            words=[f"{w:#x}" for w in _PROBE_WORDS],
        )

        # ICCM macro port: write beats per (bank, row), in time order.
        iw: dict[tuple[int, int], tuple[list[int], list[int]]] = {}
        zero_before: set[tuple[int, int]] = set()
        iunknown = before = 0
        ibeats = self.tcm.since(self.m_tcm, "iccm")
        for b in ibeats:
            for bank in range(_IBANKS):
                en = b.lane("clken", bank, 1)
                if not en:
                    iunknown += en is None
                    continue
                we = b.lane("wren", bank, 1)
                row = b.lane("addr", bank, _IAW)
                data = b.lane("wdata", bank, DATA_BITS)
                if we is None or row is None or (we and data is None):
                    iunknown += 1
                    continue
                if not we:
                    continue
                slot = (bank, row)
                times, data_words = iw.setdefault(slot, ([], []))
                times.append(b.t_ps)
                data_words.append(data)
                if t_ext is not None and b.t_ps < t_ext:
                    before += 1
                    if data == 0:
                        zero_before.add(slot)
        sample = next((b for b in ibeats if b.raw), None)
        geometry = (
            sample is not None
            and len(sample.raw["clken"]) == _IBANKS
            and len(sample.raw["addr"]) == _IBANKS * _IAW
            and len(sample.raw["wdata"]) == _IBANKS * DATA_BITS
            and ICCM_BYTES == _IBANKS * (1 << _IAW) * 4
        )
        iccm_live = (
            ext_ok
            and geometry
            and first_t is not None
            and self.tap_start_ps <= first_t
            and self.tap_stop_ps >= end_t
            and bool(iw)
            and iunknown == 0
        )
        chk.ctrl(
            "ICCM-LIVE",
            iccm_live,
            geometry=geometry,
            beats=len(ibeats),
            written_rows=len(iw),
            unknown=iunknown,
        )

        # A BL1 instruction that retires from ICCM was fetched from the row its pc maps to.
        probes = [
            r
            for r in obs.retires
            if end_t is not None
            and r.t_ps > end_t
            and not (r.exc or r.interrupt)
            and in_iccm(r.pc)
            and r.pc % 4 == 0
            and r.insn & 3 == 3
        ]

        def score(slot_of) -> int:
            hits = 0
            for r in probes:
                times, data_words = iw.get(slot_of(r.pc), ((), ()))
                i = bisect_left(times, r.t_ps)
                hits += i > 0 and data_words[i - 1] == r.insn
            return hits

        real = score(_islot)
        rotated = score(lambda a: ((_islot(a)[0] + 1) % _IBANKS, _islot(a)[1]))
        word = score(lambda a: (_islot(a)[0], ((a - ICCM_BASE) >> 2) & ((1 << _IAW) - 1)))
        iccm_map = (
            len(probes) >= _MIN_ICCM_PROBES
            and real == len(probes)
            and rotated < len(probes)
            and word < len(probes)
        )
        chk.ctrl(
            "ICCM-MAP",
            iccm_map,
            probes=len(probes),
            matched=real,
            bank_rotated=rotated,
            word_index=word,
        )

        need = [_islot(a) for a in range(ICCM_BASE, _ICCM_END, 4)]
        missing = [s for s in need if s not in zero_before]
        chk.ok(
            "ICCM-CLEARED-BEFORE-LOAD",
            iccm_live and iccm_map and t_ext is not None and not missing,
            zeroed_rows=len(need) - len(missing),
            need=len(need),
            writes_before_load=before,
            first_missing=[_hex(_iaddr(s)) for s in missing[:4]],
        )
        chk.obs(
            "CLEAR-STAGES",
            lines=[f"{line}@{t}" for t, line in obs.console if "_CLR" in line or "SCRUB" in line],
        )
