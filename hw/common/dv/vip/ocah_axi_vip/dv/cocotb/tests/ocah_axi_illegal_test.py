# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Negative control: prove the AXI protocol SVA can fail.

Every other use of ``ocah_axi_sva`` asserts that nothing is wrong. That is
worth nothing until a rule has been seen to fire, because a checker that is
compiled out, tied off, or wired to the wrong signals looks exactly like a
clean bus.

This test drives deliberately illegal traffic on ``t_axi``:

* ``AWBURST = 2'b11`` -- the reserved burst encoding (IHI 0022 A3.4.1). The
  ``AW_BURST_LEGAL`` rule must fire.
* an INCR burst crossing a 4KB boundary: 16 beats of 4 bytes from 0x0FC0
  ends at 0x1000, one byte past the page (A3.4.1). ``AW_4KB_BOUNDARY`` must
  fire.

**The pass criterion is inverted, and this coroutine does not decide it.**
Success is the simulator reporting an assertion failure. cocotb cannot read
the assertion count, so the verdict has to come from the simulator's own
summary. Consequences:

* Under VCS with assertions compiled in, this run is EXPECTED TO FAIL. That
  failure is the evidence.
* Under Verilator the rule bodies are guarded by ``OCAH_INC_ASSERT``, which
  Verilator does not define, so ``ocah_axi_sva`` is an empty module, nothing
  can fire, and a green run proves nothing at all.

Because a normal testlist has no way to say "this run must report an
assertion failure", the test is deliberately not enrolled in
``dv/testlists/all.toml``. Run it by name and read the assertion summary.

An earlier draft gated the stimulus on an ``OCAH_INC_ASSERT`` environment
variable. Nothing sets that -- it is a compile-time Verilog define -- so the
guard was always false and the illegal beats were never driven. The stimulus
is now unconditional: under Verilator it is harmless because the checker is
empty, and under VCS it is the whole point.

Illegal stimulus belongs here and nowhere else. A DUT-level test emitting it
would be reporting a stimulus bug as a DUT bug.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from ocah_axi_vip_harness import reset_dut, start_clock


async def _drive_illegal_aw(dut, *, awid: int, addr: int, burst: int, length: int):
    """Present one AW the checker must reject, then withdraw it.

    Only the address channel is driven. The AW payload is the whole point, and
    leaving the transaction incomplete avoids depending on how the fault slave
    answers traffic it should never have been offered.
    """
    clock = dut.clk
    dut.t_axi_awid.value = awid
    dut.t_axi_awaddr.value = addr
    dut.t_axi_awlen.value = length
    dut.t_axi_awsize.value = 2          # 4-byte beats
    dut.t_axi_awburst.value = burst
    dut.t_axi_awvalid.value = 1
    # Hold several cycles so a rule sampling on the clock edge sees it, and so
    # the payload is visible in a waveform without hunting for one edge.
    for _ in range(4):
        await RisingEdge(clock)
    dut.t_axi_awvalid.value = 0
    await RisingEdge(clock)


@cocotb.test()
async def ocah_axi_illegal_test(dut):
    """Drive illegal AW payloads at the bound protocol checker."""
    log = dut._log

    await start_clock(dut)
    await reset_dut(dut)

    log.info("CHK-SVA-NEGATIVE: driving AWBURST=2'b11 (reserved encoding)")
    await _drive_illegal_aw(dut, awid=0x11, addr=0x0000_1000, burst=0b11, length=0)

    log.info("CHK-SVA-NEGATIVE: driving a 16-beat INCR across a 4KB boundary")
    await _drive_illegal_aw(dut, awid=0x12, addr=0x0000_0FC0, burst=0b01, length=15)

    log.info(
        "CHK-SVA-NEGATIVE: 2 illegal AW payload(s) driven. This coroutine "
        "does NOT decide the verdict -- read the simulator assertion "
        "summary. Under VCS, no AW_BURST_LEGAL and no AW_4KB_BOUNDARY "
        "failure means the checker did not fire and is protecting nothing. "
        "Under Verilator the checker is compiled out and this run is not "
        "evidence either way.")
