# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Protocol-neutral checker evidence and finalization helpers.

One ``CHK-<ID> PASS|FAIL expected=<v> observed=<v> context=<c>`` line per
comparison, one ``CHECKER_SUMMARY`` per finalization. The SV-UVM twin is
``uvm/ocah_checker.svh``; both realizations accept the same identifier
grammar, render values the same way, and reject the same defects at
finalization: a retained failure, a missing required identifier, zero checks
(unless the caller declares the stream idle), and a second finalization.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

__all__ = ["OcahCheckFinding", "OcahChecker", "OcahCheckerError"]

_CHECK_ID_RE = re.compile(r"^CHK-[A-Z0-9][A-Z0-9_-]*$")
CheckStatus = Literal["PASS", "FAIL"]


class OcahCheckerError(AssertionError):
    """Raised when an OCAH checker comparison or finalization fails."""


@dataclass(frozen=True)
class OcahCheckFinding:
    """One immutable named checker result."""

    check_id: str
    status: CheckStatus
    expected: Any
    observed: Any
    context: str
    message: str

    @property
    def passed(self) -> bool:
        return self.status == "PASS"


class OcahChecker:
    """Named exact-value evidence with strict finalization.

    This class owns protocol-neutral evidence mechanics only. Protocol legality
    belongs in the checker shipped by each ``ocah_<protocol>_vip`` package.
    """

    def __init__(
        self,
        *,
        name: str = "OcahChecker",
        required_ids: Iterable[str] = (),
        fail_fast: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.fail_fast = fail_fast
        self.log = logger or logging.getLogger(name)
        self.required_ids = frozenset(self._validate_id(check_id) for check_id in required_ids)
        self.findings: list[OcahCheckFinding] = []
        self._seen_ids: set[str] = set()
        self._finalized = False

    @property
    def check_count(self) -> int:
        return len(self.findings)

    @property
    def pass_count(self) -> int:
        return sum(finding.passed for finding in self.findings)

    @property
    def failures(self) -> list[OcahCheckFinding]:
        return [finding for finding in self.findings if not finding.passed]

    @property
    def missing_ids(self) -> set[str]:
        return set(self.required_ids - self._seen_ids)

    @property
    def finalized(self) -> bool:
        """Whether ``finalize()`` has run since construction or the last ``clear()``."""
        return self._finalized

    def clear(self) -> None:
        """Reset retained evidence, required-ID observations, and the finalized state."""
        self.findings.clear()
        self._seen_ids.clear()
        self._finalized = False

    # ------------------------------------------------------------------
    # Comparisons
    # ------------------------------------------------------------------

    def expect_equal(
        self,
        check_id: str,
        observed: Any,
        expected: Any,
        *,
        context: str = "",
    ) -> bool:
        """Compare exact values and emit one named evidence record."""
        return self._record(
            check_id,
            passed=observed == expected,
            expected=expected,
            observed=observed,
            context=context,
        )

    def expect_true(
        self,
        check_id: str,
        condition: Any,
        *,
        context: str = "",
    ) -> bool:
        """Require a truthy condition with explicit boolean evidence."""
        return self.expect_equal(check_id, bool(condition), True, context=context)

    # ------------------------------------------------------------------
    # Timeout evidence
    # ------------------------------------------------------------------

    def expect_not_timed_out(
        self,
        check_id: str,
        *,
        timed_out: bool,
        timeout_ns: float,
        context: str = "",
    ) -> bool:
        """Require completion within a declared transaction timeout."""
        return self.expect_equal(
            check_id,
            bool(timed_out),
            False,
            context=self._timeout_context(timeout_ns, context),
        )

    def expect_timeout(
        self,
        check_id: str,
        *,
        timed_out: bool,
        timeout_ns: float,
        context: str = "",
    ) -> bool:
        """Require an explicitly expected, bounded transaction timeout."""
        return self.expect_equal(
            check_id,
            bool(timed_out),
            True,
            context=self._timeout_context(timeout_ns, context),
        )

    # ------------------------------------------------------------------
    # Reset, interrupt, and status evidence
    # ------------------------------------------------------------------

    def expect_rw1c(
        self,
        check_id: str,
        *,
        before: int,
        after: int,
        mask: int,
        context: str = "",
    ) -> bool:
        """A write-one-to-clear status: the ``mask`` bits were set in ``before`` and are clear in ``after``.

        Bits outside ``mask`` are not judged. The record shows the masked
        value after the clearing write against zero; the context carries both
        raw reads and whether the precondition held.
        """
        set_before = (int(before) & int(mask)) == int(mask)
        return self._record(
            check_id,
            passed=set_before and (int(after) & int(mask)) == 0,
            expected=0,
            observed=int(after) & int(mask),
            context=self._status_context(
                context,
                f"before=0x{int(before):x} after=0x{int(after):x} mask=0x{int(mask):x} "
                f"set_before={'true' if set_before else 'false'}",
            ),
        )

    def expect_sticky(
        self,
        check_id: str,
        *,
        first: int,
        second: int,
        mask: int,
        context: str = "",
    ) -> bool:
        """A sticky status: the ``mask`` bits read set in ``first`` and again in ``second``.

        The second read follows the first without a clearing write, so a
        pulse that has already returned to zero fails the rule.
        """
        set_first = (int(first) & int(mask)) == int(mask)
        return self._record(
            check_id,
            passed=set_first and (int(second) & int(mask)) == int(mask),
            expected=int(mask),
            observed=int(second) & int(mask),
            context=self._status_context(
                context,
                f"first=0x{int(first):x} second=0x{int(second):x} mask=0x{int(mask):x} "
                f"set_first={'true' if set_first else 'false'}",
            ),
        )

    def expect_pulse(
        self,
        check_id: str,
        *,
        asserted: bool,
        deasserted: bool,
        context: str = "",
    ) -> bool:
        """A pulse-only event: asserted for the event and deasserted after completion.

        The record encodes ``asserted`` in bit 1 and ``deasserted`` in bit 0,
        so a pulse that never fired reads ``0x1`` and one that stayed high
        reads ``0x2`` against the expected ``0x3``.
        """
        observed = (int(bool(asserted)) << 1) | int(bool(deasserted))
        return self._record(
            check_id,
            passed=observed == 0x3,
            expected=0x3,
            observed=observed,
            context=self._status_context(
                context,
                f"asserted={'true' if asserted else 'false'} "
                f"deasserted={'true' if deasserted else 'false'}",
            ),
        )

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self, *, require_checks: bool = True) -> None:
        """Emit the summary once and fail on errors, missing IDs, or zero checks.

        ``require_checks=False`` declares the checker's stream idle for this
        scenario, so zero checks pass; a retained failure or a missing
        required identifier still fails. A second call without an intervening
        ``clear()`` fails: one checker reports one summary.
        """
        if self._finalized:
            message = f"CHECKER name={self.name} finalize() called more than once"
            self.log.error(message)
            raise OcahCheckerError(message)
        self._finalized = True
        failures = self.failures
        missing = sorted(self.missing_ids)
        summary = (
            f"CHECKER_SUMMARY name={self.name} checks={self.check_count} "
            f"passed={self.pass_count} failed={len(failures)} missing={len(missing)}"
        )

        problems: list[str] = []
        if require_checks and self.check_count == 0:
            problems.append("zero checks executed")
        if failures:
            problems.append("failed IDs: " + ", ".join(finding.check_id for finding in failures))
        if missing:
            problems.append("missing required IDs: " + ", ".join(missing))

        if problems:
            self.log.error(summary)
            raise OcahCheckerError(f"{summary}; {'; '.join(problems)}")
        self.log.info(summary)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _record(
        self,
        check_id: str,
        *,
        passed: bool,
        expected: Any,
        observed: Any,
        context: str,
    ) -> bool:
        check_id = self._validate_id(check_id)
        status: CheckStatus = "PASS" if passed else "FAIL"
        normalized_context = self._normalize_context(context)
        message = (
            f"{check_id} {status} expected={self._format_value(expected)} "
            f"observed={self._format_value(observed)} context={normalized_context}"
        )
        finding = OcahCheckFinding(
            check_id=check_id,
            status=status,
            expected=expected,
            observed=observed,
            context=normalized_context,
            message=message,
        )
        self.findings.append(finding)
        self._seen_ids.add(check_id)

        if passed:
            self.log.info(message)
            return True

        self.log.error(message)
        if self.fail_fast:
            raise OcahCheckerError(message)
        return False

    @staticmethod
    def _validate_id(check_id: str) -> str:
        if not isinstance(check_id, str) or not _CHECK_ID_RE.fullmatch(check_id):
            raise ValueError(f"invalid checker ID {check_id!r}; expected CHK-[A-Z0-9][A-Z0-9_-]*")
        return check_id

    @staticmethod
    def _normalize_context(context: str) -> str:
        normalized = " ".join(str(context).split())
        return normalized or "-"

    @staticmethod
    def _format_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int):
            return hex(value)
        if isinstance(value, (bytes, bytearray)):
            return "0x" + bytes(value).hex()
        return repr(value)

    @staticmethod
    def _timeout_context(timeout_ns: float, context: str) -> str:
        bound = f"timeout_ns={timeout_ns}"
        return f"{context} {bound}".strip()

    @staticmethod
    def _status_context(context: str, fields: str) -> str:
        return f"{context} {fields}".strip()
