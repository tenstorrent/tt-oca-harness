# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure DMA inline-hash opcodes, sub-word tails, abort and the size/address errors.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target: `secure_dma` holds 48 uncovered lines in the merged VCS run
`build/runs/20260919_225443__vcs__all`. The suite only ever runs the copy
opcode at a word-aligned length, so the dark lines are the arms that need
something else:

* `vendor/lowRISC/opentitan/upstream/hw/ip/dma/rtl/secure_dma.sv:447` --
  `OpcSha512: sha2_mode = SHA2_512`, and the SHA-512 arm of the digest
  write-back at :1288-1290.
* :808-810 -- the `req_dst_be` cases for 1, 2 and 3 remaining bytes on the
  final beat of a 4-byte-wide transfer.
* :654-655 -- `ctrl_state_d = DmaIdle; clear_go = 1'b1` on a software abort.
* :827 and :837 -- `next_error[DmaSizeErr]`, raised by a zero transfer size and
  by an inline-hash opcode at a transfer width other than 4 bytes
  (:832-836 requires 4 bytes for hashing).
* :899-903 and :908-911 -- `next_error[DmaSrcAddrErr]` / `[DmaDstAddrErr]`
  from a non-zero address-high word in the internal address space.
* :1012-1013 -- `DmaShaWait -> DmaShaFinalize`, and the non-handshake arm of
  :1018-1020.

Stimulus, in four parts, all over the CSR block at
`SECURE_DMA_REG_MAP_BASE_ADDR`, programmed in the order
`tests/system/sep_cov_dma_csr_field_walk_test.py` established:

1. An SRAM-to-SRAM transfer at each inline-hash opcode (SHA-256, SHA-384,
   SHA-512), with `CONTROL.DIGEST_SWAP` driven both ways so the digest
   write-back runs through both endian conversions, and the SHA2_DIGEST words
   read out afterwards.
2. Copies whose total size is 1, 2 and 3 bytes past a word boundary, so the
   final beat carries a partial byte-enable.
3. A multi-chunk copy started and then aborted through `CONTROL.ABORT`.
4. Three programmings the design answers with its own error code -- a zero
   total size, an inline-hash opcode at a 1-byte transfer width, and a
   non-zero `SRC_ADDR_HI` / `DST_ADDR_HI` -- each followed by a read of
   `ERROR_CODE`. These stay inside the DMA: the error is reported in a status
   register, not as a bus response, so no access here is marked `allow_error`.

STATUS and ERROR_CODE are polled and logged for flow control. Nothing read is
compared against an expectation, and this leaf claims neither that a transfer
copied anything nor that a digest is correct.

Not driven here, and not a stimulus gap: the `DmaClearIntrSrc` and
`DmaWaitIntrSrcResponse` states at :686-745. They are entered only with
`cfg_handshake_en` and a raised `lsio_trigger`, and `hw/sys/sep/rtl/sep.sv:1084-1087`
ties every trigger lane off except the SPI-device one, which no register write
raises. `hw/sys/sep/rtl/sep_dma_wrap.sv:324-333` also holds the CTN response
channel's `d_valid` low permanently, so a clear routed to that bus would never
be answered.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import SepCovStim

SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")

