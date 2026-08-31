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

from .ocah_axi_timing import AxiTimingProfile

__all__ = ["OcahAxiMasterConfig"]


@dataclass
class OcahAxiMasterConfig:
    """Configuration for one AXI4 master connection."""

    name: str = "OcahAxiMaster"
    addr_width: int = 32
    data_width: int = 32
    reset_active_level: bool = False
    max_burst_len: int = 256
    # Sequence-level policy.
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
            "timeout_cycles": self.timeout_cycles,
            "timeout_ns": self.timeout_ns,
            "raise_on_error": self.raise_on_error,
        }


def _selftest() -> None:
    assert "timing" not in OcahAxiMasterConfig().driver_kwargs()
    profile = AxiTimingProfile(w_delay=1)
    cfg = OcahAxiMasterConfig(timing=profile, backend_kwargs={"foo": 1})
    kwargs = cfg.driver_kwargs()
    assert kwargs["timing"] is profile
    assert kwargs["foo"] == 1
    assert "timing" not in cfg.sequence_kwargs()


_selftest()
