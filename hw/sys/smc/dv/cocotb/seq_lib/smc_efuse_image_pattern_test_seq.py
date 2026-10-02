# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense a fully populated eFuse image and sweep every SMC_EFUSE_MAP word.

**Proof class: transport and lock enforcement.** The bank behind the sense is
the adopter's simulation stand-in for the OTP macro
(``hw/ip/efuse/dv/models/efuse_bank_model.sv``), which ``$readmemh``s the image
named by ``+smc_efuse_hex`` when its reset releases. Everything compared below
travels the real path: the sense FSM in ``efuse_shadow_regs.sv`` streams every
fuse word into the shadow file, and SEP_IN AXI reads it back through the
SMC fabric and ``efuse_shadow_reg_access_control``. Nothing here claims fuse
programming.

**Where the image comes from.** The testcase module writes the image before the
first reset releases: ``efuse_preload/pattern_efuse.py`` fills every schema
field to full width with the leaf's pattern, and ``generate_efuse_preload.py``
turns that configuration into the hex image. Every expectation is computed in
Python from that hex image and the generated register map, never from a read of
the DUT:

* data words -- word ``n`` of the image backs ``SMC_EFUSE_MAP_BASE + 4*n``.
* lock slots -- the region of each word and its ``*_WRITE_LOCK`` /
  ``*_READ_LOCK`` bit come from ``smc_addr.h`` and ``blocks/smc_efuse_map.h``.
  LOCKS (at ``SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR``) is set-only and carries
  no lock of its own; every other region is blocked by its LOCKS bits
  (``architecture.adoc``, field lock table).
  A blocked read is expected to return ``EFUSE_BLOCKED_READ_DATA`` with OKAY, the
  same expectation ``smc_efuse_map_read_test`` holds read-locked rows to. The
  OKAY response code is the observed RTL behaviour, not a sentence of the
  architecture document.

**Scenario.** Sense; read all 256 words. Write the complement of every non-LOCKS
word, then read them all: a write-unlocked word holds the complement, a
write-locked one still holds the image. Every image senses a non-zero LOCKS, so
a write of 0 is a real clear attempt: LOCKS must keep its sensed value, read
all-ones after a write of all-ones, and keep all-ones across a second write of
0. A sweep of all 256 words then sees every non-LOCKS word blocked. Cold
reset, observe sense restart, and read all 256 words against the image once
more -- the shadow writes above are gone because the shadow file is reloaded
from the bank.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cocotb
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import (
    EFUSE_BLOCKED_READ_DATA,
    EFUSE_MAP_BASE,
    EFUSE_MAP_SIZE,
    efuse_preload_words,
)
from .smc_reset_seq_base import SmcResetSeqBase

