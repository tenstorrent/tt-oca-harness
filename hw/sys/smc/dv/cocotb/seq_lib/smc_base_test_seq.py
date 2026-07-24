# SPDX-License-Identifier: Apache-2.0
"""Base sequence for SMC OSS PyUVM tests.

Agent-agnostic: child sequences override ``body`` and dispatch their own item
type to whichever sequencer they were started on. Keeping the base minimal
lets the same base host i2c, reset, axi, gpio, ... future agents without
type leakage.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from pyuvm import uvm_sequence


class smc_base_test_seq(uvm_sequence):
    """Common SMC OSS sequence base."""

    def __init__(self, name: str = "smc_base_test_seq") -> None:
        super().__init__(name)
        # Populated by ``smc_base_test.start_seq`` before ``start``.
        self.cfg = None
        self.env = None

    @property
    def memory_model(self):
        assert self.cfg is not None, "sequence cfg is not initialized"
        return self.cfg.memory_model

    async def wait_fuse_sense_done(self, max_cycles: int = 200_000) -> None:
        """Block until warm-reset domain is released via fuse sense.

        ``SCRATCH_COLD_WARM_*`` (and other warm-reset CSRs) stay in reset until
        ``fuse_reset_n`` asserts, which follows ``fuse_sense_done``. Without this
        wait, early SEP_IN AXI accesses hang (~5 us into smoke) while sense is
        still running.
        """
        dut = cocotb.top
        clk = dut.clk_smc_i
        if not int(dut.tb_fuse_sense_done.value):
            for _ in range(max_cycles):
                await RisingEdge(clk)
                if int(dut.tb_fuse_sense_done.value):
                    break
            else:
                raise AssertionError(
                    f"tb_fuse_sense_done never asserted within {max_cycles} smc clocks"
                )
        # Pipe delay between sense_done and fuse_reset_n / warm domain release.
        await ClockCycles(clk, 20)

    async def body(self) -> None:
        raise NotImplementedError
