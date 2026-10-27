# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""WDT_TIMEOUT written to 0 with no first-stage timeout leaves the second stage idle.

`cpu_ctrl.rdl` describes `WDT_TIMEOUT.data` as the cycle count at which the
second-stage watchdog timeout occurs, with no range and no meaning given to 0.
The second stage times the interval after a core's first-stage timeout, so
with no first-stage timeout raised a write of 0 must leave
`smc_wdt_second_timeout_o` low and the warm reset released.

`smc_cpu_ctrl_wrap.sv` reloads each core's stage-2 counter from WDT_TIMEOUT
while that core's first-stage timeout is low and flags the second timeout
whenever the counter reads 0, so a write of 0 raises the timeout on the next
clock and `smc_reset_ctrl.sv` folds it into the warm reset. The register block
sits on the primary reset, so the value survives the warm reset it causes and
only a non-zero write over the inbound port releases the domain.

The sequence samples the timeout pin and the warm reset after the write, then
writes the reset value back and waits for the warm domain to return before it
grades the samples, so the bench is recovered whichever way the leaf ends.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CHK = "CHK-WDT-TIMEOUT-ZERO-IDLE"
FUSE_SENSE_MAX_CYCLES = 200_000
SETTLE_CYCLES = 300
RELEASE_BOUND_CYCLES = 20_000


class smc_wdt_timeout_zero_idle_test_seq(SmcCsrSeq):
    """Write WDT_TIMEOUT=0 with the watchdog idle, sample, restore, then grade."""

    async def _first_level(self, sig, want: int, bound: int) -> int | None:
        """Cycles until ``sig`` reads ``want``, or None when it never does within ``bound``."""
        clk = cocotb.top.clk_smc_i
        for i in range(bound):
            await RisingEdge(clk)
            if sig.value.is_resolvable and int(sig.value) == want:
                return i + 1
        return None

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        wdt = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
        wdt_reset = cpu_ctrl_u32("CPU_CTRL__WDT_TIMEOUT__DATA_reset")

        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        await ClockCycles(clk, 16)

        await self.csr_read("WDT_TIMEOUT_BOOT", wdt, expected=wdt_reset)
        first_boot = int(dut.tb_wdt_first_timeout.value)
        assert first_boot == 0, f"first-stage timeout 0x{first_boot:x} raised before the write"
        assert int(dut.tb_wdt_second_timeout.value) == 0, "second timeout high before the write"
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 1, "warm reset asserted before the write"

        await self.csr_write("WDT_TIMEOUT_ZERO", wdt, 0)
        rise = await self._first_level(dut.tb_wdt_second_timeout, 1, SETTLE_CYCLES)
        fall = await self._first_level(dut.tb_rst_warm_smc_clk_n, 0, SETTLE_CYCLES)
        await ClockCycles(clk, SETTLE_CYCLES)
        first_after = int(dut.tb_wdt_first_timeout.value)
        second_after = int(dut.tb_wdt_second_timeout.value)
        warm_after = int(dut.tb_rst_warm_smc_clk_n.value)

        await self.csr_write("WDT_TIMEOUT_RESTORE", wdt, wdt_reset)
        released = await self._first_level(dut.tb_rst_warm_smc_clk_n, 1, RELEASE_BOUND_CYCLES)
        assert released is not None, (
            f"rst_warm_smc_clk_n still 0 {RELEASE_BOUND_CYCLES} cycles after WDT_TIMEOUT was "
            f"restored to 0x{wdt_reset:x}"
        )
        await ClockCycles(clk, SETTLE_CYCLES)
        await self.csr_read("WDT_TIMEOUT_RESTORE_RB", wdt, expected=wdt_reset)
        assert int(dut.tb_wdt_second_timeout.value) == 0, "second timeout high after the restore"

        assert first_after == 0, (
            f"first-stage timeout 0x{first_after:x} raised during the write under test"
        )
        samples = (
            f"second_timeout_o rose after {rise} cycles, rst_warm_smc_clk_n fell after {fall} "
            f"more cycles; {SETTLE_CYCLES} cycles after the write second_timeout_o={second_after} "
            f"rst_warm_smc_clk_n={warm_after}; released {released} cycles after the restore"
        )
        if rise is not None or fall is not None or second_after or not warm_after:
            raise AssertionError(
                f"{CHK} FAIL: WDT_TIMEOUT=0 with no first-stage timeout raised "
                f"smc_wdt_second_timeout_o and asserted the warm reset ({samples})"
            )
        cocotb.log.info(
            "%s PASS: WDT_TIMEOUT=0 with no first-stage timeout left smc_wdt_second_timeout_o "
            "low and the warm reset released (%s)",
            CHK,
            samples,
        )
