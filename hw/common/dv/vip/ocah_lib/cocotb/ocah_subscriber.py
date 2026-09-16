# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Subscriber base for an always-on invariant checker on a VIP event or item stream.

A bench ``<Dut><X>Checker`` extends it. The env hands it the shared evidence
recorder; the subclass logs an error on every violation in ``write()`` and
turns the run's aggregate into one named CHK record in ``report_evidence()``,
which the env calls once from ``check_phase``. ``write()`` never awaits. The
SV-UVM twin is ``ocah_subscriber``.
"""

from __future__ import annotations

from ocah_checker import OcahChecker
from pyuvm import uvm_subscriber

__all__ = ["OcahSubscriber"]


class OcahSubscriber(uvm_subscriber):
    """Evidence handle plus the two hooks every invariant checker fills."""

    def __init__(self, name: str, parent: object) -> None:
        super().__init__(name, parent)
        # Shared named-evidence sink, set by the env before ``run_phase``; a
        # ``None`` handle leaves only the inline error log path.
        self.evidence: OcahChecker | None = None

    def write(self, item: object) -> None:
        """Stream handler; every concrete checker overrides it.

        The base accepts and drops, so an unconnected base instance is inert.
        """

    def report_evidence(self) -> None:
        """One aggregate named-evidence record for the whole run; called once by the env."""
