# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Drive the outbound address-remap demux SEP_EXT_TO_SMU leg, both ways in.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): the `SEP_EXT_TO_SMU` legs of `address_remap_demux_select_aw`
and `address_remap_demux_select_ar` in
`hw/sys/sep/rtl/sep_system_peripherals/rtl/sep_system_peripherals.sv`, the
matching slice of `sep_system_peripheral_56_remapped_from_demux_axi_reqs`,
`smn_outbound_axi_req_o`, and the `SMU_GLOBAL_BASE_ADDR` / `SMU_REGION_SIZE`
outputs of `sep_system_csr`, which are at zero toggle today.

That decode selects `SEP_EXT_TO_SMU` on either of two terms: the programmed
SMU window, or any address at or above `EXTERNAL_TO_CHIPLET_BASE_ADDR` =
56'h1_0000_0000 (`hw/sys/sep/rtl/sep_pkg.sv:255`). Both are driven here, and
the second is the only frontdoor way to raise an outbound address bit above
bit 31.

Stimulus: reprogram SMU_GLOBAL_BASE_ADDR and SMU_REGION_SIZE away from their
reset values, open two outbound filter slots over the two target windows, then
point two local-master alias-remap regions at those windows and issue reads and
writes through them from the CPU-LSU master. The source windows are the filter
bank pages, which `seq_lib/sep_fabric_local_alias_seq.py` already uses as an
alias source; all CSR programming completes before the remap enables, because
a remapped source page no longer reaches the register file.

The SEP_EXT_TO_SMC leg is not driven: `dv/tb/tb_top.sv` ties
`smc_global_base_addr_i` and `smc_region_size_i` to zero unless the build
defines `SEP_SMC_MEM_MODEL`, so that window is empty in this run mode.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL
from seq_lib.sep_cov_stimulus_seq import (
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    SepCovStim,
)
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    ALIAS_STRIDE,
    F_ALLOW_BURST,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_WRITE_ALLOWED,
    INFILT_BASE,
    OUTFILT_BASE,
)
from seq_lib.sep_fabric_local_alias_seq import PAGE, VALID_HI

SMU_GLOBAL_BASE_ADDR = SEP_CPU_CTRL.addr("SMU_GLOBAL_BASE_ADDR")
SMU_REGION_SIZE = SEP_CPU_CTRL.addr("SMU_REGION_SIZE")

# A programmed SMU window that differs from the reset pair (0x8000_0000 /
# 0x4000_0000) in both registers, and that stays below
# EXTERNAL_TO_CHIPLET_BASE_ADDR so the window compare, and not the
# at-or-above-chiplet term, is what selects the leg.
SMU_BASE = 0x9000_0000
SMU_SIZE = 0x0800_0000

# One target page inside the programmed SMU window, and one at or above
# EXTERNAL_TO_CHIPLET_BASE_ADDR. Neither is 0x8000_0000: that address is the
# firmware STDOUT word the TB mailbox responder decodes
# (`dv/tb/sep_outbound_mbx.sv`), and writing it would raise the run's
# firmware-done flags.
TARGETS = (SMU_BASE + PAGE, 0x1_0000_0000 + PAGE)

# Source pages on the local-master path, one per target.
SOURCES = (OUTFILT_BASE & ~(PAGE - 1), INFILT_BASE & ~(PAGE - 1))

# Outbound filter slots opened over the two target pages.
FILTER_SLOTS = (0, 1)

# FILTER_CONFIG value that opens a slot. The outbound filter is built with
# EnNsFilter, and `traffic_filter.sv` passes a beat only when
# `tx_ns_initiator_i == cfg_allow_ns_i`, so allow_ns must match the security
# level of the master driving the window. The cocotb AXI master drives
# non-secure AxPROT, so the slot is opened with allow_ns set.
FILTER_OPEN = F_READ_ALLOWED | F_WRITE_ALLOWED | F_ENTRY_ENABLED | F_ALLOW_NS | F_ALLOW_BURST

# Payload of the outbound writes.
WDATA = 0x1234_5678


@pyuvm.test()
class sep_cov_fabric_outbound_demux_leg_sweep_test(sep_base_test):
    """Reads and writes down the SEP_EXT_TO_SMU demux leg. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        await stim._wr(SMU_GLOBAL_BASE_ADDR, SMU_BASE & 0xFFFF_FFFF)
        await stim._wr(SMU_GLOBAL_BASE_ADDR + 4, (SMU_BASE >> 32) & 0x00FF_FFFF)
        await stim._wr(SMU_REGION_SIZE, SMU_SIZE & 0xFFFF_FFFF)
        await stim._wr(SMU_REGION_SIZE + 4, (SMU_SIZE >> 32) & 0x00FF_FFFF)
        self.logger.info("SMU window programmed base=0x%x size=0x%x", SMU_BASE, SMU_SIZE)

        for slot_index, target in zip(FILTER_SLOTS, TARGETS):
            slot = stim.filter_slot(inbound=False, index=slot_index)
            end = target + PAGE - 1
            await stim._wr(slot + FILTER_START_ADDR, target & 0xFFFF_FFFF)
            await stim._wr(slot + FILTER_START_ADDR + 4, (target >> 32) & 0x00FF_FFFF)
            await stim._wr(slot + FILTER_END_ADDR, end & 0xFFFF_FFFF)
            await stim._wr(slot + FILTER_END_ADDR + 4, (end >> 32) & 0x00FF_FFFF)
            await stim._wr(slot + FILTER_CONFIG, FILTER_OPEN)
            self.logger.info(
                "outbound filter slot %d opened over 0x%x..0x%x", slot_index, target, end
            )

        # REGION_ATTRS.offset is added to address bits [55:12] and the low 12
        # bits are preserved (hw/ip/axi_alias_remap/regs/alias_remap.rdl), so
        # the addend is the page-number difference.
        for region, (source, target) in enumerate(zip(SOURCES, TARGETS)):
            base = ALIAS_BASE + region * ALIAS_STRIDE
            offset = ((target >> 12) - (source >> 12)) & ((1 << 44) - 1)
            offset <<= 12
            await stim._wr(base + ALIAS_START, source & 0xFFFF_FFFF)
            await stim._wr(base + ALIAS_START + 4, (source >> 32) & 0x00FF_FFFF)
            await stim._wr(base + ALIAS_END, (source + PAGE) & 0xFFFF_FFFF)
            await stim._wr(base + ALIAS_END + 4, ((source + PAGE) >> 32) & 0x00FF_FFFF)
            await stim._wr(base + ALIAS_ATTRS, offset & 0xFFFF_FFFF)
            await stim._wr(base + ALIAS_ATTRS + 4, ((offset >> 32) & 0x00FF_FFFF) | VALID_HI)
            self.logger.info(
                "alias region %d: 0x%08x -> 0x%x (offset 0x%x)", region, source, target, offset
            )

        for source, target in zip(SOURCES, TARGETS):
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=source,
                wdata=WDATA,
                name=f"cov_smu_wr_{target:x}",
            )
            await stim.access(op=SepAxiOp.READ, addr=source, name=f"cov_smu_rd_{target:x}")
            self.logger.info("drove read+write through 0x%08x -> 0x%x", source, target)
