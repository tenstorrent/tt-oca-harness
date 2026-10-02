# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sense a fully populated eFuse image and sweep every SMC_EFUSE_MAP word.

**Proof class: transport and lock enforcement.** The bank behind the sense is
the adopter's simulation stand-in for the OTP macro
(``hw/ip/efuse/dv/models/efuse_bank_model.sv``), which ``$readmemh``s the image
named by ``+smc_efuse_hex`` when its reset releases. Everything compared below
travels the real path: the sense FSM in ``efuse_shadow_regs.sv`` streams every
fuse word into the shadow file, and SEP_IN AXI reads it back through the
SMC fabric and the shadow-register lock checks. Nothing here claims fuse
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
  no lock of its own. Every other region follows its LOCKS bits: the RDL LOCKS
  description says a write-locked field "is not programmable" and a read-locked
  shadow register "is not readable", and ``architecture.adoc`` line 233 gives
  ``lock[0] = 1`` as read-locked. Neither states the response code or the word a
  read-locked read returns, so a read-locked read is held to non-disclosure only:
  its data must differ from both values the word could hold, and its response
  code is recorded, not asserted.

**Scenario.** Sense; read all 256 words. Write the complement of every non-LOCKS
word, then read them all: a write-unlocked word holds the complement, a
write-locked one still holds the image. Every image senses a non-zero LOCKS, so
a write of 0 is a real clear attempt: LOCKS must keep its sensed value, read
all-ones after a write of all-ones, and keep all-ones across a second write of
0. A sweep of all 256 words then reads LOCKS as all-ones and every other word
without disclosing it. Cold
reset, observe sense restart, and read all 256 words against the image once
more -- the shadow writes above are gone because the shadow file is reloaded
from the bank.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import cocotb
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_vip_utils import (
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


def load_image(path: Path) -> EfuseImage:
    words = efuse_preload_words(path)
    assert len(words) == EFUSE_MAP_WORDS, (
        f"{path} holds {len(words)} words; SMC_EFUSE_MAP is {EFUSE_MAP_WORDS} words"
    )
    return EfuseImage(path, words)


_SCHEMA = _REPO / "hw" / "sys" / "smc" / "dv" / "efuse_preload" / "efuse_schema.toml"


def check_schema_against_map() -> int:
    """Fail if the generator's schema disagrees with the generated register map.

    ``generate_efuse_preload.py`` lays the schema blocks out in file order and
    gives the ``i``-th block after LOCKS the LOCKS bits ``2i`` / ``2i+1``. Each
    block's bit offset and width, and each lock bit, is compared with the
    generated ``smc_addr.h`` / ``blocks/smc_efuse_map.h`` symbols. Returns the
    number of blocks checked.
    """
    with _SCHEMA.open("rb") as handle:
        schema = tomllib.load(handle)

    def _array(name: str) -> tuple[int, int]:
        sym = f"SMC_TOP_SMC_EFUSE_MAP_{name}_BASE_ADDR"
        base = smc_indexed_addr(sym, 0)
        stride = smc_indexed_addr(sym, 1) - base
        return base, stride * smc_addr(f"SMC_TOP_SMC_EFUSE_MAP_{name}_NUM")

    def _single(name: str, next_base: int) -> tuple[int, int]:
        base = smc_addr(f"SMC_TOP_SMC_EFUSE_MAP_{name}_BASE_ADDR")
        return base, next_base - base

    i2c = _array("I2C_I3C_ID")
    spare = _array("SPARE")
    smc_config = smc_addr("SMC_TOP_SMC_EFUSE_MAP_SMC_CONFIG_BASE_ADDR")
    expected = {
        "LOCKS": _single("LOCKS", smc_addr("SMC_TOP_SMC_EFUSE_MAP_JTAG_PUBLIC_IDENTITY_BASE_ADDR")),
        "JTAG_PUBLIC_IDENTITY": _single("JTAG_PUBLIC_IDENTITY", i2c[0]),
        "I2C_I3C_ID": i2c,
        "SMC_CONFIG": _single(
            "SMC_CONFIG", smc_addr("SMC_TOP_SMC_EFUSE_MAP_OCCP_TRANSPORT_TIMEOUT_BASE_ADDR")
        ),
        "OCCP_TRANSPORT_TIMEOUT": _single("OCCP_TRANSPORT_TIMEOUT", spare[0]),
        "SPARE": spare,
    }
    assert smc_config == i2c[0] + i2c[1], "I2C_I3C_ID does not end at SMC_CONFIG"
    assert list(schema) == list(expected), (
        f"efuse_schema.toml blocks {list(schema)} are not the map's {list(expected)}"
    )
    offset = 0
    for slot, (block, (base, size)) in enumerate(expected.items()):
        width = schema[block]["regwidth"]
        assert (base - EFUSE_MAP_BASE) * 8 == offset and size * 8 == width, (
            f"efuse_schema.toml {block}: bit offset {offset} width {width}, map has "
            f"offset {(base - EFUSE_MAP_BASE) * 8} width {size * 8}"
        )
        offset += width
        if block == "LOCKS":
            continue
        lock_name = "SPARE0" if block == "SPARE" else block
        for kind, bit in (("WRITE", 2 * (slot - 1)), ("READ", 2 * (slot - 1) + 1)):
            assert _lock(lock_name, kind) == 1 << bit, (
                f"generate_efuse_preload.py puts {block}'s {kind.lower()} lock at LOCKS bit "
                f"{bit}; the map has mask 0x{_lock(lock_name, kind):x}"
            )
    assert offset == EFUSE_MAP_SIZE * 8, f"schema totals {offset} bits, map is {EFUSE_MAP_SIZE * 8}"
    return len(expected)


def word_addr(word: int) -> int:
    return EFUSE_MAP_BASE + 4 * word


#: SEP_IN AXI accesses one run issues: three 256-word read sweeps, a complement
#: write and a readback of every non-LOCKS word, and three write-then-readback
#: rounds over the LOCKS words in the set-only leg.
EXPECTED_ACCESSES = 3 * EFUSE_MAP_WORDS + 2 * len(DATA_WORDS) + 3 * 2 * len(LOCKS_WORDS)
#: Of those, the reads that carry an exact expectation: every read except the
#: read-locked reads of the non-LOCKS words, which are held to non-disclosure.
EXPECTED_VALUE_CHECKS = (
    2 * EFUSE_MAP_WORDS + len(DATA_WORDS) + 3 * len(LOCKS_WORDS) + len(LOCKS_WORDS)
)


class smc_efuse_image_pattern_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """Full-map sweep, complement write, LOCKS set-only, cold-reset re-sense."""

    def __init__(self, name: str = "smc_efuse_image_pattern_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.dispatch_reset = None
        #: Read-locked reads checked for non-disclosure, and their response codes.
        self.nondisclosure_checks = 0
        self.locked_read_resps: set[int] = set()
        self.unlocked_words = 0
        self.locked_words = 0

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        await self.dispatch_reset(item)

    async def _sweep(self, label: str, words: tuple[int, ...]) -> None:
        for word in range(EFUSE_MAP_WORDS):
            await self.csr_read(f"{label}_W{word}", word_addr(word), expected=words[word])

    async def _read_locked(self, label: str, word: int) -> int:
        """A read the lock may refuse: data returned, response code not asserted."""
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = word_addr(word)
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: the read-locked read got no response"
        self.locked_read_resps.add(item.resp_code)
        return item.rdata & _WORD_MASK

    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        dut = cocotb.top

        assert not any(image.read_locked(w) for w in DATA_WORDS), (
            f"{image.path.name} read-locks a word; every sweep compares content"
        )
        await self.wait_fuse_sense_done()
        await self._sweep("SENSE", image.words)
        cocotb.log.info(
            "CHK-EFUSE-IMG-SENSE: all %d SMC_EFUSE_MAP words read back equal to %s "
            "after the first sense",
            EFUSE_MAP_WORDS,
            image.path.name,
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

        for word in range(EFUSE_MAP_WORDS):
            if word in LOCKS_WORDS:
                await self.csr_read(f"LOCKED_W{word}", word_addr(word), expected=_WORD_MASK)
                continue
            got = await self._read_locked(f"LOCKED_W{word}", word)
            held = (image.words[word], ~image.words[word] & _WORD_MASK)
            assert got not in held, (
                f"read-locked word {word} @ 0x{word_addr(word):08x} returned 0x{got:08x}, "
                f"one of the values it can hold (image 0x{held[0]:08x}, complement "
                f"0x{held[1]:08x}); the read lock disclosed it"
            )
            self.nondisclosure_checks += 1
        assert self.nondisclosure_checks == len(DATA_WORDS), (
            f"{self.nondisclosure_checks} non-disclosure checks, expected {len(DATA_WORDS)}"
        )
        cocotb.log.info(
            "CHK-EFUSE-IMG-LOCKS-SET-ONLY: LOCKS kept its sensed 0x%016x across a write "
            "of 0, read all-ones after a write of all-ones and kept all-ones across a "
            "second write of 0; all %d other words, read-locked, then returned neither "
            "their image word nor its complement (response codes seen: %s, not asserted)",
            image.locks,
            self.nondisclosure_checks,
            sorted(self.locked_read_resps),
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
        await self._sweep("RESENSE", image.words)
        cocotb.log.info(
            "CHK-EFUSE-IMG-RESENSE: tb_fuse_sense_done read 0 under the cold reset and "
            "set again after release; all %d words read back equal to %s, so the "
            "complement writes and the LOCKS set are gone from the shadow file",
            EFUSE_MAP_WORDS,
            image.path.name,
        )

        self.assert_all_reachable(EXPECTED_ACCESSES, "EFUSE_IMAGE")
