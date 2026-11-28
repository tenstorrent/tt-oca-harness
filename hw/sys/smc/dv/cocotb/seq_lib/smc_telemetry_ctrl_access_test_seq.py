# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Telemetry receiver 0 register access.

Sources: hw/ip/telemetry_receiver/regs/telemetry_receiver.rdl,
hw/ip/telemetry_receiver/doc/architecture.adoc, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import TELEMETRY_CG_EN, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_telemetry_atb_capture_test_seq import (
    BUFFER_EMPTY_BM,
    BUFFER_FULL_BM,
    CTRL,
    ENABLE_THRESHOLD_BM,
    INTR_ENABLE,
    INTR_STATUS,
    INTR_THRESHOLD_BM,
    RX_FLUSH_BM,
    STATUS,
    TELEMETRY_DATA,
    THRESHOLD_BP,
    TX_FLUSH_BM,
    _HeldSource,
    _rx_addr,
    _tel,
    _word,
)

INTR_TEST = _rx_addr("INTR_TEST")
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

TEST_THRESHOLD = _tel("TELEMETRY_RECEIVER__INTR_TEST__BUFFER_THRESHOLD_bm")
#: CTRL bit 0, reserved: no field of the RDL occupies it.
CTRL_BIT0 = 0x1

THRESHOLD_VALUES = (0x000, 0x001, 0xFFF, 0x555)
PENDING_THRESHOLD = 5
ALL_ONES = 0xFFFF_FFFF
RO_REGISTERS = (("STATUS", STATUS), ("TELEMETRY_DATA", TELEMETRY_DATA))
PULSE_BEAT = (0x21, 0x07)
RESERVED_BEAT = (0x22, 0x5E)
RO_BEAT = (0x23, 0x0B)

