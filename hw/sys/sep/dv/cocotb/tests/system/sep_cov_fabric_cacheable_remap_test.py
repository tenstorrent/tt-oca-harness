# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Transact through a remap region that ties the top AxCACHE bits high.

Stimulus only. No contract is asserted; a PASS means the path was driven,
nothing more.

Target (docs/SEP_COV_VPLAN.adoc, "SEP system fabric, system CSR and crypto
interconnect"): `aw.cache[3:2]` and `ar.cache[3:2]` on the outbound ports and
on the crossbar master ports. `REGION_ATTRS.cacheable` in
`hw/ip/axi_alias_remap/regs/alias_remap.rdl` is documented as "If set, top two
bits of a*cache will be tied high" for a matching region, and no other SEP
frontdoor raises those bits.

Stimulus: program two local-master alias-remap regions with
REGION_ATTRS.cacheable and REGION_ATTRS.valid set, one pointing a filter bank
page at a SEP_CPU_CTRL word inside the local path, and one pointing the other
filter bank page at a page of the SMU window so the tagged beats also leave on
`smn_outbound_axi_req_o`. An outbound filter slot is opened over the outbound
target first, because the outbound filter blocks by default. Then read and
write through both windows.

The source windows are the filter bank pages, which
`seq_lib/sep_fabric_local_alias_seq.py` already uses as an alias source; all
CSR programming completes before the remap enables, because a remapped source
page no longer reaches the register file.

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from sep_base_test import sep_base_test
from sep_reg_meta import LOCAL_MASTER_ALIAS_REMAP_CTRL_0
from seq_lib.sep_cov_stimulus_seq import (
    CLOCK_GATE_CTRL,
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

# REGION_ATTRS.cacheable is bit 62 of the 64-bit register, so bit 30 of the
# high 32-bit word.
CACHEABLE_HI = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "cacheable") >> 32

# Local target: a SEP_CPU_CTRL word on the same local path, as the existing
# live alias-remap datapath test uses. Outbound target: a page of the SMU
# window, whose base and size keep their reset values (0x8000_0000 /
# 0x4000_0000) in this leaf. 0x8000_0000 itself is the firmware STDOUT word
# the TB mailbox responder decodes (`dv/tb/sep_outbound_mbx.sv`), so the
# target is one page above it.
LOCAL_TARGET = CLOCK_GATE_CTRL
OUTBOUND_TARGET = 0x8000_0000 + PAGE

LOCAL_SOURCE = OUTFILT_BASE & ~(PAGE - 1)
OUTBOUND_SOURCE = INFILT_BASE & ~(PAGE - 1)

FILTER_SLOT_INDEX = 0
# The outbound filter is built with EnNsFilter, and `traffic_filter.sv` passes a
# beat only when `tx_ns_initiator_i == cfg_allow_ns_i`. The cocotb AXI master
# drives non-secure AxPROT, so the slot is opened with allow_ns set.
FILTER_OPEN = F_READ_ALLOWED | F_WRITE_ALLOWED | F_ENTRY_ENABLED | F_ALLOW_NS | F_ALLOW_BURST

WDATA = 0x0BAD_C0DE


@pyuvm.test()
class sep_cov_fabric_cacheable_remap_test(sep_base_test):
    """Traffic through cacheable-tagged remap regions. Stimulus only."""

    stimulus_only = True

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        stim = SepCovStim(self)
        await stim.ungate_clocks()

        slot = stim.filter_slot(inbound=False, index=FILTER_SLOT_INDEX)
        end = OUTBOUND_TARGET + PAGE - 1
        await stim._wr(slot + FILTER_START_ADDR, OUTBOUND_TARGET & 0xFFFF_FFFF)
        await stim._wr(slot + FILTER_START_ADDR + 4, (OUTBOUND_TARGET >> 32) & 0x00FF_FFFF)
        await stim._wr(slot + FILTER_END_ADDR, end & 0xFFFF_FFFF)
        await stim._wr(slot + FILTER_END_ADDR + 4, (end >> 32) & 0x00FF_FFFF)
        await stim._wr(slot + FILTER_CONFIG, FILTER_OPEN)
        self.logger.info(
            "outbound filter slot %d opened over 0x%x..0x%x",
            FILTER_SLOT_INDEX,
            OUTBOUND_TARGET,
            end,
        )

        windows = (
            (LOCAL_SOURCE, LOCAL_TARGET),
            (OUTBOUND_SOURCE, OUTBOUND_TARGET),
        )
        for region, (source, target) in enumerate(windows):
            base = ALIAS_BASE + region * ALIAS_STRIDE
            src_page = source & ~(PAGE - 1)
            # REGION_ATTRS.offset is added to address bits [55:12] and the low
            # 12 bits are preserved (alias_remap.rdl), so the addend is the
            # page-number difference.
            offset = (((target >> 12) - (src_page >> 12)) & ((1 << 44) - 1)) << 12
            await stim._wr(base + ALIAS_START, src_page & 0xFFFF_FFFF)
            await stim._wr(base + ALIAS_START + 4, (src_page >> 32) & 0x00FF_FFFF)
            await stim._wr(base + ALIAS_END, (src_page + PAGE) & 0xFFFF_FFFF)
            await stim._wr(base + ALIAS_END + 4, ((src_page + PAGE) >> 32) & 0x00FF_FFFF)
            await stim._wr(base + ALIAS_ATTRS, offset & 0xFFFF_FFFF)
            await stim._wr(
                base + ALIAS_ATTRS + 4,
                ((offset >> 32) & 0x00FF_FFFF) | CACHEABLE_HI | VALID_HI,
            )
            self.logger.info("alias region %d cacheable: 0x%08x -> 0x%x", region, src_page, target)

        for source, target in windows:
            access_addr = (source & ~(PAGE - 1)) | (target & (PAGE - 1))
            await stim.access(
                op=SepAxiOp.READ, addr=access_addr, name=f"cov_cacheable_rd_{target:x}"
            )
            await stim.access(
                op=SepAxiOp.WRITE,
                addr=access_addr,
                wdata=WDATA,
                name=f"cov_cacheable_wr_{target:x}",
            )
            self.logger.info("cacheable traffic driven at 0x%08x -> 0x%x", access_addr, target)
