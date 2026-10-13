# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 SCALED_COUNT shift relation and the wdogzerocmp count clear.

Contract SMC_POWER_TIMER_WDT_011, anchor smc_wdt_scale_zerocmp_test.
Scenarios WDT-SCALE.S1-S4 and WDT-ZEROCMP.S1-S5.
Sources wdt.rdl, smc-programming.adoc#watchdog.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_IP0_BIT = 28
WDT_ENALWAYS = 0x1000
WDT_ZEROCMP = 0x0200
WDT_POLL_LIMIT = 400
WDT_FAR_ABOVE = 0x100

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
_CHECKERS = (
    "CHK-WDT-SCALED-COUNT-WIDE",
    "CHK-WDT-SCALED-COUNT-SHIFT",
    "CHK-WDT-ZEROCMP-OFF",
    "CHK-WDT-ZEROCMP-CMP0",
    "CHK-WDT-ZEROCMP-CLEAR",
)


class smc_wdt_scale_zerocmp_test_seq(SmcCsrSeq):
    """Drive watchdog 0 through scale and zero-on-compare windows over SEP_IN."""

    def __init__(self, name: str = "smc_wdt_scale_zerocmp_test_seq") -> None:
        super().__init__(name)
        self.completed = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []

    def _reg(self, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE0_WDT_{reg}_BASE_ADDR")

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    async def _wr(self, label: str, reg: str, data: int) -> None:
        await self.csr_write(f"WDT0_KEY_{label}", self._reg("KEY"), WDT_MAGIC_KEY)
        await self.csr_write(f"WDT0_{reg}_{label}", self._reg(reg), data)

    async def _rd(self, label: str, reg: str) -> int:
        return await self.csr_read(f"WDT0_{reg}_{label}", self._reg(reg))

    async def _window(self, label: str, n: int) -> list[int]:
        return [await self._rd(f"{label}{i}", "COUNT") for i in range(n)]

    @staticmethod
    def _has_drop(reads: list[int]) -> bool:
        return any(b < a for a, b in zip(reads, reads[1:]))

    async def _ip0(self, label: str) -> int:
        ctrl = await self._rd(label, "CTRL")
        return (ctrl >> WDT_IP0_BIT) & 1

    async def body(self) -> None:
        # S1
        await self._wr("S1_SETUP", "CTRL", 0)
        await self._wr("S1_SETUP", "COUNT", 0x5A5A)
        shift_rows = []
        for s in range(16):
            await self._wr(f"S1_{s}", "CTRL", s)
            c1 = await self._rd(f"S1_{s}_C1", "COUNT")
            sc = await self._rd(f"S1_{s}_SC", "SCALED_COUNT")
            c2 = await self._rd(f"S1_{s}_C2", "COUNT")
            assert (c1 >> s) <= sc <= (c2 >> s), (
                f"scale {s}: SCALED_COUNT 0x{sc:x} outside [0x{c1 >> s:x}, 0x{c2 >> s:x}] "
                f"(COUNT 0x{c1:x}, 0x{c2:x})"
            )
            shift_rows.append(f"{s}:{sc:x}")
        self._mark_step("S1")

        # S2
        held_rows = []
        for s in range(1, 16):
            await self._wr(f"S2_{s}_COUNT", "COUNT", (1 << s) - 1)
            await self._wr(f"S2_{s}_CTRL", "CTRL", s)
            sc = await self._rd(f"S2_{s}_SC", "SCALED_COUNT")
            c2 = await self._rd(f"S2_{s}_C2", "COUNT")
            assert sc <= (c2 >> s), (
                f"scale {s}: SCALED_COUNT 0x{sc:x} above COUNT>>s 0x{c2 >> s:x} "
                f"(COUNT 0x{c2:x}, written 0x{(1 << s) - 1:x})"
            )
            held_rows.append(f"{s}:{sc:x}")
        self._mark_step("S2")

        # S3
        wide = []
        for count, s in ((0x12345, 0), (0x24690, 1)):
            await self._wr(f"S3_{s}_COUNT", "COUNT", count)
            await self._wr(f"S3_{s}_CTRL", "CTRL", s)
            sc = await self._rd(f"S3_{s}_SC", "SCALED_COUNT")
            wide.append((count, s, sc))
        self._mark_step("S3")
        self._log_chk(
            "CHK-WDT-SCALED-COUNT-WIDE",
            "; ".join(
                f"COUNT=0x{c:08x} scale {s}: SCALED_COUNT=0x{sc:x} COUNT>>s=0x{c >> s:x}"
                for c, s, sc in wide
            )
            + "; the width limit is SF-013 and is not asserted",
        )

        # S4
        await self._wr("S4_CMP", "CMP", 0xFFFF)
        await self._wr("S4_COUNT", "COUNT", 0x80000)
        await self._wr("S4_CTRL0", "CTRL", WDT_ENALWAYS)
        await self._wr("S4_CTRL4", "CTRL", WDT_ENALWAYS | 4)
        c1 = await self._rd("S4_C1", "COUNT")
        sc = await self._rd("S4_SC", "SCALED_COUNT")
        c2 = await self._rd("S4_C2", "COUNT")
        assert (c1 >> 4) <= sc <= (c2 >> 4), (
            f"scale 4 running: SCALED_COUNT 0x{sc:x} outside [0x{c1 >> 4:x}, 0x{c2 >> 4:x}] "
            f"(COUNT 0x{c1:x}, 0x{c2:x})"
        )
        self._mark_step("S4")
        self._log_chk(
            "CHK-WDT-SCALED-COUNT-SHIFT",
            f"scales 0..15 held: SCALED_COUNT within the shifted COUNT bracket 16 of 16 "
            f"(scale:SC {' '.join(shift_rows)}); COUNT=2^s-1 s=1..15: SCALED_COUNT <= C2>>s "
            f"15 of 15 (scale:SC {' '.join(held_rows)}); scale 4 running: "
            f"C1>>4=0x{c1 >> 4:x} <= SC=0x{sc:x} <= C2>>4=0x{c2 >> 4:x}",
        )

        # S5
        await self._wr("S5_CMP", "CMP", 0x40)
        await self._wr("S5_COUNT", "COUNT", 0)
        await self._wr("S5_CTRL", "CTRL", WDT_ENALWAYS | WDT_ZEROCMP)
        reads5 = await self._window("S5_R", 16)
        assert self._has_drop(reads5), f"S5: no COUNT read below its predecessor: {reads5}"
        ip5 = await self._ip0("S5_CTRL_RB")
        assert ip5 == 1, f"S5: CTRL.wdogip0 reads {ip5}, want 1 (COUNT reads {reads5})"
        self._mark_step("S5")

        # S6
        await self._wr("S6_CTRL", "CTRL", WDT_ENALWAYS)
        await self._wr("S6_COUNT", "COUNT", 0)
        reads6 = await self._window("S6_R", 16)
        assert all(b > a for a, b in zip(reads6, reads6[1:])), (
            f"S6: COUNT reads not strictly increasing with wdogzerocmp clear: {reads6}"
        )
        assert reads6[-1] > 0x40, f"S6: last COUNT read 0x{reads6[-1]:x} not above CMP 0x40"
        self._mark_step("S6")
        self._log_chk(
            "CHK-WDT-ZEROCMP-OFF",
            f"wdogzerocmp clear, wdogenalways set, CMP=0x40: 16 COUNT reads strictly increase "
            f"({','.join(f'{r:x}' for r in reads6)}); last 0x{reads6[-1]:x} > CMP 0x40",
        )

        # S7
        await self._wr("S7_CMP_HI", "CMP", 0xFFFF)
        await self._wr("S7_COUNT", "COUNT", 0)
        await self._wr("S7_CTRL_CLR", "CTRL", WDT_ENALWAYS)
        ip7_pre = await self._ip0("S7_CTRL_PRE")
        assert ip7_pre == 0, f"S7: CTRL.wdogip0 reads {ip7_pre} before CMP=0 is written, want 0"
        await self._wr("S7_CMP", "CMP", 0)
        await self._wr("S7_CTRL", "CTRL", WDT_ENALWAYS | WDT_ZEROCMP)
        reads7 = await self._window("S7_R", 8)
        ip7 = await self._ip0("S7_CTRL_RB")
        assert ip7 == 1, f"S7: CTRL.wdogip0 reads {ip7}, want 1 (COUNT reads {reads7})"
        self._mark_step("S7")
        self._log_chk(
            "CHK-WDT-ZEROCMP-CMP0",
            f"CMP=0xFFFF cleared: wdogip0={ip7_pre}; CMP=0 with wdogzerocmp set: "
            f"wdogip0={ip7}; 8 COUNT reads "
            f"{','.join(f'0x{r:x}' for r in reads7)} (count after each clear is SF-007)",
        )

        # S8
        await self._wr("S8_CMP", "CMP", 4)
        await self._wr("S8_COUNT", "COUNT", 0)
        await self._wr("S8_CTRL", "CTRL", WDT_ENALWAYS | WDT_ZEROCMP | 3)
        reads8 = await self._window("S8_R", 16)
        assert self._has_drop(reads8), f"S8: no COUNT read below its predecessor: {reads8}"
        ip8 = await self._ip0("S8_CTRL_RB")
        assert ip8 == 1, f"S8: CTRL.wdogip0 reads {ip8}, want 1 (COUNT reads {reads8})"
        self._mark_step("S8")

        # S9
        await self._wr("S9_CMP", "CMP", 0x40)
        await self._wr("S9_CTRL0", "CTRL", WDT_ENALWAYS)
        last = -1
        for poll in range(WDT_POLL_LIMIT):
            last = await self._rd(f"S9_POLL{poll}", "COUNT")
            if last > WDT_FAR_ABOVE:
                break
        else:
            raise AssertionError(
                f"S9: COUNT never exceeded 0x{WDT_FAR_ABOVE:x} in {WDT_POLL_LIMIT} reads "
                f"(last 0x{last:x})"
            )
        await self._wr("S9_CTRL1", "CTRL", WDT_ENALWAYS | WDT_ZEROCMP)
        reads9 = await self._window("S9_R", 8)
        assert self._has_drop(reads9), f"S9: no COUNT read below its predecessor: {reads9}"
        self._mark_step("S9")
        self._log_chk(
            "CHK-WDT-ZEROCMP-CLEAR",
            f"scale 0 CMP 0x40: 16 reads contain a drop, wdogip0={ip5}, max 0x{max(reads5):x} "
            f"vs CMP<<0=0x40; scale 3 CMP 4: 16 reads contain a drop, wdogip0={ip8}, "
            f"max 0x{max(reads8):x} vs CMP<<3=0x20; zerocmp set at COUNT 0x{last:x} after "
            f"{poll + 1} polls: 8 reads {','.join(f'0x{r:x}' for r in reads9)} contain a drop "
            f"(latency is SF-007)",
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
        last_step = {
            "CHK-WDT-SCALED-COUNT-WIDE": "S3",
            "CHK-WDT-SCALED-COUNT-SHIFT": "S4",
            "CHK-WDT-ZEROCMP-OFF": "S6",
            "CHK-WDT-ZEROCMP-CMP0": "S7",
            "CHK-WDT-ZEROCMP-CLEAR": "S9",
        }
        chk_times = [t for _, t in self._chk_marks]
        assert all(b >= a for a, b in zip(chk_times, chk_times[1:])), "checker lines out of order"
        for chk_id, t in self._chk_marks:
            assert t >= stamp_of[last_step[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<PASS; checker lines %s; "
            "stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
