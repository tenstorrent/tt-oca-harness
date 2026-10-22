# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A software core-reset pulse, and a withheld reset whose timeout gives up.

`cpu_ctrl.rdl` gives each core a `RESET_CTRL.coreN_reset_pulse_start` field:
writing a one there triggers a reset pulse whose length comes from
`CORE_RESET_PULSE_COUNT`, and `CORE_RESET_PULSE_COUNT.core_resets_done` reads
low for a core while its pulse is running. From SEP_IN, core 1 is pulsed with
every level reset field left high, so the pulse is the only reset request. Its
`core_resets_done` bit must fall and come back, and the other cores' bits must
stay high. The request is gated on the cluster draining; `RESET_TIMEOUT` is set
to force mode for this leg, as the boot contract does, so the pulse is applied
either way.

The pulse is then timed at the cluster boundary. `post_reset_count` gives the
"Cycles (clk_smc), minus one, that a core reset pulse holds the core in reset",
so with `pre_reset_count` 2 and `post_reset_count` 3, core 1's reset on
`tb_cpu_core_resets_n` must read low for one run of exactly 4 `clk_smc_i`
cycles. Next, core 1's level reset is held and core 1 is pulsed again. "A 0 in
core1_reset_n_n0_scan holds the core in reset for the whole pulse", so core 1's
reset must read low at every sample from the pulse write until
`core_resets_done` returns.

`RESET_TIMEOUT.timeout_mode = 0` means "give up and report error (stay
withheld, do not apply)". With `timeout_value` 1 and core 1's level reset
requested, the request outlasts one cycle of pending drain, so `reset_timeout`
must read 1. The request is then released, and both status bits must clear.
The reset is applied once the drain completes, even in mode 0 (card 262,
design observation); the leaf reports `reset_applied` and does not grade it. `RESET_TIMEOUT`,
`CORE_RESET_PULSE_COUNT` and `RESET_CTRL` are restored and read back.

Before any write, `RESET_CTRL` must read `debug_reset_n` 0, `uncore_reset_n` 1,
every core level reset 1 and every pulse start 0, and `RESET_VECTOR[1..3]` must
read 0xC0040000 in bits 55:0; bits 63:56 are logged (SF-011). After the core-1
legs, cores 0, 2 and 3 are each pulsed with `CORE_RESET_PULSE_COUNT` at its
reset (pre 0x8, post 0x10) and `RESET_TIMEOUT` in force mode with value 0x40:
the core's `core_resets_done` bit must fall and return while the others read 1,
and its bit of `tb_cpu_core_resets_n` must read low for one run of 17 cycles
while the other cores stay out of reset. The delay from the write response to
the first low sample is logged (SF-012). Cores 2 and 3 are then held in level
reset and released, with `reset_applied` and the core's cluster reset following
each write. `debug_reset_n` is released and re-asserted with readback, and bit
17 of each of `RESET_VECTOR[1..3]` is set and cleared with every vector read
after each write. Every poll and cluster-reset wait of these legs is bounded and
fails with its last observed state.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import cpu_ctrl_u32, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
PULSE_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
CORE1_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_N_N0_SCAN_bm")
CORE1_PULSE = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_PULSE_START_N0_SCAN_bm")
DONE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bp")
DONE_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bm")
PRE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_bp")
POST_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bp")
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
TIMED_OUT = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")

FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM
GIVE_UP_AFTER_1 = 1 << VALUE_BP
_POLLS = 64

PRE_COUNT = 2
POST_COUNT = 3
SHORT_PULSE = (PRE_COUNT << PRE_BP) | (POST_COUNT << POST_BP)
# Long enough for SEP_IN polling to see core_resets_done low.
HELD_PULSE = (PRE_COUNT << PRE_BP) | (64 << POST_BP)
# Covers the SEP_IN write, a drain bounded by FORCE_AFTER_32 and the short pulse.
_TRACE_CYCLES = 256
_LEVEL_BOUND = 256
CORE1 = 0b0010

