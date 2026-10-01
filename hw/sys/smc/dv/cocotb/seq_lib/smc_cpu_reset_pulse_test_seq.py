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

`RESET_TIMEOUT.timeout_mode = 0` means "give up and report error (stay
withheld, do not apply)". With `timeout_value` 1 and core 1's level reset
requested, the request outlasts one cycle of pending drain, so `reset_timeout`
must read 1. The request is then released, and both status bits must clear.
The reset is applied once the drain completes, even in mode 0 (card 262,
design observation); the leaf reports `reset_applied` and does not grade it. Both `RESET_TIMEOUT` and `RESET_CTRL` are
restored and read back.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
PULSE_COUNT = smc_addr("SMC_TOP_SMC_CPU_CTRL_CORE_RESET_PULSE_COUNT_BASE_ADDR")
CORE1_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_N_N0_SCAN_bm")
CORE1_PULSE = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE1_RESET_PULSE_START_N0_SCAN_bm")
DONE_BP = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bp")
DONE_BM = cpu_ctrl_u32("CPU_CTRL__CORE_RESET_PULSE_COUNT__CORE_RESETS_DONE_bm")
VALUE_BP = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_VALUE_bp")
MODE_BM = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__TIMEOUT_MODE_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
TIMED_OUT = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")

FORCE_AFTER_32 = (32 << VALUE_BP) | MODE_BM
GIVE_UP_AFTER_1 = 1 << VALUE_BP
_POLLS = 64


class smc_cpu_reset_pulse_test_seq(SmcCsrSeq):
    """Pulse core 1 from SEP_IN, then let a withheld level reset time out in give-up mode."""

    def __init__(self, name: str = "smc_cpu_reset_pulse_test_seq") -> None:
        super().__init__(name)
        self.pulse_seen = False
        self.give_up: tuple[int, int] | None = None

    async def _done_bits(self, tag: str) -> int:
        word = await self.csr_read(tag, PULSE_COUNT, length=8)
        return (word & DONE_BM) >> DONE_BP

    async def _pulse(self, ctrl: int) -> None:
        all_done = DONE_BM >> DONE_BP
        assert await self._done_bits("PULSE_DONE_IDLE") == all_done, "a core reset already running"
        await self.csr_write("PULSE_TIMEOUT_FORCE", RESET_TIMEOUT, FORCE_AFTER_32, length=8)
        await self.csr_write("PULSE_CORE1", RESET_CTRL, ctrl | CORE1_PULSE, length=8)
        seen_low = False
        for i in range(_POLLS):
            bits = await self._done_bits(f"PULSE_DONE_{i}")
            assert bits | 0b0010 == all_done, (
                f"CORE_RESET_PULSE_COUNT.core_resets_done = 0x{bits:x} while only core 1 was "
                f"pulsed; the other cores' bits must stay high"
            )
            if not bits & 0b0010:
                seen_low = True
            elif seen_low:
                break
        assert seen_low, f"core 1's core_resets_done bit never fell within {_POLLS} reads"
        assert await self._done_bits("PULSE_DONE_END") == all_done, "core 1's pulse never ended"
        self.pulse_seen = True

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
        assert ctrl & CORE1_N and not ctrl & CORE1_PULSE, f"RESET_CTRL 0x{ctrl:x} not idle"

        await self._pulse(ctrl)
        cocotb.log.info(
            "CHK-CPU-RST-PULSE: a RESET_CTRL write with core 1's pulse field set and every "
            "level reset high dropped core 1's core_resets_done bit and raised it again; "
            "the other cores' bits stayed high"
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
        await self.csr_read("RESET_CTRL_RESTORE_RB", RESET_CTRL, length=8, expected=ctrl)
