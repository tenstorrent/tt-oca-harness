# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Frame-level UART checker over the shared evidence core.

``OcahUartChecker`` compares the frames one side drove with the frames the
other side reconstructed, judges their classification and wire timing, and
emits one ``CHK-UART-*`` record per rule through ``ocah_checker.OcahChecker``:

===========================  ==============================================================
``CHK-UART-DATA``            the data values sampled on a line equal, in order, the values sent
``CHK-UART-CLEAN``           no sampled frame carries a framing, parity, or break flag
``CHK-UART-BAUD``            the wire bit period measured from the start edge to the first
                             rising edge equals ``round(1e9 / baud)`` ns on every measurable frame
``CHK-UART-IDLE-HIGH``       the line rested at the idle level when sampling began
``CHK-UART-NONVAC``          at least the required number of frames arrived and one of them
                             carries both 0 and 1 data bits
``CHK-UART-CLASSIFY``        the per-frame ``(data, framing_error, parity_error, is_break)``
                             sequence equals the injected one
``CHK-UART-FRAMING-ERROR``   the sampler flagged exactly the injected bad-stop frames
``CHK-UART-PARITY-ERROR``    the sampler flagged exactly the injected inverted-parity frames
``CHK-UART-BREAK``           the sampler classified exactly the injected breaks
``CHK-UART-GLITCH``          sub-half-bit pulses produced glitch counts and no frame
``CHK-UART-ERROR-COUNT``     the sampler's error counters equal the injected fault counts
``CHK-UART-TIMEOUT``         a read on a silent line reported its timeout
``CHK-UART-TIMEOUT-BOUND``   that timeout took exactly the declared time
``CHK-UART-NO-TIMEOUT``      a read with data present completed under its bound
``CHK-UART-STATS``           observed counters equal the expected ones
``CHK-UART-BAUD-DETECT``     a sampler at the wrong baud rate does not deliver the sent values as
                             clean frames
===========================  ==============================================================

The checker holds no simulator handles: it takes ``OcahUartFrame`` sequences,
plain integers, and statistics mappings, so it judges VIP-to-VIP traffic on
the selftest harness and DUT traffic on a bench alike. ``finalize()`` prints a
tally and fails on any failed or missing record. The checker has no SV-UVM
twin: the package ships the cocotb realization only.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ocah_checker import OcahChecker

from .ocah_uart_types import OcahUartFrame, bit_period_ns

__all__ = ["OcahUartChecker"]

Flags = tuple[int, bool, bool, bool]


def _values(frames: Iterable[OcahUartFrame | int]) -> list[int]:
    return [frame.data if isinstance(frame, OcahUartFrame) else int(frame) for frame in frames]


def _classification(frames: Iterable[OcahUartFrame]) -> list[Flags]:
    return [
        (frame.data, frame.framing_error, frame.parity_error, frame.is_break) for frame in frames
    ]


def _hex(values: Sequence[int]) -> str:
    return "[" + " ".join(f"{value:02x}" for value in values) + "]"


