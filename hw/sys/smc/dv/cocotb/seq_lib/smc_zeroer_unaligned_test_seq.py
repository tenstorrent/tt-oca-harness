# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unaligned zeroer jobs whose final beat is partial, inside one 4 KB page.

`hw/sys/smc/doc/zeroer.adoc` lists unaligned start addresses among what the
zeroer handles, and the RDL gives `DEST_ADDR` as the byte address and `SIZE` as
the byte count. When `DEST_ADDR` starts partway into a beat, the end offset
`DEST_ADDR[2:0] + SIZE` decides both how many beats the job spans and how wide
its final beat is; deriving either from `SIZE` alone corrupts the edges. The
page-crossing job in `smc_zeroer_size_corners_test` never exercises this, because
splitting on the 4 KB boundary already makes each fragment end on a word.

Two jobs here stay inside one page, so the design keeps each in a single burst:

* **A thirteen-byte job from five bytes into a word.** `[base+5, base+18)`
  touches three words: the top three bytes of the first, the whole second, and
  the low two bytes of the third. The tail past the second word spills into a
  third beat that a `SIZE`-only beat count omits, leaving `base+13..base+15`
  poisoned, while the final beat's width, taken from `SIZE`'s low bits instead
  of the end offset, clears `base+16..base+18` as five bytes rather than two.
* **A four-byte job from six bytes into a word.** `[base+6, base+10)` straddles
  two words by two bytes each. Classified as a single beat from `SIZE` alone it
  never issues the second beat, leaving `base+8..base+9` poisoned.

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
_MASK64 = 0xFFFF_FFFF_FFFF_FFFF

#: The tail job: thirteen bytes from five bytes into a word, all within one page.
_TAIL_BASE = OUTPUT_FABRIC_ADDR + 0x6000
_TAIL_DEST = _TAIL_BASE + 5
_TAIL_BYTES = 13
#: (name, word address, poison, mask of the bytes the job covers)
_TAIL_WORDS = (
    ("FIRST", _TAIL_BASE, 0xC0C1_C2C3_C4C5_C6C7, 0xFFFF_FF00_0000_0000),
    ("MIDDLE", _TAIL_BASE + _WORD_BYTES, 0xD0D1_D2D3_D4D5_D6D7, 0xFFFF_FFFF_FFFF_FFFF),
    ("LAST", _TAIL_BASE + 2 * _WORD_BYTES, 0xE0E1_E2E3_E4E5_E6E7, 0x0000_0000_0000_FFFF),
)

#: The span job: four bytes from six bytes into a word, straddling two words.
_SPAN_BASE = OUTPUT_FABRIC_ADDR + 0x6100
_SPAN_DEST = _SPAN_BASE + 6
_SPAN_BYTES = 4
_SPAN_WORDS = (
    ("FIRST", _SPAN_BASE, 0xA0A1_A2A3_A4A5_A6A7, 0xFFFF_0000_0000_0000),
    ("SECOND", _SPAN_BASE + _WORD_BYTES, 0xB0B1_B2B3_B4B5_B6B7, 0x0000_0000_0000_FFFF),
)

_GUARD_POISON = 0xF0F1_F2F3_F4F5_F6F7

# Liveness ceilings, not checked quantities: expiry FAILS.
_STATUS_CYCLES = 40000
_BURST_WAIT_CYCLES = 40000


