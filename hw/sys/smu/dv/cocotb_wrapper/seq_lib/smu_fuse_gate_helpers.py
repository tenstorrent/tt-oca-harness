# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bounded observations of the SMC eFuse sense and the boot-stall fuse-reset gate.

The wrapper runs the SMC eFuse controller's real sense. ``smc_fuse_sense_done_o``
and ``smc_fuse_reset_n_delayed_o`` both live in the SMC primary-reset domain, so
every cold reset restarts the sense, and a gate observation is anchored on that
cold reset's own sense completion:

* ``smc_fuse_sense_done_o`` is watched 0 -> 1; a wait that begins with the flag
  already high fails, because no transition was observed.
* While the stall is held, ``smc_fuse_reset_n_delayed_o`` must read 0 on every
  one of ``FUSE_GATE_HOLD_CYCLES`` edges after that rise, so the 0 is the gate
  and not the sense still running.
* Once the stall clears, the release is bounded by the gate path
  (``prim_sync3`` + sticky flop + 16-stage ``prim_pipe_stages``, about 20 SMC
  clocks), not by the sense latency, and must then stay released. The gate is
  armed immediately before the clear stimulus (sense done, gate shut), so a
  clear that itself spans many cycles, such as a TRST pulse, still brackets the
  0 -> 1 it causes.

Every cycle count is in ``clk_smu_i`` cycles; the wrapper clocks the SMC from it.

``RomFetchSampler`` reads the ROM request and the fuse-reset gate on every ``clk_smu_i``
edge and grades, per release leg, the first ROM read after the gate opens; the ROM reads
before it are logged, not graded.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import Event, RisingEdge
from cocotb.utils import get_sim_time

# The 768-word sense of the default image completes 2280-2330 clk_smu after the
# primary reset release, as measured on this bench; the expiry is about twice
# the top of that range.
FUSE_SENSE_BOUND_CYCLES = 5000
# Expiry for a release that is expected to happen. The gate path once the stall
# input clears is prim_sync3 (3) + sticky flop (1) + 16-stage pipe = 20 clk_smc,
# with the DTP export or pad path in front of it; runs on this bench measure
# 2-21 clk_smu.
FUSE_GATE_RELEASE_BOUND_CYCLES = 256
# A level that must not move is watched for this long. The window is meaningful
# only while it exceeds the real release latency -- otherwise "still 0 after N
# cycles" is "not released yet" and the hold checks cannot fail -- so
# assert_hold_window_covers() checks every measured release against it.
FUSE_GATE_HOLD_CYCLES = 64


def assert_hold_window_covers(release_cycles: int, *, label: str, log=None) -> None:
    """Fail unless a measured gate release fits inside ``FUSE_GATE_HOLD_CYCLES``.

    The hold checks assert that ``smc_fuse_reset_n_delayed_o`` stays at 0 for
    ``FUSE_GATE_HOLD_CYCLES`` while the stall is asserted. That is evidence only
    if a gate which ignored the stall would have released inside the window, so
    the window has to exceed the real release latency of this DUT: the release
    the sequence just measured is checked against the window the hold checks use.
    """
    if release_cycles >= FUSE_GATE_HOLD_CYCLES:
        raise AssertionError(
            f"{label}: gate released after {release_cycles} clk_smu, at or beyond the "
            f"{FUSE_GATE_HOLD_CYCLES}-cycle hold window; the hold checks in this package "
            "would pass without observing anything. Raise FUSE_GATE_HOLD_CYCLES above the "
            "measured release and re-run."
        )
    if log is not None:
        log.info(
            "FUSE-GATE-WINDOW %s: release %d clk_smu < hold window %d clk_smu",
            label,
            release_cycles,
            FUSE_GATE_HOLD_CYCLES,
        )


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


def _now_ns() -> float:
    return float(get_sim_time(unit="ns"))


