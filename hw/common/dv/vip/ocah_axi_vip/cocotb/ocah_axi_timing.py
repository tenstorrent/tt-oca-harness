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


def _hold_then_go(cycles: int):
    """Pause generator: hold for ``cycles`` edges, then release forever.

    The backend advances one clock edge per yielded value, so the count is in
    cycles. It never StopIterations, because a generator that ends leaves the
    channel at its last value.
    """
    for _ in range(cycles):
        yield True
    while True:
        yield False


def apply_profile(driver, profile: AxiTimingProfile) -> None:
    """Arm ``profile`` on ``driver``'s channels.

    Channels with a zero delay are actively cleared rather than left alone, so
    applying a profile fully replaces the previous one instead of merging with
    it.
    """
    for field, chan in driver.channels.items():
        cycles = getattr(profile, field)
        if cycles:
            chan.set_pause_generator(_hold_then_go(cycles))
        else:
            chan.clear_pause_generator()
            chan.pause = False


def clear_profile(driver) -> None:
    """Return every channel to the backend default (no pause)."""
    apply_profile(driver, AxiTimingProfile())


def _selftest() -> None:
    p = AxiTimingProfile()
    assert p.write_order == "same-cycle", p.write_order
    assert AxiTimingProfile(aw_delay=3).write_order == "w-first"
    assert AxiTimingProfile(w_delay=3).write_order == "aw-first"
    assert AxiTimingProfile(aw_delay=2, w_delay=2).write_order == "same-cycle"

    g = _hold_then_go(3)
    assert [next(g) for _ in range(6)] == [True, True, True, False, False, False]
    g0 = _hold_then_go(0)
    assert [next(g0) for _ in range(3)] == [False, False, False]

    for bad in ({"aw_delay": -1}, {"w_delay": "2"}):
        try:
            AxiTimingProfile(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"AxiTimingProfile accepted {bad}")


_selftest()
