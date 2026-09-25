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
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_avsbus_protocol_utils import (
    AVS_CFG_0,
    AVS_CMD,
    AVS_CODE_NAME,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_NORMAL_STATUS,
    AVS_STATE,
    CLEAR_MAX_RETRIES_ATTEMPTED_BM,
    CLEAR_SLAVE_UNRESPONSIVE_BM,
    CMD_FIFO_OCCUPIED_BM,
    CMD_FIFO_OCCUPIED_BP,
    CMD_TYPE_READ,
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    RB_FIFO_DEPTH,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    AvsFsmMonitor,
    avs_field,
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

INT_READBACK_OVERFLOW = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__READBACK_OVERFLOW_INT_bm")
INT_SLAVE_ISSUED = avs_field("AVSBUS_CONTROLLER__AVS_INTERRUPT__AVS_SLAVE_ISSUED_INTERRUPT_bm")
CLEAR_READBACK_OVERFLOW = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_READBACK_OVERFLOW_INT_bm"
)
CLEAR_SLAVE_ISSUED = avs_field(
    "AVSBUS_CONTROLLER__AVS_INTERRUPT_CLEAR__CLEAR_AVS_SLAVE_ISSUED_INTERRUPT_bm"
)
#: Commands queued together for the suppressed-retry leg: enough that the
#: first frame has a middle subframe, which only a command already waiting
#: behind it produces.
SUPPRESSED_COMMANDS = 3
#: Bound on the wait for a state on the FSM debug bus, in clk_periph_i cycles.
STATE_WAIT_CYCLES = 20_000


