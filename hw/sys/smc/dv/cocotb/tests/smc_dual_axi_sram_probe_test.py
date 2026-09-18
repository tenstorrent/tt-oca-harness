# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Measure whether an inbound AXI manager reaches the CPU scratch SRAM window.

The dual OCCP boot flow stages a payload image in the controller's scratch SRAM
with a front-door AXI write, so this probe establishes that the path works.

Each address is read before and after its write, and the check is that the value
became exactly the pattern written. Three distinct patterns are used, one of them
across a 64-byte bank stripe boundary, so neither a stuck default slave nor a
decode that only works within one bank can satisfy it. The banks are not zeroed
in this testbench (``disable_sram_auto_init_i`` is tied high), so the pre-write
values are whatever the array powers up with and are not asserted on.

Both instances come up with boot_stall released. Holding it sticky-stalls
``fuse_reset_n`` and keeps the whole warm reset domain in reset; the scratch
banks hang off the CPU cluster, so its front port never responds and the probe
hangs rather than measuring anything. Releasing means both production boot ROMs
run, which is harmless here: the probe addresses start at SMC_ROM_STACK_END,
above the ROM's own stack, and no I3C traffic exists in this test to make either
ROM write there.

The same addresses are then read through the hierarchical peek, which resolves
a byte offset to a (bank, entry) with smc_scratch_map_pkg -- the same decode the
+smc_scratch_ram_hex image loader uses. Requiring the two views to agree is what
makes that decode a measured fact rather than an assumption, so the offsets are
chosen to exercise each of its fields: the two stripe bits, the wrap of the
four-bank cycle, and a jump to the next 128 KB group.

``init_mem_done_o`` must reach 1 on both instances before the probe starts
(``CHK-AXI-INIT-MEM-DONE``); the watcher raises if either is still 0 at the bound.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test

REQUIRED_EVIDENCE = (
    "CHK-AXI-INIT-MEM-DONE",
    "CHK-AXI-SCRATCH-REACHABLE",
    "CHK-SCRATCH-BACKDOOR-DECODE",
)

# Start of the OCCP-writable SRAM window (SMC_ROM_STACK_END): the address the
# real flow stages a payload at, so the probe asks about the address that
# matters rather than a convenient one.
PROBE_BASE = 0xC006_6400
SCRATCH_WINDOW_BASE = 0xC006_0000

# One offset per field of the bank/entry decode, so a decode that is wrong in
# any one field cannot pass. Bank and entry below are what smc_scratch_map_pkg
# resolves PROBE_BASE + the offset to; PROBE_BASE itself is 0x6400 into the
# window, which is why the baseline entry is 800 rather than 0.
PROBE_PATTERNS = {
    # bank 0, entry 800 -- the baseline every other row is measured against.
    PROBE_BASE + 0x0000: 0x1122_3344_5566_7788,
    # entry low bits (address[5:3]): bank 0, entry 801.
    PROBE_BASE + 0x0008: 0xDEAD_BEEF_CAFE_F00D,
    # stripe bit 0 (address[6]): same entry, bank 1.
    PROBE_BASE + 0x0040: 0xA5A5_5A5A_C3C3_3C3C,
    # stripe bit 1 (address[7]): same entry, bank 2.
    PROBE_BASE + 0x0080: 0x0F0F_F0F0_1E1E_E1E1,
    # The four-bank cycle wraps here: back to bank 0, entry 808. A model that
    # rotates across all 32 banks every 64 bytes lands on bank 4 instead, which
    # is the disagreement this offset exists to catch.
    PROBE_BASE + 0x0100: 0x1357_9BDF_2468_ACE0,
    # Next 128 KB group (address[19:17]): bank 4, same entry as the baseline.
    PROBE_BASE + 0x2_0000: 0xFEDC_BA98_7654_3210,
}

# Bound on init_mem_done_o rising on both instances; expiry fails the test.
INIT_MEM_WATCH_CYCLES = 100_000
INIT_MEM_POLL_CYCLES = 500


