# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A real log-engine transfer on every uart_log_engine_wrap instance.

This is the software flow `hw/ip/uart/log_engine/doc/programming.adoc` writes
out, driven over SEP_IN AXI instead of from firmware: place the log bytes in
memory the engine can fetch, point LOG_REGION_ADDR at them, point
LOG_WRITE_ADDR at the wrapper's own UART transmit holding register, put that
UART in `MCR.LOOP` so the bytes come back through its own receiver, enable the
engine, and write a length into several LOG_CTRL elements at once.

What the bench then compares is the byte stream it reads out of RBR against the
bytes it wrote into memory, the LOG_CTRL elements hardware cleared, and an
INTR_STATUS that stayed clear.

Each byte carries its own source: the log region is divided into equal slots,
one per LOG_CTRL element (`architecture.adoc`, Log Fetch FSM: the fetch address
is `log_region_addr + (log_region_size/16) * log_index + word_offset`), and the
byte at offset `j` of the slot driven by element `e` of wrapper `w` is
`((w * ENTRIES + e) << 3) | j`. Every byte of the run is therefore distinct, so
a byte identifies the wrapper, the element and its position, and a stream that
carried a neighbour's slot, repeated a byte or dropped one fails.

The order the arbiter interleaves the elements in is not predicted. The doc
fixes round-robin selection among elements with non-zero lengths and nothing
more, so the check is that each element's own bytes arrive in increasing slot
offset, that every byte of every driven element arrives exactly once, and that
nothing else arrives. Within one element the order is the fetch order the same
section fixes -- ascending word offset, and ascending byte lane inside the
64-bit word the AXI little-endian lane mapping puts at ascending addresses.

Only the first `ENTRIES` elements of each wrapper are driven, each with a log
that fills its whole slot. `log_engine.rdl` sizes a slot as the region size
divided over the sixteen LOG_CTRL elements and rounds it down to complete
8-byte fetch beats, so a slot of this region is two beats and every element's
fetch has to come back for a second beat before it is done. Nothing writes a
pending LOG_CTRL length back to 0: a non-zero length is a request the arbiter
is entitled to see held until it grants, and the only clearing the design
allows is the hardware one this leaf waits for.

