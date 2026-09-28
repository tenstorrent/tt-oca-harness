# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Access sizes and write strobes on the Adams Bridge aperture.

no_cpu / +skip_fuse_sense. s_axi, one access at a time through the SEP AXI
sequencer, so the SEP scoreboard grades every response as well.

``hw/sys/sep/doc/adams_bridge.adoc`` ``[[abr-access-size]]`` states the rules:

* A 32-bit access reads or writes one register.
* A 64-bit access at an 8-byte-aligned address is carried out as two 32-bit
  accesses to the two registers it covers, low address first. A 64-bit access
  whose address has bit 2 set reaches only the upper register.
* Each word of a write is taken by its own strobe. A word whose strobe is empty
  is not written, so a 64-bit write that strobes one word writes that word
  alone, with OKAY. A word whose strobe is partial is not written, and the
  access is answered with SLVERR; in a 64-bit write the other word is still
  written when its strobe is full.
* A narrow read is performed as a read of the whole register that contains it.
  Only the bytes it names are returned; the other byte lanes read as zero.

``abr_top`` ties the register block's byte enables high and the AHB slave
zero-extends a narrow write, so a partial write that got through would
overwrite the rest of the register. Every refused write therefore targets a
register primed with a value that has a set bit in every byte it holds, and
writes the complement: a write that lands on any byte changes the readback.

Narrow reads, and 64-bit reads at addr[2]=1, are graded on the whole 64-bit R
beat that ``AbrBusWatch`` records on the ``s_axi`` pins as well as through the
VIP result, so a byte lane outside the access that is not zero fails.

Reads are graded on the identity words. Their values are not given by the RDL
or any SEP document, so ``CHK-ABR-ID-REF`` first reads each word alone at
AxSIZE=2 and every later read is compared against that capture. Writes use the
``global_intr_en_r`` / ``error_intr_en_r`` pair, the one 8-byte granule with a
read-write register in each half, and the 32-bit ``error_internal_intr_count_r``
counter, whose upper neighbour owns no register. Every register written here is
restored to the value it held on entry.

RANDCFG: the data values come from the run seed; every size, offset and
strobe pattern is walked on every seed.
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_abr_bus_seq import (
    ERROR_COUNT,
    ERROR_INTR_EN,
    GLOBAL_INTR_EN,
    IDENTITY_PAIRS,
    IDENTITY_WORDS,
    RESP_OKAY,
    RESP_SLVERR,
    RW_WORDS,
    AbrAccess,
    AbrBusWatch,
    AbrWord,
    SepAbrBus,
    identity_bytes,
)

BUS = "s_axi"

# Bound, in system clocks, on the watch recording the R beat of a read that
# has already returned.
BEAT_WAIT_CYCLES = 4

# Partial-word strobes within one 32-bit word as (byte offset, byte count,
# AxSIZE). The VIP derives WSTRB from address and length: bytes 0..3 alone,
# the two halfwords, and the two three-byte runs.
PARTIAL_RUNS: tuple[tuple[int, int, int], ...] = (
    (0, 1, 0),
    (1, 1, 0),
    (2, 1, 0),
    (3, 1, 0),
    (0, 2, 1),
    (2, 2, 1),
    (0, 3, 2),
    (1, 3, 2),
)


def _strobe(addr: int, nbytes: int) -> int:
    """WSTRB on the 64-bit bus for ``nbytes`` at ``addr``."""
    return ((1 << nbytes) - 1) << (addr & 7)


def _in_lanes(addr: int, value: int) -> int:
    """The 64-bit R beat that carries ``value`` at ``addr`` and zero on every other lane."""
    return value << (8 * (addr & 7))


def _beat_txt(beat: int | None) -> str:
    if beat is None:
        return "no single R beat recorded"
    if beat < 0:
        return "R beat X/Z"
    return f"R beat 0x{beat:016x}"


