# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""External input level hold and release at raw bits 0, 2 and 16 of cpu_interrupts.

Spec sources: interrupts.adoc smc-interrupts-risc-v-plic, smu-smc.adoc interrupt-integration.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")
# TB ceiling for a pin-to-raw-bit transition in clk_smc_i rises; not a latency claim.
WAIT_BOUND_RISES = 64
HOLD_RISES = 256
# The external inputs pass a three-flop synchroniser (interrupts.adoc).
SYNC_FLOPS = 3
RELEASE_RISES = 64
_STEPS = ("S1", "S2", "S3", "S4", "S5")
_CHECKERS = ("CHK-EXTHOLD-BIT0", "CHK-EXTHOLD-BIT2", "CHK-EXTHOLD-BIT16")
_CHK_STEP = {"CHK-EXTHOLD-BIT0": "S3", "CHK-EXTHOLD-BIT2": "S4", "CHK-EXTHOLD-BIT16": "S5"}


class smc_ext_irq_hold_release_test_seq(SmcCsrSeq):
    """Hold each external input high for 256 rises, release it, and watch the raw vector."""

    def __init__(self, name: str = "smc_ext_irq_hold_release_test_seq") -> None:
        super().__init__(name)
        self.done = False
        self._stamps: list[tuple[str, int]] = []
        self._chk_marks: list[tuple[str, int]] = []
        self._waits: list[str] = []
        self._baseline = 0
        self._hold_step = "S2"

    def _mark_step(self, step_id: str) -> None:
        self._stamps.append((step_id, int(get_sim_time("ps"))))

    def _log_chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self._chk_marks.append((chk_id, int(get_sim_time("ps"))))

    @staticmethod
    def _sample(label: str) -> int:
        sig = cocotb.top.tb_cpu_interrupts
        assert sig.value.is_resolvable, f"{label}: tb_cpu_interrupts is X/Z ({sig.value})"
        return int(sig.value)

    @staticmethod
    def _pins() -> tuple[int, int, int]:
        dut = cocotb.top
        vals = []
        for sig in (dut.tb_ext_interrupt_0_i, dut.tb_temp_interrupt_i, dut.tb_ext_interrupts_hi_i):
            assert sig.value.is_resolvable, f"{sig._name} is X/Z ({sig.value})"
            vals.append(int(sig.value))
        return vals[0], vals[1], vals[2]

    def _drive(self, bit: int, level: int, label: str) -> None:
        dut = cocotb.top
        if bit == 0:
            dut.tb_ext_interrupt_0_i.value = level
        else:
            hi = int(dut.tb_ext_interrupts_hi_i.value)
            hi = (hi | (1 << (bit - 2))) if level else (hi & ~(1 << (bit - 2)))
            dut.tb_ext_interrupts_hi_i.value = hi
        cocotb.log.info(
            "DRIVE %s: raw bit %d pin level %d (seed %s)", label, bit, level, cocotb.RANDOM_SEED
        )

    def _check_only(self, vec: int, mask: int, want: int, label: str) -> None:
        expect = self._baseline ^ (mask if want else 0)
        assert vec == expect, (
            f"{label}: tb_cpu_interrupts 0x{vec:x} want 0x{expect:x} "
            f"(baseline 0x{self._baseline:x}, XOR 0x{vec ^ self._baseline:x})"
        )

    async def _wait_bit(self, bit: int, want: int, label: str) -> int:
        mask = 1 << bit
        last = self._sample(f"{label} entry")
        for n in range(1, WAIT_BOUND_RISES + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            last = self._sample(f"{label}[{n}]")
            assert (last ^ self._baseline) & ~mask == 0, (
                f"{label}[{n}]: a second raw bit moved: vector 0x{last:x} "
                f"baseline 0x{self._baseline:x}"
            )
            if (last >> bit) & 1 == want:
                self._waits.append(f"{label}(bound {WAIT_BOUND_RISES} rises, hit at {n})")
                return n
        raise AssertionError(
            f"{label}: raw bit {bit} did not reach {want} within {WAIT_BOUND_RISES} "
            f"clk_smc_i rises (last vector 0x{last:x}, baseline 0x{self._baseline:x})"
        )

    async def _hold(self, bit: int, want: int, rises: int, label: str) -> None:
        mask = 1 << bit
        for n in range(1, rises + 1):
            await RisingEdge(cocotb.top.clk_smc_i)
            vec = self._sample(f"{label}[{n}]")
            self._check_only(vec, mask, want, f"{label}[{n}/{rises}]")
            assert (vec >> bit) & 1 == want, f"{label}[{n}/{rises}]: raw bit {bit} left {want}"

    async def _hold_release(self, bit: int, label: str) -> tuple[int, int]:
        self._drive(bit, 1, f"{label} hold")
        cocotb.log.info("LIFECYCLE CHK-EXTHOLD-BIT%d set: input for raw bit %d driven 1", bit, bit)
        rise = await self._wait_bit(bit, 1, f"{label}_RISE")
        assert rise >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} rose after {rise} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(bit, 1, HOLD_RISES, f"{label}_HOLD")
        cocotb.log.info(
            "LIFECYCLE CHK-EXTHOLD-BIT%d observed: raw bit %d read 1 after %d rises and at "
            "each of %d rises",
            bit,
            bit,
            rise,
            HOLD_RISES,
        )
        self._mark_step(self._hold_step)
        self._drive(bit, 0, f"{label} release")
        cocotb.log.info(
            "LIFECYCLE CHK-EXTHOLD-BIT%d cleared: input for raw bit %d driven 0", bit, bit
        )
        fall = await self._wait_bit(bit, 0, f"{label}_FALL")
        assert fall >= SYNC_FLOPS, (
            f"{label}: raw bit {bit} fell after {fall} rises, before the {SYNC_FLOPS}-flop "
            "synchroniser latency"
        )
        await self._hold(bit, 0, RELEASE_RISES, f"{label}_RELEASED")
        cocotb.log.info(
            "LIFECYCLE CHK-EXTHOLD-BIT%d checked_cleared: raw bit %d read 0 after %d rises and "
            "vector equals baseline for %d rises",
            bit,
            bit,
            fall,
            RELEASE_RISES,
        )
        return rise, fall

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        self._baseline = self._sample("BASELINE")
        pins = self._pins()
        assert pins == (0, 0, 0), f"baseline pins (ext0, temp, hi) = {pins}, want (0, 0, 0)"
        for bit in (0, 2, 16):
            assert (self._baseline >> bit) & 1 == 0, (
                f"baseline raw bit {bit} reads 1 (vector 0x{self._baseline:x})"
            )
        self._mark_step("S1")
        cocotb.log.info(
            "BASELINE: tb_cpu_interrupts=0x%x pins ext0/temp/hi=%s seed %s",
            self._baseline,
            pins,
            cocotb.RANDOM_SEED,
        )
        assert hasattr(dut, "tb_ext_interrupts_hi_i"), "tb_ext_interrupts_hi_i missing"

        results = {}
        for bit, hold_step, release_step in ((0, "S2", "S3"), (2, "S4", "S4"), (16, "S5", "S5")):
            self._hold_step = hold_step
            results[bit] = await self._hold_release(bit, f"BIT{bit}")
            self._mark_step(release_step)
            rise, fall = results[bit]
            self._log_chk(
                f"CHK-EXTHOLD-BIT{bit}",
                f"raw bit {bit} rose after {rise} rises (bound {WAIT_BOUND_RISES}) and held 1 "
                f"with vector XOR baseline 0x{1 << bit:x} at {HOLD_RISES} rises; fell after "
                f"{fall} rises and vector equalled baseline 0x{self._baseline:x} for "
                f"{RELEASE_RISES} rises",
            )
        await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0)
        self.done = True
        self._timeout_paths()
        self._nonvac_fence()

    def _timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, each raising AssertionError with the last "
            "vector on expiry: %s",
            len(self._waits),
            "; ".join(self._waits),
        )

    def _nonvac_fence(self) -> None:
        ids = tuple(dict.fromkeys(s for s, _ in self._stamps))
        assert ids == _STEPS, f"step ids {ids}, want {_STEPS}"
        times = [t for _, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_ids = tuple(c for c, _ in self._chk_marks)
        assert chk_ids == _CHECKERS, f"checker lines {chk_ids}, want {_CHECKERS}"
        last_stamp = {}
        for s, t in self._stamps:
            last_stamp[s] = t
        for chk_id, when in self._chk_marks:
            assert when >= last_stamp[_CHK_STEP[chk_id]], f"{chk_id} printed before its step"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence BASELINE<BIT0-HOLD<BIT0-RELEASE<BIT2-HOLD-RELEASE"
            "<BIT16-HOLD-RELEASE; checker lines %s; stamps %s",
            ",".join(chk_ids),
            ",".join(f"{s}={t}" for s, t in self._stamps),
        )
