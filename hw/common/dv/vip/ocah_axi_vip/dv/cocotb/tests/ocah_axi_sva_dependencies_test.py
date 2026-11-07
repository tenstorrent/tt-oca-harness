# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 VNCHIP LABS
"""Drive legal and deliberately illegal dependencies into the real protocol SVA.

These checker selftests own both sides of the existing wire harness. A normal
VIP responder cannot generate the invalid VALID timing being tested. Fault
modes are expected-failure leaves; their production assertion reports must
be checked in the logs because the runner cannot yet match simulator failures
when the framework XML records a passing test.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge

COMMON_FAULTS = frozenset(
    {
        "b_no_request",
        "b_aw_only",
        "b_w_only",
        "b_same_w",
        "b_same_aw",
        "r_no_request",
        "r_same_ar",
        "b_after_reset",
        "r_after_reset",
    }
)
ID_FAULTS = frozenset({"b_wrong_id", "r_wrong_id"})


def validate_case(case, lite):
    if case not in COMMON_FAULTS | ID_FAULTS | {"legal"}:
        raise ValueError(f"Unknown AXI SVA case {case!r}")
    if lite and case in ID_FAULTS:
        raise ValueError(f"AXI4-Lite has no response IDs; case {case!r} requires AXI4")


class DependencyWires:
    def __init__(self, dut, lite):
        self.dut = dut
        self.lite = lite
        self.prefix = "l_axi" if lite else "s_axi"

    def set(self, **values):
        for name, value in values.items():
            getattr(self.dut, f"{self.prefix}_{name}").value = value

    async def step(self, **values):
        await FallingEdge(self.dut.clk)
        self.set(**values)
        await RisingEdge(self.dut.clk)
        await ReadOnly()

    async def reset(self):
        await FallingEdge(self.dut.clk)
        self.set(awvalid=0, wvalid=0, arvalid=0, bvalid=0, rvalid=0)
        self.dut.rst_n.value = 0
        await RisingEdge(self.dut.clk)
        await FallingEdge(self.dut.clk)
        self.dut.rst_n.value = 1
        await RisingEdge(self.dut.clk)
        await ReadOnly()

    async def request_write(self, ident=1):
        if not self.lite:
            await self.step(awid=ident, awvalid=1, wvalid=1)
        else:
            await self.step(awvalid=1, wvalid=1)
        await self.step(awvalid=0, wvalid=0)

    async def request_read(self, ident=1, length=0):
        if not self.lite:
            await self.step(arid=ident, arlen=length, arvalid=1)
        else:
            await self.step(arvalid=1)
        await self.step(arvalid=0)

    async def legal(self):
        # W may finish before AW; no response may precede either acceptance.
        await self.step(wvalid=1)
        await self.step(wvalid=0, awvalid=1)
        await self.step(awvalid=0, bvalid=1, bready=0)
        for _ in range(3):
            await self.step()
        await self.step(bready=1)
        await self.step(bvalid=0)
        # A response on the edge immediately after AW/W acceptance is legal.
        await self.step(awvalid=1, wvalid=1)
        await self.step(awvalid=0, wvalid=0, bvalid=1)
        await self.step(bvalid=0)
        await self.step(arvalid=1)
        await self.step(arvalid=0, rvalid=1, rready=0)
        for _ in range(3):
            await self.step()
        await self.step(rready=1)
        await self.step(rvalid=0)
        if not self.lite:
            # Multiple IDs and read beats retain pending work until LAST handshakes.
            await self.request_write(1)
            await self.request_write(2)
            await self.step(bid=2, bvalid=1)
            await self.step(bid=1)
            await self.step(bvalid=0)
            await self.request_read(1, 1)
            await self.request_read(2)
            await self.step(rid=1, rvalid=1, rlast=0)
            await self.step(rid=2, rlast=1)
            await self.step(rid=1, rlast=1)
            await self.step(rvalid=0)
        # Reset discards pending requests; fresh traffic then operates normally.
        await self.request_write()
        await self.request_read()
        await self.reset()
        await self.request_write()
        await self.step(bvalid=1)
        await self.step(bvalid=0)
        await self.request_read()
        await self.step(rvalid=1)
        await self.step(rvalid=0)

    async def fault(self, case):
        if case == "b_aw_only":
            await self.step(awvalid=1)
            await self.step(awvalid=0)
        elif case == "b_w_only":
            await self.step(wvalid=1)
            await self.step(wvalid=0)
        elif case == "b_same_w":
            await self.step(awvalid=1)
            await self.step(awvalid=0)
        elif case == "b_same_aw":
            await self.step(wvalid=1)
            await self.step(wvalid=0)
        elif case == "b_wrong_id":
            await self.request_write(1)
        elif case == "r_wrong_id":
            await self.request_read(1)
        elif case == "b_after_reset":
            await self.request_write()
            await self.reset()
        elif case == "r_after_reset":
            await self.request_read()
            await self.reset()
        if case.startswith("b_"):
            values = dict(bvalid=1, bready=0)
            if case == "b_wrong_id":
                values["bid"] = 2
            if case == "b_same_w":
                values["wvalid"] = 1
            if case == "b_same_aw":
                values["awvalid"] = 1
        else:
            values = dict(rvalid=1, rready=0)
            if case == "r_wrong_id":
                values["rid"] = 2
            if case == "r_same_ar":
                values["arvalid"] = 1
        await self.step(**values)
        # If assertions are absent, expect_fail rejects the passing diagnostic.
        await self.reset()


@cocotb.test()
async def ocah_axi_sva_dependencies_test(dut):
    lite = bool(int(cocotb.plusargs.get("OCAH_AXI_SVA_LITE", "0")))
    case = cocotb.plusargs.get("OCAH_AXI_SVA_CASE", "legal")
    validate_case(case, lite)
    wires = DependencyWires(dut, lite)
    cocotb.start_soon(Clock(dut.clk, 4, "ns").start())
    dut.rst_n.value = 0
    # tb_top initializes unused bundles; this test drives only its selected link.
    wires.set(
        awvalid=0,
        wvalid=0,
        arvalid=0,
        bvalid=0,
        rvalid=0,
        awready=1,
        wready=1,
        arready=1,
        bready=1,
        rready=1,
        awaddr=0,
        araddr=0,
        wdata=0,
        wstrb=15,
        bresp=0,
        rresp=0,
        rdata=0,
    )
    if not lite:
        wires.set(
            awid=1,
            bid=1,
            arid=1,
            rid=1,
            awlen=0,
            arlen=0,
            awsize=2,
            arsize=2,
            awburst=1,
            arburst=1,
            awlock=0,
            arlock=0,
            awprot=0,
            arprot=0,
            wlast=1,
            rlast=1,
        )
    await wires.reset()
    dut._log.info("AXI-SVA-CASE lite=%d case=%s", lite, case)
    if case == "legal":
        await wires.legal()
    else:
        await wires.fault(case)
    dut._log.info("AXI-SVA-CASE completed lite=%d case=%s", lite, case)
