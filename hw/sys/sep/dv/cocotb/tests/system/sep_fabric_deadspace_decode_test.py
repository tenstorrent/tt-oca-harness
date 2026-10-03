# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode: a wrap past a block's extent must be refused.

no_cpu / +skip_fuse_sense. RANDCFG: known wrap-offset anchors every seed,
plus seed-selected dead offsets inside each block window.

A write or read past a block's allocated size must be refused (DECERR
or SLVERR; this test grades refusal only, not the code), and no live
register in that block may change. A checker that only inspects the
response would pass the day the RTL starts answering DECERR while
still writing the register, so every probe reads back the window's live
registers as well. ``memory_map.adoc`` states the rule: the fabric refuses an
address past the extent a unit allocates, and such an access never
reaches a unit.

Every probe in the set is asserted, the wrapping anchors included; the
contract is not carried by a probe that is logged or waived.

CHK-TRNG-UNOWNED covers the TRNG window, which SEP forwards whole to an
adopter endpoint. The reference integration connects no external TRNG, so no
offset owns a register and every access must be refused: never OKAY, never
the value of a neighbouring ESRC register, and no ESRC register moved.
``memory_map.adoc`` also states the code for that case: the window ends in a
DECERR slave, so a single-beat read or write answers DECERR. Each TRNG probe is
graded against that code.

CHK-DEADSPACE-BEAT and CHK-DEADSPACE-BURST grade bursts in the crypto region
only. ``memory_map.adoc`` ("Single-Beat Register Access") limits register
regions to single beats and lets the later beats of a burst to one error or
alias, so a burst into any other register region is outside the specification
and is not graded. The crypto region is the exception: ``crypto.adoc``
("Single-Beat Access Only") answers every access whose AxLEN is non-zero with
DECERR on every beat, and no beat reaches an accelerator. For each block window
in that region the test issues a four-beat INCR read burst and, where the
window takes writes, a four-beat INCR write burst, across the extent where the
window allows it and at the window base otherwise.

CHK-DEADSPACE-BEAT: the bus monitor's per-beat RRESP vector of every read
burst is DECERR on every beat, inside the extent as well as past it.

CHK-DEADSPACE-BURST: no read-burst beat returns the value of a live register
in the window snapshot, the write burst answers DECERR, and no armed register
moves. A burst that times out fails. At least one window must answer a single
beat at a burst address OKAY, which shows the refusal is the burst rule and
not a dead address.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_deadspace_seq import (
    CRYPTO_HI,
    CRYPTO_LO,
    DEADSPACE_ANCHORS,
    RESP_DECERR,
    RESP_OKAY,
    SepDeadspace,
    SepDeadspaceCfg,
    in_crypto_region,
)

RESP_SLVERR = 2
_RESP_NAME = {
    -1: "TIMEOUT",
    RESP_OKAY: "OKAY",
    1: "EXOKAY",
    RESP_SLVERR: "SLVERR",
    RESP_DECERR: "DECERR",
}

# Response to an unowned TRNG-window offset with no external TRNG connected,
# per channel (hw/sys/sep/doc/memory_map.adoc, TRNG aperture).
TRNG_UNOWNED_RESP = {"r": RESP_DECERR, "w": RESP_DECERR}


