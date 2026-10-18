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

The noise driver must run before the clean start: the leaf starts it with
``balanced`` patterns before the TRNG reset release, because the health testers
and the window counter run from the release while ``CTRL.MODULE_ENABLE`` holds
its reset value 1 (``hw/ip/entropy_source/regs/gen/adoc/entropy_source.adoc``,
``CTRL`` reset 0x1). ``run`` raises if the driver is not running. With
``release_mark`` (the ``SepEsrcPatternNoise.mark`` taken at the release) ``run``
logs the strobes from the release to the ``DECORRELATOR_CTRL`` write as
``pre_clean_strobes`` and raises if there are more than
``MAX_PRE_CLEAN_STROBES``.

``run_live`` is the same start with no ``CTRL`` write, for a leaf that grades
the state the IP reaches from its reset configuration: right after a TRNG reset
release, with ``MODULE_ENABLE`` at its reset value 1, it writes
``DECORRELATOR_CTRL.BYPASS`` = 0xFFF, the clean limits of the reset window
W0 (``HEALTH_TEST_WINDOW_SIZE`` reset value, 2048) and the extra register writes,
and it does not write ``HEALTH_TEST_WINDOW_SIZE``. The lane patterns change at
the next strobe, so every word stays whole. The health-test window counter runs
from the release, and ``run_live`` raises if more than ``MAX_PRE_CLEAN_STROBES``
strobes came from the release to the end of its last write, so the first window
holds at most that many words of the reset configuration. Each such word
changes a per-lane one count by at most one and a run by at most one word: a
``balanced`` window of W0 words (whole 64-word periods) stays at least
3W0/64 = 96 one counts inside the APT limits, and a run stays below 45 + 16
words, under the clean ``REPETITION_LIMIT`` and, before that write, under the
reset limit 25 (at most 16 words since the release), so the first window
passes.

It is separate from ``SepEsrcConfigSeq`` (``sep_esrc_bringup_seq.py``), which
``bring_up_entropy`` uses with its own noise and limits; the two share no state.

``SepEsrcLeafSetup`` is the set-up that every ESRC leaf shares around the clean
start:

* ``trng_reset``: ``SW_RESET_N`` TRNG bit 0 then 1 (``SepSwReset``), a wait for
  ``trng_reset_active_probe_o`` = 1, then for ``trng_reset_active_probe_o`` = 0
  and ``trng_axi_isolated_probe_o`` = 0. It returns the noise mark at the
  release. The first release is bounded at ``TRNG_RELEASE_CAP`` clocks, every
  later one at ``LATENCY_FACTOR`` x the first (``TRNG-RESET`` log line).
* ``measure_period``: the strobe period p, measured once per leaf and logged
  as ``OBS-ESRC-STROBE``.
* ``wait_boot_done``: ``MAIN_SM_STATUS.BOOT_PHASE_DONE`` = 1 after a clean
  start, bounded at 2W + 64 strobes (the first window after a TRNG reset can
  be partial) times p.
* ``bound`` / ``learn``: a latency bound of ``LATENCY_FACTOR`` x the clean time
  of the same operation measured earlier in the leaf, or a fixed outer cap
  before the first measurement.

The first TRNG reset release and the first boot wait of a leaf are bring-up
waits: a timeout raises ``AssertionError``. A later timeout of the same wait
raises ``TrialTimeout`` (``env/sep_trial_wait.py``), so a leaf can fail the
check of the trial that the set-up belongs to and go on.

Usage::

    noise = SepEsrcPatternNoise()
    balanced = balanced_lanes(rng)           # drawn once, logged in the plan
    noise.start(balanced)                    # before the TRNG reset release
    ...                                      # TRNG reset release
    mark = noise.mark()
    cs = SepEsrcCleanStart(self, noise, balanced, window=2048)
    await cs.run(release_mark=mark)
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

import cocotb
from cocotb.triggers import NextTimeStep, ReadOnly, RisingEdge
from env.sep_esrc_pattern_noise import (
    PERIOD,
    Balanced,
    LanePattern,
    SepEsrcPatternNoise,
    describe,
)
from env.sep_trial_wait import TrialTimeout, poll_until
from sep_reg_meta import ENTROPY_SOURCE

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_esrc_bringup_seq import (
    ESRC_APT_PROPORTION_1BIT,
    ESRC_APT_PROPORTION_LO,
    ESRC_CTRL,
    ESRC_DECORRELATOR_CTRL,
    ESRC_HEALTH_TEST_CTRL,
    ESRC_HEALTH_TEST_WINDOW_SIZE,
    ESRC_MAIN_SM_STATUS,
    ESRC_MARKOV_TEST_PROB_THRESHOLDS,
)

