# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""mem_repair_abort_i / mbist_abort_i to the STATUS_SMU sticky bits."""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import (
    DFX_MBIST_ABORT,
    DFX_MEM_REPAIR_ABORT,
    DFX_STATUS_IDLE,
    DFX_STATUS_SMU,
)
from .smc_csr_seq_utils import SmcCsrSeq

# Bound on the CSR polls each stage may take. The path being timed is
# `mem_repair_abort_i` / `mbist_abort_i` -> the STATUS_SMU sticky bit -> one
# SEP_IN AXI-Lite read; the pins are driven from this coroutine and the bit is
# sticky, so a healthy DUT shows the new word on the FIRST read after the drive
# and every stage below costs exactly one access. The bound is the only check
# here on how long the pin takes to reach the status word, and its expiry is a
# FAILURE, never a pass ([TIMEOUT-MUST-FAIL]). The observed poll count is
# carried into every token.
_MAX_STATUS_POLLS = 4
# Value-checked reads this sequence must book with the scoreboard: the two
# sticky readbacks that carry `expected=`.
EXPECTED_VALUE_CHECKS = 2
# The abort inputs are sticky until reset with no minimum width stated
# (dfx_ctrl_status.rdl), so the pulse width is drawn from one clk_smc_i cycle
# up to a bench bucket.
PULSE_MIN_CYCLES = 1
PULSE_MAX_CYCLES = 64
PINS = {
    "mem_repair_abort": ("tb_mem_repair_abort", DFX_MEM_REPAIR_ABORT, "CHK-DFX-ABORT-REPAIR"),
    "mbist_abort": ("tb_mbist_abort", DFX_MBIST_ABORT, "CHK-DFX-ABORT-MBIST"),
}


class smc_dfx_status_abort_test_seq(SmcCsrSeq):
    """STATUS_SMU idle, then mem-repair abort, then MBIST abort."""

    def __init__(self, name: str = "smc_dfx_status_abort_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        #: STATUS_SMU words observed at each stage, in order.
        self.status_progression: list[int] = []
        #: CSR polls each `_await_status` stage needed, in order.
        self.stage_polls: list[int] = []
        #: scoreboard value compares booked by this sequence's `expected=` reads
        self.value_checks = 0

    async def _await_status(self, want: int, label: str) -> int:
        last = 0
        for poll in range(1, _MAX_STATUS_POLLS + 1):
            last = await self.csr_read(label, DFX_STATUS_SMU)
            if last == want:
                self.stage_polls.append(poll)
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: STATUS_SMU=0x{last:x} want 0x{want:x} after {_MAX_STATUS_POLLS} CSR poll(s)"
        )

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_mem_repair_abort"), "tb_mem_repair_abort missing"
        assert hasattr(dut, "tb_mbist_abort"), "tb_mbist_abort missing"
        # `tb_mem_repair_abort` / `tb_mbist_abort` are top-level TB inputs wired
        # to `.mem_repair_abort_i` / `.mbist_abort_i` with no other driver; the
        # STATUS_SMU compare in the next statement fails if the pins are not at 0.
        dut.tb_mem_repair_abort.value = 0
        dut.tb_mbist_abort.value = 0

        idle = await self._await_status(DFX_STATUS_IDLE, "STATUS_IDLE")
        self.status_progression.append(idle)
        cocotb.log.info(
            "CHK-DFX-ABORT-IDLE: STATUS_SMU=0x%x (no abort bit set) after "
            "%d CSR poll(s) with both abort pins driven 0",
            idle,
            self.stage_polls[-1],
        )

        rng = random.Random(self.seed)
        order = list(PINS)
        rng.shuffle(order)
        widths = {pin: rng.randint(PULSE_MIN_CYCLES, PULSE_MAX_CYCLES) for pin in order}
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: pin order %s, pulse widths %s clk_smc_i cycles",
            self.seed,
            order,
            widths,
        )
        want = DFX_STATUS_IDLE
        for pin in order:
            signal_name, bit, chk_id = PINS[pin]
            signal = getattr(dut, signal_name)
            signal.value = 1
            await ClockCycles(dut.clk_smc_i, widths[pin])
            signal.value = 0
            want |= bit
            live = await self._await_status(want, f"STATUS_{pin.upper()}")
            polls = self.stage_polls[-1]
            sticky = await self.csr_read(
                f"STATUS_{pin.upper()}_STICKY", DFX_STATUS_SMU, expected=want
            )
            self.status_progression.append(sticky)
            cocotb.log.info(
                "%s: STATUS_SMU=0x%x after a %d-cycle pulse on %s_i, read within %d CSR "
                "poll(s) after the pin returned to 0, still 0x%x on the next read (sticky; the "
                "other abort bit at its earlier value); drawn=seed %d order %s width %d",
                chk_id,
                live,
                widths[pin],
                pin,
                polls,
                sticky,
                self.seed,
                "->".join(order),
                widths[pin],
            )

        # `csr_read` never compares `expected` itself; the scoreboard performs
        # the value compares, and these two legs require it to have seen this
        # sequence's accesses and both ``expected=`` reads
        # ([NO-ZERO-ACTIVITY-PASS]).
        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"DFX_STATUS_ABORT: the scoreboard checked only "
            f"{sb.sys_axi_checks_seen} SYS AXI item(s) but this sequence issued "
            f"{self.accesses} access(es) -- the traffic never reached the "
            f"scoreboard, so none of it is checked evidence"
        )
        self.value_checks = sb.sys_axi_value_checks_seen
        assert self.value_checks >= EXPECTED_VALUE_CHECKS, (
            f"DFX_STATUS_ABORT: the two sticky readbacks must book "
            f"{EXPECTED_VALUE_CHECKS} scoreboard value compare(s), the "
            f"scoreboard booked {self.value_checks}"
        )
        cocotb.log.info(
            "CHK-DFX-ABORT-BASIC: STATUS_SMU %s across idle -> %s; stage poll "
            "counts %s (bound %d, so each abort pulse reached the status word inside "
            "one CSR round trip); %d access(es) checked by the scoreboard, %d of them "
            "value compares (>= %d)",
            " -> ".join(f"0x{w:x}" for w in self.status_progression),
            " -> ".join(order),
            self.stage_polls,
            _MAX_STATUS_POLLS,
            sb.sys_axi_checks_seen,
            self.value_checks,
            EXPECTED_VALUE_CHECKS,
        )
