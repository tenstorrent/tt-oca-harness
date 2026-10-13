# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Idle state of reserved, internal and peripheral-owned raw tb_cpu_interrupts positions.

Contract SMC_IRQ_011, anchor smc_irq_reserved_idle_zero_test.
Allocated scenarios: IRQ-PERIPH-RSVD.S1, IRQ-RSVD-TAIL.S1, IRQ-INTERNAL.S2, IRQ-VEC-ASSEMBLY.S3.
Spec sources: interrupts.adoc SMC indexed interrupt map table and SMC interrupts trace notes.
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
WINDOW_RISES = 256
FUSE_SENSE_RISES = 200_000
AXI_TIMEOUT_NS = 50_000
EXT0_BIT = 0
TIED_BITS = (287, 327, 326, 325, 324)
INTERNAL_BITS = (323, 322, 321, 320)
PERIPH_BITS = (264, 265, 266) + tuple(range(268, 282)) + (283, 284, 285)
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = (
    "CHK-RSVDIDLE-287",
    "CHK-RSVDIDLE-TAIL",
    "CHK-RSVDIDLE-INTERNAL-LOG",
    "CHK-RSVDIDLE-PERIPH-LOG",
)
_CHECK_STEP = ("S3", "S3", "S4", "S5")


class smc_irq_reserved_idle_zero_test_seq(SmcCsrSeq):
    """Sample the raw vector over an idle window after a bit-0 liveness control."""

    def __init__(self, name: str = "smc_irq_reserved_idle_zero_test_seq") -> None:
        super().__init__(name)
        self.phases = 0
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: dict[str, tuple[str, str]] = {}
        self._base = 0

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _vector(label: str) -> int:
        sig = cocotb.top.tb_cpu_interrupts
        assert sig.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({sig.value})"
        return int(sig.value)

    def _drive(self, value: int, why: str) -> None:
        cocotb.top.tb_ext_interrupt_0_i.value = value
        cocotb.log.info(
            "DRIVE tb_ext_interrupt_0_i=%d (%s) at %d ps", value, why, int(get_sim_time("ps"))
        )

    async def _reach(self, name: str, want: int) -> int:
        """Wait until the whole vector equals want."""
        vec = self._vector(f"{name} entry")
        self._waits[name] = (f"{CEILING_RISES} rises", f"vec=0x{vec:x}")
        for n in range(1, CEILING_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._vector(f"{name}[{n}]")
            self._waits[name] = (f"{CEILING_RISES} rises", f"vec=0x{vec:x} after {n} rises")
            if vec == want:
                return n
        raise AssertionError(
            f"{name}: vector did not reach 0x{want:x} within {CEILING_RISES} clk_smc_i rises "
            f"(last 0x{vec:x})"
        )

    @staticmethod
    def _bits(vec: int, bits: tuple[int, ...]) -> str:
        return "".join(str(vec >> b & 1) for b in bits)

    async def _idle_window(self) -> list[int]:
        """Sample consecutive rises; S3, S4 and S5 are stamped at rises 256, 257 and 258."""
        samples = []
        for n in range(1, WINDOW_RISES + 3):
            await RisingEdge(cocotb.top.clk_smc_i)
            samples.append(self._vector(f"idle[{n}]"))
            if n >= WINDOW_RISES:
                self._mark_step(_STEPS[n - WINDOW_RISES + 2])
        assert len(samples) >= WINDOW_RISES, f"window {len(samples)} rises, want {WINDOW_RISES}"
        return samples

    @staticmethod
    def _distinct(samples: list[int], bits: tuple[int, ...]) -> str:
        seen: dict[str, int] = {}
        for vec in samples:
            key = "".join(str(vec >> b & 1) for b in bits)
            seen[key] = seen.get(key, 0) + 1
        return ", ".join(f"{k} x{c}" for k, c in seen.items())

    def _log_legs(self, chk: str, set_text: str, observed: str, cleared: str, checked: str):
        cocotb.log.info("LIFECYCLE %s set: %s", chk, set_text)
        cocotb.log.info("LIFECYCLE %s observed: %s", chk, observed)
        cocotb.log.info("LIFECYCLE %s cleared: %s", chk, cleared)
        cocotb.log.info("LIFECYCLE %s checked_cleared: %s", chk, checked)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        self._waits["fuse sense (AssertionError on expiry)"] = (
            f"{FUSE_SENSE_RISES} rises",
            f"tb_fuse_sense_done={int(dut.tb_fuse_sense_done.value)}",
        )
        assert hasattr(dut, "tb_ext_interrupt_0_i"), "tb_ext_interrupt_0_i missing"
        assert len(dut.tb_cpu_interrupts) >= 328, (
            f"tb_cpu_interrupts width {len(dut.tb_cpu_interrupts)}, want >= 328"
        )
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        self._waits["SEP_IN csr_read SCRATCH_COLD_WARM_0 (AssertionError on expiry)"] = (
            f"{AXI_TIMEOUT_NS} ns",
            f"read data=0x{got:x}",
        )
        cocotb.log.info(
            "SEED RANDOM_SEED=%s SCRATCH_COLD_WARM_0=0x%x", os.environ.get("RANDOM_SEED", "1"), got
        )
        self._drive(0, "idle before baseline")
        await RisingEdge(dut.clk_smc_i)
        self._base = self._vector("baseline")
        cocotb.log.info("BASELINE vector=0x%x", self._base)
        self._mark_step("S1")
        self.phases += 1

        await RisingEdge(dut.clk_smc_i)
        self._drive(1, "liveness control up")
        up = await self._reach("liveness up", self._base | 1 << EXT0_BIT)
        await RisingEdge(dut.clk_smc_i)
        self._drive(0, "liveness control down")
        down = await self._reach("liveness down", self._base)
        cocotb.log.info("LIVENESS raw bit 0 high after %d rises, baseline after %d rises", up, down)
        self._mark_step("S2")
        self.phases += 1

        samples = await self._idle_window()
        self.phases += 1
        n_rises = len(samples)
        for n, vec in enumerate(samples, 1):
            for bit in TIED_BITS:
                assert vec >> bit & 1 == 0, f"raw bit {bit} reads 1 at idle rise {n} (0x{vec:x})"
        self._log_legs(
            "CHK-RSVDIDLE-287",
            "every source idle after the liveness control",
            "tb_cpu_interrupts sampled each rise",
            "no source driven",
            "raw bit 287 reads 0 at every rise",
        )
        self._log_chk(
            "CHK-RSVDIDLE-287",
            f"raw bit 287 = 0 at each of {n_rises} consecutive rises; "
            f"values {self._distinct(samples, (287,))}",
        )
        self._log_chk(
            "CHK-RSVDIDLE-TAIL",
            f"raw bits 327:324 = 0 at each of {n_rises} consecutive rises; "
            f"values {self._distinct(samples, (327, 326, 325, 324))}",
        )

        self.phases += 1
        self._log_chk(
            "CHK-RSVDIDLE-INTERNAL-LOG",
            f"raw bits 323,322,321,320 over {n_rises} rises (SF-019, logged only): "
            f"{self._distinct(samples, INTERNAL_BITS)}",
        )

        self.phases += 1
        self._log_chk(
            "CHK-RSVDIDLE-PERIPH-LOG",
            f"raw bits 264-266,268-281,283-285 over {n_rises} rises "
            f"(SF-019, logged only): {self._distinct(samples, PERIPH_BITS)}",
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
            "CHK-NONVAC: ordered fence BASELINE<LIVENESS-CONTROL<IDLE-WINDOW<INTERNAL-LOG"
            "<PERIPHERAL-LOG; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )

    def _log_timeout_paths(self) -> None:
        waits = "; ".join(
            f"{name} bound={bound} last[{last}]" for name, (bound, last) in self._waits.items()
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: every bounded wait raises AssertionError on expiry; "
            "pin-wait expiry reports the last vector; %s",
            waits,
        )
