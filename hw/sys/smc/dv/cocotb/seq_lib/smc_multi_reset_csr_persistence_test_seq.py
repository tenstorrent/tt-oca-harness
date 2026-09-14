# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR behaviour across the public cool-reset control.

Addresses and expected defaults both come from the generated PeakRDL map via
``smc_csr_field_catalog`` (which also cross-checks the address that is actually
driven against the cataloged symbol).

Reset synchronization is handshake-based, never a fixed settle:
``smc_reset_ctrl`` de-glitches ``rst_cool_ni`` over ``RESET_DEGLITCH_WIDTH``
``clk_ref_i`` samples, so the pin is held low until the DUT is *observed* to
enter cool reset (``rst_warm_smc_clk_n`` / ``rst_primary_smc_clk_no`` drop), and
released only until the same observables are back and the fuse-sense/warm
release pipe has completed. Both waits are bounded and fail on expiry.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_field_catalog import catalog_entry
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

SCRATCH_COLD_WARM_1 = smc_indexed_addr(
    "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 1
)
CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
PERSIST_PATTERN = 0xCAFE_0020

# clk_ref_i edges. Assert bound must exceed smc_reset_ctrl's 32-sample cool
# de-glitch window; the recovery bound covers cool release + warm re-release.
COOL_ASSERT_BOUND_REF = 400
COOL_RECOVER_BOUND_REF = 4000

# Stimulus shape of this sweep: 3 writes (pre-cool pattern, post-cool pattern,
# restore) each followed by a value-checked read-back, plus 3 stand-alone
# value-checked reads (baseline RO, recovery RO, post-cool warm reset value).
EXPECTED_ACCESSES = 9
EXPECTED_VALUE_CHECKED_READS = 6


