# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A log-engine transfer halted part-way by clearing the engine enable.

`smc_log_engine_transfer_test` runs transfers to completion. `log_engine.rdl`
gives `CTRL.EN` the other half of the contract: "When cleared, the engine stops
fetching and writing, discards buffered log data and resets transfer progress.
Configuration and pending LOG_LEN values are retained." So clearing it in the
middle of a transfer has to stop the engine where it stands, and no leaf has
asked it to.

Each wrapper gets one log filling its whole slot. The slot is deliberately
large: `log_engine.rdl` sizes it as the region size over the sixteen LOG_CTRL
elements, and this region makes it twice the UART transmit FIFO the
`uart_log_engine_disable_during_xfer` firmware image pins, so the writer cannot
have finished by the time the disable one register access later lands, and it
is several fetch beats deep so the fetch side is still working too.

The three legs are an allow, a deny and an allow again, so the deny cannot pass
on a dead bus:

* the transfer starts and bytes reach the receiver;
* `CTRL.EN` is cleared, and once the UART has gone idle -- transmitter empty
  and no received data, for a run of polls longer than a character time --
  fewer than the whole log has arrived, what did arrive is the head of that
  slot in order, and a second drain finds nothing more;
* a shorter length is put in the same element while the engine is still
  disabled, the engine is re-enabled, and exactly that many bytes arrive from
  the head of the slot and hardware clears the length.

Draining until the UART reports itself idle is how the firmware image measures
the same thing, and it is what lets the halt be checked without knowing how
many bytes the UART had already buffered when the disable landed.

Nothing writes a pending LOG_CTRL length back to 0. The aborted length is
replaced by a shorter non-zero one, so the arbiter request this element holds
never drops before the hardware clear that ends it.
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
    LSR_TEMT,
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

# Region size, and the slot it gives each of the sixteen LOG_CTRL elements.
_REGION_SIZE = 0x400
_SLOT_BYTES = _REGION_SIZE // NUM_LOG_ENTRIES
# The element this leaf drives, and the log it is given: the whole slot.
_ENTRY = 0
_ABORT_BYTES = _SLOT_BYTES
# The shorter length the element is re-triggered with after the engine comes
# back. Two fetch beats, well inside the slot.
_RETRIGGER_BYTES = 16

_LOG_BUFFER_OFFSET = 0x48000

# Polls of LSR that have to show the transmitter empty and no received data
# before the UART counts as idle. A character takes far fewer register reads
# than this to arrive, so a stream still running resets the run.
_IDLE_POLLS = 32
# Polls of LSR allowed per expected byte. The bound is a liveness ceiling:
# expiry is a FAILURE.
_RX_POLLS_PER_BYTE = 400
_HWCLR_POLLS = 400

# SEP_IN accesses one wrapper needs whatever the polling costs: the log words
# written and read back, the UART and engine setup, the idle read and the
# trigger write, one poll to see the transfer start, the disable write, one
# byte and an idle run for the abort drain, an idle run for the second drain,
# the preserved-length read, the re-trigger and re-enable writes, the
# re-triggered bytes and their idle run, one hardware-clear poll, the final
# INTR_STATUS read and the restore.
_WORDS_PER_LOG = _ABORT_BYTES // 8
_MIN_ACCESSES_PER_WRAP = (
    2 * _WORDS_PER_LOG
    + ARM_UART_ACCESSES
    + 10
    + 2
    + 1
    + 1
    + (2 + _IDLE_POLLS)
    + _IDLE_POLLS
    + 1
    + 2
    + (2 * _RETRIGGER_BYTES + _IDLE_POLLS)
    + 1
    + 1
    + 5
    + RESTORE_UART_ACCESSES
)

#: Bits of a tagged byte that carry the slot offset; the rest carry the wrapper.
_OFFSET_BITS = _ABORT_BYTES.bit_length() - 1


def _tag(wrap: int, offset: int) -> int:
    """The byte at `offset` in the slot of wrapper `wrap`."""
    return (wrap << _OFFSET_BITS) | offset


