# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Debug-monitor register and boundary scenarios."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import Timer
from entropy_source_base_test import EntropySourceTb


@cocotb.test()
async def test_4_1_1_debug_ctrl_register_access(dut):
    tb = EntropySourceTb(dut, "debug_csr")
    await tb.start()
    value = (7 << 8) | 0xA5
    await tb.seq.write(reg.DEBUG_CTRL_REG_ADDR, value)
    assert await tb.seq.read(reg.DEBUG_CTRL_REG_ADDR) == value


@cocotb.test()
async def test_4_1_2_signal_index_boundary_values(dut):
    tb = EntropySourceTb(dut, "debug_index")
    await tb.start()
    dut.debug_select_div.value = 0
    for index in (0, 1, 127, 254, 255):
        dut.debug_select_signal.value = index
        dut.debug_signals.value = 1 << index
        await Timer(1, unit="ns")
        assert int(dut.debug_monitor.value) == 1
        dut.debug_signals.value = 0
        await Timer(1, unit="ns")
        assert int(dut.debug_monitor.value) == 0


@cocotb.test()
async def test_4_1_3_frequency_selector_boundary_values(dut):
    tb = EntropySourceTb(dut, "debug_divider")
    await tb.start()
    dut.debug_select_signal.value = 0
    for divider in (0, 1, 3, 7):
        dut.rst_n.value = 0
        await Timer(1, unit="ns")
        dut.rst_n.value = 1
        dut.debug_select_div.value = divider
        observed = []
        for _ in range(1 << (divider + 1)):
            dut.debug_signals.value = 1
            await Timer(1, unit="ns")
            observed.append(int(dut.debug_monitor.value))
            dut.debug_signals.value = 0
            await Timer(1, unit="ns")
        assert 1 in observed


@cocotb.test()
async def test_debug_frequency_divider_ratios(dut):
    tb = EntropySourceTb(dut, "debug_divider_ratios")
    await tb.start()
    dut.debug_select_signal.value = 0

    transition_counts = []
    for divider in range(8):
        dut.rst_n.value = 0
        dut.debug_select_div.value = divider
        dut.debug_signals.value = 0
        await Timer(4, unit="ns")
        dut.rst_n.value = 1
        await Timer(4, unit="ns")

        previous = int(dut.debug_monitor.value)
        transitions = 0
        for index in range(2048):
            dut.debug_signals.value = index & 1
            await Timer(1, unit="ns")
            current = int(dut.debug_monitor.value)
            transitions += current != previous
            previous = current
        transition_counts.append(transitions)

    assert all(count > 0 for count in transition_counts)
    for faster, slower in zip(transition_counts, transition_counts[1:]):
        assert 1.8 <= faster / slower <= 2.2
