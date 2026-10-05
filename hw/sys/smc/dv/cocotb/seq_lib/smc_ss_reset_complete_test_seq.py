# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ss_reset_complete_i to CSR bits 0/31; SW SS_WARM_RESET_N to ss_reset_ctrl_o[0]."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SS_COMPLETE = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_RESET_COMPLETE_BASE_ADDR")
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

# SS_WARM_RESET_N's reset value comes from the generated reset_unit header, the
# same accessor smc_jtag_reset_ctrl_test_seq uses, so a narrowing of the field in
# the RDL rots this expectation instead of leaving a stale golden behind.
SS_WARM_RESET_VALUE = reset_unit_u32("RESET_UNIT__SS_WARM_RESET_N__RESET_N_N0_SCAN_reset")
SS_COMPLETE_ALL_ONE = 0xFFFFFFFF
SS_COMPLETE_DROP_0_31 = 0x7FFFFFFE
_CSR_BOUND = 64
_PIN_BOUND = 64
# Scratch RW pattern. SCRATCH_COLD_WARM_0 is `scratch.rdl` SCRATCH[0]
# (sw=rw, hw=na, reset 0x0) in the misc_wrap cold+warm scratch bank.
_SCRATCH_PAT = 0xA5A5_5A5A
_SCRATCH_RESET = 0x0