SRC_ADDR_LO = sym("SECURE_DMA_SRC_ADDR_LO_REG_ADDR")
SRC_ADDR_HI = sym("SECURE_DMA_SRC_ADDR_HI_REG_ADDR")
DST_ADDR_LO = sym("SECURE_DMA_DST_ADDR_LO_REG_ADDR")
DST_ADDR_HI = sym("SECURE_DMA_DST_ADDR_HI_REG_ADDR")
ADDR_SPACE_ID = sym("SECURE_DMA_ADDR_SPACE_ID_REG_ADDR")
RANGE_BASE = sym("SECURE_DMA_ENABLED_MEMORY_RANGE_BASE_REG_ADDR")
RANGE_LIMIT = sym("SECURE_DMA_ENABLED_MEMORY_RANGE_LIMIT_REG_ADDR")
RANGE_VALID = sym("SECURE_DMA_RANGE_VALID_REG_ADDR")
TOTAL_DATA_SIZE = sym("SECURE_DMA_TOTAL_DATA_SIZE_REG_ADDR")
CHUNK_DATA_SIZE = sym("SECURE_DMA_CHUNK_DATA_SIZE_REG_ADDR")
TRANSFER_WIDTH = sym("SECURE_DMA_TRANSFER_WIDTH_REG_ADDR")
CONTROL = sym("SECURE_DMA_CONTROL_REG_ADDR")
SRC_CONFIG = sym("SECURE_DMA_SRC_CONFIG_REG_ADDR")
DST_CONFIG = sym("SECURE_DMA_DST_CONFIG_REG_ADDR")
STATUS = sym("SECURE_DMA_STATUS_REG_ADDR")
ERROR_CODE = sym("SECURE_DMA_ERROR_CODE_REG_ADDR")
SHA2_DIGEST_0 = sym("SECURE_DMA_SHA2_DIGEST_0_0__REG_ADDR")

# CONTROL bit positions, from the generated SECURE_DMA_CONTROL bitfield:
# opcode[3:0], hardware_handshake_enable[4], digest_swap[5],
# initial_transfer[8], abort[27], go[31].
CONTROL_GO = 1 << 31
CONTROL_ABORT = 1 << 27
CONTROL_INITIAL = 1 << 8
CONTROL_DIGEST_SWAP = 1 << 5

# Opcode encodings, vendor/lowRISC/opentitan/upstream/hw/ip/dma/rtl/secure_dma_pkg.sv:41-44.
OPCODE_COPY = 0x0
OPCODE_SHA256 = 0x1
OPCODE_SHA384 = 0x2
OPCODE_SHA512 = 0x3
HASH_OPCODES = ((OPCODE_SHA256, "sha256"), (OPCODE_SHA384, "sha384"), (OPCODE_SHA512, "sha512"))

# TRANSFER_WIDTH encodings, secure_dma_pkg.sv:25-27: 1, 2 and 4 bytes per beat.
WIDTH_1B = 0
WIDTH_4B = 2

# STATUS bit positions: busy[0] done[1] aborted[2] error[3]
# sha2_digest_valid[4] chunk_done[5]. The RW1C set is done, aborted, error and
# chunk_done.
STATUS_DONE = 1 << 1
STATUS_ABORTED = 1 << 2
STATUS_ERROR = 1 << 3
STATUS_CHUNK_DONE = 1 << 5
STATUS_SETTLED = STATUS_DONE | STATUS_ABORTED | STATUS_ERROR | STATUS_CHUNK_DONE

# ADDR_SPACE_ID reset value: OtInternalAddr (0x7) on both source and
# destination, which is what an SRAM-to-SRAM transfer uses.
ASID_RESET = 0x0000_0077

DIGEST_WORDS = 16

SRC_OFFSET = 0x0000
DST_OFFSET = 0x2000
COPY_BYTES = 0x100

# Sizes one, two and three bytes past a word boundary, so the last beat of a
# 4-byte-wide transfer carries a partial byte-enable.
TAIL_SIZES = (COPY_BYTES + 1, COPY_BYTES + 2, COPY_BYTES + 3)

# Bound on the STATUS poll. A 256-byte transfer settles in far fewer CSR
# reads; the cap keeps a transfer that never settles from spending the run
# timeout in one loop.
POLL_READS = 400


