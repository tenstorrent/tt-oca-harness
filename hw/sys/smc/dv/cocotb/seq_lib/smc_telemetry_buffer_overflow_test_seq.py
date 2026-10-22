# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receivers past their limits: a full message buffer, and a message with no end.

The capture leaf sends one message and pops it. The receiver has two bounded
stores behind the ATB port, and this leaf drives each past its bound:

* **The message buffer.** Messages are sent without popping until
  `STATUS.BUFFER_FULL` sets, then two more. The buffer depth is read off
  `STATUS.BUFFER_FULL` rather than assumed: the IP documents give it as both
  8 and 16. Popping afterwards has to return exactly as many messages as the
  buffer held when it filled, as one unbroken run of the probe IDs sent, in
  the order sent -- a buffer that grew, or that interleaved the extra
  messages, fails that. Which end of the run survived is recorded, not
  asserted; no document states it. `CTRL.BUFFER_THRESHOLD` with its
  interrupt enabled is checked on the way up: `telemetry_receiver.rdl` raises
  `INTR_STATUS.BUFFER_THRESHOLD` while the number of messages is greater than
  the threshold, and clears it when the level drops back.
* **The assembly buffer.** `INTR_STATUS.MISSING_LAST` is raised "when the
  Telemetry Receiver has not received a Last Packet flag when the maximum
  number of packets a message can consist of has been received"
  (`telemetry_receiver.rdl`). Packets without the flag are sent one at a time
  until it sets, which measures that maximum. A message of exactly that many
  packets whose final packet does carry the flag must then fill the assembly
  buffer without raising it, and reach the message buffer.

One beat short of that maximum, a message that has not finished must complete
nothing and raise nothing; and a flush written while a beat is presented on the
ATB port, then a second flush, must leave the next message intact.

`CTRL.BUFFER_POP` "is effective only if `STATUS.BUFFER_EMPTY = 0`", so a pop
written to an empty buffer must leave it empty and not disturb the message
that arrives next.

The packet framing and the beat driver are the capture leaf's, shared from
`smc_telemetry_receiver_csr_test_seq`.

Receivers 1 and 2 then run the queue, flush and `MISSING_LAST` legs of the
approved contract `SMC_TELEMETRY_BUFFER_OVERFLOW`, with every expected value
taken from the IP documents (`architecture.adoc`, `interface.adoc`,
`telemetry_receiver.adoc`):

* **Queue full and overflow.** Eight messages fill the `BUFFER_DEPTH` = 8 queue
  (`STATUS` = 0x10 with the first message visible); a ninth drops the oldest,
  and the eight pops present the surviving IDs in order, then the empty queue
  reads `STATUS` = 0x01 and `PROBE_ID` = 0, which one more pop leaves alone.
* **Push against pop.** With the queue full, `BUFFER_POP` is written at each
  offset from -4 to +4 `clk_periph_i` cycles around the last beat of one more
  message. The drain is either every message after the oldest, or one fewer;
  both are consistent with the documents (SF-027), and which one each offset
  produced is logged.
* **Transmitter flush.** The bench holds `afready_i` of receivers 1 and 2 high
  and does not publish their `afvalid_o`, so the flush runs at that level: the
  request self-clears and the three queued messages drain in order. The
  handshake with `afready_i` low is not reachable on this bench (SF-044).
* **MISSING_LAST.** Beats without the last-packet marker are sent one at a
  time until `INTR_STATUS.MISSING_LAST` sets, with `INTR_ENABLE` off and then
  on; `peripheral_interrupts_o[8+r]` must follow the enable, and a written one
  clears the status and the line. The beat count is logged only (SF-024).
* **INTR_TEST.** `INTR_TEST.MISSING_LAST` raises the line with the enable on
  and leaves it low with the enable off; `INTR_STATUS` after the test write is
  logged only (SF-025).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    BUFFER_POP_BM,
    CTRL,
    PROBE_ID,
    PROBE_ID_BM,
    RX,
    RX_FLUSH_BM,
    STATUS,
    TX_FLUSH_BM,
    _frame_all_ones_message,
    _rx_addr,
    _tel,
)
from .smc_telemetry_receiver_csr_test_seq import (
    _ATB_LAST_PACKET_BIT,
    _NUM_BEATS_PER_PACKET,
    _atb_write_beat,
    _send_telemetry_packet,
)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
INTR_STATUS = _rx_addr("INTR_STATUS")
INTR_ENABLE = _rx_addr("INTR_ENABLE")

BUFFER_FULL_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm")
THRESHOLD_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
INTR_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm")
INTR_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")

ATID = 0x21
#: The message buffer threshold: the interrupt is raised with more than this
#: many messages buffered.
THRESHOLD = 2
#: Messages sent after the buffer reports full.
EXTRA_MESSAGES = 2
#: Upper bound on the buffer depth; the documents give 8 and 16.
MAX_DEPTH = 32
#: Upper bound on the packets of one message.
MAX_PACKETS = 16
PROBE_ID_MASK = PROBE_ID_BM
POLL_BOUND = 200
#: A beat value with its top bit clear, so no beat carries the last-packet flag.
PARTIAL_BEAT = 0x2A


