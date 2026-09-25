# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN transfer shape: narrow sizes, byte strobes, and burst types.

``port_table.adoc`` declares ``sep_axi_in_req_i`` as a 64-bit AXI4 input, and
``smc_local_xbar.sv`` converts it to the 32-bit local AXI-Lite fabric through
``axi_dw_converter -> axi_to_axi_lite``. Three properties of that path are
exercised here, each against an expectation the conversion chain fixes:

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
  registers the burst addressed must keep the values the INCR burst left, so a
  path that errored the response but still wrote is caught. The code actually
  returned is reported, not asserted; a specification statement fixing it
  would let this become an exact expectation.
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
# Sixteen full-width beats into the SPM, above the window other hosted
# sequences use and below the top of the memory.
LONG_BURST_BEATS = 16
LONG_BURST_BYTES = 8
LONG_BURST_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR") + 0x3_0000


def long_beat(index: int) -> int:
    return (0x10B0_0000_0000_0000 | (index << 32)) ^ (0x0000_0000_C0DE_0000 | index)


LONG_BURST_PAYLOAD = sum(long_beat(i) << (64 * i) for i in range(LONG_BURST_BEATS))

# Accesses this sequence issues over SEP_IN, counted for the reachability gate.
EXPECTED_ACCESSES = 23
# Scoreboard value compares the sequence must book: all thirteen reads carry
# an expectation, so all thirteen are compared by the scoreboard.
MIN_VALUE_CHECKS = 13


class smc_sep_in_axi_shape_test_seq(SmcCsrSeq):
    """Narrow sizes, byte strobes, INCR bursts and rejected burst types."""

    def __init__(self, name: str = "smc_sep_in_axi_shape_test_seq") -> None:
        super().__init__(name)
        self.value_checks: int | None = None

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

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

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

        # FIXED and WRAP multi-beat bursts: an error response, and nothing stored.
        rejected_payload = (REJECTED_BEAT1 << 32) | REJECTED_BEAT0
        fixed = await self._axi(
            "fixed_burst",
            SmcSysAxiOp.WRITE,
            SCRATCH_COLD_0,
            beats=2,
            burst=BURST_FIXED,
            wdata=rejected_payload,
            expect_error=True,
        )
        wrap = await self._axi(
            "wrap_burst",
            SmcSysAxiOp.WRITE,
            SCRATCH_COLD_0,
            beats=2,
            burst=BURST_WRAP,
            wdata=rejected_payload,
            expect_error=True,
        )
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

        await self._axi("restore0", SmcSysAxiOp.WRITE, SCRATCH_COLD_0, wdata=0)
        await self._axi("restore1", SmcSysAxiOp.WRITE, SCRATCH_COLD_1, wdata=0)

        self.assert_all_reachable(EXPECTED_ACCESSES, "SEP_IN transfer shape")
        self.value_checks = self.env.scoreboard.sys_axi_value_checks_seen

        cocotb.log.info(
            "CHK-SEP-IN-NARROW-STROBES: SCRATCH_COLD_0 0x%08x -> AxSIZE=0 byte 0x%02x -> "
            "0x%08x -> AxSIZE=1 half 0x%04x at +2 -> 0x%08x; narrow reads returned "
            "0x%02x and 0x%04x",
            WORD_SEED,
            NARROW_BYTE,
            WORD_AFTER_BYTE,
            NARROW_HALF,
            WORD_AFTER_HALF,
            NARROW_BYTE,
            NARROW_HALF,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-INCR: AxLEN=1 INCR write placed 0x%08x in SCRATCH_COLD_0 and "
            "0x%08x in SCRATCH_COLD_1, and the AxLEN=1 INCR read returned 0x%016x",
            BURST_BEAT0,
            BURST_BEAT1,
            burst_payload,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-UNSUPPORTED: AxLEN=1 FIXED refused with resp=%s and AxLEN=1 WRAP "
            "refused with resp=%s (error codes reported, not asserted: no specification fixes "
            "them); SCRATCH_COLD_0/1 still hold 0x%08x / 0x%08x",
            fixed.resp_code,
            wrap.resp_code,
            BURST_BEAT0,
            BURST_BEAT1,
        )
        cocotb.log.info(
            "CHK-SEP-IN-BURST-LONG: AxLEN=%d INCR write of %d-byte beats at 0x%08x read back "
            "beat 0 = 0x%016x and beat %d = 0x%016x, and the AxLEN=%d read returned every beat "
            "in order; the AxLEN=1 FIXED burst of 8-byte beats answered resp=%s (reported, not "
            "asserted)",
            LONG_BURST_BEATS - 1,
            LONG_BURST_BYTES,
            LONG_BURST_BASE,
            long_beat(0),
            LONG_BURST_BEATS - 1,
            long_beat(LONG_BURST_BEATS - 1),
            LONG_BURST_BEATS - 1,
            fixed_wide.resp_code,
        )