DEFAULT_WINDOW = 2048
# Strobes allowed from the TRNG reset release to the DECORRELATOR_CTRL write.
# Each changes a health-test window count by at most one word, far inside the
# W/4 margin of the clean limits.
MAX_PRE_CLEAN_STROBES = 16
CLEAN_REPETITION_LIMIT = 200
BYPASS_ALL = (
    ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["BYPASS"]["bm"]
    >> (ENTROPY_SOURCE.fields("DECORRELATOR_CTRL")["BYPASS"]["bp"])
)
# Outer limit of the first TRNG reset release wait (clocks); never a contract.
TRNG_RELEASE_CAP = 4_000
# A latency wait is bounded at this many times its clean time in the same leaf.
LATENCY_FACTOR = 16
# Outer limit of the strobe-period measurement (clocks); never a contract.
PERIOD_CAP = 10_000
# Clocks per strobe at the reset DECORRELATOR_CTRL.SAMPLE_CLK_DIV, used only to
# bound a wait before the leaf has measured p.
RESET_STROBE_CLK = PERIOD
_BOOT_DONE = ENTROPY_SOURCE.fields("MAIN_SM_STATUS")["BOOT_PHASE_DONE"]["bm"]
_SIZE_MAX = ENTROPY_SOURCE.fields("HEALTH_TEST_WINDOW_SIZE")["SIZE"]["bm"]
_PROB_MAX = ENTROPY_SOURCE.fields("MARKOV_TEST_PROB_THRESHOLDS")["PROB_01_THRESHOLD"]["bm"]
# HEALTH_TEST_WINDOW_SIZE.SIZE reset value (entropy_source.adoc, 0x800).
RESET_WINDOW = ENTROPY_SOURCE.reset("HEALTH_TEST_WINDOW_SIZE") & _SIZE_MAX


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

    async def run(self, *, release_mark: int | None = None) -> CleanLimits:
        """Run the clean start; returns the limits it wrote. Logs ``ESRC-CLEAN-START``.

        Raises if the noise driver is not running, or if more than
        ``MAX_PRE_CLEAN_STROBES`` strobes came after ``release_mark``.
        """
        if not self.noise.running:
            raise AssertionError(
                "ESRC-CLEAN-START: the noise driver is not running; start it before the "
                "TRNG reset release"
            )
        await self._wr(ESRC_CTRL, self._ctrl(0))
        pre = self._pre_check(release_mark)
        lim = await self._clean_writes(window=True)
        await self._wr(ESRC_CTRL, self._ctrl(1))
        self._log("ESRC-CLEAN-START", pre)
        return lim

    async def run_live(self, *, release_mark: int) -> CleanLimits:
        """The clean start with no ``CTRL`` write (module docstring). Logs ``ESRC-LIVE-START``.

        The window must be the reset window W0. Raises if the noise driver is not
        running, or if more than ``MAX_PRE_CLEAN_STROBES`` strobes came from
        ``release_mark`` to the end of the last write.
        """
        if self.limits.window != RESET_WINDOW:
            raise ValueError(
                f"run_live needs the reset window {RESET_WINDOW}, not {self.limits.window}"
            )
        if not self.noise.running:
            raise AssertionError(
                "ESRC-LIVE-START: the noise driver is not running; start it before the "
                "TRNG reset release"
            )
        lim = await self._clean_writes(window=False, immediate=False)
        pre = self._pre_check(release_mark)
        self._log("ESRC-LIVE-START", pre)
        return lim

    def _pre_check(self, release_mark: int | None) -> int | None:
        pre = None if release_mark is None else self.noise.words_since(release_mark)
        if pre is not None and pre > MAX_PRE_CLEAN_STROBES:
            raise AssertionError(
                f"ESRC-CLEAN-START: pre_clean_strobes={pre} after the TRNG reset release, "
                f"more than {MAX_PRE_CLEAN_STROBES}"
            )
        return pre

    async def _clean_writes(self, *, window: bool, immediate: bool = True) -> CleanLimits:
        """Every clean-start write except ``CTRL``; ``window`` adds the window size."""
        lim = self.limits
        decor = {"BYPASS": BYPASS_ALL}
        if self.sample_clk_div is not None:
            decor["SAMPLE_CLK_DIV"] = self.sample_clk_div
        await self._wr(ESRC_DECORRELATOR_CTRL, ENTROPY_SOURCE.value("DECORRELATOR_CTRL", **decor))
        if window:
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
        self.noise.set_lanes(self.balanced, immediate=immediate)
        return lim

    def _log(self, tag: str, pre: int | None) -> None:
        self.log.info(
            "%s %s bypass=0x%03x extra_writes=%d pre_clean_strobes=%s %s",
            tag,
            self.limits.describe(),
            BYPASS_ALL,
            len(self.extra_writes),
            "n/a" if pre is None else pre,
            describe(self.balanced),
        )


