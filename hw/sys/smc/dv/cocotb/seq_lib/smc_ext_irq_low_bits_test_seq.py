# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External input bits 1 and 0 on tb_temp_interrupt_i and tb_ext_interrupt_0_i.

Spec sources: interrupts.adoc SMC indexed interrupt map table, SMC interrupts and PLIC.
"""

from __future__ import annotations

import os

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# TB ceiling in clk_smc_i rises for every pin-to-raw-bit wait; not a latency claim.
CEILING_RISES = 64
# The external inputs pass a three-flop synchroniser (interrupts.adoc).
SYNC_FLOPS = 3
HOLD_RISES = 64
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    "CHK-LOW2-BIT1",
    "CHK-LOW2-BIT0",
    "CHK-LOW2-BOTH-BIT0-FIRST",
    "CHK-LOW2-BOTH-BIT1-FIRST",
)
_CHECK_STEP = ("S2", "S3", "S4", "S5")
_PIN = {0: "tb_ext_interrupt_0_i", 1: "tb_temp_interrupt_i"}


class smc_ext_irq_low_bits_test_seq(SmcCsrSeq):
    """Drive the two dedicated pins and compare the whole raw vector against the baseline."""

    def __init__(self, name: str = "smc_ext_irq_low_bits_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._base = 0
        self._level = 0

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
        """Return (vector XOR baseline, temp sync bit, ext0 sync bit) at this rise."""
        dut = cocotb.top
        vec = self._resolved(dut.tb_cpu_interrupts, label)
        temp = self._resolved(dut.tb_temp_interrupt_irq, label)
        ext0 = self._resolved(dut.tb_ext_interrupt_0_sync, label)
        return vec ^ self._base, temp, ext0

    def _drive(self, bit: int, value: int, why: str) -> None:
        getattr(cocotb.top, _PIN[bit]).value = value
        self._level = (self._level & ~(1 << bit)) | (value << bit)
        cocotb.log.info("DRIVE %s=%d (%s) at %d ps", _PIN[bit], value, why, int(get_sim_time("ps")))

    async def _reach(self, name: str, prev: int, target: int) -> int:
        """Wait until the XOR vector equals target; no bit outside prev|target may differ."""
        bound = CEILING_RISES
        diff, temp, ext0 = self._sample(f"{name} entry")
        self._waits[name] = (bound, f"xor=0x{diff:x} temp={temp} ext0={ext0}")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, temp, ext0 = self._sample(f"{name}[{n}]")
            self._waits[name] = (bound, f"xor=0x{diff:x} temp={temp} ext0={ext0} after {n} rises")
            assert diff & ~(prev | target) == 0, (
                f"{name}: other raw bit moved, xor 0x{diff:x} (prev 0x{prev:x} target 0x{target:x})"
            )
            keep = prev & target
            assert diff & keep == keep, f"{name}: raw bit dropped early, xor 0x{diff:x}"
            if diff == target:
                assert (temp, ext0) == (target >> 1 & 1, target & 1), (
                    f"{name}: synchroniser outputs temp={temp} ext0={ext0} vs xor 0x{diff:x}"
                )
                return n
        raise AssertionError(
            f"{name}: xor vector did not reach 0x{target:x} within {bound} clk_smc_i rises "
            f"(last xor 0x{diff:x} temp={temp} ext0={ext0})"
        )

    async def _hold(self, name: str, target: int) -> None:
        for n in range(1, HOLD_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, temp, ext0 = self._sample(f"{name} hold[{n}]")
            assert diff == target, (
                f"{name}: xor 0x{diff:x} != 0x{target:x} at hold rise {n} (temp={temp} ext0={ext0})"
            )
            assert (temp, ext0) == (target >> 1 & 1, target & 1), (
                f"{name}: synchroniser outputs temp={temp} ext0={ext0} vs xor 0x{target:x}"
            )

    async def _transition(self, name: str, bit: int, value: int, prev: int, target: int) -> int:
        await RisingEdge(cocotb.top.clk_smc_i)
        self._drive(bit, value, name)
        rises = await self._reach(name, prev, target)
        assert rises >= SYNC_FLOPS, (
            f"{name}: raw bit moved after {rises} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(name, target)
        self.phases += 1
        return rises

    async def _single(self, bit: int) -> str:
        mask = 1 << bit
        up = await self._transition(f"BIT{bit} rise", bit, 1, 0, mask)
        down = await self._transition(f"BIT{bit} fall", bit, 0, mask, 0)
        self._log_legs(f"CHK-LOW2-BIT{bit}", _PIN[bit], mask)
        return f"{_PIN[bit]} high after {up} rises, raw bit {bit} low after {down} rises"

    def _log_legs(self, chk: str, set_text: str, mask: int) -> None:
        cocotb.log.info("LIFECYCLE %s set: %s driven 1", chk, set_text)
        cocotb.log.info(
            "LIFECYCLE %s observed: tb_cpu_interrupts xor 0x%x for %d rises", chk, mask, HOLD_RISES
        )
        cocotb.log.info("LIFECYCLE %s cleared: %s driven 0", chk, set_text)
        cocotb.log.info("LIFECYCLE %s checked_cleared: xor 0x0 for %d rises", chk, HOLD_RISES)

    async def _both(self, first: int) -> tuple[int, int, int]:
        second = 1 - first
        name = f"BOTH release bit{first} first"
        await RisingEdge(cocotb.top.clk_smc_i)
        self._drive(1, 1, f"{name}: temp up")
        r1 = await self._reach(f"{name} temp up", 0, 2)
        self._drive(0, 1, f"{name}: ext0 up")
        r2 = await self._reach(f"{name} ext0 up", 2, 3)
        await self._hold(f"{name} both high", 3)
        self.phases += 1
        r_first = await self._transition(f"{name} release bit{first}", first, 0, 3, 1 << second)
        r_second = await self._transition(f"{name} release bit{second}", second, 0, 1 << second, 0)
        return r_first, r_second, r1 + r2

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_ext_interrupt_0_i",
            "tb_temp_interrupt_i",
            "tb_cpu_interrupts",
            "tb_temp_interrupt_irq",
            "tb_ext_interrupt_0_sync",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0)
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(1, 0, "idle before baseline")
        self._drive(0, 0, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        self._base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        diff, temp, ext0 = self._sample("baseline")
        assert self._base & 3 == 0, f"baseline raw bits 1:0 read 0x{self._base & 3:x}"
        assert (temp, ext0) == (0, 0), f"baseline synchroniser outputs temp={temp} ext0={ext0}"
        cocotb.log.info("BASELINE vector=0x%x temp_irq=%d ext0_sync=%d", self._base, temp, ext0)
        self._mark_step("S1")

        s2 = await self._single(1)
        self._mark_step("S2")
        self._log_chk(
            "CHK-LOW2-BIT1",
            f"xor baseline 0x2 for {HOLD_RISES} rises, then 0x0 for {HOLD_RISES} rises; {s2}",
        )

        s3 = await self._single(0)
        self._mark_step("S3")
        self._log_chk(
            "CHK-LOW2-BIT0",
            f"xor baseline 0x1 for {HOLD_RISES} rises, then 0x0 for {HOLD_RISES} rises; {s3}",
        )

        for step, first, chk in (
            ("S4", 0, "CHK-LOW2-BOTH-BIT0-FIRST"),
            ("S5", 1, "CHK-LOW2-BOTH-BIT1-FIRST"),
        ):
            r_first, r_second, r_up = await self._both(first)
            self._mark_step(step)
            cocotb.log.info("LIFECYCLE %s set: both inputs driven 1", chk)
            cocotb.log.info("LIFECYCLE %s observed: tb_cpu_interrupts xor 0x3", chk)
            cocotb.log.info(
                "LIFECYCLE %s cleared: input %d then input %d driven 0", chk, first, 1 - first
            )
            cocotb.log.info("LIFECYCLE %s checked_cleared: xor 0x0 for %d rises", chk, HOLD_RISES)
            self._log_chk(
                chk,
                f"both high xor 0x3 after {r_up} rises; release bit {first}: xor 0x{2 >> first:x} "
                f"after {r_first} rises held {HOLD_RISES}; release bit {1 - first}: baseline "
                f"after {r_second} rises held {HOLD_RISES}",
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
            "CHK-NONVAC: ordered fence BASELINE<BIT1<BIT0<BOTH-RELEASE-0-FIRST<"
            "BOTH-RELEASE-1-FIRST; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    def _log_timeout_paths(self) -> None:
        waits = "; ".join(
            f"{name} bound={bound} rises last[{last}]"
            for name, (bound, last) in self._waits.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every expiry raises AssertionError with the last xor vector; "
            "ceiling %d clk_smc_i rises; %s",
            CEILING_RISES,
            waits,
        )
