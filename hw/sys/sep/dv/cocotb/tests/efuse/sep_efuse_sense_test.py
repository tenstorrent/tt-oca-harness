# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The sensed eFuse shadow registers equal the staged OTP image.

Selects an OTP image through the shared eFuse image policy and senses it through
the behavioral OTP responder. The common sense-done helper compares the sensed
shadow registers against the golden via the backdoor probe.

Log-only: ``OBS-SENSE-FIELD-ORDER`` gives, per field, the first clock on which one of its
words changed at ``efuse_shadow_probe_o`` and the clock of the
``sep_fuse_sense_done_o`` rise, counted from the start of the leaf. The
specification does not state the order in which the sense loads the fields.
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
        assert "skip_fuse_sense" not in cocotb.plusargs, (
            "CHK-SENSE FAIL: +skip_fuse_sense skips the shadow compare this record names"
        )
        self.logger.info("CHK-SENSE PASS: sensed shadow matched the staged image")
