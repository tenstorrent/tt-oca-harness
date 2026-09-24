# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus with retries suppressed: the same failure, answered differently.

`smc_avsbus_retry_exhaust_test` points the controller at a target that never
answers with a retry budget to spend. `AVS_CFG_0.MAX_RETRIES` also takes 0,
which the design reads as "programmed to suppress retries": the failing reply
is pushed to the readback FIFO as it stands and the controller carries on
instead of resending. That answer had never been asked for, so nothing showed
that a budget of 0 suppresses anything.

The failure is produced the same way -- the bench holds the AVSBus sdata pad
at its idle-high level, so every received subframe carries the Frame Valid bit
that `interface.adoc` defines as the target not responding -- and the
difference is only in the budget.

A suppressed retry is mostly an absence: no retry states, no retry counter, no
budget-exhausted interrupt. An absence proves nothing on its own
([NEGATIVE-NEEDS-POSITIVE-CONTROL]), so the same stimulus is then given a
budget of 1 on the same registers and the same probes, and those indicators
have to move.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_avsbus_protocol_utils import (
    AVS_CFG_0,
    AVS_CMD,
    AVS_FIFOS_STATUS,
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
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
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

# The same two read commands the retry leaf queues, so the two leaves differ
# only in the budget.
AVS_COMMANDS = [
    ("RAIL_VOLTAGE", build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)),
    ("AVSBUS_STATUS", build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA)),
]
CONTROL_BUDGET = 1

# The retry shift states, none of which may appear while retries are
# suppressed.
RETRY_STATES = (
    "AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME",
    "AVS_RETRY_SHIFT_XMIT_SUBFRAME",
    "AVS_RETRY_SHIFT_RECV_SUBFRAME",
)

POLL_CYCLES = 100
POLL_LIMIT = 120


