# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""HARNESS_LOCKS register behaviour and the 8-slot lock assignment of SMC_EFUSE_MAP.

Sources: smc_efuse_map.rdl (HARNESS_LOCKS, slot assignment), architecture.adoc (Hardware vs.
Software Locks).

HARNESS_LOCKS holds one write/read lock pair per slot at bits 2n and 2n+1: slots 0 to 3 for
the four functional fields, slots 4 to 6 for SPARE[0] to SPARE[2] and slot 7 for the three
SPARE_TAIL elements together; bits [63:16] are reserved and the leaf never sets them.
SUPPLEMENTARY_LOCKS, the next 64-bit register of the same set-only lock block, carries the
proof that a 32-bit write to a high word and the upper half of a 64-bit write reach the
block (region 16 at bits 32 and 33). Every LOCKS compare is against ``locks_model`` and
``supp_model``, the 64-bit values the sequence keeps. Every field
word compare is against ``shadow``, a per-word model that starts from the image and changes only
when a write to an unlocked field lands.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_efuse_map_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_efuse_image_pattern_test_seq import (
    LOCKS_WORDS,
    REGIONS,
    EfuseImage,
    word_addr,
)
from .smc_reset_seq_base import SmcResetSeqBase

#: The SPARE_TAIL write lock, HARNESS_LOCKS bit 14 (slot 7).
LOCKS_IMAGE_VALUE = 0x4000
_WORD_MASK = 0xFFFF_FFFF
_SLOTS = 8
#: Every assigned HARNESS_LOCKS bit: one write/read pair per slot.
_ASSIGNED_LOCKS = (1 << (2 * _SLOTS)) - 1
#: S3 and S5 bits: slot 0 and slot 1 write locks by 32-bit writes, slot 2 write lock and
#: slot 5 read lock by one 64-bit write; the S5R cold reset clears them again.
_HALF_LO_BIT = 0x1
_HALF_LO_BIT2 = 0x4
_WIDE_BITS = 0x0000_0000_0000_0810
#: SUPPLEMENTARY_LOCKS bits: region 16 write lock (bit 32) by a 32-bit write to the high
#: word; region 16 read lock (bit 33) and region 2 write lock (bit 4) by one 64-bit write.
_SUPP_HIGH_WORD_BIT = 0x1
_SUPP_WIDE_BITS = 0x0000_0002_0000_0010
_SMC_EFUSE_MAP_H = (
    _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_efuse_map.h"
)
_STEPS = ("S1", "S2", "S3", "S4", "S5", "S5R", "S6", "S7", "S8")
#: SMC_CONFIG low-word bits that carry an assigned meaning.
_SMC_CONFIG_ASSIGNED = (
    smc_efuse_map_u32("SMC_EFUSE_MAP__SMC_CONFIG__ROM_FLIP_ENDIANNESS_bm")
    | smc_efuse_map_u32("SMC_EFUSE_MAP__SMC_CONFIG__SRAM_AUTO_ZERO_DISABLE_bm")
    | smc_efuse_map_u32("SMC_EFUSE_MAP__SMC_CONFIG__DFT_IGNORE_ERROR_bm")
)
_SENSE_BOUND_CYCLES = 200_000


