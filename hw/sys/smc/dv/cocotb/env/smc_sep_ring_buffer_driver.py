# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stands in for SEP writing status messages into the SMC ROM's SEP ring buffer.

On silicon the SEP ROM fills this buffer over its AXI manager into SMC SRAM, and the
SMC ROM hands entries back over OCCP when a controller asks for GET_SEP_STATUS. There is
no SEP instance in the dual bench, so this driver takes that role over the target's
inbound AXI port.

Every layout constant below is a contract with the production ROM, named at its
definition:
    hw/sys/smc/bootrom/prod/lib/include/smc_ring_buffer.h   head/tail/num_entries/entries
    hw/sys/smc/bootrom/prod/lib/include/smc_scratchpad.h    scratch 9 ready bits
    hw/sys/smc/bootrom/prod/include/smc_rom_defs.h          scratch 11 holds the offset
    hw/sys/smc/bootrom/prod/lib/include/smc_status.h        the 32-bit message format

Two contracts live on the controller side instead:
    fw/tests/sep_ring_buffer_test/main.c      scratch 10 magic, scratch 12 entry count
    fw/common/occp/sep_ring_buffer_model.h    the shadow buffer and the scratch 13 guard

The shadow is what makes the firmware's checking possible. Every GET_SEP_STATUS compares
the returned word against sep_ring_buffer_model_peek(), which reads a mirror of this
buffer in the controller's own SRAM. A driver that fills the target's buffer without
mirroring it leaves the firmware expecting an empty buffer, and its guard rejects the
first real entry. The mirror has its own layout -- head, tail, entries[] with no
num_entries word -- so it is not a byte copy of the target's.
"""

from __future__ import annotations

import logging
import random

from cocotb.triggers import ClockCycles

# smc_ring_buffer_t: head at +0, tail at +4, num_entries at +8, entries[] from +12.
RING_BUFFER_SIZE = 512
RB_HEAD_OFFSET = 0
RB_TAIL_OFFSET = 4
RB_ENTRIES_OFFSET = 12

# Scratch 9, SMC-status-to-SEP. The ROM raises both before the buffer may be written.
SEP_STATUS_SRAM_INIT_BIT = 0
SEP_STATUS_BUFFER_READY_BIT = 2

# Status message: [31:24] type, [23:16] firmware id, [15:0] value.
STATUS_FW_ID_SEP_BL0 = 0x1
STATUS_TYPE_STATUS = 0x1
STATUS_TYPE_WARNING = 0x8
STATUS_TYPE_ERROR = 0xF
STATUS_TYPES = (STATUS_TYPE_STATUS, STATUS_TYPE_WARNING, STATUS_TYPE_ERROR)

# Handshake with the controller firmware's wait_for_cocotb_ready().
COCOTB_READY_MAGIC = 0xC0C0_7B00

# sep_ring_buffer_model.h: the mirror the controller firmware compares against, at a fixed
# address in its own SRAM. Layout is head, tail, entries[] -- no num_entries word, so the
# entry offset differs from the target buffer's.
SHADOW_BASE = 0xC015_B000
SHADOW_HEAD_OFFSET = 0
SHADOW_TAIL_OFFSET = 4
SHADOW_ENTRIES_OFFSET = 8

# Scratch 13, raised by the firmware around each GET_SEP_STATUS. The shadow must not move
# while it is set, or the firmware compares against a half-updated mirror.
SHADOW_GUARD_SCRATCH = 13

# Clock cycles between entry writes, so the ROM is not starved of the bus while it boots.
ENTRY_GAP_CYCLES = 10


def create_status_message(fw_id: int, msg_type: int, msg_value: int) -> int:
    return ((msg_type & 0xFF) << 24) | ((fw_id & 0xFF) << 16) | (msg_value & 0xFFFF)


def decode_status_message(message: int) -> tuple[int, int, int]:
    """(firmware id, message type, value)."""
    return ((message >> 16) & 0xFF, (message >> 24) & 0xFF, message & 0xFFFF)


class SepRingBufferDriver:
    """Writes SEP status entries into the target's ring buffer and tells the controller.

    target_csr reaches the instance running the production ROM, ctrl_csr the one running
    the DV image. The two roles are not interchangeable: the buffer lives in the target's
    SRAM, and the completion handshake lives in the controller's scratch registers.
    """

    def __init__(self, target_csr, ctrl_csr, clk, sram_base: int, scratch: dict) -> None:
        self.target = target_csr
        self.ctrl = ctrl_csr
        self.clk = clk
        self.sram_base = sram_base
        self.scratch = scratch
        self.log = logging.getLogger("cocotb.sep_ring_buffer")

        self.buffer_base_addr: int | None = None
        self.head = 0
        self.tail = 0
        self.entries_written: list[int] = []
        self.shadow_ready = False

    async def wait_for_buffer_ready(self, poll_iters: int, poll_cycles: int) -> None:
        """Block until the ROM raises both scratch 9 ready bits, then latch the layout."""
        ready_mask = (1 << SEP_STATUS_SRAM_INIT_BIT) | (1 << SEP_STATUS_BUFFER_READY_BIT)

        scratch_9 = 0
        for _ in range(poll_iters):
            scratch_9 = await self.target.read("SEP_STATUS", self.scratch["status_to_sep"])
            if (scratch_9 & ready_mask) == ready_mask:
                break
            await ClockCycles(self.clk, poll_cycles)
        else:
            raise AssertionError(
                f"target ROM never signalled the SEP status buffer ready.\n"
                f"  scratch 9 = {scratch_9:#010x}, need bits "
                f"{SEP_STATUS_SRAM_INIT_BIT} and {SEP_STATUS_BUFFER_READY_BIT} set\n"
                f"  waited {poll_iters}x{poll_cycles} cycles"
            )

        offset = await self.target.read("SEP_BUF_OFFSET", self.scratch["status_buffer_addr"])
        if offset == 0xFFFF_FFFF:
            raise AssertionError(
                "target ROM rejected its own status buffer address "
                "(scratch 11 holds SMC_SCRATCHPAD_INVALID_OFFSET)"
            )
        self.buffer_base_addr = self.sram_base + offset

        self.head = await self.target.read("RB_HEAD", self.buffer_base_addr + RB_HEAD_OFFSET)
        self.tail = await self.target.read("RB_TAIL", self.buffer_base_addr + RB_TAIL_OFFSET)
        self.log.info(
            "SEP ring buffer ready at %#010x (offset %#x): head=%d tail=%d",
            self.buffer_base_addr,
            offset,
            self.head,
            self.tail,
        )
        if self.head != self.tail:
            raise AssertionError(
                f"ROM handed over a non-empty SEP ring buffer: head={self.head} "
                f"tail={self.tail}; the entry count this test signals would be wrong"
            )

        await self._init_shadow()

    async def _init_shadow(self) -> None:
        """Publish an empty mirror before any entry lands in the target buffer."""
        await self.ctrl.write("SHADOW_HEAD", SHADOW_BASE + SHADOW_HEAD_OFFSET, self.head)
        await self.ctrl.write("SHADOW_TAIL", SHADOW_BASE + SHADOW_TAIL_OFFSET, self.tail)
        await self.ctrl.write_bytes(
            "SHADOW_ENTRIES", SHADOW_BASE + SHADOW_ENTRIES_OFFSET, bytes(RING_BUFFER_SIZE * 4)
        )
        self.shadow_ready = True
        self.log.info("controller shadow ring buffer initialised at %#010x", SHADOW_BASE)

    async def _await_guard_clear(self) -> None:
        """Block while the firmware is mid-GET_SEP_STATUS, so the mirror stays coherent."""
        while await self.ctrl.read("SHADOW_GUARD", self.scratch["shadow_guard"]) & 0x1:
            await ClockCycles(self.clk, 1)

    async def write_entry(self, value: int) -> None:
        """Append one entry and advance head, dropping the oldest when the buffer wraps."""
        assert self.buffer_base_addr is not None, "wait_for_buffer_ready() first"

        await self._await_guard_clear()

        index = self.head
        next_head = (self.head + 1) % RING_BUFFER_SIZE
        entry_addr = self.buffer_base_addr + RB_ENTRIES_OFFSET + index * 4
        await self.target.write("RB_ENTRY", entry_addr, value)
        await self.target.write("RB_HEAD", self.buffer_base_addr + RB_HEAD_OFFSET, next_head)
        self.head = next_head
        self.entries_written.append(value)

        # A full buffer keeps one slot empty, so head catching tail means the oldest entry
        # has just been overwritten and the reader has to skip past it.
        current_tail = await self.target.read("RB_TAIL", self.buffer_base_addr + RB_TAIL_OFFSET)
        if current_tail == next_head:
            self.tail = (current_tail + 1) % RING_BUFFER_SIZE
            await self.target.write("RB_TAIL", self.buffer_base_addr + RB_TAIL_OFFSET, self.tail)
            await self.ctrl.write("SHADOW_TAIL", SHADOW_BASE + SHADOW_TAIL_OFFSET, self.tail)

        # Entry before head: the firmware treats head as the point up to which entries are
        # valid, so publishing head first would expose a slot that is not written yet.
        await self.ctrl.write(
            "SHADOW_ENTRY", SHADOW_BASE + SHADOW_ENTRIES_OFFSET + index * 4, value
        )
        await self.ctrl.write("SHADOW_HEAD", SHADOW_BASE + SHADOW_HEAD_OFFSET, self.head)

    async def write_entries(self, count: int, rng: random.Random) -> list[int]:
        """Write count structured status messages, cycling the three message types."""
        self.log.info("writing %d SEP status entries (capacity %d)", count, RING_BUFFER_SIZE)
        for index in range(count):
            entry = create_status_message(
                fw_id=STATUS_FW_ID_SEP_BL0,
                msg_type=STATUS_TYPES[index % len(STATUS_TYPES)],
                msg_value=rng.randint(0, 0xFFFF),
            )
            await self.write_entry(entry)
            await ClockCycles(self.clk, ENTRY_GAP_CYCLES)

        if count:
            self.log.info(
                "wrote entries[0]=%#010x .. entries[%d]=%#010x; head=%d tail=%d",
                self.entries_written[0],
                count - 1,
                self.entries_written[-1],
                self.head,
                self.tail,
            )
        return list(self.entries_written)

    async def signal_entries_ready(self, count: int) -> None:
        """Publish the count, then the magic -- the firmware polls the magic only."""
        await self.ctrl.write("SEP_RB_COUNT", self.scratch["cocotb_entry_count"], count)
        await self.ctrl.write("SEP_RB_READY", self.scratch["cocotb_ready"], COCOTB_READY_MAGIC)
        self.log.info("signalled controller: %d entries ready", count)

    def retained_entries(self) -> list[int]:
        """The entries the ROM can still hand back, oldest first.

        A 512-slot buffer keeps one slot empty, so an overflowing run retains the newest
        RING_BUFFER_SIZE - 1 writes and the rest are gone.
        """
        capacity = RING_BUFFER_SIZE - 1
        return self.entries_written[-capacity:] if self.entries_written else []
