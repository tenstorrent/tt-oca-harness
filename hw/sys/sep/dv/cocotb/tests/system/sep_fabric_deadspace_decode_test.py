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
"""

from __future__ import annotations

import pyuvm

from sep_base_test import sep_base_test
from seq_lib.sep_fabric_deadspace_seq import SepDeadspace, SepDeadspaceCfg


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
            self.logger.info(
                "CHK-WINDOW-LIVE PASS: %s %d allocated register(s) readable",
                win.name, len(snaps[win.name]))

        refused = 0
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

        self.logger.info(
            "CHK-RANDCFG PASS: walked %d probes (%d anchors) from seed %d",
            len(cfg.probes),
            sum(1 for p in cfg.probes if p.anchor),
            cfg.seed)
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
