# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The last word of every SEP_IN-reachable window the RDL address map pins.

The RDL address map (``smc.rdl``) reserves an aperture for each unit
(``ocah_aperture_size``) and the register generator writes it, with the
extent the unit decodes, into the generated memory map
(``regs/gen/py/smc_memory_map.py``). The base side of those windows is covered
by ``smc_address_map_region_decode_test``; this sequence drives the *last* word
of each one, which a decoder that sizes a window short answers with a bus
error and a decoder that sizes it long answers from the next block. Every top
below is derived from that generated map, and ``LOCAL_BASE`` from the generated
``SMC_BASE_CONFIG.LOCAL_BASE`` reset.

The map gives each unit an aperture and a decoded extent, the part of the
aperture that decodes, and the RDL fixes what happens between the two
(``ocah_past_extent_resp``, the map's ``past_response``): the fabric refuses an
address past the decoded extent with DECERR, and inside it an offset that owns
no register answers OKAY (``ocah_hole_resp``). So where a unit's aperture is
larger than its decoded extent, the last word *of the decoded extent* is the
window top that must answer, and the last word of the aperture must be refused.

* Scratchpad memory (``spm_memory``, 1 MiB): the first and the last 64-bit word
  hold distinct co-resident patterns, so a short or aliased window fails the
  exact readback.
* Boot ROM (``spm_rom_memory``, 128 KiB, the same extent ``rom.adoc`` states):
  the last word answers, does not return either resident scratchpad pattern,
  and refuses a write with an error response and an unchanged word, which is
  what read-only means at this boundary. No specification pins the word an
  unprogrammed ROM offset holds, so its value is not compared.
* DMA controller (``dma_ctrl``, 512 B aperture, 312 B decoded) and memory
  zeroer (``zeroer_ctrl``, 256 B aperture, 24 B decoded): with distinct
  patterns resident in ``DMA_CTRL.DST_ADDRESS_LO`` and ``ZEROER_CTRL.DEST_ADDR``,
  the last word of each decoded extent answers OKAY and returns neither
  pattern -- no specification pins what an in-extent offset without a register
  returns, so the value is not compared -- and the last word of each aperture,
  past the decoded extent, is refused with DECERR.
* DMA stream banks (``dma.adoc``, Stream Support: "the register file is always
  generated with all 16 stream banks, and every bank decodes normally", and the
  reserved banks' ``NEXT_ID`` "completes with no bus error and returns 0"):
  ``NEXT_ID_1`` through ``NEXT_ID_15`` each answer OKAY with exactly 0 at the
  8-byte stream-bank stride, and ``NEXT_ID_0`` is read last, after the reserved
  sweep, because reading it is the one access that launches a transfer. The
  reserved banks hold no writable state -- the chapter ties their STATUS and
  DONE to 0 as well -- so this sweep proves that every reserved bank address
  answers as specified; it cannot tell one reserved bank from another, and
  does not claim to.
* CLA (``smc_cla``, 16 KiB): the trace-sink ``TRDSTRAMIMPL`` identification
  word in the first 8 bytes reads its generated reset, and the window's last
  8-byte word is the trace destination's ``ScratchLo``/``ScratchHi`` pair,
  which holds distinct co-resident patterns and reads them back.

The miscellaneous wrapper's 2 KiB aperture carries a 524 B decoded extent, so
it is driven the same way: the last word of the decoded extent answers OKAY
and the last word of the aperture is refused with DECERR.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_addr_map import (
    _REPO,
    DMA_CTRL_BASE,
    DMA_CTRL_DST_ADDRESS_LO,
    LOCAL_BASE_RESET,
    SPM_MEMORY_BASE,
    ZEROER_CTRL_DEST_ADDR,
    dma_ctrl_offset,
    generated_decoded_extent,
    generated_past_extent_resp,
    generated_window,
    reg_reset_word,
    smc_addr,
)
from .smc_decode_probe_utils import SmcDecodeProbeSeq

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_CLA_DST_0__SCRATCHHI_REG_ADDR,
    SMC_CLA_DST_0__SCRATCHLO_REG_ADDR,
    DFD_DST_ScratchHi_REG_DEFAULT,
    DFD_DST_ScratchLo_REG_DEFAULT,
)

_CLA_H = _REPO / "hw" / "ip" / "dfd" / "regs" / "gen" / "c" / "smc_cla.h"
CLA_TRDSTRAMIMPL_RESET = reg_reset_word(_CLA_H, "DFD_DST_SINK", "TRDSTRAMIMPL")

LOCAL_BASE = LOCAL_BASE_RESET
_WORD = 8


def _window_top(unit: str) -> int:
    """Absolute address of the last 64-bit word of ``unit``'s generated window."""
    _first, last = generated_window(unit)
    return LOCAL_BASE + last - (_WORD - 1)


def _window_base(unit: str) -> int:
    return LOCAL_BASE + generated_window(unit)[0]


def _decoded_top(unit: str) -> int:
    """Absolute address of the last aligned 64-bit word inside ``unit``'s decoded extent."""
    first, _last = generated_window(unit)
    end = first + generated_decoded_extent(unit)
    return LOCAL_BASE + (end & ~(_WORD - 1)) - _WORD


# --- generated memory map, Memory Regions -------------------------------------
ROM_SPEC_BASE = _window_base("spm_rom_memory")
ROM_SPEC_TOP = _window_top("spm_rom_memory")
assert ROM_SPEC_BASE == smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
# rom.adoc: "a 128 KiB read-only region"; the generated window has to agree.
assert ROM_SPEC_TOP - ROM_SPEC_BASE + _WORD == 128 * 1024
SPM_SPEC_BASE = _window_base("spm_memory")
SPM_SPEC_TOP = _window_top("spm_memory")
assert SPM_SPEC_BASE == SPM_MEMORY_BASE

# --- generated memory map, Data Processing -------------------------------------
# Aperture tops and decoded-extent tops of the generated memory map; the extent
# has to agree with the generated header's size.
DMA_APERTURE_TOP = _window_top("dma_ctrl")
DMA_DECODED_TOP = _decoded_top("dma_ctrl")
ZEROER_APERTURE_TOP = _window_top("zeroer_ctrl")
ZEROER_DECODED_TOP = _decoded_top("zeroer_ctrl")
assert _window_base("dma_ctrl") == DMA_CTRL_BASE
assert generated_decoded_extent("dma_ctrl") == smc_addr("SMC_TOP_DMA_CTRL_SIZE")
assert generated_decoded_extent("zeroer_ctrl") == smc_addr("SMC_TOP_ZEROER_CTRL_SIZE")
assert DMA_DECODED_TOP < DMA_APERTURE_TOP and ZEROER_DECODED_TOP < ZEROER_APERTURE_TOP
assert generated_past_extent_resp("dma_ctrl")[0] == "DECERR"
assert generated_past_extent_resp("zeroer_ctrl")[0] == "DECERR"
DMA_NEXT_ID = tuple(
    DMA_CTRL_BASE + dma_ctrl_offset(f"DMA_CTRL_NEXT_ID_{bank}_BASE_ADDR") for bank in range(16)
)
NUM_STREAM_BANKS = 16

# --- generated memory map, SMC CLA --------------------------------------------
CLA_TRDSTRAMIMPL = smc_addr("SMC_TOP_SMC_CLA_DST_SINK_TRDSTRAMIMPL_BASE_ADDR")
CLA_SPEC_TOP = _window_top("smc_cla")
# The window's last 8-byte word is the DST_0 ScratchLo/ScratchHi pair
# (32-bit registers, sw=rw, reset 0); the generated map has to place it there.
assert SMC_CLA_DST_0__SCRATCHLO_REG_ADDR == CLA_SPEC_TOP
assert SMC_CLA_DST_0__SCRATCHHI_REG_ADDR == CLA_SPEC_TOP + 4
_CLA_TOP_PATTERNS = (0x3C3C_C3C3, 0xC3C3_3C3C)

# Apertures larger than their decoded extent, driven at both tops. Each entry
# is (cell, unit, decoded top, aperture top).
MISC_WRAP_DECODED_TOP = _decoded_top("smc_misc_wrap")
MISC_WRAP_APERTURE_TOP = _window_top("smc_misc_wrap")
assert generated_decoded_extent("smc_misc_wrap") == smc_addr("SMC_TOP_SMC_MISC_WRAP_SIZE")
assert MISC_WRAP_DECODED_TOP < MISC_WRAP_APERTURE_TOP
assert generated_past_extent_resp("smc_misc_wrap")[0] == "DECERR"
_SHORT_WINDOW_TOPS = (
    ("misc-wrap-top-decodes", "smc_misc_wrap", MISC_WRAP_DECODED_TOP, MISC_WRAP_APERTURE_TOP),
)

_SPM_PATTERN_FIRST = 0xA5A5_5A5A_0000_0001
_SPM_PATTERN_LAST = 0x5A5A_A5A5_FFFF_FFF8
_ROM_WRITE_PATTERN = 0xDEAD_BEEF_DEAD_BEEF
_DMA_PATTERN = 0x3C3C_C3C3
_ZEROER_PATTERN = 0xC3C3_3C3C

EXPECTED_ACCESSES = 62
EXPECTED_VALUE_CHECKS = 31


class smc_address_window_top_decode_test_seq(SmcDecodeProbeSeq):
    """Last word of every SEP_IN-reachable window the RDL address map pins."""

    def __init__(self, name: str = "smc_address_window_top_decode_test_seq") -> None:
        super().__init__(name)
        self.value_checks_measured = 0
        self.rom_top_word: int | None = None
        self.rom_write_resp: int | None = None
        self.next_id_0: int | None = None

    async def _memory_tops(self) -> None:
        await self.rw_coresident(
            [
                ("SPM_FIRST_WORD", SPM_SPEC_BASE, _SPM_PATTERN_FIRST, 0),
                ("SPM_LAST_WORD", SPM_SPEC_TOP, _SPM_PATTERN_LAST, 0),
            ],
            length=_WORD,
        )
        self.close_cell(
            "spm-region-top",
            f"scratchpad first (0x{SPM_SPEC_BASE:08x}) and last (0x{SPM_SPEC_TOP:08x}) 64-bit words "
            f"held distinct co-resident patterns and read back exactly, so the "
            f"{(SPM_SPEC_TOP - SPM_SPEC_BASE + _WORD) // 1024} KiB window the generated memory map "
            f"pins for spm_memory reaches its last word without aliasing",
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
            f"0x{ROM_SPEC_TOP:08x} (last word of the 128 KiB spm_rom_memory window, the extent "
            f"rom.adoc states) answered OKAY with 0x{self.rom_top_word:x}, which is neither "
            f"resident scratchpad pattern; a write of 0x{_ROM_WRITE_PATTERN:x} to it was refused "
            f"with resp={self.rom_write_resp} and the word was unchanged afterwards. No "
            f"specification pins the word an unprogrammed ROM offset holds, so its value is "
            f"reported, not compared",
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
        dma_top = await self.csr_read("DMA_DECODED_TOP", DMA_DECODED_TOP, length=_WORD)
        zeroer_top = await self.csr_read("ZEROER_DECODED_TOP", ZEROER_DECODED_TOP, length=_WORD)
        for label, addr, word in (
            ("DMA", DMA_DECODED_TOP, dma_top),
            ("ZEROER", ZEROER_DECODED_TOP, zeroer_top),
        ):
            for pattern_name, pattern in (
                ("DMA DST_ADDRESS_LO", _DMA_PATTERN),
                ("ZEROER DEST_ADDR", _ZEROER_PATTERN),
            ):
                assert (word & 0xFFFF_FFFF) != pattern and (word >> 32) != pattern, (
                    f"{label} decoded-extent top 0x{addr:08x} returned the resident "
                    f"{pattern_name} pattern 0x{pattern:x} (read 0x{word:x}): the extent aliases "
                    f"onto that register"
                )
        # Past the decoded extent the fabric refuses the access (RDL ocah_past_extent_resp).
        await self.read_decerr("DMA_APERTURE_TOP", DMA_APERTURE_TOP, length=_WORD)
        await self.read_decerr("ZEROER_APERTURE_TOP", ZEROER_APERTURE_TOP, length=_WORD)
        await self.csr_write("DMA_DST_RESTORE", DMA_CTRL_DST_ADDRESS_LO, 0)
        await self.csr_read("DMA_DST_RESTORE_RB", DMA_CTRL_DST_ADDRESS_LO, expected=0)
        await self.csr_write("ZEROER_DEST_RESTORE", ZEROER_CTRL_DEST_ADDR, 0)
        await self.csr_read("ZEROER_DEST_RESTORE_RB", ZEROER_CTRL_DEST_ADDR, expected=0)
        self.close_cell(
            "dma-aperture-top",
            f"0x{DMA_DECODED_TOP:08x} (last word of the {generated_decoded_extent('dma_ctrl')} B "
            f"dma_ctrl decoded extent) answered OKAY with 0x{dma_top:x}, neither the resident "
            f"DMA nor the resident zeroer pattern -- no specification pins an in-extent word "
            f"without a register, so its value is reported, not compared -- and "
            f"0x{DMA_APERTURE_TOP:08x} (last word of the 512 B aperture, past the decoded "
            f"extent) was refused with DECERR as the RDL's past-extent response requires",
        )
        self.close_cell(
            "zeroer-aperture-top",
            f"0x{ZEROER_DECODED_TOP:08x} (last word of the "
            f"{generated_decoded_extent('zeroer_ctrl')} B zeroer_ctrl decoded extent) answered "
            f"OKAY with 0x{zeroer_top:x}, neither the resident DMA nor the resident zeroer "
            f"pattern -- reported, not compared, for the same reason -- and "
            f"0x{ZEROER_APERTURE_TOP:08x} (last word of the 256 B aperture, past the decoded "
            f"extent) was refused with DECERR as the RDL's past-extent response requires",
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
            "all-16-banks-answer",
            f"NEXT_ID_1..{NUM_STREAM_BANKS - 1} each answered OKAY with exactly 0 at the 8-byte "
            f"stream-bank stride from 0x{DMA_NEXT_ID[0]:08x} (dma.adoc: a reserved bank's "
            f"NEXT_ID completes with no bus error and returns 0) and NEXT_ID_0 answered OKAY "
            f"with 0x{self.next_id_0:x}; the reserved banks hold no writable state, so this "
            f"leg does not distinguish one reserved bank from another",
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
        await self.rw_coresident(
            [
                (
                    "CLA_DST0_SCRATCHLO",
                    SMC_CLA_DST_0__SCRATCHLO_REG_ADDR,
                    _CLA_TOP_PATTERNS[0],
                    DFD_DST_ScratchLo_REG_DEFAULT,
                ),
                (
                    "CLA_DST0_SCRATCHHI",
                    SMC_CLA_DST_0__SCRATCHHI_REG_ADDR,
                    _CLA_TOP_PATTERNS[1],
                    DFD_DST_ScratchHi_REG_DEFAULT,
                ),
            ]
        )
        self.close_cell(
            "cla-top-decodes",
            f"0x{CLA_SPEC_TOP:08x} (last 8-byte word of the 16 KiB smc_cla window) is the DST_0 "
            f"ScratchLo/ScratchHi pair: both held distinct co-resident patterns "
            f"({_CLA_TOP_PATTERNS[0]:#x}, {_CLA_TOP_PATTERNS[1]:#x}), read them back exactly and "
            f"read back their generated reset after the restore",
        )

    async def _short_window_tops(self) -> None:
        for cell, unit, decoded_top, aperture_top in _SHORT_WINDOW_TOPS:
            word = await self.csr_read(f"DECODED_TOP_{cell}", decoded_top, length=_WORD)
            await self.read_decerr(f"APERTURE_TOP_{cell}", aperture_top, length=_WORD)
            extent = generated_decoded_extent(unit)
            self.close_cell(
                cell,
                f"0x{decoded_top:08x} (last word of the {extent} B {unit} decoded extent) "
                f"answered OKAY with 0x{word:x} -- an in-extent offset without a register, so "
                f"the value is reported, not compared -- and 0x{aperture_top:08x} (last word of "
                f"the aperture, past the decoded extent) was refused with DECERR as the RDL's "
                f"past-extent response requires",
            )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        sb = self.env.scoreboard
        value_checks_before = sb.sys_axi_value_checks_seen
        self.env.axi_monitor.expected_decerr_addrs.update(
            {DMA_APERTURE_TOP, ZEROER_APERTURE_TOP}
            | {aperture_top for _cell, _unit, _decoded, aperture_top in _SHORT_WINDOW_TOPS}
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
            "compares (floor %d) over %d accesses; %d apertures larger than their decoded "
            "extent answered at the extent's last word and refused the aperture's",
            len(self.cells),
            self.value_checks_measured,
            EXPECTED_VALUE_CHECKS,
            self.accesses,
            2 + len(_SHORT_WINDOW_TOPS),
        )
