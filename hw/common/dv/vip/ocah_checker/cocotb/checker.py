# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Protocol-neutral checker evidence and finalization helpers."""

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
        self.required_ids = frozenset(
            self._validate_id(check_id) for check_id in required_ids
        )
        self.findings: list[OcahCheckFinding] = []
        self._seen_ids: set[str] = set()

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

    def clear(self) -> None:
        """Reset retained evidence and required-ID observations."""
        self.findings.clear()
        self._seen_ids.clear()

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

    def finalize(self) -> None:
        """Emit a summary and fail on errors, zero checks, or missing IDs."""
        failures = self.failures
        missing = sorted(self.missing_ids)
        summary = (
            f"CHECKER_SUMMARY name={self.name} checks={self.check_count} "
            f"passed={self.pass_count} failed={len(failures)} missing={len(missing)}"
        )

        problems: list[str] = []
        if self.check_count == 0:
            problems.append("zero checks executed")
        if failures:
            problems.append(
                "failed IDs: " + ", ".join(finding.check_id for finding in failures)
            )
        if missing:
            problems.append("missing required IDs: " + ", ".join(missing))

        if problems:
            self.log.error(summary)
            raise OcahCheckerError(f"{summary}; {'; '.join(problems)}")
        self.log.info(summary)

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
            raise ValueError(
                f"invalid checker ID {check_id!r}; expected CHK-[A-Z0-9][A-Z0-9_-]*"
            )
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
