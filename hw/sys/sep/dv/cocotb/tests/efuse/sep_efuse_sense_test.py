# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The sensed eFuse shadow registers equal the staged OTP image.

Selects an OTP image through the shared eFuse image policy and senses it through
the behavioral OTP responder. The common sense-done helper compares the sensed
shadow registers against the golden via the backdoor probe.

``CHK-SENSE-WORD-ORDER`` grades the load order that
``hw/sys/sep/doc/otp_fuse_controller.adoc`` (eFuse sensing) states: each response strobe
stores the shadow word indexed by the word counter and increments it, and
``fuse_sense_done_o`` rises one cycle after the strobe that stores the last word. Over the
words whose staged value differs from reset, the first clock on which each word changes at
``efuse_shadow_probe_o`` must rise strictly with the word index, and the
``sep_fuse_sense_done_o`` rise must come one clock after the change of word 255 (or after
the last changed word when word 255 stays at reset). At least two changed words are required.

Log-only: ``OBS-SENSE-FIELD-ORDER`` gives, per field, the first clock on which one of its
words changed and the clock of the ``sep_fuse_sense_done_o`` rise, counted from the start of
the leaf.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_efuse_plan import FIELD_NAMES, field_n_words, field_word
from sep_base_test import sep_base_test

_MAX_SENSE_CYCLES = 20_000


def _bits(sig) -> str:
    v = sig.value
    s = getattr(v, "binstr", None)
    return (s if s is not None else str(v)).strip()


async def _sense_order(rec: dict) -> None:
    """Per shadow word, the first clock it differs from the previous clock; stops at the
    ``sep_fuse_sense_done_o`` rise."""
    dut = cocotb.top
    prev = None
    clk = 0
    while True:
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        clk += 1
        cur = _bits(dut.efuse_shadow_probe_o)
        if prev is not None and cur != prev:
            n = len(cur) // 32
            for w in range(n):
                if w in rec["first"]:
                    continue
                lo = len(cur) - 32 * (w + 1)
                if cur[lo : lo + 32] != prev[lo : lo + 32]:
                    rec["first"][w] = clk
        prev = cur
        if _bits(dut.sep_fuse_sense_done_o) == "1":
            rec["done"] = clk
            return


@pyuvm.test()
class sep_efuse_sense_test(sep_base_test):
    """After sense-done every shadow register equals the staged image (backdoor probe compare)."""

    # Backdoor-only: no AXI sequencer/scoreboard needed (the shadow probe is
    # read directly), so skip the AXI env -- otherwise its check_phase fails the
    # test for "no AXI transactions".
    build_env = False
    required_evidence = (
        "CHK-SENSE-DONE",
        "CHK-SENSE-WORD-ORDER",
        "CHK-SENSE-BACKDOOR",
        "CHK-IMAGE-MATCH",
    )

    async def run_scenario(self) -> None:
        img = self.select_efuse_image()
        self.write_efuse_image(img)
        rec: dict = {"first": {}, "done": None}
        sampler = cocotb.start_soon(_sense_order(rec))
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        if not sampler.done():
            sampler.cancel()
        first = {
            f: min(
                (
                    rec["first"][w]
                    for w in range(field_word(f), field_word(f) + field_n_words(f))
                    if w in rec["first"]
                ),
                default=None,
            )
            for f in FIELD_NAMES
        }
        seen = sorted((c, f) for f, c in first.items() if c is not None)
        unseen = [f for f, c in first.items() if c is None]
        self.logger.info(
            "OBS-SENSE-FIELD-ORDER first_change=%s sense_done_cycle=%s",
            ",".join([f"{f}:{c}" for c, f in seen] + [f"{f}:none" for f in unseen]),
            "none" if rec["done"] is None else rec["done"],
        )
        assert rec["done"] is not None, "CHK-SENSE-DONE FAIL: no sep_fuse_sense_done_o rise seen"
        self.logger.info("CHK-SENSE-DONE PASS: sep_fuse_sense_done_o rose at clock %d", rec["done"])
        words = sorted(rec["first"].items())
        last = rec["first"].get(255)
        order_ok = all(a[1] < b[1] for a, b in zip(words, words[1:]))
        done_ok = rec["done"] is not None and (
            rec["done"] == last + 1
            if last is not None
            else bool(words) and rec["done"] > words[-1][1]
        )
        assert len(words) >= 2 and order_ok and done_ok, (
            f"CHK-SENSE-WORD-ORDER FAIL: changed_words={len(words)} order_ok={order_ok} "
            f"done={rec['done']} word255_clk={last} first={words}"
        )
        self.logger.info(
            "CHK-SENSE-WORD-ORDER PASS: changed_words=%d ascending by word index, "
            "done=%s word255_clk=%s",
            len(words),
            rec["done"],
            last,
        )
        # The bring-up runs the shared backdoor compare of every shadow word
        # (CHK-SENSE-BACKDOOR); +skip_fuse_sense skips it.
        backdoor = "CHK-SENSE-BACKDOOR" in self._evidence.seen
        assert "skip_fuse_sense" not in cocotb.plusargs and backdoor, (
            f"CHK-IMAGE-MATCH FAIL: backdoor compare logged={int(backdoor)}; "
            "+skip_fuse_sense skips the shadow compare this record names"
        )
        self.logger.info(
            "CHK-IMAGE-MATCH PASS: words=%d sensed shadow equals the staged image",
            len(img.words),
        )
