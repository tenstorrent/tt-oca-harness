# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog COUNT enable conditions, COUNT write semantics, COUNT_HI read and FEED write.

Contract SMC_POWER_TIMER_WDT_010, anchor smc_wdt_count_feed_test.
Scenarios WDT-COUNT-WRITE.S1-S4, WDT-COUNT-ENABLE.S1-S5 and WDT-FEED.S1, S2, S4.
Sources wdt.rdl, smc-programming.adoc#watchdog, watchdog.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_ENALWAYS = 0x1000
WDT_ENALWAYS_COREAWAKE = 0x3000
WDT_COREAWAKE = 0x2000
FEED_WORD = 0x0D09F00D
FEED_NOT_WORD = 0x0D09F00C
COUNT_START = 0x0010_0000
ROLLOVER_START = 0x7FFF_FFF0
ROLLOVER_READS = 8

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
CORE1_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_N_N0_SCAN_bm")
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM
LEVEL_BOUND = 256
CORE1_BIT = 0b0010

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_CHECKERS = (
    "CHK-WDT-COUNT-ENABLE-MATRIX",
    "CHK-WDT-COUNT-WRITE",
    "CHK-WDT-COUNTHI-ZERO",
    "CHK-WDT-COUNT-ROLLOVER",
    "CHK-WDT-FEED-RESET",
    "CHK-WDT-FEED-NONMAGIC",
    "CHK-WDT-COREAWAKE",
)
_CHECKER_STEP = dict(zip(_CHECKERS, ("S4", "S5", "S6", "S7", "S8", "S9", "S10")))


def _hexes(reads: list[int]) -> str:
    return ",".join(f"0x{r:x}" for r in reads)


def _increasing(reads: list[int]) -> bool:
    return all(b > a for a, b in zip(reads, reads[1:]))


def _deltas(reads: list[int]) -> list[int]:
    return [b - a for a, b in zip(reads, reads[1:])]


