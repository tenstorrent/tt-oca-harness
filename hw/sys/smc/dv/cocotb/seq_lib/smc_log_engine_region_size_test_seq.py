# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Log-engine slot start, capacity clamp, zero capacity and resubmission over region sizes.

`smc_log_engine_transfer_test` runs one region size. This leaf runs wrapper 0 at the other
sizes, one message at a time, and reads each delivered byte stream out of RBR in MCR.LOOP.

`architecture.adoc` ("Memory Slots and Lengths") fixes slot `i` at `LOG_REGION_ADDR +
(LOG_REGION_SIZE / 16) * i` for a size aligned to 128 bytes, a slot capacity of the slot size
truncated to a multiple of eight for any other size, a clamp of a longer `LOG_LEN` to that
capacity, and completion of a zero-capacity slot without a transfer. "Arbitration and Data
Transfer" fixes the byte order: increasing address, least significant byte first in each word.

The window holds `f(a)` at window offset `a`: the offset itself below 0x100 and the offset XOR
0xA5 from 0x100 on, so a byte names the offset it was fetched from and a start off by 0x100
fails. Above 0x100 consecutive offsets do not carry consecutive bytes, so the consecutive-offset
compare of the unaligned legs holds only for messages that end at or below offset 0x100; the
sizes and slots of those legs keep every message there (size 271, slot 15 ends exactly at 0x100)
and the leaf asserts the bound on each delivered message. Legs:

* size 0x80, slots 0 to 15, 8 bytes each: the delivered bytes are `f(8*i + j)`;
* size 0x200, slots 0, 7, 15 and a second delivery on slot 0;
* sizes 135, 143, 144 and 271: lengths 8, capacity + 8 and the largest multiple of eight the
  field holds (0xFFF8) deliver exactly the capacity (or 8); the slot start of the unaligned
  sizes is measured, and only the contiguity of the delivered offsets is compared;
* size 127: the capacity is 0, so the length clears and no byte arrives; the delivering legs of
  this leaf are the positive control on the same wiring;
* lengths 9 and 7 at size 0x200: the delivered count and bytes are measured, not compared; the
  hardware clear of LOG_LEN is compared as in every other leg.

An idle receiver is TEMT = 1 and DR = 0 on a run of consecutive LSR polls longer than a
character time. A pending length is never written back to 0: each is replaced only by the next
message after hardware cleared it.
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
_WINDOW_BYTES = 0x200
_HIGH_TAG = 0xA5

_SIZE_MIN = 0x80
_SIZE_MID = 0x200
_SIZE_ZERO_CAPACITY = 127
_UNALIGNED_SIZES = (135, 143, 144, 271)
_MIN_SLOTS = tuple(range(NUM_LOG_ENTRIES))
_MID_SLOTS = (0, 7, 15)
_UNALIGNED_SLOTS = (0, 1, 15)
_MIN_LEN = 8
_MID_LEN = 0x20
_NOT_MULT8_LENS = (9, 7)
# The largest multiple of eight LOG_LEN[15:0] holds: 0xFFF8.
_MAX_LEN = LOG_LEN & ~0x7
# Window offset the unaligned-size messages must end at or below: the tag names the offset only
# there (see the module docstring).
_TAG_IS_OFFSET_END = 0x100

# Polls of LSR allowed per expected byte; expiry is a failure.
_RX_POLLS_PER_BYTE = 400
# Reads of one LOG_CTRL element allowed before its hardware clear is declared absent.
_HWCLR_POLLS = 64
# Consecutive polls with TEMT = 1 and DR = 0 that make the receiver idle; a character takes far
# fewer reads than this to arrive.
_IDLE_POLLS = 32

