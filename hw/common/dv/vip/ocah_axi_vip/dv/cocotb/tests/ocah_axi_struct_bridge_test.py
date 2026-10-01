# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: the slave agent behind a struct-port bridge.

The mt_axi request nets are packed into a pulp request struct in tb_top, the
shape a block tb_top hands its DUT-mastered boundary; ``ocah_axi_struct_bridge``
places that struct on ``u_mt_axi_if`` and ``OcahAxiSlaveAgent`` answers there.
The shared master drives the struct side, the passive monitor on the interface
side feeds the VIP scoreboard whose reference model predicts every response
and readback, and the scenario checker records the boundary contract: a
backdoor preload reads back over the bus, single beats of every transfer size
with random IDs read back under matching BID/RID and agree with the backdoor,
INCR/FIXED/WRAP bursts land at the IHI 0022 A3.4.1 beat addresses, one-shot
read and write faults answer each programmed response code and retire, a write
fault leaves the memory untouched, requests beyond the agent's queue depth complete under
backpressure, and bounded READY stalls on the agent complete every transfer,
including a stall of the write address channel alone, under which the data
beats hand shake before their address (IHI 0022 A3.3).
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles
from ocah_axi_vip import (
    RESP_DECERR,
    RESP_SLVERR,
    OcahAxiMasterSequence,
    OcahAxiMonitor,
    OcahAxiRefModel,
    OcahAxiScoreboard,
    OcahAxiSlaveSequence,
)
from ocah_axi_vip_harness import (
    WIDE_AXI_GEOMETRY,
    build_bridge_stack,
    scenario_rng,
    start_clock_reset,
)
from ocah_checker import OcahChecker
from ocah_lib import OcahKnobs, OcahRng

log = logging.getLogger("cocotb.tb.ocah_axi_struct_bridge_test")

CHK_PRELOAD = "CHK-AXI-BRIDGE-PRELOAD"
CHK_RDBACK = "CHK-AXI-BRIDGE-RDBACK"
CHK_BACKDOOR = "CHK-AXI-BRIDGE-BACKDOOR"
CHK_ID = "CHK-AXI-BRIDGE-ID"
CHK_BURST = "CHK-AXI-BRIDGE-BURST"
CHK_WRAP = "CHK-AXI-BRIDGE-WRAP"
CHK_FAULT_RD = "CHK-AXI-BRIDGE-FAULT-RD"
CHK_FAULT_WR = "CHK-AXI-BRIDGE-FAULT-WR"
CHK_OUTSTANDING = "CHK-AXI-BRIDGE-OUTSTANDING"
CHK_BACKPRESSURE = "CHK-AXI-BRIDGE-BACKPRESSURE"
RANDOM_OPS_KNOB = "OCAH_AXI_BRIDGE_RANDOM_OPS"

BEAT_BYTES = WIDE_AXI_GEOMETRY.data_width // 8
DATA_WIDTH = WIDE_AXI_GEOMETRY.data_width
ID_WIDTH = WIDE_AXI_GEOMETRY.id_width
BURST_FIXED = 0
BURST_WRAP = 2
# Preload words, the scratch window of the random and burst phases, and the
# dedicated words of the fault, outstanding, and backpressure phases.
PRELOAD_WORDS = {0x0000_1000: 0xC0DE_F00D, 0x0000_1004: 0x1234_5678, 0x0000_10FC: 0xA500_0000}
SCRATCH_BASE = 0x0000_2000
SCRATCH_BYTES = 0x0000_6000
FAULT_WORD = SCRATCH_BASE + SCRATCH_BYTES + 0x100
OUTSTANDING_BASE = SCRATCH_BASE + SCRATCH_BYTES + 0x200
BACKPRESSURE_BASE = SCRATCH_BASE + SCRATCH_BYTES + 0x300
# More back-to-back requests than the agent's two-deep address queue holds.
OUTSTANDING_OPS = 6
STALL_CYCLES = 3


async def check_preload(
    checker: OcahChecker,
    seq: OcahAxiMasterSequence,
    slave: OcahAxiSlaveSequence,
    model: OcahAxiRefModel,
) -> None:
    """Words written through the backdoor read back over the bus; the model shadow is seeded alike."""
    for addr, word in PRELOAD_WORDS.items():
        slave.write32(addr, word)
        model.write_bytes(addr, word.to_bytes(BEAT_BYTES, "little"))
    for addr, word in PRELOAD_WORDS.items():
        rres = await seq.read_result(addr)
        checker.expect_equal(CHK_PRELOAD, rres.data, word, context=f"addr=0x{addr:08x}")


