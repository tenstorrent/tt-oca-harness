# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-channel timing control for the cocotb AXI master.

AXI channels are independent. The write address and write data channels carry
no ordering requirement between them: a master may present AW and W in the
same cycle, AW first, or W first, and a slave must handle all three (AMBA
IHI 0022 A3.3). A slave that assumes one ordering is a real defect, and a
master that can only produce one ordering cannot find it.

The cocotbext backend drives each channel from its own queue, so a single-beat
write normally presents AW and W together and nothing else is reachable. This
module adds the missing control by holding a channel back with the backend's
own pause mechanism:

    aw_delay > w_delay   -> W leads AW
    aw_delay < w_delay   -> AW leads W
    aw_delay == w_delay  -> same cycle (the backend default)

Ready-side delays do the same for the response channels, which exercises
backpressure on B and R.

Delays are cycle counts, not randomness. A caller that wants variation draws
them from ``SepSeededRng`` (or any seeded source) and passes the result, so
``--stage sim --seed N`` still replays a failing profile exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import RisingEdge

__all__ = ["AxiTimingProfile", "apply_profile", "clear_profile"]


@dataclass(frozen=True)
class AxiTimingProfile:
    """Cycles each channel is held back before it may drive.

    Zero everywhere reproduces the backend default, so an unconfigured master
    behaves exactly as it did before this module existed.
    """

    aw_delay: int = 0
    w_delay: int = 0
    ar_delay: int = 0
    b_ready_delay: int = 0
    r_ready_delay: int = 0

    def __post_init__(self) -> None:
        for name in ("aw_delay", "w_delay", "ar_delay",
                     "b_ready_delay", "r_ready_delay"):
            val = getattr(self, name)
            if not isinstance(val, int) or val < 0:
                raise ValueError(
                    f"AxiTimingProfile.{name} must be a non-negative int, "
                    f"got {val!r}"
                )

    @property
    def write_order(self) -> str:
        """Which of AW/W reaches the bus first, for logging."""
        if self.aw_delay > self.w_delay:
            return "w-first"
        if self.aw_delay < self.w_delay:
            return "aw-first"
        return "same-cycle"

    def summary(self) -> str:
        return (
            f"aw={self.aw_delay} w={self.w_delay} ar={self.ar_delay} "
            f"bready={self.b_ready_delay} rready={self.r_ready_delay} "
            f"({self.write_order})"
        )


# Request channels, whose delay separates the channels of one transfer. The
# response channels are ready-side backpressure: their queue holds what has
# been received, so it is empty exactly when they are waiting, and gating on
# that would hold READY low for the whole run.
_REQUEST_FIELDS = ("aw_delay", "w_delay", "ar_delay")


def _hold_then_go(channel, cycles: int):
    """Pause generator: hold ``cycles`` edges once the channel has work.

    The backend advances one value per clock edge from the moment the
    generator is armed, so a plain countdown measures from arming and is spent
    before a later transaction reaches the channel -- leaving the channel free
    and every ordering identical. Holding while the queue is empty makes the
    count relative to the transfer instead: the delay separates THIS write's
    channels, whenever it is issued.

    It never StopIterations, because a generator that ends leaves the channel
    at its last value.
    """
    while channel is not None and channel.empty():
        yield True
    for _ in range(cycles):
        yield True
    while True:
        yield False


# Pending release per channel. A profile armed while an earlier release is
# still waiting would have that release clear the pause it just set, so the
# previous one is cancelled first.
_OCAH_RELEASERS: dict = {}


async def _release_on_leader_valid(trailing, leading, cycles: int) -> None:
    """Hold ``trailing`` until ``leading`` asserts VALID, then ``cycles`` more.

    VALID assertion is the only event that orders the channels. A cycle count
    runs from when the profile is armed, which is spent before the write is
    issued. The leading queue empties in the same delta its beat is driven, so
    a queue-drained release fires too late to have held anything. The leading
    handshake waits on the slave, and one that holds WREADY until AW can never
    grant a W-first handshake, so a handshake-driven release deadlocks that
    ordering.
    """
    edge = RisingEdge(trailing.clock)
    while True:
        await edge
        if leading.valid is not None and leading.valid.value.integer:
            break
    for _ in range(cycles):
        await edge
    trailing.pause = False


def apply_profile(driver, profile: AxiTimingProfile) -> None:
    """Arm ``profile`` on ``driver``'s channels.

    Channels with a zero delay are actively cleared rather than left alone, so
    applying a profile fully replaces the previous one instead of merging with
    it.
    """
    for chan in driver.channels.values():
        task = _OCAH_RELEASERS.pop(chan, None)
        if task is not None:
            task.kill()

    chans = driver.channels
    # AW and W order against each other; the trailing one is held until the
    # leading one has gone. A response channel has no peer, so its delay stays
    # a plain countdown of backpressure.
    lead = {"aw_delay": "w_delay", "w_delay": "aw_delay"}

    for field, chan in chans.items():
        cycles = getattr(profile, field)
        if not cycles:
            chan.clear_pause_generator()
            chan.pause = False
            continue
        if field in lead:
            # Pause now, synchronously: the write may be issued in this same
            # delta, before any task the backend starts could run.
            chan.clear_pause_generator()
            chan.pause = True
            _OCAH_RELEASERS[chan] = cocotb.start_soon(
                _release_on_leader_valid(chan, chans[lead[field]], cycles))
        else:
            chan.set_pause_generator(_hold_then_go(None, cycles))


def clear_profile(driver) -> None:
    """Return every channel to the backend default (no pause)."""
    apply_profile(driver, AxiTimingProfile())


def _selftest() -> None:
    p = AxiTimingProfile()
    assert p.write_order == "same-cycle", p.write_order
    assert AxiTimingProfile(aw_delay=3).write_order == "w-first"
    assert AxiTimingProfile(w_delay=3).write_order == "aw-first"
    assert AxiTimingProfile(aw_delay=2, w_delay=2).write_order == "same-cycle"

    # A response channel has no peer to order against: the countdown starts
    # at once.
    g_resp = _hold_then_go(None, 2)
    assert [next(g_resp) for _ in range(4)] == [True, True, False, False]

    for bad in ({"aw_delay": -1}, {"w_delay": "2"}):
        try:
            AxiTimingProfile(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"AxiTimingProfile accepted {bad}")


_selftest()
