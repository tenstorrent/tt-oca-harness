# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PIC delivery gates, the winner by effective priority, the never value and the order flip meet the EL2_PIC contract.

Firmware ``pic_priority_gate_rand_test`` arms PIC sources from the CPU, drives
them with the source drive recipe (mailbox inbound push, OpenTitan
``INTR_TEST``), and logs the handler order. This test draws the rounds from the
run seed, patches them into the firmware parameter block, follows the console
live (``env/sep_fw_console``: graded window on ``M G`` / ``M C``) and grades:

* CHK-NONE-BEFORE-PROGRAM (firmware) no delivery with the reset meie and meipl.
* CHK-LEVEL-SWEEP (firmware) each of the 16 ``meipl`` encodings written to the
                 drawn sweep source reads back as written, in both priority
                 orders (``el2_pic.adoc``: ``intpriority`` 3:0 is RW); the
                 host requires the 32 records at the drawn source.
* CHK-GATED      (firmware) no delivery through a closed gate (meie 0, never
                 priority, mstatus.MIE 0); opening the gate delivers the same
                 source once and no other. A source held behind ``meie`` 0
                 reads 1 in ``meip`` (``closed_meip``; EL2 PRM section 8.12.3:
                 disabled requests are reported, with ``mcgc.picio`` at its
                 reset value 1, section 8.9 and table 12.2). Control:
                 ``CTRL-PICIO`` reads ``picio=1``, else ``CTRL-MISSING PICIO``.
                 One more record, after the timer
                 legs: source 1 pending at an open PIC gate with mstatus.MIE 1
                 and ``mie.MEIE`` 0 does not deliver, and ``mie.MEIE`` 1
                 delivers it once (``gate=mie_meie``; EL2 PRM section 8.6.1,
                 named by ``hw/sys/sep/doc/cpu.adoc``).
* CHK-WINNER     (host) the handlers after the mstatus.MIE gate step run in
                 effective-priority order: each one is the source of highest
                 effective priority among the sources not yet delivered,
                 computed from the drawn raw priorities and priord
                 (``env/sep_pic_map.winner``); on a tie at the top the lowest
                 source ID runs first (VeeR EL2 PRM section 8.3.3, cited at
                 ``hw/sys/sep/doc/cpu.adoc:22-23``). Every run holds one round
                 with a tie at the top effective priority; CHK-WINNER fails
                 when no graded round holds one.
* CHK-STAY-PENDING (firmware) the waiting sources read pending in meip inside
                 the winner handler; control: the set reads 0 before assertion.
* CHK-NEVER      (firmware) the never value does not deliver; effective 1 does.
* CHK-NEVER-MEIP (firmware) each enabled, asserted source at the never value
                 reads 1 in ``meip``, in the gate corner and the never corner
                 of every round (VeeR EL2 PRM ``docs/source/interrupts.md:159``
                 at the Bender pin: step 5, the pending bit is visible in
                 ``meipX``, comes before the priority step 6; ``:500``: each
                 bit is the pending indication of one source). Control:
                 ``CTRL-PICIO`` of the same round.
* CHK-FLIP       (host) after priord flips and the raw priorities are mirrored
                 the handlers run in the same order, from the same winner.
* CHK-MIE-LIVE, CHK-MIP-IDLE, CHK-NO-TIMER-TRAP, CHK-CONTROL (firmware) the
                 timer and software interrupt paths stay idle while the trap
                 path is live.
* CHK-THRESHOLD  (firmware) standard order, ``meipt`` = T drawn from 1 to 14:
                 the source at level T is pending (its ``meip`` bit reads 1)
                 with no delivery for a hold window of 32 core clocks or more
                 (``hold_clk``); at level T + 1 it delivers once (VeeR EL2
                 PRM section 8.12.5: delivery needs a priority strictly above
                 the threshold).
