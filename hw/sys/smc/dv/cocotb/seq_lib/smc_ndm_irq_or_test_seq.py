# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""NDM reset request bits into raw tb_cpu_interrupts bit 267 through the OR.

Spec sources: interrupts.adoc SMC indexed interrupt map table; port_table.adoc
smc_ndmreset_request_i.
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
HOLD_RISES = 64
LONG_HOLD_RISES = 256
NDM_BIT = 267
NDM_MASK = 1 << NDM_BIT
REQUEST_BITS = 4
_STEPS = ("S1", "S2", "S3", "S4")
_CHECKERS = ("CHK-NDM-EACH-ALONE", "CHK-NDM-OR-DROP", "CHK-NDM-HOLD")
_CHECK_STEP = ("S2", "S3", "S4")


class smc_ndm_irq_or_test_seq(SmcCsrSeq):
    """Drive tb_ndmreset_request and compare the whole raw vector against the baseline."""

    def __init__(self, name: str = "smc_ndm_irq_or_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[int, str]] = {}
        self._base = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _resolved(sig, label: str) -> int:
        assert sig.value.is_resolvable, f"{label}: {sig._name} is X/Z ({sig.value})"
        return int(sig.value)

    def _sample(self, label: str) -> tuple[int, int]:
        """Return (vector XOR baseline, tb_ndmreset_irq) at this rise."""
        dut = cocotb.top
        vec = self._resolved(dut.tb_cpu_interrupts, label)
        irq = self._resolved(dut.tb_ndmreset_irq, label)
        return vec ^ self._base, irq

    def _drive(self, value: int, why: str) -> None:
        cocotb.top.tb_ndmreset_request.value = value
        cocotb.log.info(
            "DRIVE tb_ndmreset_request=0b%s (%s) at %d ps",
            format(value, f"0{REQUEST_BITS}b"),
            why,
            int(get_sim_time("ps")),
        )

    async def _reach(self, name: str, level: int) -> int:
        """Wait until raw bit 267 equals level; no other raw bit may differ from the baseline."""
        bound = CEILING_RISES
        want = NDM_MASK * level
        diff, irq = self._sample(f"{name} entry")
        self._waits[name] = (bound, f"xor=0x{diff:x} ndm_irq={irq}")
        for n in range(1, bound + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, irq = self._sample(f"{name}[{n}]")
            self._waits[name] = (bound, f"xor=0x{diff:x} ndm_irq={irq} after {n} rises")
            assert diff & ~NDM_MASK == 0, f"{name}: other raw bit moved, xor 0x{diff:x}"
            if diff == want:
                assert irq == level, f"{name}: tb_ndmreset_irq={irq} vs raw bit 267 level {level}"
                return n
        raise AssertionError(
            f"{name}: raw bit 267 did not reach {level} within {bound} clk_smc_i rises "
            f"(last xor 0x{diff:x} ndm_irq={irq})"
        )

    async def _hold(self, name: str, level: int, rises: int) -> None:
        want = NDM_MASK * level
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            diff, irq = self._sample(f"{name} hold[{n}]")
            assert diff == want, (
                f"{name}: xor 0x{diff:x} != 0x{want:x} at hold rise {n} (ndm_irq={irq})"
            )
            assert irq == level, f"{name}: tb_ndmreset_irq={irq} vs level {level} at rise {n}"

    async def _step(self, name: str, value: int, level: int, hold: int = HOLD_RISES) -> int:
        await RisingEdge(cocotb.top.clk_smc_i)
        self._drive(value, name)
        rises = await self._reach(name, level)
        await self._hold(name, level, hold)
        self.phases += 1
        return rises

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def _each_alone(self) -> str:
        parts = []
        for j in range(REQUEST_BITS):
            up = await self._step(f"alone bit{j} up", 1 << j, 1)
            down = await self._step(f"alone bit{j} down", 0, 0)
            parts.append(f"bit{j}: high after {up} rises, baseline after {down} rises")
        return "; ".join(parts)

    async def _or_drop(self) -> str:
        parts = []
        up = await self._step("or 0b0011 up", 0b0011, 1)
        await self._step("or drop bit0 (0b0010)", 0b0010, 1)
        down = await self._step("or drop bit1 (0b0000)", 0, 0)
        parts.append(f"0b0011 high after {up} rises, still 1 after bit0 drop, low after {down}")
        up = await self._step("or 0b1111 up", 0b1111, 1)
        for j, value in ((0, 0b1110), (1, 0b1100), (2, 0b1000)):
            await self._step(f"or 0b1111 drop bit{j} ({value:04b})", value, 1)
        down = await self._step("or 0b1111 drop bit3 (0b0000)", 0, 0)
        parts.append(f"0b1111 high after {up} rises, 1 after drops of bits 0..2, low after {down}")
        return "; ".join(parts)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        for sig in (
            "tb_ndmreset_request",
            "tb_cpu_interrupts",
            "tb_ndmreset_irq",
            "tb_ndmreset_request_sync",
        ):
            assert hasattr(dut, sig), f"{sig} missing"
        assert len(dut.tb_ndmreset_request) == REQUEST_BITS, (
            f"tb_ndmreset_request width {len(dut.tb_ndmreset_request)}, want {REQUEST_BITS}"
        )
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0)
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(0, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        self._base = self._resolved(dut.tb_cpu_interrupts, "baseline")
        diff, irq = self._sample("baseline")
        assert self._base >> NDM_BIT & 1 == 0, "baseline raw bit 267 reads 1"
        assert irq == 0, f"baseline tb_ndmreset_irq={irq}"
        sync = self._resolved(dut.tb_ndmreset_request_sync, "baseline")
        cocotb.log.info("BASELINE vector=0x%x ndm_irq=%d request_sync=0x%x", self._base, irq, sync)
        self._mark_step("S1")

        s2 = await self._each_alone()
        self._mark_step("S2")
        self._log_legs(
            "CHK-NDM-EACH-ALONE",
            "tb_ndmreset_request bit j driven 1 for j=0..3",
            "tb_cpu_interrupts and tb_ndmreset_irq each rise",
            "bit j driven 0",
            "vector equals the baseline",
        )
        self._log_chk(
            "CHK-NDM-EACH-ALONE",
            f"xor baseline 1<<267 for {HOLD_RISES} rises per bit, baseline after release; {s2}",
        )

        s3 = await self._or_drop()
        self._mark_step("S3")
        self._log_legs(
            "CHK-NDM-OR-DROP",
            "two and four request bits driven 1",
            "tb_cpu_interrupts[267] each rise",
            "requests dropped one by one",
            "raw bit 267 reads 0 after the last drop",
        )
        self._log_chk(
            "CHK-NDM-OR-DROP",
            f"raw bit 267 held 1 for {HOLD_RISES} rises after each non-final drop; {s3}",
        )

        up = await self._step("hold 0b0001 up", 0b0001, 1, LONG_HOLD_RISES)
        down = await self._step("hold release", 0, 0)
        self._mark_step("S4")
        self._log_legs(
            "CHK-NDM-HOLD",
            "request held 1",
            "tb_cpu_interrupts[267] each rise",
            "request driven 0",
            "raw bit 267 reads 0 and the vector equals the baseline",
        )
        self._log_chk(
            "CHK-NDM-HOLD",
            f"bit 267 high after {up} rises, held {LONG_HOLD_RISES} consecutive rises; "
            f"low after {down} rises, baseline for {HOLD_RISES} rises",
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
            "CHK-NONVAC: ordered fence BASELINE<EACH-ALONE<OR-DROP-ORDERS<HOLD; "
            "checker lines %s; stamps %s",
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
