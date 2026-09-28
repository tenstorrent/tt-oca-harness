# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Resolve a signal by the role it plays on the loaded SMU testbench top.

A sequence asks for a signal by role rather than by pin name, and each helper
here accepts the spellings a top may give it -- the AXI slave as ``ext_in_*``
or ``s_axi_*``, the SMC primary reset observable as ``rst_primary_smc_clk_n_o``
or ``rst_primary_smc_clk_no`` -- so the sequence does not depend on how the
top flattens the DUT's ports.
"""

from __future__ import annotations

from typing import Any


def _child(dut: Any, name: str) -> Any:
    """Absent child as None, whichever way this cocotb version reports it.

    Handles raise on a missing child rather than returning None, and not always
    as AttributeError, so the default argument to getattr is not enough.
    """
    try:
        return getattr(dut, name)
    except Exception:  # noqa: BLE001 - the handle's own exception type varies
        return None


def tb_pin(dut: Any, *names: str) -> Any:
    """First of ``names`` this testbench top exposes.

    Raises rather than returning None: a sequence that reaches for a signal no
    TB has is a bug in the sequence, and a silent None would surface much later
    as an unrelated failure.
    """
    for name in names:
        handle = _child(dut, name)
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
    return "s_axi" if _child(dut, "s_axi_awvalid") is not None else "ext_in"


def smu_scope(dut: Any) -> Any:
    """The `smu` instance, wherever this testbench put it.

    tb_wrapper_top.sv's u_dut is smu_wrapper, with smu one level down as
    u_smu; a top that instantiates smu directly as u_dut resolves too. A
    sequence reaching into smu's own hierarchy asks for this rather than
    writing the path out.
    """
    u_dut = tb_pin(dut, "u_dut")
    # `is not None`, not a truth test: a cocotb handle raises TypeError when
    # cast to bool.
    inner = _child(u_dut, "u_smu")
    return u_dut if inner is None else inner