class smc_avsbus_retry_suppressed_test_seq(SmcCsrSeq):
    """A retry budget of 0 must answer the failure without resending."""

    def __init__(self, name: str = "smc_avsbus_retry_suppressed_test_seq") -> None:
        super().__init__(name)
        self.polls = 0
        self.retrying_samples = 0

    async def _set_budget(self, label: str, cfg0: int, budget: int) -> None:
        want = (cfg0 & ~MAX_RETRIES_BM) | ((budget << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write(f"AVS_CFG_0_{label}", AVS_CFG_0, want)
        await self.csr_read(f"AVS_CFG_0_{label}_RB", AVS_CFG_0, expected=want)

    async def _clear_failures(self, label: str, *, require_clear: bool = False) -> int:
        """Clear both retry failure sources; optionally require them to stay clear.

        Once the bench has held sdata at its idle level through a burst, the
        controller's own resync traffic keeps meeting the same failing reply,
        so the source can be pending again by the next read. Only the first
        leg, which runs before any command, requires the clear to hold.
        """
        await self.csr_write(
            f"AVS_INTERRUPT_CLEAR_{label}",
            AVS_INTERRUPT_CLEAR,
            CLEAR_SLAVE_UNRESPONSIVE_BM | CLEAR_MAX_RETRIES_ATTEMPTED_BM,
        )
        interrupt = await self.csr_read(f"AVS_INTERRUPT_{label}_CLEARED", AVS_INTERRUPT)
        if require_clear:
            assert interrupt & (SLAVE_UNRESPONSIVE_BM | MAX_RETRIES_ATTEMPTED_BM) == 0, (
                f"{label}: AVS_INTERRUPT still reports a retry failure after both sources "
                f"were cleared (0x{interrupt:08x}) before any command was queued"
            )
        return interrupt

    async def _queue_commands(self, label: str) -> None:
        for name, word in AVS_COMMANDS:
            await self.csr_write(f"AVS_CMD_{label}_{name}", AVS_CMD, word)

    async def _poll_for_unresponsive(self, label: str) -> int:
        """Poll until the target is reported unresponsive, sampling the retry flag."""
        status = 0
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            status = await self.csr_read(f"AVS_NORMAL_STATUS_{label}", AVS_NORMAL_STATUS)
            self.polls += 1
            if status & MASTER_IS_RETRYING_BM:
                self.retrying_samples += 1
            interrupt = await self.csr_read(f"AVS_INTERRUPT_{label}_POLL", AVS_INTERRUPT)
            if interrupt & SLAVE_UNRESPONSIVE_BM:
                return interrupt
        raise AssertionError(
            f"{label}: SLAVE_UNRESPONSIVE_INT never raised for {len(AVS_COMMANDS)} commands "
            f"at a target holding sdata at its idle level (last "
            f"AVS_NORMAL_STATUS=0x{status:08x})"
        )

    async def body(self) -> None:
        set_avs_sdata(1)
        cfg0 = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)

        # ---- Suppressed: budget 0 -------------------------------------------
        fsm = AvsFsmMonitor()
        fsm.start()
        await self._set_budget("SUPPRESS", cfg0, 0)
        await self._clear_failures("SUPPRESS", require_clear=True)
        before = await self.csr_read("AVS_NORMAL_STATUS_BEFORE", AVS_NORMAL_STATUS)
        base_retries = fifo_field(before, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)

        await self._queue_commands("SUPPRESS")
        interrupt = await self._poll_for_unresponsive("SUPPRESS")
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES * 4)
        fsm.stop()

        after = await self.csr_read("AVS_NORMAL_STATUS_AFTER", AVS_NORMAL_STATUS)
        retries = fifo_field(after, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)
        fifos = await self.csr_read("AVS_FIFOS_STATUS_AFTER", AVS_FIFOS_STATUS)
        occupied = fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)
        seen = sorted(fsm.names() & set(RETRY_STATES))

        assert retries == base_retries, (
            f"AVS_NORMAL_STATUS.TOTAL_RETRIES moved from {base_retries} to {retries} with "
            f"MAX_RETRIES programmed to 0; a budget of 0 suppresses the resend"
        )
        assert self.retrying_samples == 0, (
            f"AVS_NORMAL_STATUS.AVS_MASTER_IS_RETRYING read back set on "
            f"{self.retrying_samples} of {self.polls} polls with MAX_RETRIES programmed to 0"
        )
        assert not seen, (
            f"the AVSBus FSM debug bus held the retry state(s) {', '.join(seen)} with "
            f"MAX_RETRIES programmed to 0"
        )
        assert interrupt & MAX_RETRIES_ATTEMPTED_BM == 0, (
            f"MAX_RETRIES_ATTEMPTED_INT is raised (AVS_INTERRUPT=0x{interrupt:08x}) with a "
            f"budget of 0; no retry was attempted, so no budget can have run out"
        )
        assert occupied > 0, (
            f"the readback FIFO holds {occupied} entries after {len(AVS_COMMANDS)} commands "
            f"were answered with a failing reply and retries suppressed; the reply is pushed "
            f"as it stands rather than dropped"
        )
        cocotb.log.info(
            "CHK-AVS-RETRY-SUPPRESSED: with MAX_RETRIES=0, %d unanswered commands raised "
            "SLAVE_UNRESPONSIVE_INT (AVS_INTERRUPT=0x%08x) while TOTAL_RETRIES stayed at %d, "
            "AVS_MASTER_IS_RETRYING read clear on all %d polls, no retry state appeared on "
            "the debug bus over %d samples, MAX_RETRIES_ATTEMPTED_INT stayed clear, and the "
            "failing replies still reached the readback FIFO (%d occupied)",
            len(AVS_COMMANDS),
            interrupt,
            retries,
            self.polls,
            fsm.samples,
            occupied,
        )

        # ---- Control: budget 1 on the same probes ----------------------------
        control_fsm = AvsFsmMonitor()
        control_fsm.start()
        self.polls = 0
        self.retrying_samples = 0
        await self._set_budget("CONTROL", cfg0, CONTROL_BUDGET)
        await self._clear_failures("CONTROL")
        base = fifo_field(
            await self.csr_read("AVS_NORMAL_STATUS_CONTROL_BEFORE", AVS_NORMAL_STATUS),
            TOTAL_RETRIES_BM,
            TOTAL_RETRIES_BP,
        )
        await self._queue_commands("CONTROL")
        control_retries = base
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            status = await self.csr_read("AVS_NORMAL_STATUS_CONTROL", AVS_NORMAL_STATUS)
            control_retries = fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)
            if control_retries > base:
                break
        control_fsm.stop()
        control_seen = sorted(control_fsm.names() & set(RETRY_STATES))
        assert control_retries > base, (
            f"AVS_NORMAL_STATUS.TOTAL_RETRIES stayed at {control_retries} with a budget of "
            f"{CONTROL_BUDGET} against the same unanswered commands, so the counter above "
            f"proves nothing"
        )
        assert control_seen, (
            f"no retry state appeared on the debug bus with a budget of {CONTROL_BUDGET} "
            f"either, so its absence above proves nothing; states seen: "
            f"{sorted(control_fsm.names())}"
        )
        cocotb.log.info(
            "CHK-AVS-RETRY-SUPPRESSED-CONTROL: the same commands with MAX_RETRIES=%d took "
            "TOTAL_RETRIES from %d to %d and put %s on the debug bus, so the suppressed leg "
            "above is measuring live probes",
            CONTROL_BUDGET,
            base,
            control_retries,
            ", ".join(control_seen),
        )

        await self._clear_failures("RESTORE")
        await self.csr_write("AVS_CFG_0_RESTORE", AVS_CFG_0, cfg0)
        await self.csr_read("AVS_CFG_0_RESTORE_RB", AVS_CFG_0, expected=cfg0)
        set_avs_sdata(0)
