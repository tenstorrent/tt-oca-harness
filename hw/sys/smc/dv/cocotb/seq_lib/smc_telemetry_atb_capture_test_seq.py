# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0: capture ATB messages, decode them, then both flush paths.

The Programmer's Guide Telemetry Receiver section
(``doc/programmer/src/smc-programming.adoc``) gives the three software
procedures this sequence drives, and each leg checks the observable that
procedure names:

* *reading a message* -- "Check STATUS.BUFFER_EMPTY to ensure data is
  available ... Read TELEMETRY_PROBE_ID ... Read TELEMETRY_COUNTER_VLDS to
  determine valid counters ... Read required TELEMETRY_COUNTER ... Write
  CTRL.BUFFER_POP = 1 to advance to next message",
* *receiver flush* -- "Write CTRL.TELEMETRY_RX_FLUSH = 1 ... Check
  STATUS.BUFFER_EMPTY = 1 to confirm flush",
* *transmitter flush* -- "Write CTRL.TELEMETRY_TX_FLUSH = 1 ... Monitor bit
  until it automatically clears (flush complete)", whose pin-side handshake is
  ``afvalid_o`` / ``afready_i`` in ``doc/interface.adoc``.

The message layout is the one ``doc/index.adoc`` "Telemetry packet fields"
states: ``last_packet`` at bit 63 of each packet, block i of a packet at bits
[9i+8:9i] with its valid bit at 9i+8 and its data byte below, ``probe_id`` at
bits [60:56] of the first packet, which are data bits [6:2] of that packet's
block 6, and a counter being four consecutive blocks most-significant byte
first. "Block 0 of the first packet is not decoded; counter 0 begins at block 1
of the first packet, and later packets contribute all seven blocks", and "a
counter is valid only when all four of its blocks are valid" --
``architecture.adoc`` adds "otherwise its decoded value is zero". The four
configured counters therefore span 16 blocks: one packet's six blocks below the
header, a whole second packet and three blocks of a third. ``_decode`` is that
map written down; every message here carries a different byte in every block,
so a receiver that skipped a different block, assembled bytes in the other
order or crossed packets elsewhere reads a different counter.

``architecture.adoc`` also states the receiver's data hazard: "Every configured
counter position is decoded, including positions beyond the last packet
received. A short message following a longer one can therefore inherit trailing
values and validity bits." The validity leg sends a one-packet message after a
three-packet one and expects the counters the short message did not cover to
read the earlier message's.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from .smc_addr_map import (
    _REPO,
    TELEMETRY_CG_EN,
    _field_mask,
    _parse_indexed_bases,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

# The beat driver this leaf shares with the CSR leaf.
from .smc_telemetry_receiver_csr_test_seq import _send_telemetry_packet

_TELEMETRY_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)
_TELEMETRY_ADDR_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver_addr.h"
)

RX = 0


def _tel(symbol: str) -> int:
    """Field mask / position / reset value from generated ``telemetry_receiver.h``."""
    return _field_mask(_TELEMETRY_H, symbol)


def _rx_addr(register: str) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", RX
    )


def _counter_addr(index: int) -> int:
    """Absolute address of ``TELEMETRY_COUNTER[index]`` in receiver ``RX``.

    The SMC map carries this register behind a doubly indexed macro, which
    ``smc_indexed_addr`` cannot evaluate. The block base comes from the SMC map
    and the counter offset from the IP's own generated address header, so both
    halves still follow the RDL.
    """
    block = smc_indexed_addr("SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_BASE_ADDR", RX)
    base, stride = _parse_indexed_bases(_TELEMETRY_ADDR_H)[
        "TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR"
    ]
    return block + base + index * stride


CTRL = _rx_addr("CTRL")
STATUS = _rx_addr("STATUS")
PROBE_ID = _rx_addr("TELEMETRY_PROBE_ID")
COUNTER_VLDS = _rx_addr("TELEMETRY_COUNTER_VLDS")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

