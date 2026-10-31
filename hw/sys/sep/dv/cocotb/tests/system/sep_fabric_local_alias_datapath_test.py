# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live local-master alias-remap offset on a real CPU-LSU beat.

RANDCFG. Distinct from the CPU high-alias window
(``sep_cpu_ifu_lsu_alias_remap_matrix_test``). Scope is the sixteen
programmable remap regions ahead of the system-peripherals routing
(``hw/sys/sep/doc/fabric.adoc``, "Address Remapping"). CSR R/W stays on
``sep_fabric_remap_filter_csr_bank_test``. This vehicle programs one
region and proves the offset in both directions: an aliased write moves
the identity ``CLOCK_GATE_CTRL`` readback from a parked value to the
marker, and an aliased read follows a later identity-only write.

CHK-VALID-GATE covers the enable. ``fabric.adoc`` ("Address Remapping")
states that an invalid remap entry behaves as a transparent pass-through,
so a window whose bounds and offset are programmed with the valid bit
clear must leave the beat at the address the master issued. Programming
the window and clearing only the enable is what separates a working gate
from an address that was never in range.

The cacheable flag that ``fabric.adoc`` lists per region is not checked
here: this bench has no observable on the outbound cache bits.

OBS-DBG-AR logs ``ext_debug_bus_o[207:192]`` after reads in two regions with
the write held, and after a write in the second region, without a verdict: no
document or RDL defines what the debug bus carries in that lane.

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

DBG_LANE_LSB = 192
DBG_LANE_MSB = 207


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
        park = (
            f"addr=0x{cfg.expect_addr:08x} wrote=0x{cfg.parked:08x} "
            f"read=0x{parked.rdata & 0xFFFF_FFFF:08x} resp_ok={int(parked.resp_ok)}"
        )
        # Same text as SepChkLog.ctrl(): CHK-OFFSET-WRITE needs CLOCK_GATE_CTRL
        # parked away from the marker, so a missing park fails the leaf.
        if not (parked.resp_ok and (parked.rdata & 0xFFFF_FFFF) == cfg.parked):
            self.logger.error("CTRL-MISSING OFFSET-PARK: %s", park)
            raise AssertionError(f"CTRL-MISSING OFFSET-PARK: {park}")
        self.logger.info("CTRL-OFFSET-PARK seen: %s", park)

        await alias.program(cfg)

        await alias._wr(cfg.access_addr, cfg.marker)

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
        restored = alias_probe_seq(cfg.expect_addr)
        await self.start_seq(restored)
        restore = (
            f"addr=0x{cfg.expect_addr:08x} wrote=0x{cfg.marker:08x} "
            f"read=0x{restored.rdata & 0xFFFF_FFFF:08x} resp_ok={int(restored.resp_ok)}"
        )
        # Same text as SepChkLog.ctrl(): CHK-VALID-GATE needs the destination
        # at the marker, which differs from src_pre, so a missing restore fails
        # the leaf.
        if not (restored.resp_ok and (restored.rdata & 0xFFFF_FFFF) == cfg.marker):
            self.logger.error("CTRL-MISSING VALID-GATE-RESTORE: %s", restore)
            raise AssertionError(f"CTRL-MISSING VALID-GATE-RESTORE: {restore}")
        self.logger.info("CTRL-VALID-GATE-RESTORE seen: %s", restore)
        # Same window, enable cleared: the beat must stay where it was issued.
        # src_pre is the pre-programming read of that address, and the vacuity
        # guard above proved it differs from the marker the destination now
        # holds, so this compare fails if the remap ignores the valid bit.
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

        await self._obs_dbg_ar(alias, cfg)

        self.logger.info(
            "local-alias config: region=%d of %d src=0x%08x dest=0x%08x seed %d",
            cfg.region,
            N_REGIONS,
            cfg.access_addr,
            cfg.expect_addr,
            cfg.seed,
        )

    def _lane(self) -> str:
        """``ext_debug_bus_o[207:192]`` as a bit string, X and Z kept."""
        v = cocotb.top.ext_debug_bus_o.value
        bits = getattr(v, "binstr", None) or str(v)
        return bits[len(bits) - DBG_LANE_MSB - 1 : len(bits) - DBG_LANE_LSB]

    async def _obs_dbg_ar(self, alias: SepLocalAlias, cfg: SepLocalAliasCfg) -> None:
        """OBS-DBG-AR: the lane after reads in two regions and after a write."""
        sib = SepLocalAliasCfg(cfg.seed, sibling_of=cfg)
        self.logger.info("local-alias debug: second window %s", sib.summary())
        await alias.program(cfg)
        await alias.program(sib)
        # One write in region cfg.region, then reads in two different regions
        # with no write in between.
        await alias._wr(cfg.access_addr, cfg.marker)
        lanes = []
        for c in (cfg, sib):
            rd = alias_probe_seq(c.access_addr)
            await self.start_seq(rd)
            assert rd.resp_ok, f"CHK-OFFSET FAIL: remapped 0x{c.access_addr:08x} resp not OKAY"
            assert (rd.rdata & 0xFFFF_FFFF) == cfg.marker, (
                f"CHK-OFFSET FAIL: region {c.region} read 0x{rd.rdata & 0xFFFF_FFFF:08x} "
                f"!= marker 0x{cfg.marker:08x} -- the read did not hit its window"
            )
            lanes.append(self._lane())
        await alias._wr(sib.access_addr, cfg.marker)
        rd = alias_probe_seq(sib.access_addr)
        await self.start_seq(rd)
        assert rd.resp_ok, f"CHK-OFFSET FAIL: remapped 0x{sib.access_addr:08x} resp not OKAY"
        self.logger.info(
            "OBS-DBG-AR: write region=%d read region=%d lane=%s read region=%d lane=%s "
            "write region=%d read region=%d lane=%s",
            cfg.region,
            cfg.region,
            lanes[0],
            sib.region,
            lanes[1],
            sib.region,
            sib.region,
            self._lane(),
        )
