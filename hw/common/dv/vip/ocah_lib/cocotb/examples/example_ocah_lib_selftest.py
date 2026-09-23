# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simulator-free selftest of the shared framework library's parity contracts.

Runs as plain Python (``python -m ocah_lib.cocotb.examples.example_ocah_lib_selftest``
with ``hw/common/dv/vip`` on ``PYTHONPATH``). It pins the values the SV-UVM twin
produces for ``OcahRng.salted_seed`` and the directed prefix of
``OcahRng.directed_patterns`` at a few widths, and exercises the
``OcahScoreboard`` pairing contract: either stream first, lanes, ``flush_expected``,
unpaired items, a mismatch, and a required feature that never compares; and it
checks that a sequence INFO record reaches the log under cocotb's default levels. Every
verdict goes through the library's own evidence path; the run exits non-zero on
the first contract that does not hold.
"""

from __future__ import annotations

import logging
import random
import sys
from typing import cast

from ocah_checker import OcahCheckerError

from ocah_lib import (
    OcahKnobs,
    OcahRefModel,
    OcahRng,
    OcahScoreboard,
    OcahScoreboardError,
    OcahSequence,
)

LOG = logging.getLogger("ocah_lib_selftest")

# Values the SV twin computes: salt = sum((i + 1) * label[i]), seed ^ salt, 32-bit.
SALTED_SEED_PINS = (
    (1, "", 0x1),
    (1, "a", 0x60),
    (7, "clamp_hold", 0x1687),
    (0xDEADBEEF, "directed_patterns", 0xDEADFE78),
    (0x100000001, "x", 0x79),
)

# Directed prefix (before the random tail) of OcahRng.directed_patterns per width.
DIRECTED_PREFIX_PINS = {
    1: [0x0, 0x1],
    4: [0x0, 0xF, 0xA, 0x5, 0xC, 0x1, 0xE, 0x2, 0xD, 0x4, 0xB, 0x8, 0x7],
    8: [
        0x00,
        0xFF,
        0xAA,
        0x55,
        0x3C,
        0xEF,
        0x01,
        0xFE,
        0x04,
        0xFB,
        0x10,
        0x40,
        0xBF,
        0x80,
        0x7F,
    ],
    32: [
        0x0000_0000,
        0xFFFF_FFFF,
        0xAAAA_AAAA,
        0x5555_5555,
        0xC3C3_3C3C,
        0x89AB_CDEF,
        0x0000_0001,
        0xFFFF_FFFE,
        0x0000_0100,
        0xFFFF_FEFF,
        0x0001_0000,
        0xFFFE_FFFF,
        0x0100_0000,
        0xFEFF_FFFF,
        0x8000_0000,
        0x7FFF_FFFF,
    ],
}


class SelftestFailure(AssertionError):
    """One selftest contract did not hold."""


def disarm_sim_time_filters() -> None:
    """Drop cocotb's sim-time log filters, which PyUVM attaches and which need a simulator."""
    loggers = [logging.getLogger()] + [
        logger
        for logger in logging.Logger.manager.loggerDict.values()
        if isinstance(logger, logging.Logger)
    ]
    for logger in loggers:
        for handler in logger.handlers:
            for flt in list(handler.filters):
                if type(flt).__name__ == "SimTimeContextFilter":
                    handler.removeFilter(flt)


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SelftestFailure(what)
    LOG.info("ok: %s", what)


class _Doubler(OcahRefModel):
    """Predicts twice the observed value, one expected item per observation."""

    def write(self, item: object) -> None:
        self.expected_ap.write(cast(int, item) * 2)


class _PairScoreboard(OcahScoreboard):
    """Compares observed against expected as integers; records the pairs it saw."""

    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        self.name_tag = "selftest_scoreboard"
        self.pairs: list[tuple[str, object, object]] = []

    def compare_pair(self, feature: str, observed: object, expected: object) -> None:
        self.pairs.append((feature, observed, expected))
        self.compare_equal(feature, observed, expected, context=f"pair={len(self.pairs)}")


