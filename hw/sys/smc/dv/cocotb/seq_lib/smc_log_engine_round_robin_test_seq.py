# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine arbitration: whole messages, each exactly once, zero lengths skipped, LOG_LEN hold.

`smc_log_engine_transfer_test` triggers four slots at once and compares each slot's bytes
without a constraint on how messages interleave. This leaf reads the byte stream of wrapper 0
out of RBR in MCR.LOOP and decodes it into messages.

`architecture.adoc` ("Arbitration and Data Transfer") has the arbiter select among nonzero
lengths and advance when the selected message completes: "Scheduling is per message, not per
byte". "Memory Slots and Lengths" makes a nonzero `LOG_LEN` the pending mark and the length
"the submitted value until hardware clears it on completion". `log_engine.rdl` `LOG_CTRL`
repeats the hold and the hardware clear.

The window holds the byte `(slot << 4) | j` at slot offset `j` of a 0x100 byte region, so a
byte names the slot and the position it came from. Legs:

* wave A: `LOG_LEN` 0 on slots 0 and 11, 16 on slots 1, 4, 9 and 14;
* wave B: 16 on all sixteen slots;
* wave C: 16 on slots 3, 6 and 12, then 16 on slots 2 and 13 at the first byte read from RBR.

In every wave the LOG_CTRL element of the slot whose message is arriving is read after its
fourth byte left RBR and must still read 16: the engine is paced one character at a time, so a
remaining-byte counter would read at most 12 there. In wave C the same element is read before
the late writes, at the first byte, so the late writes land while that message is in flight at
the engine. The service order is measured, not compared. An idle receiver is TEMT = 1 and DR = 0
on a run of consecutive LSR polls longer than a character time. A pending length is never
written back to 0.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time

from .smc_addr_map import SPM_MEMORY_BASE, SPM_MEMORY_SIZE, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    CTRL_EN,
    INTR_STATUS_MASK,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    LSR_DR,
    LSR_LINE_ERRORS,
    LSR_TEMT,
    NUM_LOG_ENTRIES,
    RBR_DATA,
    THR_OFFSET,
    WRAP_NUM,
    WRAP_STRIDE_SYMBOL,
    arm_uart,
    engine_reg,
    restore_uart,
    uart_base,
    uart_reg,
)
from .smc_regblock_field_sweep_utils import array_reg_instances

WRAP = 0
_WINDOW_OFFSET = 0x40000
_REGION_SIZE = 0x100
# architecture.adoc: slot i starts at LOG_REGION_ADDR + (LOG_REGION_SIZE / 16) * i.
_MSG_LEN = _REGION_SIZE // NUM_LOG_ENTRIES

_WAVE_A_ZERO = (0, 11)
_WAVE_A_SLOTS = (1, 4, 9, 14)
_WAVE_B_SLOTS = tuple(range(NUM_LOG_ENTRIES))
_WAVE_C_FIRST = (3, 6, 12)
_WAVE_C_LATE = (2, 13)
_WAVE_C_SLOTS = _WAVE_C_FIRST + _WAVE_C_LATE

# Polls of LSR allowed per expected byte; expiry is a failure.
_RX_POLLS_PER_BYTE = 400
# Reads of one LOG_CTRL element allowed before its hardware clear is declared absent.
_HWCLR_POLLS = 64
# Bytes of the first message read out of RBR before its slot's LOG_CTRL is read mid-message.
_MID_BYTE = 4
# Consecutive polls with TEMT = 1 and DR = 0 that make the receiver idle; a character takes far
# fewer reads than this to arrive.
_IDLE_POLLS = 32

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5")
CHK_ORDER = (
    ("S2", "CHK-LOGENG-RR-ZERO-SKIPPED"),
    ("S2", "CHK-LOGENG-LEN-ZERO-NOT-PENDING"),
    ("S2", "CHK-LOGENG-LEN-HOLD-SUBMITTED"),
    ("S3", "CHK-LOGENG-RR-EXACTLY-ONCE"),
    ("S4", "CHK-LOGENG-RR-IN-FLIGHT"),
    ("S4", "CHK-LOGENG-RR-ATOMIC"),
    ("S4", "CHK-LOGENG-LEN-HWCLEAR"),
    ("S4", "CHK-LOGENG-RR-ORDER-MEASURED"),
)


def _hex(values: list[int]) -> str:
    return "[" + " ".join(f"{v:02x}" for v in values) + "]"


