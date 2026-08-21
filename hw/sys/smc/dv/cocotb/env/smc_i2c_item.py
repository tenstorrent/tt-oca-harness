# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS I2C observation agent."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcI2cOp(Enum):
    """Observation operations the I2C agent supports.

    Only ``SAMPLE`` is defined today: pre-cocotb-stimulus observability of the
    SMC-internal I2C clock-gate enable and the lowest I2C controller debug
    nibble, lifted to tb_top as ``tb_i2c_cg_en`` / ``tb_i2c_debug_lo``. Real
    bus-driving operations (``WRITE`` / ``READ``) will land once the OSS top
    exposes I2C SCL/SDA pads.
    """

    SAMPLE = "SAMPLE"


class SmcI2cItem(uvm_sequence_item):
    """Transaction item exchanged between SMC I2C sequences and the driver."""

    def __init__(self, name: str = "SmcI2cItem") -> None:
        super().__init__(name)
        self.op: SmcI2cOp = SmcI2cOp.SAMPLE
        # Result fields populated by the driver after the operation.
        self.cg_en: int = -1
        self.debug_lo: int = -1
        self.resolvable: bool = False

    def __str__(self) -> str:
        return (
            f"SmcI2cItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"cg_en={self.cg_en}, debug_lo=0x{self.debug_lo & 0xf:x})"
        )
