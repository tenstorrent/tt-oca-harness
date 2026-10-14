# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 0 CTRL.wdogip0 set, hold and clear sequence over SEP_IN.

Sources wdt.rdl, watchdog.adoc#Operation, smc-programming.adoc#watchdog.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_FEED_VALUE = 0x0D09F00D
WDT_IP0_BIT = 28
WDT_IP0_MASK = 1 << WDT_IP0_BIT
WDT_SCALE8 = 0x0008
WDT_SCALE8_ENALWAYS = 0x1008
WDT_CMP_LOW = 0x0010
WDT_CMP_MID = 0x0040
WDT_CMP_HIGH = 0x0100
WDT_COUNT_BELOW = 0x0000_1000
WDT_COUNT_ABOVE = 0x0000_4400
WDT_POLL_LIMIT = 4

_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
_CHECKERS = (
    "CHK-WDT-IP0-SET",
    "CHK-WDT-IP0-CLEAR-SEQUENCE",
    "CHK-WDT-IP0-UNLOCK-CONSUMED",
    "CHK-WDT-IP0-NO-CLEAR-ABOVE",
    "CHK-WDT-IP0-RESET-AFTER-CLEAR",
    "CHK-WDT-IP0-WRITE-ONE",
)
_LAST_STEP = {
    "CHK-WDT-IP0-SET": "S5",
    "CHK-WDT-IP0-CLEAR-SEQUENCE": "S7",
    "CHK-WDT-IP0-UNLOCK-CONSUMED": "S8",
    "CHK-WDT-IP0-NO-CLEAR-ABOVE": "S9",
    "CHK-WDT-IP0-RESET-AFTER-CLEAR": "S10",
    "CHK-WDT-IP0-WRITE-ONE": "S11",
}


