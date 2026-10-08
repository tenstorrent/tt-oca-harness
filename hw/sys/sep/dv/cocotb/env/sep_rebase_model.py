# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reference model of the SEP inbound address path.

Written from ``hw/sys/sep/doc/fabric.adoc`` ("Fabric Topology", input
fabric; "Address Remapping") and ``hw/sys/sep/doc/assets/sep-input-fabric.svg``,
never from the RTL:

* The inbound filter compares the chiplet-global address first.
* The global-to-local remap then rebases the ``SEP_REGION_SIZE``-byte window
  at ``SEP_GLOBAL_BASE_ADDR`` to local address 0 and passes every other
  address unchanged.
* The peripheral crossbar forwards a local address below ``0x4000_0000`` to
  the local crossbar and answers DECERR at or above it.

The model states nothing about base or size values; the specification states
no legal values for them.
"""

from __future__ import annotations

from dataclasses import dataclass

ADDR_MASK = (1 << 56) - 1
# The peripheral crossbar forwards a local address below this limit to the
# local crossbar and answers DECERR at or above it (fabric.adoc, "Fabric
# Topology", input fabric). The fabric tests and models take it from here.
XBAR_LIMIT = 0x4000_0000


@dataclass(frozen=True)
class Rebase:
    global_addr: int
    in_window: bool
    local: int

    @property
    def forwarded(self) -> bool:
        """The peripheral crossbar forwards the local address."""
        return self.local < XBAR_LIMIT


def rebase(global_addr: int, base: int, size: int) -> Rebase:
    """The local address of an inbound request."""
    a = global_addr & ADDR_MASK
    in_win = base <= a < base + size
    return Rebase(a, in_win, (a - base) if in_win else a)


def _selftest() -> None:
    base, size = 0x40_0000_0000, 0x2000_0000
    r = rebase(base + 0x1000_0008, base, size)
    assert r.in_window and r.local == 0x1000_0008 and r.forwarded
    r = rebase(base + size, base, size)
    assert not r.in_window and r.local == base + size and not r.forwarded
    r = rebase(base - 1, base, size)
    assert not r.in_window and not r.forwarded
    r = rebase(0x1000_0000, base, size)
    assert not r.in_window and r.local == 0x1000_0000 and r.forwarded
    r = rebase(base + 0x4000_0000, base, 0x8000_0000)
    assert r.in_window and r.local == XBAR_LIMIT and not r.forwarded


if __name__ == "__main__":
    _selftest()
    print("sep_rebase_model selftest: PASS")
