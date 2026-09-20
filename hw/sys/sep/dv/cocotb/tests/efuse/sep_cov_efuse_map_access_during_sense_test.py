# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shadow-register access while the fuse sense is still streaming.

``efuse_shadow_regs`` answers an APB request that arrives before
``fuse_sense_done`` with ``pslverr`` and the ``0xbadcab1e`` marker, in the
streaming branch of its main always_ff. Every test in the suite gates its
first shadow access on ``sep_fuse_sense_done_o``, so that arm has never run.

The stimulus releases ``rst_ni`` and issues ``SEP_EFUSE_MAP`` reads
immediately, without waiting for sense-done, then waits for sense and repeats
the same window around a resense. The reads are marked as expecting an error
response, because a SLVERR in this window is the arm being driven rather than
a bus fault; the returned value is not compared.

Real fuse sense: the window this reaches is the one where the sense FSM is
streaming words into the shadow array, which only exists when a real sense
runs.

The pre-sense probes are driven at the VIP master, because the agent driver
only runs once the reset-done event is set and the window closes before that.
Once the second sense has completed, the same shadow words are read again
through the agent, so the run carries observed AXI traffic rather than none.

The matching pre-sense arm in the preload branch is not driven here. With
``+skip_fuse_sense`` the RTL sets ``fuse_sense_done`` on the first clock edge
after reset release, so that branch is live for one cycle, which no frontdoor
master can reach.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_TEST_DEV
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_cov_efuse_iface_seq import cov_master
from seq_lib.sep_cov_remap_filter_seq import cov_read_seq

_MAX_SENSE_CYCLES = 20_000

SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
# Several words inside the aperture, so the pre-sense answer is driven for
# more than one address.
PROBE_OFFSETS = (0x000, 0x004, 0x00C, 0x020, 0x100)

# Reads issued back to back in the streaming window. The sense streams 256
# words, so the window is long compared with one AXI round trip.
PROBES_PER_WINDOW = 12

# Bound on one probe, so a window that closes mid-access reports a timeout
# instead of hanging the leaf.
_ACCESS_TIMEOUT_NS = 20_000


@pyuvm.test()
class sep_cov_efuse_map_access_during_sense_test(sep_base_test):
    """Stimulus only. No contract is asserted; a PASS means the path was driven, nothing more."""

    stimulus_only = True

    async def _probe(self, index: int) -> None:
        addr = SHADOW_BASE + PROBE_OFFSETS[index % len(PROBE_OFFSETS)]
        # Driven at the VIP master, not through the agent: the response here
        # depends on where the sense FSM is when the access lands, so it is
        # SLVERR from the pre-sense arm or OKAY from the normal one, and
        # neither is a claim this leaf makes.
        await self._master.read_bytes_result(
            addr,
            4,
            size=2,
            check_response=False,
            timeout_ns=_ACCESS_TIMEOUT_NS,
            allow_timeout=True,
        )

    async def _drive_window(self, label: str) -> None:
        done = cocotb.top.sep_fuse_sense_done_o
        driven = 0
        for index in range(PROBES_PER_WINDOW):
            if self.rd(done):
                break
            await self._probe(index)
            driven += 1
        self.logger.info("[cov] %s: %d shadow reads issued before sense-done", label, driven)

    async def run_scenario(self) -> None:
        image: SepEfuseImage = self.select_efuse_image(lc_raw=LC_TEST_DEV)
        self.write_efuse_image(image)

        # Reset release without the sense wait, so the AXI agent is running
        # while the sense FSM is still streaming.
        await self.release_no_cpu_reset()
        self._master = cov_master(self, "s_axi")
        if self._master is None:
            raise AssertionError(
                "no VIP master behind env.axi_agent.driver; the pre-sense window cannot be probed"
            )
        await self._drive_window("first sense")
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        # The same window again around a resense. `resense` waits for
        # sense-done itself, so the probes go between the reset pulse and that
        # wait.
        dut = cocotb.top
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, 20)
        dut.rst_ni.value = 1
        await self._drive_window("resense")
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        self.cfg.reset_done.set()

        # Post-sense reads of the same words, through the agent. The shadow
        # array answers OKAY once the sense has completed; no value is compared.
        for offset in PROBE_OFFSETS:
            await self.start_seq(cov_read_seq(SHADOW_BASE + offset))
        self.logger.info("[cov] %d post-sense shadow reads issued", len(PROBE_OFFSETS))