#: Receivers that run the contract legs after receiver 0's.
EXT_RECEIVERS = (1, 2)
EXT_ATID = {1: 0x11, 2: 0x22}
#: Messages the queue holds: `BUFFER_DEPTH` default 8 (interface.adoc).
QUEUE_DEPTH = 8
STATUS_EMPTY = BUFFER_EMPTY_BM
STATUS_FULL = BUFFER_FULL_BM
STATUS_NEITHER = 0x0
FILL_IDS = tuple(range(0x11, 0x11 + QUEUE_DEPTH))
NINTH_ID = 0x19
WINDOW_FILL_IDS = tuple(range(0x01, 0x01 + QUEUE_DEPTH))
WINDOW_ID = 0x09
WINDOW_OFFSETS = tuple(range(-4, 5))
#: The two drains the documents allow for a push meeting a pop (SF-027).
WINDOW_NO_DROP = [*WINDOW_FILL_IDS[1:], WINDOW_ID]
WINDOW_ONE_DROP = [*WINDOW_FILL_IDS[2:], WINDOW_ID]
TX_FLUSH_IDS = (0x1A, 0x1B, 0x1C)
AFTER_MISSING_ID = 0x11
INTR_TEST = "INTR_TEST"
INTR_TEST_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_TEST__MISSING_LAST_bm")
ENABLE_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__MISSING_LAST_bm")
#: First peripheral interrupt line of the telemetry receivers.
TELEMETRY_IRQ_BASE = 8
#: Bound on the receiver interrupt line reaching a level, in clk_smc_i cycles.
LINE_BOUND = 64
#: Bound on the beats sent without the last marker before MISSING_LAST sets.
MISSING_BEAT_BOUND = MAX_PACKETS * _NUM_BEATS_PER_PACKET
STEP_ORDER = (
    "BRINGUP",
    "TELEM12_FULL",
    "TELEM12_OVERFLOW",
    "TELEM12_PUSH_POP",
    "TELEM12_TX_FLUSH",
    "TELEM12_MISSING_LAST",
    "TELEM12_INTR_TEST",
    "TIMEOUT",
)
CHK_STEP = {
    "CHK-TELEM12-FULL": "TELEM12_FULL",
    "CHK-TELEM12-OVERFLOW-ORDER": "TELEM12_OVERFLOW",
    "CHK-TELEM12-PUSH-POP-WINDOW": "TELEM12_PUSH_POP",
    "CHK-TELEM12-TX-FLUSH": "TELEM12_TX_FLUSH",
    "CHK-TELEM12-MISSING-LAST": "TELEM12_MISSING_LAST",
    "CHK-TELEM12-INTR-TEST": "TELEM12_INTR_TEST",
    "CHK-TIMEOUT-PATHS": "TIMEOUT",
}


def _ext_addr(register: str, rx: int) -> int:
    """Address of `register` in telemetry receiver `rx`, from the SMC map."""
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", rx
    )


def _line(rx: int) -> int:
    """Level of `peripheral_interrupts_o[8 + rx]`; X/Z fails."""
    bit = cocotb.top.tb_peripheral_interrupts.value[TELEMETRY_IRQ_BASE + rx]
    text = str(bit)
    assert text in ("0", "1"), f"peripheral_interrupts_o[{TELEMETRY_IRQ_BASE + rx}] is {text}"
    return int(text)


class _LineWatch:
    """Records the first clk_smc_i cycle at which the line of `rx` is high."""

    def __init__(self, rx: int) -> None:
        self.rx = rx
        self.seen: int | None = None
        self._task = cocotb.start_soon(self._run())

    async def _run(self) -> None:
        cycle = 0
        while True:
            await RisingEdge(cocotb.top.clk_smc_i)
            cycle += 1
            if _line(self.rx):
                self.seen = cycle
                return

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


def _probe(index: int) -> int:
    """A distinct probe ID for the `index`-th message, never zero."""
    return (index % PROBE_ID_MASK) + 1


def _mid_packet() -> int:
    """A packet of the same framing as a message's, without the last-packet flag."""
    return _frame_all_ones_message(0x0A) & ~(1 << _ATB_LAST_PACKET_BIT)


