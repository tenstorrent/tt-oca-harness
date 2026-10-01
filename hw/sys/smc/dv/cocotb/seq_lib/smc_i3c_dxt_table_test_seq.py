# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Device Address and Device Characteristic Table accesses on every I3C instance.

Each of the six I3C instances keeps its DAT and DCT in a single-port RAM in the
integration shell, whose read-valid flop is set by a read that reaches the
RAM. The I3C CSR window maps both tables (`registers.rdl`: `external DAT` at
0x400, `external DCT` at 0x800), and `smc_addr.h` places them per instance at
`SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR(i)` and `..._DCT_BASE_ADDR(i)`.

**DAT.** `DAT_structure.rdl` makes every field of an entry `sw = rw`, and
nothing writes the RAM before this leaf, so a four-state simulator reads it as X.
The sequence reads entry 0 of every instance, writes each instance a different
pattern over the declared fields, and then reads all six back. Each read must
return its own instance's pattern: a read answered without reaching the RAM, or
by another instance's RAM, fails. Each entry is then cleared and read back 0.

**DCT.** `DCT_structure.rdl` makes every field `sw = r`; the controller fills
the table during dynamic address assignment, which this bench does not run.
The table's content is therefore not specified: a four-state simulator reads
it as X, a two-state one as 0. The sequence reads entry 0 of every instance
twice, word by word. Each read must complete with RRESP OKAY, and the two passes
must agree bit by bit wherever both passes read a known value; an X matches
anything.

The SEP_IN master converts every read beat to an int and cannot represent X, so
the reads of unwritten entries -- the DAT before its write, and the DCT -- are
taken from `_RawReadTap`, which records each beat's RRESP and
data as sampled on the bus. The master is handed a copy with any unresolvable
data zeroed, and its return value is not used.
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
from cocotb.types import LogicArray

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


