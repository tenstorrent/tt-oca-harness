# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ESRC clean start: an ESRC start whose startup window passes by construction.

While ``CTRL.MODULE_ENABLE`` = 0 the sequence writes
``DECORRELATOR_CTRL.BYPASS`` = 0xFFF, the health-test window W
(``HEALTH_TEST_WINDOW_SIZE.SIZE``, 2048 unless the leaf states another) and the
clean limits of W, then any extra register writes of the leaf, drives the
``balanced`` lane patterns on all 12 lanes, and then writes
``MODULE_ENABLE`` = 1. The clean limits of a window W are:

* ``APT_PROPORTION_1BIT.LIMIT`` = 3W/4 and ``APT_PROPORTION_LO.LIMIT`` = W/4;
* ``MARKOV_TEST_PROB_THRESHOLDS.PROB_01_THRESHOLD`` = W + 1 and
  ``PROB_10_THRESHOLD`` = 0;
* ``HEALTH_TEST_CTRL.REPETITION_LIMIT`` = 200.

A ``balanced``, ``bias70``, ``bias30``, ``square`` or ``alternate`` lane holds
between 19W/64 and 45W/64 ones per window, at most W alternations and no run
above 45 words, so none of them reaches a clean limit. A stuck lane does: 0 or W
ones per window and a run above 200 words.

Every field the leaf does not name keeps its RDL reset value (``value`` of the
generated C export), so a clean start does not clear a control the leaf set
elsewhere unless the leaf passes it. The window must be a multiple of the
64-word pattern period, so a window holds whole periods.

It is separate from ``SepEsrcConfigSeq`` (``sep_esrc_bringup_seq.py``), which
``bring_up_entropy`` uses with its own noise and limits; the two share no state.

Usage::

    noise = SepEsrcPatternNoise()
    balanced = balanced_lanes(rng)           # drawn once, logged in the plan
    cs = SepEsrcCleanStart(self, noise, balanced, window=2048)
    await cs.run()
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from env.sep_esrc_pattern_noise import PERIOD, Balanced, SepEsrcPatternNoise, describe
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_APT_PROPORTION_1BIT,
    ESRC_APT_PROPORTION_LO,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_MARKOV_TEST_PROB_THRESHOLDS,
)

DEFAULT_WINDOW = 2048
CLEAN_REPETITION_LIMIT = 200
BYPASS_ALL = (
    ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["BYPASS"]["bm"]
    >> (ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["BYPASS"]["bp"])
)
_SIZE_MAX = ENTROPY_SOURCE.fields("HEALTH_TEST_WINDOW_SIZE")["SIZE"]["bm"]
_PROB_MAX = ENTROPY_SOURCE.fields("MARKOV_TEST_PROB_THRESHOLDS")["PROB_01_THRESHOLD"]["bm"]


@dataclass(frozen=True)
class CleanLimits:
    """The clean health-test limits of one window size."""

    window: int
    apt_1bit: int
    apt_lo: int
    prob_01: int
    prob_10: int
    repetition: int

    def describe(self) -> str:
        return (
            f"window={self.window} apt_1bit={self.apt_1bit} apt_lo={self.apt_lo} "
            f"prob_01={self.prob_01} prob_10={self.prob_10} repetition={self.repetition}"
        )


def clean_limits(window: int) -> CleanLimits:
    """The clean limits of window ``window`` (a multiple of 64)."""
    if window <= 0 or window % PERIOD:
        raise ValueError(f"window {window} is not a positive multiple of {PERIOD}")
    if window > _SIZE_MAX or window + 1 > _PROB_MAX:
        raise ValueError(
            f"window {window} does not fit HEALTH_TEST_WINDOW_SIZE / PROB_01_THRESHOLD"
        )
    return CleanLimits(
        window=window,
        apt_1bit=3 * window // 4,
        apt_lo=window // 4,
        prob_01=window + 1,
        prob_10=0,
        repetition=CLEAN_REPETITION_LIMIT,
    )


class SepEsrcCleanStart(SepAxiRegDriver):
    """Runs the ESRC clean start through the CPU-LSU master."""

    _DRIVER_TAG = "ESRC"

    def __init__(
        self,
        test,
        noise: SepEsrcPatternNoise,
        balanced: Sequence[Balanced],
        *,
        window: int = DEFAULT_WINDOW,
        ctrl_fields: Mapping[str, int] | None = None,
        health_enable: int | None = None,
        sample_clk_div: int | None = None,
        extra_writes: Sequence[tuple[int, int]] = (),
        logger=None,
    ) -> None:
        super().__init__(test, logger=logger)
        if any(not isinstance(p, Balanced) for p in balanced):
            raise TypeError("a clean start drives balanced patterns only")
        self.noise = noise
        self.balanced = list(balanced)
        self.limits = clean_limits(window)
        ctrl = dict(ctrl_fields or {})
        ctrl.pop("MODULE_ENABLE", None)
        self.ctrl_fields = ctrl
        self.health_enable = health_enable
        self.sample_clk_div = sample_clk_div
        self.extra_writes = tuple(extra_writes)

    def _ctrl(self, module_enable: int) -> int:
        return int(ENTROPY_SOURCE.value("CTRL", MODULE_ENABLE=module_enable, **self.ctrl_fields))

    async def run(self) -> CleanLimits:
        """Run the clean start; returns the limits it wrote. Logs ``ESRC-CLEAN-START``."""
        lim = self.limits
        await self._wr(ESRC_CTRL, self._ctrl(0))
        decor = {"BYPASS": BYPASS_ALL}
        if self.sample_clk_div is not None:
            decor["SAMPLE_CLK_DIV"] = self.sample_clk_div
        await self._wr(ESRC_DECORRELATOR_CTRL, ENTROPY_SOURCE.value("DECORRELATOR_CTRL", **decor))
        await self._wr(
            ESRC_HEALTH_TEST_WINDOW_SIZE,
            ENTROPY_SOURCE.value("HEALTH_TEST_WINDOW_SIZE", SIZE=lim.window),
        )
        await self._wr(
            ESRC_APT_PROPORTION_1BIT,
            ENTROPY_SOURCE.value("APT_PROPORTION_1BIT", LIMIT=lim.apt_1bit),
        )
        await self._wr(
            ESRC_APT_PROPORTION_LO, ENTROPY_SOURCE.value("APT_PROPORTION_LO", LIMIT=lim.apt_lo)
        )
        await self._wr(
            ESRC_MARKOV_TEST_PROB_THRESHOLDS,
            ENTROPY_SOURCE.value(
                "MARKOV_TEST_PROB_THRESHOLDS",
                PROB_01_THRESHOLD=lim.prob_01,
                PROB_10_THRESHOLD=lim.prob_10,
            ),
        )
        ht = {"REPETITION_LIMIT": lim.repetition}
        if self.health_enable is not None:
            ht["ENABLE"] = self.health_enable
        await self._wr(ESRC_HEALTH_TEST_CTRL, ENTROPY_SOURCE.value("HEALTH_TEST_CTRL", **ht))
        for addr, data in self.extra_writes:
            await self._wr(addr, data)
        if self.noise.running:
            self.noise.set_lanes(self.balanced, immediate=True)
        else:
            self.noise.start(self.balanced)
        await self._wr(ESRC_CTRL, self._ctrl(1))
        self.log.info(
            "ESRC-CLEAN-START %s bypass=0x%03x extra_writes=%d %s",
            lim.describe(),
            BYPASS_ALL,
            len(self.extra_writes),
            describe(self.balanced),
        )
        return lim
