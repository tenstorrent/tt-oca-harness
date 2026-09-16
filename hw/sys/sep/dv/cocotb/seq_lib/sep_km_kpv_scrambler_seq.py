# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host client for the KPV scrambler observation ROM (``km_rom_kpv_scrambler.S``).

The key/policy vault hangs off the Key Manager's own crossbar, which has a
single slave port wired to the KM CPU, so no testbench master can reach it.
A dedicated ROM is the only way in, and it reports raw observations: the host
holds every verdict.

The exchange is raw mailbox words, not the KM firmware message protocol -- the
observation ROM is a stub and frames nothing.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_km_mailbox_seq import (
    KM_MBOX_BASE,
    KM_MBOX_READ_DATA,
    KM_MBOX_STATUS,
    KM_MBOX_WRITE_DATA,
    KM_MBOX_WRITE_SEPARATOR,
    KM_STATUS_OUTBOUND_EMPTY,
)

# 64 slots of 16 words: the key-entry file is 1024 logically indexed words.
KPV_N_WORDS = 1024
# Logical indices the ROM writes under the first key.
N_TEST_INDICES = 3
# The plaintext formula the ROM applies, kept here so the host predicts the
# written value rather than reading it back from the DUT.
PT_CONST = 0xA5C3_F00D


def plaintext_for(index: int) -> int:
    """The word the ROM writes at a logical key-entry index."""
    return ((index << 20) ^ (index << 8) ^ PT_CONST) & 0xFFFF_FFFF


class SepKpvScramblerCfg:
    """Seeded keys and logical indices for one run.

    Two keys, because a single key cannot separate "the stored word is
    transformed" from "the stored word is transformed by THIS key". The keys
    are drawn distinct and non-zero, and the three logical indices are drawn
    distinct so a collision cannot make two writes look like one.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.key_a = self._draw_key(rng)
        while True:
            self.key_b = self._draw_key(rng)
            if self.key_b != self.key_a:
                break
        picked: list[int] = []
        while len(picked) < N_TEST_INDICES:
            cand = rng.randrange(KPV_N_WORDS)
            if cand not in picked:
                picked.append(cand)
        self.indices = tuple(picked)
        self.packed_indices = self.indices[0] | (self.indices[1] << 10) | (self.indices[2] << 20)

    @staticmethod
    def _draw_key(rng) -> int:
        while True:
            key = rng.getrandbits(32)
            if key != 0:
                return key

    def summary(self) -> str:
        return (
            f"seed={self.seed} key_a=0x{self.key_a:08x} key_b=0x{self.key_b:08x} "
            f"indices={list(self.indices)} packed=0x{self.packed_indices:08x}"
        )


class SepKpvScramblerReport:
    """What the ROM observed, as raw values."""

    def __init__(
        self,
        count: int,
        pairs: list[tuple[int, int]],
        key_b_pair: tuple[int, int],
        round_trip: int,
        key_unlocked: int,
        key_readback: int,
        post_lock_round_trip: int,
        refused_round_trip: int,
        ctrl_after_refused: int,
    ) -> None:
        self.count = count
        self.pairs = pairs
        self.key_b_pair = key_b_pair
        self.round_trip = round_trip
        self.key_unlocked = key_unlocked
        self.key_readback = key_readback
        self.post_lock_round_trip = post_lock_round_trip
        self.refused_round_trip = refused_round_trip
        self.ctrl_after_refused = ctrl_after_refused


class SepKpvScrambler:
    """Posts the config and collects the ROM's observation report."""

    def __init__(self, test, *, base: int = KM_MBOX_BASE) -> None:
        self.test = test
        self.base = base
        self.log = test.logger

    async def _wr(self, offset: int, data: int) -> None:
        seq = SepAxiAccessSeq(
            "km_kpv_wr", op=SepAxiOp.WRITE, addr=self.base + offset, wdata=data, size=2
        )
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox write @0x{self.base + offset:08x} not OKAY")

    async def _rd(self, offset: int) -> int:
        seq = SepAxiAccessSeq("km_kpv_rd", op=SepAxiOp.READ, addr=self.base + offset, size=2)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"KM mailbox read @0x{self.base + offset:08x} not OKAY")
        return seq.rdata

    async def post_cfg(self, cfg: SepKpvScramblerCfg) -> None:
        for word in (cfg.key_a, cfg.key_b, cfg.packed_indices):
            await self._wr(KM_MBOX_WRITE_SEPARATOR, 1)
            await self._wr(KM_MBOX_WRITE_DATA, word)

    async def _next_word(self, what: str, *, timeout: int = 20_000, poll_cycles: int = 20) -> int:
        """Read one reported word, bounded and attributed.

        The budget is sized against the ROM's longest silence -- the two
        whole-file scans before the first report -- with room to spare, and
        well inside the leaf's own timeout. A bound that outlives
        the leaf is not a bound: the runner would kill the run first and the
        attributed message below would never be printed, which is the whole
        reason for polling with a limit rather than waiting forever.
        """
        for _ in range(timeout):
            if not (await self._rd(KM_MBOX_STATUS) & (1 << KM_STATUS_OUTBOUND_EMPTY)):
                return await self._rd(KM_MBOX_READ_DATA)
            await ClockCycles(cocotb.top.clk_i, poll_cycles)
        raise AssertionError(f"KPV scrambler ROM never reported {what}")

    async def collect(self) -> SepKpvScramblerReport:
        count = await self._next_word("the non-zero count")
        # Raise on a wrong count HERE, before draining the pair list. The ROM
        # emits two words per non-zero entry without checking for space, and the
        # outbound FIFO is far shallower than the file, so a dirty register file
        # would flood it: the pairs would be dropped and the run would die on an
        # unattributed "never reported index N" instead of saying that the count
        # was wrong. The count is the diagnosis, so it is checked first.
        if count != N_TEST_INDICES:
            raise AssertionError(
                f"CHK-COUNT FAIL: {count} of the {KPV_N_WORDS} key-entry words differ "
                f"from the zeroed setup, expected exactly {N_TEST_INDICES}. Fewer means "
                "a write never landed or the read path is stuck; more means the file "
                "was left dirty."
            )
        pairs = []
        for i in range(count):
            index = await self._next_word(f"index {i}")
            value = await self._next_word(f"value {i}")
            pairs.append((index, value))
        key_b_index = await self._next_word("the second-key index")
        key_b_value = await self._next_word("the second-key value")
        round_trip = await self._next_word("the round-trip word")
        key_unlocked = await self._next_word("the unlocked key readback")
        key_readback = await self._next_word("the locked key readback")
        post_lock = await self._next_word("the post-lock round-trip word")
        refused_rt = await self._next_word("the round-trip after the refused writes")
        ctrl_after = await self._next_word("KPV_SCRAMBLER_CTRL after the refused write")
        return SepKpvScramblerReport(
            count,
            pairs,
            (key_b_index, key_b_value),
            round_trip,
            key_unlocked,
            key_readback,
            post_lock,
            refused_rt,
            ctrl_after,
        )
