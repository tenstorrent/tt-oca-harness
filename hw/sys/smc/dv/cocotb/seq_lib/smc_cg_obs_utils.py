# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared LIVE observation helpers for SMC clock-gating cocotb sequences.

Logging policy: every record this module emits goes through ``cocotb.log``.
A module-level ``logging.getLogger(__name__)`` is **not** captured by the
cocotb/pyuvm runner, so the ``CHK-*`` / ``STEP`` / ``FENCE`` records written
through one never reach the kept log -- an evidence token that exists only in
the Python process cannot be re-verified by an audit
(``[EVIDENCE-TOKEN-CONDITIONAL]``). No module-level logger belongs here.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time

from . import smc_addr_map as _addr

# Re-exported: callers do `import smc_cg_obs_utils as cg` then `cg.PASS_ALL_CONFIG`.
from .smc_output_fabric_vip_utils import PASS_ALL_CONFIG as PASS_ALL_CONFIG

# Authoritative addresses / field masks (generated headers via smc_addr_map).
CLOCK_GATE_CONTROL = _addr.CLOCK_GATE_CONTROL
DMA_CG_EN = _addr.DMA_CG_EN
ZEROER_CG_EN = _addr.ZEROER_CG_EN
CG_HYST_SHIFT = _addr.CG_HYST_SHIFT
CG_HYST_MASK = _addr.CG_HYST_MASK

INBOUND0_FILTER_CONFIG = _addr.INBOUND0_FILTER_CONFIG
INBOUND0_START = _addr.INBOUND0_START
INBOUND0_END = _addr.INBOUND0_END
OUTBOUND0_FILTER_CONFIG = _addr.OUTBOUND0_FILTER_CONFIG
OUTBOUND0_START = _addr.OUTBOUND0_START
OUTBOUND0_END = _addr.OUTBOUND0_END

DMA_CTRL_CONFIG = _addr.DMA_CTRL_CONFIG
DMA_CTRL_STATUS_0 = _addr.DMA_CTRL_STATUS_0
DMA_CTRL_NEXT_ID_0 = _addr.DMA_CTRL_NEXT_ID_0
DMA_CTRL_DONE_0 = _addr.DMA_CTRL_DONE_0
DMA_CTRL_DST_ADDRESS_LO = _addr.DMA_CTRL_DST_ADDRESS_LO
DMA_CTRL_DST_ADDRESS_HI = _addr.DMA_CTRL_DST_ADDRESS_HI
DMA_CTRL_SRC_ADDRESS_LO = _addr.DMA_CTRL_SRC_ADDRESS_LO
DMA_CTRL_SRC_ADDRESS_HI = _addr.DMA_CTRL_SRC_ADDRESS_HI
DMA_CTRL_LENGTH_LO = _addr.DMA_CTRL_LENGTH_LO
DMA_CTRL_LENGTH_HI = _addr.DMA_CTRL_LENGTH_HI
DMA_CTRL_DST_STRIDE_LO = _addr.DMA_CTRL_DST_STRIDE_LO
DMA_CTRL_DST_STRIDE_HI = _addr.DMA_CTRL_DST_STRIDE_HI
DMA_CTRL_SRC_STRIDE_LO = _addr.DMA_CTRL_SRC_STRIDE_LO
DMA_CTRL_SRC_STRIDE_HI = _addr.DMA_CTRL_SRC_STRIDE_HI
DMA_CTRL_NUM_REPETITIONS_LO = _addr.DMA_CTRL_NUM_REPETITIONS_LO
DMA_CTRL_NUM_REPETITIONS_HI = _addr.DMA_CTRL_NUM_REPETITIONS_HI
DMA_CONFIG_ENABLED_ND = _addr.DMA_CONFIG_ENABLED_ND

ZEROER_CTRL_DEST_ADDR = _addr.ZEROER_CTRL_DEST_ADDR
ZEROER_CTRL_SIZE = _addr.ZEROER_CTRL_SIZE
ZEROER_CTRL_STATUS = _addr.ZEROER_CTRL_STATUS

#: `clk_rst.adoc`: the cool-reset pin passes a 32-sample reference-clock
#: de-glitcher before it reaches the primary reset. The pin falls between two
#: samples, so the assertion completes within one more reference cycle.
COOL_RESET_DEGLITCH_REF_CYCLES = 32
COOL_RESET_ASSERT_BOUND_REF_CYCLES = COOL_RESET_DEGLITCH_REF_CYCLES + 1


def sample_bit(dut, name: str) -> int:
    handle = getattr(dut, name)
    val = handle.value
    if val.is_resolvable is False:
        raise AssertionError(f"{name} sample is X/Z (unobservable)")
    return int(val)


