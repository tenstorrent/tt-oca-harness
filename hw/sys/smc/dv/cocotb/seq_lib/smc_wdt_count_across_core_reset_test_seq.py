# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Watchdog 1's COUNT and CTRL across a core reset held through RESET_CTRL.

`clk_rst.adoc` (SMC Reset Distribution, NOTE) states that each watchdog gets
its core's reset "as a status input, not as a reset", that "while
`wdogcoreawake` is set and `wdogenalways` is clear, [it] stops counting while
the core is in reset", that "resetting a core therefore does not clear its
watchdog's `COUNT` or configuration registers", and that "only the uncore reset
clears them".

With `wdogcoreawake` alone, COUNT counts while core 1 is released, reads the
same value at three points inside a core 1 reset hold, and counts on from that
value after the release with CTRL unchanged. With `wdogenalways` also set the
in-hold reads keep increasing. An uncore reset pulse then returns COUNT and
CTRL to their `wdt.rdl` reset words.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import _WDT_H, cpu_ctrl_u32, reg_reset_word, smc_addr, wdt_u32
from .smc_csr_seq_utils import SmcCsrSeq

CHK_SURVIVES = "CHK-WDT-COUNT-SURVIVES-CORE-RESET"
CHK_FROZEN = "CHK-WDT-COUNT-FROZEN-IN-CORE-RESET"

WDT_MAGIC_KEY = 0x51F15E
WDT_ENALWAYS = wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
WDT_COREAWAKE = wdt_u32("WDT__CTRL__WDOGCOREAWAKE_bm")
WDT_CTRL_RESET = reg_reset_word(_WDT_H, "WDT", "CTRL")
WDT_COUNT_RESET = reg_reset_word(_WDT_H, "WDT", "COUNT")
COUNT_START = 0x0010_0000
CORE = 1
WDT_KEY = smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{CORE}_WDT_KEY_BASE_ADDR")
WDT_CTRL = smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{CORE}_WDT_CTRL_BASE_ADDR")
WDT_COUNT = smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{CORE}_WDT_COUNT_BASE_ADDR")

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
CORE_N = cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{CORE}_RESET_N_N0_SCAN_bm")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_LEVEL_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM

LEVEL_BOUND = 256
HOLD_GAP_CYCLES = 256
_POLLS = 64


def _hexes(reads: list[int]) -> str:
    return ",".join(f"0x{r:x}" for r in reads)


def _increasing(reads: list[int]) -> bool:
    return all(b > a for a, b in zip(reads, reads[1:]))


