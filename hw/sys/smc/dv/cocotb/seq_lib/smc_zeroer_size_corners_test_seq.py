# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs at the edges of what SIZE and DEST_ADDR describe.

The RDL gives `SIZE` as "Size in bytes of zeros to write" and `DEST_ADDR` as
the "Byte address to write zeros to", and `hw/sys/smc/doc/zeroer.adoc` lists
unaligned start addresses and burst fragmentation at page boundaries among
what the zeroer handles. Two jobs here sit at those edges:

* **A job of zero bytes.** `CTRL_STATUS` is written, which is the trigger,
  with `SIZE` at 0. Zero bytes are to be written, so nothing may reach the
  output fabric: the poisoned word at `DEST_ADDR` has to keep its poison, and
  an eight-byte job started afterwards has to be the only write transaction
  the responder books across both triggers.
* **A job that starts four bytes before a page boundary and ends mid-word.**
  Sixteen bytes from `page - 4`: the upper half of the word below the
  boundary, the whole word at it, and the lower half of the word above. AXI
  forbids a burst across a 4 KB boundary, so the job takes at least two
  write transactions, and the bytes on either side of it have to keep their
  poison.

Both jobs are aimed at the output-fabric responder window, and `SIZE` and
`DEST_ADDR` are cleared afterwards so a later write to `CTRL_STATUS` cannot
start a job over anything.
"""

from __future__ import annotations

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_output_fabric_vip_utils import (
    OUTPUT_FABRIC_ADDR,
    OUTPUT_FABRIC_MODEL_BASE,
    OUTPUT_FABRIC_MODEL_REGION,
    OUTPUT_FABRIC_MODEL_SIZE,
    check_output_responder_delta,
    output_fabric_pass_all_cfg_seq,
    output_responder_counts,
)
from .smc_zeroer_dma_timeout_test_seq import (
    STATUS_BM,
    ZEROER_CTRL_STATUS,
    ZEROER_DEST_ADDR,
    ZEROER_SIZE,
)

_WORD_BYTES = 8
_PAGE_BYTES = 0x1000

#: The zero-size job's destination, and the eight-byte job that follows it.
_EMPTY_DEST = OUTPUT_FABRIC_ADDR + 0x2000
_EMPTY_POISON = 0xA0A1_A2A3_A4A5_A6A7
_FOLLOW_DEST = OUTPUT_FABRIC_ADDR + 0x2100
_FOLLOW_POISON = 0xB0B1_B2B3_B4B5_B6B7

#: The page-crossing job: sixteen bytes from four bytes below a page boundary.
_PAGE = OUTPUT_FABRIC_ADDR + 0x4000
_CROSS_DEST = _PAGE - 4
_CROSS_BYTES = 16
_CROSS_MIN_BURSTS = 2
#: (name, word address, poison, mask of the bytes the job covers)
_CROSS_WORDS = (
    ("BELOW", _PAGE - _WORD_BYTES, 0xC0C1_C2C3_C4C5_C6C7, 0xFFFF_FFFF_0000_0000),
    ("AT", _PAGE, 0xD0D1_D2D3_D4D5_D6D7, 0xFFFF_FFFF_FFFF_FFFF),
    ("ABOVE", _PAGE + _WORD_BYTES, 0xE0E1_E2E3_E4E5_E6E7, 0x0000_0000_FFFF_FFFF),
)

# Liveness ceilings, not checked quantities: expiry FAILS.
_STATUS_CYCLES = 40000
_BURST_WAIT_CYCLES = 40000


class smc_zeroer_size_corners_test_seq(output_fabric_pass_all_cfg_seq):
    """A zero-byte job and a job crossing a page boundary from an unaligned start."""

    def __init__(self, name: str = "smc_zeroer_size_corners_test_seq") -> None:
        super().__init__(name)
        self.empty_bursts = -1
        self.cross_bursts = -1

    def _ensure_model_region(self) -> None:
        if OUTPUT_FABRIC_MODEL_REGION not in self.memory_model.regions:
            self.memory_model.add_region(
                OUTPUT_FABRIC_MODEL_REGION,
                OUTPUT_FABRIC_MODEL_BASE,
                OUTPUT_FABRIC_MODEL_SIZE,
            )

    async def _fabric_write(self, addr: int, value: int) -> None:
        item = SmcSysAxiItem(f"fabric_preload_0x{addr:x}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = _WORD_BYTES
        item.wdata = value
        await _OneShot(item, f"fabric_preload_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )

    async def _fabric_read(self, addr: int) -> int:
        item = SmcSysAxiItem(f"fabric_readback_0x{addr:x}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = _WORD_BYTES
        await _OneShot(item, f"fabric_readback_0x{addr:x}_os").start(
            self.env.jtag_axi_agent.sequencer
        )
        return item.rdata

    async def _poison(self, label: str, addr: int, value: int) -> None:
        await self._fabric_write(addr, value)
        got = await self._fabric_read(addr)
        assert got == value, (
            f"{label}: 0x{addr:08x} reads 0x{got:016x} after a preload of 0x{value:016x}; "
            f"the word was not poisoned, so a later compare against it would prove nothing"
        )

    async def _program(self, label: str, dest: int, size: int) -> None:
        await self.csr_write(f"{label}_DEST_ADDR", ZEROER_DEST_ADDR, dest, length=8)
        await self.csr_write(f"{label}_SIZE", ZEROER_SIZE, size, length=8)
        await self.csr_read(f"{label}_DEST_ADDR_RB", ZEROER_DEST_ADDR, expected=dest, length=8)
        await self.csr_read(f"{label}_SIZE_RB", ZEROER_SIZE, expected=size, length=8)

    async def _trigger(self, label: str) -> None:
        await self.csr_write(f"{label}_TRIGGER", ZEROER_CTRL_STATUS, 0, length=8)

    async def _await_idle(self, label: str) -> None:
        """Bounded wait for `CTRL_STATUS.STATUS` at 0, which the RDL gives as idle."""
        word = STATUS_BM
        for _ in range(_STATUS_CYCLES):
            word = await self.csr_read(f"{label}_STATUS", ZEROER_CTRL_STATUS, length=8)
            if not word & STATUS_BM:
                return
            await cocotb.triggers.ClockCycles(cocotb.top.clk_smc_i, 1)
        raise AssertionError(
            f"{label}: CTRL_STATUS.STATUS never returned to 0 (last 0x{word:016x})"
        )

    async def _empty_leg(self) -> None:
        label = "EMPTY"
        await self._poison(label, _EMPTY_DEST, _EMPTY_POISON)
        await self._poison(f"{label}_FOLLOW", _FOLLOW_DEST, _FOLLOW_POISON)
        await self._program(label, _EMPTY_DEST, 0)
        start_writes, start_reads = output_responder_counts()
        await self._trigger(label)
        await self._await_idle(label)
        # The zeroer runs one job at a time, so once the eight-byte job has
        # booked its write, anything the zero-size job issued has been booked
        # before it and shows in the exact count.
        await self._program(f"{label}_FOLLOW", _FOLLOW_DEST, _WORD_BYTES)
        await self._trigger(f"{label}_FOLLOW")
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_idle(f"{label}_FOLLOW")
        end_writes, _ = output_responder_counts()
        self.empty_bursts = end_writes - start_writes
        kept = await self._fabric_read(_EMPTY_DEST)
        assert kept == _EMPTY_POISON, (
            f"{label}: 0x{_EMPTY_DEST:08x} reads 0x{kept:016x} after a job of SIZE 0 aimed "
            f"at it; zero bytes were to be written, so it has to keep 0x{_EMPTY_POISON:016x}"
        )
        cleared = await self._fabric_read(_FOLLOW_DEST)
        assert cleared == 0, (
            f"{label}: 0x{_FOLLOW_DEST:08x} reads 0x{cleared:016x} after the eight-byte job "
            f"that follows the empty one"
        )
        cocotb.log.info(
            "CHK-ZEROER-EMPTY-JOB: a trigger with SIZE 0 left the poisoned word at DEST_ADDR "
            "0x%08x holding 0x%016x, and across it and the eight-byte job that followed the "
            "output responder booked %d write transaction, the eight-byte job's",
            _EMPTY_DEST,
            kept,
            self.empty_bursts,
        )

    async def _cross_page_leg(self) -> None:
        label = "CROSS"
        guard_below = _PAGE - 2 * _WORD_BYTES
        guard_above = _PAGE + 2 * _WORD_BYTES
        guard_poison = 0xF0F1_F2F3_F4F5_F6F7
        for name, addr, poison, _mask in _CROSS_WORDS:
            await self._poison(f"{label}_{name}", addr, poison)
        await self._poison(f"{label}_GUARD_BELOW", guard_below, guard_poison)
        await self._poison(f"{label}_GUARD_ABOVE", guard_above, guard_poison)
        await self._program(label, _CROSS_DEST, _CROSS_BYTES)
        start_writes, start_reads = output_responder_counts()
        await self._trigger(label)
        # At least two transactions, since no AXI burst may cross the 4 KB
        # boundary the job straddles; the design may split further, which the
        # byte compares below still bound.
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=_CROSS_MIN_BURSTS,
            read_delta=0,
            exact_writes=False,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_idle(label)
        end_writes, _ = output_responder_counts()
        self.cross_bursts = end_writes - start_writes
        for name, addr, poison, mask in _CROSS_WORDS:
            got = await self._fabric_read(addr)
            want = poison & ~mask & 0xFFFF_FFFF_FFFF_FFFF
            assert got == want, (
                f"{label}: word {name} at 0x{addr:08x} reads 0x{got:016x}, not 0x{want:016x}; "
                f"the job covers bytes 0x{_CROSS_DEST:08x}..0x{_CROSS_DEST + _CROSS_BYTES - 1:08x}"
                f" and only those may be zeroed (poison 0x{poison:016x})"
            )
        for tag, addr in (("GUARD_BELOW", guard_below), ("GUARD_ABOVE", guard_above)):
            got = await self._fabric_read(addr)
            assert got == guard_poison, (
                f"{label}: {tag} word at 0x{addr:08x} reads 0x{got:016x}; it lies outside the "
                f"job and has to keep 0x{guard_poison:016x}"
            )
        cocotb.log.info(
            "CHK-ZEROER-PAGE-CROSS: a %d-byte job from 0x%08x, four bytes below a 4 KB "
            "boundary, zeroed exactly its bytes: the upper half of the word below the "
            "boundary, the word at it and the lower half of the word above, with both halves "
            "outside the job and the guard words either side keeping their poison, in %d "
            "write transactions",
            _CROSS_BYTES,
            _CROSS_DEST,
            self.cross_bursts,
        )

    async def body(self) -> None:
        assert _PAGE + 3 * _WORD_BYTES <= OUTPUT_FABRIC_ADDR + OUTPUT_FABRIC_MODEL_SIZE
        assert _PAGE % _PAGE_BYTES == 0
        self._ensure_model_region()
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self._empty_leg()
        await self._cross_page_leg()
        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
