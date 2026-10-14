# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PRIMARY OCTS count progression and 64-bit COUNT readout over timer_count_o.

Sources: system_timer_octs architecture.adoc and interface.adoc, system_timer_octs.rdl.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

_P = "SMC_TOP_SMC_SYSTEM_TIMER_OCTS_"
_TIMER_START = smc_addr(_P + "TIMER_START_BASE_ADDR")
_CTRL = smc_addr(_P + "CTRL_BASE_ADDR")
_STATUS = smc_addr(_P + "STATUS_BASE_ADDR")
_PRESET_LO = smc_addr(_P + "TIMER_PRESET_LO_BASE_ADDR")
_PRESET_HI = smc_addr(_P + "TIMER_PRESET_HI_BASE_ADDR")
_COUNT_LO = smc_addr(_P + "TIMER_COUNT_LO_BASE_ADDR")
_COUNT_HI = smc_addr(_P + "TIMER_COUNT_HI_BASE_ADDR")
_GPIO_ENABLE = smc_addr(_P + "TIMER_GPIO_ENABLE_BASE_ADDR")
_CREDIT_EXPIRED = smc_addr(_P + "CREDIT_EXPIRED_BASE_ADDR")

_MODE = 0x1
_RUNNING = 0x10
_M64 = (1 << 64) - 1
_RELOAD_SPAN = 0x40
_WRAP_RISE_BOUND = 48 + 64
_STEP_IDS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
_CHK_ORDER = (
    ("CHK-OCTS-NEVER-RUN", "S1"),
    ("CHK-OCTS-PRESET-LOAD-COUNT", "S3"),
    ("CHK-OCTS-NO-STOP", "S6"),
    ("CHK-OCTS-COUNT-PORT-REGISTER", "S7"),
    ("CHK-OCTS-COUNT-CARRY", "S8"),
    ("CHK-OCTS-COUNT-WRAP", "S9"),
    ("CHK-OCTS-ZERO-PRESET-START", "S10"),
    ("CHK-OCTS-ROLE-PERSISTS", "S10"),
    ("CHK-OCTS-EXPIRED-PRIMARY-ZERO", "S11"),
)


