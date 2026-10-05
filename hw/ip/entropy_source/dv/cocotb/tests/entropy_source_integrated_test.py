# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Integrated entropy-source datapath, CSR, and interrupt scenarios."""

import cocotb
import entropy_source_reg as reg
from cocotb.triggers import ClockCycles, FallingEdge
from entropy_source_base_test import EntropySourceTb
from models.entropy_conditioning_model import EntropyBiwModel
from models.entropy_noise_model import EntropyNoiseModel


def _fifo_level(status: int) -> int:
    return status & 0x7F


def _fifo_wptr(status: int) -> int:
    return (status >> 8) & 0x3F


def _fifo_rptr(status: int) -> int:
    return (status >> 16) & 0x3F


async def _drive_entropy_model(tb: EntropySourceTb) -> None:
    noise = EntropyNoiseModel()
    noise.configure("unbiased", seed_base=0x1A2B3C4D)
    lane_bytes = [0] * 12
    while True:
        await FallingEdge(tb.dut.clk)
        if tb._entropy_constant is None:
            samples = noise.step_all()
            for lane in range(12):
                lane_bytes[lane] = ((lane_bytes[lane] << 1) | ((samples >> lane) & 1)) & 0xFF
            packed = sum(value << (lane * 8) for lane, value in enumerate(lane_bytes))
            word = EntropyBiwModel.compress_from_packed(packed)
        else:
            word = tb._entropy_constant
            packed = sum(((word >> ((lane % 4) * 8)) & 0xFF) << (lane * 8) for lane in range(12))
        tb.dut.dut_entropy_inject_data.value = word
        tb.dut.dut_entropy_inject_uncompressed.value = packed
        tb.dut.dut_entropy_inject_valid.value = 1


async def _configure_fast_integrated_path(
    tb: EntropySourceTb,
    *,
    downsample: int = 0,
    bypass_compressor: bool = True,
    fifo_enable: bool = True,
    health_enable: int = 0,
    repetition_limit: int = 25,
    autotune: bool = False,
    entropy_constant: int | None = None,
    generator_fault: bool = False,
) -> None:
    """Configure the production DUT for a short, deterministic simulation cadence."""
    tb._entropy_constant = entropy_constant
    if not hasattr(tb, "_entropy_driver"):
        tb._entropy_driver = cocotb.start_soon(_drive_entropy_model(tb))
    tb.dut.dut_entropy_inject_enable.value = 0
    tb.dut.dut_generator_fault_inject.value = 0
    seq = tb.seq
    await seq.write(reg.CTRL_REG_ADDR, 1 << 8)
    await seq.write(reg.HEALTH_TEST_WINDOW_SIZE_REG_ADDR, 4)
    await seq.write(
        reg.HEALTH_TEST_CTRL_REG_ADDR,
        (repetition_limit << 8) | health_enable,
    )
    await seq.write(reg.RING_OSC_CTRL_REG_ADDR, 0)
    await seq.write(reg.RING_OSC_ENABLE_REG_ADDR, 0xFFF)
    for address in range(
        reg.GENERATOR_0_SAMPLE_CLK_CONFIG_REG_ADDR,
        reg.GENERATOR_11_SAMPLE_CLK_CONFIG_REG_ADDR + 4,
        4,
    ):
        await seq.write(address, 0)
    await seq.write(reg.DECORRELATOR_CTRL_REG_ADDR, 0xFFF)
    await seq.write(reg.DECORRELATOR_MASK_REG_ADDR, 0xFF)
    await seq.write(reg.FIFO_CTRL_REG_ADDR, int(fifo_enable))
    ctrl = (
        (1 << 1)
        | (int(autotune) << 4)
        | (int(bypass_compressor) << 8)
        | ((downsample & 0x3FF) << 16)
        | (1 << 28)
    )
    await seq.write(reg.CTRL_REG_ADDR, ctrl)
    tb.dut.dut_entropy_inject_enable.value = 1
    tb.dut.dut_generator_fault_inject.value = int(generator_fault)


async def _wait_fifo_level(tb: EntropySourceTb, minimum: int, cycles: int = 5000) -> int:
    for _ in range(cycles):
        status = await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)
        if _fifo_level(status) >= minimum:
            return status
        await ClockCycles(tb.dut.clk, 1)
    raise AssertionError(f"integrated FIFO did not reach level {minimum}")


async def _wait_status_bit(tb: EntropySourceTb, mask: int, cycles: int = 5000) -> int:
    for _ in range(cycles):
        status = await tb.seq.read(reg.INTR_STATUS_REG_ADDR)
        if status & mask:
            return status
        await ClockCycles(tb.dut.clk, 1)
    raise AssertionError(f"interrupt status 0x{mask:08x} did not assert")


async def _wait_boot(tb: EntropySourceTb, cycles: int = 5000) -> None:
    for _ in range(cycles):
        if int(tb.dut.dut_boot_phase_done.value):
            return
        await ClockCycles(tb.dut.clk, 1)
    raise AssertionError("integrated entropy-source boot gate did not open")