async def random_single_beats(
    checker: OcahChecker, seq: OcahAxiMasterSequence, slave: OcahAxiSlaveSequence, rng, count: int
) -> None:
    """Random single beats of every size with independent IDs, cross-checked through the backdoor."""
    shadow: dict[int, int] = {}
    for index in range(count):
        size = rng.randrange(0, 3)
        nbytes = 1 << size
        addr = SCRATCH_BASE + (rng.randrange(0, SCRATCH_BYTES) & ~(nbytes - 1))
        data = OcahRng.random_pattern(8 * nbytes, rng)
        awid = OcahRng.random_pattern(ID_WIDTH, rng)
        arid = OcahRng.random_pattern(ID_WIDTH, rng)
        ctx = f"op {index} addr=0x{addr:08x} size={size} awid=0x{awid:02x} arid=0x{arid:02x}"
        log.debug("%s data=0x%0*x", ctx, 2 * nbytes, data)

        wres = await seq.write_result(addr, data, size=size, id=awid)
        checker.expect_true(CHK_RDBACK, wres.ok, context=f"{ctx} write resp=0x{wres.resp:x}")
        checker.expect_equal(CHK_ID, wres.observed_id, awid, context=f"{ctx} BID")
        for offset in range(nbytes):
            shadow[addr + offset] = (data >> (8 * offset)) & 0xFF
        checker.expect_equal(
            CHK_BACKDOOR, slave.read_int(addr, nbytes), data, context=f"{ctx} backdoor after write"
        )

        rres = await seq.read_result(addr, size=size, id=arid)
        checker.expect_true(CHK_RDBACK, rres.ok, context=f"{ctx} read resp=0x{rres.resp:x}")
        checker.expect_equal(CHK_RDBACK, rres.data, data, context=f"{ctx} readback")
        checker.expect_equal(CHK_ID, rres.observed_id, arid, context=f"{ctx} RID")

    for word in sorted({addr & ~(BEAT_BYTES - 1) for addr in shadow}):
        expected = int.from_bytes(
            bytes(shadow.get(word + offset, 0) for offset in range(BEAT_BYTES)), "little"
        )
        rres = await seq.read_result(word)
        checker.expect_equal(CHK_RDBACK, rres.data, expected, context=f"merged word 0x{word:08x}")


async def bursts(checker: OcahChecker, seq: OcahAxiMasterSequence, rng) -> None:
    """INCR bursts read back in order, FIXED repeats one address, WRAP folds at its window."""
    for beats in (2, 3, 4, 16):
        base = SCRATCH_BASE + (rng.randrange(0, SCRATCH_BYTES - 256) & ~0xFF)
        words = [OcahRng.random_pattern(DATA_WIDTH, rng) for _ in range(beats)]
        burst_id = OcahRng.random_pattern(ID_WIDTH, rng)
        ctx = f"INCR {beats} beats base=0x{base:08x} id=0x{burst_id:02x}"
        wres = await seq.burst_write_result(base, words, id=burst_id)
        checker.expect_true(CHK_BURST, wres.ok, context=f"{ctx} write resp=0x{wres.resp:x}")
        checker.expect_equal(CHK_ID, wres.observed_id, burst_id, context=f"{ctx} BID")
        rres = await seq.burst_read_result(base, beats, id=burst_id)
        checker.expect_equal(CHK_BURST, list(rres.data_words), words, context=ctx)
        checker.expect_equal(CHK_ID, rres.observed_id, burst_id, context=f"{ctx} RID on RLAST")

    base = SCRATCH_BASE + (rng.randrange(0, SCRATCH_BYTES - 256) & ~0xFF)
    words = [OcahRng.random_pattern(DATA_WIDTH, rng) for _ in range(4)]
    ctx = f"FIXED 4 beats base=0x{base:08x}"
    wres = await seq.burst_write_result(base, words, burst=BURST_FIXED)
    checker.expect_true(CHK_BURST, wres.ok, context=f"{ctx} write resp=0x{wres.resp:x}")
    rres = await seq.read_result(base)
    checker.expect_equal(CHK_BURST, rres.data, words[-1], context=f"{ctx} last beat wins")
    rres = await seq.burst_read_result(base, 4, burst=BURST_FIXED)
    checker.expect_equal(
        CHK_BURST, list(rres.data_words), [words[-1]] * 4, context=f"{ctx} read repeats the word"
    )

    base = SCRATCH_BASE + (rng.randrange(0, SCRATCH_BYTES - 256) & ~0xFF)
    words = [OcahRng.random_pattern(DATA_WIDTH, rng) for _ in range(4)]
    start = base + 2 * BEAT_BYTES
    ctx = f"WRAP 4 beats window=0x{base:08x} start=0x{start:08x}"
    wres = await seq.burst_write_result(start, words, burst=BURST_WRAP)
    checker.expect_true(CHK_WRAP, wres.ok, context=f"{ctx} write resp=0x{wres.resp:x}")
    rres = await seq.burst_read_result(base, 4)
    checker.expect_equal(
        CHK_WRAP,
        list(rres.data_words),
        [words[2], words[3], words[0], words[1]],
        context=f"{ctx} INCR readback of the window",
    )
    rres = await seq.burst_read_result(start, 4, burst=BURST_WRAP)
    checker.expect_equal(CHK_WRAP, list(rres.data_words), words, context=f"{ctx} WRAP readback")


