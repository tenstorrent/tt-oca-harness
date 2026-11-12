# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA transfer matrix: address modes, widths, geometry, range edges, inline hash.

RANDOMIZED (SepSeededRng from the run seed). The leaf programs the secure DMA
over the CPU-LSU splice ``s_axi`` (no CPU); the Leg A cells alternate, from a
drawn first cell, between ``s_axi`` and the SMN-inbound master ``m_axi``, which
reaches the DMA registers through one inbound filter entry over the block.
It runs four legs on SEP SRAM (``memory_map.adoc``, 0x1000_0000 to
0x1003_FFFF), then the alias, one-byte-chunk, start, range and logged runs
below:

* Leg A: the 16 source {INCREMENT, WRAP} x destination {INCREMENT, WRAP}
  cells, each at a drawn width encoding (every encoding on every seed), a
  drawn chunk size and a drawn chunk count. The expected destination image
  and beat addresses come from ``env/sep_dma_model.DmaXfer``, a model of the
  register text (``secure_dma.adoc``, SRC_CONFIG, DST_CONFIG,
  TRANSFER_WIDTH). The cells that ``sep_dma_basic_test`` grades run only with
  two or more chunks (three or more for the source-wrap pair).
* Leg B: single-chunk totals 4 bytes and a drawn 64 to 4096 bytes, 16384 bytes
  as four 4096-byte chunks and two drawn multi-chunk transfers, back to back
  with no software clear of STATUS.DONE between them.
* Narrow-width and large copies: one copy at width encoding 0 and one at
  width encoding 1, each 1028 to 16384 bytes, and one copy at width encoding
  2 of 16388 to 65536 bytes. Each is INCREMENT on both sides in equal chunks
  of at most 4096 bytes, drawn on a separate seed stream.
* Leg C: ENABLED_MEMORY_RANGE_BASE and LIMIT exactly on the region edges (low,
  high, both, and both with a guard outside the range at the low end, the
  high end and both ends). Each cell runs two zero fills, the operation the
  range bounds (``hw/sys/sep/doc/dma.adoc:98-104``; the range does not bound
  an internal copy, ``:105``): one of the low region from BASE and one of the
  high region up to LIMIT, in a drawn order, with a wide-range control run of
  the same fills.
* Leg D: SHA-256, SHA-384 and SHA-512 inline hashing on the published 56-byte
  and 112-byte vectors at both DIGEST_SWAP values, two drawn lengths per
  algorithm, an equal split of each message into 2 to 4 chunks of one
  transfer, and one long message. The digest golden comes from Python
  ``hashlib``; the leaf never takes an expected value from the DUT.
* Leg D continuation: for each SHA-2 algorithm, one message of a drawn
  boundary length in 2 to 4 equal chunks of one transfer. The first start
  writes the algorithm and a drawn DIGEST_SWAP; each later start writes
  CONTROL with GO=1, INITIAL_TRANSFER=0, an OPCODE drawn from the two other
  SHA-2 opcodes and the inverted DIGEST_SWAP.

DIGEST_SWAP: "If 1 the value in each digest output register is converted to
big-endian byte order. This setting does not affect the order of the digest
output registers, SHA2_DIGEST_0 still contains the first 4 bytes of the
digest." (``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl:228-229``).
Read over the little-endian bus, byte lane j (bits 8j+7:8j) of SHA2_DIGEST_i
holds digest byte 4i+j with DIGEST_SWAP=1, and digest byte 4i+3-j with
DIGEST_SWAP=0 (the SHA-2 digest is a byte string whose first byte is byte 0).

Probes: register and SRAM frontdoor over ``s_axi``, register frontdoor over
``m_axi`` (Leg A rotation and the 64-bit access); ``dma_busy_probe_o``;
bit 9 of ``sep_internal_interrupts_probe_o`` (PIC source 10, DMA chunk done);
the observation taps ``dma_axi_req_probe_o`` (DMA master AR/AW/W/B after the
alias remap) and ``dma_status_probe_o`` (STATUS levels), read through
``env/sep_dma_tap.py``, and ``dma_axi_wdata_probe_o`` (the W data of the same
request), read with the W handshake of ``dma_axi_req_probe_o`` by the
test-local ``_WdataSampler``. Hooks (``docs/SEP_TB_ARCH.adoc``): the m_axi WSTRB
drive of one half-strobe write, and ``smn_outbound_resp_hold_i`` of the
outbound responder for one logged run.

Checkers (log shape ``CHK-<ID> PASS|FAIL seed=<n> ...``):
  CHK-DMA-IMAGE       per Leg A cell: destination and guard words equal the
                      model image; STATUS.ERROR and ERROR_CODE read 0.
  CHK-DMA-BEAT        per Leg A cell: AxLEN 0 on every AR and AW, AR and AW
                      and W counts equal TOTAL/width, WSTRB popcount equals the
                      width, read address step 4 inside a chunk at width 4.
  CHK-DMA-ADDR        per Leg A cell: every AR/AW address equals the model
                      (AxADDR[31:2]; the full address at width 4) and every
                      WSTRB equals ((1 << w) - 1) << (AWADDR mod 8) at every
                      width (AMBA AXI protocol specification (IHI 0022),
                      narrow transfers). AxADDR[1:0] at widths 1 and 2, and
                      ARSIZE and AWSIZE at every width, are logged only in
                      ``OBS-DMA-ADDR-LOW``.
  CHK-DMA-WDATA-LANE  per Leg A cell, alias-form copy, width-1 one-byte-chunk
                      copy and Leg B transfer: the W beat count equals
                      TOTAL/width, and on W beat k the bytes of lanes
                      L to L+w-1 (L = model AWADDR mod 8, the lanes WSTRB
                      enables) equal the w source bytes at the model source
                      address of transaction k (IHI 0022, narrow transfers;
                      ``secure_dma.adoc`` TRANSFER_WIDTH). Other lanes are not
                      graded. Reach (else CTRL-MISSING): INFO-DMA-WDATA-REACH
                      counts more than 0 graded beats.
  CHK-DMA-MASTER-ROT  per Leg A cell, before GO: each transfer register read
                      back on the programming master (``s_axi`` or ``m_axi``)
                      equals the value written and differs from the value read
                      before the write (a register that held the value is
                      first written with its inverse); the cell's checks then grade
                      the transfer (``hw/sys/sep/doc/fabric.adoc:102-103``,
                      dma_csr reached from LSU and EXT). Control
                      (else CTRL-MISSING): both masters program a cell.
  CHK-DMA-DIGEST-RESET before the first hash: SHA2_DIGEST_0..15 read the RDL
                      reset value 0.
  CHK-DMA-ALIAS-FORM  three copies (widths 1, 2, 4; drawn side, mode and
                      chunking; a fixed side runs one chunk) and one SHA-2 run
                      programmed in the local-alias form (``fabric.adoc:155-156``,
                      ``memory_map.adoc:37``): image, AR/AW addresses and
                      WSTRB, or the digest, equal the direct-form golden
                      (``env/sep_dma_model.DmaXfer``, hashlib). Control (else
                      CTRL-MISSING): SEP_LOCAL_BASE_ADDR reads its reset value.
                      The fixed-source two-chunk run of OBS-DMA-FIXED-CHUNK
                      takes a drawn direct or alias form and stays logged.
  CHK-DMA-CHUNK1      width 1 with CHUNK_DATA_SIZE 1 (the stated minimum) on a
                      drawn 2 to 16 bytes: image, beat counts, addresses and
                      WSTRB equal the model, n-1 to n CHUNK_DONE rises, n-1
                      stop reads and n GO writes; the Leg A checks follow.
  CHK-DMA-RW1C        per Leg D continuation stop: a STATUS write of 0 leaves
                      CHUNK_DONE 1 and a write of CHUNK_DONE clears it
                      (``dma.adoc:131-132``).
  CHK-DMA-RO-HOLD     after each Leg D continuation run: each SHA2_DIGEST word
                      v reads v after a write of ~v (``sw = r``); the write
                      response is logged.
  CHK-DMA-NOGO        CONTROL with INITIAL_TRANSFER=1 and GO=0: no AR or AW,
                      no BUSY rise and BUSY=0, DONE unchanged over 2000 clocks
                      (``dma.adoc:79-80``). Controls: CTRL-DMA-NOGO-WR, CONTROL
                      reads INITIAL_TRANSFER=1 GO=0 after the window; and
                      CTRL-DMA-NOGO-GO, the GO=1 write after it raises BUSY
                      within the same 2000 clocks and moves the copy.
  CHK-DMA-RANGE-COPY  an SRAM copy whose destination crosses LIMIT part-way
                      completes: DONE=1, ERROR=0, ERROR_CODE=0, the model AR
                      and AW, the model image (``dma.adoc:106``). Control
                      CTRL-DMA-RANGE-COPY: a zero fill of the same
                      destination under the same range stops at LIMIT with
                      ERROR_CODE.DST_ADDR_ERROR (``dma.adoc:98-104``).

Logged only (no stated value): OBS-DMA-CHUNK1-W4 (width 4 with
CHUNK_DATA_SIZE 1), OBS-DMA-BASELIM-COPY (a copy with BASE = LIMIT),
OBS-DMA-SHORT-LAST-CHUNK (TOTAL_DATA_SIZE not a multiple of CHUNK_DATA_SIZE),
OBS-DMA-CSR-64 (64-bit m_axi read, write and half-strobe write of a DMA
register pair), OBS-DMA-BEAT-HOLD (a DMA read whose response the outbound
responder holds for 20000 clocks) and OBS-DMA-SIZE-LARGE (the width-2 copy
above 16384 bytes: how it ended, STATUS, ERROR_CODE, AW and W counts against
TOTAL/4, destination mismatch words and guards; no text states a maximum
TOTAL_DATA_SIZE, ``secure_dma.rdl:176``). A logged run that has not ended
after its GO cap or poll bound is aborted and must reach BUSY=0.
  CHK-DMA-GEOM        per Leg B transfer and per narrow-width copy (line
                      ``leg=N width_enc=<0|1>``): DONE=1, BUSY=0, GO=0,
                      ERROR=0, ERROR_CODE=0, destination equals the model
                      image of the source (``secure_dma.rdl:199``, transactions
                      of the width until TOTAL_DATA_SIZE bytes), guards
                      intact. Control: a CONTROL read with GO=1 while
                      ``dma_busy_probe_o`` is 1 (Leg B); the destination
                      is filled with the sentinel before GO.
  CHK-DMA-CFG-REGWEN  Leg B totals of 1024 bytes or more: a CFG_REGWEN read
                      that runs entirely at ``dma_busy_probe_o`` = 1 shows
                      REGWEN = kMultiBitBool4False (0x9), and the read after
                      DONE=1 BUSY=0, entirely at ``dma_busy_probe_o`` = 0,
                      shows kMultiBitBool4True (0x6). Each read is the control
                      of the other. A long transfer with no read at BUSY=1
                      fails as CTRL-MISSING.
  CHK-DMA-DONE-CLR    Leg B totals of 1024 bytes or more after the first: a
                      STATUS read with BUSY=1 shows DONE=0. Control: DONE=1 on
                      the read just before GO.
  CHK-DMA-CHUNKDONE   Leg B single-chunk transfers read CHUNK_DONE=0 on every
                      poll. Control: the multi-chunk transfers show
                      CHUNK_DONE=1 on a poll or a rise of PIC source 10.
  CHK-DMA-CHUNKRISE   per Leg A and Leg B transfer: n-1 to n CHUNK_DONE rises
                      (none for one chunk), each of the first n-1 followed by a
                      hardware fall, no STATUS write in the window.
  CHK-DMA-DONE-ORDER  per Leg A and Leg B transfer: B count equals AW count,
                      and no DONE rise comes before the last B handshake.
  CHK-DMA-GO-CHUNKS   per Leg A and Leg B transfer of n >= 2 chunks: exactly
                      n-1 STATUS reads show CHUNK_DONE=1, BUSY=0, DONE=0, and
                      at the start of each later GO write the AW and W counts
                      equal the transactions of the chunks before it. Control:
                      the Leg B single-chunk transfers show no such read.

Multi-chunk start contract (CHK-DMA-GO-CHUNKS): "A start is a write of
`CONTROL.GO` while `STATUS.BUSY` is clear: the first chunk of a transfer, with
`INITIAL_TRANSFER` set, or a later chunk, with `GO` alone" (``dma.adoc:79-81``);
"For a transfer in several chunks without hardware handshake, wait for
`STATUS.CHUNK_DONE` after each chunk and start the next one by writing
`CONTROL` with `GO=1` and `INITIAL_TRANSFER=0`" (``sep-programming.adoc:768-770``);
STATUS.CHUNK_DONE: "Transfer of a single chunk is complete. Only raised for
multi-chunk memory-to-memory transfers" (``secure_dma.rdl:327-328``).
DONE = 0 at those stops: "**Transfer Completion:** An interrupt is raised when
the entire data transfer (as defined by `TOTAL_DATA_SIZE`) is complete."
(``vendor/lowRISC/opentitan/upstream/hw/ip/dma/doc/programmers_guide.md:34``),
and "Since interrupts are implemented as status bits" (same file, line 39).
In Leg A and Leg B the leaf writes one GO per stop it reads; the GO count is
stimulus and is not graded there.

Leg D chunk contract (CHK-DMA-HASH-CHAIN, CHK-DMA-CONT-CFG): CHUNK_DATA_SIZE is
"Size (in bytes) for a single DMA transfer" and ``sw = rw``
(``secure_dma.rdl:182``, ``:184``); TOTAL_DATA_SIZE "may consist of multiple
chunks of data as specified by the CHUNK_DATA_SIZE register"
(``secure_dma.adoc:211-212``); STATUS.CHUNK_DONE "Only raised for multi-chunk
memory-to-memory transfers. Cleared automatically by the hardware when starting
the transfer of a new chunk." (``secure_dma.adoc:320-322``); "Chunk completion
applies to multi-chunk transfers without hardware handshake"
(``hw/sys/sep/doc/dma.adoc:130``); and the stop and next GO of
``sep-programming.adoc:768-770``. A transfer of L bytes in chunks of
L/k therefore stops k-1 times and takes k GO writes.

CFG_REGWEN contract (CHK-DMA-CFG-REGWEN): "In the idle state, this register is
set to kMultiBitBool4True. When the DMA is performing an operation, i.e. the
DMA is busy, this register is set to kMultiBitBool4False."
(``vendor/lowRISC/opentitan/upstream/hw/ip/dma/data/dma.hjson:352-353``), with
the encoding "True = 6; False = 9;"
(``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/secure_dma.rdl:158-159``).
The CONTROL read with GO=1 at BUSY=1 is the control of CHK-DMA-GEOM only; the
GO value during a transfer is not graded.
  CHK-DMA-RANGE-WR    per Leg C cell, before its copy: with RANGE_REGWEN read
                      True (0x6, else CTRL-MISSING), RANGE_VALID reads 0 after
                      a write of 0, and BASE, LIMIT and RANGE_VALID read back
                      the values written next. Control: over Leg C at least
                      one write changes BASE and one changes LIMIT (the guard
                      edges), else CTRL-MISSING.
  CHK-DMA-RANGE-OK    per Leg C cell: both zero fills end with DONE=1, ERROR=0
                      and ERROR_CODE=0, each with one AW and one W beat per
                      region word on the DMA master tap, every word of both
                      regions reads 0, and the in-range gap word and the guards
                      keep the prefill. A DUT that treats BASE or LIMIT as
                      exclusive refuses the first or the last write and fails.
                      Controls: the regions, the gap word and the guards read
                      the prefill before the first GO (CTRL-DMA-RANGE-PREFILL);
                      the same fills with the wide range.
  CHK-DMA-HASH        per graded Leg D run: digest words equal the hashlib
                      golden for the swap value; the copy equals the source.
                      Control: the destination reads the sentinel just
                      before each GO (CTRL-DMA-HASH-SENTINEL).
  CHK-DMA-HASH-VALID  per Leg D run: SHA2_DIGEST_VALID reads 1 after the chain;
                      on ``dma_status_probe_o`` it rises after the initial GO,
                      and when it was 1 before the GO it falls after the GO
                      and its last rise comes after that fall, before the
                      digest read; on the long message a BUSY=1 read shows
                      it 0. Controls: it reads 1 just before the GO of the
                      second run; at least one run of the seed has the
                      probe at 1 before its GO (CTRL-DMA-DV-FALL-REACH).
  CHK-DMA-HASH-CHAIN  per message with a split form: single-chunk and split
                      digests are equal; the split run of k chunks shows
                      exactly k-1 STATUS reads with CHUNK_DONE=1, BUSY=0,
                      DONE=0 and takes exactly k GO writes to DONE. Control
                      (``CTRL-DMA-CHUNK-RB``, else CTRL-MISSING):
                      CHUNK_DATA_SIZE reads L/k back before the GO.
  CHK-DMA-CONT-CFG    per Leg D continuation run: the digest words equal the
                      hashlib golden of the first-start algorithm in the
                      first-start byte order; DONE=1, STATUS.ERROR=0,
                      ERROR_CODE=0, SHA2_DIGEST_VALID=1 after the chain, the
                      probe edges of CHK-DMA-HASH-VALID, and the copy equals
                      the source; exactly k-1 stop reads and exactly k GO
                      writes as in CHK-DMA-HASH-CHAIN. Controls (else
                      CTRL-MISSING): CHUNK_DATA_SIZE reads L/k before the GO
                      (``CTRL-DMA-CHUNK-RB``); at
                      least one run of the seed has the probe at 1 before its GO; at
                      least one later start; a CONTROL read after each later start
                      shows the OPCODE and DIGEST_SWAP that start wrote, both
                      other than the first start; the digest registers
                      before the GO differ from the golden.
  CHK-DMA-CTRL-BUSY   on a seed that draws GO=1 for the CONTROL write at BUSY=1
                      during the 4096-byte single-chunk copy: after DONE and a
                      16-clock settle, the DMA master shows exactly the AR and
                      AW counts of that one copy (n_txn each), and exactly
                      one STATUS.BUSY rise since the GO. Control
                      (``CTRL-DMA-CTRL-BUSY``, else CTRL-MISSING): the write
                      answers OKAY, BUSY stays 1 through the write, and on the
                      tap STATUS.BUSY rose before the write and STATUS.DONE
                      rises after it; the line logs the write response, the
                      write clocks and their offsets from the BUSY rise and the
                      DONE rise. A
                      seed that draws GO=0 logs ``INFO-DMA-CTRL-BUSY-SKIP``
                      with the same fields; seed 1
                      draws GO=1. ``OBS-DMA-CTRL-BUSY`` logs the CONTROL value
                      read right after the write and after DONE, STATUS,
                      ERROR_CODE and the destination compare.

Busy write contract (CHK-DMA-CTRL-BUSY): "A start is a write of `CONTROL.GO`
while `STATUS.BUSY` is clear" (``hw/sys/sep/doc/dma.adoc:79-80``), so a GO=1
write at BUSY=1 is not a start; the engine takes its configuration at a start
(``:80-86``), so the copy moves only its own beats. What the write does to
CONTROL, and what a GO=0 write at BUSY=1 does to the copy, are not stated and
stay logged.

Continuation contract (CHK-DMA-CONT-CFG): "The engine takes `OPCODE` and
`DIGEST_SWAP` at the first start of a transfer and keeps them for its later
chunks." (``hw/sys/sep/doc/dma.adoc:81-82``); "The opcode and `DIGEST_SWAP` of
the first start hold for the whole transfer." (``sep-programming.adoc:770-771``).
CONTROL.OPCODE and CONTROL.DIGEST_SWAP are ``sw = rw`` (``secure_dma.rdl:207-210``,
``:224-230``), so a CONTROL read returns the value of the last write.

Range write contract (CHK-DMA-RANGE-WR): ENABLED_MEMORY_RANGE_BASE, LIMIT and
RANGE_VALID are ``sw = rw`` (``secure_dma.rdl:118-122``, ``:125-130``,
``:133-137``) under ``regwen: "RANGE_REGWEN"`` (``dma.hjson:289``, ``:304``,
``:318``); RANGE_REGWEN "Used by firmware to lock the DMA enabled memory range
configuration registers from further modification" with True = 6 and
"Unlocked at reset" (``secure_dma.rdl:142``, ``:148-151``). The leaf never
writes RANGE_REGWEN.

