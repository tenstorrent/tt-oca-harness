# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""Plain configuration object for the AXI4 master-side VIP components.

One `OcahAxiMasterConfig` describes a master connection (naming, geometry,
timeouts, response policy, backend knobs) and can be passed to
`OcahAxiMasterAgent` instead of repeating keyword arguments. Explicit keyword
arguments always override config fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
    # Extra keyword arguments forwarded verbatim to the cocotbext backend.
    backend_kwargs: dict = field(default_factory=dict)

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiMasterDriver` construction."""
        return {
            "name": self.name,
            "addr_width": self.addr_width,
            "data_width": self.data_width,
            "reset_active_level": self.reset_active_level,
            "max_burst_len": self.max_burst_len,
            **dict(self.backend_kwargs),
        }

    def sequence_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiMasterSequence` construction."""
        return {
            "timeout_cycles": self.timeout_cycles,
            "timeout_ns": self.timeout_ns,
            "raise_on_error": self.raise_on_error,
        }