* CHK-NEST       (firmware) the handler of source A (level L drawn from 1 to
                 14) copies ``meicidpl`` into ``meicurpl``, saves ``mepc`` and
                 ``mstatus`` and sets mstatus.MIE: source B at level L stays
                 pending with no entry for a hold window of 32 core clocks or
                 more, at level L + 1 it nests once;
                 ``meicidpl`` reads L with no ``meicpct`` write (fast
                 interrupt redirect captures the claim ID and level pair,
                 PRM sections 8.6.1, 8.8, 8.12.9, 8.12.10;
                 ``hw/sys/sep/doc/interrupts.adoc:387`` names the
                 fast-interrupt path of this core).
* CHK-INT-TIMER-HOLD (firmware) internal timer k with bound 0 is pending
                 (``mip`` bit 29 - k reads 1) with ``mie.MITIEk`` 0 and
                 mstatus.MIE 1, with ``mie.MTIE`` and ``mie.MSIE`` both 0 and
                 both 1: no trap for a hold window of 32 core clocks or more;
                 then ``mie.MITIEk`` 1 takes one trap with
                 ``mcause`` 0x8000_001D (k = 0) or 0x8000_001C (k = 1)
                 (``hw/sys/sep/doc/interrupts.adoc:294-299``).
* CHK-INT-TIMER-TRAP (firmware) internal timer k stopped, ``mitcnt`` 0, bound
                 B drawn, then enabled: one trap with the timer's ``mcause``,
                 at least B core clocks after the enable (PRM chapter 6: the
                 timer signals at ``mitcnt`` >= ``mitb``). Then the bound
                 itself, with the timer stopped so ``mitcnt`` holds the
                 written value: ``mitcnt`` written to B - 1 takes no trap for
                 a hold window of 32 core clocks or more, reads back B - 1 and
                 leaves ``mip`` bit 29 - k at 0; ``mitcnt`` written to B takes
                 one trap with the timer's ``mcause``. A timer that signals
                 one count or more before ``mitb`` fails the B - 1 step. Both
                 timers run in every run, in a drawn order. No cited
                 specification states the trap latency after the timer
                 reaches its bound, so the clocks past B are logged
                 (``OBS-INT-TIMER-TRAP-LATENCY``) and have no upper bound.
* CHK-TIMER-PIN  (firmware, last leg) the host drives ``timer_int_i`` on each
                 ``REQ tint`` line. With the pin 1, ``mip.MTIP`` reads 1; with
                 ``mie.MTIE`` 0 and mstatus.MIE 1 no trap for a hold window;
                 with ``mie.MTIE`` 1 one trap with ``mcause`` 0x8000_0007;
                 with the pin 0, ``mip.MTIP`` reads 0
                 (``hw/sys/sep/doc/interrupts.adoc:291``: the pin drives
                 ``mip.MTIP``; EL2 PRM tables 13.1 and 13.2 for ``mie.mtie``
                 and ``mip.mtip``, table 13.3 for ``mcause`` 0x8000_0007).

The host also checks that each record of the threshold, nesting and timer
legs carries the drawn stimulus. Log only: ``OBS-INT-TIMER-TRAP-LATENCY``. Expected values
come from the drawn stimulus and the priority model, never from a DUT read. cpu run mode, ``+skip_fuse_sense``,
Verilator and VCS.

