# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS GPIO observer."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item

# The three OR-reduction aggregates. All three are declared unbackable in
# env.smc_probe_liveness.UNBACKABLE_PROBES: they read 1 from reset onward and no
# frontdoor stimulus can drive them to 0, so they are OBSERVED-ONLY diagnostics
# and a stated expect_<field> on them is refused by the scoreboard.
GPIO_SAMPLE_FIELDS = ("core2pad_any", "core2pad_en_any", "pad2core_en_any")

# The raw pad-output bus vectors mirrored at tb_top (tb_core2pad_o /
# tb_core2pad_en_o). Unlike the aggregates these MOVE under real frontdoor GPIO
# CSR programming, which is what makes a stated expectation on them backable:
# seq_lib.smc_probe_positive_control.prove_gpio_pad_bus_probe proves a single-bit
# delta and credits gpio_core2pad_vec / gpio_core2pad_en_vec in the liveness
# ledger, and the scoreboard books a vector compare as checked evidence only
# when that credit exists ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
GPIO_VECTOR_FIELDS = ("core2pad_vec", "core2pad_en_vec")

# The subset of GPIO_VECTOR_FIELDS a *persistence* (cross-sample stability)
# expectation may be stated on. `core2pad_en_vec` is configuration-driven: it
# only changes when something programs a pad's output enable, so an exact
# cross-sample equality on it is a real property.
#
# `core2pad_vec` is NOT here. It is the pad *value* bus, and it
# carries free-running DUT outputs -- tb_top.sv takes the AVSBus clock from
# `core2pad_o[49]` and the OCTS strobes from `[55]`/`[56]` -- so bit 49
# toggles between two samples with no GPIO stimulus at all. An exact
# cross-sample expectation on it would be a flaky check, not a proof, so it is
# an OBSERVED-ONLY diagnostic in the stability sequences. It is a *credited*
# probe because the pad-bus positive control proves it moves under real CSR
# programming, which is what a per-pad masked compare (e.g.
# smc_gpio_output_driveback_test) needs.
GPIO_STABLE_VECTOR_FIELDS = ("core2pad_en_vec",)

# field -> logical liveness-ledger probe name.
GPIO_FIELD_PROBES = {
    "core2pad_any": "gpio_core2pad_any",
    "core2pad_en_any": "gpio_core2pad_en_any",
    "pad2core_en_any": "gpio_pad2core_en_any",
    "core2pad_vec": "gpio_core2pad_vec",
    "core2pad_en_vec": "gpio_core2pad_en_vec",
}

# field -> tb_top signal, for log/diagnostic text.
GPIO_FIELD_SIGNALS = {
    "core2pad_any": "tb_gpio_core2pad_any",
    "core2pad_en_any": "tb_gpio_core2pad_en_any",
    "pad2core_en_any": "tb_gpio_pad2core_en_any",
    "core2pad_vec": "tb_core2pad_o",
    "core2pad_en_vec": "tb_core2pad_en_o",
}


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
        # Raw pad-output bus vectors (tb_core2pad_o / tb_core2pad_en_o) and their
        # width. -1 = not sampled (the tb_top mirror is absent).
        self.core2pad_vec: int = -1
        self.core2pad_en_vec: int = -1
        self.vec_width: int = 0
        # --- Optional exact expectations (None = "not checked here") ---------
        # Aggregates: unbackable, so a stated expectation on one of these is
        # REFUSED by SmcScoreboard._check_gpio (see GPIO_SAMPLE_FIELDS above).
        # The attributes exist so the refusal is a loud AssertionError naming
        # the rule rather than an AttributeError.
        self.expect_core2pad_any: int | None = None
        self.expect_core2pad_en_any: int | None = None
        self.expect_pad2core_en_any: int | None = None
        # Vectors: backable. A sequence that established (or is asserting the
        # persistence of) a pad-bus state sets these and gets a fail-capable
        # exact compare, booked as checked evidence when the pad-bus positive
        # control credited the probe in the same run.
        self.expect_core2pad_vec: int | None = None
        self.expect_core2pad_en_vec: int | None = None

    def expectations(self) -> list[tuple[str, int]]:
        """(field, expected) pairs this item explicitly asks to be compared."""
        return [
            (f, getattr(self, "expect_" + f))
            for f in GPIO_SAMPLE_FIELDS + GPIO_VECTOR_FIELDS
            if getattr(self, "expect_" + f) is not None
        ]

    @staticmethod
    def fmt_vec(value: int) -> str:
        """Render a sampled vector: hex, or ``not-sampled`` for the -1 default."""
        return "not-sampled" if value < 0 else f"0x{value:x}"

    def __str__(self) -> str:
        return (
            f"SmcGpioItem(op={self.op.value}, resolvable={self.resolvable}, "
            f"core2pad_any={self.core2pad_any}, "
            f"core2pad_en_any={self.core2pad_en_any}, "
            f"pad2core_en_any={self.pad2core_en_any}, "
            f"core2pad_vec={self.fmt_vec(self.core2pad_vec)}, "
            f"core2pad_en_vec={self.fmt_vec(self.core2pad_en_vec)}, "
            f"vec_width={self.vec_width})"
        )
