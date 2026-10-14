# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP mailbox inputs tb_sep_mailbox_interrupts[7:0] into raw interrupt bits 263:256.

Spec sources: interrupts.adoc SMC indexed interrupt map table, SMC interrupts and PLIC;
port_table.adoc sep_mailbox_interrupts_i.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
RAW_SHIFT = 256
# TB ceiling in clk_smc_i rises for every pin-to-raw-bit wait; not a latency claim.
CEILING_RISES = 64
HOLD_RISES = 64
LONG_HOLD_RISES = 256
LATENCY_REPEATS = 8
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = ("CHK-SEPMBX-WALK", "CHK-SEPMBX-HOLD", "CHK-SEPMBX-SUBSETS", "CHK-SEPMBX-LATENCY-LOG")
_CHECK_STEP = ("S2", "S3", "S4", "S5")


class smc_sep_mbx_irq_vector_test_seq(SmcCsrSeq):
    """Drive the eight SEP mailbox inputs and compare the whole raw vector to the baseline."""

    def __init__(self, name: str = "smc_sep_mbx_irq_vector_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._base = 0
        self._pbase = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[int, int, int]:
        """Return (raw vector XOR baseline, peripheral XOR baseline, mailbox_irq_any)."""
        dut = cocotb.top
        vec = self._resolved(dut.tb_cpu_interrupts, label)
        per = self._resolved(dut.tb_peripheral_interrupts, label)
        anyb = self._resolved(dut.tb_mailbox_irq_any, label)
        return vec ^ self._base, per ^ self._pbase, anyb

    def _note(self, name: str, bound: int, diff: int, per: int, anyb: int, tail: str) -> None:
        self._waits[name] = (
            bound,
            f"xor>>256=0x{diff >> RAW_SHIFT:x} per=0x{per:x} any={anyb}{tail}",
        )

    def _drive(self, value: int, why: str) -> None:
        cocotb.top.tb_sep_mailbox_interrupts.value = value
        cocotb.log.info(
            "DRIVE tb_sep_mailbox_interrupts=0x%02x (%s) at %d ps",
            value,
            why,
            int(get_sim_time("ps")),
        )

    def _check_match(self, name: str, tag: str, target: int) -> tuple[int, int, int]:
        diff, per, anyb = self._sample(f"{name} {tag}")
        assert diff == target << RAW_SHIFT, (
            f"{name} {tag}: raw xor 0x{diff:x} != 0x{target << RAW_SHIFT:x}"
        )
        assert per & 0xFF == target, f"{name} {tag}: peripheral xor 0x{per:x} != 0x{target:x}"
        assert anyb == int((self._pbase & 0xFF) | target != 0), (
            f"{name} {tag}: mailbox_irq_any {anyb} vs inputs 0x{target:x}"
        )
        return diff, per, anyb

    async def _reach(self, name: str, prev: int, target: int) -> int:
        """Wait until the raw XOR equals target<<256; only bits of prev|target may differ."""
        bound = CEILING_RISES
        diff, per, anyb = self._sample(f"{name} entry")
        self._note(name, bound, diff, per, anyb, "")
        allowed = (prev | target) << RAW_SHIFT
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, per, anyb = self._sample(f"{name}[{n}]")
            self._note(name, bound, diff, per, anyb, f" after {n} rises")
            assert diff & ~allowed == 0, (
                f"{name}: raw bit outside prev|target moved, xor 0x{diff:x} "
                f"(prev 0x{prev:x} target 0x{target:x})"
            )
            keep = (prev & target) << RAW_SHIFT
            assert diff & keep == keep, f"{name}: raw bit dropped early, xor 0x{diff:x}"
            if diff == target << RAW_SHIFT:
                self._check_match(name, f"reached[{n}]", target)
                return n
        raise AssertionError(
            f"{name}: raw xor did not reach 0x{target << RAW_SHIFT:x} within {bound} clk_smc_i "
            f"rises (last xor 0x{diff:x} per=0x{per:x} any={anyb})"
        )

    async def _hold(self, name: str, target: int, rises: int = HOLD_RISES) -> None:
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            self._check_match(name, f"hold[{n}]", target)

    async def _transition(self, name: str, value: int, prev: int, hold: int = HOLD_RISES) -> int:
        await RisingEdge(cocotb.top.clk_smc_i)
        self._drive(value, name)
        rises = await self._reach(name, prev, value)
        await self._hold(name, value, hold)
        self.phases += 1
        return rises

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str) -> None:
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: raw xor 0x0 for %d rises", chk, HOLD_RISES)

    async def _walk(self) -> str:
        parts = []
        for k in range(8):
            up = await self._transition(f"WALK in{k} rise", 1 << k, 0)
            down = await self._transition(f"WALK in{k} fall", 0, 1 << k)
            parts.append(f"in{k}:{up}/{down}")
        self._log_legs(
            "CHK-SEPMBX-WALK",
            "tb_sep_mailbox_interrupts bit k driven 1",
            "tb_cpu_interrupts and tb_peripheral_interrupts rise at 256+k and k",
            "bit k driven 0",
        )
        return " ".join(parts)

    async def _hold_long(self) -> str:
        parts = []
        for k in (0, 7):
            up = await self._transition(f"HOLD in{k} rise", 1 << k, 0, LONG_HOLD_RISES)
            down = await self._transition(f"HOLD in{k} fall", 0, 1 << k)
            parts.append(f"in{k}: high after {up} rises, held {LONG_HOLD_RISES}, low after {down}")
        self._log_legs(
            "CHK-SEPMBX-HOLD", "input held 1", "raw bit 1 at each of 256 rises", "input driven 0"
        )
        return "; ".join(parts)

    async def _subsets(self) -> str:
        parts = []
        for subset in (0xFF, 0x55, 0xAA):
            up = await self._transition(f"SUBSET 0x{subset:02x} up", subset, 0)
            down = await self._transition(f"SUBSET 0x{subset:02x} clear", 0, subset)
            parts.append(f"0x{subset:02x}:{up}/{down}")
        remaining = await self._transition("DROP start 0xff", 0xFF, 0)
        cur = 0xFF
        for i in range(8):
            nxt = cur & ~(1 << i)
            r = await self._transition(f"DROP in{i} -> 0x{nxt:02x}", nxt, cur)
            parts.append(f"drop{i}->0x{nxt:02x}:{r}")
            cur = nxt
        self._log_legs(
            "CHK-SEPMBX-SUBSETS",
            "subset driven on tb_sep_mailbox_interrupts",
            "tb_cpu_interrupts raw xor equals subset<<256",
            "inputs dropped one at a time then all",
        )
        return f"0xff up after {remaining} rises; " + " ".join(parts)

    async def _edge_latency(self, value: int) -> int:
        """Return clk_smc_i rises from the pin edge to the raw bit 256 change."""
        await RisingEdge(cocotb.top.clk_smc_i)
        self._drive(value, f"latency edge to {value}")
        bound = CEILING_RISES
        name = f"LATENCY edge {value}"
        self._waits[name] = (bound, "no sample yet")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, per, anyb = self._sample(f"{name}[{n}]")
            self._note(name, bound, diff, per, anyb, f" after {n} rises")
            assert diff & ~(1 << RAW_SHIFT) == 0, f"{name}: other raw bit moved, xor 0x{diff:x}"
            if diff == value << RAW_SHIFT:
                self.phases += 1
                return n
        raise AssertionError(f"{name}: raw bit 256 did not change within {bound} rises")

    async def _latency(self) -> str:
        rise, fall = [], []
        for _ in range(LATENCY_REPEATS):
            rise.append(await self._edge_latency(1))
            await self._hold("LATENCY settle high", 1, 4)
            fall.append(await self._edge_latency(0))
            await self._hold("LATENCY settle low", 0, 4)
        assert len(rise) == len(fall) == LATENCY_REPEATS
        return (
            f"rise_rises={rise} min={min(rise)} max={max(rise)}; "
            f"fall_rises={fall} min={min(fall)} max={max(fall)}"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_sep_mailbox_interrupts",
            "tb_cpu_interrupts",
            "tb_peripheral_interrupts",
            "tb_mailbox_irq_any",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(0, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        self._base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        self._pbase = self._resolved(dut.tb_peripheral_interrupts, "baseline")
        anyb = self._resolved(dut.tb_mailbox_irq_any, "baseline")
        assert (self._base >> RAW_SHIFT) & 0xFF == 0, (
            f"baseline raw bits 263:256 read 0x{(self._base >> RAW_SHIFT) & 0xFF:x}"
        )
        assert anyb == 0, f"baseline mailbox_irq_any {anyb}"
        cocotb.log.info(
            "BASELINE vector=0x%x peripheral=0x%x mailbox_irq_any=%d", self._base, self._pbase, anyb
        )
        self._mark_step("S1")

        walk = await self._walk()
        self._mark_step("S2")
        self._log_chk(
            "CHK-SEPMBX-WALK",
            f"8 inputs walked, raw xor 1<<(256+k) and peripheral bit k for "
            f"{HOLD_RISES} rises then baseline; rises up/down {walk}",
        )

        hold = await self._hold_long()
        self._mark_step("S3")
        self._log_chk("CHK-SEPMBX-HOLD", hold)

        subs = await self._subsets()
        self._mark_step("S4")
        self._log_chk(
            "CHK-SEPMBX-SUBSETS",
            f"subsets 0xff 0x55 0xaa and 8 single drops from 0xff matched; {subs}",
        )

        lat = await self._latency()
        self._mark_step("S5")
        self._log_chk(
            "CHK-SEPMBX-LATENCY-LOG",
            f"observed {LATENCY_REPEATS} repeats, not compared (owner value pending); {lat}",
        )

        self._nonvac_fence()
        self._log_timeout_paths()

    def _nonvac_fence(self) -> None:
        ids = tuple(s for s, _ in self._stamps)
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"step stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        stamp_of = dict(self._stamps)
        for (chk_id, when), step in zip(self._chk_marks, _CHECK_STEP):
            assert when >= stamp_of[step], f"{chk_id} printed before its step {step} stamp"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<WALK<HOLD<SUBSETS<LATENCY-REPEATS; "
            "checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    def _log_timeout_paths(self) -> None:
        names = list(self._waits)
        shown = "; ".join(
            f"{n} bound={self._waits[n][0]} rises last[{self._waits[n][1]}]"
            for n in names[:3] + names[-2:]
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each expiry raises AssertionError with the "
            "last raw xor; ceiling %d clk_smc_i rises; samples %s",
            len(names),
            CEILING_RISES,
            shown,
        )
