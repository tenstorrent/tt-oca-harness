# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""COLD vs COLD_WARM scratch across tb_sep_wdt_reset_n. No Force."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiGroupItem, SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import ALL_ONES_WORD, SmcCsrSeq
from .smc_reset_seq_base import SmcResetSeqBase

SCRATCH_COLD_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
COLD_PAT = 0xDEADBEEF
WARM_PAT = 0xCAFEB0BA
# WDT reset into the COLD_WARM domain is async; 16 SMC clocks cover the
# wrapper sync into rst_wdt. Proof is the post-pulse CSR handshake, not this
# pulse width alone.
_WDT_PULSE = 16
_CSR_BOUND = 64

# ---------------------------------------------------------------------------
# RESET_UNIT SS_* / ISOLATE_REQ sweep.
#
# All of these are `sw = rw; hw = r` with reset 0x0 in
# hw/sys/smc/regs/blocks/reset_unit/reset_unit.rdl -- plain software-owned
# storage whose only consumer is a TOP-LEVEL OUTPUT, so no write feeds back into
# the DUT and resets the bench:
#   * `ss_reset_ctrl_o [31:0]` (smc.sv) reaches tb_top as
#     `ss_reset_ctrl [31:0]` and only `ss_reset_ctrl[0].warm_reset_n` is
#     tapped out.
#   * `isolate_req_o [31:0]` (smc.sv) goes straight to the observation port
#     `tb_isolate_req_o`.
# Neither loops back into the DUT, so driving them perturbs nothing.
#
_SS_SWEEP_REGS = (
    "SS_CONFIG",
    "SS_COLD_RESET_N",
    "SS_CONFIG_HOLD",
    "SS_SRAM_HOLD",
    "SS_CRITICAL_HOLD",
    "SS_DEBUG_HOLD",
    "SS_FORCE_TO_REF_CLK",
)
# The inclusion criterion is "`sw = rw`, reset 0x0, reversible, and no path back
# into the bench". The `external` keyword only says where a register lives:
# `SS_CONFIG` @0x20 and `SS_COLD_RESET_N` @0x40 are `external` in the
# reset_unit.rdl addrmap and meet the criterion. Each register outside the
# tuple above fails it for a reason of its own:
#
#   * `SS_WARM_RESET_N` @0x44 -- `sw = rw; hw = r` like the swept seven, but its
#     reset is 0xFFFFFFFF (reset_unit.rdl), so the sweep's `expected=0`
#     reset leg does not apply, and `ss_reset_ctrl[0].warm_reset_n` is tapped
#     into the bench in `tb_top.sv`, so driving it perturbs the run.
#   * `SS_RESET_COMPLETE` @0x60 -- `sw = r; hw = w` (reset_unit.rdl):
#     software cannot write it, so a write/readback expectation does not exist.
#   * `SYNC_REG` @0xA8 -- `sw = rw; hw = r`, but a single bit `sync[0:0]`
#     (reset_unit.rdl). A 1-bit register cannot carry the alternating
#     `_SS_PATTERN`, so it would need its own expectation rather than the
#     sweep's.
#   * `SS_CONFIG_LOCK` @0x24 and `SS_COLD_RESET_LOCK` @0x70 -- `onwrite = woset`,
#     irreversible until a cold reset, and the latter removes SS_COLD_RESET_N's
#     writability, so the sweep's restore leg cannot apply;
#     `smc_reset_unit_lock_test_seq` covers them.
#   * `ISOLATE_REQ_VIS` @0xC0 -- `sw = r; hw = w` pin visibility
#     (reset_unit.rdl).
#   * `ISOLATE_REQ_SMC_REG` @0xB8 -- hardware-set, software-cleared, and one bit
#     wide. `smc_cool_reset_wrap.sv` sets it to 1 when
#     `cfg_flr_pf_active` asserts and clears it to 0 on ANY software write with
#     a non-zero bit enable, regardless of the data; its read data is
#     `{31'b0, isolate_req_smc_reg}`. A write/readback probe therefore reads
#     0x0 by specification. Proving the set half needs an FLR event, which is
#     out of this testcase's scope.
#   * `ISOLATE_REQ_PINEN_REG` @0xB4 and `ISOLATE_REQ_SMCEN_REG` @0xBC -- plain
#     `sw = rw` storage, but both OR into the pin this testcase observes:
#     `smc_cool_reset_wrap.sv` computes `isolate_req_o[i] =
#     isolate_req_reg[i] | (isolate_req_pinen_reg[i] & isolate_req_pin) |
#     (isolate_req_smcen_reg[i] & isolate_req_smc_reg)`. Leaving them at reset
#     keeps the `tb_isolate_req_o` observation below attributable to
#     `ISOLATE_REQ_REG` alone.
#
# `ISOLATE_REQ_REG` @0xB0 keeps its own dedicated check below because its value
# is observable on a DUT output pin, a property independent of all of the above.
# Alternating bits so a stuck-at-0 or stuck-at-1 register cannot read it back.
_SS_PATTERN = 0x5A5A_A5A5
# ISOLATE_REQ_REG gets a stronger check than write/readback: its value is
# observable on a DUT output pin, so the CSR-to-pin path is checked too. A
# single bit is driven, and one that is not bit 0, so a tie-off or an
# off-by-one on the bus would not satisfy it.
ISOLATE_REQ_BIT = 5

