# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Plain configuration object for the AXI4-Lite slave-side VIP components.

One `OcahAxiLiteSlaveConfig` describes a memory-backed responder (naming,
memory size, reset polarity, backend knobs) and can be passed to
`OcahAxiLiteSlaveAgent` instead of repeating keyword arguments. Explicit
keyword arguments always override config fields.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = ["OcahAxiLiteSlaveConfig"]


@dataclass
class OcahAxiLiteSlaveConfig:
    """Configuration for one AXI4-Lite memory-backed responder."""

    name: str = "OcahAxiLiteSlave"
    size: int = 2**20
    reset_active_level: bool = False
    mem: object | None = None
    # Extra keyword arguments forwarded verbatim to the cocotbext backend.
    backend_kwargs: dict = field(default_factory=dict)

    def driver_kwargs(self) -> dict:
        """Keyword arguments for `OcahAxiLiteSlaveDriver` construction."""
        return {
            "name": self.name,
            "size": self.size,
            "reset_active_level": self.reset_active_level,
            "mem": self.mem,
            **dict(self.backend_kwargs),
        }