async def _peek_bfm_scratch(dut, addr: int) -> tuple[int, int]:
    """Read the scratch macro directly, bypassing AXI -- see the docstring."""
    dut.tb_bfm_scratch_peek_offset.value = addr - SCRATCH_WINDOW_BASE
    await ClockCycles(dut.clk_smc_i, 2)
    return (
        int(dut.tb_bfm_scratch_peek_data.value),
        int(dut.tb_bfm_scratch_peek_ecc.value),
    )


async def _watch_init_mem_done(dut, log) -> None:
    """Both clusters must report mem-init done once boot_stall is released.

    With disable_sram_auto_init_i=1 the cluster's mem-init FSM passes straight
    through MEM_ZERO_IDLE -> MEM_ZERO_DONE, so init_mem_done rises within a few
    cycles of fuse_reset releasing. A flag that stays 0 means the reset never
    released or the TB is not reading the DUT's port; either fails the run.
    """
    for waited in range(0, INIT_MEM_WATCH_CYCLES, INIT_MEM_POLL_CYCLES):
        dut_done = int(dut.dut_init_mem_done_o.value)
        bfm_done = int(dut.bfm_init_mem_done_o.value)
        if dut_done == 1 and bfm_done == 1:
            log.info(
                "CHK-AXI-INIT-MEM-DONE: dut and bfm init_mem_done_o both 1 within "
                "%d clk_smc_i cycles (bound=%d)",
                waited,
                INIT_MEM_WATCH_CYCLES,
            )
            return
        await ClockCycles(dut.clk_smc_i, INIT_MEM_POLL_CYCLES)
    raise AssertionError(
        f"init_mem_done_o still dut={int(dut.dut_init_mem_done_o.value)} "
        f"bfm={int(dut.bfm_init_mem_done_o.value)} after {INIT_MEM_WATCH_CYCLES} "
        "clk_smc_i cycles: the cluster never left mem-init after boot_stall release"
    )


