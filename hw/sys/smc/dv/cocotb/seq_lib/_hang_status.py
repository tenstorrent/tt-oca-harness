# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Compare every HANG_DET_*_CTRL.irq bit against the detectors expected to be firing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from .smc_addr_map import (
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_IRQ,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SYS_AXI_CTRL,
)

_CTRL_REGS = (
    ("SYS", HANG_DET_SYS_AXI_CTRL),
    ("SEP", HANG_DET_SEP_AXI_CTRL),
    ("DATA", HANG_DET_DATA_ACCEL_CTRL),
)


async def check_hang_status(
    read: Callable[[str, int], Awaitable[int]], label: str, firing: set[str]
) -> None:
    """Read all three CTRL registers through ``read``; only ``firing`` may have ``irq`` set.

    Reading all three on every call is what catches an ``irq`` bit wired to the
    wrong detector: the fired detector's bit alone would not.
    """
    got = {}
    for name, addr in _CTRL_REGS:
        rdata = await read(f"{label}_{name}_CTRL_IRQ", addr)
        got[name] = int(bool(rdata & HANG_DET_IRQ))
    want = {name: int(name in firing) for name, _addr in _CTRL_REGS}
    assert got == want, f"{label}: HANG_DET_*_CTRL.irq read {got}, want {want}"
