# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS I2C observation agent."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item


class SmcI2cOp(Enum):
    """Observation operations the I2C agent supports.

    Only ``SAMPLE`` is defined: observability of the SMC-internal I2C clock-gate
    enable and the lowest I2C controller debug nibble, lifted to tb_top as
    ``tb_i2c_cg_en`` / ``tb_i2c_debug_lo``. Pad-level I2C traffic is driven by
    ``seq_lib/smc_i2c_protocol_vip.py``, not by this agent.
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
        # --- Optional exact expectations --------------------------------------
        # cg_en: None => the idle default 0. A sequence that has programmed the
        # I2C clock gate on sets expect_cg_en=1 so the same probe gets a
        # positive control ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        self.expect_cg_en: int | None = None
        # debug_lo: None => sampled for diagnostics only, NOT compared. There is
        # no SPEC/RDL reset value for the probed i2c_debug[0] nibble in this
        # environment, so the scoreboard refuses to invent one and instead
        # labels the field OBSERVED-ONLY in its log line. A sequence with an
        # independently sourced expectation sets it and gets a real compare.
        self.expect_debug_lo: int | None = None

    def expected_cg_en(self) -> int:
        return 0 if self.expect_cg_en is None else self.expect_cg_en

    def __str__(self) -> str:
        return (
            f"SmcI2cItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"cg_en={self.cg_en}, debug_lo=0x{self.debug_lo & 0xF:x})"
        )
