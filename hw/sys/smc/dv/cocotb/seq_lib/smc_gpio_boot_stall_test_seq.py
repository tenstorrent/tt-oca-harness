# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad 57 boot-stall. Requires +smc_hold_cpu_boot. Sticky cannot re-assert until primary reset."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_pad_table import BOOT_STALL_PAD as _BOOT_STALL_PAD

# Live mux -> prim_sync3 (3) -> sticky flop (1). Window is fail-closed: a
# faulty re-assert would have reached tb_boot_stall_combined_o by then.
_LOCKOUT_CYCLES = 16
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")


class smc_gpio_boot_stall_test_seq(SmcCsrSeq):
    """Pad-57 hold from reset, release, sticky-lockout."""

    def __init__(self, name: str = "smc_gpio_boot_stall_test_seq") -> None:
        super().__init__(name)
        self.held_ok = False
        self.release_ok = False
        self.lockout_ok = False

    @staticmethod
    def _stall(dut) -> int:
        assert dut.tb_boot_stall_combined_o.value.is_resolvable, (
            "tb_boot_stall_combined_o unresolvable"
        )
        return int(dut.tb_boot_stall_combined_o.value)

    async def _wait_stall(self, dut, expect: int, label: str) -> None:
        clk = dut.clk_smc_i
        for _ in range(2000):
            if dut.tb_boot_stall_combined_o.value.is_resolvable:
                if int(dut.tb_boot_stall_combined_o.value) == expect:
                    return
            await RisingEdge(clk)
        raise AssertionError(
            f"{label}: tb_boot_stall_combined_o!={expect} last={dut.tb_boot_stall_combined_o.value}"
        )

    async def _stay_low(self, dut, label: str) -> None:
        """Pad 57 must be high and combined must stay 0 for the lockout window."""
        clk = dut.clk_smc_i
        for cycle in range(_LOCKOUT_CYCLES):
            await RisingEdge(clk)
            if not dut.tb_gpio_pad57.value.is_resolvable:
                raise AssertionError(f"{label}: tb_gpio_pad57 unresolvable at {cycle}")
            pad = int(dut.tb_gpio_pad57.value)
            if pad != 1:
                raise AssertionError(
                    f"{label}: pad57={pad} at cycle {cycle}; re-drive did not land"
                )
            if not dut.tb_boot_stall_combined_o.value.is_resolvable:
                raise AssertionError(f"{label}: combined unresolvable at {cycle}")
            if int(dut.tb_boot_stall_combined_o.value) != 0:
                raise AssertionError(f"{label}: combined rose at cycle {cycle} while pad57=1")

    async def body(self) -> None:
        dut = cocotb.top
        # Stall holds fuse_reset_n (smc_peripherals fuse_reset_stalled_n), so
        # wait_fuse_sense_done would time out. Combined/sticky is observable
        # without the warm CSR domain.

        assert int(dut.tb_hold_cpu_boot.value) == 1, (
            "+smc_hold_cpu_boot must hold pad 57 from t=0 (sticky already released otherwise)"
        )
        await self._wait_stall(dut, 1, "HOLD")
        self.held_ok = True
        cocotb.log.info("CHK-GPIO-BOOT-STALL-HOLD: combined=1 while pad57 held")

        dut.tb_hold_cpu_boot.value = 0
        await self._wait_stall(dut, 0, "RELEASE")
        self.release_ok = True
        cocotb.log.info("CHK-GPIO-BOOT-STALL-REL: combined=0 after pad57 release")

        # Re-drive pad 57 high: sticky must stay 0 until next primary reset.
        dut.tb_gpio_ext_drive_en.value = 1 << _BOOT_STALL_PAD
        dut.tb_gpio_ext_drive_value.value = 1 << _BOOT_STALL_PAD
        await self._stay_low(dut, "LOCK")
        self.lockout_ok = True
        dut.tb_gpio_ext_drive_en.value = 0
        dut.tb_gpio_ext_drive_value.value = 0
        cocotb.log.info("CHK-GPIO-BOOT-STALL-LOCK: combined stayed 0 on pad57 re-assert")
        # Warm-domain CSR is gated while stall holds fuse_reset_n. After release
        # it must complete with the RDL reset value (not hang, not X).
        await self.wait_fuse_sense_done()
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-GPIO-BOOT-STALL-WARM: SCRATCH_COLD_WARM_0=0x%x after release", got)
        cocotb.log.info(
            "CHK-GPIO-BOOT-STALL-BASIC: hold=%s rel=%s lock=%s",
            self.held_ok,
            self.release_ok,
            self.lockout_ok,
        )