class SepEsrcLeafSetup:
    """TRNG reset, strobe period, boot wait and latency bounds of one ESRC leaf.

    ``test`` is the running base test (``rd`` reads a probe), ``swrst`` its
    ``SepSwReset`` and ``noise`` its running ``SepEsrcPatternNoise``; the clock
    count is ``noise.clk``.
    """

    def __init__(self, test, swrst, noise: SepEsrcPatternNoise, *, logger=None) -> None:
        self.test = test
        self.swrst = swrst
        self.noise = noise
        self.log = logger if logger is not None else test.logger
        self.p: int | None = None
        self.clean: dict[str, int] = {}
        self.booted = False

    # -- clocks and latency bounds --------------------------------------------
    def now(self) -> int:
        return self.noise.clk

    def period(self) -> int:
        """The measured strobe period, or ``RESET_STROBE_CLK`` before it is measured."""
        return self.p if self.p is not None else RESET_STROBE_CLK

    def bound(self, kind: str, cap: int) -> int:
        """``LATENCY_FACTOR`` x the clean time of ``kind``, or ``cap`` before it is known."""
        clean = self.clean.get(kind)
        return LATENCY_FACTOR * clean if clean else cap

    def learn(self, kind: str, clocks: int) -> None:
        """Record the first (clean) time of ``kind``; later calls keep it."""
        if kind not in self.clean:
            self.clean[kind] = max(1, clocks)
            self.log.info(
                "CLEAN-TIME %s clean=%d bound=%d",
                kind,
                self.clean[kind],
                LATENCY_FACTOR * self.clean[kind],
            )

    # -- waits -------------------------------------------------------------------
    async def wait_probe(self, cond: Callable[[], bool], bound: int) -> int | None:
        """Clocks until ``cond()`` holds on a sampled clock edge; None after ``bound``."""
        clk = cocotb.top.clk_i
        for n in range(1, bound + 1):
            await RisingEdge(clk)
            await ReadOnly()
            if cond():
                await NextTimeStep()
                return n
        await NextTimeStep()
        return None

    async def trng_reset(
        self,
        *,
        balanced: Sequence[LanePattern] | None = None,
        before_release: Callable[[], None] | None = None,
    ) -> int:
        """TRNG reset 0 then 1; returns the noise mark at the release.

        While the reset is held no strobe comes, so ``before_release`` (for
        example a release of the leaf's inject ports) and the pattern change to
        ``balanced`` take effect as a whole before the first strobe.
        """
        dut = cocotb.top
        await self.swrst.park("trng")
        if (
            await self.wait_probe(
                lambda: self.test.rd(dut.trng_reset_active_probe_o, mask=1) == 1,
                TRNG_RELEASE_CAP,
            )
            is None
        ):
            raise AssertionError(f"TRNG reset not active bound={TRNG_RELEASE_CAP}")
        if before_release is not None:
            before_release()
        if balanced is not None:
            self.noise.set_lanes(balanced, immediate=True)
        mark = self.noise.mark()
        await self.swrst.release("trng")
        bound = self.bound("trng_release", TRNG_RELEASE_CAP)
        took = await self.wait_probe(
            lambda: (
                self.test.rd(dut.trng_reset_active_probe_o, mask=1) == 0
                and self.test.rd(dut.trng_axi_isolated_probe_o, mask=1) == 0
            ),
            bound,
        )
        if took is None:
            if "trng_release" in self.clean:
                raise TrialTimeout("trng_reset_release", bound)
            raise AssertionError(f"TRNG reset release not seen bound={bound}")
        self.learn("trng_release", took)
        self.log.info(
            "TRNG-RESET sw_reset_n=0x%02x clean=%d bound=%d took=%d",
            self.swrst.value,
            self.clean["trng_release"],
            bound,
            took,
        )
        return mark

    async def measure_period(self, chk, n: int = 8, **fields) -> int:
        """Measure p once (``n`` strobes); logs ``OBS-ESRC-STROBE``. Returns p."""
        if self.p is None:
            self.p = max(1, int(await self.noise.measure_period(n, bound=PERIOD_CAP)))
            chk.obs("ESRC-STROBE", p=self.p, **fields)
        return self.p

    async def wait_boot_done(self, driver: SepAxiRegDriver, window: int) -> int:
        """Poll ``MAIN_SM_STATUS.BOOT_PHASE_DONE`` = 1 after a clean start; returns clocks.

        Bound: 2W + 64 strobes x p. A clean start passes by construction, so a
        timeout is a set-up failure and raises.
        """
        bound = (2 * window + 64) * self.period()
        t0 = self.now()
        ok, samples = await poll_until(
            lambda: driver._rd(ESRC_MAIN_SM_STATUS), self.now, _BOOT_DONE, _BOOT_DONE, bound
        )
        if not ok:
            if self.booted:
                raise TrialTimeout("boot_phase_done", bound)
            raise AssertionError(
                f"MAIN_SM_STATUS.BOOT_PHASE_DONE not 1 after the clean start bound={bound}"
            )
        self.booted = True
        clocks = (samples[-1][0] if samples else self.now()) - t0
        self.log.info(
            "BOOT-DONE window=%d clk=%d bound=%d (2W+64 strobes x p)", window, clocks, bound
        )
        return clocks
