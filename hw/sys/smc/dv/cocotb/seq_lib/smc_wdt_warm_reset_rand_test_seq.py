# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded watchdog two-stage expiry to the warm reset, and the watchdog state after it.

Specs: hw/sys/smc/doc/clk_rst.adoc (Reset Architecture, the "SMC reset sources and effects"
table, Primary and Warm Reset), hw/sys/smc/regs/blocks/wdt/wdt.rdl (KEY, CMP, COUNT, CTRL),
hw/sys/smc/regs/blocks/cpu_ctrl/cpu_ctrl.rdl (WDT_TIMEOUT, RESET_CTRL) and
doc/programmer/src/smc-programming.adoc (Watchdog Timers).

The seed draws the core, the second-stage count `CPU_CTRL.WDT_TIMEOUT` and the first-stage
compare `CMP`. The drawn core's watchdog is armed with `wdogrsten` and `wdogenalways` and left
unserviced. Every `clk_smc_i` rise from the arming to the release of the warm reset is sampled
on the timeout taps, the warm, fuse and primary resets, and the graded relations are read from
that record. `COUNT` is read once after the first timeout, before the warm reset, and must be
non-zero, so its reset-value compare after the release tells a reset from a kept value. After the
release the drawn core's `CTRL`, `COUNT` and `CMP` and `CPU_CTRL.WDT_TIMEOUT` are read back.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _WDT_H, cpu_ctrl_u32, reg_reset_word, smc_addr, wdt_u32
from .smc_csr_seq_utils import SmcCsrSeq

# wdt.rdl KEY: the magic key written before every other write of the block.
WDT_MAGIC_KEY = 0x51F15E
WDT_CTRL_ARM = wdt_u32("WDT__CTRL__WDOGRSTEN_bm") | wdt_u32("WDT__CTRL__WDOGENALWAYS_bm")
WDT_CTRL_IP0 = wdt_u32("WDT__CTRL__WDOGIP0_bm")
WDT_CTRL_RESET = reg_reset_word(_WDT_H, "WDT", "CTRL")
WDT_COUNT_RESET = wdt_u32("WDT__COUNT__WDOGCOUNT_reset")
WDT_CMP_RESET = wdt_u32("WDT__CMP__WDOGCMP0_reset")
WDT_TIMEOUT_RESET = cpu_ctrl_u32("CPU_CTRL__WDT_TIMEOUT__DATA_reset")
WDT_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
CORES = (0, 1, 2, 3)
ALL_CORES_RELEASED = (1 << len(CORES)) - 1

# Drawn ranges. CMP counts scaled cycles with wdogscale 0; both ranges keep the expiry inside
# its bounded waits and exclude the reset value of the register they are written to.
CMP_MIN, CMP_MAX = 0x40, 0x800
TIMEOUT_MIN, TIMEOUT_MAX = 0x40, 0x2000

FUSE_SENSE_BOUND = 200_000
CORE_RELEASE_BOUND = 2_000
FIRST_BOUND_PER_CMP = 8
FIRST_BOUND_FLOOR = 4_096
# smc-programming.adoc (Watchdog Timers): `CPU_CTRL.WDT_TIMEOUT` sets the countdown length in
# SMC clock cycles; the second timeout follows the first by that length within SECOND_SLACK.
SECOND_SLACK = 4
WARM_ASSERT_BOUND = 256
WARM_RELEASE_BOUND = 200_000
TAIL_CYCLES = 8

# Step 5 grades the record step 4 closed, with no simulation time of its own: its three
# checker lines are printed after the step 4 stamp and step 5 is not stamped.
STEPS = ("S1", "S2", "S3", "S4", "S6", "S7")
CHK_STEPS = (
    ("CHK-WWR-FIRST-NO-RESET", "S4"),
    ("CHK-WWR-SECOND-WARM", "S4"),
    ("CHK-WWR-WARM-TERMS", "S4"),
    ("CHK-WWR-STICKY", "S6"),
    ("CHK-WWR-STATE-XFREE", "S6"),
)
_TAPS = (
    "tb_wdt_first_timeout",
    "tb_wdt_second_timeout",
    "tb_rst_warm_smc_clk_n",
    "tb_fuse_reset_n",
    "rst_primary_smc_clk_no",
    "tb_wdt_first_timeout_seen",
    "tb_wdt_second_timeout_seen",
)
FIRST, SECOND, WARM, FUSE, PRIMARY, FIRST_SEEN, SECOND_SEEN = range(len(_TAPS))