def mark_fence(fence: list[tuple[str, int]], term: str) -> None:
    t = int(get_sim_time(unit="ns"))
    fence.append((term, t))
    cocotb.log.info("FENCE %s @ %dns", term, t)


def emit_chk(chk_seen: dict[str, str], name: str, line: str) -> None:
    cocotb.log.info("%s", line)
    chk_seen[name] = line


def log_step(step_id: str, msg: str) -> None:
    cocotb.log.info("STEP %s: %s", step_id, msg)


async def count_gated_rising(dut, gated_clk_name: str, smc_cycles: int) -> int:
    """Count rising edges on a TB-lifted gated clock over ~smc_cycles of clk_smc_i.

    Yields one timestep before raising the stop flag so a same-time gated edge
    at the window close can be counted (mitigates free-running N-1 under-count).
    Prefer :func:`count_enabled_at_smc_rise` for exact every-cycle proof.
    """
    edges = {"n": 0}
    stop = {"done": False}
    gated = getattr(dut, gated_clk_name)

    async def _edge_counter() -> None:
        while not stop["done"]:
            await RisingEdge(gated)
            if not stop["done"]:
                edges["n"] += 1

    counter = cocotb.start_soon(_edge_counter())
    await ClockCycles(dut.clk_smc_i, smc_cycles)
    # Let a same-timestep gated RisingEdge handler run before we stop it.
    await Timer(1, unit="ps")
    stop["done"] = True
    await Timer(1, unit="ps")
    counter.cancel()
    return edges["n"]


async def count_enabled_at_smc_rise(dut, gated_clk_name: str, smc_cycles: int) -> int:
    """Count how many of ``smc_cycles`` successive clk_smc rising edges sample gated==1.

    Same-domain free-running gated clocks (test_en bypass / disable_cg) sample 1
    on every SMC rise → return equals ``smc_cycles``.  A gated-off cycle samples 0.
    This avoids RisingEdge start/stop races that under- or over-count edge totals.
    Leaves the scheduler outside ReadOnly so the caller may drive TB pins next.
    """
    gated = getattr(dut, gated_clk_name)
    hits = 0
    for _ in range(smc_cycles):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        val = gated.value
        if val.is_resolvable is False:
            raise AssertionError(f"{gated_clk_name} sample is X/Z (unobservable)")
        if int(val) == 1:
            hits += 1
    # Exit ReadOnly before returning (caller may drive tb_test_en_i etc.).
    await Timer(1, unit="ps")
    return hits


async def count_enabled_pair_at_smc_rise(
    dut, gated_a: str, gated_b: str, smc_cycles: int
) -> tuple[int, int]:
    """Concurrent per-SMC-rise enable samples for two gated clocks (same window)."""
    ga = getattr(dut, gated_a)
    gb = getattr(dut, gated_b)
    hits_a = 0
    hits_b = 0
    for _ in range(smc_cycles):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        va = ga.value
        vb = gb.value
        if va.is_resolvable is False:
            raise AssertionError(f"{gated_a} sample is X/Z (unobservable)")
        if vb.is_resolvable is False:
            raise AssertionError(f"{gated_b} sample is X/Z (unobservable)")
        if int(va) == 1:
            hits_a += 1
        if int(vb) == 1:
            hits_b += 1
    await Timer(1, unit="ps")
    return hits_a, hits_b


async def count_enabled_triple_at_smc_rise(
    dut, gated_a: str, gated_b: str, gated_c: str, smc_cycles: int
) -> tuple[int, int, int]:
    """Concurrent per-SMC-rise enable samples for three gated clocks (same window)."""
    ga = getattr(dut, gated_a)
    gb = getattr(dut, gated_b)
    gc = getattr(dut, gated_c)
    hits_a = 0
    hits_b = 0
    hits_c = 0
    for _ in range(smc_cycles):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        va = ga.value
        vb = gb.value
        vc = gc.value
        if va.is_resolvable is False:
            raise AssertionError(f"{gated_a} sample is X/Z (unobservable)")
        if vb.is_resolvable is False:
            raise AssertionError(f"{gated_b} sample is X/Z (unobservable)")
        if vc.is_resolvable is False:
            raise AssertionError(f"{gated_c} sample is X/Z (unobservable)")
        if int(va) == 1:
            hits_a += 1
        if int(vb) == 1:
            hits_b += 1
        if int(vc) == 1:
            hits_c += 1
    await Timer(1, unit="ps")
    return hits_a, hits_b, hits_c


