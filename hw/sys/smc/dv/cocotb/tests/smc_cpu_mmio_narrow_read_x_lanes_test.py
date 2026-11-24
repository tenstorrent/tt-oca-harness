# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Narrow uncached MMIO loads complete when the unrequested R lanes are X.

Firmware test (`fw/tests/mmio_narrow_read`), four-state simulators only.
Requires:
  +smc_scratch_ram_hex=mmio_narrow_read.ecc.hex   (bare basename; staged by c_compile)
  +smc_hold_cpu_boot
  +smc_sys_out_r_xfill                            (tb_top X-fills the unrequested lanes)
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_mmio_narrow_read_x_lanes_test_seq import (
    NARROW_LOADS,
    smc_cpu_mmio_narrow_read_x_lanes_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_mmio_narrow_read_x_lanes_test(smc_base_test):
    """Byte, halfword and word MMIO loads with X on the lanes they did not ask for."""

    auto_protocol_vip = False
    required_evidence = (
        "CHK-FW-MMIO-NARROW-X-BOOT",
        "CHK-FW-MMIO-NARROW-X-LANES",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_cpu_mmio_narrow_read_x_lanes_test_seq("cpu_mmio_narrow_read_x_lanes_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.boot.get("boot_checked") is True, f"firmware boot was not checked: {seq.boot}"
        assert seq.xfill_beats == NARROW_LOADS, f"X-filled beats {seq.xfill_beats}"
        assert seq.xfill_overlaps == 0, f"overlapping reads {seq.xfill_overlaps}"
        assert seq.cpu_x_beats == NARROW_LOADS, f"CPU MMIO X beats {seq.cpu_x_beats}"
