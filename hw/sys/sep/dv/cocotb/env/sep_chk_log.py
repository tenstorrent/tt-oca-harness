# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Record every graded check of a leaf and give the leaf one verdict at its end.

A leaf makes one ``SepChkLog`` and grades each contract through it:

* ``ok(name, cond, **fields)`` logs ``CHK-<NAME> PASS: seed=<n> <fields>`` or
  ``CHK-<NAME> FAIL: seed=<n> <fields>``. A FAIL is recorded and the leaf
  continues, so one run reports every check, not only the first that fails.
* ``ctrl(name, cond, **fields)`` logs ``CTRL-<NAME> ...``. A false control logs
  ``CTRL-MISSING <NAME>`` and is recorded as a failure: a check whose control
  did not show the healthy behaviour proves nothing.
* ``obs(name, **fields)`` logs ``OBS-<NAME> ...`` and ``blocked(check, reason)``
  logs ``OBS-BLOCKED CHK-<NAME> reason=<r>``. Neither grades anything.
* ``finish()`` is the verdict. It raises ``AssertionError`` if any check or
  control failed, or if no check passed. Otherwise it hands the
  ``RESULT <leaf> seed=<n> PASS checks=<k>`` line to ``result_pass`` of the
  base test.

A leaf cannot end without the verdict. The constructor wraps the evidence gate
of the base test (``_finalize_evidence``, which ``run_phase`` calls after
``run_scenario`` returns), so a leaf that returns without ``finish()`` fails
there. Each FAIL and each missing control is also appended to
``test.env.scoreboard.errors``, which ``SepScoreboard.check_phase`` fails on.

A ``CHK-<NAME> PASS`` line is the evidence the base test counts
(``_EvidenceFilter`` in ``tests/sep_base_test.py``); a FAIL, CTRL or OBS line
is not. Names are upper case: ``[A-Z0-9_-]``, with or without the ``CHK-``
prefix. Field values print as given: ``bool`` as 0/1, ``int`` in decimal, a
list as ``[a,b]``; pass a register value as a string, e.g. ``f"0x{v:08x}"``.
"""

from __future__ import annotations

import re
from typing import Any

_NAME = re.compile(r"^[A-Z0-9][A-Z0-9_-]*$")


def _name(name: str) -> str:
    base = name[4:] if name.startswith("CHK-") else name
    if not _NAME.match(base):
        raise ValueError(f"check name {name!r} is not [A-Z0-9_-]")
    return base


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_fmt(v) for v in value) + "]"
    text = str(value)
    return repr(text) if (not text or any(c.isspace() for c in text)) else text


class SepChkLog:
    """Graded-check recorder and end-of-leaf verdict of one leaf.

    ``test`` is the running ``SepBaseTest``; ``entry`` is the leaf name printed
    in the ``RESULT`` line; ``seed`` is the leaf seed printed on every line.
    """

    def __init__(self, test: Any, entry: str, seed: int) -> None:
        if getattr(test, "_sep_chk_log", None) is not None:
            raise RuntimeError(f"{entry}: a SepChkLog already exists for this test")
        self._test = test
        self._entry = entry
        self._seed = seed
        self._log = test.logger
        self._passed: set[str] = set()
        self._failed: dict[str, int] = {}
        self._ctrl_missing: dict[str, int] = {}
        self._lines: list[str] = []
        self._finished = False
        test._sep_chk_log = self

        gate = test._finalize_evidence

        def _gate_with_verdict() -> None:
            if not self._finished:
                raise AssertionError(
                    f"{self._entry}: the leaf ended without SepChkLog.finish(); "
                    "a leaf without its verdict call cannot pass"
                )
            gate()

        test._finalize_evidence = _gate_with_verdict

    # -- recording -----------------------------------------------------------

    def _line(self, head: str, fields: dict[str, Any]) -> str:
        parts = [head, f"seed={self._seed}"]
        parts += [f"{k}={_fmt(v)}" for k, v in fields.items()]
        return " ".join(parts)

    def _record_error(self, line: str) -> None:
        self._lines.append(line)
        env = getattr(self._test, "env", None)
        scoreboard = getattr(env, "scoreboard", None)
        errors = getattr(scoreboard, "errors", None)
        if errors is not None:
            errors.append(line)

    def _open(self, what: str) -> None:
        if self._finished:
            raise RuntimeError(f"{self._entry}: {what} after SepChkLog.finish() is not graded")

    def ok(self, name: str, cond: bool, **fields: Any) -> bool:
        """Grade one check. Returns ``cond`` so the leaf can branch on it."""
        self._open(f"CHK-{name}")
        base = _name(name)
        cond = bool(cond)
        if cond:
            self._passed.add(base)
            self._log.info(self._line(f"CHK-{base} PASS:", fields))
        else:
            self._failed[base] = self._failed.get(base, 0) + 1
            line = self._line(f"CHK-{base} FAIL:", fields)
            self._log.error(line)
            self._record_error(line)
        return cond

    def ctrl(self, name: str, cond: bool, **fields: Any) -> bool:
        """Log one control. A false control is a recorded failure."""
        self._open(f"CTRL-{name}")
        base = _name(name)
        cond = bool(cond)
        self._log.info(self._line(f"CTRL-{base} {'seen' if cond else 'absent'}:", fields))
        if not cond:
            self._ctrl_missing[base] = self._ctrl_missing.get(base, 0) + 1
            line = self._line(f"CTRL-MISSING {base}:", fields)
            self._log.error(line)
            self._record_error(line)
        return cond

    def obs(self, name: str, **fields: Any) -> None:
        """Log one observation. It grades nothing and never fails the leaf."""
        self._log.info(self._line(f"OBS-{_name(name)}", fields))

    def blocked(self, check: str, reason: str) -> None:
        """Log a check that this leaf cannot grade. It earns no credit."""
        self._log.info(f"OBS-BLOCKED CHK-{_name(check)} reason={_fmt(reason)} seed={self._seed}")

    # -- verdict -------------------------------------------------------------

    def checks(self) -> int:
        """Number of distinct graded names that passed and never failed."""
        return len(self._passed - set(self._failed))

    @property
    def failures(self) -> int:
        """Number of FAIL lines plus missing controls recorded so far."""
        return sum(self._failed.values()) + sum(self._ctrl_missing.values())

    def finish(self, extra: str = "") -> None:
        """Give the leaf verdict. Raises unless every check passed and one ran.

        Call it once, as the last step of ``run_scenario``.
        """
        if self._finished:
            raise RuntimeError(f"{self._entry}: SepChkLog.finish() called twice")
        self._finished = True
        if self.failures:
            raise AssertionError(
                f"{self._entry} seed={self._seed}: {self.failures} graded failure(s) "
                f"(checks {sorted(self._failed)}, controls {sorted(self._ctrl_missing)}): "
                + "; ".join(self._lines)
            )
        if not self._passed:
            raise AssertionError(
                f"{self._entry} seed={self._seed}: no graded check ran; "
                "a leaf that grades nothing cannot pass"
            )
        self._test.result_pass(self._entry, self._seed, self.checks(), extra)
