# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Entropy FIFO functional and security scenarios."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import FallingEdge, RisingEdge, Timer
from entropy_source_base_test import EntropySourceTb
from entropy_source_scenarios import FIFO_DEPTH, fifo_flush, fifo_pop, fifo_push


async def _start(dut, name):
    tb = EntropySourceTb(dut, name)
    await tb.start()
    return tb


@cocotb.test()
async def test_2_1_1_reset_behavior(dut):
    await _start(dut, "fifo_reset")
    assert int(dut.fifo_level.value) == 0
    assert int(dut.fifo_wptr.value) == 0
    assert int(dut.fifo_rptr.value) == 0
    assert int(dut.fifo_security_alert.value) == 0


@cocotb.test()
async def test_2_1_2_single_push_operation(dut):
    tb = await _start(dut, "fifo_single_push")
    await fifo_push(tb, 0xA55A1234)
    assert int(dut.fifo_level.value) == 1
    assert int(dut.fifo_rdata.value) == 0xA55A1234


@cocotb.test()
async def test_2_1_3_single_pop_operation(dut):
    tb = await _start(dut, "fifo_single_pop")
    await fifo_push(tb, 0x10203040)
    assert await fifo_pop(tb) == 0x10203040
    assert int(dut.fifo_level.value) == 0


@cocotb.test()
async def test_2_1_4_fill_and_drain_sequence(dut):
    tb = await _start(dut, "fifo_fill_drain")
    expected = [0x60000000 | i for i in range(FIFO_DEPTH)]
    for word in expected:
        await fifo_push(tb, word)
    assert int(dut.fifo_level.value) == FIFO_DEPTH
    observed = [await fifo_pop(tb) for _ in expected]
    assert observed == expected
    assert int(dut.fifo_level.value) == 0


@cocotb.test()
async def test_2_1_5_simultaneous_push_and_pop(dut):
    tb = await _start(dut, "fifo_simultaneous")
    await fifo_push(tb, 0x11111111)
    dut.fifo_wdata.value = 0x22222222
    dut.fifo_push.value = 1
    dut.fifo_pop.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    dut.fifo_push.value = 0
    dut.fifo_pop.value = 0
    assert int(dut.fifo_level.value) == 1
    assert int(dut.fifo_rdata.value) == 0x22222222


@cocotb.test()
async def test_2_2_1_pointer_wraparound(dut):
    tb = await _start(dut, "fifo_wrap")
    for i in range(FIFO_DEPTH * 2):
        await fifo_push(tb, i)
        assert await fifo_pop(tb) == i
    assert int(dut.fifo_level.value) == 0
    assert int(dut.fifo_wptr.value) == 0
    assert int(dut.fifo_rptr.value) == 0


@cocotb.test()
async def test_2_3_1_overflow_detection(dut):
    tb = await _start(dut, "fifo_overflow")
    for i in range(FIFO_DEPTH):
        await fifo_push(tb, i)
    dut.fifo_wdata.value = 0xDEADBEEF
    dut.fifo_push.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_overflow.value) == 1
    assert int(dut.fifo_level.value) == FIFO_DEPTH
    dut.fifo_push.value = 0


@cocotb.test()
async def test_2_3_2_underflow_detection(dut):
    await _start(dut, "fifo_underflow")
    dut.fifo_pop.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_underflow.value) == 1
    dut.fifo_pop.value = 0


@cocotb.test()
async def test_2_4_1_data_pattern_tests(dut):
    tb = await _start(dut, "fifo_patterns")
    patterns = [0, 0xFFFFFFFF, 0xAAAAAAAA, 0x55555555, 0x01234567, 0x89ABCDEF]
    for word in patterns:
        await fifo_push(tb, word)
    assert [await fifo_pop(tb) for _ in patterns] == patterns


@cocotb.test()
async def test_2_5_1_fifo_enable_disable(dut):
    tb = await _start(dut, "fifo_control")
    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 1)
    assert await tb.seq.read(reg.FIFO_CTRL_REG_ADDR) & 1
    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
    assert (await tb.seq.read(reg.FIFO_CTRL_REG_ADDR) & 1) == 0


