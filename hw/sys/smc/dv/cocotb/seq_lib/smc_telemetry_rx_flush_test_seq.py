# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver flush on receiver 0.

Sources: hw/ip/telemetry_receiver/doc/architecture.adoc (Reset and Flush, Interrupts),
hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl, doc/programmer/src/smc-programming.adoc.

The ATB framing is the DV-owned table of the telemetry receiver CSR leaf: 8-bit beats, 64-bit
packets, 9-bit blocks, 5-bit probe ID header. No document fixes the bit positions.
"""

from __future__ import annotations

import re

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    _REPO,
    _SMC_ADDR_H,
    TELEMETRY_CG_EN,
    _field_mask,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_TELEMETRY_H = (
    _REPO / "hw" / "ip" / "telemetry_receiver" / "regs" / "gen" / "c" / "telemetry_receiver.h"
)


def _tel(symbol: str) -> int:
    return _field_mask(_TELEMETRY_H, symbol)


def _rx_addr(register: str) -> int:
    return smc_indexed_addr(
        f"SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_{register}_BASE_ADDR", 0
    )


def _counter_addr(receiver: int, index: int) -> int:
    symbol = "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR"
    match = re.search(
        rf"#define\s+{symbol}\(\w+,\s*\w+\)\s+\((0x[0-9A-Fa-f]+)\s*\+\s*\(\w+\s*\*\s*"
        r"(0x[0-9A-Fa-f]+)\)\s*\+\s*\(\w+\s*\*\s*(0x[0-9A-Fa-f]+)\)\)",
        _SMC_ADDR_H.read_text(encoding="utf-8"),
    )
    assert match, f"{symbol} not in {_SMC_ADDR_H}"
    base, receiver_stride, index_stride = (int(group, 0) for group in match.groups())
    return base + receiver * receiver_stride + index * index_stride


CTRL = _rx_addr("CTRL")
STATUS = _rx_addr("STATUS")
INTR_STATUS = _rx_addr("INTR_STATUS")
INTR_ENABLE = _rx_addr("INTR_ENABLE")
PROBE_ID = _rx_addr("TELEMETRY_PROBE_ID")
COUNTER_VLDS = _rx_addr("TELEMETRY_COUNTER_VLDS")
COUNTER_FIRST = _counter_addr(0, 0)
COUNTER_WORDS = 4
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

BUFFER_POP_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
THRESHOLD_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
PROBE_ID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")
INTR_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm")
INTR_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__MISSING_LAST_bm")
ENABLE_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")

THRESHOLD = 1
CTRL_THRESHOLD = THRESHOLD << THRESHOLD_BP
CTRL_FLUSH = CTRL_THRESHOLD | RX_FLUSH_BM
CTRL_POP = CTRL_THRESHOLD | BUFFER_POP_BM

# ATB framing (DV-owned table, same layout as the telemetry receiver CSR leaf).
_ATB_BEAT_BITS = 8
_ATB_PACKET_BITS = 64
_BEATS_PER_PACKET = _ATB_PACKET_BITS // _ATB_BEAT_BITS
_ATB_BLOCK_BITS = 9
_ATB_PROBE_ID_BITS = 5
_ATB_PROBE_ID_LSB = 56
_ATB_LAST_PACKET_BIT = 63
_ATB_NEXT_BLOCK_LSB = 54
_ATB_ID = 0x21
_ALL_ONES_BLOCK = (1 << _ATB_BLOCK_BITS) - 1
PARTIAL_BEAT = 0x2A
PARTIAL_BEATS = 5
MAX_PACKETS = 16

BUFFER_POLL_BOUND = 200
ATB_READY_BOUND = 64
IRQ_WAIT_BOUND = 64
QUIET_CYCLES = 64
IN_FLIGHT_BEATS = 2
FUSE_SENSE_MAX_CYCLES = 200_000

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_TERMS = (
    "SETUP_DONE",
    "POPULATED_FLUSH_DONE",
    "ONE_SHOT_DONE",
    "RESTART_DONE",
    "MID_MESSAGE_DONE",
    "BEATS_AROUND_DONE",
    "MISSING_LAST_KEPT",
)
CHECKER_FOR_STEP = {
    "S2": "CHK-TELEMETRY-RX-FLUSH-EMPTIES",
    "S3": "CHK-TELEMETRY-RX-FLUSH-ONE-SHOT",
    "S4": "CHK-TELEMETRY-RX-FLUSH-RESTART",
    "S5": "CHK-TELEMETRY-RX-FLUSH-MID-MESSAGE",
    "S6": "CHK-TELEMETRY-RX-FLUSH-BEATS-AROUND",
    "S7": "CHK-TELEMETRY-RX-FLUSH-KEEPS-MISSING-LAST",
}


def _frame_message(probe_id: int) -> int:
    packet = 1 << _ATB_LAST_PACKET_BIT
    packet |= (probe_id & ((1 << _ATB_PROBE_ID_BITS) - 1)) << _ATB_PROBE_ID_LSB
    for block_lsb in range(0, _ATB_NEXT_BLOCK_LSB, _ATB_BLOCK_BITS):
        packet |= _ALL_ONES_BLOCK << block_lsb
    return packet


def _frame_unflagged() -> int:
    return _frame_message(0x0A) & ~(1 << _ATB_LAST_PACKET_BIT)


def _level(signal) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{signal._name} is X/Z: {raw}"
    return int(raw)


class smc_telemetry_rx_flush_test_seq(SmcCsrSeq):
    """Flush receiver 0 with a populated queue, a partial message, beats in flight and an IRQ."""

    def __init__(self, name: str = "smc_telemetry_rx_flush_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_log: list[tuple[str, str, int]] = []
        self._waits: list[list[str]] = []
        self._wait_index: dict[str, int] = {}
        self._beats_accepted = 0
        self._beats_stalled = 0

    def _note_wait(self, name: str, bound: str, last: str = "not-ended") -> None:
        if name in self._wait_index:
            self._waits[self._wait_index[name]][2] = last
            return
        self._wait_index[name] = len(self._waits)
        self._waits.append([name, bound, last])

    def _stamp(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))

    def _emit(self, step: str, check_id: str, text: str, *args) -> None:
        assert self._stamps and self._stamps[-1][0] == step, (
            f"{check_id} printed before step {step} was stamped"
        )
        self._chk_log.append((check_id, step, len(self._stamps)))
        cocotb.log.info(f"{check_id}: {text}", *args)

    def _irq0(self) -> int:
        return _level(cocotb.top.tb_telemetry_irq) & 1

    async def _wait_irq0(self, want: int, label: str) -> int:
        self._note_wait(f"irq_{label}", f"{IRQ_WAIT_BOUND}cycles fail-on-expiry=AssertionError")
        for cycle in range(IRQ_WAIT_BOUND + 1):
            if self._irq0() == want:
                self._note_wait(f"irq_{label}", "", f"irq[0]={want} after {cycle} cycles")
                return cycle
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: tb_telemetry_irq[0] stayed {self._irq0()} for {IRQ_WAIT_BOUND} "
            f"clk_smc_i cycles, want {want}"
        )

    async def _hold_irq0(self, want: int, cycles: int, label: str) -> None:
        for cycle in range(cycles):
            assert self._irq0() == want, (
                f"{label}: tb_telemetry_irq[0] left {want} after {cycle} of {cycles} cycles"
            )
            await RisingEdge(cocotb.top.clk_smc_i)

    async def _wait_buffer(self, empty: bool, label: str) -> int:
        self._note_wait(
            f"buffer_poll_{label}", f"{BUFFER_POLL_BOUND}polls fail-on-expiry=AssertionError"
        )
        status = 0
        for polls in range(1, BUFFER_POLL_BOUND + 1):
            status = await self.csr_read(f"TELEMETRY_STATUS_{label}", STATUS)
            if bool(status & BUFFER_EMPTY_BM) == empty:
                self._note_wait(
                    f"buffer_poll_{label}", "", f"STATUS=0x{status:08x} after {polls} polls"
                )
                return polls
            await ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: STATUS.BUFFER_EMPTY never reached {int(empty)} over "
            f"{BUFFER_POLL_BOUND} polls (last STATUS=0x{status:08x})"
        )

    async def _drive_beat(self, dut, value: int, label: str) -> None:
        dut.tb_telemetry0_atdata.value = value & 0xFF
        dut.tb_telemetry0_atid.value = _ATB_ID
        dut.tb_telemetry0_atvalid.value = 1
        await RisingEdge(dut.clk_smc_i)
        for _ in range(ATB_READY_BOUND):
            if _level(dut.tb_telemetry0_atready):
                self._beats_accepted += 1
                return
            self._beats_stalled += 1
            await RisingEdge(dut.clk_smc_i)
        dut.tb_telemetry0_atvalid.value = 0
        raise AssertionError(
            f"{label}: ATB beat not accepted, tb_telemetry0_atready low for "
            f"{ATB_READY_BOUND} clk_smc_i cycles"
        )

    async def _send_beats(self, dut, packet: int, count: int, label: str) -> None:
        self._note_wait("atb_beat_accept", f"{ATB_READY_BOUND}cycles fail-on-expiry=AssertionError")
        mask = (1 << _ATB_BEAT_BITS) - 1
        try:
            for beat in range(count):
                await self._drive_beat(dut, (packet >> (beat * _ATB_BEAT_BITS)) & mask, label)
        finally:
            dut.tb_telemetry0_atvalid.value = 0
        self._note_wait("atb_beat_accept", "", f"{label} {count} beats accepted")

    async def _send_message(self, probe_id: int, label: str) -> None:
        await self._send_beats(
            cocotb.top, _frame_message(probe_id), _BEATS_PER_PACKET, f"message_{label}"
        )

    async def _flush_and_wait(self, label: str) -> None:
        await self.csr_write(f"{label}_FLUSH", CTRL, CTRL_FLUSH)
        await self._wait_buffer(True, f"{label}_FLUSHED")

    async def _read_head(self, label: str) -> list[int]:
        words = [
            await self.csr_read(f"{label}_PROBE", PROBE_ID) & PROBE_ID_BM,
            await self.csr_read(f"{label}_VLDS", COUNTER_VLDS),
        ]
        for index in range(COUNTER_WORDS):
            words.append(await self.csr_read(f"{label}_COUNTER{index}", COUNTER_FIRST + 4 * index))
        return words

    async def _pop_to_empty(self, label: str) -> None:
        await self.csr_write(f"{label}_POP", CTRL, CTRL_POP)
        await self._wait_buffer(True, f"{label}_DRAINED")

    async def body(self) -> None:
        dut = cocotb.top
        for pin in ("tb_telemetry0_atvalid", "tb_telemetry0_atready", "tb_telemetry_irq"):
            assert hasattr(dut, pin), f"{pin} missing from the bench top"
        self._note_wait(
            "sep_in_access", f"{self.cfg.axi_timeout_ns}ns driver bound fail-on-expiry=driver raise"
        )
        self._note_wait(
            "fuse_sense", f"{FUSE_SENSE_MAX_CYCLES}cycles fail-on-expiry=AssertionError"
        )
        self._note_wait(
            "missing_last_packets", f"{MAX_PACKETS}packets fail-on-expiry=AssertionError"
        )

        # S1: setup
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._note_wait("fuse_sense", "", "tb_rst_warm_smc_clk_n high")
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)
        await self._flush_and_wait("SETUP")
        await self.csr_write("SETUP_INTR_ENABLE", INTR_ENABLE, 0)
        await self.csr_write("SETUP_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST)
        self._stamp("S1")

        # S2: populated flush
        await self.csr_write("POP_THRESHOLD", CTRL, CTRL_THRESHOLD)
        await self.csr_write("POP_INTR_ENABLE", INTR_ENABLE, ENABLE_THRESHOLD)
        for probe_id in (0x01, 0x02, 0x03):
            await self._send_message(probe_id, f"populate_{probe_id:02x}")
            await self._wait_buffer(False, f"POPULATE_{probe_id:02x}")
        before = await self._read_head("POP_BEFORE")
        assert before[0] == 0x01 and any(before[1:]), (
            f"head registers before the flush are not a live message: {before}"
        )
        intr = await self.csr_read("POP_INTR_BEFORE", INTR_STATUS)
        assert intr & INTR_THRESHOLD, f"three messages above threshold 1: INTR_STATUS 0x{intr:x}"
        await self._wait_irq0(1, "populated_rise")
        await self.csr_write("POP_FLUSH", CTRL, CTRL_FLUSH)
        polls = await self._wait_buffer(True, "POP_FLUSHED")
        after = await self._read_head("POP_AFTER")
        assert after == [0] * (2 + COUNTER_WORDS), f"head registers after the flush: {after}"
        intr = await self.csr_read("POP_INTR_AFTER", INTR_STATUS)
        assert not intr & INTR_THRESHOLD, f"INTR_STATUS.BUFFER_THRESHOLD still set (0x{intr:x})"
        await self._wait_irq0(0, "populated_fall")
        self._stamp("S2")
        self._emit(
            "S2",
            "CHK-TELEMETRY-RX-FLUSH-EMPTIES",
            "three messages (probe IDs 0x01 0x02 0x03) gave BUFFER_EMPTY 0, INTR_STATUS "
            "BUFFER_THRESHOLD 1, irq[0] 1 and head words %s; after one flush BUFFER_EMPTY 1 in "
            "%d poll(s) (bound %d), PROBE_ID, COUNTER_VLDS and COUNTER[0..3] all 0, "
            "BUFFER_THRESHOLD 0 and irq[0] 0",
            [hex(word) for word in before],
            polls,
            BUFFER_POLL_BOUND,
        )

        # S3: one-shot
        ctrl_after = await self.csr_read("ONE_SHOT_CTRL", CTRL)
        assert not ctrl_after & RX_FLUSH_BM, f"CTRL.TELEMETRY_RX_FLUSH reads 1 (0x{ctrl_after:x})"
        ctrl_reads = [ctrl_after]
        for repeat in range(2):
            if repeat:
                await self._hold_irq0(0, QUIET_CYCLES, "one_shot_quiet")
            await self.csr_write(f"ONE_SHOT_FLUSH_{repeat}", CTRL, CTRL_FLUSH)
            await self._wait_buffer(True, f"ONE_SHOT_{repeat}")
            head = await self._read_head(f"ONE_SHOT_{repeat}")
            assert head == [0] * (2 + COUNTER_WORDS), f"head after an empty flush: {head}"
            intr = await self.csr_read(f"ONE_SHOT_INTR_{repeat}", INTR_STATUS)
            assert not intr & (INTR_THRESHOLD | INTR_MISSING_LAST), (
                f"an empty flush raised INTR_STATUS 0x{intr:x}"
            )
            ctrl = await self.csr_read(f"ONE_SHOT_CTRL_{repeat}", CTRL)
            assert not ctrl & RX_FLUSH_BM, f"CTRL.TELEMETRY_RX_FLUSH reads 1 (0x{ctrl:x})"
            ctrl_reads.append(ctrl)
        self._stamp("S3")
        self._emit(
            "S3",
            "CHK-TELEMETRY-RX-FLUSH-ONE-SHOT",
            "CTRL bit 4 read 0 after the flush and after two further flushes (CTRL reads %s, "
            "owner value pending for the pulse readback); each empty flush left BUFFER_EMPTY 1, "
            "the head registers 0 "
            "and no interrupt source",
            [hex(word) for word in ctrl_reads],
        )

        # S4: restart
        await self._send_message(0x1A, "restart")
        polls = await self._wait_buffer(False, "RESTART")
        probe = await self.csr_read("RESTART_PROBE", PROBE_ID) & PROBE_ID_BM
        assert probe == 0x1A, f"PROBE_ID after the flush is 0x{probe:02x}, want 0x1A"
        await self._pop_to_empty("RESTART")
        self._stamp("S4")
        self._emit(
            "S4",
            "CHK-TELEMETRY-RX-FLUSH-RESTART",
            "a message sent after the flush cleared BUFFER_EMPTY in %d poll(s) (bound %d) and "
            "PROBE_ID read 0x%02x",
            polls,
            BUFFER_POLL_BOUND,
            probe,
        )

        # S5: mid-message flush
        partial = int.from_bytes(bytes([PARTIAL_BEAT]) * _BEATS_PER_PACKET, "little")
        await self._send_beats(dut, partial, PARTIAL_BEATS, "partial")
        await self.csr_write("MID_FLUSH", CTRL, CTRL_FLUSH)
        await self._send_message(0x15, "mid_recovery")
        polls = await self._wait_buffer(False, "MID_NEXT")
        probe = await self.csr_read("MID_PROBE", PROBE_ID) & PROBE_ID_BM
        assert probe == 0x15, f"PROBE_ID after the mid-message flush is 0x{probe:02x}, want 0x15"
        await self._pop_to_empty("MID")
        self._stamp("S5")
        self._emit(
            "S5",
            "CHK-TELEMETRY-RX-FLUSH-MID-MESSAGE",
            "%d of %d beats of an unfinished packet and one flush (no second flush): the next "
            "complete message read PROBE_ID 0x%02x in %d poll(s) and one pop emptied the queue "
            "(exactly one message; probe latch rule pending)",
            PARTIAL_BEATS,
            _BEATS_PER_PACKET,
            probe,
            polls,
        )

        # S6: beats around the pulse
        self._beats_accepted = 0
        self._beats_stalled = 0
        self._note_wait(
            "beats_around_in_flight", f"{ATB_READY_BOUND}cycles fail-on-expiry=AssertionError"
        )
        beats_task = cocotb.start_soon(
            self._send_beats(dut, _frame_message(0x13), _BEATS_PER_PACKET, "beats_around")
        )
        for _ in range(ATB_READY_BOUND):
            if self._beats_accepted >= IN_FLIGHT_BEATS:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            raise AssertionError(
                f"only {self._beats_accepted} beats accepted in {ATB_READY_BOUND} cycles"
            )
        in_flight = self._beats_accepted
        self._note_wait("beats_around_in_flight", "", f"{in_flight} beats accepted before write")
        await self.csr_write("BEATS_FLUSH", CTRL, CTRL_FLUSH)
        at_write = self._beats_accepted
        await beats_task
        accepted, stalled = self._beats_accepted, self._beats_stalled
        await ClockCycles(dut.clk_smc_i, QUIET_CYCLES)
        quiet_status = await self.csr_read("BEATS_QUIET_STATUS", STATUS)
        quiet_probe = await self.csr_read("BEATS_QUIET_PROBE", PROBE_ID) & PROBE_ID_BM
        await self._flush_and_wait("BEATS")
        await self._send_message(0x14, "beats_recovery")
        polls = await self._wait_buffer(False, "BEATS_NEXT")
        probe = await self.csr_read("BEATS_PROBE", PROBE_ID) & PROBE_ID_BM
        assert probe == 0x14, f"PROBE_ID after the quiet flush is 0x{probe:02x}, want 0x14"
        await self._pop_to_empty("BEATS")
        self._stamp("S6")
        self._emit(
            "S6",
            "CHK-TELEMETRY-RX-FLUSH-BEATS-AROUND",
            "%d beats accepted before the flush write and %d when it returned, %d accepted in "
            "total of %d presented with %d stalled cycle(s) (not compared); STATUS after "
            "%d quiet cycles 0x%08x with PROBE_ID 0x%02x; after one quiet flush the next message "
            "read PROBE_ID 0x%02x in %d poll(s) as exactly one message",
            in_flight,
            at_write,
            accepted,
            _BEATS_PER_PACKET,
            stalled,
            QUIET_CYCLES,
            quiet_status,
            quiet_probe,
            probe,
            polls,
        )

        # S7: flush against MISSING_LAST
        await self.csr_write("MISSING_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST)
        packets = 0
        for packets in range(1, MAX_PACKETS + 1):
            await self._send_beats(dut, _frame_unflagged(), _BEATS_PER_PACKET, "unflagged")
            intr = await self.csr_read(f"MISSING_{packets}_INTR", INTR_STATUS)
            if intr & INTR_MISSING_LAST:
                self._note_wait(
                    "missing_last_packets", "", f"MISSING_LAST set after {packets} packets"
                )
                break
        else:
            raise AssertionError(f"MISSING_LAST never set over {MAX_PACKETS} unflagged packets")
        await self.csr_write("MISSING_INTR_ENABLE", INTR_ENABLE, ENABLE_MISSING_LAST)
        await self._wait_irq0(1, "missing_rise")
        await self.csr_write("MISSING_FLUSH", CTRL, CTRL_FLUSH)
        intr_flush = await self.csr_read("MISSING_INTR_FLUSH", INTR_STATUS)
        assert intr_flush & INTR_MISSING_LAST, f"the flush cleared MISSING_LAST (0x{intr_flush:x})"
        await self._hold_irq0(1, QUIET_CYCLES, "missing_hold")
        intr_hold = await self.csr_read("MISSING_INTR_HOLD", INTR_STATUS)
        assert intr_hold & INTR_MISSING_LAST, f"MISSING_LAST fell while held (0x{intr_hold:x})"
        await self.csr_write("MISSING_INTR_W1C", INTR_STATUS, INTR_MISSING_LAST)
        intr_clear = await self.csr_read("MISSING_INTR_CLEARED", INTR_STATUS)
        assert not intr_clear & INTR_MISSING_LAST, (
            f"a written one did not clear MISSING_LAST (0x{intr_clear:x})"
        )
        await self._wait_irq0(0, "missing_fall")
        await self.csr_write("MISSING_INTR_DISABLE", INTR_ENABLE, 0)
        await self._flush_and_wait("END")
        await self.csr_write("END_THRESHOLD_OFF", CTRL, 0)
        self._stamp("S7")
        self._emit(
            "S7",
            "CHK-TELEMETRY-RX-FLUSH-KEEPS-MISSING-LAST",
            "MISSING_LAST set on packet %d and irq[0] 1; after CTRL.TELEMETRY_RX_FLUSH "
            "INTR_STATUS read 0x%x, irq[0] stayed 1 for %d cycles and INTR_STATUS read 0x%x; "
            "a written one cleared it (0x%x) and irq[0] fell",
            packets,
            intr_flush,
            QUIET_CYCLES,
            intr_hold,
            intr_clear,
        )

        await self.csr_write("CLOCK_GATE_CONTROL_RESTORE", CLOCK_GATE_CONTROL, original_cg)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RESTORE_RB", CLOCK_GATE_CONTROL, expected=original_cg
        )

        self._finish()

    def _finish(self) -> None:
        steps = [step for step, _ in self._stamps]
        assert steps == list(STEP_ORDER), f"step stamps {steps} differ from {list(STEP_ORDER)}"
        times = [ps for _, ps in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        printed = [check for check, _, _ in self._chk_log]
        expected = [CHECKER_FOR_STEP[s] for s in STEP_ORDER[1:]]
        assert printed == expected, f"checker lines {printed} differ from {expected}"
        for check, step, stamps_seen in self._chk_log:
            assert stamps_seen == STEP_ORDER.index(step) + 1, (
                f"{check} printed with {stamps_seen} steps stamped, not after {step}"
            )
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(printed),
            ",".join(f"{s}={ps}" for s, ps in self._stamps),
        )
        self._note_wait("sep_in_access", "", f"{self.accesses} accesses completed")
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={last}" for n, b, last in self._waits),
        )
