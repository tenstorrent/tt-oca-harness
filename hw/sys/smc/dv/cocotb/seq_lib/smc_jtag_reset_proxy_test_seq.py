# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG-adjacent reset recovery proxy sequence."""

from __future__ import annotations

from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_base_test_seq import smc_base_test_seq
from .smc_csr_field_catalog import misc_wrap_reset

CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")
SCRATCH_COLD_2 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 2)
SCRATCH_PATTERN = 0x1A7A_0002
# Generated reset of the scratch data field, the value a taken reset restores.
SCRATCH_RESET = misc_wrap_reset("SCRATCH__SCRATCH__DATA_reset")

# Same bounds smc_flr_sanity_test_seq uses for the cool-reset handshake.
# smc_reset_ctrl de-glitches rst_cool_ni over 32 clk_ref_i samples
# (docs/SMC_VPLAN.adoc), so any hold shorter than that is silently rejected and
# no reset is taken at all.
COOL_ASSERT_BOUND_REF = 400
COOL_RECOVER_BOUND_REF = 4000


class smc_jtag_reset_proxy_test_seq(smc_base_test_seq):
    """Cool-reset recovery around safe CSRs; the CPU JTAG TAP proof runs in the test module."""

    def __init__(self, name: str = "smc_jtag_reset_proxy_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _reset_op(self, name: str, op: SmcResetOp) -> None:
        item = SmcResetItem(name)
        item.op = op
        await self.dispatch_reset(item)

    _SEND_KEYS = frozenset(
        [f"expect_{f}" for f in RESET_SAMPLE_FIELDS] + ["expect_left_stable", "timeout_ref_cycles"]
    )

    async def _wait_reset_state(self, label: str, bound: int, **expects) -> SmcResetItem:
        """Bounded WAIT_STATE handshake carrying exact expected reset levels.

        The expectations travel on the item, so a window that never matches
        fails in the scoreboard with the last observed state rather than being
        absorbed here ([TIMEOUT-MUST-FAIL] / [NO-BLIND-DELAY-SYNC]). Same guard
        as SmcResetSeqBase._send: a mistyped ``expect_*`` would otherwise become
        a silent non-check.
        """
        bad = set(expects) - self._SEND_KEYS
        assert not bad, f"unknown reset item keyword(s) {sorted(bad)} (typo = silent non-check)"
        item = SmcResetItem(label)
        item.op = SmcResetOp.WAIT_STATE
        item.timeout_ref_cycles = bound
        for field, value in expects.items():
            setattr(item, field, value)
        await self.dispatch_reset(item)
        return item

    async def body(self) -> None:
        await self._read("CHIP_CONFIG_VERSION_LO", CHIP_CONFIG_VERSION_LO, expected=0x0001_00A0)
        await self._write("SCRATCH_COLD_2", SCRATCH_COLD_2, SCRATCH_PATTERN)
        await self._read("SCRATCH_COLD_2", SCRATCH_COLD_2, expected=SCRATCH_PATTERN)

        # Hold rst_cool_ni low until the reset is observed taken, then release
        # it and wait for the observed release. A fixed hold is not usable here:
        # anything below smc_reset_ctrl's 32-sample de-glitch window is
        # rejected, no reset is taken, and the recovery reads below would
        # re-read CSRs that never went anywhere -- a DUT ignoring rst_cool_ni
        # entirely would look identical.
        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        await self._wait_reset_state(
            "cool_asserted",
            COOL_ASSERT_BOUND_REF,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        await self._reset_op("cool_rst_hi", SmcResetOp.COOL_RST_HI)
        await self._wait_reset_state(
            "cool_released",
            COOL_RECOVER_BOUND_REF,
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=1,
            expect_rst_primary_smc_clk_n=1,
            expect_rst_wdt_smc_clk_n=1,
        )
        # The warm domain the CSRs live in returns through the fuse/warm release
        # pipe; wait on that handshake before touching CSRs again.
        await self.wait_fuse_sense_done()

        # A taken cool reset restores the generated reset value, so the pattern
        # written before the reset must be gone: the pre-reset write and this
        # read straddle the reset, and a reset that never happened leaves
        # SCRATCH_PATTERN here and fails. smc_multi_reset_csr_persistence_test_seq
        # checks the same direction under CHK-COOL-RESET-CLEARS-WARM-SCRATCH.
        await self._read(
            "CHIP_CONFIG_VERSION_LO_RECOVERY", CHIP_CONFIG_VERSION_LO, expected=0x0001_00A0
        )
        await self._read("SCRATCH_COLD_2_CLEARED", SCRATCH_COLD_2, expected=SCRATCH_RESET)
        # The register is still writable after the reset. Writing the reset
        # value over a register that already reads it would prove nothing, so
        # write the pattern back, read it, then leave the register clean.
        await self._write("SCRATCH_COLD_2_REWRITE", SCRATCH_COLD_2, SCRATCH_PATTERN)
        await self._read("SCRATCH_COLD_2_REWRITE", SCRATCH_COLD_2, expected=SCRATCH_PATTERN)
        await self._write("SCRATCH_COLD_2_RESTORE", SCRATCH_COLD_2, SCRATCH_RESET)
        assert self.accesses == 8, (
            f"JTAG reset proxy access mismatch: issued {self.accesses}, expected 8"
        )
