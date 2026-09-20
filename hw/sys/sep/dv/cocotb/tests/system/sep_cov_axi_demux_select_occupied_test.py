# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""One AxID outstanding to two different crossbar master ports, to occupy the demux select."""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_base_test import sep_base_test
from seq_lib.sep_cov_axi_burst_seq import BURST_INCR, SIZE_8B, SepCovAxiStim, incr_bytes

# Two apertures that decode to different master ports of the local crossbar,
# both inside the inbound allow windows in seq_lib/sep_cov_axi_burst_seq.py:
# entry 0 is the SEP SRAM and entry 3 is the crypto block. Addresses from
# hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv.
SRAM_BASE = 0x1000_0000
OTBN_DMEM_BASE = 0x1090_8000

# `axi_demux_simple` keeps a per-ID counter of outstanding transactions and the
# master port each ID is currently bound to. While an ID is outstanding, an Ax
# on that same ID for a DIFFERENT master port must wait: the request is held
# until the counter drains, so responses on one ID cannot interleave across
# ports (vendor/pulp-platform/axi/upstream/src/axi_demux_simple.sv, the
# `ar_select_occupied` / `aw_select_occupied` guards at :234 and :385).
#
# Every SEP access so far leaves AxID at 0 and retires one transaction before
# starting the next, so an ID is never bound to a port when the next Ax on it
# arrives and the occupied guard never holds anything.
SHARED_ID = 5

BEATS = 4
BURST_BYTES = incr_bytes(BEATS)  # 32 B at size=3

# The first access must still be outstanding when the second is offered, so
# its response is held off. The second is then released by the first retiring.
BACKPRESSURE_CYCLES = 400
ACCESS_TIMEOUT_NS = 60_000


@pyuvm.test()
class sep_cov_axi_demux_select_occupied_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven,
    nothing more.

    Reads and writes carrying one AxID are offered to two different crossbar
    master ports at once, with the first response backpressured so the ID is
    still bound to the first port when the second Ax arrives. That is the only
    condition under which the demux ID counters report the select as occupied
    and hold the second request, and no SEP leaf reaches it today because every
    access uses AxID 0 and retires before the next one starts.

    Both directions are driven: a read pair and a write pair, each SRAM first
    then crypto, and each again in the opposite order so the bound port is not
    always the same one. The accesses go through the VIP master rather than the
    UVM sequencer: the SEP AXI driver awaits each item to completion, so the
    sequencer cannot leave one outstanding while it offers the next.

    Targets are scratch storage -- an SRAM word and an OTBN DMEM word while the
    core is idle -- and read data is logged, never compared.
    """

    # Coverage stimulus: this leaf grades nothing, so the own-evidence floor
    # in sep_base_test._finalize_evidence does not apply to it.
    stimulus_only = True

    async def _pair(self, stim, first: int, second: int, op: str, rng) -> None:
        """Offer two same-ID accesses at two apertures with the first held open."""
        master = stim.master()
        tasks = []
        for tag, addr in (("first", first), ("second", second)):
            if op == "read":
                task = cocotb.start_soon(
                    master.read_bytes_result(
                        addr,
                        BURST_BYTES,
                        size=SIZE_8B,
                        burst=BURST_INCR,
                        id=SHARED_ID,
                        check_response=False,
                        timeout_ns=ACCESS_TIMEOUT_NS,
                        allow_timeout=True,
                    )
                )
            else:
                payload = rng.getrandbits(8 * BURST_BYTES).to_bytes(BURST_BYTES, "little")
                task = cocotb.start_soon(
                    master.write_bytes_result(
                        addr,
                        payload,
                        size=SIZE_8B,
                        burst=BURST_INCR,
                        id=SHARED_ID,
                        check_response=False,
                        timeout_ns=ACCESS_TIMEOUT_NS,
                        allow_timeout=True,
                    )
                )
            tasks.append((tag, addr, task))

        for tag, addr, task in tasks:
            res = await task
            stim.driven += 1
            self.logger.info(
                "COV-STIM demux_occupied_%s_%s: %s 0x%08x id=%d beats=%d -> resp=%d%s",
                op,
                tag,
                op,
                addr,
                SHARED_ID,
                BEATS,
                res.resp,
                " (no response, tolerated)" if res.timed_out else "",
            )

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        rng = SepSeededRng(self.random_seed())
        stim = SepCovAxiStim(self)
        await stim.open_windows()

        drv = stim.timing_driver()
        drv.set_timing(
            AxiTimingProfile(b_ready_delay=BACKPRESSURE_CYCLES, r_ready_delay=BACKPRESSURE_CYCLES)
        )
        try:
            await self._pair(stim, SRAM_BASE, OTBN_DMEM_BASE, "read", rng)
            await stim.settle()
            await self._pair(stim, OTBN_DMEM_BASE + 0x100, SRAM_BASE + 0x100, "read", rng)
            await stim.settle()
            await self._pair(stim, SRAM_BASE + 0x200, OTBN_DMEM_BASE + 0x200, "write", rng)
            await stim.settle()
            await self._pair(stim, OTBN_DMEM_BASE + 0x300, SRAM_BASE + 0x300, "write", rng)
        finally:
            drv.set_timing(AxiTimingProfile())
        await stim.settle()

        stim.record(
            "COV-AXI-DEMUX-SELECT-OCCUPIED",
            f"read and write pairs on AxID {SHARED_ID} offered to the SRAM and "
            "crypto master ports together, in both orders, with the first "
            "response held off",
        )
