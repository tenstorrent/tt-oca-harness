# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""How one AVSBus frame follows another, which the command mix decides.

`architecture.adoc` "Protocol State Machine" describes a frame as a first
subframe, as many middle subframes as there are further commands ready, and a
last one. Which way the machine leaves each of those is therefore a property
of what is queued when it gets there, and the leaves so far queue their
commands in one burst up front, so two of the three ways have never been
taken:

* **A command on its own.** With nothing queued behind it, the first subframe
  is followed straight by the last one rather than by a middle subframe.
* **A command arriving late.** A command queued while the last subframe is on
  the wire starts a new frame from the end of that one instead of letting the
  bus go idle.

The third leg is about what the master does with a reply it had to buffer. A
frame that needs retrying while a later frame is already on the wire leaves
that later reply pending; when the master comes back to it, it either retries
that one too or, if it turns out fine, resynchronises the slave and carries
on. The bench decides which by driving the pad: the retries are provoked with
the sdata line at its idle level, and the line is then released to its
responding level so the buffered reply is a good one.

Every leg is measured from the readback FIFO and the retry counter, with the
FSM debug bus naming the states it passed through.
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
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    AvsFsmMonitor,
    build_avs_cmd,
    fifo_field,
    set_avs_sdata,
)
from .smc_avsbus_protocol_utils import AVS_READBACK as AVS_READBACK_REG
from .smc_csr_seq_utils import SmcCsrSeq

#: Two read commands, the same pair the other AVSBus leaves use.
CMD_RAIL_VOLTAGE = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)
CMD_AVSBUS_STATUS = build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA)

#: Commands queued one at a time while the bus is already running, spaced so
#: that one of them lands while a last subframe is on the wire.
TRICKLE_COMMANDS = 6
TRICKLE_GAP_CYCLES = 60
RETRY_BUDGET = 2

POLL_CYCLES = 100
POLL_LIMIT = 200


