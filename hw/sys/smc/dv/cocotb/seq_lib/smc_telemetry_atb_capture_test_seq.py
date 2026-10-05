# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0: capture one ATB message, then both flush paths.

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

The ATB beat framing is the DV-owned table already in
``smc_telemetry_receiver_csr_test_seq``; it is imported rather than restated so
the two leaves cannot drift apart. Which 9-bit block of a packet a given
counter byte lands in has no documented source, so the message here fills every
block below the header with an all-ones valid block. ``doc/index.adoc`` states
the rest: "block |9 bits |Seven per packet: 1-bit valid + 8-bit data",
"counter |32 bits |Four consecutive blocks" and "a counter is valid only when
all four of its blocks are valid". One packet therefore offers six blocks below
its header block, which completes exactly one counter, and that counter reads
0xFFFFFFFF whichever six blocks the receiver consumed. Both expectations follow
from the document rather than from where this bench decided to put a byte.
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

# The framing table and the beat driver this leaf shares with the CSR leaf.
from .smc_telemetry_receiver_csr_test_seq import (
    _ATB_BLOCK_BITS,
    _ATB_LAST_PACKET_BIT,
    _ATB_NEXT_BLOCK_LSB,
    _ATB_PROBE_ID_BITS,
    _ATB_PROBE_ID_LSB,
    _send_telemetry_packet,
)

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

MESSAGE_PROBE_ID = 0x1D
MESSAGE_ATID = 0x33
# Every block below the header carries the valid flag and an all-ones data
# byte, so the one counter the packet completes reads all-ones.
ATB_BLOCK_ALL_ONES = (1 << _ATB_BLOCK_BITS) - 1
EXPECTED_VLDS = 0x1
EXPECTED_COUNTER = 0xFFFFFFFF
# The next counter register up. Only six blocks are available below the header
# and a counter needs four, so this one stays at its generated RDL reset --
# which separates "the receiver reassembled what was sent" from "every counter
# register reads all-ones".
UNFILLED_COUNTER = 1
UNFILLED_COUNTER_RESET = _tel("TELEMETRY_RECEIVER__TELEMETRY_COUNTER__COUNTER_reset")


def _frame_all_ones_message(probe_id: int) -> int:
    """One last-flagged packet: ``probe_id`` in the header block, every other block valid."""
    packet = 1 << _ATB_LAST_PACKET_BIT
    packet |= (probe_id & ((1 << _ATB_PROBE_ID_BITS) - 1)) << _ATB_PROBE_ID_LSB
    for block_lsb in range(0, _ATB_NEXT_BLOCK_LSB, _ATB_BLOCK_BITS):
        packet |= ATB_BLOCK_ALL_ONES << block_lsb
    return packet


MESSAGE_PACKET = _frame_all_ones_message(MESSAGE_PROBE_ID)

# Bounds on the DUT-side observations. Expiry is a failure, never a pass.
BUFFER_POLL_BOUND = 200
FLUSH_POLL_BOUND = 64


class smc_telemetry_atb_capture_test_seq(SmcCsrSeq):
    """Drive one ATB message into receiver 0, read it back, then flush both ways."""

    def __init__(self, name: str = "smc_telemetry_atb_capture_test_seq") -> None:
        super().__init__(name)
        self.captured_probe_id: int | None = None
        self.captured_vlds: int | None = None
        self.captured_counter: int | None = None
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

    async def _capture_message(self, dut) -> None:
        await _send_telemetry_packet(dut, MESSAGE_PACKET, rx=RX, atid=MESSAGE_ATID)
        await self._wait_buffer(False, "CAPTURE")

        probe = await self.csr_read("TELEMETRY_PROBE_ID_CAPTURE", PROBE_ID)
        self.captured_probe_id = probe & PROBE_ID_BM
        assert self.captured_probe_id == MESSAGE_PROBE_ID, (
            f"TELEMETRY_PROBE_ID reads 0x{self.captured_probe_id:02x}, expected the "
            f"0x{MESSAGE_PROBE_ID:02x} framed into the message header"
        )

        vlds = await self.csr_read("TELEMETRY_COUNTER_VLDS_CAPTURE", COUNTER_VLDS)
        self.captured_vlds = vlds
        assert vlds == EXPECTED_VLDS, (
            f"TELEMETRY_COUNTER_VLDS reads 0x{vlds:08x}, expected 0x{EXPECTED_VLDS:08x}: one "
            f"packet offers six valid blocks below its header block and a counter needs four"
        )

        counter = await self.csr_read("TELEMETRY_COUNTER_0_CAPTURE", _counter_addr(0))
        self.captured_counter = counter
        assert counter == EXPECTED_COUNTER, (
            f"TELEMETRY_COUNTER[0] reads 0x{counter:08x}, expected 0x{EXPECTED_COUNTER:08x} "
            f"reassembled from four all-ones blocks"
        )
        unfilled = await self.csr_read(
            "TELEMETRY_COUNTER_UNFILLED", _counter_addr(UNFILLED_COUNTER)
        )
        assert unfilled == UNFILLED_COUNTER_RESET, (
            f"TELEMETRY_COUNTER[{UNFILLED_COUNTER}] reads 0x{unfilled:08x} though the message "
            f"carried no blocks for it; its generated reset is 0x{UNFILLED_COUNTER_RESET:08x}"
        )

        await self.csr_write("TELEMETRY_CTRL_POP", CTRL, BUFFER_POP_BM)
        await self._wait_buffer(True, "POP")
        cocotb.log.info(
            "CHK-TELEMETRY-ATB-MESSAGE-CAPTURE: one last-flagged ATB message on receiver %d "
            "cleared STATUS.BUFFER_EMPTY, read back PROBE_ID=0x%02x, COUNTER_VLDS=0x%08x and "
            "COUNTER[0]=0x%08x with COUNTER[%d] still at its reset 0x%08x, and CTRL.BUFFER_POP "
            "returned the buffer to empty",
            RX,
            self.captured_probe_id,
            self.captured_vlds,
            self.captured_counter,
            UNFILLED_COUNTER,
            UNFILLED_COUNTER_RESET,
        )

    async def _receiver_flush(self, dut) -> None:
        await _send_telemetry_packet(dut, MESSAGE_PACKET, rx=RX, atid=MESSAGE_ATID)
        await self._wait_buffer(False, "FLUSH_FILL")
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
