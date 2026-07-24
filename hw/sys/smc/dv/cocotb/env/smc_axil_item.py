# SPDX-License-Identifier: Apache-2.0
"""Transaction items for the SMC OSS AXI-Lite observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcAxilOp(Enum):
    SAMPLE = "SAMPLE"


class SmcAxilItem(uvm_sequence_item):

    def __init__(self, name: str = "SmcAxilItem") -> None:
        super().__init__(name)
        self.op: SmcAxilOp = SmcAxilOp.SAMPLE
        # Per-interface activity bits (1 = at least one *_valid handshake high).
        self.dtp_csr_active: int = -1
        self.pll_active: int = -1
        self.pvt_active: int = -1
        self.extension_active: int = -1
        self.efuse_bank_active: int = -1
        # OR-of-all across the five interfaces.
        self.any_master_active: int = -1
        self.resolvable: bool = False

    def __str__(self) -> str:
        return (
            f"SmcAxilItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"any={self.any_master_active}, dtp={self.dtp_csr_active}, "
            f"pll={self.pll_active}, pvt={self.pvt_active}, "
            f"ext={self.extension_active}, efuse={self.efuse_bank_active})"
        )
