# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Core 0 watchdog KEY protocol corners and relock on every register.

Contract SMC_POWER_TIMER_WDT_008, anchor smc_wdt_key_relock_test.
Allocated scenarios: WDT-KEY-UNLOCK.S3-S6, WDT-RELOCK.S1-S5, WDT-RELOCK.S7, WDT-RELOCK.S8.
Spec sources: hw/sys/smc/doc/watchdog.adoc (Register Access), hw/sys/smc/regs/blocks/wdt/wdt.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_CMP_RESET = 0x1000
WDT_KEY_UNLOCKED = 0x1
WDT_KEY_LOCKED = 0x0
WDT_NONMAGIC_KEYS = (0x0051_F15F, 0xFFFF_FFFF, 0x0000_0000)
WDT_CMP_DROPPED = 0x2222
WDT_CMP_REPEAT = 0x3333
WDT_CMP_REPEAT_DROPPED = 0x4444
WDT_CMP_RELOCK = 0x1234
WDT_CMP_RELOCK_DROPPED = 0x4321
WDT_CMP_REG_DROPPED = 0x2468
WDT_CMP_LOCKED_WRITE = 0x1357
WDT_CTRL_RELOCK = 0x0000_0002
WDT_CTRL_LOCKED_WRITE = 0x0000_0330
WDT_COUNT_RELOCK = 0x0010_0000
WDT_COUNT_LOCKED_WRITE = 0x0020_0000
WDT_COUNT_WIDE = 0x0030_0000
WDT_FEED_VALUE = 0x0D09_F00D
WDT_SCALED_PROBE = 0x1234
WDT_WIDE_DATA = (WDT_MAGIC_KEY << 32) | WDT_FEED_VALUE

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
CHECKERS = (
    ("CHK-WDT-KEY-NONMAGIC", "S2"),
    ("CHK-WDT-KEY-REPEATED-MAGIC", "S3"),
    ("CHK-WDT-KEY-READ-UNLOCKED", "S4"),
    ("CHK-WDT-RELOCK-CMP", "S5"),
    ("CHK-WDT-RELOCK-REGISTERS", "S7"),
    ("CHK-WDT-LOCKED-WRITE-DROP", "S8"),
    ("CHK-WDT-WIDE-WRITE-LOCK", "S9"),
)


