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
  with ``arm_w_before_aw()`` and without it, on every write of a run
  (CHK-AXI-SLAVE-W-FIRST);
* after ``randomize_resp_user(seed)`` every B beat carries the next draw of
  ``random.Random(seed)`` on BUSER and every R beat the next draw of
  ``random.Random(seed + 1)`` on RUSER;
* ``OcahAxiDelays`` gives the stream the SV-UVM ``ocah_axi_delays`` gives for
  the same seed; under ``enable_random_backpressure`` no AW, W or AR handshake
  waits longer than its source can draw, some wait outlasts every short draw,
  and the same seeds repeat the same waits (CHK-AXI-SLAVE-STALL);
* under ``set_response_delay`` each B and R comes exactly the drawn number of
  cycles later than the same access without a delay, on the AXI4 and the
  AXI4-Lite responder (CHK-AXI-SLAVE-RESP-DELAY);
* the AXI4 monitor records the AxCACHE, AxUSER and WUSER the master drives
  (CHK-AXI-MON-ATTR);
* RVALID falls as the reset input asserts between two clock edges, and the
  responder answers again once the reset is released.
"""

from __future__ import annotations

import itertools
import logging
import random

import cocotb
from cocotb.triggers import ClockCycles, Event, FallingEdge, ReadOnly, RisingEdge, Timer
from ocah_axi_vip import OcahAxiDelays, OcahAxiMonitor
from ocah_axi_vip_harness import (
    CLK_PERIOD_NS,
    build_full_stack,
    build_lite_stack,
    build_wire_slave,
    drive_wire_ar,
    drive_wire_read,
    drive_wire_write,
    handshake_cycles,
    scenario_rng,
    start_clock_reset,
)
from ocah_checker import OcahChecker

log = logging.getLogger("cocotb.tb.ocah_axi_responder_ops_test")

RESP_OKAY = 0
RESP_SLVERR = 2
RESP_DECERR = 3
USER_OPS = 16

CHK_W_FIRST = "CHK-AXI-SLAVE-W-FIRST"
CHK_STALL = "CHK-AXI-SLAVE-STALL"
CHK_RESP_DELAY = "CHK-AXI-SLAVE-RESP-DELAY"
CHK_MON_ATTR = "CHK-AXI-MON-ATTR"

# Writes with AW held back after the armed and the unarmed one.
W_FIRST_RUN = 4

# The stream both realizations check for this source.
GOLDEN_DELAYS = {"short_min": 0, "short_max": 9, "long_percent": 25, "long_min": 40, "long_max": 60}
GOLDEN_SEED = 1
GOLDEN_VECTOR = [7, 2, 1, 5, 8, 3, 6, 4, 48, 6, 1, 41]

# READY stall windows: mostly short, some long enough to outlast every short one.
STALL_DELAYS = {"short_min": 0, "short_max": 3, "long_percent": 40, "long_min": 20, "long_max": 40}
STALL_OPS = 8

# B and R delays: mostly short, some long.
RESP_DELAYS = {"short_min": 0, "short_max": 5, "long_percent": 25, "long_min": 10, "long_max": 20}
DELAY_OPS = 8

ATTR_OPS = 8

_REQUEST_KEYS = ("awvalid", "awready", "wvalid", "wready", "arvalid", "arready")
_TIMING_KEYS = (*_REQUEST_KEYS, "bvalid", "bready", "rvalid", "rready")


def _sample(handle) -> int:
    try:
        return int(handle.value)
    except ValueError:
        return 0


async def record(dut, prefix: str, keys: tuple[str, ...], stop: Event) -> list[dict[str, int]]:
    """Record ``<prefix>_<key>`` once per cycle through the edge ``stop`` is set on.

    Returns on the next edge, so the awaiting coroutine can drive signals.
    """
    samples: list[dict[str, int]] = []
    while True:
        await RisingEdge(dut.clk)
        samples.append({key: _sample(getattr(dut, f"{prefix}_{key}")) for key in keys})
        await ReadOnly()
        if stop.is_set():
            await RisingEdge(dut.clk)
            return samples


def ready_waits(samples: list[dict[str, int]], channel: str) -> list[int]:
    """Cycles each handshake on ``channel`` waited with VALID high and READY low."""
    valid, ready = f"{channel}valid", f"{channel}ready"
    waits: list[int] = []
    pending = 0
    for row in samples:
        if row[valid] and row[ready]:
            waits.append(pending)
            pending = 0
        elif row[valid]:
            pending += 1
        else:
            pending = 0
    return waits


def rises(samples: list[dict[str, int]], key: str) -> list[int]:
    """Every sample index where ``key`` goes high."""
    return [i for i, row in enumerate(samples) if row[key] and (i == 0 or not samples[i - 1][key])]


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


async def check_w_before_aw(dut, seq, checker: OcahChecker) -> None:
    """Every write's W handshake completes before its AWVALID rises, armed or not."""
    for index, armed in enumerate([True] + [False] * (1 + W_FIRST_RUN)):
        addr = random.randrange(0, 2**14) & ~0x3
        data = random.getrandbits(32)
        if armed:
            seq.arm_w_before_aw()
        stop = Event()
        recorder = cocotb.start_soon(record(dut, "t_axi", ("awvalid", "wvalid", "wready"), stop))
        resp = await drive_wire_write(dut, awid=4, addr=addr, data=data, w_first=True)
        stop.set()
        samples = await recorder
        stored = seq.read32(addr)
        w_hs = handshake_cycles(samples, "wvalid", "wready")
        aw_rise = rises(samples, "awvalid")
        ctx = f"W-before-AW write {index} armed={armed}"
        log.info(
            "%s: resp=%d stored=0x%08x W at %s AWVALID at %s", ctx, resp, stored, w_hs, aw_rise
        )
        checker.expect_true(
            CHK_W_FIRST,
            len(w_hs) == 1 and len(aw_rise) == 1 and w_hs[0] < aw_rise[0],
            context=f"{ctx} W handshake {w_hs} before AWVALID rose {aw_rise}",
        )
        checker.expect_equal(CHK_W_FIRST, resp, RESP_OKAY, context=f"{ctx} BRESP")
        checker.expect_equal(CHK_W_FIRST, stored, data, context=f"{ctx} stored word")


