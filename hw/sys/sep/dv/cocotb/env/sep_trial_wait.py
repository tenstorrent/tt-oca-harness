# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded register polls of one trial, and the timeout a trial catches.

A trial of a randomized crypto leaf polls a status register until a field
reads a value, within a bound in clocks. ``poll_until`` returns every sample
with its clock, so the leaf can grade the samples as well as the end value.
``wait_until`` raises ``TrialTimeout`` when the bound expires; the leaf catches
it, logs the owning check as FAIL with ``reason=timeout:<what> bound=<n>`` and
goes on with the next trial.

``now`` returns the clock count of the leaf, for example the ``clk`` of a
running ``SepBitWatch`` (``env/sep_bit_watch.py``). A bus read takes at least
one clock, so the poll also stops after ``bound + 1`` reads: the wait stays
bounded when the clock count does not move.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable


class TrialTimeout(Exception):
    """A bounded wait inside a trial expired."""

    def __init__(self, what: str, bound: int) -> None:
        super().__init__(f"{what} bound={bound}")
        self.what = what
        self.bound = bound


async def poll_until(
    read: Callable[[], Awaitable[int]],
    now: Callable[[], int],
    mask: int,
    want: int,
    bound: int,
) -> tuple[bool, list[tuple[int, int]]]:
    """Back-to-back reads until ``(value & mask) == want`` or ``bound`` clocks pass.

    Returns ``(matched, samples)``; ``samples`` is the ``(clock, value)`` of every read.
    """
    samples: list[tuple[int, int]] = []
    t0 = now()
    for _ in range(bound + 1):
        if now() - t0 > bound:
            break
        value = await read()
        samples.append((now(), value))
        if value & mask == want:
            return True, samples
    return False, samples


async def wait_until(
    read: Callable[[], Awaitable[int]],
    now: Callable[[], int],
    mask: int,
    want: int,
    bound: int,
    what: str,
) -> list[tuple[int, int]]:
    """``poll_until`` that raises ``TrialTimeout(what, bound)`` when the bound expires."""
    matched, samples = await poll_until(read, now, mask, want, bound)
    if not matched:
        raise TrialTimeout(what, bound)
    return samples
