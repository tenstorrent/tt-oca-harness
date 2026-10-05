# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Interleaved ABR reads and writes from both masters each act on the address they name.

no_cpu / +skip_fuse_sense.

``hw/sys/sep/doc/adams_bridge.adoc`` states that any number of reads and writes
may be outstanding on the aperture from any mix of masters, and that they are
performed one at a time, each returning the value of the address it names.
This leaf drives that: s_axi and m_axi each run a seeded stream of reads and
writes with several outstanding, at the same time, with both response channels
throttled from the master side.

Ownership keeps the expectation exact without assuming any order between the
masters: every read-write register is written by one master only, and that
master issues all its writes on one AWID, so its writes to a register land in
issue order. A read may still overlap writes to the register it names, so it is
graded against a window: the value of the last write whose response came back
before the read was issued, or of any later write issued before the read
returned. A read of an identity word must return that word exactly. The RDL
and the SEP documents give no identity value, so ``CHK-ABR-ID-REF`` first reads
each word alone and that capture is the reference. The identity words read are
those whose captured value no other of them holds, so a response swapped
between two of them is a mismatch. A 64-bit access is graded per word.
Partial-word writes are mixed in and must answer SLVERR without
moving their register.

After both streams drain, every read-write register must hold the last value
its owner wrote. Registers are restored to their entry values at the end.

RANDCFG: the op mix, addresses, data, outstanding depths and throttle patterns
all come from the run seed. The identity addresses a stream picks from are the
pool built from the capture, so the configuration is built after it.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_abr_bus_seq import (
    ERROR_COUNT,
    ERROR_INTR_EN,
    GLOBAL_INTR_EN,
    ID_WIDTH,
    IDENTITY,
    IDENTITY_PAIRS,
    IDENTITY_WORDS,
    NOTIF_COUNT,
    NOTIF_INTR_EN,
    RESP_OKAY,
    RESP_SLVERR,
    RW,
    RW_WORDS,
    AbrAccess,
    AbrBusWatch,
    AbrWord,
    SepAbrBus,
    lane_value,
)

OPS_PER_MASTER = 96

# Each read-write register is written by one master.
OWNED: dict[str, tuple[AbrWord, ...]] = {
    "s_axi": (GLOBAL_INTR_EN, ERROR_INTR_EN, ERROR_COUNT),
    "m_axi": (NOTIF_INTR_EN, NOTIF_COUNT),
}
# The one 8-byte granule with a read-write register in each half; s_axi owns
# both, so its 64-bit writes there are ordered with its 32-bit ones.
PAIR = (GLOBAL_INTR_EN, ERROR_INTR_EN)


def _distinct_goldens(words: tuple[AbrWord, ...]) -> tuple[AbrWord, ...]:
    """``words`` in order, without any word whose value an earlier one holds."""
    seen: set[int | None] = set()
    kept = []
    for w in words:
        if w.value not in seen:
            seen.add(w.value)
            kept.append(w)
    return tuple(kept)


def identity_pool() -> tuple[tuple[AbrWord, ...], tuple[int, ...]]:
    """The identity words the streams read, and the granules of the 64-bit reads.

    Built from the captured reference, so call it after ``capture_identity``.
    Two identity words can hold the same value, and a response swapped between
    them would grade as correct, so each value appears once in the pool. The
    64-bit reads use the granules whose two words are both in the pool.
    """
    pool = _distinct_goldens(IDENTITY_WORDS)
    values = [w.value for w in pool]
    assert None not in values, "identity pool built before capture_identity() passed"
    assert len(set(values)) == len(values), "identity pool values unique"
    addrs = {w.addr for w in pool}
    granules = tuple(lo.addr for lo, hi in IDENTITY_PAIRS if lo.addr in addrs and hi.addr in addrs)
    # CHK-ABR-ID-REF requires the two words of a granule to differ, so the
    # first granule is always whole in the pool.
    assert granules, "at least one identity granule for the 64-bit reads"
    return pool, granules


# Op mix, as cumulative weights out of 100.
_MIX = (
    ("wr32", 30),
    ("wr64", 36),  # s_axi only; m_axi rolls it as wr32
    ("wr_partial", 42),
    ("rd32", 82),
    ("rd64", 100),
)

# Share of reads that name a read-write register rather than an identity word.
RW_READ_PCT = 60

# Fraction, out of 16, of cycles a throttled response channel holds READY low.
THROTTLE_16THS = 6


def _selftest() -> None:
    owned = [w.addr for regs in OWNED.values() for w in regs]
    assert sorted(owned) == sorted(RW), "every read-write register has exactly one owner"
    assert all(w in OWNED["s_axi"] for w in PAIR)
    assert PAIR[1].addr == PAIR[0].addr + 4 and PAIR[0].addr % 8 == 0


_selftest()


