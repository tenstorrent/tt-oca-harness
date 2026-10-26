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

After those legs the sdata pad is handed to ``AvsReplyDriver``, the bit-by-bit
responder of ``smc_avsbus_slave_reply_test``, which answers each master
subframe with a queued slave subframe. ``architecture.adoc`` "Error Handling
and Diagnostics" makes SlaveAck 1 and 2 retry codes, counted in
``TOTAL_RETRIES``, with ``MAX_RETRIES`` + 1 attempts in all before
``MAX_RETRIES_ATTEMPTED_INT``:

* the accepted CRC-3 code of every reply shape is found first with
  ``MAX_RETRIES`` at 0, since no pinned document gives the polynomial and
  exactly one of the eight codes updates ``AVS_LATEST_SLAVE_SUBFRAME``,
* budgets of 8 and 10 against SlaveAck 1 on every attempt, and 8 against
  SlaveAck 2, must send exactly ``MAX_RETRIES`` + 1 identical master subframes,
  raise ``TOTAL_RETRIES`` by the budget and set the interrupt; the
  ``AVS_READBACK`` content after exhaustion is logged only (SF-032),
* success on retry 1 and retry 7 costs exactly that many retries, raises no
  interrupt and delivers the SlaveAck 0 reply,
* with two commands back to back and the first retried twice, the reply to the
  second waits and is delivered after the first's, and a slave resync follows,
* ``MAX_RETRIES_ATTEMPTED_INT`` reaches the AVSBus interrupt line only while
  its ``AVS_INTERRUPT_MASK`` bit is clear, and not after the clear.

S4 needs the interrupt clear before it starts, so S6 raises the flag again
with the S3 stimulus before it samples the line.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import smc_addr
from .smc_avsbus_protocol_utils import (
    AVS_BUS_IS_IDLE_BM,
    AVS_CFG_0,
    AVS_CMD,
    AVS_FIFOS_STATUS,
    AVS_INTERRUPT,
    AVS_INTERRUPT_CLEAR,
    AVS_INTERRUPT_MASK,
    AVS_NORMAL_STATUS,
    CLEAR_MAX_RETRIES_ATTEMPTED_BM,
    CLEAR_SLAVE_UNRESPONSIVE_BM,
    CMD_TYPE_READ,
    MASTER_IS_RETRYING_BM,
    MAX_RETRIES_ATTEMPTED_BM,
    MAX_RETRIES_BM,
    MAX_RETRIES_BP,
    RB_FIFO_DEPTH,
    RB_FIFO_OCCUPIED_BM,
    RB_FIFO_OCCUPIED_BP,
    READ_CMD_DATA,
    READBACK_HAS_DATA_BM,
    SLAVE_UNRESPONSIVE_BM,
    TOTAL_RETRIES_BM,
    TOTAL_RETRIES_BP,
    AvsFsmMonitor,
    avs_field,
    build_avs_cmd,
    expected_master_subframe,
    fifo_field,
    set_avs_sdata,
)
from .smc_avsbus_protocol_utils import AVS_READBACK as AVS_READBACK_REG
from .smc_avsbus_slave_reply_test_seq import AvsReplyDriver, reply
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

AVS_LATEST = smc_addr("SMC_TOP_SMC_AVSBUS_CONTROLLER_AVS_LATEST_SLAVE_SUBFRAME_BASE_ADDR")
IN_RESYNC_BM = avs_field("AVSBUS_CONTROLLER__AVS_NORMAL_STATUS__AVS_SLAVE_IS_IN_RESYNC_bm")
#: The AVS_READBACK fields, in the slave subframe's own bit positions.
READBACK_FIELDS = (
    avs_field("AVSBUS_CONTROLLER__AVS_READBACK__SLAVE_ACK_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__STATUS_RESPONSE_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CMD_DATA_bm")
    | avs_field("AVSBUS_CONTROLLER__AVS_READBACK__CRC_bm")
)
CLEAR_ALL = 0x1FF
MASK_ALL = 0x1FF
#: interface.adoc "AVSBus Interrupt Sources": bit 5 is MAX_RETRIES_ATTEMPTED_INT.
MASK_KEEP_MAX_RETRIES = 0x1DF
CLEAR_MAX_RETRIES_ONLY = 0x20
CRC_CODES = 8
#: interface.adoc "AVSBus Slave Subframe" acknowledge codes.
ACK_GOOD, ACK_UNAVAILABLE, ACK_BAD_CRC = 0, 1, 2