FOUR_STATE_SIMULATORS = ("vcs", "xcelium", "xmsim", "ncsim", "questa", "modelsim", "riviera")


def four_state_simulator() -> bool:
    name = str(getattr(cocotb, "SIM_NAME", "") or "").lower()
    return any(sim in name for sim in FOUR_STATE_SIMULATORS)


class _TapRecorder:
    """Samples the timeout taps and the reset probes at every `clk_smc_i` rise."""

    def __init__(self) -> None:
        self.samples: list[tuple[int, ...]] = []
        self.running = True

    async def run(self) -> None:
        dut = cocotb.top
        while self.running:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            row = []
            for name in _TAPS:
                value = getattr(dut, name).value
                assert value.is_resolvable, f"{name} is X/Z ({value}) at sample {len(self.samples)}"
                row.append(int(value) & 1)
            self.samples.append(tuple(row))


class smc_wdt_warm_reset_rand_test_seq(SmcCsrSeq):
    """Drawn core, `WDT_TIMEOUT` and `CMP`; two-stage expiry, warm reset, state read after it."""

    def __init__(self, name: str = "smc_wdt_warm_reset_rand_test_seq", *, seed: int) -> None:
        super().__init__(name)
        self.seed = seed
        self.rng = random.Random(self.seed)
        self.core = -1
        self.timeout = 0
        self.cmp = 0
        self.rec: _TapRecorder | None = None
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str]] = []
        self.waits: list[str] = []
        self.idx: dict[str, int] = {}
        self.done = False

    # -- plumbing ---------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_lines.append((chk_id, step))
        cocotb.log.info("%s: %s", chk_id, text)

    def _drawn(self) -> str:
        return f"drawn=core {self.core} WDT_TIMEOUT 0x{self.timeout:x} CMP 0x{self.cmp:x}"

    def _wdt(self, reg: str) -> int:
        return smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE{self.core}_WDT_{reg}_BASE_ADDR")

    async def _access(self, name: str, addr: int, op: SmcSysAxiOp, data: int = 0) -> int:
        item = SmcSysAxiItem(f"{'rd' if op is SmcSysAxiOp.READ else 'wr'}_{name}")
        item.op, item.addr, item.length = op, addr, 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code == 0, f"{name}@0x{addr:x}: response {item.resp_code}, want OKAY"
        return int(item.rdata) if op is SmcSysAxiOp.READ else 0

    async def _rd(self, name: str, addr: int) -> int:
        return await self._access(name, addr, SmcSysAxiOp.READ)

    async def _wr(self, name: str, addr: int, data: int) -> None:
        await self._access(name, addr, SmcSysAxiOp.WRITE, data)

    async def _keyed(self, name: str, reg: str, data: int) -> None:
        await self._wr(f"WDT{self.core}_KEY_{name}", self._wdt("KEY"), WDT_MAGIC_KEY)
        await self._wr(f"WDT{self.core}_{name}", self._wdt(reg), data)

    async def _until(self, label: str, tap: int, level: int, start: int, bound: int) -> int:
        """Index of the first recorded sample at or after `start` with `tap` at `level`."""
        samples = self.rec.samples
        scan = start
        while True:
            while scan < len(samples) and scan - start <= bound:
                if samples[scan][tap] == level:
                    self.waits.append(f"{label}={scan - start}/{bound} clk_smc_i")
                    return scan
                scan += 1
            if scan - start > bound:
                raise AssertionError(
                    f"{label}: {_TAPS[tap]} not {level} within {bound} clk_smc_i rises of "
                    f"sample {start}; last sample {samples[-1]}; {self._drawn()}"
                )
            await RisingEdge(cocotb.top.clk_smc_i)

    # -- steps ------------------------------------------------------------

    async def _s1(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        for name in _TAPS + ("tb_cpu_core_resets_n", "tb_fuse_sense_done"):
            assert hasattr(dut, name), f"tb_top has no {name}"
        self.core = self.rng.choice(CORES)
        self.timeout = self.rng.randint(TIMEOUT_MIN, TIMEOUT_MAX)
        self.cmp = self.rng.randint(CMP_MIN, CMP_MAX)
        assert self.timeout != WDT_TIMEOUT_RESET and self.cmp != WDT_CMP_RESET
        assert TIMEOUT_MIN <= self.timeout <= TIMEOUT_MAX and CMP_MIN <= self.cmp <= CMP_MAX
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: core %d, CPU_CTRL.WDT_TIMEOUT 0x%x (range 0x%x..0x%x), "
            "CMP 0x%x (range 0x%x..0x%x)",
            self.seed,
            self.core,
            self.timeout,
            TIMEOUT_MIN,
            TIMEOUT_MAX,
            self.cmp,
            CMP_MIN,
            CMP_MAX,
        )
        cores = -1
        for _ in range(CORE_RELEASE_BOUND):
            cores = int(dut.tb_cpu_core_resets_n.value)
            if cores == ALL_CORES_RELEASED:
                break
            await RisingEdge(dut.clk_smc_i)
        assert cores == ALL_CORES_RELEASED, (
            f"tb_cpu_core_resets_n 0x{cores:x} after {CORE_RELEASE_BOUND} rises, want 0x"
            f"{ALL_CORES_RELEASED:x} (cpu_ctrl.rdl RESET_CTRL resets the four cores released)"
        )
        self.waits.append(f"cores_released<={CORE_RELEASE_BOUND} clk_smc_i")
        for name in ("tb_wdt_first_timeout", "tb_wdt_second_timeout"):
            assert int(getattr(dut, name).value) == 0, f"{name} high before arming"
        assert int(dut.tb_rst_warm_smc_clk_n.value) == 1, "warm reset asserted before arming"
        await self._wr("WDT_TIMEOUT", WDT_TIMEOUT, self.timeout)
        got = await self._rd("WDT_TIMEOUT_RB", WDT_TIMEOUT)
        assert got == self.timeout, f"WDT_TIMEOUT reads 0x{got:x}, wrote 0x{self.timeout:x}"
        self._mark("S1")

    async def _s2(self) -> None:
        self.rec = _TapRecorder()
        cocotb.start_soon(self.rec.run())
        await RisingEdge(cocotb.top.clk_smc_i)
        await self._keyed("CMP", "CMP", self.cmp)
        got = await self._rd(f"WDT{self.core}_CMP_RB", self._wdt("CMP"))
        assert got == self.cmp, f"CMP reads 0x{got:x}, wrote 0x{self.cmp:x}"
        await self._keyed("COUNT", "COUNT", 0)
        await self._keyed("CTRL", "CTRL", WDT_CTRL_ARM)
        self.idx["armed"] = len(self.rec.samples)
        ctrl = await self._rd(f"WDT{self.core}_CTRL_RB", self._wdt("CTRL"))
        assert ctrl & ~WDT_CTRL_IP0 == WDT_CTRL_ARM, (
            f"CTRL reads 0x{ctrl:08x} after the keyed write of 0x{WDT_CTRL_ARM:08x}"
        )
        self.idx["ctrl_rb"] = ctrl
        self._mark("S2")

    async def _s3(self) -> None:
        bound = FIRST_BOUND_PER_CMP * self.cmp + FIRST_BOUND_FLOOR
        i1 = await self._until("first_timeout", FIRST, 1, self.idx["armed"], bound)
        row = self.rec.samples[i1]
        assert row[SECOND] == 0, f"second timeout high on the first-timeout rise {i1}"
        assert row[WARM] == 1, f"warm reset asserted on the first-timeout rise {i1}"
        self.idx["first"] = i1
        count = await self._rd(f"WDT{self.core}_COUNT_PRE", self._wdt("COUNT"))
        self.idx["count_pre"] = count
        self.idx["count_pre_at"] = len(self.rec.samples)
        assert count != WDT_COUNT_RESET, (
            f"COUNT reads 0x{count:x} after the first timeout, its reset value: the compare after "
            f"the warm reset could not tell a reset from a kept value; {self._drawn()}"
        )
        self._mark("S3")

    async def _s4(self) -> None:
        i1 = self.idx["first"]
        i2 = await self._until("second_timeout", SECOND, 1, i1, self.timeout + SECOND_SLACK)
        i3 = await self._until("warm_assert", WARM, 0, i2, WARM_ASSERT_BOUND)
        i4 = await self._until("warm_release", WARM, 1, i3, WARM_RELEASE_BOUND)
        await ClockCycles(cocotb.top.clk_smc_i, TAIL_CYCLES)
        self.rec.running = False
        await RisingEdge(cocotb.top.clk_smc_i)
        self.idx.update(second=i2, warm_fall=i3, warm_rise=i4)
        self._mark("S4")

    async def _s5(self) -> None:
        s = self.rec.samples
        i1, i2, i3, i4 = (self.idx[k] for k in ("first", "second", "warm_fall", "warm_rise"))
        at = self.idx["count_pre_at"]
        assert at < i2, f"the COUNT read after the first timeout ended at sample {at}, second {i2}"
        early_low = [i for i in range(0, i2) if s[i][WARM] == 0]
        assert not early_low, f"warm reset low at samples {early_low[:8]} before the second {i2}"
        assert i2 - i1 >= self.timeout - SECOND_SLACK, (
            f"second timeout {i2 - i1} rises after the first, want WDT_TIMEOUT 0x{self.timeout:x} "
            f"({self.timeout}) within {SECOND_SLACK}"
        )
        self._chk(
            "S4",
            "CHK-WWR-FIRST-NO-RESET",
            f"first timeout latched at sample {i1} ({i1 - self.idx['armed']} rises after the "
            f"CTRL write) with tb_wdt_second_timeout 0 and tb_rst_warm_smc_clk_n 1, and "
            f"tb_rst_warm_smc_clk_n read 1 at all {i2} samples up to the second timeout; "
            f"{self._drawn()}",
        )
        self._chk(
            "S4",
            "CHK-WWR-SECOND-WARM",
            f"second timeout latched {i2 - i1} rises after the first, within {SECOND_SLACK} of "
            f"WDT_TIMEOUT 0x{self.timeout:x} ({self.timeout}) SMC clock cycles, "
            f"tb_rst_warm_smc_clk_n fell {i3 - i2} rises after it (bound {WARM_ASSERT_BOUND}) "
            f"and rose again {i4 - i3} rises later; {self._drawn()}",
        )
        bad = [i for i, row in enumerate(s) if row[FUSE] != 1 or row[PRIMARY] != 1]
        assert not bad, (
            f"tb_fuse_reset_n or rst_primary_smc_clk_no low at samples {bad[:8]} "
            f"({[s[i] for i in bad[:4]]})"
        )
        low = [i for i, row in enumerate(s) if row[WARM] == 0]
        assert low and min(low) >= i2, f"warm low at {low[:4]}, second timeout at {i2}"
        self._chk(
            "S4",
            "CHK-WWR-WARM-TERMS",
            f"over {len(s)} clk_smc_i rises tb_rst_warm_smc_clk_n read 0 at {len(low)} rises, "
            f"all at or after the second timeout (first low {min(low)}, second {i2}); "
            f"tb_fuse_reset_n and rst_primary_smc_clk_no read 1 at every rise; {self._drawn()}",
        )

    async def _s6(self) -> None:
        s = self.rec.samples
        i1, i2, i3 = self.idx["first"], self.idx["second"], self.idx["warm_fall"]
        last_high = i3 - 1
        drop = [i for i in range(i1, last_high + 1) if s[i][FIRST] != 1]
        assert not drop, (
            f"tb_wdt_first_timeout read 0 at samples {drop[:8]} between its latch {i1} and the "
            f"last warm-high sample {last_high}"
        )
        second_high = sum(1 for i in range(i2, i3) if s[i][SECOND] == 1)
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_SENSE_BOUND)
        self.waits.append(f"post_reset_fuse_sense_done<={FUSE_SENSE_BOUND} clk_smc_i")
        seen = int(dut.tb_wdt_second_timeout_seen.value)
        live = int(dut.tb_wdt_second_timeout.value)
        ctrl = await self._rd(f"WDT{self.core}_CTRL_POST", self._wdt("CTRL"))
        count = await self._rd(f"WDT{self.core}_COUNT_POST", self._wdt("COUNT"))
        cmp_ = await self._rd(f"WDT{self.core}_CMP_POST", self._wdt("CMP"))
        timeout = await self._rd("WDT_TIMEOUT_POST", WDT_TIMEOUT)
        self._mark("S6")
        self._chk(
            "S6",
            "CHK-WWR-STICKY",
            f"tb_wdt_first_timeout read 1 at all {last_high - i1 + 1} rises from its latch "
            f"{i1} to the last warm-high rise {last_high}; logged, not compared: "
            f"tb_wdt_second_timeout read 1 at {second_high} of the {i3 - i2} rises from its "
            f"rise to the warm reset, tb_wdt_second_timeout_seen {seen}, tb_wdt_second_timeout "
            f"{live} after the release; {self._drawn()}",
        )
        assert ctrl == WDT_CTRL_RESET, f"CTRL 0x{ctrl:x} after the warm reset, want 0"
        assert count == WDT_COUNT_RESET, f"COUNT 0x{count:x} after the warm reset, want 0"
        assert cmp_ == WDT_CMP_RESET, f"CMP 0x{cmp_:x} after the warm reset, want 0x1000"
        assert timeout == self.timeout, (
            f"WDT_TIMEOUT 0x{timeout:x} after the warm reset, want the programmed "
            f"0x{self.timeout:x}"
        )
        if four_state_simulator():
            xnote = (
                "four-state simulator: every read bit resolved (the AXI master converts the "
                "read data to an integer, which fails on an unknown bit)"
            )
        else:
            xnote = (
                "X resolution printed, not graded: it is graded on a four-state simulator only, "
                "and none is in the scheduled runs; the values compared"
            )
        self._chk(
            "S6",
            "CHK-WWR-STATE-XFREE",
            f"after the release CTRL 0x{ctrl:x}, COUNT 0x{count:x}, CMP 0x{cmp_:x} equal the "
            f"wdt.rdl reset values 0x{WDT_CTRL_RESET:x}, 0x{WDT_COUNT_RESET:x}, "
            f"0x{WDT_CMP_RESET:x} (before the reset CTRL read 0x{self.idx['ctrl_rb']:x}, CMP "
            f"0x{self.cmp:x} and COUNT 0x{self.idx['count_pre']:x}, read after the first timeout "
            f"and required non-zero, the read ending at sample {self.idx['count_pre_at']} before "
            f"the second timeout at {self.idx['second']}) and CPU_CTRL.WDT_TIMEOUT 0x{timeout:x} "
            f"equals the programmed value "
            f"(reset 0x{WDT_TIMEOUT_RESET:x}); {xnote}; {self._drawn()}",
        )

    async def _s7(self) -> None:
        await self._wr("WDT_TIMEOUT_RESTORE", WDT_TIMEOUT, WDT_TIMEOUT_RESET)
        got = await self._rd("WDT_TIMEOUT_RESTORE_RB", WDT_TIMEOUT)
        assert got == WDT_TIMEOUT_RESET, f"WDT_TIMEOUT restore reads 0x{got:x}"
        self._mark("S7")
        bound = self.cfg.axi_timeout_ns
        self.waits.append(f"axi_access<={bound} ns per access ({self.accesses} accesses)")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; first-timeout bound %d * CMP + %d from the "
            "arming, second-timeout bound WDT_TIMEOUT + %d, warm assert %d and release %d "
            "clk_smc_i rises; expiry raises AssertionError",
            len(self.waits),
            "; ".join(self.waits),
            FIRST_BOUND_PER_CMP,
            FIRST_BOUND_FLOOR,
            SECOND_SLACK,
            WARM_ASSERT_BOUND,
            WARM_RELEASE_BOUND,
        )
        self._nonvac()

    def _nonvac(self) -> None:
        assert [st for st, _ in self.steps] == list(STEPS), f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert self.chk_lines == list(CHK_STEPS), f"checker lines {self.chk_lines}"
        s = self.rec.samples
        changed = {
            name: len({row[tap] for row in s}) == 2
            for name, tap in (("first", FIRST), ("second", SECOND), ("warm", WARM))
        }
        assert all(changed.values()), f"taps that never changed in the pass: {changed}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; stamps %s; checker lines %s; both timeout taps and "
            "the warm reset changed over %d samples; %s",
            " < ".join(STEPS),
            ",".join(str(ps) for ps in stamps),
            ",".join(c for c, _ in self.chk_lines),
            len(s),
            self._drawn(),
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        self.done = True