class smc_wdt_count_across_core_reset_test_seq(SmcCsrSeq):
    """Hold core 1 in reset around watchdog 1 COUNT reads, then pulse the uncore reset."""

    def __init__(self, name: str = "smc_wdt_count_across_core_reset_test_seq") -> None:
        super().__init__(name)
        self.passes: list[str] = []

    async def _wr(self, label: str, addr: int, data: int) -> None:
        await self.csr_write(f"WDT{CORE}_KEY_{label}", WDT_KEY, WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{CORE}_{label}", addr, data)

    async def _count(self, label: str) -> int:
        return await self.csr_read(f"WDT{CORE}_COUNT_{label}", WDT_COUNT)

    async def _window(self, label: str, n: int) -> list[int]:
        return [await self._count(f"{label}{i}") for i in range(n)]

    @staticmethod
    def _core_reset_n() -> int:
        value = cocotb.top.tb_cpu_core_resets_n.value
        assert value.is_resolvable, f"tb_cpu_core_resets_n is not resolvable: {value}"
        return (int(value) >> CORE) & 1

    async def _await_core(self, want: int, when: str) -> int:
        for rises in range(LEVEL_BOUND):
            if self._core_reset_n() == want:
                return rises
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"tb_cpu_core_resets_n[{CORE}] did not read {want} within {LEVEL_BOUND} rises {when}; "
            f"last {self._core_reset_n()}"
        )

    async def _await_status(self, tag: str, want_applied: bool) -> int:
        word = 0
        for i in range(_POLLS):
            word = await self.csr_read(f"{tag}_{i}", RESET_TIMEOUT, length=8)
            if bool(word & APPLIED) == want_applied:
                return word
        raise AssertionError(
            f"{tag}: RESET_TIMEOUT 0x{word:x}, reset_applied never read "
            f"{int(want_applied)} within {_POLLS} reads"
        )

    async def _hold(self, ctrl_idle: int, tag: str) -> tuple[int, list[int], int]:
        """Hold core 1 in reset; return (CTRL read in the hold, COUNT reads, rises to the hold)."""
        await self.csr_write(f"{tag}_CORE_LO", RESET_CTRL, ctrl_idle & ~CORE_N, length=8)
        lo_rises = await self._await_core(0, f"after core {CORE}'s level reset was written 0")
        ctrl_held = await self.csr_read(f"WDT{CORE}_CTRL_{tag}_HELD", WDT_CTRL)
        held = [await self._count(f"{tag}_HELD0"), await self._count(f"{tag}_HELD1")]
        await ClockCycles(cocotb.top.clk_smc_i, HOLD_GAP_CYCLES)
        held.append(await self._count(f"{tag}_HELD2"))
        still = self._core_reset_n()
        assert still == 0, f"{tag}: tb_cpu_core_resets_n[{CORE}] read {still} inside the hold"
        return ctrl_held, held, lo_rises

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        ctrl_idle = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout_idle = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        assert ctrl_idle & UNCORE_N and ctrl_idle & CORE_LEVEL_N == CORE_LEVEL_N, (
            f"RESET_CTRL 0x{ctrl_idle:x}: the uncore and every core are expected released at idle"
        )
        assert not timeout_idle & APPLIED, (
            f"RESET_TIMEOUT 0x{timeout_idle:x}: a reset is already applied"
        )
        await self.csr_write("TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)

        # S1: wdogcoreawake alone, core released: COUNT counts.
        await self._wr("S1_CTRL", WDT_CTRL, WDT_COREAWAKE)
        await self._wr("S1_COUNT", WDT_COUNT, COUNT_START)
        pre = await self._window("S1_PRE", 3)
        assert _increasing(pre), f"S1: COUNT not increasing with the core released: {_hexes(pre)}"
        step = max(b - a for a, b in zip(pre, pre[1:]))

        # S2: core 1 held: COUNT reads the same value at three points, CTRL unchanged.
        ctrl_held, held, lo_rises = await self._hold(ctrl_idle, "S2")
        assert ctrl_held == WDT_COREAWAKE, (
            f"S2: CTRL reads 0x{ctrl_held:x} inside the hold, want 0x{WDT_COREAWAKE:x}"
        )
        assert held[0] == held[1] == held[2], (
            f"{CHK_FROZEN} FAIL: COUNT moved inside the core {CORE} reset hold with "
            f"wdogcoreawake set and wdogenalways clear: reads {_hexes(held)} "
            f"({HOLD_GAP_CYCLES} clk_smc_i cycles between the second and third), released reads "
            f"{_hexes(pre)} advanced up to 0x{step:x} per read"
        )
        assert held[0] >= pre[-1], (
            f"S2: first in-hold read 0x{held[0]:x} below the last released read 0x{pre[-1]:x}"
        )

        # S3: release: COUNT counts on from the held value, CTRL unchanged.
        await self.csr_write("S3_CORE_HI", RESET_CTRL, ctrl_idle, length=8)
        hi_rises = await self._await_core(1, f"after core {CORE}'s level reset was released")
        ctrl_post = await self.csr_read(f"WDT{CORE}_CTRL_S3_POST", WDT_CTRL)
        post = await self._window("S3_POST", 3)
        assert _increasing(post), f"S3: COUNT not increasing after the release: {_hexes(post)}"
        assert post[0] >= held[2] and ctrl_post == WDT_COREAWAKE, (
            f"{CHK_SURVIVES} FAIL: after the core {CORE} reset COUNT reads 0x{post[0]:x} "
            f"(in-hold 0x{held[2]:x}) and CTRL 0x{ctrl_post:x} (want 0x{WDT_COREAWAKE:x})"
        )
        assert post[0] - held[2] <= 4 * step, (
            f"S3: first released read 0x{post[0]:x} is more than 4 steps (0x{step:x}) above the "
            f"in-hold value 0x{held[2]:x}"
        )

        # S4: wdogenalways also set: COUNT keeps counting inside the hold.
        await self._wr("S4_CTRL", WDT_CTRL, WDT_COREAWAKE | WDT_ENALWAYS)
        ctrl_held_always, held_always, _ = await self._hold(ctrl_idle, "S4")
        assert ctrl_held_always == WDT_COREAWAKE | WDT_ENALWAYS, (
            f"S4: CTRL reads 0x{ctrl_held_always:x} inside the hold"
        )
        assert _increasing(held_always), (
            f"S4: COUNT not increasing inside the hold with wdogenalways set: {_hexes(held_always)}"
        )
        await self.csr_write("S4_CORE_HI", RESET_CTRL, ctrl_idle, length=8)
        await self._await_core(1, f"after core {CORE}'s second release")
        cocotb.log.info(
            "%s PASS: wdogcoreawake alone on watchdog %d: released reads %s increasing; core %d "
            "held (tb_cpu_core_resets_n[%d] 0 after %d rises) COUNT read %s at three points, "
            "%d clk_smc_i cycles before the third, CTRL 0x%x; with wdogenalways also set the "
            "in-hold reads %s increase",
            CHK_FROZEN,
            CORE,
            _hexes(pre),
            CORE,
            CORE,
            lo_rises,
            _hexes(held),
            HOLD_GAP_CYCLES,
            ctrl_held,
            _hexes(held_always),
        )
        self.passes.append(CHK_FROZEN)

        # S5: the uncore reset clears COUNT and CTRL.
        count_before = await self._count("S5_BEFORE")
        ctrl_before = await self.csr_read(f"WDT{CORE}_CTRL_S5_BEFORE", WDT_CTRL)
        assert count_before != WDT_COUNT_RESET and ctrl_before != WDT_CTRL_RESET, (
            f"S5: COUNT 0x{count_before:x} or CTRL 0x{ctrl_before:x} already at its reset word"
        )
        await self.csr_write("S5_UNCORE_LO", RESET_CTRL, ctrl_idle & ~UNCORE_N, length=8)
        await self._await_status("S5_APPLIED", True)
        await self.csr_write("S5_UNCORE_HI", RESET_CTRL, ctrl_idle, length=8)
        await self._await_status("S5_RELEASED", False)
        await self._await_core(1, "after the uncore reset release")
        count_after = await self._count("S5_AFTER")
        ctrl_after = await self.csr_read(f"WDT{CORE}_CTRL_S5_AFTER", WDT_CTRL)
        assert count_after == WDT_COUNT_RESET and ctrl_after == WDT_CTRL_RESET, (
            f"{CHK_SURVIVES} FAIL: after the uncore reset COUNT reads 0x{count_after:x} and CTRL "
            f"0x{ctrl_after:x}, want the reset words 0x{WDT_COUNT_RESET:x} and "
            f"0x{WDT_CTRL_RESET:x}"
        )
        cocotb.log.info(
            "%s PASS: core %d released after %d rises: CTRL 0x%x unchanged and COUNT reads %s, "
            "the first >= the in-hold 0x%x and within 4 steps of 0x%x; the uncore reset pulse "
            "took COUNT 0x%x -> 0x%x and CTRL 0x%x -> 0x%x (reset words 0x%x / 0x%x)",
            CHK_SURVIVES,
            CORE,
            hi_rises,
            ctrl_post,
            _hexes(post),
            held[2],
            step,
            count_before,
            count_after,
            ctrl_before,
            ctrl_after,
            WDT_COUNT_RESET,
            WDT_CTRL_RESET,
        )
        self.passes.append(CHK_SURVIVES)

        await self.csr_write("TIMEOUT_RESTORE", RESET_TIMEOUT, timeout_idle, length=8)
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl_idle)