class smc_multi_reset_csr_persistence_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Prove CSR reset-domain behaviour and CSR-path recovery across cool reset.

    Reset items (and the ``expect_*`` keyword guard, should a leg ever grow an
    expectation) come from ``SmcResetSeqBase``; only the dispatch is local,
    because this sequence runs on the SEP_IN AXI sequencer.
    """

    ASSERT_BOUND_REF_CYCLES = COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COOL_RECOVER_BOUND_REF

    def __init__(self, name: str = "smc_multi_reset_csr_persistence_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        """Reset items travel on the reset agent's sequencer, not ours."""
        await self.dispatch_reset(item)

    async def _reset_op(self, name: str, op: SmcResetOp) -> None:
        await self._send(op, item_name=name)

    async def _await_level(self, signal: str, want: int, bound: int, label: str) -> None:
        """Bounded poll on a top-level reset observable; expiry fails the test."""
        dut = cocotb.top
        sig = getattr(dut, signal)
        last: int | None = None
        for _ in range(bound):
            value = sig.value
            last = int(value) if value.is_resolvable else None
            if last == want:
                return
            await RisingEdge(dut.clk_ref_i)
        raise AssertionError(
            f"{label}: {signal} never reached {want} within {bound} clk_ref_i "
            f"edges (last={'X/Z' if last is None else last})"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        version = catalog_entry(
            "CHIP_CONFIG_VERSION_LO",
            CHIP_CONFIG_VERSION_LO,
            writable=False,
        )
        scratch = catalog_entry(
            "SCRATCH_COLD_WARM_1",
            SCRATCH_COLD_WARM_1,
            writable=True,
        )

        got = await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_BASELINE", version.addr, expected=version.expected
        )
        cocotb.log.info(
            "CHK-CSR-BASELINE-RO: %s @ 0x%08x read 0x%08x == its mapped default "
            "0x%08x before any reset stimulus",
            version.name,
            version.addr,
            got,
            version.expected,
        )

        await self.csr_write_readback("SCRATCH_COLD_WARM_1_PRE_COOL", scratch.addr, PERSIST_PATTERN)
        cocotb.log.info(
            "CHK-CSR-PRE-COOL-READBACK: %s @ 0x%08x wrote and read back "
            "0x%08x before the cool pulse",
            scratch.name,
            scratch.addr,
            PERSIST_PATTERN,
        )

        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        # Hold rst_cool_ni low until the reset is really taken: a fixed hold
        # shorter than the de-glitch window is silently rejected and nothing
        # downstream would reset at all.
        await self._await_level("rst_primary_smc_clk_no", 0, COOL_ASSERT_BOUND_REF, "COOL_ASSERT")
        await self._await_level(
            "tb_rst_warm_smc_clk_n", 0, COOL_ASSERT_BOUND_REF, "COOL_ASSERT_WARM"
        )
        cocotb.log.info(
            "CHK-COOL-RESET-ASSERTED: rst_cool_ni=0 de-glitched into "
            "rst_primary_smc_clk_no=0 and rst_warm_smc_clk_n=0 within "
            "%d clk_ref_i edges",
            COOL_ASSERT_BOUND_REF,
        )

        await self._reset_op("cool_rst_hi", SmcResetOp.COOL_RST_HI)
        await self._await_level("rst_primary_smc_clk_no", 1, COOL_RECOVER_BOUND_REF, "COOL_RELEASE")
        await self._await_level(
            "tb_rst_warm_smc_clk_n", 1, COOL_RECOVER_BOUND_REF, "COOL_RELEASE_WARM"
        )
        await self.wait_fuse_sense_done()
        cocotb.log.info(
            "CHK-COOL-RESET-RELEASED: rst_primary_smc_clk_no=1 and "
            "rst_warm_smc_clk_n=1 observed after rst_cool_ni=1 (bounded by "
            "%d clk_ref_i edges), fuse/warm release pipe complete",
            COOL_RECOVER_BOUND_REF,
        )

        got = await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_RECOVERY", version.addr, expected=version.expected
        )
        cocotb.log.info(
            "CHK-CSR-POST-COOL-RECOVERY: %s @ 0x%08x read 0x%08x, again its "
            "mapped default 0x%08x, so the SEP_IN AXI CSR path recovered from "
            "the cool reset",
            version.name,
            version.addr,
            got,
            version.expected,
        )

        got = await self.csr_read(
            "SCRATCH_COLD_WARM_1_POST_COOL", scratch.addr, expected=scratch.expected
        )
        cocotb.log.info(
            "CHK-COOL-RESET-CLEARS-WARM-SCRATCH: %s @ 0x%08x read 0x%08x "
            "(== its mapped reset value 0x%08x) instead of the pre-cool "
            "0x%08x — the cool pulse reached the warm reset domain this "
            "register lives in",
            scratch.name,
            scratch.addr,
            got,
            scratch.expected,
            PERSIST_PATTERN,
        )

        await self.csr_write_readback(
            "SCRATCH_COLD_WARM_1_POST_COOL_RW", scratch.addr, PERSIST_PATTERN
        )
        cocotb.log.info(
            "CHK-CSR-WRITABLE-AFTER-COOL: %s @ 0x%08x wrote and read back "
            "0x%08x after cool recovery",
            scratch.name,
            scratch.addr,
            PERSIST_PATTERN,
        )

        await self.csr_restore("SCRATCH_COLD_WARM_1", scratch.addr, data=scratch.expected)
        # Loop integrity + scoreboard cross-check: `assert_all_reachable`
        # requires the scoreboard to have checked at least as many SYS AXI items
        # as this sequence issued, which the sequence's own counter cannot see.
        # A no-response raises in the AXI driver, so no timeout count is
        # asserted here. The fail-capable value proof is the floor below.
        self.assert_all_reachable(EXPECTED_ACCESSES, "multi-reset CSR sweep")
        sb = self.env.scoreboard
        # Fail-capable floor: the scoreboard books a value check only after an
        # exact rdata compare passed, so a read that lost its `expected` fails
        # here instead of still counting as an access.
        assert sb.sys_axi_value_checks_seen >= EXPECTED_VALUE_CHECKED_READS, (
            f"expected {EXPECTED_VALUE_CHECKED_READS} value-checked SEP_IN AXI "
            f"reads, scoreboard saw {sb.sys_axi_value_checks_seen}"
        )
        # The token carries the run's measured counters (`sys_axi_value_checks_seen`
        # from the scoreboard, `accesses` from this sequence), not the module
        # constants ([EVIDENCE-TOKEN-CONDITIONAL]).
        value_checked = sb.sys_axi_value_checks_seen
        cocotb.log.info(
            "CHK-MULTI-RESET-CSR-SWEEP: %d SEP_IN AXI CSR accesses issued "
            "around one observed cool assert/release (>= %d required); the "
            "scoreboard measured %d value-checked reads (>= %d required, rdata "
            "compared against the generated map / written pattern) out of %d "
            "SYS AXI items it checked, each write proven by its read-back",
            self.accesses,
            EXPECTED_ACCESSES,
            value_checked,
            EXPECTED_VALUE_CHECKED_READS,
            sb.sys_axi_checks_seen,
        )