def _decode(label: str, stream: list[int]) -> list[int]:
    """Split `stream` into whole messages and return the slot of each, in arrival order."""
    assert len(stream) % _MSG_LEN == 0, (
        f"[{label}]: {len(stream)} bytes are not whole {_MSG_LEN}-byte messages: {_hex(stream)}"
    )
    slots = []
    for start in range(0, len(stream), _MSG_LEN):
        chunk = stream[start : start + _MSG_LEN]
        slot = chunk[0] >> 4
        want = [(slot << 4) | j for j in range(_MSG_LEN)]
        assert chunk == want, (
            f"[{label}]: message at stream position {start} is {_hex(chunk)}, a whole slot "
            f"{slot} message is {_hex(want)}"
        )
        slots.append(slot)
    return slots


class smc_log_engine_round_robin_test_seq(SmcCsrSeq):
    """Drive wrapper 0's log engine with several pending slots and decode the stream."""

    def __init__(self, name: str = "smc_log_engine_round_robin_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.elements = []
        self.window = 0
        self.pending: set[int] = set()
        self.orders: dict[str, list[int]] = {}
        self.clear_polls: dict[str, dict[int, int]] = {}
        self.hold_reads: dict[int, int] = {}
        self.wave_a_zero_reads: dict[int, int] = {}
        self.late_start: dict[int, int] = {}
        self.first_message_slot = -1
        self.mid_reads: dict[str, tuple[int, int]] = {}
        self.in_flight_read: tuple[int, int] = (-1, -1)

    # -- fence -----------------------------------------------------------

    def _mark(self, step: str) -> None:
        self.steps.append((step, int(get_sim_time("ps"))))

    def _chk(self, step: str, chk_id: str, text: str) -> None:
        assert self.steps and self.steps[-1][0] == step, f"{chk_id} printed before {step} ended"
        self.chk_steps.append((step, chk_id))
        cocotb.log.info("%s: %s", chk_id, text)

    def _nonvac(self) -> None:
        assert tuple(s for s, _ in self.steps) == STEP_ORDER, f"step order {self.steps}"
        stamps = [ps for _, ps in self.steps]
        assert all(b > a for a, b in zip(stamps, stamps[1:])), f"stamps not increasing {stamps}"
        assert tuple(self.chk_steps) == CHK_ORDER, f"checker lines {self.chk_steps}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence S1 < S2 < S3 < S4 < S5, step stamps strictly "
            "increasing, each checker line after its own step; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    # -- register legs ---------------------------------------------------

    async def _load_window(self) -> None:
        self.window = SPM_MEMORY_BASE + _WINDOW_OFFSET
        assert self.window % 8 == 0 and (
            self.window + _REGION_SIZE <= SPM_MEMORY_BASE + SPM_MEMORY_SIZE
        ), f"log window 0x{self.window:08x} is unaligned or runs past the SPM window"
        words = []
        for word in range(0, _REGION_SIZE, 8):
            value = 0
            for lane in range(8):
                value |= (word + lane) << (8 * lane)
            words.append(value)
        for index, value in enumerate(words):
            await self.csr_write(f"WINDOW_W{index}", self.window + index * 8, value, length=8)
        for index, value in enumerate(words):
            await self.csr_read(
                f"WINDOW_W{index}_RB", self.window + index * 8, expected=value, length=8
            )

    async def _setup(self) -> None:
        await self.wait_fuse_sense_done()
        await arm_uart(self, WRAP)
        await self.csr_write("LE_OFF", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_write("INTR_CLEAR", engine_reg(WRAP, "INTR_STATUS"), INTR_STATUS_MASK)
        await self.csr_write("INTR_ENABLE", engine_reg(WRAP, "INTR_ENABLE"), 0)
        await self.csr_write("REGION_SIZE", engine_reg(WRAP, "LOG_REGION_SIZE"), _REGION_SIZE)
        await self.csr_write(
            "WRITE_ADDR", engine_reg(WRAP, "LOG_WRITE_ADDR"), uart_base(WRAP) + THR_OFFSET
        )
        await self._load_window()
        region_addr = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write("REGION_ADDR_LO", region_addr, self.window & 0xFFFF_FFFF)
        await self.csr_write("REGION_ADDR_HI", region_addr + 4, self.window >> 32)
        await self.csr_write("LE_ON", engine_reg(WRAP, "CTRL"), CTRL_EN)
        await self.csr_read("LE_ON_RB", engine_reg(WRAP, "CTRL"), expected=CTRL_EN)

    async def _write_len(self, label: str, slot: int, length: int) -> None:
        if length == 0:
            assert slot not in self.pending, (
                f"[{label}]: software zero write to pending slot {slot}"
            )
        else:
            self.pending.add(slot)
        await self.csr_write(f"LOG_LEN_{label}_S{slot}", self.elements[slot].addr, length)

    async def _read_serving(self, label: str, first_byte: int) -> tuple[int, int]:
        """LOG_CTRL.LOG_LEN of the slot whose message `first_byte` opened; must still hold 16."""
        slot = first_byte >> 4
        value = (
            await self.csr_read(f"LOG_CTRL_{label}_S{slot}", self.elements[slot].addr)
        ) & LOG_LEN
        assert value == _MSG_LEN, (
            f"[{label}]: LOG_CTRL[{slot}] reads {value} while its {_MSG_LEN}-byte message is "
            f"arriving; the submitted length must hold until the message completes"
        )
        return slot, value

    async def _drain_count(self, label: str, expected: int, on_first=None) -> list[int]:
        """Read `expected` bytes; after byte `_MID_BYTE` of the first message read its slot's
        LOG_CTRL and require 16."""
        lsr = uart_reg(WRAP, "LSR")
        rbr = uart_reg(WRAP, "RBR")
        received: list[int] = []
        for _ in range(expected * _RX_POLLS_PER_BYTE):
            status = await self.csr_read(f"LSR_{label}", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"[{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its overrun, parity, "
                f"framing and break bits after {len(received)} byte(s)"
            )
            if status & LSR_DR:
                byte = await self.csr_read(f"RBR_{label}", rbr)
                received.append(byte & RBR_DATA)
                if len(received) == 1 and on_first is not None:
                    await on_first(received[0])
                if len(received) == _MID_BYTE:
                    self.mid_reads[label] = await self._read_serving(f"{label}_MID", received[0])
                if len(received) == expected:
                    return received
        raise AssertionError(
            f"[{label}]: {len(received)} of {expected} bytes reached RBR within "
            f"{expected * _RX_POLLS_PER_BYTE} LSR reads"
        )

    async def _idle_rule(self, label: str) -> list[int]:
        """Bytes that arrive before the receiver has been idle for `_IDLE_POLLS` polls."""
        lsr = uart_reg(WRAP, "LSR")
        rbr = uart_reg(WRAP, "RBR")
        extra: list[int] = []
        idle_run = 0
        for _ in range(_IDLE_POLLS * _RX_POLLS_PER_BYTE):
            status = await self.csr_read(f"LSR_IDLE_{label}", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"[{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in the idle rule"
            )
            if status & LSR_DR:
                extra.append((await self.csr_read(f"RBR_IDLE_{label}", rbr)) & RBR_DATA)
                idle_run = 0
            elif status & LSR_TEMT:
                idle_run += 1
                if idle_run >= _IDLE_POLLS:
                    return extra
            else:
                idle_run = 0
        raise AssertionError(f"[{label}]: the receiver never went idle after {len(extra)} byte(s)")

    async def _poll_clear(self, label: str, slots: tuple[int, ...]) -> dict[int, int]:
        polls: dict[int, int] = {}
        for slot in slots:
            value = None
            for count in range(1, _HWCLR_POLLS + 1):
                value = (
                    await self.csr_read(f"LOG_CTRL_{label}_S{slot}", self.elements[slot].addr)
                ) & LOG_LEN
                assert value in (0, _MSG_LEN), (
                    f"[{label}]: LOG_CTRL[{slot}] reads {value} while {_MSG_LEN} was submitted"
                )
                if value == 0:
                    polls[slot] = count
                    self.pending.discard(slot)
                    break
            assert value == 0, (
                f"[{label}]: LOG_CTRL[{slot}] still reads {_MSG_LEN} after {_HWCLR_POLLS} reads "
                f"following the idle receiver"
            )
        self.clear_polls[label] = polls
        return polls

    async def _intr(self, label: str) -> int:
        status = (
            await self.csr_read(f"INTR_{label}", engine_reg(WRAP, "INTR_STATUS"))
        ) & INTR_STATUS_MASK
        assert status == 0, f"[{label}]: INTR_STATUS bits 0x{status:x} after the wave"
        return status

    async def _finish_wave(
        self, label: str, stream: list[int], slots: tuple[int, ...]
    ) -> list[int]:
        extra = await self._idle_rule(label)
        assert extra == [], f"[{label}]: {len(extra)} byte(s) after the last message {_hex(extra)}"
        await self._poll_clear(label, slots)
        await self._intr(label)
        order = _decode(label, stream)
        self.orders[label] = order
        return order

    # -- steps -----------------------------------------------------------

    async def _s2(self) -> None:
        for slot in _WAVE_A_ZERO:
            await self._write_len("A", slot, 0)
        for slot in _WAVE_A_SLOTS:
            await self._write_len("A", slot, _MSG_LEN)
        for slot in _WAVE_A_SLOTS:
            self.hold_reads[slot] = (
                await self.csr_read(f"LOG_CTRL_A_EARLY_S{slot}", self.elements[slot].addr)
            ) & LOG_LEN
        stream = await self._drain_count("A", len(_WAVE_A_SLOTS) * _MSG_LEN)
        order = await self._finish_wave("A", stream, _WAVE_A_SLOTS)
        others = tuple(s for s in range(NUM_LOG_ENTRIES) if s not in _WAVE_A_SLOTS)
        for slot in others:
            self.wave_a_zero_reads[slot] = (
                await self.csr_read(f"LOG_CTRL_A_OTHER_S{slot}", self.elements[slot].addr)
            ) & LOG_LEN
        self._mark("S2")

        stray = [b for b in stream if (b >> 4) not in _WAVE_A_SLOTS]
        assert stray == [], f"wave A delivered bytes of other slots {_hex(stray)}"
        assert sorted(order) == list(_WAVE_A_SLOTS), f"wave A served slots {order}"
        assert all(v == 0 for v in self.wave_a_zero_reads.values()), (
            f"never-written entries read {self.wave_a_zero_reads}"
        )
        self._chk(
            "S2",
            "CHK-LOGENG-RR-ZERO-SKIPPED",
            f"wave A stream of {len(stream)} bytes carries only slot tags "
            f"{sorted({b >> 4 for b in stream})} inside {list(_WAVE_A_SLOTS)}; entries "
            f"{list(others)} read LOG_LEN "
            f"{[self.wave_a_zero_reads[s] for s in others]} after the wave",
        )
        zero_bytes = [b for b in stream if (b >> 4) in _WAVE_A_ZERO]
        assert zero_bytes == [], f"slot 0 or 11 bytes delivered {_hex(zero_bytes)}"
        self._chk(
            "S2",
            "CHK-LOGENG-LEN-ZERO-NOT-PENDING",
            f"LOG_LEN 0 written to entries {list(_WAVE_A_ZERO)} delivered no byte tagged slot "
            f"0 or 11 in {len(stream)} bytes and both read "
            f"{[self.wave_a_zero_reads[s] for s in _WAVE_A_ZERO]} after the wave",
        )
        early = [self.hold_reads[s] for s in _WAVE_A_SLOTS]
        assert all(v in (0, _MSG_LEN) for v in early), f"LOG_LEN reads during wave A {early}"
        assert _MSG_LEN in early, f"no LOG_CTRL read during wave A returned {_MSG_LEN}: {early}"
        mid_slot, mid_value = self.mid_reads["A"]
        assert mid_value == _MSG_LEN, f"mid-message LOG_CTRL[{mid_slot}] read {mid_value}"
        self._chk(
            "S2",
            "CHK-LOGENG-LEN-HOLD-SUBMITTED",
            f"LOG_CTRL reads of entries {list(_WAVE_A_SLOTS)} right after the writes returned "
            f"{early}, each {_MSG_LEN} or 0 and {early.count(_MSG_LEN)} of them {_MSG_LEN}; "
            f"LOG_CTRL[{mid_slot}] read {mid_value} after byte {_MID_BYTE} of its message left "
            f"RBR (a remaining-byte counter reads at most {_MSG_LEN - _MID_BYTE} there); after "
            f"the wave each read 0 in {[self.clear_polls['A'][s] for s in _WAVE_A_SLOTS]} read(s)",
        )

    async def _s3(self) -> None:
        for slot in _WAVE_B_SLOTS:
            await self._write_len("B", slot, _MSG_LEN)
        stream = await self._drain_count("B", len(_WAVE_B_SLOTS) * _MSG_LEN)
        order = await self._finish_wave("B", stream, _WAVE_B_SLOTS)
        self._mark("S3")
        assert len(stream) == NUM_LOG_ENTRIES * _MSG_LEN, f"wave B stream {len(stream)} bytes"
        assert sorted(order) == list(_WAVE_B_SLOTS), (
            f"wave B served {order}, each of {list(_WAVE_B_SLOTS)} once is required"
        )
        self._chk(
            "S3",
            "CHK-LOGENG-RR-EXACTLY-ONCE",
            f"wave B stream of {len(stream)} bytes decodes into {len(order)} messages, slots "
            f"{sorted(order)} each exactly once, no byte after the last message under the idle "
            f"rule, all {NUM_LOG_ENTRIES} entries read 0",
        )

    async def _s4(self) -> None:
        async def second_wave(first_byte: int) -> None:
            self.in_flight_read = await self._read_serving("C_FIRST", first_byte)
            for slot in _WAVE_C_LATE:
                await self._write_len("C", slot, _MSG_LEN)

        for slot in _WAVE_C_FIRST:
            await self._write_len("C", slot, _MSG_LEN)
        stream = await self._drain_count("C", len(_WAVE_C_SLOTS) * _MSG_LEN, on_first=second_wave)
        order = await self._finish_wave("C", stream, _WAVE_C_SLOTS)
        self._mark("S4")

        assert sorted(order) == sorted(_WAVE_C_SLOTS), (
            f"wave C served {order}, each of {sorted(_WAVE_C_SLOTS)} once is required"
        )
        first_slot = order[0]
        assert first_slot in _WAVE_C_FIRST, (
            f"the first message of wave C came from slot {first_slot}, written after the first byte"
        )
        starts = {slot: order.index(slot) * _MSG_LEN for slot in _WAVE_C_LATE}
        assert all(pos >= _MSG_LEN for pos in starts.values()), (
            f"slots {list(_WAVE_C_LATE)} started at stream positions {starts}"
        )
        self.first_message_slot = first_slot
        flight_slot, flight_value = self.in_flight_read
        assert (flight_slot, flight_value) == (first_slot, _MSG_LEN), (
            f"LOG_CTRL[{flight_slot}] read {flight_value} before the late writes; the first "
            f"message is slot {first_slot}"
        )
        self._chk(
            "S4",
            "CHK-LOGENG-RR-IN-FLIGHT",
            f"wave C: the first message is slot {first_slot}, stream bytes 0 to {_MSG_LEN - 1} "
            f"all tagged slot {first_slot}; LOG_CTRL[{flight_slot}] read {flight_value} at the "
            f"first byte, before the late writes, so that message was in flight at the engine; "
            f"slots {list(_WAVE_C_LATE)}, written then, each delivered once and started at "
            f"stream positions {starts}, none before {_MSG_LEN}",
        )
        decoded = {k: len(v) for k, v in self.orders.items()}
        self._chk(
            "S4",
            "CHK-LOGENG-RR-ATOMIC",
            f"waves A, B and C decoded into whole {_MSG_LEN}-byte messages, bytes "
            f"(slot << 4) | 0 to (slot << 4) | {_MSG_LEN - 1} in order with no byte of another "
            f"slot inside a message: messages per wave {decoded}; INTR_STATUS bits 0 and 4 "
            f"read 0 after each wave",
        )
        cleared = {w: sorted(self.clear_polls[w].items()) for w in sorted(self.clear_polls)}
        mid = {w: self.mid_reads[w] for w in sorted(self.mid_reads)}
        self._chk(
            "S4",
            "CHK-LOGENG-LEN-HWCLEAR",
            f"every entry written {_MSG_LEN} in waves A, B and C read LOG_LEN 0 within "
            f"{_HWCLR_POLLS} LOG_CTRL reads after its message arrived (slot, reads): {cleared}; "
            f"mid-message reads after byte {_MID_BYTE} (slot, value) per wave: {mid}, each "
            f"{_MSG_LEN}; no zero write reached a pending entry and the clear poll never read LSR",
        )
        self._chk(
            "S4",
            "CHK-LOGENG-RR-ORDER-MEASURED",
            "measured order="
            + "; ".join(f"wave {w} {self.orders[w]}" for w in sorted(self.orders))
            + " (measured, not compared)",
        )

    async def _s5(self) -> None:
        await self.csr_write("LE_OFF_FINAL", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_read("LE_OFF_RB", engine_reg(WRAP, "CTRL"), expected=0)
        await self.csr_write("WRITE_ADDR_CLR", engine_reg(WRAP, "LOG_WRITE_ADDR"), 0)
        await self.csr_write("REGION_SIZE_CLR", engine_reg(WRAP, "LOG_REGION_SIZE"), 0)
        region_addr = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write("REGION_ADDR_LO_CLR", region_addr, 0)
        await self.csr_write("REGION_ADDR_HI_CLR", region_addr + 4, 0)
        await restore_uart(self, WRAP)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S5")
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but this "
            f"sequence issued {self.accesses}"
        )
        self._nonvac()

    async def body(self) -> None:
        assert smc_addr(WRAP_NUM) > WRAP, "the generated map has no wrapper 0"
        self.elements = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, WRAP)
        assert len(self.elements) == NUM_LOG_ENTRIES, (
            f"the generated map declares {len(self.elements)} LOG_CTRL elements"
        )
        await self._setup()
        self._mark("S1")
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
