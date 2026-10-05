# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cluster WDT first and second timeout, observed on the smc_wrapper pins.

The core-0 watchdog is armed over SEP_IN AXI with the magic-key protocol of
``hw/sys/smc/regs/blocks/wdt/wdt.rdl``: ``CTRL.wdogrsten`` makes the elapsed
compare drive the per-core ``wdt_reset`` output sticky, ``CTRL.wdogenalways``
lets the counter run whatever the core is doing, and ``CMP`` sets how many
scaled cycles elapse first. ``smc_base.sv`` ORs the four per-core outputs onto
``smc_wdt_first_timeout_o``; ``smc_cpu_ctrl_wrap.sv`` then counts
``CPU_CTRL.WDT_TIMEOUT`` (``cpu_ctrl.rdl``, reset ``0x4000``) further cycles
while that stays high and raises ``smc_wdt_second_timeout_o``, which
``smc_reset_ctrl.sv`` folds into the warm reset.

The sequence reads the two pins through the ``tb_wdt_*_seen`` latches of
``tb_top.sv`` rather than through any CSR: the second timeout resets the
cluster, so the WDT and both live pins clear again a few cycles later and only
the sticky pair survives to be read. Every expectation below is a DUT
observation with a bound:

* the first timeout is seen within ``FIRST_TIMEOUT_BOUND_CYCLES`` of arming,
  with the second timeout still clear on that same cycle;
* the second timeout is seen ``WDT_TIMEOUT`` cycles later, within
  ``SECOND_TIMEOUT_SLACK_CYCLES`` of the programmed stage-2 count;
* ``rst_warm`` then asserts and releases, after which both live pins read 0
  while both sticky latches still read 1.

``smc_cpu_ctrl_wrap.sv`` keeps a stage-2 count per core, so after core 0's
pass the same sequence runs on cores 1, 2 and 3 in turn, each after the
previous warm reset has released. The sticky latches are already set by then,
so those passes read the live pins, which the warm reset clears again.

Each holds before its ``CHK-WDT-TIMEOUT-{FIRST,SECOND,RESET,CORES}`` line is logged;
the SMC_VPLAN card of the same name declares the three.

``+smc_wdt_timeout_negative`` is the same run with one expectation inverted:
it requires the second timeout to be visible on the cycle the first one is,
before its stage-2 count could have elapsed. That run must FAIL; it is the
control that shows the second-timeout observer can complain.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

# wdt.rdl KEY: the magic key, written before every other write in the block.
WDT_MAGIC_KEY = 0x51F15E
# wdt.rdl CTRL: wdogrsten (bit 8) drives the sticky reset output on the
# elapsed compare; wdogenalways (bit 12) counts regardless of core state.
WDT_CTRL_RSTEN = 1 << 8
WDT_CTRL_ENALWAYS = 1 << 12
WDT_CTRL_ARM = WDT_CTRL_RSTEN | WDT_CTRL_ENALWAYS
# wdt.rdl CTRL.wdogip0 (bit 28) latches the elapsed compare; it may already be
# set by the time the readback of the arming write completes, so the readback
# is compared on the two enable bits only.
WDT_CTRL_IP0 = 1 << 28
# Scaled cycles (wdogscale = 0) until the first timeout.
WDT_CMP_FIRST = 0x0100
# cpu_ctrl.rdl WDT_TIMEOUT reset: stage-2 cycles between the two timeouts.
WDT_TIMEOUT_RESET = 0x4000

WDT_CORE = 0
# smc_cpu_ctrl_wrap.sv keeps a stage-2 count per core; the rest of the cluster.
OTHER_CORES = (1, 2, 3)

# Polling bounds, in clk_smc_i cycles. The first timeout needs CMP scaled
# cycles plus the arming write's completion. The second is WDT_TIMEOUT
# decrements plus the output flop in smc_cpu_ctrl_wrap.sv, so it lands one
# cycle past the count; the slack covers that flop with a few cycles to spare
# and the lower bound stays at the count itself. The warm reset follows within
# a synchroniser depth.
FIRST_TIMEOUT_BOUND_CYCLES = 4 * WDT_CMP_FIRST
SECOND_TIMEOUT_SLACK_CYCLES = 8
WARM_RESET_BOUND_CYCLES = 256
WARM_RELEASE_BOUND_CYCLES = 200_000

# Accesses issued by body(): per core, one CPU_CTRL read plus the arming writes
# and readbacks on that core's WDT block.
WDT_TIMEOUT_PIN_ACCESSES = 9 * (1 + len(OTHER_CORES))

NEGATIVE_PLUSARG = "smc_wdt_timeout_negative"


