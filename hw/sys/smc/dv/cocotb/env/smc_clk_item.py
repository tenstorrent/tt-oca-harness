# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS clock observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcClkOp(Enum):
    """Operations the clock observer supports."""

    COUNT_EDGES = "COUNT_EDGES"


class SmcClkItem(uvm_sequence_item):
    """Carries clock-edge counts over a fixed observation window."""

    def __init__(self, name: str = "SmcClkItem") -> None:
        super().__init__(name)
        self.op: SmcClkOp = SmcClkOp.COUNT_EDGES
        self.window_ref_cycles: int = 50  # observation window in clk_ref_i edges
        self.ref_rising_edges: int = -1
        self.smc_rising_edges: int = -1
        self.periph_rising_edges: int = -1

    def __str__(self) -> str:
        return (
            f"SmcClkItem(op={self.op.value}, window_ref={self.window_ref_cycles}, "
            f"ref={self.ref_rising_edges}, smc={self.smc_rising_edges}, "
            f"periph={self.periph_rising_edges})"
        )
