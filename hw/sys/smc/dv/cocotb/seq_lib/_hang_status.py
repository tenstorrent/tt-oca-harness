# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Compare every HANG_DET_*_STATUS.irq bit against the detectors expected to be firing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_STATUS,
    HANG_DET_SEP_AXI_STATUS,
    HANG_DET_STATUS_IRQ,
    HANG_DET_SYS_AXI_STATUS,
)

_STATUS_REGS = (
    ("SYS", HANG_DET_SYS_AXI_STATUS),
    ("SEP", HANG_DET_SEP_AXI_STATUS),
    ("DATA", HANG_DET_DATA_ACCEL_STATUS),
)


async def check_hang_status(
    read: Callable[[str, int], Awaitable[int]], label: str, firing: set[str]
) -> None:
    """Read all three status registers through ``read``; only ``firing`` may read 1.

    Reading all three on every call is what catches a status register wired to
    the wrong detector: the fired detector's bit alone would not.
    """
    got = {}
    for name, addr in _STATUS_REGS:
        rdata = await read(f"{label}_{name}_STATUS", addr)
        got[name] = int(bool(rdata & HANG_DET_STATUS_IRQ))
    want = {name: int(name in firing) for name, _addr in _STATUS_REGS}
    assert got == want, f"{label}: HANG_DET_*_STATUS.irq read {got}, want {want}"