class smc_octs_primary_count_test_seq(SmcCsrSeq):
    """Sample timer_count_o at every clk_smc_i rise while the PRIMARY runs, and read COUNT."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.samples: list[int] = []
        self.steps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int]] = []

    async def _monitor(self) -> None:
        clk = cocotb.top.clk_smc_i
        net = cocotb.top.timer_count
        while True:
            await RisingEdge(clk)
            value = net.value
            assert value.is_resolvable, f"timer_count has X/Z at sample {len(self.samples)}"
            self.samples.append(int(value))

    async def _until(self, target: int, what: str) -> None:
        """Wait, bounded by the missing rise count plus 8, until `target` samples exist."""
        clk = cocotb.top.clk_smc_i
        bound = max(target - len(self.samples), 0) + 8
        for _ in range(bound):
            if len(self.samples) >= target:
                return
            await ClockCycles(clk, 1)
        assert len(self.samples) >= target, (
            f"{what}: {len(self.samples)} of {target} samples after {bound} rises; "
            f"last count 0x{self.samples[-1]:x}"
        )

    async def _window(self, count: int, what: str) -> tuple[int, list[int]]:
        """Return the index of the next rise and the `count` samples from it."""
        start = len(self.samples)
        await self._until(start + count, what)
        return start, self.samples[start : start + count]

    async def _stepping(self, before_idx: int, post_idx: int, count: int, what: str) -> None:
        """+1 per rise from the last rise before the write through `count` rises after it."""
        await self._until(post_idx + count, what)
        window = self.samples[before_idx - 1 : post_idx + count]
        for i in range(1, len(window)):
            diff = (window[i] - window[i - 1]) & _M64
            assert diff == 1, (
                f"{what}: step {i} is {diff} (0x{window[i - 1]:x} -> 0x{window[i]:x}); "
                f"samples {[hex(v) for v in window]}"
            )

    def _stamp(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str, *args: object) -> None:
        cocotb.log.info("%s: " + text, chk_id, *args)
        self.chk_lines.append((chk_id, len(self.steps)))

    async def _read(self, name: str, addr: int) -> int:
        value = await self.csr_read(name, addr)
        assert value is not None, f"{name} returned no data"
        return value

    async def _count(self, name: str) -> int:
        hi = await self._read(f"{name}_HI", _COUNT_HI)
        lo = await self._read(f"{name}_LO", _COUNT_LO)
        return (hi << 32) | lo

    def _reload_idx(self, start: int, window: list[int], preset: int, what: str) -> int:
        for i, value in enumerate(window):
            if (value - preset) & _M64 <= _RELOAD_SPAN:
                return start + i
        raise AssertionError(
            f"{what}: no sample in [0x{preset:x}, 0x{(preset + _RELOAD_SPAN) & _M64:x}] in "
            f"{len(window)} rises; samples {[hex(v) for v in window]}"
        )

    def _diffs_from(self, idx: int, count: int, what: str) -> int:
        """Every consecutive difference from idx over `count` rises is 1 mod 2**64."""
        seg = self.samples[idx : idx + count]
        for i in range(1, len(seg)):
            diff = (seg[i] - seg[i - 1]) & _M64
            assert diff == 1, f"{what}: difference {diff} at 0x{seg[i - 1]:x} -> 0x{seg[i]:x}"
        return len(seg) - 1

    async def _preset_start(self, lo: int, hi: int | None) -> int:
        await self.csr_write("PRESET_LO", _PRESET_LO, lo)
        if hi is not None:
            await self.csr_write("PRESET_HI", _PRESET_HI, hi)
        await self.csr_write("START", _TIMER_START, 1)
        return len(self.samples)

    async def body(self) -> None:
        dut = cocotb.top
        assert hasattr(dut, "timer_count"), "tb_top exports no timer_count"
        assert hasattr(dut, "clk_smc_i"), "tb_top exports no clk_smc_i"
        clk = dut.clk_smc_i
        monitor = cocotb.start_soon(self._monitor())
        modes: list[tuple[str, int]] = []

        # S1: never-run state.
        lo1 = await self._read("COUNT_LO_A", _COUNT_LO)
        hi1 = await self._read("COUNT_HI_A", _COUNT_HI)
        await ClockCycles(clk, 100)
        lo2 = await self._read("COUNT_LO_B", _COUNT_LO)
        hi2 = await self._read("COUNT_HI_B", _COUNT_HI)
        status = await self._read("STATUS_S1", _STATUS)
        _, win = await self._window(64, "S1 never-run window")
        assert (lo1, hi1, lo2, hi2) == (0, 0, 0, 0), (
            f"COUNT read 0x{hi1:x}_{lo1:08x} then 0x{hi2:x}_{lo2:08x} with no START written"
        )
        assert not status & _RUNNING, f"STATUS.RUNNING set before START (0x{status:08x})"
        assert all(v == 0 for v in win), f"count net left 0 before START: {win}"
        self._stamp("S1")
        self._chk(
            "CHK-OCTS-NEVER-RUN",
            "no START written: COUNT reads 0x0 and 0x0 100 cycles apart, STATUS=0x%08x "
            "(RUNNING 0, MODE %d), count net 0 at %d of %d rises",
            status,
            status & _MODE,
            len(win),
            len(win),
        )

        # S2: start from preset 0.
        start = await self._preset_start(0, 0)
        status_first = await self._read("STATUS_FIRST", _STATUS)
        status_first_idx = len(self.samples)
        await self._until(start + 64, "S2 window")
        win = self.samples[start : start + 64]
        status_64 = await self._read("STATUS_64TH", _STATUS)
        nz = next((i for i, v in enumerate(win) if v), None)
        assert nz is not None, f"count net stayed 0 over 64 rises after START; {win}"
        self._diffs_from(start + nz, 64 - nz, "S2 zero-preset run")
        assert status_64 & _RUNNING, f"STATUS.RUNNING clear at the 64th rise (0x{status_64:08x})"
        zero_start = (nz, win[nz], status_first, status_first_idx - start, status_64)
        status_s2 = await self._read("STATUS_S2", _STATUS)
        modes.append(("S2", status_s2 & _MODE))
        self._stamp("S2")

        # S3: reload on the running timer.
        start = await self._preset_start(0x1000, None)
        await self._until(start + 64, "S3 window")
        win = self.samples[start : start + 64]
        reload_idx = self._reload_idx(start, win, 0x1000, "S3")
        checked = self._diffs_from(reload_idx, start + 64 - reload_idx, "S3 reload run")
        status_s3 = await self._read("STATUS_S3", _STATUS)
        modes.append(("S3", status_s3 & _MODE))
        self._stamp("S3")
        self._chk(
            "CHK-OCTS-PRESET-LOAD-COUNT",
            "PRESET 0x1000 then START on a running timer: first sample in [0x1000, 0x1040] is "
            "0x%x at rise index %d of 64, %d consecutive differences all exactly 1 (owner value "
            "pending)",
            win[reload_idx - start],
            reload_idx - start,
            checked,
        )

        # S4: COUNT_LO reads bracketed by count net samples.
        brackets = []
        for i in range(8):
            before = self.samples[-1]
            lo = await self._read(f"COUNT_LO_BRK{i}", _COUNT_LO)
            after = self.samples[-1]
            b32, a32 = before & 0xFFFFFFFF, after & 0xFFFFFFFF
            assert b32 <= a32, f"read {i}: bracket wraps (0x{before:x}, 0x{after:x})"
            assert b32 <= lo <= a32, f"read {i}: COUNT_LO 0x{lo:x} outside [0x{b32:x}, 0x{a32:x}]"
            brackets.append((b32, lo, a32))
        self._stamp("S4")

        # S5: TIMER_START=0 keeps counting.
        before = len(self.samples)
        await self.csr_write("START0", _TIMER_START, 0)
        await self._stepping(before, len(self.samples), 32, "S5 after START=0")
        self._stamp("S5")

        # S6: CTRL, GPIO enable, preset writes keep counting.
        events = (
            ("CTRL", _CTRL, 0x0001_0210),
            ("GPIO_ENABLE_1", _GPIO_ENABLE, 1),
            ("GPIO_ENABLE_0", _GPIO_ENABLE, 0),
            ("PRESET_LO", _PRESET_LO, 0x9999),
        )
        for name, addr, data in events:
            before = len(self.samples)
            await self.csr_write(name, addr, data)
            await self._stepping(before, len(self.samples), 32, f"S6 after {name}")
        self._stamp("S6")
        self._chk(
            "CHK-OCTS-NO-STOP",
            "the count net stepped by exactly 1 at 32 of 32 consecutive rises after each of "
            "5 of 5 events: START=0, CTRL=0x00010210, GPIO_ENABLE 1, GPIO_ENABLE 0, "
            "PRESET_LO=0x9999 (no hold, no jump to the preset)",
        )

        # S7: HI, LO, HI triples.
        triples = []
        for i in range(3):
            before = self.samples[-1]
            hi_a = await self._read(f"TRIPLE{i}_HI_A", _COUNT_HI)
            lo = await self._read(f"TRIPLE{i}_LO", _COUNT_LO)
            hi_b = await self._read(f"TRIPLE{i}_HI_B", _COUNT_HI)
            after = self.samples[-1]
            comp = (hi_a << 32) | lo
            assert hi_a == hi_b, f"triple {i}: high halves 0x{hi_a:x} and 0x{hi_b:x} differ"
            assert before <= comp <= after, (
                f"triple {i}: composite 0x{comp:x} outside [0x{before:x}, 0x{after:x}]"
            )
            triples.append(comp)
        self._stamp("S7")
        self._chk(
            "CHK-OCTS-COUNT-PORT-REGISTER",
            "8 of 8 COUNT_LO reads inside their bracketing count net samples %s; 3 of 3 "
            "HI,LO,HI triples with equal high halves and composites %s inside their brackets",
            [(hex(b), hex(v), hex(a)) for b, v, a in brackets],
            [hex(c) for c in triples],
        )

        # S8: carry across 2**32.
        start = await self._preset_start(0xFFFF_FFF0, 0)
        await self._until(start + 48, "S8 window")
        win = self.samples[start : start + 48]
        reload_idx = self._reload_idx(start, win, 0xFFFF_FFF0, "S8")
        checked = self._diffs_from(reload_idx, start + 48 - reload_idx, "S8 carry run")
        crossing = [i for i, v in enumerate(win) if v == 1 << 32]
        assert crossing, f"count net never reached 0x100000000; {[hex(v) for v in win]}"
        hi_a = await self._read("CARRY_HI_A", _COUNT_HI)
        lo = await self._read("CARRY_LO", _COUNT_LO)
        hi_b = await self._read("CARRY_HI_B", _COUNT_HI)
        after = self.samples[-1]
        comp = (hi_a << 32) | lo
        assert hi_a == 1 and hi_b == 1, f"COUNT_HI reads 0x{hi_a:x}, 0x{hi_b:x} after the carry"
        assert (1 << 32) <= comp <= after, (
            f"composite 0x{comp:x} after the carry; count net 0x{after:x}"
        )
        status_s8 = await self._read("STATUS_S8", _STATUS)
        modes.append(("S8", status_s8 & _MODE))
        self._stamp("S8")
        self._chk(
            "CHK-OCTS-COUNT-CARRY",
            "preset 0xFFFFFFF0: the count net crossed 0x100000000 at rise index %d with %d "
            "consecutive differences all exactly 1; COUNT_HI read 0x%x/0x%x and COUNT_LO "
            "0x%x after the crossing",
            crossing[0],
            checked,
            hi_a,
            hi_b,
            lo,
        )

        # S9: wrap through 2**64 with STATUS reads on the way.
        await self.csr_write("PRESET_LO", _PRESET_LO, 0xFFFF_FFF0)
        await self.csr_write("PRESET_HI", _PRESET_HI, 0xFFFF_FFFF)
        await self.csr_write("START", _TIMER_START, 1)
        start = len(self.samples)
        status_reads = []
        while len(self.samples) < start + 48:
            b = len(self.samples)
            st = await self._read("STATUS_WRAP", _STATUS)
            status_reads.append((b - start, len(self.samples) - start, st))
            assert len(self.samples) - start <= _WRAP_RISE_BOUND, (
                f"S9: {len(self.samples) - start} rises passed, bound {_WRAP_RISE_BOUND}; "
                f"last STATUS 0x{st:08x}"
            )
        win = self.samples[start : start + 48]
        preset = 0xFFFF_FFFF_FFFF_FFF0
        reload_idx = self._reload_idx(start, win, preset, "S9")
        wraps = [i for i, v in enumerate(win) if v == 0]
        assert wraps, f"no wrap to 0 in 48 rises; {[hex(v) for v in win]}"
        checked = self._diffs_from(reload_idx, start + 48 - reload_idx, "S9 wrap run")
        near_zero = [
            (b, a, hex(st), (st & _RUNNING) >> 4)
            for b, a, st in status_reads
            if any(win[j] in (0, 1) for j in range(b, min(a + 1, 48)))
        ]
        status_s9 = await self._read("STATUS_S9", _STATUS)
        modes.append(("S9", status_s9 & _MODE))
        self._stamp("S9")
        self._chk(
            "CHK-OCTS-COUNT-WRAP",
            "preset 0xFFFFFFFFFFFFFFF0: the count net passed 0xFFFFFFFFFFFFFFFF to 0 at rise "
            "index %d with %d consecutive differences all exactly 1 mod 2^64; STATUS reads "
            "bracketing a 0 or 1 sample (before_idx, after_idx, STATUS, RUNNING) %s; "
            "STATUS.RUNNING after the run %d (owner value pending)",
            wraps[0],
            checked,
            near_zero,
            (status_s9 & _RUNNING) >> 4,
        )

        # S10: role persists; zero-preset evidence.
        final = await self._read("STATUS_FINAL", _STATUS)
        assert all(m == 0 for _, m in modes), f"STATUS.MODE set after a start: {modes}"
        self._stamp("S10")
        nz, first, st_first, st_first_off, st_64 = zero_start
        self._chk(
            "CHK-OCTS-ZERO-PRESET-START",
            "preset 0 then START: first nonzero sample 0x%x at rise index %d, every later "
            "difference exactly 1; STATUS 0x%08x read after rise index %d (RUNNING %d, owner value "
            "pending), "
            "STATUS 0x%08x at the 64th rise (RUNNING 1)",
            first,
            nz,
            st_first,
            st_first_off,
            (st_first & _RUNNING) >> 4,
            st_64,
        )
        self._chk(
            "CHK-OCTS-ROLE-PERSISTS",
            "STATUS.MODE read 0 after 4 of 4 starts %s; final STATUS 0x%08x MODE %d (owner value "
            "pending)",
            modes,
            final,
            final & _MODE,
        )

        # S11: credit expiry on the PRIMARY.
        expired = await self._read("CREDIT_EXPIRED", _CREDIT_EXPIRED)
        assert expired == 0, f"CREDIT_EXPIRED 0x{expired:08x} on a PRIMARY"
        self._stamp("S11")
        self._chk(
            "CHK-OCTS-EXPIRED-PRIMARY-ZERO",
            "CREDIT_EXPIRED read 0x%08x on the PRIMARY after the whole sequence",
            expired,
        )

        monitor.kill()
        self._fence()

    def _fence(self) -> None:
        ids = [s for s, _ in self.steps]
        assert ids == list(_STEP_IDS), f"step stamps {ids} not in expected order"
        times = [t for _, t in self.steps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        order = [c for c, _ in self.chk_lines]
        assert order == [c for c, _ in _CHK_ORDER], f"checker lines {order} out of order"
        step_pos = {s: i + 1 for i, s in enumerate(_STEP_IDS)}
        for (chk_id, printed_after), (_, step) in zip(self.chk_lines, _CHK_ORDER):
            assert printed_after >= step_pos[step], f"{chk_id} printed before its step {step}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            "NEVER-RUN, PRESET-LOAD-COUNT, NO-STOP, COUNT-PORT-REGISTER, COUNT-CARRY, "
            "COUNT-WRAP, ZERO-PRESET-START, ROLE-PERSISTS, EXPIRED-PRIMARY-ZERO in step order",
            order,
            [(s, t) for s, t in self.steps],
        )
