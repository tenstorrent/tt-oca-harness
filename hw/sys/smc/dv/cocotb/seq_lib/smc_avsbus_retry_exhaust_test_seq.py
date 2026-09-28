# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus retry sequence against a target that never answers.

``hw/ip/avsbus_controller/doc/interface.adoc`` "AVSBus Slave Subframe" defines
bit 29 of the reply as Frame Valid, where "a 1 means the target did not respond
and raises ``SLAVE_UNRESPONSIVE_INT``". The bench holds the AVSBus sdata pad at
its idle-high level, so every received subframe carries that bit set and the
controller must take the retry path ``architecture.adoc`` "Error Handling and
Diagnostics" specifies: resend up to ``AVS_CFG_0.MAX_RETRIES`` times, count each
attempt in ``AVS_NORMAL_STATUS.TOTAL_RETRIES``, and raise
``MAX_RETRIES_ATTEMPTED_INT`` when the budget runs out.

Two commands are queued back to back, which is what separates the three retry
shapes the specification names: the reply to the first command arrives while
the second is already on the wire, so the controller retries while still
receiving (the transmit-and-receive states), then alternates transmit-only and
receive-only retries, then evaluates the buffered reply to the second command in
``AVS_PROCESS_PREVIOUS_SDATA``.

Three DUT-produced observables carry the proof: the FSM debug bus walks the
three retry shift states, ``AVS_NORMAL_STATUS`` reports the
master retrying while it happens, and the interrupt register ends with both
failure flags raised and clears on the documented write-1-clear.
``smc_avsbus_frame_transaction_test`` is the opposite leg on the same
registers: with the pad driven low, every one of those indicators stays 0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_avsbus_protocol_utils import (
    AVS_BUS_IS_IDLE_BM,
    AVS_CFG_0,
    AVS_CMD,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_NORMAL_STATUS,
    CLEAR_MAX_RETRIES_ATTEMPTED_BM,
    CLEAR_SLAVE_UNRESPONSIVE_BM,
    CMD_TYPE_READ,
    MASTER_IS_RETRYING_BM,
    MAX_RETRIES_ATTEMPTED_BM,
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    READ_CMD_DATA,
    SLAVE_UNRESPONSIVE_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    AvsFsmMonitor,
    build_avs_cmd,
    fifo_field,
    set_avs_sdata,
)
from .smc_csr_seq_utils import SmcCsrSeq

# Retry budget for this scenario. Small enough to keep the burst short, and at
# least two so the countdown is walked rather than stepped straight to zero.
RETRY_BUDGET = 2

# interface.adoc "AVSBus Command Codes (Command Group 0)": 0x0 target rail
# voltage and 0xE AVSBus status, both read commands with the read data field.
AVS_COMMANDS = [
    ("RAIL_VOLTAGE", build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)),
    ("AVSBUS_STATUS", build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA)),
]
COMMAND_COUNT = len(AVS_COMMANDS)

# The retry shapes architecture.adoc "Protocol State Machine" names, restricted
# to the ones that last a whole subframe. The debug bus crosses two handshake
# data synchronizers between the AVS clock and the bench, and a handshake sync
# forwards the value it holds when a transfer opens, so the single-cycle
# end-of-subframe and buffered-reply states can pass between two transfers and
# never appear. Their effect is what the interrupt and counter checks below
# measure instead.
RETRY_STATES = (
    "AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME",
    "AVS_RETRY_SHIFT_XMIT_SUBFRAME",
    "AVS_RETRY_SHIFT_RECV_SUBFRAME",
)

# Poll bound for the retry burst. Each retry costs two 32-cycle subframes on an
# AVS clock that is the reference divided by four; expiry is a failure.
POLL_CYCLES = 100
POLL_LIMIT = 120


