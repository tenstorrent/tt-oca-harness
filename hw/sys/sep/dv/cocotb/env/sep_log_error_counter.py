# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Count the ERROR records a bench model logs, so a test can fail on them.

A model that catches its own exception (for example the SPI flash BFM, which
logs and drops a frame whose handler raised) does not fail the test by
itself. Attach a counter to the model's logger and require zero at the end.
"""

from __future__ import annotations

import logging


class LogErrorCounter(logging.Handler):
    """Keeps every record at ERROR or above that its logger emits."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.records: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append(record.getMessage())
        except Exception:  # a broken format string still counts as an error
            self.records.append(str(record.msg))


def attach_error_counter(logger: logging.Logger) -> LogErrorCounter:
    """Attach a new counter to ``logger`` and return it."""
    counter = LogErrorCounter()
    logger.addHandler(counter)
    return counter
