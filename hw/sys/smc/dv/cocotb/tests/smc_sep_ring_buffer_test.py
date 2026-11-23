# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared driver for the SEP ring-buffer family: cocotb fills the buffer, the ROM drains it.

    u_dut  the OCCP *target*     -- the production boot ROM, owner of the SEP ring buffer
    u_bfm  the OCCP *controller* -- the sep_ring_buffer_test DV image

Unlike the rom-only family, the testbench is a participant here, not just an observer: no
SEP instance exists in this bench, so this test writes the status entries SEP would have
written, over the target's inbound AXI port. The controller then asks for them back one
GET_SEP_STATUS at a time and, with the STATUS_RPT_DISABLE strap clear, checks that the buffer
drains to empty.

Members differ only in how many entries are written, which is what selects the boundary
under test:

    +sep_rb_entries=0     underflow  -- every read must return an empty buffer (strap clear)
    +sep_rb_entries=600   overflow   -- 512-slot buffer, so the oldest 89 are dropped
    (unset)               nominal    -- randomised 1..512

Gating follows the rom-only family: poll both instances' scratch 0, fail on TEST_FAIL from
either, pass on TEST_PASS. The firmware walks min(count, 511) entries and then requires ten
further reads to return 0; its GET_SEP_STATUS helper compares each entry, in FIFO order, with
the shadow this driver mirrors into controller SRAM. With the STATUS_RPT_DISABLE strap set,
every GET_SEP_STATUS must instead return Unsupported_StatusID (0x07), and neither the entries
nor the empty buffer are checked. The entries this driver wrote are logged so a failure can be
read against them by hand.

The controller answers GetVersion before any entry is written and again after the drain. With
+sep_rb_terminal the first two entries are a SEP status and the error the SEP ROM records before
it halts on a manifest signature failure. status-coordination.adoc and occp-processing.adoc let
the primary SMC ROM leave its OCCP loop only on its own terminal paths, a scratch 3 park request
or a successful hand-off, so that entry must neither park hart 0 nor end OCCP service.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller rom-mode image           (required)
    +sep_rb_case=<name>       label for log and assertion text    (default: module name)
    +sep_rb_entries=<n>       entries to write                    (default: random 1..512)
    +sep_rb_terminal          lead with the named entries; needs +FORCE_STATUS_REPORTING
    +rom_test_timeout=<ns>    completion bound in ns              (default: DEFAULT_POLL_ITERS)
