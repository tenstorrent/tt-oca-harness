# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: the responder operations a DUT bench programs.

Wire-level proof on the t_axi bundle, whose request channels the test drives
by hand against the shared fault slave, and on the s_axi bundle, where the
shared master runs against it:

* an errored read beat answers the RDATA word its injection armed, truncated
  to the bus width, or zero when none was given; the next read of the slot
  returns memory;
* the responder accepts a write's W beat while its AW has not been presented,
  with ``arm_w_before_aw()`` and without it;
* after ``randomize_resp_user(seed)`` every B beat carries the next draw of
  ``random.Random(seed)`` on BUSER and every R beat the next draw of
  ``random.Random(seed + 1)`` on RUSER;
* RVALID falls as the reset input asserts between two clock edges, and the
  responder answers again once the reset is released.
"""

from __future__ import annotations

import logging
import random

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge, Timer
from ocah_axi_vip_harness import (
    CLK_PERIOD_NS,
    build_full_stack,
    build_wire_slave,
    drive_wire_ar,
    drive_wire_read,
    drive_wire_write,
    start_clock_reset,
)

log = logging.getLogger("cocotb.tb.ocah_axi_responder_ops_test")

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3
USER_OPS = 16


async def check_errored_beat_word(dut, seq) -> None:
    """An armed read error answers its RDATA word once; the slot reads memory again."""
    addr = random.randrange(0, 2**14) & ~0x3
    preload = random.getrandbits(32)
    word = preload ^ random.randrange(1, 2**32)
    seq.write32(addr, preload)

    seq.inject_error(addr, RESP_SLVERR, read=True, write=False, rdata=(0xA5 << 32) | word)
    resp, rdata = await drive_wire_read(dut, arid=1, addr=addr)
    log.info("armed SLVERR read: resp=%d rdata=0x%08x word=0x%08x", resp, rdata, word)
    assert resp == RESP_SLVERR, f"armed SLVERR answered resp={resp}"
    assert rdata == word, f"errored beat RDATA 0x{rdata:08x} != armed word 0x{word:08x}"

    seq.inject_error(addr, RESP_DECERR, read=True, write=False)
    resp, rdata = await drive_wire_read(dut, arid=2, addr=addr)
    log.info("armed DECERR read without a word: resp=%d rdata=0x%08x", resp, rdata)
    assert resp == RESP_DECERR, f"armed DECERR answered resp={resp}"
    assert rdata == 0, f"errored beat without a word answered 0x{rdata:08x}"

    resp, rdata = await drive_wire_read(dut, arid=3, addr=addr)
    log.info("unarmed read: resp=%d rdata=0x%08x preload=0x%08x", resp, rdata, preload)
    assert resp == RESP_OKAY and rdata == preload, (
        f"unarmed read resp={resp} rdata=0x{rdata:08x}, expected the preload 0x{preload:08x}"
    )


async def check_w_before_aw(dut, seq) -> None:
    """The W handshake completes with AWVALID low, armed and unarmed."""
    for armed in (True, False):
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)
        if armed:
            seq.arm_w_before_aw()
        resp = await drive_wire_write(dut, awid=4, addr=addr, data=data, w_first=True)
        stored = seq.read32(addr)
        log.info(
            "W-before-AW write armed=%s: resp=%d stored=0x%08x data=0x%08x",
            armed,
            resp,
            stored,
            data,
        )
        assert resp == RESP_OKAY, f"W-before-AW write (armed={armed}) answered resp={resp}"
        assert stored == data, f"W-before-AW write (armed={armed}) stored 0x{stored:08x}"


async def record_user(dut, b_user: list[int], r_user: list[int]) -> None:
    """Record BUSER and RUSER at every s_axi B and R handshake."""
    while True:
        await RisingEdge(dut.clk)
        if int(dut.s_axi_bvalid.value) and int(dut.s_axi_bready.value):
            b_user.append(int(dut.s_axi_buser.value))
        if int(dut.s_axi_rvalid.value) and int(dut.s_axi_rready.value):
            r_user.append(int(dut.s_axi_ruser.value))


async def check_resp_user(dut) -> None:
    """Each B and R beat carries the next draw of its seeded stream."""
    master, slave = build_full_stack(dut)
    await master.start()
    seed = random.getrandbits(32)
    slave.sequence.randomize_resp_user(seed)
    width = len(dut.s_axi_buser)
    b_user: list[int] = []
    r_user: list[int] = []
    recorder = cocotb.start_soon(record_user(dut, b_user, r_user))
    for _ in range(USER_OPS):
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)
        wres = await master.sequence.write_result(addr, data)
        assert wres.ok, f"write resp=0x{wres.resp:x}"
        rres = await master.sequence.read_result(addr)
        assert rres.ok and rres.data == data, f"read resp=0x{rres.resp:x} data=0x{rres.data:08x}"
    await ClockCycles(dut.clk, 2)
    recorder.cancel()
    b_rng = random.Random(seed)
    r_rng = random.Random(seed + 1)
    expected_b = [b_rng.getrandbits(width) for _ in range(USER_OPS)]
    expected_r = [r_rng.getrandbits(width) for _ in range(USER_OPS)]
    log.info("seed=%d BUSER=%s RUSER=%s", seed, b_user, r_user)
    assert b_user == expected_b, f"BUSER {b_user} != random.Random({seed}) draws {expected_b}"
    assert r_user == expected_r, f"RUSER {r_user} != random.Random({seed + 1}) draws {expected_r}"


async def check_reset_drops_rvalid(dut, seq) -> None:
    """RVALID falls with the reset, before the next clock edge."""
    dut.t_axi_rready.value = 0
    await drive_wire_ar(dut, arid=5, addr=random.randrange(0, 2**14) & ~0x3)
    for _ in range(50):
        await RisingEdge(dut.clk)
        if int(dut.t_axi_rvalid.value):
            break
    else:
        raise AssertionError("RVALID never rose for the held read")

    await FallingEdge(dut.clk)
    dut.rst_n.value = 0
    await Timer(CLK_PERIOD_NS // 4, "ns")
    await ReadOnly()
    rvalid = int(dut.t_axi_rvalid.value)
    log.info("RVALID a quarter period after the reset asserted: %d", rvalid)
    assert rvalid == 0, "RVALID stayed high after the reset asserted"
    await ClockCycles(dut.clk, 3)
    dut.rst_n.value = 1
    dut.t_axi_rready.value = 1
    await ClockCycles(dut.clk, 5)

    addr = random.randrange(0, 2**14) & ~0x3
    data = random.getrandbits(32)
    seq.write32(addr, data)
    resp, rdata = await drive_wire_read(dut, arid=6, addr=addr)
    assert resp == RESP_OKAY and rdata == data, (
        f"read after the reset resp={resp} rdata=0x{rdata:08x}, expected 0x{data:08x}"
    )


@cocotb.test()
async def ocah_axi_responder_ops_test(dut) -> None:
    await start_clock_reset(dut)
    slave = build_wire_slave(dut)
    await check_errored_beat_word(dut, slave.sequence)
    await check_w_before_aw(dut, slave.sequence)
    await check_resp_user(dut)
    await check_reset_drops_rvalid(dut, slave.sequence)
