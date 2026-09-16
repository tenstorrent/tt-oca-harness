# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simulator-free selftest of the shared checker evidence core.

Every rule of the contract in ``hw/common/dv/docs/vip-checker-model.adoc`` is
exercised positively and then made to fail:

1. the identifier grammar, at construction and at record time;
2. the evidence grammar and value rendering of every record;
3. fail-fast raising after the finding is retained, and aggregate collection;
4. finalization rejecting a retained failure, a missing required identifier,
   zero checks, and a second call; ``require_checks=False`` declaring an idle
   stream; ``clear()`` re-arming;
5. the timeout evidence in both directions with the bound in the context;
6. the reset, interrupt, and status helpers (write-one-to-clear, sticky,
   pulse) with their preconditions;
7. immutability of retained findings.

Run from the repository root::

    uv run --locked --group dv python \\
      hw/common/dv/vip/ocah_checker/cocotb/examples/example_checker_selftest.py
"""

from __future__ import annotations

import dataclasses
import logging
import re
from collections.abc import Callable

from ocah_checker import OcahChecker, OcahCheckerError

LOG = logging.getLogger("ocah_checker.selftest")
_LINE = re.compile(r"^CHK-[A-Z0-9][A-Z0-9_-]* (PASS|FAIL) expected=\S+ observed=\S+ context=\S.*$")
_QUIET = logging.getLogger("ocah_checker.selftest.quiet")
_QUIET.setLevel(logging.CRITICAL)


class SelftestFailure(AssertionError):
    """A contract rule the core did not honour."""


def check(condition: bool, what: str) -> None:
    if not condition:
        raise SelftestFailure(what)
    LOG.info("ok: %s", what)


def rejects(action: Callable[[], object], what: str, *, needle: str = "") -> str:
    """``action`` must raise ``OcahCheckerError`` whose text carries ``needle``."""
    try:
        action()
    except OcahCheckerError as exc:
        text = str(exc)
        check(needle in text, f"{what} ({needle!r} in {text!r})" if needle else what)
        return text
    raise SelftestFailure(f"{what}: no OcahCheckerError raised")


def quiet(**kwargs: object) -> OcahChecker:
    return OcahChecker(logger=_QUIET, **kwargs)  # type: ignore[arg-type]


# ----------------------------------------------------------------------
# 1. identifier grammar
# ----------------------------------------------------------------------


def selftest_identifier_grammar() -> None:
    for good in ("CHK-A", "CHK-0", "CHK-DATA-1", "CHK-A_B-C9"):
        quiet(required_ids=(good,))
    for bad in ("chk-a", "CHK-", "CHK--A", "CHK-_A", "CHK-a", "DATA", "CHK-A B", "CHK-A.B"):
        try:
            quiet(required_ids=(bad,))
        except ValueError:
            continue
        raise SelftestFailure(f"invalid required ID {bad!r} accepted at construction")
    check(True, "identifier grammar CHK-[A-Z0-9][A-Z0-9_-]* enforced at construction")
    checker = quiet()
    try:
        checker.expect_true("CHK-lower", True)
    except ValueError:
        check(checker.check_count == 0, "an invalid ID records nothing")
    else:
        raise SelftestFailure("invalid ID accepted at record time")


# ----------------------------------------------------------------------
# 2. evidence grammar and rendering
# ----------------------------------------------------------------------


def selftest_rendering() -> None:
    checker = quiet(fail_fast=False)
    checker.expect_equal("CHK-INT", 0xA5, 0xA5, context="addr=0x1000")
    checker.expect_equal("CHK-BOOL", True, False)
    checker.expect_equal("CHK-BYTES", b"\x01\xff", b"\x01\xff", context="  two\n  lines  ")
    checker.expect_equal("CHK-STR", "abc", "abc")
    checker.expect_equal("CHK-ZERO", 0, 0)
    messages = [finding.message for finding in checker.findings]
    check(all(_LINE.fullmatch(message) for message in messages), "every record matches the grammar")
    check(messages[0] == "CHK-INT PASS expected=0xa5 observed=0xa5 context=addr=0x1000", "int hex")
    check(
        messages[1] == "CHK-BOOL FAIL expected=false observed=true context=-",
        "bool lowercase, empty context",
    )
    check(
        messages[2] == "CHK-BYTES PASS expected=0x01ff observed=0x01ff context=two lines",
        "bytes hex, context whitespace collapsed",
    )
    check(
        messages[3] == "CHK-STR PASS expected='abc' observed='abc' context=-", "other values repr"
    )
    check(messages[4].startswith("CHK-ZERO PASS expected=0x0 observed=0x0"), "zero renders 0x0")
    check(checker.pass_count == 4 and len(checker.failures) == 1, "counters follow the records")


# ----------------------------------------------------------------------
# 3. fail-fast and aggregate modes
# ----------------------------------------------------------------------


def selftest_modes() -> None:
    fast = quiet()
    rejects(lambda: fast.expect_equal("CHK-FAST", 1, 2), "fail-fast raises", needle="CHK-FAST FAIL")
    check(
        fast.check_count == 1 and not fast.findings[0].passed, "fail-fast retains the finding first"
    )
    aggregate = quiet(fail_fast=False)
    check(aggregate.expect_equal("CHK-AGG", 1, 2) is False, "aggregate returns False")
    check(aggregate.expect_equal("CHK-AGG", 2, 2) is True, "aggregate returns True")
    rejects(
        aggregate.finalize, "aggregate finalization rejects the retained failure", needle="failed=1"
    )


# ----------------------------------------------------------------------
# 4. finalization
# ----------------------------------------------------------------------


def selftest_finalization() -> None:
    rejects(quiet().finalize, "zero checks rejected", needle="zero checks executed")

    idle = quiet()
    idle.finalize(require_checks=False)
    check(idle.finalized, "an idle stream declared with require_checks=False passes")

    missing = quiet(required_ids=("CHK-SEEN", "CHK-NEVER"))
    missing.expect_true("CHK-SEEN", True)
    check(missing.missing_ids == {"CHK-NEVER"}, "missing_ids names the unrecorded identifier")
    rejects(missing.finalize, "missing required ID rejected", needle="CHK-NEVER")

    idle_missing = quiet(required_ids=("CHK-NEVER",))
    rejects(
        lambda: idle_missing.finalize(require_checks=False),
        "an idle declaration does not excuse a missing required ID",
        needle="missing required IDs",
    )

    once = quiet()
    once.expect_true("CHK-ONCE", True)
    once.finalize()
    rejects(once.finalize, "a second finalize is rejected", needle="more than once")
    once.clear()
    check(
        not once.finalized and once.check_count == 0 and once.missing_ids == set(),
        "clear() re-arms finalization and forgets evidence",
    )
    rejects(once.finalize, "a cleared checker is empty again", needle="zero checks")

    twice = quiet(fail_fast=False)
    twice.expect_equal("CHK-TWICE", 1, 2)
    rejects(twice.finalize, "first finalize reports the failure", needle="failed=1")
    rejects(
        twice.finalize, "second finalize after a failure is still rejected", needle="more than once"
    )


# ----------------------------------------------------------------------
# 5. timeout evidence
# ----------------------------------------------------------------------


def selftest_timeouts() -> None:
    checker = quiet(fail_fast=False)
    check(
        checker.expect_not_timed_out("CHK-DONE", timed_out=False, timeout_ns=500, context="read"),
        "completion under the bound passes",
    )
    check(checker.findings[-1].context == "read timeout_ns=500", "the bound rides in the context")
    check(
        not checker.expect_not_timed_out("CHK-DONE", timed_out=True, timeout_ns=500),
        "an unexpected timeout fails",
    )
    check(
        checker.expect_timeout("CHK-BOUND", timed_out=True, timeout_ns=200),
        "an expected, bounded timeout passes",
    )
    check(
        not checker.expect_timeout("CHK-BOUND", timed_out=False, timeout_ns=200),
        "an expected timeout that completed fails",
    )
    check(
        checker.findings[-1].message.endswith("context=timeout_ns=200"), "bound with empty context"
    )


# ----------------------------------------------------------------------
# 6. reset, interrupt, and status helpers
# ----------------------------------------------------------------------


def selftest_status_helpers() -> None:
    checker = quiet(fail_fast=False)
    check(
        checker.expect_rw1c("CHK-RW1C", before=0x13, after=0x10, mask=0x03, context="csr=STATUS"),
        "write-one-to-clear: set before, clear after",
    )
    check(
        checker.findings[-1].message
        == "CHK-RW1C PASS expected=0x0 observed=0x0 context=csr=STATUS before=0x13 after=0x10 mask=0x3 set_before=true",
        "rw1c record shows the masked value after the write and the raw reads",
    )
    check(
        not checker.expect_rw1c("CHK-RW1C", before=0x10, after=0x10, mask=0x03),
        "rw1c: never set fails",
    )
    check(
        not checker.expect_rw1c("CHK-RW1C", before=0x13, after=0x11, mask=0x03),
        "rw1c: still set fails",
    )
    check(
        checker.expect_rw1c("CHK-RW1C", before=0xFF, after=0xF0, mask=0x0F),
        "rw1c: bits outside the mask are not judged",
    )

    check(
        checker.expect_sticky("CHK-STICKY", first=0x81, second=0x81, mask=0x80),
        "sticky: set twice passes",
    )
    check(
        not checker.expect_sticky("CHK-STICKY", first=0x81, second=0x01, mask=0x80),
        "sticky: dropped fails",
    )
    check(
        not checker.expect_sticky("CHK-STICKY", first=0x01, second=0x81, mask=0x80),
        "sticky: not set first fails",
    )

    check(
        checker.expect_pulse("CHK-PULSE", asserted=True, deasserted=True),
        "pulse: fired and released passes",
    )
    check(
        not checker.expect_pulse("CHK-PULSE", asserted=False, deasserted=True),
        "pulse: never fired fails",
    )
    check(
        not checker.expect_pulse("CHK-PULSE", asserted=True, deasserted=False),
        "pulse: stuck high fails",
    )
    check(
        checker.findings[-1].message
        == "CHK-PULSE FAIL expected=0x3 observed=0x2 context=asserted=true deasserted=false",
        "pulse record encodes both halves",
    )


# ----------------------------------------------------------------------
# 7. findings are immutable
# ----------------------------------------------------------------------


def selftest_findings_immutable() -> None:
    checker = quiet()
    checker.expect_true("CHK-FROZEN", True)
    finding = checker.findings[0]
    try:
        finding.status = "FAIL"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        check(finding.passed, "a retained finding cannot be rewritten")
    else:
        raise SelftestFailure("finding status was rewritten")


def positive_flow() -> None:
    logging.getLogger("ocah_checker.selftest.positive").setLevel(logging.INFO)
    checker = OcahChecker(
        name="core-positive",
        required_ids=("CHK-DATA", "CHK-NONVAC"),
        logger=logging.getLogger("ocah_checker.selftest.positive"),
    )
    checker.expect_equal("CHK-DATA", 0xA5, 0xA5, context="addr=0x1000")
    checker.expect_true("CHK-NONVAC", 0xA5 not in (0x00, 0xFF), context="observed=0xa5")
    checker.finalize()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    positive_flow()
    selftest_identifier_grammar()
    selftest_rendering()
    selftest_modes()
    selftest_finalization()
    selftest_timeouts()
    selftest_status_helpers()
    selftest_findings_immutable()
    LOG.info("ocah_checker selftest PASS")


if __name__ == "__main__":
    main()
