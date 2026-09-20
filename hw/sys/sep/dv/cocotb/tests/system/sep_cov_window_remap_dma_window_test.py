# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: DMA transfers on both sides of the local-alias window.

``sep_dma_wrap`` puts an ``axi_window_remap`` on the DMA master
(``u_dma_local_alias_remap``): an address inside the local-alias window is
carried onto ``sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE``, and an address outside
it passes through. The window base is the ``SEP_LOCAL_BASE_ADDR`` CSR, which
this test reads rather than assumes. Every DMA transfer in the suite is
firmware-issued with both ends below the window, so ``aw_in_alias`` and
``ar_in_alias`` stay low and the adjusted-address bits never move.

The descriptors below put the source and the destination on each side of the
window in turn -- both outside, source inside, destination inside, both inside
-- at several transfer lengths and buffer alignments, so the adjusted address
spans the window. Each transfer is a single-chunk 4-byte-wide incrementing
copy, programmed in the register order of
``dv/fw/tests/dma_basic_test/dma_basic_test.c``.

The STATUS poll is bounded and its value is logged, not graded: a transfer that
reports an error still leaves the window-remap logic driven, and this test
claims nothing about the DMA engine.

no_cpu, +skip_fuse_sense: the DMA descriptor CSRs are reachable from the
CPU-LSU master and the copy does not depend on a fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import (
    DMA_ALIAS_TARGET_BASE,
    SEP_CPU_CTRL_LOCAL_BASE,
    SEP_SRAM_BASE,
    SepCovDma,
)

# Two SRAM buffers, far enough apart that the longest transfer below cannot
# reach from one into the other.
_SRC_OFFSET = 0x1000
_DST_OFFSET = 0x8000
_LENGTHS = (16, 64, 256)
# Alignments inside the buffer, all 4-byte aligned for the 4-byte transfer
# width, so the low adjusted-address bits differ per transfer.
_ALIGNMENTS = (0x0, 0x4, 0x40, 0x400)


@pyuvm.test()
class sep_cov_window_remap_dma_window_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Copy SRAM to SRAM with each end inside and outside the alias window.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        dma = SepCovDma(self)

        alias_base = await dma.read32(SEP_CPU_CTRL_LOCAL_BASE)
        adjust = (alias_base - DMA_ALIAS_TARGET_BASE) & 0xFFFF_FFFF
        self.logger.info(
            "DMA local-alias window base 0x%08x -> target 0x%08x (adjust 0x%08x)",
            alias_base,
            DMA_ALIAS_TARGET_BASE,
            adjust,
        )

        def aliased(addr: int) -> int:
            """The alias-window address that the DMA remapper carries onto ``addr``."""
            return (addr + adjust) & 0xFFFF_FFFF

        await dma.enable_full_range()

        for length in _LENGTHS:
            for align in _ALIGNMENTS:
                src = SEP_SRAM_BASE + _SRC_OFFSET + align
                dst = SEP_SRAM_BASE + _DST_OFFSET + align
                for src_alias, dst_alias in (
                    (False, False),
                    (True, False),
                    (False, True),
                    (True, True),
                ):
                    await dma.clear_status()
                    status = await dma.run_copy(
                        src=aliased(src) if src_alias else src,
                        dst=aliased(dst) if dst_alias else dst,
                        nbytes=length,
                    )
                    self.logger.info(
                        "DMA copy %d bytes src%s dst%s align 0x%x -> STATUS 0x%08x",
                        length,
                        "-alias" if src_alias else "",
                        "-alias" if dst_alias else "",
                        align,
                        status,
                    )
        await dma.clear_status()
