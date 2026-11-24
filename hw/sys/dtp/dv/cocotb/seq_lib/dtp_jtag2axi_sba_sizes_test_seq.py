# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG2AXI System Bus Access sizes, byte lanes and autoincrement on every bridge.

An access of each size up to the data width, at each offset aligned to it,
strobes exactly its bytes, carries write data on the byte lanes the address
selects and takes read data from them. With sbautoincrement the address
advances by the access size after each access, from sbaddress0 into
sbaddress1 on a bridge wider than 32 bits.
"""

from __future__ import annotations

import random

from env.dtp_types import JTAG2AXI_TARGETS, DtpDmReg
from ocah_lib import OcahKnobs

from .dtp_jtag2axi_base_test_seq import dtp_jtag2axi_base_test_seq

AUTOINC_CHECK_ID = "CHK-J2A-AUTOINC"
AUTOINC_NEGATIVE_KNOB = "DTP_J2A_AUTOINC_NEGATIVE"
# Whole beats one autoincrement stream writes, so every byte a read of the stream returns is
# one the stream wrote.
STREAM_BEATS = (2, 3)


class dtp_jtag2axi_sba_sizes_test_seq(dtp_jtag2axi_base_test_seq):
    """Every access size and aligned offset, and an autoincrement stream, on each bridge in a
    seeded order."""

    def __init__(
        self,
        name: str = "dtp_jtag2axi_sba_sizes_test_seq",
        *,
        scenario_seed: int | None = None,
        random_count: int = 5,
    ) -> None:
        super().__init__(name, scenario_seed=scenario_seed, random_count=random_count)
        self._ledger_target: str | None = None

    def bus_ledger_target(self) -> str | None:
        return self._ledger_target

    async def body(self) -> None:
        self.log_banner("System Bus Access sizes, byte lanes and autoincrement on every bridge")
        await self.enable_all_debug()
        await self.reset_tap()
        rng = self.rng("sba_sizes")
        targets = list(JTAG2AXI_TARGETS)
        rng.shuffle(targets)
        for target in targets:
            self._ledger_target = target
            self.open_bus_ledger()
            await self.lanes_case(target, rng)
            await self.autoincrement_case(target, rng)
            self.close_bus_ledger()
            self._ledger_target = None
            self.log_summary(f"{target} System Bus Access sizes complete")

    def aligned_accesses(self, target: str) -> list[tuple[int, int]]:
        """Every (size, offset in the beat) pair ``target`` supports, the offset aligned to
        the size."""
        cfg = self.target_cfg(target)
        return [
            (size, offset)
            for size in range(cfg.data_size + 1)
            for offset in range(0, cfg.beat_bytes, 1 << size)
        ]

    async def lanes_case(self, target: str, rng: random.Random) -> None:
        """Each read takes its bytes from the lanes its address selects, and each write
        changes only the bytes it strobes."""
        cfg = self.target_cfg(target)
        ctx = f"{target}.lanes"
        base = self.random_target_addr(target, rng)
        # Distinct bytes, so a read from any other lane returns other data.
        beat = int.from_bytes(bytes(rng.sample(range(256), cfg.beat_bytes)), "little")
        await self.sba_write(target, base, beat, size=cfg.data_size, context=f"{ctx}.fill")
        self.check_target_word(target, base, beat, size=cfg.data_size, context=f"{ctx}.fill.mem")
        accesses = self.aligned_accesses(target)
        rng.shuffle(accesses)
        for size, offset in accesses:
            access = f"{ctx}.read.size{size}.offset{offset}"
            mask = self.data_mask(size)
            rdata = await self.sba_read(target, base + offset, size=size, context=access)
            self.check_bridge_rdata(
                target, rdata & mask, (beat >> (8 * offset)) & mask, context=access
            )
        rng.shuffle(accesses)
        for size, offset in accesses:
            access = f"{ctx}.write.size{size}.offset{offset}"
            mask = self.data_mask(size) << (8 * offset)
            old = beat & mask
            while True:
                lanes = (rng.getrandbits(8 << size) << (8 * offset)) & mask
                if lanes != old:
                    break
            await self.sba_write(
                target, base + offset, lanes >> (8 * offset), size=size, context=access
            )
            beat = (beat & ~mask) | lanes
            self.check_target_word(target, base, beat, size=cfg.data_size, context=f"{access}.mem")

    async def autoincrement_case(self, target: str, rng: random.Random) -> None:
        """An autoincrement stream at every size ``target`` supports, in a seeded order."""
        sizes = list(range(self.target_cfg(target).data_size + 1))
        rng.shuffle(sizes)
        for size in sizes:
            await self.autoincrement_stream(target, size, rng)

    async def autoincrement_stream(self, target: str, size: int, rng: random.Random) -> None:
        """With sbautoincrement each sbdata0 write starts a ``size`` write at the next address,
        and a read started by an sbaddress0 write advances the address too; on a bridge wider
        than 32 bits the stream crosses address bit 32."""
        cfg = self.target_cfg(target)
        ctx = f"{target}.autoinc.size{size}"
        stride = 1 << size
        per_beat = cfg.beat_bytes // stride
        beats = rng.randint(*STREAM_BEATS)
        count = beats * per_beat
        if cfg.addr_width > 32:
            below = rng.randint(1, beats - 1)
            boundary = (rng.randrange((1 << (cfg.addr_width - 32)) - 1) + 1) << 32
            start = boundary - below * cfg.beat_bytes
            # The read is of the last element below the boundary.
            index = below * per_beat - 1
        else:
            start = min(
                self.random_target_addr(target, rng),
                (1 << cfg.addr_width) - (beats + 1) * cfg.beat_bytes,
            )
            index = rng.randrange(count)
        words = distinct_words(rng, 8 * stride, count)
        await self.sba_setup(
            target, start, size, read=False, autoincrement=True, context=f"{ctx}.stream"
        )
        for element, word in enumerate(words):
            await self.sba_write_data(
                target, start + element * stride, word, size=size, context=f"{ctx}.write{element}"
            )
        await self.check_sba_address(target, start + count * stride, context=f"{ctx}.stream")
        for element, word in enumerate(words):
            self.check_target_word(
                target, start + element * stride, word, size=size, context=f"{ctx}.mem{element}"
            )
        addr = start + index * stride
        rdata = await self.sba_read(
            target, addr, size=size, autoincrement=True, context=f"{ctx}.read"
        )
        self.check_bridge_rdata(
            target, rdata & self.data_mask(size), words[index], context=f"{ctx}.read"
        )
        await self.check_sba_address(target, addr + stride, context=f"{ctx}.read")

    async def check_sba_address(self, target: str, expected: int, *, context: str) -> None:
        """``CHK-J2A-AUTOINC``: sbaddress reads ``expected``.

        ``DTP_J2A_AUTOINC_NEGATIVE=1`` flips the expected bit 0, so the run
        must fail.
        """
        observed = await self.dmi_read(target, DtpDmReg.SBADDRESS0, context=f"{context}.sbaddress0")
        if self.target_cfg(target).addr_width > 32:
            observed |= (
                await self.dmi_read(target, DtpDmReg.SBADDRESS1, context=f"{context}.sbaddress1")
            ) << 32
        expected = self.masked_addr(target, expected)
        if OcahKnobs.is_set(AUTOINC_NEGATIVE_KNOB):
            expected ^= 0x1
        self.check_equal(
            self.target_evidence(target),
            AUTOINC_CHECK_ID,
            observed,
            expected,
            context=f"{context} target={target} observed=0x{observed:x} expected=0x{expected:x}",
        )


def distinct_words(rng: random.Random, bits: int, count: int) -> list[int]:
    """``count`` seeded nonzero ``bits``-bit words, no two equal."""
    words: list[int] = []
    while len(words) < count:
        word = rng.getrandbits(bits)
        if word and word not in words:
            words.append(word)
    return words
