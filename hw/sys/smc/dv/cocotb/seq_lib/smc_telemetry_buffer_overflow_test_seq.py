# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 past its limits: a full message buffer, and a message with no end.

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

`CTRL.BUFFER_POP` "is effective only if `STATUS.BUFFER_EMPTY = 0`", so a pop
written to an empty buffer must leave it empty and not disturb the message
that arrives next.

The packet framing and the beat driver are the capture leaf's, shared from
`smc_telemetry_receiver_csr_test_seq`.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
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
    _frame_all_ones_message,
    _rx_addr,
    _tel,
)
from .smc_telemetry_receiver_csr_test_seq import _ATB_LAST_PACKET_BIT, _send_telemetry_packet

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

    async def _status(self, label: str) -> int:
        return await self.csr_read(f"TELEMETRY_STATUS_{label}", STATUS)

    async def _wait_status(self, label: str, mask: int, want: bool) -> int:
        status = 0
        for _ in range(POLL_BOUND):
            status = await self._status(label)
            if bool(status & mask) == want:
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

    async def body(self) -> None:
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)

        await self._pop_on_empty()
        await self._overflow()
        await self._missing_last()

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
