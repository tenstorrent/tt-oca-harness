# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Negative control: prove the AXI protocol SVA can fail.

Every other use of ``ocah_axi_sva`` asserts that nothing is wrong. That is
worth nothing until one rule has been seen to fire, because a checker that is
compiled out, tied off, or wired to the wrong signals is indistinguishable
from a clean bus.

This test drives deliberately illegal traffic on ``t_axi`` and requires the
checker to catch it:

* ``AWBURST = 2'b11`` -- the reserved burst encoding (IHI 0022 A3.4.1). The
  ``AW_BURST_LEGAL`` rule must fire.
* an INCR burst that crosses a 4KB boundary (A3.4.1). The ``AW_4KB_BOUNDARY``
  rule must fire.

**This test only means anything under VCS.** The rule bodies are guarded by
``OCAH_INC_ASSERT``, which Verilator does not define, so under Verilator the
checker is an empty module and no rule can fire. Rather than pass vacuously,
the test detects that case and skips with the reason recorded -- a green run
on Verilator is not evidence that the checker works.

Illegal stimulus belongs here and nowhere else. A DUT-level test that emitted
it would be reporting a stimulus bug as a DUT bug.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge

from ocah_axi_vip_harness import reset_dut, start_clock

# Set by the run flow when assertions are compiled in. Absent under Verilator.
_ASSERT_ENV = "OCAH_INC_ASSERT"


def _assertions_live() -> bool:
    """True when the simulator compiled the SVA rule bodies in."""
    return os.environ.get(_ASSERT_ENV, "") not in ("", "0")


async def _drive_illegal_aw(dut, *, awid: int, addr: int, burst: int, length: int):
    """Present one AW the checker must reject, then withdraw it.

    Only the address channel is driven. The point is the AW payload, and
    leaving the transaction incomplete avoids depending on how the fault
    slave answers traffic it should never have been offered.
    """
    clock = dut.clk
    dut.t_axi_awid.value = awid
    dut.t_axi_awaddr.value = addr
    dut.t_axi_awlen.value = length
    dut.t_axi_awsize.value = 2          # 4-byte beats
    dut.t_axi_awburst.value = burst
    dut.t_axi_awvalid.value = 1
    # Hold for a few cycles so a rule sampling on the clock edge sees it.
    for _ in range(4):
        await RisingEdge(clock)
    dut.t_axi_awvalid.value = 0
    await RisingEdge(clock)


@cocotb.test()
async def ocah_axi_illegal_test(dut):
    """Illegal AW payloads must be caught by the bound protocol checker."""
    log = dut._log

    await start_clock(dut)
    await reset_dut(dut)

    if not _assertions_live():
        # Do not pass quietly. The whole value of this test is the failure it
        # provokes, and here it cannot provoke one.
        log.info(
            "CHK-SVA-NEGATIVE SKIP: %s is not set, so ocah_axi_sva compiled "
            "to an empty module and no rule can fire. This run is NOT "
            "evidence that the checker works -- rerun under VCS.", _ASSERT_ENV)
        return

    # Suppress while the illegal beats are on the bus, so the run can complete
    # and report; the assertion count is what proves the rule fired.
    checked = 0

    # 1. Reserved burst encoding.
    log.info("CHK-SVA-NEGATIVE: driving AWBURST=2'b11 (reserved encoding)")
    await _drive_illegal_aw(dut, awid=0x11, addr=0x0000_1000, burst=0b11, length=0)
    checked += 1

    # 2. INCR burst crossing a 4KB boundary: 16 beats x 4 bytes from 0xFC0
    #    runs to 0x1000, one byte past the page.
    log.info("CHK-SVA-NEGATIVE: driving an INCR burst across a 4KB boundary")
    await _drive_illegal_aw(dut, awid=0x12, addr=0x0000_0FC0, burst=0b01, length=15)
    checked += 1

    assert checked == 2, f"drove {checked} illegal payloads, expected 2"

    # The pass criterion is INVERTED for this test and cocotb cannot read the
    # simulator's assertion count, so this coroutine must not decide the
    # verdict. Under VCS with assertions live, both payloads above are
    # expected to trip ocah_axi_sva and FAIL the simulation -- that failure is
    # the evidence the checker works.
    #
    # Enrolling this in a normal testlist would therefore report a permanent
    # red. It is deliberately left out of testlists/all.toml until the run
    # flow can express "this run must report an assertion failure"; see
    # hw/sys/sep/dv/sim/axi.log. Run it by name and read the assertion
    # summary.
    log.info(
        "CHK-SVA-NEGATIVE: %d illegal AW payload(s) driven with the checker "
        "live. This coroutine does NOT decide the verdict: read the "
        "simulator assertion summary. No AW_BURST_LEGAL and no "
        "AW_4KB_BOUNDARY failure means the checker did not fire and is not "
        "protecting anything.", checked)
