# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Narrow-write byte masking and memory-window readback.

no_cpu / +skip_fuse_sense. Every AxSIZE at every legal lane offset runs on
every seed; the seed varies the staged data, never whether a case is covered.

CHK-STROBE: a write narrower than the bus beat must change only its own byte
lanes. The word is primed with a known value first and the expected result is
computed from the AXI lane rule, so a stage that widens the strobe, drops it,
or writes the whole beat fails the compare rather than looking normal.

OBS-OTBN-MEM-BUSY-ACCESS: the memory windows are OTBN IMEM and DMEM. The
no_cpu run does not bring EDN up, so OTBN stays in its post-reset internal wipe
(STATUS BUSY_SEC_WIPE_INT). The OTBN register text states that a busy OTBN
reads 0 and ignores the write; each window write and readback is logged, not
graded, under the OTBN wipe-state memory access exception
(docs/test_contracts/smoke_uvm.adoc).
CTRL-OTBN-MEM-PRECOND fails the leaf unless STATUS reads BUSY_SEC_WIPE_INT
before the windows, so a configuration that leaves the wipe is noticed.

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

        await sw.check_otbn_busy()
        for p in cfg.windows:
            await sw.observe_window(p)

        if fails:
            raise AssertionError(
                f"CHK-STROBE FAIL: {len(fails)} failure(s); "
                f"{sw.narrow_ok}/{len(cfg.writes)} narrow writes masked correctly"
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

        # Config report, not a checker: the size axis is the SIZE_BYTES loop, and
        # the module selftest pins its shape at import.
        self.logger.info(
            "strobe config: %d narrow write(s) over %d window(s), sizes %s, seed %d",
            len(cfg.writes),
            len(cfg.windows),
            sorted({SIZE_BYTES[w.size] for w in cfg.writes}),
            cfg.seed,
        )
