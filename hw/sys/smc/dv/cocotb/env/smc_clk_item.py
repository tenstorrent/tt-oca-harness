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
        # clk_ref_i / clk_smc_i / clk_periph_i are DUT *inputs* that
        # smc_base_test._bring_up drives with cocotb Clock(...). Counting them
        # measures the TB clock generators, never DUT RTL -- the scoreboard
        # therefore books these three as a SETUP self-check, not DUT evidence.
        self.ref_rising_edges: int = -1
        self.smc_rising_edges: int = -1
        self.periph_rising_edges: int = -1
        # --- DUT-generated gated clock (fail-capable against RTL) -------------
        # Passive tb_top probe on a DUT clock-gater output plus its enable.
        # `expect_gated_clk_running`: None => observed only (no compare);
        # True  => the gated clock must toggle over the window;
        # False => it must be fully quiet (0 edges) over the window.
        # `expect_gated_cg_en`: None => not compared, else exact 0/1.
        self.gated_clk_probe: str = "tb_zeroer_gated_reg_clk"
        self.gated_cg_en_probe: str = "tb_zeroer_cg_en"
        self.gated_clk_rising_edges: int = -1
        self.gated_cg_en: int = -1
        self.gated_probe_resolvable: bool = False
        self.expect_gated_clk_running: bool | None = None
        self.expect_gated_cg_en: int | None = None
        # Default DUT check when no explicit expectation is given: a clock
        # gater whose enable is deasserted (cg_en == 0) must pass its clock
        # through, so the gated output has to toggle over the window. This is
        # the only leg of COUNT_EDGES that can fail because of DUT RTL. Set
        # False on a leg where the gated clock is stopped for a
        # different reason (e.g. its source domain is held in reset).
        self.gated_clk_contract: bool = True

    def __str__(self) -> str:
        gated = ""
        if self.gated_clk_rising_edges >= 0 or self.gated_cg_en >= 0:
            gated = (
                f", {self.gated_clk_probe}={self.gated_clk_rising_edges}"
                f", {self.gated_cg_en_probe}={self.gated_cg_en}"
            )
        return (
            f"SmcClkItem(op={self.op.value}, window_ref={self.window_ref_cycles}, "
            f"ref={self.ref_rising_edges}, smc={self.smc_rising_edges}, "
            f"periph={self.periph_rising_edges}{gated})"
        )
