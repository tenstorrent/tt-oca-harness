# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The last word of every SEP_IN-reachable window memmap.adoc pins.

``memmap.adoc`` states each window as an inclusive ``BASE + lo - BASE + hi``
range (SMC Address Space Layout) or as a base plus an instance stride (SMC
Component Address Map). The base side of those windows is covered by
``smc_address_map_region_decode_test``; this sequence drives the *last* word of
each one, which a decoder that sizes a window short answers with a bus error
and a decoder that sizes it long answers from the next block.

Every expectation below comes from the chapter or from the generated register
map, never from a first read of the DUT:

* Scratchpad memory (``BASE + 0x006_0000 - BASE + 0x007_FFFF``): the first and
  the last 64-bit word hold distinct co-resident patterns, so a short or
  aliased window fails the exact readback.
* Boot ROM (``BASE + 0x004_0000 - BASE + 0x005_FFFF``, ``rom.adoc``: "128 KiB
  read-only region"): the last word answers, does not return either resident
  scratchpad pattern, and refuses a write with an error response and an
  unchanged word, which is what read-only means at this boundary.
* DMA controller (``BASE + 0x003_8000 - BASE + 0x003_81FF``) and memory zeroer
  (``BASE + 0x003_8200 - BASE + 0x003_83FF``): with distinct patterns resident
  in ``DMA_CTRL.DST_ADDRESS_LO`` and ``ZEROER_CTRL.DEST_ADDR``, the last word of
  each 512 B aperture answers and returns neither pattern.
* DMA stream banks (``dma.adoc``, Stream Support: "the register file is always
  generated with all 16 stream banks, and every bank decodes normally"):
  ``NEXT_ID_1`` through ``NEXT_ID_15`` read exactly 0 as the chapter states and
  ``NEXT_ID_0`` is read last, after the reserved sweep, because reading it is
  the one access that launches a transfer.
* CLA (``BASE + 0x016_0000``): the trace-sink ``TRDSTRAMIMPL`` identification
  word reads its generated reset.

Window tops that the reference RTL does not answer are read with the error
response tolerated and left open with the measured response and the
specification line they disagree with, rather than being claimed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import (
    _REPO,
    DMA_CTRL_BASE,
    DMA_CTRL_DST_ADDRESS_LO,
    SPM_MEMORY_BASE,
    ZEROER_CTRL_DEST_ADDR,
    dma_ctrl_offset,
    reg_reset_word,
    smc_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

_CLA_H = _REPO / "hw" / "ip" / "dfd" / "regs" / "gen" / "c" / "smc_cla.h"
CLA_TRDSTRAMIMPL_RESET = reg_reset_word(_CLA_H, "DFD_DST_SINK", "TRDSTRAMIMPL")

LOCAL_BASE = 0xC000_0000
_WORD = 8

# --- memmap.adoc, SMC Address Space Layout: Memory Regions -------------------
# "SPM ROM Memory | BASE + 0x004_0000 - BASE + 0x005_FFFF | 128KB"
ROM_SPEC_BASE = LOCAL_BASE + 0x0004_0000
ROM_SPEC_TOP = LOCAL_BASE + 0x0005_FFF8
assert ROM_SPEC_BASE == smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
# "SPM Memory | BASE + 0x006_0000 - BASE + 0x007_FFFF | 128KB"
SPM_SPEC_BASE = LOCAL_BASE + 0x0006_0000
SPM_SPEC_TOP = LOCAL_BASE + 0x0007_FFF8
assert SPM_SPEC_BASE == SPM_MEMORY_BASE

# --- memmap.adoc, SMC Component Address Map: Data Processing -----------------
DMA_SPEC_TOP = LOCAL_BASE + 0x0003_81F8
ZEROER_SPEC_TOP = LOCAL_BASE + 0x0003_83F8
DMA_NEXT_ID = tuple(
    DMA_CTRL_BASE + dma_ctrl_offset(f"DMA_CTRL_NEXT_ID_{bank}_BASE_ADDR") for bank in range(16)
)
NUM_STREAM_BANKS = 16

# --- memmap.adoc, SMC Component Address Map: SMC CLA ------------------------
CLA_TRDSTRAMIMPL = smc_addr("SMC_TOP_SMC_CLA_DST_SINK_TRDSTRAMIMPL_BASE_ADDR")

# Window tops memmap.adoc pins that the reference RTL sizes shorter. Each entry
# is (cell, address, the chapter line it disagrees with).
_SHORT_WINDOW_TOPS = (
    (
        "misc-wrap-top-decodes",
        LOCAL_BASE + 0x0000_2FF8,
        "memmap.adoc:107 gives the miscellaneous wrapper BASE + 0x000_2800 - BASE + 0x000_2FFF "
        "(2 KiB); smc_addr.h SMC_TOP_SMC_MISC_WRAP_SIZE is 0x20C, so the window top has no "
        "register behind it",
    ),
    (
        "cla-top-decodes",
        LOCAL_BASE + 0x0016_8FF8,
        "memmap.adoc:74 and :178 give the CLA BASE + 0x016_0000 - BASE + 0x016_8FFF (36 KiB); "
        "smc_addr.h SMC_TOP_SMC_CLA_SIZE is 0x4000 (16 KiB), so the window top is past the block",
    ),
)

_SPM_PATTERN_FIRST = 0xA5A5_5A5A_0000_0001
_SPM_PATTERN_LAST = 0x5A5A_A5A5_FFFF_FFF8
_ROM_WRITE_PATTERN = 0xDEAD_BEEF_DEAD_BEEF
_DMA_PATTERN = 0x3C3C_C3C3
_ZEROER_PATTERN = 0xC3C3_3C3C

EXPECTED_ACCESSES = 52
EXPECTED_VALUE_CHECKS = 29


class smc_address_window_top_decode_test_seq(SmcDecodeProbeSeq):
    """Last word of every SEP_IN-reachable window memmap.adoc pins."""

    def __init__(self, name: str = "smc_address_window_top_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0
        self.rom_top_word: int | None = None
        self.rom_write_resp: int | None = None
        self.next_id_0: int | None = None
        self.short_window_resps: dict[str, int | None] = {}

    async def _memory_tops(self) -> None:
        await self.rw_coresident(
            [
                ("SPM_FIRST_WORD", SPM_SPEC_BASE, _SPM_PATTERN_FIRST, 0),
                ("SPM_LAST_WORD", SPM_SPEC_TOP, _SPM_PATTERN_LAST, 0),
            ],
            length=_WORD,
        )
        # One cell, not two: the scratchpad window top and the Memory Regions
        # row top are the same address, closed by this one co-resident readback.
        self.close_cell(
            "spm-region-top",
            f"scratchpad first (0x{SPM_SPEC_BASE:08x}) and last (0x{SPM_SPEC_TOP:08x}) 64-bit words "
            f"held distinct co-resident patterns and read back exactly, so the 128 KiB window "
            f"memmap.adoc pins reaches its last word without aliasing; 0x{SPM_SPEC_TOP:08x} is "
            f"also the last word of the Memory Regions row of the Address Space Layout table and "
            f"answered with its co-resident pattern 0x{_SPM_PATTERN_LAST:x}",
        )

    async def _rom_top(self) -> None:
        # Re-arm the scratchpad patterns so an alias of the ROM top onto the
        # scratchpad shows up as one of them coming back.
        await self.csr_write("SPM_FIRST_ARM", SPM_SPEC_BASE, _SPM_PATTERN_FIRST, length=_WORD)
        await self.csr_write("SPM_LAST_ARM", SPM_SPEC_TOP, _SPM_PATTERN_LAST, length=_WORD)
        self.rom_top_word = await self.csr_read("ROM_SPEC_TOP", ROM_SPEC_TOP, length=_WORD)
        assert self.rom_top_word not in (_SPM_PATTERN_FIRST, _SPM_PATTERN_LAST), (
            f"0x{ROM_SPEC_TOP:08x}, the last word of the 128 KiB boot ROM, returned a resident "
            f"scratchpad pattern (0x{self.rom_top_word:x}): the ROM window aliases onto the "
            f"scratchpad"
        )
        self.rom_write_resp = await self.write_expect_error(
            "ROM_SPEC_TOP_WRITE", ROM_SPEC_TOP, _ROM_WRITE_PATTERN, length=_WORD
        )
        await self.csr_read(
            "ROM_SPEC_TOP_AFTER_WRITE", ROM_SPEC_TOP, expected=self.rom_top_word, length=_WORD
        )
        await self.csr_write("SPM_FIRST_RESTORE", SPM_SPEC_BASE, 0, length=_WORD)
        await self.csr_read("SPM_FIRST_RESTORE_RB", SPM_SPEC_BASE, expected=0, length=_WORD)
        await self.csr_write("SPM_LAST_RESTORE", SPM_SPEC_TOP, 0, length=_WORD)
        await self.csr_read("SPM_LAST_RESTORE_RB", SPM_SPEC_TOP, expected=0, length=_WORD)
        self.close_cell(
            "rom-top-read",
            f"0x{ROM_SPEC_TOP:08x} (last word of the region rom.adoc:7 pins at "
            f"0xC004_0000-0xC005_FFFF) answered with 0x{self.rom_top_word:x}, which is neither "
            f"resident scratchpad pattern; a write of 0x{_ROM_WRITE_PATTERN:x} to it was refused "
            f"with resp={self.rom_write_resp} and the word was unchanged afterwards",
        )

    async def _data_processing_tops(self) -> None:
        await self.rw_coresident(
            [
                ("DMA_DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, _DMA_PATTERN, 0),
                ("ZEROER_DEST_ADDR", ZEROER_CTRL_DEST_ADDR, _ZEROER_PATTERN, 0),
            ]
        )
        await self.csr_write("DMA_DST_ARM", DMA_CTRL_DST_ADDRESS_LO, _DMA_PATTERN)
        await self.csr_write("ZEROER_DEST_ARM", ZEROER_CTRL_DEST_ADDR, _ZEROER_PATTERN)
        dma_top = await self.csr_read("DMA_SPEC_TOP", DMA_SPEC_TOP, length=_WORD)
        zeroer_top = await self.csr_read("ZEROER_SPEC_TOP", ZEROER_SPEC_TOP, length=_WORD)
        for label, addr, word in (
            ("DMA", DMA_SPEC_TOP, dma_top),
            ("ZEROER", ZEROER_SPEC_TOP, zeroer_top),
        ):
            for pattern_name, pattern in (
                ("DMA DST_ADDRESS_LO", _DMA_PATTERN),
                ("ZEROER DEST_ADDR", _ZEROER_PATTERN),
            ):
                assert (word & 0xFFFF_FFFF) != pattern and (word >> 32) != pattern, (
                    f"{label} aperture top 0x{addr:08x} returned the resident {pattern_name} "
                    f"pattern 0x{pattern:x} (read 0x{word:x}): the aperture aliases onto that "
                    f"register"
                )
        await self.csr_write("DMA_DST_RESTORE", DMA_CTRL_DST_ADDRESS_LO, 0)
        await self.csr_read("DMA_DST_RESTORE_RB", DMA_CTRL_DST_ADDRESS_LO, expected=0)
        await self.csr_write("ZEROER_DEST_RESTORE", ZEROER_CTRL_DEST_ADDR, 0)
        await self.csr_read("ZEROER_DEST_RESTORE_RB", ZEROER_CTRL_DEST_ADDR, expected=0)
        self.close_cell(
            "dma-aperture-top",
            f"0x{DMA_SPEC_TOP:08x} (last word of the 512 B DMA aperture) answered with "
            f"0x{dma_top:x}, neither the resident DMA nor the resident zeroer pattern",
        )
        self.close_cell(
            "zeroer-aperture-top",
            f"0x{ZEROER_SPEC_TOP:08x} (last word of the 512 B zeroer aperture) answered with "
            f"0x{zeroer_top:x}, neither the resident DMA nor the resident zeroer pattern",
        )

    async def _stream_banks(self) -> None:
        for bank in range(1, NUM_STREAM_BANKS):
            await self.read_reset(f"DMA_NEXT_ID_{bank}", DMA_NEXT_ID[bank], 0)
            assert DMA_NEXT_ID[bank] == DMA_NEXT_ID[0] + bank * 8, (
                f"NEXT_ID_{bank} is at 0x{DMA_NEXT_ID[bank]:08x}, not the 8-byte stream-bank "
                f"stride from 0x{DMA_NEXT_ID[0]:08x}"
            )
        # Last, because dma.adoc says a read of NEXT_ID_0 launches a transfer
        # built from the shared descriptor registers. The scoreboard enforces
        # the OKAY response; the value is reported, since the chapter allows a
        # rejected command to return 0 as well.
        self.next_id_0 = await self.csr_read("DMA_NEXT_ID_0", DMA_NEXT_ID[0])
        self.close_cell(
            "all-16-banks-decode",
            f"NEXT_ID_1..{NUM_STREAM_BANKS - 1} each read exactly 0 at the 8-byte stream-bank "
            f"stride from 0x{DMA_NEXT_ID[0]:08x} (dma.adoc: reserved banks decode and return 0) "
            f"and NEXT_ID_0 answered OKAY with 0x{self.next_id_0:x}",
        )

    async def _cla_base(self) -> None:
        impl = await self.read_reset(
            "CLA_DST_SINK_TRDSTRAMIMPL", CLA_TRDSTRAMIMPL, CLA_TRDSTRAMIMPL_RESET
        )
        self.close_cell(
            "cla-base-decodes",
            f"trace-sink TRDSTRAMIMPL @0x{CLA_TRDSTRAMIMPL:08x}, in the first 8 bytes of the CLA "
            f"window, read the generated reset 0x{impl:x}",
        )

    async def _short_window_tops(self) -> None:
        for cell, addr, note in _SHORT_WINDOW_TOPS:
            resp, rdata = await self.read_any(f"SHORT_WINDOW_TOP_{cell}", addr)
            self.short_window_resps[cell] = resp
            self.leave_open(
                cell,
                f"0x{addr:08x} answered resp={resp} rdata=0x{rdata:x}, not a register read: {note}",
            )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        self.env.axi_monitor.expected_decerr_addrs.update(
            {addr for _cell, addr, _note in _SHORT_WINDOW_TOPS}
        )

        await self._memory_tops()
        await self._rom_top()
        await self._data_processing_tops()
        await self._stream_banks()
        await self._cla_base()
        await self._short_window_tops()

        self.value_checks_measured = sb.sys_axi_value_checks_seen - value_checks_before
        assert self.value_checks_measured >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked {self.value_checks_measured} exact-value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        self.report_cells("CHK-ADDRESS-WINDOW-TOP")
        cocotb.log.info(
            "CHK-ADDRESS-WINDOW-TOP-DECODE: %d window tops closed with %d scoreboard exact-value "
            "compares (floor %d) over %d accesses; %d window tops memmap.adoc pins are not "
            "answered by the reference RTL and are left open with their measured response",
            len(self.cells),
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
            self.accesses,
            len(self.unreachable),
        )
