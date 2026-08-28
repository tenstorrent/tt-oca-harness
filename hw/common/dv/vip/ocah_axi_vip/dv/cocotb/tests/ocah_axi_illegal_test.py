# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Negative control: prove the AXI protocol SVA can fail.

Every other use of ``ocah_axi_sva`` asserts that nothing is wrong. That is
worth nothing until a rule has been seen to fire, because a checker that is
compiled out, tied off, or wired to the wrong signals looks exactly like a
clean bus.

This test drives deliberately illegal traffic on ``t_axi``:

* ``AWBURST = 2'b11`` -- the reserved burst encoding (IHI 0022 A3.4.1).
  ``OCAH_AXI_AW_BURST_LEGAL`` must fire.
* an INCR burst crossing a 4KB boundary: 16 beats of 4 bytes from 0x0FC4
  covers 0x0FC4 to 0x1003, so its last four bytes are in the next page
  (A3.4.1). ``OCAH_AXI_AW_4KB_BOUNDARY`` must fire. 0x0FC0 would NOT do: it
  covers 0x0FC0 to 0x0FFF, ending on the last byte inside the page, which
  AXI permits.

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
assertion failure", the entry in ``dv/testlists/all.toml`` carries the
``axi_sva_negative`` tag, no ``ci`` tag and no group membership. Select it by
name and read the assertion summary.

The stimulus is unconditional. ``OCAH_INC_ASSERT`` is a compile-time Verilog
define and is not readable from Python, so there is nothing here to gate on:
under Verilator the illegal beats are harmless because the checker is empty,
and under VCS they are the whole point.

The fault slave is built with ``tolerate_illegal_addressing``. Both payloads
are requests it would otherwise refuse to serve, and the refusal would end
the run before the rule under test had been sampled. The tolerance is opt-in
and applies to this bench only: every other user of the slave still raises on
a reserved encoding or a page crossing, which is what makes those violations
visible when a DUT emits them.

Illegal stimulus belongs here and nowhere else. A DUT-level test emitting it
would be reporting a stimulus bug as a DUT bug.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from ocah_axi_vip_harness import (
    build_wire_slave,
    start_clock_reset,
    _wait_ready,
)


async def _drive_illegal_aw(dut, *, awid: int, addr: int, burst: int, length: int):
    """Present one AW the checker must reject, and complete the handshake.

    Every AW payload rule is qualified on ``awvalid && awready`` -- an accepted
    request, not an offered one. Driving AWVALID alone therefore proves
    nothing: without a slave raising AWREADY the antecedent never holds and no
    rule can fire, however illegal the payload is. So the fault slave is
    attached and this waits for AWREADY before withdrawing.
    """
    clock = dut.clk
    dut.t_axi_awid.value = awid
    dut.t_axi_awaddr.value = addr
    dut.t_axi_awlen.value = length
    dut.t_axi_awsize.value = 2          # 4-byte beats
    dut.t_axi_awburst.value = burst
    dut.t_axi_awvalid.value = 1
    await _wait_ready(clock, dut.t_axi_awready)
    dut.t_axi_awvalid.value = 0
    await RisingEdge(clock)


@cocotb.test()
async def ocah_axi_illegal_test(dut):
    """Drive illegal AW payloads at the bound protocol checker."""
    log = dut._log

    build_wire_slave(dut, tolerate_illegal_addressing=True)
    await start_clock_reset(dut)

    log.info(
        "CHK-SVA-NEGATIVE: driving AWBURST=2'b11 (reserved encoding); "
        "OCAH_AXI_AW_BURST_LEGAL must fire")
    await _drive_illegal_aw(dut, awid=0x11, addr=0x0000_1000, burst=0b11, length=0)

    log.info(
        "CHK-SVA-NEGATIVE: driving a 16-beat INCR across a 4KB boundary; "
        "OCAH_AXI_AW_4KB_BOUNDARY must fire")
    await _drive_illegal_aw(dut, awid=0x12, addr=0x0000_0FC4, burst=0b01, length=15)

    log.info(
        "CHK-SVA-NEGATIVE: 2 illegal AW payload(s) driven. This coroutine "
        "does NOT decide the verdict -- read the simulator assertion "
        "summary. Under VCS, no AW_BURST_LEGAL and no AW_4KB_BOUNDARY "
        "failure means the checker did not fire and is protecting nothing. "
        "Under Verilator the checker is compiled out and this run is not "
        "evidence either way.")
