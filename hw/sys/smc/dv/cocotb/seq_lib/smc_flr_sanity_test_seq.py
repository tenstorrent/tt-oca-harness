# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_flr_sanity_test.

Scope: this test verifies the *downstream* half of an FLR
recovery only -- the cool reset itself and the CSR path across it -- and drives
it from the ``rst_cool_ni`` pin. It does NOT exercise the PCIe FLR request path.

The FLR trigger path (``cfg_flr_pf_active_i`` -> isolate-req CSR -> FLR delay /
hold counters -> ``rst_cool_no``) is a real, available TB stimulus
(``tb_top.sv:143`` ``tb_cfg_flr_pf_active``, wired at ``tb_top.sv:1244``) and is
covered by the enrolled sibling ``smc_cool_reset_from_pcie_test``
(``seq_lib/smc_cool_reset_from_pcie_test_seq.py``). To keep the
attribution exact, this sequence asserts ``tb_cfg_flr_pf_active`` is inactive
while it drives its own pin-cool pulse, so the observed cool reset can only have
come from ``rst_cool_ni``.

What this sequence proves: CSR access before the pulse, assert/release of cool
reset, reset stability, and SEP_IN AXI CSR-path recovery afterwards.

The cool pulse has two independent FAIL-ONs that the stimulus reached the
DUT, so RTL that ignores ``rst_cool_ni`` fails instead of coasting to the
post-release checks ([NO-ALWAYS-PASS-CHECKER]):

* mid-assert: a bounded ``WAIT_STATE`` on ``rst_primary_ref/smc == 0`` while the
  cold-stable path stays released (``clk_rst.adoc``: cool reset is a
  primary-level reset). It also fixes the stimulus itself -- ``smc_reset_ctrl``
  de-glitches ``rst_cool_ni`` over 32 ``clk_ref_i`` samples, so a fixed hold
  shorter than the de-glitch window is silently rejected and no reset is taken.
  Holding the pin low until the reset is *observed* cannot be too short.
* post-release: ``SCRATCH_COLD_WARM_0`` is read *before* being rewritten and
  must equal its mapped reset value, not the pattern written before the pulse --
  cool reaches the warm reset domain this register lives in. The following
  write/read-back is the positive control that the CSR path is alive again.