class smc_zeroer_unaligned_test_seq(output_fabric_pass_all_cfg_seq):
    """Unaligned in-page jobs whose final beat is partial."""

    def __init__(self, name: str = "smc_zeroer_unaligned_test_seq") -> None:
        super().__init__(name)
        self.tail_bursts = -1
        self.span_bursts = -1

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

    async def _run_leg(
        self,
        label: str,
        dest: int,
        size: int,
        words: tuple[tuple[str, int, int, int], ...],
        guard_below: int,
        guard_above: int,
    ) -> int:
        for name, addr, poison, _mask in words:
            await self._poison(f"{label}_{name}", addr, poison)
        await self._poison(f"{label}_GUARD_BELOW", guard_below, _GUARD_POISON)
        await self._poison(f"{label}_GUARD_ABOVE", guard_above, _GUARD_POISON)
        await self._program(label, dest, size)
        start_writes, start_reads = output_responder_counts()
        await self._trigger(label)
        # The job stays inside one page, so it books at least one write
        # transaction; the byte compares below bound whatever split the design
        # chooses.
        await check_output_responder_delta(
            start_writes=start_writes,
            start_reads=start_reads,
            write_delta=1,
            read_delta=0,
            exact_writes=False,
            timeout_cycles=_BURST_WAIT_CYCLES,
        )
        await self._await_idle(label)
        end_writes, _ = output_responder_counts()
        for name, addr, poison, mask in words:
            got = await self._fabric_read(addr)
            want = poison & ~mask & _MASK64
            assert got == want, (
                f"{label}: word {name} at 0x{addr:08x} reads 0x{got:016x}, not 0x{want:016x}; "
                f"the job covers bytes 0x{dest:08x}..0x{dest + size - 1:08x} and only those may "
                f"be zeroed (poison 0x{poison:016x})"
            )
        for tag, addr in (("GUARD_BELOW", guard_below), ("GUARD_ABOVE", guard_above)):
            got = await self._fabric_read(addr)
            assert got == _GUARD_POISON, (
                f"{label}: {tag} word at 0x{addr:08x} reads 0x{got:016x}; it lies outside the "
                f"job and has to keep 0x{_GUARD_POISON:016x}"
            )
        return end_writes - start_writes

    async def _tail_leg(self) -> None:
        label = "TAIL"
        self.tail_bursts = await self._run_leg(
            label,
            _TAIL_DEST,
            _TAIL_BYTES,
            _TAIL_WORDS,
            guard_below=_TAIL_BASE - _WORD_BYTES,
            guard_above=_TAIL_BASE + 3 * _WORD_BYTES,
        )
        cocotb.log.info(
            "CHK-ZEROER-UNALIGNED-TAIL: a %d-byte job from 0x%08x, five bytes into a word, "
            "zeroed exactly its bytes: the top three bytes of the first word, the whole second "
            "word and the low two bytes of the third, leaving the rest of each edge word and "
            "the guard words either side poisoned, in %d write transaction(s)",
            _TAIL_BYTES,
            _TAIL_DEST,
            self.tail_bursts,
        )

    async def _span_leg(self) -> None:
        label = "SPAN"
        self.span_bursts = await self._run_leg(
            label,
            _SPAN_DEST,
            _SPAN_BYTES,
            _SPAN_WORDS,
            guard_below=_SPAN_BASE - _WORD_BYTES,
            guard_above=_SPAN_BASE + 2 * _WORD_BYTES,
        )
        cocotb.log.info(
            "CHK-ZEROER-UNALIGNED-SPAN: a %d-byte job from 0x%08x, six bytes into a word, "
            "zeroed exactly its bytes across the two words it straddles: the top two bytes of "
            "the first and the low two of the second, with the guard words either side keeping "
            "their poison, in %d write transaction(s)",
            _SPAN_BYTES,
            _SPAN_DEST,
            self.span_bursts,
        )

    async def body(self) -> None:
        assert _TAIL_DEST + _TAIL_BYTES <= _TAIL_BASE + _PAGE_BYTES
        assert _SPAN_DEST + _SPAN_BYTES <= _SPAN_BASE + _PAGE_BYTES
        assert _TAIL_BASE % _PAGE_BYTES == 0 and _SPAN_BASE % _WORD_BYTES == 0
        assert _SPAN_BASE + 2 * _WORD_BYTES < OUTPUT_FABRIC_ADDR + OUTPUT_FABRIC_MODEL_SIZE
        self._ensure_model_region()
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self._tail_leg()
        await self._span_leg()
        await self.csr_write("ZEROER_SIZE_CLEAR", ZEROER_SIZE, 0, length=8)
        await self.csr_write("ZEROER_DEST_ADDR_CLEAR", ZEROER_DEST_ADDR, 0, length=8)
        await self.csr_read("ZEROER_SIZE_CLEAR_RB", ZEROER_SIZE, expected=0, length=8)
