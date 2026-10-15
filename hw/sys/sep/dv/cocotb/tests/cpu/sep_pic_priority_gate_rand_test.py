# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PIC delivery gates, the winner by effective priority, the never value and the order flip meet the EL2_PIC contract.

Firmware ``pic_priority_gate_rand_test`` arms PIC sources from the CPU, drives
them with the source drive recipe (mailbox inbound push, OpenTitan
``INTR_TEST``), and logs the handler order. This test draws the rounds from the
run seed, patches them into the firmware parameter block, follows the console
live (``env/sep_fw_console``: graded window on ``M G`` / ``M C``) and grades:

* CHK-NONE-BEFORE-PROGRAM (firmware) no delivery with the reset meie and meipl.
* CHK-GATED      (firmware) no delivery through a closed gate (meie 0, never
                 priority, mstatus.MIE 0); opening the gate delivers the same
                 source once and no other.
* CHK-WINNER     (host) the first handler after the mstatus.MIE gate step is
                 the source of highest effective priority, computed from the
                 drawn raw priorities and priord (``env/sep_pic_map.winner``).
* CHK-STAY-PENDING (firmware) the waiting sources read pending in meip inside
                 the winner handler; control: the set reads 0 before assertion.
* CHK-NEVER      (firmware) the never value does not deliver; effective 1 does.
* CHK-FLIP       (host) after priord flips and the raw priorities are mirrored
                 the first handler is the same winner.
* CHK-MIE-LIVE, CHK-MIP-IDLE, CHK-NO-TIMER-TRAP, CHK-CONTROL (firmware) the
                 timer and software interrupt paths stay idle while the trap
                 path is live.

Log only: ``OBS-LEVEL-SWEEP`` (window closed), ``OBS-NEVER-MEIP``, the handler
order after the first entry. Expected values come from the drawn stimulus and
the priority model, never from a DUT read. cpu run mode, ``+skip_fuse_sense``,
Verilator and VCS.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fcov_gate import close_graded_window
from env.sep_fw_console import SepFwConsole
from env.sep_pic_map import effective, meip_idle_mask_words, mirror, raw_for_effective, winner
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
HOLD_ITERS = 3000
WAIT_ITERS = 200_000
# PIC sources the firmware can drive: mailbox inbound lines 1 to 8, HMAC 18 and
# 20, KMAC 21 and 23, CSRNG 24, EDN 28, OTBN 30 (hw/sys/sep/doc/interrupts.adoc).
CATALOG = (1, 2, 3, 4, 5, 6, 7, 8, 18, 20, 21, 23, 24, 28, 30)
GATE_MEIE0, GATE_NEVER = 0, 1


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
        return cls(seed, rounds, rng.choice(CATALOG))

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
        return out

    def draw_lines(self) -> list[str]:
        out = [f"DRAW rounds={len(self.rounds)} sweep_src={self.sweep}"]
        for i, rd in enumerate(self.rounds):
            out.append(
                f"DRAW round={i} priord={rd.priord} srcs={rd.srcs} raws={rd.raws} "
                f"eff={[effective(x, rd.priord) for x in rd.raws]} "
                f"gates={['meie0' if g == GATE_MEIE0 else 'never' for g in rd.gates]} "
                f"open_order={[rd.srcs[k] for k in rd.order]} never_src={rd.srcs[rd.never_idx]}"
            )
        return out