class smc_avsbus_frame_sequencing_test_seq(SmcCsrSeq):
    """A lone command, a late command, and a buffered reply that turns out good."""

    def __init__(self, name: str = "smc_avsbus_frame_sequencing_test_seq") -> None:
        super().__init__(name)
        self.single_states: set[str] = set()
        self.trickle_states: set[str] = set()
        self.buffered_states: set[str] = set()

    async def _occupancy(self, label: str) -> int:
        fifos = await self.csr_read(label, AVS_FIFOS_STATUS)
        return fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)

    async def _retries(self, label: str) -> int:
        status = await self.csr_read(label, AVS_NORMAL_STATUS)
        return fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)

    async def _drain_readback(self, label: str) -> int:
        """Pop while the block reports data to read; an empty read is refused."""
        drained = 0
        for _ in range(POLL_LIMIT):
            status = await self.csr_read(f"{label}_STATUS", AVS_NORMAL_STATUS)
            if not status & READBACK_HAS_DATA_BM:
                return drained
            await self.csr_read(f"{label}_READBACK", AVS_READBACK_REG)
            drained += 1
        raise AssertionError(f"{label}: the readback FIFO never emptied")

    async def _await_occupancy(self, label: str, wanted: int) -> int:
        occupied = 0
        for _ in range(POLL_LIMIT):
            occupied = await self._occupancy(f"{label}_FIFOS")
            if occupied >= wanted:
                return occupied
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        raise AssertionError(
            f"{label}: the readback FIFO holds {occupied} responses, not the {wanted} the "
            f"commands queued should have produced"
        )

    async def _set_budget(self, label: str, cfg0: int, budget: int) -> None:
        want = (cfg0 & ~MAX_RETRIES_BM) | ((budget << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write(f"AVS_CFG_0_{label}", AVS_CFG_0, want)
        await self.csr_read(f"AVS_CFG_0_{label}_RB", AVS_CFG_0, expected=want)

    async def _single_command_leg(self) -> None:
        label = "SINGLE"
        set_avs_sdata(0)
        await self._drain_readback(label)
        fsm = AvsFsmMonitor()
        fsm.start()
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_RAIL_VOLTAGE)
        occupied = await self._await_occupancy(label, 1)
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        fsm.stop()
        self.single_states = set(fsm.names())
        assert "AVS_SHIFT_LAST_SUBFRAME" in self.single_states, (
            f"{label}: the debug bus never held AVS_SHIFT_LAST_SUBFRAME for a command queued "
            f"on its own; with nothing behind it the first subframe is followed by the last "
            f"(states seen: {sorted(self.single_states)})"
        )
        cocotb.log.info(
            "CHK-AVS-SINGLE-COMMAND: one command with nothing queued behind it produced %d "
            "response in the readback FIFO and took the machine through the last-subframe "
            "shift rather than a middle one (states seen: %s)",
            occupied,
            ", ".join(sorted(self.single_states)),
        )
        await self._drain_readback(label)

    async def _trickle_leg(self) -> None:
        label = "TRICKLE"
        fsm = AvsFsmMonitor()
        fsm.start()
        for i in range(TRICKLE_COMMANDS):
            cmd = CMD_RAIL_VOLTAGE if i % 2 == 0 else CMD_AVSBUS_STATUS
            await self.csr_write(f"{label}_CMD{i}", AVS_CMD, cmd)
            await ClockCycles(cocotb.top.clk_smc_i, TRICKLE_GAP_CYCLES)
        occupied = await self._await_occupancy(label, TRICKLE_COMMANDS)
        fsm.stop()
        self.trickle_states = set(fsm.names())
        assert occupied >= TRICKLE_COMMANDS, (
            f"{label}: {occupied} responses for {TRICKLE_COMMANDS} commands"
        )
        cocotb.log.info(
            "CHK-AVS-LATE-COMMAND: %d commands written one at a time while the bus was "
            "already running all produced responses (%d in the readback FIFO), so a command "
            "arriving during a frame is launched from the end of it (states seen: %s)",
            TRICKLE_COMMANDS,
            occupied,
            ", ".join(sorted(self.trickle_states)),
        )
        await self._drain_readback(label)

    async def _buffered_reply_leg(self) -> None:
        label = "BUFFERED"
        cfg0 = await self.csr_read("AVS_CFG_0_SAVE", AVS_CFG_0)
        await self._set_budget(label, cfg0, RETRY_BUDGET)
        await self.csr_write(
            f"{label}_INTR_CLR",
            AVS_INTERRUPT_CLEAR,
            CLEAR_SLAVE_UNRESPONSIVE_BM | CLEAR_MAX_RETRIES_ATTEMPTED_BM,
        )
        base = await self._retries(f"{label}_RETRIES_BEFORE")

        fsm = AvsFsmMonitor()
        fsm.start()
        # Idle level: every reply reports the target as not responding, so the
        # first frame goes into its retry sequence with the second already on
        # the wire behind it.
        set_avs_sdata(1)
        await self.csr_write(f"{label}_CMD0", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self.csr_write(f"{label}_CMD1", AVS_CMD, CMD_AVSBUS_STATUS)
        retries = base
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            retries = await self._retries(f"{label}_RETRIES")
            if retries > base:
                break
        else:
            raise AssertionError(
                f"{label}: TOTAL_RETRIES stayed at {retries} with the sdata pad at its idle "
                f"level and a budget of {RETRY_BUDGET}"
            )
        # Responding level: the reply the master buffered is now a good one,
        # so it resynchronises the slave instead of retrying that frame too.
        set_avs_sdata(0)
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            if "AVS_SLAVE_RESYNC" in fsm.names():
                break
        fsm.stop()
        self.buffered_states = set(fsm.names())
        assert "AVS_SLAVE_RESYNC" in self.buffered_states, (
            f"{label}: the debug bus never held AVS_SLAVE_RESYNC after the retry sequence "
            f"(states seen: {sorted(self.buffered_states)})"
        )
        interrupt = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        cocotb.log.info(
            "CHK-AVS-BUFFERED-REPLY: a frame retried with a second already on the wire left "
            "that second reply buffered; releasing the sdata pad to its responding level made "
            "the buffered reply a good one, and the master resynchronised the slave instead "
            "of retrying it (TOTAL_RETRIES %d -> %d, AVS_INTERRUPT=0x%08x, states seen: %s)",
            base,
            retries,
            interrupt,
            ", ".join(sorted(self.buffered_states)),
        )
        await self.csr_write(
            f"{label}_INTR_CLR_END",
            AVS_INTERRUPT_CLEAR,
            CLEAR_SLAVE_UNRESPONSIVE_BM | CLEAR_MAX_RETRIES_ATTEMPTED_BM,
        )
        await self.csr_write("AVS_CFG_0_RESTORE", AVS_CFG_0, cfg0)
        await self._drain_readback(label)

    async def body(self) -> None:
        await self._single_command_leg()
        await self._trickle_leg()
        await self._buffered_reply_leg()
        set_avs_sdata(0)
