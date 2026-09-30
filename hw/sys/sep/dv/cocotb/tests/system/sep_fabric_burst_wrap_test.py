# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A write burst that runs past a block's extent must not change a live register.

no_cpu / +skip_fuse_sense. RAND-NONE: one directed burst per block.

``hw/sys/sep/doc/memory_map.adoc`` says the fabric refuses an address past
the extent a unit allocates, and such an access never reaches a unit. The
crossbar routes a burst on its first address, so a write burst that starts on
a block's last live word carries its later beats past the extent into the
same block. For each of ``sep_reset_ctrl``, ``wdt_timer`` and
``secure_dma`` the burst ends where its address repeats a writable target
register's offset at the next power-of-two span, and its final beat toggles
that register. See ``seq_lib/sep_fabric_burst_wrap_seq.py``.

CHK-WRAP-CONTROL: a single-beat write of the same toggled value to the
target reads back, and the original value is then restored. Without it the
no-change compare below could pass on a register that cannot change.

CHK-WRAP-STIM: the AW handshake on the testbench port is one INCR burst with
the start address, AxLEN and AxSIZE of the anchor, so the burst was not split
into shorter bursts that stay inside the extent.

CHK-WRAP-NO-ALIAS: after the burst, every watched register in the block
reads its snapshot value. A burst beat past the extent that reaches the unit
and lands on a live register fails. The response is logged and not graded:
one BRESP covers the whole burst, and the specification names no flavour.

``sep_fabric_deadspace_decode_test`` grades read bursts and single beats past
an extent; this leaf grades what a write burst leaves behind.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_burst_wrap_seq import SepBurstWrap, wrap_anchors

# clk_wdt period as a multiple of the core period (see run_scenario).
WDT_CLK_RATIO = 8


@pyuvm.test()
class sep_fabric_burst_wrap_test(sep_base_test):
    """A write burst past a block's extent leaves every live register unchanged."""

    required_evidence = ("CHK-WRAP-CONTROL", "CHK-WRAP-STIM", "CHK-WRAP-NO-ALIAS")

    async def run_scenario(self) -> None:
        anchors = wrap_anchors()
        # Sim-timing knob: clk_wdt at WDT_CLK_RATIO x the core period, still
        # slower than the core, so the aon_timer register CDC that a WDT write
        # waits on resolves inside the AXI timeout. Set before bring-up so
        # start_clocks uses it.
        self.cfg.wdt_clk_period_ns = WDT_CLK_RATIO * self.cfg.sys_clk_period_ns
        await self.bring_up_no_cpu()
        wrap = SepBurstWrap(self)

        fails: list[str] = []
        for a in anchors:
            name = a.window.name
            self.logger.info(
                "burst-wrap config: %s start=0x%08x beats=%d size=%d final=0x%08x "
                "(extent ends 0x%08x, span 0x%x, target %s @0x%08x)",
                name,
                a.start,
                a.beats,
                a.size,
                a.end_addr,
                a.window.dead_lo,
                a.span,
                a.target,
                a.target_addr,
            )
            snap = await wrap.snapshot(a)
            assert a.target_addr in snap, (
                f"CHK-WRAP-CONTROL FAIL: {name} {a.target} is not in the stable "
                "snapshot, so the no-change compare cannot fail on it"
            )
            miss = await wrap.control(a, snap)
            assert miss is None, f"CHK-WRAP-CONTROL FAIL: {name}: {miss}"
            self.logger.info(
                "CHK-WRAP-CONTROL PASS: %s %s stores a single-beat write of "
                "0x%08x and returns to 0x%08x",
                name,
                a.target,
                snap[a.target_addr] ^ a.flip_mask,
                snap[a.target_addr],
            )

            resp, timed_out, miss = await wrap.burst(a, snap)
            assert miss is None, f"CHK-WRAP-STIM FAIL: {name}: {miss}"
            self.logger.info(
                "CHK-WRAP-STIM PASS: %s one INCR AW at 0x%08x with AxLEN=%d on the pins",
                name,
                a.start,
                a.beats - 1,
            )
            self.logger.info("burst-wrap response: %s BRESP=%d timed_out=%s", name, resp, timed_out)
            if timed_out:
                fails.append(f"{name} burst at 0x{a.start:08x} timed out")
                self.logger.error("CHK-WRAP-NO-ALIAS FAIL: %s", fails[-1])
                continue

            moved, unread = await wrap.changed(a, snap)
            self.logger.info(
                "burst-wrap scope: %s compared %d watched register(s), %d unreadable",
                name,
                len(snap) - len(unread),
                len(unread),
            )
            if unread:
                fails.append(f"{name} re-read failed: {' '.join(unread)}")
                self.logger.error("CHK-WRAP-NO-ALIAS FAIL: %s", fails[-1])
            if moved:
                detail = " ".join(
                    f"+0x{addr - a.window.base:x}:0x{old:08x}->0x{new:08x}"
                    for addr, (old, new) in sorted(moved.items())
                )
                fails.append(
                    f"{name} write burst 0x{a.start:08x}..0x{a.end_addr:08x} "
                    f"(BRESP={resp}) changed live register(s) {detail}; a beat "
                    f"past the extent reached the unit"
                )
                self.logger.error("CHK-WRAP-NO-ALIAS FAIL: %s", fails[-1])
                await wrap.restore(a, snap)
            elif not unread:
                self.logger.info(
                    "CHK-WRAP-NO-ALIAS PASS: %s no live register changed across a "
                    "%d-beat write burst ending 0x%x past the extent (BRESP=%d)",
                    name,
                    a.beats,
                    a.end_addr - a.window.dead_lo,
                    resp,
                )

        if fails:
            raise AssertionError(
                f"CHK-WRAP-NO-ALIAS FAIL: {len(fails)} of {len(anchors)} block(s): "
                + "; ".join(fails)
            )
        self.logger.info(
            "CHK-WRAP-NO-ALIAS PASS: %d block(s) kept every live register across a "
            "write burst past the extent",
            len(anchors),
        )
