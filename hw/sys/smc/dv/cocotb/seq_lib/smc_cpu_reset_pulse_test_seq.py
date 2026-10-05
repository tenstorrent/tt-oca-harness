# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A software core-reset pulse, and a withheld reset whose timeout gives up.

`cpu_ctrl.rdl` gives each core a `RESET_CTRL.coreN_reset_pulse_start` field:
writing a one there triggers a reset pulse whose length comes from
`CORE_RESET_PULSE_COUNT`, and `CORE_RESET_PULSE_COUNT.core_resets_done` reads
low for a core while its pulse is running. The only writer had been the
firmware boot contract. From SEP_IN, core 1 is pulsed with every level reset
field left high, so the pulse is the only reset request. Its `core_resets_done`
bit must fall and come back, and the other cores' bits must stay high. The
request is gated on the cluster draining; `RESET_TIMEOUT` is set to force mode
for this leg, as the boot contract does, so the pulse is applied either way.

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
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import cpu_ctrl_u32, smc_addr
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


class smc_cpu_reset_pulse_test_seq(SmcCsrSeq):
    """Pulse core 1 from SEP_IN, then let a withheld level reset time out in give-up mode."""

    def __init__(self, name: str = "smc_cpu_reset_pulse_test_seq") -> None:
        super().__init__(name)
        self.pulse_seen = False
        self.width_runs: list[int] | None = None
        self.held_samples: int | None = None
        self.give_up: tuple[int, int] | None = None

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

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
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