@dataclass
class _Write:
    t_issue: int
    t_done: int
    value: int


def _throttle(rng: SepSeededRng):
    """READY pause pattern: True holds the channel's READY low for a cycle."""
    while True:
        yield rng.randrange(16) < THROTTLE_16THS


class SepAbrConcurrentRwCfg:
    """RANDCFG: both op streams, their depths and IDs, and the throttle seeds.

    ``pool`` and ``granules`` are the identity reads' targets from
    ``identity_pool``.
    """

    def __init__(self, seed: int, pool: tuple[AbrWord, ...], granules: tuple[int, ...]) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.pool = pool
        self.granules = granules
        self.depth = {bus: rng.randrange(3, 7) for bus in OWNED}
        self.awid = {bus: rng.randrange(1 << ID_WIDTH[bus]) for bus in OWNED}
        self.initial = {w.addr: rng.getrandbits(32) & w.mask for w in RW_WORDS}
        self.throttle_seed = {bus: rng.getrandbits(32) for bus in OWNED}
        self.ops = {bus: self._stream(rng, bus) for bus in OWNED}

    def _stream(self, rng: SepSeededRng, bus: str) -> list[AbrAccess]:
        ops: list[AbrAccess] = []
        n_ids = 1 << ID_WIDTH[bus]
        rw = [w.addr for w in RW_WORDS]
        identity = [w.addr for w in self.pool]
        identity_granules = list(self.granules)
        for k in range(OPS_PER_MASTER):
            roll = rng.randrange(100)
            kind = next(name for name, edge in _MIX if roll < edge)
            if kind == "wr64" and bus != "s_axi":
                kind = "wr32"
            rid = k % n_ids
            if kind == "wr32":
                reg = rng.choice(list(OWNED[bus]))
                ops.append(AbrAccess(bus, "wr", reg.addr, wdata=rng.getrandbits(32), tag="wr32"))
            elif kind == "wr64":
                ops.append(
                    AbrAccess(bus, "wr", PAIR[0].addr, 8, 3, wdata=rng.getrandbits(64), tag="wr64")
                )
            elif kind == "wr_partial":
                reg = rng.choice(list(OWNED[bus]))
                off = rng.randrange(4)
                ops.append(
                    AbrAccess(
                        bus,
                        "wr",
                        reg.addr + off,
                        1,
                        0,
                        wdata=rng.getrandbits(8),
                        tag="wr_partial",
                    )
                )
            elif kind == "rd32":
                pool = rw if rng.randrange(100) < RW_READ_PCT else identity
                ops.append(AbrAccess(bus, "rd", rng.choice(pool), axi_id=rid, tag="rd32"))
            else:
                on_rw = rng.randrange(100) < RW_READ_PCT
                granule = PAIR[0].addr if on_rw else rng.choice(identity_granules)
                ops.append(AbrAccess(bus, "rd", granule, 8, 3, axi_id=rid, tag="rd64"))
        for acc in ops:
            if acc.op == "wr":
                acc.axi_id = self.awid[bus]
        return ops

    def summary(self) -> str:
        mix = {
            bus: {t: sum(a.tag == t for a in ops) for t, _e in _MIX}
            for bus, ops in self.ops.items()
        }
        return f"seed={self.seed} depth={self.depth} awid={self.awid} mix={mix}"


