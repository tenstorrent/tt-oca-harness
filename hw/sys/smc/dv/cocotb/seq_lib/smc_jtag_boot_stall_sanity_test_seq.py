# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG override forces stall low while pad 57 is held (clears sticky)."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Live mux -> prim_sync3 (3) -> sticky flop (1). Fail-closed stay-low window.
_LOCKOUT_CYCLES = 16
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")


class smc_jtag_boot_stall_sanity_test_seq(SmcCsrSeq):
    """JTAG override releases sticky stall while pad 57 stays held."""

    def __init__(self, name: str = "smc_jtag_boot_stall_sanity_test_seq") -> None:
        super().__init__(name)
        self.held_ok = False
        self.override_ok = False
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
        clk = dut.clk_smc_i
        for cycle in range(_LOCKOUT_CYCLES):
            await RisingEdge(clk)
            if int(dut.tb_hold_cpu_boot.value) != 1:
                raise AssertionError(f"{label}: pad hold dropped at cycle {cycle}")
            if not dut.tb_gpio_pad57.value.is_resolvable:
                raise AssertionError(f"{label}: tb_gpio_pad57 unresolvable at {cycle}")
            if int(dut.tb_gpio_pad57.value) != 1:
                raise AssertionError(
                    f"{label}: pad57={int(dut.tb_gpio_pad57.value)} at {cycle}; hold not on pad"
                )
            if not dut.tb_boot_stall_combined_o.value.is_resolvable:
                raise AssertionError(f"{label}: combined unresolvable at {cycle}")
            if int(dut.tb_boot_stall_combined_o.value) != 0:
                raise AssertionError(
                    f"{label}: combined rose at cycle {cycle} while pad57 still held"
                )

    async def body(self) -> None:
        dut = cocotb.top
        # Stall holds fuse_reset_n; do not wait for the warm domain.

        assert int(dut.tb_hold_cpu_boot.value) == 1, (
            "+smc_hold_cpu_boot required so pad 57 is 1 when JTAG override fires"
        )
        await self._wait_stall(dut, 1, "HOLD")
        self.held_ok = True
        cocotb.log.info("CHK-JTAG-BOOT-STALL-HOLD: combined=1 before JTAG override")

        dut.tb_boot_stall_jtag_val_i.value = 0
        dut.tb_boot_stall_jtag_ovrd_i.value = 1
        await self._wait_stall(dut, 0, "JTAG_OVRD")
        assert int(dut.tb_hold_cpu_boot.value) == 1, "pad hold dropped; JTAG path not proven"
        self.override_ok = True
        cocotb.log.info(
            "CHK-JTAG-BOOT-STALL-OVRD: combined=0 with ovrd=1 val=0 while pad57 still held"
        )

        dut.tb_boot_stall_jtag_ovrd_i.value = 0
        await self._stay_low(dut, "LOCK")
        self.lockout_ok = True
        cocotb.log.info("CHK-JTAG-BOOT-STALL-LOCK: combined stayed 0 after ovrd drop")
        await self.wait_fuse_sense_done()
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info(
            "CHK-JTAG-BOOT-STALL-WARM: SCRATCH_COLD_WARM_0=0x%x after JTAG release", got
        )
        cocotb.log.info(
            "CHK-JTAG-BOOT-STALL-BASIC: hold=%s ovrd=%s lock=%s",
            self.held_ok,
            self.override_ok,
            self.lockout_ok,
        )
