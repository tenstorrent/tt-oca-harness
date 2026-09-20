# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Field walk over the Secure DMA CSR block, then transfers at each width.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `reg_req_i`, `axi32_slv_req`, `axi32_slv_req_offset`,
`dma_req_o` and `dma_axi_req_raw` in `hw/sys/sep/rtl/sep_dma_wrap.sv`. The
register path carries one value per field today, and the DMA's own master
never issues a wide or multi-beat command.

Stimulus, in two parts.

First a pattern walk -- 0xFFFF_FFFF, 0x5555_5555, 0xAAAA_AAAA, 0x0000_0000 --
through every R/W configuration word of the block at
`SECURE_DMA_REG_MAP_BASE_ADDR`: SRC_ADDR_LO/HI, DST_ADDR_LO/HI,
ADDR_SPACE_ID, ENABLED_MEMORY_RANGE_BASE/LIMIT, TOTAL_DATA_SIZE,
CHUNK_DATA_SIZE, TRANSFER_WIDTH, SRC_CONFIG and DST_CONFIG. CONTROL is not in
the walk: its GO bit would start a transfer from walk data. RANGE_REGWEN and
CFG_REGWEN are not in the walk either: RANGE_REGWEN is one-way until reset and
would lock the range registers out of the transfers below.

Then SRAM-to-SRAM copies at each legal TRANSFER_WIDTH, and one copy whose
chunk size is smaller than the total so the DMA master issues more than one
command. The programming order and the CONTROL word follow
`dv/fw/tests/dma_basic_test/dma_basic_test.c`, which drives the same block
from EL2 firmware. STATUS is polled with a bound and its value is logged, not
graded: this leaf does not claim a transfer completed or copied anything.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_stimulus_seq import WALK_PATTERNS, SepCovStim

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

WALK_REGS = (
    SRC_ADDR_LO,
    SRC_ADDR_HI,
    DST_ADDR_LO,
    DST_ADDR_HI,
    ADDR_SPACE_ID,
    RANGE_BASE,
    RANGE_LIMIT,
    TOTAL_DATA_SIZE,
    CHUNK_DATA_SIZE,
    TRANSFER_WIDTH,
    SRC_CONFIG,
    DST_CONFIG,
)

# CONTROL bit positions, from the generated SECURE_DMA_CONTROL bitfield
# (regs/gen/py/sep_reg.py): opcode[3:0], initial_transfer[8], go[31].
CONTROL_GO = 1 << 31
CONTROL_INITIAL = 1 << 8
OPCODE_COPY = 0

# STATUS bit positions from the same export: busy[0] done[1] aborted[2]
# error[3] sha2_digest_valid[4] chunk_done[5]. The RW1C set is done, error and
# chunk_done.
STATUS_DONE = 1 << 1
STATUS_ERROR = 1 << 3
STATUS_CHUNK_DONE = 1 << 5
STATUS_SETTLED = STATUS_DONE | STATUS_ERROR | STATUS_CHUNK_DONE

# ADDR_SPACE_ID reset value: the encoded OT address space on both source and
# destination, which is what an SRAM-to-SRAM copy uses.
ASID_RESET = 0x0000_0077

# Legal TRANSFER_WIDTH encodings: 1, 2 and 4 bytes per beat.
TRANSFER_WIDTHS = (0, 1, 2)

SRC_OFFSET = 0x0000
DST_OFFSET = 0x2000
COPY_BYTES = 0x100

# Bound on the STATUS poll. A 256-byte copy settles in far fewer CSR reads;
# the cap stops a DMA that never settles from consuming the run timeout on one
# poll loop.
POLL_READS = 200


@pyuvm.test()
class sep_cov_dma_csr_field_walk_test(sep_base_test):
    """Secure DMA CSR walk plus width and chunk sweeps. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        self.stim = SepCovStim(self)
        await self.stim.ungate_clocks()

        for addr in WALK_REGS:
            for pattern in WALK_PATTERNS:
                await self.stim._wr(addr, pattern)
        self.logger.info("DMA CSR pattern walk driven over %d registers", len(WALK_REGS))

        # Open the enabled-memory range over the SEP SRAM aperture and mark it
        # valid. RANGE_REGWEN keeps its reset value, so the range stays
        # writable for the rest of the run.
        await self.stim._wr(RANGE_BASE, SRAM_BASE)
        await self.stim._wr(RANGE_LIMIT, SRAM_BASE + SRAM_SIZE - 1)
        await self.stim._wr(RANGE_VALID, 1)

        for width in TRANSFER_WIDTHS:
            await self._transfer(width=width, total=COPY_BYTES, chunk=COPY_BYTES)

        # Chunk smaller than the total: the DMA master issues one command per
        # chunk instead of one for the whole transfer.
        await self._transfer(width=2, total=COPY_BYTES, chunk=COPY_BYTES // 4)

    async def _transfer(self, *, width: int, total: int, chunk: int) -> None:
        """Program and start one SRAM-to-SRAM copy, then poll STATUS."""
        await self.stim._wr(SRC_ADDR_LO, SRAM_BASE + SRC_OFFSET)
        await self.stim._wr(SRC_ADDR_HI, 0)
        await self.stim._wr(DST_ADDR_LO, SRAM_BASE + DST_OFFSET)
        await self.stim._wr(DST_ADDR_HI, 0)
        await self.stim._wr(ADDR_SPACE_ID, ASID_RESET)
        await self.stim._wr(TRANSFER_WIDTH, width)
        await self.stim._wr(TOTAL_DATA_SIZE, total)
        await self.stim._wr(CHUNK_DATA_SIZE, chunk)
        await self.stim._wr(SRC_CONFIG, 0)
        await self.stim._wr(DST_CONFIG, 0)
        await self.stim._wr(CONTROL, CONTROL_GO | CONTROL_INITIAL | OPCODE_COPY)

        status = 0
        for _ in range(POLL_READS):
            status = await self.stim._rd(STATUS)
            if status & STATUS_SETTLED:
                break
        self.logger.info(
            "DMA copy width=%d total=%d chunk=%d driven; STATUS=0x%08x (logged, not graded)",
            width,
            total,
            chunk,
            status,
        )
        # Clear the RW1C status bits so the next transfer starts from a clean
        # word. Writing bits that are already zero has no effect.
        await self.stim._wr(STATUS, STATUS_SETTLED)