class smc_wdt_count_feed_test_seq(SmcCsrSeq):
    """Drive watchdog 0 and watchdog 1 COUNT, CTRL and FEED over SEP_IN."""

    def __init__(self, name: str = "smc_wdt_count_feed_test_seq") -> None:
        super().__init__(name)
        self.completed = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _reg(self, core: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _wr(self, label: str, reg: str, data: int, core: int = 0) -> None:
        await self.csr_write(f"WDT{core}_KEY_{label}", self._reg(core, "KEY"), WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{core}_{reg}_{label}", self._reg(core, reg), data)

    async def _rd(self, label: str, reg: str, core: int = 0) -> int:
        return await self.csr_read(f"WDT{core}_{reg}_{label}", self._reg(core, reg))

    async def _window(self, label: str, n: int, core: int = 0) -> list[int]:
        return [await self._rd(f"{label}{i}", "COUNT", core) for i in range(n)]

    @staticmethod
    def _core1_reset_n() -> int:
        value = cocotb.top.tb_cpu_core_resets_n.value
        assert value.is_resolvable, f"tb_cpu_core_resets_n is not resolvable: {value}"
        return (int(value) & CORE1_BIT) >> 1

    async def _await_core1_reset_n(self, want: int, when: str) -> int:
        for rises in range(LEVEL_BOUND):
            if self._core1_reset_n() == want:
                return rises
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"tb_cpu_core_resets_n[1] did not read {want} within {LEVEL_BOUND} rises {when}; "
            f"last {self._core1_reset_n()}"
        )

    async def body(self) -> None:
        assert hasattr(cocotb.top, "tb_cpu_core_resets_n"), "tb_top has no tb_cpu_core_resets_n"

        # S1
        await self._wr("S1", "CTRL", 0)
        await self._wr("S1", "COUNT", COUNT_START)
        s1 = await self._window("S1_R", 3)
        s1_held = s1[0] == s1[1] == s1[2]
        self._mark_step("S1")

        # S2
        await self._wr("S2", "CTRL", WDT_ENALWAYS)
        s2 = await self._window("S2_R", 3)
        assert _increasing(s2), f"S2: COUNT not strictly increasing with wdogenalways: {s2}"
        self._mark_step("S2")

        # S3
        await self._wr("S3", "CTRL", WDT_ENALWAYS_COREAWAKE)
        s3 = await self._window("S3_R", 3)
        assert _increasing(s3), f"S3: COUNT not strictly increasing with both enables: {s3}"
        self._mark_step("S3")

        # S4
        await self._wr("S4", "CTRL", 0)
        s4 = await self._window("S4_R", 3)
        if s1_held:
            assert s4[0] == s4[1] == s4[2], (
                f"S4: COUNT moved after wdogenalways was cleared although S1 held: {s4} (S1 {s1})"
            )
        else:
            assert _increasing(s4), (
                f"S4: COUNT not increasing after wdogenalways was cleared although S1 counted: "
                f"{s4} (S1 {s1})"
            )
        self._mark_step("S4")
        self._log_chk(
            "CHK-WDT-COUNT-ENABLE-MATRIX",
            f"wdogenalways: reads {_hexes(s2)} strictly increasing; wdogenalways+wdogcoreawake: "
            f"reads {_hexes(s3)} strictly increasing (2 of 2 cells); both clear: reads "
            f"{_hexes(s1)} increase per read {_deltas(s1)} ({'held' if s1_held else 'counted'}, "
            f"SF-014 is not asserted); wdogenalways cleared: reads {_hexes(s4)} increase per "
            f"read {_deltas(s4)} matches the S1 behaviour",
        )

        # S5
        await self._wr("S5_EN", "CTRL", WDT_ENALWAYS)
        pre = await self._rd("S5_PRE", "COUNT")
        await self._wr("S5_100", "COUNT", 0x100)
        s5 = await self._window("S5_R", 3)
        allowance = max(b - a for a, b in zip(s5, s5[1:]))
        assert pre > 0x100 + 2 * allowance, (
            f"S5: vacuous leg, pre-write COUNT 0x{pre:x} not above 0x100 + 2 * {allowance}: {s5}"
        )
        assert s5[0] < pre, f"S5: first read 0x{s5[0]:x} not below pre-write COUNT 0x{pre:x}"
        assert all(r >= 0x100 for r in s5), f"S5: a COUNT read is below 0x100: {s5}"
        assert _increasing(s5), f"S5: COUNT not strictly increasing after the write: {s5}"
        await self._wr("S5_DIS", "CTRL", 0)
        await self._wr("S5_BIT31", "COUNT", 0x8000_0010)
        c31 = await self._rd("S5_BIT31_RB", "COUNT")
        assert not c31 >> 31, f"S5: COUNT bit 31 reads 1 after the 0x80000010 write: 0x{c31:x}"
        assert (c31 & 0x7FFF_FFFF) >= 0x10, f"S5: COUNT[30:0] 0x{c31:x} below 0x10"
        assert (c31 & 0x7FFF_FFFF) <= 0x10 + allowance, (
            f"S5: COUNT[30:0] 0x{c31:x} above 0x10 + allowance {allowance}"
        )
        self._mark_step("S5")
        self._log_chk(
            "CHK-WDT-COUNT-WRITE",
            f"COUNT=0x100 with wdogenalways: reads {_hexes(s5)} each >= 0x100 and strictly "
            f"increasing (first read minus written value {s5[0] - 0x100}, V or V+1 is SF-007), "
            f"pre-write 0x{pre:x} above first read 0x{s5[0]:x}, allowance {allowance}; "
            f"COUNT=0x80000010 both enables clear read 0x{c31:08x} with bit 31 = 0 and "
            f"bits 30:0 within 0x10..0x10+{allowance}",
        )

        # S6
        await self._wr("S6", "COUNT", 0x1234_5678)
        hi = await self._rd("S6_HI", "COUNT_HI")
        c6 = await self._rd("S6_COUNT", "COUNT")
        assert hi == 0, f"S6: COUNT_HI reads 0x{hi:x}, want 0"
        assert c6 != 0, "S6: COUNT reads 0 after the 0x12345678 write (no positive control)"
        self._mark_step("S6")
        self._log_chk(
            "CHK-WDT-COUNTHI-ZERO",
            f"COUNT_HI read 0x{hi:08x} while COUNT read 0x{c6:08x} after a write of 0x12345678 "
            f"(allowance {c6 - 0x1234_5678})",
        )

        # S7
        await self._wr("S7_EN", "CTRL", WDT_ENALWAYS)
        await self._wr("S7", "COUNT", ROLLOVER_START)
        s7 = await self._window("S7_R", ROLLOVER_READS)
        bit31 = [r for r in s7 if r >> 31]
        assert not bit31, f"S7: COUNT bit 31 read 1 in {_hexes(bit31)} (reads {_hexes(s7)})"
        below = next(((i, r) for i, r in enumerate(s7) if r < ROLLOVER_START), None)
        self._mark_step("S7")
        below_txt = (
            f"first read below 0x7ffffff0 is read {below[0]} = 0x{below[1]:x}"
            if below
            else "no read fell below 0x7ffffff0"
        )
        self._log_chk(
            "CHK-WDT-COUNT-ROLLOVER",
            f"{ROLLOVER_READS} reads from 0x7ffffff0: {_hexes(s7)}; bit 31 never read 1; "
            f"{below_txt} (the value after 0x7fffffff is SF-014 and is not asserted)",
        )

        # S8
        await self._wr("S8_COUNT", "COUNT", COUNT_START)
        await self._wr("S8_FEED", "FEED", FEED_WORD)
        s8 = await self._window("S8_R", 2)
        assert s8[0] < COUNT_START, f"S8: COUNT 0x{s8[0]:x} not below 0x100000 after the feed"
        assert s8[1] > s8[0], f"S8: second COUNT read 0x{s8[1]:x} not above first 0x{s8[0]:x}"
        self._mark_step("S8")
        self._log_chk(
            "CHK-WDT-FEED-RESET",
            f"COUNT=0x100000 then KEY and FEED=0x0d09f00d: reads {_hexes(s8)}; first below "
            f"0x100000 and second larger",
        )

        # S9
        await self._wr("S9_COUNT", "COUNT", COUNT_START)
        await self._wr("S9_FEED_C", "FEED", FEED_NOT_WORD)
        c9 = await self._rd("S9_COUNT_RB", "COUNT")
        key9 = await self._rd("S9_KEY_RB", "KEY")
        assert c9 >= COUNT_START, f"S9: COUNT 0x{c9:x} below 0x100000 after FEED=0x0d09f00c"
        if key9:
            await self._wr("S9_RELOCK", "CTRL", WDT_ENALWAYS)
        key9_locked = await self._rd("S9_KEY_LOCKED", "KEY")
        assert key9_locked == 0, f"S9: KEY reads 0x{key9_locked:x} before the locked FEED write"
        await self.csr_write("WDT0_FEED_LOCKED", self._reg(0, "FEED"), FEED_WORD)
        c9b = await self._rd("S9_COUNT_LOCKED", "COUNT")
        assert c9b >= COUNT_START, f"S9: COUNT 0x{c9b:x} below 0x100000 after the locked FEED"
        self._mark_step("S9")
        self._log_chk(
            "CHK-WDT-FEED-NONMAGIC",
            f"keyed FEED=0x0d09f00c left COUNT at 0x{c9:x} (>= 0x100000); KEY read 0x{key9:x} "
            f"after it ({'unlocked, re-locked by a CTRL rewrite' if key9 else 'locked'}, "
            f"SF-010 is not asserted); locked FEED=0x0d09f00d left COUNT at 0x{c9b:x} "
            f"(>= 0x100000)",
        )

        # S10
        await self._wr("S10_CTRL", "CTRL", WDT_COREAWAKE, core=1)
        await self._wr("S10_COUNT", "COUNT", COUNT_START, core=1)
        pre = await self._window("S10_PRE", 3, core=1)
        assert _increasing(pre), f"S10: core 1 COUNT not increasing out of reset: {pre}"
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        assert ctrl & CORE1_N, f"S10: RESET_CTRL 0x{ctrl:x} has core 1's level reset low"
        await self.csr_write("S10_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("S10_CORE1_LO", RESET_CTRL, ctrl & ~CORE1_N, length=8)
        lo_rises = await self._await_core1_reset_n(0, "after core 1's level reset was written 0")
        bound = self.env.cfg.axi_timeout_ns
        timeouts_before = self.timeouts
        held_ctrl = await self.csr_read_bounded(
            "WDT1_CTRL_S10_HELD",
            self._reg(1, "CTRL"),
            timeout_ns=bound,
            allow_error=True,
        )
        held_done = self.timeouts == timeouts_before
        held = []
        if held_done:
            for i in range(3):
                before = self.timeouts
                value = await self.csr_read_bounded(
                    f"WDT1_COUNT_S10_HELD{i}",
                    self._reg(1, "COUNT"),
                    timeout_ns=bound,
                    allow_error=True,
                )
                if self.timeouts != before:
                    held.append(None)
                    break
                held.append(value)
            held_txt = (
                f"the bounded CTRL read completed with 0x{held_ctrl:x} and the bounded COUNT reads "
                f"{','.join('no completion' if r is None else f'0x{r:x}' for r in held)} "
                f"(nothing asserted)"
            )
        else:
            held_txt = (
                f"no completion within {bound} ns for the bounded CTRL read (RTL-4 candidate, "
                f"no further access during the hold)"
            )
        still_low = self._core1_reset_n()
        assert still_low == 0, f"S10: tb_cpu_core_resets_n[1] read {still_low} after the hold"
        await self.csr_write("S10_CORE1_HI", RESET_CTRL, ctrl, length=8)
        hi_rises = await self._await_core1_reset_n(1, "after core 1's level reset was released")
        after_ctrl = await self._rd("S10_CTRL_POST", "CTRL", core=1)
        assert after_ctrl & WDT_COREAWAKE, f"S10: CTRL reads 0x{after_ctrl:x} after the release"
        post = await self._window("S10_POST", 3, core=1)
        assert _increasing(post), f"S10: core 1 COUNT not increasing after the release: {post}"
        self._mark_step("S10")
        self._log_chk(
            "CHK-WDT-COREAWAKE",
            f"wdogcoreawake alone on core 1: out of reset reads {_hexes(pre)} increasing; "
            f"tb_cpu_core_resets_n[1] read 0 after {lo_rises} rises (bound {LEVEL_BOUND}); hold "
            f"phase: {held_txt}; released, tb_cpu_core_resets_n[1] read 1 after {hi_rises} rises, "
            f"CTRL 0x{after_ctrl:x} with wdogcoreawake set and reads {_hexes(post)} increasing "
            f"(the reset that defines the condition is SF-015)",
        )

        await self.csr_write("S10_TIMEOUT_RESTORE", RESET_TIMEOUT, 0, length=8)
        await self._wr("RESTORE_C1", "CTRL", 0, core=1)
        await self._wr("RESTORE_C0", "CTRL", 0)

        self._nonvac_fence()
        self.completed = True

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        chk_times = [t for _, t in self._chk_marks]
        assert all(b >= a for a, b in zip(chk_times, chk_times[1:])), "checker lines out of order"
        for chk_id, t in self._chk_marks:
            assert t >= stamp_of[_CHECKER_STEP[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