RESET_VECTOR = tuple(
    smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", n) for n in range(4)
)
DEBUG_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__DEBUG_RESET_N_N0_SCAN_bm")
UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_N = tuple(cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{n}_RESET_N_N0_SCAN_bm") for n in range(4))
CORE_PULSE = tuple(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{n}_RESET_PULSE_START_N0_SCAN_bm") for n in range(4)
)
ALL_CORES_N = CORE_N[0] | CORE_N[1] | CORE_N[2] | CORE_N[3]
ALL_PULSES = CORE_PULSE[0] | CORE_PULSE[1] | CORE_PULSE[2] | CORE_PULSE[3]
PRE_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__PRE_RESET_COUNT_bm")
POST_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__POST_RESET_COUNT_bm")

# cpu_ctrl.adoc reset values and the S4/S7 stimulus words of the contract.
VECTOR_RESET = 0xC004_0000
VECTOR_BIT17 = 0xC006_0000
VECTOR_FIELD = (1 << 56) - 1
PULSE_PRE_RESET = 0x8
PULSE_POST_RESET = 0x10
FORCE_AFTER_0X40 = (0x40 << VALUE_BP) | MODE_BM
PULSED_CORES = (0, 2, 3)
LEVEL_CORES = (2, 3)
ALL_CORES = 0b1111
# Done polls cover the drain bounded by FORCE_AFTER_0X40 plus a reset-count pulse.
_DONE_POLLS = 64
_APPLIED_POLLS = 64
_RESET_N_CYCLES = 256

FENCE = (
    "RESET-VALUES",
    "CORE1-LEGS",
    "PULSE-0-2-3",
    "LEVEL-2-3",
    "DEBUG-RESET",
    "VECTOR-BIT17",
)


@dataclass
class _BoundedWait:
    """One bounded wait: its bound, whether expiry is tolerated, and what it last saw."""

    name: str
    bound: int
    unit: str
    allow_timeout: bool = False
    timed_out: bool = False
    used: int = 0
    last: str = "not sampled"


class smc_cpu_reset_pulse_test_seq(SmcCsrSeq):
    """Pulse core 1 from SEP_IN, then let a withheld level reset time out in give-up mode."""

    def __init__(self, name: str = "smc_cpu_reset_pulse_test_seq") -> None:
        super().__init__(name)
        self.pulse_seen = False
        self.width_runs: list[int] | None = None
        self.held_samples: int | None = None
        self.give_up: tuple[int, int] | None = None
        self.waits: list[_BoundedWait] = []
        self.axi_items: list[SmcSysAxiItem] = []
        self.fence: list[tuple[str, int, int]] = []
        self.pulse_cores: dict[int, tuple[list[int], int]] = {}
        self.level_cores: dict[int, tuple[int, int, int, int]] = {}

    def _stamp(self, term: str, count: int) -> None:
        self.fence.append((term, count, int(get_sim_time("ns"))))

    async def _access(self, tag: str, addr: int, data: int | None = None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{'rd' if data is None else 'wr'}_{tag}")
        item.op = SmcSysAxiOp.READ if data is None else SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 8
        if data is not None:
            item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        self.axi_items.append(item)
        assert item.resp_ok and not item.timed_out, f"{tag}: SEP_IN access did not complete OKAY"
        return item

    async def _rd(self, tag: str, addr: int) -> int:
        return (await self._access(tag, addr)).rdata

    async def _wr(self, tag: str, addr: int, data: int) -> None:
        await self._access(tag, addr, data)

    async def _bounded(
        self, wait: _BoundedWait, probe: Callable[[int], Awaitable[tuple[bool, str]]]
    ) -> None:
        self.waits.append(wait)
        for i in range(wait.bound):
            done, wait.last = await probe(i)
            wait.used = i + 1
            if done:
                cocotb.log.info(
                    "WAIT %s: bound=%d %s allow_timeout=%s used=%d last=%s",
                    wait.name,
                    wait.bound,
                    wait.unit,
                    wait.allow_timeout,
                    wait.used,
                    wait.last,
                )
                return
        wait.timed_out = True
        cocotb.log.info(
            "WAIT %s: expired after bound=%d %s allow_timeout=%s last=%s",
            wait.name,
            wait.bound,
            wait.unit,
            wait.allow_timeout,
            wait.last,
        )
        if not wait.allow_timeout:
            raise AssertionError(
                f"{wait.name}: condition not met within {wait.bound} {wait.unit}; "
                f"last observed {wait.last}"
            )

    @staticmethod
    def _resets_n() -> int:
        value = cocotb.top.tb_cpu_core_resets_n.value
        assert value.is_resolvable, f"tb_cpu_core_resets_n is not resolvable: {value}"
        return int(value) & ALL_CORES

    async def _record_resets(self, samples: list[int]) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            samples.append(self._resets_n())

    async def _await_resets_n(self, name: str, mask: int, want: int) -> None:
        async def probe(_i: int) -> tuple[bool, str]:
            now = self._resets_n()
            if now & mask == want:
                return True, f"tb_cpu_core_resets_n=0x{now:x}"
            await RisingEdge(cocotb.top.clk_smc_i)
            return False, f"tb_cpu_core_resets_n=0x{now:x}"

        await self._bounded(_BoundedWait(name, _RESET_N_CYCLES, "clk_smc_i cycles"), probe)

    async def _pulse_core(self, ctrl: int, core: int) -> None:
        bit = 1 << core
        others = ALL_CORES & ~bit
        all_done = DONE_BM >> DONE_BP
        await self._await_resets_n(f"PULSE{core}_IDLE_RESETS_N", ALL_CORES, ALL_CORES)
        samples: list[int] = []
        recorder = cocotb.start_soon(self._record_resets(samples))
        await self._wr(f"PULSE{core}_START", RESET_CTRL, ctrl | CORE_PULSE[core])
        write_idx = len(samples)
        t_set = int(get_sim_time("ns"))
        seen = {"low": False, "t_low": 0}

        async def done_probe(i: int) -> tuple[bool, str]:
            word = await self._rd(f"PULSE{core}_DONE_{i}", PULSE_COUNT)
            bits = (word & DONE_BM) >> DONE_BP
            assert bits & others == others, (
                f"core {core} pulse: core_resets_done = 0x{bits:x}; the other cores' bits "
                f"must read 1 on every poll"
            )
            state = f"core_resets_done=0x{bits:x} seen_low={seen['low']}"
            if not bits & bit:
                if not seen["low"]:
                    seen["t_low"] = int(get_sim_time("ns"))
                seen["low"] = True
                return False, state
            return seen["low"], state

        await self._bounded(
            _BoundedWait(f"PULSE{core}_DONE_CYCLE", _DONE_POLLS, "SEP_IN reads"), done_probe
        )
        t_cleared = int(get_sim_time("ns"))
        await self._await_resets_n(f"PULSE{core}_RELEASED_RESETS_N", ALL_CORES, ALL_CORES)
        recorder.kill()
        final_done = (await self._rd(f"PULSE{core}_DONE_END", PULSE_COUNT) & DONE_BM) >> DONE_BP
        assert final_done == all_done, (
            f"core {core} pulse: core_resets_done 0x{final_done:x} at end"
        )
        t_checked = int(get_sim_time("ns"))
        await self._wr(f"PULSE{core}_START_CLR", RESET_CTRL, ctrl)

        mine = [(s >> core) & 1 for s in samples]
        runs = self._low_runs(mine)
        foreign = [i for i, s in enumerate(samples) if s & others != others]
        assert runs == [PULSE_POST_RESET + 1], (
            f"core {core} cluster reset low runs {runs} over {len(samples)} clk_smc_i samples; "
            f"post_reset_count {PULSE_POST_RESET} must hold the core in reset for one run of "
            f"{PULSE_POST_RESET + 1} cycles"
        )
        assert not foreign, (
            f"core {core} pulse: another core's cluster reset asserted at samples {foreign[:8]} "
            f"(values {[hex(samples[i]) for i in foreign[:8]]})"
        )
        first_low = mine.index(0)
        delay = first_low - write_idx
        cocotb.log.info(
            "PULSE core%d lifecycle: set@%dns observed(done low)@%dns cleared(done high)@%dns "
            "checked_cleared(done=0x%x resets_n=0x%x)@%dns",
            core,
            t_set,
            seen["t_low"],
            t_cleared,
            final_done,
            samples[-1],
            t_checked,
        )
        self.pulse_cores[core] = (runs, delay)

    async def _level_core(self, ctrl: int, core: int) -> None:
        bit = 1 << core
        others = ALL_CORES & ~bit
        samples: list[int] = []
        recorder = cocotb.start_soon(self._record_resets(samples))
        status_idle = await self._rd(f"LEVEL{core}_STATUS_IDLE", RESET_TIMEOUT)
        before = 1 if status_idle & APPLIED else 0
        await self._wr(f"LEVEL{core}_LO", RESET_CTRL, ctrl & ~CORE_N[core])
        t_set = int(get_sim_time("ns"))

        def applied_probe(want: int, phase: str):
            async def probe(i: int) -> tuple[bool, str]:
                word = await self._rd(f"LEVEL{core}_{phase}_{i}", RESET_TIMEOUT)
                return (1 if word & APPLIED else 0) == want, f"RESET_TIMEOUT=0x{word:x}"

            return probe

        await self._bounded(
            _BoundedWait(f"LEVEL{core}_APPLIED_1", _APPLIED_POLLS, "SEP_IN reads"),
            applied_probe(1, "APPLIED"),
        )
        await self._await_resets_n(f"LEVEL{core}_RESET_N_0", bit, 0)
        held = self._resets_n()
        t_observed = int(get_sim_time("ns"))
        await self._wr(f"LEVEL{core}_HI", RESET_CTRL, ctrl)
        t_cleared = int(get_sim_time("ns"))
        await self._bounded(
            _BoundedWait(f"LEVEL{core}_APPLIED_0", _APPLIED_POLLS, "SEP_IN reads"),
            applied_probe(0, "RELEASED"),
        )
        await self._await_resets_n(f"LEVEL{core}_RESET_N_1", bit, bit)
        released = self._resets_n()
        t_checked = int(get_sim_time("ns"))
        recorder.kill()
        foreign = [i for i, s in enumerate(samples) if s & others != others]
        assert before == 0, f"core {core} level leg: reset_applied already 1 before the request"
        assert held & others == others, (
            f"core {core} level reset: tb_cpu_core_resets_n=0x{held:x}, other cores in reset"
        )
        assert not foreign, (
            f"core {core} level leg: another core's cluster reset asserted at samples "
            f"{foreign[:8]} (values {[hex(samples[i]) for i in foreign[:8]]})"
        )
        cocotb.log.info(
            "LEVEL core%d lifecycle: set@%dns observed(applied=1 resets_n=0x%x)@%dns "
            "cleared@%dns checked_cleared(applied=0 resets_n=0x%x)@%dns",
            core,
            t_set,
            held,
            t_observed,
            t_cleared,
            released,
            t_checked,
        )
        self.level_cores[core] = (before, (held >> core) & 1, (released >> core) & 1, len(samples))

    @staticmethod
    def _ctrl_fields(word: int) -> tuple[int, int, int, int]:
        return (
            1 if word & DEBUG_N else 0,
            1 if word & UNCORE_N else 0,
            word & ALL_CORES_N,
            word & ALL_PULSES,
        )

    def _check_ctrl(self, word: int, want_debug: int, when: str) -> None:
        debug, uncore, cores, pulses = self._ctrl_fields(word)
        assert (debug, uncore, cores, pulses) == (want_debug, 1, ALL_CORES_N, 0), (
            f"RESET_CTRL 0x{word:x} {when}: debug_reset_n={debug} (want {want_debug}), "
            f"uncore_reset_n={uncore} (want 1), core reset_n=0x{cores:x} (want 0x{ALL_CORES_N:x}), "
            f"pulse starts=0x{pulses:x} (want 0)"
        )

    async def _done_bits(self, tag: str) -> int:
        word = await self.csr_read(tag, PULSE_COUNT, length=8)
        return (word & DONE_BM) >> DONE_BP

    async def _await_core1_done_cycle(self, tag: str) -> None:
        all_done = DONE_BM >> DONE_BP
        seen_low = False
        for i in range(_POLLS):
            bits = await self._done_bits(f"{tag}_DONE_{i}")
            assert bits | CORE1 == all_done, (
                f"CORE_RESET_PULSE_COUNT.core_resets_done = 0x{bits:x} while only core 1 was "
                f"pulsed; the other cores' bits must stay high"
            )
            if not bits & CORE1:
                seen_low = True
            elif seen_low:
                break
        assert seen_low, f"core 1's core_resets_done bit never fell within {_POLLS} reads"
        assert await self._done_bits(f"{tag}_DONE_END") == all_done, "core 1's pulse never ended"

    @staticmethod
    def _core1_reset_n() -> int:
        value = cocotb.top.tb_cpu_core_resets_n.value
        assert value.is_resolvable, f"tb_cpu_core_resets_n is not resolvable: {value}"
        return (int(value) & CORE1) >> 1

    async def _record_core1(self, samples: list[int]) -> None:
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            samples.append(self._core1_reset_n())

    async def _await_core1_reset_n(self, want: int, when: str) -> None:
        for _ in range(_LEVEL_BOUND):
            if self._core1_reset_n() == want:
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"core 1's cluster reset did not read {want} within {_LEVEL_BOUND} cycles {when}"
        )

    @staticmethod
    def _low_runs(samples: list[int]) -> list[int]:
        runs: list[int] = []
        length = 0
        for sample in samples:
            if sample == 0:
                length += 1
            elif length:
                runs.append(length)
                length = 0
        if length:
            runs.append(length)
        return runs

    async def _pulse(self, ctrl: int) -> None:
        all_done = DONE_BM >> DONE_BP
        assert await self._done_bits("PULSE_DONE_IDLE") == all_done, "a core reset already running"
        await self.csr_write("PULSE_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("PULSE_CORE1", RESET_CTRL, ctrl | CORE1_PULSE, length=8)
        await self._await_core1_done_cycle("PULSE")
        self.pulse_seen = True

    async def _pulse_width(self, ctrl: int) -> None:
        all_done = DONE_BM >> DONE_BP
        await self.csr_write("WIDTH_COUNT", PULSE_COUNT, SHORT_PULSE, length=8)
        await self.csr_write("WIDTH_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self._await_core1_reset_n(1, "before the timed pulse")
        samples: list[int] = []
        recorder = cocotb.start_soon(self._record_core1(samples))
        await self.csr_write("WIDTH_CORE1", RESET_CTRL, ctrl | CORE1_PULSE, length=8)
        await ClockCycles(cocotb.top.clk_smc_i, _TRACE_CYCLES)
        recorder.kill()
        assert await self._done_bits("WIDTH_DONE_END") == all_done, (
            f"core 1's timed pulse had not ended {_TRACE_CYCLES} cycles after its write"
        )
        runs = self._low_runs(samples)
        assert runs == [POST_COUNT + 1], (
            f"core 1's cluster reset low runs {runs} over {len(samples)} clk_smc_i samples; "
            f"post_reset_count {POST_COUNT} must hold the core in reset for one run of "
            f"{POST_COUNT + 1} cycles"
        )
        self.width_runs = runs

    async def _pulse_held(self, ctrl: int) -> None:
        held = ctrl & ~CORE1_N
        await self.csr_write("HELD_COUNT", PULSE_COUNT, HELD_PULSE, length=8)
        await self.csr_write("HELD_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("HELD_CORE1_LO", RESET_CTRL, held, length=8)
        await self._await_core1_reset_n(0, "after core1_reset_n was written 0")
        samples: list[int] = []
        recorder = cocotb.start_soon(self._record_core1(samples))
        await self.csr_write("HELD_CORE1_PULSE", RESET_CTRL, held | CORE1_PULSE, length=8)
        await self._await_core1_done_cycle("HELD")
        recorder.kill()
        released = sum(samples)
        await self.csr_write("HELD_CORE1_HI", RESET_CTRL, ctrl, length=8)
        await self._await_core1_reset_n(1, "after core1_reset_n was written 1")
        assert released == 0, (
            f"core 1's cluster reset read 1 at {released} of {len(samples)} clk_smc_i samples "
            f"while core1_reset_n was 0 and core 1's pulse ran"
        )
        self.held_samples = len(samples)

    async def _give_up(self, ctrl: int) -> None:
        await self.csr_write("GIVEUP_TIMEOUT", RESET_TIMEOUT, GIVE_UP_AFTER_1, length=8)
        await self.csr_write("GIVEUP_CORE1_LO", RESET_CTRL, ctrl & ~CORE1_N, length=8)
        await ClockCycles(cocotb.top.clk_smc_i, 16)
        status = await self.csr_read("GIVEUP_STATUS", RESET_TIMEOUT, length=8)
        await self.csr_write("GIVEUP_CORE1_HI", RESET_CTRL, ctrl, length=8)
        for i in range(_POLLS):
            after = await self.csr_read(f"GIVEUP_RELEASED_{i}", RESET_TIMEOUT, length=8)
            if not after & (APPLIED | TIMED_OUT):
                break
        else:
            raise AssertionError(f"RESET_TIMEOUT 0x{after:x} did not clear after the release")
        self.give_up = (status, after)

    async def _reset_values(self) -> int:
        ctrl0 = await self._rd("S2_RESET_CTRL", RESET_CTRL)
        vectors = [await self._rd(f"S2_RESET_VECTOR_{n}", RESET_VECTOR[n]) for n in (1, 2, 3)]
        self._check_ctrl(ctrl0, 0, "after the cold reset")
        for n, word in zip((1, 2, 3), vectors):
            assert word & VECTOR_FIELD == VECTOR_RESET, (
                f"RESET_VECTOR[{n}] = 0x{word:x}; bits 55:0 must reset to 0x{VECTOR_RESET:x}"
            )
        self._stamp("RESET-VALUES", 1 + len(vectors))
        cocotb.log.info(
            "CHK-CPU-RST-VECTOR-RESET: vec1/2/3[55:0] = 0x%x/0x%x/0x%x (reset 0x%x); "
            "bits 63:56 measured (SF-011) = 0x%x/0x%x/0x%x",
            *(w & VECTOR_FIELD for w in vectors),
            VECTOR_RESET,
            *(w >> 56 for w in vectors),
        )
        return ctrl0

    async def _pulses_0_2_3(self, ctrl: int) -> None:
        counts = await self._rd("PULSES_COUNT_IDLE", PULSE_COUNT)
        pre = (counts & PRE_BM) >> PRE_BP
        post = (counts & POST_BM) >> POST_BP
        assert (pre, post) == (PULSE_PRE_RESET, PULSE_POST_RESET), (
            f"CORE_RESET_PULSE_COUNT 0x{counts:x}: pre {pre:#x} post {post:#x}, the pulse legs "
            f"need the reset counts pre {PULSE_PRE_RESET:#x} post {PULSE_POST_RESET:#x}"
        )
        await self._wr("PULSES_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_0X40)
        for core in PULSED_CORES:
            await self._pulse_core(ctrl, core)
        self._stamp("PULSE-0-2-3", len(self.pulse_cores))
        cocotb.log.info(
            "CHK-CPU-RST-PULSE-CORES: core0/2/3 each done 1->0->1 with the other done bits 1 on "
            "every poll; cluster reset low runs %s (post_reset_count 0x%x -> %d cycles), other "
            "cores held out of reset; pre-reset delay from write response to first low sample "
            "measured (SF-012) = %s clk_smc_i cycles",
            {c: r for c, (r, _d) in self.pulse_cores.items()},
            PULSE_POST_RESET,
            PULSE_POST_RESET + 1,
            {c: d for c, (_r, d) in self.pulse_cores.items()},
        )

    async def _levels_2_3(self, ctrl: int) -> None:
        await self._wr("LEVEL_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_0X40)
        for core in LEVEL_CORES:
            await self._level_core(ctrl, core)
        self._stamp("LEVEL-2-3", len(self.level_cores))
        cocotb.log.info(
            "CHK-CPU-RST-LEVEL-CORES: %s",
            "; ".join(
                f"core{c} applied {b}->1->0 reset 1->{h}->{r} ({n} samples, others held)"
                for c, (b, h, r, n) in self.level_cores.items()
            ),
        )

    async def _debug_reset(self, ctrl0: int) -> None:
        await self._wr("DEBUG_RELEASE", RESET_CTRL, ctrl0 | DEBUG_N)
        released = await self._rd("DEBUG_RELEASE_RB", RESET_CTRL)
        self._check_ctrl(released, 1, "after debug_reset_n was written 1")
        await self._wr("DEBUG_REASSERT", RESET_CTRL, ctrl0 & ~DEBUG_N)
        reasserted = await self._rd("DEBUG_REASSERT_RB", RESET_CTRL)
        self._check_ctrl(reasserted, 0, "after debug_reset_n was written 0")
        self._stamp("DEBUG-RESET", 3)
        reads = (ctrl0, released, reasserted)
        cocotb.log.info(
            "CHK-CPU-DBG-RST-REASSERT: dbg reset %s; uncore=%s cores=%s pulses=%s throughout "
            "(RESET_CTRL 0x%x / 0x%x / 0x%x)",
            " -> ".join(str(self._ctrl_fields(w)[0]) for w in reads),
            "/".join(str(self._ctrl_fields(w)[1]) for w in reads),
            "/".join(hex(self._ctrl_fields(w)[2]) for w in reads),
            "/".join(hex(self._ctrl_fields(w)[3] >> 4) for w in reads),
            *reads,
        )

    async def _vector_bit17(self) -> None:
        written = others = restores = 0
        for n in (1, 2, 3):
            await self._wr(f"VEC{n}_BIT17", RESET_VECTOR[n], VECTOR_BIT17)
            for m in (1, 2, 3):
                word = await self._rd(f"VEC{n}_BIT17_RD{m}", RESET_VECTOR[m])
                want = VECTOR_BIT17 if m == n else VECTOR_RESET
                assert word & VECTOR_FIELD == want, (
                    f"after RESET_VECTOR[{n}] <- 0x{VECTOR_BIT17:x}, RESET_VECTOR[{m}] = "
                    f"0x{word:x}; bits 55:0 must read 0x{want:x}"
                )
                if m == n:
                    written += 1
                else:
                    others += 1
            await self._wr(f"VEC{n}_RESTORE", RESET_VECTOR[n], VECTOR_RESET)
            word = await self._rd(f"VEC{n}_RESTORE_RB", RESET_VECTOR[n])
            assert word & VECTOR_FIELD == VECTOR_RESET, (
                f"RESET_VECTOR[{n}] = 0x{word:x} after the restore; bits 55:0 must read "
                f"0x{VECTOR_RESET:x}"
            )
            restores += 1
        self._stamp("VECTOR-BIT17", written + others + restores)
        cocotb.log.info(
            "CHK-CPU-RST-VECTOR-BIT17: %d writes, written==0x%x %d/3, %d/6 others==0x%x, "
            "%d/3 restores==0x%x",
            written,
            VECTOR_BIT17,
            written,
            others,
            VECTOR_RESET,
            restores,
            VECTOR_RESET,
        )

    def _timeout_paths(self) -> None:
        bounds = sorted({item.timeout_ns or self.cfg.axi_timeout_ns for item in self.axi_items})
        axi_allow = sum(1 for item in self.axi_items if item.allow_timeout)
        axi_expired = sum(1 for item in self.axi_items if item.timed_out)
        expired = [w.name for w in self.waits if w.timed_out]
        tolerant = [w.name for w in self.waits if w.allow_timeout]
        assert not expired and not tolerant and not axi_expired and not axi_allow, (
            f"bounded waits expired {expired} / tolerating expiry {tolerant}; SEP_IN accesses "
            f"expired {axi_expired} / tolerating expiry {axi_allow}"
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, bound/last-state per wait, %d expired: %s; "
            "%d SEP_IN accesses bound %s ns allow_timeout=%d timed_out=%d; expiry raises "
            "AssertionError with the last observed state",
            len(self.waits),
            len(expired),
            "; ".join(
                f"{w.name} bound={w.bound} {w.unit} allow_timeout={w.allow_timeout} "
                f"timed_out={w.timed_out} used={w.used} last={w.last}"
                for w in self.waits
            ),
            len(self.axi_items),
            bounds,
            axi_allow,
            axi_expired,
        )

    def _nonvac(self) -> None:
        terms = [t for t, _c, _ns in self.fence]
        assert terms == list(FENCE), f"fence terms {terms}, want {list(FENCE)}"
        zero = [t for t, c, _ns in self.fence if c <= 0]
        assert not zero, f"fence terms with zero count {zero}"
        times = [ns for _t, _c, ns in self.fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing {times}"
        cocotb.log.info(
            "CHK-NONVAC: %s (%s)",
            " < ".join(FENCE),
            ", ".join(f"{t} count={c} t={ns}ns" for t, c, ns in self.fence),
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        ctrl0 = await self._reset_values()
        ctrl = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL, length=8)
        timeout = await self.csr_read("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, length=8)
        counts = await self.csr_read("PULSE_COUNT_IDLE", PULSE_COUNT, length=8)
        assert ctrl & CORE1_N and not ctrl & CORE1_PULSE, f"RESET_CTRL 0x{ctrl:x} not idle"

        await self._pulse(ctrl)
        cocotb.log.info(
            "CHK-CPU-RST-PULSE: a RESET_CTRL write with core 1's pulse field set and every "
            "level reset high dropped core 1's core_resets_done bit and raised it again; "
            "the other cores' bits stayed high"
        )

        await self._pulse_width(ctrl)
        cocotb.log.info(
            "CHK-CPU-RST-PULSE-WIDTH: with pre_reset_count %d and post_reset_count %d, core 1's "
            "cluster reset read low for runs %s",
            PRE_COUNT,
            POST_COUNT,
            self.width_runs,
        )

        await self._pulse_held(ctrl)
        cocotb.log.info(
            "CHK-CPU-RST-PULSE-HELD: core 1's cluster reset read 0 at all %d clk_smc_i samples "
            "of a pulse run with core1_reset_n held 0",
            self.held_samples,
        )

        await self._give_up(ctrl)
        status, _after = self.give_up
        assert status & TIMED_OUT, (
            f"RESET_TIMEOUT 0x{status:x}: core 1's level reset was still pending past a "
            f"timeout_value of 1 cycle, yet reset_timeout is clear"
        )
        cocotb.log.info(
            "CHK-CPU-RST-GIVEUP: core 1's level reset under timeout_mode 0, timeout_value 1 "
            "read RESET_TIMEOUT 0x%x (reset_timeout=%d, reset_applied=%d); released, both "
            "status bits cleared",
            status,
            1 if status & TIMED_OUT else 0,
            1 if status & APPLIED else 0,
        )

        await self.csr_write("RESET_TIMEOUT_RESTORE", RESET_TIMEOUT, timeout, length=8)
        await self.csr_read("RESET_TIMEOUT_RESTORE_RB", RESET_TIMEOUT, length=8, expected=timeout)
        await self.csr_write("PULSE_COUNT_RESTORE", PULSE_COUNT, counts, length=8)
        await self.csr_read("PULSE_COUNT_RESTORE_RB", PULSE_COUNT, length=8, expected=counts)
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl)
        self._stamp("CORE1-LEGS", 4)

        await self._pulses_0_2_3(ctrl)
        await self._levels_2_3(ctrl)
        await self._debug_reset(ctrl0)
        await self._vector_bit17()

        await self._wr("S8_RESET_TIMEOUT_RESTORE", RESET_TIMEOUT, timeout)
        restored = await self._rd("S8_RESET_TIMEOUT_RESTORE_RB", RESET_TIMEOUT)
        assert restored == timeout, (
            f"RESET_TIMEOUT 0x{restored:x} after the restore; want 0x{timeout:x}"
        )
        final_ctrl = await self._rd("S8_RESET_CTRL_RB", RESET_CTRL)
        self._check_ctrl(final_ctrl, 0, "at the end of the leaf")
        self._timeout_paths()
        self._nonvac()