#: Reply shapes, CRC-3 bits zero; the accepted code is found at run time.
SHAPES = {
    "ACK1": reply(ACK_UNAVAILABLE, 0x00, 0x5678),
    "ACK2": reply(ACK_BAD_CRC, 0x08, 0x9ABC),
    "GOOD_1111": reply(ACK_GOOD, 0x10, 0x1111),
    "GOOD_2222": reply(ACK_GOOD, 0x10, 0x2222),
}
LONG_BUDGETS = (8, 10)
ACK2_BUDGET = 8
EARLY_RETRIES = (1, 7)
HELD_RETRIES = 2

CMD_A = build_avs_cmd(CMD_TYPE_READ, 0, 0x0, 0x3, READ_CMD_DATA)
CMD_B = build_avs_cmd(CMD_TYPE_READ, 0, 0xE, 0x5, READ_CMD_DATA)

#: Bound for the reply-driven legs: a retry of 10 costs eleven 32-bit
#: subframes plus a resync on an AVS clock of a quarter of the reference.
REPLY_POLL_CYCLES = 50
REPLY_POLL_LIMIT = 400
#: Bound for reads issued back to back while a resync is awaited.
RESYNC_POLL_LIMIT = 600
#: Bound for the interrupt line to follow a mask or clear write, and the span
#: over which it must then hold that level, both in clk_smc_i cycles.
IRQ_POLL_BOUND = 400
IRQ_HOLD_CYCLES = 200


