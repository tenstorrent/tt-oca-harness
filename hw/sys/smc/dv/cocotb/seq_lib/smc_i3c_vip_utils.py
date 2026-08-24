# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I3C pin-level helpers for SMC OSS tests."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles


async def check_i3c0_external_pull_low() -> None:
    """Verify the I3C0 resolved SCL/SDA lines respond to external pull-low.

    Drives the split-port ``tb_i3c0_{scl,sda}_ext_low`` controls through a
    release / SCL-low / SDA-low / release sequence and asserts the resolved
    ``tb_i3c0_{scl,sda}`` lines follow. This check is the primary gate for
    I3C0 line health.
    """
    dut = cocotb.top

    dut.tb_i3c0_scl_ext_low.value = 0
    dut.tb_i3c0_sda_ext_low.value = 0
    await ClockCycles(dut.clk_smc_i, 20)
    assert int(dut.tb_i3c0_scl.value) == 1, "I3C0 SCL should release high"
    assert int(dut.tb_i3c0_sda.value) == 1, "I3C0 SDA should release high"

    dut.tb_i3c0_scl_ext_low.value = 1
    await ClockCycles(dut.clk_smc_i, 20)
    assert int(dut.tb_i3c0_scl.value) == 0, "I3C0 external SCL pull-low not observed"
    assert int(dut.tb_i3c0_sda.value) == 1, "I3C0 SDA should stay released"

    dut.tb_i3c0_scl_ext_low.value = 0
    dut.tb_i3c0_sda_ext_low.value = 1
    await ClockCycles(dut.clk_smc_i, 20)
    assert int(dut.tb_i3c0_scl.value) == 1, "I3C0 SCL should release high"
    assert int(dut.tb_i3c0_sda.value) == 0, "I3C0 external SDA pull-low not observed"

    dut.tb_i3c0_sda_ext_low.value = 0
    await ClockCycles(dut.clk_smc_i, 20)
    assert int(dut.tb_i3c0_scl.value) == 1, "I3C0 SCL release restore failed"
    assert int(dut.tb_i3c0_sda.value) == 1, "I3C0 SDA release restore failed"


__all__ = [
    "check_i3c0_external_pull_low",
]