async def _reset(tb: EntropySourceTb) -> None:
    tb.dut.rst_n.value = 0
    await ClockCycles(tb.dut.clk, 5)
    tb.dut.rst_n.value = 1
    await ClockCycles(tb.dut.clk, 5)


@cocotb.test()
async def test_integrated_entropy_stream_and_fifo_csr(dut):
    tb = EntropySourceTb(dut, "integrated_entropy_stream_and_fifo_csr")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(tb)
    overflow = 1 << 8
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, overflow)

    await _wait_fifo_level(tb, 6)
    stream_words = []
    for _ in range(200):
        await ClockCycles(dut.clk, 1)
        if int(dut.entropy_stream_valid.value):
            stream_words.append(int(dut.entropy_stream_data.value))
    assert len(stream_words) >= 4
    assert len(set(stream_words)) > 1

    await _wait_fifo_level(tb, 64)
    await ClockCycles(dut.clk, 8)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & overflow
    assert int(dut.irq.value) == 1

    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, overflow)
    status = await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)
    level_before = _fifo_level(status)
    rptr_before = _fifo_rptr(status)
    words = [await tb.seq.read(reg.FIFO_RDATA_REG_ADDR) for _ in range(4)]
    status = await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)

    assert _fifo_level(status) == level_before - 4
    assert _fifo_rptr(status) == (rptr_before + 4) % 64
    assert len(set(words)) > 1
    assert any(words)


@cocotb.test()
async def test_integrated_fifo_enable_and_underflow_irq(dut):
    tb = EntropySourceTb(dut, "integrated_fifo_enable_and_underflow_irq")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(tb, fifo_enable=False)

    await ClockCycles(dut.clk, 64)
    assert _fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)) == 0

    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 1)
    await _wait_fifo_level(tb, 4)
    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
    frozen = await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)
    await ClockCycles(dut.clk, 64)
    assert _fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)) == _fifo_level(frozen)

    while _fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)):
        await tb.seq.read(reg.FIFO_RDATA_REG_ADDR)

    underflow = 1 << 12
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, underflow)
    await tb.seq.read(reg.FIFO_RDATA_REG_ADDR)
    await ClockCycles(dut.clk, 2)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & underflow
    assert int(dut.irq.value) == 1
    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, underflow)
    await ClockCycles(dut.clk, 2)
    assert int(dut.irq.value) == 0


@cocotb.test()
async def test_integrated_fifo_pointer_fault_irq(dut):
    tb = EntropySourceTb(dut, "integrated_fifo_pointer_fault_irq")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(tb)
    await _wait_fifo_level(tb, 4)
    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
    fifo_error = 1 << 4
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, fifo_error)

    dut.fifo_pointer_fault_inject.value = 1
    await ClockCycles(dut.clk, 3)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & fifo_error
    assert int(dut.irq.value) == 1
    level = _fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR))

    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 1)
    await ClockCycles(dut.clk, 32)
    assert _fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)) == level

    dut.fifo_pointer_fault_inject.value = 0
    await _reset(tb)
    assert int(dut.irq.value) == 0


@cocotb.test()
async def test_integrated_fifo_parity_fault_irq(dut):
    tb = EntropySourceTb(dut, "integrated_fifo_parity_fault_irq")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(tb)
    status = await _wait_fifo_level(tb, 4)
    await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
    fifo_error = 1 << 4
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, fifo_error)

    read_pointer = _fifo_rptr(status)
    entry = dut.u_dut.u_entropy_fifo.mem[read_pointer]
    entry.value = int(entry.value) ^ (1 << 32)
    await ClockCycles(dut.clk, 3)
    assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & fifo_error
    assert int(dut.irq.value) == 1


@cocotb.test()
async def test_integrated_health_failure_counters_and_irq(dut):
    tb = EntropySourceTb(dut, "integrated_health_failure_counters_and_irq")
    await tb.start(disable_dut=False)
    health_irq = 1
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, health_irq)
    await tb.seq.write(reg.ALERT_THRESHOLD_REG_ADDR, 0)
    await _configure_fast_integrated_path(
        tb,
        bypass_compressor=False,
        fifo_enable=False,
        health_enable=0b001,
        repetition_limit=1,
        entropy_constant=0,
    )

    await _wait_status_bit(tb, health_irq)
    assert int(dut.dut_health_status.value) & 1
    assert await tb.seq.read(reg.HEALTH_TEST_STATUS_REG_ADDR) & 1
    assert await tb.seq.read(reg.REPETITION_TEST_COUNT_REG_ADDR) > 0
    assert await tb.seq.read(reg.REPCNT_TOTAL_FAILS_REG_ADDR) > 0
    assert int(dut.irq.value) == 1
    await tb.seq.write(reg.HEALTH_TEST_CTRL_REG_ADDR, 0)
    await tb.seq.write(reg.HEALTH_TEST_STATUS_REG_ADDR, 0xFF)
    await tb.seq.write(reg.INTR_STATUS_REG_ADDR, health_irq)
    await ClockCycles(dut.clk, 3)
    assert (await tb.seq.read(reg.HEALTH_TEST_STATUS_REG_ADDR) & 0xFF) == 0
    assert (await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & health_irq) == 0
    assert int(dut.irq.value) == 0