class smc_avsbus_frame_sequencing_test_seq(SmcCsrSeq):
    """A lone command, a late command, and a buffered reply that turns out good."""

    def __init__(self, name: str = "smc_avsbus_frame_sequencing_test_seq") -> None:
        super().__init__(name)
        self.single_states: set[str] = set()
        self.trickle_states: set[str] = set()
        self.buffered_states: set[str] = set()
        self.lone_retry: list[str] = []
        self.back_to_back: tuple[list[str], int] = ([], 0)
        self.suppressed_mid: tuple[int, list[str]] = (0, [])
        self.slave_clear: tuple[int, int] = (0, 0)
        self.overflow: tuple[int, int] = (0, 0)

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

    @staticmethod
    def _state_code() -> int | None:
        raw = cocotb.top.tb_avsbus_cur_state_debug.value
        return int(raw) if raw.is_resolvable else None

    async def _wait_state(self, label: str, name: str) -> None:
        """Bounded wait until the FSM debug bus holds ``name`` on two samples."""
        want = AVS_STATE[name]
        previous = None
        for _ in range(STATE_WAIT_CYCLES):
            await RisingEdge(cocotb.top.clk_periph_i)
            code = self._state_code()
            if code == want and previous == want:
                return
            previous = code
        raise AssertionError(f"{label}: the FSM debug bus never held {name}")

    async def _record_sequence(self, into: list[str], stop_after: int) -> None:
        """Append each state the debug bus holds for two samples, in order."""
        previous = None
        for _ in range(stop_after):
            await RisingEdge(cocotb.top.clk_periph_i)
            code = self._state_code()
            if code is not None and code == previous:
                name = AVS_CODE_NAME.get(code)
                if name and (not into or into[-1] != name):
                    into.append(name)
            previous = code

    async def _clear_all_retry_flags(self, label: str) -> None:
        await self.csr_write(
            f"{label}_INTR_CLR",
            AVS_INTERRUPT_CLEAR,
            CLEAR_SLAVE_UNRESPONSIVE_BM | CLEAR_MAX_RETRIES_ATTEMPTED_BM | CLEAR_READBACK_OVERFLOW,
        )

    async def _settle_idle(self, label: str) -> None:
        set_avs_sdata(0)
        await self._wait_state(label, "AVS_IDLE")
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES * 4)
        await self._drain_readback(label)

    async def _lone_retry_leg(self) -> None:
        """A command on its own, retried: the retry is launched from the last subframe."""
        label = "LONE_RETRY"
        cfg0 = await self.csr_read(f"{label}_CFG0", AVS_CFG_0)
        await self._set_budget(label, cfg0, RETRY_BUDGET)
        await self._clear_all_retry_flags(label)
        await self._settle_idle(label)
        seq: list[str] = []
        recorder = cocotb.start_soon(self._record_sequence(seq, STATE_WAIT_CYCLES))
        set_avs_sdata(1)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self._wait_state(label, "AVS_RETRY_SHIFT_XMIT_SUBFRAME")
        await self._settle_idle(label)
        recorder.kill()
        assert "AVS_SHIFT_LAST_SUBFRAME" in seq, (
            f"{label}: the lone command never reached its last subframe ({seq})"
        )
        assert "AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME" not in seq, (
            f"{label}: a transmit-and-receive retry appeared for a command with nothing "
            f"behind it; with no second frame on the wire the retry transmits only ({seq})"
        )
        await self._clear_all_retry_flags(f"{label}_END")
        await self.csr_write(f"{label}_CFG0_RESTORE", AVS_CFG_0, cfg0)
        self.lone_retry = seq

    async def _back_to_back_leg(self) -> None:
        """A command written while the last subframe of another is on the wire."""
        label = "BACK_TO_BACK"
        await self._settle_idle(label)
        seq: list[str] = []
        recorder = cocotb.start_soon(self._record_sequence(seq, STATE_WAIT_CYCLES))
        await self.csr_write(f"{label}_CMD0", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self._wait_state(label, "AVS_SHIFT_LAST_SUBFRAME")
        await self.csr_write(f"{label}_CMD1", AVS_CMD, CMD_AVSBUS_STATUS)
        occupied = await self._await_occupancy(label, 2)
        recorder.kill()
        last = seq.index("AVS_SHIFT_LAST_SUBFRAME")
        after = [s for s in seq[last + 1 :] if s not in ("AVS_END_LAST_SUBFRAME",)]
        assert after and after[0] == "AVS_SHIFT_1ST_SUBFRAME", (
            f"{label}: after the first frame's last subframe the machine went to "
            f"{after[:1] or 'nothing'}, not straight to the next frame's first subframe; a "
            f"command waiting at the end of a frame is launched from there ({seq})"
        )
        self.back_to_back = (seq, occupied)
        await self._drain_readback(label)

    async def _suppressed_mid_leg(self) -> None:
        """Retries suppressed with further commands queued behind a middle subframe."""
        label = "SUPPRESSED_MID"
        cfg0 = await self.csr_read(f"{label}_CFG0", AVS_CFG_0)
        await self._set_budget(label, cfg0, 0)
        await self._clear_all_retry_flags(label)
        await self._settle_idle(label)
        base = await self._retries(f"{label}_BASE")
        seq: list[str] = []
        recorder = cocotb.start_soon(self._record_sequence(seq, STATE_WAIT_CYCLES))
        set_avs_sdata(1)
        for i in range(SUPPRESSED_COMMANDS):
            await self.csr_write(f"{label}_CMD{i}", AVS_CMD, CMD_RAIL_VOLTAGE)
        occupied = await self._await_occupancy(label, SUPPRESSED_COMMANDS)
        recorder.kill()
        retries = await self._retries(f"{label}_AFTER")
        assert "AVS_SHIFT_MID_SUBFRAME" in seq, (
            f"{label}: no middle subframe appeared with {SUPPRESSED_COMMANDS} commands queued ({seq})"
        )
        assert retries == base and not any("RETRY" in s for s in seq), (
            f"{label}: a retry happened with MAX_RETRIES at 0 (TOTAL_RETRIES {base} -> "
            f"{retries}, states {seq})"
        )
        self.suppressed_mid = (occupied, seq)
        await self._settle_idle(label)
        await self._clear_all_retry_flags(f"{label}_END")
        await self.csr_write(f"{label}_CFG0_RESTORE", AVS_CFG_0, cfg0)

    async def _overflow_leg(self) -> None:
        """The buffered reply of a retried pair, pushed into a FIFO already full.

        Each launch decision checks the room left for the reply of the frame it
        launches. A frame launched while an earlier one is still retrying has
        its reply buffered and pushed later, after the earlier reply has taken
        the last slot, so with one slot left before the pair the second reply
        meets a full FIFO.

        The pair only goes out as a middle subframe if the second command is
        queued before the first subframe ends, which two register writes in a
        row cannot promise against a fast AVS clock. `architecture.adoc` says
        the master launches nothing while the readback FIFO is full, so the
        pair is queued behind a full FIFO and one reply is then popped: both
        commands are waiting when the first launch is decided.
        """
        label = "OVERFLOW"
        cfg0 = await self.csr_read(f"{label}_CFG0", AVS_CFG_0)
        await self._set_budget(label, cfg0, RETRY_BUDGET)
        await self._clear_all_retry_flags(label)
        await self._settle_idle(label)
        prefill = RB_FIFO_DEPTH - 1
        for i in range(prefill):
            await self.csr_write(f"{label}_PREFILL{i}", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self._await_occupancy(label, prefill)
        await self.csr_write(f"{label}_FILL", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self._await_occupancy(label, RB_FIFO_DEPTH)
        interrupt = await self.csr_read(f"{label}_INTR_BEFORE", AVS_INTERRUPT)
        assert interrupt & INT_READBACK_OVERFLOW == 0, (
            f"{label}: READBACK_OVERFLOW_INT already set before the pair (0x{interrupt:08x})"
        )
        set_avs_sdata(1)
        await self.csr_write(f"{label}_CMD0", AVS_CMD, CMD_RAIL_VOLTAGE)
        await self.csr_write(f"{label}_CMD1", AVS_CMD, CMD_AVSBUS_STATUS)
        fifos = await self.csr_read(f"{label}_PAIR_QUEUED", AVS_FIFOS_STATUS)
        queued = fifo_field(fifos, CMD_FIFO_OCCUPIED_BM, CMD_FIFO_OCCUPIED_BP)
        assert queued == 2, (
            f"{label}: {queued} of the pair are still queued behind a full readback FIFO, "
            f"not 2; the master launched a command with no room for its reply "
            f"(AVS_FIFOS_STATUS=0x{fifos:08x})"
        )
        await self.csr_read(f"{label}_POP", AVS_READBACK_REG)
        await self._wait_state(label, "AVS_RETRY_SHIFT_XMIT_AND_RECV_SUBFRAME")
        set_avs_sdata(0)
        for _ in range(POLL_LIMIT):
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
            interrupt = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
            if interrupt & INT_READBACK_OVERFLOW:
                break
        occupied = await self._occupancy(f"{label}_FIFOS")
        self.overflow = (interrupt, occupied)
        assert interrupt & INT_READBACK_OVERFLOW, (
            f"{label}: READBACK_OVERFLOW_INT stayed clear with {prefill} of {RB_FIFO_DEPTH} "
            f"slots filled before a retried pair (AVS_INTERRUPT=0x{interrupt:08x}, "
            f"{occupied} occupied)"
        )
        await self.csr_write(f"{label}_OVF_CLR", AVS_INTERRUPT_CLEAR, CLEAR_READBACK_OVERFLOW)
        cleared = await self.csr_read(f"{label}_INTR_CLEARED", AVS_INTERRUPT)
        assert cleared & INT_READBACK_OVERFLOW == 0, (
            f"{label}: READBACK_OVERFLOW_INT survived its clear (0x{cleared:08x})"
        )
        await self._settle_idle(label)
        await self._clear_all_retry_flags(f"{label}_END")
        await self.csr_write(f"{label}_CFG0_RESTORE", AVS_CFG_0, cfg0)

    async def _slave_interrupt_clear_leg(self) -> None:
        """Clear the slave-issued interrupt once nothing can raise it again.

        `avsbus_controller.sv` raises the source in two places: while the bus
        is idle and the slave holds sdata low, and at the end of a first
        subframe whose reply opens with two zero bits. With sdata at its
        responding level, low, both keep raising it, so a clear is overtaken
        at once. With sdata released high neither can, and a clear has to
        remove the source and keep it removed until sdata is taken low again.
        """
        label = "SLAVE_INT_CLEAR"
        await self._settle_idle(label)
        pending = await self.csr_read(f"{label}_PENDING", AVS_INTERRUPT)
        assert pending & INT_SLAVE_ISSUED, (
            f"{label}: the slave-issued interrupt is not pending at idle with sdata held low "
            f"(0x{pending:08x})"
        )
        set_avs_sdata(1)
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_SLAVE_ISSUED)
        cleared = pending
        for _ in range(POLL_LIMIT):
            cleared = await self.csr_read(f"{label}_CLEARED", AVS_INTERRUPT)
            if not cleared & INT_SLAVE_ISSUED:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: the slave-issued interrupt survived its clear with sdata released "
                f"high (0x{cleared:08x})"
            )
        await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES * 20)
        held = await self.csr_read(f"{label}_HELD", AVS_INTERRUPT)
        assert held & INT_SLAVE_ISSUED == 0, (
            f"{label}: the slave-issued interrupt came back with sdata still high "
            f"(0x{held:08x}); nothing on an idle bus should raise it"
        )
        set_avs_sdata(0)
        rearmed = held
        for _ in range(POLL_LIMIT):
            rearmed = await self.csr_read(f"{label}_REARMED", AVS_INTERRUPT)
            if rearmed & INT_SLAVE_ISSUED:
                break
            await ClockCycles(cocotb.top.clk_smc_i, POLL_CYCLES)
        else:
            raise AssertionError(
                f"{label}: the slave-issued interrupt did not come back once sdata was taken "
                f"low at idle (0x{rearmed:08x})"
            )
        self.slave_clear = (held, rearmed)

    async def body(self) -> None:
        await self._single_command_leg()
        await self._trickle_leg()
        await self._buffered_reply_leg()
        await self._lone_retry_leg()
        await self._back_to_back_leg()
        await self._suppressed_mid_leg()
        await self._slave_interrupt_clear_leg()
        await self._overflow_leg()
        set_avs_sdata(0)
        cocotb.log.info(
            "CHK-AVS-LONE-RETRY: a command with nothing behind it, answered as not "
            "responding, was retried from its last subframe with a transmit-only retry (%s)",
            ", ".join(self.lone_retry),
        )
        cocotb.log.info(
            "CHK-AVS-BACK-TO-BACK: a command written while another frame's last subframe was "
            "on the wire started its own first subframe straight from the end of it, and both "
            "replies arrived (%d occupied; %s)",
            self.back_to_back[1],
            ", ".join(self.back_to_back[0]),
        )
        cocotb.log.info(
            "CHK-AVS-SUPPRESSED-MID: with MAX_RETRIES at 0 and %d commands queued, every "
            "failing reply was kept without a retry, including the one ended at a middle "
            "subframe with more commands waiting (%d replies in the readback FIFO)",
            SUPPRESSED_COMMANDS,
            self.suppressed_mid[0],
        )
        cocotb.log.info(
            "CHK-AVS-SLAVE-INT-CLEAR: the slave-issued interrupt, cleared with sdata released "
            "high, stayed clear (0x%08x) until sdata was taken low again at idle, when it came "
            "back (0x%08x)",
            self.slave_clear[0],
            self.slave_clear[1],
        )
        cocotb.log.info(
            "CHK-AVS-READBACK-OVERFLOW: with one readback slot left before a retried pair, the "
            "second frame's buffered reply met a full FIFO and raised READBACK_OVERFLOW_INT "
            "(AVS_INTERRUPT=0x%08x, %d occupied), which its clear removed",
            self.overflow[0],
            self.overflow[1],
        )