_SMC_EFUSE_MAP_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_efuse_map.h"
)
_WORD_MASK = 0xFFFF_FFFF
EFUSE_MAP_WORDS = EFUSE_MAP_SIZE // 4
_LOCKS_BASE = smc_addr("SMC_TOP_SMC_EFUSE_MAP_LOCKS_BASE_ADDR")
#: Map words that hold LOCKS, low word first.
LOCKS_WORDS = range(
    (_LOCKS_BASE - EFUSE_MAP_BASE) // 4,
    (smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR") - EFUSE_MAP_BASE) // 4,
)
#: Every map word outside LOCKS.
DATA_WORDS = tuple(w for w in range(EFUSE_MAP_WORDS) if w not in LOCKS_WORDS)
_LOCKS_ALL_SET = (1 << (32 * len(LOCKS_WORDS))) - 1


@dataclass(frozen=True)
class _Region:
    name: str
    first_word: int
    end_word: int
    write_lock: int
    read_lock: int


def _lock(name: str, kind: str) -> int:
    return _field_mask(_SMC_EFUSE_MAP_H, f"SMC_EFUSE_MAP__LOCKS__{name}_{kind}_LOCK_bm")


def _regions() -> tuple[_Region, ...]:
    """Every lockable region of the map, in address order, from the generated map."""
    starts = [
        ("JTAG_PUBLIC_IDENTITY", smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR")),
        ("I2C_I3C_ID", smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_I2C_I3C_ID_BASE_ADDR", 0)),
        ("SMC_CONFIG", smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR")),
        (
            "OCCP_TRANSPORT_TIMEOUT",
            smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR"),
        ),
    ]
    for k in range(smc_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_NUM")):
        starts.append((f"SPARE{k}", smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", k)))
    regions = []
    for idx, (name, addr) in enumerate(starts):
        end = starts[idx + 1][1] if idx + 1 < len(starts) else EFUSE_MAP_BASE + EFUSE_MAP_SIZE
        regions.append(
            _Region(
                name,
                (addr - EFUSE_MAP_BASE) // 4,
                (end - EFUSE_MAP_BASE) // 4,
                _lock(name, "WRITE"),
                _lock(name, "READ"),
            )
        )
    return tuple(regions)


REGIONS = _regions()


def region_of(word: int) -> _Region | None:
    """The lockable region holding ``word``, or None for the LOCKS words."""
    for region in REGIONS:
        if region.first_word <= word < region.end_word:
            return region
    assert word in LOCKS_WORDS, f"word {word} is in no region of SMC_EFUSE_MAP"
    return None


@dataclass(frozen=True)
class EfuseImage:
    """The expectation model of one sensed image."""

    path: Path
    words: tuple[int, ...]

    @property
    def locks(self) -> int:
        return sum(self.words[w] << (32 * i) for i, w in enumerate(LOCKS_WORDS))

    def read_locked(self, word: int, locks: int | None = None) -> bool:
        region = region_of(word)
        return region is not None and bool(
            (self.locks if locks is None else locks) & region.read_lock
        )

    def write_locked(self, word: int) -> bool:
        region = region_of(word)
        return region is not None and bool(self.locks & region.write_lock)

    def expect_read(self, word: int, locks: int | None = None) -> int:
        if self.read_locked(word, locks):
            return EFUSE_BLOCKED_READ_DATA
        return self.words[word]


def load_image(path: Path) -> EfuseImage:
    words = efuse_preload_words(path)
    assert len(words) == EFUSE_MAP_WORDS, (
        f"{path} holds {len(words)} words; SMC_EFUSE_MAP is {EFUSE_MAP_WORDS} words"
    )
    return EfuseImage(path, words)


def word_addr(word: int) -> int:
    return EFUSE_MAP_BASE + 4 * word


#: SEP_IN AXI accesses one run issues: three 256-word read sweeps, a complement
#: write and a readback of every non-LOCKS word, and three write-then-readback
#: rounds over the LOCKS words in the set-only leg.
EXPECTED_ACCESSES = 3 * EFUSE_MAP_WORDS + 2 * len(DATA_WORDS) + 3 * 2 * len(LOCKS_WORDS)
#: Of those, the reads that carry an exact expectation (every read does).
EXPECTED_VALUE_CHECKS = 3 * EFUSE_MAP_WORDS + len(DATA_WORDS) + 3 * len(LOCKS_WORDS)


class smc_efuse_image_pattern_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Full-map sweep, complement write, LOCKS set-only, cold-reset re-sense."""

    def __init__(self, name: str = "smc_efuse_image_pattern_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.dispatch_reset = None
        #: Words compared against the image, per sweep that compares content.
        self.content_compares: list[int] = []
        self.unlocked_words = 0
        self.locked_words = 0

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    async def _sweep(self, label: str, expect) -> list[int]:
        return [
            await self.csr_read(f"{label}_W{word}", word_addr(word), expected=expect(word))
            for word in range(EFUSE_MAP_WORDS)
        ]

    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        dut = cocotb.top

        await self.wait_fuse_sense_done()
        self.content_compares.append(len(await self._sweep("SENSE", image.expect_read)))
        cocotb.log.info(
            "CHK-EFUSE-IMG-SENSE: all %d SMC_EFUSE_MAP words read back equal to %s "
            "after the first sense (%d read-locked by the image)",
            self.content_compares[-1],
            image.path.name,
            sum(image.read_locked(w) for w in range(EFUSE_MAP_WORDS)),
        )

        data_words = DATA_WORDS
        for word in data_words:
            await self.csr_write(f"COMPL_W{word}", word_addr(word), ~image.words[word] & _WORD_MASK)
        for word in data_words:
            if image.write_locked(word):
                self.locked_words += 1
                expected = image.words[word]
            else:
                self.unlocked_words += 1
                expected = ~image.words[word] & _WORD_MASK
            await self.csr_read(f"COMPL_RB_W{word}", word_addr(word), expected=expected)
        assert self.locked_words >= 1 and self.unlocked_words >= 1, (
            f"complement leg saw {self.locked_words} write-locked and "
            f"{self.unlocked_words} write-unlocked words; it needs at least one of each"
        )
        cocotb.log.info(
            "CHK-EFUSE-IMG-WRITE: %d write-unlocked words hold their complement and "
            "%d write-locked words still hold the image after a complement write to "
            "every non-LOCKS word",
            self.unlocked_words,
            self.locked_words,
        )

        assert image.locks != 0, (
            f"{image.path.name} senses LOCKS = 0, so a write of 0 cannot tell a "
            "set-only LOCKS from a plain read-write register"
        )
        sensed = [image.words[w] for w in LOCKS_WORDS]
        ones = [_WORD_MASK] * len(LOCKS_WORDS)
        for label, data, expected in (
            ("CLEAR", 0, sensed),
            ("SET", _WORD_MASK, ones),
            ("CLEAR_AFTER_SET", 0, ones),
        ):
            for word in LOCKS_WORDS:
                await self.csr_write(f"LOCKS_{label}_W{word}", word_addr(word), data)
            for word, exp in zip(LOCKS_WORDS, expected):
                await self.csr_read(f"LOCKS_{label}_RB_W{word}", word_addr(word), expected=exp)

        def _after_set(word: int) -> int:
            if word in LOCKS_WORDS:
                return _WORD_MASK
            return image.expect_read(word, _LOCKS_ALL_SET)

        observed = await self._sweep("LOCKED", _after_set)
        blocked = sum(observed[w] == EFUSE_BLOCKED_READ_DATA for w in DATA_WORDS)
        assert blocked == len(DATA_WORDS), (
            f"{blocked} of {len(DATA_WORDS)} non-LOCKS words returned the blocked "
            "signature under all-ones LOCKS"
        )
        cocotb.log.info(
            "CHK-EFUSE-IMG-LOCKS-SET-ONLY: LOCKS kept its sensed 0x%016x across a write "
            "of 0, read all-ones after a write of all-ones and kept all-ones across a "
            "second write of 0; all %d other words then read the blocked signature 0x%08x",
            image.locks,
            blocked,
            EFUSE_BLOCKED_READ_DATA,
        )

        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            "efuse image cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        sense_in_reset = int(dut.tb_fuse_sense_done.value)
        assert sense_in_reset == 0, (
            "tb_fuse_sense_done is still 1 with the cold reset asserted, so the "
            "sweep after release cannot show that sense ran again"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released("efuse image cold release")
        await self.wait_fuse_sense_done()
        self.content_compares.append(len(await self._sweep("RESENSE", image.expect_read)))
        cocotb.log.info(
            "CHK-EFUSE-IMG-RESENSE: tb_fuse_sense_done read 0 under the cold reset and "
            "set again after release; all %d words read back equal to %s, so the "
            "complement writes and the LOCKS set are gone from the shadow file",
            self.content_compares[-1],
            image.path.name,
        )

        self.assert_all_reachable(EXPECTED_ACCESSES, "EFUSE_IMAGE")
