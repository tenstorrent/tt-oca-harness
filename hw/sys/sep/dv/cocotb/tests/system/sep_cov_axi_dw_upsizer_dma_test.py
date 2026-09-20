# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA transfers, the only path that reaches the 32-to-64 upsizer."""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_4B, SepCovAxiStim

# Secure DMA CSRs. Addresses from hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv
# (OCH_SEP_TOP_SECURE_DMA_*_BASE_ADDR); field positions from
# hw/sys/sep/regs/gen/py/sep_reg.py.
DMA_SRC_ADDR_LO = 0x1080_0010
DMA_SRC_ADDR_HI = 0x1080_0014
DMA_DST_ADDR_LO = 0x1080_0018
DMA_DST_ADDR_HI = 0x1080_001C
DMA_RANGE_BASE = 0x1080_0024
DMA_RANGE_LIMIT = 0x1080_0028
DMA_RANGE_VALID = 0x1080_002C
DMA_TOTAL_DATA_SIZE = 0x1080_0038
DMA_CHUNK_DATA_SIZE = 0x1080_003C
DMA_TRANSFER_WIDTH = 0x1080_0040
DMA_CONTROL = 0x1080_0044
DMA_SRC_CONFIG = 0x1080_0048
DMA_DST_CONFIG = 0x1080_004C
DMA_STATUS = 0x1080_0050
DMA_ERROR_CODE = 0x1080_0054

# CONTROL fields (SECURE_DMA_CONTROL_reg_t): opcode[3:0], initial_transfer[8],
# go[31]. opcode 0 is the memory-to-memory copy.
CTRL_OPCODE_COPY = 0x0
CTRL_INITIAL_TRANSFER = 1 << 8
CTRL_GO = 1 << 31

# SRC_CONFIG / DST_CONFIG: increment[0], wrap[1].
CFG_INCREMENT = 1 << 0

# TRANSFER_WIDTH.transaction_width: 2 is the 4-byte beat, which is what makes
# the DMA's own master a 32-bit source into `u_axi_dw_upsizer_dma`.
TRANSFER_WIDTH_4B = 2

# STATUS.busy[0], done[1], error[3].
STATUS_DONE = 1 << 1
STATUS_ERROR = 1 << 3

# Scratch SRAM source and destination, far enough apart that the largest
# transfer below cannot overlap them.
# OCH_SEP_TOP_SEP_SRAM_BASE_ADDR = 0x10000000; the SRAM row of
# env/sep_axi_decode_map.py runs to 0x1000FFFF.
SRAM_BASE = 0x1000_0000
SRC_OFFSET = 0x4000
DST_OFFSET = 0x8000

# Three transfers: aligned 1 KB, the same length from an unaligned source, and
# 4 KB, which at a 4-byte source beat upsizes to more than 256 beats and so
# makes the upsizer split its master burst.
TRANSFERS = (
    ("aligned_1k", SRC_OFFSET, DST_OFFSET, 0x400),
    ("unaligned_1k", SRC_OFFSET + 1, DST_OFFSET, 0x400),
    ("split_4k", SRC_OFFSET, DST_OFFSET, 0x1000),
)

# Bounded poll. A transfer the DMA refuses reports through STATUS/ERROR_CODE
# rather than a bus error, so the poll ends and the outcome is logged either
# way; nothing here decides a verdict from it.
POLL_ATTEMPTS = 64


@pyuvm.test()
class sep_cov_axi_dw_upsizer_dma_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    `axi_dw_upsizer` has one instance in SEP, on the Secure DMA engine's own
    AXI master port. No fabric transaction reaches it: the only way to make
    the DMA drive that port is to programme a transfer through its CSR window
    and start it.

    Three transfers are programmed from the SMN inbound master: an aligned
    1 KB copy, the same copy from an unaligned source, and a 4 KB copy whose
    upsized burst exceeds 256 beats. STATUS and ERROR_CODE are read and
    logged after each one; they are evidence of what the engine reported, and
    this leaf states nothing about whether that report is correct.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _wr(self, stim: SepCovAxiStim, tag: str, addr: int, data: int) -> None:
        await stim.burst(
            tag,
            op=SepAxiOp.WRITE,
            addr=addr,
            length=4,
            size=SIZE_4B,
            burst=BURST_INCR,
            wdata=data,
        )

    async def _rd(self, stim: SepCovAxiStim, tag: str, addr: int) -> int:
        seq = await stim.burst(
            tag,
            op=SepAxiOp.READ,
            addr=addr,
            length=4,
            size=SIZE_4B,
            burst=BURST_INCR,
        )
        return seq.rdata & 0xFFFF_FFFF

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        # The enabled memory range has to cover both ends of every copy.
        await self._wr(stim, "dma_range_base", DMA_RANGE_BASE, SRAM_BASE)
        await self._wr(stim, "dma_range_limit", DMA_RANGE_LIMIT, SRAM_BASE + 0xFFFF)
        await self._wr(stim, "dma_range_valid", DMA_RANGE_VALID, 1)

        for name, src_off, dst_off, length in TRANSFERS:
            await self._wr(stim, f"{name}_src_lo", DMA_SRC_ADDR_LO, SRAM_BASE + src_off)
            await self._wr(stim, f"{name}_src_hi", DMA_SRC_ADDR_HI, 0)
            await self._wr(stim, f"{name}_dst_lo", DMA_DST_ADDR_LO, SRAM_BASE + dst_off)
            await self._wr(stim, f"{name}_dst_hi", DMA_DST_ADDR_HI, 0)
            await self._wr(stim, f"{name}_src_cfg", DMA_SRC_CONFIG, CFG_INCREMENT)
            await self._wr(stim, f"{name}_dst_cfg", DMA_DST_CONFIG, CFG_INCREMENT)
            await self._wr(stim, f"{name}_total", DMA_TOTAL_DATA_SIZE, length)
            await self._wr(stim, f"{name}_chunk", DMA_CHUNK_DATA_SIZE, length)
            await self._wr(stim, f"{name}_width", DMA_TRANSFER_WIDTH, TRANSFER_WIDTH_4B)
            await self._wr(
                stim,
                f"{name}_go",
                DMA_CONTROL,
                CTRL_OPCODE_COPY | CTRL_INITIAL_TRANSFER | CTRL_GO,
            )

            status = 0
            for attempt in range(POLL_ATTEMPTS):
                await stim.settle(64)
                status = await self._rd(stim, f"{name}_status{attempt}", DMA_STATUS)
                if status & (STATUS_DONE | STATUS_ERROR):
                    break
            error_code = await self._rd(stim, f"{name}_error", DMA_ERROR_CODE)
            self.logger.info(
                "COV-STIM dma_%s: %d bytes 0x%08x -> 0x%08x at a 4-byte source "
                "beat; STATUS=0x%08x ERROR_CODE=0x%08x",
                name,
                length,
                SRAM_BASE + src_off,
                SRAM_BASE + dst_off,
                status,
                error_code,
            )
            await stim.settle(64)

        stim.record(
            "COV-AXI-DW-UPSIZER-DMA",
            f"{len(TRANSFERS)} DMA transfers programmed and started through the "
            "DMA CSR window (aligned, unaligned source, and a length whose "
            "upsized burst exceeds 256 beats)",
        )
