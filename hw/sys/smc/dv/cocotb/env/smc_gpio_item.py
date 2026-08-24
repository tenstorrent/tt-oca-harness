# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS GPIO observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcGpioOp(Enum):
    SAMPLE = "SAMPLE"


class SmcGpioItem(uvm_sequence_item):

    def __init__(self, name: str = "SmcGpioItem") -> None:
        super().__init__(name)
        self.op: SmcGpioOp = SmcGpioOp.SAMPLE
        self.core2pad_any: int = -1
        self.core2pad_en_any: int = -1
        self.pad2core_en_any: int = -1
        self.resolvable: bool = False

    def __str__(self) -> str:
        return (
            f"SmcGpioItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"core2pad_any={self.core2pad_any}, "
            f"core2pad_en_any={self.core2pad_en_any}, "
            f"pad2core_en_any={self.pad2core_en_any})"
        )
