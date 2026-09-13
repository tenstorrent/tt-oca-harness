# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain configuration object for the AXI4-Lite master-side VIP components.

One `OcahAxiLiteMasterConfig` describes a master connection (naming, data
width, timeouts, response policy, backend knobs) and can be passed to
`OcahAxiLiteMasterAgent` instead of repeating keyword arguments. Explicit
keyword arguments always override config fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["OcahAxiLiteMasterConfig"]


@dataclass
class OcahAxiLiteMasterConfig:
    """Configuration for one AXI4-Lite master connection."""

    name: str = "OcahAxiLiteMaster"
    data_width: int = 32
    reset_active_level: bool = False
    # Sequence-level policy.
    timeout_cycles: int = 1000
    # None selects the package default (DEFAULT_TIMEOUT_NS or +OCAH_AXI_TIMEOUT_NS).
    timeout_ns: int | None = None
    raise_on_error: bool = True
    # Extra keyword arguments forwarded verbatim to the cocotbext backend.
    backend_kwargs: dict = field(default_factory=dict)

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiLiteMasterDriver` construction."""
        return {
            "name": self.name,
            "data_width": self.data_width,
            "reset_active_level": self.reset_active_level,
            **dict(self.backend_kwargs),
        }

    def sequence_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiLiteMasterSequence` construction."""
        return {
            "timeout_cycles": self.timeout_cycles,
            "timeout_ns": self.timeout_ns,
            "raise_on_error": self.raise_on_error,
        }
