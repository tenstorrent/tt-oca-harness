# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Passive monitor at the slave-side observation point.

The slave side watches the same IEEE 1149.1 wire as the master side, so the
sampling and IR/DR reconstruction logic is shared with
`OcahJtagMasterMonitor`; this class fixes the side-appropriate default name
so slave agents label their item streams distinctly.
"""

from __future__ import annotations

from .ocah_jtag_master_monitor import OcahJtagMasterMonitor

__all__ = ["OcahJtagSlaveMonitor"]


class OcahJtagSlaveMonitor(OcahJtagMasterMonitor):
    """Passive TAP monitor for a slave (device-side) agent."""

    def __init__(
        self,
        jtag_intf,
        *,
        name: str = "OcahJtagSlaveMonitor",
        **kwargs,
    ) -> None:
        super().__init__(jtag_intf, name=name, **kwargs)
