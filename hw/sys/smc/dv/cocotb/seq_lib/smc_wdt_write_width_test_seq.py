# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 byte-enable handling of every register write over SEP_IN.

Sources wdt.rdl, watchdog.adoc#Register Access.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_CMP_RESET = 0x1000
WDT_COUNT_BASE = 0x0010_0000
WDT_FEED_MAGIC = 0x0D09F00D
WDT_IP0_MASK = 1 << 28
WDT_UNLOCKED = 1
WDT_LOCKED = 0

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
_CHECKERS = (
    "CHK-WDT-NARROW-KEY-FEED",
    "CHK-WDT-HALFWORD-CMP-SCALED",
    "CHK-WDT-CTRL-BYTELANES",
    "CHK-WDT-NARROW-COUNT",
    "CHK-WDT-ZERO-STROBE",
)
_CHECKER_STEP = dict(zip(_CHECKERS, ("S4", "S6", "S8", "S9", "S10")))


class smc_wdt_write_width_test_seq(SmcCsrSeq):
    """Drive watchdog 0 with every byte-enable mask the test lists."""

    def __init__(self, name: str = "smc_wdt_write_width_test_seq") -> None:
        super().__init__(name)
        self.completed = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._hold = 0

    def _reg(self, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE0_WDT_{reg}_BASE_ADDR")

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _rd(self, label: str, reg: str) -> int:
        return await self.csr_read(f"WDT0_{reg}_{label}", self._reg(reg))

    async def _wr(self, label: str, reg: str, data: int) -> None:
        await self.csr_write(f"WDT0_{reg}_{label}", self._reg(reg), data)

    async def _wr_strb(self, label: str, reg: str, data: int, strb: int) -> None:
        await self.csr_write_strobed(f"WDT0_{reg}_{label}", self._reg(reg), data, strb)

    async def _key(self, label: str) -> None:
        await self._wr(f"{label}_UNLOCK", "KEY", WDT_MAGIC_KEY)

    async def _expect_key(self, label: str, want: int) -> None:
        got = await self._rd(f"{label}_KEY", "KEY")
        assert got == want, f"{label}: KEY reads 0x{got:x}, want 0x{want:x}"

    async def _expect_cmp(self, label: str, want: int) -> None:
        got = await self._rd(f"{label}_CMP", "CMP")
        assert got == want, f"{label}: CMP reads 0x{got:x}, want 0x{want:x}"

    async def _near(self, label: str, ref: int) -> int:
        count = await self._rd(f"{label}_COUNT", "COUNT")
        assert abs(count - ref) <= self._hold, (
            f"{label}: COUNT 0x{count:x} is {abs(count - ref):#x} from 0x{ref:x}, "
            f"hold allowance A=0x{self._hold:x}"
        )
        return count

    async def body(self) -> None:
        # S1
        await self._wr("S1_CTRL", "CTRL", 0)
        c0 = await self._rd("S1_A0", "COUNT")
        c1 = await self._rd("S1_A1", "COUNT")
        self._hold = abs(c1 - c0)
        await self._key("S1")
        await self._wr("S1_COUNT", "COUNT", WDT_COUNT_BASE)
        self._mark_step("S1")

        # S2
        await self._key("S2")
        narrow_count = (
            (0x0000_00FF, 0b0001),
            (0x0000_FFFF, 0b0011),
            (0x00FF_FFFF, 0b0111),
            (0xFFFF_FF00, 0b1110),
        )
        count_rows = []
        for data, strb in narrow_count:
            await self._wr_strb(f"S2_M{strb:04b}", "COUNT", data, strb)
            count = await self._near(f"S2_M{strb:04b}", WDT_COUNT_BASE)
            await self._expect_key(f"S2_M{strb:04b}", WDT_UNLOCKED)
            count_rows.append(f"{strb:04b}:0x{count:x}")
        self._mark_step("S2")

        # S3
        await self._wr("S3_RELOCK", "COUNT", WDT_COUNT_BASE)
        await self._expect_key("S3_LOCKED", WDT_LOCKED)
        for strb in (0b0011, 0b0111):
            await self._wr_strb(f"S3_KEY{strb:04b}", "KEY", WDT_MAGIC_KEY, strb)
            await self._expect_key(f"S3_KEY{strb:04b}", WDT_LOCKED)
            await self._wr(f"S3_CMP{strb:04b}", "CMP", 0x3333)
            await self._expect_cmp(f"S3_CMP{strb:04b}", WDT_CMP_RESET)
        self._mark_step("S3")

        # S4
        await self._key("S4")
        before = await self._near("S4_BEFORE", WDT_COUNT_BASE)
        await self._wr_strb("S4_FEED", "FEED", WDT_FEED_MAGIC, 0b0011)
        after = await self._near("S4_AFTER", before)
        assert after > 0x1000, f"S4: COUNT 0x{after:x} looks reset by the narrow FEED write"
        await self._expect_key("S4", WDT_UNLOCKED)
        self._mark_step("S4")
        self._log_chk(
            "CHK-WDT-NARROW-KEY-FEED",
            f"KEY=0x{WDT_MAGIC_KEY:06x} with masks 0b0011 and 0b0111 left KEY 0 and the CMP write "
            f"0x3333 after each dropped (CMP 0x{WDT_CMP_RESET:x}); FEED=0x{WDT_FEED_MAGIC:08x} "
            f"mask 0b0011 while unlocked: OKAY, COUNT 0x{before:x} -> 0x{after:x} within "
            f"A=0x{self._hold:x}, KEY 1; FEED/KEY read values are open owner questions and are not "
            f"asserted",
        )

        # S5
        cmp_rows = []
        for data, strb in ((0x00FF, 0b0001), (0xFF00, 0b0010)):
            await self._wr_strb(f"S5_CMP{strb:04b}", "CMP", data, strb)
            await self._expect_cmp(f"S5_CMP{strb:04b}", WDT_CMP_RESET)
            await self._expect_key(f"S5_CMP{strb:04b}", WDT_UNLOCKED)
            cmp_rows.append(f"{strb:04b}:0x{WDT_CMP_RESET:x}")
        await self._wr_strb("S5_CMP0011", "CMP", 0xA5A5, 0b0011)
        await self._expect_cmp("S5_CMP0011", 0xA5A5)
        await self._expect_key("S5_CMP0011", WDT_LOCKED)
        await self._key("S5_SC1")
        await self._wr_strb("S5_SC0001", "SCALED_COUNT", 0x00FF, 0b0001)
        await self._expect_key("S5_SC0001", WDT_UNLOCKED)
        await self._wr_strb("S5_SC0011", "SCALED_COUNT", 0x00FF, 0b0011)
        await self._expect_key("S5_SC0011", WDT_LOCKED)
        self._mark_step("S5")

        # S6
        await self._key("S6")
        await self._wr_strb("S6_COUNT_HI", "COUNT_HI", 0xFFFF_FFFF, 0b0011)
        await self._expect_key("S6_COUNT_HI", WDT_UNLOCKED)
        self._mark_step("S6")
        self._log_chk(
            "CHK-WDT-HALFWORD-CMP-SCALED",
            f"CMP masks {' '.join(cmp_rows)} left CMP 0x{WDT_CMP_RESET:x} with KEY 1; mask 0b0011 "
            "read back 0xa5a5 with KEY 0; SCALED_COUNT mask 0b0001 left KEY 1 and mask 0b0011 "
            "locked it (KEY 0); COUNT_HI=0xffffffff mask 0b0011 answered OKAY with KEY 1; "
            "SCALED_COUNT and COUNT_HI read values are open owner questions and are not asserted",
        )

        # S7
        lane_rows = []
        prev = await self._rd("S7_BASE", "CTRL")
        lane_rows.append(f"base:0x{prev & ~WDT_IP0_MASK:x}")
        raise_cmp = False
        for lane, value in ((0, 0x05), (1, 0x03), (1, 0x30), (3, 0x10)):
            if lane == 1 and value == 0x30:
                await self._key("S7_CMP_HI")
                await self._wr("S7_CMP_HI", "CMP", 0xFFFF)
                raise_cmp = True
            await self._key(f"S7_L{lane}_{value:02x}")
            await self._wr_strb(f"S7_L{lane}_{value:02x}", "CTRL", value << (8 * lane), 1 << lane)
            lane_mask = 0xFF << (8 * lane)
            want = (prev & ~lane_mask) | ((value << (8 * lane)) & lane_mask)
            got = await self._rd(f"S7_L{lane}_{value:02x}_RB", "CTRL")
            assert (got & ~WDT_IP0_MASK) == (want & ~WDT_IP0_MASK), (
                f"S7 lane {lane} value 0x{value:02x}: CTRL 0x{got:08x}, want 0x{want:08x} "
                f"(bit 28 masked, previous 0x{prev:08x})"
            )
            lane_rows.append(f"lane{lane}=0x{value:02x}:0x{got & ~WDT_IP0_MASK:x}")
            prev = got
            if lane == 1 and value == 0x30:
                await self._key("S7_CLEAR")
                await self._wr_strb("S7_CLEAR", "CTRL", 0, 0b0010)
                got = await self._rd("S7_CLEAR_RB", "CTRL")
                want = prev & ~0xFF00
                assert (got & ~WDT_IP0_MASK) == (want & ~WDT_IP0_MASK), (
                    f"S7 clear: CTRL 0x{got:08x}, want 0x{want:08x} (bit 28 masked)"
                )
                prev = got
        assert raise_cmp
        await self._key("S7_CMP_RESTORE")
        await self._wr("S7_CMP_RESTORE", "CMP", WDT_CMP_RESET)
        await self._key("S7_COUNT_ZERO")
        await self._wr("S7_COUNT_ZERO", "COUNT", 0)
        await self._key("S7_IP0_CLEAR")
        await self._wr_strb("S7_IP0_CLEAR", "CTRL", 0, 0b1000)
        got = await self._rd("S7_IP0_CLEAR_RB", "CTRL")
        assert got == prev & ~WDT_IP0_MASK, (
            f"S7: CTRL 0x{got:08x} after clearing bit 28, want 0x{prev & ~WDT_IP0_MASK:08x}"
        )
        self._mark_step("S7")

        # S8
        await self._key("S8_A")
        await self._wr_strb("S8_A_B0", "CTRL", 0x03, 0b0001)
        await self._wr_strb("S8_A_B1", "CTRL", 0x01 << 8, 0b0010)
        one_key = await self._rd("S8_A_RB", "CTRL")
        assert one_key == 0x0000_0003, f"S8: CTRL 0x{one_key:08x} after KEY, b0, b1, want 0x3"
        await self._key("S8_B0")
        await self._wr_strb("S8_B_B0", "CTRL", 0x03, 0b0001)
        await self._key("S8_B1")
        await self._wr_strb("S8_B_B1", "CTRL", 0x01 << 8, 0b0010)
        two_key = await self._rd("S8_B_RB", "CTRL")
        assert two_key == 0x0000_0103, f"S8: CTRL 0x{two_key:08x} after KEY,b0,KEY,b1, want 0x103"
        await self._key("S8_RESTORE")
        await self._wr("S8_RESTORE", "CTRL", 0)
        self._mark_step("S8")
        self._log_chk(
            "CHK-WDT-CTRL-BYTELANES",
            f"single-byte CTRL writes changed only the written lane (bit 28 masked): "
            f"{' '.join(lane_rows)}; KEY,b0,b1 read 0x{one_key:x}; KEY,b0,KEY,b1 read "
            f"0x{two_key:x}; CTRL restored to 0",
        )

        # S9
        await self._key("S9")
        await self._wr_strb("S9_NARROW", "COUNT", 0x7F, 0b0001)
        await self._expect_key("S9_NARROW", WDT_UNLOCKED)
        await self._wr("S9_FULL", "COUNT", 0x40)
        count9 = await self._near("S9_FULL", 0x40)
        await self._expect_key("S9_FULL", WDT_LOCKED)
        self._mark_step("S9")
        self._log_chk(
            "CHK-WDT-NARROW-COUNT",
            f"narrow COUNT writes (masks {' '.join(count_rows)}) answered OKAY with COUNT within "
            f"A=0x{self._hold:x} of 0x{WDT_COUNT_BASE:x} and KEY 1; a byte-0 write of 0x7f left "
            f"the unlock in place, the 32-bit write was accepted (COUNT 0x{count9:x} within A of "
            "0x40) and KEY read 0; counting with neither enable is an open owner question and is "
            "not asserted",
        )

        # S10
        await self._key("S10")
        await self._wr_strb("S10_ZERO", "CMP", 0x5555, 0)
        await self._expect_cmp("S10", WDT_CMP_RESET)
        await self._expect_key("S10", WDT_UNLOCKED)
        self._mark_step("S10")
        self._log_chk(
            "CHK-WDT-ZERO-STROBE",
            f"CMP=0x5555 with byte-enable mask 0b0000 answered OKAY, CMP read 0x{WDT_CMP_RESET:x}, "
            "KEY read 1",
        )

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
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10<PASS; checker lines %s; "
            "stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