class smc_wdt_ip0_clear_test_seq(SmcCsrSeq):
    """Drive watchdog 0 pending bit through set, hold and clear windows over SEP_IN."""

    def __init__(self, name: str = "smc_wdt_ip0_clear_test_seq") -> None:
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

    async def _ctrl(self, label: str, expected: int | None = None) -> int:
        return await self.csr_read(f"WDT0_CTRL_{label}", self._reg("CTRL"), expected=expected)

    async def _poll_ip0(self, label: str, ctrl_other: int) -> int:
        """Read CTRL until bit 28 reads 1; return the 1-based read index."""
        last = 0
        for n in range(1, WDT_POLL_LIMIT + 1):
            last = await self._ctrl(f"{label}_POLL{n}")
            if last & WDT_IP0_MASK:
                assert last == (ctrl_other | WDT_IP0_MASK), (
                    f"{label}: CTRL 0x{last:08x}, want 0x{ctrl_other | WDT_IP0_MASK:08x}"
                )
                return n
        raise AssertionError(
            f"{label}: CTRL bit 28 not 1 within {WDT_POLL_LIMIT} reads (last 0x{last:08x})"
        )

    async def _expect(self, label: str, value: int) -> None:
        got = await self._ctrl(label)
        assert got == value, f"{label}: CTRL 0x{got:08x}, want 0x{value:08x}"

    async def body(self) -> None:
        ctrl_a = WDT_SCALE8_ENALWAYS

        # S1
        await self._ctrl("S1_RESET", expected=0)
        self._mark_step("S1")

        # S2
        await self._wr("S2_CMP", "CMP", WDT_CMP_MID)
        await self._wr("S2_CTRL", "CTRL", WDT_SCALE8)
        await self._wr("S2_COUNT_BELOW", "COUNT", WDT_COUNT_BELOW)
        await self._expect("S2_BELOW", WDT_SCALE8)
        await self._wr("S2_COUNT_ABOVE", "COUNT", WDT_COUNT_ABOVE)
        await self._expect("S2_ABOVE", WDT_SCALE8 | WDT_IP0_MASK)
        self._mark_step("S2")

        # S3
        await self._wr("S3_CTRL", "CTRL", WDT_SCALE8)
        await self._expect("S3_HELD", WDT_SCALE8 | WDT_IP0_MASK)
        self._mark_step("S3")

        # S4
        await self._wr("S4_CMP", "CMP", WDT_CMP_HIGH)
        await self._wr("S4_CTRL", "CTRL", WDT_SCALE8)
        await self._expect("S4_CLEARED", WDT_SCALE8)
        self._mark_step("S4")

        # S5
        await self._wr("S5_CMP", "CMP", WDT_CMP_LOW)
        latency = await self._poll_ip0("S5", WDT_SCALE8)
        self._mark_step("S5")
        self._log_chk(
            "CHK-WDT-IP0-SET",
            f"CTRL bit 28 read 0 at reset and with scaled count 0x{WDT_COUNT_BELOW >> 8:x} below "
            f"CMP 0x{WDT_CMP_MID:x}, 1 with scaled count 0x{WDT_COUNT_ABOVE >> 8:x}, stayed 1 "
            f"after a keyed CTRL write of bit 28 = 0 above CMP, 0 after CMP "
            f"0x{WDT_CMP_HIGH:x} and the clear sequence, and 1 at read {latency} of "
            f"{WDT_POLL_LIMIT} after CMP dropped to "
            f"0x{WDT_CMP_LOW:x} (first-read latency is an open owner question)",
        )

        # S6
        await self._wr("S6_CMP", "CMP", WDT_CMP_MID)
        await self._wr("S6_CTRL", "CTRL", ctrl_a)
        await self._wr("S6_COUNT", "COUNT", WDT_COUNT_ABOVE)
        pre6 = await self._poll_ip0("S6_SET", ctrl_a)
        await self._wr("S6_FEED", "FEED", WDT_FEED_VALUE)
        await self._expect("S6_AFTER_FEED", ctrl_a | WDT_IP0_MASK)
        await self._wr("S6_CLEAR", "CTRL", ctrl_a)
        await self._expect("S6_CLEARED", ctrl_a)
        self._mark_step("S6")

        # S7
        await self._wr("S7_COUNT_SET", "COUNT", WDT_COUNT_ABOVE)
        pre7 = await self._poll_ip0("S7_SET", ctrl_a)
        await self._wr("S7_COUNT_BELOW", "COUNT", WDT_COUNT_BELOW)
        await self._wr("S7_CLEAR", "CTRL", ctrl_a)
        await self._expect("S7_CLEARED", ctrl_a)
        self._mark_step("S7")
        self._log_chk(
            "CHK-WDT-IP0-CLEAR-SEQUENCE",
            f"CMP 0x{WDT_CMP_MID:x} scale 8 enalways: bit 28 set at read {pre6}, feed left CTRL "
            f"0x{ctrl_a | WDT_IP0_MASK:08x}, KEY and CTRL write cleared it to 0x{ctrl_a:08x}; set "
            f"again at read {pre7}, COUNT 0x{WDT_COUNT_BELOW:x} below CMP then KEY and CTRL write "
            f"cleared it to 0x{ctrl_a:08x}",
        )

        # S8
        await self._wr("S8_COUNT_SET", "COUNT", WDT_COUNT_ABOVE)
        pre8 = await self._poll_ip0("S8_SET", ctrl_a)
        await self._wr("S8_FEED", "FEED", WDT_FEED_VALUE)
        await self.csr_write("WDT0_CTRL_S8_NOKEY_FEED", self._reg("CTRL"), ctrl_a)
        await self._expect("S8_FEED_HELD", ctrl_a | WDT_IP0_MASK)
        await self._wr("S8_COUNT_BELOW", "COUNT", WDT_COUNT_BELOW)
        await self.csr_write("WDT0_CTRL_S8_NOKEY_COUNT", self._reg("CTRL"), ctrl_a)
        await self._expect("S8_COUNT_HELD", ctrl_a | WDT_IP0_MASK)
        self._mark_step("S8")
        self._log_chk(
            "CHK-WDT-IP0-UNLOCK-CONSUMED",
            f"bit 28 set at read {pre8}; after KEY and FEED, and after KEY and COUNT "
            f"0x{WDT_COUNT_BELOW:x}, a CTRL write of 0x{ctrl_a:08x} without a second KEY was "
            f"dropped and CTRL read 0x{ctrl_a | WDT_IP0_MASK:08x} both times; "
            f"the feed left bit 28 = 1",
        )

        # S9
        await self._wr("S9_COUNT", "COUNT", WDT_COUNT_ABOVE)
        await self._wr("S9_CTRL", "CTRL", ctrl_a)
        await self._expect("S9_HELD", ctrl_a | WDT_IP0_MASK)
        self._mark_step("S9")
        self._log_chk(
            "CHK-WDT-IP0-NO-CLEAR-ABOVE",
            f"with a fresh KEY and scaled count 0x{WDT_COUNT_ABOVE >> 8:x} above CMP "
            f"0x{WDT_CMP_MID:x} a CTRL write of 0x{ctrl_a:08x} left CTRL "
            f"0x{ctrl_a | WDT_IP0_MASK:08x}",
        )

        # S10
        await self._wr("S10_FEED", "FEED", WDT_FEED_VALUE)
        await self._wr("S10_CLEAR", "CTRL", ctrl_a)
        await self._expect("S10_CLEARED", ctrl_a)
        await self._wr("S10_COUNT", "COUNT", WDT_COUNT_ABOVE)
        pre10 = await self._poll_ip0("S10_RESET", ctrl_a)
        self._mark_step("S10")
        self._log_chk(
            "CHK-WDT-IP0-RESET-AFTER-CLEAR",
            f"after the feed, KEY and CTRL clear read 0x{ctrl_a:08x}, COUNT 0x{WDT_COUNT_ABOVE:x} "
            f"with CMP 0x{WDT_CMP_MID:x} set bit 28 again at read {pre10}",
        )

        # S11
        await self._wr("S11_FEED", "FEED", WDT_FEED_VALUE)
        await self._wr("S11_CLEAR", "CTRL", ctrl_a)
        await self._expect("S11_CLEARED", ctrl_a)
        await self._wr("S11_WRITE_ONE", "CTRL", ctrl_a | WDT_IP0_MASK)
        ctrl11 = await self._ctrl("S11_READ")
        assert ctrl11 in range(0, 1 << 32), f"S11: CTRL read 0x{ctrl11:x} out of range"
        self._mark_step("S11")
        self._log_chk(
            "CHK-WDT-IP0-WRITE-ONE",
            f"scaled count below CMP 0x{WDT_CMP_MID:x}: after KEY and CTRL write of "
            f"0x{ctrl_a | WDT_IP0_MASK:08x} CTRL read 0x{ctrl11:08x}, bit 28 = "
            f"{(ctrl11 >> WDT_IP0_BIT) & 1} (value is an open owner question and is not asserted)",
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
            assert t >= stamp_of[_LAST_STEP[chk_id]], f"{chk_id} printed before its step stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1<S2<S3<S4<S5<S6<S7<S8<S9<S10<S11; checker lines %s; "
            "stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