async def record_user(dut, b_user: list[int], r_user: list[int]) -> None:
    """Record BUSER and RUSER at every s_axi B and R handshake."""
    while True:
        await RisingEdge(dut.clk)
        if int(dut.s_axi_bvalid.value) and int(dut.s_axi_bready.value):
            b_user.append(int(dut.s_axi_buser.value))
        if int(dut.s_axi_rvalid.value) and int(dut.s_axi_rready.value):
            r_user.append(int(dut.s_axi_ruser.value))


async def check_resp_user(dut, master, slave) -> None:
    """Each B and R beat carries the next draw of its seeded stream."""
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


def check_golden_delays(checker: OcahChecker) -> None:
    """The delay source gives the stream the SV-UVM twin gives for the same seed."""
    drawn = list(itertools.islice(OcahAxiDelays(GOLDEN_SEED, **GOLDEN_DELAYS), len(GOLDEN_VECTOR)))
    checker.expect_equal(CHK_STALL, drawn, GOLDEN_VECTOR, context=f"seed {GOLDEN_SEED} stream")


async def stalled_pass(
    dut, master, slave, seeds: dict[str, int], ops: list[tuple[int, int]]
) -> tuple[dict[str, list[int]], dict[str, int]]:
    """Run ``ops`` under random READY stalls; each channel's handshake waits and bound."""
    sources = {ch: OcahAxiDelays(seeds[ch], **STALL_DELAYS) for ch in ("aw", "w", "ar")}
    await ClockCycles(dut.clk, 4)
    for channel, source in sources.items():
        slave.sequence.enable_random_backpressure(channels=(channel,), stalls=source)
    stop = Event()
    recorder = cocotb.start_soon(record(dut, "s_axi", _REQUEST_KEYS, stop))
    for addr, data in ops:
        wres = await master.sequence.write_result(addr, data)
        rres = await master.sequence.read_result(addr)
        assert wres.ok and rres.ok and rres.data == data, (
            f"stalled access 0x{addr:x}: write resp=0x{wres.resp:x} read resp=0x{rres.resp:x} "
            f"data=0x{rres.data:08x} expected 0x{data:08x}"
        )
    stop.set()
    samples = await recorder
    slave.sequence.disable_backpressure()
    waits = {ch: ready_waits(samples, ch) for ch in sources}
    return waits, {ch: source.max_value for ch, source in sources.items()}