@cocotb.test()
async def test_2_5_2_fifo_rdata_autopop(dut):
    tb = await _start(dut, "fifo_autopop")
    for word in (0xA, 0xB, 0xC):
        await fifo_push(tb, word)
    assert await fifo_pop(tb) == 0xA
    assert int(dut.fifo_level.value) == 2
    assert int(dut.fifo_rdata.value) == 0xB


@cocotb.test()
async def test_2_6_1_fifo_intr_test_and_error(dut):
    tb = await _start(dut, "fifo_interrupt")
    mask = 1 << 4
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, mask)
    await tb.seq.write(reg.INTR_TEST_REG_ADDR, mask)
    await RisingEdge(dut.clk)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & mask
    assert int(dut.irq.value) == 1
    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, mask)
    await RisingEdge(dut.clk)
    assert int(dut.irq.value) == 0


@cocotb.test()
async def test_2_7_1_parity_generation(dut):
    tb = await _start(dut, "fifo_parity_generation")
    for i in range(FIFO_DEPTH):
        await fifo_push(tb, (i * 0x10204081) & 0xFFFFFFFF)
        assert int(dut.fifo_parity_error.value) == 0
    for _ in range(FIFO_DEPTH):
        await fifo_pop(tb)
        assert int(dut.fifo_parity_error.value) == 0


@cocotb.test()
async def test_2_7_2_parity_error_detection(dut):
    tb = await _start(dut, "fifo_parity_fault")
    await fifo_push(tb, 0x12345678)
    entry = dut.u_fifo.mem[0]
    entry.value = int(entry.value) ^ (1 << 32)
    await Timer(1, unit="ns")
    assert int(dut.fifo_parity_error.value) == 1
    assert int(dut.fifo_security_alert.value) == 1


@cocotb.test()
async def test_2_7_3_pointer_fault_detection(dut):
    tb = await _start(dut, "fifo_pointer_fault")
    await fifo_push(tb, 0x12345678)
    dut.fifo_pointer_fault_inject.value = 1
    await RisingEdge(dut.clk)
    await FallingEdge(dut.clk)
    assert int(dut.fifo_pointer_error.value) == 1
    assert int(dut.fifo_security_alert.value) == 1

    level = int(dut.fifo_level.value)
    await fifo_push(tb, 0xDEADBEEF)
    assert int(dut.fifo_level.value) == level
    dut.fifo_pointer_fault_inject.value = 0


@cocotb.test()
async def test_2_7_4_combined_security_alert(dut):
    tb = await _start(dut, "fifo_security_alert")
    await fifo_push(tb, 0xCAFEBABE)
    entry = dut.u_fifo.mem[0]
    entry.value = int(entry.value) ^ (1 << 33)
    await Timer(1, unit="ns")
    assert int(dut.fifo_parity_error.value) == 1
    assert int(dut.fifo_security_alert.value) == 1
    await fifo_flush(tb)


@cocotb.test()
async def test_fifo_churn_xor_behavior(dut):
    tb = await _start(dut, "fifo_churn")
    baseline = [(0x10204081 * (index + 1)) & 0xFFFFFFFF for index in range(FIFO_DEPTH)]
    for word in baseline:
        await fifo_push(tb, word)
    assert [await fifo_pop(tb) for _ in range(FIFO_DEPTH // 2)] == baseline[: FIFO_DEPTH // 2]

    incoming = [0xA5000000 | index for index in range(FIFO_DEPTH // 2)]
    expected = [word ^ baseline[index + FIFO_DEPTH // 2] for index, word in enumerate(incoming)]
    for word in incoming:
        await fifo_push(tb, word, churn=True)

    assert [await fifo_pop(tb) for _ in range(FIFO_DEPTH // 2)] == baseline[FIFO_DEPTH // 2 :]
    assert [await fifo_pop(tb) for _ in range(FIFO_DEPTH // 2)] == expected