class smc_telemetry_buffer_overflow_test_seq(SmcCsrSeq):
    """Overfill the message buffer, and run a message past the assembly buffer."""

    def __init__(self, name: str = "smc_telemetry_buffer_overflow_test_seq") -> None:
        super().__init__(name)
        self.depth = 0
        self.popped: list[int] = []
        self.max_packets = 0
        self.waits: dict[str, tuple[int, str, str]] = {}
        self.stamps: list[tuple[str, int]] = []
        self.chk_lines: list[tuple[str, int, int]] = []

    def _wait(self, name: str, bound: int, unit: str, last: str) -> None:
        self.waits[name] = (bound, unit, last)

    def _stamp(self, step: str) -> None:
        self.stamps.append((step, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_lines.append((chk_id, int(get_sim_time("ps")), len(self.stamps)))

    async def _status(self, label: str) -> int:
        return await self.csr_read(f"TELEMETRY_STATUS_{label}", STATUS)

    async def _wait_status(self, label: str, mask: int, want: bool) -> int:
        status = 0
        for _ in range(POLL_BOUND):
            status = await self._status(label)
            if bool(status & mask) == want:
                self._wait("rx0_status_poll", POLL_BOUND, "polls", f"STATUS=0x{status:02x}")
                return status
            await ClockCycles(cocotb.top.clk_smc_i, 4)
        raise AssertionError(
            f"{label}: STATUS bit 0x{mask:x} never reached {int(want)} (STATUS=0x{status:08x})"
        )

    async def _send(self, probe_id: int) -> None:
        await _send_telemetry_packet(
            cocotb.top, _frame_all_ones_message(probe_id), rx=RX, atid=ATID
        )
        await ClockCycles(cocotb.top.clk_smc_i, 8)

    async def _flush(self, label: str) -> None:
        await self.csr_write(f"{label}_FLUSH", CTRL, RX_FLUSH_BM)
        await self._wait_status(f"{label}_FLUSHED", BUFFER_EMPTY_BM, True)

    async def _pop_on_empty(self) -> None:
        await self._flush("POP_EMPTY")
        await self.csr_write("POP_EMPTY_POP", CTRL, BUFFER_POP_BM)
        await ClockCycles(cocotb.top.clk_smc_i, 8)
        status = await self._status("POP_EMPTY_AFTER")
        assert status & BUFFER_EMPTY_BM and not status & BUFFER_FULL_BM, (
            f"a pop written to an empty buffer changed STATUS to 0x{status:08x}"
        )
        probe_id = 0x13
        await self._send(probe_id)
        await self._wait_status("POP_EMPTY_NEXT", BUFFER_EMPTY_BM, False)
        got = await self.csr_read("POP_EMPTY_PROBE", PROBE_ID) & PROBE_ID_BM
        assert got == probe_id, (
            f"after a pop on an empty buffer the next message read back probe ID 0x{got:02x}, "
            f"not the 0x{probe_id:02x} sent"
        )
        await self.csr_write("POP_EMPTY_POP_NEXT", CTRL, BUFFER_POP_BM)
        await self._wait_status("POP_EMPTY_DRAINED", BUFFER_EMPTY_BM, True)
        cocotb.log.info(
            "CHK-TELEMETRY-POP-EMPTY: CTRL.BUFFER_POP on an empty buffer left STATUS empty and "
            "not full, and the next message read back its own probe ID 0x%02x",
            probe_id,
        )

    async def _overflow(self) -> None:
        await self._flush("FILL")
        await self.csr_write("FILL_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST)
        ctrl = (THRESHOLD << THRESHOLD_BP) & THRESHOLD_BM
        await self.csr_write("FILL_THRESHOLD", CTRL, ctrl)
        await self.csr_read("FILL_THRESHOLD_RB", CTRL, expected=ctrl)
        await self.csr_write("FILL_INTR_ENABLE", INTR_ENABLE, ENABLE_THRESHOLD)

        threshold_seen_at = 0
        sent = 0
        for sent in range(1, MAX_DEPTH + 1):
            await self._send(_probe(sent - 1))
            await self._wait_status(f"FILL_{sent}", BUFFER_EMPTY_BM, False)
            intr = await self.csr_read(f"FILL_{sent}_INTR", INTR_STATUS)
            above = sent > THRESHOLD
            assert bool(intr & INTR_THRESHOLD) == above, (
                f"with {sent} messages buffered and CTRL.BUFFER_THRESHOLD={THRESHOLD}, "
                f"INTR_STATUS.BUFFER_THRESHOLD reads {int(bool(intr & INTR_THRESHOLD))}"
            )
            if above and not threshold_seen_at:
                threshold_seen_at = sent
            status = await self._status(f"FILL_{sent}_FULL")
            if status & BUFFER_FULL_BM:
                break
        else:
            raise AssertionError(f"STATUS.BUFFER_FULL never set after {MAX_DEPTH} messages")
        self.depth = sent
        assert self.depth > THRESHOLD, (
            f"the buffer filled at {self.depth} messages, not above the threshold {THRESHOLD}"
        )
        for extra in range(EXTRA_MESSAGES):
            await self._send(_probe(self.depth + extra))
        status = await self._status("OVERFULL")
        assert status & BUFFER_FULL_BM, (
            f"STATUS.BUFFER_FULL cleared after {EXTRA_MESSAGES} more messages (0x{status:08x})"
        )

        for index in range(self.depth + 1):
            status = await self._status(f"DRAIN_{index}")
            if status & BUFFER_EMPTY_BM:
                break
            self.popped.append(await self.csr_read(f"DRAIN_{index}_PROBE", PROBE_ID) & PROBE_ID_BM)
            # CTRL carries the threshold beside the pop, so the pop rewrites it.
            await self.csr_write(f"DRAIN_{index}_POP", CTRL, ctrl | BUFFER_POP_BM)
            await ClockCycles(cocotb.top.clk_smc_i, 4)
            left = self.depth - len(self.popped)
            intr = await self.csr_read(f"DRAIN_{index}_INTR", INTR_STATUS)
            assert bool(intr & INTR_THRESHOLD) == (left > THRESHOLD), (
                f"with {left} messages left and CTRL.BUFFER_THRESHOLD={THRESHOLD}, "
                f"INTR_STATUS.BUFFER_THRESHOLD reads {int(bool(intr & INTR_THRESHOLD))}"
            )
        status = await self._status("DRAINED")
        assert status & BUFFER_EMPTY_BM, f"the buffer is not empty after the drain (0x{status:08x})"
        cocotb.log.info(
            "CHK-TELEMETRY-THRESHOLD-INTR: with CTRL.BUFFER_THRESHOLD=%d and its interrupt "
            "enabled, INTR_STATUS.BUFFER_THRESHOLD was clear for each of the first %d messages "
            "and set from message %d on; it cleared again as the drain left %d messages",
            THRESHOLD,
            THRESHOLD,
            threshold_seen_at,
            THRESHOLD,
        )
        sent_ids = [_probe(i) for i in range(self.depth + EXTRA_MESSAGES)]
        assert len(self.popped) == self.depth, (
            f"{len(self.popped)} messages came back from a buffer that reported full at "
            f"{self.depth}: {[hex(p) for p in self.popped]}"
        )
        runs = {start: sent_ids[start : start + self.depth] for start in range(EXTRA_MESSAGES + 1)}
        start = next((s for s, run in runs.items() if run == self.popped), None)
        assert start is not None, (
            f"the {self.depth} messages popped, {[hex(p) for p in self.popped]}, are not an "
            f"unbroken run of the probe IDs sent in order, {[hex(p) for p in sent_ids]}"
        )
        kept = {0: "the first", EXTRA_MESSAGES: "the last"}.get(start, f"from message {start}")
        await self.csr_write("FILL_INTR_DISABLE", INTR_ENABLE, 0)
        await self.csr_write("FILL_THRESHOLD_OFF", CTRL, 0)
        cocotb.log.info(
            "CHK-TELEMETRY-BUFFER-OVERFLOW: STATUS.BUFFER_FULL set at %d messages and stayed "
            "set through %d more; the drain returned exactly %d messages, %s %d of the %d sent "
            "in order, and left the buffer empty",
            self.depth,
            EXTRA_MESSAGES,
            self.depth,
            kept,
            self.depth,
            self.depth + EXTRA_MESSAGES,
        )

    async def _missing_last(self) -> None:
        await self._flush("MISSING")
        await self.csr_write("MISSING_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST)
        intr = await self.csr_read("MISSING_INTR_ENTRY", INTR_STATUS)
        assert not intr & INTR_MISSING_LAST, f"MISSING_LAST is set before the leg (0x{intr:08x})"
        packets = 0
        for packets in range(1, MAX_PACKETS + 1):
            await _send_telemetry_packet(cocotb.top, _mid_packet(), rx=RX, atid=ATID)
            await ClockCycles(cocotb.top.clk_smc_i, 8)
            intr = await self.csr_read(f"MISSING_{packets}_INTR", INTR_STATUS)
            if intr & INTR_MISSING_LAST:
                break
        else:
            raise AssertionError(
                f"INTR_STATUS.MISSING_LAST never set over {MAX_PACKETS} packets without the "
                f"last-packet flag"
            )
        assert packets > 1, "MISSING_LAST set after a single packet; a message is one packet"
        self.max_packets = packets
        await self.csr_write("MISSING_INTR_W1C", INTR_STATUS, INTR_MISSING_LAST)
        intr = await self.csr_read("MISSING_INTR_CLEARED", INTR_STATUS)
        assert not intr & INTR_MISSING_LAST, (
            f"a written one did not clear INTR_STATUS.MISSING_LAST (0x{intr:08x})"
        )
        cocotb.log.info(
            "CHK-TELEMETRY-MISSING-LAST: INTR_STATUS.MISSING_LAST set on the %dth packet sent "
            "without the last-packet flag, stayed clear on the %d before it, and cleared on a "
            "written one",
            packets,
            packets - 1,
        )

        await self._flush("FIT")
        for index in range(self.max_packets - 1):
            await _send_telemetry_packet(cocotb.top, _mid_packet(), rx=RX, atid=ATID)
            await ClockCycles(cocotb.top.clk_smc_i, 8)
            intr = await self.csr_read(f"FIT_{index}_INTR", INTR_STATUS)
            assert not intr & INTR_MISSING_LAST, (
                f"MISSING_LAST set after {index + 1} of {self.max_packets} packets"
            )
        await _send_telemetry_packet(cocotb.top, _frame_all_ones_message(0x0A), rx=RX, atid=ATID)
        await ClockCycles(cocotb.top.clk_smc_i, 8)
        intr = await self.csr_read("FIT_INTR", INTR_STATUS)
        assert not intr & INTR_MISSING_LAST, (
            f"a message of {self.max_packets} packets whose last carries the flag raised "
            f"MISSING_LAST (0x{intr:08x})"
        )
        await self._wait_status("FIT_BUFFERED", BUFFER_EMPTY_BM, False)
        await self.csr_write("FIT_POP", CTRL, BUFFER_POP_BM)
        await self._wait_status("FIT_DRAINED", BUFFER_EMPTY_BM, True)
        cocotb.log.info(
            "CHK-TELEMETRY-FULL-MESSAGE: a message of %d packets, the most one can consist of, "
            "with the last-packet flag on its final packet reached the message buffer without "
            "raising MISSING_LAST",
            self.max_packets,
        )

    async def _partial_and_flush_leg(self) -> None:
        """Stop one beat short of the assembly buffer, and flush with a beat presented."""
        await self._flush("PARTIAL")
        await self.csr_write("PARTIAL_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST)
        beats = self.max_packets * _NUM_BEATS_PER_PACKET - 1
        for index in range(beats):
            await _atb_write_beat(cocotb.top, PARTIAL_BEAT, beat=index, rx=RX, atid=ATID)
        await ClockCycles(cocotb.top.clk_smc_i, 16)
        intr = await self.csr_read("PARTIAL_INTR", INTR_STATUS)
        status = await self._status("PARTIAL")
        assert not intr & INTR_MISSING_LAST and status & BUFFER_EMPTY_BM, (
            f"with {beats} beats of an unfinished message, one short of the most a message "
            f"can hold, INTR_STATUS=0x{intr:08x} STATUS=0x{status:08x}; nothing may complete "
            f"and MISSING_LAST may not set"
        )
        atvalid = getattr(cocotb.top, f"tb_telemetry{RX}_atvalid")
        atdata = getattr(cocotb.top, f"tb_telemetry{RX}_atdata")
        atdata.value = 0
        atvalid.value = 1
        await self.csr_write("PARTIAL_FLUSH_HELD", CTRL, RX_FLUSH_BM)
        atvalid.value = 0
        await self._flush("PARTIAL_CLEAN")
        await self._send(0x15)
        await self._wait_status("PARTIAL_NEXT", BUFFER_EMPTY_BM, False)
        got = await self.csr_read("PARTIAL_NEXT_PROBE", PROBE_ID) & PROBE_ID_BM
        assert got == 0x15, (
            f"after the partial message and a flush taken with a beat presented, the next "
            f"message read back probe ID 0x{got:02x}, not 0x15"
        )
        await self.csr_write("PARTIAL_NEXT_POP", CTRL, BUFFER_POP_BM)
        await self._wait_status("PARTIAL_DRAINED", BUFFER_EMPTY_BM, True)
        cocotb.log.info(
            "CHK-TELEMETRY-PARTIAL-FLUSH: %d beats of an unfinished message, one short of the "
            "assembly buffer, completed nothing and raised no MISSING_LAST; a flush taken "
            "while a beat was presented, and a second one, left the next message reading back "
            "its own probe ID",
            beats,
        )

    # Receivers 1 and 2: the contract legs.

    async def _ext_poll(self, label: str, addr: int, done, wait: str) -> int:
        """Read `addr` until `done(value)`; raise with the last value on expiry."""
        value = 0
        for _ in range(POLL_BOUND):
            value = await self.csr_read(label, addr)
            if done(value):
                self._wait(wait, POLL_BOUND, "register polls", f"0x{value:08x}")
                return value
            await ClockCycles(cocotb.top.clk_smc_i, 4)
        raise AssertionError(
            f"{label}: {wait} expired after {POLL_BOUND} polls (last read 0x{value:08x})"
        )

    async def _ext_status(self, label: str, rx: int) -> int:
        return await self.csr_read(f"R{rx}_{label}_STATUS", _ext_addr("STATUS", rx))

    async def _ext_probe(self, label: str, rx: int) -> int:
        probe = await self.csr_read(f"R{rx}_{label}_PROBE", _ext_addr("TELEMETRY_PROBE_ID", rx))
        return probe & PROBE_ID_BM

    async def _ext_pop(self, label: str, rx: int) -> None:
        await self.csr_write(f"R{rx}_{label}_POP", _ext_addr("CTRL", rx), BUFFER_POP_BM)

    async def _ext_send(self, rx: int, probe_id: int) -> None:
        await _send_telemetry_packet(
            cocotb.top, _frame_all_ones_message(probe_id), rx=rx, atid=EXT_ATID[rx]
        )

    async def _await_line(self, rx: int, want: int, label: str) -> int:
        last = _line(rx)
        for cycle in range(LINE_BOUND + 1):
            if last == want:
                self._wait("irq_line_level", LINE_BOUND, "clk_smc_i", f"line={last}")
                return cycle
            await RisingEdge(cocotb.top.clk_smc_i)
            last = _line(rx)
        raise AssertionError(
            f"{label}: peripheral_interrupts_o[{TELEMETRY_IRQ_BASE + rx}] stayed {last} for "
            f"{LINE_BOUND} clk_smc_i cycles, want {want}"
        )

    async def _line_stays_low(self, rx: int, label: str) -> None:
        for cycle in range(LINE_BOUND):
            assert _line(rx) == 0, (
                f"{label}: peripheral_interrupts_o[{TELEMETRY_IRQ_BASE + rx}] rose {cycle} "
                f"clk_smc_i cycles into a window where it must stay 0"
            )
            await RisingEdge(cocotb.top.clk_smc_i)
        self._wait("irq_line_hold_low", LINE_BOUND, "clk_smc_i", "line=0")

    async def _ext_fill(self, rx: int, ids: tuple[int, ...], label: str) -> None:
        """Send `ids` into an empty queue; BUFFER_FULL must set on the last, not before."""
        status_addr = _ext_addr("STATUS", rx)
        for index, probe_id in enumerate(ids, 1):
            await self._ext_send(rx, probe_id)
            name = f"R{rx}_{label}_{index}_STATUS"
            if index == 1:
                status = await self._ext_poll(
                    name, status_addr, lambda v: not v & BUFFER_EMPTY_BM, "message_arrival"
                )
            elif index == len(ids):
                status = await self._ext_poll(
                    name, status_addr, lambda v: v & BUFFER_FULL_BM, "queue_full"
                )
            else:
                status = await self.csr_read(name, status_addr)
            want = STATUS_FULL if index == len(ids) else STATUS_NEITHER
            assert status == want, (
                f"receiver {rx}: STATUS reads 0x{status:08x} after message {index} of "
                f"{len(ids)}, expected 0x{want:02x}"
            )
        head = await self._ext_probe(f"{label}_HEAD", rx)
        assert head == ids[0], (
            f"receiver {rx}: a full queue shows PROBE_ID=0x{head:02x}, not the first message "
            f"0x{ids[0]:02x}"
        )

    async def _ext_bringup(self) -> None:
        for rx in EXT_RECEIVERS:
            await self.csr_write(f"R{rx}_BRINGUP_FLUSH", _ext_addr("CTRL", rx), RX_FLUSH_BM)
            status = await self._ext_status("BRINGUP", rx)
            intr = await self.csr_read(f"R{rx}_BRINGUP_INTR", _ext_addr("INTR_STATUS", rx))
            line = _line(rx)
            assert (status, intr, line) == (STATUS_EMPTY, 0, 0), (
                f"receiver {rx} after CTRL.TELEMETRY_RX_FLUSH: STATUS=0x{status:08x} "
                f"INTR_STATUS=0x{intr:08x} line={line}, expected 0x01, 0x00, 0"
            )
        self._stamp("BRINGUP")

    async def _ext_full_and_overflow(self) -> None:
        for rx in EXT_RECEIVERS:
            await self._ext_fill(rx, FILL_IDS, "FULL")
        first_pop: dict[int, int] = {}
        for rx in EXT_RECEIVERS:
            await self._ext_send(rx, NINTH_ID)
            head = await self._ext_poll(
                f"R{rx}_NINTH_PROBE",
                _ext_addr("TELEMETRY_PROBE_ID", rx),
                lambda v: v & PROBE_ID_BM != FILL_IDS[0],
                "ninth_message_arrival",
            )
            head &= PROBE_ID_BM
            status = await self._ext_status("NINTH", rx)
            assert (status, head) == (STATUS_FULL, FILL_IDS[1]), (
                f"receiver {rx} after the ninth message: STATUS=0x{status:08x} "
                f"PROBE_ID=0x{head:02x}, expected 0x10 and 0x{FILL_IDS[1]:02x}"
            )
            survivors = [*FILL_IDS[1:], NINTH_ID]
            for index, want_id in enumerate(survivors):
                got = await self._ext_probe(f"DRAIN_{index}", rx)
                assert got == want_id, (
                    f"receiver {rx}: pop {index} presents PROBE_ID=0x{got:02x}, expected "
                    f"0x{want_id:02x} of {[hex(i) for i in survivors]}"
                )
                await self._ext_pop(f"DRAIN_{index}", rx)
                status = await self._ext_status(f"DRAIN_{index}", rx)
                last = index == len(survivors) - 1
                want_status = STATUS_EMPTY if last else STATUS_NEITHER
                assert status == want_status, (
                    f"receiver {rx}: STATUS=0x{status:08x} after pop {index + 1}, expected "
                    f"0x{want_status:02x}"
                )
                if index == 0:
                    first_pop[rx] = status
            probe = await self._ext_probe("DRAINED", rx)
            assert probe == 0, f"receiver {rx}: the empty queue reads PROBE_ID=0x{probe:02x}"
            await self._ext_pop("EXTRA", rx)
            status = await self._ext_status("EXTRA", rx)
            probe = await self._ext_probe("EXTRA", rx)
            assert (status, probe) == (STATUS_EMPTY, 0), (
                f"receiver {rx}: a pop on the empty queue left STATUS=0x{status:08x} "
                f"PROBE_ID=0x{probe:02x}, expected 0x01 and 0x00"
            )
        self._chk(
            "CHK-TELEM12-FULL",
            f"on receivers {list(EXT_RECEIVERS)}, STATUS read 0x00 after each of messages 1-7 "
            f"and 0x10 after the eighth with PROBE_ID=0x{FILL_IDS[0]:02x}; the first pop after "
            f"the overflow read STATUS "
            + ", ".join(f"r{rx}=0x{first_pop[rx]:02x}" for rx in EXT_RECEIVERS),
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_FULL")
        self._chk(
            "CHK-TELEM12-OVERFLOW-ORDER",
            f"on receivers {list(EXT_RECEIVERS)}, the ninth message 0x{NINTH_ID:02x} left "
            f"STATUS=0x10 and PROBE_ID=0x{FILL_IDS[1]:02x}; the eight pops presented "
            f"0x{FILL_IDS[1]:02x}..0x{NINTH_ID:02x} in order, then STATUS=0x01 and PROBE_ID=0x00, "
            f"and the extra pop left both unchanged",
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_OVERFLOW")

    async def _ext_window_trial(self, rx: int, offset: int) -> str:
        """Pop at `offset` clk_periph_i cycles from the last beat of one more message."""
        dut = cocotb.top
        label = f"WINDOW_D{offset:+d}"
        await self._ext_fill(rx, WINDOW_FILL_IDS, label)
        packet = _frame_all_ones_message(WINDOW_ID)
        beats = [(packet >> (8 * i)) & 0xFF for i in range(_NUM_BEATS_PER_PACKET)]
        for index, beat in enumerate(beats[:-1]):
            await _atb_write_beat(dut, beat, beat=index, rx=rx, atid=EXT_ATID[rx])
        last = len(beats) - 1
        if offset < 0:
            pop = cocotb.start_soon(self._ext_pop(label, rx))
            await ClockCycles(dut.clk_periph_i, -offset)
            await _atb_write_beat(dut, beats[last], beat=last, rx=rx, atid=EXT_ATID[rx])
            await pop
        else:
            await _atb_write_beat(dut, beats[last], beat=last, rx=rx, atid=EXT_ATID[rx])
            if offset:
                await ClockCycles(dut.clk_periph_i, offset)
            await self._ext_pop(label, rx)

        # The pop has landed; the push has landed once the queue is full again or
        # the head has moved past the second message.
        second = WINDOW_FILL_IDS[1]
        status = head = 0
        for _ in range(POLL_BOUND):
            status = await self._ext_status(f"{label}_SETTLED", rx)
            head = await self._ext_probe(f"{label}_SETTLED", rx)
            if status & BUFFER_FULL_BM or head != second:
                self._wait(
                    "window_push_arrival",
                    POLL_BOUND,
                    "register polls",
                    f"STATUS=0x{status:02x} PROBE_ID=0x{head:02x}",
                )
                break
            await ClockCycles(dut.clk_smc_i, 4)
        else:
            raise AssertionError(
                f"receiver {rx} {label}: message 0x{WINDOW_ID:02x} never reached the queue "
                f"(STATUS=0x{status:08x} PROBE_ID=0x{head:02x})"
            )

        drained: list[int] = []
        for index in range(QUEUE_DEPTH + 1):
            status = await self._ext_status(f"{label}_DRAIN_{index}", rx)
            if status & BUFFER_EMPTY_BM:
                break
            drained.append(await self._ext_probe(f"{label}_DRAIN_{index}", rx))
            await self._ext_pop(f"{label}_DRAIN_{index}", rx)
        else:
            raise AssertionError(
                f"receiver {rx} {label}: queue not empty after {QUEUE_DEPTH + 1} pops "
                f"({[hex(i) for i in drained]})"
            )
        if drained == WINDOW_NO_DROP:
            return "no-drop"
        if drained == WINDOW_ONE_DROP:
            return "one-drop"
        raise AssertionError(
            f"receiver {rx} {label}: drained {[hex(i) for i in drained]}, neither "
            f"{[hex(i) for i in WINDOW_NO_DROP]} nor {[hex(i) for i in WINDOW_ONE_DROP]}"
        )

    async def _ext_push_pop_window(self) -> None:
        outcomes: dict[int, list[str]] = {}
        for rx in EXT_RECEIVERS:
            outcomes[rx] = [await self._ext_window_trial(rx, d) for d in WINDOW_OFFSETS]
        for rx in EXT_RECEIVERS:
            cocotb.log.info(
                "TELEM12 push/pop window receiver %d (SF-027): %s",
                rx,
                " ".join(f"d={d:+d}:{o}" for d, o in zip(WINDOW_OFFSETS, outcomes[rx])),
            )
        self._chk(
            "CHK-TELEM12-PUSH-POP-WINDOW",
            f"for every offset d in {WINDOW_OFFSETS[0]}..{WINDOW_OFFSETS[-1]} clk_periph_i "
            f"cycles on receivers {list(EXT_RECEIVERS)}, the drain was exactly "
            f"{[hex(i) for i in WINDOW_NO_DROP]} (no-drop) or "
            f"{[hex(i) for i in WINDOW_ONE_DROP]} (one-drop), in order; per offset (SF-027): "
            + "; ".join(
                f"r{rx} " + ",".join(f"{d:+d}={o}" for d, o in zip(WINDOW_OFFSETS, outcomes[rx]))
                for rx in EXT_RECEIVERS
            ),
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_PUSH_POP")

    async def _ext_queue_counted(self, rx: int, ids: tuple[int, ...], label: str) -> None:
        """Queue `ids` one at a time, each confirmed by the occupancy it reaches.

        Occupancy above `CTRL.BUFFER_THRESHOLD` raises `INTR_STATUS.BUFFER_THRESHOLD`,
        so a threshold of k - 1 confirms the k-th message is queued before the next
        is sent.
        """
        ctrl = _ext_addr("CTRL", rx)
        intr_addr = _ext_addr("INTR_STATUS", rx)
        for count, probe_id in enumerate(ids, 1):
            threshold = ((count - 1) << THRESHOLD_BP) & THRESHOLD_BM
            await self.csr_write(f"R{rx}_{label}_THRESHOLD_{count}", ctrl, threshold)
            await self._ext_send(rx, probe_id)
            await self._ext_poll(
                f"R{rx}_{label}_QUEUED_{count}",
                intr_addr,
                lambda v: v & INTR_THRESHOLD,
                "queue_occupancy",
            )

    async def _ext_tx_flush_ready_high(self) -> None:
        """TELEMETRY_TX_FLUSH with afready_i at its bench level, which is high."""
        for rx in EXT_RECEIVERS:
            ctrl = _ext_addr("CTRL", rx)
            await self.csr_write(f"R{rx}_TXF_RX_FLUSH", ctrl, RX_FLUSH_BM)
            await self._ext_poll(
                f"R{rx}_TXF_EMPTY",
                _ext_addr("STATUS", rx),
                lambda v: v & BUFFER_EMPTY_BM,
                "rx_flush_empty",
            )
            await self._ext_queue_counted(rx, TX_FLUSH_IDS, "TXF")
            threshold = ((len(TX_FLUSH_IDS) - 1) << THRESHOLD_BP) & THRESHOLD_BM
            await self.csr_write(f"R{rx}_TXF_FLUSH", ctrl, threshold | TX_FLUSH_BM)
            await self._ext_poll(
                f"R{rx}_TXF_CTRL", ctrl, lambda v: not v & TX_FLUSH_BM, "tx_flush_self_clear"
            )
            status = await self._ext_status("TXF", rx)
            head = await self._ext_probe("TXF", rx)
            assert (status, head) == (STATUS_NEITHER, TX_FLUSH_IDS[0]), (
                f"receiver {rx} after CTRL.TELEMETRY_TX_FLUSH: STATUS=0x{status:08x} "
                f"PROBE_ID=0x{head:02x}, expected 0x00 and 0x{TX_FLUSH_IDS[0]:02x}"
            )
            for index, want_id in enumerate(TX_FLUSH_IDS):
                got = await self._ext_probe(f"TXF_DRAIN_{index}", rx)
                assert got == want_id, (
                    f"receiver {rx}: after the TX flush pop {index} presents 0x{got:02x}, "
                    f"expected 0x{want_id:02x}"
                )
                await self._ext_pop(f"TXF_DRAIN_{index}", rx)
            status = await self._ext_status("TXF_DRAINED", rx)
            assert status == STATUS_EMPTY, (
                f"receiver {rx}: STATUS=0x{status:08x} after draining the three messages"
            )
        self._chk(
            "CHK-TELEM12-TX-FLUSH",
            f"on receivers {list(EXT_RECEIVERS)} with afready_i at its bench level (high), the "
            f"written CTRL.TELEMETRY_TX_FLUSH self-cleared within {POLL_BOUND} polls, STATUS read "
            f"0x00 with PROBE_ID=0x{TX_FLUSH_IDS[0]:02x}, and the queued messages drained in "
            f"order {[hex(i) for i in TX_FLUSH_IDS]}; the afready_i-low handshake is "
            f"NOT-REACHABLE-AT-THIS-LEVEL on this bench (SF-044)",
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_TX_FLUSH")

    async def _beats_until_missing(self, rx: int, label: str) -> int:
        intr_addr = _ext_addr("INTR_STATUS", rx)
        packet = _mid_packet()
        intr = 0
        for beats in range(1, MISSING_BEAT_BOUND + 1):
            index = (beats - 1) % _NUM_BEATS_PER_PACKET
            await _atb_write_beat(
                cocotb.top, (packet >> (8 * index)) & 0xFF, beat=index, rx=rx, atid=EXT_ATID[rx]
            )
            intr = await self.csr_read(f"R{rx}_{label}_{beats}_INTR", intr_addr)
            if intr & INTR_MISSING_LAST:
                assert intr == INTR_MISSING_LAST, (
                    f"receiver {rx}: INTR_STATUS=0x{intr:08x} when MISSING_LAST set, expected 0x01"
                )
                self._wait("missing_last_beats", MISSING_BEAT_BOUND, "beats", f"0x{intr:02x}")
                return beats
        raise AssertionError(
            f"receiver {rx} {label}: MISSING_LAST never set over {MISSING_BEAT_BOUND} beats "
            f"without the last marker (INTR_STATUS=0x{intr:08x})"
        )

    async def _ext_missing_last(self) -> None:
        counts: dict[int, tuple[int, int]] = {}
        for rx in EXT_RECEIVERS:
            intr_addr = _ext_addr("INTR_STATUS", rx)
            enable = _ext_addr("INTR_ENABLE", rx)
            await self.csr_write(f"R{rx}_ML_FLUSH", _ext_addr("CTRL", rx), RX_FLUSH_BM)
            await self.csr_write(f"R{rx}_ML_ENABLE_OFF", enable, 0)
            await self.csr_read(f"R{rx}_ML_ENTRY", intr_addr, expected=0)
            off = await self._beats_until_missing(rx, "ML_OFF")
            assert _line(rx) == 0, f"receiver {rx}: line high with INTR_ENABLE=0x00"
            await self._line_stays_low(rx, f"receiver {rx} MISSING_LAST disabled")
            await self.csr_write(f"R{rx}_ML_OFF_W1C", intr_addr, INTR_MISSING_LAST)
            intr = await self.csr_read(f"R{rx}_ML_OFF_CLEARED", intr_addr)
            assert intr == 0, f"receiver {rx}: INTR_STATUS=0x{intr:08x} after the written 0x01"

            await self.csr_write(f"R{rx}_ML_ENABLE_ON", enable, ENABLE_MISSING_LAST)
            on = await self._beats_until_missing(rx, "ML_ON")
            await self._await_line(rx, 1, f"receiver {rx} MISSING_LAST enabled")
            await self.csr_write(f"R{rx}_ML_ON_W1C", intr_addr, INTR_MISSING_LAST)
            intr = await self.csr_read(f"R{rx}_ML_ON_CLEARED", intr_addr)
            assert intr == 0, f"receiver {rx}: INTR_STATUS=0x{intr:08x} after the written 0x01"
            await self._await_line(rx, 0, f"receiver {rx} MISSING_LAST cleared")

            await self._ext_send(rx, AFTER_MISSING_ID)
            await self._ext_poll(
                f"R{rx}_ML_NEXT",
                _ext_addr("STATUS", rx),
                lambda v: not v & BUFFER_EMPTY_BM,
                "message_arrival",
            )
            head = await self._ext_probe("ML_NEXT", rx)
            assert head == AFTER_MISSING_ID, (
                f"receiver {rx}: the message after MISSING_LAST reads PROBE_ID=0x{head:02x}, "
                f"expected 0x{AFTER_MISSING_ID:02x}"
            )
            await self._ext_pop("ML_NEXT", rx)
            await self.csr_write(f"R{rx}_ML_ENABLE_RESTORE", enable, 0)
            counts[rx] = (off, on)
        self._chk(
            "CHK-TELEM12-MISSING-LAST",
            f"on receivers {list(EXT_RECEIVERS)}, INTR_STATUS read 0x01 with the line at 0 "
            f"while INTR_ENABLE=0x00 and with the line at 1 while INTR_ENABLE=0x01; each "
            f"written 0x01 returned INTR_STATUS to 0x00 and the line to 0; the next complete "
            f"message read PROBE_ID=0x{AFTER_MISSING_ID:02x}; "
            + " ".join(
                f"beats_to_missing_last_r{rx}={counts[rx][0]},{counts[rx][1]}"
                for rx in EXT_RECEIVERS
            )
            + " (measured, LINKED-ISSUE SF-024)",
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_MISSING_LAST")

    async def _ext_intr_test(self) -> None:
        logged: dict[int, tuple[int, int]] = {}
        rise: dict[int, int] = {}
        for rx in EXT_RECEIVERS:
            intr_addr = _ext_addr("INTR_STATUS", rx)
            enable = _ext_addr("INTR_ENABLE", rx)
            test = _ext_addr(INTR_TEST, rx)
            await self.csr_write(f"R{rx}_IT_ENABLE_ON", enable, ENABLE_MISSING_LAST)
            await self.csr_read(f"R{rx}_IT_ENTRY", intr_addr, expected=0)
            assert _line(rx) == 0, f"receiver {rx}: line high before INTR_TEST"
            watch = _LineWatch(rx)
            await self.csr_write(f"R{rx}_IT_ON", test, INTR_TEST_MISSING_LAST)
            for _ in range(LINE_BOUND):
                if watch.seen is not None:
                    break
                await RisingEdge(cocotb.top.clk_smc_i)
            watch.stop()
            assert watch.seen is not None, (
                f"receiver {rx}: INTR_TEST.MISSING_LAST with INTR_ENABLE=0x01 did not raise "
                f"peripheral_interrupts_o[{TELEMETRY_IRQ_BASE + rx}] within the write and "
                f"{LINE_BOUND} clk_smc_i cycles (line={_line(rx)})"
            )
            self._wait("intr_test_rise", LINE_BOUND, "clk_smc_i", "line=1")
            rise[rx] = watch.seen
            after_on = await self.csr_read(f"R{rx}_IT_ON_INTR", intr_addr)
            await self.csr_write(f"R{rx}_IT_ON_W1C", intr_addr, INTR_MISSING_LAST)
            await self._await_line(rx, 0, f"receiver {rx} INTR_TEST cleared")

            await self.csr_write(f"R{rx}_IT_ENABLE_OFF", enable, 0)
            watch = _LineWatch(rx)
            await self.csr_write(f"R{rx}_IT_OFF", test, INTR_TEST_MISSING_LAST)
            await ClockCycles(cocotb.top.clk_smc_i, LINE_BOUND)
            watch.stop()
            assert watch.seen is None, (
                f"receiver {rx}: INTR_TEST.MISSING_LAST with INTR_ENABLE=0x00 raised the line "
                f"{watch.seen} clk_smc_i cycles in"
            )
            self._wait("intr_test_hold_low", LINE_BOUND, "clk_smc_i", "line=0")
            after_off = await self.csr_read(f"R{rx}_IT_OFF_INTR", intr_addr)
            await self.csr_write(f"R{rx}_IT_OFF_W1C", intr_addr, INTR_MISSING_LAST)
            logged[rx] = (after_on, after_off)
        self._chk(
            "CHK-TELEM12-INTR-TEST",
            f"on receivers {list(EXT_RECEIVERS)}, INTR_TEST.MISSING_LAST with INTR_ENABLE=0x01 "
            f"raised the line ("
            + ", ".join(f"r{rx} {rise[rx]} cycles" for rx in EXT_RECEIVERS)
            + ") and with INTR_ENABLE=0x00 left it 0; INTR_STATUS after the test write "
            "(logged, SF-025): "
            + " ".join(
                f"r{rx}_enabled=0x{logged[rx][0]:02x} r{rx}_disabled=0x{logged[rx][1]:02x}"
                for rx in EXT_RECEIVERS
            ),
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TELEM12_INTR_TEST")

    async def _ext_fence(self) -> None:
        names = " ".join(
            f"{name}(bound={bound} {unit}, last {last})"
            for name, (bound, unit, last) in sorted(self.waits.items())
        )
        self._chk(
            "CHK-TIMEOUT-PATHS",
            f"{len(self.waits)} bounded waits, each raising AssertionError with its last "
            f"observed register or line state on expiry: {names}",
        )
        await ClockCycles(cocotb.top.clk_smc_i, 1)
        self._stamp("TIMEOUT")

        steps = [s for s, _ in self.stamps]
        assert tuple(steps) == STEP_ORDER, f"fence steps {steps} out of order"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        stamp_of = dict(self.stamps)
        for chk_id, t, stamps_before in self.chk_lines:
            step = CHK_STEP[chk_id]
            assert stamps_before == STEP_ORDER.index(step) and t <= stamp_of[step], (
                f"{chk_id} at {t} ps followed {stamps_before} step stamps; it belongs inside "
                f"step {step}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s after the receiver-0 legs; checker lines %s; stamps %s",
            " < ".join(STEP_ORDER),
            ",".join(c for c, _, _ in self.chk_lines),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )

    async def body(self) -> None:
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)

        await self._pop_on_empty()
        await self._overflow()
        await self._missing_last()
        await self._partial_and_flush_leg()

        await self._ext_bringup()
        await self._ext_full_and_overflow()
        await self._ext_push_pop_window()
        await self._ext_tx_flush_ready_high()
        await self._ext_missing_last()
        await self._ext_intr_test()
        await self._ext_fence()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