The UART is left at the engine's disposal and put back: the wrapper's pad-mux
enable, the divisor latches, LCR, MCR and the FIFO control are all restored,
and `MCR.LOOP` keeps the bytes inside the UART (`uart_16550_main.rdl`: "the
transmitter is internally connected to the receiver. The `tx_o` output is set
to `1`"), so no pad carries them.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import SPM_MEMORY_BASE, SPM_MEMORY_SIZE, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    ARM_UART_ACCESSES,
    CTRL_EN,
    INTR_STATUS_MASK,
    LOG_CTRL_PATH,
    LOG_CTRL_PY,
    LOG_LEN,
    LSR_DR,
    LSR_LINE_ERRORS,
    NUM_LOG_ENTRIES,
    RBR_DATA,
    RESTORE_UART_ACCESSES,
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

# log_engine.rdl gives LOG_CTRL 16 elements and architecture.adoc divides the
# region equally among them, so the region size fixes the slot size.
_REGION_SIZE = 0x100
_SLOT_BYTES = _REGION_SIZE // NUM_LOG_ENTRIES
# Elements driven per wrapper. More than one, so the arbiter has to grant more
# than one requester before the run can finish.
_ENTRIES = 4
# Bytes per element: the whole capacity of a slot, which is two 64-bit fetch
# beats, so each element's fetch takes a second beat before it is done.
_LOG_BYTES = _SLOT_BYTES
_WORDS_PER_LOG = _LOG_BYTES // 8

_LOG_BUFFER_OFFSET = 0x40000

# SEP_IN accesses one wrapper needs whatever the polling costs: the log words
# written and read back (2 per element), the UART and engine setup (10 each),
# the idle read and the trigger write of every element (2 each), at least one
# LSR read and one RBR read per byte, at least one LOG_CTRL read per element,
# the quiet LSR read and the final INTR_STATUS read, and the 13-access restore.
_MIN_ACCESSES_PER_WRAP = (
    2 * _ENTRIES * _WORDS_PER_LOG
    + ARM_UART_ACCESSES
    + 10
    + 2 * _ENTRIES
    + 2 * _ENTRIES * _LOG_BYTES
    + _ENTRIES
    + 2
    + 5
    + RESTORE_UART_ACCESSES
)

# Reads of LSR allowed per expected byte before the transfer is declared stuck.
# The bound is generous so a slow build cannot flake; expiry is a FAILURE.
_RX_POLLS_PER_BYTE = 400
# Reads of one LOG_CTRL element allowed before its hardware clear is declared
# not to have happened.
_HWCLR_POLLS = 64


#: Bits of a tagged byte that carry the slot offset. The rest carry the index
#: of the (wrapper, element) pair, so every byte of the run is distinct.
_OFFSET_BITS = _LOG_BYTES.bit_length() - 1


def _tag(wrap: int, entry: int, offset: int) -> int:
    """The byte at `offset` in the slot element `entry` of wrapper `wrap` drives."""
    return (((wrap * _ENTRIES) + entry) << _OFFSET_BITS) | offset


def _untag(byte: int) -> tuple[int, int, int]:
    """The wrapper, element and slot offset a received byte names."""
    index = byte >> _OFFSET_BITS
    return index // _ENTRIES, index % _ENTRIES, byte & ((1 << _OFFSET_BITS) - 1)


class smc_log_engine_transfer_test_seq(SmcCsrSeq):
    """Run a real log transfer through every wrapper's engine and UART."""

    def __init__(self, name: str = "smc_log_engine_transfer_test_seq") -> None:
        super().__init__(name)
        self.transfers = 0
        self.bytes_checked = 0
        self.hwclr_elements = 0

    # -- addressing ------------------------------------------------------

    @staticmethod
    def _buffer(wrap: int) -> int:
        base = SPM_MEMORY_BASE + _LOG_BUFFER_OFFSET + wrap * _REGION_SIZE
        assert base + _REGION_SIZE <= SPM_MEMORY_BASE + SPM_MEMORY_SIZE, (
            f"the log region of wrapper {wrap} at 0x{base:08x} runs past the end of the "
            f"SPM window the generated map declares"
        )
        return base

    # -- legs ------------------------------------------------------------

    async def _load_region(self, wrap: int, slot_bytes: int) -> dict[int, list[int]]:
        """Write each driven element's log into its own slot, and return them."""
        base = self._buffer(wrap)
        logs: dict[int, list[int]] = {}
        for entry in range(_ENTRIES):
            logs[entry] = [_tag(wrap, entry, offset) for offset in range(_LOG_BYTES)]
        for entry in range(_ENTRIES):
            slot = base + entry * slot_bytes
            for word in range(0, _LOG_BYTES, 8):
                value = 0
                for lane in range(8):
                    value |= logs[entry][word + lane] << (8 * lane)
                await self.csr_write(
                    f"WRAP{wrap}_SLOT{entry}_W{word // 8}", slot + word, value, length=8
                )
        for entry in range(_ENTRIES):
            slot = base + entry * slot_bytes
            for word in range(0, _LOG_BYTES, 8):
                value = 0
                for lane in range(8):
                    value |= logs[entry][word + lane] << (8 * lane)
                await self.csr_read(
                    f"WRAP{wrap}_SLOT{entry}_W{word // 8}_RB",
                    slot + word,
                    expected=value,
                    length=8,
                )
        return logs

    async def _arm_engine(self, wrap: int) -> None:
        base = self._buffer(wrap)
        await self.csr_write(f"WRAP{wrap}_LE_OFF", engine_reg(wrap, "CTRL"), 0)
        await self.csr_write(
            f"WRAP{wrap}_REGION_SIZE", engine_reg(wrap, "LOG_REGION_SIZE"), _REGION_SIZE
        )
        region_addr = engine_reg(wrap, "LOG_REGION_ADDR")
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_LO", region_addr, base & 0xFFFF_FFFF)
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_HI", region_addr + 4, base >> 32)
        await self.csr_write(
            f"WRAP{wrap}_WRITE_ADDR",
            engine_reg(wrap, "LOG_WRITE_ADDR"),
            uart_base(wrap) + THR_OFFSET,
        )
        await self.csr_write(
            f"WRAP{wrap}_INTR_CLEAR", engine_reg(wrap, "INTR_STATUS"), INTR_STATUS_MASK
        )
        await self.csr_write(f"WRAP{wrap}_INTR_ENABLE", engine_reg(wrap, "INTR_ENABLE"), 0)
        status = await self.csr_read(
            f"WRAP{wrap}_INTR_IDLE", engine_reg(wrap, "INTR_STATUS"), expected=0
        )
        assert status & INTR_STATUS_MASK == 0, (
            f"wrapper {wrap}: INTR_STATUS still reports 0x{status & INTR_STATUS_MASK:x} "
            f"after the clearing write, so a later error could not be told from a stale one"
        )
        await self.csr_write(f"WRAP{wrap}_LE_ON", engine_reg(wrap, "CTRL"), CTRL_EN)
        await self.csr_read(f"WRAP{wrap}_LE_ON_RB", engine_reg(wrap, "CTRL"), expected=CTRL_EN)

    async def _drain(self, wrap: int, expected_bytes: int) -> list[int]:
        lsr = uart_reg(wrap, "LSR")
        rbr = uart_reg(wrap, "RBR")
        received: list[int] = []
        budget = expected_bytes * _RX_POLLS_PER_BYTE
        while len(received) < expected_bytes and budget > 0:
            budget -= 1
            status = await self.csr_read(f"WRAP{wrap}_LSR", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"wrapper {wrap}: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its "
                f"overrun, parity, framing and break bits after {len(received)} byte(s), so "
                f"the receiver did not take the log intact"
            )
            if status & LSR_DR:
                byte = await self.csr_read(f"WRAP{wrap}_RBR", rbr)
                received.append(byte & RBR_DATA)
        assert len(received) == expected_bytes, (
            f"wrapper {wrap}: {len(received)} of {expected_bytes} log byte(s) reached the "
            f"receiver within {expected_bytes * _RX_POLLS_PER_BYTE} LSR reads; the engine "
            f"never finished the transfer"
        )
        return received

    def _check_stream(self, wrap: int, received: list[int], logs: dict[int, list[int]]) -> None:
        per_entry: dict[int, list[int]] = {entry: [] for entry in logs}
        for position, byte in enumerate(received):
            source, entry, offset = _untag(byte)
            assert source == wrap and entry in logs and offset < _LOG_BYTES, (
                f"wrapper {wrap}: byte {position} of the stream is 0x{byte:02x}, which names "
                f"wrapper {source} element {entry} offset {offset}; no log this leaf wrote "
                f"carries it"
            )
            per_entry[entry].append(byte)
        for entry, payload in logs.items():
            assert per_entry[entry] == payload, (
                f"wrapper {wrap} element {entry}: its bytes arrived as "
                f"{[f'0x{b:02x}' for b in per_entry[entry]]}, the log written into its slot "
                f"is {[f'0x{b:02x}' for b in payload]}"
            )
            self.bytes_checked += len(payload)

    async def _await_hwclr(self, wrap: int, elements) -> None:
        for entry in range(_ENTRIES):
            inst = elements[entry]
            remaining = None
            for _ in range(_HWCLR_POLLS):
                remaining = await self.csr_read(f"WRAP{wrap}_LOG_CTRL{entry}_HWCLR", inst.addr)
                remaining &= LOG_LEN
                if remaining == 0:
                    break
            assert remaining == 0, (
                f"wrapper {wrap} LOG_CTRL[{entry}] @ 0x{inst.addr:08x} still reports "
                f"{remaining} byte(s) outstanding after the whole log arrived, so hardware "
                f"did not clear the length the transfer completed"
            )
            self.hwclr_elements += 1

    async def _restore(self, wrap: int) -> None:
        await self.csr_write(f"WRAP{wrap}_LE_OFF_FINAL", engine_reg(wrap, "CTRL"), 0)
        await self.csr_read(f"WRAP{wrap}_LE_OFF_RB", engine_reg(wrap, "CTRL"), expected=0)
        await self.csr_write(f"WRAP{wrap}_WRITE_ADDR_CLR", engine_reg(wrap, "LOG_WRITE_ADDR"), 0)
        await self.csr_write(f"WRAP{wrap}_REGION_SIZE_CLR", engine_reg(wrap, "LOG_REGION_SIZE"), 0)
        region_addr = engine_reg(wrap, "LOG_REGION_ADDR")
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_LO_CLR", region_addr, 0)
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_HI_CLR", region_addr + 4, 0)
        await restore_uart(self, wrap)

    # -- body ------------------------------------------------------------

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        wraps = smc_addr(WRAP_NUM)
        elements = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, 0)
        slot_bytes = _REGION_SIZE // len(elements)
        assert _ENTRIES <= len(elements), (
            f"this leaf drives {_ENTRIES} elements, the generated map declares {len(elements)}"
        )
        assert slot_bytes >= _LOG_BYTES and _LOG_BYTES % 8 == 0, (
            f"a log of {_LOG_BYTES} bytes has to be whole 64-bit fetch beats and fit a slot "
            f"of {slot_bytes} bytes"
        )
        expected_bytes = _ENTRIES * _LOG_BYTES
        tags = {
            _tag(w, e, o) for w in range(wraps) for e in range(_ENTRIES) for o in range(_LOG_BYTES)
        }
        assert len(tags) == wraps * expected_bytes, (
            "the byte tags of this run are not pairwise distinct, so a received byte would "
            "not name its wrapper, element and offset"
        )

        for wrap in range(wraps):
            wrap_elements = array_reg_instances(
                LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, wrap
            )
            logs = await self._load_region(wrap, slot_bytes)
            await arm_uart(self, wrap)
            await self._arm_engine(wrap)

            for entry in range(_ENTRIES):
                await self.csr_read(
                    f"WRAP{wrap}_LOG_CTRL{entry}_IDLE", wrap_elements[entry].addr, expected=0
                )
            for entry in range(_ENTRIES):
                await self.csr_write(
                    f"WRAP{wrap}_LOG_CTRL{entry}_GO", wrap_elements[entry].addr, _LOG_BYTES
                )

            received = await self._drain(wrap, expected_bytes)
            self._check_stream(wrap, received, logs)
            await self._await_hwclr(wrap, wrap_elements)

            quiet = await self.csr_read(f"WRAP{wrap}_LSR_QUIET", uart_reg(wrap, "LSR"))
            assert quiet & LSR_DR == 0, (
                f"wrapper {wrap}: the receiver still reports data after the whole log was "
                f"read out, so the engine sent more bytes than the logs it was given"
            )
            status = await self.csr_read(
                f"WRAP{wrap}_INTR_FINAL", engine_reg(wrap, "INTR_STATUS"), expected=0
            )
            assert status & INTR_STATUS_MASK == 0, (
                f"wrapper {wrap}: INTR_STATUS reports 0x{status & INTR_STATUS_MASK:x} after "
                f"the transfer, so the engine hit a fetch or a write error"
            )
            await self._restore(wrap)
            self.transfers += 1

        assert self.transfers == wraps, f"{self.transfers} of {wraps} wrappers completed a transfer"
        assert self.bytes_checked == wraps * expected_bytes, (
            f"{self.bytes_checked} bytes compared, {wraps * expected_bytes} were written"
        )
        assert self.hwclr_elements == wraps * _ENTRIES, (
            f"{self.hwclr_elements} of {wraps * _ENTRIES} elements were seen cleared"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "no scoreboard on this sequence's env, so the CSR traffic cannot be "
            "corroborated independently of the sequence's own counter"
        )
        # The drain loop makes the access count depend on how many LSR reads the
        # baud rate needed, so the gate is a floor rather than an exact count.
        floor = wraps * _MIN_ACCESSES_PER_WRAP
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses, a run that transferred "
            f"{wraps * expected_bytes} bytes cannot have issued fewer than {floor}"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-BYTES: %d log bytes reached the receiver of %d "
            "wrapper(s) through a real engine transfer -- %d elements per wrapper fetched "
            "from their own slot of the SPM log region and wrote the wrapper's own THR -- "
            "and every element's bytes arrived in slot order, exactly once, with no byte "
            "from any other element or wrapper",
            self.bytes_checked,
            self.transfers,
            _ENTRIES,
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-HWCLR: all %d driven LOG_CTRL elements read a length "
            "of 0 after their log arrived; nothing in this leaf wrote a pending length "
            "back, so the clear is the hardware completion the RDL declares",
            self.hwclr_elements,
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-TRANSFER-CLEAN: across %d wrapper(s) every LSR read during the "
            "transfer showed no overrun, parity, framing or break error, the receiver went "
            "quiet after the last expected byte, and INTR_STATUS read clear, so the engine "
            "hit neither a fetch nor a write error and sent nothing it was not asked to; "
            "%d SEP_IN accesses, all checked by the scoreboard",
            self.transfers,
            self.accesses,
        )