@pyuvm.test()
class sep_cov_dma_hash_and_tail_test(sep_base_test):
    """Secure DMA hash opcodes, partial tails, abort and error arms. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.stim = SepCovStim(self)
        await self.stim.ungate_clocks()

        # Open the enabled-memory range over the SEP SRAM aperture and mark it
        # valid. RANGE_REGWEN keeps its reset value, so the range stays
        # writable for the rest of the run.
        await self.stim._wr(RANGE_BASE, SRAM_BASE)
        await self.stim._wr(RANGE_LIMIT, SRAM_BASE + SRAM_SIZE - 1)
        await self.stim._wr(RANGE_VALID, 1)

        for opcode, label in HASH_OPCODES:
            for swap in (0, CONTROL_DIGEST_SWAP):
                await self._program(total=COPY_BYTES, chunk=COPY_BYTES, width=WIDTH_4B)
                await self._go(opcode | swap, f"{label} digest_swap={1 if swap else 0}")
                await self._read_digest(label)

        for total in TAIL_SIZES:
            await self._program(total=total, chunk=total, width=WIDTH_4B)
            await self._go(OPCODE_COPY, f"copy tail total={total}")

        await self._abort_run()

        # Programmings the DMA answers with its own error code. Each one is a
        # legal register write; the design reports the refusal in ERROR_CODE.
        await self._program(total=0, chunk=0, width=WIDTH_4B)
        await self._go(OPCODE_COPY, "zero total size")

        await self._program(total=COPY_BYTES, chunk=COPY_BYTES, width=WIDTH_1B)
        await self._go(OPCODE_SHA256, "inline hash at a 1-byte transfer width")

        await self._program(total=COPY_BYTES, chunk=COPY_BYTES, width=WIDTH_4B, src_hi=1)
        await self._go(OPCODE_COPY, "non-zero SRC_ADDR_HI")

        await self._program(total=COPY_BYTES, chunk=COPY_BYTES, width=WIDTH_4B, dst_hi=1)
        await self._go(OPCODE_COPY, "non-zero DST_ADDR_HI")

    async def _program(
        self, *, total: int, chunk: int, width: int, src_hi: int = 0, dst_hi: int = 0
    ) -> None:
        """Write every configuration register of one transfer, CONTROL last."""
        await self.stim._wr(SRC_ADDR_LO, SRAM_BASE + SRC_OFFSET)
        await self.stim._wr(SRC_ADDR_HI, src_hi)
        await self.stim._wr(DST_ADDR_LO, SRAM_BASE + DST_OFFSET)
        await self.stim._wr(DST_ADDR_HI, dst_hi)
        await self.stim._wr(ADDR_SPACE_ID, ASID_RESET)
        await self.stim._wr(TRANSFER_WIDTH, width)
        await self.stim._wr(TOTAL_DATA_SIZE, total)
        await self.stim._wr(CHUNK_DATA_SIZE, chunk)
        await self.stim._wr(SRC_CONFIG, 0)
        await self.stim._wr(DST_CONFIG, 0)

    async def _go(self, control_bits: int, label: str) -> int:
        """Start a transfer, poll STATUS with a bound, then clear the RW1C bits."""
        await self.stim._wr(CONTROL, CONTROL_GO | CONTROL_INITIAL | control_bits)
        status = 0
        for _ in range(POLL_READS):
            status = await self.stim._rd(STATUS)
            if status & STATUS_SETTLED:
                break
        err = await self.stim._rd(ERROR_CODE)
        self.logger.info(
            "cov stimulus: DMA %s driven; STATUS=0x%08x ERROR_CODE=0x%08x (logged, not graded)",
            label,
            status,
            err,
        )
        await self.stim._wr(STATUS, STATUS_SETTLED)
        return status

    async def _read_digest(self, label: str) -> None:
        """Read the SHA2_DIGEST window so its write-back is addressed."""
        words = [await self.stim._rd(SHA2_DIGEST_0 + 4 * i) for i in range(DIGEST_WORDS)]
        self.logger.info(
            "cov stimulus: DMA %s digest window read (first word 0x%08x), logged not graded",
            label,
            words[0],
        )

    async def _abort_run(self) -> None:
        """Start a multi-chunk copy and abort it from software."""
        await self._program(total=COPY_BYTES * 8, chunk=COPY_BYTES, width=WIDTH_4B)
        await self.stim._wr(CONTROL, CONTROL_GO | CONTROL_INITIAL | OPCODE_COPY)
        await self.stim._wr(CONTROL, CONTROL_ABORT)
        status = 0
        for _ in range(POLL_READS):
            status = await self.stim._rd(STATUS)
            if status & STATUS_SETTLED:
                break
        self.logger.info(
            "cov stimulus: DMA abort driven; STATUS=0x%08x (logged, not graded)", status
        )
        await self.stim._wr(STATUS, STATUS_SETTLED)