BUFFER_POP_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
TX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
PROBE_ID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")

# Telemetry packet fields, index.adoc "Telemetry packet fields".
LAST_PACKET_BIT = 63
BLOCK_BITS = 9
BLOCKS_PER_PACKET = 7
BLOCK_DATA_MASK = 0xFF
PROBE_ID_LSB = 56
PROBE_ID_BITS = 5
PROBE_ID_BLOCK = 6
PROBE_ID_DATA_LSB = 2
COUNTERS_PER_MESSAGE = 4
BLOCKS_PER_COUNTER = 4
# One header block plus four blocks per counter, over seven blocks per packet.
PACKETS_PER_MESSAGE = -(-(1 + COUNTERS_PER_MESSAGE * BLOCKS_PER_COUNTER) // BLOCKS_PER_PACKET)
# The first counter register past the configured count; it reads 0 with its
# validity bit clear (architecture.adoc "Message Queue and Readout").
BEYOND_COUNTER = COUNTERS_PER_MESSAGE

MESSAGE_ATID = 0x33
# Probe IDs and the byte seed of each message; every block of a message carries
# seed + 7 x packet + block, so no two blocks of a message share a byte.
FIRST_PROBE_ID, FIRST_SEED = 0x1D, 0x10
INVALID_PROBE_ID, INVALID_SEED = 0x0A, 0x40
INVALID_BLOCK = (0, 3)
LONG_PROBE_ID, LONG_SEED = 0x15, 0x70
SHORT_PROBE_ID, SHORT_SEED = 0x07, 0xA0

# Bounds on the DUT-side observations. Expiry is a failure, never a pass.
BUFFER_POLL_BOUND = 200
FLUSH_POLL_BOUND = 64


def _packet(blocks: list[tuple[int, int]], last: bool) -> int:
    word = int(last) << LAST_PACKET_BIT
    for index, (valid, data) in enumerate(blocks):
        word |= ((valid << (BLOCK_BITS - 1)) | (data & BLOCK_DATA_MASK)) << (BLOCK_BITS * index)
    return word


def _message(
    probe_id: int, seed: int, packets: int = PACKETS_PER_MESSAGE, invalid: tuple = ()
) -> list[int]:
    """A message of ``packets`` packets, the last one flagged, distinct bytes per block.

    Block (0, 6) carries ``probe_id`` in data bits [6:2]; ``invalid`` names the
    (packet, block) pairs whose valid bit is clear.
    """
    words = []
    for packet in range(packets):
        blocks = []
        for block in range(BLOCKS_PER_PACKET):
            data = (seed + BLOCKS_PER_PACKET * packet + block) & BLOCK_DATA_MASK
            if (packet, block) == (0, PROBE_ID_BLOCK):
                data &= ~(((1 << PROBE_ID_BITS) - 1) << PROBE_ID_DATA_LSB)
                data |= probe_id << PROBE_ID_DATA_LSB
            blocks.append((int((packet, block) not in invalid), data))
        words.append(_packet(blocks, packet == packets - 1))
    return words


def _frame_all_ones_message(probe_id: int) -> int:
    """One last-flagged packet: six valid all-ones blocks, ``probe_id`` in an invalid block 6."""
    blocks = [(1, BLOCK_DATA_MASK)] * (BLOCKS_PER_PACKET - 1)
    blocks.append((0, probe_id << PROBE_ID_DATA_LSB))
    return _packet(blocks, last=True)


def _decode(words: list[int]) -> tuple[int, int, list[int]]:
    """Probe ID, COUNTER_VLDS and the four counters the index.adoc map gives ``words``."""
    blocks: list[tuple[int, int]] = []
    for packet, word in enumerate(words):
        for block in range(1 if packet == 0 else 0, BLOCKS_PER_PACKET):
            field = (word >> (BLOCK_BITS * block)) & ((1 << BLOCK_BITS) - 1)
            blocks.append((field >> (BLOCK_BITS - 1), field & BLOCK_DATA_MASK))
    probe_id = (words[0] >> PROBE_ID_LSB) & ((1 << PROBE_ID_BITS) - 1)
    vlds, counters = 0, []
    for index in range(COUNTERS_PER_MESSAGE):
        four = blocks[BLOCKS_PER_COUNTER * index : BLOCKS_PER_COUNTER * (index + 1)]
        valid = len(four) == BLOCKS_PER_COUNTER and all(v for v, _ in four)
        vlds |= int(valid) << index
        counters.append(int.from_bytes(bytes(d for _, d in four), "big") if valid else 0)
    return probe_id, vlds, counters


FIRST_MESSAGE = _message(FIRST_PROBE_ID, FIRST_SEED)
INVALID_MESSAGE = _message(INVALID_PROBE_ID, INVALID_SEED, invalid=(INVALID_BLOCK,))
LONG_MESSAGE = _message(LONG_PROBE_ID, LONG_SEED)
SHORT_MESSAGE = _message(SHORT_PROBE_ID, SHORT_SEED, packets=1)


class smc_telemetry_atb_capture_test_seq(SmcCsrSeq):
    """Drive ATB messages into receiver 0, decode them, then flush both ways."""

    def __init__(self, name: str = "smc_telemetry_atb_capture_test_seq") -> None:
        super().__init__(name)
        self.captured_probe_id: int | None = None
        self.captured_vlds: int | None = None
        self.captured_counters: list[int] = []
        self.rx_flush_polls = 0
        self.tx_flush_rise_cycles = 0
        self.tx_flush_fall_cycles = 0

    async def body(self) -> None:
        dut = cocotb.top
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)

        await self.csr_read("TELEMETRY_STATUS_ENTRY", STATUS, expected=BUFFER_EMPTY_BM)

        await self._capture_message(dut)
        await self._counter_validity(dut)
        await self._receiver_flush(dut)
        await self._transmitter_flush(dut)

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original_cg
        )

    async def _wait_buffer(self, empty: bool, label: str) -> int:
        """Poll STATUS.BUFFER_EMPTY until it reaches ``empty``; raise on expiry."""
        status = 0
        for polls in range(1, BUFFER_POLL_BOUND + 1):
            status = await self.csr_read(f"TELEMETRY_STATUS_{label}", STATUS)
            if bool(status & BUFFER_EMPTY_BM) == empty:
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 4)
        raise AssertionError(
            f"{label}: STATUS.BUFFER_EMPTY never reached {int(empty)} over "
            f"{BUFFER_POLL_BOUND} polls (last STATUS=0x{status:08x})"
        )

    async def _send_message(self, dut, label: str, words: list[int]) -> None:
        for word in words:
            await _send_telemetry_packet(dut, word, rx=RX, atid=MESSAGE_ATID)
        await self._wait_buffer(False, label)

    async def _read_message(self, label: str, expected: list[int]) -> tuple[int, int, list[int]]:
        """Read the oldest message and compare it with ``_decode(expected)``."""
        want_probe, want_vlds, want_counters = _decode(expected)
        probe = await self.csr_read(f"{label}_PROBE_ID", PROBE_ID) & PROBE_ID_BM
        assert probe == want_probe, (
            f"{label}: TELEMETRY_PROBE_ID reads 0x{probe:02x}, expected the 0x{want_probe:02x} "
            f"framed at bits [60:56] of the first packet"
        )
        vlds = await self.csr_read(f"{label}_COUNTER_VLDS", COUNTER_VLDS)
        assert vlds == want_vlds, (
            f"{label}: TELEMETRY_COUNTER_VLDS reads 0x{vlds:08x}, expected 0x{want_vlds:08x} "
            f"from the valid bits of the four blocks of each counter"
        )
        counters = []
        for index, want in enumerate(want_counters):
            counter = await self.csr_read(f"{label}_COUNTER_{index}", _counter_addr(index))
            assert counter == want, (
                f"{label}: TELEMETRY_COUNTER[{index}] reads 0x{counter:08x}, expected "
                f"0x{want:08x}: blocks {BLOCKS_PER_COUNTER * index + 1} to "
                f"{BLOCKS_PER_COUNTER * (index + 1)} of the message counted from block 1 of the "
                f"first packet, most-significant byte first, zero unless all four are valid"
            )
            counters.append(counter)
        return probe, vlds, counters

    async def _pop(self, label: str) -> None:
        await self.csr_write(f"{label}_POP", CTRL, BUFFER_POP_BM)
        await self._wait_buffer(True, f"{label}_POPPED")

    async def _capture_message(self, dut) -> None:
        await self._send_message(dut, "CAPTURE", FIRST_MESSAGE)
        probe, vlds, counters = await self._read_message("CAPTURE", FIRST_MESSAGE)
        beyond = await self.csr_read("CAPTURE_COUNTER_BEYOND", _counter_addr(BEYOND_COUNTER))
        assert beyond == 0, (
            f"TELEMETRY_COUNTER[{BEYOND_COUNTER}] reads 0x{beyond:08x} past the "
            f"{COUNTERS_PER_MESSAGE} configured counters; it must read 0"
        )
        self.captured_probe_id, self.captured_vlds, self.captured_counters = probe, vlds, counters
        await self._pop("CAPTURE")
        cocotb.log.info(
            "CHK-TELEMETRY-ATB-MESSAGE-CAPTURE: a %d-packet last-flagged ATB message on receiver "
            "%d cleared STATUS.BUFFER_EMPTY, read back PROBE_ID=0x%02x and COUNTER_VLDS=0x%08x "
            "with COUNTER[%d] at 0 past the configured counters, and CTRL.BUFFER_POP returned "
            "the buffer to empty",
            len(FIRST_MESSAGE),
            RX,
            probe,
            vlds,
            BEYOND_COUNTER,
        )
        cocotb.log.info(
            "CHK-TELEMETRY-COUNTER-BYTE-MAP: packets %s with a distinct byte in every block read "
            "back COUNTER[0..3] = %s: counter 0 from blocks 1-4 of the first packet (block 0 "
            "skipped), counter 1 from its blocks 5-6 and blocks 0-1 of the second, counters 2 and "
            "3 across the second and third packets, most-significant byte first, with the probe "
            "ID inside block 6's data byte",
            ", ".join(f"0x{w:016x}" for w in FIRST_MESSAGE),
            ", ".join(f"0x{c:08x}" for c in counters),
        )

    async def _counter_validity(self, dut) -> None:
        await self._send_message(dut, "INVALID", INVALID_MESSAGE)
        _, invalid_vlds, invalid_counters = await self._read_message("INVALID", INVALID_MESSAGE)
        await self._pop("INVALID")

        await self._send_message(dut, "LONG", LONG_MESSAGE)
        await self._read_message("LONG", LONG_MESSAGE)
        await self._pop("LONG")
        inherited = SHORT_MESSAGE + LONG_MESSAGE[1:]
        await self._send_message(dut, "SHORT", SHORT_MESSAGE)
        _, short_vlds, short_counters = await self._read_message("SHORT", inherited)
        await self._pop("SHORT")
        cocotb.log.info(
            "CHK-TELEMETRY-COUNTER-VALIDITY: with block %d of packet %d invalid COUNTER_VLDS read "
            "0x%08x and COUNTER[0..3] = %s (counter 0 zero, the others intact); a one-packet "
            "message after a three-packet one read COUNTER_VLDS 0x%08x and COUNTER[0..3] = %s, "
            "counter 1's lower half and counters 2 and 3 inherited from the earlier message's "
            "trailing packets",
            INVALID_BLOCK[1],
            INVALID_BLOCK[0],
            invalid_vlds,
            ", ".join(f"0x{c:08x}" for c in invalid_counters),
            short_vlds,
            ", ".join(f"0x{c:08x}" for c in short_counters),
        )

    async def _receiver_flush(self, dut) -> None:
        await self._send_message(dut, "FLUSH_FILL", FIRST_MESSAGE)
        await self.csr_write("TELEMETRY_CTRL_RX_FLUSH", CTRL, RX_FLUSH_BM)
        self.rx_flush_polls = await self._wait_buffer(True, "RX_FLUSH")
        await self.csr_write("TELEMETRY_CTRL_RX_FLUSH_CLEAR", CTRL, 0)
        await self.csr_read("TELEMETRY_CTRL_RX_FLUSH_CLEAR_RB", CTRL, expected=0)
        cocotb.log.info(
            "CHK-TELEMETRY-RX-FLUSH: a buffered message on receiver %d left STATUS.BUFFER_EMPTY "
            "clear, CTRL.TELEMETRY_RX_FLUSH returned it to empty within %d polls, and clearing "
            "the request read CTRL back at 0",
            RX,
            self.rx_flush_polls,
        )

    async def _transmitter_flush(self, dut) -> None:
        afready = getattr(dut, f"tb_telemetry{RX}_afready")
        afvalid = getattr(dut, f"tb_telemetry{RX}_afvalid")
        afready.value = 0
        await ClockCycles(dut.clk_smc_i, FLUSH_POLL_BOUND)
        assert self._level(afvalid) == 0, (
            "telemetry afvalid_o is asserted before software requested a transmitter flush"
        )

        await self.csr_write("TELEMETRY_CTRL_TX_FLUSH", CTRL, TX_FLUSH_BM)
        self.tx_flush_rise_cycles = await self._await_level(dut, afvalid, 1, "TX_FLUSH_RISE")
        held = await self.csr_read("TELEMETRY_CTRL_TX_FLUSH_HELD", CTRL)
        assert held & TX_FLUSH_BM, (
            f"CTRL.TELEMETRY_TX_FLUSH cleared itself while telemetry afready_i was still low "
            f"(CTRL=0x{held:08x})"
        )

        afready.value = 1
        self.tx_flush_fall_cycles = await self._await_level(dut, afvalid, 0, "TX_FLUSH_FALL")
        cleared = await self.csr_read("TELEMETRY_CTRL_TX_FLUSH_CLEARED", CTRL)
        assert cleared & TX_FLUSH_BM == 0, (
            f"CTRL.TELEMETRY_TX_FLUSH still set after telemetry afready_i acknowledged the "
            f"request (CTRL=0x{cleared:08x})"
        )
        cocotb.log.info(
            "CHK-TELEMETRY-TX-FLUSH-HANDSHAKE: afvalid_o idle at 0, raised %d clk_smc_i cycles "
            "after CTRL.TELEMETRY_TX_FLUSH was written and held while afready_i was low, then "
            "retired %d cycles after afready_i went high with CTRL.TELEMETRY_TX_FLUSH "
            "self-cleared (CTRL=0x%08x)",
            self.tx_flush_rise_cycles,
            self.tx_flush_fall_cycles,
            cleared,
        )

    @staticmethod
    def _level(signal) -> int:
        raw = signal.value
        assert raw.is_resolvable, f"{signal._name} is X/Z: {raw}"
        return int(raw)

    async def _await_level(self, dut, signal, want: int, label: str) -> int:
        if self._level(signal) == want:
            return 0
        for cycle in range(1, FLUSH_POLL_BOUND + 1):
            await RisingEdge(dut.clk_smc_i)
            if self._level(signal) == want:
                return cycle
        raise AssertionError(
            f"{label}: telemetry afvalid_o stayed {self._level(signal)} for "
            f"{FLUSH_POLL_BOUND} clk_smc_i cycles, want {want}"
        )