FCOV: the samples of owner ``sep_pic_priority_gate_rand_test`` are held at
their DUT event and sample only when a bit of ``pic_fw_pass`` rises
(``env/sep_fcov_gate.set_pic_fw_pass``). A follower of the console writes the
bit of a graded leg after every check of that leg passed, and writes the drop
bit at the start of each graded leg and on a FAIL record.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fcov_gate import (
    PFP_DROP_320,
    PFP_IDLE,
    PFP_NEST,
    PFP_RESET,
    PFP_ROUND,
    PFP_THRESHOLD,
    PFP_TIMER,
    close_graded_window,
    set_pic_fw_pass,
)
from env.sep_fw_console import ConsoleRec, SepFwConsole, parse_kv
from env.sep_pic_map import (
    NUM_LEVELS,
    effective,
    meip_idle_mask_words,
    mirror,
    raw_for_effective,
    winner,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym

TEST = "sep_pic_priority_gate_rand_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "pic_priority_gate_rand_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_priority_gate_rand_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_priority_gate_rand_test.dtcm.hex")
_BANNER = "SEP PIC priority gate test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 20_000_000
_NO_BOOT_CYCLES = 80_000

# Parameter block (fw/tests/pic_priority_gate_rand_test, enum P_* / R_*).
P_MAGIC = 0x320B6A7E
R_MAX = 6
S_MAX = 5
HOLD_ITERS = 1500
WAIT_ITERS = 20_000
# Loop iterations of the hold window of the threshold, nesting and timer legs;
# the firmware check of each leg needs the window to be 32 core clocks or more.
LEG_HOLD_ITERS = 16
# PIC sources the firmware can drive: mailbox inbound lines 1 to 8, HMAC 18 and
# 20, KMAC 21 and 23, CSRNG 24, EDN 28, OTBN 30 (hw/sys/sep/doc/interrupts.adoc).
CATALOG = (1, 2, 3, 4, 5, 6, 7, 8, 18, 20, 21, 23, 24, 28, 30)
GATE_MEIE0, GATE_NEVER = 0, 1
# Threshold and nesting levels: an interior level, so that level + 1 is a
# meipl value (el2_pic.adoc, meipl.INTPRIORITY) and the level is above 0.
LEVEL_LO, LEVEL_HI = 1, NUM_LEVELS - 2
# Internal-timer trap bound: drawn stimulus range in core clocks.
IT_BOUND_MIN, IT_BOUND_MAX = 256, 4096
# mitb of the hold legs: mitcnt >= 0 holds on every clock, so the timer stays
# pending (VeeR EL2 PRM chapter 6, cited at hw/sys/sep/doc/cpu.adoc:22-23).
IT_HOLD_MITB = 0
# Clocks the follower holds a pic_fw_pass bit before it writes 0.
PFP_HOLD_CLK = 2


@dataclass
class Round:
    priord: int
    srcs: list[int]
    raws: list[int]
    gates: list[int]
    order: list[int]
    never_idx: int

    def raw_map(self) -> dict[int, int]:
        return dict(zip(self.srcs, self.raws, strict=True))


@dataclass
class PrioCfg:
    """The seeded stimulus. A pure function of the run seed."""

    seed: int
    rounds: list[Round] = field(default_factory=list)
    sweep: int = 1
    tie_round: int = -1
    tie_srcs: tuple[int, int] = (0, 0)
    thr_src: int = 0
    thr_t: int = LEVEL_LO
    nest_a: int = 0
    nest_b: int = 0
    nest_pl: int = LEVEL_LO
    it_first: int = 0
    it_bound: list[int] = field(default_factory=lambda: [IT_BOUND_MIN, IT_BOUND_MIN])

    @classmethod
    def from_seed(cls, seed: int) -> "PrioCfg":
        rng = SepSeededRng(seed)
        nr = rng.randrange(3, R_MAX + 1)
        prd = [rng.randrange(0, 2) for _ in range(nr)]
        if len(set(prd)) == 1:  # each order in at least one round
            prd[rng.randrange(nr)] ^= 1
        r_eff1 = rng.randrange(nr)
        r_eff15 = rng.randrange(nr)
        rounds = []
        for r in range(nr):
            n = rng.randrange(2, S_MAX + 1)
            srcs = rng.sample(CATALOG, n)
            forced = [e for e, rr in ((1, r_eff1), (15, r_eff15)) if rr == r]
            pool = [e for e in range(1, 16) if e not in forced]
            effs = forced + rng.sample(pool, n - len(forced))
            rng.shuffle(effs)
            raws = [raw_for_effective(e, prd[r]) for e in effs]
            gates = [GATE_MEIE0, GATE_NEVER] + [rng.randrange(0, 2) for _ in range(n - 2)]
            rng.shuffle(gates)
            order = list(range(n))
            rng.shuffle(order)
            rounds.append(Round(prd[r], srcs, raws, gates, order, rng.randrange(n)))
        cfg = cls(seed, rounds, rng.choice(CATALOG))
        # Draws below come after every draw above, so the rounds, the sweep
        # source and recorded seeds keep their values except the tie source.
        cfg._draw_tie(rng, r_eff1)
        cfg.thr_t = rng.randrange(LEVEL_LO, LEVEL_HI + 1)
        cfg.thr_src = rng.choice(CATALOG)
        cfg.nest_pl = rng.randrange(LEVEL_LO, LEVEL_HI + 1)
        cfg.nest_a, cfg.nest_b = rng.sample(CATALOG, 2)
        cfg.it_first = rng.randrange(2)
        cfg.it_bound = [rng.randrange(IT_BOUND_MIN, IT_BOUND_MAX + 1) for _ in range(2)]
        return cfg

    def _draw_tie(self, rng: SepSeededRng, r_eff1: int) -> None:
        """Give one source of one round the top effective priority of that round.

        A round qualifies when a source other than its top one does not hold
        the forced effective priority 1. Every round without a forced value
        qualifies, and at most two rounds of the three or more hold one, so
        each run has a tie round.
        """
        cands = []
        for r, rd in enumerate(self.rounds):
            effs = [effective(x, rd.priord) for x in rd.raws]
            top = max(effs)
            js = [j for j, e in enumerate(effs) if e != top and not (e == 1 and r == r_eff1)]
            if js:
                cands.append((r, js, effs.index(top), top))
        r, js, i_top, top = rng.choice(cands)
        j = rng.choice(js)
        rd = self.rounds[r]
        rd.raws[j] = raw_for_effective(top, rd.priord)
        self.tie_round = r
        self.tie_srcs = (rd.srcs[i_top], rd.srcs[j])

    def words(self) -> list[int]:
        out = [
            P_MAGIC,
            self.seed & 0xFFFF_FFFF,
            len(self.rounds),
            self.sweep,
            HOLD_ITERS,
            WAIT_ITERS,
        ]
        out += meip_idle_mask_words()
        for r in range(R_MAX):
            if r >= len(self.rounds):
                out += [0] * (3 + 4 * S_MAX)
                continue
            rd = self.rounds[r]
            pad = [0] * (S_MAX - len(rd.srcs))
            out += [rd.priord, len(rd.srcs), rd.never_idx]
            out += rd.srcs + pad + rd.raws + pad + rd.gates + pad + rd.order + pad
        out += [self.thr_src, self.thr_t, self.thr_t, self.thr_t + 1]
        out += [self.nest_a, self.nest_b, self.nest_pl, self.nest_pl, self.nest_pl + 1]
        out += [self.it_first] + self.it_bound + self.it_bound + [IT_HOLD_MITB]
        out += [LEG_HOLD_ITERS]
        return out

    def draw_lines(self) -> list[str]:
        out = [f"INFO-DRAW LOG rounds={len(self.rounds)} sweep_src={self.sweep}"]
        for i, rd in enumerate(self.rounds):
            out.append(
                f"INFO-DRAW LOG round={i} priord={rd.priord} srcs={rd.srcs} raws={rd.raws} "
                f"eff={[effective(x, rd.priord) for x in rd.raws]} "
                f"gates={['meie0' if g == GATE_MEIE0 else 'never' for g in rd.gates]} "
                f"open_order={[rd.srcs[k] for k in rd.order]} never_src={rd.srcs[rd.never_idx]}"
            )
        out.append(f"INFO-DRAW LOG tie round={self.tie_round} srcs={list(self.tie_srcs)}")
        out.append(
            f"INFO-DRAW LOG legs thr_src={self.thr_src} thr_t={self.thr_t} nest_a={self.nest_a} "
            f"nest_b={self.nest_b} nest_pl={self.nest_pl} it_first={self.it_first} "
            f"it_bound={self.it_bound}"
        )
        return out

    def leg_problem(self, rec: ConsoleRec, k: int) -> str | None:
        """Why record ``rec`` (the ``k``-th of its name) does not carry the
        drawn stimulus of its leg, or None."""
        kv = rec.kv

        def num(key: str) -> int:
            try:
                return int(kv.get(key, -1))
            except ValueError:
                return -1

        if rec.name == "CHK-THRESHOLD":
            got = (num("src"), num("meipt"), num("pl_held"), num("pl_open"))
            exp = (self.thr_src, self.thr_t, self.thr_t, self.thr_t + 1)
        elif rec.name == "CHK-NEST":
            got = (num("a"), num("b"), num("pl_a"), num("pl_same"), num("pl_high"))
            exp = (self.nest_a, self.nest_b, self.nest_pl, self.nest_pl, self.nest_pl + 1)
        elif rec.name == "CHK-INT-TIMER-HOLD":
            got = (num("timer"), num("mtie_msie"), num("mitb"))
            exp = (self.it_first ^ (k // 2), k % 2, IT_HOLD_MITB)
        elif rec.name == "CHK-INT-TIMER-TRAP":
            t = self.it_first ^ k
            got = (num("timer"), num("mitb"), num("bound"))
            exp = (t, self.it_bound[t], self.it_bound[t])
        else:
            return None
        return None if got == exp else f"record {got} != drawn {exp}"


def _ids(text: str) -> list[int]:
    return [] if text in ("", "none") else [int(x) for x in text.split(",")]


def _exp_order(raws: dict[int, int], priord: int) -> list[int]:
    """Delivery order of a set asserted together: the winner, then the winner
    of the sources not yet delivered, and so on."""
    rest = dict(raws)
    out = []
    while rest:
        w = winner(rest, priord)
        out.append(w)
        del rest[w]
    return out


def _has_top_tie(raws: dict[int, int], priord: int) -> bool:
    effs = [effective(r, priord) for r in raws.values()]
    return effs.count(max(effs)) >= 2


def _fmt(text: str) -> str:
    return text.replace(": ", ":").replace(", ", ",")


# Firmware checks whose records carry the drawn stimulus of their leg.
_LEG_CHKS = ("CHK-THRESHOLD", "CHK-NEST", "CHK-INT-TIMER-HOLD", "CHK-INT-TIMER-TRAP")

# The last check of each graded leg, and the pic_fw_pass bit that the pass of
# every check of the leg releases.
_LEG_LAST = {
    "reset_window": ("CHK-NONE-BEFORE-PROGRAM", PFP_RESET),
    "threshold": ("CHK-THRESHOLD", PFP_THRESHOLD),
    "nest": ("CHK-NEST", PFP_NEST),
    "itimer_hold": ("CHK-INT-TIMER-HOLD", PFP_TIMER),
    "itimer_trap": ("CHK-INT-TIMER-TRAP", PFP_TIMER),
    "idle": ("CHK-NO-TIMER-TRAP", PFP_IDLE),
}


@pyuvm.test()
class sep_pic_priority_gate_rand_test(sep_base_test):
    """PIC gates, winner, never value, order flip and idle timer/software paths meet the EL2_PIC contract."""

    build_env = False
    required_evidence = (
        "CHK-NONE-BEFORE-PROGRAM",
        "CHK-GATED",
        "CHK-WINNER",
        "CHK-STAY-PENDING",
        "CHK-NEVER",
        "CHK-NEVER-MEIP",
        "CHK-FLIP",
        "CHK-MIE-LIVE",
        "CHK-MIP-IDLE",
        "CHK-NO-TIMER-TRAP",
        "CHK-CONTROL",
        "CHK-THRESHOLD",
        "CHK-NEST",
        "CHK-INT-TIMER-HOLD",
        "CHK-INT-TIMER-TRAP",
        "CHK-TIMER-PIN",
        "CHK-LEVEL-SWEEP",
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _order_lines(self, corner: str) -> list[dict]:
        return [parse_kv(t) for t in self.con.text_lines("INFO-ORDER") if f"corner={corner}" in t]

    def _winner_verdict(self, i: int, ids: list[int]) -> tuple[bool, str, list[int]]:
        """CHK-WINNER of round ``i``: (pass, body, expected order)."""
        rd = self.tcfg.rounds[i]
        raws = rd.raw_map()
        eff = {s: effective(r, rd.priord) for s, r in raws.items()}
        exp = winner(raws, rd.priord)
        order = _exp_order(raws, rd.priord)
        first = ids[0] if ids else None
        tie = int(_has_top_tie(raws, rd.priord))
        body = _fmt(
            f"seed={self.tcfg.seed} round={i} priord={rd.priord} raw={raws} eff={eff} tie={tie} "
            f"first={first} exp_first={exp} order={','.join(str(x) for x in ids)} "
            f"exp_order={','.join(str(x) for x in order)}"
        )
        return first == exp and ids == order, body, order

    def _flip_verdict(self, i: int, fids: list[int]) -> tuple[bool, str]:
        """CHK-FLIP of round ``i``: (pass, body)."""
        rd = self.tcfg.rounds[i]
        raws = rd.raw_map()
        exp = winner(raws, rd.priord)
        to = rd.priord ^ 1
        mraw = {s: mirror(r) for s, r in raws.items()}
        exp_f = winner(mraw, to)
        order_f = _exp_order(mraw, to)
        ffirst = fids[0] if fids else None
        body = _fmt(
            f"seed={self.tcfg.seed} round={i} priord_from={rd.priord} priord_to={to} "
            f"first={ffirst} exp={exp_f} raw_to={mraw} order={','.join(str(x) for x in fids)} "
            f"exp_order={','.join(str(x) for x in order_f)}"
        )
        return ffirst == exp_f and exp_f == exp and fids == order_f, body

    def _chk_order(self) -> int:
        seed = self.tcfg.seed
        wins = self._order_lines("winner")
        flips = self._order_lines("flip")
        nr = len(self.tcfg.rounds)
        if len(wins) != nr or len(flips) != nr:
            raise AssertionError(
                f"CHK-WINNER FAIL seed={seed}: {len(wins)} winner and {len(flips)} flip INFO-ORDER lines, "
                f"expected {nr} each"
            )
        n = 0
        ties = 0
        for i in range(nr):
            ok, body, _ = self._winner_verdict(i, _ids(wins[i].get("ids", "")))
            if not ok:
                raise AssertionError(f"CHK-WINNER FAIL {body}")
            self.logger.info("CHK-WINNER PASS %s", body)
            n += 1
            ties += int(_has_top_tie(self.tcfg.rounds[i].raw_map(), self.tcfg.rounds[i].priord))
            ok, fbody = self._flip_verdict(i, _ids(flips[i].get("ids", "")))
            if not ok:
                raise AssertionError(f"CHK-FLIP FAIL {fbody}")
            self.logger.info("CHK-FLIP PASS %s", fbody)
            n += 1
        if ties == 0:
            raise AssertionError(
                f"CHK-WINNER FAIL seed={seed}: no graded round holds a tie at the top "
                f"effective priority (drawn tie round {self.tcfg.tie_round})"
            )
        return n

    def _round_echo(self, i: int, kv: dict) -> str | None:
        rd = self.tcfg.rounds[i]
        try:
            got = (int(kv["priord"]), _ids(kv["srcs"]), _ids(kv["raws"]), _ids(kv["gates"]))
        except (KeyError, ValueError) as exc:
            return f"round {i}: INFO-ROUND line unreadable ({exc})"
        if got != (rd.priord, rd.srcs, rd.raws, rd.gates):
            return f"round {i}: firmware ran {got}, drew {rd}"
        return None

    def _chk_echo(self) -> None:
        rows = [parse_kv(t) for t in self.con.text_lines("INFO-ROUND")]
        if len(rows) != len(self.tcfg.rounds):
            raise AssertionError(f"firmware ran {len(rows)} rounds, drew {len(self.tcfg.rounds)}")
        for i, kv in enumerate(rows):
            bad = self._round_echo(i, kv)
            if bad:
                raise AssertionError(bad)

    def _chk_legs(self) -> None:
        """Each threshold, nesting and timer record carries the drawn stimulus."""
        for name in _LEG_CHKS:
            for k, rec in enumerate(self.con.records(name)):
                bad = self.tcfg.leg_problem(rec, k)
                if bad:
                    raise AssertionError(f"{name} FAIL host: {bad}: {rec.text}")

    # ---- pass label ----
    def _round_passed(self, i: int, recs: list[ConsoleRec], lines: list[str]) -> bool:
        """Every check of round ``i`` passed: the firmware checks of the round
        and the host checks on its INFO-ROUND and INFO-ORDER lines (the compares of
        CHK-WINNER and CHK-FLIP)."""
        rd = self.tcfg.rounds[i]
        chk = [r for r in recs if r.name.startswith("CHK-")]
        gated = [r for r in chk if r.name == "CHK-GATED"]
        names = sorted(r.name for r in chk)
        n_meip = 1 + sum(g == GATE_NEVER for g in rd.gates)
        want = sorted(
            ["CHK-GATED"] * (len(rd.srcs) + 1)
            + ["CHK-STAY-PENDING", "CHK-NEVER"]
            + ["CHK-NEVER-MEIP"] * n_meip
        )
        if names != want or any(r.verdict != "PASS" for r in chk):
            return False
        kinds = [(int(r.kv["src"]), r.kv["gate"]) for r in gated if r.kv.get("gate") != "mie0"]
        exp = [(rd.srcs[k], "meie0" if rd.gates[k] == GATE_MEIE0 else "never") for k in rd.order]
        rounds = [parse_kv(t) for t in lines if t.startswith("INFO-ROUND")]
        wins = [parse_kv(t) for t in lines if t.startswith("INFO-ORDER") and "corner=winner" in t]
        flips = [parse_kv(t) for t in lines if t.startswith("INFO-ORDER") and "corner=flip" in t]
        if kinds != exp or len(rounds) != 1 or len(wins) != 1 or len(flips) != 1:
            return False
        if self._round_echo(i, rounds[0]) is not None:
            return False
        if not self._winner_verdict(i, _ids(wins[0].get("ids", "")))[0]:
            return False
        return self._flip_verdict(i, _ids(flips[0].get("ids", "")))[0]

    async def _label_follower(self) -> None:
        """Write pic_fw_pass from the console: the drop bit at each ``M G``
        marker and on a FAIL record, the bit of a graded leg after every
        check of that leg passed. Runs at the rising edge, after the console
        follower parsed the lines of the previous clock (read-only phase)."""
        con = self.con
        n_legs = n_recs = n_lines = 0
        leg: str | None = None
        leg_clk = 0
        leg_round = -1
        leg_done = True
        n_round = 0
        n_name: dict[str, int] = {}
        hold = 0
        while True:
            await RisingEdge(cocotb.top.clk_i)
            if hold:
                hold -= 1
                if hold == 0:
                    set_pic_fw_pass(0, self.logger)
            out = 0
            new_line = n_lines < len(con.lines)
            n_lines = len(con.lines)
            while n_legs < len(con.legs):
                clk, kind, name = con.legs[n_legs]
                n_legs += 1
                if kind != "G":
                    continue
                out |= 1 << PFP_DROP_320
                leg, leg_clk, leg_done = name, clk, False
                if name == "round":
                    leg_round = n_round
                    n_round += 1
            new_recs = con.recs[n_recs:]
            n_recs = len(con.recs)
            for rec in new_recs:
                if rec.verdict == "FAIL":
                    out |= 1 << PFP_DROP_320
                    leg_done = True
                    close_graded_window(self.logger)
                if rec.name in _LEG_CHKS:
                    k = n_name.get(rec.name, 0)
                    n_name[rec.name] = k + 1
                    if self.tcfg.leg_problem(rec, k) is not None:
                        out |= 1 << PFP_DROP_320
                        leg_done = True
            if leg is not None and not leg_done and not out & (1 << PFP_DROP_320):
                recs = [r for r in con.recs if r.clk >= leg_clk]
                if leg == "round":
                    lines = [t for c, t in con.lines if c >= leg_clk]
                    if new_line and any(
                        t.startswith("INFO-ORDER") and "corner=flip" in t for t in lines
                    ):
                        leg_done = True
                        try:
                            passed = self._round_passed(leg_round, recs, lines)
                        except (KeyError, ValueError, IndexError):
                            passed = False
                        if passed:
                            out |= 1 << PFP_ROUND
                        else:
                            out |= 1 << PFP_DROP_320
                elif leg in _LEG_LAST:
                    last, bit = _LEG_LAST[leg]
                    if any(r.name == last for r in recs):
                        leg_done = True
                        chk = [r for r in recs if r.name.startswith("CHK-")]
                        if all(r.verdict == "PASS" for r in chk):
                            out |= 1 << bit
                        else:
                            out |= 1 << PFP_DROP_320
            if out:
                set_pic_fw_pass(out, self.logger)
                hold = PFP_HOLD_CLK

    async def _req_tint(self, kv: dict) -> None:
        await RisingEdge(cocotb.top.clk_i)
        cocotb.top.timer_int_i.value = 1 if int(kv["on"]) else 0
        self.logger.info("INFO-TINT-DRIVE LOG on=%d", int(kv["on"]))

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = PrioCfg.from_seed(seed)
        self.logger.info("INFO-SEED seed=%d", seed)
        for line in self.tcfg.draw_lines():
            self.logger.info("%s", line)
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_pic_prio.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, self.tcfg.words())
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=TEST).start()
        close_graded_window(self.logger)
        set_pic_fw_pass(0, self.logger)
        self.con.on_request("tint", self._req_tint)
        follower = cocotb.start_soon(self._label_follower())
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
        finally:
            follower.kill()
            await self.con.stop()
            set_pic_fw_pass(0, self.logger)
            cocotb.top.timer_int_i.value = 0
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        prm = self.con.text_lines("INFO-PARAMS")
        want = f"seed=0x{seed & 0xFFFF_FFFF:08x} rounds={len(self.tcfg.rounds)}"
        if not prm or want not in prm[0]:
            raise AssertionError(f"firmware did not run the patched block: {prm} (want {want})")
        self._chk_echo()
        n_fw = self.con.relay_chk()
        nr = len(self.tcfg.rounds)
        n_never_gates = sum(g == GATE_NEVER for rd in self.tcfg.rounds for g in rd.gates)
        self.con.require_counts(
            {
                "CHK-NONE-BEFORE-PROGRAM": 1,
                "CHK-GATED": sum(len(r.srcs) for r in self.tcfg.rounds) + nr + 1,
                "CHK-STAY-PENDING": nr,
                "CHK-NEVER": nr,
                "CHK-NEVER-MEIP": nr + n_never_gates,
                "CHK-MIE-LIVE": 1,
                "CHK-MIP-IDLE": 3,
                "CHK-NO-TIMER-TRAP": 1,
                "CHK-CONTROL": 1,
                "CHK-THRESHOLD": 1,
                "CHK-NEST": 1,
                "CHK-INT-TIMER-HOLD": 4,
                "CHK-INT-TIMER-TRAP": 2,
                "CHK-TIMER-PIN": 1,
                "CHK-LEVEL-SWEEP": 32,
            }
        )
        sweep = sorted(
            (int(r.kv["src"]), int(r.kv["priord"]), int(r.kv["wrote"]))
            for r in self.con.records("CHK-LEVEL-SWEEP")
        )
        want_sweep = [(self.tcfg.sweep, p, v) for p in range(2) for v in range(16)]
        if sweep != want_sweep:
            raise AssertionError(f"CHK-LEVEL-SWEEP FAIL host: cells {sweep} != drawn {want_sweep}")
        self._chk_legs()
        # The gate kinds of the CHK-GATED lines are the drawn ones, in the drawn order.
        exp = []
        for rd in self.tcfg.rounds:
            for k in rd.order:
                exp.append((rd.srcs[k], "meie0" if rd.gates[k] == GATE_MEIE0 else "never"))
        got = [
            (int(r.kv["src"]), r.kv["gate"])
            for r in self.con.records("CHK-GATED")
            if r.kv.get("gate") not in ("mie0", "mie_meie")
        ]
        if got != exp:
            raise AssertionError(f"CHK-GATED FAIL: firmware cells {got} != drawn {exp}")
        n_host = self._chk_order()
        for rec in self.con.records("CHK-INT-TIMER-TRAP"):
            trap_clk = int(rec.kv.get("trap_clk", -1))
            bound = int(rec.kv.get("bound", -1))
            self.logger.info(
                "OBS-INT-TIMER-TRAP-LATENCY LOG timer=%s bound=%d trap_clk=%d "
                "clocks_past_bound=%d (logged; no stated latency)",
                rec.kv.get("timer"),
                bound,
                trap_clk,
                trap_clk - bound,
            )
        self.result_pass(TEST, seed, n_fw + n_host)