async def faults(
    checker: OcahChecker,
    seq: OcahAxiMasterSequence,
    slave: OcahAxiSlaveSequence,
    monitor: OcahAxiMonitor,
    model: OcahAxiRefModel,
    rng,
) -> None:
    """One-shot read and write faults programmed through the slave sequence, each direction once per code."""
    word = FAULT_WORD
    stored = OcahRng.random_pattern(DATA_WIDTH, rng)
    wres = await seq.write_result(word, stored)
    checker.expect_true(CHK_FAULT_RD, wres.ok, context="seed write")

    for read_code, write_code in ((RESP_SLVERR, RESP_DECERR), (RESP_DECERR, RESP_SLVERR)):
        slave.inject_error(word, read_code, read=True, write=False)
        model.expect_error(word, read_code, read=True, write=False)
        monitor.arm_expected_resp(read_code, direction="read")
        rres = await seq.read_result(word, check_response=False)
        checker.expect_equal(
            CHK_FAULT_RD, rres.resp, read_code, context=f"read fault response 0x{read_code:x}"
        )
        rres = await seq.read_result(word)
        checker.expect_true(
            CHK_FAULT_RD,
            rres.ok and rres.data == stored,
            context=f"one-shot 0x{read_code:x} retired, data intact",
        )

        other = OcahRng.random_pattern(DATA_WIDTH, rng)
        slave.inject_error(word, write_code, read=False, write=True)
        model.expect_error(word, write_code, read=False, write=True)
        monitor.arm_expected_resp(write_code, direction="write")
        wres = await seq.write_result(word, other, check_response=False)
        checker.expect_equal(
            CHK_FAULT_WR, wres.resp, write_code, context=f"write fault response 0x{write_code:x}"
        )
        checker.expect_equal(
            CHK_FAULT_WR,
            slave.read32(word),
            stored,
            context=f"backdoor: memory untouched after 0x{write_code:x}",
        )
        rres = await seq.read_result(word)
        checker.expect_true(
            CHK_FAULT_WR,
            rres.ok and rres.data == stored,
            context=f"bus: memory untouched after 0x{write_code:x}",
        )


