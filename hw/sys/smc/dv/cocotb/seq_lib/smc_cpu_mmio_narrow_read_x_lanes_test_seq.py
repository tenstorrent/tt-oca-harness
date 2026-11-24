# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Narrow uncached MMIO loads complete when the unrequested R lanes are X.

`fw/tests/mmio_narrow_read` reads one 64-bit word behind SYS_OUT with eight
byte loads, four halfword loads and two word loads, then one doubleword load,
one at a time, and checks each value. AXI lets a target leave the byte lanes
outside 2^ARSIZE undriven; a 32-bit target behind a 64-to-32-bit downsizer does.
With `+smc_sys_out_r_xfill`, tb_top drives X on those lanes of every narrow R
beat in the window at 0xB000_0000 and counts the accepted beats it filled
whose requested lanes were known (`tb_output_axi_xfill_count`). The fill is
matched to the R beat by ID and is exact while one read is outstanding at a
time; `tb_output_axi_xfill_overlap_count` counts the ARs that broke that.
`tb_cpu_mmio_r_x_count` counts the R beats the CPU MMIO port accepted with an
unknown data bit, so the X is seen where the CPU cluster takes the beat.

A load response stays valid when an unrequested lane of the uncached beat is
X; a response that goes X stops the core before the PASS word. The image
posts PASS only if every load returned its bytes.

Bench observation: before release the bench preloads the word and opens
inbound filter 0 and outbound filter 0; after PASS it requires one filled R
beat per narrow load at SYS_OUT and at the CPU MMIO port and no overlapping
read, so a run whose loads never carried X cannot pass. Needs a four-state simulator: on Verilator an X lane
is a 0 or 1 and the case does not exist.

Tokens: CHK-FW-MMIO-NARROW-X-BOOT, CHK-FW-MMIO-NARROW-X-LANES.
"""

from __future__ import annotations

import cocotb

from .smc_fw_image_boot_seq import smc_fw_image_boot_seq
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq

MMIO_NARROW_ADDR = 0xB000_0000
MMIO_NARROW_WORD = 0x8877_6655_4433_2211
# Eight byte, four halfword and two word loads carry unrequested lanes; the
# doubleword load does not.
NARROW_LOADS = 8 + 4 + 2
XFILL_COUNTERS = (
    "tb_output_axi_xfill_count",
    "tb_output_axi_xfill_overlap_count",
    "tb_cpu_mmio_r_x_count",
)


class smc_cpu_mmio_narrow_read_x_lanes_test_seq(smc_fw_image_boot_seq):
    """Boot the narrow-read image with X on every unrequested SYS_OUT R lane."""

    tag = "MMIO-NARROW-X"
    poll_iterations = 2000

    def __init__(self, name: str = "smc_cpu_mmio_narrow_read_x_lanes_test_seq") -> None:
        super().__init__(name)
        self.xfill_beats = -1
        self.xfill_overlaps = -1
        self.cpu_x_beats = -1

    async def before_boot(self) -> None:
        plusargs = cocotb.plusargs or {}
        assert "smc_sys_out_r_xfill" in plusargs, (
            "this leaf needs +smc_sys_out_r_xfill; without it no R lane is X"
        )
        image = plusargs.get("smc_scratch_ram_hex")
        assert image and str(image).endswith("mmio_narrow_read.ecc.hex"), (
            "this leaf needs the staged +smc_scratch_ram_hex=mmio_narrow_read.ecc.hex"
        )
        sys_out_mem = self.cfg.sys_out_mem
        assert sys_out_mem is not None, "SYS_OUT responder not bound"
        sys_out_mem.write_int(MMIO_NARROW_ADDR, MMIO_NARROW_WORD, 8)
        await output_fabric_pass_all_cfg_seq.program_inbound_pass_all(self)
        await output_fabric_pass_all_cfg_seq.program_outbound_pass_all(self)
        dut = cocotb.top
        for name in XFILL_COUNTERS:
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z before the image ran"
            assert int(sig.value) == 0, f"{name} is {int(sig.value)} before the image ran"

    async def after_pass(self) -> None:
        dut = cocotb.top
        for name in XFILL_COUNTERS:
            assert getattr(dut, name).value.is_resolvable, f"{name} is X/Z after PASS"
        self.xfill_overlaps = int(dut.tb_output_axi_xfill_overlap_count.value)
        assert self.xfill_overlaps == 0, (
            f"{self.xfill_overlaps} SYS_OUT reads were accepted while an earlier one was "
            f"outstanding: the X fill did not follow the read it was latched for"
        )
        self.xfill_beats = int(dut.tb_output_axi_xfill_count.value)
        assert self.xfill_beats == NARROW_LOADS, (
            f"{self.xfill_beats} SYS_OUT R beats carried X lanes, expected {NARROW_LOADS} "
            f"(one per narrow load): the loads did not see the case under test"
        )
        self.cpu_x_beats = int(dut.tb_cpu_mmio_r_x_count.value)
        assert self.cpu_x_beats == NARROW_LOADS, (
            f"the CPU MMIO port accepted {self.cpu_x_beats} R beats with an unknown data "
            f"bit, expected {NARROW_LOADS}: the X lanes did not reach the CPU cluster"
        )
        cocotb.log.info(
            "CHK-FW-MMIO-NARROW-X-LANES: %d narrow SYS_OUT R beats carried X on their "
            "unrequested byte lanes and known data on the requested ones, %d overlapping "
            "reads, and the CPU MMIO port accepted %d R beats with an unknown data bit",
            self.xfill_beats,
            self.xfill_overlaps,
            self.cpu_x_beats,
        )