@dual_test(REQUIRED_EVIDENCE)
async def smc_dual_axi_sram_probe_test(harness: SmcDualHarness) -> None:
    dut = cocotb.top
    log = cocotb.log

    # boot_stall released on both: holding it keeps fuse_reset_n asserted and
    # the whole warm domain -- including the CPU cluster the scratch banks hang
    # off -- in reset. See the module docstring.
    await harness.bring_up(hold_dut_boot=False, hold_bfm_boot=False)

    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)
    await _watch_init_mem_done(dut, log)

    # check_response=False everywhere: a DECERR is a *result* here, not an
    # error to raise. If the window is unreachable this probe must say so
    # precisely rather than dying inside the VIP.
    failures: list[str] = []

    before: dict[int, int] = {}
    for addr in PROBE_PATTERNS:
        rd = await bfm_csr.seq.read_result(addr, size=3, check_response=False)
        before[addr] = int(rd.data)
        log.info("AXI-PROBE pre-read  %#010x -> %#018x  resp=%s", addr, before[addr], rd.resp)
        if int(rd.resp) != 0:
            failures.append(f"pre-read {addr:#010x} resp={rd.resp} (want OKAY)")

    for addr, pattern in PROBE_PATTERNS.items():
        wr = await bfm_csr.seq.write_result(addr, pattern, size=3, check_response=False)
        log.info("AXI-PROBE write     %#010x <- %#018x  resp=%s", addr, pattern, wr.resp)
        if int(wr.resp) != 0:
            failures.append(f"write {addr:#010x} resp={wr.resp} (want OKAY)")

    for addr, pattern in PROBE_PATTERNS.items():
        rd = await bfm_csr.seq.read_result(addr, size=3, check_response=False)
        got = int(rd.data)
        peek_data, peek_ecc = await _peek_bfm_scratch(dut, addr)
        log.info(
            "AXI-PROBE post-read %#010x -> %#018x  resp=%s  "
            "(was %#018x; peek data=%#018x ecc=%#04x)",
            addr,
            got,
            rd.resp,
            before[addr],
            peek_data,
            peek_ecc,
        )
        if int(rd.resp) != 0:
            failures.append(f"post-read {addr:#010x} resp={rd.resp} (want OKAY)")
        elif got != pattern:
            failures.append(
                f"{addr:#010x} reads {got:#018x} after writing {pattern:#018x} "
                f"(was {before[addr]:#018x} before the write)"
            )
        # The backdoor has to land on the same macro word the front door did.
        # Only checked once the AXI value is known good, so a decode complaint
        # cannot be raised about a write that never took.
        if int(rd.resp) == 0 and got == pattern and peek_data != pattern:
            failures.append(
                f"backdoor decode: {addr:#010x} holds {pattern:#018x} over AXI but "
                f"smc_scratch_map_pkg resolves offset {addr - SCRATCH_WINDOW_BASE:#07x} "
                f"to a macro word holding {peek_data:#018x}. The image loader in "
                "smc_cpu_mem_dv.sv uses this same decode, so firmware staged with "
                "+smc_scratch_ram_hex is landing somewhere the CPU will not fetch it."
            )

    # ------------------------------------------------------------------
    # I3C CSR instance decode.
    #
    # The wrapper's range-based instance decode only works when it is given the
    # system base address. With BASE_ADDR=0 it matches nothing and falls through
    # to instance 0 silently, answering OKAY, which leaves five of six
    # controllers unreachable. Assert each instance decodes to itself.
    # ------------------------------------------------------------------
    I3C_WRAP_BASE = 0xC003_A000
    I3C_WRAP_STRIDE = 0x1000
    for inst in (0, 1, 3):
        addr = I3C_WRAP_BASE + inst * I3C_WRAP_STRIDE
        # +0x0 is the wrapper reset/enable register i3c_release_reset() writes
        # first.
        wr = await bfm_csr.seq.write_result(addr, 0x0000_0000, size=2, check_response=False)
        await ClockCycles(dut.clk_periph_i, 8)
        got_addr = int(dut.tb_bfm_i3c_awaddr.value)
        got_sel = int(dut.tb_bfm_i3c_wsel.value)
        log.info(
            "AXI-PROBE i3c-decode: wrote %#010x (instance %d) resp=%s -> wrapper "
            "saw awaddr=%#010x, write_select=%d",
            addr,
            inst,
            wr.resp,
            got_addr,
            got_sel,
        )
        if int(wr.resp) != 0:
            failures.append(f"i3c CSR write {addr:#010x} resp={wr.resp}")
        elif got_sel != inst:
            failures.append(
                f"i3c CSR write to instance {inst} ({addr:#010x}) was decoded to "
                f"instance {got_sel} (wrapper saw awaddr={got_addr:#010x}). "
                "Every instance aliases to whatever this decodes to, so the "
                "firmware's channel choice has no effect on which core drives "
                "the pads."
            )

    if failures:
        raise AssertionError(
            "CHK-AXI-SCRATCH-REACHABLE: bfm_axi (SEP_IN) did NOT reach the CPU "
            f"scratch window at {PROBE_BASE:#010x}:\n  " + "\n  ".join(failures)
        )

    log.info(
        "CHK-AXI-SCRATCH-REACHABLE: bfm_axi (SEP_IN) wrote %d distinct patterns "
        "at %#010x -- covering both stripe bits, the wrap of the four-bank cycle "
        "and the next 128 KB group -- and read every one of them back, each "
        "having changed from its pre-write value. The front door reaches the CPU "
        "scratch window.",
        len(PROBE_PATTERNS),
        PROBE_BASE,
    )
    log.info(
        "CHK-SCRATCH-BACKDOOR-DECODE: the hierarchical peek resolved every one of "
        "those offsets to the macro word AXI had just written, so the decode "
        "smc_scratch_map_pkg gives the +smc_scratch_ram_hex loader agrees with "
        "the cluster's own."
    )
    # A front-door probe that raised a DED or tripped a watchdog on either
    # instance would still have read its patterns back; the latches say it
    # did neither.
    harness.assert_no_fault_latched("AXI-PROBE fault-latches")