async def check_random_stalls(dut, master, slave, checker: OcahChecker) -> None:
    """READY waits stay within the drawn bounds, some are long, and a seed repeats them."""
    rng = scenario_rng("responder_ops.stall")
    seeds = {ch: rng.getrandbits(32) for ch in ("aw", "w", "ar")}
    ops = [(rng.randrange(0, 2**14) & ~0x3, rng.getrandbits(32)) for _ in range(STALL_OPS)]
    first, bounds = await stalled_pass(dut, master, slave, seeds, ops)
    again, _ = await stalled_pass(dut, master, slave, seeds, ops)
    log.info("READY waits seeds=%s first=%s again=%s", seeds, first, again)
    for channel, waits in first.items():
        ctx = f"{channel.upper()} seed {seeds[channel]}"
        checker.expect_equal(CHK_STALL, len(waits), STALL_OPS, context=f"{ctx} handshakes")
        checker.expect_true(
            CHK_STALL,
            all(wait <= bounds[channel] for wait in waits),
            context=f"{ctx} waits {waits} within {bounds[channel]}",
        )
        checker.expect_equal(CHK_STALL, again[channel], waits, context=f"{ctx} repeated waits")
    longest = max(max(waits, default=0) for waits in first.values())
    checker.expect_true(
        CHK_STALL,
        longest > STALL_DELAYS["short_max"],
        context=f"longest wait {longest} outlasts every short draw",
    )


async def latency_pass(
    dut, prefix: str, master_seq, ops: list[tuple[int, int]]
) -> tuple[list[int], list[int]]:
    """Cycles from each write's last request handshake to BVALID, and each read's AR to RVALID."""
    stop = Event()
    recorder = cocotb.start_soon(record(dut, prefix, _TIMING_KEYS, stop))
    for addr, data in ops:
        wres = await master_seq.write_result(addr, data)
        rres = await master_seq.read_result(addr)
        assert wres.ok and rres.ok and rres.data == data, (
            f"{prefix} access 0x{addr:x}: write resp=0x{wres.resp:x} read resp=0x{rres.resp:x} "
            f"data=0x{rres.data:08x} expected 0x{data:08x}"
        )
    stop.set()
    samples = await recorder
    aw_hs = handshake_cycles(samples, "awvalid", "awready")
    w_hs = handshake_cycles(samples, "wvalid", "wready")
    ar_hs = handshake_cycles(samples, "arvalid", "arready")
    b_rise, r_rise = rises(samples, "bvalid"), rises(samples, "rvalid")
    writes = [b - max(aw, w) for aw, w, b in zip(aw_hs, w_hs, b_rise)]
    reads = [r - ar for ar, r in zip(ar_hs, r_rise)]
    return writes, reads


