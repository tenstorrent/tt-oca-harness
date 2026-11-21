# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI single write and read-back through one bridge's System Bus Access."""

from __future__ import annotations

from env.dtp_types import JTAG2AXI_TARGETS

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq


class dtp_jtag2axi_single_write_read_test_seq(dtp_jtag2axi_base_test_seq):
    """Write a seeded word and its neighbour through ``target``, then read the first back."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_single_write_read_test_seq",
        *,
        target: str = "smc_axi",
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        if target not in JTAG2AXI_TARGETS:
            raise ValueError(f"unknown JTAG2AXI target {target!r}")
        self.target = target

    def bus_ledger_target(self) -> str | None:
        return self.target

    async def body(self) -> None:
        self.log_banner(f"{self.target} single write-read")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng(f"{self.target}_single_wr_rd")
        addr = self.random_target_addr(self.target, rng)
        rdata, data = await self.write_neighbour_then_read(
            self.target, addr, rng, context="single_wr_rd"
        )
        self.log_summary(
            f"{self.target} single write-read complete",
            addr=f"0x{addr:x}",
            data=f"0x{data:x}",
            rdata=f"0x{rdata:x}",
        )
