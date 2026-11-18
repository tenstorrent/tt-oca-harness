# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A MODULE_ENABLE pulse arms HT_WATERMARK for the selected mode; a selector write alone does not.

no_cpu / +skip_fuse_sense / +esrc_noise_force. HEALTH_TEST_CTRL.ENABLE stays 0 on
every arming leg. RANDCFG walks every supported selector through MODULE_ENABLE,
then an unsupported selector and two low-mode falls (APT_LO, MARKOV_LO). After the
last fall, with the graded window closed, one source leg per selector drives a
fixed noise pattern.

Contract (hw/ip/entropy_source/regs/entropy_source.rdl HT_WATERMARK_NUM :799-807,
HT_WATERMARK :810-818; hw/ip/entropy_source/doc/architecture.adoc:130-132):
  CHK-NO-REARM     a selector write alone does not move the watermark (rdl:800); the
                   selector reads back as written (rdl:802, sw = rw), which proves the
                   write reached the DUT.
  CHK-ARM-MEN      a MODULE_ENABLE pulse arms 0x0000 for a high-watermark mode and
                   0xFFFF for a low-watermark mode (rdl:811). The entry arm of each leg
                   (the opposite polarity) is graded the same way.
  CHK-UNSUPPORTED  after a write of an unsupported selector, a MODULE_ENABLE pulse arms
                   0x0000, the high-mode arm value (rdl:805: "Unsupported values select
                   REPCNT_HI"; rdl:811). The entry holds 0xFFFF, so a dropped write
                   fails. Which counter the watermark then tracks is not graded;
                   OBS-HT-WM-SOURCE logs it.
  OBS-HT-UNSUP-SEL the HT_WATERMARK_NUM readback after that write. Logged, not graded:
                   no text states the stored or read value of an unsupported selector.
  CHK-LOW-FALL     a low-mode watermark arms 0xFFFF and falls from it once health
                   tests run.
  CHK-RANDCFG      every encoding of enum WATERMARK_TEST (rdl:790-796) armed to its value.
  OBS-HT-WM-SOURCE for each of the five selectors and the unsupported value: the
                   selector readback, the arm value, the noise pattern, the word
                   count, the HT_WATERMARK value after that pattern ran with the
                   health tests on, and moved (watermark differs from the arm
                   value). The value is logged, not graded: no text states which
                   test instance or statistic feeds HT_WATERMARK, so no expected
                   count exists. The legs run outside the graded window and draw
                   nothing from the seed.

Source legs. Every lane carries one fixed pattern, chosen so that the input
statistic of the selected test moves away from the arm value:
  REPCNT_HI  stuck1: one run for the whole leg (highest repetition count).
  APT_HI     stuck1: all ones (highest one-count).
  APT_LO     stuck0: no ones (lowest one-count).
  MARKOV_HI  alternate: a transition on every word (highest alternation count).
  MARKOV_LO  square32: one transition per 32 words (lowest alternation count).
  unsupported: the REPCNT_HI pattern and word count, so its line compares with
  the REPCNT_HI line (rdl:805).
The decorrelator (architecture.adoc:107) and the BIW mix (:115) sit between the
forced bit and the 32-bit health test, so the pattern sets the input statistic,
not the counted value. The APT and Markov tests compare at window boundaries
(architecture.adoc:124; rdl:330, HEALTH_TEST_WINDOW_SIZE counts valid entropy
words per APT and Markov window), so their legs run the reset window (the leaf
never writes HEALTH_TEST_WINDOW_SIZE) plus one eighth, which holds at least one
window boundary with the tests on. The repetition count is continuous, so its
legs run 256 words. A leg whose watermark stays at the arm value logs moved=0.

FCOV: the graded window of owner sep_esrc_ht_watermark_arming_test opens after the
health tests are held off and covers the arm walk, the unsupported leg and each
low-mode fall up to its CHK-LOW-FALL grade. It closes on the first FAIL, before
the hold-off between the two falls, and at the end. Each owned bin samples on a
HT_WATERMARK read whose sample condition is the compare of the check that grades
that read: SepHtWatermark.write_num reads a supported selector back before every
MODULE_ENABLE pulse, so the selector the sampler takes at the pulse is the
selector the check derives its golden from. The unsupported bin takes no
selector readback: it samples on the unsupported write and the arm read alone.

SepHtWatermarkCfg holds the walk and the seed-selected knobs.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import NextTimeStep, RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_esrc_pattern_noise import (
    NUM_LANES,
    Alternate,
    EsrcStrobeTimeout,
    LanePattern,
    SepEsrcPatternNoise,
    Square,
    Stuck,
)
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test
from sep_reg_meta import ENTROPY_SOURCE
from seq_lib.sep_esrc_ht_watermark_seq import (
    APT_HI,
    APT_LO,
    ARM_HIGH,
    ARM_LOW,
    MARKOV_HI,
    MARKOV_LO,
    RDL_MODE_COUNT,
    REPCNT_HI,
    SUPPORTED,
    SepHtWatermark,
    SepHtWatermarkCfg,
    arm_value,
    sel_name,
)

TEST = "sep_esrc_ht_watermark_arming_test"
_FALL_TIMEOUT_CYCLES = 80_000
_FALL_POLL_EVERY = 64
_HT_WINDOW_WORDS = ENTROPY_SOURCE.value("HEALTH_TEST_WINDOW_SIZE") & 0xFFFF
_WINDOW_LEG_WORDS = _HT_WINDOW_WORDS + _HT_WINDOW_WORDS // 8
_REPCNT_LEG_WORDS = 256
# Source legs: selector -> (pattern on every lane, word count).
_SOURCE_LEGS: dict[int, tuple[LanePattern, int]] = {
    REPCNT_HI: (Stuck(1), _REPCNT_LEG_WORDS),
    APT_HI: (Stuck(1), _WINDOW_LEG_WORDS),
    APT_LO: (Stuck(0), _WINDOW_LEG_WORDS),
    MARKOV_HI: (Alternate(0), _WINDOW_LEG_WORDS),
    MARKOV_LO: (Square(32, 0), _WINDOW_LEG_WORDS),
}
_SOURCE_CYCLES_PER_WORD_BOUND = 64


@pyuvm.test()
class sep_esrc_ht_watermark_arming_test(sep_base_test):
    """HT_WATERMARK arms per mode on MODULE_ENABLE, not on a selector write."""

    def _grade(self, chk: str, ok: bool, text: str) -> None:
        """One PASS or FAIL line; a FAIL is logged, closes the graded window, then raises."""
        if self.chk.ok(chk, ok, detail=text):
            return
        close_graded_window(self.logger)
        raise AssertionError(f"{chk} FAIL: {text}")

    async def _force_polarity(self, ht: SepHtWatermark, *, high: bool) -> int:
        """Arm the opposite polarity so the next leg's expected value can fail."""
        sel = REPCNT_HI if high else APT_LO
        want = ARM_HIGH if high else ARM_LOW
        await ht.write_num(sel)
        await ht.pulse_module_enable()
        got = await ht.read_watermark()
        self._grade(
            "CHK-ARM-MEN",
            got == want,
            f"entry {sel_name(sel)} ({'high' if high else 'low'}) "
            f"HT_WATERMARK=0x{got:04x} want 0x{want:04x}",
        )
        return got

    async def _arm_leg(
        self,
        ht: SepHtWatermark,
        sel: int,
        path: str,
    ) -> int:
        want = arm_value(sel)
        entry = await self._force_polarity(ht, high=(want == ARM_LOW))
        await ht.write_num(sel)
        # The selector readback is the positive probe that the write reached the
        # DUT. It is read, and a mismatch fails, before the HT_WATERMARK read that
        # the no-rearm bin samples.
        sel_rb = await ht.read_num()
        if entry == want or sel_rb != sel:
            self._grade(
                "CHK-NO-REARM",
                False,
                f"{sel_name(sel)} selector write: HT_WATERMARK_NUM=0x{sel_rb:x} want "
                f"0x{sel:x}, entry 0x{entry:04x} arm value 0x{want:04x} (must differ)",
            )
        still = await ht.read_watermark()
        self._grade(
            "CHK-NO-REARM",
            still == entry,
            f"{sel_name(sel)} selector write: HT_WATERMARK_NUM=0x{sel_rb:x} want 0x{sel:x}, "
            f"HT_WATERMARK 0x{entry:04x} -> 0x{still:04x} want 0x{entry:04x} "
            f"(arm value 0x{want:04x} differs from the entry) before {path}",
        )
        await ht.pulse_module_enable()
        got = await ht.read_watermark()
        self._grade(
            "CHK-ARM-MEN",
            got == want,
            f"{sel_name(sel)}/{path} HT_WATERMARK=0x{got:04x} want 0x{want:04x}",
        )
        return got

    async def _check_unsupported(self, ht: SepHtWatermark, sel: int) -> None:
        entry = await self._force_polarity(ht, high=False)
        await ht.write_unsupported(sel)
        got_sel = await ht.read_num()
        self.logger.info(
            "OBS-HT-UNSUP-SEL: wrote 0x%x, HT_WATERMARK_NUM=0x%x (no stated readback)",
            sel,
            got_sel,
        )
        still = await ht.read_watermark()
        self._grade(
            "CHK-NO-REARM",
            still == entry,
            f"unsupported 0x{sel:x} write: HT_WATERMARK 0x{entry:04x} -> 0x{still:04x} "
            f"want 0x{entry:04x}",
        )
        await ht.pulse_module_enable()
        got = await ht.read_watermark()
        self._grade(
            "CHK-UNSUPPORTED",
            got == ARM_HIGH,
            f"after MODULE_ENABLE HT_WATERMARK=0x{got:04x} want 0x{ARM_HIGH:04x} "
            f"(0x{sel:x}: high-mode arm value)",
        )

    async def _check_low_fall(self, ht: SepHtWatermark, sel: int) -> None:
        await ht.write_num(sel)
        await ht.pulse_module_enable()
        armed = await ht.read_watermark()
        self._grade(
            "CHK-LOW-FALL",
            armed == ARM_LOW,
            f"{sel_name(sel)} armed HT_WATERMARK=0x{armed:04x} want 0x{ARM_LOW:04x}",
        )
        await ht.enable_sample_path()
        await ht.enable_health_tests()
        dut = cocotb.top
        got = armed
        fell = False
        for cycle in range(_FALL_TIMEOUT_CYCLES):
            dut.esrc_noise_ext_i.value = cycle & 1
            await RisingEdge(dut.clk_i)
            if cycle % _FALL_POLL_EVERY != 0:
                continue
            got = await ht.read_watermark()
            if got < ARM_LOW:
                fell = True
                break
        self._grade(
            "CHK-LOW-FALL",
            fell,
            f"{sel_name(sel)} HT_WATERMARK 0x{ARM_LOW:04x} -> 0x{got:04x} within "
            f"{_FALL_TIMEOUT_CYCLES} cycles after ENABLE (want below 0x{ARM_LOW:04x})",
        )

    async def _observe_source(self, ht: SepHtWatermark, sel: int) -> None:
        """OBS-HT-WM-SOURCE: HT_WATERMARK after the fixed pattern of selector ``sel``.

        An unsupported ``sel`` runs the REPCNT_HI pattern and word count. The leg
        grades nothing: a selector that does not settle to the written value
        (``sel_settled=0``) or a pattern that delivers fewer words than asked
        within the pacing bound (``short``) is logged on the record, not raised.
        """
        pattern, want_words = _SOURCE_LEGS.get(sel, _SOURCE_LEGS[REPCNT_HI])
        await ht.hold_health_tests_off()
        sel_settled = 1
        if sel in SUPPORTED:
            try:
                await ht.write_num(sel)
            except AssertionError:
                sel_settled = 0
        else:
            await ht.write_unsupported(sel)
        sel_rb = await ht.read_num()
        await ht.pulse_module_enable()
        arm = await ht.read_watermark()
        noise = SepEsrcPatternNoise(logger=self.logger)
        noise.start([pattern] * NUM_LANES)
        try:
            await ht.enable_sample_path()
            await ht.enable_health_tests()
            mark = noise.mark()
            short = 0
            try:
                await noise.wait_words(want_words, want_words * _SOURCE_CYCLES_PER_WORD_BOUND)
            except EsrcStrobeTimeout as exc:
                short = exc.missing
            words = noise.words_since(mark)
            wm = await ht.read_watermark()
        finally:
            await noise.stop()
        await ht.hold_health_tests_off()
        self.chk.obs(
            "HT-WM-SOURCE",
            sel=f"0x{sel:x}",
            sel_rb=f"0x{sel_rb:x}",
            sel_settled=sel_settled,
            arm=f"0x{arm:04x}",
            pattern=pattern.describe(),
            words=words,
            short=short,
            watermark=f"0x{wm:04x}",
            moved=wm != arm,
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seed = self.random_seed()
        self.chk = SepChkLog(self, TEST, seed)
        cfg = SepHtWatermarkCfg(seed)
        ht = SepHtWatermark(self)
        self.logger.info("esrc ht watermark arming: %s", cfg.summary())

        await ht.hold_health_tests_off()
        try:
            open_graded_window(TEST, self.logger)
            # Count only the selectors whose DUT readback matched the documented arm
            # value, and hold that count against the size of enum WATERMARK_TEST as
            # the RDL itself defines it. The bound does not move with the generator
            # that drove the loop, so a walk that skips a mode fails here.
            proven: list[int] = []
            for sel, path in cfg.cells():
                armed = await self._arm_leg(ht, sel, path)
                if armed == arm_value(sel):
                    proven.append(sel)
            self._grade(
                "CHK-RANDCFG",
                len(proven) == RDL_MODE_COUNT,
                f"{len(proven)} selectors armed to their documented value, want "
                f"{RDL_MODE_COUNT} (proven={sorted(proven)})",
            )
            await self._check_unsupported(ht, cfg.unsupported)
            for fall_sel in cfg.fall_sels:
                await self._check_low_fall(ht, fall_sel)
                close_graded_window(self.logger)
                await ht.hold_health_tests_off()
                if fall_sel != cfg.fall_sels[-1]:
                    open_graded_window(TEST, self.logger)
            for sel in (*SUPPORTED, cfg.unsupported):
                await self._observe_source(ht, sel)
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            close_graded_window(self.logger)
            raise
        self.logger.info(
            "esrc ht watermark arming done: %d of %d HT_WATERMARK_NUM encodings armed; "
            "unsupported=%s fall=%s",
            len(proven),
            RDL_MODE_COUNT,
            f"0x{cfg.unsupported:x}",
            [sel_name(s) for s in cfg.fall_sels],
        )
        self.chk.finish()