Both waits are bounded and raise with the last observed state on expiry
([NO-BLIND-DELAY-SYNC] / [TIMEOUT-MUST-FAIL]); the proof path has no fixed
settle.
"""

from __future__ import annotations

import cocotb
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_field_catalog import catalog_entry
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

# Addresses and expected defaults both come from the generated PeakRDL map via
# smc_csr_field_catalog, which cross-checks the driven address against the
# cataloged symbol ([ADDRESS-FROM-AUTHORITATIVE-MAP]).
CHIP_CONFIG_VERSION_LO = catalog_entry(
    "CHIP_CONFIG_VERSION_LO",
    smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"),
    writable=False,
)
SCRATCH_COLD_WARM_0 = catalog_entry(
    "SCRATCH_COLD_WARM_0",
    smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0),
    writable=True,
)
SCRATCH_PATTERN = 0xF1A0_0001

# clk_ref_i edges. The assert bound must exceed smc_reset_ctrl's 32-sample cool
# de-glitch window; the recovery bound covers cool release plus the warm/fuse
# re-release pipe. Ceilings only -- never the checked quantity.
COOL_ASSERT_BOUND_REF = 400
COOL_RECOVER_BOUND_REF = 4000


EXPECTED_ACCESSES = 8
# Reads carrying an exact expected value; the scoreboard bumps
# `sys_axi_value_checks_seen` only after such a compare has passed, which makes
# it the fail-capable floor (unlike a self-issued access count).
EXPECTED_VALUE_CHECKS = 5


class smc_flr_sanity_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Pin-cool reset + CSR recovery sanity (FLR trigger path: see docstring).

    Reset items come from ``SmcResetSeqBase``, whose ``expect_*`` keyword guard
    rejects a mistyped expectation. Only the dispatch is local: this sequence
    runs on the SEP_IN AXI sequencer, so its reset items are handed to the reset
    agent's sequencer via ``dispatch_reset``.
    """

    # Ceilings only, never the checked quantity (see the constants above).
    ASSERT_BOUND_REF_CYCLES = COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COOL_RECOVER_BOUND_REF

    def __init__(self, name: str = "smc_flr_sanity_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcResetItem] = []
        self.dispatch_reset = None

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        """Reset items travel on the reset agent's sequencer, not ours."""
        await self.dispatch_reset(item)

    def _assert_flr_pin_idle(self, label: str) -> None:
        """The cool reset under test must be attributable to ``rst_cool_ni``.

        ``cfg_flr_pf_active_i`` is the other cool-reset request source in this
        TB; if it were active the observed cool reset could have come from the
        FLR path instead of the pin this test drives.
        """
        dut = cocotb.top
        assert hasattr(dut, "tb_cfg_flr_pf_active"), "tb_cfg_flr_pf_active missing"
        value = dut.tb_cfg_flr_pf_active.value
        assert value.is_resolvable, f"{label}: tb_cfg_flr_pf_active is X/Z"
        assert int(value) == 0, (
            f"{label}: cfg_flr_pf_active_i={int(value)}; the cool reset would "
            f"not be attributable to the rst_cool_ni pulse this test drives"
        )

    async def _reset_op(self, name: str, op: SmcResetOp) -> None:
        await self._send(op, item_name=name)

    async def _wait_reset_state(self, name: str, bound: int, **expects) -> SmcResetItem:
        """Bounded reset handshake; the scoreboard raises on expiry.

        Keyword validation and dispatch come from ``SmcResetSeqBase._send``.
        """
        return await self._wait_state(name, bound=bound, **expects)

    async def _sample_reset(self, name: str) -> SmcResetItem:
        item = await self._send(SmcResetOp.SAMPLE, item_name=name)
        self.samples.append(item)
        return item

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_BASELINE",
            CHIP_CONFIG_VERSION_LO.addr,
            expected=CHIP_CONFIG_VERSION_LO.expected,
        )
        await self.csr_write("SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0.addr, SCRATCH_PATTERN)
        await self.csr_read(
            "SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0.addr, expected=SCRATCH_PATTERN
        )

        self._assert_flr_pin_idle("pre cool pulse")
        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        # Hold rst_cool_ni low until the reset is really taken (mid-assert
        # FAIL-ON), never for a fixed count below the de-glitch window.
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
        # The warm domain the CSRs live in comes back through the fuse/warm
        # release pipe; wait on that handshake before touching CSRs again.
        await self.wait_fuse_sense_done()
        await self._sample_reset("post_cool_reset")

        await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_RECOVERY",
            CHIP_CONFIG_VERSION_LO.addr,
            expected=CHIP_CONFIG_VERSION_LO.expected,
        )
        # Cool-effect compare, before any rewrite: the pre-cool pattern must be
        # gone and the mapped reset value back.
        await self.csr_read(
            "SCRATCH_COLD_WARM_0_POST_COOL",
            SCRATCH_COLD_WARM_0.addr,
            expected=SCRATCH_COLD_WARM_0.expected,
        )
        # Positive control for that negative-looking compare: the same register
        # is provably writable/readable after the cool recovery, so the reset
        # value above is a real reset, not a dead CSR path
        # ([NEGATIVE-NEEDS-POSITIVE-CONTROL]).
        await self.csr_write(
            "SCRATCH_COLD_WARM_0_POST_COOL_RW", SCRATCH_COLD_WARM_0.addr, SCRATCH_PATTERN
        )
        await self.csr_read(
            "SCRATCH_COLD_WARM_0_POST_COOL_RW", SCRATCH_COLD_WARM_0.addr, expected=SCRATCH_PATTERN
        )
        await self.csr_write(
            "SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0.addr, SCRATCH_COLD_WARM_0.expected
        )

        for s in self.samples:
            assert s.resolvable, f"unresolved FLR sample: {s.get_name()}"
            assert s.powergood_stable == 1, f"powergood unstable at {s.get_name()}"
            assert s.rst_primary_ref_clk_n == 1, f"primary ref reset asserted at {s.get_name()}"
            assert s.rst_primary_smc_clk_n == 1, f"primary smc reset asserted at {s.get_name()}"
            assert s.rst_wdt_smc_clk_n == 1, f"wdt reset asserted at {s.get_name()}"
        self._assert_flr_pin_idle("post cool recovery")
        # Loop integrity + scoreboard cross-check: the scoreboard must have
        # checked at least as many SYS AXI items as this sequence issued, which
        # the sequence's own counter cannot see (a no-response raises in the
        # AXI driver). The fail-capable value proof is the floor below.
        self.assert_all_reachable(EXPECTED_ACCESSES, "FLR sanity CSR sweep")
        sb = self.env.scoreboard
        # Fail-capable floor: the scoreboard books a value check only after an
        # exact rdata compare has passed, so a leg that lost its `expected`
        # fails here instead of counting as an access.
        assert sb.sys_axi_value_checks_seen >= EXPECTED_VALUE_CHECKS, (
            f"expected {EXPECTED_VALUE_CHECKS} value-checked SEP_IN AXI reads "
            f"(baseline RO, pre-cool readback, post-cool RO, post-cool reset "
            f"value, post-cool readback), scoreboard saw "
            f"{sb.sys_axi_value_checks_seen}"
        )
        # The cool pulse must have been proven at both ends, not merely driven.
        assert sb.reset_wait_checks_seen >= 2, (
            "expected the cool assert and release handshakes to be checked, "
            f"scoreboard saw {sb.reset_wait_checks_seen}"
        )