def _ids(text: str) -> list[int]:
    return [] if text in ("", "none") else [int(x) for x in text.split(",")]


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
        "CHK-FLIP",
        "CHK-MIE-LIVE",
        "CHK-MIP-IDLE",
        "CHK-NO-TIMER-TRAP",
        "CHK-CONTROL",
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _order_lines(self, corner: str) -> list[dict]:
        from env.sep_fw_console import parse_kv

        return [parse_kv(t) for t in self.con.text_lines("ORDER") if f"corner={corner}" in t]

    def _chk_order(self) -> int:
        seed = self.tcfg.seed
        wins = self._order_lines("winner")
        flips = self._order_lines("flip")
        nr = len(self.tcfg.rounds)
        if len(wins) != nr or len(flips) != nr:
            raise AssertionError(
                f"CHK-WINNER FAIL seed={seed}: {len(wins)} winner and {len(flips)} flip ORDER lines, "
                f"expected {nr} each"
            )
        n = 0
        for i, rd in enumerate(self.tcfg.rounds):
            raws = rd.raw_map()
            eff = {s: effective(r, rd.priord) for s, r in raws.items()}
            exp = winner(raws, rd.priord)
            ids = _ids(wins[i].get("ids", ""))
            first = ids[0] if ids else None
            body = (
                f"seed={seed} round={i} priord={rd.priord} raw={raws} eff={eff} first={first} "
                f"exp_first={exp} order={','.join(str(x) for x in ids)}"
            ).replace(" ", " ")
            body = body.replace(": ", ":").replace(", ", ",")
            if first != exp or sorted(ids) != sorted(rd.srcs):
                raise AssertionError(f"CHK-WINNER FAIL {body}")
            self.logger.info("CHK-WINNER PASS %s", body)
            n += 1
            to = rd.priord ^ 1
            mraw = {s: mirror(r) for s, r in raws.items()}
            exp_f = winner(mraw, to)
            fids = _ids(flips[i].get("ids", ""))
            ffirst = fids[0] if fids else None
            fbody = (
                (
                    f"seed={seed} round={i} priord_from={rd.priord} priord_to={to} first={ffirst} "
                    f"exp={exp_f} raw_to={mraw} order={','.join(str(x) for x in fids)}"
                )
                .replace(": ", ":")
                .replace(", ", ",")
            )
            if ffirst != exp_f or exp_f != exp or sorted(fids) != sorted(rd.srcs):
                raise AssertionError(f"CHK-FLIP FAIL {fbody}")
            self.logger.info("CHK-FLIP PASS %s", fbody)
            n += 1
        return n

    def _chk_echo(self) -> None:
        from env.sep_fw_console import parse_kv

        rows = [parse_kv(t) for t in self.con.text_lines("ROUND")]
        if len(rows) != len(self.tcfg.rounds):
            raise AssertionError(f"firmware ran {len(rows)} rounds, drew {len(self.tcfg.rounds)}")
        for i, (kv, rd) in enumerate(zip(rows, self.tcfg.rounds, strict=True)):
            got = (int(kv["priord"]), _ids(kv["srcs"]), _ids(kv["raws"]), _ids(kv["gates"]))
            if got != (rd.priord, rd.srcs, rd.raws, rd.gates):
                raise AssertionError(f"round {i}: firmware ran {got}, drew {rd}")

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.tcfg = PrioCfg.from_seed(seed)
        self.logger.info("SEED seed=%d", seed)
        for line in self.tcfg.draw_lines():
            self.logger.info("%s", line)
        dtcm = os.path.join(os.getcwd(), "sep_dtcm_pic_prio.hex")
        patch_param_block(_DTCM_HEX, dtcm, P_MAGIC, self.tcfg.words())
        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=TEST).start()
        close_graded_window(self.logger)
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
            await self.con.stop()
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        prm = self.con.text_lines("PARAMS")
        want = f"seed=0x{seed & 0xFFFF_FFFF:08x} rounds={len(self.tcfg.rounds)}"
        if not prm or want not in prm[0]:
            raise AssertionError(f"firmware did not run the patched block: {prm} (want {want})")
        self._chk_echo()
        n_fw = self.con.relay_chk()
        nr = len(self.tcfg.rounds)
        self.con.require_counts(
            {
                "CHK-NONE-BEFORE-PROGRAM": 1,
                "CHK-GATED": sum(len(r.srcs) for r in self.tcfg.rounds) + nr,
                "CHK-STAY-PENDING": nr,
                "CHK-NEVER": nr,
                "CHK-MIE-LIVE": 1,
                "CHK-MIP-IDLE": 3,
                "CHK-NO-TIMER-TRAP": 1,
                "CHK-CONTROL": 1,
            }
        )
        # The gate kinds of the CHK-GATED lines are the drawn ones, in the drawn order.
        exp = []
        for rd in self.tcfg.rounds:
            for k in rd.order:
                exp.append((rd.srcs[k], "meie0" if rd.gates[k] == GATE_MEIE0 else "never"))
        got = [
            (int(r.kv["src"]), r.kv["gate"])
            for r in self.con.records("CHK-GATED")
            if r.kv.get("gate") != "mie0"
        ]
        if got != exp:
            raise AssertionError(f"CHK-GATED FAIL: firmware cells {got} != drawn {exp}")
        n_host = self._chk_order()
        for rec in self.con.records("OBS-NEVER-MEIP")[:8]:
            self.logger.info("%s", rec.text)
        self.result_pass(TEST, seed, n_fw + n_host)