async def check_response_delay(dut, label: str, prefix: str, master, slave, checker) -> None:
    """Each B and R comes the drawn number of cycles later than with no delay."""
    rng = scenario_rng(f"responder_ops.delay.{label}")
    seeds = {"write": rng.getrandbits(32), "read": rng.getrandbits(32)}
    ops = [(rng.randrange(0, 2**14) & ~0x3, rng.getrandbits(32)) for _ in range(DELAY_OPS)]
    slave.sequence.clear_response_delay()
    base_w, base_r = await latency_pass(dut, prefix, master.sequence, ops)
    slave.sequence.set_response_delay(OcahAxiDelays(seeds["write"], **RESP_DELAYS), read=False)
    slave.sequence.set_response_delay(OcahAxiDelays(seeds["read"], **RESP_DELAYS), write=False)
    late_w, late_r = await latency_pass(dut, prefix, master.sequence, ops)
    slave.sequence.clear_response_delay()
    for kind, base, late in (("write", base_w, late_w), ("read", base_r, late_r)):
        drawn = list(itertools.islice(OcahAxiDelays(seeds[kind], **RESP_DELAYS), DELAY_OPS))
        added = [b - a for a, b in zip(base, late)]
        log.info("%s %s latency base=%s delayed=%s drawn=%s", label, kind, base, late, drawn)
        ctx = f"{label} {kind} seed {seeds[kind]}"
        checker.expect_equal(
            CHK_RESP_DELAY, (len(base), len(late)), (DELAY_OPS, DELAY_OPS), context=f"{ctx} count"
        )
        checker.expect_equal(CHK_RESP_DELAY, added, drawn, context=f"{ctx} added cycles")


async def check_monitor_attrs(dut, master, checker: OcahChecker) -> None:
    """The AXI4 monitor's items carry the AxCACHE, AxUSER and WUSER the master drove."""
    rng = scenario_rng("responder_ops.attrs")
    monitor = OcahAxiMonitor.from_prefix(dut, "s_axi", dut.clk, name="harness_s_axi_monitor")
    await monitor.start()
    users = {kind: [i % 2 for i in range(ATTR_OPS)] for kind in ("aw", "w", "ar")}
    for values in users.values():
        rng.shuffle(values)
    expected_w: list[tuple[int, int, tuple[int, ...]]] = []
    expected_r: list[tuple[int, int]] = []
    for op in range(ATTR_OPS):
        addr = rng.randrange(0, 2**14) & ~0x3
        data = rng.getrandbits(32)
        wcache, rcache = rng.randrange(1, 16), rng.randrange(1, 16)
        await master.sequence.write_bytes_result(
            addr,
            data.to_bytes(4, "little"),
            size=2,
            user=users["aw"][op],
            attrs={"cache": wcache, "wuser": users["w"][op]},
        )
        await master.sequence.read_bytes_result(
            addr, 4, size=2, user=users["ar"][op], attrs={"cache": rcache}
        )
        expected_w.append((wcache, users["aw"][op], (users["w"][op],)))
        expected_r.append((rcache, users["ar"][op]))
    await ClockCycles(dut.clk, 2)
    observed_w = [(i.cache, i.user, i.wusers) for i in monitor.get_write_transactions()]
    observed_r = [(i.cache, i.user) for i in monitor.get_read_transactions()]
    await monitor.stop()
    log.info("monitor writes=%s reads=%s", observed_w, observed_r)
    checker.expect_equal(CHK_MON_ATTR, observed_w, expected_w, context="write cache/user/wuser")
    checker.expect_equal(CHK_MON_ATTR, observed_r, expected_r, context="read cache/user")


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
    checker = OcahChecker(
        name="ocah_axi_responder_ops",
        fail_fast=False,
        logger=log,
        required_ids=(CHK_W_FIRST, CHK_STALL, CHK_RESP_DELAY, CHK_MON_ATTR),
    )
    slave = build_wire_slave(dut)
    await check_errored_beat_word(dut, slave.sequence)
    await check_w_before_aw(dut, slave.sequence, checker)
    master, full = build_full_stack(dut)
    await master.start()
    await check_resp_user(dut, master, full)
    check_golden_delays(checker)
    await check_random_stalls(dut, master, full, checker)
    await check_response_delay(dut, "axi4", "s_axi", master, full, checker)
    lite_master, lite = build_lite_stack(dut)
    await lite_master.start()
    await check_response_delay(dut, "axi4-lite", "l_axi", lite_master, lite, checker)
    await check_monitor_attrs(dut, master, checker)
    await check_reset_drops_rvalid(dut, slave.sequence)
    checker.finalize()
