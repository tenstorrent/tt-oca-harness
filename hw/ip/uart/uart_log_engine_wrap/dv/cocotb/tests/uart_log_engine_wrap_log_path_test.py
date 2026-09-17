# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART and Log Engine wrapper log path: fetch memory to the serial line.

Scenarios:

1. Single log — a random slot's payload, fetched over the log-fetch port,
   leaves the wrapper on ``uart_tx`` as clean 8N1 frames in order, paced by
   the UART's transmit-ready; the slot's length clears and no log engine
   interrupt fires.
2. Concurrent CSR traffic — while a second log drains, the CSR master keeps
   reading the UART's LSR through the same UART port the engine writes,
   and the frames on the line are still byte-exact.
3. Several slots — a few slots armed back to back all reach the line as
   whole logs.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles
from uart_log_engine_wrap_base_test import (
    FRAME_CYCLES,
    LOG_CTRL_ADDRS,
    NUM_LOG_ENTRIES,
    REG,
    UartLogEngineWrapTb,
    random_seed,
    slot_capacity,
)

REGION_SIZE = 16 * 64  # 64-byte slots


def split_stream(stream: list[int], payloads: dict[int, bytes]) -> list[int]:
    order: list[int] = []
    pending = dict(payloads)
    pos = 0
    while pos < len(stream):
        match = next((i for i, p in pending.items() if stream[pos : pos + len(p)] == list(p)), None)
        assert match is not None, (
            f"stream position {pos} matches no pending slot; remaining {sorted(pending)}"
        )
        order.append(match)
        pos += len(pending.pop(match))
    assert not pending, f"slots {sorted(pending)} never reached the line"
    return order


@cocotb.test()
async def uart_log_engine_wrap_log_path_test(dut) -> None:
    tb = UartLogEngineWrapTb(dut, name="uart_log_engine_wrap_log_path_test")
    seed = random_seed()
    random.seed(seed)
    tb.log.info("seed=%d", seed)

    await tb.start()
    await tb.configure_uart()
    await tb.configure_log_engine(REGION_SIZE)
    capacity = slot_capacity(REGION_SIZE)

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 1: one log from the fetch memory to uart_tx")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(random.randint(9, capacity))
    tb.load_slot(index, payload)
    await tb.write(LOG_CTRL_ADDRS[index], len(payload))
    frames = await tb.expect_frames(len(payload), f"slot {index}")
    observed = [frame.data for frame in frames]
    assert observed == list(payload), (
        f"slot {index}: {len(payload)} bytes loaded, line carried {bytes(observed).hex()}"
    )
    await tb.wait_slot_done(index, 4 * FRAME_CYCLES, f"slot {index}")
    status = await tb.read(REG.LOG_ENGINE_INTR_STATUS_REG_ADDR)
    assert status == 0 and int(dut.log_engine_irq.value) == 0, (
        f"log engine flagged an error (INTR_STATUS 0x{status:x})"
    )
    tb.log.info(
        "slot %d: %d bytes reached uart_tx byte-exact; LOG_CTRL cleared", index, len(payload)
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 2: CSR reads through the UART port during a transfer")
    tb.log.info("=" * 70)
    index = random.randrange(NUM_LOG_ENTRIES)
    payload = random.randbytes(random.randint(9, capacity))
    tb.load_slot(index, payload)
    tb.line_sampler.clear()
    await tb.write(LOG_CTRL_ADDRS[index], len(payload))
    polls = 0
    while await tb.read(LOG_CTRL_ADDRS[index]) != 0:
        lsr = await tb.read_u(REG.UART_16550_MAIN_LSR_reg_u, REG.UART_LSR_REG_ADDR)
        assert lsr.f.oe == 0 and lsr.f.fe == 0, (
            f"LSR reports a line error (0x{lsr.val:02x}) during the transfer"
        )
        polls += 1
        await ClockCycles(dut.clk, FRAME_CYCLES // 3)
        assert polls < 4 * len(payload), f"slot {index} never completed"
    frames = await tb.expect_frames(len(payload), f"slot {index} under CSR traffic")
    observed = [frame.data for frame in frames]
    assert observed == list(payload), (
        f"slot {index} under CSR traffic: line carried {bytes(observed).hex()}"
    )
    tb.log.info(
        "slot %d: %d bytes byte-exact while %d LSR reads shared the UART port",
        index,
        len(payload),
        polls,
    )

    # ------------------------------------------------------------------
    tb.log.info("=" * 70)
    tb.log.info("TEST 3: several slots armed back to back")
    tb.log.info("=" * 70)
    slots = random.sample(range(NUM_LOG_ENTRIES), 3)
    payloads = {i: random.randbytes(random.randint(1, capacity // 2)) for i in slots}
    for i, data in payloads.items():
        tb.load_slot(i, data)
    tb.line_sampler.clear()
    for i, data in payloads.items():
        await tb.write(LOG_CTRL_ADDRS[i], len(data))
    total = sum(len(data) for data in payloads.values())
    frames = await tb.expect_frames(total, "three slots")
    order = split_stream([frame.data for frame in frames], payloads)
    for i in slots:
        await tb.wait_slot_done(i, 4 * FRAME_CYCLES, "three slots")
    tb.log.info(
        "%d bytes from slots %s reached uart_tx as whole logs in order %s", total, slots, order
    )

    tb.log.info("uart_log_engine_wrap_log_path_test PASSED (seed=%d)", seed)
