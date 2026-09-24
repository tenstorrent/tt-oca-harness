# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Device Address and Device Characteristic Table accesses on every I3C instance.

Each of the six I3C instances keeps its DAT and DCT in a single-port RAM in the
integration shell, whose read-valid flop is set by a read that reaches the
RAM. The I3C CSR window maps both tables (`registers.rdl`: `external DAT` at
0x400, `external DCT` at 0x800), and `smc_addr.h` places them per instance at
`SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR(i)` and `..._DCT_BASE_ADDR(i)`.

**DAT.** `DAT_structure.rdl` makes every field of an entry `sw = rw`. The
sequence records entry 0 of every instance, writes each instance a different
pattern over the declared fields, and then reads all six back. Each read must
return its own instance's pattern: a read answered without reaching the RAM, or
by another instance's RAM, fails. The recorded entries are then restored.

**DCT.** `DCT_structure.rdl` makes every field `sw = r`; the controller fills
the table during dynamic address assignment, which this bench does not run.
The table's content is therefore not specified, and the sequence reads entry 0
of every instance twice, word by word, and requires each read to complete OKAY
and the two passes to agree.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_I3C_RDL = (
    (Path(__file__).resolve().parents[6] / "vendor" / "chipsalliance" / "i3c-core" / "upstream")
    / "src"
    / "rdl"
)
_FIELD_RE = re.compile(r"\}\s*(\w+)\s*\[(\d+):(\d+)\]\s*;")
_REGWIDTH_RE = re.compile(r"regwidth\s*=\s*(\d+)\s*;")


def _structure(name: str) -> tuple[int, int]:
    """Return ``(declared field mask, entry width in bits)`` from an I3C table RDL."""
    text = (_I3C_RDL / f"{name}.rdl").read_text(encoding="utf-8")
    width = int(_REGWIDTH_RE.search(text).group(1))
    mask = 0
    for _field, msb, lsb in _FIELD_RE.findall(text):
        mask |= ((1 << (int(msb) - int(lsb) + 1)) - 1) << int(lsb)
    assert mask, f"{name}.rdl declares no field"
    return mask, width


DAT_MASK, DAT_BITS = _structure("DAT_structure")
_DCT_MASK, DCT_BITS = _structure("DCT_structure")
DAT_WORDS = DAT_BITS // 32
DCT_WORDS = DCT_BITS // 32
NUM_I3C = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_NUM")
assert NUM_I3C == smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DCT_NUM")


def dat_word(instance: int, word: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR", instance) + 4 * word


def dct_word(instance: int, word: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DCT_BASE_ADDR", instance) + 4 * word


def dat_pattern(instance: int) -> int:
    """A DAT entry value over the declared fields, different for every instance."""
    raw = 0x5A3C_96F0_A5C3_690F ^ (0x0101_0101_0101_0101 * (instance + 1))
    return raw & DAT_MASK


class smc_i3c_dxt_table_test_seq(SmcCsrSeq):
    """Write and read DAT entry 0, and read DCT entry 0, on every I3C instance."""

    def __init__(self, name: str = "smc_i3c_dxt_table_test_seq") -> None:
        super().__init__(name)
        self.dat_checked = 0
        self.dct_checked = 0

    async def _entry(self, tag: str, addr_of, instance: int, words: int) -> int:
        value = 0
        for word in range(words):
            got = await self.csr_read(f"{tag}{instance}_W{word}", addr_of(instance, word))
            value |= (got & 0xFFFF_FFFF) << (32 * word)
        return value

    async def _write_dat(self, tag: str, instance: int, value: int) -> None:
        for word in range(DAT_WORDS):
            await self.csr_write(
                f"{tag}{instance}_W{word}",
                dat_word(instance, word),
                (value >> (32 * word)) & 0xFFFF_FFFF,
            )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        instances = range(NUM_I3C)
        patterns = [dat_pattern(i) for i in instances]
        assert len(set(patterns)) == NUM_I3C, "two instances share a DAT pattern"

        saved = [await self._entry("DAT_SAVE_I", dat_word, i, DAT_WORDS) for i in instances]
        for i in instances:
            assert patterns[i] != saved[i] & DAT_MASK, (
                f"I3C{i} DAT entry 0 already holds the pattern 0x{patterns[i]:016x}, so the "
                f"write-then-read below would not show the write"
            )
            await self._write_dat("DAT_PATTERN_I", i, patterns[i])
        for i in instances:
            got = await self._entry("DAT_READ_I", dat_word, i, DAT_WORDS)
            assert got & DAT_MASK == patterns[i], (
                f"I3C{i} DAT entry 0 reads 0x{got:016x} over its declared fields "
                f"(mask 0x{DAT_MASK:016x}); the write put 0x{patterns[i]:016x} there and every "
                f"DAT field is sw = rw"
            )
            self.dat_checked += 1
        for i in instances:
            await self._write_dat("DAT_RESTORE_I", i, saved[i])
            restored = await self._entry("DAT_RESTORE_RB_I", dat_word, i, DAT_WORDS)
            assert restored & DAT_MASK == saved[i] & DAT_MASK, (
                f"I3C{i} DAT entry 0 reads 0x{restored:016x} after restoring 0x{saved[i]:016x}"
            )

        for i in instances:
            first = await self._entry("DCT_READ_A_I", dct_word, i, DCT_WORDS)
            second = await self._entry("DCT_READ_B_I", dct_word, i, DCT_WORDS)
            assert first == second, (
                f"I3C{i} DCT entry 0 read 0x{first:032x} and then 0x{second:032x}; nothing "
                f"in this bench runs dynamic address assignment, the only writer of the DCT"
            )
            self.dct_checked += 1

        cocotb.log.info(
            "CHK-I3C-DAT-TABLE-RW: DAT entry 0 of each of the %d I3C instances took its own "
            "%d-bit pattern over the fields DAT_structure.rdl declares (mask 0x%016x), all "
            "instances read back their own pattern after all six were written, and each entry was "
            "restored and read back",
            self.dat_checked,
            DAT_BITS,
            DAT_MASK,
        )
        cocotb.log.info(
            "CHK-I3C-DCT-TABLE-READ: DCT entry 0 of each of the %d I3C instances was read "
            "twice as %d words through the I3C CSR window, every read completing, and the two "
            "passes agreed",
            self.dct_checked,
            DCT_WORDS,
        )