# ---------------------------------------------------------------------------
# Software-owned storage legs (testcase contract SMC_COV_B1_001, S1-S11).
#
# Every expected value below comes from hw/sys/smc/regs/gen/adoc/blocks/
# reset_unit.adoc (each register 31:0 RW, reset 0x0, locks RW1S reset 0x0),
# doc/trm/src/register-field-access.adoc (RW reads return the written value)
# and hw/sys/smc/doc/clk_rst.adoc (the register interface is reset by the
# primary reset; the isolation registers and FLR count storage are reset only
# by the stable cold reset and survive a cool reset).
OKAY = 0


def _ru(reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{reg}_BASE_ADDR")


SS_CONFIG_LOCK = _ru("SS_CONFIG_LOCK")
SS_COLD_RESET_LOCK = _ru("SS_COLD_RESET_LOCK")
HOLD_REGS = ("SS_CONFIG_HOLD", "SS_SRAM_HOLD", "SS_CRITICAL_HOLD", "SS_DEBUG_HOLD")
FORCE_REG = "SS_FORCE_TO_REF_CLK"
ISOLATE_REG = "ISOLATE_REQ_REG"
FLR_REGS = ("ISOLATE_REQ_FLR_COUNTER_VALUE", "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")
FLR_SHORT = {
    "ISOLATE_REQ_FLR_COUNTER_VALUE": "COUNTER",
    "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE": "RESET_COUNTER",
}
RESET_VALUE_REGS = (*HOLD_REGS, FORCE_REG, ISOLATE_REG, *FLR_REGS)
# 0xFFFFFFFF, 0x00000000, then 1<<b for b = 0..31.
PATTERN_WORDS = (ALL_ONES_WORD, 0x0000_0000, *(1 << b for b in range(32)))
HOLD_PRELOAD = (0x1111_1111, 0x2222_2222, 0x4444_4444, 0x8888_8888)
FLR_B2B_FIRST = 0x0000_00A5
FLR_B2B_SECOND = 0x0000_005A
COOL_ISOLATE = 0x0000_0020
COOL_FLR = {
    "ISOLATE_REQ_FLR_COUNTER_VALUE": 0x0000_1234,
    "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE": 0x0000_4321,
}
COOL_HOLD_CONTROL = 0x0000_C0DE
# One AXI ID for both back-to-back writes, so AXI same-ID ordering makes the
# second write the last one the register sees.
FLR_B2B_AXI_ID = 0
# TB bounds: ceilings for the waits, never the checked quantity. The cool assert
# bound exceeds the 32-sample cool de-glitch window plus the output
# synchronizers; the release bound covers the primary reset release.
FLR_B2B_BOUND_NS = 10_000
COOL_ASSERT_BOUND_REF = 400
COOL_RELEASE_BOUND_REF = 4000
RU_ANSWER_BOUND_NS = 10_000
FENCE_TERMS = (
    "LOCKS-CLEAR",
    "RESET-VALUES",
    "HOLD-PATTERN",
    "HOLD-ISOLATION",
    "FORCE-PATTERN",
    "ISOLATE-PATTERN",
    "FLR-PATTERN",
    "FLR-B2B",
    "COOL-RESET",
    "POST-COOL-READ",
)


class smc_reset_unit_sanity_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """COLD persists across SEP WDT reset; COLD_WARM does not; reset-unit storage."""

    ASSERT_BOUND_REF_CYCLES = COOL_ASSERT_BOUND_REF
    RELEASE_BOUND_REF_CYCLES = COOL_RELEASE_BOUND_REF

    def __init__(self, name: str = "smc_reset_unit_sanity_test_seq") -> None:
        super().__init__(name)
        # Names of the registers the SS_* sweep actually drove, published for
        # the testcase module's zero-activity guard.
        self.ss_regs_swept: list[str] = []
        # (term, sim time in ps, compares) per CHK-NONVAC fence term, in the
        # order the terms completed.
        self.fence: list[tuple[str, int, int]] = []
        self._reset_values: dict[str, int] = {}
        self._waits: list[str] = []

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

    def _term(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} completed with 0 compares"
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count))
        cocotb.log.info("STEP %s: done at %d ps with %d compares", term, now, count)

    async def _rd(self, name: str, addr: int, expected: int) -> int:
        """Read carrying an exact value and an OKAY response expectation."""
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        item.expected_resp = OKAY
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, f"{name} @ 0x{addr:x}: RRESP={item.resp_code}"
        got = item.rdata & ALL_ONES_WORD
        assert got == expected, f"{name} @ 0x{addr:x}: read 0x{got:08x} want 0x{expected:08x}"
        return got

    def _wr_item(self, name: str, addr: int, data: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.expected_resp = OKAY
        return item

    async def _wr(self, name: str, addr: int, data: int) -> None:
        item = self._wr_item(name, addr, data)
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == OKAY, f"{name} @ 0x{addr:x}: BRESP={item.resp_code}"

    async def _pattern_sweep(self, reg: str) -> int:
        """Write every PATTERN_WORDS word to `reg`, reading back after each."""
        addr = _ru(reg)
        n = 0
        for word in PATTERN_WORDS:
            await self._wr(f"{reg}_PAT_{word:08x}", addr, word)
            await self._rd(f"{reg}_PAT_{word:08x}_RB", addr, word)
            n += 1
        return n

    async def _s1_locks_clear(self) -> None:
        cfg = await self._rd("SS_CONFIG_LOCK_S1", SS_CONFIG_LOCK, 0)
        cold = await self._rd("SS_COLD_RESET_LOCK_S1", SS_COLD_RESET_LOCK, 0)
        cocotb.log.info(
            "STEP S1: SS_CONFIG_LOCK=0x%08x SS_COLD_RESET_LOCK=0x%08x, no lock can mask a write",
            cfg,
            cold,
        )
        self._term("LOCKS-CLEAR", 2)

    async def _s2_reset_values(self) -> None:
        for reg in RESET_VALUE_REGS:
            self._reset_values[reg] = await self._rd(f"{reg}_S2_RESET", _ru(reg), 0)
        v = self._reset_values
        cocotb.log.info(
            "CHK-RU-HOLD-RESET: SS_CONFIG_HOLD=0x%08x SS_SRAM_HOLD=0x%08x "
            "SS_CRITICAL_HOLD=0x%08x SS_DEBUG_HOLD=0x%08x resp=OKAY x4",
            *(v[r] for r in HOLD_REGS),
        )
        self._term("RESET-VALUES", len(RESET_VALUE_REGS))

    async def _s3_hold_patterns(self) -> None:
        n = 0
        for reg in HOLD_REGS:
            n += await self._pattern_sweep(reg)
        want = len(HOLD_REGS) * len(PATTERN_WORDS)
        assert n == want == 136, f"hold pattern compares {n}, want 136"
        cocotb.log.info(
            "CHK-RU-HOLD-PATTERN: %d regs x %d words, %d/%d readback==written, resp OKAY",
            len(HOLD_REGS),
            len(PATTERN_WORDS),
            n,
            want,
        )
        self._term("HOLD-PATTERN", n)

    async def _s4_hold_isolation(self) -> None:
        for reg, word in zip(HOLD_REGS, HOLD_PRELOAD):
            await self._wr(f"{reg}_PRELOAD", _ru(reg), word)
        neighbours = 0
        targets = 0
        for reg, word in zip(HOLD_REGS, HOLD_PRELOAD):
            comp = ~word & ALL_ONES_WORD
            await self._wr(f"{reg}_COMPLEMENT", _ru(reg), comp)
            for other in HOLD_REGS:
                if other == reg:
                    await self._rd(f"{reg}_COMPLEMENT_RB", _ru(reg), comp)
                    targets += 1
                else:
                    preload = HOLD_PRELOAD[HOLD_REGS.index(other)]
                    await self._rd(f"{other}_UNDER_{reg}", _ru(other), preload)
                    neighbours += 1
            await self._wr(f"{reg}_REPRELOAD", _ru(reg), word)
            await self._rd(f"{reg}_REPRELOAD_RB", _ru(reg), word)
        assert neighbours == 12 and targets == 4, (neighbours, targets)
        for reg in HOLD_REGS:
            await self._wr(f"{reg}_RESTORE", _ru(reg), 0)
            await self._rd(f"{reg}_RESTORE_RB", _ru(reg), 0)
        cocotb.log.info(
            "CHK-RU-HOLD-ISOLATION: %d writes, %d/12 neighbours unchanged, %d/4 targets==complement",
            len(HOLD_REGS),
            neighbours,
            targets,
        )
        self._term("HOLD-ISOLATION", neighbours + targets)

    async def _s5_force_patterns(self) -> None:
        n = await self._pattern_sweep(FORCE_REG)
        assert n == 34, f"force pattern compares {n}, want 34"
        await self._wr(f"{FORCE_REG}_RESTORE", _ru(FORCE_REG), 0)
        await self._rd(f"{FORCE_REG}_RESTORE_RB", _ru(FORCE_REG), 0)
        cocotb.log.info(
            "CHK-RU-FORCE-STORAGE: reset=0x%08x, %d/34 readback==written, resp OKAY",
            self._reset_values[FORCE_REG],
            n,
        )
        self._term("FORCE-PATTERN", n)

    async def _s6_isolate_patterns(self) -> None:
        n = await self._pattern_sweep(ISOLATE_REG)
        assert n == 34, f"isolate pattern compares {n}, want 34"
        await self._wr(f"{ISOLATE_REG}_RESTORE", _ru(ISOLATE_REG), 0)
        await self._rd(f"{ISOLATE_REG}_RESTORE_RB", _ru(ISOLATE_REG), 0)
        cocotb.log.info(
            "CHK-RU-ISOLATE-STORAGE: reset=0x%08x, %d/34 readback==written, resp OKAY",
            self._reset_values[ISOLATE_REG],
            n,
        )
        self._term("ISOLATE-PATTERN", n)

    async def _s7_flr_patterns(self) -> None:
        n = 0
        for reg in FLR_REGS:
            n += await self._pattern_sweep(reg)
            await self._wr(f"{reg}_RESTORE", _ru(reg), 0)
            await self._rd(f"{reg}_RESTORE_RB", _ru(reg), 0)
        assert n == 68, f"FLR pattern compares {n}, want 68"
        cocotb.log.info(
            "CHK-RU-FLR-STORAGE: COUNTER reset=0x%08x RESET_COUNTER reset=0x%08x, "
            "%d/68 readback==written",
            self._reset_values[FLR_REGS[0]],
            self._reset_values[FLR_REGS[1]],
            n,
        )
        self._term("FLR-PATTERN", n)

    async def _s8_flr_b2b(self, dut) -> None:
        rbs: dict[str, int] = {}
        lat: dict[str, int] = {}
        okays = 0
        for reg in FLR_REGS:
            addr = _ru(reg)
            first = self._wr_item(f"{reg}_B2B_A5", addr, FLR_B2B_FIRST)
            second = self._wr_item(f"{reg}_B2B_5A", addr, FLR_B2B_SECOND)
            for w in (first, second):
                w.axi_id = FLR_B2B_AXI_ID
                w.timeout_ns = FLR_B2B_BOUND_NS
            group = SmcSysAxiGroupItem(f"{reg}_b2b_group", [first, second])
            cycles = 0
            done = False

            async def _count() -> None:
                nonlocal cycles
                while not done:
                    await RisingEdge(dut.clk_smc_i)
                    cycles += 1

            counter = cocotb.start_soon(_count())
            await _OneShot(group, f"{reg}_b2b_os").start(self.env.sys_axi_agent.sequencer)
            done = True
            counter.kill()
            self.accesses += 2
            for w in (first, second):
                assert not w.timed_out, (
                    f"{w.get_name()}: no BRESP within {FLR_B2B_BOUND_NS} ns; last state "
                    f"resp={w.resp_code} ok={w.resp_ok}"
                )
                assert w.resp_code == OKAY, f"{w.get_name()}: BRESP={w.resp_code}"
                okays += 1
            self._waits.append(
                f"{reg} back-to-back write responses: bound={FLR_B2B_BOUND_NS} ns per write, "
                f"fail path=driver AssertionError naming the address, last state "
                f"BRESP=({first.resp_code},{second.resp_code}) after {cycles} smc cycles"
            )
            lat[reg] = cycles
            rbs[reg] = await self._rd(f"{reg}_B2B_RB", addr, FLR_B2B_SECOND)
        assert okays == 4, f"back-to-back BRESP OKAY count {okays}, want 4"
        cocotb.log.info(
            "CHK-RU-FLR-B2B: COUNTER rb=0x%08x RESET_COUNTER rb=0x%08x, %d/4 BRESP OKAY, "
            "latencies=COUNTER:%d RESET_COUNTER:%d smc cycles (both writes in flight; "
            "measured, no spec bound)",
            rbs[FLR_REGS[0]],
            rbs[FLR_REGS[1]],
            okays,
            lat[FLR_REGS[0]],
            lat[FLR_REGS[1]],
        )
        self._term("FLR-B2B", okays + 2)

    async def _s9_cool_reset(self, dut) -> dict[str, int]:
        pre = {ISOLATE_REG: COOL_ISOLATE, **COOL_FLR, "SS_CONFIG_HOLD": COOL_HOLD_CONTROL}
        n = 0
        for reg, word in pre.items():
            await self._wr(f"{reg}_PRE_COOL", _ru(reg), word)
            await self._rd(f"{reg}_PRE_COOL_RB", _ru(reg), word)
            n += 1
        flr = dut.tb_cfg_flr_pf_active.value
        assert flr.is_resolvable and int(flr) == 0, (
            f"cfg_flr_pf_active_i={flr}; the cool reset would not be attributable to rst_cool_ni"
        )
        assert int(dut.rst_cold_ni.value) == 1, "rst_cold_ni must be inactive for the cool pulse"
        await self._send(SmcResetOp.COOL_RST_LO, item_name="ru_cool_rst_lo")
        asserted = await self._wait_state(
            "RU_COOL_ASSERTED",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=1,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        cold_pin = dut.rst_cold_ni.value
        assert cold_pin.is_resolvable and int(cold_pin) == 1, (
            f"rst_cold_ni={cold_pin} during the cool pulse; the cold reset must stay inactive"
        )
        await self._send(SmcResetOp.COOL_RST_HI, item_name="ru_cool_rst_hi")
        released = await self._wait_released("RU_COOL_RELEASED")
        await self.wait_fuse_sense_done()
        self._waits.append(
            f"cool assert: bound={COOL_ASSERT_BOUND_REF} ref cycles, fail path=scoreboard "
            f"WAIT_STATE expiry with last state, matched after {asserted.wait_ref_cycles}"
        )
        self._waits.append(
            f"cool release: bound={COOL_RELEASE_BOUND_REF} ref cycles, fail path=scoreboard "
            f"WAIT_STATE expiry with last state, matched after {released.wait_ref_cycles}"
        )
        vis = SmcSysAxiItem("rd_RU_ANSWER_AFTER_COOL")
        vis.op = SmcSysAxiOp.READ
        vis.addr = _ru("ISOLATE_REQ_VIS")
        vis.length = 4
        vis.expected_resp = OKAY
        vis.timeout_ns = RU_ANSWER_BOUND_NS
        t0 = int(get_sim_time("ns"))
        await self.start_item(vis)
        await self.finish_item(vis)
        self.accesses += 1
        assert not vis.timed_out and vis.resp_code == OKAY, (
            f"reset-unit register interface did not answer within {RU_ANSWER_BOUND_NS} ns "
            f"after the cool reset: last state resp={vis.resp_code} timed_out={vis.timed_out}"
        )
        self._waits.append(
            f"reset-unit answer after cool reset: bound={RU_ANSWER_BOUND_NS} ns, fail "
            f"path=driver AssertionError naming the address, answered OKAY after "
            f"{int(get_sim_time('ns')) - t0} ns"
        )
        self._term("COOL-RESET", n + 1)
        return pre

    async def _s10_post_cool(self, pre: dict[str, int]) -> None:
        hold = await self._rd("SS_CONFIG_HOLD_POST_COOL", _ru("SS_CONFIG_HOLD"), 0)
        iso = await self._rd(f"{ISOLATE_REG}_POST_COOL", _ru(ISOLATE_REG), COOL_ISOLATE)
        flr = {}
        for reg in FLR_REGS:
            flr[reg] = await self._rd(f"{reg}_POST_COOL", _ru(reg), COOL_FLR[reg])
        cocotb.log.info(
            "CHK-RU-ISOLATE-COOL-RETAIN: SS_CONFIG_HOLD 0x%08x->0x%08x (primary reset seen), "
            "ISOLATE_REQ_REG 0x%08x->0x%08x",
            pre["SS_CONFIG_HOLD"],
            hold,
            pre[ISOLATE_REG],
            iso,
        )
        cocotb.log.info(
            "CHK-RU-FLR-COOL-RETAIN: COUNTER 0x%08x->0x%08x RESET_COUNTER 0x%08x->0x%08x "
            "(control cleared)",
            pre[FLR_REGS[0]],
            flr[FLR_REGS[0]],
            pre[FLR_REGS[1]],
            flr[FLR_REGS[1]],
        )
        for reg in (ISOLATE_REG, *FLR_REGS):
            await self._wr(f"{reg}_POST_COOL_RESTORE", _ru(reg), 0)
            await self._rd(f"{reg}_POST_COOL_RESTORE_RB", _ru(reg), 0)
        self._term("POST-COOL-READ", 2 + len(FLR_REGS))

    def _check_fence(self) -> None:
        names = tuple(t for t, _, _ in self.fence)
        assert names == FENCE_TERMS, f"fence terms {names}, want {FENCE_TERMS}"
        times = [t for _, t, _ in self.fence]
        assert all(a < b for a, b in zip(times, times[1:])), f"fence out of order: {self.fence}"
        assert all(c > 0 for _, _, c in self.fence), f"zero-count fence term: {self.fence}"
        cocotb.log.info(
            "CHK-NONVAC: %s (counts and times per term: %s)",
            " < ".join(FENCE_TERMS),
            ", ".join(f"{t}={c}@{ps}ps" for t, ps, c in self.fence),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, 0 expired: %s",
            len(self._waits),
            " | ".join(self._waits),
        )

    async def _ss_sweep(self, dut) -> None:
        """Write/readback/restore the software-owned RESET_UNIT SS_* registers.

        Run AFTER the SEP WDT pulse: the pulse clears the COLD_WARM
        domain, so values written before it would not survive to be read back.
        """
        for reg in _SS_SWEEP_REGS:
            addr = smc_addr(f"SMC_TOP_SMC_RESET_UNIT_{reg}_BASE_ADDR")
            await self.csr_read(f"{reg}_RESET", addr, expected=0)
            await self.csr_write(f"{reg}_WR", addr, _SS_PATTERN)
            await self.csr_read(f"{reg}_RB", addr, expected=_SS_PATTERN)
            await self.csr_write(f"{reg}_RESTORE", addr, 0)
            await self.csr_read(f"{reg}_RESTORE_RB", addr, expected=0)
            self.ss_regs_swept.append(reg)

        # ISOLATE_REQ_REG: CSR value must also appear on the DUT output pin.
        iso = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
        assert hasattr(dut, "tb_isolate_req_o"), (
            "tb_isolate_req_o missing from the TB top: the CSR-to-pin half of "
            "the ISOLATE_REQ_REG check has no observation port"
        )
        pin_idle = int(dut.tb_isolate_req_o.value)
        assert pin_idle == 0, (
            f"isolate_req_o is already 0x{pin_idle:x} before ISOLATE_REQ_REG "
            f"was written; the pin check below could not be attributed to the "
            f"CSR write"
        )
        await self.csr_read("ISOLATE_REQ_REG_RESET", iso, expected=0)
        await self.csr_write("ISOLATE_REQ_REG_WR", iso, 1 << ISOLATE_REQ_BIT)
        await self.csr_read("ISOLATE_REQ_REG_RB", iso, expected=1 << ISOLATE_REQ_BIT)
        await RisingEdge(dut.clk_smc_i)
        pin_set = int(dut.tb_isolate_req_o.value)
        assert pin_set == (1 << ISOLATE_REQ_BIT), (
            f"ISOLATE_REQ_REG read back 0x{1 << ISOLATE_REQ_BIT:x} but the DUT "
            f"output isolate_req_o is 0x{pin_set:x}; the CSR stores the value "
            f"without driving the pin it is specified to drive"
        )
        await self.csr_write("ISOLATE_REQ_REG_RESTORE", iso, 0)
        await self.csr_read("ISOLATE_REQ_REG_RESTORE_RB", iso, expected=0)
        await RisingEdge(dut.clk_smc_i)
        pin_clr = int(dut.tb_isolate_req_o.value)
        assert pin_clr == 0, (
            f"isolate_req_o stayed 0x{pin_clr:x} after ISOLATE_REQ_REG was restored to 0"
        )
        cocotb.log.info(
            "CHK-RESET-UNIT-SS-SWEEP: %d software-owned SS_*/ISOLATE_REQ "
            "registers took 0x%08x on a reset-read / write / readback / restore "
            "cycle; ISOLATE_REQ_REG additionally drove isolate_req_o 0x%x -> "
            "0x%x -> 0x%x, so the CSR-to-pin path is checked and not just the "
            "storage. Every RESET_UNIT register outside this set is named in "
            "the module header with the criterion that excludes it",
            len(_SS_SWEEP_REGS),
            _SS_PATTERN,
            pin_idle,
            pin_set,
            pin_clr,
        )

    async def _await_warm_cleared(self, dut, label: str) -> int:
        last = None
        for _ in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_WARM", SCRATCH_COLD_WARM_0)
            if last == 0:
                return last
            await RisingEdge(dut.clk_smc_i)
        raise AssertionError(f"{label}: COLD_WARM last=0x{last:x} want=0 after {_CSR_BOUND} polls")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert int(dut.tb_sep_wdt_reset_n.value) == 1, "SEP WDT reset must idle high"
        await self._s1_locks_clear()

        await self.csr_write("SCRATCH_COLD_0", SCRATCH_COLD_0, COLD_PAT)
        await self.csr_write("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, WARM_PAT)
        got_c = await self.csr_read("SCRATCH_COLD_0_PRE", SCRATCH_COLD_0, expected=COLD_PAT)
        got_w = await self.csr_read(
            "SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0, expected=WARM_PAT
        )
        cocotb.log.info(
            "CHK-RESET-UNIT-PRE: COLD=0x%x COLD_WARM=0x%x before SEP WDT pulse",
            got_c,
            got_w,
        )

        dut.tb_sep_wdt_reset_n.value = 0
        for _ in range(_WDT_PULSE):
            await RisingEdge(dut.clk_smc_i)
        dut.tb_sep_wdt_reset_n.value = 1

        got_w = await self._await_warm_cleared(dut, "POST")
        got_c = await self.csr_read("SCRATCH_COLD_0_POST", SCRATCH_COLD_0, expected=COLD_PAT)
        cocotb.log.info(
            "CHK-RESET-UNIT-WDT: COLD stayed 0x%x COLD_WARM cleared to 0x%x",
            got_c,
            got_w,
        )
        # S2 reads the eight storage registers before the SS_* sweep writes any
        # of them, so each reset value is a first access after cold reset.
        await self._s2_reset_values()
        await self._ss_sweep(dut)
        # The two per-leg tokens above carry the evidence; the fail-capable legs
        # are `csr_read(expected=...)`, `_await_warm_cleared`'s expiry, and
        # `_ss_sweep`'s CSR-to-pin check on `tb_isolate_req_o`
        # ([NO-ALWAYS-PASS-CHECKER]).
        sb = self.env.scoreboard
        checks_before = sb.sys_axi_value_checks_seen
        await self._s3_hold_patterns()
        await self._s4_hold_isolation()
        await self._s5_force_patterns()
        await self._s6_isolate_patterns()
        await self._s7_flr_patterns()
        await self._s8_flr_b2b(dut)
        pre = await self._s9_cool_reset(dut)
        await self._s10_post_cool(pre)
        scored = sb.sys_axi_value_checks_seen - checks_before
        assert scored >= 136 + 16 + 34 + 34 + 68 + 2, (
            f"scoreboard value-checked {scored} storage reads, fewer than the S3-S8 legs issue"
        )
        self._check_fence()