class smc_efuse_map_locks_register_test_seq(SmcResetSeqBase, SmcCsrSeq):
    """HARNESS_LOCKS write-one-to-set, slot assignment, persistence and cold-reset restore."""

    def __init__(self, name: str = "smc_efuse_map_locks_register_test_seq") -> None:
        super().__init__(name)
        self.image: EfuseImage | None = None
        self.dispatch_reset = None
        self.seed = 1
        self.access_floor = 0
        self.locks_model = 0
        self.supp_model = 0
        self._events: list[tuple[str, str]] = []
        self._stamps: list[tuple[str, int]] = []
        self._waits: list[tuple[str, int, str]] = []

    async def _dispatch_reset_item(self, item) -> None:
        await self.dispatch_reset(item)

    # --- fence ----------------------------------------------------------
    def _done(self, step: str) -> None:
        self._stamps.append((step, int(get_sim_time("ps"))))
        self._events.append(("step", step))

    def _chk(self, chk_id: str, fmt: str, *args) -> None:
        self._events.append(("chk", chk_id))
        cocotb.log.info("%s: " + fmt, chk_id, *args)

    # --- probes ---------------------------------------------------------
    @staticmethod
    def _gate(up: bool) -> None:
        """Drive tb_fcov_gate, the graded window of smc_efuse_lock_cg."""
        cocotb.top.tb_fcov_gate.value = int(up)
        cocotb.log.info("CTRL-FCOV-GATE: %s %d ps", "rise" if up else "fall", get_sim_time("ps"))

    @staticmethod
    def _sig(name: str) -> int:
        dut = cocotb.top
        assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        value = getattr(dut, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _probe_word(self, word: int) -> int:
        return (self._sig("efuse_shadow_probe_o") >> (32 * word)) & _WORD_MASK

    async def _sense_wait(self, label: str) -> None:
        try:
            await self.wait_fuse_sense_done(_SENSE_BOUND_CYCLES)
        except AssertionError as exc:
            raise AssertionError(f"{label}: {exc}; {self._sense_state()}") from exc
        self._waits.append((label, _SENSE_BOUND_CYCLES, self._sense_state()))

    def _sense_state(self) -> str:
        return (
            f"tb_fuse_sense_done={self._sig('tb_fuse_sense_done')},"
            f"tb_fuse_reset_n={self._sig('tb_fuse_reset_n')},"
            f"tb_rst_warm_smc_clk_n={self._sig('tb_rst_warm_smc_clk_n')}"
        )

    # --- LOCKS ----------------------------------------------------------
    async def _read_locks(self, label: str) -> tuple[int, int]:
        addr = word_addr(LOCKS_WORDS[0])
        model = self.locks_model
        lo = await self.csr_read(f"{label}_LO", addr, expected=model & _WORD_MASK)
        hi = await self.csr_read(f"{label}_HI", addr + 4, expected=(model >> 32) & _WORD_MASK)
        return lo & _WORD_MASK, hi & _WORD_MASK

    async def _write_locks64(self, label: str, bits: int) -> None:
        await self.csr_write(label, word_addr(LOCKS_WORDS[0]), bits, length=8)
        self.locks_model |= bits

    async def _read_supp_locks(self, label: str) -> tuple[int, int]:
        addr = word_addr(LOCKS_WORDS[2])
        model = self.supp_model
        lo = await self.csr_read(f"{label}_LO", addr, expected=model & _WORD_MASK)
        hi = await self.csr_read(f"{label}_HI", addr + 4, expected=(model >> 32) & _WORD_MASK)
        return lo & _WORD_MASK, hi & _WORD_MASK

    # --- field access ---------------------------------------------------
    async def _write_field(self, label: str, word: int, data: int) -> int:
        item = SmcSysAxiItem(f"wr_{label}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = word_addr(word)
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: the field write got no response"
        return item.resp_code

    async def _read_any(self, label: str, word: int) -> int:
        item = SmcSysAxiItem(f"rd_{label}")
        item.op = SmcSysAxiOp.READ
        item.addr = word_addr(word)
        item.length = 4
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert item.resp_code is not None, f"{label}: the read got no response"
        return item.rdata & _WORD_MASK

    def _fresh(self, rnd: random.Random, slot: int, k: int) -> int:
        old = self.shadow[self.fields[slot][1] + k]
        while True:
            value = rnd.getrandbits(32)
            if slot == 2 and k == 0:
                value &= ~_SMC_CONFIG_ASSIGNED & _WORD_MASK
            if value not in (old, ~old & _WORD_MASK, 0, _WORD_MASK):
                return value

    def _locked(self, slot: int, kind: str) -> bool:
        return bool(self.locks_model & self.fields[slot][2 if kind == "w" else 3])

    async def _prewrite_fields(self, rnd: random.Random, tag: str) -> int:
        """Write a non-zero pattern to every field and read each back against the model."""
        accesses = 0
        for m in range(_SLOTS):
            _n, mfirst, _w, _r, mwords = self.fields[m]
            for k in range(mwords):
                value = self._fresh(rnd, m, k)
                await self._write_field(f"{tag}_FIELD{m}_WR{k}", mfirst + k, value)
                if not self._locked(m, "w"):
                    self.shadow[mfirst + k] = value
            for k in range(mwords):
                await self.csr_read(
                    f"{tag}_FIELD{m}_RB{k}", word_addr(mfirst + k), expected=self.shadow[mfirst + k]
                )
            accesses += 2 * mwords
        return accesses

    async def _cold_reset(self, tag: str, sense_label: str) -> None:
        await self._send(SmcResetOp.COLD_RST_LO)
        await self._wait_state(
            f"{tag} cold assert",
            expect_powergood_stable=1,
            expect_rst_cold_stable_ref_clk_n=0,
            expect_rst_primary_ref_clk_n=0,
            expect_rst_primary_smc_clk_n=0,
            expect_left_stable=True,
        )
        assert self._sig("tb_fuse_sense_done") == 0, (
            "tb_fuse_sense_done is still 1 with the cold reset asserted"
        )
        await self._send(SmcResetOp.COLD_RST_HI)
        await self._wait_released(f"{tag} cold release")
        await self._sense_wait(sense_label)

    # --- body -----------------------------------------------------------
    async def body(self) -> None:
        image = self.image
        assert image is not None, "the testcase module sets the image before starting"
        #: (name, first word, write lock mask, read lock mask, words) per slot; regions that
        #: share one lock pair (the SPARE_TAIL elements, slot 7) form one contiguous entry.
        self.fields = []
        for region in REGIONS:
            n = (region.write_lock.bit_length() - 1) // 2
            assert region.write_lock == 1 << (2 * n) and region.read_lock == 1 << (2 * n + 1), (
                f"slot {n} {region.name}: masks 0x{region.write_lock:x}/0x{region.read_lock:x} "
                f"are not HARNESS_LOCKS bits {2 * n}/{2 * n + 1}"
            )
            if self.fields and self.fields[-1][2] == region.write_lock:
                name, first, wmask, rmask, words = self.fields[-1]
                assert first + words == region.first_word, (
                    f"slot {n}: {region.name} does not follow {name} in the map"
                )
                self.fields[-1] = (name, first, wmask, rmask, region.end_word - first)
                continue
            assert n == len(self.fields), f"slot {n} {region.name} out of order"
            self.fields.append(
                (
                    region.name,
                    region.first_word,
                    region.write_lock,
                    region.read_lock,
                    region.end_word - region.first_word,
                )
            )
        assert len(self.fields) == _SLOTS, f"{len(self.fields)} lock slots, expected {_SLOTS}"
        assert list(LOCKS_WORDS) == [0, 1, 2, 3] and word_addr(LOCKS_WORDS[2]) == smc_addr(
            "SMC_TOP_SMC_EFUSE_MAP_SUPPLEMENTARY_LOCKS_BASE_ADDR"
        ), f"LOCKS words {list(LOCKS_WORDS)}; SUPPLEMENTARY_LOCKS is not words 2 and 3"
        for name, mask in (
            ("REGION16_WRITE_LOCK", _SUPP_HIGH_WORD_BIT << 32),
            ("REGION16_READ_LOCK", _SUPP_WIDE_BITS & ~_WORD_MASK),
            ("REGION2_WRITE_LOCK", _SUPP_WIDE_BITS & _WORD_MASK),
        ):
            got = _field_mask(_SMC_EFUSE_MAP_H, f"SMC_EFUSE_MAP__SUPPLEMENTARY_LOCKS__{name}_bm")
            assert got == mask, f"SUPPLEMENTARY_LOCKS {name} mask 0x{got:x} is not 0x{mask:x}"
        lo_word = LOCKS_WORDS[0]
        assert image.words[lo_word] == LOCKS_IMAGE_VALUE and all(
            image.words[w] == 0 for w in LOCKS_WORDS[1:]
        ), (
            f"image LOCKS words {[hex(image.words[w]) for w in LOCKS_WORDS]} are not "
            f"0x{LOCKS_IMAGE_VALUE:x} followed by zeros"
        )
        assert all(image.words[w] == 0 for w in range(len(image.words)) if w not in LOCKS_WORDS), (
            "the image has a non-zero word outside LOCKS"
        )
        self.shadow = list(image.words)
        self.locks_model = image.locks
        self.supp_model = 0
        assert self.locks_model == LOCKS_IMAGE_VALUE, (
            f"image LOCKS 0x{self.locks_model:016x} is not 0x{LOCKS_IMAGE_VALUE:016x}"
        )
        floor = 0

        # S1: sense wait
        await self._sense_wait("sense1")
        self._done("S1")

        # smc_efuse_lock_cg samples the LOCKS writes and the field accesses of
        # S2 to S6, with the gate low over each cold reset (the sample event of
        # the reset covergroup) and over S7 and S8.
        self._gate(True)
        try:
            # S2: sensed LOCKS
            lo, hi = await self._read_locks("SENSED")
            slo, shi = await self._read_supp_locks("SENSED_SUPP")
            floor += 4
            self._done("S2")
            self._chk(
                "CHK-EMAP-LOCKS-SENSED",
                "HARNESS_LOCKS lo=0x%08x hi=0x%08x == image words 0/1; SUPPLEMENTARY_LOCKS "
                "lo=0x%08x hi=0x%08x == image words 2/3",
                lo,
                hi,
                slo,
                shi,
            )

            # Non-zero TB pattern in every field before any lock is set from software
            pre_rnd = random.Random(self.seed + 1)
            floor += await self._prewrite_fields(pre_rnd, "PRE")
            prewritten = sum(
                1
                for m in range(_SLOTS)
                if not self._locked(m, "w") and self.shadow[self.fields[m][1]]
            )

            # S3: 32-bit halves: two writes to the low word set one bit each; a 32-bit write of 0
            # to the reserved high word is accepted and changes nothing
            base = word_addr(lo_word)
            await self.csr_write("HALF_LO", base, _HALF_LO_BIT)
            self.locks_model |= _HALF_LO_BIT
            h1 = await self._read_locks("HALF_LO_RB")
            await self.csr_write("HALF_LO2", base, _HALF_LO_BIT2)
            self.locks_model |= _HALF_LO_BIT2
            h2 = await self._read_locks("HALF_LO2_RB")
            await self.csr_write("HALF_HI_ZERO", base + 4, 0)
            h3 = await self._read_locks("HALF_HI_ZERO_RB")
            supp_base = word_addr(LOCKS_WORDS[2])
            await self.csr_write("HALF_HI_SUPP", supp_base + 4, _SUPP_HIGH_WORD_BIT)
            self.supp_model |= _SUPP_HIGH_WORD_BIT << 32
            h4 = await self._read_supp_locks("HALF_HI_SUPP_RB")
            floor += 12
            self._done("S3")
            self._chk(
                "CHK-EMAP-LOCKS-HALVES",
                "after the 32-bit write of 0x%x to the low word lo=0x%08x hi=0x%08x; after the "
                "32-bit write of 0x%x lo=0x%08x hi=0x%08x; after a 32-bit write of 0 to the high "
                "word (bits [63:16] reserved) lo=0x%08x hi=0x%08x; after a 32-bit write of 0x%x to "
                "the SUPPLEMENTARY_LOCKS high word (region 16 write lock, bit 32) SUPPLEMENTARY_LOCKS "
                "lo=0x%08x hi=0x%08x",
                _HALF_LO_BIT,
                *h1,
                _HALF_LO_BIT2,
                *h2,
                *h3,
                _SUPP_HIGH_WORD_BIT,
                *h4,
            )

            # S4: idempotent set
            await self.csr_write("IDEMPOTENT", base, _HALF_LO_BIT)
            i1 = await self._read_locks("IDEMPOTENT_RB")
            floor += 3
            self._done("S4")
            self._chk(
                "CHK-EMAP-LOCKS-IDEMPOTENT",
                "repeat write of 0x1 to low word: lo=0x%08x hi=0x%08x unchanged",
                *i1,
            )

            # S5: one 64-bit write
            await self._write_locks64("WIDE", _WIDE_BITS)
            w1 = await self._read_locks("WIDE_RB")
            wide = await self.csr_read("WIDE_RB64", base, expected=self.locks_model, length=8)
            await self.csr_write("WIDE_SUPP", supp_base, _SUPP_WIDE_BITS, length=8)
            self.supp_model |= _SUPP_WIDE_BITS
            w2 = await self._read_supp_locks("WIDE_SUPP_RB")
            swide = await self.csr_read(
                "WIDE_SUPP_RB64", supp_base, expected=self.supp_model, length=8
            )
            floor += 8
            self._done("S5")
            self._chk(
                "CHK-EMAP-LOCKS-WIDE",
                "64-bit write 0x%016x: lo=0x%08x hi=0x%08x, 64-bit read 0x%016x; 64-bit write "
                "0x%016x to SUPPLEMENTARY_LOCKS (region 16 read lock bit 33, region 2 write lock bit "
                "4): lo=0x%08x hi=0x%08x, 64-bit read 0x%016x",
                _WIDE_BITS,
                *w1,
                wide,
                _SUPP_WIDE_BITS,
                *w2,
                swide,
            )

            # S5R: cold reset re-sense, image LOCKS restored, patterns re-applied
            await RisingEdge(cocotb.top.clk_smc_i)
            self._gate(False)
            await self._cold_reset("resense", "sense_resense")
            self._gate(True)
            self.locks_model = image.locks
            self.supp_model = 0
            self.shadow = list(image.words)
            rs = await self._read_locks("RESENSE")
            srs = await self._read_supp_locks("RESENSE_SUPP")
            floor += 4
            floor += await self._prewrite_fields(random.Random(self.seed + 2), "RE")
            prewritten = sum(
                1
                for m in range(_SLOTS)
                if not self._locked(m, "w") and self.shadow[self.fields[m][1]]
            )
            self._done("S5R")

            # S6: slot sweep
            rnd = random.Random(self.seed)
            order = list(range(_SLOTS))
            rnd.shuffle(order)
            bits_written: list[int] = []
            rejected = hidden = isolated = unreadable = probe_rejected = 0
            preset = [b for b in range(2 * _SLOTS) if (self.locks_model >> b) & 1]
            probe_checked = False
            for n in order:
                name, first, wmask, rmask, words = self.fields[n]
                wbit = wmask.bit_length() - 1
                rbit = rmask.bit_length() - 1
                await self._write_locks64(f"SLOT{n}_WLOCK", wmask)
                bits_written.append(wbit)
                await self._read_locks(f"SLOT{n}_WLOCK_RB")
                floor += 3
                assert self._locked(n, "w")
                held_words = self.shadow[first : first + words]
                if self._locked(n, "r"):
                    assert [self._probe_word(first + k) for k in range(words)] == held_words, (
                        f"slot {n} {name}: probe words differ from the model before the write"
                    )
                for k in range(words):
                    await self._write_field(
                        f"SLOT{n}_LOCKED_WR{k}", first + k, self._fresh(rnd, n, k)
                    )
                floor += words
                if self._locked(n, "r"):
                    unreadable += 1
                    assert [self._probe_word(first + k) for k in range(words)] == held_words, (
                        f"slot {n} {name}: the rejected write changed the probe words"
                    )
                    probe_rejected += words
                else:
                    for k in range(words):
                        await self.csr_read(
                            f"SLOT{n}_HELD{k}",
                            word_addr(first + k),
                            expected=self.shadow[first + k],
                        )
                        rejected += 1
                    floor += words
                for m in range(_SLOTS):
                    if self._locked(m, "w"):
                        continue
                    mname, mfirst, _w, _r, mwords = self.fields[m]
                    for k in range(mwords):
                        value = self._fresh(rnd, m, k)
                        await self._write_field(f"SLOT{n}_FIELD{m}_WR{k}", mfirst + k, value)
                        self.shadow[mfirst + k] = value
                    if self._locked(m, "r"):
                        continue
                    for k in range(mwords):
                        await self.csr_read(
                            f"SLOT{n}_FIELD{m}_RB{k}",
                            word_addr(mfirst + k),
                            expected=self.shadow[mfirst + k],
                        )
                    isolated += 1
                    if not probe_checked:
                        probe_checked = True
                        got = self._probe_word(mfirst)
                        alt = self._probe_word(len(self.shadow) - 1 - mfirst)
                        assert got == self.shadow[mfirst] and alt != got, (
                            f"efuse_shadow_probe_o word {mfirst} reads 0x{got:08x}, the field holds "
                            f"0x{self.shadow[mfirst]:08x}; mirrored word reads 0x{alt:08x}"
                        )
                await self._write_locks64(f"SLOT{n}_RLOCK", rmask)
                bits_written.append(rbit)
                await self._read_locks(f"SLOT{n}_RLOCK_RB")
                held = self.shadow[first]
                got = await self._read_any(f"SLOT{n}_HIDDEN", first)
                assert got not in (held, ~held & _WORD_MASK), (
                    f"slot {n} {name} first word reads 0x{got:08x} with its read lock set; "
                    f"the field holds 0x{held:08x}"
                )
                hidden += 1
                floor += 4
            assert probe_checked, "no unlocked field was available for the probe word-order check"
            assert len(bits_written) == 2 * _SLOTS and sorted(bits_written) == list(
                range(2 * _SLOTS)
            )
            assert self.locks_model == _ASSIGNED_LOCKS, (
                f"LOCKS model 0x{self.locks_model:x} is not every assigned bit 0x{_ASSIGNED_LOCKS:x}"
            )
            final = await self._read_locks("SWEEP_FINAL")
            floor += 2
            self._done("S6")
            self._chk(
                "CHK-EMAP-SLOT-MAP",
                "%d slots: write lock 2n rejected writes of %d words read back over SEP_IN in %d "
                "slots and %d words observed on efuse_shadow_probe_o in %d slots (read lock already "
                "set); %d fields held a non-zero TB value after the re-sense; slot %d (SPARE_TAIL) "
                "image-locked, compared against image 0; read lock 2n+1 hid %d first words (neither "
                "value nor complement); order %s",
                _SLOTS,
                rejected,
                _SLOTS - unreadable,
                probe_rejected,
                unreadable,
                prewritten,
                _SLOTS - 1,
                hidden,
                order,
            )
            self._chk(
                "CHK-EMAP-SLOT-ISOLATION",
                "after each lock %d not-yet-locked fields accepted a write and read back",
                isolated,
            )
        finally:
            # A compare that fails inside a step leaves it with the exception;
            # the gate is written after the next clock edge.
            await RisingEdge(cocotb.top.clk_smc_i)
            self._gate(False)

        # S7: persistence on the probe
        jpi = self.fields[0][1]
        before = self._probe_word(jpi)
        assert before == self.shadow[jpi], (
            f"JPI word 0 probe 0x{before:08x} differs from the model 0x{self.shadow[jpi]:08x}"
        )
        assert before != 0, "JPI word 0 holds zero before the persistence write"
        fresh = self._fresh(rnd, 0, 0)
        await self._write_field("PERSIST_JPI0", jpi, fresh)
        after = self._probe_word(jpi)
        assert after == before, (
            f"JPI word 0 probe changed from 0x{before:08x} to 0x{after:08x} after a write of "
            f"0x{fresh:08x} with every lock set"
        )
        floor += 1
        self._done("S7")
        self._chk(
            "CHK-EMAP-LOCK-PERSIST",
            "JPI word0 probe before=0x%08x after=0x%08x unchanged after the %d-slot sweep "
            "(write attempted 0x%08x)",
            before,
            after,
            _SLOTS,
            fresh,
        )

        # S8: cold reset restore
        await self._cold_reset("locks", "sense2")
        self.locks_model = image.locks
        post = await self._read_locks("RESET")
        floor += 2
        self._done("S8")
        self._chk(
            "CHK-EMAP-LOCKS-BITWISE",
            "seed=%d %d bits set from 0 alone in order %s; bit %s preset by the image (no-op), "
            "sensed lo=0x%08x hi=0x%08x after the re-sense (SUPPLEMENTARY_LOCKS lo=0x%08x "
            "hi=0x%08x, the S3 and S5 supplementary bits cleared); after each write LOCKS == "
            "model; final lo=0x%08x hi=0x%08x (every assigned bit); after cold reset lo=0x%08x "
            "hi=0x%08x == image",
            self.seed,
            2 * _SLOTS - len(preset),
            [b for b in bits_written if b not in preset],
            ",".join(str(b) for b in preset),
            rs[0],
            rs[1],
            srs[0],
            srs[1],
            final[0],
            final[1],
            post[0],
            post[1],
        )
        self.access_floor = floor

        # fence
        assert [s for s, _t in self._stamps] == list(_STEPS), (
            f"steps completed {[s for s, _t in self._stamps]}, expected {list(_STEPS)}"
        )
        times = [t for _s, t in self._stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        chk_step = {
            "CHK-EMAP-LOCKS-SENSED": "S2",
            "CHK-EMAP-LOCKS-HALVES": "S3",
            "CHK-EMAP-LOCKS-IDEMPOTENT": "S4",
            "CHK-EMAP-LOCKS-WIDE": "S5",
            "CHK-EMAP-SLOT-MAP": "S6",
            "CHK-EMAP-SLOT-ISOLATION": "S6",
            "CHK-EMAP-LOCK-PERSIST": "S7",
            "CHK-EMAP-LOCKS-BITWISE": "S8",
        }
        printed = [ident for kind, ident in self._events if kind == "chk"]
        assert printed == list(chk_step), f"checker lines printed {printed}"
        for index, (kind, ident) in enumerate(self._events):
            if kind == "chk":
                assert ("step", chk_step[ident]) in self._events[:index], (
                    f"{ident} printed before step {chk_step[ident]} completed"
                )
        pos = {ident: i for i, (_k, ident) in enumerate(self._events)}
        assert (
            pos["CHK-EMAP-LOCKS-SENSED"]
            < pos["CHK-EMAP-LOCKS-HALVES"]
            < pos["CHK-EMAP-LOCKS-IDEMPOTENT"]
            < pos["CHK-EMAP-LOCKS-WIDE"]
            < pos["S5R"]
            < pos["CHK-EMAP-LOCKS-BITWISE"]
        ) and pos["CHK-EMAP-SLOT-MAP"] < pos["CHK-EMAP-LOCK-PERSIST"] < pos["S8"]
        cocotb.log.info(
            "CHK-NONVAC: ordered fence SENSED < HALVES < IDEMPOTENT < WIDE < RESENSE < BITWISE "
            "and SLOT-MAP < PERSIST < RESET; checker lines %s; stamps %s ps",
            ", ".join(printed),
            ", ".join(f"{s}={t}" for s, t in self._stamps),
        )
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s",
            len(self._waits),
            " ".join(
                f"{name}={bound}smc_clk(fails with AssertionError on expiry) last={state}"
                for name, bound, state in self._waits
            ),
        )