class smc_log_engine_abort_test_seq(SmcCsrSeq):
    """Halt a log transfer with CTRL.EN and bring the engine back."""

    def __init__(self, name: str = "smc_log_engine_abort_test_seq") -> None:
        super().__init__(name)
        self.aborts = 0
        self.retriggers = 0
        #: Bytes that had reached the receiver when each disable took effect.
        self.moved_before_disable: list[int] = []

    @staticmethod
    def _buffer(wrap: int) -> int:
        base = SPM_MEMORY_BASE + _LOG_BUFFER_OFFSET + wrap * _REGION_SIZE
        assert base + _REGION_SIZE <= SPM_MEMORY_BASE + SPM_MEMORY_SIZE, (
            f"the log region of wrapper {wrap} at 0x{base:08x} runs past the end of the "
            f"SPM window the generated map declares"
        )
        return base

    async def _load_slot(self, wrap: int) -> list[int]:
        payload = [_tag(wrap, offset) for offset in range(_ABORT_BYTES)]
        slot = self._buffer(wrap) + _ENTRY * _SLOT_BYTES
        words = []
        for word in range(0, _ABORT_BYTES, 8):
            value = 0
            for lane in range(8):
                value |= payload[word + lane] << (8 * lane)
            words.append(value)
        for index, value in enumerate(words):
            await self.csr_write(f"WRAP{wrap}_SLOT_W{index}", slot + index * 8, value, length=8)
        for index, value in enumerate(words):
            await self.csr_read(
                f"WRAP{wrap}_SLOT_W{index}_RB", slot + index * 8, expected=value, length=8
            )
        return payload

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
        await self.csr_read(f"WRAP{wrap}_INTR_IDLE", engine_reg(wrap, "INTR_STATUS"), expected=0)
        await self.csr_write(f"WRAP{wrap}_LE_ON", engine_reg(wrap, "CTRL"), CTRL_EN)
        await self.csr_read(f"WRAP{wrap}_LE_ON_RB", engine_reg(wrap, "CTRL"), expected=CTRL_EN)

    async def _await_first_byte(self, wrap: int) -> None:
        lsr = uart_reg(wrap, "LSR")
        for _ in range(_ABORT_BYTES * _RX_POLLS_PER_BYTE):
            status = await self.csr_read(f"WRAP{wrap}_LSR_START", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"wrapper {wrap}: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its overrun, "
                f"parity, framing and break bits before the first log byte was read out"
            )
            if status & LSR_DR:
                return
        raise AssertionError(
            f"wrapper {wrap}: no log byte reached the receiver, so there was no transfer in "
            f"flight for the disable below to halt"
        )

    async def _drain_until_idle(self, wrap: int, label: str, budget: int) -> list[int]:
        lsr = uart_reg(wrap, "LSR")
        rbr = uart_reg(wrap, "RBR")
        received: list[int] = []
        idle_run = 0
        for _ in range(budget):
            status = await self.csr_read(f"WRAP{wrap}_LSR_{label}", lsr)
            assert status & LSR_LINE_ERRORS == 0, (
                f"wrapper {wrap} [{label}]: LSR reports 0x{status & LSR_LINE_ERRORS:x} in its "
                f"overrun, parity, framing and break bits after {len(received)} byte(s), so "
                f"the receiver did not take the log intact"
            )
            if status & LSR_DR:
                byte = await self.csr_read(f"WRAP{wrap}_RBR_{label}", rbr)
                received.append(byte & RBR_DATA)
                idle_run = 0
            elif status & LSR_TEMT:
                idle_run += 1
                if idle_run >= _IDLE_POLLS:
                    return received
            else:
                idle_run = 0
        raise AssertionError(
            f"wrapper {wrap} [{label}]: the UART never reported itself idle -- transmitter "
            f"empty with no received data for {_IDLE_POLLS} polls -- within {budget} LSR "
            f"reads, after {len(received)} byte(s)"
        )

    async def _restore(self, wrap: int) -> None:
        await self.csr_write(f"WRAP{wrap}_LE_OFF_FINAL", engine_reg(wrap, "CTRL"), 0)
        await self.csr_read(f"WRAP{wrap}_LE_OFF_RB", engine_reg(wrap, "CTRL"), expected=0)
        await self.csr_write(f"WRAP{wrap}_WRITE_ADDR_CLR", engine_reg(wrap, "LOG_WRITE_ADDR"), 0)
        await self.csr_write(f"WRAP{wrap}_REGION_SIZE_CLR", engine_reg(wrap, "LOG_REGION_SIZE"), 0)
        region_addr = engine_reg(wrap, "LOG_REGION_ADDR")
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_LO_CLR", region_addr, 0)
        await self.csr_write(f"WRAP{wrap}_REGION_ADDR_HI_CLR", region_addr + 4, 0)
        await restore_uart(self, wrap)

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        wraps = smc_addr(WRAP_NUM)
        assert _ABORT_BYTES % 8 == 0 and _RETRIGGER_BYTES % 8 == 0, (
            "a log has to be whole 64-bit fetch beats"
        )
        assert _RETRIGGER_BYTES < _ABORT_BYTES, (
            "the re-triggered log has to be shorter than the aborted one, so the count "
            "after the re-trigger tells the two apart"
        )
        tags = {_tag(w, o) for w in range(wraps) for o in range(_ABORT_BYTES)}
        assert len(tags) == wraps * _ABORT_BYTES, (
            "the byte tags of this run are not pairwise distinct, so a received byte would "
            "not name its wrapper and offset"
        )
        abort_budget = (_ABORT_BYTES + 1) * _RX_POLLS_PER_BYTE

        for wrap in range(wraps):
            element = array_reg_instances(LOG_CTRL_PATH, LOG_CTRL_PY, WRAP_STRIDE_SYMBOL, wrap)[
                _ENTRY
            ]
            payload = await self._load_slot(wrap)
            await arm_uart(self, wrap)
            await self._arm_engine(wrap)

            await self.csr_read(f"WRAP{wrap}_LOG_CTRL_IDLE", element.addr, expected=0)
            await self.csr_write(f"WRAP{wrap}_LOG_CTRL_GO", element.addr, _ABORT_BYTES)
            await self._await_first_byte(wrap)

            await self.csr_write(f"WRAP{wrap}_LE_DISABLE", engine_reg(wrap, "CTRL"), 0)
            moved = await self._drain_until_idle(wrap, "ABORT", abort_budget)
            assert 0 < len(moved) < _ABORT_BYTES, (
                f"wrapper {wrap}: {len(moved)} of {_ABORT_BYTES} byte(s) had arrived when the "
                f"UART went idle after the disable; a halt part-way through needs at least "
                f"one byte and fewer than the whole log"
            )
            assert moved == payload[: len(moved)], (
                f"wrapper {wrap}: the bytes that arrived before the disable took effect are "
                f"{[f'0x{b:02x}' for b in moved]}, the head of the slot is "
                f"{[f'0x{b:02x}' for b in payload[: len(moved)]]}"
            )
            late = await self._drain_until_idle(wrap, "LATE", abort_budget)
            assert late == [], (
                f"wrapper {wrap}: {len(late)} more byte(s) arrived after the UART had gone "
                f"idle, so clearing CTRL.EN did not stop the engine"
            )
            self.moved_before_disable.append(len(moved))
            self.aborts += 1

            held = await self.csr_read(f"WRAP{wrap}_LOG_CTRL_HELD", element.addr)
            assert held & LOG_LEN == _ABORT_BYTES, (
                f"wrapper {wrap}: LOG_CTRL[{_ENTRY}] reads {held & LOG_LEN} while the engine "
                f"is disabled; the RDL disables the engine and resets its FSMs, flops and "
                f"FIFOs but preserves the registers, so the length has to still be "
                f"{_ABORT_BYTES}"
            )

            # The shorter length goes in while the engine is still disabled, so
            # the element never holds 0 and the re-enable starts exactly one
            # transfer of a known size.
            await self.csr_write(f"WRAP{wrap}_LOG_CTRL_RETRIGGER", element.addr, _RETRIGGER_BYTES)
            await self.csr_write(f"WRAP{wrap}_LE_REENABLE", engine_reg(wrap, "CTRL"), CTRL_EN)
            again = await self._drain_until_idle(
                wrap, "RETRIGGER", (_RETRIGGER_BYTES + 1) * _RX_POLLS_PER_BYTE
            )
            assert again == payload[:_RETRIGGER_BYTES], (
                f"wrapper {wrap}: the re-triggered transfer delivered "
                f"{[f'0x{b:02x}' for b in again]}, the first {_RETRIGGER_BYTES} bytes of the "
                f"slot are {[f'0x{b:02x}' for b in payload[:_RETRIGGER_BYTES]]}"
            )
            remaining = None
            for _ in range(_HWCLR_POLLS):
                remaining = await self.csr_read(f"WRAP{wrap}_LOG_CTRL_HWCLR", element.addr)
                remaining &= LOG_LEN
                if remaining == 0:
                    break
            assert remaining == 0, (
                f"wrapper {wrap}: LOG_CTRL[{_ENTRY}] still reports {remaining} byte(s) "
                f"outstanding after the re-triggered log arrived, so hardware did not clear "
                f"the length the transfer completed"
            )
            status = await self.csr_read(
                f"WRAP{wrap}_INTR_FINAL", engine_reg(wrap, "INTR_STATUS"), expected=0
            )
            assert status & INTR_STATUS_MASK == 0, (
                f"wrapper {wrap}: INTR_STATUS reports 0x{status & INTR_STATUS_MASK:x}; "
                f"neither the halted transfer nor the re-triggered one may raise a fetch or "
                f"a write error"
            )
            self.retriggers += 1
            await self._restore(wrap)

        assert self.aborts == wraps and self.retriggers == wraps, (
            f"{self.aborts} halted and {self.retriggers} re-triggered transfers for "
            f"{wraps} wrappers"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, (
            "no scoreboard on this sequence's env, so the CSR traffic cannot be "
            "corroborated independently of the sequence's own counter"
        )
        floor = wraps * _MIN_ACCESSES_PER_WRAP
        assert self.accesses >= floor, (
            f"the sequence issued {self.accesses} SEP_IN accesses; a run that halted and "
            f"re-triggered a transfer on {wraps} wrapper(s) cannot have issued fewer "
            f"than {floor}"
        )
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"the scoreboard checked only {sb.sys_axi_checks_seen} SEP_IN AXI item(s) but "
            f"this sequence issued {self.accesses}, so the traffic never reached it"
        )

        cocotb.log.info(
            "CHK-LOG-ENGINE-ABORT-HALTED: on %d wrapper(s) a %d-byte transfer was in flight "
            "-- bytes had reached the receiver -- when CTRL.EN was cleared, and once the "
            "UART reported itself idle only %s byte(s) had arrived, each the head of that "
            "wrapper's own slot in order, with a second drain finding nothing more",
            self.aborts,
            _ABORT_BYTES,
            ", ".join(str(n) for n in self.moved_before_disable),
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-ABORT-LENGTH-KEPT: on %d wrapper(s) LOG_CTRL still read the "
            "%d bytes it was given while the engine was disabled, which is the RDL's "
            "'pending LOG_LEN values are retained'",
            self.aborts,
            _ABORT_BYTES,
        )
        cocotb.log.info(
            "CHK-LOG-ENGINE-ABORT-RETRIGGER: on %d wrapper(s) a shorter length written into "
            "the same element while the engine was disabled delivered exactly its %d bytes "
            "from the head of the slot once CTRL.EN was set again, hardware cleared the "
            "length, and INTR_STATUS stayed clear across both the halt and the re-trigger; "
            "%d SEP_IN accesses, all checked by the scoreboard",
            self.retriggers,
            _RETRIGGER_BYTES,
            self.accesses,
        )
