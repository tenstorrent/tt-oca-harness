# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-offset accesses, all-ones and all-zero words, and a high in-aperture offset on every mailbox port.

Sources: axi_lite_mailbox_unit `architecture.adoc` and `interface.adoc`, `axil_mailbox.rdl`
(`WRITE_DATA`: any write pushes one entry irrespective of WSTRB and byte lanes whose strobe is 0
are pushed as 0; `READ_DATA`: a read of any size or alignment pops one whole entry and returns
only the byte lanes it requests; the aperture is 0x800 bytes with its last register at 0x48).

On every one of the 64 mailbox apertures, writer and reader sides of each of the 32 pairs, the
leaf pushes a byte through `WRITE_DATA` on lane 1 and on lane 2 with 64-bit writes whose strobe
enables that lane only while every other lane carries the byte's complement, and pops each
entry with a 64-bit read of `READ_DATA` that must return the byte on its lane and zeros
elsewhere, so a push that ignores the strobe or lands the byte on another lane reads back
wrong; then it pushes a byte with a 1-byte write at offset 3 and an all-ones word, and pops
them with a 1-byte read at offset 3, which must return the byte, and a 64-bit read. The FIFOs
hold two entries, so pushes and pops alternate in pairs. An all-zero word is pushed, `STATUS`
must report the FIFO not empty, and the word pops as 0. Last it reads the reader aperture at
offset 0x780, which no register occupies: `SLVERR` inside the unit's address span (`memmap.adoc`,
a read past the last register), `DECERR` where the offset lies past `SMC_TOP_SMC_MAILBOX_SIZE`
(the inbound aperture of pair 31); `STATUS` then reports the FIFO empty.
"""

from __future__ import annotations

import cocotb
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")
MAILBOX_CG_EN = _field_mask(
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h",
    "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__MAILBOX_CG_EN_bm",
)
FUSE_SENSE_RISES = 200_000
NUM_PAIRS = 32
DIRECTIONS = (("OUTBOUND", "INBOUND"), ("INBOUND", "OUTBOUND"))
BYTE_OFFSETS = (1, 2, 3)
ONES = 0xFFFF_FFFF_FFFF_FFFF
# An offset inside the 0x800-byte aperture past the last register at 0x48, with address
# bits [10:7] all set.
HIGH_OFFSET = 0x780
_MAILBOX_H = _REPO / "hw" / "ip" / "axi_lite_mailbox_unit" / "regs" / "gen" / "c" / "axil_mailbox.h"
STATUS_EMPTY = _field_mask(_MAILBOX_H, "AXIL_MAILBOX__STATUS__EMPTY_bm")
STATUS_FLAGS = STATUS_EMPTY + sum(
    _field_mask(_MAILBOX_H, f"AXIL_MAILBOX__STATUS__{flag}_bm")
    for flag in ("FULL", "WRITE_LEVEL_ABOVE_THRESH", "READ_LEVEL_ABOVE_THRESH")
)
MAILBOX_END = smc_addr("SMC_TOP_SMC_MAILBOX_BASE_ADDR") + smc_addr("SMC_TOP_SMC_MAILBOX_SIZE")
AXI_RESP_SLVERR = 2
AXI_RESP_DECERR = 3
STROBED_LANES = (1, 2)
# Accesses per direction: three byte pushes and three pops, the all-ones and all-zero words
# with their pops and the not-empty STATUS read, the high-offset read and the STATUS read.
DIRECTION_ACCESSES = 3 + 3 + 2 + 2 + 1 + 2
CG_ACCESSES = 3
PLANNED_ACCESSES = CG_ACCESSES + NUM_PAIRS * len(DIRECTIONS) * DIRECTION_ACCESSES
TERMS = ("SETUP", "BYTES", "WORDS", "OFFSET")
CHECKERS = (
    "CHK-MBXWALK-BYTE-LANES",
    "CHK-MBXWALK-HIGH-OFFSET-STATUS",
    "CHK-MBXWALK-WORDS",
    "CHK-NONVAC",
)


def _addr(direction: str, pair: int, reg: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_MAILBOX_{direction}_MAILBOX_{pair}_{reg}_BASE_ADDR")


def _byte(pair: int, offset: int, direction: str) -> int:
    """A byte that differs per pair, offset and direction and is never 0x00 or 0xFF."""
    return (
        ((0xA5 ^ (pair * 7) ^ (offset * 0x31)) | (0x40 if direction == "INBOUND" else 0)) & 0x7F
    ) | 0x01


def _lane_word(byte: int, lane: int) -> int:
    """A 64-bit word carrying `byte` on `lane` and its complement on every other lane."""
    return sum((byte if k == lane else (~byte) & 0xFF) << (8 * k) for k in range(8))


class smc_mailbox_lane_offset_walk_test_seq(SmcCsrSeq):
    """Byte-offset pushes and pops, all-ones and all-zero words, and a high offset on every port."""

    def __init__(self, name: str = "smc_mailbox_lane_offset_walk_test_seq") -> None:
        super().__init__(name)
        self.chk_seen: list[str] = []
        self.byte_lanes_ok = 0
        self.words_ok = 0
        self.offsets_ok = 0
        self.high_resps: dict[int, int] = {}
        self._stamps: list[tuple[str, int, int]] = []

    def _mark(self, term: str, count: int) -> None:
        assert count > 0, f"fence term {term} did nothing"
        self._stamps.append((term, count, int(get_sim_time("ns"))))

    def _chk(self, chk_id: str, text: str) -> None:
        cocotb.log.info("%s: %s", chk_id, text)
        self.chk_seen.append(chk_id)

    async def _observe_read(self, name: str, addr: int) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 8
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{name}: no response"
        return item

    async def _bytes(self, writer: str, reader: str, pair: int) -> None:
        wr = _addr(writer, pair, "WRITE_DATA")
        rd = _addr(reader, pair, "READ_DATA")
        tag = f"{writer[0]}{pair}"
        b1, b2, b3 = (_byte(pair, o, writer) for o in BYTE_OFFSETS)
        for lane, byte in zip(STROBED_LANES, (b1, b2)):
            await self.csr_write_strobed(
                f"{tag}_W{lane}", wr, _lane_word(byte, lane), 1 << lane, length=8
            )
        for lane, byte in zip(STROBED_LANES, (b1, b2)):
            await self.csr_read(f"{tag}_R{lane}", rd, expected=byte << (8 * lane), length=8)
        await self.csr_write(f"{tag}_W3", wr + 3, b3, length=1)
        await self.csr_write(f"{tag}_WONES", wr, ONES, length=8)
        await self.csr_read(f"{tag}_R3", rd + 3, expected=b3, length=1)
        await self.csr_read(f"{tag}_RONES", rd, expected=ONES, length=8)
        self.byte_lanes_ok += 1

    async def _words(self, writer: str, reader: str, pair: int) -> None:
        tag = f"{writer[0]}{pair}"
        await self.csr_write(f"{tag}_WZERO", _addr(writer, pair, "WRITE_DATA"), 0, length=8)
        live = await self.csr_read(f"{tag}_LIVE", _addr(reader, pair, "STATUS"), length=8)
        assert live & STATUS_EMPTY == 0, (
            f"{reader} pair {pair} STATUS reads {live:#x} with the all-zero word pushed; "
            f"the FIFO holds one entry, so empty must read 0"
        )
        await self.csr_read(f"{tag}_RZERO", _addr(reader, pair, "READ_DATA"), expected=0, length=8)
        self.words_ok += 1

    async def _offset(self, reader: str, pair: int) -> None:
        tag = f"{reader[0]}{pair}"
        base = _addr(reader, pair, "WRITE_DATA")
        high = await self._observe_read(f"{tag}_HIGH", base + HIGH_OFFSET)
        want = AXI_RESP_DECERR if base + HIGH_OFFSET >= MAILBOX_END else AXI_RESP_SLVERR
        assert high.resp_code == want, (
            f"{reader} pair {pair} read at {base + HIGH_OFFSET:#x} answered resp "
            f"{high.resp_code}, expected {want} ({'past' if want == AXI_RESP_DECERR else 'inside'}"
            f" the mailbox span ending at {MAILBOX_END:#x})"
        )
        self.high_resps[high.resp_code] = self.high_resps.get(high.resp_code, 0) + 1
        status = await self.csr_read(f"{tag}_STATUS", _addr(reader, pair, "STATUS"), length=8)
        assert status & STATUS_FLAGS == STATUS_EMPTY, (
            f"{reader} pair {pair} STATUS reads {status:#x} after the pops; the FIFO is empty "
            f"and no threshold is set, so the flags must read {STATUS_EMPTY:#x}"
        )
        self.offsets_ok += 1

    async def body(self) -> None:
        await self.wait_fuse_sense_done(max_cycles=FUSE_SENSE_RISES)
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("CLOCK_GATE_CONTROL_EN", CLOCK_GATE_CONTROL, cg | MAILBOX_CG_EN)
        await self.csr_read(
            "CLOCK_GATE_CONTROL_RB", CLOCK_GATE_CONTROL, expected=cg | MAILBOX_CG_EN
        )
        self._mark("SETUP", CG_ACCESSES)

        for pair in range(NUM_PAIRS):
            for writer, reader in DIRECTIONS:
                await self._bytes(writer, reader, pair)
        self._mark("BYTES", self.byte_lanes_ok)
        self._chk(
            "CHK-MBXWALK-BYTE-LANES",
            f"{self.byte_lanes_ok}/{NUM_PAIRS * len(DIRECTIONS)} ports: lane-strobed pushes "
            f"on lanes 1 and 2 popped as the byte on its lane with zeros elsewhere, the 1-byte "
            f"push at offset 3 popped by a 1-byte read at offset 3 with the written byte, and "
            f"the all-ones word popped intact after it",
        )

        for pair in range(NUM_PAIRS):
            for writer, reader in DIRECTIONS:
                await self._words(writer, reader, pair)
        self._mark("WORDS", self.words_ok)
        self._chk(
            "CHK-MBXWALK-WORDS",
            f"{self.words_ok}/{NUM_PAIRS * len(DIRECTIONS)} ports: STATUS read empty 0 with the "
            f"all-zero word pushed, and the word popped as 0",
        )

        for pair in range(NUM_PAIRS):
            for _writer, reader in DIRECTIONS:
                await self._offset(reader, pair)
        self._mark("OFFSET", self.offsets_ok)
        resps = ", ".join(f"resp {r}: {n}" for r, n in sorted(self.high_resps.items()))
        self._chk(
            "CHK-MBXWALK-HIGH-OFFSET-STATUS",
            f"{self.offsets_ok}/{NUM_PAIRS * len(DIRECTIONS)} apertures: the read at offset "
            f"{HIGH_OFFSET:#x} answered SLVERR inside the mailbox span and DECERR past it "
            f"({resps}) and STATUS then read empty",
        )

        assert tuple(t for t, _c, _s in self._stamps) == TERMS, f"fence {self._stamps}"
        times = [s for _t, _c, s in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing {times}"
        assert sorted(self.chk_seen) == sorted(CHECKERS[:-1]), f"checker set {self.chk_seen}"
        self._chk(
            "CHK-NONVAC",
            " < ".join(TERMS)
            + "; terms "
            + ", ".join(f"{t}(n={c})@{s}ns" for t, c, s in self._stamps)
            + f"; SEP_IN accesses {self.accesses}",
        )