class smc_wdt_timeout_pin_test_seq(SmcCsrSeq):
    """Arm the core-0 WDT and watch both timeout pins at the DUT boundary."""

    def __init__(self, name: str = "smc_wdt_timeout_pin_test_seq") -> None:
        super().__init__(name)
        #: WDT_TIMEOUT as read back from CPU_CTRL before arming
        self.stage2_cycles: int | None = None
        #: cycles from the arming readback to the first timeout latch
        self.first_seen_cycles: int | None = None
        #: cycles from the first timeout latch to the second timeout latch
        self.second_gap_cycles: int | None = None
        #: cycles from the second timeout latch to rst_warm asserting
        self.warm_reset_cycles: int | None = None
        #: live pins after the warm reset released (first, second)
        self.live_after_reset: tuple[int, int] | None = None
        #: per other core: (first-timeout, second-gap, warm-reset) cycles
        self.other_cores: dict[int, tuple[int, int, int]] = {}

    def _reg(self, reg: str, core: int = WDT_CORE) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{core}_WDT_{reg}_BASE_ADDR")

    async def _arm(self, core: int) -> None:
        """Arm one core's WDT with the keyed CMP, COUNT and CTRL writes."""
        key = self._reg("KEY", core)
        # Each write needs its own unlock (wdt.rdl KEY): the block re-locks
        # after one write.
        await self.csr_write(f"WDT{core}_KEY_CMP", key, WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{core}_CMP", self._reg("CMP", core), WDT_CMP_FIRST)
        await self.csr_read(f"WDT{core}_CMP_RB", self._reg("CMP", core), expected=WDT_CMP_FIRST)
        await self.csr_write(f"WDT{core}_KEY_COUNT", key, WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{core}_COUNT", self._reg("COUNT", core), 0)
        await self.csr_write(f"WDT{core}_KEY_CTRL", key, WDT_MAGIC_KEY)
        await self.csr_write(f"WDT{core}_CTRL", self._reg("CTRL", core), WDT_CTRL_ARM)
        ctrl_rb = await self.csr_read(f"WDT{core}_CTRL_RB", self._reg("CTRL", core))
        assert (ctrl_rb & ~WDT_CTRL_IP0) == WDT_CTRL_ARM, (
            f"WDT{core} CTRL reads 0x{ctrl_rb:08x} after the keyed arming write, "
            f"expected 0x{WDT_CTRL_ARM:08x} (plus wdogip0)"
        )

    async def _other_core(self, core: int) -> tuple[int, int, int]:
        """Both stages and the warm reset for one of cores 1..3, on the live pins.

        The sticky latches are already set by core 0's pass, so this reads the
        live pins, which the warm reset clears.
        """
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        live = (int(dut.tb_wdt_first_timeout.value), int(dut.tb_wdt_second_timeout.value))
        assert live == (0, 0), f"live timeout pins {live} before core {core}'s WDT was armed"
        stage2 = await self.csr_read(
            f"CPU_CTRL_WDT_TIMEOUT_CORE{core}",
            smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR"),
            expected=WDT_TIMEOUT_RESET,
        )
        await self._arm(core)
        first = await self._wait_level(
            dut.tb_wdt_first_timeout, 1, FIRST_TIMEOUT_BOUND_CYCLES, f"core {core} first timeout"
        )
        assert int(dut.tb_wdt_second_timeout.value) == 0, (
            f"core {core}: second timeout high on the cycle the first rose, before its "
            f"stage-2 count of 0x{stage2:x} cycles could have run"
        )
        gap = await self._wait_level(
            dut.tb_wdt_second_timeout,
            1,
            stage2 + SECOND_TIMEOUT_SLACK_CYCLES,
            f"core {core} second timeout",
        )
        assert stage2 <= gap <= stage2 + SECOND_TIMEOUT_SLACK_CYCLES, (
            f"core {core}: second timeout {gap} cycles after the first; expected the "
            f"WDT_TIMEOUT stage-2 count 0x{stage2:x} (+{SECOND_TIMEOUT_SLACK_CYCLES})"
        )
        warm = await self._wait_level(
            dut.tb_rst_warm_smc_clk_n, 0, WARM_RESET_BOUND_CYCLES, f"core {core} rst_warm assert"
        )
        await self._wait_level(
            dut.tb_rst_warm_smc_clk_n, 1, WARM_RELEASE_BOUND_CYCLES, f"core {core} rst_warm release"
        )
        await ClockCycles(dut.clk_smc_i, 8)
        live = (int(dut.tb_wdt_first_timeout.value), int(dut.tb_wdt_second_timeout.value))
        assert live == (0, 0), (
            f"core {core}: live timeout pins {live} after the warm reset released"
        )
        return first, gap, warm

    @staticmethod
    async def _wait_level(sig, want: int, bound: int, label: str) -> int:
        clk = cocotb.top.clk_smc_i
        for i in range(bound):
            await RisingEdge(clk)
            if sig.value.is_resolvable and int(sig.value) == want:
                return i + 1
        raise AssertionError(f"{label}: not {want} within {bound} clk_smc_i cycles")

    async def body(self) -> None:
        dut = cocotb.top
        clk = dut.clk_smc_i
        negative = NEGATIVE_PLUSARG in cocotb.plusargs

        await self.wait_fuse_sense_done()

        # Entry state: nothing has timed out since cold reset.
        for name in (
            "tb_wdt_first_timeout",
            "tb_wdt_first_timeout_seen",
            "tb_wdt_second_timeout",
            "tb_wdt_second_timeout_seen",
        ):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable and int(sig.value) == 0, (
                f"{name} = {sig.value} before the WDT was armed"
            )

        stage2 = await self.csr_read(
            "CPU_CTRL_WDT_TIMEOUT",
            smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR"),
            expected=WDT_TIMEOUT_RESET,
        )
        self.stage2_cycles = stage2

        await self._arm(WDT_CORE)

        first_cycles = await self._wait_level(
            dut.tb_wdt_first_timeout_seen, 1, FIRST_TIMEOUT_BOUND_CYCLES, "first timeout"
        )
        self.first_seen_cycles = first_cycles
        second_at_first = int(dut.tb_wdt_second_timeout_seen.value)
        if negative:
            # Control: demands the stage-2 output before its count can have
            # run. A DUT (or an observer) that satisfies this is broken.
            assert second_at_first == 1, (
                f"negative control ({NEGATIVE_PLUSARG}): second timeout not "
                f"visible on the cycle the first one latched (stage-2 count "
                f"0x{stage2:x} cycles still to run) -- the observer can fail"
            )
        assert second_at_first == 0, (
            "second timeout latched on the same cycle as the first, before its "
            f"stage-2 count of 0x{stage2:x} cycles could have run"
        )
        cocotb.log.info(
            "CHK-WDT-TIMEOUT-FIRST: smc_wdt_first_timeout_o latched %d cycles "
            "after the core-%d arming readback (CMP=0x%x, CTRL=0x%x); "
            "smc_wdt_second_timeout_o still 0",
            first_cycles,
            WDT_CORE,
            WDT_CMP_FIRST,
            WDT_CTRL_ARM,
        )

        # The warm reset that follows the second timeout is observed as a
        # transition: released while the stage-2 count runs, asserted after it.
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 1, (
            "rst_warm already asserted on the cycle the first timeout latched, "
            f"with the stage-2 count of 0x{stage2:x} cycles still to run"
        )
        gap = await self._wait_level(
            dut.tb_wdt_second_timeout_seen,
            1,
            stage2 + SECOND_TIMEOUT_SLACK_CYCLES,
            "second timeout",
        )
        self.second_gap_cycles = gap
        assert stage2 <= gap <= stage2 + SECOND_TIMEOUT_SLACK_CYCLES, (
            f"second timeout latched {gap} cycles after the first; expected the "
            f"WDT_TIMEOUT stage-2 count 0x{stage2:x} (+{SECOND_TIMEOUT_SLACK_CYCLES})"
        )
        cocotb.log.info(
            "CHK-WDT-TIMEOUT-SECOND: smc_wdt_second_timeout_o latched %d cycles "
            "after the first (CPU_CTRL.WDT_TIMEOUT=0x%x)",
            gap,
            stage2,
        )

        # Downstream of the pin: the reset unit folds the second timeout into
        # the warm reset, which clears the WDT and drops both live pins.
        warm = await self._wait_level(
            dut.tb_rst_warm_smc_clk_n, 0, WARM_RESET_BOUND_CYCLES, "rst_warm assert"
        )
        self.warm_reset_cycles = warm
        await self._wait_level(
            dut.tb_rst_warm_smc_clk_n, 1, WARM_RELEASE_BOUND_CYCLES, "rst_warm release"
        )
        await ClockCycles(clk, 8)
        live = (int(dut.tb_wdt_first_timeout.value), int(dut.tb_wdt_second_timeout.value))
        self.live_after_reset = live
        assert live == (0, 0), (
            f"live timeout pins (first, second) = {live} after the warm reset "
            "released; the WDT did not clear"
        )
        assert int(dut.tb_wdt_first_timeout_seen.value) == 1
        assert int(dut.tb_wdt_second_timeout_seen.value) == 1
        cocotb.log.info(
            "CHK-WDT-TIMEOUT-RESET: rst_warm released on the first-timeout cycle, "
            "asserted %d cycles after the second timeout and released again; live "
            "pins back to %s, sticky latches still set",
            warm,
            live,
        )

        for core in OTHER_CORES:
            self.other_cores[core] = await self._other_core(core)
        cocotb.log.info(
            "CHK-WDT-TIMEOUT-CORES: cores %s each raised the first timeout, then the second "
            "after their stage-2 count, then the warm reset, on the live pins "
            "(first/second-gap/warm cycles: %s)",
            ", ".join(str(c) for c in OTHER_CORES),
            "; ".join(f"core {c}={f}/{g}/{w}" for c, (f, g, w) in self.other_cores.items()),
        )

        self.assert_all_reachable(WDT_TIMEOUT_PIN_ACCESSES, "WDT_TIMEOUT_PIN")