STEP_ORDER = ("S1", "S2", "S3", "S4", "S5", "S6", "S7")
CHK_ORDER = (
    ("S2", "CHK-LOGENG-REGION-SLOT-START-MIN"),
    ("S3", "CHK-LOGENG-REGION-SLOT-START-MID"),
    ("S3", "CHK-LOGENG-REGION-RESUBMIT"),
    ("S3", "CHK-LOGENG-REGION-BYTE-ORDER"),
    ("S4", "CHK-LOGENG-REGION-UNALIGNED-CAPACITY"),
    ("S4", "CHK-LOGENG-REGION-UNALIGNED-BELOW-CAP"),
    ("S4", "CHK-LOGENG-REGION-UNALIGNED-START-MEASURED"),
    ("S5", "CHK-LOGENG-REGION-ZERO-CAPACITY"),
    ("S6", "CHK-LOGENG-REGION-LEN-NOT-MULT8-MEASURED"),
)


def _tag(offset: int) -> int:
    """Byte stored at window offset `offset`."""
    return (offset & 0xFF) ^ (_HIGH_TAG if offset >= 0x100 else 0)


def _capacity(size: int) -> int:
    """Slot capacity of `size`: the slot size truncated to a multiple of eight."""
    return (size // NUM_LOG_ENTRIES) // 8 * 8


def _hex(values: list[int]) -> str:
    return "[" + " ".join(f"{v:02x}" for v in values) + "]"


class smc_log_engine_region_size_test_seq(SmcCsrSeq):
    """Drive wrapper 0's log engine over several region sizes and read the stream back."""

    def __init__(self, name: str = "smc_log_engine_region_size_test_seq") -> None:
        super().__init__(name)
        self.steps: list[tuple[str, int]] = []
        self.chk_steps: list[tuple[str, str]] = []
        self.elements = []
        self.window = 0
        self.messages = 0
        self.byte_order_checked = 0

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
            "CHK-NONVAC: ordered fence S1 < S2 < S3 < S4 < S5 < S6 < S7, step stamps strictly "
            "increasing, each checker line after its own step; checker lines %s; stamps %s",
            ",".join(c for _, c in self.chk_steps),
            ",".join(f"{s}={ps}" for s, ps in self.steps),
        )

    # -- register legs ---------------------------------------------------

    async def _load_window(self) -> None:
        self.window = SPM_MEMORY_BASE + _WINDOW_OFFSET
        assert self.window % 8 == 0 and (
            self.window + _WINDOW_BYTES <= SPM_MEMORY_BASE + SPM_MEMORY_SIZE
        ), f"log window 0x{self.window:08x} is unaligned or runs past the SPM window"
        words = []
        for word in range(0, _WINDOW_BYTES, 8):
            value = 0
            for lane in range(8):
                value |= _tag(word + lane) << (8 * lane)
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
        await self.csr_write(
            "WRITE_ADDR", engine_reg(WRAP, "LOG_WRITE_ADDR"), uart_base(WRAP) + THR_OFFSET
        )
        await self._load_window()
        region_addr = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write("REGION_ADDR_LO", region_addr, self.window & 0xFFFF_FFFF)
        await self.csr_write("REGION_ADDR_HI", region_addr + 4, self.window >> 32)
        await self.csr_write("LE_ON", engine_reg(WRAP, "CTRL"), CTRL_EN)
        await self.csr_read("LE_ON_RB", engine_reg(WRAP, "CTRL"), expected=CTRL_EN)

    async def _set_size(self, size: int) -> None:
        await self.csr_write(f"REGION_SIZE_{size}", engine_reg(WRAP, "LOG_REGION_SIZE"), size)

    async def _drain_until_idle(self, label: str, expected: int) -> list[int]:
        lsr = uart_reg(WRAP, "LSR")
        rbr = uart_reg(WRAP, "RBR")
        received: list[int] = []
        idle_run = 0
        for _ in range((expected + 1) * _RX_POLLS_PER_BYTE):
            status = await self.csr_read(f"LSR_{label}", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"[{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its overrun, parity, "
                f"framing and break bits after {len(received)} byte(s)"
            )
            if status & LSR_DR:
                byte = await self.csr_read(f"RBR_{label}", rbr)
                received.append(byte & RBR_DATA)
                idle_run = 0
            elif status & LSR_TEMT:
                idle_run += 1
                if idle_run >= _IDLE_POLLS:
                    return received
            else:
                idle_run = 0
        raise AssertionError(
            f"[{label}]: the receiver never went idle within "
            f"{(expected + 1) * _RX_POLLS_PER_BYTE} LSR reads after {len(received)} byte(s)"
        )

    async def _message(self, label: str, slot: int, length: int) -> tuple[list[int], int, int]:
        """Write `length` into `slot`, drain to idle, check the clear; return the results."""
        element = self.elements[slot]
        await self.csr_write(f"LOG_LEN_{label}", element.addr, length)
        received = await self._drain_until_idle(label, length)
        cleared = None
        polls = 0
        for polls in range(1, _HWCLR_POLLS + 1):
            cleared = (await self.csr_read(f"LOG_CTRL_{label}", element.addr)) & LOG_LEN
            assert cleared in (0, length), (
                f"[{label}]: LOG_CTRL[{slot}] reads {cleared} while 0x{length:x} was submitted"
            )
            if cleared == 0:
                break
        assert cleared == 0, (
            f"[{label}]: LOG_CTRL[{slot}] still reads 0x{length:x} after {_HWCLR_POLLS} reads "
            f"following the idle receiver"
        )
        status = await self.csr_read(f"INTR_{label}", engine_reg(WRAP, "INTR_STATUS"))
        self.messages += 1
        return received, polls, status & INTR_STATUS_MASK

    # -- steps -----------------------------------------------------------

    async def _s2(self) -> None:
        await self._set_size(_SIZE_MIN)
        stride = _SIZE_MIN // NUM_LOG_ENTRIES
        for slot in _MIN_SLOTS:
            got, _, status = await self._message(f"MIN_S{slot}", slot, _MIN_LEN)
            want = [_tag(stride * slot + j) for j in range(_MIN_LEN)]
            assert got == want, (
                f"size 0x{_SIZE_MIN:x} slot {slot}: delivered {_hex(got)}, slot start "
                f"LOG_REGION_ADDR + {stride * slot} gives {_hex(want)}"
            )
            assert status == 0, f"size 0x{_SIZE_MIN:x} slot {slot}: INTR_STATUS 0x{status:x}"
            self.byte_order_checked += 1
        self._mark("S2")
        self._chk(
            "S2",
            "CHK-LOGENG-REGION-SLOT-START-MIN",
            f"LOG_REGION_SIZE 0x{_SIZE_MIN:x}: all {len(_MIN_SLOTS)} slots delivered 8 bytes "
            f"equal to f(8*i + j), slot stride {stride}, first bytes "
            f"{[f'{_tag(stride * s):02x}' for s in _MIN_SLOTS]}, INTR_STATUS read 0 after each",
        )

    async def _s3(self) -> None:
        await self._set_size(_SIZE_MID)
        stride = _SIZE_MID // NUM_LOG_ENTRIES
        firsts = []
        first_zero = None
        for slot in _MID_SLOTS:
            got, _, status = await self._message(f"MID_S{slot}", slot, _MID_LEN)
            want = [_tag(stride * slot + j) for j in range(_MID_LEN)]
            assert got == want, (
                f"size 0x{_SIZE_MID:x} slot {slot}: delivered {_hex(got)}, slot start "
                f"LOG_REGION_ADDR + {stride * slot} gives {_hex(want)}"
            )
            assert status == 0, f"size 0x{_SIZE_MID:x} slot {slot}: INTR_STATUS 0x{status:x}"
            firsts.append(got[0])
            if slot == 0:
                first_zero = got
        self._mark("S3")
        self._chk(
            "S3",
            "CHK-LOGENG-REGION-SLOT-START-MID",
            f"LOG_REGION_SIZE 0x{_SIZE_MID:x}: slots {list(_MID_SLOTS)} first bytes "
            f"{[f'{b:02x}' for b in firsts]} equal f({stride}*i) = "
            f"{[f'{_tag(stride * s):02x}' for s in _MID_SLOTS]}, all {_MID_LEN} bytes of each "
            f"slot equal f({stride}*i + j), INTR_STATUS read 0 after each",
        )
        again, polls, status = await self._message("MID_S0_AGAIN", 0, _MID_LEN)
        assert again == first_zero, (
            f"slot 0 second delivery {_hex(again)} differs from the first {_hex(first_zero)}"
        )
        assert status == 0, f"second delivery: INTR_STATUS 0x{status:x}"
        self._chk(
            "S3",
            "CHK-LOGENG-REGION-RESUBMIT",
            f"slot 0 at 0x{_SIZE_MID:x}: LOG_LEN read 0 after the first delivery, writing "
            f"0x{_MID_LEN:x} again delivered the same {len(again)} bytes {_hex(again)} and "
            f"LOG_LEN read 0 after {polls} read(s)",
        )
        self._chk(
            "S3",
            "CHK-LOGENG-REGION-BYTE-ORDER",
            f"{self.byte_order_checked} slots at 0x{_SIZE_MIN:x} and {len(_MID_SLOTS)} at "
            f"0x{_SIZE_MID:x} each delivered exactly LOG_LEN bytes (8 or {_MID_LEN}) in "
            f"increasing window-offset order and LSR.DR read 0 under the idle rule after them",
        )

    async def _s4(self) -> None:
        capacity_rows = []
        below_rows = []
        start_rows = []
        for size in _UNALIGNED_SIZES:
            cap = _capacity(size)
            await self._set_size(size)
            for slot in _UNALIGNED_SLOTS:
                for kind, length, want_count in (
                    ("BELOW", _MIN_LEN, _MIN_LEN),
                    ("CAP", cap + 8, cap),
                    ("MAX", _MAX_LEN, cap),
                ):
                    label = f"UN{size}_S{slot}_{kind}"
                    got, _, status = await self._message(label, slot, length)
                    row = (size, slot, length, want_count, got, status)
                    (below_rows if kind == "BELOW" else capacity_rows).append(row)
                    if slot in (1, 15):
                        start_rows.append(row)
                    assert got, f"size {size} slot {slot} LOG_LEN 0x{length:x}: no byte delivered"
                    assert all(b - a == 1 for a, b in zip(got, got[1:])), (
                        f"size {size} slot {slot} LOG_LEN 0x{length:x}: delivered {_hex(got)}, "
                        f"not consecutive window offsets"
                    )
                    assert got[0] + len(got) <= _TAG_IS_OFFSET_END, (
                        f"size {size} slot {slot} LOG_LEN 0x{length:x}: message of {len(got)} "
                        f"bytes from offset {got[0]} ends past 0x{_TAG_IS_OFFSET_END:x}, where "
                        f"the window tag no longer names the offset"
                    )
        for size, slot, length, want_count, got, status in capacity_rows:
            assert len(got) == want_count, (
                f"size {size} slot {slot} LOG_LEN 0x{length:x}: delivered {len(got)} bytes, "
                f"capacity is {want_count}"
            )
            assert status == 0, f"size {size} slot {slot}: INTR_STATUS 0x{status:x}"
        self._mark("S4")
        self._chk(
            "S4",
            "CHK-LOGENG-REGION-UNALIGNED-CAPACITY",
            "LOG_LEN = capacity + 8 and 0x%x (the largest multiple of eight the field holds) "
            "delivered exactly the capacity and LOG_LEN read 0 afterwards: %s; INTR_STATUS read 0"
            % (
                _MAX_LEN,
                "; ".join(
                    f"size {s} slot {sl} len 0x{ln:x} -> {len(g)}/{w}"
                    for s, sl, ln, w, g, _ in capacity_rows
                ),
            ),
        )
        for size, slot, length, want_count, got, status in below_rows:
            assert len(got) == _MIN_LEN, (
                f"size {size} slot {slot} LOG_LEN {length}: delivered {len(got)} bytes"
            )
            assert status == 0, f"size {size} slot {slot}: INTR_STATUS 0x{status:x}"
        self._chk(
            "S4",
            "CHK-LOGENG-REGION-UNALIGNED-BELOW-CAP",
            f"LOG_LEN = {_MIN_LEN} delivered exactly {_MIN_LEN} bytes at sizes "
            f"{list(_UNALIGNED_SIZES)} on slots {list(_UNALIGNED_SLOTS)} "
            f"({len(below_rows)} messages), nothing beyond them",
        )
        self._chk(
            "S4",
            "CHK-LOGENG-REGION-UNALIGNED-START-MEASURED",
            "measured first fetched window offset (not compared): "
            + "; ".join(
                f"size {s} slot {sl} len 0x{ln:x} start={g[0]}" for s, sl, ln, _, g, _ in start_rows
            )
            + f"; compared: all {len(below_rows) + len(capacity_rows)} delivered messages are "
            f"consecutive window offsets ending at or below offset 0x{_TAG_IS_OFFSET_END:x}",
        )

    async def _s5(self) -> None:
        await self._set_size(_SIZE_ZERO_CAPACITY)
        assert _capacity(_SIZE_ZERO_CAPACITY) == 0
        rows = []
        for slot in _UNALIGNED_SLOTS:
            got, polls, status = await self._message(f"ZERO_S{slot}", slot, _MIN_LEN)
            assert got == [], f"slot {slot} at size {_SIZE_ZERO_CAPACITY}: delivered {_hex(got)}"
            lsr = await self.csr_read(f"LSR_ZERO_S{slot}", uart_reg(WRAP, "LSR"))
            assert lsr & LSR_DR == 0 and lsr & LSR_TEMT, f"LSR reads 0x{lsr:x} after the idle rule"
            assert status == 0, f"slot {slot} at size {_SIZE_ZERO_CAPACITY}: INTR 0x{status:x}"
            rows.append((slot, polls))
        self._mark("S5")
        self._chk(
            "S5",
            "CHK-LOGENG-REGION-ZERO-CAPACITY",
            f"LOG_REGION_SIZE {_SIZE_ZERO_CAPACITY}: LOG_LEN {_MIN_LEN} on slots "
            f"{list(_UNALIGNED_SLOTS)} read 0 after {[p for _, p in rows]} LOG_CTRL read(s) "
            f"(bound {_HWCLR_POLLS}), no byte reached RBR (LSR.DR = 0, TEMT = 1 under the "
            f"idle rule), INTR_STATUS bits read 0",
        )

    async def _s6(self) -> None:
        await self._set_size(_SIZE_MID)
        rows = []
        for length in _NOT_MULT8_LENS:
            got, polls, status = await self._message(f"NOT8_{length}", 0, length)
            rows.append(
                f"LOG_LEN={length} delivered={len(got)} bytes={_hex(got)} cleared_after_reads="
                f"{polls} intr_status=0x{status:x}"
            )
        self._mark("S6")
        self._chk(
            "S6",
            "CHK-LOGENG-REGION-LEN-NOT-MULT8-MEASURED",
            "measured (count and bytes not compared; the LOG_LEN clear is compared) "
            + "; ".join(rows),
        )

    async def _s7(self) -> None:
        await self.csr_write("LE_OFF_FINAL", engine_reg(WRAP, "CTRL"), 0)
        await self.csr_read("LE_OFF_RB", engine_reg(WRAP, "CTRL"), expected=0)
        await self.csr_write("WRITE_ADDR_CLR", engine_reg(WRAP, "LOG_WRITE_ADDR"), 0)
        await self.csr_write("REGION_SIZE_CLR", engine_reg(WRAP, "LOG_REGION_SIZE"), 0)
        region_addr = engine_reg(WRAP, "LOG_REGION_ADDR")
        await self.csr_write("REGION_ADDR_LO_CLR", region_addr, 0)
        await self.csr_write("REGION_ADDR_HI_CLR", region_addr + 4, 0)
        await restore_uart(self, WRAP)
        await ClockCycles(cocotb.top.clk_smc_i, 2)
        self._mark("S7")
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
        await self._s6()
        await self._s7()
