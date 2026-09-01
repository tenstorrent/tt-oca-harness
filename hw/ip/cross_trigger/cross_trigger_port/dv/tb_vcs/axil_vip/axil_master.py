# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
AXI4-Lite Master VIP for Cross Trigger Port testbench

Implements AXI4-Lite master protocol using request/response structures.
"""

from cocotb.triggers import RisingEdge


class AxiLiteMaster:
    """
    AXI4-Lite master driving the cross_trigger_port AXI-Lite slave.
    Implements proper AXI4-Lite protocol with all 5 channels.
    Signal names follow cross_trigger_port ports using request/response structures.
    """

    def __init__(self, dut):
        self.dut = dut
        # Access flattened AXI-Lite signals at top level
        self.clk = dut.clk
        self.rst_n = dut.rst_n

        # Write address channel
        self.axil_awvalid = dut.axil_awvalid
        self.axil_awaddr = dut.axil_awaddr
        self.axil_awprot = dut.axil_awprot
        self.axil_awready = dut.axil_awready

        # Write data channel
        self.axil_wvalid = dut.axil_wvalid
        self.axil_wdata = dut.axil_wdata
        self.axil_wstrb = dut.axil_wstrb
        self.axil_wready = dut.axil_wready

        # Write response channel
        self.axil_bready = dut.axil_bready
        self.axil_bvalid = dut.axil_bvalid
        self.axil_bresp = dut.axil_bresp

        # Read address channel
        self.axil_arvalid = dut.axil_arvalid
        self.axil_araddr = dut.axil_araddr
        self.axil_arprot = dut.axil_arprot
        self.axil_arready = dut.axil_arready

        # Read data channel
        self.axil_rready = dut.axil_rready
        self.axil_rvalid = dut.axil_rvalid
        self.axil_rdata = dut.axil_rdata
        self.axil_rresp = dut.axil_rresp

    async def initialize_bus(self) -> None:
        """Drive AXI-Lite control lines to idle."""
        # Initialize all signals
        self.axil_awvalid.value = 0
        self.axil_wvalid.value = 0
        self.axil_bready.value = 0
        self.axil_arvalid.value = 0
        self.axil_rready.value = 0
        self.axil_awaddr.value = 0
        self.axil_awprot.value = 0
        self.axil_wdata.value = 0
        self.axil_wstrb.value = 0
        self.axil_araddr.value = 0
        self.axil_arprot.value = 0
        # Wait a cycle to settle
        await RisingEdge(self.clk)

    async def apply_reset(self, cycles: int = 2) -> None:
        """
        Apply active-low reset for given cycles, and leave bus in idle.
        Note: clock generation is expected to be handled by the test.
        """
        self.dut._log.info(f"AxiLiteMaster: applying reset for {cycles} cycles")
        self.rst_n.value = 0
        await self.initialize_bus()
        for _ in range(cycles):
            await RisingEdge(self.clk)
        self.rst_n.value = 1
        # Post-reset settle
        for _ in range(2):
            await RisingEdge(self.clk)

    async def write(self, addr: int, data: int, prot: int = 0) -> None:
        """
        Perform an AXI4-Lite write transaction.
        AXI4-Lite write sequence:
          1. Assert AWVALID with address and prot
          2. Wait for AWREADY
          3. Assert WVALID with data and strb
          4. Wait for WREADY
          5. Assert BREADY
          6. Wait for BVALID
          7. Deassert all signals
        """
        # Write Address Channel
        self.axil_awaddr.value = addr & 0xFFFFFFFF
        self.axil_awprot.value = prot & 0x7
        self.axil_awvalid.value = 1

        # Wait for AWREADY
        while True:
            await RisingEdge(self.clk)
            if self.axil_awready.value:
                break

        # Deassert AWVALID
        self.axil_awvalid.value = 0

        # Write Data Channel
        self.axil_wdata.value = data & 0xFFFFFFFF
        self.axil_wstrb.value = 0xF  # All bytes enabled
        self.axil_wvalid.value = 1

        # Wait for WREADY
        while True:
            await RisingEdge(self.clk)
            if self.axil_wready.value:
                break

        # Deassert WVALID
        self.axil_wvalid.value = 0

        # Write Response Channel
        self.axil_bready.value = 1

        # Wait for BVALID
        while True:
            await RisingEdge(self.clk)
            if self.axil_bvalid.value:
                break

        # Check response (should be OKAY = 0)
        resp = int(self.axil_bresp.value)
        if resp != 0:
            self.dut._log.warning(f"AXI write response not OKAY: {resp}")

        # Deassert BREADY
        self.axil_bready.value = 0

        # Optional idle cycle
        await RisingEdge(self.clk)

    async def read(self, addr: int, prot: int = 0) -> int:
        """
        Perform an AXI4-Lite read transaction and return data.
        AXI4-Lite read sequence:
          1. Assert ARVALID with address and prot
          2. Wait for ARREADY
          3. Assert RREADY
          4. Wait for RVALID
          5. Sample RDATA
          6. Deassert all signals
        """
        # Read Address Channel
        self.axil_araddr.value = addr & 0xFFFFFFFF
        self.axil_arprot.value = prot & 0x7
        self.axil_arvalid.value = 1

        # Wait for ARREADY
        while True:
            await RisingEdge(self.clk)
            if self.axil_arready.value:
                break

        # Deassert ARVALID
        self.axil_arvalid.value = 0

        # Read Data Channel - assert RREADY
        self.axil_rready.value = 1

        # Wait for RVALID
        while True:
            await RisingEdge(self.clk)
            if self.axil_rvalid.value:
                break

        # Sample RDATA
        data = int(self.axil_rdata.value)

        # Check response (should be OKAY = 0)
        resp = int(self.axil_rresp.value)
        if resp != 0:
            self.dut._log.warning(f"AXI read response not OKAY: {resp}")

        # Deassert RREADY
        self.axil_rready.value = 0

        # Optional idle cycle
        await RisingEdge(self.clk)

        return data
