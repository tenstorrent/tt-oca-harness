# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

Coverage stimulus: AXI bursts, IDs and sizes into the SEP SRAM aperture.

The SRAM ``memory_interface`` converts an AXI burst into SRAM requests through
``axi_to_mem``, but every access the suite issues is a single beat at AxID 0
near the base of the aperture, so ``mem_axi_req_i.aw.len``, ``.burst``,
``.size``, ``.id`` and the high ``.addr`` bits, and with them ``mem_req_o.addr``
/ ``.strb`` / ``.wdata``, hold one value.

This test sweeps AxLEN over 1, 2, 4, 8 and 16 INCR beats, AxSIZE over 1, 2, 4
and 8 bytes per beat, AxID over the full CPU-LSU instance width, start
addresses spanning the whole SRAM window so the high address bits move, and a
walking-one then walking-zero write payload. Every access is naturally aligned
to its AxSIZE and every burst stays inside the aperture.

Nothing here programs a filter or a remap rule, so no rule can cut off the
master.

no_cpu, +skip_fuse_sense: the SRAM aperture does not depend on a fuse sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_cov_remap_filter_seq import (
    SEP_SRAM_BASE,
    SEP_SRAM_SIZE,
    cov_read_seq,
    cov_write_seq,
    walking_data,
)

# s_axi carries ID_WIDTH(3) in dv/tb/tb_top.sv, so the instance ID range is 0..7.
_LSU_ID_WIDTH = 3
_BURST_INCR = 1
# AxSIZE encodings 0..3 -> 1, 2, 4 and 8 bytes per beat. The bus is 64 bits, so
# 8 bytes is the widest beat.
_SIZES = (0, 1, 2, 3)
_BEAT_COUNTS = (1, 2, 4, 8, 16)
# Sixteen start pages spanning the whole aperture, so the high address bits of
# the request move. The last one leaves room for the longest burst below.
_SPAN_STEP = SEP_SRAM_SIZE // 16
_LONGEST_BURST_BYTES = max(_BEAT_COUNTS) * (1 << max(_SIZES))


@pyuvm.test()
class sep_cov_memory_interface_sram_burst_id_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more.

    Sweep AxLEN, AxSIZE, AxID, start address and write data into the SRAM.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _burst(self, addr: int, *, size: int, beats: int, axi_id: int, data: int) -> None:
        nbytes = beats * (1 << size)
        burst = _BURST_INCR if beats > 1 else None
        await self.start_seq(
            cov_write_seq(addr, data, length=nbytes, size=size, burst=burst, axi_id=axi_id)
        )
        await self.start_seq(
            cov_read_seq(addr, length=nbytes, size=size, burst=burst, axi_id=axi_id)
        )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()

        # Length x size, at the base of the aperture.
        for size in _SIZES:
            for beats in _BEAT_COUNTS:
                nbytes = beats * (1 << size)
                await self._burst(
                    SEP_SRAM_BASE + (1 << size) * 4,
                    size=size,
                    beats=beats,
                    axi_id=0,
                    data=walking_data(nbytes, 1),
                )
                await self._burst(
                    SEP_SRAM_BASE + (1 << size) * 4,
                    size=size,
                    beats=beats,
                    axi_id=0,
                    data=walking_data(nbytes, 1, invert=True),
                )

        # AxID over the full instance width, one four-beat burst each.
        for axi_id in range(1 << _LSU_ID_WIDTH):
            await self._burst(
                SEP_SRAM_BASE + 0x100 + axi_id * 0x20,
                size=2,
                beats=4,
                axi_id=axi_id,
                data=walking_data(16, axi_id),
            )

        # Start addresses spanning the aperture, so the high address bits move.
        for page in range(16):
            addr = SEP_SRAM_BASE + page * _SPAN_STEP
            if page == 15:
                addr = SEP_SRAM_BASE + SEP_SRAM_SIZE - _LONGEST_BURST_BYTES
            await self._burst(
                addr,
                size=3,
                beats=8,
                axi_id=page & ((1 << _LSU_ID_WIDTH) - 1),
                data=walking_data(64, page * 7),
            )
        self.logger.info(
            "SRAM burst sweep: sizes %s x beats %s, ids 0..%d, 16 start pages",
            _SIZES,
            _BEAT_COUNTS,
            (1 << _LSU_ID_WIDTH) - 1,
        )
