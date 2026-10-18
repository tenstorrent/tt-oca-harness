# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Host side of the POKE Key Manager image (``tests/km_fw/km_rom_poke.S``).

The test builds a list of KM bus operations with the builders of
``env/sep_km_poke.py`` (``rd``, ``wr``, ``poll``, ...). ``SepKmPoke`` posts the
list to ``SEP_WRITE_DATA`` through the SEP-side mailbox, waits (bounded) for the
image to finish it, and reads every result from KM SRAM words 0 to 97 through
``km_sram_probe_o`` (``KM-RESULT``). Each data word and each ``slv``/``dec``
flag is a value the image read from the DUT; nothing in a result comes from the
host, except the word of a ``mark`` or ``sync`` op.

A wait that runs out raises ``AssertionError``: a timeout fails the leaf and is
not a verdict about the contract. A result word with an unknown bit raises
unless the caller asks for ``allow_unknown``.

The inbound FIFO is 16 words deep (``architecture.adoc``, "Mailbox Transport": SEP
instantiates the KM with 16 words). The image drains the list into SRAM as it
arrives, so ``post`` writes a list of up to ``BUF_WORDS`` + 1 words in chunks
that fit the free FIFO space.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles
from env import sep_km_poke as kp

from seq_lib.sep_km_mailbox_seq import (
    KM_STATUS_INBOUND_DEPTH_LSB,
    KM_STATUS_INBOUND_DEPTH_MASK,
    SepKmMailbox,
)
from seq_lib.sep_km_mem_smoke_seq import sep_km_release_seq

MBOX_FIFO_WORDS = 16
WORD_BITS = 32

# Bounds of the waits, in clk_i cycles. A list of reporting ops costs about
# 40 KM bus reads per slot; a long read loop costs more, so callers raise the
# bound for it.
BOOT_TIMEOUT_CYCLES = 200_000
LIST_TIMEOUT_CYCLES = 2_000_000
POLL_CYCLES = 16


@dataclass(frozen=True)
class PokeHandle:
    """A posted list: its tag and its ops."""

    tag: int
    ops: tuple[kp.PokeOp, ...]


