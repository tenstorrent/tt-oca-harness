# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Clock-edge sampling shared by the passive AXI monitors and protocol watchers.

A sampler that reads every VALID low has nothing to record, so it waits for a
VALID to rise instead of waking at every rising clock edge. VALID changes only
at a rising edge of the sampled clock or while that clock is low; a rise while
the clock is low is sampled at the next rising edge, as a per-cycle wait
samples it.
"""

from __future__ import annotations

from typing import Any

from cocotb.triggers import First, ReadOnly, RisingEdge

__all__ = ["is_high", "next_sample", "valid_handles"]

_VALID_SIGNALS = (
    ("aw", "awvalid"),
    ("w", "wvalid"),
    ("b", "bvalid"),
    ("ar", "arvalid"),
    ("r", "rvalid"),
)


def is_high(signal: Any) -> bool:
    """Return True when ``signal`` reads 1; X, Z and unresolved handles read as low."""
    try:
        return int(signal.value) == 1
    except Exception:  # noqa: BLE001 - X/Z values and unresolved handles read as low
        return False


def valid_handles(bus: Any) -> list[Any]:
    """Return the VALID handle of every channel that ``bus`` carries."""
    channels = {
        "aw": bus.write.aw,
        "w": bus.write.w,
        "b": bus.write.b,
        "ar": bus.read.ar,
        "r": bus.read.r,
    }
    return [
        handle
        for channel, name in _VALID_SIGNALS
        if (handle := getattr(channels[channel], name, None)) is not None
    ]


async def next_sample(clock: Any, wake: list[Any] | None) -> None:
    """Advance to the next sampled rising edge of ``clock`` and enter ReadOnly.

    With ``wake`` set, whole cycles pass until one of its triggers fires; a
    trigger that fires while the clock is low is sampled at the next rising
    edge.
    """
    if wake:
        await First(*wake)
        if not is_high(clock):
            await RisingEdge(clock)
    else:
        await RisingEdge(clock)
    await ReadOnly()
