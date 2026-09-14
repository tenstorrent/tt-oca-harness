# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transaction items for the SMC OSS reset agent."""

from __future__ import annotations

from enum import Enum

from pyuvm import uvm_sequence_item

# Every reset observable the driver samples, in log order. Anything sampled and
# logged must appear here so it also gets a fail-capable compare
# ([EXACT-EXPECTATION]: an observed-but-never-compared field reads as checked).
RESET_SAMPLE_FIELDS = (
    "powergood_stable",
    "rst_cold_stable_ref_clk_n",
    "rst_primary_ref_clk_n",
    "rst_primary_smc_clk_n",
    "rst_wdt_smc_clk_n",
)

# The subset whose all-1 combination means "DUT is fully in the post-release
# stable state". `expect_left_stable` fails when all of these read 1.
RESET_POST_STABLE_FIELDS = RESET_SAMPLE_FIELDS[:4]


class SmcResetOp(Enum):
    """Operations the reset agent supports."""

    SAMPLE = "SAMPLE"
    RAW_SAMPLE = "RAW_SAMPLE"
    # Bounded poll until the requested expect_* state is observed. Expiry is a
    # testcase failure with last-state diagnostics ([TIMEOUT-MUST-FAIL]): a
    # handshake, not a fixed ClockCycles delay followed by SAMPLE.
    WAIT_STATE = "WAIT_STATE"
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
        # --- Optional exact expectations (None = "not checked here") ---------
        # On SAMPLE every field defaults to the post-release value 1; set an
        # expect_* to override one leg with a SPEC-exact value for that leg.
        # On RAW_SAMPLE / WAIT_STATE nothing is checked unless at least one
        # expect_* (or expect_left_stable) is set: a mid-glitch snapshot has no
        # post-release invariant to assert, so the sequence owns the contract.
        self.expect_powergood_stable: int | None = None
        self.expect_rst_cold_stable_ref_clk_n: int | None = None
        self.expect_rst_primary_ref_clk_n: int | None = None
        self.expect_rst_primary_smc_clk_n: int | None = None
        self.expect_rst_wdt_smc_clk_n: int | None = None
        # True => this sample must NOT be in the fully post-stable state, i.e.
        # the driven glitch/assert had an observable effect. Fails when
        # powergood_stable / cold-stable / both primary resets all read 1.
        self.expect_left_stable: bool = False
        # WAIT_STATE bound + results.
        self.timeout_ref_cycles: int = 2000
        self.timed_out: bool = False
        self.wait_ref_cycles: int = -1

    def expectations(self) -> list[tuple[str, int]]:
        """(field, expected) pairs this item explicitly asks to be compared."""
        return [
            (f, getattr(self, "expect_" + f))
            for f in RESET_SAMPLE_FIELDS
            if getattr(self, "expect_" + f) is not None
        ]

    def __str__(self) -> str:
        if self.op in (SmcResetOp.SAMPLE, SmcResetOp.RAW_SAMPLE, SmcResetOp.WAIT_STATE):
            tail = ""
            if self.op is SmcResetOp.WAIT_STATE:
                tail = f", timed_out={self.timed_out}, wait_ref_cycles={self.wait_ref_cycles}"
            return (
                f"SmcResetItem(op={self.op.value}, resolvable={self.resolvable}, "
                f"powergood_stable={self.powergood_stable}, "
                f"rst_cold_stable_ref={self.rst_cold_stable_ref_clk_n}, "
                f"rst_primary_ref={self.rst_primary_ref_clk_n}, "
                f"rst_primary_smc={self.rst_primary_smc_clk_n}, "
                f"rst_wdt_smc={self.rst_wdt_smc_clk_n}{tail})"
            )
        return f"SmcResetItem(op={self.op.value})"
