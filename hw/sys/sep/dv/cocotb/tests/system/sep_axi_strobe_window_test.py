# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Narrow-write byte masking and memory-window readback.

no_cpu / +skip_fuse_sense. Every AxSIZE at every legal lane offset runs on
every seed; the seed varies the staged data, never whether a case is covered.

CHK-STROBE: a write narrower than the bus beat must change only its own byte
lanes. The word is primed with a known value first and the expected result is
computed from the AXI lane rule, so a stage that widens the strobe, drops it,
or writes the whole beat fails the compare rather than looking normal.

CHK-WINDOW-DATA: a memory-mapped window must read back what was written. A
window behind an SRAM-style TileLink adapter uses the mask on reads, unlike a
register behind a register adapter which ignores it, so a bridge that drives
the mask from the write strobe returns zeros from the window while every
register in the same block behaves. The response is correct in that failure,
which is why only a data compare catches it.

A window that will not accept the write at all is reported as skipped with the
response code, not counted as a pass.

FCOV: the owner window of this leaf (``sep_axi_decode_cg.cp_strobe_merge``)
is open for one narrow write and its read-back at a time. It opens after the
prime word read back as written and closes after the CHK-STROBE compare of
that write, so the prime write and prime read are outside it. The sampler
compares the read-back with the prime read-back merged with the driven write
under its strobes, the same compare as CHK-STROBE, so it samples only a merge
that CHK-STROBE passes. After the first CHK-STROBE FAIL no window opens again.
The memory-window probes run with the window closed.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from seq_lib.sep_axi_strobe_window_seq import (
    SIZE_BYTES,
    SepAxiStrobeWindow,
    SepAxiStrobeWindowCfg,
)

TEST = "sep_axi_strobe_window_test"

# clk_i edges the window stays open after a passing compare, so the close
# never falls in the clock of the read-back beat that the sampler counts.
WINDOW_HOLD_CYCLES = 2


@pyuvm.test()
class sep_axi_strobe_window_test(sep_base_test):
    """Byte-lane masking on narrow writes; data integrity through windows."""

    async def run_scenario(self) -> None:
        cfg = SepAxiStrobeWindowCfg(self.random_seed())
        self.logger.info("strobe/window config: %s", cfg.summary())
        await self.bring_up_no_cpu()
        sw = SepAxiStrobeWindow(self)

        fails: list[str] = []
        try:
            for w in cfg.writes:
                miss = await sw.stage(w)
                if miss is None:
                    if not fails:
                        open_graded_window(TEST, self.logger)
                    miss = await sw.narrow(w)
                if miss is None:
                    await ClockCycles(cocotb.top.clk_i, WINDOW_HOLD_CYCLES)
                    close_graded_window(self.logger)
                    self.logger.info(
                        "CHK-STROBE PASS: 0x%08x %dB at byte %d masked correctly",
                        w.addr,
                        SIZE_BYTES[w.size],
                        w.byte_off,
                    )
                else:
                    close_graded_window(self.logger)
                    fails.append(miss)
                    self.logger.error("CHK-STROBE FAIL: %s", miss)
        finally:
            close_graded_window(self.logger)

        for p in cfg.windows:
            miss = await sw.probe_window(p)
            if miss is not None:
                fails.append(miss)
                self.logger.error("CHK-WINDOW-DATA FAIL: %s", miss)
            elif p.name in sw.window_skipped:
                self.logger.info(
                    "CHK-WINDOW-DATA SKIP: %s not writable here (%s)",
                    p.name,
                    sw.window_skipped[p.name],
                )
            else:
                self.logger.info(
                    "CHK-WINDOW-DATA PASS: %s 0x%08x read back 0x%08x", p.name, p.addr, p.value
                )

        if fails:
            raise AssertionError(
                f"CHK-STROBE/WINDOW FAIL: {len(fails)} failure(s); "
                f"{sw.narrow_ok}/{len(cfg.writes)} narrow writes masked "
                f"correctly, {sw.window_ok}/{len(cfg.windows)} windows verified"
            )

        # Positive evidence: every narrow write ran and was compared.
        assert sw.narrow_ok == len(cfg.writes), (
            f"CHK-STROBE FAIL: {sw.narrow_ok} of {len(cfg.writes)} narrow writes produced a compare"
        )
        self.logger.info(
            "CHK-STROBE PASS: %d narrow write(s) changed only their own byte "
            "lanes (sizes 1B/2B/4B at every legal offset)",
            sw.narrow_ok,
        )

        # Windows are load-bearing evidence only when at least one was
        # writable; say which, rather than implying all three were checked.
        if sw.window_ok:
            self.logger.info(
                "CHK-WINDOW-DATA PASS: %d of %d memory window(s) returned the "
                "written value; %d skipped as not writable here",
                sw.window_ok,
                len(cfg.windows),
                len(sw.window_skipped),
            )
        else:
            raise AssertionError(
                "CHK-WINDOW-DATA FAIL: no memory window was writable, so the "
                "read-mask contract has no evidence here ("
                + ", ".join(f"{k}: {v}" for k, v in sw.window_skipped.items())
                + ")"
            )

        # Config report, not a checker: the size axis is the SIZE_BYTES loop, and
        # the module selftest pins its shape at import.
        self.logger.info(
            "strobe config: %d narrow write(s) over %d window(s), sizes %s, seed %d",
            len(cfg.writes),
            len(cfg.windows),
            sorted({SIZE_BYTES[w.size] for w in cfg.writes}),
            cfg.seed,
        )
