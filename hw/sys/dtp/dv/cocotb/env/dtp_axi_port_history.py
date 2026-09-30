# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Completed-transaction history of one JTAG2AXI bridge port.

Counts every write and read the port's shared monitor completes and keeps the
newest item of each direction, so a scenario can wait for the transaction an
operation put on the port, judge it and prove that no other one appeared
(``CHK-J2A-BUS-REQ``), and compare an errored read beat with its capture
(``CHK-J2A-ERR-RDATA``). ``mark`` holds the counts the last ledgered pass
closed with. Publishes nothing and checks nothing. The SV-UVM twin is
``uvm/env/dtp_axi_port_history.svh``.
"""

from __future__ import annotations

from ocah_axi_vip import OcahAxiItem

__all__ = ["DtpAxiPortHistory"]


class DtpAxiPortHistory:
    """Exact per-direction completion counts and the newest item of each direction."""

    def __init__(self) -> None:
        self.writes = 0
        self.reads = 0
        self.last_write: OcahAxiItem | None = None
        self.last_read: OcahAxiItem | None = None
        # (writes, reads) at the close of the last ledgered pass.
        self.mark: tuple[int, int] | None = None

    def observe(self, item: OcahAxiItem) -> None:
        """Monitor item callback: a write completes at its B, a read at its last R."""
        if item.is_write:
            self.writes += 1
            self.last_write = item
        else:
            self.reads += 1
            self.last_read = item

    def count(self, *, read: bool) -> int:
        return self.reads if read else self.writes

    def counts(self) -> tuple[int, int]:
        """The (writes, reads) the port has completed."""
        return self.writes, self.reads

    def last(self, *, read: bool) -> OcahAxiItem | None:
        return self.last_read if read else self.last_write