class smc_wdt_key_relock_test_seq(SmcCsrSeq):
    """Core 0 watchdog non-magic, repeated and per-register KEY relock corners."""

    def __init__(self, name: str = "smc_wdt_key_relock_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []

    def _reg(self, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE0_WDT_{reg}_BASE_ADDR")

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    async def _unlock(self, label: str) -> None:
        await self.csr_write(label, self._reg("KEY"), WDT_MAGIC_KEY)

    async def _read_key(self, label: str, expected: int) -> int:
        return await self.csr_read(label, self._reg("KEY"), expected=expected)

    async def _cmp_write_dropped(self, label: str, value: int, still: int) -> None:
        cmp_ = self._reg("CMP")
        await self.csr_write(f"{label}_CMP_WR", cmp_, value)
        await self.csr_read(f"{label}_CMP_RB", cmp_, expected=still)

    async def body(self) -> None:
        key = self._reg("KEY")
        cmp_ = self._reg("CMP")
        count = self._reg("COUNT")

        # S1
        await self._read_key("S1_KEY", WDT_KEY_LOCKED)
        await self.csr_read("S1_CMP", cmp_, expected=WDT_CMP_RESET)
        r1 = await self.csr_read("S1_COUNT_R1", count)
        r2 = await self.csr_read("S1_COUNT_R2", count)
        assert r2 >= r1, f"COUNT went backwards between back-to-back reads: {r1:#x} {r2:#x}"
        allowance = 4 * (r2 - r1)
        self._step("S1")

        # S2
        for i, value in enumerate(WDT_NONMAGIC_KEYS):
            await self.csr_write(f"S2_KEY_{i}", key, value)
            await self._read_key(f"S2_KEY_RB_{i}", WDT_KEY_LOCKED)
            await self._cmp_write_dropped(f"S2_{i}", WDT_CMP_DROPPED, WDT_CMP_RESET)
        self._step("S2")
        self._chk(
            "CHK-WDT-KEY-NONMAGIC",
            "S2",
            "locked KEY writes of %s each left KEY at 0x%x and the CMP write of 0x%04x "
            "dropped (CMP 0x%04x), 3 of 3 values; hold allowance A=%d",
            ",".join(f"0x{v:08x}" for v in WDT_NONMAGIC_KEYS),
            WDT_KEY_LOCKED,
            WDT_CMP_DROPPED,
            WDT_CMP_RESET,
            allowance,
        )

        # S3
        await self._unlock("S3_KEY_WR1")
        await self._unlock("S3_KEY_WR2")
        key_between = await self._read_key("S3_KEY_BETWEEN", None)
        await self.csr_write("S3_CMP_WR", cmp_, WDT_CMP_REPEAT)
        await self.csr_read("S3_CMP_RB", cmp_, expected=WDT_CMP_REPEAT)
        await self._read_key("S3_KEY_RELOCKED", WDT_KEY_LOCKED)
        await self._cmp_write_dropped("S3", WDT_CMP_REPEAT_DROPPED, WDT_CMP_REPEAT)
        self._step("S3")
        self._chk(
            "CHK-WDT-KEY-REPEATED-MAGIC",
            "S3",
            "after two magic writes CMP write 0x%04x read back 0x%04x, KEY then read 0x%x and "
            "the next write of 0x%04x was dropped (CMP 0x%04x); KEY read between the magic "
            "writes and the register write = 0x%x (SF-009)",
            WDT_CMP_REPEAT,
            WDT_CMP_REPEAT,
            WDT_KEY_LOCKED,
            WDT_CMP_REPEAT_DROPPED,
            WDT_CMP_REPEAT,
            key_between,
        )

        # S4
        await self._unlock("S4_KEY_WR")
        k_before = await self._read_key("S4_KEY_BEFORE", WDT_KEY_UNLOCKED)
        reads = {}
        for reg in ("CTRL", "COUNT", "CMP", "SCALED_COUNT", "COUNT_HI"):
            reads[reg] = await self.csr_read(f"S4_{reg}", self._reg(reg))
        k_after = await self._read_key("S4_KEY_AFTER", WDT_KEY_UNLOCKED)
        await self.csr_write("S4_CMP_WR", cmp_, WDT_CMP_RESET)
        await self._read_key("S4_KEY_RELOCKED", WDT_KEY_LOCKED)
        self._step("S4")
        self._chk(
            "CHK-WDT-KEY-READ-UNLOCKED",
            "S4",
            "unlocked KEY read 0x%x before and 0x%x after reads of CTRL=0x%08x COUNT=0x%08x "
            "CMP=0x%04x SCALED_COUNT=0x%08x COUNT_HI=0x%08x; the CMP write was accepted and "
            "KEY then read 0x%x",
            k_before,
            k_after,
            reads["CTRL"],
            reads["COUNT"],
            reads["CMP"],
            reads["SCALED_COUNT"],
            reads["COUNT_HI"],
            WDT_KEY_LOCKED,
        )

        # S5
        await self._unlock("S5_KEY_WR")
        await self.csr_write("S5_CMP_WR", cmp_, WDT_CMP_RELOCK)
        await self._read_key("S5_KEY_RELOCKED", WDT_KEY_LOCKED)
        await self._cmp_write_dropped("S5", WDT_CMP_RELOCK_DROPPED, WDT_CMP_RELOCK)
        self._step("S5")
        self._chk(
            "CHK-WDT-RELOCK-CMP",
            "S5",
            "after KEY and CMP=0x%04x KEY read 0x%x and the CMP write of 0x%04x without KEY "
            "left CMP at 0x%04x",
            WDT_CMP_RELOCK,
            WDT_KEY_LOCKED,
            WDT_CMP_RELOCK_DROPPED,
            WDT_CMP_RELOCK,
        )

        # S6
        for reg, value in (
            ("CTRL", WDT_CTRL_RELOCK),
            ("COUNT", WDT_COUNT_RELOCK),
            ("FEED", WDT_FEED_VALUE),
        ):
            await self._unlock(f"S6_{reg}_KEY_WR")
            await self.csr_write(f"S6_{reg}_WR", self._reg(reg), value)
            await self._read_key(f"S6_{reg}_KEY_RB", WDT_KEY_LOCKED)
            await self._cmp_write_dropped(f"S6_{reg}", WDT_CMP_REG_DROPPED, WDT_CMP_RELOCK)
        self._step("S6")

        # S7
        await self._unlock("S7_KEY_WR")
        await self.csr_write("S7_SCALED_WR", self._reg("SCALED_COUNT"), WDT_SCALED_PROBE)
        scaled = await self.csr_read("S7_SCALED_RB", self._reg("SCALED_COUNT"))
        ctrl_now = await self.csr_read("S7_CTRL", self._reg("CTRL"), expected=WDT_CTRL_RELOCK)
        count_after = await self.csr_read("S7_COUNT_AFTER", count)
        await self._read_key("S7_KEY_RB", WDT_KEY_LOCKED)
        scale = ctrl_now & 0xF
        assert scaled != WDT_SCALED_PROBE, f"SCALED_COUNT took the write: 0x{scaled:x}"
        assert scaled <= (count_after >> scale), (
            f"SCALED_COUNT 0x{scaled:x} above COUNT>>{scale} = 0x{count_after >> scale:x}"
        )
        self._step("S7")
        self._chk(
            "CHK-WDT-RELOCK-REGISTERS",
            "S7",
            "after KEY and a 32-bit write to each of CTRL, COUNT, FEED and SCALED_COUNT KEY read "
            "0x%x and the CMP write without KEY was dropped (CMP 0x%04x); SCALED_COUNT read "
            "0x%x (not 0x%04x) with COUNT>>%d = 0x%x; 4 of 4 registers",
            WDT_KEY_LOCKED,
            WDT_CMP_RELOCK,
            scaled,
            WDT_SCALED_PROBE,
            scale,
            count_after >> scale,
        )

        # S8
        prev_count = count_after
        await self.csr_write("S8_CTRL_WR", self._reg("CTRL"), WDT_CTRL_LOCKED_WRITE)
        await self.csr_write("S8_COUNT_WR", count, WDT_COUNT_LOCKED_WRITE)
        await self.csr_write("S8_CMP_WR", cmp_, WDT_CMP_LOCKED_WRITE)
        ctrl_rb = await self.csr_read("S8_CTRL_RB", self._reg("CTRL"), expected=WDT_CTRL_RELOCK)
        count_rb = await self.csr_read("S8_COUNT_RB", count)
        await self.csr_read("S8_CMP_RB", cmp_, expected=WDT_CMP_RELOCK)
        await self._read_key("S8_KEY_RB", WDT_KEY_LOCKED)
        assert count_rb <= prev_count + 2 * allowance, (
            f"COUNT 0x{count_rb:x} above previous 0x{prev_count:x} by more than 2*A={2 * allowance}"
        )
        self._step("S8")
        self._chk(
            "CHK-WDT-LOCKED-WRITE-DROP",
            "S8",
            "locked writes CTRL=0x%08x COUNT=0x%08x CMP=0x%04x changed nothing: CTRL read 0x%08x, "
            "CMP read 0x%04x, COUNT read 0x%08x vs previous 0x%08x with 2*A=%d, KEY read 0x%x; "
            "3 of 3 registers",
            WDT_CTRL_LOCKED_WRITE,
            WDT_COUNT_LOCKED_WRITE,
            WDT_CMP_LOCKED_WRITE,
            ctrl_rb,
            WDT_CMP_RELOCK,
            count_rb,
            prev_count,
            2 * allowance,
            WDT_KEY_LOCKED,
        )

        # S9
        feed = self._reg("FEED")
        await self._unlock("S9_KEY_WR_COUNT")
        await self.csr_write("S9_COUNT_WR", count, WDT_COUNT_WIDE)
        await self.csr_write("S9_WIDE_LOCKED", feed, WDT_WIDE_DATA, length=8)
        await self._read_key("S9_KEY_RB_LOCKED", WDT_KEY_LOCKED)
        count_locked = await self.csr_read("S9_COUNT_LOCKED", count)
        await self._unlock("S9_KEY_WR_UNLOCKED")
        await self.csr_write("S9_WIDE_UNLOCKED", feed, WDT_WIDE_DATA, length=8)
        await self._read_key("S9_KEY_RB_UNLOCKED", WDT_KEY_LOCKED)
        count_unlocked = await self.csr_read("S9_COUNT_UNLOCKED", count)
        self._step("S9")
        self._chk(
            "CHK-WDT-WIDE-WRITE-LOCK",
            "S9",
            "64-bit write 0x%016x at FEED: KEY read 0x%x after the locked-state write and 0x%x "
            "after the unlocked-state write; COUNT read 0x%08x (locked state) and 0x%08x "
            "(unlocked state) after COUNT=0x%08x (SF-011)",
            WDT_WIDE_DATA,
            WDT_KEY_LOCKED,
            WDT_KEY_LOCKED,
            count_locked,
            count_unlocked,
            WDT_COUNT_WIDE,
        )

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        expected_accesses = self.accesses
        self.assert_all_reachable(expected_accesses, "WDT_KEY_RELOCK")
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, strictly increasing step "
            "stamps, each line printed after its own compare; checker lines %s; stamps %s",
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
