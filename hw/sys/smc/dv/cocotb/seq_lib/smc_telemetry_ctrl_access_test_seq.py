# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_POWER_TELEMETRY_016 / smc_telemetry_ctrl_access_test: receiver 0 register access.

Scenarios: TLM-CTRL-ACCESS.S1, S2, S3, S4, S5, S6, TLM-STATUS-FLAGS.S5.
Sources: hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl,
hw/ip/telemetry_receiver/doc/architecture.adoc, doc/programmer/src/smc-programming.adoc.

The ATB framing is the DV-owned table of the telemetry receiver CSR leaf: 8-bit beats, 64-bit
packets, 9-bit blocks, 5-bit probe ID header. No document fixes the bit positions.
"""

from __future__ import annotations

import re

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

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


CTRL = _rx_addr("CTRL")
STATUS = _rx_addr("STATUS")
INTR_STATUS = _rx_addr("INTR_STATUS")
INTR_ENABLE = _rx_addr("INTR_ENABLE")
INTR_TEST = _rx_addr("INTR_TEST")
PROBE_ID = _rx_addr("TELEMETRY_PROBE_ID")
COUNTER_VLDS = _rx_addr("TELEMETRY_COUNTER_VLDS")
_COUNTER_SYMBOL = (
    "SMC_TOP_SMC_TELEMETRY_RECEIVER_WRAP_TELEMETRY_RECEIVER_TELEMETRY_COUNTER_BASE_ADDR"
)


def _counter_addr(receiver: int, index: int) -> int:
    """Evaluate the two-index TELEMETRY_COUNTER macro of the generated address header."""
    match = re.search(
        rf"#define\s+{_COUNTER_SYMBOL}\(\w+,\s*\w+\)\s+\((0x[0-9A-Fa-f]+)\s*\+\s*"
        r"\(\w+\s*\*\s*(0x[0-9A-Fa-f]+)\)\s*\+\s*\(\w+\s*\*\s*(0x[0-9A-Fa-f]+)\)\)",
        _SMC_ADDR_H.read_text(encoding="utf-8"),
    )
    assert match, f"{_COUNTER_SYMBOL}(rx, idx) not found in {_SMC_ADDR_H}"
    base, rx_stride, idx_stride = (int(g, 0) for g in match.groups())
    return base + receiver * rx_stride + index * idx_stride


COUNTER_FIRST = _counter_addr(0, 0)
COUNTER_LAST = _counter_addr(0, 31)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

BUFFER_POP_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_POP_bm")
RX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_RX_FLUSH_bm")
TX_FLUSH_BM = _tel("TELEMETRY_RECEIVER__CTRL__TELEMETRY_TX_FLUSH_bm")
THRESHOLD_BM = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bm")
THRESHOLD_BP = _tel("TELEMETRY_RECEIVER__CTRL__BUFFER_THRESHOLD_bp")
BUFFER_EMPTY_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_EMPTY_bm")
BUFFER_FULL_BM = _tel("TELEMETRY_RECEIVER__STATUS__BUFFER_FULL_bm")
PROBE_ID_BM = _tel("TELEMETRY_RECEIVER__TELEMETRY_PROBE_ID__PROBE_ID_bm")
INTR_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_STATUS__MISSING_LAST_bm")
INTR_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_STATUS__BUFFER_THRESHOLD_bm")
ENABLE_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__MISSING_LAST_bm")
ENABLE_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_ENABLE__BUFFER_THRESHOLD_bm")
TEST_MISSING_LAST = _tel("TELEMETRY_RECEIVER__INTR_TEST__MISSING_LAST_bm")
TEST_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")

THRESHOLD_VALUES = (0x000, 0x001, 0xFFF, 0x555)
PENDING_THRESHOLD = 5
ALL_ONES = 0xFFFF_FFFF
RO_REGISTERS = (
    ("STATUS", STATUS),
    ("PROBE_ID", PROBE_ID),
    ("COUNTER_VLDS", COUNTER_VLDS),
    ("COUNTER0", COUNTER_FIRST),
    ("COUNTER31", COUNTER_LAST),
)

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

BUFFER_POLL_BOUND = 200
ATB_READY_BOUND = 64
FUSE_SENSE_MAX_CYCLES = 200_000

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
FENCE_TERMS = (
    "SETUP_DONE",
    "THRESHOLD_FIELD_DONE",
    "PULSE_READS_DONE",
    "FULL_WORD_DONE",
    "INTR_ENABLE_DONE",
    "INTR_TEST_DONE",
    "RO_WRITES_DONE",
)
CHECKER_FOR_STEP = {
    "S2": "CHK-TELEMETRY-THRESHOLD-FIELD-RW",
    "S3": "CHK-TELEMETRY-CTRL-PULSE-READ",
    "S4": "CHK-TELEMETRY-CTRL-FULL-WORD",
    "S5": "CHK-TELEMETRY-INTR-ENABLE-BITS",
    "S6": "CHK-TELEMETRY-INTR-TEST-ACCESS",
    "S7": "CHK-TELEMETRY-RO-WRITE-IGNORED",
}


def _frame_message(probe_id: int) -> int:
    packet = 1 << _ATB_LAST_PACKET_BIT
    packet |= (probe_id & ((1 << _ATB_PROBE_ID_BITS) - 1)) << _ATB_PROBE_ID_LSB
    for block_lsb in range(0, _ATB_NEXT_BLOCK_LSB, _ATB_BLOCK_BITS):
        packet |= _ALL_ONES_BLOCK << block_lsb
    return packet


def _level(signal) -> int:
    raw = signal.value
    assert raw.is_resolvable, f"{signal._name} is X/Z: {raw}"
    return int(raw)


class smc_telemetry_ctrl_access_test_seq(SmcCsrSeq):
    """Access CTRL, INTR_ENABLE, INTR_TEST and the read-only registers of receiver 0."""

    def __init__(self, name: str = "smc_telemetry_ctrl_access_test_seq") -> None:
        super().__init__(name)
        self._stamps: list[tuple[str, int]] = []
        self._chk_log: list[tuple[str, str, int]] = []
        self._waits: list[list[str]] = []
        self._wait_index: dict[str, int] = {}

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

    async def _send_message(self, probe_id: int, label: str) -> None:
        dut = cocotb.top
        self._note_wait("atb_beat_accept", f"{ATB_READY_BOUND}cycles fail-on-expiry=AssertionError")
        packet = _frame_message(probe_id)
        mask = (1 << _ATB_BEAT_BITS) - 1
        try:
            for beat in range(_BEATS_PER_PACKET):
                dut.tb_telemetry0_atdata.value = (packet >> (beat * _ATB_BEAT_BITS)) & mask
                dut.tb_telemetry0_atid.value = _ATB_ID
                dut.tb_telemetry0_atvalid.value = 1
                await RisingEdge(dut.clk_smc_i)
                for _ in range(ATB_READY_BOUND):
                    if _level(dut.tb_telemetry0_atready):
                        break
                    await RisingEdge(dut.clk_smc_i)
                else:
                    raise AssertionError(
                        f"{label}: ATB beat {beat} not accepted, tb_telemetry0_atready low for "
                        f"{ATB_READY_BOUND} clk_smc_i cycles"
                    )
        finally:
            dut.tb_telemetry0_atvalid.value = 0
        self._note_wait("atb_beat_accept", "", f"{label} {_BEATS_PER_PACKET} beats accepted")

    async def _drain(self, label: str) -> None:
        await self.csr_write(f"{label}_FLUSH", CTRL, RX_FLUSH_BM)
        await self._wait_buffer(True, f"{label}_FLUSHED")

    async def _write_response(self, name: str, addr: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None and not item.timed_out, (
            f"{name} @ 0x{addr:08x}: no write response (timed_out={item.timed_out})"
        )
        return item.resp_code

    async def _read_ro(self, label: str) -> list[int]:
        return [await self.csr_read(f"{label}_{n}", a) for n, a in RO_REGISTERS]

    async def _ro_leg(self, leg: str) -> tuple[list[int], list[int]]:
        before = await self._read_ro(f"{leg}_BEFORE")
        responses = []
        for (reg, addr), word in zip(RO_REGISTERS, before):
            for data in (ALL_ONES, 0):
                resp = await self._write_response(f"{leg}_{reg}_{data:x}", addr, data)
                responses.append(resp)
                after = await self._read_ro(f"{leg}_{reg}_{data:x}_AFTER")
                assert after == before, (
                    f"{leg}: write 0x{data:08x} to {reg} (pre-write 0x{word:08x}, resp {resp}) "
                    f"changed the read-only words {[hex(w) for w in before]} -> "
                    f"{[hex(w) for w in after]}"
                )
        return before, responses

    async def body(self) -> None:
        dut = cocotb.top
        for pin in ("tb_telemetry0_atvalid", "tb_telemetry0_atready", "tb_telemetry0_afready"):
            assert hasattr(dut, pin), f"{pin} missing from the bench top"
        self._note_wait(
            "sep_in_access", f"{self.cfg.axi_timeout_ns}ns driver bound fail-on-expiry=driver raise"
        )
        self._note_wait(
            "fuse_sense", f"{FUSE_SENSE_MAX_CYCLES}cycles fail-on-expiry=AssertionError"
        )
        afready = dut.tb_telemetry0_afready

        # S1: setup
        await self.wait_fuse_sense_done(FUSE_SENSE_MAX_CYCLES)
        self._note_wait("fuse_sense", "", "tb_rst_warm_smc_clk_n high")
        original_cg = await self.csr_read("CLOCK_GATE_CONTROL_SAVE", CLOCK_GATE_CONTROL)
        ungated = original_cg & ~TELEMETRY_CG_EN
        await self.csr_write("CLOCK_GATE_CONTROL_TEL_ON", CLOCK_GATE_CONTROL, ungated)
        await self.csr_read("CLOCK_GATE_CONTROL_TEL_ON_RB", CLOCK_GATE_CONTROL, expected=ungated)
        afready.value = 1
        await self._drain("SETUP")
        await self.csr_write("SETUP_INTR_ENABLE", INTR_ENABLE, 0)
        await self.csr_write("SETUP_INTR_CLR", INTR_STATUS, INTR_MISSING_LAST | INTR_THRESHOLD)
        self._stamp("S1")

        # S2: threshold field
        reads = []
        for value in THRESHOLD_VALUES:
            word = value << THRESHOLD_BP
            await self.csr_write(f"THRESHOLD_{value:03x}", CTRL, word)
            ctrl = await self.csr_read(f"THRESHOLD_{value:03x}_RB", CTRL)
            assert ctrl == word, (
                f"CTRL after writing BUFFER_THRESHOLD 0x{value:03x} reads 0x{ctrl:08x}, "
                f"want 0x{word:08x} (field and no other bit)"
            )
            reads.append(ctrl)
        self._stamp("S2")
        self._emit(
            "S2",
            "CHK-TELEMETRY-THRESHOLD-FIELD-RW",
            "BUFFER_THRESHOLD written %s read back CTRL %s exactly, no other CTRL bit set",
            [hex(v) for v in THRESHOLD_VALUES],
            [hex(word) for word in reads],
        )

        # S3: pulse fields
        pulse_reads = []
        for fill in (False, True):
            for pulse_name, pulse in (
                ("POP", BUFFER_POP_BM),
                ("RX_FLUSH", RX_FLUSH_BM),
                ("POP_AND_RX_FLUSH", BUFFER_POP_BM | RX_FLUSH_BM),
            ):
                queue = "msg" if fill else "empty"
                label = f"PULSE_{pulse_name}_{queue}"
                if fill:
                    await self._send_message(0x07, label)
                    await self._wait_buffer(False, f"{label}_FILLED")
                await self.csr_write(label, CTRL, pulse)
                ctrl = await self.csr_read(f"{label}_RB", CTRL)
                if fill:
                    await self._wait_buffer(True, f"{label}_DONE")
                pulse_reads.append(
                    f"{pulse_name}/{queue}=0x{ctrl:08x}(b0={ctrl & BUFFER_POP_BM},"
                    f"b4={(ctrl & RX_FLUSH_BM) >> 4})"
                )
        self._stamp("S3")
        self._emit(
            "S3",
            "CHK-TELEMETRY-CTRL-PULSE-READ",
            "CTRL read after each write pulse, bits 0 and 4 printed and not compared "
            "(SF-012 open): %s; the queued message left the queue after every write",
            " ".join(pulse_reads),
        )

        # S4: full-word overwrite
        afready.value = 0
        pending = (PENDING_THRESHOLD << THRESHOLD_BP) | TX_FLUSH_BM
        await self.csr_write("FULL_WORD_PENDING", CTRL, pending)
        pending_rb = await self.csr_read("FULL_WORD_PENDING_RB", CTRL)
        pending_threshold = (pending_rb & THRESHOLD_BM) >> THRESHOLD_BP
        assert pending_threshold == PENDING_THRESHOLD, (
            f"CTRL BUFFER_THRESHOLD reads {pending_threshold} before the full-word overwrite, "
            f"want {PENDING_THRESHOLD} (CTRL=0x{pending_rb:08x})"
        )
        await self.csr_write("FULL_WORD_POP_ONLY", CTRL, BUFFER_POP_BM)
        ctrl = await self.csr_read("FULL_WORD_AFTER", CTRL)
        afready.value = 1
        threshold = (ctrl & THRESHOLD_BM) >> THRESHOLD_BP
        assert threshold == 0, (
            f"CTRL BUFFER_THRESHOLD reads {threshold} after a full-word write of only "
            f"BUFFER_POP (CTRL=0x{ctrl:08x}, before 0x{pending_rb:08x})"
        )
        self._stamp("S4")
        self._emit(
            "S4",
            "CHK-TELEMETRY-CTRL-FULL-WORD",
            "CTRL 0x%08x with BUFFER_THRESHOLD 5 and TX_FLUSH pending; after the full-word "
            "write 0x%x CTRL read 0x%08x with BUFFER_THRESHOLD %d and bit 8 = %d "
            "(pending request cancelled: SF-012 open, printed only)",
            pending_rb,
            BUFFER_POP_BM,
            ctrl,
            threshold,
            (ctrl & TX_FLUSH_BM) >> 8,
        )

        # S5: INTR_ENABLE
        enable_reads = []
        for value in (
            ENABLE_MISSING_LAST,
            ENABLE_THRESHOLD,
            ENABLE_MISSING_LAST | ENABLE_THRESHOLD,
            0,
        ):
            await self.csr_write(f"INTR_ENABLE_{value:x}", INTR_ENABLE, value)
            read = await self.csr_read(f"INTR_ENABLE_{value:x}_RB", INTR_ENABLE)
            assert read == value, f"INTR_ENABLE wrote 0x{value:x} and read 0x{read:x}"
            enable_reads.append(read)
        self._stamp("S5")
        self._emit(
            "S5",
            "CHK-TELEMETRY-INTR-ENABLE-BITS",
            "INTR_ENABLE written 0x1 0x10 0x11 0x0 read back %s exactly, bits 0 and 4 held "
            "independently",
            [hex(v) for v in enable_reads],
        )

        # S6: INTR_TEST
        await self.csr_write("INTR_TEST_THRESHOLD", INTR_TEST, TEST_THRESHOLD)
        held = await self.csr_read("INTR_TEST_THRESHOLD_RB", INTR_TEST)
        assert held == TEST_THRESHOLD, f"INTR_TEST wrote 0x10 and read 0x{held:x}"
        await self.csr_write("INTR_TEST_ZERO", INTR_TEST, 0)
        released = await self.csr_read("INTR_TEST_ZERO_RB", INTR_TEST)
        assert released == 0, f"INTR_TEST wrote 0 and read 0x{released:x}"
        await self.csr_write("INTR_TEST_PULSE", INTR_TEST, TEST_MISSING_LAST)
        pulse = await self.csr_read("INTR_TEST_PULSE_RB", INTR_TEST)
        intr = await self.csr_read("INTR_TEST_PULSE_STATUS", INTR_STATUS)
        await self.csr_write("INTR_TEST_END_ZERO", INTR_TEST, 0)
        await self.csr_write("INTR_TEST_END_CLR", INTR_STATUS, INTR_MISSING_LAST | INTR_THRESHOLD)
        self._stamp("S6")
        self._emit(
            "S6",
            "CHK-TELEMETRY-INTR-TEST-ACCESS",
            "INTR_TEST read 0x%x after a write of 0x10 and 0x%x after a write of 0; after a "
            "write of 0x1 it read 0x%x (bit 0 = %d) with INTR_STATUS 0x%x (SF-006 open, "
            "printed only)",
            held,
            released,
            pulse,
            pulse & TEST_MISSING_LAST,
            intr,
        )

        # S7: read-only registers
        empty_before, empty_resp = await self._ro_leg("RO_EMPTY")
        assert empty_before[0] & BUFFER_EMPTY_BM and not empty_before[0] & BUFFER_FULL_BM, (
            f"STATUS 0x{empty_before[0]:08x} does not report an empty queue before the writes"
        )
        await self._send_message(0x0B, "RO_MSG")
        await self._wait_buffer(False, "RO_MSG_FILLED")
        msg_before, msg_resp = await self._ro_leg("RO_MSG")
        assert not msg_before[0] & (BUFFER_EMPTY_BM | BUFFER_FULL_BM), (
            f"STATUS 0x{msg_before[0]:08x} does not report one queued message"
        )
        assert msg_before[1] & PROBE_ID_BM == 0x0B, f"PROBE_ID 0x{msg_before[1]:08x}, want 0x0B"
        await self._drain("RO_END")
        await self.csr_write("END_CTRL_ZERO", CTRL, 0)
        self._stamp("S7")
        self._emit(
            "S7",
            "CHK-TELEMETRY-RO-WRITE-IGNORED",
            "writes of 0xFFFFFFFF and 0 to STATUS, PROBE_ID, COUNTER_VLDS, COUNTER[0] and "
            "COUNTER[31] left every register at its pre-write word, empty queue %s and one "
            "queued message %s; write responses (0 OKAY, 2 SLVERR, 3 DECERR; SF-008 open, "
            "printed only) empty %s message %s",
            [hex(w) for w in empty_before],
            [hex(w) for w in msg_before],
            empty_resp,
            msg_resp,
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
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(f"{n}={b} last={last}" for n, b, last in self._waits),
        )