async def measure_gate_off_latency(
    dut,
    gated_clk_name: str,
    *,
    max_smc: int,
    diag_names: tuple[str, ...] = (),
) -> int:
    """Cycles from now until gated clock samples 0 at an SMC rise (then stays 0 once).

    Returns the cycle index of the first gated-off sample (0 = already off on the
    first rise). Raises on timeout. Used for card within-1-cycle idle gate-off.
    """
    gated = getattr(dut, gated_clk_name)
    for cyc in range(max_smc):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        val = gated.value
        if val.is_resolvable is False:
            raise AssertionError(f"{gated_clk_name} sample is X/Z (unobservable)")
        off = int(val) == 0
        await Timer(1, unit="ps")
        if off:
            return cyc
    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
    raise AssertionError(
        f"TIMEOUT waiting {gated_clk_name} gate-off within {max_smc} smc cycles {diag}"
    )


async def measure_gate_off_from_enable(
    dut,
    enable_name: str,
    gated_clk_name: str,
    *,
    enable_wait_smc: int,
    max_smc: int,
    diag_names: tuple[str, ...] = (),
) -> tuple[int, int]:
    """Cycles from the gate enable's own rising edge until the gated clock samples 0.

    Both nets are sampled at every clk_smc_i rise. The enable must read 0 on
    the first sample, so the origin is a real edge and not a level already
    present, and must rise within ``enable_wait_smc`` samples. The sample on
    which it first reads 1 is cycle 0; the result is ``(enable_at, latency)``
    with ``enable_at`` that sample's index and ``latency`` the number of
    samples after it on which the gated clock first read 0. Start this as a
    task before the enable is written: the frontdoor accesses that program the
    enable, and any readback after it, then cannot move the origin. Either
    wait expiring is a failure, never a pass ([TIMEOUT-MUST-FAIL]).
    """
    enable = getattr(dut, enable_name)
    gated = getattr(dut, gated_clk_name)
    enable_at = -1
    for cyc in range(enable_wait_smc + max_smc):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        en_val = enable.value
        g_val = gated.value
        if en_val.is_resolvable is False:
            raise AssertionError(f"{enable_name} sample is X/Z (unobservable)")
        if g_val.is_resolvable is False:
            raise AssertionError(f"{gated_clk_name} sample is X/Z (unobservable)")
        en_on = int(en_val) == 1
        off = int(g_val) == 0
        await Timer(1, unit="ps")
        if enable_at < 0:
            if en_on and cyc == 0:
                raise AssertionError(
                    f"{enable_name} already reads 1 on the first sample: the gate-off "
                    f"latency origin must be the enable's own rising edge"
                )
            if not en_on:
                if cyc + 1 >= enable_wait_smc:
                    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
                    raise AssertionError(
                        f"TIMEOUT waiting {enable_name} to rise within {enable_wait_smc} "
                        f"smc cycles {diag}"
                    )
                continue
            enable_at = cyc
        if off:
            return enable_at, cyc - enable_at
        if cyc - enable_at >= max_smc:
            break
    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
    raise AssertionError(
        f"TIMEOUT waiting {gated_clk_name} gate-off within {max_smc} smc cycles of "
        f"{enable_name} rising {diag}"
    )


async def wait_gate_off_edge(
    dut,
    gated_clk_name: str,
    *,
    max_smc: int,
    diag_names: tuple[str, ...] = (),
) -> tuple[float, int]:
    """Wait for the gated clock to sample 1 and then 0 at successive clk_smc_i rises.

    Returns the simulation time in ns of the first gated-off sample that
    follows an enabled one, and the number of samples taken to reach it. A
    caller that starts this as a task before waking the clock is handed the
    gate-off boundary that wake produces and can issue its next access from
    that instant. Expiry is a failure ([TIMEOUT-MUST-FAIL]).
    """
    gated = getattr(dut, gated_clk_name)
    seen_on = False
    for cyc in range(max_smc):
        await RisingEdge(dut.clk_smc_i)
        await ReadOnly()
        val = gated.value
        if val.is_resolvable is False:
            raise AssertionError(f"{gated_clk_name} sample is X/Z (unobservable)")
        on = int(val) == 1
        await Timer(1, unit="ps")
        if on:
            seen_on = True
        elif seen_on:
            return get_sim_time(unit="ns"), cyc + 1
    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
    raise AssertionError(
        f"TIMEOUT waiting {gated_clk_name} to run and gate off again within {max_smc} smc "
        f"cycles (seen_enabled={seen_on}) {diag}"
    )


async def wait_gated_off(
    dut,
    gated_clk_name: str,
    *,
    hyst: int,
    idle_observe: int,
    timeout_smc: int,
    diag_names: tuple[str, ...] = (),
) -> tuple[int, int]:
    """Wait until idle_observe consecutive smc cycles show zero gated rising edges."""
    last_toggle_at = -1
    for cyc in range(0, timeout_smc, idle_observe):
        edges = await count_gated_rising(dut, gated_clk_name, idle_observe)
        if edges == 0 and cyc >= hyst:
            return cyc + idle_observe, last_toggle_at
        if edges > 0:
            last_toggle_at = cyc + idle_observe
    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
    raise AssertionError(
        f"TIMEOUT waiting {gated_clk_name} off: last_toggle_at={last_toggle_at} hyst={hyst} {diag}"
    )


