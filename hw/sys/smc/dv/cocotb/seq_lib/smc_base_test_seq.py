# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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
        ``rst_warm`` deasserts. That path is
        ``fuse_sense_done → fuse_reset_n (16-stage delayed o) → rst_warm sync``.
        Waiting only on ``tb_fuse_sense_done`` + a short settle is not enough —
        warm-domain AXI then hangs with no ready.
        """
        dut = cocotb.top
        clk = dut.clk_smc_i

        async def _wait_high(sig, name: str) -> None:
            if int(sig.value):
                return
            for _ in range(max_cycles):
                await RisingEdge(clk)
                if int(sig.value):
                    return
            raise AssertionError(f"{name} never asserted within {max_cycles} smc clocks")

        await _wait_high(dut.tb_fuse_sense_done, "tb_fuse_sense_done")
        # Prefer the delayed fuse_reset (matches CPU/mem-init pipe) when present.
        if hasattr(dut, "tb_fuse_reset_n"):
            await _wait_high(dut.tb_fuse_reset_n, "tb_fuse_reset_n")
        if hasattr(dut, "tb_rst_warm_smc_clk_n"):
            await _wait_high(dut.tb_rst_warm_smc_clk_n, "tb_rst_warm_smc_clk_n")
        else:
            # Fallback when the TB probes are absent.
            await ClockCycles(clk, 64)

    async def body(self) -> None:
        raise NotImplementedError
