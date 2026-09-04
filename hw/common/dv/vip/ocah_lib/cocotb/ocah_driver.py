# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Driver base for the DUT-local agent a one-consumer protocol gets.

A driver is the only class besides a monitor that waits on pin edges, always
through the handles its cfg names and always bounded by a cfg timeout. The
SV-UVM twin is ``ocah_driver``.
"""

from __future__ import annotations

from pyuvm import uvm_driver

__all__ = ["OcahDriver"]


class OcahDriver(uvm_driver):
    """Base of a DUT-local driver; pulls items from ``seq_item_port``."""
