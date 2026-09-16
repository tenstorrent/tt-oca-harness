# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.


from cocotb.triggers import RisingEdge


class APBMaster:
    """
    APB4 master driving the entropy_source APB slave.
    Implements proper APB4 protocol with pready wait states.
    Signal names follow entropy_source ports:
      clk_i, rst_ni, paddr_i[11:0], psel_i, penable_i, pwrite_i, pwdata_i[31:0],
      prdata_o[31:0], pready_o, pslverr_o
    """

    def __init__(self, dut):
        self.dut = dut
        # Support either direct DUT ports or an apb interface under tb
        apb = getattr(dut, "apb", None)
        handle = apb if apb is not None else dut
        # Convenience aliases
        self.pclk = handle.pclk if apb is not None else handle.pclk_i
        self.presetn = handle.presetn if apb is not None else handle.presetn_i
        self.paddr = handle.paddr if apb is not None else handle.paddr_i
        self.psel = handle.psel if apb is not None else handle.psel_i
        self.penable = handle.penable if apb is not None else handle.penable_i
        self.pwrite = handle.pwrite if apb is not None else handle.pwrite_i
        self.pwdata = handle.pwdata if apb is not None else handle.pwdata_i
        self.prdata = handle.prdata if apb is not None else handle.prdata_o
        # APB4 signals (may not be present on all DUTs)
        self.pready = getattr(handle, "pready", None)
        self.pslverr = getattr(handle, "pslverr", None)

    async def initialize_bus(self) -> None:
        """Drive APB control lines to idle."""
        self.psel.value = 0
        self.penable.value = 0
        self.pwrite.value = 0
        self.paddr.value = 0
        self.pwdata.value = 0
        # Wait a cycle to settle
        await RisingEdge(self.pclk)

    async def apply_reset(self, cycles: int = 2) -> None:
        """
        Apply active-low reset for given cycles, and leave bus in idle.
        Note: clock generation is expected to be handled by the test.
        """
        self.dut._log.info(f"APBMaster: applying reset for {cycles} cycles")
        self.presetn.value = 0
        await self.initialize_bus()
        for _ in range(cycles):
            await RisingEdge(self.pclk)
        self.presetn.value = 1
        # Post-reset settle
        for _ in range(2):
            await RisingEdge(self.pclk)

    async def write(self, addr: int, data: int) -> None:
        """
        Perform a single-beat APB write.
        APB4 compliant sequence with pready wait states:
          - SETUP: psel=1, penable=0, pwrite=1, paddr/pwdata valid
          - ACCESS: penable=1, wait for pready=1
          - IDLE: deassert psel/penable/pwrite
        """
        # SETUP phase
        self.paddr.value = addr & 0xFFF
        self.pwdata.value = data & 0xFFFF_FFFF
        self.pwrite.value = 1
        self.psel.value = 1
        self.penable.value = 0
        await RisingEdge(self.pclk)

        # ACCESS phase - assert penable and wait for pready
        self.penable.value = 1
        if self.pready is not None:
            # Wait for rising edge and check pready on that edge
            while True:
                await RisingEdge(self.pclk)
                if self.pready.value:
                    break
        else:
            await RisingEdge(self.pclk)

        # Return to IDLE
        self.psel.value = 0
        self.penable.value = 0
        self.pwrite.value = 0
        # Optional idle cycle
        await RisingEdge(self.pclk)

    async def read(self, addr: int) -> int:
        """
        Perform a single-beat APB read and return prdata.
        APB4 compliant with pready wait states:
          - SETUP: psel=1, penable=0, pwrite=0, paddr valid
          - ACCESS: penable=1, wait for pready=1, then sample prdata
          - IDLE: deassert psel/penable
        """
        # SETUP phase
        self.paddr.value = addr & 0xFFF
        self.pwrite.value = 0
        self.psel.value = 1
        self.penable.value = 0
        await RisingEdge(self.pclk)

        # ACCESS phase - assert penable, wait for pready, then sample PRDATA
        self.penable.value = 1
        if self.pready is not None:
            # Wait for rising edge and check pready on that edge
            while True:
                await RisingEdge(self.pclk)
                if self.pready.value:
                    break
        else:
            await RisingEdge(self.pclk)
        # Sample PRDATA when pready is asserted
        data = int(self.prdata.value)

        # Return to IDLE
        self.psel.value = 0
        self.penable.value = 0
        # Optional idle cycle
        await RisingEdge(self.pclk)
        return data
