# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN transfer shape: narrow sizes, byte strobes, and burst types.

``port_table.adoc`` declares ``sep_axi_in_req_i`` as a 64-bit AXI4 input, and
``smc_local_xbar.sv`` converts it to the 32-bit local AXI-Lite fabric through
``axi_dw_converter -> axi_to_axi_lite``. That path is under test; the
expectations below come from AXI4 strobe and burst arithmetic, and the refused
burst types from the DV-owned rule stated with them:

* AxSIZE below the bus width is a narrow transfer, and the byte strobes the
  master derives from the address select the lanes. A 1-byte write must leave
  the other three bytes of the addressed word alone and a 2-byte write must
  leave the other half alone, so the readback word is the merge of the three
  writes rather than any one of them.
* A multi-beat INCR burst is split into consecutive single-beat accesses, so
  the two beats of a 2-beat burst land in two consecutive registers and a
  2-beat burst read returns them in the same order.
* FIXED and WRAP multi-beat bursts: the SMC fabric chapter (``fabric.adoc``)
  does not state how the SEP_IN path answers a burst type it does not
  support, so the expectation is the DV-owned one for a refused write -- an
  AXI error response of either kind, never OKAY and never a wedge -- and the
  registers the burst addressed, read back before any further write, must keep
  the values the INCR burst left, so a path that errored the response but still
  wrote is caught. The code actually
  returned is reported, not asserted, because no specification statement
  fixes it.
* A 16-beat INCR burst of full-width beats into the SPM: every beat must land
  at its own address and a 16-beat read must return them in order, so a
  splitter that drops, repeats or reorders beats past the first few is caught.
* A 2-beat FIXED burst of full-width beats to the scratch registers: the
  response is tolerated either way and reported, since the same fabric
  statement is missing for it, and its payload equals what the registers
  already hold, so a path that stores it changes nothing the readbacks test.