class smc_avsbus_retry_exhaust_test_seq(SmcCsrSeq):
    """Queue two AVSBus commands at an unresponsive target and exhaust the retries."""

    def __init__(self, name: str = "smc_avsbus_retry_exhaust_test_seq") -> None:
        super().__init__(name)
        self.fsm = AvsFsmMonitor()
        self.retrying_samples = 0
        self.status_polls = 0

    async def body(self) -> None:
        set_avs_sdata(1)
        self.fsm.start()

        cfg0 = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)
        budget = (cfg0 & ~MAX_RETRIES_BM) | ((RETRY_BUDGET << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write("AVS_CFG_0_BUDGET", AVS_CFG_0, budget)
        await self.csr_read("AVS_CFG_0_BUDGET_RB", AVS_CFG_0, expected=budget)

        entry = await self.csr_read("AVS_INTERRUPT_ENTRY", AVS_INTERRUPT)
        assert entry & (SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM) == 0, (
            f"AVS_INTERRUPT already reports a retry failure before any command was queued "
            f"(0x{entry:08x})"
        )

        for name, word in AVS_COMMANDS:
            await self.csr_write(f"AVS_CMD_{name}", AVS_CMD, word)

        final = await self._poll_until_retries_exhausted()
        self.fsm.stop()

        self._check_retry_path()
        self._check_retry_in_progress()
        await self._check_budget_exhausted(final)
        await self._check_interrupt_w1c()

        await self.csr_write("AVS_CFG_0_RESTORE", AVS_CFG_0, cfg0)
        await self.csr_read("AVS_CFG_0_RESTORE_RB", AVS_CFG_0, expected=cfg0)

    async def _poll_until_retries_exhausted(self) -> int:
        """Poll AVS_NORMAL_STATUS until the budget is spent; count retrying samples."""
        status = 0
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            status = await self.csr_read("AVS_NORMAL_STATUS_POLL", AVS_NORMAL_STATUS)
            self.status_polls += 1
            if status & MASTER_IS_RETRYING_BM:
                self.retrying_samples += 1
            interrupt = await self.csr_read("AVS_INTERRUPT_POLL", AVS_INTERRUPT)
            if interrupt & MAX_RETRIES_ATTEMPTED_BM:
                return await self.csr_read("AVS_NORMAL_STATUS_DONE", AVS_NORMAL_STATUS)
        raise AssertionError(
            f"MAX_RETRIES_ATTEMPTED_INT never raised after {COMMAND_COUNT} commands at an "
            f"unresponsive target with MAX_RETRIES={RETRY_BUDGET}, over "
            f"{POLL_LIMIT * POLL_CYCLES} clk_smc_i cycles "
            f"(last AVS_NORMAL_STATUS=0x{status:08x})"
        )

    def _check_retry_path(self) -> None:
        missing = self.fsm.missing(RETRY_STATES)
        assert not missing, (
            f"AVSBus FSM debug bus never held {', '.join(missing)} over two consecutive "
            f"clk_periph_i samples while {COMMAND_COUNT} unanswered commands exhausted a "
            f"budget of {RETRY_BUDGET}; states seen: {sorted(self.fsm.names())}"
        )
        cocotb.log.info(
            "CHK-AVS-RETRY-FSM-PATH: cur_state_debug held every one of the %d retry states "
            "%s over two consecutive samples across %d samples (bit order transcribed from "
            "architecture.adoc 'Protocol State Machine')",
            len(RETRY_STATES),
            ", ".join(RETRY_STATES),
            self.fsm.samples,
        )

    def _check_retry_in_progress(self) -> None:
        assert self.retrying_samples > 0, (
            f"AVS_NORMAL_STATUS.AVS_MASTER_IS_RETRYING was never seen set across "
            f"{self.status_polls} polls spanning the whole retry burst, though the FSM debug "
            f"bus showed the retry states"
        )
        cocotb.log.info(
            "CHK-AVS-RETRY-IN-PROGRESS: AVS_NORMAL_STATUS.AVS_MASTER_IS_RETRYING read back set "
            "on %d of %d polls taken while the burst was in flight, a register-path witness "
            "for the retry independent of the debug bus",
            self.retrying_samples,
            self.status_polls,
        )

    async def _check_budget_exhausted(self, status: int) -> None:
        retries = fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)
        # Each unanswered command spends its whole budget before the controller
        # gives up, so the counter is at least one full budget.
        assert retries >= RETRY_BUDGET, (
            f"AVS_NORMAL_STATUS.TOTAL_RETRIES is {retries} after a command exhausted a budget "
            f"of {RETRY_BUDGET} at an unresponsive target (0x{status:08x})"
        )
        interrupt = await self.csr_read("AVS_INTERRUPT_EXHAUSTED", AVS_INTERRUPT)
        wanted = SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM
        assert interrupt & wanted == wanted, (
            f"AVS_INTERRUPT is 0x{interrupt:08x}; both SLAVE_UNRESPONSIVE_INT "
            f"(0x{SLAVE_UNRESPONSIVE_BM:02x}) and MAX_RETRIES_ATTEMPTED_INT "
            f"(0x{MAX_RETRIES_ATTEMPTED_BM:02x}) must be raised once the budget is spent"
        )
        cocotb.log.info(
            "CHK-AVS-RETRY-BUDGET-EXHAUSTED: TOTAL_RETRIES=%d (at least the programmed budget "
            "of %d) and AVS_INTERRUPT=0x%08x carries SLAVE_UNRESPONSIVE_INT and "
            "MAX_RETRIES_ATTEMPTED_INT after %d unanswered commands",
            retries,
            RETRY_BUDGET,
            interrupt,
            COMMAND_COUNT,
        )

    async def _check_interrupt_w1c(self) -> None:
        await self._wait_bus_idle()
        clear = CLEAR_SLAVE_UNRESPONSIVE_BM | CLEAR_MAX_RETRIES_ATTEMPTED_BM
        await self.csr_write("AVS_INTERRUPT_CLEAR_RETRY", AVS_INTERRUPT_CLEAR, clear)
        # Both flags are raised in the AVS clock domain and the clear request
        # crosses back into it, so the register settles a few cycles after the
        # write. Expiry is a failure, never a pass.
        after = 0
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            after = await self.csr_read("AVS_INTERRUPT_AFTER_CLEAR", AVS_INTERRUPT)
            if after & (SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM) == 0:
                break
        else:
            still = after & (SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM)
            raise AssertionError(
                f"AVS_INTERRUPT still reports 0x{still:02x} after AVS_INTERRUPT_CLEAR <= "
                f"0x{clear:02x} on an idle bus (0x{after:08x})"
            )
        cocotb.log.info(
            "CHK-AVS-RETRY-INT-W1C: AVS_INTERRUPT_CLEAR <= 0x%02x cleared both retry failure "
            "flags on an idle bus; AVS_INTERRUPT=0x%08x",
            clear,
            after,
        )

    async def _wait_bus_idle(self) -> None:
        """Block until AVS_NORMAL_STATUS reports the bus idle, so no flag is re-raised."""
        status = 0
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            status = await self.csr_read("AVS_NORMAL_STATUS_IDLE_WAIT", AVS_NORMAL_STATUS)
            if status & AVS_BUS_IS_IDLE_BM:
                return
        raise AssertionError(
            f"AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE never set after the retry budget was spent "
            f"(last 0x{status:08x})"
        )
