# SPDX-License-Identifier: Apache-2.0
"""Transaction items for the SMC OSS reset agent."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcResetOp(Enum):
    """Operations the reset agent supports."""

    SAMPLE = "SAMPLE"
    RAW_SAMPLE = "RAW_SAMPLE"
    POWERGOOD_LO = "POWERGOOD_LO"
    POWERGOOD_HI = "POWERGOOD_HI"
    COLD_RST_LO = "COLD_RST_LO"
    COLD_RST_HI = "COLD_RST_HI"
    COOL_RST_LO = "COOL_RST_LO"
    COOL_RST_HI = "COOL_RST_HI"


class SmcResetItem(uvm_sequence_item):
    """Transaction item carrying SMC reset agent transactions."""

    def __init__(self, name: str = "SmcResetItem") -> None:
        super().__init__(name)
        self.op: SmcResetOp = SmcResetOp.SAMPLE
        # SAMPLE result fields. Active-low resets: 1 = released, 0 = asserted.
        self.powergood_stable: int = -1
        self.rst_cold_stable_ref_clk_n: int = -1
        self.rst_primary_ref_clk_n: int = -1
        self.rst_primary_smc_clk_n: int = -1
        self.rst_wdt_smc_clk_n: int = -1
        self.resolvable: bool = False

    def __str__(self) -> str:
        if self.op is SmcResetOp.SAMPLE:
            return (
                f"SmcResetItem(op={self.op.value}, resolvable={self.resolvable}, "
                f"powergood_stable={self.powergood_stable}, "
                f"rst_cold_stable_ref={self.rst_cold_stable_ref_clk_n}, "
                f"rst_primary_ref={self.rst_primary_ref_clk_n}, "
                f"rst_primary_smc={self.rst_primary_smc_clk_n}, "
                f"rst_wdt_smc={self.rst_wdt_smc_clk_n})"
            )
        return f"SmcResetItem(op={self.op.value})"