SCRATCH_COLD_0/1 are the targets: plain read/write storage with no side
effects, restored to zero before the sequence ends.
"""

from __future__ import annotations

import os
import random

import cocotb
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_0 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_COLD_1 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)

BURST_FIXED = 0
BURST_INCR = 1
BURST_WRAP = 2

# Word written first, then partially overwritten by the narrow accesses.
WORD_SEED = 0x1111_1111
NARROW_BYTE = 0xAB
NARROW_HALF = 0xBEEF
WORD_AFTER_BYTE = 0x1111_11AB
WORD_AFTER_HALF = 0xBEEF_11AB

# Two beats of the INCR burst; the second must land in SCRATCH_COLD_1.
BURST_BEAT0 = 0x5A5A_0001
BURST_BEAT1 = 0x5A5A_0002
# Payload of the rejected FIXED / WRAP bursts, which must never be stored.
REJECTED_BEAT0 = 0xDEAD_0001
REJECTED_BEAT1 = 0xDEAD_0002
# FIXED and WRAP bursts of two beats at the byte, half-word and double-word
# sizes the 2-beat bursts above leave out. SCRATCH_COLD_0 is 16-byte aligned,
# so every WRAP here is aligned to its total size as AXI requires.
NARROW_REJECT_SHAPES = (
    ("fixed_byte_burst", 1, BURST_FIXED),
    ("wrap_byte_burst", 1, BURST_WRAP),
    ("fixed_half_burst", 2, BURST_FIXED),
    ("wrap_half_burst", 2, BURST_WRAP),
    ("wrap_dword_burst", 8, BURST_WRAP),
)


def _narrow_reject_payload(length: int) -> int:
    beat = int.from_bytes(bytes([0xD0 + i for i in range(length)]), "little")
    return (beat << (8 * length)) | beat


# Sixteen full-width beats into the SPM, above the window other hosted
# sequences use and below the top of the memory.
LONG_BURST_BEATS = 16
LONG_BURST_BYTES = 8
LONG_BURST_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x3_0000


def long_beat(index: int) -> int:
    return (0x10B0_0000_0000_0000 | (index << 32)) ^ (0x0000_0000_C0DE_0000 | index)


LONG_BURST_PAYLOAD = sum(long_beat(i) << (64 * i) for i in range(LONG_BURST_BEATS))
# Last page of the unmapped gap below mmode_region, which the fabric error
# slave answers with DECERR on the write channel as on the read channel the
# error-depth test proves.
UNIMPLEMENTED_ADDR = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR") - 0x1000
AXI_RESP_DECERR = 3

# Seed-drawn shapes after the pinned legs: INCR of one or two beats on the two
# scratch registers, INCR of three to sixteen beats into an SPM page, and FIXED
# or WRAP bursts on the scratch pair, each at a drawn AxSIZE and aligned
# offset, plus one zero-strobe beat. One shape of each kind is drawn first and
# the remaining two kinds are drawn freely, so every seed carries every kind.
# A byte model of SCRATCH_COLD_0/1 gives the exact read-back after every shape.
DRAWN_SHAPES = 6
SCRATCH_PAIR_BYTES = 8
SPM_DRAW_PAGE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x3_1000
SPM_PAGE_BYTES = 0x1000
SHAPE_KINDS = ("incr_scratch", "incr_spm", "fixed", "wrap")
BURST_NAME = {BURST_FIXED: "FIXED", BURST_INCR: "INCR", BURST_WRAP: "WRAP"}


def draw_shapes(rng: random.Random) -> list[tuple[str, int, int, int, int, int]]:
    """(kind, AxSIZE, beats, byte offset, burst type, payload) per drawn shape."""
    plan = []
    kinds = list(SHAPE_KINDS)
    kinds += [rng.choice(SHAPE_KINDS) for _ in range(DRAWN_SHAPES - len(SHAPE_KINDS))]
    for kind in kinds:
        if kind == "incr_scratch":
            size = rng.choice((1, 2, 4))
            beats = rng.choice((1, 2))
            offset = rng.randrange(0, SCRATCH_PAIR_BYTES - beats * size + 1, size)
            burst = BURST_INCR
        elif kind == "incr_spm":
            size = rng.choice((1, 2, 4, 8))
            beats = rng.randint(3, 16)
            offset = rng.randrange(0, SPM_PAGE_BYTES - beats * size + 1, size)
            burst = BURST_INCR
        elif kind == "fixed":
            size = rng.choice((1, 2, 4))
            beats = rng.randint(2, 8)
            offset = rng.randrange(0, SCRATCH_PAIR_BYTES - size + 1, size)
            burst = BURST_FIXED
        else:
            size = rng.choice((1, 2, 4))
            beats = rng.choice([b for b in (2, 4, 8) if b * size <= SCRATCH_PAIR_BYTES])
            offset = rng.randrange(0, SCRATCH_PAIR_BYTES - size + 1, size)
            burst = BURST_WRAP
        plan.append((kind, size, beats, offset, burst, rng.getrandbits(8 * size * beats)))
    assert {kind for kind, *_rest in plan} == set(SHAPE_KINDS), plan
    return plan


def drawn_accesses(plan) -> int:
    return sum(4 if kind == "incr_spm" else 3 for kind, *_rest in plan) + 3


# Accesses this sequence issues over SEP_IN, before the NARROW_REJECT_SHAPES
# legs, which add three accesses each whatever their response, and before the
# drawn shapes.
BASE_ACCESSES = 28
PINNED_ACCESSES = BASE_ACCESSES + 3 * len(NARROW_REJECT_SHAPES)
# Scoreboard value compares the sequence must book: the seventeen reads outside
# NARROW_REJECT_SHAPES all carry an expectation. The readbacks after a refused
# shape add to it only when a shape is refused.
MIN_VALUE_CHECKS = 17


class smc_sep_in_axi_shape_test_seq(SmcCsrSeq):
    """Narrow sizes, byte strobes, INCR bursts and rejected burst types."""

    def __init__(self, name: str = "smc_sep_in_axi_shape_test_seq") -> None:
        super().__init__(name)
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        self.value_checks: int | None = None
        self.shape_resps: dict[str, int] = {}
        self.drawn_lines: dict[str, list[str]] = {k: [] for k in SHAPE_KINDS}
        self.zero_strobe_line = ""

    async def _axi(
        self,
        label: str,
        op: SmcSysAxiOp,
        addr: int,
        *,
        length: int = 4,
        beats: int = 1,
        burst: int = BURST_INCR,
        wdata: int = 0,
        expected: int | None = None,
        expect_error: bool = False,
        allow_error: bool = False,
    ) -> SmcSysAxiItem:
        item = SmcSysAxiItem(f"{op.value}_{label}")
        item.op = op
        item.addr = addr
        item.length = length
        item.beats = beats
        item.burst = burst
        item.wdata = wdata
        item.expected = expected
        if expect_error or allow_error:
            item.allow_error = True
        if expect_error:
            item.expect_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item

    async def _pair_words(self, label: str, model: bytearray) -> None:
        """Read both scratch words back against the byte model (exact compares)."""
        word0 = int.from_bytes(model[0:4], "little")
        word1 = int.from_bytes(model[4:8], "little")
        await self._axi(f"{label}_rb0", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=word0)
        await self._axi(f"{label}_rb1", SmcSysAxiOp.READ, SCRATCH_COLD_1, expected=word1)

    async def _drawn_shape(self, n: int, shape, model: bytearray) -> None:
        kind, size, beats, offset, burst, payload = shape
        label = f"drawn{n}_{kind}"
        total = size * beats
        head = f"#{n} {BURST_NAME[burst]} size={size} beats={beats} +0x{offset:x}"
        if kind == "incr_scratch":
            await self._axi(
                label,
                SmcSysAxiOp.WRITE,
                SCRATCH_COLD_0 + offset,
                length=size,
                beats=beats,
                wdata=payload,
            )
            model[offset : offset + total] = payload.to_bytes(total, "little")
            await self._pair_words(label, model)
            self.drawn_lines[kind].append(f"{head} OKAY, both words read back from the model")
        elif kind == "incr_spm":
            base = SPM_DRAW_PAGE + offset
            await self._axi(label, SmcSysAxiOp.WRITE, base, length=size, beats=beats, wdata=payload)
            beat_mask = (1 << (8 * size)) - 1
            await self._axi(
                f"{label}_beat0", SmcSysAxiOp.READ, base, length=size, expected=payload & beat_mask
            )
            await self._axi(
                f"{label}_beat_last",
                SmcSysAxiOp.READ,
                base + (beats - 1) * size,
                length=size,
                expected=(payload >> (8 * size * (beats - 1))) & beat_mask,
            )
            await self._axi(
                f"{label}_rd", SmcSysAxiOp.READ, base, length=size, beats=beats, expected=payload
            )
            self.drawn_lines[kind].append(
                f"{head} at 0x{base:08x} OKAY, first and last beat and the whole burst read back"
            )
        else:
            item = await self._axi(
                label,
                SmcSysAxiOp.WRITE,
                SCRATCH_COLD_0 + offset,
                length=size,
                beats=beats,
                burst=burst,
                wdata=payload,
                allow_error=True,
            )
            if item.resp_code != 0:
                await self._pair_words(label, model)
                outcome = f"resp={item.resp_code} (reported), both words unchanged"
            else:
                word0 = int.from_bytes(model[0:4], "little")
                word1 = int.from_bytes(model[4:8], "little")
                await self._axi(f"{label}_reseed0", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=word0)
                await self._axi(f"{label}_reseed1", SmcSysAxiOp.WRITE, SCRATCH_COLD_1, wdata=word1)
                outcome = "resp=OKAY (reported), both words re-seeded"
            self.drawn_lines[kind].append(f"{head} {outcome}")

    async def _zero_strobe(self, size: int, offset: int, data: int, model: bytearray) -> None:
        item = SmcSysAxiItem("write_drawn_zero_strobe")
        item.op = SmcSysAxiOp.WRITE
        item.addr = SCRATCH_COLD_0 + offset
        item.length = size
        item.wdata = data
        item.wstrb = 0
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        assert not item.timed_out and item.resp_code is not None, "zero-strobe beat: no response"
        await self._pair_words("zero_strobe", model)
        self.zero_strobe_line = (
            f"zero-strobe beat size={size} +0x{offset:x} wdata=0x{data:x} BRESP={item.resp_code} "
            f"(reported), both words unchanged"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        rng = random.Random(self.seed)
        plan = draw_shapes(rng)
        zs_size = rng.choice((1, 2, 4))
        zs_offset = rng.randrange(0, SCRATCH_PAIR_BYTES - zs_size + 1, zs_size)
        zs_data = rng.getrandbits(8 * zs_size)
        drawn = (
            f"seed {self.seed} shapes "
            + " ".join(
                f"{k}/{BURST_NAME[b]}/size{sz}/beats{bt}/+0x{o:x}" for k, sz, bt, o, b, _p in plan
            )
            + f" zero_strobe size{zs_size}/+0x{zs_offset:x}"
        )
        cocotb.log.info("RAND-SEED: %d; RAND-DRAW: %s", self.seed, drawn)
        expected_accesses = PINNED_ACCESSES + drawn_accesses(plan)

        await self._axi("seed", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=WORD_SEED)
        await self._axi("seed_rb", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=WORD_SEED)

        # AxSIZE=0: one byte into lane 0, the upper three bytes untouched.
        await self._axi("byte", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, length=1, wdata=NARROW_BYTE)
        await self._axi("after_byte", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=WORD_AFTER_BYTE)
        # AxSIZE=1: two bytes into lanes 2 and 3, the lower half untouched.
        await self._axi("half", SmcSysAxiOp.WRITE, SCRATCH_COLD_0 + 2, length=2, wdata=NARROW_HALF)
        await self._axi("after_half", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=WORD_AFTER_HALF)
        # Narrow reads return the addressed lanes of the same word.
        await self._axi("byte_rd", SmcSysAxiOp.READ, SCRATCH_COLD_0, length=1, expected=NARROW_BYTE)
        await self._axi(
            "half_rd", SmcSysAxiOp.READ, SCRATCH_COLD_0 + 2, length=2, expected=NARROW_HALF
        )

        # AxLEN=1 INCR: beat 0 to SCRATCH_COLD_0, beat 1 to SCRATCH_COLD_1.
        burst_payload = (BURST_BEAT1 << 32) | BURST_BEAT0
        await self._axi(
            "incr_burst", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, beats=2, wdata=burst_payload
        )
        await self._axi("incr_beat0", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=BURST_BEAT0)
        await self._axi("incr_beat1", SmcSysAxiOp.READ, SCRATCH_COLD_1, expected=BURST_BEAT1)
        await self._axi(
            "incr_burst_rd", SmcSysAxiOp.READ, SCRATCH_COLD_0, beats=2, expected=burst_payload
        )

        # FIXED and WRAP multi-beat bursts: an error response, and nothing
        # stored. Each is read back before anything else writes the registers,
        # so a refused burst that was still committed is caught at its own
        # size and type.
        rejected_payload = (REJECTED_BEAT1 << 32) | REJECTED_BEAT0
        rejected: dict[str, SmcSysAxiItem] = {}
        for label, burst in (("fixed_burst", BURST_FIXED), ("wrap_burst", BURST_WRAP)):
            rejected[label] = await self._axi(
                label,
                SmcSysAxiOp.WRITE,
                SCRATCH_COLD_0,
                beats=2,
                burst=burst,
                wdata=rejected_payload,
                expect_error=True,
            )
            await self._axi(f"{label}_rb0", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=BURST_BEAT0)
            await self._axi(f"{label}_rb1", SmcSysAxiOp.READ, SCRATCH_COLD_1, expected=BURST_BEAT1)
        fixed, wrap = rejected["fixed_burst"], rejected["wrap_burst"]
        # A FIXED burst of full-width beats carries the words the registers
        # already hold, so whether the path stores or refuses it the readbacks
        # below still test the INCR result.
        fixed_wide = await self._axi(
            "fixed_wide_burst",
            SmcSysAxiOp.WRITE,
            SCRATCH_COLD_0,
            length=8,
            beats=2,
            burst=BURST_FIXED,
            wdata=(burst_payload << 64) | burst_payload,
            allow_error=True,
        )
        await self._axi("after_reject0", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=BURST_BEAT0)
        await self._axi("after_reject1", SmcSysAxiOp.READ, SCRATCH_COLD_1, expected=BURST_BEAT1)

        # The same two burst types at the other beat sizes a 64-bit manager may
        # issue. An error response must leave both registers as they were; an
        # OKAY is reported, and the registers are re-seeded for the next shape.
        for label, length, burst in NARROW_REJECT_SHAPES:
            item = await self._axi(
                label,
                SmcSysAxiOp.WRITE,
                SCRATCH_COLD_0,
                length=length,
                beats=2,
                burst=burst,
                wdata=_narrow_reject_payload(length),
                allow_error=True,
            )
            self.shape_resps[label] = item.resp_code
            if item.resp_code != 0:
                await self._axi(
                    f"{label}_rb0", SmcSysAxiOp.READ, SCRATCH_COLD_0, expected=BURST_BEAT0
                )
                await self._axi(
                    f"{label}_rb1", SmcSysAxiOp.READ, SCRATCH_COLD_1, expected=BURST_BEAT1
                )
            else:
                await self._axi(
                    f"{label}_reseed", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=BURST_BEAT0
                )
                await self._axi(
                    f"{label}_reseed1", SmcSysAxiOp.WRITE, SCRATCH_COLD_1, wdata=BURST_BEAT1
                )

        # AxLEN=15 INCR of full-width beats into the SPM, read back beat by
        # beat at both ends and as one burst.
        await self._axi(
            "long_burst",
            SmcSysAxiOp.WRITE,
            LONG_BURST_BASE,
            length=LONG_BURST_BYTES,
            beats=LONG_BURST_BEATS,
            wdata=LONG_BURST_PAYLOAD,
        )
        await self._axi(
            "long_beat0", SmcSysAxiOp.READ, LONG_BURST_BASE, length=8, expected=long_beat(0)
        )
        await self._axi(
            "long_beat_last",
            SmcSysAxiOp.READ,
            LONG_BURST_BASE + (LONG_BURST_BEATS - 1) * LONG_BURST_BYTES,
            length=8,
            expected=long_beat(LONG_BURST_BEATS - 1),
        )
        await self._axi(
            "long_burst_rd",
            SmcSysAxiOp.READ,
            LONG_BURST_BASE,
            length=LONG_BURST_BYTES,
            beats=LONG_BURST_BEATS,
            expected=LONG_BURST_PAYLOAD,
        )

        # The drawn shapes on the scratch pair and the SPM page, then the
        # zero-strobe beat; the pair holds the INCR beats when they start.
        model = bytearray(
            ((BURST_BEAT1 << 32) | BURST_BEAT0).to_bytes(SCRATCH_PAIR_BYTES, "little")
        )
        for n, shape in enumerate(plan):
            await self._drawn_shape(n, shape, model)
        await self._zero_strobe(zs_size, zs_offset, zs_data, model)

        # The write channel of a region with no block behind it.
        monitor = getattr(getattr(self, "env", None), "axi_monitor", None)
        if monitor is not None:
            monitor.expected_decerr_addrs.add(UNIMPLEMENTED_ADDR)
        dead_wr = await self._axi(
            "unimplemented_wr",
            SmcSysAxiOp.WRITE,
            UNIMPLEMENTED_ADDR,
            wdata=0xDEAD_0000,
            allow_error=True,
        )
        assert dead_wr.resp_code == AXI_RESP_DECERR, (
            f"SEP_IN write to unimplemented 0x{UNIMPLEMENTED_ADDR:08x} answered "
            f"resp={dead_wr.resp_code}, expected DECERR"
        )

        await self._axi("restore0", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=0)
        await self._axi("restore1", SmcSysAxiOp.WRITE, SCRATCH_COLD_1, wdata=0)

        self.assert_all_reachable(expected_accesses, "SEP_IN transfer shape")
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen

        cocotb.log.info(
            "CHK-SEP-IN-NARROW-STROBES: SCRATCH_COLD_0 0x%08x -> AxSIZE=0 byte 0x%02x -> "
            "0x%08x -> AxSIZE=1 half 0x%04x at +2 -> 0x%08x; narrow reads returned "
            "0x%02x and 0x%04x; drawn %s; drawn=%s",
            WORD_SEED,
            NARROW_BYTE,
            WORD_AFTER_BYTE,
            NARROW_HALF,
            WORD_AFTER_HALF,
            NARROW_BYTE,
            NARROW_HALF,
            self.zero_strobe_line,
            drawn,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-INCR: AxLEN=1 INCR write placed 0x%08x in SCRATCH_COLD_0 and "
            "0x%08x in SCRATCH_COLD_1, and the AxLEN=1 INCR read returned 0x%016x; drawn INCR "
            "on the scratch pair: %s; drawn=%s",
            BURST_BEAT0,
            BURST_BEAT1,
            burst_payload,
            "; ".join(self.drawn_lines["incr_scratch"]) or "none drawn",
            drawn,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-UNSUPPORTED: AxLEN=1 FIXED refused with resp=%s and AxLEN=1 WRAP "
            "refused with resp=%s (error codes reported, not asserted: no specification fixes "
            "them); SCRATCH_COLD_0/1 still hold 0x%08x / 0x%08x; at the other beat sizes %s, "
            "each refused one leaving both registers unchanged; drawn FIXED/WRAP shapes: %s; "
            "drawn=%s",
            fixed.resp_code,
            wrap.resp_code,
            BURST_BEAT0,
            BURST_BEAT1,
            ", ".join(f"{k}=resp {v}" for k, v in self.shape_resps.items()),
            "; ".join(self.drawn_lines["fixed"] + self.drawn_lines["wrap"]) or "none drawn",
            drawn,
        )
        cocotb.log.info(
            "CHK-SEP-IN-DECERR-WRITE: SEP_IN write to the unmapped page 0x%08x answered DECERR",
            UNIMPLEMENTED_ADDR,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-LONG: AxLEN=%d INCR write of %d-byte beats at 0x%08x read back "
            "beat 0 = 0x%016x and beat %d = 0x%016x, and the AxLEN=%d read returned every beat "
            "in order; the AxLEN=1 FIXED burst of 8-byte beats answered resp=%s (reported, not "
            "asserted); drawn INCR bursts into the SPM page: %s; drawn=%s",
            LONG_BURST_BEATS - 1,
            LONG_BURST_BYTES,
            LONG_BURST_BASE,
            long_beat(0),
            LONG_BURST_BEATS - 1,
            long_beat(LONG_BURST_BEATS - 1),
            LONG_BURST_BEATS - 1,
            fixed_wide.resp_code,
            "; ".join(self.drawn_lines["incr_spm"]) or "none drawn",
            drawn,
        )