async def wait_rise(signal, clk, *, timeout_cycles: int, name: str) -> int:
    """Cycles until ``signal`` reads 1, having read 0 when the wait began."""
    last = _sample(signal, name)
    if last != 0:
        raise AssertionError(f"{name} already {last} before the wait: no 0->1 observed")
    for cycle in range(1, timeout_cycles + 1):
        await RisingEdge(clk)
        last = _sample(signal, name)
        if last == 1:
            return cycle
    raise AssertionError(f"timeout waiting for {name}==1: bound={timeout_cycles} last_state={last}")


async def wait_level(signal, clk, *, expect: int, timeout_cycles: int, name: str) -> int:
    """Cycles until ``signal`` reads ``expect``; 0 when it already does."""
    last = _sample(signal, name)
    if last == expect:
        return 0
    for cycle in range(1, timeout_cycles + 1):
        await RisingEdge(clk)
        last = _sample(signal, name)
        if last == expect:
            return cycle
    raise AssertionError(
        f"timeout waiting for {name}=={expect}: bound={timeout_cycles} last_state={last}"
    )


async def hold_level(signal, clk, *, expect: int, cycles: int, name: str) -> None:
    """Fail unless ``signal`` reads ``expect`` on each of ``cycles`` consecutive edges."""
    for cycle in range(cycles):
        await RisingEdge(clk)
        got = _sample(signal, name)
        if got != expect:
            raise AssertionError(f"{name} left {expect} at cycle {cycle} of {cycles}: got {got}")


async def wait_fuse_sense_done(dut, log, *, phase: str) -> int:
    """``smc_fuse_sense_done_o`` 0 -> 1 within ``FUSE_SENSE_BOUND_CYCLES``; cycles taken."""
    cycles = await wait_rise(
        dut.smc_fuse_sense_done_o,
        dut.clk_smu_i,
        timeout_cycles=FUSE_SENSE_BOUND_CYCLES,
        name=f"smc_fuse_sense_done_o ({phase})",
    )
    log.info(
        "FUSE-SENSE %s: smc_fuse_sense_done_o rose after %d clk_smu (bound %d) at %.1f ns; "
        "smc_fuse_reset_n_delayed_o=%d",
        phase,
        cycles,
        FUSE_SENSE_BOUND_CYCLES,
        _now_ns(),
        _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
    )
    return cycles