@pyuvm.test()
class sep_fabric_deadspace_decode_test(sep_base_test):
    """Refuse unpopulated offsets inside a block window; do not alias live CSRs."""

    async def run_scenario(self) -> None:
        cfg = SepDeadspaceCfg(self.random_seed())
        self.logger.info("deadspace config: %s", cfg.summary())
        assert not cfg.short_windows, (
            "CHK-DEADSPACE-RAND FAIL: window(s) short of the random-probe quota: "
            + ", ".join(
                f"{name}={got}/{want}" for name, (got, want) in sorted(cfg.short_windows.items())
            )
        )
        await self.bring_up_no_cpu()
        dead = SepDeadspace(self)

        snaps = {}
        for win in cfg.windows.values():
            snaps[win.name] = await dead.snapshot(win)
            assert snaps[win.name], (
                f"{win.name}: watch snapshot is empty; the no-alias checker cannot fail"
            )
            # Both numbers, because they differ and the smaller one is the real
            # coverage: readable is what the read-alias compare uses, armed is
            # what the per-probe change compare can actually fail on. Printing
            # only the first reads as more coverage than the change compare has.
            hw_updating = sum(1 for addr in snaps[win.name] if addr in win.hw_updating)
            assert len(snaps[win.name]) - hw_updating > 0, (
                f"CHK-WINDOW-LIVE FAIL: {win.name} has no register armed for the change "
                f"compare ({len(snaps[win.name])} readable, all hardware-updating); the "
                "no-store-alias check cannot fail there"
            )
            self.logger.info(
                "CHK-WINDOW-LIVE PASS: %s %d %s register(s) readable, "
                "%d armed for the change compare (%d hardware-updating)",
                win.name,
                len(snaps[win.name]),
                f"neighbouring {win.watch_from}" if win.watch_from else "allocated",
                len(snaps[win.name]) - hw_updating,
                hw_updating,
            )

        refused = 0
        aliased = 0
        accepted = 0
        fails: list[str] = []
        # (op, addr, resp, refused) of every probe of an adopter window.
        adopter_probes: list[tuple[str, int, int, bool]] = []
        for item in cfg.probes:
            win = cfg.windows[item.window]
            hit = await dead.probe(win, item, snaps[win.name])
            tag = "anchor" if item.anchor else "rand"
            if win.adopter:
                adopter_probes.append((item.op, item.addr, dead.last_resp, not hit))
                self.logger.info(
                    "TRNG-UNOWNED-RESP: %s %s 0x%08x resp=%s (%s)",
                    item.window,
                    item.op,
                    item.addr,
                    _RESP_NAME.get(dead.last_resp, str(dead.last_resp)),
                    tag,
                )
            if hit:
                fails.extend(hit)
                if any("changed live" in f for f in hit):
                    aliased += 1
                if any("resp=" in f for f in hit):
                    accepted += 1
                for line in hit:
                    self.logger.error("CHK-DEADSPACE FAIL [%s]: %s", tag, line)
            else:
                refused += 1
                self.logger.info(
                    "CHK-DEADSPACE-REFUSE PASS: %s %s 0x%08x refused (%s)",
                    item.window,
                    item.op,
                    item.addr,
                    tag,
                )

        # Bursts are graded in the crypto region only; see the module docstring.
        burst_fails: list[str] = []
        beat_fails: list[str] = []
        burst_graded: list[str] = []
        controlled: list[str] = []
        not_graded: list[str] = []
        for win in cfg.windows.values():
            if not in_crypto_region(win.base):
                not_graded.append(win.name)
                continue
            burst_graded.append(win.name)
            # Across the extent where a legal burst can reach it, so the burst
            # also carries beats past the extent; otherwise at the window base.
            crosses = win.dead_lo % 0x1000 != 0 and win.dead_lo > win.base + 8
            start = None if crosses else win.base
            start, _resps, timed_out, words, singles, beat_resps = await dead.burst_across_extent(
                win, start
            )
            for i, (word, (sresp, sdata)) in enumerate(zip(words, singles)):
                self.logger.info(
                    "deadspace burst-audit: %s beat%d 0x%08x %-9s burst=0x%08x "
                    "beat_resp=%s single=0x%08x(resp=%d)",
                    win.name,
                    i,
                    start + 4 * i,
                    "in-extent" if start + 4 * i < win.dead_lo else "past",
                    word,
                    beat_resps[i] if i < len(beat_resps) else "n/a",
                    sdata,
                    sresp,
                )
            if timed_out:
                burst_fails.append(f"{win.name} read burst at 0x{start:08x} timed out")
                continue
            if not beat_resps:
                beat_fails.append(
                    f"{win.name}: no per-beat RRESP vector for the read burst at 0x{start:08x}"
                )
            for i, r in enumerate(beat_resps):
                if r != RESP_DECERR:
                    beat_fails.append(
                        f"{win.name} beat{i} 0x{start + 4 * i:08x} answered "
                        f"{_RESP_NAME.get(r, str(r))} inside a read burst; the crypto "
                        f"demux answers every beat of a burst DECERR"
                    )
            for i, word in enumerate(words):
                for live_addr, live_val in snaps[win.name].items():
                    if word == live_val:
                        burst_fails.append(
                            f"{win.name} beat{i} 0x{start + 4 * i:08x} of the read burst "
                            f"returned 0x{word:08x}, the value of live register 0x{live_addr:08x}"
                        )
                        break
            if any(sresp == RESP_OKAY for sresp, _ in singles):
                controlled.append(win.name)
            if win.write_ok:
                bresp, wr_timed_out, moved = await dead.burst_write(win, start, snaps[win.name])
                self.logger.info(
                    "deadspace burst-audit: %s write burst 0x%08x BRESP=%s",
                    win.name,
                    start,
                    _RESP_NAME.get(bresp, str(bresp)),
                )
                if wr_timed_out:
                    burst_fails.append(f"{win.name} write burst at 0x{start:08x} timed out")
                elif bresp != RESP_DECERR:
                    burst_fails.append(
                        f"{win.name} write burst at 0x{start:08x} answered "
                        f"{_RESP_NAME.get(bresp, str(bresp))}; the crypto demux answers DECERR"
                    )
                burst_fails.extend(moved)

        # Config report, not a checker. Every anchor is placed unconditionally
        # and nothing filters them, so a count against the list that built them
        # cannot fail; the real failure -- an anchor whose window is absent from
        # the map -- raises when the config is built.
        self.logger.info(
            "deadspace config: %d probes including %d directed anchors, seed %d",
            len(cfg.probes),
            len(DEADSPACE_ANCHORS),
            cfg.seed,
        )
        # Reported, not asserted: this test grades refusal only, not the code.
        for line in dead.flavour_findings:
            self.logger.info("DEADSPACE-FLAVOUR: %s", line)
        if dead.flavour_findings:
            self.logger.info(
                "DEADSPACE-FLAVOUR: %d refusal(s) used an error response other "
                "than DECERR. The access was refused, "
                "which is the asserted contract.",
                len(dead.flavour_findings),
            )

        # Adjudicate refuse/no-alias first and log their verdicts, then the
        # burst contract, so a burst failure cannot stop the other two
        # summaries from reaching the log.
        if fails:
            self.logger.error(
                "CHK-DEADSPACE-REFUSE FAIL: %d fail line(s) on %d probes "
                "(%d accepted OKAY, %d aliased a live register)",
                len(fails),
                len(cfg.probes),
                accepted,
                aliased,
            )
            raise AssertionError(
                f"CHK-DEADSPACE-REFUSE FAIL: {accepted} probe(s) accepted "
                f"OKAY and {aliased} aliased a live register"
            )
        self.logger.info(
            "CHK-DEADSPACE-REFUSE PASS: all %d dead offsets were refused", len(cfg.probes)
        )
        self.logger.info(
            "CHK-DEADSPACE-NO-ALIAS PASS: no allocated register moved across any probe"
        )

        # Refusal and no-alias of the TRNG probes are part of CHK-DEADSPACE-REFUSE
        # / -NO-ALIAS above, which already raised on any OKAY, timeout or alias.
        # This checker grades the code of each probe and requires a read and a
        # write in the window.
        trng_rd = sorted({r for op, _a, r, ok in adopter_probes if op == "r" and ok})
        trng_wr = sorted({r for op, _a, r, ok in adopter_probes if op == "w" and ok})
        assert trng_rd and trng_wr, (
            f"CHK-TRNG-UNOWNED FAIL: need a refused read and a refused write in the "
            f"TRNG window, got {len(adopter_probes)} probe(s): {adopter_probes}"
        )
        trng_bad = [
            f"{op} 0x{addr:08x} answered {_RESP_NAME.get(r, r)}, "
            f"memory_map.adoc states {_RESP_NAME[TRNG_UNOWNED_RESP[op]]}"
            for op, addr, r, _ok in adopter_probes
            if r != TRNG_UNOWNED_RESP[op]
        ]
        for line in trng_bad:
            self.logger.error("CHK-TRNG-UNOWNED FAIL: %s", line)
        assert not trng_bad, (
            f"CHK-TRNG-UNOWNED FAIL: {len(trng_bad)} of {len(adopter_probes)} TRNG-window "
            "probe(s) answered a code other than the one memory_map.adoc states"
        )
        self.logger.info(
            "CHK-TRNG-UNOWNED PASS: %d TRNG-window probes refused, none OKAY, no ESRC "
            "register aliased or moved; every read answered %s and every write %s, "
            "as memory_map.adoc states with no external TRNG connected",
            len(adopter_probes),
            "/".join(_RESP_NAME[r] for r in trng_rd),
            "/".join(_RESP_NAME[r] for r in trng_wr),
        )

        # Log both checkers' failures before either asserts, so a beat failure
        # cannot hide what the write burst did.
        for line in beat_fails:
            self.logger.error("CHK-DEADSPACE-BEAT FAIL: %s", line)
        for line in burst_fails:
            self.logger.error("CHK-DEADSPACE-BURST FAIL: %s", line)
        assert not beat_fails, (
            f"CHK-DEADSPACE-BEAT FAIL: {len(beat_fails)} read-burst beat(s) in the crypto "
            f"region did not answer DECERR"
        )
        assert burst_graded, (
            f"CHK-DEADSPACE-BEAT FAIL: no window lies in the crypto region "
            f"0x{CRYPTO_LO:08x}-0x{CRYPTO_HI - 1:08x}, so the burst rule has no evidence"
        )
        self.logger.info(
            "CHK-DEADSPACE-BEAT PASS: every beat of a read burst answered DECERR in %d "
            "crypto-region window(s) (%s)",
            len(burst_graded),
            ", ".join(burst_graded),
        )
        assert not burst_fails, (
            f"CHK-DEADSPACE-BURST FAIL: {len(burst_fails)} burst finding(s) in the crypto region"
        )
        assert controlled, (
            "CHK-DEADSPACE-BURST FAIL: no crypto-region window answered a single beat "
            "at a burst address OKAY, so a dead address would pass the burst checks"
        )
        self.logger.info(
            "CHK-DEADSPACE-BURST PASS: in %d crypto-region window(s) no read-burst beat "
            "returned a live value, every write burst answered DECERR and moved no armed "
            "register; a single beat at a burst address answered OKAY in %s. Not graded, "
            "outside the crypto region (memory_map.adoc, Single-Beat Register Access): %s",
            len(burst_graded),
            ", ".join(controlled),
            ", ".join(not_graded) or "none",
        )