@cocotb.test()
async def test_integrated_autotune_failure_irq(dut):
    tb = EntropySourceTb(dut, "integrated_autotune_failure_irq")
    await tb.start(disable_dut=False)
    autotune_irq = 1 << 20
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, autotune_irq)
    await tb.seq.write(reg.ALERT_THRESHOLD_REG_ADDR, 0)
    await _configure_fast_integrated_path(
        tb,
        bypass_compressor=False,
        fifo_enable=False,
        health_enable=0b001,
        repetition_limit=1,
        autotune=True,
        entropy_constant=0,
        generator_fault=True,
    )

    await _wait_status_bit(tb, autotune_irq)
    assert int(dut.irq.value) == 1
    lane_status = []
    for address in range(
        reg.GENERATOR_0_HEALTH_STATUS_REG_ADDR,
        reg.GENERATOR_11_HEALTH_STATUS_REG_ADDR + 4,
        4,
    ):
        lane_status.append(await tb.seq.read(address))
    assert any(lane_status)


@cocotb.test()
async def test_integrated_sha_status_progress(dut):
    tb = EntropySourceTb(dut, "integrated_sha_status_progress")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(
        tb,
        bypass_compressor=False,
        fifo_enable=True,
        health_enable=0,
    )
    await _wait_boot(tb)

    input_counts = set()
    output_counts = []
    previous_output = None
    for _ in range(10000):
        await ClockCycles(dut.clk, 1)
        input_counts.add(int(dut.dut_sha_input_count.value))
        output_count = int(dut.dut_sha_output_count.value)
        if output_count != previous_output:
            output_counts.append(output_count)
            previous_output = output_count
        if 8 in output_counts and output_counts[-1] == 0:
            break
    else:
        raise AssertionError("integrated SHA conditioner did not produce and drain a digest")

    assert max(input_counts) >= 8
    start = output_counts.index(8)
    assert output_counts[start : start + 9] == list(range(8, -1, -1))
    assert (await tb.seq.read(reg.SHA256_STATUS_REG_ADDR) & 0xF00) == 0


@cocotb.test()
async def test_integrated_debug_monitor_csr_path(dut):
    tb = EntropySourceTb(dut, "integrated_debug_monitor_csr_path")
    await tb.start(disable_dut=False)
    await _configure_fast_integrated_path(tb)

    counts = []
    for divider in (0, 3):
        await tb.seq.write(reg.DEBUG_CTRL_REG_ADDR, 16 | (divider << 8))
        previous = int(dut.signal_monitor.value)
        transitions = 0
        for _ in range(2048):
            await ClockCycles(dut.clk, 1)
            current = int(dut.signal_monitor.value)
            transitions += current != previous
            previous = current
        counts.append(transitions)
    assert counts[0] > counts[1] > 0
    assert counts[0] / counts[1] >= 6


@cocotb.test()
async def test_integrated_downsample_rate(dut):
    tb = EntropySourceTb(dut, "integrated_downsample_rate")
    await tb.start(disable_dut=False)

    levels = []
    for rate in (0, 7):
        await _reset(tb)
        await _configure_fast_integrated_path(
            tb,
            downsample=rate,
            fifo_enable=False,
        )
        await _wait_boot(tb)
        await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 1)
        await ClockCycles(dut.clk, 30)
        await tb.seq.write(reg.FIFO_CTRL_REG_ADDR, 0)
        levels.append(_fifo_level(await tb.seq.read(reg.FIFO_STATUS_REG_ADDR)))

    assert levels[0] > levels[1] > 0
    assert levels[0] / levels[1] >= 2


@cocotb.test()
async def test_all_interrupt_test_sources(dut):
    tb = EntropySourceTb(dut, "all_interrupt_test_sources")
    await tb.start()
    sources = [1 << shift for shift in range(0, 29, 4)]
    await tb.seq.write(reg.INTR_ENABLE_REG_ADDR, sum(sources))

    for source in sources:
        await tb.seq.write(reg.INTR_TEST_REG_ADDR, source)
        await ClockCycles(dut.clk, 2)
        assert await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & source
        assert int(dut.irq.value) == 1
        await tb.seq.write(reg.INTR_STATUS_REG_ADDR, source)
        await ClockCycles(dut.clk, 2)
        assert (await tb.seq.read(reg.INTR_STATUS_REG_ADDR) & source) == 0
        assert int(dut.irq.value) == 0