class _RawReadTap:
    """Record every SEP_IN read beat as sampled, before the master converts it."""

    def __init__(self, master) -> None:
        self.channel = master.read_if.r_channel
        self.width = len(self.channel.bus.rdata)
        self.beats: list[tuple[int, str]] = []

    def __enter__(self) -> _RawReadTap:
        # The sink's recv() resolves _recv per beat, after its queue wait, so a
        # receive already pending when the tap goes in still passes through it.
        release = self.channel._recv

        def _recv(beat):
            beat = release(beat)
            self.beats.append((int(beat.rresp), str(beat.rdata)))
            if not beat.rdata.is_resolvable:
                beat.rdata = LogicArray("0" * len(beat.rdata))
            return beat

        self.channel._recv = _recv
        return self

    def __exit__(self, *_exc) -> None:
        del self.channel._recv

    def word(self, addr: int) -> str:
        """The 32 data bits of the last beat for ``addr``, MSB first, X kept."""
        lsb = 8 * (addr % (self.width // 8))
        bits = self.beats[-1][1]
        return bits[self.width - lsb - 32 : self.width - lsb]


def _agree(first: str, second: str) -> tuple[bool, int]:
    """Bits known in both passes must match; return (agree, bits known in both)."""
    known = [(a, b) for a, b in zip(first, second) if a in "01" and b in "01"]
    return all(a == b for a, b in known), len(known)


def _holds(bits: str, pattern: int) -> bool:
    """True when every declared DAT bit is known in ``bits`` and equals ``pattern``."""
    for index, bit in enumerate(reversed(bits)):
        if DAT_MASK >> index & 1 and bit != str(pattern >> index & 1):
            return False
    return True


class smc_i3c_dxt_table_test_seq(SmcCsrSeq):
    """Write and read DAT entry 0, and read DCT entry 0, on every I3C instance."""

    def __init__(self, name: str = "smc_i3c_dxt_table_test_seq") -> None:
        super().__init__(name)
        self.dat_checked = 0
        self.dct_checked = 0
        self.dct_known_bits = 0

    async def _entry(self, tag: str, addr_of, instance: int, words: int) -> int:
        value = 0
        for word in range(words):
            got = await self.csr_read(f"{tag}{instance}_W{word}", addr_of(instance, word))
            value |= (got & 0xFFFF_FFFF) << (32 * word)
        return value

    async def _raw_entry(
        self, tap: _RawReadTap, tag: str, addr_of, instance: int, words_in_entry: int
    ) -> str:
        """Entry 0 of one instance's table as a bit string, MSB first, X kept."""
        words = []
        for word in range(words_in_entry):
            addr = addr_of(instance, word)
            tap.beats.clear()
            await self.csr_read(f"{tag}{instance}_W{word}", addr)
            assert len(tap.beats) == 1, (
                f"I3C{instance} {tag} word {word} @ 0x{addr:08x}: {len(tap.beats)} read beats "
                f"recorded for a single-beat read"
            )
            rresp = tap.beats[0][0]
            assert rresp == 0, (
                f"I3C{instance} {tag} word {word} @ 0x{addr:08x} completed with RRESP {rresp}, "
                f"not OKAY"
            )
            words.append(tap.word(addr))
        return "".join(reversed(words))

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

        with _RawReadTap(self.env.sys_axi_agent.driver.axi.backend) as tap:
            for i in instances:
                before = await self._raw_entry(tap, "DAT_BEFORE_I", dat_word, i, DAT_WORDS)
                assert not _holds(before, patterns[i]), (
                    f"I3C{i} DAT entry 0 already holds the pattern 0x{patterns[i]:016x} on every "
                    f"declared field (read {before}, MSB first), so the write-then-read below "
                    f"would not show the write"
                )
                await self._write_dat("DAT_PATTERN_I", i, patterns[i])
            for i in instances:
                got = await self._entry("DAT_READ_I", dat_word, i, DAT_WORDS)
                assert got & DAT_MASK == patterns[i], (
                    f"I3C{i} DAT entry 0 reads 0x{got:016x} over its declared fields "
                    f"(mask 0x{DAT_MASK:016x}); the write put 0x{patterns[i]:016x} there and "
                    f"every DAT field is sw = rw"
                )
                self.dat_checked += 1
            for i in instances:
                await self._write_dat("DAT_CLEAR_I", i, 0)
                cleared = await self._entry("DAT_CLEAR_RB_I", dat_word, i, DAT_WORDS)
                assert cleared & DAT_MASK == 0, (
                    f"I3C{i} DAT entry 0 reads 0x{cleared:016x} after being cleared"
                )

            for i in instances:
                first = await self._raw_entry(tap, "DCT_READ_A_I", dct_word, i, DCT_WORDS)
                second = await self._raw_entry(tap, "DCT_READ_B_I", dct_word, i, DCT_WORDS)
                agree, known = _agree(first, second)
                assert agree, (
                    f"I3C{i} DCT entry 0 read {first} and then {second} (MSB first); a bit "
                    f"known in both passes changed, and nothing in this bench runs dynamic "
                    f"address assignment, the only writer of the DCT"
                )
                self.dct_known_bits += known
                self.dct_checked += 1

        cocotb.log.info(
            "CHK-I3C-DAT-TABLE-RW: DAT entry 0 of each of the %d I3C instances took its own "
            "%d-bit pattern over the fields DAT_structure.rdl declares (mask 0x%016x), all "
            "instances read back their own pattern after all six were written, and each entry was "
            "then cleared and read back 0",
            self.dat_checked,
            DAT_BITS,
            DAT_MASK,
        )
        cocotb.log.info(
            "CHK-I3C-DCT-TABLE-READ: DCT entry 0 of each of the %d I3C instances was read "
            "twice as %d words through the I3C CSR window, every read completing with RRESP "
            "OKAY, and the two passes agreed on all %d bits known in both (of %d read)",
            self.dct_checked,
            DCT_WORDS,
            self.dct_known_bits,
            self.dct_checked * DCT_BITS,
        )
