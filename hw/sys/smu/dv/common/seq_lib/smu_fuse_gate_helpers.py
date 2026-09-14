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
"""

from __future__ import annotations

from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

# The 768-word sense of the default image completes about 2 350 clk_smu after
# the primary reset release; the expiry is about twice that.
FUSE_SENSE_BOUND_CYCLES = 5000
# Gate path once the stall input clears: prim_sync3 (3) + sticky flop (1) +
# 16-stage pipe = 20 clk_smc, with the DTP export or pad path in front of it.
FUSE_GATE_RELEASE_BOUND_CYCLES = 256
# A level that must not move is watched for this long; it exceeds the gate
# path, so a gate that ignored the stall would release inside the window.
FUSE_GATE_HOLD_CYCLES = 64


def _sample(signal, name: str) -> int:
    val = signal.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z sample on {name}: {val}")
    return int(val)


def _now_ns() -> float:
    return float(get_sim_time(units="ns"))


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
