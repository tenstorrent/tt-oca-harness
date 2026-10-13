# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-core watchdog register decode, CTRL fields and CMP width over SEP_IN.

Contract SMC_POWER_TIMER_WDT_007, anchor smc_wdt_register_map_test.
Allocated scenarios: WDT-APERTURE.S2-S5, WDT-CTRL-FIELDS.S1-S4, WDT-CMP.S2.
Spec sources: hw/sys/smc/doc/watchdog.adoc (Operation, Register Access),
hw/sys/smc/regs/blocks/wdt/wdt.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

WDT_MAGIC_KEY = 0x51F15E
WDT_CORES = (0, 1, 2, 3)
WDT_CMP_RESET = 0x1000
WDT_KEY_UNLOCKED = 0x1
WDT_KEY_LOCKED = 0x0
WDT_CTRL_SCALE2 = 0x2
WDT_COUNT_PROBE = 0x0001_0000
WDT_FEED_VALUE = 0x0D09_F00D
WDT_CMP_STEP = 0x1111
WDT_CMP_DROPPED = 0x5555
WDT_CMP_PAIR_SPENT = 0x3000
WDT_INTERLEAVE_PAIRS = ((0, 3), (1, 2))
WDT_CMP_A_FIRST = 0x2AAA
WDT_CMP_B_FIRST = 0x2BBB
WDT_CMP_A_SECOND = 0x2CCC
WDT_CMP_MAX = 0xFFFF
WDT_FIELD_CELLS = [(f"wdogscale_{s}", s) for s in range(16)] + [
    ("wdogrsten", 0x100),
    ("wdogzerocmp", 0x200),
    ("wdogenalways", 0x1000),
    ("wdogcoreawake", 0x2000),
]
WDT_CLEAR_AFTER = (0x1000, 0x2000)
WDT_CTRL_RESERVED_ALL = 0xEFFF_CCF0
WDT_CTRL_ALL_ONES = 0xFFFF_FFFF
WDT_CTRL_IP_BIT = 1 << 28
WDT_CTRL_ALL_WRITABLE = 0x0000_330F
WDT_CMP_WIDE = 0xDEAD_A5A5
WDT_CMP_WIDE_READ = 0x0000_A5A5

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
CHECKERS = (
    ("CHK-WDT-CTRL-RESET", "S1"),
    ("CHK-WDT-OFFSET-DECODE", "S2"),
    ("CHK-WDT-APERTURE-ISOLATION", "S4"),
    ("CHK-WDT-APERTURE-INTERLEAVE", "S5"),
    ("CHK-WDT-CTRL-FIELD-READBACK", "S6"),
    ("CHK-WDT-CTRL-RESERVED", "S7"),
    ("CHK-WDT-CTRL-LOCKED-WRITE", "S8"),
    ("CHK-WDT-CMP-WIDE-WRITE", "S9"),
)