async def expect_release_after_sense(dut, sb, log, *, phase: str, name: str) -> tuple[int, int]:
    """No stall: the sense completes, then the release follows within the gate bound.

    Returns (cycles to sense-done, cycles from sense-done to release).
    """
    sense = await wait_fuse_sense_done(dut, log, phase=phase)
    release = await wait_rise(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        timeout_cycles=FUSE_GATE_RELEASE_BOUND_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    await hold_level(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        expect=1,
        cycles=FUSE_GATE_HOLD_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    assert_hold_window_covers(release, label=f"{phase} release-after-sense", log=log)
    log.info(
        "FUSE-GATE %s: smc_fuse_reset_n_delayed_o rose %d clk_smu after sense-done "
        "(bound %d) and held 1 for %d clk_smu at %.1f ns",
        phase,
        release,
        FUSE_GATE_RELEASE_BOUND_CYCLES,
        FUSE_GATE_HOLD_CYCLES,
        _now_ns(),
    )
    sb.expect_eq(name, _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"), 1)
    return sense, release


async def expect_gate_held_after_sense(
    dut, sb, log, *, phase: str, name: str, evidence: str | None = None
) -> int:
    """Stall held: the sense completes and the gate keeps the release low.

    Returns the cycles to sense-done for this primary reset.
    """
    sense = await wait_fuse_sense_done(dut, log, phase=phase)
    await hold_level(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        expect=0,
        cycles=FUSE_GATE_HOLD_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    log.info(
        "FUSE-GATE %s: smc_fuse_reset_n_delayed_o held 0 for %d clk_smu after sense-done "
        "at %.1f ns",
        phase,
        FUSE_GATE_HOLD_CYCLES,
        _now_ns(),
    )
    sb.expect_eq(
        name,
        _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
        0,
        evidence=evidence,
    )
    return sense


def arm_gate_release(dut, sb, *, name: str) -> float:
    """Immediately before the clear stimulus: the sense is done and the gate is shut.

    Returns the simulation time in ns, for the release latency.
    """
    sb.expect_eq(
        f"{name}: sense done before the clear",
        _sample(dut.smc_fuse_sense_done_o, "smc_fuse_sense_done_o"),
        1,
    )
    sb.expect_eq(
        f"{name}: gate shut before the clear",
        _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
        0,
    )
    return _now_ns()


async def expect_gate_release(
    dut, sb, log, *, armed_ns: float, phase: str, name: str, evidence: str | None = None
) -> int:
    """After the clear stimulus that followed ``arm_gate_release``: the gate opens.

    The rise must arrive within ``FUSE_GATE_RELEASE_BOUND_CYCLES`` of this call
    (a level already high counts as 0 cycles, the arm having read it low) and
    then stay high. Returns the cycles from the call to the release.
    """
    release = await wait_level(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        expect=1,
        timeout_cycles=FUSE_GATE_RELEASE_BOUND_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    await hold_level(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        expect=1,
        cycles=FUSE_GATE_HOLD_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    log.info(
        "FUSE-GATE %s: smc_fuse_reset_n_delayed_o released %d clk_smu after the wait began "
        "(bound %d; armed shut at %.1f ns) and held 1 for %d clk_smu at %.1f ns",
        phase,
        release,
        FUSE_GATE_RELEASE_BOUND_CYCLES,
        armed_ns,
        FUSE_GATE_HOLD_CYCLES,
        _now_ns(),
    )
    sb.expect_eq(
        name,
        _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
        1,
        evidence=evidence,
    )
    return release


async def expect_no_regate(dut, sb, log, *, phase: str, name: str, evidence: str | None = None):
    """Stall re-asserted after release: the sticky latch keeps the gate open."""
    await hold_level(
        dut.smc_fuse_reset_n_delayed_o,
        dut.clk_smu_i,
        expect=1,
        cycles=FUSE_GATE_HOLD_CYCLES,
        name=f"smc_fuse_reset_n_delayed_o ({phase})",
    )
    log.info(
        "FUSE-GATE %s: smc_fuse_reset_n_delayed_o stayed 1 for %d clk_smu after the re-assert",
        phase,
        FUSE_GATE_HOLD_CYCLES,
    )
    sb.expect_eq(
        name,
        _sample(dut.smc_fuse_reset_n_delayed_o, "smc_fuse_reset_n_delayed_o"),
        1,
        evidence=evidence,
    )


# The specification states no latency from the fuse-reset release to the first ROM
# request, so the wait is a liveness bound declared here: 32 banks x 4096 entries
# zero-filled at one write per cycle, times 4 for a multi-cycle sequencer.
FIRST_FETCH_BOUND_CYCLES = 32 * 4096 * 4

# The ROM is 128 KiB at 0xC004_0000 and its request carries a 14-bit address of
# 64-bit words (hw/sys/smc/doc/rom.adoc:9-10, :22-24).
ROM_BASE = 0xC004_0000
ROM_LAST_BYTE = 0xC005_FFFF
ROM_WORD_BYTES = 8

# rom_req_t is a packed struct, MSB first: clk, en, addr[13:0], wdata[63:0], wmode, wmask.
ROM_REQ_BITS = 82
ROM_REQ_EN_BIT = 80
ROM_REQ_ADDR_LSB = 66
ROM_REQ_ADDR_WIDTH = 14
ROM_REQ_WMODE_BIT = 1


def _bits(text: str, lsb: int, width: int, name: str) -> int:
    chunk = text[len(text) - lsb - width : len(text) - lsb]
    if not set(chunk) <= {"0", "1"}:
        raise AssertionError(f"X/Z sample on {name}: {chunk}")
    return int(chunk, 2)


@dataclass
class FetchLeg:
    """One release leg: the held window, the release edge and the first ROM read."""

    name: str
    start: int
    held_edges: int = 0
    held_reads: int = 0
    max_count: int = 0
    saw_low: bool = False
    release_at: int | None = None
    fell_at: int | None = None
    first_at: int | None = None
    first_addr: int | None = None
    expired: bool = False
    count_at_arm: int | None = None
    stall_seen: bool = False
    clear_at: int | None = None
    error: str | None = None
    last_state: str = ""
    done: Event = field(default_factory=Event)

    def finish(self) -> None:
        self.done.set()


class RomFetchSampler:
    """Passive per-``clk_smu_i`` sampler of the fuse-reset gate and the SMC ROM request.

    ``begin_leg`` opens a leg at a cold-reset release. From then on every edge reads
    ``smc_rom_read_count_o`` (which the cold reset pin clears) and the ROM macro request
    ``u_dut.smc_rom_intf_req`` (en, wmode, addr). The leg ends at the first read request
    after the gate release edge, or when ``FIRST_FETCH_BOUND_CYCLES`` edges pass without one.
    """

    def __init__(self, dut, log) -> None:
        self._gate = dut.smc_fuse_reset_n_delayed_o
        self._count = dut.smc_rom_read_count_o
        self._stall_ovrd = dut.jtag_boot_stall_ovrd
        self._stall_val = dut.jtag_boot_stall
        self._req = dut.u_dut.smc_rom_intf_req
        if len(self._req) != ROM_REQ_BITS:
            raise AssertionError(f"{self._req._path} is {len(self._req)} bits, not rom_req_t")
        self._clk = dut.clk_smu_i
        self._log = log
        self.cycle = 0
        self.legs: dict[str, FetchLeg] = {}
        self.fence: list[tuple[str, float]] = []
        self.first_fetch_waits: list[tuple[str, int, int]] = []
        self._open: FetchLeg | None = None
        self._task = cocotb.start_soon(self._run())

    def mark(self, label: str) -> None:
        self.fence.append((label, _now_ns()))

    def begin_leg(self, name: str, *, record_count_at_arm: bool = False) -> None:
        """Open a leg at a cold-reset release.

        ``record_count_at_arm`` reads ``smc_rom_read_count_o`` at arming for the
        OBS-NO-FETCH-WHILE-HELD line; it is not graded.
        """
        if self._open is not None:
            raise AssertionError(f"leg {name} begins while leg {self._open.name} is still open")
        if name in self.legs:
            raise AssertionError(f"leg {name} begins twice")
        leg = FetchLeg(name=name, start=self.cycle)
        if record_count_at_arm:
            leg.count_at_arm = _sample(self._count, "smc_rom_read_count_o")
        self.legs[name] = leg
        self._open = leg

    async def _run(self) -> None:
        while True:
            await RisingEdge(self._clk)
            self.cycle += 1
            gate = _sample(self._gate, "smc_fuse_reset_n_delayed_o")
            count = _sample(self._count, "smc_rom_read_count_o")
            stall = _sample(self._stall_ovrd, "jtag_boot_stall_ovrd") & _sample(
                self._stall_val, "jtag_boot_stall"
            )
            req = str(self._req.value)
            en = _bits(req, ROM_REQ_EN_BIT, 1, "smc_rom_intf_req.en")
            wmode = _bits(req, ROM_REQ_WMODE_BIT, 1, "smc_rom_intf_req.wmode")
            addr = _bits(req, ROM_REQ_ADDR_LSB, ROM_REQ_ADDR_WIDTH, "smc_rom_intf_req.addr")
            leg = self._open
            if leg is not None:
                self._step(leg, gate, count, en and not wmode, addr, stall)

    def _step(self, leg: FetchLeg, gate: int, count: int, read: int, addr: int, stall: int) -> None:
        if stall:
            leg.stall_seen = True
        elif leg.stall_seen and leg.clear_at is None:
            leg.clear_at = self.cycle
        leg.last_state = (
            f"cycle={self.cycle} gate={gate} rom_read_count={count} read_en={read} "
            f"word_addr=0x{addr:04x}"
        )
        if leg.release_at is None:
            leg.max_count = max(leg.max_count, count)
            if gate == 0:
                leg.saw_low = True
                leg.held_edges += 1
                if read:
                    leg.held_reads += 1
            elif not leg.saw_low:
                leg.error = "the fuse reset reads 1 on the first sample of the leg"
            else:
                leg.release_at = self.cycle
            if leg.error is not None:
                self._open = None
                leg.finish()
                return
            if leg.release_at is None:
                return
        if gate == 0 and leg.fell_at is None:
            leg.fell_at = self.cycle
        if read:
            leg.first_at, leg.first_addr = self.cycle, addr
        elif self.cycle - leg.release_at >= FIRST_FETCH_BOUND_CYCLES:
            leg.expired = True
        else:
            return
        self._open = None
        leg.finish()

    def check_clear_to_release(self, log, name: str) -> int:
        """CHK-STALL-TRST: the gate opens within the bound of the stall-clear edge, then stays open.

        The clear edge is the first clk_smu edge on which jtag_boot_stall_ovrd and
        jtag_boot_stall no longer both read 1 after both read 1 inside the leg; the release
        edge is the first edge on which the gate reads 1. Both come from the per-edge sampler,
        so the count has no gap. The gate must then read 1 on every sampled edge from the
        release edge on, and at least ``FUSE_GATE_HOLD_CYCLES`` of those edges must have been
        sampled. Returns the cycles from the clear edge to the release edge.
        """
        leg = self.legs[name]
        if leg.release_at is None or leg.clear_at is None:
            raise AssertionError(
                f"CHK-STALL-TRST: leg={name} release_edge={leg.release_at} "
                f"clear_edge={leg.clear_at} not both seen last_state={leg.last_state}"
            )
        cycles = leg.release_at - leg.clear_at
        if not 0 <= cycles <= FUSE_GATE_RELEASE_BOUND_CYCLES:
            raise AssertionError(
                f"CHK-STALL-TRST: leg={name} clear_to_release={cycles} clk_smu outside "
                f"0..{FUSE_GATE_RELEASE_BOUND_CYCLES} last_state={leg.last_state}"
            )
        if leg.fell_at is not None:
            raise AssertionError(
                f"CHK-STALL-TRST: leg={name} gate fell {leg.fell_at - leg.release_at} clk_smu "
                f"after the release edge last_state={leg.last_state}"
            )
        sampled_end = leg.first_at if leg.first_at is not None else self.cycle
        held = sampled_end - leg.release_at
        if held < FUSE_GATE_HOLD_CYCLES:
            raise AssertionError(
                f"CHK-STALL-TRST: leg={name} only {held} clk_smu sampled after the release "
                f"edge, hold needs {FUSE_GATE_HOLD_CYCLES}"
            )
        log.info(
            "CHK-STALL-TRST: leg=%s clear_to_release=%d clk_smu bound=%d "
            "clear_edge=jtag_boot_stall_ovrd&jtag_boot_stall held_from_release=%d min=%d PASS",
            name,
            cycles,
            FUSE_GATE_RELEASE_BOUND_CYCLES,
            held,
            FUSE_GATE_HOLD_CYCLES,
        )
        return cycles

    def check_held(self, log, name: str) -> None:
        """OBS-NO-FETCH-WHILE-HELD: log the held window; nothing here is graded.

        The window is counted from the cold-reset pin release, and part of it is held by the
        primary reset, not by the fuse reset alone; the fuse-only part is shorter than the
        first-fetch latency, so a read count of 0 here cannot show that the fuse reset holds
        the CPU. The leg's error and a missing release edge still stop the test, because the
        first-fetch check depends on that edge.
        """
        leg = self.legs[name]
        if leg.error is not None:
            raise AssertionError(f"leg={name} {leg.error} last_state={leg.last_state}")
        if leg.release_at is None:
            raise AssertionError(f"leg={name} release edge not seen last_state={leg.last_state}")
        log.info(
            "OBS-NO-FETCH-WHILE-HELD: leg=%s held_cycles=%d rom_reads=%d max_rom_read_count=%d "
            "count_at_arm=%s not graded",
            name,
            leg.held_edges,
            leg.held_reads,
            leg.max_count,
            leg.count_at_arm,
        )

    async def check_first_fetch(self, sb, log, name: str, *, expect_word_addr: int) -> int:
        """CHK-FIRST-FETCH-AFTER-RELEASE: first read request within the declared bound.

        Returns the measured latency in clk_smu. The latency is logged, never graded.
        """
        leg = self.legs[name]
        log.info(
            "CHK-TIMEOUT-PATHS: wait=first-fetch leg=%s bound=%d clk_smu "
            "expiry=fail test with the last sampled state",
            name,
            FIRST_FETCH_BOUND_CYCLES,
        )
        await leg.done.wait()
        if leg.error is not None:
            raise AssertionError(
                f"CHK-FIRST-FETCH-AFTER-RELEASE: leg={name} {leg.error} last_state={leg.last_state}"
            )
        if leg.expired:
            raise AssertionError(
                f"CHK-FIRST-FETCH-AFTER-RELEASE: leg={name} no ROM read request within "
                f"bound={FIRST_FETCH_BOUND_CYCLES} clk_smu last_state={leg.last_state}"
            )
        latency = leg.first_at - leg.release_at
        self.first_fetch_waits.append((name, FIRST_FETCH_BOUND_CYCLES, latency))
        byte_addr = ROM_BASE + ROM_WORD_BYTES * expect_word_addr
        sb.expect_eq(
            f"first ROM read request word address ({name})",
            leg.first_addr,
            expect_word_addr,
            evidence="CHK-FIRST-FETCH-AFTER-RELEASE",
        )
        log.info(
            "CHK-FIRST-FETCH-AFTER-RELEASE: leg=%s latency=%d clk_smu bound=%d en=1 wmode=0 "
            "word_addr=0x%04x byte_addr=0x%08X window=0x%08X..0x%08X PASS",
            name,
            latency,
            FIRST_FETCH_BOUND_CYCLES,
            leg.first_addr,
            byte_addr,
            ROM_BASE,
            ROM_LAST_BYTE,
        )
        self.mark(f"CHK-FIRST-FETCH-AFTER-RELEASE {name}")
        return latency

    def check_fence(self, sb, log, expected: list[str]) -> None:
        """CHK-NONVAC fence and the CHK-TIMEOUT-PATHS summary line."""
        labels = [label for label, _ in self.fence]
        stamps = [ns for _, ns in self.fence]
        sb.expect_eq(
            "CHK-NONVAC ordered fence labels of every leg checker",
            labels,
            expected,
            evidence="CHK-NONVAC",
        )
        if stamps != sorted(stamps):
            raise AssertionError(f"CHK-NONVAC: fence stamps {stamps} are not ordered")
        first = sum(label.startswith("CHK-FIRST-FETCH-AFTER-RELEASE") for label in labels)
        log.info(
            "CHK-NONVAC: PASS fence=%s first_fetch_lines=%d",
            " < ".join(labels),
            first,
        )
        if len(self.first_fetch_waits) != len(self.legs):
            raise AssertionError(
                f"CHK-TIMEOUT-PATHS: {len(self.first_fetch_waits)} first-fetch waits finished "
                f"for {len(self.legs)} legs"
            )
        log.info(
            "CHK-TIMEOUT-PATHS: sense-done bound=%d gate-release bound=%d first-fetch bound=%d "
            "first_fetch_waits=%d expired=0",
            FUSE_SENSE_BOUND_CYCLES,
            FUSE_GATE_RELEASE_BOUND_CYCLES,
            FIRST_FETCH_BOUND_CYCLES,
            len(self.first_fetch_waits),
        )