def _selftest() -> None:
    strobes = {_strobe(off, n) for off, n, _size in PARTIAL_RUNS}
    assert strobes == {0x1, 0x2, 0x4, 0x8, 0x3, 0xC, 0x7, 0xE}, strobes
    assert _strobe(ERROR_INTR_EN.addr, 4) == 0xF0
    assert _strobe(GLOBAL_INTR_EN.addr, 7) == 0x7F
    assert _strobe(GLOBAL_INTR_EN.addr + 2, 6) == 0xFC
    assert _in_lanes(0x1094_000D, 0xA5) == 0x0000_A500_0000_0000


_selftest()


class SepAbrAccessSizeCfg:
    """RANDCFG: the data values each write uses. Coverage is fixed."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        # A value with a set bit in every byte, so a write that lands on any
        # byte of the register moves it.
        self.count_prime = 0
        while any(((self.count_prime >> (8 * i)) & 0xFF) in (0x00, 0xFF) for i in range(4)):
            self.count_prime = rng.getrandbits(32)
        self.count_words = [rng.getrandbits(32) for _ in range(4)]
        self.upper_junk = rng.getrandbits(32) | 1

    def summary(self) -> str:
        return (
            f"seed={self.seed} count_prime=0x{self.count_prime:08x} "
            f"count_words={[hex(w) for w in self.count_words]}"
        )


@pyuvm.test()
class sep_abr_access_size_test(sep_base_test):
    """ABR 64-bit, narrow and partial-strobe accesses follow [[abr-access-size]]."""

    required_evidence = (
        "CHK-ABR-ID-REF",
        "CHK-ABR-SIZE-RD32",
        "CHK-ABR-SIZE-RD64",
        "CHK-ABR-SIZE-RD64-UNALIGNED",
        "CHK-ABR-SIZE-RD-NARROW",
        "CHK-ABR-SIZE-WR32",
        "CHK-ABR-SIZE-WR64-FULL",
        "CHK-ABR-SIZE-WR64-LO",
        "CHK-ABR-SIZE-WR64-HI",
        "CHK-ABR-SIZE-WR32-HI",
        "CHK-ABR-SIZE-WR-PARTIAL",
        "CHK-ABR-SIZE-WR64-MIXED",
        "CHK-ABR-SIZE-RD-NARROW-RW",
        "CHK-ABR-SIZE-RESTORE",
    )

    async def _rd(self, addr: int, nbytes: int = 4, size: int = 2) -> AbrAccess:
        acc = await self.abr.one(AbrAccess(BUS, "rd", addr, nbytes, size))
        self.logger.info("ABR-SIZE %s", acc.describe())
        return acc

    async def _wr(
        self, addr: int, data: int, nbytes: int = 4, size: int = 2, *, refused: bool = False
    ) -> AbrAccess:
        acc = await self.abr.one(
            AbrAccess(BUS, "wr", addr, nbytes, size, wdata=data), refused=refused
        )
        self.logger.info("ABR-SIZE %s strb=0x%02x", acc.describe(), _strobe(addr, nbytes))
        return acc

    async def _rd_beat(self, addr: int, nbytes: int, size: int) -> tuple[AbrAccess, int | None]:
        """A read, and the whole 64-bit R beat the ``s_axi`` pins carried for it."""
        rec = self.watch.rec[BUS]
        seen = len(rec.r)
        acc = await self._rd(addr, nbytes=nbytes, size=size)
        # The test can resume on the R handshake edge before the watch has
        # recorded that edge.
        for _ in range(BEAT_WAIT_CYCLES):
            if len(rec.r) > seen:
                break
            await RisingEdge(self.clk)
        beats = rec.r[seen:]
        return acc, beats[0][3] if len(beats) == 1 else None

    async def _word(self, reg: AbrWord) -> int:
        acc = await self._rd(reg.addr)
        assert acc.resp == RESP_OKAY, f"readback of {reg.name} returned {acc.resp_name}"
        data: int = acc.data
        return data

    async def _set(self, reg: AbrWord, value: int) -> None:
        """Write one register at full width and require it to read back."""
        acc = await self._wr(reg.addr, value)
        got = await self._word(reg)
        assert acc.resp == RESP_OKAY and got == value & reg.mask, (
            f"{reg.name}: 32-bit write of 0x{value:08x} answered {acc.resp_name} and read "
            f"back 0x{got:08x}, expected 0x{value & reg.mask:08x}"
        )

    async def run_scenario(self) -> None:
        cfg = SepAbrAccessSizeCfg(self.random_seed())
        self.logger.info("abr access size: %s", cfg.summary())
        await self.bring_up_no_cpu()
        self.abr = SepAbrBus(self)
        await self.abr.capture_identity(BUS)
        top: Any = cocotb.top
        self.clk = top.clk_i
        self.watch = AbrBusWatch((BUS,))
        self.watch.start()

        try:
            entry = {reg.addr: await self._word(reg) for reg in RW_WORDS}
            self.logger.info(
                "ABR-SIZE entry values: %s",
                " ".join(f"{r.name}=0x{entry[r.addr]:08x}" for r in RW_WORDS),
            )

            await self._reads()
            await self._full_word_writes(cfg)
            await self._wide_writes(cfg)
            await self._partial_writes(cfg)
            await self._narrow_rw_reads(cfg)
        finally:
            self.watch.stop()

        # --- CHK-ABR-SIZE-RESTORE ---------------------------------------------
        for reg in RW_WORDS:
            await self._set(reg, entry[reg.addr])
        self.logger.info(
            "CHK-ABR-SIZE-RESTORE PASS: %d registers read back their entry values",
            len(RW_WORDS),
        )

    async def _reads(self) -> None:
        # --- CHK-ABR-SIZE-RD32 ------------------------------------------------
        for w in IDENTITY_WORDS:
            acc = await self._rd(w.addr)
            assert acc.resp == RESP_OKAY and acc.data == w.value, (
                f"CHK-ABR-SIZE-RD32 FAIL: {w.name} returned {acc.resp_name} "
                f"0x{acc.data:08x}, expected 0x{w.value:08x}"
            )
        self.logger.info(
            "CHK-ABR-SIZE-RD32 PASS: %d identity words each read their captured value at AxSIZE=2",
            len(IDENTITY_WORDS),
        )

        # --- CHK-ABR-SIZE-RD64 ------------------------------------------------
        pairs = list(IDENTITY_PAIRS)
        for lo, hi in pairs:
            acc = await self._rd(lo.addr, nbytes=8, size=3)
            want = (hi.value << 32) | lo.value
            assert acc.resp == RESP_OKAY and acc.data == want, (
                f"CHK-ABR-SIZE-RD64 FAIL: 64-bit read at {lo.name} returned "
                f"{acc.resp_name} 0x{acc.data:016x}, expected {{{hi.name},{lo.name}}} "
                f"= 0x{want:016x}"
            )
        self.logger.info(
            "CHK-ABR-SIZE-RD64 PASS: %d 64-bit reads each returned {high word, low word} "
            "of the two registers they cover",
            len(pairs),
        )

        # --- CHK-ABR-SIZE-RD64-UNALIGNED --------------------------------------
        # AxSIZE=3 at an address with addr[2]=1: the transfer covers one
        # register, the upper half of the granule.
        for _lo, hi in pairs:
            acc, beat = await self._rd_beat(hi.addr, nbytes=4, size=3)
            want_beat = _in_lanes(hi.addr, hi.value)
            assert acc.resp == RESP_OKAY and acc.data == hi.value and beat == want_beat, (
                f"CHK-ABR-SIZE-RD64-UNALIGNED FAIL: AxSIZE=3 read at {hi.name} "
                f"(0x{hi.addr:08x}) returned {acc.resp_name} 0x{acc.data:08x} in "
                f"{_beat_txt(beat)}, expected 0x{hi.value:08x} in R beat 0x{want_beat:016x}"
            )
        self.logger.info(
            "CHK-ABR-SIZE-RD64-UNALIGNED PASS: %d AxSIZE=3 reads starting at the upper "
            "word returned that word, with the lower four byte lanes of the R beat zero",
            len(pairs),
        )

        # --- CHK-ABR-SIZE-RD-NARROW -------------------------------------------
        cells = 0
        for lo, _hi in pairs[:2]:
            for size, nbytes in ((0, 1), (1, 2)):
                for off in range(0, 8, nbytes):
                    addr = lo.addr + off
                    acc, beat = await self._rd_beat(addr, nbytes, size)
                    want = identity_bytes(addr, nbytes)
                    want_beat = _in_lanes(addr, want)
                    assert acc.resp == RESP_OKAY and acc.data == want and beat == want_beat, (
                        f"CHK-ABR-SIZE-RD-NARROW FAIL: {nbytes}-byte read at 0x{addr:08x} "
                        f"returned {acc.resp_name} 0x{acc.data:0{2 * nbytes}x} in "
                        f"{_beat_txt(beat)}, expected 0x{want:0{2 * nbytes}x} in R beat "
                        f"0x{want_beat:016x}"
                    )
                    cells += 1
        self.logger.info(
            "CHK-ABR-SIZE-RD-NARROW PASS: %d byte and halfword reads over the ML-DSA "
            "NAME and VERSION granules each returned the addressed bytes, with every other "
            "byte lane of the R beat zero",
            cells,
        )

    async def _full_word_writes(self, cfg: SepAbrAccessSizeCfg) -> None:
        # --- CHK-ABR-SIZE-WR32 ------------------------------------------------
        # Each register walked to its all-ones mask and back to zero, so a
        # register that stores nothing cannot pass.
        for reg in (GLOBAL_INTR_EN, ERROR_INTR_EN):
            await self._set(reg, reg.mask)
            await self._set(reg, 0)
        for word in cfg.count_words:
            await self._set(ERROR_COUNT, word)
        self.logger.info(
            "CHK-ABR-SIZE-WR32 PASS: 32-bit writes land on %s, %s and %s",
            GLOBAL_INTR_EN.name,
            ERROR_INTR_EN.name,
            ERROR_COUNT.name,
        )

    async def _pair(self) -> tuple[int, int]:
        acc = await self._rd(GLOBAL_INTR_EN.addr, nbytes=8, size=3)
        assert acc.resp == RESP_OKAY, f"64-bit read of the pair returned {acc.resp_name}"
        return acc.data & 0xFFFF_FFFF, acc.data >> 32

    async def _wide_writes(self, cfg: SepAbrAccessSizeCfg) -> None:
        lo_reg, hi_reg = GLOBAL_INTR_EN, ERROR_INTR_EN
        base = lo_reg.addr

        # --- CHK-ABR-SIZE-WR64-FULL -------------------------------------------
        await self._set(lo_reg, 0)
        await self._set(hi_reg, 0)
        acc = await self._wr(base, (hi_reg.mask << 32) | lo_reg.mask, nbytes=8, size=3)
        lo, hi = await self._word(lo_reg), await self._word(hi_reg)
        pair = await self._pair()
        assert acc.resp == RESP_OKAY and (lo, hi) == (lo_reg.mask, hi_reg.mask) == pair, (
            f"CHK-ABR-SIZE-WR64-FULL FAIL: 64-bit write of {{0x{hi_reg.mask:x},"
            f"0x{lo_reg.mask:x}}} at 0x{base:08x} answered {acc.resp_name}; words read "
            f"back lo=0x{lo:08x} hi=0x{hi:08x}, 64-bit read {pair}"
        )
        # The counter's upper neighbour owns no register: its half of the beat
        # is discarded and it reads zero, while the low half lands whole.
        acc = await self._wr(
            ERROR_COUNT.addr, (cfg.upper_junk << 32) | cfg.count_prime, nbytes=8, size=3
        )
        cnt = await self._word(ERROR_COUNT)
        wide = await self._rd(ERROR_COUNT.addr, nbytes=8, size=3)
        assert acc.resp == RESP_OKAY and cnt == cfg.count_prime and wide.data == cnt, (
            f"CHK-ABR-SIZE-WR64-FULL FAIL: 64-bit write of 0x{cfg.count_prime:08x} to "
            f"{ERROR_COUNT.name} answered {acc.resp_name}; counter reads 0x{cnt:08x}, "
            f"64-bit read 0x{wide.data:016x}"
        )
        self.logger.info(
            "CHK-ABR-SIZE-WR64-FULL PASS: a full-strobe 64-bit write lands both words of "
            "the %s/%s pair, and all 32 bits of the low word on %s",
            lo_reg.name,
            hi_reg.name,
            ERROR_COUNT.name,
        )

        # --- CHK-ABR-SIZE-WR64-LO ---------------------------------------------
        # AxSIZE=3, WSTRB=0x0F: the upper word's half of the split beat has no
        # byte enabled and must complete without touching that register.
        acc = await self._wr(base, 0, nbytes=4, size=3)
        pair = await self._pair()
        assert acc.resp == RESP_OKAY and pair == (0, hi_reg.mask), (
            f"CHK-ABR-SIZE-WR64-LO FAIL: AxSIZE=3 WSTRB=0x0F write of 0 answered "
            f"{acc.resp_name}; pair reads lo=0x{pair[0]:x} hi=0x{pair[1]:x}, expected "
            f"lo=0 hi=0x{hi_reg.mask:x}"
        )
        self.logger.info(
            "CHK-ABR-SIZE-WR64-LO PASS: AxSIZE=3 WSTRB=0x0F wrote %s alone, OKAY, %s unchanged",
            lo_reg.name,
            hi_reg.name,
        )

        # --- CHK-ABR-SIZE-WR64-HI ---------------------------------------------
        await self._set(lo_reg, lo_reg.mask)
        acc = await self._wr(hi_reg.addr, 0, nbytes=4, size=3)
        pair = await self._pair()
        assert acc.resp == RESP_OKAY and pair == (lo_reg.mask, 0), (
            f"CHK-ABR-SIZE-WR64-HI FAIL: AxSIZE=3 WSTRB=0xF0 write of 0 at "
            f"0x{hi_reg.addr:08x} answered {acc.resp_name}; pair reads lo=0x{pair[0]:x} "
            f"hi=0x{pair[1]:x}, expected lo=0x{lo_reg.mask:x} hi=0"
        )
        self.logger.info(
            "CHK-ABR-SIZE-WR64-HI PASS: AxSIZE=3 WSTRB=0xF0 wrote %s alone, OKAY, %s unchanged",
            hi_reg.name,
            lo_reg.name,
        )

        # --- CHK-ABR-SIZE-WR32-HI ---------------------------------------------
        acc = await self._wr(hi_reg.addr, hi_reg.mask, nbytes=4, size=2)
        pair = await self._pair()
        assert acc.resp == RESP_OKAY and pair == (lo_reg.mask, hi_reg.mask), (
            f"CHK-ABR-SIZE-WR32-HI FAIL: AxSIZE=2 WSTRB=0xF0 write at 0x{hi_reg.addr:08x} "
            f"answered {acc.resp_name}; pair reads lo=0x{pair[0]:x} hi=0x{pair[1]:x}"
        )
        await self._wr(hi_reg.addr, 0, nbytes=4, size=2)
        pair = await self._pair()
        assert pair == (lo_reg.mask, 0), (
            f"CHK-ABR-SIZE-WR32-HI FAIL: clearing {hi_reg.name} left pair {pair}"
        )
        self.logger.info(
            "CHK-ABR-SIZE-WR32-HI PASS: AxSIZE=2 writes at addr[2]=1 (WSTRB=0xF0) set and "
            "cleared %s, OKAY, %s unchanged",
            hi_reg.name,
            lo_reg.name,
        )

    async def _partial_writes(self, cfg: SepAbrAccessSizeCfg) -> None:
        # --- CHK-ABR-SIZE-WR-PARTIAL ------------------------------------------
        # (register, primed value, data written): the complement of the prime
        # on every byte, so a partial write that reached the register moves it.
        targets = (
            (GLOBAL_INTR_EN, GLOBAL_INTR_EN.mask, 0),
            (ERROR_INTR_EN, ERROR_INTR_EN.mask, 0),
            (ERROR_COUNT, cfg.count_prime, ~cfg.count_prime & 0xFFFF_FFFF),
        )
        cells = 0
        for reg, prime, data in targets:
            await self._set(reg, prime)
            for off, nbytes, size in PARTIAL_RUNS:
                addr = reg.addr + off
                chunk = (data >> (8 * off)) & ((1 << (8 * nbytes)) - 1)
                acc = await self._wr(addr, chunk, nbytes=nbytes, size=size, refused=True)
                got = await self._word(reg)
                assert acc.resp == RESP_SLVERR and got == prime, (
                    f"CHK-ABR-SIZE-WR-PARTIAL FAIL: {nbytes}-byte write at 0x{addr:08x} "
                    f"(WSTRB=0x{_strobe(addr, nbytes):02x}) answered {acc.resp_name}, "
                    f"expected SLVERR; {reg.name} reads 0x{got:08x}, primed 0x{prime:08x}"
                )
                cells += 1
        self.logger.info(
            "CHK-ABR-SIZE-WR-PARTIAL PASS: %d partial-word writes (8 strobe patterns on "
            "each of %d registers, both halves of the granule) answered SLVERR and left "
            "the register unchanged",
            cells,
            len(targets),
        )

        # --- CHK-ABR-SIZE-WR64-MIXED ------------------------------------------
        # A 64-bit beat whose strobe covers one word whole and the other in
        # part: two 32-bit accesses, low first. The whole word lands, the
        # partial one is refused, and the one response is the error.
        lo_reg, hi_reg = GLOBAL_INTR_EN, ERROR_INTR_EN
        await self._set(lo_reg, 0)
        await self._set(hi_reg, hi_reg.mask)
        acc = await self._wr(lo_reg.addr, lo_reg.mask, nbytes=7, size=3, refused=True)
        pair = await self._pair()
        assert acc.resp == RESP_SLVERR and pair == (lo_reg.mask, hi_reg.mask), (
            f"CHK-ABR-SIZE-WR64-MIXED FAIL: WSTRB=0x7F write answered {acc.resp_name}, "
            f"expected SLVERR; pair reads lo=0x{pair[0]:x} hi=0x{pair[1]:x}, expected "
            f"lo=0x{lo_reg.mask:x} (whole word written) hi=0x{hi_reg.mask:x} (refused)"
        )
        await self._set(lo_reg, lo_reg.mask)
        acc = await self._wr(lo_reg.addr + 2, 0, nbytes=6, size=3, refused=True)
        pair = await self._pair()
        assert acc.resp == RESP_SLVERR and pair == (lo_reg.mask, 0), (
            f"CHK-ABR-SIZE-WR64-MIXED FAIL: WSTRB=0xFC write answered {acc.resp_name}, "
            f"expected SLVERR; pair reads lo=0x{pair[0]:x} hi=0x{pair[1]:x}, expected "
            f"lo=0x{lo_reg.mask:x} (refused) hi=0 (whole word written)"
        )
        self.logger.info(
            "CHK-ABR-SIZE-WR64-MIXED PASS: WSTRB=0x7F and 0xFC each wrote the whole word "
            "they cover, left the partial word unchanged, and answered SLVERR"
        )

    async def _narrow_rw_reads(self, cfg: SepAbrAccessSizeCfg) -> None:
        # --- CHK-ABR-SIZE-RD-NARROW-RW ----------------------------------------
        await self._set(ERROR_COUNT, cfg.count_prime)
        cells = 0
        for size, nbytes in ((0, 1), (1, 2)):
            for off in range(0, 4, nbytes):
                addr = ERROR_COUNT.addr + off
                acc, beat = await self._rd_beat(addr, nbytes, size)
                want = (cfg.count_prime >> (8 * off)) & ((1 << (8 * nbytes)) - 1)
                want_beat = _in_lanes(addr, want)
                assert acc.resp == RESP_OKAY and acc.data == want and beat == want_beat, (
                    f"CHK-ABR-SIZE-RD-NARROW-RW FAIL: {nbytes}-byte read at +{off} of "
                    f"{ERROR_COUNT.name} returned {acc.resp_name} 0x{acc.data:x} in "
                    f"{_beat_txt(beat)}, expected 0x{want:x} in R beat 0x{want_beat:016x}"
                )
                cells += 1
        self.logger.info(
            "CHK-ABR-SIZE-RD-NARROW-RW PASS: %d byte and halfword reads of %s = 0x%08x "
            "returned the addressed bytes, with every other byte lane of the R beat zero",
            cells,
            ERROR_COUNT.name,
            cfg.count_prime,
        )
