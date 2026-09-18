# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OSS SMU Tier A: alias-remap manager scope (FAB_SMC_018 subset).

SEP=1 honest scope (no sep_in / no Force):
  S3  J2A programs alias region[0], writes via alias window, proves remapped
      SPM consumer readback (jtag manager path through smc_alias_remap_wrap).
  S1  not covered: DMA data_accel observe needs DMA bring-up.
  S2  not covered: Log Engine observe needs log_engine stimulus.
  S4  not covered: smc_alias_remap_wrap has no cpu_ext manager port.
  S5  not covered: alias-then-filter ordering is not provable on this bench.

The remapped target is proven by SPM consumer readback (same address math)
rather than by a hierarchical AW watch on axi_to_input_mux_req.*.
"""

from __future__ import annotations

import cocotb
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr, smc_indexed_addr
from seq_lib.smu_jtag_helpers import (
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
)

ADDR_MASK56 = (1 << 56) - 1
PAGE_MASK = ADDR_MASK56 & ~0xFFF
ATTRS_VALID = 1 << 63

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
PROGRAMMED_ALIAS_INPUT = 0xC050_0000
ALIAS_SIZE = 0x1000
ALIAS_END = PROGRAMMED_ALIAS_INPUT + ALIAS_SIZE
ALIAS_TARGET_SPM = SPM_BASE + 0xA000

_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_END = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"

JTAG_ISSUE = PROGRAMMED_ALIAS_INPUT + 0x300
JTAG_WDATA = 0x0180_CAFE
EXPECTED_REMAPPED = ALIAS_TARGET_SPM + (JTAG_ISSUE - PROGRAMMED_ALIAS_INPUT)

DEFERRED_S1_TEXT = (
    "SMCF-ALIAS-REMAP-SCOPE.S1 (dma.alias_remapped) "
    "NOT-REACHABLE-AT-THIS-LEVEL on the wrapper without DMA bring-up + "
    "data_accel AW observe. Do not invent J2A substitute for DMA manager."
)
DEFERRED_S2_TEXT = (
    "SMCF-ALIAS-REMAP-SCOPE.S2 (log_engine.alias_remapped) "
    "NOT-REACHABLE-AT-THIS-LEVEL on the wrapper without Log Engine stimulus + "
    "log AR observe."
)
DEFERRED_S4_TEXT = (
    "SMCF-ALIAS-REMAP-SCOPE.S4 (cpu_ext.alias_remapped) deferred "
    "NOT-REACHABLE-AT-THIS-LEVEL. smc_alias_remap_wrap has no "
    "cpu_ext manager port on this bench."
)
DEFERRED_S5_TEXT = (
    "INT-SMCF-ALIAS-THEN-FILTER deferred NOT-REACHABLE-AT-THIS-LEVEL "
    "Alias-then-filter ordering at outbound filter not provable "
    "on this bench."
)


def _region_attrs(offset_delta: int, *, valid: bool) -> int:
    val = offset_delta & PAGE_MASK
    if valid:
        val |= ATTRS_VALID
    return val


class smu_axi_alias_remap_manager_scope_test_seq:
    """Alias-remap S3 over J2A on a live SPM consumer; S1/S2/S4/S5 logged as not reachable."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.s3_ok = False
        self.s1_deferred = False
        self.s2_deferred = False
        self.s4_deferred = False
        self.s5_deferred = False

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _j2a_wr(self, jtag, addr: int, data: int, name: str) -> None:
        st, _ = await jtag2axi_single_write(jtag, addr, data, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A WR {name} @0x{addr:08x} status={st}")
        self._log(f"J2A WR {name} @0x{addr:08x} data=0x{data:x}")

    async def _j2a_rd(self, jtag, addr: int, name: str) -> int:
        st, rdata = await jtag2axi_single_read(jtag, addr, require_complete=True)
        if st != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A RD {name} @0x{addr:08x} status={st}")
        return int(rdata)

    async def _program_alias_region(
        self, jtag, *, region_start: int, region_end: int, target_base: int
    ) -> int:
        offset_delta = (target_base - region_start) & ADDR_MASK56
        start_val = region_start & PAGE_MASK
        end_val = region_end & PAGE_MASK
        attrs_val = _region_attrs(offset_delta, valid=True)
        start_a = smc_indexed_addr(_START, 0)
        end_a = smc_indexed_addr(_END, 0)
        attrs_a = smc_indexed_addr(_ATTRS, 0)
        await self._j2a_wr(jtag, attrs_a, 0, "ALIAS0_ATTRS_CLR")
        await self._j2a_wr(jtag, start_a, start_val, "ALIAS0_START")
        await self._j2a_wr(jtag, end_a, end_val, "ALIAS0_END")
        await self._j2a_wr(jtag, attrs_a, attrs_val, "ALIAS0_ATTRS")
        rb_s = await self._j2a_rd(jtag, start_a, "ALIAS0_START_RB")
        rb_e = await self._j2a_rd(jtag, end_a, "ALIAS0_END_RB")
        rb_a = await self._j2a_rd(jtag, attrs_a, "ALIAS0_ATTRS_RB")
        if (rb_s & PAGE_MASK) != start_val:
            raise AssertionError(f"START rb 0x{rb_s:x} want 0x{start_val:x}")
        if (rb_e & PAGE_MASK) != end_val:
            raise AssertionError(f"END rb 0x{rb_e:x} want 0x{end_val:x}")
        if (rb_a & (PAGE_MASK | ATTRS_VALID)) != attrs_val:
            raise AssertionError(f"ATTRS rb 0x{rb_a:x} want 0x{attrs_val:x}")
        self._log(
            f"alias_remap[0]: [0x{region_start:x},0x{region_end:x}) -> "
            f"base 0x{target_base:x} offset=0x{offset_delta & ADDR_MASK56:x}"
        )
        return attrs_val

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)

        idcode = await jtag.read_idcode()
        if idcode != 0x1:
            raise AssertionError(f"IDCODE want 0x1 got 0x{idcode:08x}")
        sb.expect_eq("CHK-ALIAS-REMAP-J2A-READY", idcode, 0x1)

        if not (PROGRAMMED_ALIAS_INPUT >= SPM_BASE + 0x100000 or ALIAS_END <= SPM_BASE):
            raise AssertionError(
                f"alias window [0x{PROGRAMMED_ALIAS_INPUT:x},0x{ALIAS_END:x}) "
                f"overlaps SPM base 0x{SPM_BASE:x}"
            )

        await self._program_alias_region(
            jtag,
            region_start=PROGRAMMED_ALIAS_INPUT,
            region_end=ALIAS_END,
            target_base=ALIAS_TARGET_SPM,
        )

        # Clear target SPM word first (identity address; not in alias window).
        await self._j2a_wr(jtag, EXPECTED_REMAPPED, 0, "S3_SPM_CLR")
        clr = await self._j2a_rd(jtag, EXPECTED_REMAPPED, "S3_SPM_CLR_RB")
        if (clr & 0xFFFF_FFFF) != 0:
            raise AssertionError(f"SPM clear failed got=0x{clr:x}")

        # S3: write through alias window; prove remapped SPM consumer.
        await self._j2a_wr(jtag, JTAG_ISSUE, JTAG_WDATA, "S3_ALIAS_WR")
        got = await self._j2a_rd(jtag, EXPECTED_REMAPPED, "S3_SPM_RB")
        if (got & 0xFFFF_FFFF) != (JTAG_WDATA & 0xFFFF_FFFF):
            raise AssertionError(
                f"S3 remapped SPM mismatch got=0x{got:x} want=0x{JTAG_WDATA:x} "
                f"issue=0x{JTAG_ISSUE:x} target=0x{EXPECTED_REMAPPED:x}"
            )
        # Alias window itself must not retain a separate copy when remapped.
        # Reading the issue address via J2A also remaps → same SPM word.
        alias_rb = await self._j2a_rd(jtag, JTAG_ISSUE, "S3_ALIAS_RB")
        if (alias_rb & 0xFFFF_FFFF) != (JTAG_WDATA & 0xFFFF_FFFF):
            raise AssertionError(f"S3 alias readback 0x{alias_rb:x} want 0x{JTAG_WDATA:x}")

        self.s3_ok = True
        self._log(
            "CHK-ALIAS-REMAP-SCOPE-S3: jtag2axi.alias_remapped=1 "
            f"issue=0x{JTAG_ISSUE:x} remapped=0x{EXPECTED_REMAPPED:x} "
            "proof=SPM_consumer"
        )
        sb.expect_eq("CHK-ALIAS-REMAP-SCOPE-S3", got & 0xFFFF_FFFF, JTAG_WDATA)

        self._log(f"DEFERRED-NOTE(S1): {DEFERRED_S1_TEXT}")
        self.s1_deferred = True
        self._log(f"DEFERRED-NOTE(S2): {DEFERRED_S2_TEXT}")
        self.s2_deferred = True
        self._log(f"DEFERRED-NOTE(S4): {DEFERRED_S4_TEXT}")
        self.s4_deferred = True
        self._log(f"DEFERRED-NOTE(S5): {DEFERRED_S5_TEXT}")
        self.s5_deferred = True