class SepKmPoke:
    """Post POKE op lists and read their results back."""

    def __init__(self, test, *, mbox: SepKmMailbox | None = None, logger=None) -> None:
        self.test = test
        self.log = logger if logger is not None else test.logger
        self.mbox = mbox if mbox is not None else SepKmMailbox(test, logger=self.log)
        self._tag = 0
        kp.check_image()

    # --- KM release and boot ------------------------------------------------
    async def release(self) -> None:
        """Write SW_RESET_N with the KM bit high (the caller waits for the
        ``sep_reset_n`` release on ``dbg_sep_reset_n_o`` first)."""
        await self.test.start_seq(sep_km_release_seq("km_poke_release"))

    async def wait_boot(self, *, timeout_cycles: int = BOOT_TIMEOUT_CYCLES) -> int:
        """Wait for the start marker (STATE = BOOT). Returns the cycles waited.

        After a reset, the marker is fresh only when STATE did not already read
        BOOT before the reset: call ``prepare_reset`` first.
        """
        waited, _ = await self._wait_word0(
            lambda st: st == (kp.ST_BOOT, 0), "start marker (STATE=BOOT)", timeout_cycles
        )
        return waited

    async def prepare_reset(self) -> None:
        """Leave STATE at DONE so the next BOOT marker can only come from a new boot."""
        st = self.state()
        if st is not None and st[0] == kp.ST_BOOT:
            await self.run([])

    # --- raw reads of the result words ---------------------------------------
    def _probe(self):
        return cocotb.top.km_sram_probe_o

    def word(self, index: int, *, allow_unknown: bool = False) -> int:
        mask = kp.WORD_MASK << (WORD_BITS * index)
        value = self.test.rd(self._probe(), mask, allow_unknown=allow_unknown)
        return (value >> (WORD_BITS * index)) & kp.WORD_MASK

    def words(self) -> tuple[list[int], set[int]]:
        """Result words 0..97 (unknown bits read as 0) and the indices that held one."""
        probe = self._probe()
        full = (1 << (WORD_BITS * kp.RESULT_WORDS)) - 1
        unknown: set[int] = set()
        try:
            value = self.test.rd(probe, full)
        except AssertionError:
            value = self.test.rd(probe, full, allow_unknown=True)
            for i in range(kp.RESULT_WORDS):
                try:
                    self.word(i)
                except AssertionError:
                    unknown.add(i)
        out = [(value >> (WORD_BITS * i)) & kp.WORD_MASK for i in range(kp.RESULT_WORDS)]
        return out, unknown

    def state(self) -> tuple[int, int] | None:
        """(state, tag) of STATE, or None when it holds no POKE state (or an unknown bit)."""
        try:
            return kp.state_of(self.word(kp.W_STATE))
        except AssertionError:
            return None

    def progress(self) -> tuple[int, int]:
        """(ops completed, slots written) of the current or last list."""
        return kp.progress_of(self.word(kp.W_PROG))

    def counts(self) -> tuple[int, int, int]:
        """Handler entries of CPU IRQ lines 3, 4 and 5."""
        return self.word(kp.W_CNT3), self.word(kp.W_CNT4), self.word(kp.W_CNT5)

    def hword(self) -> int:
        """IRQ_STATUS that the ACT_SPIN handler stored (or the ``reseth`` value)."""
        return self.word(kp.W_HWORD)

    def spin_word(self) -> int:
        """IRQ_STATUS that the ROM spin loop stored last (or the ``reseth`` value)."""
        return self.word(kp.W_SPIN)

    # --- lists ----------------------------------------------------------------
    def _next_tag(self) -> int:
        self._tag = self._tag % 0xFF + 1
        return self._tag

    async def post(self, ops: Sequence[kp.PokeOp]) -> PokeHandle:
        """Post one list. Does not wait for it to run."""
        handle = PokeHandle(self._next_tag(), tuple(ops))
        words = kp.encode_list(handle.ops, handle.tag)
        pos = 0
        while pos < len(words):
            status = await self.mbox.read_status()
            depth = (status >> KM_STATUS_INBOUND_DEPTH_LSB) & KM_STATUS_INBOUND_DEPTH_MASK
            free = MBOX_FIFO_WORDS - depth
            if free <= 0:
                await ClockCycles(cocotb.top.clk_i, POLL_CYCLES)
                continue
            chunk = words[pos : pos + free]
            await self.mbox.post_raw_words(chunk)
            pos += len(chunk)
        self.log.info(
            "POKE post tag=%d ops=%d words=%d slots=%d",
            handle.tag,
            len(handle.ops),
            len(words),
            kp.list_slots(handle.ops),
        )
        return handle

    async def _wait_word0(
        self,
        accept: Callable[[tuple[int, int]], bool],
        what: str,
        timeout_cycles: int,
        tag: int | None = None,
    ) -> tuple[int, tuple[int, int]]:
        waited = 0
        st = None
        while waited <= timeout_cycles:
            st = self.state()
            if st is not None:
                if accept(st):
                    return waited, st
                if st[0] == kp.ST_ERROR and (tag is None or st[1] == tag):
                    raise AssertionError(
                        f"POKE ERROR tag={st[1]}: {kp.error_text(self.word(kp.W_ERR))}"
                    )
            await ClockCycles(cocotb.top.clk_i, POLL_CYCLES)
            waited += POLL_CYCLES
        word0 = self.word(kp.W_STATE, allow_unknown=True)
        raise AssertionError(
            f"POKE timeout: no {what} within {timeout_cycles} cycles; STATE=0x{word0:08x} "
            f"({self._state_text(st)}), PROG=0x{self.word(kp.W_PROG, allow_unknown=True):08x}, "
            f"KM ROM fetches={self.test.rd(cocotb.top.km_rom_req_count_o, allow_unknown=True)}"
        )

    @staticmethod
    def _state_text(st: tuple[int, int] | None) -> str:
        if st is None:
            return "no POKE state"
        return f"{kp.STATE_NAMES.get(st[0], hex(st[0]))} tag={st[1]}"

    async def wait(
        self,
        handle: PokeHandle,
        states: Sequence[int] = (kp.ST_DONE,),
        *,
        timeout_cycles: int = LIST_TIMEOUT_CYCLES,
    ) -> int:
        """Wait until STATE is one of ``states`` with the tag of ``handle``.

        Returns the state reached. An ERROR state of this list raises.
        """
        want = tuple(states)
        names = "/".join(kp.STATE_NAMES.get(s, hex(s)) for s in want)
        _, st = await self._wait_word0(
            lambda s: s[1] == handle.tag and s[0] in want,
            f"{names} for tag {handle.tag}",
            timeout_cycles,
            tag=handle.tag,
        )
        return st[0]

    async def reply_sync(
        self, handle: PokeHandle, word: int = 0, *, timeout_cycles: int = LIST_TIMEOUT_CYCLES
    ) -> None:
        """Post the word a ``sync`` op waits for. STATE must read SYNC for this list."""
        st = self.state()
        if st != (kp.ST_SYNC, handle.tag):
            raise AssertionError(
                f"POKE reply_sync: STATE is {self._state_text(st)}, not SYNC tag={handle.tag}"
            )
        await self.mbox.post_raw_words([word & kp.WORD_MASK])
        await self._wait_word0(
            lambda s: s[1] == handle.tag and s[0] != kp.ST_SYNC,
            f"leave SYNC for tag {handle.tag}",
            timeout_cycles,
            tag=handle.tag,
        )

    def results(
        self, handle: PokeHandle, *, allow_unknown: bool = False, partial: bool = False
    ) -> list[kp.PokeResult]:
        """Results of the ops that the image completed for ``handle``.

        ``partial=False`` requires every op to be complete (a list that ended in
        DONE). ``partial=True`` returns the ops before a JUMP that did not return,
        or before a trap. A result that uses a word with an unknown bit raises
        unless ``allow_unknown``; then it carries ``known=False``.
        """
        st = self.state()
        if st is None or st[1] != handle.tag:
            raise AssertionError(
                f"POKE results: STATE is {self._state_text(st)}, not tag={handle.tag}"
            )
        done, slots = self.progress()
        if not partial and done != len(handle.ops):
            raise AssertionError(
                f"POKE results: {done} of {len(handle.ops)} ops completed for tag={handle.tag}"
            )
        expect_slots = kp.list_slots(handle.ops[:done])
        if slots != expect_slots:
            raise AssertionError(
                f"POKE results: image wrote {slots} slots for {done} ops, the list needs "
                f"{expect_slots}"
            )
        words, unknown = self.words()
        out = kp.decode(handle.ops, words, count=done, unknown=unknown)
        if not allow_unknown:
            bad = [r for r in out if not r.known]
            if bad:
                raise AssertionError(
                    "POKE results: unknown bits in the result of "
                    + ", ".join(f"op {r.index} ({r.op.name})" for r in bad)
                )
        return out

    async def run(
        self,
        ops: Sequence[kp.PokeOp],
        *,
        timeout_cycles: int = LIST_TIMEOUT_CYCLES,
        on_sync: Callable[[int], Awaitable[int | None]] | None = None,
        allow_unknown: bool = False,
    ) -> list[kp.PokeResult]:
        """Post ``ops``, wait for DONE and return the results.

        At each ``sync`` op the image stops; ``on_sync(k)`` (k = 0, 1, ...) runs the
        host action and returns the word to post (None posts 0). A list with a
        ``sync`` op and no ``on_sync`` raises.
        """
        handle = await self.post(ops)
        k = 0
        while True:
            st = await self.wait(handle, (kp.ST_DONE, kp.ST_SYNC), timeout_cycles=timeout_cycles)
            if st == kp.ST_DONE:
                break
            if on_sync is None:
                raise AssertionError(f"POKE tag={handle.tag} reached a sync op and no on_sync")
            word = await on_sync(k)
            await self.reply_sync(
                handle, 0 if word is None else word, timeout_cycles=timeout_cycles
            )
            k += 1
        return self.results(handle, allow_unknown=allow_unknown)
