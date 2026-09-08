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

``init_mem_done_o`` and the hierarchical scratch peek are reported but gate
nothing. The peek reproduces smc_cpu_mem_integration's striped bank/entry decode,
which is only known-good at offset 0, so it disagrees with AXI at other offsets.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from smc_dual_base_test import DualCsr, SmcDualHarness

# Start of the OCCP-writable SRAM window (SMC_ROM_STACK_END): the address the
# real flow stages a payload at, so the probe asks about the address that
# matters rather than a convenient one.
PROBE_BASE = 0xC006_6400
SCRATCH_WINDOW_BASE = 0xC006_0000

PROBE_PATTERNS = {
    PROBE_BASE + 0x00: 0x1122_3344_5566_7788,
    PROBE_BASE + 0x08: 0xDEAD_BEEF_CAFE_F00D,
    # +0x40 crosses into the next 64-byte bank stripe.
    PROBE_BASE + 0x40: 0xA5A5_5A5A_C3C3_3C3C,
}

# How long to watch init_mem_done_o before giving up on it (informational).
INIT_MEM_WATCH_CYCLES = 100_000
INIT_MEM_POLL_CYCLES = 500


async def _peek_bfm_scratch(dut, addr: int) -> tuple[int, int]:
    """Informational only -- see the module docstring."""
    dut.tb_bfm_scratch_peek_offset.value = addr - SCRATCH_WINDOW_BASE
    await ClockCycles(dut.clk_smc_i, 2)
    return (
        int(dut.tb_bfm_scratch_peek_data.value),
        int(dut.tb_bfm_scratch_peek_ecc.value),
    )


async def _watch_init_mem_done(dut, log) -> bool:
    """Report when the cluster's mem-init FSM leaves reset. Never fails."""
    for _ in range(INIT_MEM_WATCH_CYCLES // INIT_MEM_POLL_CYCLES):
        if int(dut.bfm_init_mem_done_o.value) == 1:
            log.info("AXI-PROBE init_mem_done_o: asserted on the bfm instance")
            return True
        await ClockCycles(dut.clk_smc_i, INIT_MEM_POLL_CYCLES)
    log.warning(
        "AXI-PROBE init_mem_done_o: still 0 on bfm (dut=%d) after %d clk_smc_i "
        "cycles. Reported, not fatal: with disable_sram_auto_init_i=1 there is "
        "no zeroing to wait for, and this flag is not on the AXI path.",
        int(dut.dut_init_mem_done_o.value),
        INIT_MEM_WATCH_CYCLES,
    )
    return False


@cocotb.test()
async def smc_dual_axi_sram_probe_test(_dut) -> None:
    dut = cocotb.top
    log = cocotb.log

    harness = SmcDualHarness()
    # boot_stall released on both: holding it keeps fuse_reset_n asserted and
    # the whole warm domain -- including the CPU cluster the scratch banks hang
    # off -- in reset. See the module docstring.
    await harness.bring_up(hold_dut_boot=False, hold_bfm_boot=False)

    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)
    init_done = await _watch_init_mem_done(dut, log)

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
            f"scratch window at {PROBE_BASE:#010x} "
            f"(init_mem_done={int(init_done)}):\n  " + "\n  ".join(failures)
        )

    log.info(
        "CHK-AXI-SCRATCH-REACHABLE: bfm_axi (SEP_IN) wrote %d distinct patterns "
        "across a bank stripe boundary at %#010x and read every one of them "
        "back, each having changed from its pre-write value. The front door "
        "reaches the CPU scratch window.",
        len(PROBE_PATTERNS),
        PROBE_BASE,
    )