class smc_wdt_register_map_test_seq(SmcCsrSeq):
    """Four-core watchdog aperture, offset decode, CTRL field and CMP width proof."""

    def __init__(self, name: str = "smc_wdt_register_map_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.cmp_model = {core: WDT_CMP_RESET for core in WDT_CORES}

    def _reg(self, core: int, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    async def _unlock(self, label: str, core: int) -> None:
        await self.csr_write(label, self._reg(core, "KEY"), WDT_MAGIC_KEY)

    async def _keyed_write(self, label: str, core: int, reg: str, value: int) -> None:
        await self._unlock(f"{label}_KEY", core)
        await self.csr_write(label, self._reg(core, reg), value)

    async def _key(self, label: str, core: int, expected: int) -> None:
        await self.csr_read(label, self._reg(core, "KEY"), expected=expected)

    async def _s1(self) -> None:
        for core in WDT_CORES:
            await self.csr_read(f"S1_CTRL{core}", self._reg(core, "CTRL"), expected=0)
        self._step("S1")
        self._chk(
            "CHK-WDT-CTRL-RESET",
            "S1",
            "CTRL read 0x%08x on %d of %d cores before any write",
            0,
            len(WDT_CORES),
            len(WDT_CORES),
        )

    async def _s2(self) -> None:
        brackets = []
        for core in WDT_CORES:
            ctrl = self._reg(core, "CTRL")
            count = self._reg(core, "COUNT")
            await self._keyed_write(f"S2_C{core}_CTRL_WR", core, "CTRL", WDT_CTRL_SCALE2)
            await self.csr_read(f"S2_C{core}_CTRL_RB", ctrl, expected=WDT_CTRL_SCALE2)
            await self._keyed_write(f"S2_C{core}_COUNT_WR", core, "COUNT", WDT_COUNT_PROBE)
            c1 = await self.csr_read(f"S2_C{core}_COUNT_R1", count)
            sc = await self.csr_read(f"S2_C{core}_SCALED", self._reg(core, "SCALED_COUNT"))
            c2 = await self.csr_read(f"S2_C{core}_COUNT_R2", count)
            assert c1 >= WDT_COUNT_PROBE, (
                f"core {core} COUNT 0x{c1:x} after write of 0x{WDT_COUNT_PROBE:x} is below it"
            )
            lo, hi = c1 >> WDT_CTRL_SCALE2, c2 >> WDT_CTRL_SCALE2
            assert lo <= sc <= hi, (
                f"core {core} SCALED_COUNT 0x{sc:x} outside [0x{lo:x}, 0x{hi:x}] "
                f"(COUNT reads 0x{c1:x}, 0x{c2:x})"
            )
            await self._keyed_write(f"S2_C{core}_FEED_WR", core, "FEED", WDT_FEED_VALUE)
            fed = await self.csr_read(f"S2_C{core}_COUNT_FED", count)
            assert fed < WDT_COUNT_PROBE, f"core {core} COUNT 0x{fed:x} after FEED not below probe"
            await self.csr_read(f"S2_C{core}_COUNT_HI", self._reg(core, "COUNT_HI"), expected=0)
            await self._key(f"S2_C{core}_KEY", core, WDT_KEY_LOCKED)
            await self._keyed_write(f"S2_C{core}_CTRL_RESTORE", core, "CTRL", 0)
            await self._keyed_write(f"S2_C{core}_COUNT_RESTORE", core, "COUNT", 0)
            brackets.append(f"core{core}:0x{c1:x}<=0x{sc:x}<=0x{c2:x}(shifted 0x{lo:x},0x{hi:x})")
        self._step("S2")
        self._chk(
            "CHK-WDT-OFFSET-DECODE",
            "S2",
            "on %d of %d cores CTRL=0x%x read back, SCALED_COUNT within its COUNT bracket [%s], "
            "COUNT below 0x%08x after FEED 0x%08x, COUNT_HI and KEY read 0 (SF-014)",
            len(WDT_CORES),
            len(WDT_CORES),
            WDT_CTRL_SCALE2,
            "; ".join(brackets),
            WDT_COUNT_PROBE,
            WDT_FEED_VALUE,
        )

    async def _read_all_cmp(self, label: str, expected: dict[int, int]) -> None:
        for core in WDT_CORES:
            await self.csr_read(f"{label}_C{core}", self._reg(core, "CMP"), expected=expected[core])

    async def _s3(self) -> None:
        for core in WDT_CORES:
            value = WDT_CMP_STEP * (core + 1)
            await self._keyed_write(f"S3_C{core}_CMP_WR", core, "CMP", value)
            self.cmp_model[core] = value
            await self._read_all_cmp(f"S3_N{core}_RB", self.cmp_model)
        self._step("S3")

    async def _s4(self) -> None:
        pairs = 0
        for n in WDT_CORES:
            for m in WDT_CORES:
                if n == m:
                    continue
                tag = f"S4_{n}{m}"
                await self._unlock(f"{tag}_UNLOCK", n)
                await self._key(f"{tag}_KEY_M", m, WDT_KEY_LOCKED)
                await self.csr_write(f"{tag}_CMP_M_WR", self._reg(m, "CMP"), WDT_CMP_DROPPED)
                await self.csr_read(
                    f"{tag}_CMP_M_RB", self._reg(m, "CMP"), expected=self.cmp_model[m]
                )
                await self._key(f"{tag}_KEY_N", n, WDT_KEY_UNLOCKED)
                spent = WDT_CMP_PAIR_SPENT + 4 * n + m
                await self.csr_write(f"{tag}_CMP_N_WR", self._reg(n, "CMP"), spent)
                self.cmp_model[n] = spent
                await self.csr_read(f"{tag}_CMP_N_RB", self._reg(n, "CMP"), expected=spent)
                pairs += 1
        assert pairs == 12, f"{pairs} ordered pairs run, expected 12"
        self._step("S4")
        self._chk(
            "CHK-WDT-APERTURE-ISOLATION",
            "S4",
            "each CMP write to core N changed core N only (CMP reads 0x%04x*(k+1) for k<=N, "
            "0x%04x above) on %d of %d cores; after unlocking core N the KEY of every other "
            "core read 0x%x and its CMP write of 0x%04x was dropped, %d of 12 ordered pairs",
            WDT_CMP_STEP,
            WDT_CMP_RESET,
            len(WDT_CORES),
            len(WDT_CORES),
            WDT_KEY_LOCKED,
            WDT_CMP_DROPPED,
            pairs,
        )

    async def _s5(self) -> None:
        for a, b in WDT_INTERLEAVE_PAIRS:
            tag = f"S5_{a}{b}"
            cmp_a, cmp_b = self._reg(a, "CMP"), self._reg(b, "CMP")
            await self._unlock(f"{tag}_KEY_A", a)
            await self._unlock(f"{tag}_KEY_B", b)
            await self.csr_write(f"{tag}_CMP_A_WR", cmp_a, WDT_CMP_A_FIRST)
            await self.csr_write(f"{tag}_CMP_B_WR", cmp_b, WDT_CMP_B_FIRST)
            await self.csr_read(f"{tag}_CMP_A_RB", cmp_a, expected=WDT_CMP_A_FIRST)
            await self.csr_read(f"{tag}_CMP_B_RB", cmp_b, expected=WDT_CMP_B_FIRST)
            await self._unlock(f"{tag}_KEY_A2", a)
            await self.csr_write(f"{tag}_CMP_B_DROPPED", cmp_b, WDT_CMP_DROPPED)
            await self.csr_write(f"{tag}_CMP_A_WR2", cmp_a, WDT_CMP_A_SECOND)
            await self.csr_read(f"{tag}_CMP_A_RB2", cmp_a, expected=WDT_CMP_A_SECOND)
            await self.csr_read(f"{tag}_CMP_B_RB2", cmp_b, expected=WDT_CMP_B_FIRST)
            self.cmp_model[a] = WDT_CMP_A_SECOND
            self.cmp_model[b] = WDT_CMP_B_FIRST
        self._step("S5")
        self._chk(
            "CHK-WDT-APERTURE-INTERLEAVE",
            "S5",
            "on pairs %s KEY(A),KEY(B),write(A)=0x%04x,write(B)=0x%04x read both back; then "
            "KEY(A),write(B) dropped (B stayed 0x%04x),write(A)=0x%04x read back; %d of 2 pairs",
            list(WDT_INTERLEAVE_PAIRS),
            WDT_CMP_A_FIRST,
            WDT_CMP_B_FIRST,
            WDT_CMP_B_FIRST,
            WDT_CMP_A_SECOND,
            len(WDT_INTERLEAVE_PAIRS),
        )

    async def _s6(self) -> None:
        ctrl = self._reg(0, "CTRL")
        await self._keyed_write("S6_CMP_MAX", 0, "CMP", WDT_CMP_MAX)
        await self.csr_read("S6_CMP_MAX_RB", self._reg(0, "CMP"), expected=WDT_CMP_MAX)
        for name, value in WDT_FIELD_CELLS:
            await self._keyed_write(f"S6_{name}_WR", 0, "CTRL", value)
            await self.csr_read(f"S6_{name}_RB", ctrl, expected=value)
            if value in WDT_CLEAR_AFTER:
                await self._keyed_write(f"S6_{name}_CLEAR", 0, "CTRL", 0)
        await self._keyed_write("S6_CMP_RESTORE", 0, "CMP", WDT_CMP_RESET)
        self.cmp_model[0] = WDT_CMP_RESET
        self._step("S6")
        self._chk(
            "CHK-WDT-CTRL-FIELD-READBACK",
            "S6",
            "wdogscale 0..15, wdogrsten 0x%x, wdogzerocmp 0x%x, wdogenalways 0x%x and "
            "wdogcoreawake 0x%x each read back exactly the written value on core 0, %d of 20 cells",
            0x100,
            0x200,
            0x1000,
            0x2000,
            len(WDT_FIELD_CELLS),
        )

    async def _s7(self) -> None:
        await self._keyed_write("S7_CTRL_WR", 0, "CTRL", WDT_CTRL_RESERVED_ALL)
        await self.csr_read("S7_CTRL_RB", self._reg(0, "CTRL"), expected=0)
        self._step("S7")
        self._chk(
            "CHK-WDT-CTRL-RESERVED",
            "S7",
            "CTRL write of 0x%08x (reserved bits only) read back 0x%08x",
            WDT_CTRL_RESERVED_ALL,
            0,
        )

    async def _s8(self) -> None:
        ctrl = self._reg(0, "CTRL")
        await self.csr_write("S8_CTRL_LOCKED_WR", ctrl, WDT_CTRL_ALL_ONES)
        await self.csr_read("S8_CTRL_LOCKED_RB", ctrl, expected=0)
        await self._keyed_write("S8_CTRL_WR", 0, "CTRL", WDT_CTRL_ALL_ONES)
        value = await self.csr_read("S8_CTRL_RB", ctrl)
        masked = value & ~WDT_CTRL_IP_BIT
        assert masked == WDT_CTRL_ALL_WRITABLE, (
            f"CTRL 0x{value:08x} with bit 28 masked is 0x{masked:08x}, "
            f"expected 0x{WDT_CTRL_ALL_WRITABLE:08x}"
        )
        await self._keyed_write("S8_CTRL_RESTORE", 0, "CTRL", 0)
        self._step("S8")
        self._chk(
            "CHK-WDT-CTRL-LOCKED-WRITE",
            "S8",
            "locked CTRL write of 0x%08x read back 0x%08x; after KEY the same write read 0x%08x, "
            "0x%08x with bit 28 masked; bit 28 (wdogip0) read %d (SF-008)",
            WDT_CTRL_ALL_ONES,
            0,
            value,
            masked,
            (value >> 28) & 1,
        )

    async def _s9(self) -> None:
        cmp_ = self._reg(0, "CMP")
        await self._keyed_write("S9_CMP_WR", 0, "CMP", WDT_CMP_WIDE)
        await self.csr_read("S9_CMP_RB", cmp_, expected=WDT_CMP_WIDE_READ)
        await self._keyed_write("S9_CMP_RESTORE", 0, "CMP", WDT_CMP_RESET)
        await self.csr_read("S9_CMP_RESTORE_RB", cmp_, expected=WDT_CMP_RESET)
        self._step("S9")
        self._chk(
            "CHK-WDT-CMP-WIDE-WRITE",
            "S9",
            "32-bit CMP write of 0x%08x read back 0x%08x",
            WDT_CMP_WIDE,
            WDT_CMP_WIDE_READ,
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await self._s9()

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        self.assert_all_reachable(self.accesses, "WDT_REGISTER_MAP")
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, strictly increasing step "
            "stamps, each line printed after its own compare; checker lines %s; stamps %s",
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