The Leg D cells that ``sep_dma_hash_test`` grades (SHA-256 at 56 bytes as one
chunk at either swap value, SHA-256 at 56 bytes as two 28-byte chunks with
DIGEST_SWAP=1, SHA-384 at 56 bytes as one chunk with DIGEST_SWAP=1) are
controls: they log ``INFO-DMA-HASH-CTRL`` and print no CHK-DMA-HASH or
CHK-DMA-HASH-CHAIN line.

Run mode: no_cpu, target ``lsu_stub_all_live``, ``+skip_fuse_sense``, never
asserts ``rst_ni``; Verilator and VCS. Graded-window owner code from
``tb/sep_fcov_owner_codes.svh``. The graded window opens at the GO write of
each graded transfer (at the range writes of a Leg C cell) and closes after
the checks of that transfer; setup, memory fills, the stale-digest read, the
scrub runs, the control runs and the narrow-width and large copies run with
it closed, so the graded narrow-width copies add no cell to the sampler. A
FAIL closes the window before it raises. The sampler holds every cell of this owner and samples the
held cells only when the pass label ``dma_matrix_pass``
(``env/sep_fcov_gate.set_dma_matrix_pass``) rises; the leaf writes 0 before
setup and 1 after every check of the run passed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, replace

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, FallingEdge, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_bit_watch import BitWatchTimeout, SepBitWatch
from env.sep_dma_model import (
    BUS_BYTES,
    DmaXfer,
    bytes_to_words,
    draw_sentinel_byte,
    draw_source_words,
    words_to_bytes,
)
from env.sep_dma_tap import FIELDS, DmaTapEvents, DmaTapMark, SepDmaTap
from env.sep_fcov_gate import (
    close_graded_window,
    open_graded_window,
    set_dma_matrix_pass,
)
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_dma_ops import (
    CFG_REGWEN,
    CHUNK_DATA_SIZE,
    CONTROL,
    DIGEST_BASE,
    DIGEST_WORDS,
    DST_ADDR_HI,
    ERROR_CODE,
    ERROR_CODE_MASK,
    INTR_CHUNK_DONE,
    INTR_ENABLE,
    OP_COPY,
    OP_SHA256,
    OP_SHA384,
    OP_SHA512,
    OP_ZERO,
    RANGE_BASE,
    RANGE_LIMIT,
    RANGE_REGWEN,
    RANGE_VALID,
    SECURE_DMA,
    SRC_ADDR_HI,
    ST_BUSY,
    ST_CHUNK_DONE,
    ST_DONE,
    ST_ERROR,
    STATUS,
    DmaStatus,
    DmaTimeout,
    SepDmaOps,
    SepMemWords,
    asid_word,
    control_word,
)
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank

TEST = "sep_dma_transfer_matrix_rand_test"

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
SRAM_LIMIT = SRAM_BASE + SRAM_SIZE - 1
# ADDR_SPACE_ID = 0x77: source and destination ASID 7.
ASID = 0x7
GO_MASK = control_word(go=1)
# Clocks a re-GO waits for the rise of dma_busy_probe_o.
BUSY_RISE_BOUND = 2_000
# STATUS reads a wait for SHA2_DIGEST_VALID may take after DONE.
VALID_POLL_BOUND = 200
# CONTROL reads per Leg B transfer that look for GO=1 at BUSY=1.
CTRL_READ_TRIES = 8
# A total of this size or more lets a frontdoor read land while the engine runs.
LONG_TOTAL = 1024
# CFG_REGWEN.REGWEN is MultiBitBool4 (secure_dma.rdl:158-159): True, its reset,
# at idle and False, the complement of True, while the DMA is busy
# (dma.hjson:352-353).
CFG_REGWEN_MASK = SECURE_DMA.field_mask("CFG_REGWEN", "regwen")
CFG_REGWEN_IDLE = SECURE_DMA.reset("CFG_REGWEN") & CFG_REGWEN_MASK
CFG_REGWEN_BUSY = CFG_REGWEN_IDLE ^ CFG_REGWEN_MASK
# CONTROL fields a later start writes (secure_dma.rdl:207-210, :224-230).
CTRL_OPCODE_MASK = SECURE_DMA.field_mask("CONTROL", "opcode")
CTRL_SWAP_MASK = SECURE_DMA.field_mask("CONTROL", "digest_swap")
CTRL_CFG_MASK = CTRL_OPCODE_MASK | CTRL_SWAP_MASK
# Clocks the pass label stays 1, and clocks after it for the replay of the
# clocked FCOV cells (one bin per clock, at most eight).
LABEL_CLKS = 2
LABEL_REPLAY_CLKS = 16
# Clocks after DONE before the DMA master tap is read for the busy-write copy.
BUSY_SETTLE_CLKS = 16
# Range registers (secure_dma.rdl:118-122 BASE, :125-130 LIMIT, :133-137
# RANGE_VALID, all ``sw = rw``; :141-153 RANGE_REGWEN, True at :142,
# "Unlocked at reset" at :151; dma.hjson:289, :304, :318 put the three under
# RANGE_REGWEN).
RANGE_BASE_MASK = SECURE_DMA.field_mask("ENABLED_MEMORY_RANGE_BASE", "base")
RANGE_LIMIT_MASK = SECURE_DMA.field_mask("ENABLED_MEMORY_RANGE_LIMIT", "limit")
RANGE_VALID_MASK = SECURE_DMA.field_mask("RANGE_VALID", "range_valid")
RANGE_REGWEN_MASK = SECURE_DMA.field_mask("RANGE_REGWEN", "regwen")
RANGE_REGWEN_UNLOCKED = SECURE_DMA.reset("RANGE_REGWEN") & RANGE_REGWEN_MASK
M32 = 0xFFFF_FFFF

# Draws added after the first stream come from a second stream on the same
# seed, so every value of the first stream keeps its seed mapping.
SALT = 0x5A17_C0DE
# The narrow-width and large copies draw from a third stream, so every value of
# the first two streams keeps its seed mapping.
SIZE_SALT = 0x51CE_D4A7
# Copy sizes of the narrow-width and large copies. Graded totals stay at or
# below NARROW_TOTAL_MAX; no text states a maximum TOTAL_DATA_SIZE, so the
# large copy (above NARROW_TOTAL_MAX, up to LARGE_TOTAL_MAX) is logged only.
NARROW_TOTAL_MIN = 1028
NARROW_TOTAL_MAX = 16384
LARGE_TOTAL_MAX = 65536
CHUNK_MAX = 4096
# DMA register block, admitted to m_axi by one inbound filter entry.
DMA_CSR_BASE = sym("SECURE_DMA_REG_MAP_BASE_ADDR")
DMA_CSR_LAST = DMA_CSR_BASE + sym("SECURE_DMA_REG_MAP_SIZE") - 1
IN_ENTRY = 0
# Local alias: the window at SEP_LOCAL_BASE_ADDR reaches 0x1000_0000, the SEP
# SRAM base (hw/sys/sep/doc/fabric.adoc:155-156; "0xD000_0000 aliases
# 0x1000_0000", hw/sys/sep/doc/memory_map.adoc:37).
LOCAL_ALIAS = SEP_CPU_CTRL.reset("SEP_LOCAL_BASE_ADDR")
LOCAL_BASE_REG = SEP_CPU_CTRL.addr("SEP_LOCAL_BASE_ADDR")
# SHA2_DIGEST_0[16] reset value (secure_dma.rdl SHA2_DIGEST_0, sw = r).
DIGEST_RESET = sym("SECURE_DMA_SHA2_DIGEST_0_REG_DEFAULT")
DST_ADDR_ERROR = SECURE_DMA.field_mask("ERROR_CODE", "dst_addr_error")
# 8-byte-aligned RW register pairs for the 64-bit m_axi access.
CSR64_PAIRS = (("SRC_ADDR_LO", "SRC_ADDR_HI"), ("DST_ADDR_LO", "DST_ADDR_HI"))
for _lo, _hi in CSR64_PAIRS:
    if SECURE_DMA.addr(_lo) % 8 or SECURE_DMA.addr(_hi) != SECURE_DMA.addr(_lo) + 4:
        raise ValueError(f"{_lo}/{_hi} is not an 8-byte-aligned register pair")
# Clocks the leaf waits for m_axi WVALID while it drives a sparse strobe.
STRB_FOLLOW_BOUND = 2_000
# STATUS reads after ABORT that a logged run may take to reach BUSY=0.
ABORT_POLL_BOUND = 200
# Outbound source window inside the SMU aperture at its reset value, away from
# the console and verdict words of tb/sep_outbound_mbx.sv; the pair of outbound
# entries admits it at either AxPROT[1].
SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
OUT_WIN_LO = SMU_BASE + 0x0001_0000
OUT_WIN_HI = OUT_WIN_LO + 0xFFFF
OUT_PAIR = (2, 3)
DMA_BUS_ERR_STATUS = SEP_CPU_CTRL.addr("DMA_BUS_ERR_STATUS")
# Clocks smn_outbound_resp_hold_i holds the responses of the outbound responder.
HOLD_CLKS = 20_000


def alias_of(addr: int) -> int:
    """Local-alias form of a SEP-local address."""
    return LOCAL_ALIAS + (addr - SRAM_BASE)


# The order in which step 4 writes the transfer registers is drawn from these.
XFER_ORDER_REGS = (
    "SRC_ADDR_LO",
    "DST_ADDR_LO",
    "TOTAL_DATA_SIZE",
    "CHUNK_DATA_SIZE",
    "TRANSFER_WIDTH",
    "SRC_CONFIG",
    "DST_CONFIG",
)

# The 16 Leg A cells: (src INCREMENT, src WRAP, dst INCREMENT, dst WRAP).
CELLS = tuple((si, sw, di, dw) for si in (0, 1) for sw in (0, 1) for di in (0, 1) for dw in (0, 1))
# (cell, width encoding) pairs that sep_dma_basic_test grades at one chunk (or
# two for the source-wrap pair) -> the smallest chunk count this leaf uses.
BASIC_PAIRS_MIN_N = {
    ((1, 0, 1, 0), 0): 2,
    ((1, 0, 1, 0), 1): 2,
    ((1, 0, 1, 0), 2): 2,
    ((0, 1, 1, 0), 2): 2,
    ((1, 0, 0, 1), 2): 2,
    ((1, 1, 1, 0), 2): 3,
}

# Published SHA-2 vectors (FIPS 180-4 examples): 56 bytes for SHA-256 and
# 112 bytes for SHA-384 and SHA-512.
VEC56 = b"abcdbcdecdefdefgefghfghighijhijkijkljklmklmnlmnomnopnopq"
VEC112 = (
    b"abcdefghbcdefghicdefghijdefghijkefghijklfghijklmghijklmn"
    b"hijklmnoijklmnopjklmnopqklmnopqrlmnopqrsmnopqrstnopqrstu"
)
BOUNDARY_LENGTHS = (52, 56, 60, 64, 108, 112, 116, 124, 128, 132)
ALGS = {
    256: (OP_SHA256, hashlib.sha256, 8),
    384: (OP_SHA384, hashlib.sha384, 12),
    512: (OP_SHA512, hashlib.sha512, 16),
}
OP_ALG = {op: alg for alg, (op, _, _) in ALGS.items()}