@pyuvm.test()
class sep_abr_concurrent_rw_test(sep_base_test):
    """Interleaved ABR reads from both masters match the windowed expectation, and writes land."""

    required_evidence = (
        "CHK-ABR-ID-REF",
        "CHK-ABR-CRW-WRITE-RESP",
        "CHK-ABR-CRW-READ",
        "CHK-ABR-CRW-STRESS",
        "CHK-ABR-CRW-FINAL",
        "CHK-ABR-CRW-RESTORE",
    )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        abr = SepAbrBus(self)
        await abr.capture_identity("s_axi")
        pool, granules = identity_pool()
        cfg = SepAbrConcurrentRwCfg(self.random_seed(), pool, granules)
        self.logger.info(
            "abr concurrent rw: %s identity-pool=%s",
            cfg.summary(),
            ",".join(w.name for w in pool),
        )
        await abr.open_m_axi_window(write=True)

        entry = {}
        for reg in RW_WORDS:
            acc = await abr.read("s_axi", reg.addr)
            assert acc.resp == RESP_OKAY, f"entry read of {reg.name} returned {acc.resp_name}"
            entry[reg.addr] = acc.data
        for reg in RW_WORDS:
            await self._set(abr, reg, cfg.initial[reg.addr])

        watch = AbrBusWatch(tuple(OWNED))
        for bus in OWNED:
            chans = abr.driver(bus).channels
            chans["r_ready_delay"].set_pause_generator(
                _throttle(SepSeededRng(cfg.throttle_seed[bus]))
            )
            chans["b_ready_delay"].set_pause_generator(
                _throttle(SepSeededRng(cfg.throttle_seed[bus] ^ 0x5A5A_5A5A))
            )
        watch.start()
        try:
            tasks = [cocotb.start_soon(abr.stream(cfg.ops[bus], cfg.depth[bus])) for bus in OWNED]
            for t in tasks:
                await t
        finally:
            watch.stop()
            for bus in OWNED:
                chans = abr.driver(bus).channels
                for name in ("r_ready_delay", "b_ready_delay"):
                    chans[name].clear_pause_generator()
                    chans[name].pause = False

        every = [a for ops in cfg.ops.values() for a in ops]
        stuck = [a for a in every if a.timed_out]
        assert not stuck, (
            f"{len(stuck)} of {len(every)} accesses did not complete; first: {stuck[0].describe()}"
        )
        for a in every:
            self.logger.info("ABR-CRW %s %s t=[%d,%d]ps", a.tag, a.describe(), a.t_issue, a.t_done)

        history = self._history(cfg)
        self._grade_writes(every)
        self._grade_reads(cfg, every, history)
        self._grade_stress(cfg, watch)

        # --- CHK-ABR-CRW-FINAL ------------------------------------------------
        for reg in RW_WORDS:
            want = history[reg.addr][-1].value if history[reg.addr] else cfg.initial[reg.addr]
            for bus in OWNED:
                acc = await abr.read(bus, reg.addr)
                assert acc.resp == RESP_OKAY and acc.data == want, (
                    f"CHK-ABR-CRW-FINAL FAIL: {reg.name} reads {acc.resp_name} "
                    f"0x{acc.data:08x} on {bus} after both streams drained, expected "
                    f"0x{want:08x}, the last value its owner wrote"
                )
        self.logger.info(
            "CHK-ABR-CRW-FINAL PASS: after both streams drained, each of %d registers "
            "reads the last value its owner wrote, from both masters",
            len(RW_WORDS),
        )

        # --- CHK-ABR-CRW-RESTORE ----------------------------------------------
        for reg in RW_WORDS:
            await self._set(abr, reg, entry[reg.addr])
        self.logger.info(
            "CHK-ABR-CRW-RESTORE PASS: %d registers read back their entry values",
            len(RW_WORDS),
        )

    async def _set(self, abr: SepAbrBus, reg: AbrWord, value: int) -> None:
        wr = await abr.write("s_axi", reg.addr, value)
        rd = await abr.read("s_axi", reg.addr)
        assert wr.resp == RESP_OKAY and rd.resp == RESP_OKAY and rd.data == value & reg.mask, (
            f"{reg.name}: write of 0x{value:08x} answered {wr.resp_name}, read back "
            f"{rd.resp_name} 0x{rd.data:08x}"
        )

    @staticmethod
    def _landed(acc: AbrAccess) -> dict[int, int]:
        """Register address -> stored value for a write expected to land."""
        if acc.tag == "wr32":
            return {acc.addr: acc.wdata & RW[acc.addr].mask}
        if acc.tag == "wr64":
            lo, hi = PAIR
            return {lo.addr: acc.wdata & lo.mask, hi.addr: (acc.wdata >> 32) & hi.mask}
        return {}

    def _history(self, cfg: SepAbrConcurrentRwCfg) -> dict[int, list[_Write]]:
        """Per register, the owner's landing writes in issue order."""
        hist: dict[int, list[_Write]] = {w.addr: [] for w in RW_WORDS}
        for ops in cfg.ops.values():
            for acc in ops:
                for addr, value in self._landed(acc).items():
                    hist[addr].append(_Write(acc.t_issue, acc.t_done, value))
        return hist

    def _grade_writes(self, every: list[AbrAccess]) -> None:
        # --- CHK-ABR-CRW-WRITE-RESP -------------------------------------------
        bad = []
        for a in every:
            if a.op != "wr":
                continue
            want = RESP_SLVERR if a.tag == "wr_partial" else RESP_OKAY
            if a.resp != want:
                bad.append(f"{a.tag} {a.describe()} expected resp {want}")
        assert not bad, (
            f"CHK-ABR-CRW-WRITE-RESP FAIL: {len(bad)} write(s) answered the wrong "
            f"response; first: {bad[0]}"
        )
        n_full = sum(a.tag in ("wr32", "wr64") for a in every)
        n_part = sum(a.tag == "wr_partial" for a in every)
        self.logger.info(
            "CHK-ABR-CRW-WRITE-RESP PASS: %d full-word writes answered OKAY and %d "
            "partial-word writes answered SLVERR under concurrent traffic",
            n_full,
            n_part,
        )

    def _legal(
        self, cfg: SepAbrConcurrentRwCfg, hist: list[_Write], addr: int, rd: AbrAccess
    ) -> set[int]:
        """Values a read of ``addr`` may return given the owner's write history."""
        landed = [k for k, w in enumerate(hist) if w.t_done < rd.t_issue]
        first = landed[-1] if landed else -1
        legal = {hist[first].value if first >= 0 else cfg.initial[addr]}
        for w in hist[first + 1 :]:
            if w.t_issue <= rd.t_done:
                legal.add(w.value)
        return legal

    def _grade_reads(self, cfg: SepAbrConcurrentRwCfg, every: list[AbrAccess], history) -> None:
        # --- CHK-ABR-CRW-READ -------------------------------------------------
        bad: list[str] = []
        words = exact = windowed = cross = tight = 0
        for rd in every:
            if rd.op != "rd":
                continue
            if rd.resp != RESP_OKAY:
                bad.append(f"{rd.describe()} expected OKAY")
                continue
            for off in range(0, rd.nbytes, 4):
                addr = rd.addr + off
                got = lane_value(off, 4, rd.data)
                words += 1
                if addr in IDENTITY:
                    legal = {IDENTITY[addr].value}
                    exact += 1
                else:
                    legal = self._legal(cfg, history[addr], addr, rd)
                    windowed += 1
                    tight += len(legal) == 1
                    owner = next(
                        b for b, regs in OWNED.items() if any(r.addr == addr for r in regs)
                    )
                    if owner != rd.bus and got != cfg.initial[addr]:
                        cross += 1
                if got not in legal:
                    name = IDENTITY[addr].name if addr in IDENTITY else RW[addr].name
                    bad.append(
                        f"{rd.describe()}: {name} word 0x{got:08x} not in "
                        f"{{{', '.join(f'0x{v:08x}' for v in sorted(legal))}}}"
                    )
        assert not bad, (
            f"CHK-ABR-CRW-READ FAIL: {len(bad)} read(s) returned a value their address "
            f"could not hold at that time; first: {bad[0]}"
        )
        assert windowed and exact and cross and tight, (
            f"CHK-ABR-CRW-READ FAIL: the streams graded {exact} identity words, "
            f"{windowed} read-write words ({tight} with a single legal value) and "
            f"{cross} cross-master observations; each class needs at least one or the "
            "compare covers less than it claims"
        )
        self.logger.info(
            "CHK-ABR-CRW-READ PASS: %d words read under concurrent traffic: %d identity "
            "words exact, %d read-write words inside their write window (%d of them with "
            "a single legal value), %d a value the other master wrote",
            words,
            exact,
            windowed,
            tight,
            cross,
        )

    def _grade_stress(self, cfg: SepAbrConcurrentRwCfg, watch: AbrBusWatch) -> None:
        # --- CHK-ABR-CRW-STRESS -----------------------------------------------
        problems = []
        for bus in OWNED:
            rec = watch.rec[bus]
            self.logger.info(
                "ABR-CRW %s: %d AR, %d R, %d AW, %d B; max %d reads, %d writes, %d "
                "accesses outstanding; RREADY held low %d cycles, BREADY %d cycles",
                bus,
                len(rec.ar),
                len(rec.r),
                len(rec.aw),
                len(rec.b),
                rec.max_rd_outstanding,
                rec.max_wr_outstanding,
                rec.max_outstanding,
                rec.r_stall_cycles,
                rec.b_stall_cycles,
            )
            n_rd = sum(a.op == "rd" for a in cfg.ops[bus])
            n_wr = sum(a.op == "wr" for a in cfg.ops[bus])
            if (len(rec.ar), len(rec.aw), len(rec.b)) != (n_rd, n_wr, n_wr):
                problems.append(
                    f"{bus}: {len(rec.ar)} AR / {len(rec.aw)} AW / {len(rec.b)} B on the "
                    f"pins for {n_rd} reads and {n_wr} writes issued"
                )
            if rec.max_outstanding < 3:
                problems.append(
                    f"{bus}: at most {rec.max_outstanding} accesses outstanding at once, "
                    f"with a stream depth of {cfg.depth[bus]}"
                )
            if not (rec.r_stall_cycles and rec.b_stall_cycles):
                problems.append(f"{bus}: a response channel was never held off")
        self.logger.info(
            "ABR-CRW cycles with both masters outstanding: %d of %d",
            watch.all_busy_cycles,
            watch.cycles,
        )
        if watch.all_busy_cycles == 0:
            problems.append("the two masters were never outstanding in the same cycle")
        assert not problems, "CHK-ABR-CRW-STRESS FAIL: " + "; ".join(problems)
        self.logger.info(
            "CHK-ABR-CRW-STRESS PASS: both masters held several accesses outstanding, "
            "overlapped for %d cycles, and had R and B held off by RREADY/BREADY",
            watch.all_busy_cycles,
        )
