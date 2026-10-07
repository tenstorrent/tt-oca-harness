# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad57 stall then JTAG override. Sticky cannot re-assert until primary reset."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Live mux -> prim_sync3 (3) -> sticky flop (1). Fail-closed stay window.
_LOCKOUT_CYCLES = 16
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")


class smc_mixed_boot_stall_test_seq(SmcCsrSeq):
    """GPIO stall gates fuse; JTAG ovrd val=0 releases; val=1 does not re-stall."""

    def __init__(self, name: str = "smc_mixed_boot_stall_test_seq") -> None:
        super().__init__(name)
        self.gpio_gate_ok = False
        self.ovrd_release_ok = False
        self.val1_lockout_ok = False
        self.ovrd_drop_ok = False

    async def _wait_pin(self, sig, expect: int, label: str, bound: int) -> None:
        clk = cocotb.top.clk_smc_i
        last = None
        for _ in range(bound):
            if sig.value.is_resolvable and int(sig.value) == expect:
                return
            last = sig.value
            await RisingEdge(clk)
        raise AssertionError(f"{label}: last={last} want={expect} after {bound} smc clocks")

    async def _stay(self, dut, combined_expect: int, label: str) -> None:
        clk = dut.clk_smc_i
        for cycle in range(_LOCKOUT_CYCLES):
            await RisingEdge(clk)
            if int(dut.tb_hold_cpu_boot.value) != 1:
                raise AssertionError(f"{label}: pad hold dropped at {cycle}")
            if not dut.tb_gpio_pad57.value.is_resolvable:
                raise AssertionError(f"{label}: pad57 unresolvable at {cycle}")
            if int(dut.tb_gpio_pad57.value) != 1:
                raise AssertionError(f"{label}: pad57 not high at {cycle}")
            if not dut.tb_boot_stall_combined_o.value.is_resolvable:
                raise AssertionError(f"{label}: combined unresolvable at {cycle}")
            if int(dut.tb_boot_stall_combined_o.value) != combined_expect:
                raise AssertionError(
                    f"{label}: combined={int(dut.tb_boot_stall_combined_o.value)} "
                    f"want={combined_expect} at {cycle}"
                )

    async def body(self) -> None:
        dut = cocotb.top
        assert int(dut.tb_hold_cpu_boot.value) == 1, (
            "+smc_hold_cpu_boot required so pad 57 is held from t=0"
        )

        await self._wait_pin(dut.tb_boot_stall_combined_o, 1, "HOLD_COMBINED", 2000)
        assert int(dut.tb_boot_stall_jtag_ovrd_i.value) == 0, (
            "JTAG ovrd active; GPIO-alone not proven"
        )
        self.gpio_gate_ok = True
        cocotb.log.info(
            "CHK-MIXED-BOOT-STALL-GPIO: combined=1 ovrd=0 pad57 held (GPIO-alone stall)"
        )

        dut.tb_boot_stall_jtag_val_i.value = 0
        dut.tb_boot_stall_jtag_ovrd_i.value = 1
        await self._wait_pin(dut.tb_boot_stall_combined_o, 0, "OVRD_COMBINED", 2000)
        assert int(dut.tb_hold_cpu_boot.value) == 1, "pad hold dropped during JTAG ovrd"
        self.ovrd_release_ok = True
        cocotb.log.info("CHK-MIXED-BOOT-STALL-OVRD: ovrd=1 val=0 combined=0 pad57 held")

        # With pad57 held, the GPIO stall holds combined at 1 before the release
        # and the sticky lockout holds it at 0 after it, so val=1 cannot be shown
        # to re-assert a stall: this leg checks the lockout only.
        dut.tb_boot_stall_jtag_val_i.value = 1
        await self._stay(dut, combined_expect=0, label="VAL1")
        self.val1_lockout_ok = True
        cocotb.log.info(
            "CHK-MIXED-BOOT-STALL-VAL1: after the ovrd release, driving val=1 for "
            "%d cycles did not re-stall -- the release is sticky. This does NOT "
            "claim val=1 asserts a stall; that direction is unreachable here.",
            _LOCKOUT_CYCLES,
        )

        dut.tb_boot_stall_jtag_val_i.value = 0
        dut.tb_boot_stall_jtag_ovrd_i.value = 0
        await self._stay(dut, combined_expect=0, label="DROP")
        self.ovrd_drop_ok = True
        cocotb.log.info("CHK-MIXED-BOOT-STALL-DROP: combined stayed 0 after ovrd drop")

        await self.wait_fuse_sense_done()
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-MIXED-BOOT-STALL-WARM: SCRATCH_COLD_WARM_0=0x%x", got)
        cocotb.log.info(
            "CHK-MIXED-BOOT-STALL-BASIC: gpio=%s ovrd=%s val1=%s drop=%s",
            self.gpio_gate_ok,
            self.ovrd_release_ok,
            self.val1_lockout_ok,
            self.ovrd_drop_ok,
        )
