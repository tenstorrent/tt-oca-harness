# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-monitor signal selection and divider checks."""

import cocotb
from cocotb.triggers import Timer
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def entropy_source_debug_test(dut) -> None:
    tb = EntropySourceTb(dut, "entropy_source_debug_test")
    await tb.start()

    selected_bit = 7
    dut.debug_select_signal.value = selected_bit
    dut.debug_select_div.value = 0

    dut.debug_signals.value = 1 << 3
    await Timer(1, unit="ns")
    assert int(dut.debug_monitor.value) == 0

    dut.debug_signals.value = 1 << selected_bit
    await Timer(1, unit="ns")
    assert int(dut.debug_monitor.value) == 1

    dut.debug_signals.value = 0
    await Timer(1, unit="ns")
    assert int(dut.debug_monitor.value) == 0

    dut.rst_n.value = 0
    await Timer(1, unit="ns")
    dut.rst_n.value = 1
    await Timer(1, unit="ns")
    dut.debug_select_div.value = 1
    states = []
    for _ in range(4):
        dut.debug_signals.value = 1 << selected_bit
        await Timer(1, unit="ns")
        states.append(int(dut.debug_monitor.value))
        dut.debug_signals.value = 0
        await Timer(1, unit="ns")
    assert states == [1, 0, 1, 0]