async def wait_reset_asserted(dut, rst_name: str, *, ref_cycles: int, ref_period_ns: float) -> int:
    """Wait for an active-low reset output to read 0, sampling every SMC rise.

    The bound is ``ref_cycles`` reference-clock periods of simulation time, so
    it holds at any SMC-to-reference clock ratio. Expiry is a FAILURE
    ([TIMEOUT-MUST-FAIL]). Returns the SMC cycles waited.
    """
    sig = getattr(dut, rst_name)
    start_ns = get_sim_time("ns")
    cycles = 0
    while int(sig.value) != 0:
        if get_sim_time("ns") - start_ns >= ref_cycles * ref_period_ns:
            raise AssertionError(
                f"TIMEOUT waiting {rst_name} assert within {ref_cycles} reference-clock "
                f"cycles ({cycles} smc cycles)"
            )
        await RisingEdge(dut.clk_smc_i)
        cycles += 1
    return cycles


async def wait_enabled(
    dut,
    gated_clk_name: str,
    *,
    timeout_smc: int,
    diag_names: tuple[str, ...] = (),
) -> int:
    """Wait until a gated clock samples enabled again; return the cycle it did.

    The event-driven counterpart to :func:`wait_gated_off`, for the settle
    between driving a bypass/enable and starting a counted window. Expiry is a
    FAILURE with the last observed state of ``diag_names``, never a pass
    ([TIMEOUT-MUST-FAIL]), so it cannot be used as a blind delay.
    """
    for cyc in range(timeout_smc):
        if await count_gated_rising(dut, gated_clk_name, 1) > 0:
            return cyc + 1
    diag = " ".join(f"{n}={sample_bit(dut, n)}" for n in diag_names)
    raise AssertionError(
        f"TIMEOUT waiting {gated_clk_name} to become enabled within "
        f"{timeout_smc} smc cycle(s): {diag}"
    )


async def measure_regate_delay(
    dut,
    gated_clk_name: str,
    *,
    hyst: int,
    timeout_smc: int,
) -> int:
    """Measure cycles from now until gated clock stays quiet for 2 cycles.

    Call immediately after activity ends (busy fallen / access done). Returns the
    cycle index of the last observed gated rising edge (0 if already quiet).
    """
    last_edge_at = -1
    for cyc in range(timeout_smc):
        # Sample one smc cycle of gated edges.
        edges = await count_gated_rising(dut, gated_clk_name, 1)
        if edges > 0:
            last_edge_at = cyc
        elif last_edge_at >= 0 and (cyc - last_edge_at) >= 2:
            return last_edge_at + 1
        elif last_edge_at < 0 and cyc >= max(1, hyst):
            # Never toggled after idle start — delay ≈ 0.
            return 0
    raise AssertionError(
        f"TIMEOUT measuring re-gate delay on {gated_clk_name}: "
        f"last_edge_at={last_edge_at} hyst={hyst}"
    )


def assert_fence_order(fence: list[tuple[str, int]], expected: list[str]) -> None:
    """Structural record only: the term order equals the source order.

    In a straight-line body the recorded order equals ``expected`` by
    construction, so this cannot fail on any RTL -- it is a bookkeeping
    restatement, not a proof. A sequence whose non-vacuity token rests on the
    fence must use :func:`assert_fence_progress` (which adds the DUT-time
    claim) and pair it with a measured contrast in the same token
    (``[NO-ALWAYS-PASS-CHECKER]``).
    """
    order = [t for t, _ in fence]
    assert order == expected, f"NONVAC fence order wrong: {order} expected {expected}"


def assert_fence_progress(fence: list[tuple[str, int]], expected: list[str]) -> list[int]:
    """Fence order **plus** strictly increasing simulation timestamps.

    Unlike :func:`assert_fence_order`, the timestamp leg is a claim about the
    run and not about the source text: it fails if two phases were recorded at
    the same simulation time, i.e. if a phase completed without the DUT
    advancing (a gater that never gates, an activity window that consumed no
    time, a wait that returned immediately). Returns the timestamps so the
    caller can carry them in its evidence token.
    """
    assert_fence_order(fence, expected)
    times = [t for _, t in fence]
    for prev, nxt in zip(times, times[1:]):
        assert nxt > prev, (
            f"NONVAC fence timestamps are not strictly increasing: {fence} -- a "
            f"phase was recorded at the same simulation time as its "
            f"predecessor, so no DUT time elapsed between them"
        )
    return times
