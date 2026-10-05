# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS AXI-Lite observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item

AXIL_PORT_FIELDS = ("dtp_csr_active", "external_active", "efuse_bank_active")
AXIL_SAMPLE_FIELDS = AXIL_PORT_FIELDS + ("any_master_active",)

# Fields whose idle `== 0` may be asserted, because a positive control for the
# probe can exist in this TB. `dtp_csr_active` is excluded: tb_top ties
# `axil_dtp_csr_resp = '0'`, so there is no responder and an AXI-Lite access
# into the DTP CSR window would wedge instead of completing. Any sequence-side
# idle helper must iterate this tuple, not AXIL_SAMPLE_FIELDS, and report
# `dtp_csr_active` as OBSERVED-ONLY / not closure evidence
# ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
AXIL_UNBACKABLE_FIELDS = ("dtp_csr_active",)
AXIL_CHECKABLE_FIELDS = tuple(f for f in AXIL_SAMPLE_FIELDS if f not in AXIL_UNBACKABLE_FIELDS)


class SmcAxilOp(Enum):
    SAMPLE = "SAMPLE"


class SmcAxilItem(uvm_sequence_item):
    def __init__(self, name: str = "SmcAxilItem") -> None:
        super().__init__(name)
        self.op: SmcAxilOp = SmcAxilOp.SAMPLE
        # Per-interface activity bits (1 = at least one *_valid handshake high).
        self.dtp_csr_active: int = -1
        self.external_active: int = -1
        self.efuse_bank_active: int = -1
        # OR-of-all across the five interfaces.
        self.any_master_active: int = -1
        self.resolvable: bool = False
        # --- Positive control for the idle probe -----------------------------
        # The default (all expectations None) is the idle contract: every
        # sampled activity bit must read 0. That alone is a negative check --
        # a stuck-at-0 or mis-bound probe passes it identically. A sequence
        # driving real AXI-Lite master traffic sets the leg it drove to 1 so
        # the same probe is proven able to read 1
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]), then re-samples with the
        # default to prove it returns to idle.
        self.expect_dtp_csr_active: int | None = None
        self.expect_external_active: int | None = None
        self.expect_efuse_bank_active: int | None = None
        self.expect_any_master_active: int | None = None

    def expected(self, field: str) -> int:
        """Expected value for `field`: the item's override, else idle 0."""
        exp = getattr(self, "expect_" + field)
        return 0 if exp is None else exp

    def __str__(self) -> str:
        return (
            f"SmcAxilItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"any={self.any_master_active}, dtp={self.dtp_csr_active}, "
            f"ext={self.external_active}, efuse={self.efuse_bank_active})"
        )