async def outstanding(checker: OcahChecker, seq: OcahAxiMasterSequence, rng) -> None:
    """Back-to-back requests beyond the agent's queue depth all complete in order."""
    words = [OcahRng.random_pattern(DATA_WIDTH, rng) for _ in range(OUTSTANDING_OPS)]
    write_tasks = [
        cocotb.start_soon(seq.write_result(OUTSTANDING_BASE + BEAT_BYTES * index, word, id=index))
        for index, word in enumerate(words)
    ]
    write_results = [await task for task in write_tasks]
    checker.expect_true(
        CHK_OUTSTANDING,
        all(result.ok for result in write_results),
        context=f"{OUTSTANDING_OPS} back-to-back writes resp={[r.resp for r in write_results]}",
    )
    read_tasks = [
        cocotb.start_soon(seq.read_result(OUTSTANDING_BASE + BEAT_BYTES * index, id=index))
        for index in range(OUTSTANDING_OPS)
    ]
    read_results = [await task for task in read_tasks]
    checker.expect_true(
        CHK_OUTSTANDING,
        all(result.ok for result in read_results),
        context=f"{OUTSTANDING_OPS} back-to-back reads resp={[r.resp for r in read_results]}",
    )
    checker.expect_equal(
        CHK_OUTSTANDING,
        [result.data for result in read_results],
        words,
        context=f"{OUTSTANDING_OPS} back-to-back readbacks",
    )


async def backpressure(
    checker: OcahChecker, seq: OcahAxiMasterSequence, slave: OcahAxiSlaveSequence, rng
) -> None:
    """Bounded READY stalls on the agent's request channels complete every transfer.

    The second round stalls the write address channel alone: the master
    presents AW and W together, so the data beats hand shake first and the
    agent pairs them with the address that follows.
    """
    for round_index, channels in enumerate((("aw", "w", "ar"), ("aw",))):
        slave.enable_backpressure(channels=channels, stall_cycles=STALL_CYCLES)
        for index in range(4):
            addr = BACKPRESSURE_BASE + BEAT_BYTES * (4 * round_index + index)
            data = OcahRng.random_pattern(DATA_WIDTH, rng)
            wres = await seq.write_result(addr, data)
            rres = await seq.read_result(addr)
            checker.expect_true(
                CHK_BACKPRESSURE,
                wres.ok and rres.ok and rres.data == data,
                context=(
                    f"stall={STALL_CYCLES} channels={','.join(channels)} "
                    f"op {index} addr=0x{addr:08x}"
                ),
            )
        slave.disable_backpressure()


@cocotb.test()
async def ocah_axi_struct_bridge_test(dut: Any) -> None:
    """Preload, single beats, bursts, faults, outstanding requests, and stalls through the bridge."""
    await start_clock_reset(dut)
    master, slave_agent, monitor = build_bridge_stack(dut)
    slave = slave_agent.sequence
    model = OcahAxiRefModel(name="ocah_axi_struct_bridge_model", beat_bytes=BEAT_BYTES, logger=log)
    scoreboard = OcahAxiScoreboard(
        name="ocah_axi_struct_bridge_scoreboard",
        model=model,
        required_ids=("CHK-AXI-RESP", "CHK-AXI-RDATA"),
        logger=log,
    )
    scoreboard.attach_monitor(monitor)
    await monitor.start()
    await master.start()
    seq = master.sequence
    checker = OcahChecker(
        name="ocah_axi_struct_bridge",
        required_ids=(
            CHK_PRELOAD,
            CHK_RDBACK,
            CHK_BACKDOOR,
            CHK_ID,
            CHK_BURST,
            CHK_WRAP,
            CHK_FAULT_RD,
            CHK_FAULT_WR,
            CHK_OUTSTANDING,
            CHK_BACKPRESSURE,
        ),
        logger=log,
    )
    rng = scenario_rng("ocah_axi_struct_bridge_test")
    random_count = OcahKnobs.get_int_min(RANDOM_OPS_KNOB, 16, 1)
    log.info("=" * 70)
    log.info(
        "slave agent behind the struct bridge: preload, %d random single beats, "
        "INCR/FIXED/WRAP bursts, faults, %d outstanding requests, READY stalls of %d",
        random_count,
        OUTSTANDING_OPS,
        STALL_CYCLES,
    )
    log.info("=" * 70)

    await check_preload(checker, seq, slave, model)
    await random_single_beats(checker, seq, slave, rng, random_count)
    await bursts(checker, seq, rng)
    await faults(checker, seq, slave, monitor, model, rng)
    await outstanding(checker, seq, rng)
    await backpressure(checker, seq, slave, rng)

    await ClockCycles(dut.clk, 10)
    await monitor.stop()
    log.info(
        "done: master stats=%s slave stats=%s monitor stats=%s",
        seq.get_statistics(),
        slave.get_statistics(),
        monitor.get_statistics(),
    )
    scoreboard.finalize()
    checker.finalize()