def selftest_rng() -> None:
    for seed, label, pinned in SALTED_SEED_PINS:
        check(
            OcahRng.salted_seed(seed, label) == pinned,
            f"salted_seed({seed}, {label!r}) == {pinned:#x}",
        )
    check(OcahRng.bit_mask(0) == 0 and OcahRng.bit_mask(64) == (1 << 64) - 1, "bit_mask edges")
    check(OcahRng.bit_mask(65) == (1 << 65) - 1, "bit_mask above 64 bits is exact")
    for width, prefix in DIRECTED_PREFIX_PINS.items():
        patterns = OcahRng.directed_patterns(width, 3, random.Random(1))
        check(patterns[: len(prefix)] == prefix, f"directed prefix width={width}")
        check(len(patterns) == len(set(patterns)), f"directed patterns deduplicated width={width}")
        check(
            all(0 <= p <= OcahRng.bit_mask(width) for p in patterns),
            f"patterns in range width={width}",
        )
    same = OcahRng.directed_patterns(8, 4, random.Random(5)) == OcahRng.directed_patterns(
        8, 4, random.Random(5)
    )
    check(same, "same seed, same pattern list")


def _build_scoreboard(*features: str, required: tuple[str, ...] = ()) -> _PairScoreboard:
    # PyUVM keeps one root; component names under it must be unique per build.
    scoreboard = _PairScoreboard(f"scoreboard_{features[0]}", None)
    scoreboard.build_phase()
    for feature in features:
        scoreboard.add_feature(feature, required=feature in required)
    disarm_sim_time_filters()
    return scoreboard


def selftest_scoreboard_pairing() -> None:
    scoreboard = _build_scoreboard("echo", "lanes")
    model = _Doubler("echo_model", None)
    disarm_sim_time_filters()
    model.expected_ap.connect(scoreboard.expected_export("echo"))
    # Expected first, then observed; then observed first, then expected.
    model.write(3)
    scoreboard.observed_export("echo").write(6)
    scoreboard.observed_export("echo").write(10)
    model.write(5)
    check(scoreboard.compare_count("echo") == 2, "two pairs compared in either arrival order")
    check(scoreboard.mismatch_count("echo") == 0, "matching pairs record no mismatch")
    # Lanes pair independently and in order within a lane.
    scoreboard.push_observed("lanes", 1, lane="p0")
    scoreboard.push_observed("lanes", 2, lane="p1")
    scoreboard.push_expected("lanes", 2, lane="p1")
    scoreboard.push_expected("lanes", 1, lane="p0")
    check(
        scoreboard.compare_count("lanes") == 2 and scoreboard.mismatch_count("lanes") == 0,
        "lanes pair per lane",
    )
    scoreboard.check_phase()
    check(
        scoreboard.evidence is not None and scoreboard.evidence.pass_count == 2,
        "one passing CHK-SB record per feature",
    )
    check(
        OcahScoreboard.feature_check_id("xtrig_csr") == "CHK-SB-XTRIG-CSR",
        "feature check id format",
    )


def selftest_scoreboard_flush_and_unpaired() -> None:
    scoreboard = _build_scoreboard("flush")
    scoreboard.push_expected("flush", 1)
    scoreboard.push_expected("flush", 2, lane="b")
    check(
        scoreboard.flush_expected("flush") == 2,
        "flush_expected drops waiting expectations on every lane",
    )
    scoreboard.push_observed("flush", 9)
    scoreboard.push_expected("flush", 9)
    scoreboard.check_phase()
    check(scoreboard.mismatch_count("flush") == 0, "flushed expectations never pair")

    scoreboard = _build_scoreboard("dangling")
    scoreboard.push_observed("dangling", 1)
    scoreboard.push_observed("dangling", 2)
    scoreboard.push_expected("dangling", 2)
    try:
        scoreboard.check_phase()
    except OcahCheckerError:
        LOG.info("ok: an unpaired observed item fails the run")
    else:
        raise SelftestFailure("unpaired observed item did not fail check_phase")


