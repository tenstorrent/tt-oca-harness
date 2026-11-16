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
data zeroed, and its return value is not used. Each of those reads is declared
to the AXI monitor, which exempts its beats from the X rules; every other read
of the leaf is judged. The leaf counts the reads it declares and fails when the
monitor's exempt AR and exempt beat tallies are not exactly that count, so an
exemption that covered any undeclared beat is caught. On VCS every DCT bit reads
X, so the two DCT passes agree on zero bits and CHK-I3C-DCT-TABLE-READ grades
only the RRESP of each read there.

**Window aliases.** `memmap.adoc` states that only 16 entries of each table
are implemented, that index decoding keeps four bits so higher window slots
alias lower entries (DAT slot 16 at 0x480 aliases slot 0 at 0x400, DCT slot 16
at 0x900 aliases slot 0 at 0x800), and `oca_i3c_wrap.rdl` adds that DCT writes
are dropped. On every instance the leaf writes DAT entry 0 and reads it back
through slot 16, writes slot 16 and reads entry 0, and clears both; a window
slot with storage of its own, or one that does not reach entry 0, fails it.
It then writes the first word of DCT entry 0 and of DCT slot 16 and reads both
raw: each must still agree with the pre-write pass on every bit known in both,
and neither may hold the written word, so a write that lands in either slot
fails it.
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
#: The first window slot past the 16 implemented entries (memmap.adoc: DAT slot
#: 16 at 0x480 aliases slot 0 at 0x400, DCT slot 16 at 0x900 aliases slot 0 at 0x800).
ALIAS_SLOT = 16
DAT_ALIAS_OFFSET = ALIAS_SLOT * (DAT_BITS // 8)
DCT_ALIAS_OFFSET = ALIAS_SLOT * (DCT_BITS // 8)
assert (DAT_ALIAS_OFFSET, DCT_ALIAS_OFFSET) == (0x80, 0x100)
DCT_WRITE_WORD = 0xA5C3_1E7B
NUM_I3C = smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_NUM")
assert NUM_I3C == smc_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DCT_NUM")


def dat_word(instance: int, word: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DAT_BASE_ADDR", instance) + 4 * word


def dct_word(instance: int, word: int) -> int:
    return smc_indexed_addr("SMC_TOP_OCA_I3C_WRAP_I3C_CSR_DCT_BASE_ADDR", instance) + 4 * word


def dat_alias_word(instance: int, word: int) -> int:
    return dat_word(instance, word) + DAT_ALIAS_OFFSET


def dct_alias_word(instance: int, word: int) -> int:
    return dct_word(instance, word) + DCT_ALIAS_OFFSET


def dat_pattern(instance: int) -> int:
    """A DAT entry value over the declared fields, different for every instance."""
    raw = 0x5A3C_96F0_A5C3_690F ^ (0x0101_0101_0101_0101 * (instance + 1))
    return raw & DAT_MASK


def dat_alias_pattern(instance: int) -> int:
    """A second DAT entry value per instance, written through the aliasing slot."""
    return (~dat_pattern(instance) ^ (0x1010_1010_1010_1010 * (instance + 1))) & DAT_MASK


def _word0(bits: str) -> str:
    """The lowest 32 bits of an entry read MSB first."""
    return bits[-32:]


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
        self.declared_reads = 0
        self.dat_aliased = 0
        self.dct_dropped = 0
        self.dct_after_known_bits = 0

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
            with self.env.axi_monitor.declared_unknown_rdata():
                await self.csr_read(f"{tag}{instance}_W{word}", addr)
            self.declared_reads += 1
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

    async def _write_dat(self, tag: str, instance: int, value: int, addr_of=dat_word) -> None:
        for word in range(DAT_WORDS):
            await self.csr_write(
                f"{tag}{instance}_W{word}",
                addr_of(instance, word),
                (value >> (32 * word)) & 0xFFFF_FFFF,
            )

    async def _dat_alias(self, i: int) -> None:
        pattern, alias = dat_pattern(i), dat_alias_pattern(i)
        assert pattern != alias and alias & DAT_MASK, f"I3C{i}: the alias pattern is not distinct"
        await self._write_dat("DAT_ALIAS_SRC_I", i, pattern)
        via_alias = await self._entry("DAT_ALIAS_RD16_I", dat_alias_word, i, DAT_WORDS)
        assert via_alias & DAT_MASK == pattern, (
            f"I3C{i} DAT slot {ALIAS_SLOT} (+0x{DAT_ALIAS_OFFSET:x}) reads 0x{via_alias:016x} "
            f"after entry 0 took 0x{pattern:016x}; memmap.adoc states slot {ALIAS_SLOT} aliases "
            f"slot 0"
        )
        await self._write_dat("DAT_ALIAS_WR16_I", i, alias, dat_alias_word)
        via_entry = await self._entry("DAT_ALIAS_RD0_I", dat_word, i, DAT_WORDS)
        assert via_entry & DAT_MASK == alias, (
            f"I3C{i} DAT entry 0 reads 0x{via_entry:016x} after slot {ALIAS_SLOT} took "
            f"0x{alias:016x}; a write through the aliasing slot lands in entry 0"
        )
        await self._write_dat("DAT_ALIAS_CLEAR_I", i, 0)
        for tag, addr_of in (("DAT_ALIAS_CLR0_I", dat_word), ("DAT_ALIAS_CLR16_I", dat_alias_word)):
            cleared = await self._entry(tag, addr_of, i, DAT_WORDS)
            assert cleared & DAT_MASK == 0, (
                f"I3C{i} {tag}: reads 0x{cleared:016x} after entry 0 was cleared"
            )
        self.dat_aliased += 1

    async def _dct_write_dropped(self, tap: _RawReadTap, i: int, before: str) -> None:
        for tag, addr_of in (("DCT_WR0_I", dct_word), ("DCT_WR16_I", dct_alias_word)):
            await self.csr_write(f"{tag}{i}", addr_of(i, 0), DCT_WRITE_WORD)
        for tag, addr_of in (("DCT_AFTER0_I", dct_word), ("DCT_AFTER16_I", dct_alias_word)):
            after = await self._raw_entry(tap, tag, addr_of, i, DCT_WORDS)
            agree, known = _agree(before, after)
            assert agree, (
                f"I3C{i} {tag}: DCT read {after} (MSB first) after the writes, which differs on "
                f"a bit known in both from the pre-write read {before}; DCT writes are dropped"
            )
            assert _word0(after) != f"{DCT_WRITE_WORD:032b}", (
                f"I3C{i} {tag}: DCT word 0 holds the written 0x{DCT_WRITE_WORD:08x}; DCT writes "
                f"are dropped"
            )
            self.dct_after_known_bits += known
        dat0 = await self._entry("DCT_DAT0_AFTER_I", dat_word, i, DAT_WORDS)
        assert dat0 & DAT_MASK == 0, (
            f"I3C{i} DAT entry 0 reads 0x{dat0:016x} after the DCT writes; it was cleared "
            f"before them and a dropped DCT write lands nowhere"
        )
        self.dct_dropped += 1

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
                await self._dat_alias(i)

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
                await self._dct_write_dropped(tap, i, second)

        cocotb.log.info(
            "CHK-I3C-DAT-ALIAS-16: on each of the %d I3C instances DAT entry 0 written at its "
            "own offset read back through slot %d (+0x%x) and a write through slot %d read back "
            "at entry 0, after which both read 0 once entry 0 was cleared",
            self.dat_aliased,
            ALIAS_SLOT,
            DAT_ALIAS_OFFSET,
            ALIAS_SLOT,
        )
        cocotb.log.info(
            "CHK-I3C-DCT-WRITE-DROPPED: on each of the %d I3C instances a write of 0x%08x to the "
            "first word of DCT entry 0 and of DCT slot %d (+0x%x) completed, both slots read "
            "back agreeing with the pre-write pass on every bit known in both (%d bits known "
            "in both over all post-write reads, of %d read) with neither holding the written "
            "word, and the cleared DAT entry 0 still read 0",
            self.dct_dropped,
            DCT_WRITE_WORD,
            ALIAS_SLOT,
            DCT_ALIAS_OFFSET,
            self.dct_after_known_bits,
            self.dct_dropped * 2 * DCT_BITS,
        )
        cocotb.log.info(
            "CHK-I3C-DAT-TABLE-RW: DAT entry 0 of each of the %d I3C instances took its own "
            "%d-bit pattern over the fields DAT_structure.rdl declares (mask 0x%016x), all "
            "instances read back their own pattern after all six were written, and each entry was "
            "then cleared and read back 0",
            self.dat_checked,
            DAT_BITS,
            DAT_MASK,
        )
        monitor = self.env.axi_monitor
        assert monitor.ar_exempt == self.declared_reads, (
            f"the AXI monitor exempted {monitor.ar_exempt} ARs but the leaf declared "
            f"{self.declared_reads} reads as observed-only"
        )
        assert monitor.r_beats_exempt == self.declared_reads, (
            f"the AXI monitor exempted {monitor.r_beats_exempt} R beats but the leaf declared "
            f"{self.declared_reads} single-beat reads as observed-only"
        )
        cocotb.log.info(
            "CHK-I3C-DCT-TABLE-READ: DCT entry 0 of each of the %d I3C instances was read "
            "twice as %d words through the I3C CSR window, every read completing with RRESP "
            "OKAY, and the two passes agreed on all %d bits known in both (of %d read); "
            "%d single-beat raw reads (DAT before its write, and both DCT passes) were declared "
            "to the AXI monitor as observed-only and it exempted exactly %d ARs and %d R beats, "
            "one per declared read; every other beat was judged",
            self.dct_checked,
            DCT_WORDS,
            self.dct_known_bits,
            self.dct_checked * DCT_BITS,
            self.declared_reads,
            monitor.ar_exempt,
            monitor.r_beats_exempt,
        )