class smc_ss_reset_complete_test_seq(SmcCsrSeq):
    """Pin 1→drop bits 0/31→1 on CSR; SW warm bit 0 1→0→1 on SS0 pin."""

    def __init__(self, name: str = "smc_ss_reset_complete_test_seq") -> None:
        super().__init__(name)
        # Values captured for the evidence tokens and the testcase-level gate.
        #   * `idle_csr` / `drop_csr` / `restore_csr` come from `_await_csr`,
        #     which raises unless the value matches, so they hold the wanted
        #     constants; the fail-capable content is `_await_csr`'s expiry path.
        #   * `warm_pins` likewise comes from `_await_warm_pin`.
        #   * `warm_csr` holds three plain `csr_read` words with NO `expected=`;
        #     this sequence asserts only bit 0 of the asserted/released reads, so
        #     a full-word compare at testcase level covers the other 31 bits
        #     ([NO-ALWAYS-PASS-CHECKER]).
        self.idle_csr: int | None = None
        self.drop_csr: int | None = None
        self.restore_csr: int | None = None
        self.warm_csr: tuple[int, int, int] | None = None
        self.warm_pins: tuple[int, int, int] | None = None
        # label -> polls/cycles the matching wait actually consumed. This is the
        # varying measured quantity the tokens report.
        self.polls: dict[str, int] = {}

    async def _await_csr(self, want: int, label: str) -> int:
        """Poll until the CSR mirrors `want`, or raise on expiry.

        NOTE ON WHAT THIS PROVES: the returned value can only ever BE `want` --
        every other outcome raises. So a token that prints the return value is
        printing a constant. The fail-capable content is the expiry path, and
        the varying measured quantity is the poll count, recorded in
        `self.polls[label]` and reported in the evidence tokens.
        """
        last = None
        for polls in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_COMPLETE", SS_COMPLETE)
            if last == want:
                self.polls[label] = polls
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: SS_RESET_COMPLETE last=0x{last:x} want=0x{want:x} after {_CSR_BOUND} polls"
        )

    def _warm_pin(self, dut) -> int:
        pin = dut.tb_ss0_warm_reset_n
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on tb_ss0_warm_reset_n: {pin.value}")
        return int(pin.value) & 1

    async def _await_warm_pin(self, dut, want: int, label: str) -> int:
        """Wait for the pin to reach `want`, or raise on expiry.

        Same caveat as `_await_csr`: the return value is `want` by construction,
        so it is NOT an independently checked measurement. The cycle count is,
        and it is recorded in `self.polls[label]`.
        """
        last = -1
        for cycles in range(_PIN_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = self._warm_pin(dut)
            if last == want:
                self.polls[label] = cycles
                return last
        raise AssertionError(f"{label}: ss0 warm_reset_n stuck {last} want {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ss_reset_complete"), "tb_ss_reset_complete missing"
        assert hasattr(dut, "tb_ss0_warm_reset_n"), "tb_ss0_warm_reset_n missing"

        dut.tb_ss_reset_complete.value = SS_COMPLETE_ALL_ONE
        self.idle_csr = await self._await_csr(SS_COMPLETE_ALL_ONE, "IDLE")
        cocotb.log.info("CHK-SS-COMPLETE-IDLE: CSR=0x%x pin=all-1", self.idle_csr)

        dut.tb_ss_reset_complete.value = SS_COMPLETE_DROP_0_31
        self.drop_csr = await self._await_csr(SS_COMPLETE_DROP_0_31, "DROP")
        cocotb.log.info(
            "CHK-SS-COMPLETE-DROP: CSR=0x%x pin=0x%x bits 0 and 31 low",
            self.drop_csr,
            SS_COMPLETE_DROP_0_31,
        )

        dut.tb_ss_reset_complete.value = SS_COMPLETE_ALL_ONE
        self.restore_csr = await self._await_csr(SS_COMPLETE_ALL_ONE, "RESTORE")
        cocotb.log.info("CHK-SS-COMPLETE-RESTORE: CSR=0x%x pin=all-1", self.restore_csr)

        warm0 = await self.csr_read("SS_WARM_IDLE", SS_WARM)
        assert warm0 == SS_WARM_RESET_VALUE, (
            f"SS_WARM_RESET_N idle 0x{warm0:x} want the generated reset value "
            f"0x{SS_WARM_RESET_VALUE:x}"
        )
        pin0 = await self._await_warm_pin(dut, 1, "WARM_IDLE")
        await self.csr_write("SS_WARM_SS0_LO", SS_WARM, SS_WARM_RESET_VALUE & ~0x1)
        pin1 = await self._await_warm_pin(dut, 0, "WARM_ASSERT")
        warm1 = await self.csr_read("SS_WARM_ASSERTED", SS_WARM)
        assert (warm1 & 0x1) == 0, f"SS_WARM bit0 stuck 1: 0x{warm1:x}"
        await self.csr_write("SS_WARM_SS0_HI", SS_WARM, SS_WARM_RESET_VALUE)
        pin2 = await self._await_warm_pin(dut, 1, "WARM_RELEASE")
        warm2 = await self.csr_read("SS_WARM_RELEASED", SS_WARM)
        assert (warm2 & 0x1) == 1, f"SS_WARM bit0 stuck 0: 0x{warm2:x}"
        self.warm_csr = (warm0, warm1, warm2)
        self.warm_pins = (pin0, pin1, pin2)
        cocotb.log.info(
            "CHK-SS-WARM-SS0: pin %d→%d→%d (these are the WANTED values by "
            "construction -- _await_warm_pin raises unless matched; the "
            "fail-capable content is the bounded wait and the CSR compares) "
            "reached in %s/%s/%s clk_smc_i cycles; CSR=0x%x→0x%x→0x%x read "
            "without expected= and compared here and at testcase level",
            pin0,
            pin1,
            pin2,
            self.polls.get("WARM_IDLE"),
            self.polls.get("WARM_ASSERT"),
            self.polls.get("WARM_RELEASE"),
            warm0,
            warm1,
            warm2,
        )
        # SCRATCH_COLD_WARM_0 read/write/restore. This scenario drives no SMC
        # warm or cool reset -- the SW SS_WARM_RESET_N bit exercised above is
        # subsystem 0's OUTBOUND pin, not the SMC warm domain -- so no claim is
        # made here about reset clearing this register (that property is proven
        # by smc_jtag_reset_ctrl_test, which causes a real cool reset). What is
        # proven is that the register is a live sw=rw scratch cell.
        await self.csr_write("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, _SCRATCH_PAT)
        wrote = await self.csr_read(
            "SCRATCH_COLD_WARM_0_RB", SCRATCH_COLD_WARM_0, expected=_SCRATCH_PAT
        )
        await self.csr_write("SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0, _SCRATCH_RESET)
        restored = await self.csr_read(
            "SCRATCH_COLD_WARM_0_RESTORE_RB",
            SCRATCH_COLD_WARM_0,
            expected=_SCRATCH_RESET,
        )
        cocotb.log.info(
            "CHK-SS-COMPLETE-SCRATCH-RW: SCRATCH_COLD_WARM_0 took 0x%08x then "
            "0x%08x on write/readback (no SMC warm or cool reset occurs in this "
            "scenario, so no reset-clearing claim is made)",
            wrote,
            restored,
        )
