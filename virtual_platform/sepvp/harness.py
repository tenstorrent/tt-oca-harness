# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Harness base — the backend-agnostic pexpect ``expect()`` API.

Mirrors the example bootcode harness (``sep_test/harness.py``): ordered, streaming,
substring/regex ``expect()`` with auto-fail on error patterns, plus ``expect_hex32`` and
``finish``. Adds ``expect_status()`` for the sep-vp ``[SEP_STATUS]`` production-status
lines (the analog of the example's decoded status-string asserts).

A backend (e.g. :class:`sepvp.sepvp_harness.SepVpHarness`) implements :meth:`spawn`,
which must set ``self.child`` to a live ``pexpect`` spawn.
"""

from __future__ import annotations

import logging
import re

import pexpect

log = logging.getLogger("sepvp")

# Decoded status/console lines lost their CSML prefixes in tt-oca-harness-model 0ec43f9cc, which folded
# sep_status_report + sep_virt_console into sep_scratch_cold and emits straight to std::cout:
#
#   old:  [174010 ns] [INFO 2] [SEP_STATUS] - BL0 ERROR    0x0213 SEP_MSG_MANIFEST_LOAD_FAILED
#   new:                                      BL0 ERROR    0x0213 SEP_MSG_MANIFEST_LOAD_FAILED
#
# Both prefixes are matched optionally so one harness drives either VP generation (useful when
# bisecting across the bump). Without the prefix to anchor on, the patterns instead pin the full
# line shape -- stage, padded severity, 4-hex code, SEP_MSG_ name -- so ordinary SIM_OUT text
# that happens to contain the word ERROR cannot masquerade as a production status line.
SEP_STATUS_PREFIX = r"(?:\[SEP_STATUS\] - )?"
SIM_OUT_PREFIX = r"(?:\[SIM_OUT\] - )?"

# Format of a decoded production-status line's message field (sep_status_decoder.h):
#   "<stage> <SEVERITY> 0x%04x <NAME>"  e.g. "BL0 INFO     0x0044 SEP_MSG_BOOTROM_START"
# The decoder pads the type field, so a literal-space match is unsafe — use ` +`.
_STATUS_BODY = r"{stage} +{type} +0x[0-9a-fA-F]{{4}} +{name}\b"
_STATUS_LINE = SEP_STATUS_PREFIX + _STATUS_BODY

# A production ERROR-type status line (the default negative assertion).
SEP_STATUS_ERROR_RE = SEP_STATUS_PREFIX + _STATUS_BODY.format(
    stage=r"\S+", type="ERROR", name=r"SEP_MSG_\w+"
)

# Any production status line, regardless of severity — for "no status was emitted" assertions.
SEP_STATUS_ANY_RE = SEP_STATUS_PREFIX + _STATUS_BODY.format(
    stage=r"\S+", type=r"\S+", name=r"SEP_MSG_\w+"
)


class HarnessError(Exception):
    """Raised when an expect sees an error pattern, hits EOF, or times out."""


class Harness:
    """Base harness: drives ``expect()`` over ``self.child`` (a pexpect spawn).

    Subclasses set ``self.child`` in :meth:`spawn`. ``default_error_patterns`` is the
    fallback negative-assertion set used when a caller does not pass ``error_patterns``.
    """

    default_timeout = 30
    default_error_patterns = (SEP_STATUS_ERROR_RE,)

    def __init__(self, config):
        self.config = config
        self.child: pexpect.spawn | None = None

    # -- backends implement this --
    def spawn(self):
        raise NotImplementedError

    # -- context-manager sugar --
    def __enter__(self):
        self.spawn()
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    # -- core expect -----------------------------------------------------------
    def expect(self, pattern, error_patterns=None, timeout=None):
        """Wait for *pattern* (regex/substring). Returns the match object.

        Any *error_patterns* (default: a production-ERROR line) that match first abort
        with :class:`HarnessError`; EOF also aborts. Pass ``error_patterns=[]`` to disable.
        """
        if self.child is None:
            raise HarnessError("expect() called before spawn()")
        timeout = self.default_timeout if timeout is None else timeout
        if error_patterns is None:
            error_patterns = list(self.default_error_patterns)
        else:
            error_patterns = list(error_patterns)

        patterns = [pattern, *error_patterns, pexpect.EOF]
        log.debug("expect %r (errors=%r, timeout=%s)", pattern, error_patterns, timeout)
        index = self.child.expect(patterns, timeout=timeout)
        if index == 0:
            return self.child.match
        if index == len(patterns) - 1:
            raise HarnessError(f"Hit EOF while looking for {pattern!r}")
        err = error_patterns[index - 1]
        # Let a little trailing context flush into the log before raising.
        self.child.expect([pexpect.TIMEOUT, pexpect.EOF], timeout=2)
        raise HarnessError(f"Saw error pattern {err!r} while looking for {pattern!r}")

    def expect_ignoring(self, pattern, ignore_patterns=(), error_patterns=None, timeout=None):
        """Like :meth:`expect`, but lines matching *ignore_patterns* are skipped, not fatal."""
        if self.child is None:
            raise HarnessError("expect_ignoring() called before spawn()")
        timeout = self.default_timeout if timeout is None else timeout
        if error_patterns is None:
            error_patterns = list(self.default_error_patterns)
        ignore_patterns = list(ignore_patterns)
        error_patterns = list(error_patterns)
        n_ignore = len(ignore_patterns)
        n_err = len(error_patterns)

        while True:
            patterns = [pattern, *ignore_patterns, *error_patterns, pexpect.EOF]
            index = self.child.expect(patterns, timeout=timeout)
            if index == 0:
                return self.child.match
            if 1 <= index <= n_ignore:
                log.debug("expect_ignoring skipped %r", ignore_patterns[index - 1])
                continue
            if index == 1 + n_ignore + n_err:
                raise HarnessError(f"Hit EOF while looking for {pattern!r}")
            err = error_patterns[index - 1 - n_ignore]
            self.child.expect([pexpect.TIMEOUT, pexpect.EOF], timeout=2)
            raise HarnessError(f"Saw error pattern {err!r} while looking for {pattern!r}")

    def expect_hex32(self, value_name, separator=" = ", timeout=None):
        """Match ``<value_name><sep>0xXXXXXXXX`` and return the int."""
        match = self.expect(
            rf"{re.escape(value_name)}{separator}(0x[0-9A-Fa-f]{{8}})", timeout=timeout
        )
        return int(match.group(1), 16)

    # -- SEP_STATUS production-status assertions -------------------------------
    def expect_status(self, name, type=None, fwid=None, timeout=None, allow_error=None):
        """Match a ``[SEP_STATUS]`` line by SEP_MSG name (optionally pinning type/fwid).

        *name* is matched exactly (``SEP_MSG_BOOTROM_START`` will not match
        ``SEP_MSG_BOOTROM_START_MAIN``). When the expected status is itself an ERROR
        (``type='ERROR'``, or ``allow_error=True``), the default ERROR error-pattern is
        suppressed so the target line is not treated as a failure.
        """
        stage = re.escape(fwid) if fwid else r"\S+"
        type_pat = re.escape(type) if type else r"\S+"
        pattern = _STATUS_LINE.format(stage=stage, type=type_pat, name=re.escape(name))

        if allow_error is None:
            allow_error = type == "ERROR"
        error_patterns = [] if allow_error else None
        return self.expect(pattern, error_patterns=error_patterns, timeout=timeout)

    # -- teardown --------------------------------------------------------------
    def finish(self, timeout=None, expect_pass=None):
        """Optionally assert a final marker, then stop the VP.

        sep-vp does not self-terminate, so we do not drain to EOF; we assert
        *expect_pass* (if given) within *timeout*, then terminate the process.
        """
        if expect_pass is not None:
            self.expect(
                expect_pass, timeout=timeout if timeout is not None else self.config.boot_timeout
            )
        self.close()

    def close(self):
        """Terminate the VP process and close any log file. Safe to call repeatedly."""
        child = self.child
        if child is not None and child.isalive():
            try:
                child.terminate(force=True)
            except Exception:  # noqa: BLE001 — best-effort teardown
                log.debug("terminate() raised during close()", exc_info=True)
        self._close_log()

    def _close_log(self):
        """Hook for backends that own a log file object."""