def golden_words(alg: int, msg: bytes, swap: int) -> list[int]:
    """Expected SHA2_DIGEST_0 words of ``msg`` for one DIGEST_SWAP value (hashlib)."""
    digest = ALGS[alg][1](msg).digest()
    order = "little" if swap else "big"
    return [int.from_bytes(digest[4 * i : 4 * i + 4], order) for i in range(len(digest) // 4)]


def split_ks(length: int) -> list[int]:
    """Chunk counts k in {2, 3, 4} that split ``length`` bytes into equal 4-byte multiples."""
    return [k for k in (2, 3, 4) if length % k == 0 and (length // k) % 4 == 0]


# Boundary lengths with an equal split; the Leg D continuation draws from them.
CONT_LENGTHS = tuple(n for n in BOUNDARY_LENGTHS if split_ks(n))


def place(rng: SepSeededRng, sizes: list[int]) -> list[int]:
    """Disjoint 4-aligned SRAM addresses for blocks of ``sizes`` bytes, in a drawn order."""
    free = SRAM_SIZE - sum(sizes)
    if free < 0:
        raise ValueError(f"blocks of {sum(sizes)} bytes do not fit the SRAM")
    cuts = sorted(rng.randrange(free // 4 + 1) for _ in sizes)
    order = list(range(len(sizes)))
    rng.shuffle(order)
    out = [0] * len(sizes)
    pos = prev = 0
    for cut, i in zip(cuts, order):
        pos += (cut - prev) * 4
        prev = cut
        out[i] = SRAM_BASE + pos
        pos += sizes[i]
    return out


def ff(prefix: str, fc) -> str:
    """``<prefix>_value= <prefix>_expect= <prefix>_mask= <prefix>_rsvd=`` of a field compare."""
    m = fc.mask
    return (
        f"{prefix}_value=0x{fc.got & m:x} {prefix}_expect=0x{fc.expect & m:x} "
        f"{prefix}_mask=0x{m:x} {prefix}_rsvd=0x{fc.rsvd:x}"
    )


def poll_size(n_bytes: int) -> int:
    """Size handed to the poll bound of ``SepDmaOps``: twice the bytes moved.

    A frontdoor STATUS read takes about 14 core clocks and a 4-byte DMA
    transaction about 26, so ``SepDmaOps.done_bound`` of the plain size can
    expire on a long transfer that still runs. The bound stays linear in the
    size of the transfer.
    """
    return 2 * n_bytes


def sentinel_word(s: int) -> int:
    return s * 0x0101_0101


def cell_name(cell: tuple[int, int, int, int]) -> str:
    si, sw, di, dw = cell
    return f"{si}{sw}{di}{dw}"


def rle(items: list[str]) -> str:
    """Run-length form of a sequence of short tokens: ``tok*count,...``."""
    out: list[str] = []
    for tok in items:
        if out and out[-1].rsplit("*", 1)[0] == tok:
            head, cnt = out[-1].rsplit("*", 1)
            out[-1] = f"{head}*{int(cnt) + 1}"
        else:
            out.append(f"{tok}*1")
    return ",".join(out)


# ---------------------------------------------------------------- draws ----


@dataclass
class CopyXfer:
    """One memory-to-memory copy with its images (all drawn from the seed)."""

    x: DmaXfer
    sentinel: int
    src_words: list[int]
    src_addr: int  # first source word
    dst_region: int  # first destination word (guard words included)
    dst_region_words: int
    guard_words: list[int] = field(default_factory=list)  # addresses of guard words
    order: tuple[str, ...] = XFER_ORDER_REGS

    def expected_dst(self) -> list[int]:
        s = self.sentinel
        init = {self.dst_region + b: s for b in range(4 * self.dst_region_words)}
        img = self.x.dst_image(words_to_bytes(self.src_addr, self.src_words), init)
        return bytes_to_words(img, self.dst_region, self.dst_region_words)


@dataclass
class CellDraw:
    cell: tuple[int, int, int, int]
    enc: int
    n: int
    chunk: int
    copy: CopyXfer


@dataclass
class EdgeDraw:
    edge: str  # low, high, both, guard_low, guard_high, guard_both
    order: str  # high_first or low_first: the region the first fill writes
    size: int
    g_low: int
    g_high: int
    block: int
    sentinel: int

    @property
    def lo_region(self) -> int:
        return self.block + self.g_low

    @property
    def hi_region(self) -> int:
        # One in-range prefill word sits between the two regions.
        return self.lo_region + self.size + 4

    def fills(self) -> tuple[tuple[str, int], tuple[str, int]]:
        """The two zero-fill regions, (name, first byte), in the drawn order."""
        lo, hi = ("lo", self.lo_region), ("hi", self.hi_region)
        return (hi, lo) if self.order == "high_first" else (lo, hi)

    @property
    def prefill(self) -> int:
        """A word with no zero byte, so a byte the fill skips never reads 0."""
        return sentinel_word(self.sentinel) or M32

    @property
    def gap_word(self) -> int:
        return self.lo_region + self.size

    @property
    def range_lo(self) -> int:
        return self.lo_region

    @property
    def range_hi(self) -> int:
        return self.hi_region + self.size - 1

    def base_limit(self) -> tuple[int, int]:
        if self.edge == "low":
            return self.range_lo, SRAM_LIMIT
        if self.edge == "high":
            return SRAM_BASE, self.range_hi
        return self.range_lo, self.range_hi

    def guards(self) -> list[int]:
        """Addresses of the prefill words the fills must leave unchanged."""
        out = [self.gap_word]
        out += [self.block + 4 * i for i in range(self.g_low // 4)]
        out += [self.range_hi + 1 + 4 * i for i in range(self.g_high // 4)]
        return out


@dataclass
class HashMsg:
    alg: int
    kind: str  # pub, drawn, long
    msg: bytes
    sentinel: int
    swaps: list[int]
    split: int  # 0 when the message has no split form
    src: int = 0
    dst: int = 0


@dataclass
class ContMsg:
    """One Leg D continuation run: the first start and the CONTROL of each later start."""

    alg: int
    msg: bytes
    sentinel: int
    swap: int  # DIGEST_SWAP of the first start
    split: int  # chunk count, 2 to 4
    cont_ops: list[int]  # OPCODE of each later start, never the first-start opcode
    src: int = 0
    dst: int = 0


class Plan:
    """Every value of the leaf, drawn from the seed before the first DUT access."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lines: list[str] = []
        self._leg_a(rng)
        self._leg_b(rng)
        self._leg_c(rng)
        self._leg_d(rng)
        self._leg_d_cont(rng)
        self._logged(rng)
        self._salted(SepSeededRng(seed ^ SALT))
        self._sized(SepSeededRng(seed ^ SIZE_SALT))

    def _logged(self, rng: SepSeededRng) -> None:
        """Logged runs, drawn after every graded leg so the graded draws keep their values."""
        chunk = 4 * rng.randrange(1, 17)
        # Fixed source (INCREMENT=0, WRAP=0), incrementing destination, two chunks.
        src, dst = place(rng, [2 * chunk, 2 * chunk])
        s = rng.randrange(256)
        self.fixed = (src, dst, chunk, s, draw_source_words(rng, 2 * chunk // 4, s))
        # One CONTROL write at BUSY=1 during a long single-chunk copy.
        self.busy_go = rng.randrange(2)
        self.busy_copy = self._copy(rng, dict(total=4096, chunk=4096, width_enc=2), order=False)
        self.lines.append(
            f"DRAW logged fixed_src=0x{src:08x} fixed_dst=0x{dst:08x} fixed_chunk={chunk} "
            f"busy_ctrl_go={self.busy_go} busy_src=0x{self.busy_copy.x.src_base:08x} "
            f"busy_dst=0x{self.busy_copy.x.dst_base:08x}"
        )

    def _salted(self, rng: SepSeededRng) -> None:
        """Draws of the master rotation, alias, chunk, range and logged runs."""
        self.rot_start = rng.randrange(2)
        self.alias_cells: list[tuple[CellDraw, str]] = []
        modes = {"inc": (1, 0), "wrap": (1, 1), "fixed": (0, 0)}
        for enc in (0, 1, 2):
            side = rng.choice(("src", "dst", "both"))
            si, sw = modes[rng.choice(tuple(modes))]
            di, dw = modes[rng.choice(tuple(modes))]
            # A fixed side runs one chunk: the fixed multi-chunk source address is open.
            n = 1 if not si or not di else rng.randrange(2, 9)
            chunk = 4 * rng.randrange(1, 17)
            cell = (si, sw, di, dw)
            copy = self._copy(
                rng,
                dict(
                    total=n * chunk,
                    chunk=chunk,
                    width_enc=enc,
                    src_inc=bool(si),
                    src_wrap=bool(sw),
                    dst_inc=bool(di),
                    dst_wrap=bool(dw),
                ),
            )
            self.alias_cells.append((CellDraw(cell, enc, n, chunk, copy), side))
            self.lines.append(
                f"DRAW alias cell={cell_name(cell)} enc={enc} n={n} chunk={chunk} side={side} "
                f"src=0x{copy.x.src_base:08x} dst=0x{copy.x.dst_base:08x}"
            )
        alg = rng.choice((256, 384, 512))
        length = rng.choice(CONT_LENGTHS)
        m = self._drawn_msg(rng, alg, "alias", length)
        m.src, m.dst = place(rng, [length, length])
        self.alias_dst = rng.randrange(2)
        self.alias_msg = m
        self.fixed_form = rng.choice(("direct", "alias"))
        self.lines.append(
            f"DRAW alias_sha alg={alg} len={length} split={m.split} swap={m.swaps[0]} "
            f"dst_alias={self.alias_dst} src=0x{m.src:08x} dst=0x{m.dst:08x} "
            f"fixed_chunk_form={self.fixed_form}"
        )
        n1 = rng.randrange(2, 17)
        sw1, dw1 = rng.randrange(2), rng.randrange(2)
        c1 = self._copy(
            rng,
            dict(total=n1, chunk=1, width_enc=0, src_wrap=bool(sw1), dst_wrap=bool(dw1)),
        )
        self.chunk1 = CellDraw((1, sw1, 1, dw1), 0, n1, 1, c1)
        self.lines.append(
            f"DRAW chunk1 cell={cell_name(self.chunk1.cell)} bytes={n1} "
            f"src=0x{c1.x.src_base:08x} dst=0x{c1.x.dst_base:08x}"
        )
        src, dst = place(rng, [8, 8])
        s = rng.randrange(256)
        self.chunk1_w4 = (src, dst, s, draw_source_words(rng, 2, s))
        self.baselim = self._copy(rng, dict(total=16, chunk=16, width_enc=2), order=False)
        self.baselim_word = self.baselim.src_addr + 4 * rng.randrange(4)
        k = rng.randrange(2, 17)
        total = rng.randrange(1, 4) * 4 * k + 4 * rng.randrange(1, k)
        self.short = self._copy(rng, dict(total=total, chunk=4 * k, width_enc=2), order=False)
        nogo_total = 4 * rng.randrange(16, 1025)
        self.nogo = self._copy(
            rng, dict(total=nogo_total, chunk=nogo_total, width_enc=2), order=False
        )
        size = 4 * rng.randrange(8, 65)
        s = rng.randrange(256)
        words = draw_source_words(rng, size // 4, s)
        (blk,) = place(rng, [2 * size + 8])
        x = DmaXfer(blk, blk + size + 4, total=size, chunk=size, width_enc=2)
        self.range_copy = CopyXfer(
            x, s, words, blk, blk + size, size // 4 + 2, [blk + size, blk + 2 * size + 4]
        )
        # BASE at the source, LIMIT inside the destination: the copy leaves the range.
        self.range_limit = x.dst_base + 4 * rng.randrange(1, size // 4) - 1
        self.csr64 = (
            rng.choice(CSR64_PAIRS),
            rng.getrandbits(64),
            rng.getrandbits(64),
            rng.choice((0x0F, 0xF0)),
        )
        hold_src = OUT_WIN_LO + 8 * rng.randrange(0x100)
        (hold_dst,) = place(rng, [8])
        self.hold = (hold_src, hold_dst, rng.randrange(256))
        self.lines.append(
            f"DRAW salted rot_start={'ext' if self.rot_start else 'lsu'} "
            f"chunk1_w4_src=0x{src:08x} baselim_word=0x{self.baselim_word:08x} "
            f"short_total={total} short_chunk={4 * k} nogo_total={nogo_total} "
            f"range_copy_src=0x{blk:08x} range_copy_bytes={size} "
            f"range_limit=0x{self.range_limit:08x} csr64_pair={self.csr64[0][0]} "
            f"csr64_strb=0x{self.csr64[3]:02x} hold_src=0x{hold_src:08x} hold_dst=0x{hold_dst:08x}"
        )

    def _sized(self, rng: SepSeededRng) -> None:
        """Width 0 and width 1 copies above 1 KB, and one width-2 copy above 16 KB.

        Every copy is INCREMENT on both sides in n equal chunks of at most
        CHUNK_MAX bytes, so TOTAL_DATA_SIZE is a multiple of CHUNK_DATA_SIZE.
        """
        self.narrow: list[CopyXfer] = []
        for enc in (0, 1):
            n = rng.randrange(1, 17)
            cmin = -(-NARROW_TOTAL_MIN // (4 * n))
            cmax = min(CHUNK_MAX, NARROW_TOTAL_MAX // n) // 4
            chunk = 4 * rng.randrange(cmin, cmax + 1)
            self.narrow.append(
                self._copy(rng, dict(total=n * chunk, chunk=chunk, width_enc=enc), order=False)
            )
        n = rng.randrange(NARROW_TOTAL_MAX // CHUNK_MAX + 1, LARGE_TOTAL_MAX // CHUNK_MAX + 1)
        cmin = -(-(NARROW_TOTAL_MAX + 4) // (4 * n))
        chunk = 4 * rng.randrange(cmin, CHUNK_MAX // 4 + 1)
        self.large = self._copy(rng, dict(total=n * chunk, chunk=chunk, width_enc=2), order=False)
        for name, c in [("N", c) for c in self.narrow] + [("large", self.large)]:
            self.lines.append(
                f"DRAW leg={name} width_enc={c.x.width_enc} total={c.x.total} "
                f"chunk={c.x.chunk} n={c.x.n_chunks} src=0x{c.x.src_base:08x} "
                f"dst=0x{c.x.dst_base:08x} sentinel=0x{c.sentinel:02x}"
            )

    # Leg A ---------------------------------------------------------------
    def _copy(
        self, rng: SepSeededRng, x_args: dict, *, order: bool = True, sentinel: int | None = None
    ) -> CopyXfer:
        """Place, fill and model one copy; ``x_args`` are DmaXfer arguments without bases."""
        probe = DmaXfer(0, 0, **x_args)
        src_fp = probe.src_footprint()
        dst_fp = probe.dst_footprint()
        src_words_n = -(-len(src_fp) // 4)
        dst_words_n = -(-len(dst_fp) // 4) + 2
        src_addr, dst_region = place(rng, [4 * src_words_n, 4 * dst_words_n])
        s = rng.randrange(256) if sentinel is None else sentinel
        words = draw_source_words(rng, src_words_n, s)
        x = DmaXfer(src_addr, dst_region + 4, **x_args)
        regs = list(XFER_ORDER_REGS)
        if order:
            rng.shuffle(regs)
        return CopyXfer(
            x,
            s,
            words,
            src_addr,
            dst_region,
            dst_words_n,
            [dst_region, dst_region + 4 * (dst_words_n - 1)],
            tuple(regs),
        )

    def _leg_a(self, rng: SepSeededRng) -> None:
        cells = list(CELLS)
        rng.shuffle(cells)
        encs = [0, 1, 2] + [rng.randrange(3) for _ in range(len(cells) - 3)]
        rng.shuffle(encs)
        self.cells: list[CellDraw] = []
        for cell, enc in zip(cells, encs):
            si, sw, di, dw = cell
            fixed_side = (not si and not sw) or (not di and not dw)
            min_n = BASIC_PAIRS_MIN_N.get((cell, enc), 1)
            if fixed_side:
                n = 1
            elif min_n > 1:
                n = rng.randrange(min_n, 17)
            else:
                n = 1 if rng.randrange(3) == 0 else rng.randrange(2, 17)
            chunk = 4 * rng.randrange(1, min(16, 1024 // (4 * n)) + 1)
            copy = self._copy(
                rng,
                dict(
                    total=n * chunk,
                    chunk=chunk,
                    width_enc=enc,
                    src_inc=bool(si),
                    src_wrap=bool(sw),
                    dst_inc=bool(di),
                    dst_wrap=bool(dw),
                ),
            )
            self.cells.append(CellDraw(cell, enc, n, chunk, copy))
            self.lines.append(
                f"DRAW leg=A cell={cell_name(cell)} enc={enc} n={n} chunk={chunk} "
                f"bytes={n * chunk} src=0x{copy.x.src_base:08x} dst=0x{copy.x.dst_base:08x} "
                f"sentinel=0x{copy.sentinel:02x} order={','.join(copy.order)}"
            )

    # Leg B ---------------------------------------------------------------
    def _leg_b(self, rng: SepSeededRng) -> None:
        mid = rng.choice((64, 256, 1024, 4096))
        shapes = [(4, 4), (mid, mid), (16384, 4096)]
        for _ in range(2):
            n = rng.randrange(2, 17)
            cmax = min(4096, 16384 // n) // 4
            chunk = 4 * rng.randrange(1, cmax + 1)
            shapes.append((n * chunk, chunk))
        self.mid_total = mid
        self.b_xfers: list[CopyXfer] = []
        for total, chunk in shapes:
            c = self._copy(rng, dict(total=total, chunk=chunk, width_enc=2), order=False)
            self.b_xfers.append(c)
            self.lines.append(
                f"DRAW leg=B total={total} chunk={chunk} n={total // chunk} "
                f"src=0x{c.x.src_base:08x} dst=0x{c.x.dst_base:08x} sentinel=0x{c.sentinel:02x}"
            )

    # Leg C ---------------------------------------------------------------
    def _leg_c(self, rng: SepSeededRng) -> None:
        self.edges: list[EdgeDraw] = []
        for edge in ("low", "high", "both", "guard_low", "guard_high", "guard_both"):
            order = rng.choice(("high_first", "low_first"))
            size = 4 * rng.randrange(4, 65)
            g_low = 4 * rng.randrange(1, 9) if edge in ("guard_low", "guard_both") else 0
            g_high = 4 * rng.randrange(1, 9) if edge in ("guard_high", "guard_both") else 0
            (block,) = place(rng, [g_low + 2 * size + 4 + g_high])
            s = rng.randrange(256)
            # Unused words: the draw keeps every later value of the seed stream.
            draw_source_words(rng, size // 4, s)
            e = EdgeDraw(edge, order, size, g_low, g_high, block, s)
            self.edges.append(e)
            base, limit = e.base_limit()
            self.lines.append(
                f"DRAW leg=C edge={edge} order={order} bytes={size} g_low={g_low} "
                f"g_high={g_high} lo=0x{e.lo_region:08x} hi=0x{e.hi_region:08x} "
                f"base=0x{base:08x} limit=0x{limit:08x} prefill=0x{e.prefill:08x}"
            )

    # Leg D ---------------------------------------------------------------
    def _drawn_msg(self, rng: SepSeededRng, alg: int, kind: str, length: int) -> HashMsg:
        s = rng.randrange(256)
        msg = b"".join(w.to_bytes(4, "little") for w in draw_source_words(rng, length // 4, s))
        ks = split_ks(length) if kind != "long" else []
        split = rng.choice(ks) if ks else 0
        return HashMsg(alg, kind, msg, s, [rng.randrange(2)], split)

    def _leg_d(self, rng: SepSeededRng) -> None:
        algs = [256, 384, 512]
        rng.shuffle(algs)
        self.msgs: list[HashMsg] = []
        for alg in algs:
            vec = VEC56 if alg == 256 else VEC112
            swaps = [0, 1]
            rng.shuffle(swaps)
            ks = split_ks(len(vec))
            pub = HashMsg(
                alg, "pub", vec, draw_sentinel_byte(rng, vec), swaps, rng.choice(ks) if ks else 0
            )
            self.msgs.append(pub)
            for _ in range(2):
                if rng.randrange(4) < 3:
                    length = rng.choice(BOUNDARY_LENGTHS)
                else:
                    length = 4 * rng.randrange(1, 65)
                self.msgs.append(self._drawn_msg(rng, alg, "drawn", length))
        long_alg = rng.choice((256, 384, 512))
        self.msgs.append(self._drawn_msg(rng, long_alg, "long", 4 * rng.randrange(256, 1025)))
        for m in self.msgs:
            m.src, m.dst = place(rng, [len(m.msg), len(m.msg)])
            self.lines.append(
                f"DRAW leg=D alg={m.alg} kind={m.kind} len={len(m.msg)} split={m.split} "
                f"swaps={','.join(map(str, m.swaps))} src=0x{m.src:08x} dst=0x{m.dst:08x} "
                f"sentinel=0x{m.sentinel:02x}"
            )

    def _leg_d_cont(self, rng: SepSeededRng) -> None:
        """One continuation run per algorithm; every draw comes after the Leg D draws."""
        algs = [256, 384, 512]
        rng.shuffle(algs)
        self.conts: list[ContMsg] = []
        for alg in algs:
            length = rng.choice(CONT_LENGTHS)
            s = rng.randrange(256)
            msg = b"".join(w.to_bytes(4, "little") for w in draw_source_words(rng, length // 4, s))
            split = rng.choice(split_ks(length))
            swap = rng.randrange(2)
            others = [op for a, (op, _, _) in ALGS.items() if a != alg]
            cont_ops = [rng.choice(others) for _ in range(split - 1)]
            src, dst = place(rng, [length, length])
            c = ContMsg(alg, msg, s, swap, split, cont_ops, src, dst)
            self.conts.append(c)
            self.lines.append(
                f"DRAW leg=D_cont alg={alg} len={length} split={split} swap={swap} "
                f"cont_ops={','.join(map(str, cont_ops))} cont_swap={1 - swap} "
                f"src=0x{src:08x} dst=0x{dst:08x} sentinel=0x{s:02x}"
            )


def is_hash_control(alg: int, length: int, split: int, swap: int) -> bool:
    """A Leg D cell that sep_dma_hash_test grades (a control here)."""
    if alg == 256 and length == 56:
        return split == 0 or (split == 2 and swap == 1)
    return alg == 384 and length == 56 and split == 0 and swap == 1


# ---------------------------------------------------------------- ops ------


class _LoggedDmaOps(SepDmaOps):
    """SepDmaOps that records every register write with the tap clock."""

    def __init__(self, test, tap: SepDmaTap) -> None:
        super().__init__(test)
        self.tap = tap
        self.writes: list[tuple[int, int, int, int]] = []  # (clk0, clk1, addr, data)

    async def wr(self, addr: int, data: int) -> None:
        c0 = self.tap.clk
        await super().wr(addr, data)
        self.writes.append((c0, self.tap.clk, addr, data))

    def status_writes(self, clk0: int, clk1: int) -> int:
        return sum(1 for a, b, addr, _ in self.writes if addr == STATUS and b > clk0 and a < clk1)


class _RotDmaOps(_LoggedDmaOps):
    """_LoggedDmaOps whose register accesses run on the master named by ``master``.

    ``lsu`` is the CPU-LSU splice (``s_axi``) and ``ext`` the SMN-inbound
    master (``m_axi``). The access is the 32-bit ``SepAxiAccessSeq`` of
    ``SepDmaOps.access``; ``wr``, ``rd`` and the write log are inherited.
    """

    MASTERS = ("lsu", "ext")

    def __init__(self, test, tap: SepDmaTap) -> None:
        super().__init__(test, tap)
        self.master = "lsu"

    async def access(
        self, op: SepAxiOp, addr: int, data: int = 0, *, ungraded: bool = False
    ) -> SepAxiAccessSeq:
        if self.master == "lsu":
            return await super().access(op, addr, data, ungraded=ungraded)
        seq = SepAxiAccessSeq(
            f"dma_ext_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=data & M32,
            size=2,
            allow_unverified_write_resp=ungraded and op is SepAxiOp.WRITE,
            allow_ungraded_read_resp=ungraded and op is SepAxiOp.READ,
        )
        await self.test.start_ext_seq(seq)
        return seq


@dataclass
class XferRecord:
    """What one Leg A or Leg B transfer showed in its window."""

    ev: DmaTapEvents
    clk0: int
    clk1: int
    go_writes: int
    statuses: list[DmaStatus]
    irq_rises: int


@dataclass(frozen=True)
class DigestValidEdges:
    """SHA2_DIGEST_VALID on ``dma_status_probe_o`` from the initial GO to the digest read.

    Clocks are relative to the tap mark taken just before the GO write.
    ``fall`` is the first fall, ``rise`` the last rise. With the bit 1 before
    the GO, the clear at the initial transfer and the set when the digest is
    written hold when the first fall precedes the last rise. With the bit 0
    before the GO, no clear can show, so only the rise is graded. Edges
    between them are not graded.
    """

    pre_go: int | None
    go_clk: int
    falls: list[int]
    rises: list[int]

    @property
    def fall(self) -> int | None:
        return self.falls[0] if self.falls else None

    @property
    def rise(self) -> int | None:
        return self.rises[-1] if self.rises else None

    @property
    def fall_graded(self) -> bool:
        return self.pre_go == 1

    @property
    def ok(self) -> bool:
        if self.rise is None:
            return False
        return not self.fall_graded or (self.fall is not None and self.rise > self.fall)

    def fmt(self) -> str:
        def rel(c: int | None) -> str:
            return "-" if c is None else f"+{c - self.go_clk}"

        fall = rel(self.fall) if self.fall_graded else "n/a"
        return (
            f"dv_pre_go={self.pre_go} go_clk={self.go_clk} dv_fall_clk={fall} "
            f"dv_rise_clk={rel(self.rise)} dv_falls={len(self.falls)} dv_rises={len(self.rises)}"
        )


_REQ_F = {n: (lsb, w) for n, lsb, w in FIELDS}


class _WdataSampler:
    """W beats of the DMA master with their data, from the two DMA master taps.

    On every rising edge of ``clk_i``, in the read-only phase, a W handshake
    (``w_valid`` and ``w_ready`` of ``dma_axi_req_probe_o`` high) records the
    byte of each lane of ``dma_axi_wdata_probe_o``, lane j being bits
    8j+7:8j; a lane with an X or Z bit records None.
    """

    def __init__(self, dut) -> None:
        self._clk = dut.clk_i
        self._req = dut.dma_axi_req_probe_o
        self._wd = dut.dma_axi_wdata_probe_o
        self.beats: list[tuple[int | None, ...]] = []
        self._task = None

    def start(self) -> "_WdataSampler":
        width = len(self._wd)
        if width != 8 * BUS_BYTES:
            raise AssertionError(f"dma_axi_wdata_probe_o is {width} bits; expected {8 * BUS_BYTES}")
        self._task = cocotb.start_soon(self._run())
        return self

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def mark(self) -> int:
        return len(self.beats)

    def since(self, mark: int) -> list[tuple[int | None, ...]]:
        if self._task is None or self._task.done():
            raise AssertionError("DMA-WDATA-TAP FAIL: the W data sampler is not running")
        return self.beats[mark:]

    @staticmethod
    def _bits(sig) -> str:
        v = sig.value
        s = getattr(v, "binstr", None)
        return (s if s is not None else str(v)).strip()

    async def _run(self) -> None:
        v_lsb, r_lsb = _REQ_F["w_valid"][0], _REQ_F["w_ready"][0]
        while True:
            await RisingEdge(self._clk)
            await ReadOnly()
            req = self._bits(self._req)
            n = len(req)
            if req[n - 1 - v_lsb] != "1" or req[n - 1 - r_lsb] != "1":
                continue
            wd = self._bits(self._wd)
            m = len(wd)
            lanes = []
            for j in range(BUS_BYTES):
                b = wd[m - 8 * (j + 1) : m - 8 * j]
                lanes.append(int(b, 2) if all(c in "01" for c in b) else None)
            self.beats.append(tuple(lanes))


@pyuvm.test()
class sep_dma_transfer_matrix_rand_test(sep_base_test):
    """Secure DMA copy and hash matrix over address modes, widths, sizes, range edges and SHA-2."""

    required_evidence = (
        "CHK-DMA-IMAGE",
        "CHK-DMA-BEAT",
        "CHK-DMA-ADDR",
        "CHK-DMA-WDATA-LANE",
        "CHK-DMA-GEOM",
        "CHK-DMA-CFG-REGWEN",
        "CHK-DMA-DONE-CLR",
        "CHK-DMA-CHUNKDONE",
        "CHK-DMA-CHUNKRISE",
        "CHK-DMA-DONE-ORDER",
        "CHK-DMA-GO-CHUNKS",
        "CHK-DMA-RANGE-WR",
        "CHK-DMA-RANGE-OK",
        "CHK-DMA-HASH",
        "CHK-DMA-HASH-VALID",
        "CHK-DMA-HASH-CHAIN",
        "CHK-DMA-CONT-CFG",
        "CHK-DMA-DIGEST-RESET",
        "CHK-DMA-MASTER-ROT",
        "CHK-DMA-RW1C",
        "CHK-DMA-RO-HOLD",
        "CHK-DMA-ALIAS-FORM",
        "CHK-DMA-CHUNK1",
        "CHK-DMA-NOGO",
        "CHK-DMA-RANGE-COPY",
    )

    # ---- log helpers ------------------------------------------------------
    def _pass(self, chk: str, ok: bool, values: str) -> None:
        """Grade one check; a FAIL closes the graded window, then raises."""
        line = f"{chk} {'PASS' if ok else 'FAIL'} seed={self.seed} {values}"
        if not ok:
            self._close()
            self.logger.error(line)
            raise AssertionError(line)
        self.logger.info(line)
        self.k += 1

    def _ctrl_missing(self, chk: str, why: str) -> None:
        self._close()
        line = f"CTRL-MISSING {chk} seed={self.seed} {why}"
        self.logger.error(line)
        raise AssertionError(line)

    def _ctrl_chunk_rb(self, chk: str, tag: str, chunk_rb: int, expect: int) -> None:
        """CTRL-DMA-CHUNK-RB: CHUNK_DATA_SIZE reads back the chunk written, else CTRL-MISSING."""
        self.logger.info(
            "CTRL-DMA-CHUNK-RB LOG seed=%d %s chunk_rb=%d expect_chunk=%d",
            self.seed,
            tag,
            chunk_rb,
            expect,
        )
        if chunk_rb != expect:
            self._ctrl_missing(chk, f"{tag} CHUNK_DATA_SIZE read {chunk_rb}, wrote {expect}")

    def _open(self) -> None:
        open_graded_window(TEST, self.logger)

    def _close(self) -> None:
        close_graded_window(self.logger)

    async def _release_matrix(self) -> None:
        """Every check of the run passed: dma_matrix_pass 1 samples the held 412 cells."""
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        set_dma_matrix_pass(True, self.logger)
        await ClockCycles(clk, LABEL_CLKS)
        set_dma_matrix_pass(False, self.logger)
        await ClockCycles(clk, LABEL_REPLAY_CLKS)

    # ---- scenario ---------------------------------------------------------
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.k = 0
        plan = Plan(self.seed)
        self.logger.info(
            "PLAN %s seed=%d legA_cells=%d legB_xfers=%d legC_cells=%d legD_msgs=%d "
            "legD_cont_runs=%d",
            TEST,
            self.seed,
            len(plan.cells),
            len(plan.b_xfers),
            len(plan.edges),
            len(plan.msgs),
            len(plan.conts),
        )
        for line in plan.lines:
            self.logger.info(line)

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        dut = cocotb.top
        self.tap = SepDmaTap(dut).start()
        self.busy = SepBitWatch(dut.dma_busy_probe_o, name="dma_busy_probe_o").start()
        self.wdata = _WdataSampler(dut).start()
        self.wdata_beats = 0
        self.ops = _RotDmaOps(self, self.tap)
        self.mem = SepMemWords(self)
        try:
            await RisingEdge(dut.clk_i)
            set_dma_matrix_pass(False, self.logger)
            await self._setup()
            self.irq = SepBitWatch(
                dut.sep_internal_interrupts_probe_o, {"chunk": 9}, name="pic_src10"
            ).start()
            await self._leg_a(plan)
            await self._alias_runs(plan)
            await self._chunk1(plan)
            await self._obs_fixed_chunk(plan)
            await self._leg_b(plan)
            self._wdata_reach()
            await self._obs_ctrl_busy(plan)
            await self._leg_c(plan)
            await self._leg_d(plan)
            await self._leg_d_cont(plan)
            await self._nogo(plan)
            await self._range_copy(plan)
            await self._obs_chunk1_w4(plan)
            await self._obs_baselim_copy(plan)
            await self._obs_short_last_chunk(plan)
            await self._obs_csr64(plan)
            await self._obs_beat_hold(plan)
            await self._narrow_copies(plan)
            await self._obs_size_large(plan)
            self._close()
            await self._release_matrix()
        finally:
            self._close()
            await self.tap.stop()
            await self.busy.stop()
            await self.wdata.stop()
            if getattr(self, "irq", None) is not None:
                await self.irq.stop()
        self.result_pass(TEST, self.seed, self.k)

    async def _setup(self) -> None:
        """Step 2: digest reset read, wide range, ADDR_SPACE_ID, ADDR_HI, STATUS clear,
        chunk-done interrupt, inbound entry over the DMA registers."""
        ops = self.ops
        await self._check_digest_reset()
        await ops.program_range(SRAM_BASE, SRAM_LIMIT, valid=True)
        await ops.set_asid(ASID, ASID)
        await ops.wr(SRC_ADDR_HI, 0)
        await ops.wr(DST_ADDR_HI, 0)
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        await ops.wr(INTR_ENABLE, INTR_CHUNK_DONE)
        await SepFilterBank(self, "in").program(
            IN_ENTRY,
            FilterEntry(
                start=DMA_CSR_BASE,
                end=DMA_CSR_LAST,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=True,
            ),
        )
        self.logger.info(
            "SETUP range=0x%08x..0x%08x valid=1 addr_space_id=0x%02x intr_enable=0x%x",
            SRAM_BASE,
            SRAM_LIMIT,
            asid_word(ASID, ASID),
            INTR_CHUNK_DONE,
        )

    async def _check_digest_reset(self) -> None:
        """CHK-DMA-DIGEST-RESET: SHA2_DIGEST_0..15 read the reset value before any hash."""
        words = await self.ops.read_digest(DIGEST_WORDS)
        bad = [i for i, w in enumerate(words) if w != DIGEST_RESET]
        self._pass(
            "CHK-DMA-DIGEST-RESET",
            not bad,
            f"words={len(words)} expect=0x{DIGEST_RESET:08x} bad_words={bad or '-'} "
            f"values={','.join(f'0x{w:08x}' for w in words)}",
        )

    # ---- shared transfer pieces -------------------------------------------
    async def _fill_copy(self, c: CopyXfer) -> None:
        await self.mem.fill(c.src_addr, c.src_words)
        await self.mem.fill(c.dst_region, [sentinel_word(c.sentinel)] * c.dst_region_words)

    async def _program(
        self, c: CopyXfer, *, src: int | None = None, dst: int | None = None
    ) -> dict[str, int]:
        """Program ``c``; ``src`` and ``dst`` replace the model bases (alias form)."""
        x = c.x
        return await self.ops.program_transfer(
            src=x.src_base if src is None else src,
            dst=x.dst_base if dst is None else dst,
            total=x.total,
            chunk=x.chunk,
            width_enc=x.width_enc,
            src_inc=x.src_inc,
            src_wrap=x.src_wrap,
            dst_inc=x.dst_inc,
            dst_wrap=x.dst_wrap,
            order=list(c.order),
        )

    def _record(self, m_tap, m_irq, go_writes: int, statuses: list[DmaStatus]) -> XferRecord:
        m_end = self.tap.mark()
        return XferRecord(
            self.tap.between(m_tap, m_end),
            m_tap.clk,
            m_end.clk,
            go_writes,
            statuses,
            self.irq.rises_since(m_irq, "chunk"),
        )

    def _check_chunkrise(self, rec: XferRecord, n: int, tag: str) -> None:
        ev = rec.ev
        rises = ev.rises("chunk_done")
        falls = ev.falls("chunk_done")
        done_rises = ev.rises("done")
        r = len(rises)
        need = min(r, n - 1)
        hw_falls = 0
        for i in range(need):
            c = rises[i]
            nxt = [x for x in rises[i + 1 :] + done_rises if x > c]
            end = min(nxt) if nxt else rec.clk1 + 1
            if any(c < f < end for f in falls):
                hw_falls += 1
        sw = self.ops.status_writes(rec.clk0, rec.clk1)
        ok_count = (r == 0) if n == 1 else (n - 1 <= r <= n)
        ok = ok_count and hw_falls >= need and sw == 0
        self.logger.info(
            "OBS-DMA-LAST-CHUNKDONE seed=%d n=%d rises=%d last_rise_exempt=%d %s",
            self.seed,
            n,
            r,
            int(n > 1 and r == n),
            tag,
        )
        self._pass(
            "CHK-DMA-CHUNKRISE",
            ok,
            f"n={n} rises={r} hw_falls={hw_falls} last_rise_exempt={int(n > 1 and r == n)} "
            f"status_writes_in_window={sw} {tag} rise_clks={rises} fall_clks={falls}",
        )

    def _check_done_order(self, rec: XferRecord, total: int, tag: str) -> None:
        ev = rec.ev
        aw, b = len(ev.aw), len(ev.b)
        done_rises = ev.rises("done")
        last_b = max((x.clk for x in ev.b), default=None)
        # STATUS is the register output, sampled in the cycle of the handshake: DONE=1 in
        # the last B cycle was set before that B completed.
        early = [d for d in done_rises if last_b is None or d <= last_b]
        bad_resp = sum(1 for x in ev.b if x.resp != 0)
        ok = b > 0 and b == aw and bool(done_rises) and not early
        self._pass(
            "CHK-DMA-DONE-ORDER",
            ok,
            f"bytes={total} aw={aw} b={b} done_rises={len(done_rises)} last_b_clk={last_b} "
            f"done_rise_clk={done_rises[-1] if done_rises else None} early_rises={len(early)} "
            f"bresp_nonzero={bad_resp} {tag}",
        )

    def _digest_valid_edges(self, m_go: DmaTapMark, pre_go: int | None) -> DigestValidEdges:
        ev = self.tap.since(m_go)
        return DigestValidEdges(
            pre_go, m_go.clk, ev.falls("sha2_digest_valid"), ev.rises("sha2_digest_valid")
        )

    def _check_dv_pre_go(self, chk: str, dv: DigestValidEdges, tag: str) -> None:
        if dv.pre_go not in (0, 1):
            self._ctrl_missing(chk, f"{tag}: SHA2_DIGEST_VALID before the GO = {dv.pre_go}")

    def _dv_fall_reach(self, chk: str, falls: int, runs: int) -> None:
        """At least one run of the seed starts with SHA2_DIGEST_VALID=1, so a clear can show."""
        line = f"{chk} runs={runs} graded_fall={falls}"
        if not falls:
            self._ctrl_missing(chk, f"no run with SHA2_DIGEST_VALID=1 before the GO: {line}")
        self.logger.info("CTRL-DMA-DV-FALL-REACH seen seed=%d %s", self.seed, line)

    def _obs_edge_order(self, ev: DmaTapEvents, clk0: int, tag: str) -> None:
        """STATUS edge clocks and the last B of one transfer, relative to its GO."""

        def rel(clks: list[int]) -> str:
            return ",".join(str(c - clk0) for c in clks) or "-"

        last_b = max((x.clk for x in ev.b), default=None)
        self.logger.info(
            "OBS-DMA-EDGE-ORDER seed=%d %s busy_rise=%s chunk_done_rise=%s done_rise=%s "
            "done_fall=%s digest_valid_rise=%s digest_valid_fall=%s last_b=%s",
            self.seed,
            tag,
            rel(ev.rises("busy")),
            rel(ev.rises("chunk_done")),
            rel(ev.rises("done")),
            rel(ev.falls("done")),
            rel(ev.rises("sha2_digest_valid")),
            rel(ev.falls("sha2_digest_valid")),
            "-" if last_b is None else str(last_b - clk0),
        )

    def _check_go_chunks(self, rec: XferRecord, x: DmaXfer, tag: str) -> int:
        """Stops between chunks and destination progress at each later GO.

        Returns the number of STATUS reads with CHUNK_DONE=1, BUSY=0, DONE=0.
        Graded only for n >= 2 chunks; a single-chunk caller uses the count as
        the control.
        """
        n = x.n_chunks
        stops = sum(1 for s in rec.statuses if s.chunk_done and not s.busy and not s.done)
        if n < 2:
            return stops
        gos = [
            c0
            for c0, _, addr, data in self.ops.writes
            if addr == CONTROL and data & GO_MASK and rec.clk0 <= c0 < rec.clk1
        ]
        progress = []
        bad = 0
        for k, c0 in enumerate(gos[1:], start=1):
            want = sum(1 for i in range(x.n_txn) if x.chunk_of(i) < k)
            aw = sum(1 for b in rec.ev.aw if b.clk < c0)
            wb = sum(1 for b in rec.ev.w if b.clk < c0)
            progress.append(f"{k}:{aw}/{wb}/{want}")
            if aw != want or wb != want:
                bad += 1
        self._pass(
            "CHK-DMA-GO-CHUNKS",
            stops == n - 1 and bad == 0,
            f"n={n} stop_reads={stops} expect_stops={n - 1} progress_bad={bad} "
            f"aw/w/expect_at_go={','.join(progress) or '-'} {tag}",
        )
        return stops

    async def _read_regs(self) -> tuple[DmaStatus, int, int]:
        st = await self.ops.read_status()
        err = await self.ops.rd(ERROR_CODE)
        ctl = await self.ops.rd(CONTROL)
        return st, err, ctl

    async def _wait_idle_done(self, tag: str) -> DmaStatus:
        return await self.ops.poll_status(
            lambda s: bool(s.done and not s.busy), 50, f"DONE=1 BUSY=0 {tag}"
        )

    # ---- Leg A ------------------------------------------------------------
    async def _leg_a(self, plan: Plan) -> None:
        reach = dict.fromkeys(_RotDmaOps.MASTERS, 0)
        enc2_lanes: set[int] = set()
        for i, cd in enumerate(plan.cells):
            master = _RotDmaOps.MASTERS[(plan.rot_start + i) % len(_RotDmaOps.MASTERS)]
            reach[master] += 1
            meas = await self._cell_measure(cd, master=master, rot=True)
            if cd.enc == 2:
                enc2_lanes |= {b.strb for b in meas["rec"].ev.w if b.strb is not None}
            await self._cell_grade(cd, meas)
        self.logger.info(
            "INFO-DMA-LANE-REACH seed=%d enc2_lanes=%s",
            self.seed,
            ",".join(f"0x{v:02x}" for v in sorted(enc2_lanes)) or "-",
        )
        line = " ".join(f"{k}={v}" for k, v in reach.items())
        self.logger.info("INFO-DMA-MASTER-REACH seed=%d %s", self.seed, line)
        if not all(reach.values()):
            self._ctrl_missing("CHK-DMA-MASTER-ROT", f"a master programmed no transfer: {line}")

    async def _read_xfer_regs(self) -> dict[str, int]:
        return {
            n: await self.ops.rd(SECURE_DMA.addr(n)) & SECURE_DMA.mask32(n) for n in XFER_ORDER_REGS
        }

    async def _master_readback(
        self, written: dict[str, int], prior: dict[str, int], master: str, tag: str
    ) -> None:
        """CHK-DMA-MASTER-ROT: each transfer register write of the master changes the register.

        ``prior`` holds the values read before the program. A register that
        already held the value written is written with the inverted field
        value, read, and written again, so every graded write moves the
        register away from the value read before it.
        """
        ops = self.ops
        bad = []
        vals = []
        for name, value in written.items():
            mask = SECURE_DMA.mask32(name)
            addr = SECURE_DMA.addr(name)
            want = value & mask
            before = prior[name]
            if before == want:
                await ops.wr(addr, ~value & mask)
                before = await ops.rd(addr) & mask
                await ops.wr(addr, value)
            got = await ops.rd(addr) & mask
            vals.append(f"{name}:0x{before:x}/0x{want:x}/0x{got:x}")
            if got != want or before == want:
                bad.append(name)
        self._pass(
            "CHK-DMA-MASTER-ROT",
            not bad,
            f"master={master} regs={len(written)} bad={','.join(bad) or '-'} "
            f"prior/written/readback={','.join(vals)} "
            f"contract=hw/sys/sep/doc/fabric.adoc:102-103 {tag}",
        )

    async def _cell_measure(
        self,
        cd: CellDraw,
        *,
        master: str = "lsu",
        rot: bool = False,
        src: int | None = None,
        dst: int | None = None,
        tag_extra: str = "",
    ) -> dict:
        """Run one Leg-A-shaped copy and collect its readbacks; the window stays open.

        ``master`` programs and polls the DMA registers; with ``rot`` the
        transfer registers are read back on it before GO. ``src`` and ``dst``
        replace the programmed bases (alias form); the expected values stay
        those of the direct-form model.
        """
        ops = self.ops
        c, x = cd.copy, cd.copy.x
        tag = f"cell={cell_name(cd.cell)} enc={cd.enc}{tag_extra}"
        await self._fill_copy(c)
        ops.master = master
        try:
            prior = await self._read_xfer_regs() if rot else {}
            written = await self._program(c, src=src, dst=dst)
            if rot:
                await self._master_readback(written, prior, master, tag)
            m_tap, m_irq, m_wd = self.tap.mark(), self.irq.mark(), self.wdata.mark()
            self._open()
            await ops.go(opcode=OP_COPY, initial=1)
            # The poll bound scales with the transaction count of the cell.
            res = await ops.run_to_done(
                poll_size(4 * x.n_txn), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=f" {tag}"
            )
            if res.status.done:
                await self._wait_idle_done(tag)
            rec = self._record(m_tap, m_irq, res.go_writes, res.statuses)
            wd = self.wdata.since(m_wd)
            st, err, _ = await self._read_regs()
        finally:
            ops.master = "lsu"
        self.logger.info(
            "LEGA %s master=%s statuses=%s",
            tag,
            master,
            rle([f"b{s.busy}d{s.done}c{s.chunk_done}e{s.error}" for s in res.statuses]),
        )
        got_dst = await self.mem.read(c.dst_region, c.dst_region_words)
        got_src = await self.mem.read(c.src_addr, len(c.src_words))
        exp = c.expected_dst()
        sw = sentinel_word(c.sentinel)
        return dict(
            tag=tag,
            res=res,
            rec=rec,
            wd=wd,
            st=st,
            got_dst=got_dst,
            exp=exp,
            mism=sum(1 for g, e in zip(got_dst[1:-1], exp[1:-1]) if g != e),
            guard_ok=int(got_dst[0] == sw and got_dst[-1] == sw),
            src_ok=int(got_src == c.src_words),
            fst=field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR),
            fer=field_compare(err, 0, ERROR_CODE_MASK),
        )

    async def _cell_grade(self, cd: CellDraw, meas: dict) -> None:
        """The Leg A checks of one measured copy; closes the window and clears STATUS."""
        c, x = cd.copy, cd.copy.x
        tag, res, rec, st = meas["tag"], meas["res"], meas["rec"], meas["st"]
        mism, fst, fer = meas["mism"], meas["fst"], meas["fer"]
        if mism:
            got_dst, exp = meas["got_dst"], meas["exp"]
            first = next(i for i, (g, e) in enumerate(zip(got_dst, exp)) if g != e and 0 < i)
            self.logger.error(
                "LEGA %s first mismatch word %d @0x%08x got=0x%08x exp=0x%08x",
                tag,
                first,
                c.dst_region + 4 * first,
                got_dst[first],
                exp[first],
            )
        ok = mism == 0 and meas["guard_ok"] and meas["src_ok"] and fst.ok and fer.ok
        self._pass(
            "CHK-DMA-IMAGE",
            ok,
            f"cell={cell_name(cd.cell)} enc={cd.enc} w={x.w} chunk={cd.chunk} n={cd.n} "
            f"bytes={x.total} mem_mismatch={mism} guard_ok={meas['guard_ok']} error={st.error} "
            f"go_writes={res.go_writes} src_ok={meas['src_ok']} {ff('status', fst)} "
            f"{ff('error_code', fer)}",
        )
        self._check_beats(cd, rec)
        self._check_wdata(c, meas["wd"], tag)
        self._check_chunkrise(rec, cd.n, tag)
        self._check_done_order(rec, x.total, tag)
        self._check_go_chunks(rec, x, tag)
        self._close()
        await self.ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)

    @staticmethod
    def _beat_mm(x: DmaXfer, ev: DmaTapEvents) -> tuple[int, int, int]:
        """(AR/AW address mismatches, WSTRB mismatches, address mask) against ``x``.

        WSTRB of a w-byte write at A is ``((1 << w) - 1) << (A mod 8)`` on the
        64-bit master (AMBA AXI protocol specification (IHI 0022), narrow
        transfers; ``env/sep_dma_model.wstrb_lanes``).
        """
        n = x.n_txn
        amask = 0xFFFF_FFFF if x.width_enc == 2 else 0xFFFF_FFFC
        addr_mm = abs(len(ev.ar) - n) + abs(len(ev.aw) - n)
        for got, exp in ((ev.ar, x.ar_addrs()), (ev.aw, x.aw_addrs())):
            addr_mm += sum(
                1 for b, e in zip(got, exp) if b.addr is None or (b.addr & amask) != (e & amask)
            )
        strb_mm = abs(len(ev.w) - n) + sum(1 for b, e in zip(ev.w, x.wstrbs()) if b.strb != e)
        return addr_mm, strb_mm, amask

    def _check_beats(self, cd: CellDraw, rec: XferRecord) -> None:
        x, ev = cd.copy.x, rec.ev
        n_txn = x.n_txn
        ar, aw, wb = ev.ar, ev.aw, ev.w
        axlen_nz = sum(1 for b in ar + aw if b.len != 0)
        wstrb_bad = sum(1 for b in wb if b.strb is None or bin(b.strb).count("1") != x.w)
        rstep_bad = 0
        if cd.enc == 2 and x.src_inc:
            for i in range(1, min(len(ar), n_txn)):
                if x.chunk_of(i) == x.chunk_of(i - 1):
                    if ar[i].addr is None or ar[i - 1].addr is None:
                        rstep_bad += 1
                    elif ar[i].addr - ar[i - 1].addr != 4:
                        rstep_bad += 1
        name = cell_name(cd.cell)
        ok = (
            len(ar) == n_txn
            and len(aw) == n_txn
            and len(wb) == n_txn
            and n_txn > 0
            and axlen_nz == 0
            and wstrb_bad == 0
            and rstep_bad == 0
        )
        self._pass(
            "CHK-DMA-BEAT",
            ok,
            f"cell={name} enc={cd.enc} w={x.w} bytes={x.total} ar={len(ar)} aw={len(aw)} "
            f"axlen_nonzero={axlen_nz} wstrb_bad={wstrb_bad} rstep_bad={rstep_bad} "
            f"w_beats={len(wb)} expect_beats={n_txn}",
        )
        exp_ar, exp_aw = x.ar_addrs(), x.aw_addrs()
        addr_mm, strb_mm, amask = self._beat_mm(x, ev)
        low_eq = "-"
        if cd.enc != 2:
            low_eq = str(
                sum(
                    1
                    for got, exp in ((ar, exp_ar), (aw, exp_aw))
                    for b, e in zip(got, exp)
                    if b.addr is not None and b.addr & 3 == e & 3
                )
            )
        self.logger.info(
            "OBS-DMA-ADDR-LOW LOG seed=%d enc=%d width_bytes=%d beats=%d low_eq_model=%s "
            "arsize=%s awsize=%s cell=%s",
            self.seed,
            cd.enc,
            x.w,
            len(ar) + len(aw),
            low_eq,
            rle([str(b.size) for b in ar]) or "-",
            rle([str(b.size) for b in aw]) or "-",
            name,
        )
        if addr_mm or strb_mm:
            for i, (b, e) in enumerate(zip(ar, exp_ar)):
                if b.addr is None or (b.addr & amask) != (e & amask):
                    self.logger.error("AR %d got=%s exp=0x%08x", i, b.addr, e)
                    break
            for i, (b, e) in enumerate(zip(aw, exp_aw)):
                if b.addr is None or (b.addr & amask) != (e & amask):
                    self.logger.error("AW %d got=%s exp=0x%08x", i, b.addr, e)
                    break
            for i, (b, e) in enumerate(zip(wb, x.wstrbs())):
                if b.strb != e:
                    self.logger.error("W %d strb=%s exp=0x%02x", i, b.strb, e)
                    break
        lanes = sorted({b.strb for b in wb if b.strb is not None})
        self._pass(
            "CHK-DMA-ADDR",
            n_txn > 0 and addr_mm == 0 and strb_mm == 0,
            f"cell={name} enc={cd.enc} beats={len(ar) + len(aw)} addr_mismatch={addr_mm} "
            f"strb_lane_mismatch={strb_mm} addr_mask=0x{amask:08x} "
            f"strb_lanes={','.join(f'0x{v:02x}' for v in lanes) or '-'}",
        )

    def _check_wdata(self, c: CopyXfer, beats: list[tuple[int | None, ...]], tag: str) -> None:
        """CHK-DMA-WDATA-LANE: each W beat carries its source bytes on its WSTRB lanes.

        Write beat k carries the w bytes read at the source address of
        transaction k on lanes L to L+w-1, L = AWADDR mod 8 of the model
        (AMBA AXI protocol specification (IHI 0022), narrow transfers; the
        width of TRANSFER_WIDTH.TRANSACTION_WIDTH,
        ``vendor/lowRISC/opentitan/overlay/regs/secure_dma/regs/gen/adoc/secure_dma.adoc:241-243``).
        Lanes outside the WSTRB lanes are not graded.
        """
        x = c.x
        src = words_to_bytes(c.src_addr, c.src_words)
        bad = 0
        first = "-"
        graded = beats[: x.n_txn]
        for k, lanes in enumerate(graded):
            lane0 = x.dst_addr(k) % BUS_BYTES
            for i in range(x.w):
                lane = lane0 + i
                exp = src[x.src_addr(k) + i]
                got = lanes[lane]
                if got != exp:
                    bad += 1
                    if first == "-":
                        got_s = "x" if got is None else f"0x{got:02x}"
                        first = f"beat{k}/lane{lane}/got={got_s}/exp=0x{exp:02x}"
        self.wdata_beats += len(graded)
        self._pass(
            "CHK-DMA-WDATA-LANE",
            x.n_txn > 0 and len(beats) == x.n_txn and bad == 0,
            f"{tag} w={x.w} w_beats={len(beats)} expect_beats={x.n_txn} "
            f"graded_beats={len(graded)} byte_mismatch={bad} first_mismatch={first}",
        )

    def _wdata_reach(self) -> None:
        line = f"seed={self.seed} graded_beats={self.wdata_beats}"
        self.logger.info("INFO-DMA-WDATA-REACH %s", line)
        if self.wdata_beats == 0:
            self._ctrl_missing("CHK-DMA-WDATA-LANE", f"no W beat graded: {line}")

    # ---- Leg B ------------------------------------------------------------
    async def _check_cfg_regwen(self, regwen_busy: int | None, tag: str) -> int:
        """CHK-DMA-CFG-REGWEN for one long Leg B transfer; returns 1 when graded.

        ``regwen_busy`` is the REGWEN field of a read that ran entirely at
        ``dma_busy_probe_o`` = 1 (None: no such read, not graded). The idle read
        runs after DONE=1 BUSY=0 and must run entirely at ``dma_busy_probe_o`` = 0.
        """
        if regwen_busy is None:
            self.logger.info("LEGB %s CFG_REGWEN no read landed at BUSY=1; not graded", tag)
            return 0
        m = self.busy.mark()
        v = await self.ops.rd(CFG_REGWEN)
        idle_through = int(self.busy.level() == 0 and not self.busy.rise_clks_since(m))
        regwen_idle = v & CFG_REGWEN_MASK
        line = (
            f"busy_regwen=0x{regwen_busy:x} busy_expect=0x{CFG_REGWEN_BUSY:x} "
            f"idle_regwen=0x{regwen_idle:x} idle_expect=0x{CFG_REGWEN_IDLE:x} "
            f"busy_through_read=1 idle_through_read={idle_through} {tag}"
        )
        if not idle_through:
            self._ctrl_missing("CHK-DMA-CFG-REGWEN", f"idle read not at BUSY=0: {line}")
        self._pass(
            "CHK-DMA-CFG-REGWEN",
            regwen_busy == CFG_REGWEN_BUSY and regwen_idle == CFG_REGWEN_IDLE,
            line,
        )
        return 1

    async def _poll_b(
        self, total: int, m_busy, want_ctrl: bool, tag: str
    ) -> tuple[DmaStatus, int, list[tuple[DmaStatus, int]], int | None, int | None]:
        """Steps 9 and 10: poll to DONE=1 BUSY=0 after a BUSY rise, with the re-GO rule.

        Returns the last STATUS, the GO-write count, every (STATUS, probe level)
        read, the GO bit of a CONTROL read that ran entirely at BUSY=1, and the
        CFG_REGWEN value of a read that ran entirely at BUSY=1 (None when no such
        read landed).
        """
        ops = self.ops
        bound = ops.done_bound(poll_size(total))
        go_writes = 1
        reads: list[tuple[DmaStatus, int]] = []
        ctrl_go: int | None = None
        regwen_busy: int | None = None
        tries = 0
        regwen_tries = 0
        for _ in range(bound):
            if want_ctrl and ctrl_go != 1 and tries < CTRL_READ_TRIES and self.busy.level() == 1:
                m = self.busy.mark()
                v = await ops.rd(CONTROL)
                tries += 1
                if self.busy.level() == 1 and not self.busy.fall_clks_since(m):
                    ctrl_go = int(bool(v & GO_MASK))
                    self.logger.info(
                        "LEGB %s CONTROL=0x%08x go=%d busy_through_read=1", tag, v, ctrl_go
                    )
            if (
                want_ctrl
                and regwen_busy is None
                and regwen_tries < CTRL_READ_TRIES
                and self.busy.level() == 1
            ):
                m = self.busy.mark()
                v = await ops.rd(CFG_REGWEN)
                regwen_tries += 1
                if self.busy.level() == 1 and not self.busy.fall_clks_since(m):
                    regwen_busy = v & CFG_REGWEN_MASK
                    self.logger.info("LEGB %s CFG_REGWEN=0x%08x busy_through_read=1", tag, v)
            st = await ops.read_status()
            reads.append((st, int(self.busy.level() or 0)))
            if st.done and not st.busy and self.busy.rose_since(m_busy):
                return st, go_writes, reads, ctrl_go, regwen_busy
            if st.error or st.aborted:
                return st, go_writes, reads, ctrl_go, regwen_busy
            if st.chunk_done and not st.done and not st.busy:
                m = self.busy.mark()
                value = (ops.last_control & ~control_word(initial=1)) | GO_MASK
                await ops.wr(CONTROL, value)
                go_writes += 1
                await self.busy.wait_rise(m, BUSY_RISE_BOUND)
        msg = (
            f"FAIL-DMA-TIMEOUT {tag}: DONE=1 BUSY=0 after a BUSY rise not seen in {bound} "
            f"STATUS reads (total={total}, go_writes={go_writes})"
        )
        self.logger.error(msg)
        raise DmaTimeout(msg)

    async def _grade_geom(
        self, c: CopyXfer, st: DmaStatus, err: int, ctl: int, go_writes: int, cgb: str, lead: str
    ) -> None:
        """CHK-DMA-GEOM: DONE=1 BUSY=0 ERROR=0, GO=0, ERROR_CODE=0, model image, guards intact."""
        x = c.x
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        exp = c.expected_dst()
        mism = sum(1 for g, e in zip(got[1:-1], exp[1:-1]) if g != e)
        sw = sentinel_word(c.sentinel)
        guard_ok = got[0] == sw and got[-1] == sw
        fst = field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
        fgo = field_compare(ctl, 0, GO_MASK)
        fer = field_compare(err, 0, ERROR_CODE_MASK)
        self._pass(
            "CHK-DMA-GEOM",
            fst.ok and fgo.ok and fer.ok and mism == 0 and guard_ok,
            f"{lead}total={x.total} chunk={x.chunk} n={x.n_chunks} go_writes={go_writes} "
            f"done={st.done} busy={st.busy} go={int(bool(ctl & GO_MASK))} error={st.error} "
            f"mem_mismatch={mism} control_go_busy={cgb} guard_ok={int(guard_ok)} "
            f"{ff('status', fst)} {ff('control', fgo)} {ff('error_code', fer)}",
        )

    async def _leg_b(self, plan: Plan) -> None:
        ops = self.ops
        single_runs: list[tuple[int, int, int]] = []  # (total, n, polls_with_chunk_done)
        multi_polls = 0
        multi_chunk_polls = 0
        multi_irq_rises = 0
        ctrl_go_busy_seen = False
        regwen_graded = 0
        single_stops: list[int] = []
        for i, c in enumerate(plan.b_xfers):
            x = c.x
            n = x.n_chunks
            tag = f"total={x.total} chunk={x.chunk}"
            await self._fill_copy(c)
            await self._program(c)
            await ops.wr(STATUS, ST_CHUNK_DONE)
            pre_go_done = None
            if i > 0:
                pre = await ops.read_status()
                pre_go_done = pre.done
                self.logger.info("LEGB %s pre-GO %s", tag, pre.fmt())
            m_tap, m_irq, m_busy = self.tap.mark(), self.irq.mark(), self.busy.mark()
            m_wd = self.wdata.mark()
            self._open()
            await ops.go(opcode=OP_COPY, initial=1)
            st, go_writes, reads, ctrl_go, regwen_busy = await self._poll_b(
                x.total, m_busy, x.total >= LONG_TOTAL, tag
            )
            rec = self._record(m_tap, m_irq, go_writes, [s for s, _ in reads])
            wd = self.wdata.since(m_wd)
            self._obs_edge_order(rec.ev, rec.clk0, f"leg=B {tag}")
            busy_trace = (
                f"rises={self.busy.rise_clks_since(m_busy)} "
                f"falls={self.busy.fall_clks_since(m_busy)} from_clk={m_busy.clk}"
            )
            self.logger.info(
                "LEGB %s go_writes=%d reads=%s busy_probe %s",
                tag,
                go_writes,
                rle([f"b{s.busy}d{s.done}c{s.chunk_done}p{p}" for s, p in reads]),
                busy_trace,
            )
            st2, err, ctl = await self._read_regs()
            if x.total >= LONG_TOTAL:
                regwen_graded += await self._check_cfg_regwen(regwen_busy, tag)
            if x.total >= LONG_TOTAL and ctrl_go == 1:
                ctrl_go_busy_seen = True
            cgb = "1" if (x.total >= LONG_TOTAL and ctrl_go == 1) else "-"
            await self._grade_geom(c, st2, err, ctl, go_writes, cgb, "")
            if i > 0 and x.total >= LONG_TOTAL:
                if pre_go_done != 1:
                    self._ctrl_missing("CHK-DMA-DONE-CLR", f"{tag} pre_go_done={pre_go_done}")
                k0 = sum(1 for s, _ in reads if s.busy and not s.done)
                self._pass(
                    "CHK-DMA-DONE-CLR",
                    k0 >= 1,
                    f"total={x.total} pre_go_done=1 busy_reads_done0={k0} "
                    f"busy_reads={sum(1 for s, _ in reads if s.busy)}",
                )
            self._check_wdata(c, wd, f"leg=B {tag}")
            if n == 1:
                single_runs.append((x.total, n, sum(1 for s, _ in reads if s.chunk_done)))
            else:
                multi_polls += len(reads)
                multi_chunk_polls += sum(1 for s, _ in reads if s.chunk_done)
                multi_irq_rises += rec.irq_rises
            self._check_chunkrise(rec, n, tag)
            self._check_done_order(rec, x.total, tag)
            stops = self._check_go_chunks(rec, x, tag)
            self._close()
            if n == 1:
                single_stops.append(stops)
        if not single_stops or any(single_stops):
            self._ctrl_missing(
                "CHK-DMA-GO-CHUNKS",
                f"single-chunk stop reads={single_stops}, expected one 0 per transfer",
            )
        if not ctrl_go_busy_seen:
            self._ctrl_missing(
                "CHK-DMA-GEOM", "no CONTROL read returned GO=1 at BUSY=1 on a total >= 1024"
            )
        if regwen_graded == 0:
            self._ctrl_missing(
                "CHK-DMA-CFG-REGWEN", "no total >= 1024 had a CFG_REGWEN read at BUSY=1"
            )
        if multi_chunk_polls == 0 and multi_irq_rises == 0:
            self._ctrl_missing(
                "CHK-DMA-CHUNKDONE",
                f"multi-chunk polls={multi_polls} with CHUNK_DONE=1: 0, PIC source 10 rises: 0",
            )
        for total, n, k in single_runs:
            self._pass(
                "CHK-DMA-CHUNKDONE",
                k == 0,
                f"n={n} single=1 polls_with_chunk_done={k} "
                f"control_multi_polls={multi_chunk_polls} "
                f"control_chunk_irq_rises={multi_irq_rises} total={total}",
            )

    # ---- logged runs --------------------------------------------------------
    async def _obs_fixed_chunk(self, plan: Plan) -> None:
        """Source address of the second chunk of a two-chunk copy from a fixed source.

        The source is programmed in the drawn form (direct or local alias); the
        tap addresses are after the alias remap.
        """
        ops = self.ops
        src, dst, chunk, s, words = plan.fixed
        await self.mem.fill(src, words)
        await self.mem.fill(dst, [sentinel_word(s)] * (2 * chunk // 4))
        await ops.program_transfer(
            src=alias_of(src) if plan.fixed_form == "alias" else src,
            dst=dst,
            total=2 * chunk,
            chunk=chunk,
            width_enc=2,
            src_inc=False,
        )
        m_tap = self.tap.mark()
        await ops.go(opcode=OP_COPY, initial=1)
        res = await ops.run_to_done(
            poll_size(2 * chunk), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=" fixed-src"
        )
        if res.status.done:
            await self._wait_idle_done("fixed-src")
        ev = self.tap.since(m_tap)
        gos = [
            c0
            for c0, _, addr, data in ops.writes
            if addr == CONTROL and data & GO_MASK and c0 >= m_tap.clk
        ]
        second = [b.addr for b in ev.ar if len(gos) > 1 and b.clk >= gos[1]]
        err = await ops.rd(ERROR_CODE)
        self.logger.info(
            "OBS-DMA-FIXED-CHUNK seed=%d form=%s chunk=%d go_writes=%d done=%d error=%d "
            "error_code=0x%x src=0x%08x chunk2_ar=%s chunk2_first_off=%s",
            self.seed,
            plan.fixed_form,
            chunk,
            res.go_writes,
            res.status.done,
            res.status.error,
            err,
            src,
            ",".join("-" if a is None else f"0x{a:08x}" for a in second) or "-",
            "-" if not second or second[0] is None else str(second[0] - src),
        )
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE | ST_ERROR)

    async def _obs_ctrl_busy(self, plan: Plan) -> None:
        """A CONTROL write with a drawn GO bit while BUSY=1, during a long single-chunk copy."""
        ops = self.ops
        c, x = plan.busy_copy, plan.busy_copy.x
        await self._fill_copy(c)
        await self._program(c)
        m_tap, m_busy = self.tap.mark(), self.busy.mark()
        await ops.go(opcode=OP_COPY, initial=1)
        await self.busy.wait_rise(m_busy, BUSY_RISE_BOUND)
        value = (ops.last_control & ~GO_MASK) | (GO_MASK if plan.busy_go else 0)
        m_wr = self.busy.mark()
        wr_c0 = self.tap.clk
        wseq = await ops.access(SepAxiOp.WRITE, CONTROL, value)
        wr_c1 = self.tap.clk
        ops.writes.append((wr_c0, wr_c1, CONTROL, value))
        busy_through = int(self.busy.level() == 1 and not self.busy.fall_clks_since(m_wr))
        ctrl_wr = await ops.rd(CONTROL)
        st = None
        for _ in range(ops.done_bound(poll_size(x.total))):
            st = await ops.read_status()
            if (st.done and not st.busy) or st.error or st.aborted:
                break
        await ClockCycles(cocotb.top.clk_i, BUSY_SETTLE_CLKS)
        err = await ops.rd(ERROR_CODE)
        ctrl_done = await ops.rd(CONTROL)
        ev = self.tap.since(m_tap)
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        exp = c.expected_dst()
        mism = sum(1 for g, e in zip(got[1:-1], exp[1:-1]) if g != e)
        self.logger.info(
            "OBS-DMA-CTRL-BUSY seed=%d go=%d control=0x%08x busy_through_write=%d ar=%d aw=%d "
            "n_txn=%d %s error_code=0x%x dst_mismatch=%d control_after_write=0x%08x "
            "control_after_done=0x%08x",
            self.seed,
            plan.busy_go,
            value,
            busy_through,
            len(ev.ar),
            len(ev.aw),
            x.n_txn,
            st.fmt(),
            err,
            mism,
            ctrl_wr,
            ctrl_done,
        )
        # Tap clocks: the STATUS.BUSY rise of this copy, the write, and the
        # first STATUS.DONE rise after the write.
        busy_rise = next(iter(ev.rises("busy")), None)
        busy_rises = len(list(ev.rises("busy")))
        done_rise = next((c for c in ev.rises("done") if c >= wr_c1), None)
        ctrl = (
            f"go={plan.busy_go} write_resp={wseq.resp_code} busy_through_write={busy_through} "
            f"write_clk={wr_c0}-{wr_c1} busy_rise_clk={'-' if busy_rise is None else busy_rise} "
            f"done_clk={'-' if done_rise is None else done_rise} "
            f"write_after_busy={'-' if busy_rise is None else wr_c0 - busy_rise} "
            f"done_after_write={'-' if done_rise is None else done_rise - wr_c1}"
        )
        if not plan.busy_go:
            self.logger.info("INFO-DMA-CTRL-BUSY-SKIP seed=%d %s", self.seed, ctrl)
        elif not (
            wseq.resp_ok
            and busy_through
            and busy_rise is not None
            and done_rise is not None
            and busy_rise <= wr_c0
        ):
            self._ctrl_missing("CHK-DMA-CTRL-BUSY", ctrl)
        else:
            self.logger.info("CTRL-DMA-CTRL-BUSY PASS seed=%d %s", self.seed, ctrl)
            self._pass(
                "CHK-DMA-CTRL-BUSY",
                len(ev.ar) == x.n_txn and len(ev.aw) == x.n_txn and busy_rises == 1,
                f"contract=hw/sys/sep/doc/dma.adoc:79-86 go=1 ar={len(ev.ar)} aw={len(ev.aw)} "
                f"expect={x.n_txn} busy_rises={busy_rises} expect_busy_rises=1",
            )
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE | ST_ERROR)

    # ---- Leg C ------------------------------------------------------------
    async def _range_write(self, base: int, limit: int, tag: str) -> tuple[int, int]:
        """CHK-DMA-RANGE-WR: unlocked range writes land; returns (base, limit) changed flags.

        The leaf writes RANGE_VALID 0, then BASE, LIMIT and RANGE_VALID 1 while
        RANGE_REGWEN reads True (its reset), and reads each register back. The
        registers held the wide range before, so a guarded edge changes BASE
        or LIMIT and every edge changes RANGE_VALID twice.
        """
        ops = self.ops
        regwen = await ops.rd(RANGE_REGWEN) & RANGE_REGWEN_MASK
        if regwen != RANGE_REGWEN_UNLOCKED:
            self._ctrl_missing(
                "CHK-DMA-RANGE-WR", f"{tag} RANGE_REGWEN=0x{regwen:x} before the range writes"
            )
        base0 = await ops.rd(RANGE_BASE) & RANGE_BASE_MASK
        limit0 = await ops.rd(RANGE_LIMIT) & RANGE_LIMIT_MASK
        valid0 = await ops.rd(RANGE_VALID) & RANGE_VALID_MASK
        await ops.wr(RANGE_VALID, 0)
        valid_mid = await ops.rd(RANGE_VALID) & RANGE_VALID_MASK
        await ops.program_range(base, limit, valid=True)
        got_base = await ops.rd(RANGE_BASE) & RANGE_BASE_MASK
        got_limit = await ops.rd(RANGE_LIMIT) & RANGE_LIMIT_MASK
        got_valid = await ops.rd(RANGE_VALID) & RANGE_VALID_MASK
        ok = (
            valid_mid == 0
            and got_base == base & RANGE_BASE_MASK
            and got_limit == limit & RANGE_LIMIT_MASK
            and got_valid == RANGE_VALID_MASK
        )
        self._pass(
            "CHK-DMA-RANGE-WR",
            ok,
            f"{tag} regwen=0x{regwen:x} base_before=0x{base0:08x} base=0x{got_base:08x} "
            f"base_expect=0x{base & RANGE_BASE_MASK:08x} limit_before=0x{limit0:08x} "
            f"limit=0x{got_limit:08x} limit_expect=0x{limit & RANGE_LIMIT_MASK:08x} "
            f"valid_before={valid0} valid_after_0={valid_mid} valid={got_valid} "
            f"valid_expect={RANGE_VALID_MASK}",
        )
        return int(base0 != base & RANGE_BASE_MASK), int(limit0 != limit & RANGE_LIMIT_MASK)

    async def _edge_fill(self, e: EdgeDraw, base: int, limit: int, tag: str, graded: bool):
        """One Leg C cell: zero fills of the low and the high region under one range.

        The fill is the operation the range bounds (``hw/sys/sep/doc/dma.adoc:98-104``):
        the low region starts at ``range_lo`` and the high region ends at
        ``range_hi``, so the cell writes the bytes at BASE and at LIMIT that its
        edge places there. A graded cell runs in the window from its range
        writes to its reads. Before any GO, every word of both regions, the gap
        word and the guards must read the prefill, else CTRL-MISSING. Returns
        one (name, STATUS, ERROR_CODE, AW beats, W beats) per fill run, the
        nonzero words of the regions filled, the guards changed and the
        RANGE-WR changed flags.
        """
        ops = self.ops
        pre = e.prefill
        words = e.size // 4
        for region in (e.lo_region, e.hi_region):
            await self.mem.fill(region, [pre] * words)
        for g in e.guards():
            await self.mem.fill(g, [pre])
        seen = []
        for region in (e.lo_region, e.hi_region):
            seen += await self.mem.read(region, words)
        for g in e.guards():
            seen += await self.mem.read(g, 1)
        not_pre = sum(1 for w in seen if w != pre)
        pre_vals = f"{tag} prefill=0x{pre:08x} words={len(seen)} not_prefill={not_pre}"
        if not_pre:
            self._ctrl_missing("CHK-DMA-RANGE-OK", f"prefill readback {pre_vals}")
        self.logger.info("CTRL-DMA-RANGE-PREFILL PASS seed=%d %s", self.seed, pre_vals)
        changed = (0, 0)
        if graded:
            self._open()
            changed = await self._range_write(base, limit, tag)
        else:
            await ops.program_range(base, limit, valid=True)
        runs = []
        for name, region in e.fills():
            await ops.program_transfer(
                src=0, dst=region, total=e.size, chunk=e.size, width_enc=2, order=XFER_ORDER_REGS
            )
            m_tap = self.tap.mark()
            await ops.go(opcode=OP_ZERO, initial=1)
            res = await ops.run_to_done(
                poll_size(e.size), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=f" {tag}"
            )
            if res.status.done:
                await self._wait_idle_done(tag)
            ev = self.tap.since(m_tap)
            # ERROR_CODE is read before any STATUS write.
            st, err, _ = await self._read_regs()
            runs.append((name, st, err, len(ev.aw), len(ev.w)))
            if st.error:
                await self._clear_error(tag)
                break
            await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        nonzero = 0
        for _, region in e.fills()[: len(runs)]:
            got = await self.mem.read(region, e.size // 4)
            nonzero += sum(1 for w in got if w != 0)
        guards_bad = 0
        for g in e.guards():
            (v,) = await self.mem.read(g, 1)
            guards_bad += int(v != pre)
        if graded:
            self._close()
        return runs, nonzero, guards_bad, changed

    async def _clear_error(self, tag: str) -> None:
        """W1C STATUS.ERROR, DONE, ABORTED and CHUNK_DONE, then wait for BUSY=0.

        BUSY stays 1 in the error state until ERROR is cleared.
        """
        await self.ops.clean_state()
        await self.ops.poll_status(
            lambda s: not s.busy, ABORT_POLL_BOUND, f"BUSY=0 after the ERROR clear {tag}"
        )

    @staticmethod
    def _fill_grade(runs: list, words: int) -> tuple[bool, str]:
        """Both fills ended with DONE=1, BUSY=0, ERROR=0 and ERROR_CODE=0, and
        each put one AW and one W beat per region word on the DMA master tap."""
        ok = len(runs) == 2
        parts = [f"fills_run={len(runs)} expect_beats={words}"]
        for name, st, err, aw, w in runs:
            fst = field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
            fer = field_compare(err, 0, ERROR_CODE_MASK)
            ok = ok and fst.ok and fer.ok and aw == words and w == words
            parts.append(
                f"{ff(f'{name}_status', fst)} {ff(f'{name}_error_code', fer)} "
                f"{name}_aw={aw} {name}_w={w}"
            )
        return ok, " ".join(parts)

    async def _leg_c(self, plan: Plan) -> None:
        await self.ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        base_changed = limit_changed = 0
        for e in plan.edges:
            base, limit = e.base_limit()
            tag = f"edge={e.edge} order={e.order}"
            runs, nz, gbad, (bc, lc) = await self._edge_fill(e, base, limit, tag, graded=True)
            base_changed += bc
            limit_changed += lc
            # Control: the same fills under the wide range of step 2.
            cruns, cnz, cgbad, _ = await self._edge_fill(
                e, SRAM_BASE, SRAM_LIMIT, f"{tag} control_wide", graded=False
            )
            cok, cvals = self._fill_grade(cruns, e.size // 4)
            control_wide = int(cok and cnz == 0 and cgbad == 0)
            if not control_wide:
                self._ctrl_missing(
                    "CHK-DMA-RANGE-OK",
                    f"{tag} wide-range control failed: {cvals} nonzero_words={cnz} "
                    f"guards_bad={cgbad}",
                )
            fok, fvals = self._fill_grade(runs, e.size // 4)
            edge = "guard" if e.edge.startswith("guard") else e.edge
            self._pass(
                "CHK-DMA-RANGE-OK",
                fok and nz == 0 and gbad == 0,
                f"contract=hw/sys/sep/doc/dma.adoc:98-104 edge={edge} order={e.order} "
                f"base=0x{base:08x} limit=0x{limit:08x} lo=0x{e.lo_region:08x} "
                f"hi_last=0x{e.range_hi:08x} bytes={e.size} nonzero_words={nz} "
                f"guards_bad={gbad} control_wide={control_wide} cell={e.edge} {fvals}",
            )
        # The guard edges place BASE above and LIMIT below the wide range, so
        # every seed writes a changed BASE and a changed LIMIT.
        if base_changed == 0 or limit_changed == 0:
            self._ctrl_missing(
                "CHK-DMA-RANGE-WR",
                f"changed writes base={base_changed} limit={limit_changed}, expected >= 1 each",
            )

    # ---- Leg D ------------------------------------------------------------
    async def _hash_run(
        self,
        m: HashMsg,
        split: int,
        swap: int,
        run_idx: int,
        ctrl_state: dict,
        graded: bool,
        *,
        src: int | None = None,
        dst: int | None = None,
    ) -> tuple[list[int], dict]:
        """Steps 17 to 22 for one form and swap value; returns the digest words read.

        A graded run opens the window at its GO; the caller closes it after
        the checks of the run.
        """
        ops = self.ops
        alg_op, _, n_words = ALGS[m.alg]
        length = len(m.msg)
        chunk = length // split if split else length
        k = split or 1
        tag = f"alg={m.alg} kind={m.kind} len={length} split={split} swap={swap}"
        sw = sentinel_word(m.sentinel)
        await self.mem.fill(m.dst, [sw] * (length // 4))
        not_sw = sum(1 for w in await self.mem.read(m.dst, length // 4) if w != sw)
        self.logger.info(
            "CTRL-DMA-HASH-SENTINEL LOG seed=%d %s dst=0x%08x sentinel=0x%08x words=%d "
            "not_sentinel=%d",
            self.seed,
            tag,
            m.dst,
            sw,
            length // 4,
            not_sw,
        )
        if not_sw:
            self._ctrl_missing(
                "CHK-DMA-HASH", f"{tag}: {not_sw} destination words before the GO not the sentinel"
            )
        await ops.program_transfer(
            src=m.src if src is None else src,
            dst=m.dst if dst is None else dst,
            total=length,
            chunk=chunk,
            width_enc=2,
            order=XFER_ORDER_REGS,
        )
        chunk_rb = await ops.rd(CHUNK_DATA_SIZE) if split else None
        if split:
            self._ctrl_chunk_rb("CHK-DMA-HASH-CHAIN", tag, chunk_rb, chunk)
        if run_idx >= 1:
            pre = await ops.read_status()
            self.logger.info("LEGD %s pre-GO %s", tag, pre.fmt())
            if run_idx == 1:
                ctrl_state["before_second"] = pre.digest_valid
        if graded:
            self._open()
        dv_pre = self.tap.level("sha2_digest_valid")
        m_tap = self.tap.mark()
        await ops.go(opcode=alg_op, digest_swap=swap, initial=1)
        try:
            res = await ops.run_to_done(
                poll_size(length),
                busy=self.busy,
                w1c_chunk_done=True,
                busy_bound=BUSY_RISE_BOUND,
                max_go=k,
                tag=f" {tag}",
            )
        except DmaTimeout:
            raise
        except AssertionError as exc:
            msg = f"FAIL-DMA-TIMEOUT {tag}: more than {k} GO writes ({exc})"
            self.logger.error(msg)
            raise DmaTimeout(msg) from exc
        if res.status.done:
            await self._wait_idle_done(tag)
        busy_reads = [s for s in res.statuses if s.busy]
        stops = sum(1 for s in res.statuses if s.chunk_done and not s.busy and not s.done)
        self.logger.info(
            "LEGD %s go_writes=%d busy_reads=%s",
            tag,
            res.go_writes,
            rle([f"b{s.busy}d{s.done}c{s.chunk_done}v{s.digest_valid}" for s in busy_reads]),
        )
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        valid_after = 0
        for _ in range(VALID_POLL_BOUND):
            if (await ops.read_status()).digest_valid:
                valid_after = 1
                break
        dv = self._digest_valid_edges(m_tap, dv_pre)
        st, err, _ = await self._read_regs()
        words = await ops.read_digest(n_words)
        if split:
            self._obs_edge_order(self.tap.since(m_tap), m_tap.clk, f"leg=D {tag}")
        if n_words < DIGEST_WORDS:
            rest = (await ops.read_digest(DIGEST_WORDS))[n_words:]
            self.logger.info(
                "OBS-DMA-DIGEST-UNUSED seed=%d %s first_unused=%d words=%s",
                self.seed,
                tag,
                n_words,
                ",".join(f"0x{w:08x}" for w in rest),
            )
        dst = await self.mem.read(m.dst, length // 4)
        copy_mm = sum(
            1 for i, w in enumerate(dst) if w != int.from_bytes(m.msg[4 * i : 4 * i + 4], "little")
        )
        info = dict(
            tag=tag,
            split=split,
            swap=swap,
            go_writes=res.go_writes,
            stops=stops,
            chunk=chunk,
            chunk_rb=chunk_rb,
            done=res.status.done,
            error=st.error,
            err=err,
            busy_reads=len(busy_reads),
            busy_valid0=sum(1 for s in busy_reads if not s.digest_valid),
            valid_after=valid_after,
            dv=dv,
            copy_mm=copy_mm,
        )
        return words, info

    async def _scrub_digest(self, m: HashMsg, swap: int, run_idx: int, ctrl_state: dict) -> int:
        """Leave a different digest in the registers before a split-form run.

        The single-chunk run of the same message and swap leaves the golden
        digest in SHA2_DIGEST. A control hash of the complemented message, in
        a closed graded window, replaces it, so a split run that writes no
        digest reads the control digest and fails CHK-DMA-HASH. Returns the
        next run index.
        """
        scrub = replace(m, msg=bytes(b ^ 0xFF for b in m.msg))
        gold = golden_words(m.alg, m.msg, swap)
        scrub_gold = golden_words(m.alg, scrub.msg, swap)
        if scrub_gold == gold:
            self._ctrl_missing("CHK-DMA-HASH", f"alg={m.alg} scrub digest equals the golden")
        length = len(m.msg)
        words_of = [int.from_bytes(scrub.msg[i : i + 4], "little") for i in range(0, length, 4)]
        await self.mem.fill(m.src, words_of)
        words, info = await self._hash_run(scrub, 0, swap, run_idx, ctrl_state, graded=False)
        await self.mem.fill(
            m.src, [int.from_bytes(m.msg[i : i + 4], "little") for i in range(0, length, 4)]
        )
        mism = sum(1 for g, e in zip(words, scrub_gold) if g != e) + abs(
            len(words) - len(scrub_gold)
        )
        self.logger.info(
            "CTRL-DMA-HASH-SCRUB LOG seed=%d alg=%d len=%d swap=%d mismatch=%d done=%d error=%d",
            self.seed,
            m.alg,
            length,
            swap,
            mism,
            info["done"],
            info["error"],
        )
        if mism or info["done"] != 1 or info["error"]:
            self._ctrl_missing(
                "CHK-DMA-HASH", f"alg={m.alg} len={length} scrub run mismatch={mism}"
            )
        return run_idx + 1

    async def _leg_d(self, plan: Plan) -> None:
        run_idx = 0
        ctrl_state: dict = {}
        valid_lines: list[tuple[HashMsg, dict]] = []
        for m in plan.msgs:
            length = len(m.msg)
            sw = sentinel_word(m.sentinel)
            await self.mem.fill(
                m.src, [int.from_bytes(m.msg[i : i + 4], "little") for i in range(0, length, 4)]
            )
            await self.mem.fill(m.dst, [sw] * (length // 4))
            forms = [0] + ([m.split] if m.split else [])
            digests: dict[tuple[int, int], tuple[list[int], bool, dict]] = {}
            for split in forms:
                for swap in m.swaps:
                    if split:
                        run_idx = await self._scrub_digest(m, swap, run_idx, ctrl_state)
                    control = is_hash_control(m.alg, length, split, swap)
                    words, info = await self._hash_run(
                        m, split, swap, run_idx, ctrl_state, graded=not control
                    )
                    run_idx += 1
                    gold = golden_words(m.alg, m.msg, swap)
                    mism = sum(1 for g, e in zip(words, gold) if g != e) + abs(
                        len(words) - len(gold)
                    )
                    fer = field_compare(info["err"], 0, ERROR_CODE_MASK)
                    digests[(split, swap)] = (words, control, info)
                    if control:
                        self.logger.info(
                            "INFO-DMA-HASH-CTRL LOG seed=%d alg=%d len=%d split=%d swap=%d "
                            "words=%d mismatch=%d copy_mismatch=%d error=%d",
                            self.seed,
                            m.alg,
                            length,
                            split,
                            swap,
                            len(words),
                            mism,
                            info["copy_mm"],
                            info["error"],
                        )
                    else:
                        if mism:
                            self.logger.error(
                                "LEGD %s digest got=%s exp=%s",
                                info["tag"],
                                [f"{w:08x}" for w in words],
                                [f"{w:08x}" for w in gold],
                            )
                        ok = (
                            mism == 0
                            and info["copy_mm"] == 0
                            and info["done"] == 1
                            and info["error"] == 0
                            and fer.ok
                        )
                        self._pass(
                            "CHK-DMA-HASH",
                            ok,
                            f"alg={m.alg} len={length} split={split} swap={swap} "
                            f"words={len(gold)} mismatch={mism} copy_mismatch={info['copy_mm']} "
                            f"go_writes={info['go_writes']} {ff('error_code', fer)}",
                        )
                    valid_lines.append((m, info))
                    self._close()
            for swap in m.swaps:
                if not m.split:
                    continue
                a, ca, _ = digests[(0, swap)]
                b, cb, si = digests[(m.split, swap)]
                if ca or cb:
                    continue
                k = m.split
                expect_go = k
                ok = a == b and si["go_writes"] == expect_go and si["stops"] == k - 1
                self._pass(
                    "CHK-DMA-HASH-CHAIN",
                    ok,
                    f"alg={m.alg} len={length} split={k} single_eq_split={int(a == b)} "
                    f"go_writes={si['go_writes']} expect_go={expect_go} "
                    f"chunk_stops={si['stops']} expect_stops={k - 1} "
                    f"chunk_rb={si['chunk_rb']} expect_chunk={si['chunk']} swap={swap}",
                )
        if ctrl_state.get("before_second") != 1:
            self._ctrl_missing(
                "CHK-DMA-HASH-VALID",
                f"SHA2_DIGEST_VALID before the GO of the second run = "
                f"{ctrl_state.get('before_second')}",
            )
        falls_graded = 0
        for m, info in valid_lines:
            length = len(m.msg)
            graded_clear = length >= LONG_TOTAL
            if graded_clear and info["busy_reads"] == 0:
                self._ctrl_missing(
                    "CHK-DMA-HASH-VALID", f"{info['tag']}: no STATUS read landed at BUSY=1"
                )
            dv: DigestValidEdges = info["dv"]
            self._check_dv_pre_go("CHK-DMA-HASH-VALID", dv, info["tag"])
            falls_graded += dv.fall_graded
            ok = (
                info["valid_after"] == 1
                and dv.ok
                and (not graded_clear or info["busy_valid0"] >= 1)
            )
            self._pass(
                "CHK-DMA-HASH-VALID",
                ok,
                f"alg={m.alg} len={length} "
                f"busy_reads_valid0={info['busy_valid0'] if graded_clear else '-'} "
                f"after_last={info['valid_after']} {dv.fmt()} control_before_second=1 "
                f"kind={m.kind} split={info['split']} swap={info['swap']}",
            )
        self._dv_fall_reach("CHK-DMA-HASH-VALID", falls_graded, len(valid_lines))

    # ---- Leg D continuation -----------------------------------------------
    def _cont_control(self, c: ContMsg, i: int) -> int:
        """CONTROL of later start ``i``: GO=1, INITIAL_TRANSFER=0, drawn OPCODE, inverted swap."""
        return control_word(opcode=c.cont_ops[i], digest_swap=1 - c.swap, initial=0, go=1)

    def _cont_golden(self, c: ContMsg) -> list[int]:
        """Digest words of the first-start algorithm in the first-start byte order."""
        return golden_words(c.alg, c.msg, c.swap)

    async def _cont_run(self, c: ContMsg) -> bool:
        """One continuation run; returns whether its SHA2_DIGEST_VALID fall was graded."""
        ops = self.ops
        alg_op, _, n_words = ALGS[c.alg]
        length = len(c.msg)
        k = c.split
        tag = (
            f"alg={c.alg} len={length} split={k} swap={c.swap} "
            f"cont_ops={','.join(map(str, c.cont_ops))} cont_swap={1 - c.swap}"
        )
        gold = golden_words(c.alg, c.msg, c.swap)
        # Housekeeping with the window closed: message fill, stale digest.
        self._close()
        await self.mem.fill(
            c.src, [int.from_bytes(c.msg[i : i + 4], "little") for i in range(0, length, 4)]
        )
        await self.mem.fill(c.dst, [sentinel_word(c.sentinel)] * (length // 4))
        stale = await ops.read_digest(n_words)
        if stale == gold:
            self._ctrl_missing("CHK-DMA-CONT-CFG", f"{tag} digest before the GO equals the golden")

        await ops.program_transfer(
            src=c.src,
            dst=c.dst,
            total=length,
            chunk=length // k,
            width_enc=2,
            order=XFER_ORDER_REGS,
        )
        chunk_rb = await ops.rd(CHUNK_DATA_SIZE)
        self._ctrl_chunk_rb("CHK-DMA-CONT-CFG", tag, chunk_rb, length // k)
        self._open()
        dv_pre = self.tap.level("sha2_digest_valid")
        m_tap = self.tap.mark()
        first = await ops.go(opcode=alg_op, digest_swap=c.swap, initial=1)
        bound = ops.done_bound(poll_size(length))
        go_writes = 1
        stops = 0
        conts: list[tuple[int, int]] = []  # (CONTROL written, CONTROL read after it)
        st = None
        for _ in range(bound):
            st = await ops.read_status()
            if st.done or st.error or st.aborted:
                break
            if st.chunk_done and not st.busy:
                stops += 1
                if go_writes >= k:
                    self._pass(
                        "CHK-DMA-CONT-CFG",
                        False,
                        f"{tag} CHUNK_DONE=1 DONE=0 BUSY=0 after {go_writes} GO writes "
                        f"(chunks={k}); {st.fmt()}",
                    )
                await self._chunk_done_rw1c(tag, go_writes)
                mark = self.busy.mark()
                value = self._cont_control(c, go_writes - 1)
                await ops.wr(CONTROL, value)
                go_writes += 1
                conts.append((value, await ops.rd(CONTROL)))
                await self.busy.wait_rise(mark, BUSY_RISE_BOUND)
        else:
            self._close()
            msg = (
                f"FAIL-DMA-TIMEOUT {tag}: DONE not seen in {bound} STATUS reads "
                f"(go_writes={go_writes}, last {st.fmt() if st else 'none'})"
            )
            self.logger.error(msg)
            raise DmaTimeout(msg)
        done = st.done
        if done:
            await self._wait_idle_done(tag)
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        valid_after = 0
        for _ in range(VALID_POLL_BOUND):
            if (await ops.read_status()).digest_valid:
                valid_after = 1
                break
        dv = self._digest_valid_edges(m_tap, dv_pre)
        st2, err, _ = await self._read_regs()
        words = await ops.read_digest(n_words)
        dst = await self.mem.read(c.dst, length // 4)
        copy_mm = sum(
            1 for i, w in enumerate(dst) if w != int.from_bytes(c.msg[4 * i : 4 * i + 4], "little")
        )

        # Controls: the later starts reached CONTROL with values other than the first.
        rb_bad = [
            f"0x{w:08x}/0x{r:08x}"
            for w, r in conts
            if (r & CTRL_CFG_MASK) != (w & CTRL_CFG_MASK)
            or (w & CTRL_OPCODE_MASK) == (first & CTRL_OPCODE_MASK)
            or (w & CTRL_SWAP_MASK) == (first & CTRL_SWAP_MASK)
        ]
        rb_line = (
            f"first_control=0x{first:08x} later_starts={len(conts)} "
            f"control_written/read={','.join(f'0x{w:08x}/0x{r:08x}' for w, r in conts) or '-'}"
        )
        self._check_dv_pre_go("CHK-DMA-CONT-CFG", dv, tag)
        if not conts or rb_bad:
            self._ctrl_missing(
                "CHK-DMA-CONT-CFG",
                f"{tag} later start not carrying a changed OPCODE and DIGEST_SWAP: "
                f"bad={','.join(rb_bad) or '-'} {rb_line}",
            )

        exp = self._cont_golden(c)
        mism = sum(1 for g, e in zip(words, exp) if g != e) + abs(len(words) - len(exp))
        fer = field_compare(err, 0, ERROR_CODE_MASK)
        if mism:
            self.logger.error(
                "LEGD_CONT %s digest got=%s exp=%s",
                tag,
                [f"{w:08x}" for w in words],
                [f"{w:08x}" for w in exp],
            )
        ok = (
            mism == 0
            and done == 1
            and st2.error == 0
            and fer.ok
            and valid_after == 1
            and dv.ok
            and copy_mm == 0
            and go_writes == k
            and stops == k - 1
        )
        self._pass(
            "CHK-DMA-CONT-CFG",
            ok,
            f"{tag} words={len(exp)} mismatch={mism} done={done} error={st2.error} "
            f"digest_valid_after={valid_after} {dv.fmt()} copy_mismatch={copy_mm} "
            f"go_writes={go_writes} expect_go={k} chunk_stops={stops} expect_stops={k - 1} "
            f"chunk_rb={chunk_rb} expect_chunk={length // k} "
            f"stale_eq_golden=0 {rb_line} {ff('error_code', fer)}",
        )
        await self._digest_ro_hold(tag)
        self._close()
        return dv.fall_graded

    async def _chunk_done_rw1c(self, tag: str, stop: int) -> None:
        """CHK-DMA-RW1C at a continuation stop (CHUNK_DONE=1, BUSY=0, DONE=0).

        STATUS.CHUNK_DONE is RW1C (``secure_dma.adoc`` STATUS; "Status completion
        and error bits are write-one-to-clear", ``hw/sys/sep/doc/dma.adoc:131-132``):
        a write of 0 leaves it 1 and a write of 1 clears it. No GO is written
        between the writes, so no chunk start clears it.
        """
        ops = self.ops
        await ops.wr(STATUS, 0)
        st0 = await ops.read_status()
        await ops.wr(STATUS, ST_CHUNK_DONE)
        st1 = await ops.read_status()
        line = (
            f"bit=CHUNK_DONE stop={stop} after_w0={st0.chunk_done} expect_after_w0=1 "
            f"after_w1={st1.chunk_done} expect_after_w1=0 busy={st0.busy}/{st1.busy} "
            f"done={st0.done}/{st1.done} {tag}"
        )
        if st0.busy or st1.busy or st0.done or st1.done:
            self._ctrl_missing("CHK-DMA-RW1C", f"stop left: {line}")
        self._pass("CHK-DMA-RW1C", st0.chunk_done == 1 and st1.chunk_done == 0, line)

    async def _digest_ro_hold(self, tag: str) -> None:
        """CHK-DMA-RO-HOLD: each SHA2_DIGEST word keeps value v after a write of ~v.

        SHA2_DIGEST_0[16] is ``sw = r`` (``secure_dma.adoc`` SHA2_DIGEST_0). No
        text states the response of a write to it, so the response is logged.
        """
        ops = self.ops
        before = await ops.read_digest(DIGEST_WORDS)
        resps = []
        for i, v in enumerate(before):
            seq = await ops.access(SepAxiOp.WRITE, DIGEST_BASE + 4 * i, ~v & M32, ungraded=True)
            resps.append(str(seq.resp_code))
        after = await ops.read_digest(DIGEST_WORDS)
        changed = [
            f"{i}:0x{a:08x}/0x{b:08x}" for i, (a, b) in enumerate(zip(after, before)) if a != b
        ]
        self._pass(
            "CHK-DMA-RO-HOLD",
            not changed,
            f"reg=SHA2_DIGEST_0[0..{DIGEST_WORDS - 1}] written=complement changed="
            f"{','.join(changed) or '-'} word0=0x{before[0]:08x} write_resp={rle(resps)} {tag}",
        )

    async def _leg_d_cont(self, plan: Plan) -> None:
        falls_graded = 0
        for c in plan.conts:
            falls_graded += await self._cont_run(c)
        self._dv_fall_reach("CHK-DMA-CONT-CFG", falls_graded, len(plan.conts))

    # ---- alias form -------------------------------------------------------
    async def _alias_runs(self, plan: Plan) -> None:
        """CHK-DMA-ALIAS-FORM: alias-form copies at widths 1, 2, 4 and an alias-source hash.

        Expected values are those of the same transfer in the direct form: beat
        addresses, WSTRB and image from ``env/sep_dma_model.DmaXfer``, the digest
        from hashlib.
        """
        ops = self.ops
        base = await ops.rd(LOCAL_BASE_REG)
        line = f"sep_local_base=0x{base:08x} expect=0x{LOCAL_ALIAS & M32:08x}"
        if base != LOCAL_ALIAS & M32:
            self._ctrl_missing("CHK-DMA-ALIAS-FORM", line)
        self.logger.info("CTRL-DMA-ALIAS-BASE seen seed=%d %s", self.seed, line)
        for cd, side in plan.alias_cells:
            x = cd.copy.x
            src = alias_of(x.src_base) if side in ("src", "both") else None
            dst = alias_of(x.dst_base) if side in ("dst", "both") else None
            meas = await self._cell_measure(
                cd, src=src, dst=dst, tag_extra=f" form=alias side={side}"
            )
            ev = meas["rec"].ev
            addr_mm, strb_mm, _ = self._beat_mm(x, ev)
            ok = (
                meas["mism"] == 0
                and meas["guard_ok"]
                and meas["src_ok"]
                and meas["fst"].ok
                and meas["fer"].ok
                and addr_mm == 0
                and strb_mm == 0
            )
            self._pass(
                "CHK-DMA-ALIAS-FORM",
                ok,
                f"kind=copy side={side} cell={cell_name(cd.cell)} enc={cd.enc} n={cd.n} "
                f"chunk={cd.chunk} prog_src=0x{(x.src_base if src is None else src):08x} "
                f"prog_dst=0x{(x.dst_base if dst is None else dst):08x} "
                f"mem_mismatch={meas['mism']} guard_ok={meas['guard_ok']} "
                f"addr_mismatch={addr_mm} strb_mismatch={strb_mm} ar={len(ev.ar)} "
                f"aw={len(ev.aw)} expect_beats={x.n_txn} {ff('status', meas['fst'])} "
                f"{ff('error_code', meas['fer'])}",
            )
            await self._cell_grade(cd, meas)
        m = plan.alias_msg
        swap = m.swaps[0]
        length = len(m.msg)
        gold = golden_words(m.alg, m.msg, swap)
        await self.mem.fill(
            m.src, [int.from_bytes(m.msg[i : i + 4], "little") for i in range(0, length, 4)]
        )
        stale = await ops.read_digest(len(gold))
        if stale == gold:
            self._ctrl_missing("CHK-DMA-ALIAS-FORM", f"alg={m.alg} digest before GO equals golden")
        dst = alias_of(m.dst) if plan.alias_dst else m.dst
        words, info = await self._hash_run(
            m, m.split, swap, 2, {}, graded=True, src=alias_of(m.src), dst=dst
        )
        mism = sum(1 for g, e in zip(words, gold) if g != e) + abs(len(words) - len(gold))
        fer = field_compare(info["err"], 0, ERROR_CODE_MASK)
        self._pass(
            "CHK-DMA-ALIAS-FORM",
            mism == 0
            and info["copy_mm"] == 0
            and info["done"] == 1
            and info["error"] == 0
            and fer.ok,
            f"kind=sha alg={m.alg} len={length} split={m.split} swap={swap} "
            f"prog_src=0x{alias_of(m.src):08x} prog_dst=0x{dst:08x} words={len(gold)} "
            f"mismatch={mism} copy_mismatch={info['copy_mm']} done={info['done']} "
            f"{ff('error_code', fer)}",
        )
        self._close()
        self.logger.info(
            "INFO-DMA-ALIAS-REACH seed=%d copies=%d sha=1 fixed_chunk_form=%s",
            self.seed,
            len(plan.alias_cells),
            plan.fixed_form,
        )

    # ---- one-byte chunks ----------------------------------------------------
    async def _chunk1(self, plan: Plan) -> None:
        """CHK-DMA-CHUNK1: width 1, CHUNK_DATA_SIZE 1 (the stated minimum).

        One chunk per byte: the image, the AR/AW/W counts, addresses and WSTRB
        equal the model, n-1 to n CHUNK_DONE rises and n-1 stop reads, one GO
        per chunk.
        """
        cd = plan.chunk1
        x = cd.copy.x
        meas = await self._cell_measure(cd, tag_extra=" chunk=1")
        ev, res = meas["rec"].ev, meas["res"]
        addr_mm, strb_mm, _ = self._beat_mm(x, ev)
        rises = len(ev.rises("chunk_done"))
        stops = sum(1 for s in res.statuses if s.chunk_done and not s.busy and not s.done)
        n = x.n_chunks
        ok = (
            meas["mism"] == 0
            and meas["guard_ok"]
            and meas["src_ok"]
            and meas["fst"].ok
            and meas["fer"].ok
            and addr_mm == 0
            and strb_mm == 0
            and n - 1 <= rises <= n
            and stops == n - 1
            and res.go_writes == n
        )
        self._pass(
            "CHK-DMA-CHUNK1",
            ok,
            f"cell={cell_name(cd.cell)} bytes={x.total} chunks={n} mem_mismatch={meas['mism']} "
            f"guard_ok={meas['guard_ok']} addr_mismatch={addr_mm} strb_mismatch={strb_mm} "
            f"ar={len(ev.ar)} aw={len(ev.aw)} w={len(ev.w)} expect_beats={x.n_txn} "
            f"chunk_done_rises={rises} stop_reads={stops} go_writes={res.go_writes} "
            f"{ff('status', meas['fst'])} {ff('error_code', meas['fer'])}",
        )
        await self._cell_grade(cd, meas)

    # ---- INITIAL_TRANSFER without GO ------------------------------------------
    async def _nogo(self, plan: Plan) -> None:
        """CHK-DMA-NOGO: CONTROL with INITIAL_TRANSFER=1 and GO=0 starts nothing.

        "A start is a write of CONTROL.GO while STATUS.BUSY is clear"
        (``hw/sys/sep/doc/dma.adoc:79-80``). Over BUSY_RISE_BOUND clocks after
        the write: no AR or AW on the DMA master, no BUSY rise, and a STATUS read
        with BUSY=0 and DONE as before. Control CTRL-DMA-NOGO-GO: the GO=1
        write that follows raises BUSY within the same bound and moves the copy.
        """
        ops = self.ops
        c, x = plan.nogo, plan.nogo.x
        await self._fill_copy(c)
        await self._program(c)
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        pre = await ops.read_status()
        self._open()
        m_tap, m_busy = self.tap.mark(), self.busy.mark()
        await ops.wr(CONTROL, control_word(opcode=OP_COPY, initial=1, go=0))
        await ClockCycles(cocotb.top.clk_i, BUSY_RISE_BOUND)
        ev = self.tap.since(m_tap)
        st = await ops.read_status()
        probe_rises = self.busy.rises_since(m_busy)
        ctl = await ops.rd(CONTROL)
        init_mask = control_word(initial=1)
        wr_line = (
            f"control=0x{ctl:08x} initial_transfer={int(bool(ctl & init_mask))} "
            f"go={int(bool(ctl & GO_MASK))}"
        )
        if ctl & (init_mask | GO_MASK) != init_mask:
            self._ctrl_missing("CHK-DMA-NOGO", f"INITIAL_TRANSFER=1 GO=0 write: {wr_line}")
        self.logger.info("CTRL-DMA-NOGO-WR PASS seed=%d %s", self.seed, wr_line)
        nogo = (
            f"ar={len(ev.ar)} aw={len(ev.aw)} tap_busy_rises={len(ev.rises('busy'))} "
            f"probe_busy_rises={probe_rises} busy={st.busy} done_before={pre.done} "
            f"done_after={st.done} window_clks={BUSY_RISE_BOUND}"
        )
        m_tap, m_busy = self.tap.mark(), self.busy.mark()
        await ops.go(opcode=OP_COPY, initial=1)
        try:
            rise = await self.busy.wait_rise(m_busy, BUSY_RISE_BOUND)
        except BitWatchTimeout:
            self._ctrl_missing("CHK-DMA-NOGO", f"GO=1 raised no BUSY: {nogo}")
        res = await ops.run_to_done(
            poll_size(x.total), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=" nogo-go"
        )
        if res.status.done:
            await self._wait_idle_done("nogo-go")
        ev_go = self.tap.since(m_tap)
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        exp = c.expected_dst()
        mism = sum(1 for g, e in zip(got, exp) if g != e)
        ctrl = (
            f"go_to_busy_clks={rise - m_busy.clk} ar={len(ev_go.ar)} aw={len(ev_go.aw)} "
            f"expect={x.n_txn} mem_mismatch={mism} done={res.status.done}"
        )
        if not (
            rise - m_busy.clk < BUSY_RISE_BOUND
            and len(ev_go.ar) == x.n_txn
            and len(ev_go.aw) == x.n_txn
            and mism == 0
            and res.status.done
        ):
            self._ctrl_missing("CHK-DMA-NOGO", ctrl)
        self.logger.info("CTRL-DMA-NOGO-GO PASS seed=%d %s", self.seed, ctrl)
        self._pass(
            "CHK-DMA-NOGO",
            not ev.ar
            and not ev.aw
            and not ev.rises("busy")
            and probe_rises == 0
            and st.busy == 0
            and st.done == pre.done,
            f"contract=hw/sys/sep/doc/dma.adoc:79-80 bytes={x.total} {nogo}",
        )
        self._close()
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)

    # ---- range and internal copies --------------------------------------------
    async def _set_range(self, base: int, limit: int, tag: str) -> None:
        """Program BASE, LIMIT and RANGE_VALID=1 and read them back (else CTRL-MISSING)."""
        ops = self.ops
        await ops.program_range(base, limit, valid=True)
        got = (
            await ops.rd(RANGE_BASE) & RANGE_BASE_MASK,
            await ops.rd(RANGE_LIMIT) & RANGE_LIMIT_MASK,
            await ops.rd(RANGE_VALID) & RANGE_VALID_MASK,
        )
        want = (base & RANGE_BASE_MASK, limit & RANGE_LIMIT_MASK, RANGE_VALID_MASK)
        if got != want:
            self._ctrl_missing(
                "RANGE-SET",
                f"{tag} base/limit/valid read 0x{got[0]:08x}/0x{got[1]:08x}/{got[2]} "
                f"expect 0x{want[0]:08x}/0x{want[1]:08x}/{want[2]}",
            )

    async def _range_copy(self, plan: Plan) -> None:
        """CHK-DMA-RANGE-COPY: an SRAM copy whose destination leaves the range completes.

        "The range does not bound a copy between internal addresses"
        (``hw/sys/sep/doc/dma.adoc:106``): DONE=1, ERROR=0, ERROR_CODE=0, every
        AR and AW of the model, and the image equals the model. Control
        CTRL-DMA-RANGE-COPY: under the same range a zero fill of the same
        destination stops at LIMIT with ERROR and ERROR_CODE.DST_ADDR_ERROR and
        keeps the words before it (``dma.adoc:98-104``), so the range is in force.
        """
        ops = self.ops
        c, x = plan.range_copy, plan.range_copy.x
        limit = plan.range_limit
        tag = f"src=0x{x.src_base:08x} dst=0x{x.dst_base:08x} bytes={x.total} limit=0x{limit:08x}"
        sw = sentinel_word(c.sentinel)
        await self._fill_copy(c)
        await self._set_range(x.src_base, limit, tag)
        await ops.program_transfer(src=0, dst=x.dst_base, total=x.total, chunk=x.total)
        await ops.go(opcode=OP_ZERO, initial=1)
        # A STATUS write while ERROR=1 also clears ERROR_CODE: it is read first.
        zst = await ops.poll_status(
            lambda s: bool(s.done or s.error),
            ops.done_bound(poll_size(x.total)),
            f"zero fill end {tag}",
        )
        zerr = await ops.rd(ERROR_CODE)
        zimg = await self.mem.read(x.dst_base, x.total // 4)
        in_words = (limit + 1 - x.dst_base) // 4
        zero_ok = all(w == 0 for w in zimg[:in_words]) and all(w == sw for w in zimg[in_words:])
        ctrl = (
            f"zero_error={zst.error} zero_error_code=0x{zerr:x} words_in_range={in_words} "
            f"zero_image_ok={int(zero_ok)}"
        )
        if not (zst.error and zerr & DST_ADDR_ERROR and zero_ok):
            self._ctrl_missing("CHK-DMA-RANGE-COPY", f"{ctrl} {tag}")
        self.logger.info("CTRL-DMA-RANGE-COPY PASS seed=%d %s %s", self.seed, ctrl, tag)
        await self._clear_error(tag)
        await self.mem.fill(c.dst_region, [sw] * c.dst_region_words)
        self._open()
        m_tap = self.tap.mark()
        await self._program(c)
        await ops.go(opcode=OP_COPY, initial=1)
        res = await ops.run_to_done(
            poll_size(x.total), busy=self.busy, busy_bound=BUSY_RISE_BOUND, tag=" range-copy"
        )
        if res.status.done:
            await self._wait_idle_done("range-copy")
        ev = self.tap.since(m_tap)
        st, err, _ = await self._read_regs()
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        mism = sum(1 for g, e in zip(got, c.expected_dst()) if g != e)
        addr_mm, _, _ = self._beat_mm(x, ev)
        past = sum(1 for b in ev.aw if b.addr is not None and b.addr > limit)
        fst = field_compare(st.raw, ST_DONE, ST_DONE | ST_BUSY | ST_ERROR)
        fer = field_compare(err, 0, ERROR_CODE_MASK)
        self._pass(
            "CHK-DMA-RANGE-COPY",
            fst.ok and fer.ok and mism == 0 and addr_mm == 0 and past > 0,
            f"contract=hw/sys/sep/doc/dma.adoc:106 {tag} ar={len(ev.ar)} aw={len(ev.aw)} "
            f"expect_beats={x.n_txn} aw_past_limit={past} addr_mismatch={addr_mm} "
            f"mem_mismatch={mism} {ff('status', fst)} {ff('error_code', fer)}",
        )
        self._close()
        await ops.wr(STATUS, ST_DONE | ST_CHUNK_DONE)
        await self._set_range(SRAM_BASE, SRAM_LIMIT, "restore")

    # ---- narrow-width and large copies -----------------------------------------
    async def _narrow_copies(self, plan: Plan) -> None:
        """Width 0 and width 1 copies above 1 KB, graded as CHK-DMA-GEOM with the window closed."""
        ops = self.ops
        for c in plan.narrow:
            x = c.x
            lead = f"leg=N width_enc={x.width_enc} "
            tag = f"{lead}total={x.total} chunk={x.chunk}"
            await self._fill_copy(c)
            await self._program(c)
            await ops.wr(STATUS, ST_CHUNK_DONE)
            m_busy = self.busy.mark()
            await ops.go(opcode=OP_COPY, initial=1)
            # The poll bound scales with the transaction count, as in Leg A.
            _, go_writes, reads, _, _ = await self._poll_b(4 * x.n_txn, m_busy, False, tag)
            self.logger.info(
                "LEGN %s go_writes=%d reads=%s",
                tag,
                go_writes,
                rle([f"b{s.busy}d{s.done}c{s.chunk_done}p{p}" for s, p in reads]),
            )
            st, err, ctl = await self._read_regs()
            await self._grade_geom(c, st, err, ctl, go_writes, "-", lead)

    async def _obs_size_large(self, plan: Plan) -> None:
        """A width-2 COPY above 16 KB; no text states the maximum TOTAL_DATA_SIZE."""
        ops = self.ops
        c, x = plan.large, plan.large.x
        # The narrow-width copies leave DONE=1; _logged_run ends on the first DONE=1 read.
        await ops.clean_state()
        await self._fill_copy(c)
        await self._program(c)
        m_tap = self.tap.mark()
        st, go_clks, ended = await self._logged_run(x.total, x.n_chunks + 1, "size-large")
        ev = self.tap.since(m_tap)
        err = await ops.rd(ERROR_CODE)
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        exp = c.expected_dst()
        mism = sum(1 for g, e in zip(got[1:-1], exp[1:-1]) if g != e)
        sw = sentinel_word(c.sentinel)
        self.logger.info(
            "OBS-DMA-SIZE-LARGE seed=%d total=%d chunk=%d n=%d width_enc=%d ended=%s "
            "go_writes=%d %s error_code=0x%x aw=%d w=%d expect_txn=%d dst_mismatch_words=%d "
            "guard_ok=%d",
            self.seed,
            x.total,
            x.chunk,
            x.n_chunks,
            x.width_enc,
            ended,
            len(go_clks),
            st.fmt(),
            err,
            len(ev.aw),
            len(ev.w),
            x.n_txn,
            mism,
            int(got[0] == sw and got[-1] == sw),
        )
        await ops.clean_state()

    # ---- logged runs (open questions) -----------------------------------------
    async def _logged_run(
        self, n_bytes: int, go_cap: int, tag: str
    ) -> tuple[DmaStatus, list[int], str]:
        """A COPY with the re-GO rule, capped at ``go_cap`` GO writes; nothing graded.

        Returns the last STATUS, the tap clock of each GO write and how the run
        ended (done, error, go_cap, bound). A run that has not ended is aborted
        and must reach BUSY=0 within ABORT_POLL_BOUND reads.
        """
        ops = self.ops
        go_clks = [self.tap.clk]
        await ops.go(opcode=OP_COPY, initial=1)
        ended = "bound"
        st = None
        for _ in range(ops.done_bound(poll_size(n_bytes))):
            st = await ops.read_status()
            if st.done and not st.busy:
                ended = "done"
                break
            if st.error or st.aborted:
                ended = "error"
                break
            if st.chunk_done and not st.busy:
                if len(go_clks) >= go_cap:
                    ended = "go_cap"
                    break
                m = self.busy.mark()
                go_clks.append(self.tap.clk)
                await ops.wr(CONTROL, (ops.last_control & ~control_word(initial=1)) | GO_MASK)
                try:
                    await self.busy.wait_rise(m, BUSY_RISE_BOUND)
                except BitWatchTimeout:
                    self.logger.info("LOGGED %s no BUSY rise after GO %d", tag, len(go_clks))
        if ended in ("bound", "go_cap"):
            await ops.abort()
            st = await ops.poll_status(
                lambda s: not s.busy, ABORT_POLL_BOUND, f"BUSY=0 after ABORT {tag}"
            )
        return st, go_clks, ended

    async def _obs_chunk1_w4(self, plan: Plan) -> None:
        """Width 4 with CHUNK_DATA_SIZE 1, total 8 (no text relates the two)."""
        ops = self.ops
        src, dst, s, words = plan.chunk1_w4
        await self.mem.fill(src, words)
        await self.mem.fill(dst, [sentinel_word(s)] * 2)
        await ops.program_transfer(src=src, dst=dst, total=8, chunk=1, width_enc=2)
        m_tap = self.tap.mark()
        st, go_clks, ended = await self._logged_run(8, 9, "chunk1-w4")
        ev = self.tap.since(m_tap)
        err = await ops.rd(ERROR_CODE)
        got = await self.mem.read(dst, 2)
        self.logger.info(
            "OBS-DMA-CHUNK1-W4 seed=%d ended=%s %s error_code=0x%x ar=%d aw=%d w=%d wstrb=%s "
            "go_writes=%d dst=%s src=%s",
            self.seed,
            ended,
            st.fmt(),
            err,
            len(ev.ar),
            len(ev.aw),
            len(ev.w),
            rle([f"0x{b.strb:02x}" if b.strb is not None else "X" for b in ev.w]) or "-",
            len(go_clks),
            ",".join(f"0x{w:08x}" for w in got),
            ",".join(f"0x{w:08x}" for w in words),
        )
        await ops.clean_state()

    async def _obs_baselim_copy(self, plan: Plan) -> None:
        """A 16-byte SRAM copy with ENABLED_MEMORY_RANGE_BASE = LIMIT inside the source."""
        ops = self.ops
        c, x = plan.baselim, plan.baselim.x
        word = plan.baselim_word
        await self._fill_copy(c)
        await self._set_range(word, word, "baselim")
        await self._program(c)
        m_tap = self.tap.mark()
        st, go_clks, ended = await self._logged_run(x.total, 1, "baselim")
        ev = self.tap.since(m_tap)
        err = await ops.rd(ERROR_CODE)
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        self.logger.info(
            "OBS-DMA-BASELIM-COPY seed=%d base=limit=0x%08x ended=%s %s error_code=0x%x "
            "ar=%d aw=%d expect_beats=%d dst_eq_model=%d dst=%s",
            self.seed,
            word,
            ended,
            st.fmt(),
            err,
            len(ev.ar),
            len(ev.aw),
            x.n_txn,
            int(got == c.expected_dst()),
            ",".join(f"0x{w:08x}" for w in got),
        )
        await ops.clean_state()
        await self._set_range(SRAM_BASE, SRAM_LIMIT, "restore")

    async def _obs_short_last_chunk(self, plan: Plan) -> None:
        """A firmware-paced COPY whose TOTAL_DATA_SIZE is not a multiple of CHUNK_DATA_SIZE."""
        ops = self.ops
        c, x = plan.short, plan.short.x
        await self._fill_copy(c)
        await self._program(c)
        m_tap = self.tap.mark()
        st, go_clks, ended = await self._logged_run(x.total, x.n_chunks + 2, "short-last")
        ev = self.tap.since(m_tap)
        ctl = await ops.rd(CONTROL)
        got = await self.mem.read(c.dst_region, c.dst_region_words)
        # W beats of chunk i lie between GO write i and GO write i + 1.
        ends = go_clks[1:] + [ev.last_beat_clk() or go_clks[-1]]
        per_chunk = []
        last: list = []
        for i, (c0, c1) in enumerate(zip(go_clks, ends)):
            last = [b for b in ev.w if c0 <= b.clk and (b.clk < c1 or i == len(go_clks) - 1)]
            strbs = rle([f"0x{b.strb:02x}" if b.strb is not None else "X" for b in last])
            per_chunk.append(f"{i}:{len(last)}/{strbs or '-'}")
        last_bytes = sum(bin(b.strb).count("1") for b in last if b.strb is not None)
        self.logger.info(
            "OBS-DMA-SHORT-LAST-CHUNK seed=%d total=%d chunk=%d tail=%d ended=%s go_writes=%d "
            "w_per_chunk=%s last_chunk_bytes=%d %s control_go=%d dst_eq_model=%d",
            self.seed,
            x.total,
            x.chunk,
            x.total % x.chunk,
            ended,
            len(go_clks),
            ",".join(per_chunk),
            last_bytes,
            st.fmt(),
            int(bool(ctl & GO_MASK)),
            int(got == c.expected_dst()),
        )
        await ops.clean_state()

    # ---- 64-bit register access from m_axi ------------------------------------
    async def _drive_strb(self, strb: int, seen: dict) -> None:
        """Drive ``m_axi_wstrb`` to ``strb`` at each falling edge while WVALID is high.

        Returns after the falling edge whose read-only phase shows WVALID and
        WREADY high, so the W handshake on the next rising edge takes ``strb``;
        ``seen`` then holds that strobe. Bounded by STRB_FOLLOW_BOUND clocks.
        """
        top = cocotb.top
        for _ in range(STRB_FOLLOW_BOUND):
            await FallingEdge(top.clk_i)
            if self.rd(top.m_axi_wvalid, allow_unknown=True) != 1:
                continue
            top.m_axi_wstrb.value = strb
            await ReadOnly()
            if self.rd(top.m_axi_wready, allow_unknown=True) == 1:
                seen["wstrb"] = self.rd(top.m_axi_wstrb)
                return

    async def _obs_csr64(self, plan: Plan) -> None:
        """64-bit m_axi read, full-strobe write and half-strobe write of a DMA register pair."""
        ops = self.ops
        (lo_name, hi_name), full, half, strb = plan.csr64
        lo, hi = SECURE_DMA.addr(lo_name), SECURE_DMA.addr(hi_name)
        pre = (await ops.rd(lo), await ops.rd(hi))
        mon = self.env.ext_axi_monitor

        def acc(op: SepAxiOp, data: int = 0) -> SepAxiAccessSeq:
            return SepAxiAccessSeq(
                f"dma_csr64_{op.value}_0x{lo:08x}",
                op=op,
                addr=lo,
                wdata=data,
                length=8,
                size=3,
                allow_unverified_write_resp=op is SepAxiOp.WRITE,
                allow_ungraded_read_resp=op is SepAxiOp.READ,
            )

        rseq = acc(SepAxiOp.READ)
        mon.open_error_rdata_window()
        try:
            await self.start_ext_seq(rseq)
        finally:
            mon.close_error_rdata_window()
        wseq = acc(SepAxiOp.WRITE, full)
        await self.start_ext_seq(wseq)
        after_full = (await ops.rd(lo), await ops.rd(hi))
        seen: dict = {}
        drive = cocotb.start_soon(self._drive_strb(strb, seen))
        hseq = acc(SepAxiOp.WRITE, half)
        await self.start_ext_seq(hseq)
        await drive
        after_half = (await ops.rd(lo), await ops.rd(hi))
        await ops.wr(lo, pre[0])
        await ops.wr(hi, pre[1])
        restored = (await ops.rd(lo), await ops.rd(hi))
        line = (
            f"pair={lo_name}/{hi_name} read_resp={rseq.resp_code} read_ok={int(rseq.resp_ok)} "
            f"rdata=0x{int(rseq.rdata):016x} pre=0x{pre[1]:08x}_{pre[0]:08x} "
            f"full_wdata=0x{full:016x} full_bresp={wseq.resp_code} "
            f"after_full=0x{after_full[1]:08x}_{after_full[0]:08x} half_wdata=0x{half:016x} "
            f"half_strb=0x{strb:02x} half_bresp={hseq.resp_code} "
            f"after_half=0x{after_half[1]:08x}_{after_half[0]:08x}"
        )
        if seen.get("wstrb") != strb:
            self._ctrl_missing("OBS-DMA-CSR-64", f"strobe not on the bus seen={seen} {line}")
        if restored != pre:
            self._ctrl_missing(
                "OBS-DMA-CSR-64", f"restore read 0x{restored[1]:08x}_{restored[0]:08x}"
            )
        self.logger.info("OBS-DMA-CSR-64 seed=%d %s", self.seed, line)

    # ---- held outbound response -------------------------------------------------
    async def _obs_beat_hold(self, plan: Plan) -> None:
        """A DMA read from the outbound window while the responder holds its R response.

        ``smn_outbound_resp_hold_i`` holds the response for HOLD_CLKS clocks;
        the line logs STATUS and ERROR_CODE at the bound, and STATUS, ERROR_CODE
        and DMA_BUS_ERR_STATUS after the release. No text states a timeout of a
        DMA beat. Inside the hold only DMA CSR accesses run: DMA_BUS_ERR_STATUS
        shares the peripheral demux with the held read, so a read of it waits for
        the release.
        """
        ops = self.ops
        dut = cocotb.top
        src, dst, s = plan.hold
        await SepFilterBank(self, "out").program_pair(OUT_PAIR, OUT_WIN_LO, OUT_WIN_HI)
        await self._set_range(0, M32, "hold")
        await self.mem.fill(dst, [sentinel_word(s)] * 2)
        await ops.program_transfer(src=src, dst=dst, total=8, chunk=8, width_enc=2)
        m_tap = self.tap.mark()
        dut.smn_outbound_resp_hold_i.value = 1
        try:
            await ops.go(opcode=OP_COPY, initial=1)
            await ClockCycles(dut.clk_i, HOLD_CLKS)
            ev = self.tap.since(m_tap)
            st_hold = await ops.read_status()
            err_hold = await ops.rd(ERROR_CODE)
        finally:
            dut.smn_outbound_resp_hold_i.value = 0
        st = await ops.poll_status(
            lambda x: bool((x.done or x.error or x.aborted) and not x.busy),
            ops.done_bound(poll_size(8)),
            "end after the hold release",
        )
        ev_end = self.tap.since(m_tap)
        err = await ops.rd(ERROR_CODE)
        bus = await ops.rd(DMA_BUS_ERR_STATUS)
        got = await self.mem.read(dst, 2)
        self.logger.info(
            "OBS-DMA-BEAT-HOLD seed=%d hold_clks=%d src=0x%08x at_bound: ar=%d aw=%d b=%d "
            "busy=%d error=%d done=%d error_code=0x%x after_release: "
            "ar=%d aw=%d b=%d %s error_code=0x%x dma_bus_err_status=0x%x dst=%s",
            self.seed,
            HOLD_CLKS,
            src,
            len(ev.ar),
            len(ev.aw),
            len(ev.b),
            st_hold.busy,
            st_hold.error,
            st_hold.done,
            err_hold,
            len(ev_end.ar),
            len(ev_end.aw),
            len(ev_end.b),
            st.fmt(),
            err,
            bus,
            ",".join(f"0x{w:08x}" for w in got),
        )
        await ops.clean_state()
        await self._set_range(SRAM_BASE, SRAM_LIMIT, "restore")
