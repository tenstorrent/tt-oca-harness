# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Capture one sep-vp process over a single monotonic observation window."""

from __future__ import annotations

import os
import re
import signal
import time
from dataclasses import dataclass
from enum import Enum

import pexpect

_VERDICT_RE = re.compile(
    r"^\[VP\] SIMULATION OF THE TEST (PASSED|FAILED)\r?$",
    re.MULTILINE,
)


class StopReason(Enum):
    FIRMWARE_VERDICT = "firmware_verdict"
    TIMEOUT = "timeout"
    PROCESS_EXIT = "process_exit"
    SIMULATOR_CRASH = "simulator_crash"


@dataclass(frozen=True)
class RunResult:
    output: str
    stop_reason: StopReason
    duration: float
    exit_code: int | None
    signal: int | None
    firmware_verdict: str | None
    timed_out: bool
    harness_terminated: bool


def _text(value) -> str:
    return value if isinstance(value, str) else ""


def _close_and_status(child: pexpect.spawn) -> tuple[int | None, int | None]:
    child.close()
    return child.exitstatus, child.signalstatus


def _terminate(child: pexpect.spawn) -> None:
    if not child.isalive():
        return
    pid = getattr(child, "pid", None)
    if pid is not None:
        try:
            process_group = os.getpgid(pid)
            if process_group != os.getpgrp():
                os.killpg(process_group, signal.SIGKILL)
                return
        except (ProcessLookupError, PermissionError):
            pass
    child.terminate(force=True)


def _exited_result(
    child: pexpect.spawn,
    *,
    output: str,
    started: float,
    observed_at: float,
    verdict: str | None,
) -> RunResult:
    exit_code, term_signal = _close_and_status(child)
    return RunResult(
        output=output,
        stop_reason=(
            StopReason.SIMULATOR_CRASH if term_signal is not None else StopReason.PROCESS_EXIT
        ),
        duration=observed_at - started,
        exit_code=exit_code,
        signal=term_signal,
        firmware_verdict=verdict,
        timed_out=False,
        harness_terminated=False,
    )


def _terminated_result(
    child: pexpect.spawn,
    *,
    output: str,
    started: float,
    observed_at: float,
    reason: StopReason,
    verdict: str | None,
) -> RunResult:
    _terminate(child)
    exit_code, term_signal = _close_and_status(child)
    return RunResult(
        output=output,
        stop_reason=reason,
        duration=observed_at - started,
        exit_code=exit_code,
        signal=term_signal,
        firmware_verdict=verdict,
        timed_out=reason is StopReason.TIMEOUT,
        harness_terminated=True,
    )


def _supervise(
    child: pexpect.spawn,
    *,
    timeout: float,
    verdict_settle: float = 2.0,
) -> RunResult:
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    if verdict_settle < 0:
        raise ValueError("verdict_settle must not be negative")

    started = time.monotonic()
    deadline = started + timeout
    chunks = []

    remaining = max(0.0, deadline - time.monotonic())
    index = child.expect([_VERDICT_RE, pexpect.EOF, pexpect.TIMEOUT], timeout=remaining)
    chunks.append(_text(child.before))

    if index == 1:
        observed_at = time.monotonic()
        return _exited_result(
            child,
            output="".join(chunks),
            started=started,
            observed_at=observed_at,
            verdict=None,
        )
    if index == 2:
        observed_at = time.monotonic()
        if not child.isalive():
            return _exited_result(
                child,
                output="".join(chunks),
                started=started,
                observed_at=observed_at,
                verdict=None,
            )
        return _terminated_result(
            child,
            output="".join(chunks),
            started=started,
            observed_at=observed_at,
            reason=StopReason.TIMEOUT,
            verdict=None,
        )

    chunks.append(_text(child.after))
    verdict = child.match.group(1)
    verdict_observed_at = time.monotonic()
    settle_deadline = min(deadline, verdict_observed_at + verdict_settle)
    run_deadline_wins = deadline <= verdict_observed_at + verdict_settle
    remaining = max(0.0, settle_deadline - time.monotonic())
    settle_index = child.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=remaining)
    chunks.append(_text(child.before))
    observed_at = time.monotonic()

    if settle_index == 0 or not child.isalive():
        return _exited_result(
            child,
            output="".join(chunks),
            started=started,
            observed_at=observed_at,
            verdict=verdict,
        )
    return _terminated_result(
        child,
        output="".join(chunks),
        started=started,
        observed_at=observed_at,
        reason=StopReason.TIMEOUT if run_deadline_wins else StopReason.FIRMWARE_VERDICT,
        verdict=verdict,
    )


def supervise(
    child: pexpect.spawn,
    *,
    timeout: float,
    verdict_settle: float = 2.0,
) -> RunResult:
    """Observe *child* and guarantee teardown if the harness is interrupted."""
    try:
        return _supervise(
            child,
            timeout=timeout,
            verdict_settle=verdict_settle,
        )
    except BaseException:
        _terminate(child)
        child.close()
        raise
