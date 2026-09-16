# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain configuration object for the AXI4 master-side VIP components.

One `OcahAxiMasterConfig` describes a master connection (naming, geometry,
timeouts, response policy, default channel timing, backend knobs) and can
be passed to `OcahAxiMasterAgent` instead of repeating keyword arguments.
Explicit keyword arguments always override config fields. The agent forwards
`driver_kwargs()` (including `timing`) into `OcahAxiMasterDriver`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["AxiTimingProfile", "OcahAxiMasterConfig"]


@dataclass(frozen=True)
class AxiTimingProfile:
    """Cycles each channel is held back before it may drive.

    AXI channels are independent. The write address and write data channels
    carry no ordering requirement between them: a master may present AW and W
    in the same cycle, AW first, or W first, and a slave must handle all three
    (AMBA IHI 0022 A3.3). A slave that assumes one ordering is a real defect,
    and a master that can only produce one ordering cannot find it. The
    cocotbext backend drives each channel from its own queue, so a single-beat
    write normally presents AW and W together and nothing else is reachable;
    `OcahAxiMasterDriver.set_timing` arms this profile to reach the rest:

        aw_delay > w_delay   -> W leads AW
        aw_delay < w_delay   -> AW leads W
        aw_delay == w_delay  -> same cycle (the backend default)

    Ready-side delays do the same for the response channels, which exercises
    backpressure on B and R.

    Delays are cycle counts, not randomness. A caller that wants variation
    draws them from a seeded source and passes the result, so
    ``--stage sim --seed N`` still replays a failing profile exactly. Zero
    everywhere is the backend default, so an unconfigured master is
    unaffected.
    """

    aw_delay: int = 0
    w_delay: int = 0
    ar_delay: int = 0
    b_ready_delay: int = 0
    r_ready_delay: int = 0

    def __post_init__(self) -> None:
        for name in ("aw_delay", "w_delay", "ar_delay", "b_ready_delay", "r_ready_delay"):
            val = getattr(self, name)
            if not isinstance(val, int) or val < 0:
                raise ValueError(f"AxiTimingProfile.{name} must be a non-negative int, got {val!r}")
        if self.aw_delay and self.w_delay:
            raise ValueError(
                "AxiTimingProfile holds the trailing write channel until the "
                "leading one asserts VALID, so at most one of aw_delay / "
                "w_delay may be non-zero; got "
                f"aw_delay={self.aw_delay} w_delay={self.w_delay}"
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


@dataclass
class OcahAxiMasterConfig:
    """Configuration for one AXI4 master connection."""

    name: str = "OcahAxiMaster"
    addr_width: int = 32
    data_width: int = 32
    reset_active_level: bool = False
    max_burst_len: int = 256
    # Sequence-level policy. timeout_cycles has no consumer on the AXI4 master;
    # the transaction bound is timeout_ns, and None selects the package default
    # (DEFAULT_TIMEOUT_NS or +OCAH_AXI_TIMEOUT_NS).
    timeout_cycles: int = 1000
    timeout_ns: int | None = None
    raise_on_error: bool = True
    # Default AW/W / ready-side delays. None leaves the backend default (same
    # cycle). The driver applies this at construction; a test that changes
    # order per write still calls OcahAxiMasterDriver.set_timing().
    timing: AxiTimingProfile | None = None
    # Extra keyword arguments forwarded verbatim to the cocotbext backend.
    backend_kwargs: dict = field(default_factory=dict)

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiMasterDriver` construction."""
        kwargs = {
            "name": self.name,
            "addr_width": self.addr_width,
            "data_width": self.data_width,
            "reset_active_level": self.reset_active_level,
            "max_burst_len": self.max_burst_len,
            **dict(self.backend_kwargs),
        }
        # Omit the default: a leaked `timing=None` reaches cocotbext AxiMaster
        # and TypeErrors at construction.
        if self.timing is not None:
            kwargs["timing"] = self.timing
        return kwargs

    def sequence_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiMasterSequence` construction."""
        return {
            "timeout_ns": self.timeout_ns,
            "raise_on_error": self.raise_on_error,
        }


def _selftest() -> None:
    p = AxiTimingProfile()
    assert p.write_order == "same-cycle", p.write_order
    assert AxiTimingProfile(aw_delay=3).write_order == "w-first"
    assert AxiTimingProfile(w_delay=3).write_order == "aw-first"
    for bad in ({"aw_delay": 2, "w_delay": 2}, {"aw_delay": -1}, {"w_delay": "2"}):
        try:
            AxiTimingProfile(**bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"AxiTimingProfile accepted {bad}")

    assert "timing" not in OcahAxiMasterConfig().driver_kwargs()
    profile = AxiTimingProfile(w_delay=1)
    cfg = OcahAxiMasterConfig(timing=profile, backend_kwargs={"foo": 1})
    kwargs = cfg.driver_kwargs()
    assert kwargs["timing"] is profile
    assert kwargs["foo"] == 1
    assert "timing" not in cfg.sequence_kwargs()


_selftest()