BUFFER_POLL_BOUND = 200
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

    async def _read_ro(self, label: str, regs) -> list[int]:
        return [await self.csr_read(f"{label}_{n}", a) for n, a in regs]

    async def _ro_leg(self, leg: str, regs) -> tuple[list[int], list[int]]:
        """Write all ones and all zeros to each of `regs`; every one must read as before."""
        before = await self._read_ro(f"{leg}_BEFORE", regs)
        responses = []
        for (reg, addr), word in zip(regs, before):
            for data in (ALL_ONES, 0):
                resp = await self._write_response(f"{leg}_{reg}_{data:x}", addr, data)
                responses.append(resp)
                after = await self._read_ro(f"{leg}_{reg}_{data:x}_AFTER", regs)
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
        await self.csr_write("SETUP_INTR_TEST", INTR_TEST, 0)
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

        # S3: pulse field and the reserved bit 0
        pulse_reads = []
        for fill in (False, True):
            queue = "beat" if fill else "empty"
            label = f"PULSE_RX_FLUSH_{queue}"
            if fill:
                await _HeldSource(dut, [PULSE_BEAT]).task
                await self._wait_buffer(False, f"{label}_FILLED")
            await self.csr_write(label, CTRL, RX_FLUSH_BM)
            ctrl = await self.csr_read(f"{label}_RB", CTRL)
            assert ctrl & RX_FLUSH_BM == 0, f"{label}: CTRL 0x{ctrl:08x} reads bit 4 set"
            if fill:
                await self._wait_buffer(True, f"{label}_DONE")
                await self.csr_read(f"{label}_DATA", TELEMETRY_DATA, expected=0)
            pulse_reads.append(f"RX_FLUSH/{queue}=0x{ctrl:08x}")
        await _HeldSource(dut, [RESERVED_BEAT]).task
        await self._wait_buffer(False, "RESERVED_FILLED")
        await self.csr_write("RESERVED_BIT0", CTRL, CTRL_BIT0)
        reserved = await self.csr_read("RESERVED_BIT0_RB", CTRL)
        assert reserved == 0, f"CTRL after a write of bit 0 alone reads 0x{reserved:08x}"
        await self.csr_read("RESERVED_STATUS", STATUS, expected=0)
        await self.csr_read("RESERVED_DATA", TELEMETRY_DATA, expected=_word(RESERVED_BEAT))
        await self.csr_read("RESERVED_DATA_EMPTY", TELEMETRY_DATA, expected=0)
        self._stamp("S3")
        self._emit(
            "S3",
            "CHK-TELEMETRY-CTRL-PULSE-READ",
            "CTRL read after each TELEMETRY_RX_FLUSH write, bit 4 read 0 (sw=w in the RDL): %s; "
            "the queued beat left the FIFO on the flush; a write of reserved bit 0 read back "
            "CTRL 0x%08x and left the queued beat in place for TELEMETRY_DATA to return",
            " ".join(pulse_reads),
            reserved,
        )

        # S4: full-word overwrite
        afready.value = 0
        pending = (PENDING_THRESHOLD << THRESHOLD_BP) | TX_FLUSH_BM
        await self.csr_write("FULL_WORD_PENDING", CTRL, pending)
        pending_rb = await self.csr_read("FULL_WORD_PENDING_RB", CTRL)
        assert pending_rb == pending, (
            f"CTRL reads 0x{pending_rb:08x} before the full-word overwrite, want 0x{pending:08x}"
        )
        await self.csr_write("FULL_WORD_ZERO", CTRL, 0)
        ctrl = await self.csr_read("FULL_WORD_AFTER", CTRL)
        afready.value = 1
        assert ctrl == 0, (
            f"CTRL reads 0x{ctrl:08x} after a full-word write of 0 over 0x{pending_rb:08x}; the "
            f"threshold takes the written 0 and the RDL withdraws a pending TX flush on a 0"
        )
        self._stamp("S4")
        self._emit(
            "S4",
            "CHK-TELEMETRY-CTRL-FULL-WORD",
            "CTRL 0x%08x with BUFFER_THRESHOLD %d and TX_FLUSH pending; after the full-word "
            "write of 0 CTRL read 0x%08x, the threshold cleared and the pending request withdrawn",
            pending_rb,
            PENDING_THRESHOLD,
            ctrl,
        )

        # S5: INTR_ENABLE
        enable_reads = []
        for value, want in (
            (ENABLE_THRESHOLD_BM, ENABLE_THRESHOLD_BM),
            (0, 0),
            (ALL_ONES, ENABLE_THRESHOLD_BM),
            (0, 0),
        ):
            await self.csr_write(f"INTR_ENABLE_{value:x}", INTR_ENABLE, value)
            read = await self.csr_read(f"INTR_ENABLE_{value:x}_RB", INTR_ENABLE)
            assert read == want, (
                f"INTR_ENABLE wrote 0x{value:x} and read 0x{read:x}, want 0x{want:x}"
            )
            enable_reads.append(read)
        self._stamp("S5")
        self._emit(
            "S5",
            "CHK-TELEMETRY-INTR-ENABLE-BITS",
            "INTR_ENABLE written 0x10 0x0 0xffffffff 0x0 read back %s: bit 4 held and no other "
            "bit stored",
            [hex(v) for v in enable_reads],
        )

        # S6: INTR_TEST
        await self.csr_write("INTR_TEST_THRESHOLD", INTR_TEST, TEST_THRESHOLD)
        held = await self.csr_read("INTR_TEST_THRESHOLD_RB", INTR_TEST)
        assert held == TEST_THRESHOLD, f"INTR_TEST wrote 0x10 and read 0x{held:x}"
        forced = await self.csr_read("INTR_TEST_THRESHOLD_STATUS", INTR_STATUS)
        assert forced == INTR_THRESHOLD_BM, f"INTR_STATUS 0x{forced:x} with INTR_TEST held"
        await self.csr_write("INTR_TEST_ZERO", INTR_TEST, 0)
        released = await self.csr_read("INTR_TEST_ZERO_RB", INTR_TEST)
        assert released == 0, f"INTR_TEST wrote 0 and read 0x{released:x}"
        await self.csr_write("INTR_TEST_ONES", INTR_TEST, ALL_ONES)
        ones = await self.csr_read("INTR_TEST_ONES_RB", INTR_TEST)
        assert ones == TEST_THRESHOLD, f"INTR_TEST wrote all ones and read 0x{ones:x}"
        await self.csr_write("INTR_TEST_END_ZERO", INTR_TEST, 0)
        intr = await self.csr_read("INTR_TEST_END_STATUS", INTR_STATUS)
        assert intr == 0, f"INTR_STATUS 0x{intr:x} after INTR_TEST was released"
        self._stamp("S6")
        self._emit(
            "S6",
            "CHK-TELEMETRY-INTR-TEST-ACCESS",
            "INTR_TEST read 0x%x after a write of 0x10 with INTR_STATUS 0x%x, 0x%x after a write "
            "of 0, and 0x%x after a write of all ones; INTR_STATUS read 0x%x once it was released",
            held,
            forced,
            released,
            ones,
            intr,
        )

        # S7: read-only registers
        empty_before, empty_resp = await self._ro_leg("RO_EMPTY", RO_REGISTERS)
        assert empty_before == [BUFFER_EMPTY_BM, 0], (
            f"STATUS and TELEMETRY_DATA {[hex(w) for w in empty_before]} do not report an empty "
            f"FIFO before the writes"
        )
        await _HeldSource(dut, [RO_BEAT]).task
        await self._wait_buffer(False, "RO_BEAT_FILLED")
        beat_before, beat_resp = await self._ro_leg("RO_BEAT", RO_REGISTERS[:1])
        assert not beat_before[0] & (BUFFER_EMPTY_BM | BUFFER_FULL_BM), (
            f"STATUS 0x{beat_before[0]:08x} does not report one queued beat"
        )
        await self.csr_read("RO_BEAT_DATA", TELEMETRY_DATA, expected=_word(RO_BEAT))
        await self._drain("RO_END")
        await self.csr_write("END_CTRL_ZERO", CTRL, 0)
        self._stamp("S7")
        self._emit(
            "S7",
            "CHK-TELEMETRY-RO-WRITE-IGNORED",
            "writes of 0xFFFFFFFF and 0 to STATUS and TELEMETRY_DATA left both at their "
            "pre-write words with the FIFO empty %s, and writes to STATUS left it at %s with one "
            "beat queued, which TELEMETRY_DATA then returned as 0x%08x; write responses (0 "
            "OKAY, 2 SLVERR, 3 DECERR; not specified, measured, printed only) empty %s beat %s",
            [hex(w) for w in empty_before],
            [hex(w) for w in beat_before],
            _word(RO_BEAT),
            empty_resp,
            beat_resp,
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