class OcahUartChecker:
    """Judges driven frames against sampled frames and records ``CHK-UART-*`` evidence."""

    def __init__(
        self,
        *,
        name: str = "OcahUartChecker",
        required_ids: Iterable[str] = (),
        raise_on_error: bool = True,
        logger: logging.Logger | None = None,
    ) -> None:
        self.name = name
        self.log = logger or logging.getLogger(name)
        self.evidence = OcahChecker(
            name=name, required_ids=required_ids, fail_fast=raise_on_error, logger=self.log
        )
        self._frames_judged = 0
        self._faults_judged = 0
        self._timeouts_judged = 0

    def clear(self) -> None:
        """Forget every record and tally."""
        self.evidence.clear()
        self._frames_judged = self._faults_judged = self._timeouts_judged = 0

    # ------------------------------------------------------------------
    # Data-path rules
    # ------------------------------------------------------------------

    def check_data(
        self,
        sent: Sequence[OcahUartFrame | int],
        observed: Sequence[OcahUartFrame],
        *,
        label: str,
        context: str = "",
    ) -> bool:
        """The values sampled on ``label`` equal, in order, the values sent."""
        got = _values(observed)
        want = _values(sent)
        self._frames_judged += len(got)
        return self.expect_equal(
            "CHK-UART-DATA",
            _hex(got),
            _hex(want),
            context=f"line={label} sent={len(want)} sampled={len(got)} {context}",
        )

    def check_clean(
        self, observed: Sequence[OcahUartFrame], *, label: str, context: str = ""
    ) -> bool:
        """No sampled frame on ``label`` carries a framing, parity, or break flag."""
        flagged = [frame for frame in observed if not frame.clean]
        first = "-" if not flagged else f"0x{flagged[0].data:02x}@{flagged[0].start_ns}ns"
        return self.expect_equal(
            "CHK-UART-CLEAN",
            len(flagged),
            0,
            context=f"line={label} frames={len(observed)} first_flagged={first} {context}",
        )

    def check_baud(
        self,
        observed: Sequence[OcahUartFrame],
        baud: int,
        *,
        label: str,
        context: str = "",
    ) -> bool:
        """Every measurable frame on ``label`` shows the bit period of ``baud`` on the wire.

        A frame is measurable when the sampler recorded the first rising edge
        after its start edge and its data is not zero; a scenario whose frames
        are all unmeasurable fails the rule.
        """
        expected = bit_period_ns(baud)
        measured = [frame.measured_bit_ns for frame in observed]
        periods = [value for value in measured if value is not None]
        wrong = sorted({value for value in periods if value != expected})
        passed = bool(periods) and not wrong
        return self.expect_true(
            "CHK-UART-BAUD",
            passed,
            context=(
                f"line={label} baud={baud} expected_ns={expected} measured={len(periods)}/"
                f"{len(measured)} wrong_ns={wrong} {context}"
            ),
        )

    def check_idle_high(self, level: int | None, *, label: str, context: str = "") -> bool:
        """The line rested at the idle (high) level when sampling began."""
        return self.expect_equal("CHK-UART-IDLE-HIGH", level, 1, context=f"line={label} {context}")

    def check_nonvacuous(
        self,
        observed: Sequence[OcahUartFrame],
        *,
        label: str,
        min_frames: int = 1,
        context: str = "",
    ) -> bool:
        """At least ``min_frames`` frames arrived and one carries both 0 and 1 data bits."""
        mixed = [frame for frame in observed if frame.data not in (0, (1 << frame.bits) - 1)]
        return self.expect_true(
            "CHK-UART-NONVAC",
            len(observed) >= min_frames and bool(mixed),
            context=(
                f"line={label} frames={len(observed)} min={min_frames} mixed={len(mixed)} {context}"
            ),
        )

    def check_line(
        self,
        sent: Sequence[OcahUartFrame | int],
        observed: Sequence[OcahUartFrame],
        *,
        baud: int,
        label: str,
        min_frames: int = 1,
        context: str = "",
    ) -> bool:
        """Data, clean, baud, and non-vacuity rules over one line."""
        passed = self.check_data(sent, observed, label=label, context=context)
        passed &= self.check_clean(observed, label=label, context=context)
        passed &= self.check_baud(observed, baud, label=label, context=context)
        passed &= self.check_nonvacuous(
            observed, label=label, min_frames=min_frames, context=context
        )
        return passed

    # ------------------------------------------------------------------
    # Fault rules
    # ------------------------------------------------------------------

    def check_classification(
        self,
        observed: Sequence[OcahUartFrame],
        expected: Sequence[OcahUartFrame],
        *,
        label: str,
        context: str = "",
    ) -> bool:
        """The sampled ``(data, framing, parity, break)`` sequence equals the injected one.

        Per fault kind present in ``expected``, the sampler's count of that
        kind is recorded as its own rule. A break is not counted as a framing
        error.
        """
        got = _classification(observed)
        want = _classification(expected)
        self._frames_judged += len(got)
        passed = self.expect_equal(
            "CHK-UART-CLASSIFY",
            got,
            want,
            context=f"line={label} frames={len(got)} expected={len(want)} {context}",
        )
        kinds = (
            ("CHK-UART-FRAMING-ERROR", lambda f: f.framing_error and not f.is_break),
            ("CHK-UART-PARITY-ERROR", lambda f: f.parity_error),
            ("CHK-UART-BREAK", lambda f: f.is_break),
        )
        for check_id, rule in kinds:
            wanted = sum(1 for frame in expected if rule(frame))
            if wanted == 0:
                continue
            self._faults_judged += wanted
            seen = sum(1 for frame in observed if rule(frame))
            passed &= self.expect_equal(
                check_id, seen, wanted, context=f"line={label} frames={len(got)} {context}"
            )
        return passed

    def check_glitches(
        self,
        stats: Mapping[str, int],
        expected: int,
        *,
        frames_expected: int,
        frames_observed: int,
        label: str,
        context: str = "",
    ) -> bool:
        """``expected`` glitches were counted and produced no frame."""
        self._faults_judged += expected
        return self.expect_equal(
            "CHK-UART-GLITCH",
            (int(stats.get("glitches", 0)), frames_observed),
            (expected, frames_expected),
            context=f"line={label} (glitches, frames) {context}",
        )

    def check_error_counts(
        self,
        stats: Mapping[str, int],
        *,
        label: str,
        framing_errors: int = 0,
        parity_errors: int = 0,
        breaks: int = 0,
        glitches: int = 0,
        context: str = "",
    ) -> bool:
        """The sampler's error counters equal the injected fault counts."""
        keys = ("framing_errors", "parity_errors", "breaks", "glitches")
        want = dict(zip(keys, (framing_errors, parity_errors, breaks, glitches)))
        got = {key: int(stats.get(key, 0)) for key in keys}
        return self.expect_equal(
            "CHK-UART-ERROR-COUNT", got, want, context=f"line={label} {context}"
        )

    def check_baud_mismatch(
        self,
        sent: Sequence[OcahUartFrame | int],
        observed: Sequence[OcahUartFrame],
        *,
        label: str,
        context: str = "",
    ) -> bool:
        """A sampler at the wrong rate does not deliver the sent values as clean frames."""
        equal = _values(observed) == _values(sent)
        clean = all(frame.clean for frame in observed)
        return self.expect_true(
            "CHK-UART-BAUD-DETECT",
            not (equal and clean),
            context=(
                f"line={label} sent={len(sent)} sampled={len(observed)} equal={equal} "
                f"clean={clean} {context}"
            ),
        )

    # ------------------------------------------------------------------
    # Timeout rules
    # ------------------------------------------------------------------

    def check_timeout(
        self,
        *,
        timed_out: bool,
        elapsed_ns: float,
        timeout_us: int,
        label: str,
        context: str = "",
    ) -> bool:
        """A read on a silent line timed out, and took exactly ``timeout_us``."""
        self._timeouts_judged += 1
        bound_ns = int(timeout_us) * 1000
        passed = bool(
            self.evidence.expect_timeout(
                "CHK-UART-TIMEOUT",
                timed_out=timed_out,
                timeout_ns=bound_ns,
                context=f"op={label} {context}",
            )
        )
        passed &= self.expect_equal(
            "CHK-UART-TIMEOUT-BOUND",
            round(elapsed_ns),
            bound_ns,
            context=f"op={label} elapsed_ns={round(elapsed_ns)} {context}",
        )
        return passed

    def check_completed(
        self, *, timed_out: bool, timeout_us: int, label: str, context: str = ""
    ) -> bool:
        """A read with data present completed under its bound."""
        return bool(
            self.evidence.expect_not_timed_out(
                "CHK-UART-NO-TIMEOUT",
                timed_out=timed_out,
                timeout_ns=int(timeout_us) * 1000,
                context=f"op={label} {context}",
            )
        )

    # ------------------------------------------------------------------
    # Statistics, passthrough, finalization
    # ------------------------------------------------------------------

    def check_statistics(
        self,
        observed: Mapping[str, Any],
        expected: Mapping[str, Any],
        *,
        label: str,
        context: str = "",
    ) -> bool:
        """Every counter named in ``expected`` has that value in ``observed``."""
        got = {key: observed.get(key) for key in expected}
        return self.expect_equal(
            "CHK-UART-STATS", got, dict(expected), context=f"component={label} {context}"
        )

    def expect_equal(
        self, check_id: str, observed: Any, expected: Any, *, context: str = ""
    ) -> bool:
        """Emit one exact-value evidence record through the common core."""
        return bool(self.evidence.expect_equal(check_id, observed, expected, context=context))

    def expect_true(self, check_id: str, condition: Any, *, context: str = "") -> bool:
        """Emit one boolean evidence record through the common core."""
        return bool(self.evidence.expect_true(check_id, condition, context=context))

    def finalize(self) -> None:
        """Log the tally and finalize the evidence; raises on failed or missing records."""
        self.log.info(
            "UART_CHECKER_SUMMARY name=%s frames_judged=%d faults_judged=%d timeouts_judged=%d",
            self.name,
            self._frames_judged,
            self._faults_judged,
            self._timeouts_judged,
        )
        self.evidence.finalize()
