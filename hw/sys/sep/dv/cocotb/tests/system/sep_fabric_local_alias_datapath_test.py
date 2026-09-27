# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live local-master alias-remap offset on a real CPU-LSU beat.

RANDCFG. Distinct from the CPU high-alias window
(``sep_cpu_ifu_lsu_alias_remap_matrix_test``). Scope is the sixteen
programmable regions ahead of the system-peripherals routing demux
(``hw/sys/sep/doc/fabric.adoc``, ``axi_alias_remap``). CSR R/W stays on
``sep_fabric_remap_filter_csr_bank_test``. This vehicle programs one
region and proves the offset in both directions: an aliased write moves
the identity ``CLOCK_GATE_CTRL`` readback from a parked value to the
marker, and an aliased read follows a later identity-only write.

CHK-VALID-GATE covers the enable. ``axi_alias_remap`` carries
``region_valid`` per region and gates the hit on it, so a window whose
bounds and offset are programmed with the bit clear must leave the beat
at the address the master issued. Programming the window and clearing
only the enable is what separates a working gate from an address that
was never in range.

The cacheable attribute is not checked here: ``axi_alias_remap`` drives
``axi_out_req_o.aw.cache`` from the region on a hit, and this bench has
no observable on the outbound cache bits.

no_cpu, +skip_fuse_sense: the remapper does not depend on sense.
"""

from __future__ import annotations

import cocotb
import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_local_alias_seq import (
    N_REGIONS,
    SepLocalAlias,
    SepLocalAliasCfg,
    alias_probe_seq,
)


@pyuvm.test()
class sep_fabric_local_alias_datapath_test(sep_base_test):
    """Programmed region translates a live beat by the programmed offset."""

    async def run_scenario(self) -> None:
        cfg = SepLocalAliasCfg(self.random_seed())
        self.logger.info("local-alias datapath: %s", cfg.summary())
        await self.bring_up_no_cpu()

        pre = alias_probe_seq(cfg.access_addr)
        await self.start_seq(pre)
        assert pre.resp_ok, f"source 0x{cfg.access_addr:08x} resp not OKAY before remap"
        src_pre = pre.rdata & 0xFFFF_FFFF

        alias = SepLocalAlias(self)
        await alias._wr(cfg.expect_addr, cfg.marker)
        identity = alias_probe_seq(cfg.expect_addr)
        await self.start_seq(identity)
        assert identity.resp_ok, f"identity dest 0x{cfg.expect_addr:08x} resp not OKAY"
        dest_data = identity.rdata & 0xFFFF_FFFF
        assert dest_data == cfg.marker, (
            f"CLOCK_GATE_CTRL wrote 0x{cfg.marker:08x} read 0x{dest_data:08x}"
        )
        assert src_pre != dest_data, (
            f"CHK-OFFSET FAIL: source 0x{cfg.access_addr:08x}=0x{src_pre:08x} "
            f"already equals dest 0x{cfg.expect_addr:08x} -- vacuous"
        )
        # Park CLOCK_GATE_CTRL at a value other than the marker. The aliased
        # write below must then change it, which only a write that lands on
        # CLOCK_GATE_CTRL can do.
        await alias._wr(cfg.expect_addr, cfg.parked)
        parked = alias_probe_seq(cfg.expect_addr)
        await self.start_seq(parked)
        assert parked.resp_ok and (parked.rdata & 0xFFFF_FFFF) == cfg.parked, (
            f"CLOCK_GATE_CTRL wrote 0x{cfg.parked:08x} read "
            f"0x{parked.rdata & 0xFFFF_FFFF:08x} before the aliased write"
        )

        await alias.program(cfg)

        # A write hit places the four-bit region index in remap_debug_t[7:4].
        # Selecting region 8..15 makes the upper debug bits nonzero.
        await alias._wr(cfg.access_addr, cfg.marker)
        debug_raw = self.rd_known(cocotb.top.ext_debug_bus_o, 0xFFFF << 192)
        debug_lane = (debug_raw >> 192) & 0xFFFF
        assert (debug_lane >> 8) == 0, (
            f"remap debug lane reserved [15:8]=0x{debug_lane >> 8:02x}, expected 0"
        )
        assert ((debug_lane >> 4) & 0xF) == cfg.region, (
            f"remap debug AW index=0x{(debug_lane >> 4) & 0xF:x}, "
            f"expected region 0x{cfg.region:x} (lane=0x{debug_lane:04x})"
        )
        self.logger.info(
            "CHK-DEBUG-BUS PASS: lane[207:192]=0x%04x; reserved[15:8]=0, AW remap index[7:4]=0x%x",
            debug_lane,
            cfg.region,
        )

        landed = alias_probe_seq(cfg.expect_addr)
        await self.start_seq(landed)
        assert landed.resp_ok, f"identity dest 0x{cfg.expect_addr:08x} resp not OKAY"
        landed_data = landed.rdata & 0xFFFF_FFFF
        assert landed_data == cfg.marker, (
            f"CHK-OFFSET-WRITE FAIL: aliased write of 0x{cfg.marker:08x} to "
            f"0x{cfg.access_addr:08x} left identity CLOCK_GATE_CTRL "
            f"0x{cfg.expect_addr:08x} at 0x{landed_data:08x} (parked 0x{cfg.parked:08x}) "
            "-- the write landed somewhere else"
        )
        self.logger.info(
            "CHK-OFFSET-WRITE PASS: aliased write to 0x%08x moved identity "
            "CLOCK_GATE_CTRL 0x%08x from 0x%08x to 0x%08x",
            cfg.access_addr,
            cfg.expect_addr,
            cfg.parked,
            landed_data,
        )

        hit = alias_probe_seq(cfg.access_addr)
        await self.start_seq(hit)
        assert hit.resp_ok, f"remapped 0x{cfg.access_addr:08x} resp not OKAY"
        debug_lane = self.rd(cocotb.top.ext_debug_bus_o, mask=0xFFFF << 192) >> 192
        expected_debug_byte = (cfg.region << 4) | cfg.region
        assert debug_lane == expected_debug_byte, (
            f"remap debug lane=0x{debug_lane:04x}, expected reserved [15:8]=0, "
            f"AW index [7:4]=AR index [3:0]=0x{cfg.region:x}"
        )
        self.logger.info(
            "CHK-DEBUG-BUS-BYTE PASS: lane[207:192]=0x%04x; reserved[15:8]=0, "
            "AW index[7:4]=AR index[3:0]=0x%x",
            debug_lane,
            cfg.region,
        )
        got = hit.rdata & 0xFFFF_FFFF
        assert got == dest_data, (
            f"CHK-OFFSET FAIL: access 0x{cfg.access_addr:08x} read "
            f"0x{got:08x} != dest 0x{cfg.expect_addr:08x} "
            f"identity 0x{dest_data:08x}"
        )
        # The aliased read must follow CLOCK_GATE_CTRL when only the identity
        # address changes. A read that lands on the source page or on any
        # other register does not see this identity write.
        await alias._wr(cfg.expect_addr, cfg.parked)
        follow = alias_probe_seq(cfg.access_addr)
        await self.start_seq(follow)
        assert follow.resp_ok, f"remapped 0x{cfg.access_addr:08x} resp not OKAY"
        follow_data = follow.rdata & 0xFFFF_FFFF
        assert follow_data == cfg.parked, (
            f"CHK-OFFSET FAIL: after identity CLOCK_GATE_CTRL was set to "
            f"0x{cfg.parked:08x}, access 0x{cfg.access_addr:08x} read "
            f"0x{follow_data:08x} -- the aliased read does not track CLOCK_GATE_CTRL"
        )
        self.logger.info(
            "CHK-OFFSET PASS: remapped beat -> 0x%08x (aliased read 0x%08x then "
            "0x%08x tracks identity CLOCK_GATE_CTRL across an identity-only write)",
            cfg.expect_addr,
            got,
            follow_data,
        )
        # Restore the marker so the gated leg below compares against a
        # destination value that differs from the source's own value.
        await alias._wr(cfg.expect_addr, cfg.marker)
        # Same window, enable cleared: the beat must stay where it was issued.
        # src_pre is the pre-programming read of that address, and the vacuity
        # guard above already proved it differs from the remapped destination,
        # so this compare fails if the remap ignores region_valid.
        await alias.program(cfg, valid=False)
        gated = alias_probe_seq(cfg.access_addr)
        await self.start_seq(gated)
        assert gated.resp_ok, (
            f"CHK-VALID-GATE FAIL: 0x{cfg.access_addr:08x} resp not OKAY with "
            f"the region programmed and valid clear"
        )
        gated_data = gated.rdata & 0xFFFF_FFFF
        assert gated_data != dest_data, (
            f"CHK-VALID-GATE FAIL: access 0x{cfg.access_addr:08x} read "
            f"0x{gated_data:08x}, the remapped destination value, with "
            f"region {cfg.region} valid clear -- the enable does not gate"
        )
        assert gated_data == src_pre, (
            f"CHK-VALID-GATE FAIL: access 0x{cfg.access_addr:08x} read "
            f"0x{gated_data:08x} != 0x{src_pre:08x} read before the region "
            f"was programmed -- the beat did not pass through unchanged"
        )
        self.logger.info(
            "CHK-VALID-GATE PASS: region %d programmed with valid clear leaves "
            "0x%08x reading 0x%08x, its own value, not the remapped 0x%08x",
            cfg.region,
            cfg.access_addr,
            gated_data,
            dest_data,
        )

        # Config report, not a checker. The seed picks one region of the bank,
        # and a bound on an index the same seed generated cannot fail. What this
        # entry proves is asserted above, against the DUT.
        self.logger.info(
            "local-alias config: region=%d of %d src=0x%08x dest=0x%08x seed %d",
            cfg.region,
            N_REGIONS,
            cfg.access_addr,
            cfg.expect_addr,
            cfg.seed,
        )