class smc_avsbus_retry_exhaust_test_seq(SmcCsrSeq):
    """Queue two AVSBus commands at an unresponsive target and exhaust the retries."""

    def __init__(self, name: str = "smc_avsbus_retry_exhaust_test_seq") -> None:
        super().__init__(name)
        self.fsm = AvsFsmMonitor()
        self.retrying_samples = 0
        self.status_polls = 0
        self.driver: AvsReplyDriver | None = None
        self.good_crc: dict[str, int] = {}
        self.cfg0 = 0
        self.waits: list[tuple[str, int, str]] = []
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, str, int]] = []
        self.early: list[str] = []

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

        self.cfg0 = cfg0
        await self._reply_legs()

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
                self.waits.append(
                    ("budget2_exhaust", POLL_LIMIT * POLL_CYCLES, f"intr=0x{interrupt:08x}")
                )
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
                self.waits.append(("budget2_w1c", POLL_LIMIT * POLL_CYCLES, f"intr=0x{after:08x}"))
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
                self.waits.append(("bus_idle", POLL_LIMIT * POLL_CYCLES, f"status=0x{status:08x}"))
                return
        raise AssertionError(
            f"AVS_NORMAL_STATUS.AVS_BUS_IS_IDLE never set after the retry budget was spent "
            f"(last 0x{status:08x})"
        )

    # --- Reply-driven legs ---------------------------------------------------

    def _stamp(self, term: str) -> None:
        self.stamps.append((term, int(get_sim_time("ps"))))

    def _chk(self, term: str, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, term, int(get_sim_time("ps"))))

    def _word(self, shape: str) -> int:
        return SHAPES[shape] | self.good_crc[shape]

    def _send(self, *words: int) -> None:
        assert self.driver is not None
        self.driver.replies.extend(words)

    def _masters_since(self, start: int) -> list[int]:
        assert self.driver is not None
        return self.driver.masters[start:]

    async def _set_retries(self, label: str, budget: int) -> None:
        want = (self.cfg0 & ~MAX_RETRIES_BM) | ((budget << MAX_RETRIES_BP) & MAX_RETRIES_BM)
        await self.csr_write(f"{label}_CFG0", AVS_CFG_0, want)
        await self.csr_read(f"{label}_CFG0_RB", AVS_CFG_0, expected=want)

    async def _total_retries(self, label: str) -> int:
        status = await self.csr_read(f"{label}_NORMAL", AVS_NORMAL_STATUS)
        return fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)

    async def _occupancy(self, label: str) -> int:
        fifos = await self.csr_read(f"{label}_FIFOS", AVS_FIFOS_STATUS)
        return fifo_field(fifos, RB_FIFO_OCCUPIED_BM, RB_FIFO_OCCUPIED_BP)

    async def _poll(self, label: str, what: str, read, done) -> int:
        """Read with `read` every REPLY_POLL_CYCLES until `done(value)`; expiry fails."""
        bound = REPLY_POLL_LIMIT * REPLY_POLL_CYCLES
        value = 0
        for _ in range(REPLY_POLL_LIMIT):
            value = await read()
            if done(value):
                self.waits.append((f"{label}_{what}", bound, f"0x{value:08x}"))
                return value
            await ClockCycles(cocotb.top.clk_smc_i, REPLY_POLL_CYCLES)
        raise AssertionError(
            f"{label}: {what} not reached within {bound} clk_smc_i cycles (last 0x{value:08x})"
        )

    async def _await_idle(self, label: str) -> int:
        return await self._poll(
            label,
            "bus_idle",
            lambda: self.csr_read(f"{label}_IDLE", AVS_NORMAL_STATUS),
            lambda v: bool(v & AVS_BUS_IS_IDLE_BM),
        )

    async def _await_occupancy(self, label: str, wanted: int) -> int:
        return await self._poll(
            label,
            f"readback_occupancy_ge_{wanted}",
            lambda: self._occupancy(label),
            lambda v: v >= wanted,
        )

    async def _clear_interrupts(self, label: str) -> None:
        await self.csr_write(f"{label}_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        await self._poll(
            label,
            "max_retries_int_clear",
            lambda: self.csr_read(f"{label}_INTR_CLEARED", AVS_INTERRUPT),
            lambda v: not v & MAX_RETRIES_ATTEMPTED_BM,
        )

    async def _pop(self, label: str) -> int:
        """Pop one AVS_READBACK entry and wait for the occupancy to drop by one."""
        occupied = await self._await_occupancy(label, 1)
        word = await self.csr_read(f"{label}_READBACK", AVS_READBACK_REG)
        await self._poll(
            label,
            f"readback_occupancy_le_{occupied - 1}",
            lambda: self._occupancy(f"{label}_POPPED"),
            lambda v: v <= occupied - 1,
        )
        return word

    async def _drain(self, label: str) -> list[int]:
        popped: list[int] = []
        for index in range(RB_FIFO_DEPTH + 1):
            status = await self.csr_read(f"{label}_HAS_DATA{index}", AVS_NORMAL_STATUS)
            if not status & READBACK_HAS_DATA_BM:
                return popped
            popped.append(await self._pop(f"{label}_DRAIN{index}"))
        raise AssertionError(f"{label}: the readback FIFO did not empty after {len(popped)} pops")

    async def _learn_crc(self, shape: str) -> None:
        """Send `shape` with each CRC code under MAX_RETRIES=0; exactly one is accepted."""
        label = f"S1_CRC_{shape}"
        accepted: list[int] = []
        for code in range(CRC_CODES):
            word = SHAPES[shape] | code
            before = await self.csr_read(f"{label}{code}_LATEST_BEFORE", AVS_LATEST)
            self._send(word)
            await self.csr_write(f"{label}{code}_CMD", AVS_CMD, CMD_A)
            got = await self._pop(f"{label}{code}")
            assert got & READBACK_FIELDS == word & READBACK_FIELDS, (
                f"{label}: with MAX_RETRIES at 0 the reply 0x{word:08x} reached AVS_READBACK "
                f"as 0x{got:08x}"
            )
            latest = await self.csr_read(f"{label}{code}_LATEST", AVS_LATEST)
            if latest == word:
                accepted.append(code)
            else:
                assert latest == before, (
                    f"{label}: CRC code {code} was not accepted, yet AVS_LATEST_SLAVE_SUBFRAME "
                    f"changed from 0x{before:08x} to 0x{latest:08x}"
                )
        assert len(accepted) == 1, (
            f"{label}: {len(accepted)} of the eight CRC codes were accepted for 0x"
            f"{SHAPES[shape]:08x} ({accepted}); a 3-bit check accepts exactly one"
        )
        self.good_crc[shape] = accepted[0]
        await self._await_idle(label)

    async def _exhaust(self, label: str, budget: int, shape: str) -> dict:
        """One command answered `shape` on every attempt with MAX_RETRIES=`budget`."""
        await self._set_retries(label, budget)
        await self._clear_interrupts(label)
        t0 = await self._total_retries(f"{label}_T0")
        assert self.driver is not None
        start = len(self.driver.masters)
        word = self._word(shape)
        self._send(*([word] * (budget + 1)))
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_A)
        intr = await self._poll(
            label,
            "max_retries_int",
            lambda: self.csr_read(f"{label}_INTR_POLL", AVS_INTERRUPT),
            lambda v: bool(v & MAX_RETRIES_ATTEMPTED_BM),
        )
        await self._await_idle(label)
        t1 = await self._total_retries(f"{label}_T1")
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        frames = self._masters_since(start)
        leftover = len(self.driver.replies)
        self.driver.replies.clear()
        readback = await self._drain(label)
        return {
            "t0": t0,
            "t1": t1,
            "intr": intr,
            "frames": frames,
            "leftover": leftover,
            "readback": readback,
            "word": word,
        }

    def _check_exhaust(self, label: str, budget: int, shape: str, got: dict) -> None:
        frames = got["frames"]
        want_frame = expected_master_subframe(CMD_A)
        assert [f & ~0x7 for f in frames] == [want_frame] * (budget + 1), (
            f"{label}: with MAX_RETRIES={budget} and {shape} on every attempt the master "
            f"subframes were {[hex(f) for f in frames]}; {budget + 1} copies of "
            f"0x{want_frame:08x} (CRC-3 bits aside) were expected"
        )
        assert len(set(frames)) == 1, (
            f"{label}: the retried master subframes differ: {[hex(f) for f in frames]}"
        )
        assert got["t1"] - got["t0"] == budget, (
            f"{label}: TOTAL_RETRIES went {got['t0']} -> {got['t1']}; a budget of {budget} "
            f"exhausted adds exactly {budget}"
        )
        assert got["intr"] & MAX_RETRIES_ATTEMPTED_BM, (
            f"{label}: AVS_INTERRUPT=0x{got['intr']:08x}; MAX_RETRIES_ATTEMPTED_INT must be set "
            f"once the last of {budget} retries also failed"
        )

    async def _early(self, label: str, k: int) -> None:
        await self._set_retries(label, 8)
        await self._clear_interrupts(label)
        t0 = await self._total_retries(f"{label}_T0")
        assert self.driver is not None
        start = len(self.driver.masters)
        good = self._word("GOOD_1111" if k == 1 else "GOOD_2222")
        self._send(*([self._word("ACK1")] * k), good)
        await self.csr_write(f"{label}_CMD", AVS_CMD, CMD_A)
        got = await self._pop(label)
        await self._await_idle(label)
        t1 = await self._total_retries(f"{label}_T1")
        intr = await self.csr_read(f"{label}_INTR", AVS_INTERRUPT)
        frames = len(self._masters_since(start))
        assert t1 - t0 == k, (
            f"{label}: success on retry {k} moved TOTAL_RETRIES {t0} -> {t1}; exactly {k} expected"
        )
        assert not intr & MAX_RETRIES_ATTEMPTED_BM, (
            f"{label}: AVS_INTERRUPT=0x{intr:08x}; success on retry {k} of 8 must leave "
            f"MAX_RETRIES_ATTEMPTED_INT clear"
        )
        assert got & READBACK_FIELDS == good & READBACK_FIELDS, (
            f"{label}: AVS_READBACK=0x{got:08x}, not the SlaveAck=0 reply 0x{good:08x}"
        )
        self.early.append(
            f"k={k} TOTAL_RETRIES {t0}->{t1} AVS_INTERRUPT=0x{intr:08x} "
            f"AVS_READBACK=0x{got:08x} (sent 0x{good:08x}) master_subframes={frames}"
        )

    async def _held(self) -> None:
        label = "S5"
        await self._set_retries(label, 8)
        await self._clear_interrupts(label)
        t0 = await self._total_retries(f"{label}_T0")
        assert self.driver is not None
        start = len(self.driver.masters)
        ack1 = self._word("ACK1")
        first = self._word("GOOD_1111")
        second = self._word("GOOD_2222")
        # Replies in wire order: command A, command B (held), A's two retries.
        self._send(ack1, second, ack1, first)
        await self.csr_write(f"{label}_CMD_A", AVS_CMD, CMD_A)
        await self.csr_write(f"{label}_CMD_B", AVS_CMD, CMD_B)
        retried = False
        resync_status = None
        status = 0
        for _ in range(RESYNC_POLL_LIMIT):
            status = await self.csr_read(f"{label}_RESYNC_POLL", AVS_NORMAL_STATUS)
            retries = fifo_field(status, TOTAL_RETRIES_BM, TOTAL_RETRIES_BP)
            retried = retried or retries - t0 >= HELD_RETRIES
            if retried and status & IN_RESYNC_BM:
                resync_status = status
                break
        else:
            raise AssertionError(
                f"{label}: AVS_SLAVE_IS_IN_RESYNC never read 1 after the retries within "
                f"{RESYNC_POLL_LIMIT} back-to-back reads (retries done={retried}, last "
                f"AVS_NORMAL_STATUS=0x{status:08x})"
            )
        self.waits.append((f"{label}_resync", RESYNC_POLL_LIMIT, f"0x{resync_status:08x}"))
        pops = [await self._pop(f"{label}_POP{i}") for i in range(2)]
        await self._await_idle(label)
        t1 = await self._total_retries(f"{label}_T1")
        frames = self._masters_since(start)
        assert [w & READBACK_FIELDS for w in pops] == [
            first & READBACK_FIELDS,
            second & READBACK_FIELDS,
        ], (
            f"{label}: AVS_READBACK popped {[hex(w) for w in pops]}; the first command's reply "
            f"0x{first:08x} then the second's 0x{second:08x} were expected"
        )
        self._chk(
            "AVS_RETRY_HELD",
            "CHK-AVS-RETRY-HELD-REPLY",
            f"two back-to-back commands, the first answered SlaveAck=1 twice then 0x{first:08x} "
            f"(data 0x1111), the second 0x{second:08x} (data 0x2222): AVS_READBACK popped "
            f"0x{pops[0]:08x} then 0x{pops[1]:08x}; AVS_SLAVE_IS_IN_RESYNC read 1 after "
            f"TOTAL_RETRIES reached T0+{HELD_RETRIES} (AVS_NORMAL_STATUS=0x{resync_status:08x}); "
            f"TOTAL_RETRIES {t0}->{t1}; master subframes {[hex(f) for f in frames]}",
        )

    async def _line_level(self, label: str, level: int) -> None:
        """Wait for tb_avsbus_irq to reach `level`, then require it to hold it."""
        line = cocotb.top.tb_avsbus_irq
        clk = cocotb.top.clk_smc_i
        last = None
        for cycle in range(IRQ_POLL_BOUND):
            raw = line.value
            last = str(raw)
            if raw.is_resolvable and int(raw) == level:
                break
            await ClockCycles(clk, 1)
        else:
            raise AssertionError(
                f"{label}: tb_avsbus_irq did not reach {level} within {IRQ_POLL_BOUND} "
                f"clk_smc_i cycles (last {last})"
            )
        for _ in range(IRQ_HOLD_CYCLES):
            await ClockCycles(clk, 1)
            raw = line.value
            assert raw.is_resolvable and int(raw) == level, (
                f"{label}: tb_avsbus_irq left {level} (now {raw}) within {IRQ_HOLD_CYCLES} "
                f"clk_smc_i cycles"
            )
        self.waits.append(
            (f"{label}_line_{level}", IRQ_POLL_BOUND, f"reached after {cycle} cycles, held")
        )

    async def _int_line(self) -> None:
        label = "S6"
        await self.csr_write(f"{label}_MASK_SOURCE", AVS_INTERRUPT_MASK, MASK_ALL)
        again = await self._exhaust(f"{label}_RAISE", ACK2_BUDGET, "ACK2")
        self._check_exhaust(f"{label}_RAISE", ACK2_BUDGET, "ACK2", again)
        intr = await self.csr_read(f"{label}_INTR_SET", AVS_INTERRUPT)
        assert intr & MAX_RETRIES_ATTEMPTED_BM, (
            f"{label}: AVS_INTERRUPT=0x{intr:08x} before the line samples; bit 5 must be set"
        )
        await self.csr_write(f"{label}_MASK_UNMASK", AVS_INTERRUPT_MASK, MASK_KEEP_MAX_RETRIES)
        await self._line_level(f"{label}_UNMASKED", 1)
        await self.csr_write(f"{label}_MASK_ALL", AVS_INTERRUPT_MASK, MASK_ALL)
        await self._line_level(f"{label}_MASKED", 0)
        await self.csr_write(f"{label}_CLEAR_BIT5", AVS_INTERRUPT_CLEAR, CLEAR_MAX_RETRIES_ONLY)
        cleared = await self._poll(
            label,
            "bit5_clear",
            lambda: self.csr_read(f"{label}_INTR_AFTER_CLEAR", AVS_INTERRUPT),
            lambda v: not v & MAX_RETRIES_ATTEMPTED_BM,
        )
        await self.csr_write(
            f"{label}_MASK_UNMASK_AGAIN", AVS_INTERRUPT_MASK, MASK_KEEP_MAX_RETRIES
        )
        await self._line_level(f"{label}_CLEARED", 0)
        await self.csr_write(f"{label}_MASK_END", AVS_INTERRUPT_MASK, MASK_ALL)
        self._chk(
            "AVS_RETRY_INT_LINE",
            "CHK-AVS-RETRY-INT-LINE",
            f"with MAX_RETRIES_ATTEMPTED_INT set (AVS_INTERRUPT=0x{intr:08x}) tb_avsbus_irq read 1 "
            f"with AVS_INTERRUPT_MASK=0x{MASK_KEEP_MAX_RETRIES:03x} and 0 with 0x{MASK_ALL:03x}; "
            f"after AVS_INTERRUPT_CLEAR=0x{CLEAR_MAX_RETRIES_ONLY:02x} AVS_INTERRUPT=0x{cleared:08x} "
            f"(bit 5 = 0) and the line held 0 with mask 0x{MASK_KEEP_MAX_RETRIES:03x}",
        )

    async def _reply_legs(self) -> None:
        # S1: responder on sdata, accepted CRC codes, interrupts cleared.
        await self.csr_write("S1_MASK_ALL", AVS_INTERRUPT_MASK, MASK_ALL)
        self.driver = AvsReplyDriver(default=reply(ACK_GOOD, 0, 0))
        await self._set_retries("S1", 0)
        await self._await_idle("S1")
        stale = await self._drain("S1_STALE")
        for shape in SHAPES:
            await self._learn_crc(shape)
        await self._clear_interrupts("S1")
        cocotb.log.info(
            "S1: accepted CRC-3 codes %s; %d readback entries left by the earlier legs drained",
            ", ".join(f"{k}={v}" for k, v in self.good_crc.items()),
            len(stale),
        )
        self._stamp("BRINGUP")

        # S2: budgets of 8 and 10, SlaveAck=1 throughout.
        notes = []
        for budget in LONG_BUDGETS:
            label = f"S2_M{budget}"
            got = await self._exhaust(label, budget, "ACK1")
            self._check_exhaust(label, budget, "ACK1", got)
            notes.append(
                f"M={budget}: {len(got['frames'])} identical master subframes "
                f"0x{got['frames'][0]:08x}, TOTAL_RETRIES {got['t0']}->{got['t1']}, "
                f"AVS_INTERRUPT=0x{got['intr']:08x}"
            )
            cocotb.log.info(
                "CHK-AVS-RETRY8-ACK1: AVS_READBACK_M%d=%s (SF-032, measured, not compared; "
                "unused replies left queued=%d)",
                budget,
                ",".join(f"0x{w:08x}" for w in got["readback"]) or "empty",
                got["leftover"],
            )
        self._chk(
            "AVS_RETRY8_ACK1",
            "CHK-AVS-RETRY8-ACK1",
            "SlaveAck=1 on every attempt: " + "; ".join(notes) + " (bit 5 set each time)",
        )
        self._stamp("AVS_RETRY8_ACK1")

        # S3: budget of 8, SlaveAck=2 throughout.
        got = await self._exhaust("S3", ACK2_BUDGET, "ACK2")
        self._check_exhaust("S3", ACK2_BUDGET, "ACK2", got)
        self._chk(
            "AVS_RETRY8_ACK2",
            "CHK-AVS-RETRY8-ACK2",
            f"MAX_RETRIES={ACK2_BUDGET}, SlaveAck=2 on every attempt: {len(got['frames'])} "
            f"identical master subframes 0x{got['frames'][0]:08x}, TOTAL_RETRIES "
            f"{got['t0']}->{got['t1']}, AVS_INTERRUPT=0x{got['intr']:08x} (bit 5 set); "
            f"AVS_READBACK {','.join(f'0x{w:08x}' for w in got['readback']) or 'empty'} logged",
        )
        self._stamp("AVS_RETRY8_ACK2")

        # S4: success on retry k.
        for k in EARLY_RETRIES:
            await self._early(f"S4_K{k}", k)
        self._chk(
            "AVS_RETRY_EARLY",
            "CHK-AVS-RETRY-EARLY-SUCCESS",
            "MAX_RETRIES=8, SlaveAck=1 k times then SlaveAck=0: " + "; ".join(self.early),
        )
        self._stamp("AVS_RETRY_EARLY")

        # S5: held reply across two back-to-back commands.
        await self._held()
        self._stamp("AVS_RETRY_HELD")

        # S6: the interrupt line through the mask.
        await self._int_line()
        self._stamp("AVS_RETRY_INT_LINE")

        await self.csr_write("END_CLEAR", AVS_INTERRUPT_CLEAR, CLEAR_ALL)
        self.driver.stop()
        set_avs_sdata(1)

        # S7: every bounded wait, with its bound and last observed state.
        self._chk(
            "TIMEOUT",
            "CHK-TIMEOUT-PATHS",
            "%d bounded waits, each raising AssertionError with its last observed state on "
            "expiry (bounds in clk_smc_i cycles, resync poll in reads): %s"
            % (len(self.waits), "; ".join(f"{n} bound={b} last={s}" for n, b, s in self.waits)),
        )
        self._check_fence()

    def _check_fence(self) -> None:
        order = [
            "BRINGUP",
            "AVS_RETRY8_ACK1",
            "AVS_RETRY8_ACK2",
            "AVS_RETRY_EARLY",
            "AVS_RETRY_HELD",
            "AVS_RETRY_INT_LINE",
        ]
        terms = [t for t, _ in self.stamps]
        assert terms == order, f"fence terms {terms} out of order, expected {order}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:], strict=False)), (
            f"fence stamps not strictly increasing: {times}"
        )
        stamp_of = dict(self.stamps)
        for chk_id, term, when in self.chk_lines:
            if term not in stamp_of:
                continue
            index = order.index(term)
            assert when <= stamp_of[term], f"{chk_id} printed after its fence term {term}"
            assert when > stamp_of[order[index - 1]], f"{chk_id} printed before its step ran"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence existing legs (CHK-AVS-RETRY-FSM-PATH, "
            "CHK-AVS-RETRY-IN-PROGRESS, CHK-AVS-RETRY-BUDGET-EXHAUSTED, CHK-AVS-RETRY-INT-W1C) "
            "< %s; checker lines %s; stamps %s",
            " < ".join(order),
            ",".join(c for c, _, _ in self.chk_lines),
            ",".join(f"{t}={s}" for t, s in self.stamps),
        )
