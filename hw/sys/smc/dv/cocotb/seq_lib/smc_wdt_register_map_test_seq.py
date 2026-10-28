# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-core watchdog register decode, CTRL fields and CMP width over SEP_IN.

Spec sources: hw/sys/smc/doc/watchdog.adoc (Operation, Register Access),
hw/sys/smc/regs/blocks/wdt/wdt.rdl.
"""

from __future__ import annotations

import math
import os
import random

import cocotb
from cocotb.utils import get_sim_time
from env.smc_env_cfg import measure_clock_period_ns

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
WDT_REGISTER_MAP_ACCESSES = 287

# S10, the drawn strobed walk (watchdog.adoc, Register Access): a write acts
# only when its byte enables cover the width the register requires, and a
# narrower one answers OKAY and changes nothing.
WDT_REGS = ("CTRL", "COUNT", "COUNT_HI", "SCALED_COUNT", "FEED", "KEY", "CMP")
WDT_FULL_WIDTH = ("COUNT", "COUNT_HI", "FEED", "KEY")
WDT_LOW_HALF = ("SCALED_COUNT", "CMP")
WDT_CTRL_RSTEN = 0x100
WDT_CTRL_ENABLES = 0x3000
WDT_COUNT_MASK = 0x7FFF_FFFF
WDT_CMP_MASK = 0xFFFF
WDT_MASK_MIN = 1
WDT_MASK_MAX = 0xF
WDT_EFFECTIVE_CORES = 2
WDT_SCALE_MASK = 0xF
WDT_SCALED_MASK = 0xFFFF

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")
CHECKERS = (
    ("CHK-WDT-CTRL-RESET", "S1"),
    ("CHK-WDT-OFFSET-DECODE", "S2"),
    ("CHK-WDT-APERTURE-ISOLATION", "S4"),
    ("CHK-WDT-APERTURE-INTERLEAVE", "S5"),
    ("CHK-WDT-CTRL-FIELD-READBACK", "S6"),
    ("CHK-WDT-CTRL-RESERVED", "S7"),
    ("CHK-WDT-CTRL-LOCKED-WRITE", "S8"),
    ("CHK-WDT-CMP-WIDE-WRITE", "S9"),
    ("CHK-WDT-DRAWN-STROBE-WALK", "S10"),
)


def _effective(reg: str, mask: int) -> bool:
    if reg in WDT_FULL_WIDTH:
        return mask == WDT_MASK_MAX
    if reg in WDT_LOW_HALF:
        return mask & 0x3 == 0x3
    return True


def _byte_mask(mask: int) -> int:
    return sum(0xFF << (8 * lane) for lane in range(4) if mask >> lane & 1)


def _class_masks(reg: str, eff: bool) -> list[int]:
    """The byte masks of one class of `reg`: effective (0xF for a full-width register; 3, 7, 0xB
    or 0xF for a half-word one; every mask for CTRL) or narrower (the rest of 1..15)."""
    return [m for m in range(WDT_MASK_MIN, WDT_MASK_MAX + 1) if _effective(reg, m) == eff]


def draw_walk(rng: random.Random) -> list[tuple[int, str, int, int]]:
    """The 28 (core, register) cells in a drawn order with a pattern and a byte mask each.

    The mask class is drawn per cell so that every register but CTRL takes both classes in
    every run: two of its four cores, drawn by `rng.sample`, take an effective mask and the
    other two a narrower one, the mask then drawn inside the class. Every CTRL byte is
    written on its own, so CTRL takes any mask of 1..15.
    """
    effective = {
        reg: set(rng.sample(WDT_CORES, WDT_EFFECTIVE_CORES)) for reg in WDT_REGS if reg != "CTRL"
    }
    cells = [(core, reg) for core in WDT_CORES for reg in WDT_REGS]
    rng.shuffle(cells)
    plan = []
    for core, reg in cells:
        pattern = rng.getrandbits(32)
        while (reg == "CTRL" and pattern & WDT_CTRL_RSTEN and pattern & WDT_CTRL_ENABLES) or (
            reg == "KEY" and pattern == WDT_MAGIC_KEY
        ):
            pattern = rng.getrandbits(32)
        if reg == "CTRL":
            mask = rng.randint(WDT_MASK_MIN, WDT_MASK_MAX)
        else:
            mask = rng.choice(_class_masks(reg, core in effective[reg]))
        plan.append((core, reg, pattern, mask))
    return plan


def effective_cores(plan: list[tuple[int, str, int, int]]) -> dict[str, list[int]]:
    """Per register but CTRL, the cores whose drawn mask is effective, from the plan alone."""
    cores: dict[str, list[int]] = {reg: [] for reg in WDT_REGS if reg != "CTRL"}
    for core, reg, _pattern, mask in plan:
        if reg != "CTRL" and _effective(reg, mask):
            cores[reg].append(core)
    return {reg: sorted(c) for reg, c in cores.items()}


def walk_accesses(plan: list[tuple[int, str, int, int]]) -> int:
    """Accesses the drawn walk issues, from the plan alone."""
    total = 0
    for _core, reg, _pattern, _mask in plan:
        total += 4
        if reg == "SCALED_COUNT":
            # The COUNT read before, and the COUNT and CTRL reads after, the strobed write.
            total += 3
        # CTRL: background write, read-back and second unlock before the strobed write, and
        # the restore write and read-back after it.
        total += {"CTRL": 6, "COUNT": 3, "CMP": 3}.get(reg, 0)
    return total


class smc_wdt_register_map_test_seq(SmcCsrSeq):
    """Four-core watchdog aperture, offset decode, CTRL field and CMP width proof."""

    def __init__(self, name: str = "smc_wdt_register_map_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.cmp_model = {core: WDT_CMP_RESET for core in WDT_CORES}
        self._walk_accesses = 0
        self.t_smc_ns = 0.0

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
            "CTRL read 0x%08x on %d of %d cores before any write (bench limit: 2-state zero init, "
            "a missing reset also reads 0)",
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
            "COUNT below 0x%08x after FEED 0x%08x, COUNT_HI and KEY read 0 (not specified, "
            "measured)",
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
            "0x%08x with bit 28 masked; bit 28 (wdogip0) read %d (not specified, measured)",
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

    async def _s10_cell(self, core: int, reg: str, pattern: int, mask: int) -> str:
        addr = self._reg(core, reg)
        key = self._reg(core, "KEY")
        eff = _effective(reg, mask)
        tag = f"S10_C{core}_{reg}"
        await self._unlock(f"{tag}_KEY", core)
        background = 0
        if reg == "CTRL":
            # A non-zero, non-arming background (no enable bit) in every writable byte,
            # written and read back before the strobed write, so a DUT that zero-fills the
            # bytes the strobe leaves out fails the compare below.
            background = ~pattern & WDT_CTRL_ALL_WRITABLE & ~WDT_CTRL_ENABLES
            for lane in (WDT_CTRL_ALL_WRITABLE & 0xFF, WDT_CTRL_ALL_WRITABLE & 0xFF00):
                if not background & lane:
                    background |= lane & -lane
            await self.csr_write(f"{tag}_BG_WR", addr, background)
            bg_rb = await self.csr_read(f"{tag}_BG_RB", addr)
            assert bg_rb & ~WDT_CTRL_IP_BIT == background, (
                f"{tag}: CTRL reads 0x{bg_rb:08x} after the background write 0x{background:08x}"
            )
            await self._unlock(f"{tag}_KEY_AGAIN", core)
        before_ps = get_sim_time("ps")
        before = (
            await self.csr_read(f"{tag}_COUNT_BEFORE", self._reg(core, "COUNT"))
            if reg in ("SCALED_COUNT", "COUNT")
            else None
        )
        write_ps = get_sim_time("ps")
        await self.csr_write_strobed(f"{tag}_WR", addr, pattern, mask)
        rb = await self.csr_read(f"{tag}_RB", addr)
        # clk_smc_i cycles between the issue of the write and the return of the read: the
        # bound on how far a counter set by the write can have counted on by the read.
        elapsed = math.ceil((get_sim_time("ps") - write_ps) / (self.t_smc_ns * 1000.0))
        if reg == "CTRL":
            # The enabled bytes take the pattern, the other bytes keep the background.
            lanes = _byte_mask(mask)
            want = ((pattern & lanes) | (background & ~lanes)) & WDT_CTRL_ALL_WRITABLE
            assert rb & ~WDT_CTRL_IP_BIT == want, (
                f"{tag}: CTRL reads 0x{rb:08x} (bit 28 masked 0x{rb & ~WDT_CTRL_IP_BIT:08x}) "
                f"after pattern 0x{pattern:08x} mask 0x{mask:x} over background "
                f"0x{background:08x}, expected 0x{want:08x}"
            )
            verdict = (
                f"rb=0x{rb:08x} == 0x{want:08x} with bit 28 masked (background 0x{background:08x} "
                f"in the bytes the strobe left out)"
            )
        elif reg == "CMP":
            want = pattern & WDT_CMP_MASK if eff else self.cmp_model[core]
            assert rb == want, f"{tag}: CMP reads 0x{rb:x}, expected 0x{want:x} (eff={eff})"
            verdict = f"rb=0x{rb:04x} == 0x{want:04x}"
        elif reg == "COUNT":
            if eff:
                # wdt.rdl: the counter is set to the written value, then counts on; a
                # dropped write leaves the count running on from `before` instead.
                want = pattern & WDT_COUNT_MASK
                counted = (rb - want) & WDT_COUNT_MASK
                assert counted <= elapsed, (
                    f"{tag}: COUNT reads 0x{rb:x}, not within {elapsed} clk_smc_i cycles above "
                    f"the pattern 0x{want:x} (0x{before:x} before the write)"
                )
                verdict = (
                    f"before=0x{before:08x} rb=0x{rb:08x} = 0x{want:08x} + {counted} "
                    f"<= {elapsed} cycles elapsed"
                )
            else:
                # wdt.rdl: "Any other write returns OKAY and changes nothing", and the
                # counter continues counting up from `before`, so the read-back is at most
                # the clk_smc_i cycles since the before-read above it.
                since = math.ceil((get_sim_time("ps") - before_ps) / (self.t_smc_ns * 1000.0))
                counted = (rb - before) & WDT_COUNT_MASK
                assert counted <= since, (
                    f"{tag}: COUNT reads 0x{rb:x} after a narrower write, not within {since} "
                    f"clk_smc_i cycles above 0x{before:x} read before it (changes nothing)"
                )
                verdict = (
                    f"before=0x{before:08x} rb=0x{rb:08x} = before + {counted} <= {since} "
                    f"cycles since the before-read (narrower write: changes nothing, counts on)"
                )
        elif reg == "COUNT_HI":
            assert rb == 0, f"{tag}: COUNT_HI reads 0x{rb:x}, expected 0 (no storage)"
            verdict = "rb=0 (no storage)"
        elif reg == "SCALED_COUNT":
            after = await self.csr_read(f"{tag}_COUNT_AFTER", self._reg(core, "COUNT"))
            ctrl = await self.csr_read(f"{tag}_CTRL", self._reg(core, "CTRL"))
            scale = ctrl & WDT_SCALE_MASK
            # wdt.rdl: the write changes nothing in COUNT, which counts on from `before`;
            # a write that leaked into COUNT would move it by more than the cycles since.
            since = math.ceil((get_sim_time("ps") - before_ps) / (self.t_smc_ns * 1000.0))
            counted = (after - before) & WDT_COUNT_MASK
            assert counted <= since, (
                f"{tag}: COUNT reads 0x{after:x} after the SCALED_COUNT write, not within "
                f"{since} clk_smc_i cycles above 0x{before:x} read before it (changes nothing)"
            )
            # The 16-bit field against the two COUNT reads shifted by wdogscale and masked
            # to 16 bits; the bracket wraps when the low half-word did between the reads.
            lo = (before >> scale) & WDT_SCALED_MASK
            hi = (after >> scale) & WDT_SCALED_MASK
            inside = lo <= rb <= hi if lo <= hi else rb >= lo or rb <= hi
            assert inside, (
                f"{tag}: SCALED_COUNT 0x{rb:x} outside the COUNT bracket [0x{before:x}, "
                f"0x{after:x}] shifted by wdogscale {scale} and masked to 16 bits "
                f"[0x{lo:x}, 0x{hi:x}]"
            )
            verdict = (
                f"rb=0x{rb:04x} inside [0x{lo:04x}, 0x{hi:04x}] (COUNT 0x{before:x}..0x{after:x} "
                f">> wdogscale {scale}, 16 bits; COUNT counted {counted} <= {since} cycles)"
            )
        elif reg == "FEED":
            verdict = f"rb=0x{rb:08x} printed (not specified)"
        else:  # KEY
            # wdt.rdl, KEY: "Reading this reg returns 1 if key has been written to it and it
            # is unlocked, 0 otherwise"; an effective write of a non-magic word leaves it
            # locked, a narrower one changes nothing.
            want = WDT_KEY_LOCKED if eff else WDT_KEY_UNLOCKED
            assert rb == want, f"{tag}: KEY reads {rb}, expected {want} (eff={eff})"
            verdict = f"rb={rb} == {want}"
        key_rb = await self.csr_read(f"{tag}_KEY_RB", key)
        if reg == "KEY":
            lock = f"KEY={key_rb} (the cell's own compare)"
        elif eff:
            # wdt.rdl: "Each effective write to a register other than KEY locks the watchdog".
            assert key_rb == WDT_KEY_LOCKED, (
                f"{tag}: KEY reads {key_rb} after an effective write, expected 0"
            )
            lock = f"KEY={key_rb} locked"
        else:
            # wdt.rdl: "Any other write returns OKAY and changes nothing, not even the lock".
            assert key_rb == WDT_KEY_UNLOCKED, (
                f"{tag}: KEY reads {key_rb} after a narrower write, expected 1 (the lock unchanged)"
            )
            lock = f"KEY={key_rb} still unlocked"
        if reg == "CTRL":
            await self._keyed_write(f"{tag}_RESTORE", core, "CTRL", 0)
            await self.csr_read(f"{tag}_RESTORE_RB", addr, expected=0)
        elif reg == "COUNT":
            await self._keyed_write(f"{tag}_RESTORE", core, "COUNT", 0)
        elif reg == "CMP":
            await self._keyed_write(f"{tag}_RESTORE", core, "CMP", WDT_CMP_RESET)
            await self.csr_read(f"{tag}_RESTORE_RB", addr, expected=WDT_CMP_RESET)
            self.cmp_model[core] = WDT_CMP_RESET
        return (
            f"C{core}.{reg} p=0x{pattern:08x} m=0x{mask:x} {'eff' if eff else 'narrow'} "
            f"{verdict} {lock}"
        )

    async def _s10(self) -> None:
        rng = random.Random(self.seed)
        plan = draw_walk(rng)
        eff_cores = effective_cores(plan)
        assert all(len(c) == WDT_EFFECTIVE_CORES for c in eff_cores.values()), (
            f"the draw gave {eff_cores}, not two effective cores per register"
        )
        eff_text = " ".join(f"{r}:C{','.join(map(str, c))}" for r, c in eff_cores.items())
        self.t_smc_ns = await measure_clock_period_ns(cocotb.top.clk_smc_i)
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: strobed walk %s; effective cores %s",
            self.seed,
            " ".join(f"C{c}.{r}:0x{p:08x}/0x{m:x}" for c, r, p, m in plan),
            eff_text,
        )
        start = self.accesses
        rows = [await self._s10_cell(*cell) for cell in plan]
        assert self.accesses - start == walk_accesses(plan), (
            f"S10 issued {self.accesses - start} accesses, the plan calls for {walk_accesses(plan)}"
        )
        self._step("S10")
        self._chk(
            "CHK-WDT-DRAWN-STROBE-WALK",
            "S10",
            "%d cells in the drawn order, each a keyed write of a drawn pattern under a drawn "
            "byte mask, every register but CTRL effective on two drawn cores (%s) and narrower "
            "on the other two: an effective write reads back as wdt.rdl states (CTRL the pattern "
            "in its enabled bytes over the non-zero, non-arming background the cell wrote first, "
            "masked to its fields, bit 28 masked, so a zero-fill of the unstrobed bytes fails; "
            "CMP[15:0]; COUNT the pattern plus at most the clk_smc_i cycles elapsed between the "
            "write and the read, COUNT read before the write too; COUNT_HI 0; KEY 0; "
            "SCALED_COUNT inside the two COUNT reads shifted by wdogscale and masked to 16 bits, "
            "COUNT itself moving by at most the cycles since the before-read) and a "
            "narrower write leaves CMP, "
            "KEY and the lock unchanged (KEY still reads 1, wdt.rdl: changes nothing, not even "
            "the lock) and COUNT reading the value read before it plus at most the clk_smc_i "
            "cycles since that read (the counter counts on); FEED is printed; CTRL, COUNT and "
            "CMP restored after each cell; cells: %s; drawn=seed %d walk %s",
            len(plan),
            eff_text,
            "; ".join(rows),
            self.seed,
            " ".join(f"C{c}.{r}:0x{p:08x}/0x{m:x}" for c, r, p, m in plan),
        )
        self._walk_accesses = walk_accesses(plan)

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
        await self._s10()

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        self.assert_all_reachable(
            WDT_REGISTER_MAP_ACCESSES + self._walk_accesses, "WDT_REGISTER_MAP"
        )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence checker lines in step order, strictly increasing step "
            "stamps, each line printed after its own compare; checker lines %s; stamps %s",
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
