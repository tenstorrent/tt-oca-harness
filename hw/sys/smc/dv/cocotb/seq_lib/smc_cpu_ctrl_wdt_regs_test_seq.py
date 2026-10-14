# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_wdt_regs_test: CPU_CTRL WDT and TEST_CTRL scalar registers.

Sources: hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

FUSE_SENSE_MAX_CYCLES = 200_000
WDT_PATTERNS = (0x0000_FFFF, 0xFFFF_0000, 0xA5A5_5A5A, 0xFFFF_FFFF)
TEST_CTRL_PATTERNS = (0xFFFF_FFFF, 0xAAAA_AAAA)
STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
FENCE_TERMS = {
    "S1": "BRINGUP_DONE",
    "S2": "WDT_RESET_COMPARED",
    "S3": "WDT_PATTERNS_COMPARED",
    "S4": "WDT_PULSE_BITS_COMPARED",
    "S5": "TEST_CTRL_COMPARED",
}
CHK_STEP = {
    "CHK-WDT-RESET": "S2",
    "CHK-WDT-RW": "S3",
    "CHK-WDTRST-PULSE": "S4",
    "CHK-TESTCTRL-RO": "S5",
}
CHK_ORDER = tuple(CHK_STEP)


class smc_cpu_ctrl_wdt_regs_test_seq(SmcCsrSeq):
    """Exercise WDT_TIMEOUT, WDT_TIMEOUT_RESET and TEST_CTRL over SEP_IN."""

    def __init__(self, name: str = "smc_cpu_ctrl_wdt_regs_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: set[str] = set()
        self._stamps: list[tuple[str, int]] = []
        self._chk_order: list[tuple[str, int]] = []
        self._waits: list[tuple[str, str, str]] = []
        self._last_access = "none"

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_order.append((chk_id, len(self._stamps)))
        self.chk_seen.add(chk_id)

    async def _rd(self, name: str, addr: int, expected: int | None = None) -> int:
        data = await self.csr_read(name, addr, expected=expected)
        self._last_access = f"rd {name}@0x{addr:08x} rdata=0x{data:08x} resp=OKAY"
        assert expected is None or data == expected, (
            f"{name}@0x{addr:08x}: read 0x{data:08x}, expected 0x{expected:08x}"
        )
        return data

    async def _wr(self, name: str, addr: int, data: int) -> None:
        await self.csr_write(name, addr, data)
        self._last_access = f"wr {name}@0x{addr:08x} wdata=0x{data:08x} resp=OKAY"

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "tb_fuse_sense_done"), "tb_fuse_sense_done not exported"
        axi_bound = self.cfg.axi_timeout_ns
        wdt = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
        wdt_rst = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR")
        test_ctrl = smc_addr("SMC_TOP_SMC_CPU_CTRL_TEST_CTRL_BASE_ADDR")
        wdt_reset = cpu_ctrl_u32("CPU_CTRL__WDT_TIMEOUT__DATA_reset")
        assert wdt_reset != 0, "generated WDT_TIMEOUT reset is zero; compare could not fail"
        bits = [
            cpu_ctrl_u32(f"CPU_CTRL__WDT_TIMEOUT_RESET__RESET_CYCLE_COUNT_{n}_bm") for n in range(4)
        ]
        all_bits = bits[0] | bits[1] | bits[2] | bits[3]

        # S1
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        sense = int(dut.tb_fuse_sense_done.value)
        assert sense == 1, "tb_fuse_sense_done low after the wait returned"
        self._waits.append(
            (
                "fuse_sense_done",
                f"{FUSE_SENSE_MAX_CYCLES}cyc(enforced-by=seq_lib/smc_base_test_seq.py)",
                f"tb_fuse_sense_done={sense}",
            )
        )
        self._stamp("S1")

        # S2
        first = await self._rd("WDT_TIMEOUT_RESET_VALUE", wdt, expected=wdt_reset)
        self._stamp("S2")
        self._chk(
            "CHK-WDT-RESET",
            f"WDT_TIMEOUT@0x{wdt:08x} read 0x{first:08x} == generated reset 0x{wdt_reset:08x}",
        )

        # S3
        seen = []
        for pat in WDT_PATTERNS:
            await self._wr("WDT_TIMEOUT_PATTERN", wdt, pat)
            got = await self._rd("WDT_TIMEOUT_PATTERN_RB", wdt, expected=pat)
            seen.append(f"0x{pat:08x}->0x{got:08x}")
        await self._wr("WDT_TIMEOUT_RESTORE", wdt, wdt_reset)
        restored = await self._rd("WDT_TIMEOUT_RESTORE_RB", wdt, expected=wdt_reset)
        self._stamp("S3")
        self._chk(
            "CHK-WDT-RW",
            f"WDT_TIMEOUT readbacks {' '.join(seen)}; restore 0x{wdt_reset:08x}->0x{restored:08x}",
        )

        # S4
        rows = []
        writes = [(f"BIT{n}", bits[n]) for n in range(4)] + [("ALL", all_bits)]
        for label, val in writes:
            await self._wr(f"WDT_TIMEOUT_RESET_{label}", wdt_rst, val)
            imm = await self._rd(f"WDT_TIMEOUT_RESET_{label}_IMMEDIATE", wdt_rst)
            after = await self._rd(f"WDT_TIMEOUT_RESET_{label}_AFTER", wdt_rst, expected=0)
            rows.append(f"{label}:wrote=0x{val:x},immediate=0x{imm:x},after=0x{after:x}")
        self._stamp("S4")
        self._chk(
            "CHK-WDTRST-PULSE",
            "WDT_TIMEOUT_RESET bits [3:0] read 0 after each write completed; immediate readback "
            "printed, not compared (owner value pending): " + " ".join(rows),
        )

        # S5
        base = await self._rd("TEST_CTRL_FIRST", test_ctrl)
        rows = []
        for pat in TEST_CTRL_PATTERNS:
            await self._wr("TEST_CTRL_PATTERN", test_ctrl, pat)
            got = await self._rd("TEST_CTRL_PATTERN_RB", test_ctrl, expected=base)
            rows.append(f"wrote=0x{pat:08x},read=0x{got:08x}")
        self._waits.append(("sep_in_access", f"{axi_bound}ns", self._last_access))
        self._stamp("S5")
        self._chk(
            "CHK-TESTCTRL-RO",
            f"TEST_CTRL@0x{test_ctrl:08x} first read 0x{base:08x} (value open, owner value "
            "pending) unchanged after writes: " + " ".join(rows),
        )

        expected = 1 + (2 * len(WDT_PATTERNS) + 2) + 3 * len(writes)
        expected += 1 + 2 * len(TEST_CTRL_PATTERNS)
        self.assert_all_reachable(expected, "CPU_CTRL_WDT")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={s}" for n, b, s in self._waits),
        )
        self._chk_order.append(("CHK-TIMEOUT-PATHS", len(self._stamps)))
        self.chk_seen.add("CHK-TIMEOUT-PATHS")
        self._fence()

    def _fence(self) -> None:
        steps = [s for s, _ in self._stamps]
        assert tuple(steps) == STEP_ORDER, f"step order {steps}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        order = [c for c, _ in self._chk_order]
        assert tuple(order[: len(CHK_ORDER)]) == CHK_ORDER, f"checker order {order}"
        for chk_id, n_stamps in self._chk_order:
            step = CHK_STEP.get(chk_id)
            if step:
                assert n_stamps == STEP_ORDER.index(step) + 1, f"{chk_id} printed before {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS[s] for s in steps),
            ",".join(order),
            ",".join(f"{s}={t}ps" for s, t in self._stamps),
        )
        self.chk_seen.add("CHK-NONVAC")