"""

from __future__ import annotations

import logging
import random

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_sep_ring_buffer_driver import (
    CTRL_PHASE_BASELINE,
    CTRL_PHASE_DONE,
    RING_BUFFER_SIZE,
    SEP_STATUS_CONTROL,
    SEP_TERMINAL_SIGNATURE_FAILURE,
    SepRingBufferDriver,
)
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import (
    SMC_CLK_PERIOD_NS,
    DualCsr,
    SmcDualHarness,
    dual_test,
    random_seed,
)
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    SCRATCH_SEP_RB_COUNT,
    SCRATCH_SEP_RB_FIRST,
    SCRATCH_SEP_RB_GUARD,
    SCRATCH_SEP_RB_PHASE,
    SCRATCH_SEP_RB_READY,
    SCRATCH_SEP_RB_SECOND,
    SCRATCH_STATUS_BUFFER_ADDR,
    SCRATCH_STATUS_TO_SEP,
    SMC_SRAM_BASE,
    STRAP_BITS,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    post_code_boot_phase,
    required_plusarg,
)
from smc_rom_park_defs import HART0_PARKED, PARK_REQ_VALUE, SCRATCH_PARK_REQ, park_loop_pcs

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000
PROGRESS_EVERY = 200

# Bound on the buffer-ready handshake alone. The ROM raises both scratch 9 bits during its
# own SRAM init, well before it can answer OCCP, so this is a stall detector rather than a
# budget: 10 ms of sim time at POLL_CYCLES granularity.
READY_POLL_ITERS = 1000
REQUIRED_EVIDENCE = ("CHK-SEP-RING-BUFFER",)
TERMINAL_EVIDENCE = (
    "CHK-SEP-TERMINAL-ENTRY",
    "CHK-SEP-TERMINAL-OCCP-LIVE",
    "CHK-SEP-TERMINAL-NO-PARK",
)
TERMINAL_ENTRIES = (SEP_STATUS_CONTROL, SEP_TERMINAL_SIGNATURE_FAILURE)

# Hart 0 sampling after the exchange: a parked hart retires only the park loop.
NO_PARK_WINDOW_CYCLES = 4000
NO_PARK_SAMPLE_CYCLES = 50


def _poll_iterations() -> tuple[int, str]:
    """Poll count for this run, and the text explaining where it came from."""
    budget = cocotb.plusargs.get("rom_test_timeout")
    if budget is None:
        return DEFAULT_POLL_ITERS, f"default bound {DEFAULT_POLL_ITERS} polls"
    budget_ns = int(str(budget), 0)
    if budget_ns <= 0:
        raise AssertionError(f"+rom_test_timeout must be a positive ns value, got {budget!r}")
    interval = POLL_CYCLES * SMC_CLK_PERIOD_NS
    iters = max(1, int(-(-budget_ns // interval)))
    return iters, f"+rom_test_timeout={budget_ns} ns / {interval} ns -> {iters} polls"


def _entry_count(rng: random.Random, leading: int) -> tuple[int, str]:
    """How many entries to write, and where that number came from."""
    # The ring keeps one slot empty, so a full write would drop the named leading entries.
    maximum = RING_BUFFER_SIZE - 1 if leading else RING_BUFFER_SIZE
    named = cocotb.plusargs.get("sep_rb_entries")
    if named is None:
        count = rng.randint(max(1, leading), maximum)
        return count, f"randomised to {count} (no +sep_rb_entries)"
    count = int(str(named), 0)
    if count < leading:
        raise AssertionError(f"+sep_rb_entries must be at least {leading}, got {named!r}")
    if leading and count > maximum:
        raise AssertionError(
            f"+sep_rb_entries={named} overwrites the {leading} named leading entries; "
            f"use at most {maximum}"
        )
    return count, f"+sep_rb_entries={count}"


async def _await_ctrl_phase(dut, bfm_csr: DualCsr, want: int, poll_iters: int) -> int:
    phase = 0
    for _ in range(poll_iters):
        phase = await bfm_csr.read("CTRL_PHASE", SCRATCH_SEP_RB_PHASE)
        if phase == want:
            return phase
        if await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL) == TEST_FAIL:
            break
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)
    raise AssertionError(f"controller never reached phase {want:#010x}; last {phase:#010x}")


async def _check_terminal(dut, harness: SmcDualHarness, dut_csr: DualCsr, bfm_csr: DualCsr):
    """The named entries came back exactly, OCCP stayed live, and hart 0 never parked."""
    first = await bfm_csr.read("CTRL_FIRST_ENTRY", SCRATCH_SEP_RB_FIRST)
    second = await bfm_csr.read("CTRL_SECOND_ENTRY", SCRATCH_SEP_RB_SECOND)
    if (first, second) != TERMINAL_ENTRIES:
        raise AssertionError(
            f"controller read back {first:#010x}, {second:#010x}; the driver wrote "
            f"{TERMINAL_ENTRIES[0]:#010x}, {TERMINAL_ENTRIES[1]:#010x}"
        )
    cocotb.log.info(
        "CHK-SEP-TERMINAL-ENTRY: GetStatus 0x8000 returned the control entry %#010x and then the "
        "SEP terminal signature-failure entry %#010x, each equal to the shadow",
        first,
        second,
    )
    phase = await bfm_csr.read("CTRL_PHASE", SCRATCH_SEP_RB_PHASE)
    if phase != CTRL_PHASE_DONE:
        raise AssertionError(f"controller phase {phase:#010x}, want {CTRL_PHASE_DONE:#010x}")
    cocotb.log.info(
        "CHK-SEP-TERMINAL-OCCP-LIVE: GetVersion 1.0.0 answered before the entries were written "
        "and again after the terminal entry was drained (controller phase %#010x)",
        phase,
    )

    park_req = await dut_csr.read("TARGET_PARK_REQ", SCRATCH_PARK_REQ)
    scratch_9 = await dut_csr.read("TARGET_SEP_STATUS", SCRATCH_STATUS_TO_SEP)
    post = await dut_csr.read("TARGET_POST_CODE_TERMINAL", SCRATCH_POST_CODE)
    loop = park_loop_pcs()
    pcs: set[int] = set()
    for _ in range(NO_PARK_WINDOW_CYCLES // NO_PARK_SAMPLE_CYCLES):
        pcs.add(int(dut.dut_wb_pc0.value))
        await ClockCycles(dut.clk_smc_i, NO_PARK_SAMPLE_CYCLES)
    parked = sorted(hex(pc) for pc in pcs & loop)
    if (
        park_req == PARK_REQ_VALUE
        or scratch_9 & HART0_PARKED
        or parked
        or post_code_boot_phase(post) != POST_CODE_BOOT_PHASE_OCCP_PROC
    ):
        raise AssertionError(
            f"after the terminal entry: target scratch 3 = {park_req:#010x}, scratch 9 = "
            f"{scratch_9:#010x}, park-loop PCs retired {parked}, POST {describe_post_code(post)}"
            f"\nCPU state:\n{harness.cpu_trace_report()}"
        )
    cocotb.log.info(
        "CHK-SEP-TERMINAL-NO-PARK: target scratch 3 = %#010x (no park request), scratch 9 = "
        "%#010x (HART0_PARKED clear), %d hart-0 PCs over %d cycles none in the park loop %s, "
        "POST %s",
        park_req,
        scratch_9,
        len(pcs),
        NO_PARK_WINDOW_CYCLES,
        sorted(hex(pc) for pc in loop),
        describe_post_code(post),
    )


@dual_test(REQUIRED_EVIDENCE)
async def smc_sep_ring_buffer_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_sep_ring_buffer_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_sep_ring_buffer_test")
    case = str(cocotb.plusargs.get("sep_rb_case") or "smc_sep_ring_buffer_test")
    poll_iters, poll_source = _poll_iterations()

    seed = random_seed()
    rng = random.Random(seed)
    terminal = cocotb.plusargs.get("sep_rb_terminal") is not None
    if terminal:
        if cocotb.plusargs.get("FORCE_STATUS_REPORTING") is None:
            raise AssertionError("+sep_rb_terminal needs +FORCE_STATUS_REPORTING")
        harness.required_evidence += TERMINAL_EVIDENCE
    leading = TERMINAL_ENTRIES if terminal else ()
    entry_count, count_source = _entry_count(rng, len(leading))

    cocotb.log.info(
        "%s (RANDOM_SEED=%d): u_dut = production ROM target, u_bfm = %s controller; "
        "%d entries (%s); %s",
        case,
        seed,
        controller_image,
        entry_count,
        count_source,
        poll_source,
    )

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)
    if terminal and harness.straps["dut"] >> STRAP_BITS["STATUS_RPT_DISABLE"] & 1:
        raise AssertionError("STATUS_RPT_DISABLE is set; the terminal entry could not be read")

    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Target first, as in the rom-only family: the controller's initialize_interface()
    # spins on the target-ready pad forever, so releasing the target is what lets the
    # controller past its own bring-up.
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    baseline_activity = bus_activity(dut)

    driver = SepRingBufferDriver(
        target_csr=dut_csr,
        ctrl_csr=bfm_csr,
        clk=dut.clk_smc_i,
        sram_base=SMC_SRAM_BASE,
        scratch={
            "status_to_sep": SCRATCH_STATUS_TO_SEP,
            "status_buffer_addr": SCRATCH_STATUS_BUFFER_ADDR,
            "cocotb_ready": SCRATCH_SEP_RB_READY,
            "cocotb_entry_count": SCRATCH_SEP_RB_COUNT,
            "shadow_guard": SCRATCH_SEP_RB_GUARD,
        },
    )

    try:
        await driver.wait_for_buffer_ready(READY_POLL_ITERS, POLL_CYCLES)
    except AssertionError as exc:
        dut_console.flush()
        bfm_console.flush()
        raise AssertionError(
            f"{case}: {exc}\n"
            f"target firmware trace:\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        ) from exc

    await _await_ctrl_phase(dut, bfm_csr, CTRL_PHASE_BASELINE, poll_iters)
    cocotb.log.info("%s: controller GetVersion answered before any entry was written", case)

    written = await driver.write_entries(entry_count, rng, leading)
    retained = driver.retained_entries()

    # The controller reads back at most one less than capacity, because the ring keeps one
    # slot empty. Anything older than that was overwritten before it could be asked for.
    cocotb.log.info(
        "%s: wrote %d entries, %d retained in the buffer (capacity %d)",
        case,
        len(written),
        len(retained),
        RING_BUFFER_SIZE - 1,
    )

    await driver.signal_entries_ready(len(written))

    target_scratch0 = 0
    ctrl_scratch0 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)

        if target_scratch0 == TEST_FAIL or ctrl_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            raise AssertionError(
                f"{case} reported failure.\n"
                f"  controller image    = {controller_image}\n"
                f"  entries written     = {len(written)} ({count_source})\n"
                f"  entries retained    = {len(retained)}\n"
                f"  buffer base         = {driver.buffer_base_addr:#010x}\n"
                f"  head/tail           = {driver.head}/{driver.tail}\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if target_scratch0 == TEST_PASS or ctrl_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "%s in flight (poll %d/%d): target=%#010x ctrl=%#010x, bus [%s]",
                case,
                iteration,
                poll_iters,
                target_scratch0,
                ctrl_scratch0,
                format_activity(bus_activity(dut)),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"{case} did not complete within {poll_iters}x{POLL_CYCLES} clk_smc_i "
            f"({poll_source}).\n"
            f"  controller image    = {controller_image}\n"
            f"  entries written     = {len(written)} ({count_source})\n"
            f"  buffer base         = {driver.buffer_base_addr:#010x}\n"
            f"  head/tail           = {driver.head}/{driver.tail}\n"
            f"  target scratch0     = {target_scratch0:#010x} "
            f"(expected {TEST_PASS:#010x})\n"
            f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    activity = bus_activity(dut)
    moved = [
        (ch, falls - base_falls, starts - base_starts)
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(activity, baseline_activity)
        if falls > base_falls
    ]
    if moved:
        cocotb.log.info(
            "%s bus activity: %s",
            case,
            ", ".join(
                f"I3C{ch} (+{falls} scl_falls, +{starts} starts)" for ch, falls, starts in moved
            ),
        )
    else:
        cocotb.log.info(
            "NOTE: no I3C channel saw an SCL fall. The pass did not come from GET_SEP_STATUS "
            "traffic on the wire; this is informational, not a gate."
        )

    if terminal:
        await _check_terminal(dut, harness, dut_csr, bfm_csr)

    cocotb.log.info(
        "CHK-SEP-RING-BUFFER: %d entries written, %d retained; target scratch0=%#010x, "
        "controller scratch0=%#010x. Final target POST %s",
        len(written),
        len(retained),
        target_scratch0,
        ctrl_scratch0,
        describe_post_code(post),
    )
    cocotb.log.info("%s PASS", case)
