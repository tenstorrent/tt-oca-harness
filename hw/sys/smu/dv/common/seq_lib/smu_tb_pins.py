# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Resolve a signal by whichever name the loaded SMU testbench gives it.

seq_lib is shared by both SMU DUTs, so a sequence cannot hardcode a pin name:
tb/tb_top.sv and tb/tb_wrapper_top.sv expose the same signals under different
ones. The differences are naming, not substance -- the AXI slave is
``s_axi_*`` against ``ext_in_*``, and the SMC primary reset observable is
``rst_primary_smc_clk_no`` against ``rst_primary_smc_clk_n_o``.

Ask for the signal by role instead, and the sequence runs on either DUT.
"""

from __future__ import annotations

from typing import Any


def tb_pin(dut: Any, *names: str) -> Any:
    """First of ``names`` this testbench top exposes.

    Raises rather than returning None: a sequence that reaches for a signal no
    TB has is a bug in the sequence, and a silent None would surface much later
    as an unrelated failure.
    """
    for name in names:
        handle = getattr(dut, name, None)
        if handle is not None:
            return handle
    raise AssertionError(f"none of {names} exists on this TB top ({type(dut).__name__})")


def smc_primary_reset(dut: Any) -> Any:
    """Active-low SMC primary reset observable."""
    return tb_pin(dut, "rst_primary_smc_clk_no", "rst_primary_smc_clk_n_o")


def cold_stable_reset(dut: Any) -> Any:
    """Active-low cold-stable reset observable, on the ref clock."""
    return tb_pin(dut, "rst_cold_stable_ref_clk_no", "rst_cold_n_o")


def smu_axi_in_prefix(dut: Any) -> str:
    """Flattened-signal prefix for the SMU AXI slave on this TB."""
    return "s_axi" if getattr(dut, "s_axi_awvalid", None) is not None else "ext_in"
