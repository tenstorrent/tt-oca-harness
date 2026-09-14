# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Monitor base for a DUT-local observation no VIP provides.

A monitor publishes items or events on a ``<stream>_ap`` analysis port and
never checks protocol content; checking lives in the scoreboard, a subscriber,
or a reference model. The SV-UVM twin is ``ocah_monitor``.
"""

from __future__ import annotations

from pyuvm import uvm_monitor

__all__ = ["OcahMonitor"]


class OcahMonitor(uvm_monitor):
    """Base of a DUT-local monitor; publishes only."""
