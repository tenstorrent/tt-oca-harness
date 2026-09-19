# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode: a wrap past a block's extent must be refused.

no_cpu / +skip_fuse_sense. RANDCFG: known wrap-offset anchors every seed,
plus seed-selected dead offsets inside each block window.

A write or read past a block's allocated size must be refused (DECERR
or SLVERR; the specification does not mandate which), and no live
register in that block may change. A checker that only inspects the
response would pass the day the RTL starts answering DECERR while
still writing the register, so every probe reads back the window's live
registers as well. ``memory_map.adoc`` states the rule: the fabric refuses an
address past the extent a unit allocates, and such an access never
reaches a unit. It names no response flavour.

Every probe in the set is asserted, the wrapping anchors included; the
contract is not carried by a probe that is logged or waived.

CHK-DEADSPACE-BURST asserts the same refusal on a beat a single-beat probe
cannot reach: AXI decodes the request address only, so an INCR begun in a
block's last live words carries its remaining beats past REG_MAP_SIZE. Each
burst that answers OKAY where the same address is refused as a single beat
fails. The master reports one response for the whole burst, so a burst that
refused only some of its beats cannot be told from one that refused all of
them; a beat inside the extent is therefore also compared against the value the
single-beat path reads, which catches data the single beat could not reach. A
burst that times out is a failure of the audit, not a pass. A window whose dead space is
4KB-aligned carries no legal burst into it and is reported as not auditable,
never counted as a pass; a run where no window was auditable fails.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_deadspace_seq import (
    DEADSPACE_ANCHORS,
    RESP_OKAY,
    SepDeadspace,
    SepDeadspaceCfg,
)


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
            # what the write-probe store compare can actually fail on. Printing
            # only the first reads as more coverage than the store compare has.
            hw_updating = sum(1 for addr in snaps[win.name] if addr in win.hw_updating)
            self.logger.info(
                "CHK-WINDOW-LIVE PASS: %s %d allocated register(s) readable, "
                "%d armed for the store compare (%d hardware-updating)",
                win.name,
                len(snaps[win.name]),
                len(snaps[win.name]) - hw_updating,
                hw_updating,
            )

        refused = 0
        burst_fails: list[str] = []
        beat_fails: list[str] = []
        aliased = 0
        accepted = 0
        fails: list[str] = []
        for item in cfg.probes:
            win = cfg.windows[item.window]
            hit = await dead.probe(win, item, snaps[win.name])
            tag = "anchor" if item.anchor else "rand"
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

        # Burst reachability of the refused span, and a HARD FAIL when a beat
        # lands there. `memory_map.adoc` says an address past a unit's extent
        # is refused at the fabric and never reaches a unit; it draws no distinction
        # between a single beat and a later beat of a burst. An INCR begun in the
        # last live words carries its later beats past REG_MAP_SIZE because AXI
        # decodes the request address only.
        #
        # Those later beats must be refused too, and the refusal is asserted,
        # not logged, like the wrap anchors above.
        burst_audited: list[str] = []
        burst_skipped: list[str] = []
        beat_audited: list[str] = []
        beat_discriminating: list[str] = []
        beat_skipped: list[str] = []
        for win in cfg.windows.values():
            # A window whose dead space starts on a 4KB boundary cannot be
            # entered by a legal burst, and one with no live words before it
            # has nowhere to begin. Neither can carry the contract; both are
            # named rather than absorbed.
            if win.dead_lo % 0x1000 == 0:
                burst_skipped.append(f"{win.name}: dead space is 4KB-aligned")
                continue
            if win.dead_lo <= win.base + 8:
                burst_skipped.append(f"{win.name}: no live words before it")
                continue
            burst_audited.append(win.name)
            start, resps, timed_out, words, singles, beat_resps = await dead.burst_across_extent(
                win
            )
            for i, (word, (sresp, sdata)) in enumerate(zip(words, singles)):
                where = "in-extent" if start + 4 * i < win.dead_lo else "PAST"
                self.logger.info(
                    "deadspace burst-audit: %s beat%d 0x%08x %-9s burst=0x%08x "
                    "single=0x%08x(resp=%d) beat_resp=%s",
                    win.name,
                    i,
                    start + 4 * i,
                    where,
                    word,
                    sdata,
                    sresp,
                    resps[i] if i < len(resps) else "n/a",
                )
            self.logger.info(
                "deadspace burst-audit: %s beat responses=%s timed_out=%s",
                win.name,
                resps,
                timed_out,
            )

            # A burst that never completed proves nothing either way, so it is
            # a failure of the audit rather than a silent pass.
            if timed_out:
                burst_fails.append(
                    f"{win.name} burst beginning 0x{start:08x} timed out, so "
                    f"no beat response is evidence"
                )
                continue
            # Per-beat refusal, read off the bus. The master collapses a read
            # burst to one response, so `resps` cannot say WHICH beats were
            # refused; the monitor keeps each beat's RRESP in order.
            #
            # The rule is one-directional. `memory_map.adoc` requires that an
            # access past the extent never reaches the unit, so no beat past it
            # may answer OKAY. It does not require the beats inside the extent
            # to be served: refusing the whole burst is legal AXI and is the
            # more conservative answer, so a window that answers every beat
            # non-OKAY is recorded, not failed. Asserting the other direction
            # would fail a fabric for being stricter than the specification.
            if beat_resps:
                self.logger.info("deadspace beat-audit: %s per-beat RRESP=%s", win.name, beat_resps)
                for i, r in enumerate(beat_resps):
                    addr = start + 4 * i
                    if addr >= win.dead_lo and r == RESP_OKAY:
                        beat_fails.append(
                            f"{win.name} beat{i} 0x{addr:08x} is past the "
                            f"extent but answered OKAY inside the burst "
                            f"beginning 0x{start:08x}"
                        )
                beat_audited.append(win.name)
                # A window that serves its in-extent beats and refuses only the
                # tail is the only shape that proves the refusal is per beat
                # rather than per burst. Without at least one, this checker has
                # shown that nothing past an extent is served, but not that the
                # fabric can tell the beats apart.
                if all(
                    r == RESP_OKAY for i, r in enumerate(beat_resps) if start + 4 * i < win.dead_lo
                ):
                    beat_discriminating.append(win.name)
            else:
                beat_skipped.append(
                    f"{win.name}: the bus monitor captured no {len(words)}-beat "
                    f"RRESP sequence for the burst at 0x{start:08x}"
                )

            # CHK-DEADSPACE-BURST: any non-OKAY single-beat refusal, not
            # DECERR-only. The specification does not mandate DECERR vs SLVERR.
            # A window whose past-extent single beat answers SLVERR must still
            # fail an OKAY burst to the same address.
            worst = max(resps) if resps else RESP_OKAY
            for i, (sresp, sdata) in enumerate(singles):
                addr = start + 4 * i
                if addr >= win.dead_lo:
                    if sresp != RESP_OKAY and worst == RESP_OKAY:
                        burst_fails.append(
                            f"{win.name} 0x{addr:08x} is refused as a single "
                            f"beat (resp={sresp}) but the burst beginning "
                            f"0x{start:08x} was accepted (resp={worst})"
                        )
                        break
                    continue
                # Inside the extent, and only when the burst was accepted: an
                # accepted burst must read what the single-beat path reads. A
                # refused burst carries the error slave's poison on every beat,
                # which is not data and is not compared.
                if worst != RESP_OKAY:
                    continue
                if sresp == RESP_OKAY and words[i] != sdata:
                    burst_fails.append(
                        f"{win.name} 0x{addr:08x} reads 0x{sdata:08x} as a "
                        f"single beat but 0x{words[i]:08x} as beat{i} of the "
                        f"burst beginning 0x{start:08x}"
                    )
                    break

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
        # Reported, not asserted: memory_map.adoc says such an access is
        # refused but names no response flavour, and which error responses are
        # permitted is a specification question for the design owner.
        for line in dead.flavour_findings:
            self.logger.info("DEADSPACE-FLAVOUR: %s", line)
        if dead.flavour_findings:
            self.logger.info(
                "DEADSPACE-FLAVOUR: %d refusal(s) used an error response other "
                "than the DECERR memory_map.adoc names. The access was refused, "
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

        for line in burst_fails:
            self.logger.error("CHK-DEADSPACE-BURST FAIL: %s", line)
        if burst_fails:
            raise AssertionError(
                f"CHK-DEADSPACE-BURST FAIL: {len(burst_fails)} window(s) "
                f"accepted a burst beat in dead space: a burst begun in a "
                f"block's last live words carries its remaining beats past "
                f"REG_MAP_SIZE and is answered OKAY"
            )
        assert burst_audited, (
            "CHK-DEADSPACE-BURST FAIL: no window could carry the burst "
            "contract, so it has no evidence here (" + "; ".join(burst_skipped) + ")"
        )
        self.logger.info(
            "CHK-DEADSPACE-BURST PASS: %d of %d window(s) refused a burst "
            "that ends past its allocated extent (%s); %d not auditable (%s)",
            len(burst_audited),
            len(cfg.windows),
            ", ".join(burst_audited),
            len(burst_skipped),
            "; ".join(burst_skipped) or "none",
        )

        for line in beat_fails:
            self.logger.error("CHK-DEADSPACE-BEAT FAIL: %s", line)
        if beat_fails:
            raise AssertionError(
                f"CHK-DEADSPACE-BEAT FAIL: {len(beat_fails)} beat(s) answered "
                f"against the extent rule inside a burst"
            )
        assert beat_audited, (
            "CHK-DEADSPACE-BEAT FAIL: no burst yielded a per-beat response "
            "vector, so per-beat refusal has no evidence here (" + "; ".join(beat_skipped) + ")"
        )
        assert beat_discriminating, (
            "CHK-DEADSPACE-BEAT FAIL: every audited window refused its whole "
            "burst, so nothing past an extent was served but the fabric was "
            "never shown to tell one beat from another"
        )
        self.logger.info(
            "CHK-DEADSPACE-BEAT PASS: %d window(s) served no beat past the "
            "extent (%s), of which %d served their in-extent beats and refused "
            "only the tail (%s) -- refusal is per beat, not per burst; the rest "
            "refused the whole burst, which is legal and stricter. %d without a "
            "vector (%s). Read bursts only: one BRESP covers a write burst, so "
            "per-beat write refusal is not observable at the protocol level.",
            len(beat_audited),
            ", ".join(beat_audited),
            len(beat_discriminating),
            ", ".join(beat_discriminating) or "none",
            len(beat_skipped),
            "; ".join(beat_skipped) or "none",
        )