def selftest_scoreboard_verdicts() -> None:
    scoreboard = _build_scoreboard("value")
    scoreboard.push_observed("value", 1)
    scoreboard.push_expected("value", 2)
    check(scoreboard.mismatch_count("value") == 1, "a mismatch is counted")
    try:
        scoreboard.check_phase()
    except OcahCheckerError:
        LOG.info("ok: a mismatch fails the run at check_phase")
    else:
        raise SelftestFailure("mismatch did not fail check_phase")

    scoreboard = _build_scoreboard("silent", "spoken", required=("silent",))
    scoreboard.push_observed("spoken", 4)
    scoreboard.push_expected("spoken", 4)
    try:
        scoreboard.check_phase()
    except OcahCheckerError:
        LOG.info("ok: a required feature with zero comparisons fails the run")
    else:
        raise SelftestFailure("required feature with zero comparisons passed")

    scoreboard = _build_scoreboard("idle")
    scoreboard.check_phase()
    LOG.info("ok: an optional feature that never compares is not a failure")

    scoreboard = _build_scoreboard("miss")
    check(
        scoreboard.compare_equal("miss", None, 0) is False,
        "an unresolvable observation never matches",
    )

    scoreboard = _build_scoreboard("known")
    for what, call in (
        ("push on unregistered feature", lambda: scoreboard.push_observed("unknown", 1)),
        ("duplicate registration", lambda: scoreboard.add_feature("known")),
        ("require unregistered feature", lambda: scoreboard.require_feature("unknown")),
        ("bad feature name", lambda: scoreboard.add_feature("bad/name")),
    ):
        try:
            call()
        except OcahScoreboardError:
            LOG.info("ok: %s is a usage error", what)
        else:
            raise SelftestFailure(f"{what} was accepted")
    base = OcahScoreboard("base", None)
    base.build_phase()
    disarm_sim_time_filters()
    base.add_feature("f")
    try:
        base.push_observed("f", 1)
        base.push_expected("f", 1)
    except OcahScoreboardError:
        LOG.info("ok: compare_pair must be implemented by the bench")
    else:
        raise SelftestFailure("base compare_pair accepted a pair")


def selftest_knobs() -> None:
    import os

    os.environ["OCAH_SELFTEST_KNOB"] = "0x10"
    os.environ["OCAH_SELFTEST_ZERO"] = "0"
    os.environ["OCAH_SELFTEST_EMPTY"] = ""
    check(OcahKnobs.get_int("OCAH_SELFTEST_KNOB", 1) == 16, "get_int parses 0x text")
    check(OcahKnobs.get_int("OCAH_SELFTEST_ABSENT", 7) == 7, "absent knob returns the default")
    check(OcahKnobs.get_int("OCAH_SELFTEST_EMPTY", 7) == 7, "empty knob is unset")
    check(
        OcahKnobs.is_set("OCAH_SELFTEST_KNOB") and not OcahKnobs.is_set("OCAH_SELFTEST_ZERO"),
        "is_set treats 0 as off",
    )
    check(
        OcahKnobs.has_value("OCAH_SELFTEST_ZERO")
        and not OcahKnobs.has_value("OCAH_SELFTEST_EMPTY"),
        "has_value sees an explicit 0",
    )
    try:
        OcahKnobs.get_int_min("OCAH_SELFTEST_ZERO", 5, 1)
    except ValueError:
        LOG.info("ok: a value below the minimum is a defect, not clamped")
    else:
        raise SelftestFailure("get_int_min clamped or accepted a value below the minimum")


def selftest_sequence_logger() -> None:
    """A sequence INFO record reaches a root handler under cocotb's default log levels."""
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    root = logging.getLogger()
    cocotb_logger = logging.getLogger("cocotb")
    saved = (root.handlers[:], root.level, cocotb_logger.level)
    # cocotb's default configuration: handler on the root, root left at WARNING,
    # only the `cocotb` hierarchy raised to INFO.
    root.handlers = [_Capture()]
    root.setLevel(logging.WARNING)
    cocotb_logger.setLevel(logging.INFO)
    try:
        seq = OcahSequence("selftest_seq")
        seq.log.info("sequence-info")
        logging.getLogger("selftest_bare").info("bare-info")
    finally:
        root.handlers, root.level = saved[0], saved[1]
        cocotb_logger.setLevel(saved[2])
    messages = [record.getMessage() for record in records]
    check(seq.log.name == "cocotb.selftest_seq", "sequence logger sits under the cocotb hierarchy")
    check("sequence-info" in messages, "sequence INFO record reaches the root handler")
    check("bare-info" not in messages, "a root-child logger's INFO record is dropped (control)")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("selftest_scoreboard").setLevel(logging.CRITICAL)
    for step in (
        selftest_rng,
        selftest_knobs,
        selftest_scoreboard_pairing,
        selftest_scoreboard_flush_and_unpaired,
        selftest_scoreboard_verdicts,
        selftest_sequence_logger,
    ):
        LOG.info("---- %s", step.__name__)
        step()
    LOG.info("ocah_lib selftest PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
