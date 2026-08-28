# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode. Hard FAILED until RTL refuses the wrap.

no_cpu / +skip_fuse_sense. RANDCFG: known wrap-offset anchors every seed,
plus seed-selected dead offsets inside each block window.

A write or read past a block's allocated size must be refused (DECERR
or SLVERR; the specification does not mandate which), and no live
register in that block may change. A checker that only inspects the
response would pass the day the RTL starts answering DECERR while
still writing the register. The intra-block refuse rule is the filed
RTL defect, not a shall written in ``memory_map.adoc``.

Keep the full probe set. Do not XFAIL. Do not drop the addresses that
already wrap.

KNOWN HARD FAIL, following up the crossbar decode fix in PR #1216. That change
made every single-beat access to a dead offset refuse. It did not reach a later
beat of a burst: AXI decodes the request address only, so an INCR begun in a
block's last live words carries its remaining beats past REG_MAP_SIZE.
entropy_source and sep_lifecycle_ctrl answer OKAY there, the other seven windows
refuse -- issue #1306, which proposes adding both to OCAH_REG_ERR_CHECK_BLOCKS.
CHK-DEADSPACE-BURST fails until that lands.
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_fabric_deadspace_seq import (
    RESP_DECERR,
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
        await self.bring_up_no_cpu()
        dead = SepDeadspace(self)

        snaps = {}
        for win in cfg.windows.values():
            snaps[win.name] = await dead.snapshot(win)
            assert snaps[win.name], (
                f"{win.name}: watch snapshot is empty; the no-alias "
                f"checker cannot fail"
            )
            # Both numbers, because they differ and the smaller one is the real
            # coverage: readable is what the read-alias compare uses, armed is
            # what the write-probe store compare can actually fail on. Printing
            # only the first reads as more coverage than the store compare has.
            hw_updating = sum(
                1 for addr in snaps[win.name] if addr in win.hw_updating)
            self.logger.info(
                "CHK-WINDOW-LIVE PASS: %s %d allocated register(s) readable, "
                "%d armed for the store compare (%d hardware-updating)",
                win.name, len(snaps[win.name]),
                len(snaps[win.name]) - hw_updating, hw_updating)

        refused = 0
        burst_fails: list[str] = []
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
                    item.window, item.op, item.addr, tag)

        # Burst reachability of the refused span, and a HARD FAIL when a beat
        # lands there. `memory_map.adoc` says the span past a unit's extent
        # returns DECERR and never reaches the unit; it draws no distinction
        # between a single beat and a later beat of a burst. An INCR begun in the
        # last live words carries its later beats past REG_MAP_SIZE because AXI
        # decodes the request address only.
        #
        # entropy_source and sep_lifecycle_ctrl answer OKAY there; the other
        # seven windows refuse. Do not XFAIL and do not demote to a log line --
        # the same rule as the wrap anchors above.
        for win in cfg.windows.values():
            if win.dead_lo % 0x1000 == 0 or win.dead_lo <= win.base + 8:
                continue
            start, resp, timed_out, words, singles = \
                await dead.burst_across_extent(win)
            for i, (word, (sresp, sdata)) in enumerate(zip(words, singles)):
                where = "in-extent" if start + 4 * i < win.dead_lo else "PAST"
                self.logger.info(
                    "deadspace burst-audit: %s beat%d 0x%08x %-9s burst=0x%08x "
                    "single=0x%08x(resp=%d)",
                    win.name, i, start + 4 * i, where, word, sdata, sresp)
            self.logger.info(
                "deadspace burst-audit: %s burst resp=%d timed_out=%s",
                win.name, resp, timed_out)
            for i, (sresp, _sdata) in enumerate(singles):
                addr = start + 4 * i
                if addr < win.dead_lo or sresp != RESP_DECERR:
                    continue
                # The single beat proves the address is dead. If the burst was
                # not refused, that same address answered a burst beat.
                if resp == RESP_OKAY:
                    burst_fails.append(
                        f"{win.name} 0x{addr:08x} is refused as a single beat "
                        f"(resp={sresp}) but a burst beginning 0x{start:08x} "
                        f"was accepted (resp={resp})"
                    )
                    break

        self.logger.info(
            "CHK-RANDCFG PASS: walked %d probes (%d anchors) from seed %d",
            len(cfg.probes),
            sum(1 for p in cfg.probes if p.anchor),
            cfg.seed)
        for line in burst_fails:
            self.logger.error("CHK-DEADSPACE-BURST FAIL: %s", line)
        if burst_fails:
            raise AssertionError(
                f"CHK-DEADSPACE-BURST FAIL: {len(burst_fails)} window(s) "
                f"accepted a burst beat in dead space -- see issue 1306"
            )
        self.logger.info(
            "CHK-DEADSPACE-BURST PASS: every window refused a burst that ends "
            "past its allocated extent")
        if fails:
            self.logger.error(
                "CHK-DEADSPACE-REFUSE FAIL: %d fail line(s) on %d probes "
                "(%d accepted OKAY, %d aliased a live register)",
                len(fails), len(cfg.probes), accepted, aliased)
            raise AssertionError(
                f"CHK-DEADSPACE-REFUSE FAIL: {accepted} probe(s) accepted "
                f"OKAY and {aliased} aliased a live register"
            )
        self.logger.info(
            "CHK-DEADSPACE-REFUSE PASS: all %d dead offsets were refused",
            len(cfg.probes))
        self.logger.info(
            "CHK-DEADSPACE-NO-ALIAS PASS: no allocated register moved "
            "across any probe")
