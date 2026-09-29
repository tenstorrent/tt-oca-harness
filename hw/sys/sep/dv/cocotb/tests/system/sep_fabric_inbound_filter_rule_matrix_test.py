# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound-filter per-entry RULE matrix.

With the SEP inbound filter ACTIVE (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs inbound FILTER_CONFIG allow-entries and the EXTERNAL SMN
master (m_axi, the only path through u_inbound_filter) proves per-entry rule
enforcement: an allowed address -> OKAY + exact CSR value; any other address ->
DECERR, never the value staged there (block-by-default); read_allowed/write_allowed gate the matched
read/write. With smc_global_base=0 the inbound global->local remap is identity, so
the external master drives the SEP-local address directly.

Walks entries 0 and 7 x two address windows x {rw, read-only,
write-only} at src_id=0 (match-all), plus entry 0 / window 0 x {rw, r, w} at
src_id=5 with a matching AXI user and one src-mismatch cell. SepInboundFilterMatrixCfg
is the single source of truth. Stays at sep_debug=0 the whole time and proves
the PER-ENTRY allow-by-rule vs block-by-default policy, not the global
sep_debug skip gate (sep_lcc_uvm_inbound_filter_gating_test).

CHK-OWNERSHIP ports the CPU-vs-external asymmetry at the CSRs that
reposition the inbound remap or program a filter: inbound CFG, outbound
CFG[0], alias/AP/STEE remap bases, SEP_GLOBAL_BASE_ADDR, and
SEP_REGION_SIZE. CPU-LSU reads each register; the external master
completes DECERR on read and write; the denied write does not land.
That is the spec's "only the SEP CPU can program these filters" under
correct programming (those CSRs stay outside every allow window).
Firmware must not allow-list them; HW does not hard-block that SW hole,
so this test never opens one. SEP_GLOBAL_BASE_ADDR and SEP_REGION_SIZE
share the window-0 (SEP_SW_DEBUG) 4 KB page, so they also prove the
live window is START/END, not the page.

CHK-BURST-DENY / CHK-BURST-ALLOW and CHK-BURST-WRITE-DENY /
CHK-BURST-WRITE-ALLOW walk FILTER_CONFIG.allow_burst (bit 24) on both
traffic_filter instances (AR and AW). Every other access is a single
beat (AxLEN=0), so ``pass_burst = cfg_burst_en | (tx_len == 0)`` is
otherwise always true. Each deny cell is anti-vacuous: a single-beat
access of the same scratch window is OKAY, then a 2-beat INCR is DECERR
(and a denied write does not land). Each allow cell programs a window
that already spans two 4 KB pages so axi_filter_wrap.sv's same-page
widen does not fire; the checker asserts the programmed range.
CHK-BURST-TO-SINGLE watches the system-CSR AXI-Lite AR/AW after
``u_system_csr_a2l_1``: a denied AxLEN=1 produces zero Lite handshakes
(filter before the converter); an allowed AxLEN=1 produces two Lite
singles (fabric.adoc convert burst to single). WRAP/FIXED/AxLEN>1 are
not walked.
CHK-PAGE-WIDEN / CHK-PAGE-BOUND / CHK-CONFIG-LOCK cover the same-page
allow_burst=1 window on entry 15. An 8-byte window inside the
dual-scratch page (0x1080_2000) is rewritten by axi_filter_wrap.sv to the
whole page, and traffic_filter.sv then compares only addr[AddrWidth-1:12].
CHK-PAGE-WIDEN proves the 4 KB page grant ON THE BUS
(hw/ip/axi_filter/doc/index.adoc: START down, END up):
an external access to an address inside the granted page but OUTSIDE the
programmed START..END is OKAY for read and write, with the exact staged
value.
CHK-PAGE-BOUND is the security contract: memory_map.adoc packs distinct
blocks of this aperture at the same 4 KB pitch (DMA CSR 0x1080_0000, WDT
0x1080_1000, dual scratch banks 0x1080_2000), so a page-crossing grant would
hand access to a neighbouring block. The boundary at 0x1080_2000 is proven
from both sides: a WDT register one page below is DECERR under the
scratch-page grant, then the WDT page becomes the granted one, which answers
that WDT probe and turns the scratch register DECERR. Each probe is therefore
proven reachable, so neither DECERR can be an address-decode hole.
CHK-CONFIG-LOCK sets FILTER_CONFIG.locked (bit 63) and proves allow_burst
cannot move. fabric.adoc specifies the lock as write-once, so the field must
not change once set; it does not say how the refused write completes, so the
cell requires only that the write completes (no timeout). The field reads back
unchanged and the frozen bit still grants the widened page. The lock is sticky until reset,
so this cell runs last on entry 15.

RUN-MODE: no_cpu + external SMN master. FUSE-MODE: real PROD fuse sense (sep_debug=0
=> filter active). RAND-REP (entry x window x R/W-allow x src-id class; window
values from seed).
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import F_ALLOW_BURST, FILTER_RW_MASK
from seq_lib.sep_inbound_filter_rule_seq import (
    FILTER_LOCKED_HI_BIT,
    GRANULE_BYTES,
    PAGE_SHIFT,
    PAGE_SIZE,
    RESP_DECERR,
    RESP_OKAY,
    SepInboundFilter,
    SepInboundFilterCfg,
    SepInboundFilterMatrixCfg,
    ext_burst_read_seq,
    ext_burst_write_seq,
    ext_read_seq,
    ext_write_seq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_MAX_SENSE_CYCLES = 20_000
# Distinct non-zero disable vectors so the decoded FEAT_CTRL is non-vacuous.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF


@pyuvm.test()
class sep_fabric_inbound_filter_rule_matrix_test(sep_base_test):
    """Per-entry inbound-filter allow-rule vs block-by-default, via the external master."""

    async def _ext_read(self, addr: int, *, user: int = 0) -> tuple[int, int]:
        seq = ext_read_seq(addr, user=user)
        await self.start_ext_seq(seq)
        return seq.resp_code, (seq.rdata & 0xFFFF_FFFF)

    async def _assert_ext_deny_read(
        self, addr: int, *, user: int = 0, tag: str = "deny", staged: int | None = None
    ) -> int:
        """Require DECERR and, when the live value is known, that it is not returned.

        ``hw/ip/axi_filter/doc/index.adoc`` (Blocked Transactions) steers a
        blocked access to an error subordinate and names DECERR, not the read
        data. So the data conjunct is the absence of the protected value: an
        access that reached the target would hand back ``staged``, which the
        allow leg proves readable.
        """
        resp, data = await self._ext_read(addr, user=user)
        assert resp == RESP_DECERR, f"{tag}: ext read 0x{addr:08x} resp={resp}, expected DECERR"
        if staged is not None:
            assert data != staged & 0xFFFF_FFFF, (
                f"{tag}: denied ext read 0x{addr:08x} returned the live value "
                f"0x{data:08x}; the blocked access reached the target"
            )
        return data

    async def _ext_write(self, addr: int, data: int, *, user: int = 0) -> int:
        seq = ext_write_seq(addr, data, user=user)
        await self.start_ext_seq(seq)
        return seq.resp_code

    async def _ext_burst_read(self, addr: int, *, expect_error: bool = False) -> tuple[int, int]:
        seq = ext_burst_read_seq(addr, expect_error=expect_error)
        await self.start_ext_seq(seq)
        return seq.resp_code, (seq.rdata & 0xFFFF_FFFF)

    async def _ext_burst_write(self, addr: int, data: int, *, expect_error: bool = False) -> int:
        seq = ext_burst_write_seq(addr, data, expect_error=expect_error)
        await self.start_ext_seq(seq)
        return seq.resp_code

    async def _ext_burst_read_watch(
        self, addr: int, *, expect_error: bool = False
    ) -> tuple[int, int, list[int]]:
        task, addrs = self.watch_sys_csr_lite(write=False)
        try:
            resp, data = await self._ext_burst_read(addr, expect_error=expect_error)
        finally:
            task.kill()
        return resp, data, list(addrs)

    async def _ext_burst_write_watch(
        self, addr: int, data: int, *, expect_error: bool = False
    ) -> tuple[int, list[int]]:
        task, addrs = self.watch_sys_csr_lite(write=True)
        try:
            resp = await self._ext_burst_write(addr, data, expect_error=expect_error)
        finally:
            task.kill()
        return resp, list(addrs)

    def _expect_lite_split(self, addrs: list[int], *, start: int, nbeats: int, tag: str) -> None:
        """AxLEN=N-1 INCR of 4-byte beats becomes N AXI-Lite singles."""
        expected = [start + i * 4 for i in range(nbeats)]
        assert addrs == expected, (
            f"{tag}: Lite singles {[hex(a) for a in addrs]} != "
            f"{[hex(a) for a in expected]} (fabric.adoc convert burst to single)"
        )

    async def _check_burst_dimension(self, mcfg: SepInboundFilterMatrixCfg) -> None:
        """Walk allow_burst deny then allow on the scratch window.

        Runs after the single-beat matrix and before ownership.
        CHK-CONFIG-LOCK is sticky, so the lock cell runs last on entry 15.
        """
        burst_addr, burst_val, burst_end = mcfg.burst_window()
        await self.filt.stage_target(burst_addr, burst_val)

        await self.filt.disable_all()
        burst_cfg = SepInboundFilterCfg(entry=0, allow_addr=burst_addr, allow_value=burst_val)
        await self.filt.program_rule(
            burst_cfg, read_allowed=True, write_allowed=True, allow_burst=False
        )

        resp, data = await self._ext_read(burst_addr)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-DENY: single-beat read of 0x{burst_addr:08x} "
            f"resp={resp}, expected OKAY (anti-vacuous)"
        )
        assert data == burst_val, (
            f"CHK-BURST-DENY: single-beat rdata 0x{data:08x} != staged 0x{burst_val:08x}"
        )
        resp, data, lite_ar = await self._ext_burst_read_watch(burst_addr, expect_error=True)
        assert resp == RESP_DECERR, (
            f"CHK-BURST-DENY FAIL: allow_burst=0 2-beat INCR read of "
            f"0x{burst_addr:08x} resp={resp}, expected DECERR"
        )
        assert data != burst_val, (
            f"CHK-BURST-DENY FAIL: denied burst returned the staged value "
            f"0x{data:08x}; the blocked burst reached the target"
        )
        self._expect_lite_split(
            lite_ar, start=burst_addr, nbeats=0, tag="CHK-BURST-TO-SINGLE deny AR"
        )
        self.logger.info(
            "CHK-BURST-DENY PASS: allow_burst=0 single-beat OKAY rdata=0x%08x; "
            "2-beat INCR DECERR at 0x%08x",
            burst_val,
            burst_addr,
        )

        await self.filt.disable_all()
        await self.filt.program_rule(
            burst_cfg, read_allowed=True, write_allowed=True, allow_burst=True, end_addr=burst_end
        )
        start_rb = await self.filt.read_cpu(burst_cfg.start_addr_reg)
        end_rb = await self.filt.read_cpu(burst_cfg.end_addr_reg)
        assert start_rb == burst_addr, (
            f"CHK-BURST-ALLOW: START_ADDR 0x{start_rb:08x} != programmed 0x{burst_addr:08x}"
        )
        assert end_rb == burst_end, (
            f"CHK-BURST-ALLOW: END_ADDR 0x{end_rb:08x} != programmed "
            f"0x{burst_end:08x} (page-widen must not fire)"
        )
        assert (burst_addr >> 12) != (burst_end >> 12), (
            f"CHK-BURST-ALLOW: window 0x{burst_addr:08x}..0x{burst_end:08x} shares a 4 KB page"
        )
        cfg_rb = await self.filt.read_cpu(burst_cfg.cfg_addr)
        expected_cfg = burst_cfg.config_word(
            read_allowed=True, write_allowed=True, allow_burst=True
        )
        assert (cfg_rb & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
            f"CHK-BURST-ALLOW: FILTER_CONFIG rw 0x{cfg_rb & FILTER_RW_MASK:08x} "
            f"!= 0x{expected_cfg & FILTER_RW_MASK:08x}"
        )
        resp, data, lite_ar = await self._ext_burst_read_watch(burst_addr)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-ALLOW FAIL: allow_burst=1 2-beat INCR read of "
            f"0x{burst_addr:08x} resp={resp}, expected OKAY"
        )
        assert data == burst_val, (
            f"CHK-BURST-ALLOW FAIL: burst rdata 0x{data:08x} != staged 0x{burst_val:08x}"
        )
        self._expect_lite_split(
            lite_ar, start=burst_addr, nbeats=2, tag="CHK-BURST-TO-SINGLE allow AR"
        )
        self.logger.info(
            "CHK-BURST-ALLOW PASS: allow_burst=1 START=0x%08x END=0x%08x "
            "(two pages); 2-beat INCR OKAY rdata=0x%08x",
            start_rb,
            end_rb,
            data,
        )
        self.logger.info(
            "CHK-BURST-TO-SINGLE PASS: AxLEN=1 read -> %d Lite AR %s (denied burst -> 0 Lite AR)",
            len(lite_ar),
            [hex(a) for a in lite_ar],
        )

        poke_sb = burst_val ^ 0x00FF_FF00
        poke_burst = burst_val ^ 0xFFFF_0000
        if poke_sb == burst_val:
            poke_sb ^= 1
        if poke_burst == burst_val:
            poke_burst ^= 1

        await self.filt.disable_all()
        await self.filt.stage_target(burst_addr, burst_val)
        await self.filt.program_rule(
            burst_cfg, read_allowed=True, write_allowed=True, allow_burst=False
        )
        resp = await self._ext_write(burst_addr, poke_sb)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-WRITE-DENY: single-beat write of 0x{burst_addr:08x} "
            f"resp={resp}, expected OKAY (anti-vacuous)"
        )
        landed = await self.filt.read_cpu(burst_addr)
        assert landed == poke_sb, (
            f"CHK-BURST-WRITE-DENY: single-beat write did not land "
            f"(0x{landed:08x} != 0x{poke_sb:08x})"
        )
        await self.filt.stage_target(burst_addr, burst_val)
        resp, lite_aw = await self._ext_burst_write_watch(burst_addr, poke_burst, expect_error=True)
        assert resp == RESP_DECERR, (
            f"CHK-BURST-WRITE-DENY FAIL: allow_burst=0 2-beat INCR write of "
            f"0x{burst_addr:08x} resp={resp}, expected DECERR"
        )
        self._expect_lite_split(
            lite_aw, start=burst_addr, nbeats=0, tag="CHK-BURST-TO-SINGLE deny AW"
        )
        after = await self.filt.read_cpu(burst_addr)
        assert after == burst_val, (
            f"CHK-BURST-WRITE-DENY FAIL: denied burst write landed "
            f"(0x{after:08x} != staged 0x{burst_val:08x})"
        )
        self.logger.info(
            "CHK-BURST-WRITE-DENY PASS: allow_burst=0 single-beat write OKAY "
            "and landed; 2-beat INCR DECERR and did not land at 0x%08x",
            burst_addr,
        )

        await self.filt.disable_all()
        await self.filt.program_rule(
            burst_cfg, read_allowed=True, write_allowed=True, allow_burst=True, end_addr=burst_end
        )
        start_rb = await self.filt.read_cpu(burst_cfg.start_addr_reg)
        end_rb = await self.filt.read_cpu(burst_cfg.end_addr_reg)
        assert start_rb == burst_addr, (
            f"CHK-BURST-WRITE-ALLOW: START_ADDR 0x{start_rb:08x} != programmed 0x{burst_addr:08x}"
        )
        assert end_rb == burst_end, (
            f"CHK-BURST-WRITE-ALLOW: END_ADDR 0x{end_rb:08x} != programmed "
            f"0x{burst_end:08x} (page-widen must not fire)"
        )
        resp, lite_aw = await self._ext_burst_write_watch(burst_addr, poke_burst)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-WRITE-ALLOW FAIL: allow_burst=1 2-beat INCR write of "
            f"0x{burst_addr:08x} resp={resp}, expected OKAY"
        )
        landed = await self.filt.read_cpu(burst_addr)
        assert landed == poke_burst, (
            f"CHK-BURST-WRITE-ALLOW FAIL: burst write did not land "
            f"(0x{landed:08x} != 0x{poke_burst:08x})"
        )
        self._expect_lite_split(
            lite_aw, start=burst_addr, nbeats=2, tag="CHK-BURST-TO-SINGLE allow AW"
        )
        await self.filt.stage_target(burst_addr, burst_val)
        self.logger.info(
            "CHK-BURST-WRITE-ALLOW PASS: allow_burst=1 START=0x%08x END=0x%08x "
            "(two pages); 2-beat INCR write OKAY and landed 0x%08x",
            start_rb,
            end_rb,
            poke_burst,
        )
        self.logger.info(
            "CHK-BURST-TO-SINGLE PASS: AxLEN=1 write -> %d Lite AW %s (denied burst -> 0 Lite AW)",
            len(lite_aw),
            [hex(a) for a in lite_aw],
        )
        self.logger.info(
            "CHK-BURST-WALK PASS: allow_burst deny + allow walked on AR and AW "
            "of the scratch window"
        )

    async def _check_page_widen(self, mcfg: SepInboundFilterMatrixCfg) -> None:
        """Measure the same-page allow_burst=1 widen and its bounds, then lock it.

        Runs LAST: FILTER_CONFIG.locked is sticky until reset, so once this cell
        locks its entry no later step may reprogram or disable that entry.
        """
        wcfg = mcfg.widen
        cell = SepInboundFilterCfg(
            entry=wcfg.entry, allow_addr=wcfg.window_addr, allow_value=wcfg.values[0]
        )

        async def restage() -> None:
            for addr, val in wcfg.staged:
                await self.filt.stage_target(addr, val)

        async def program_widen() -> None:
            await self.filt.program_rule(
                cell,
                read_allowed=True,
                write_allowed=True,
                allow_burst=True,
                end_addr=wcfg.window_end,
                expect_page_widen=True,
            )

        await restage()
        await self.filt.disable_all()
        await program_widen()

        start_rb = await self.filt.read_cpu(cell.start_addr_reg)
        end_rb = await self.filt.read_cpu(cell.end_addr_reg)
        assert start_rb == wcfg.page_base, (
            f"CHK-PAGE-WIDEN FAIL: START_ADDR 0x{start_rb:08x} != page base "
            f"0x{wcfg.page_base:08x} (programmed 0x{wcfg.window_addr:08x})"
        )
        assert end_rb == wcfg.page_end, (
            f"CHK-PAGE-WIDEN FAIL: END_ADDR 0x{end_rb:08x} != page end "
            f"0x{wcfg.page_end:08x} (programmed 0x{wcfg.window_end:08x})"
        )
        granted = end_rb - start_rb + 1
        assert granted == PAGE_SIZE, (
            f"CHK-PAGE-WIDEN FAIL: granted extent {granted} B != one 4 KB page"
        )

        resp, data = await self._ext_read(wcfg.window_addr)
        assert resp == RESP_OKAY, (
            f"CHK-PAGE-WIDEN FAIL: read inside the programmed window "
            f"0x{wcfg.window_addr:08x} resp={resp}, expected OKAY (positive control)"
        )
        assert data == wcfg.values[0], (
            f"CHK-PAGE-WIDEN FAIL: in-window rdata 0x{data:08x} != staged 0x{wcfg.values[0]:08x}"
        )

        # The widen, observed: an address in the same page but outside the
        # programmed START..END is granted for read AND write.
        for addr, val in wcfg.staged[1:]:
            assert not (wcfg.window_addr <= addr <= wcfg.window_end), (
                f"CHK-PAGE-WIDEN: probe 0x{addr:08x} is inside the programmed "
                f"window 0x{wcfg.window_addr:08x}..0x{wcfg.window_end:08x}"
            )
            resp, data = await self._ext_read(addr)
            assert resp == RESP_OKAY, (
                f"CHK-PAGE-WIDEN FAIL: 0x{addr:08x} is outside the programmed "
                f"window but inside its 4 KB page, resp={resp}, expected OKAY "
                f"(the widen must grant the whole page)"
            )
            assert data == val, (
                f"CHK-PAGE-WIDEN FAIL: rdata 0x{data:08x} != staged 0x{val:08x} at 0x{addr:08x}"
            )
            poke = val ^ 0xFFFF_0000
            resp = await self._ext_write(addr, poke)
            assert resp == RESP_OKAY, (
                f"CHK-PAGE-WIDEN FAIL: write of 0x{addr:08x} (widened grant) "
                f"resp={resp}, expected OKAY"
            )
            landed = await self.filt.read_cpu(addr)
            assert landed == poke, (
                f"CHK-PAGE-WIDEN FAIL: widened-grant write did not land "
                f"(0x{landed:08x} != 0x{poke:08x})"
            )
        await restage()

        probes = [wcfg.window_addr] + wcfg.in_page_addrs
        self.logger.info(
            "CHK-PAGE-WIDEN PASS: programmed 0x%08x..0x%08x (%d B) -> HW readback "
            "0x%08x..0x%08x, measured granted extent %d B (one 4 KB page); probes "
            "OKAY at %s, of which %s lie outside the programmed range",
            wcfg.window_addr,
            wcfg.window_end,
            GRANULE_BYTES,
            start_rb,
            end_rb,
            granted,
            [hex(a) for a in probes],
            [hex(a) for a in wcfg.in_page_addrs],
        )

        # The grant must stop at the page edge. The boundary at 0x1080_2000 is
        # proven from both sides so neither probe rests on an unproven decode: the
        # WDT register one page below is denied while the scratch page is granted,
        # then the WDT page becomes the granted one -- which answers the WDT probe
        # and denies the scratch register that was OKAY a moment ago.
        adj = wcfg.adj_addr
        rev = wcfg.in_page_addrs[0]
        assert (adj >> 12) + 1 == (wcfg.page_base >> 12), (
            f"CHK-PAGE-BOUND: 0x{adj:08x} is not the page below 0x{wcfg.page_base:08x}"
        )
        await self._assert_ext_deny_read(
            adj,
            tag=(
                f"CHK-PAGE-BOUND FAIL: 0x{adj:08x} is in the page below the granted "
                f"0x{start_rb:08x}..0x{end_rb:08x}"
            ),
        )
        await self.filt.disable_all()
        adj_cell = SepInboundFilterCfg(entry=wcfg.entry, allow_addr=adj, allow_value=0)
        await self.filt.program_rule(
            adj_cell,
            read_allowed=True,
            write_allowed=False,
            allow_burst=True,
            end_addr=adj + GRANULE_BYTES - 1,
            expect_page_widen=True,
        )
        resp, _ = await self._ext_read(adj)
        assert resp == RESP_OKAY, (
            f"CHK-PAGE-BOUND: 0x{adj:08x} resp={resp} with its own page granted, "
            f"expected OKAY (so the DECERR above is the filter, not a decode hole)"
        )
        await self._assert_ext_deny_read(
            rev,
            staged=dict(wcfg.staged)[rev],
            tag=(
                f"CHK-PAGE-BOUND FAIL: 0x{rev:08x} is in the page above the granted "
                f"WDT page 0x{adj & ~0xFFF:08x}"
            ),
        )
        self.logger.info(
            "CHK-PAGE-BOUND PASS: grant 0x%08x..0x%08x denies 0x%08x one page "
            "below; with 0x%08x's own page granted it answers OKAY and 0x%08x one "
            "page above turns DECERR -- the 4 KB grant stops at both page edges",
            start_rb,
            end_rb,
            adj,
            adj,
            rev,
        )

        await self.filt.disable_all()
        await restage()
        await program_widen()
        cfg_lo = await self.filt.read_cpu(cell.cfg_addr)
        assert cfg_lo & F_ALLOW_BURST, (
            f"CHK-CONFIG-LOCK: allow_burst not set before the lock "
            f"(FILTER_CONFIG lo 0x{cfg_lo:08x})"
        )
        await self.filt.lock_entry(wcfg.entry)
        hi = await self.filt.read_cpu(cell.cfg_addr + 4)
        assert (hi >> FILTER_LOCKED_HI_BIT) & 1, (
            f"CHK-CONFIG-LOCK FAIL: locked did not set (hi 0x{hi:08x})"
        )
        resp = await self.filt.write_tolerant(cell.cfg_addr, cfg_lo & ~F_ALLOW_BURST & 0xFFFF_FFFF)
        after = await self.filt.read_cpu(cell.cfg_addr)
        assert after == cfg_lo, (
            f"CHK-CONFIG-LOCK FAIL: FILTER_CONFIG moved under the lock "
            f"(0x{after:08x} != 0x{cfg_lo:08x}); allow_burst is "
            f"{bool(after & F_ALLOW_BURST)}, was {bool(cfg_lo & F_ALLOW_BURST)}"
        )
        resp_hi = await self.filt.write_tolerant(cell.cfg_addr + 4, 0)
        hi_after = await self.filt.read_cpu(cell.cfg_addr + 4)
        assert (hi_after >> FILTER_LOCKED_HI_BIT) & 1, (
            f"CHK-CONFIG-LOCK FAIL: locked cleared (hi 0x{hi_after:08x})"
        )
        # The frozen bit still drives the hardware, not just the CSR readback.
        probe_addr, probe_val = wcfg.staged[1]
        resp, data = await self._ext_read(probe_addr)
        assert resp == RESP_OKAY and data == probe_val, (
            f"CHK-CONFIG-LOCK FAIL: frozen allow_burst stopped granting the page "
            f"(0x{probe_addr:08x} resp={resp} rdata=0x{data:08x}, staged "
            f"0x{probe_val:08x})"
        )
        self.logger.info(
            "CHK-CONFIG-LOCK PASS: entry %d locked -- clearing allow_burst (resp=%d) "
            "leaves FILTER_CONFIG lo 0x%08x (allow_burst=%d), clearing locked "
            "(resp=%d) leaves the bit set, and the frozen granule still grants 0x%08x",
            wcfg.entry,
            resp,
            after,
            bool(after & F_ALLOW_BURST),
            resp_hi,
            probe_addr,
        )

    async def _bring_up_prod_filter_active(self) -> None:
        """Real-sense a PROD image -> sep_debug=0 (inbound filter active)."""
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        # select_efuse_image pins lc_raw to LC_PROD, so the DUT-side evidence that
        # PROD took effect is the FEAT_CTRL read below, value-checked against
        # feat_ctrl_expected.
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        # security_disable read from the DUT rather than passed as a literal. This
        # entry value-checks FEAT_CTRL against the lifecycle golden, so every
        # input to that golden should be observed where it can be; sec_dis can be, via
        # lcc_security_disable_probe_o.
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert ctl.sep_debug == 0, (
            f"sep_debug must be 0 (filter active) in PROD, got {ctl.sep_debug} "
            f"(FEAT_CTRL=0x{ctl.feat_ctrl:016x})"
        )
        self.logger.info("inbound filter ACTIVE: %s sep_debug=0", lc_state_name(image.lc_raw()))

    async def run_scenario(self) -> None:
        mcfg = SepInboundFilterMatrixCfg.from_seed(self.random_seed())
        self.logger.info("inbound-filter matrix: %s", mcfg.summary())

        await self._bring_up_prod_filter_active()
        self.filt = SepInboundFilter(self)

        for addr, val in mcfg.windows:
            await self.filt.stage_target(addr, val)
            staged = await self.filt.read_cpu(addr)
            assert staged == val, f"staged target 0x{addr:08x}=0x{staged:08x} != 0x{val:08x}"

        first = True
        deny_rule_logged = False
        src_match_logged = False
        src_mismatch_logged = False
        walked = 0
        for (
            entry,
            widx,
            mode,
            addr,
            val,
            read_ok,
            write_ok,
            src_class,
            cfg_src_id,
            axi_user,
            expect_hit,
        ) in mcfg.cells():
            walked += 1
            await self.filt.disable_all()
            cell = SepInboundFilterCfg(entry=entry, allow_addr=addr, allow_value=val)
            cell.src_id = cfg_src_id
            await self.filt.program_rule(cell, read_allowed=read_ok, write_allowed=write_ok)

            if not expect_hit:
                await self._assert_ext_deny_read(
                    addr,
                    user=axi_user,
                    staged=val,
                    tag=f"cell entry={entry} w{widx} {mode} {src_class}: src mismatch read",
                )
                resp = await self._ext_write(addr, 0x5555_AAAA, user=axi_user)
                assert resp == RESP_DECERR, (
                    f"cell entry={entry} w{widx} {mode} {src_class}: "
                    f"src mismatch write resp={resp}, expected DECERR"
                )
                if not src_mismatch_logged:
                    self.logger.info(
                        "CHK-SRC-ID PASS: cfg_src_id=0x%x user=0x%x -> DECERR "
                        "(mismatch; allow bits do not apply)",
                        cfg_src_id,
                        axi_user,
                    )
                    src_mismatch_logged = True
            else:
                if read_ok:
                    resp, data = await self._ext_read(addr, user=axi_user)
                    assert resp == RESP_OKAY, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"allowed ext read resp={resp}"
                    )
                    assert data == val, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"ext read 0x{data:08x} != staged 0x{val:08x}"
                    )
                    if first:
                        self.logger.info(
                            "CHK-ALLOW-RULE PASS: ext read 0x%08x -> OKAY, rdata=0x%08x", addr, data
                        )
                else:
                    data = await self._assert_ext_deny_read(
                        addr,
                        user=axi_user,
                        staged=val,
                        tag=f"cell entry={entry} w{widx} {mode} {src_class}: read_allowed=0",
                    )
                    if not deny_rule_logged:
                        self.logger.info(
                            "CHK-ALLOW-RULE PASS: denied ext read 0x%08x -> DECERR, "
                            "rdata=0x%08x (not the staged value)",
                            addr,
                            data,
                        )
                        deny_rule_logged = True

                if write_ok:
                    poke = val ^ 0xFFFF_0000
                    resp = await self._ext_write(addr, poke, user=axi_user)
                    assert resp == RESP_OKAY, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"allowed ext write resp={resp}"
                    )
                    landed = await self.filt.read_cpu(addr)
                    assert landed == poke, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"ext write did not land (0x{landed:08x})"
                    )
                    await self.filt.stage_target(addr, val)
                else:
                    resp = await self._ext_write(addr, 0x5555_AAAA, user=axi_user)
                    assert resp == RESP_DECERR, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"write_allowed=0 got resp={resp}"
                    )
                if src_class == "match" and not src_match_logged:
                    self.logger.info(
                        "CHK-SRC-ID PASS: cfg_src_id=0x%x user=0x%x matched "
                        "(exact source-ID, r/w allow bits still apply)",
                        cfg_src_id,
                        axi_user,
                    )
                    src_match_logged = True

            data = await self._assert_ext_deny_read(
                mcfg.blocked_addr,
                user=axi_user,
                tag=(
                    f"cell entry={entry} w{widx} {mode} {src_class}: "
                    f"blocked 0x{mcfg.blocked_addr:08x}"
                ),
            )
            if first:
                self.logger.info(
                    "CHK-BLOCK-DEFAULT PASS: ext read 0x%08x -> DECERR, "
                    "rdata=0x%08x (block-by-default)",
                    mcfg.blocked_addr,
                    data,
                )
            if expect_hit and mode == "r":
                self.logger.info(
                    "CHK-WRITE-ALLOWED PASS: write_allowed gates the matched ext write "
                    "(DECERR) entry=%d window=%d src=%s",
                    entry,
                    widx,
                    src_class,
                )
                self.logger.info(
                    "CHK-READ-ALLOWED PASS: read_allowed gates the matched ext read "
                    "(OKAY) entry=%d window=%d src=%s",
                    entry,
                    widx,
                    src_class,
                )
            if expect_hit and mode == "w":
                self.logger.info(
                    "CHK-READ-ALLOWED PASS: read_allowed gates the matched ext read "
                    "(DECERR) entry=%d window=%d src=%s",
                    entry,
                    widx,
                    src_class,
                )
                self.logger.info(
                    "CHK-WRITE-ALLOWED PASS: write_allowed gates the matched ext write "
                    "(OKAY) entry=%d window=%d src=%s",
                    entry,
                    widx,
                    src_class,
                )
            self.logger.info(
                "CHK-CELL PASS: entry=%d window=%d mode=%s src=%s addr=0x%08x",
                entry,
                widx,
                mode,
                src_class,
                addr,
            )
            first = False

        assert walked == mcfg.n_cells(), (
            f"CHK-RAND-REP FAIL: walked {walked} cells, n_cells()={mcfg.n_cells()}"
        )
        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells "
            "(entries %s x %d windows x rw/r/w match-all + "
            "entry0/window0 x rw/r/w match + 1 mismatch)",
            walked,
            list(mcfg.entries),
            len(mcfg.windows),
        )

        await self._check_burst_dimension(mcfg)

        # Restore entry 0 / window A / rw for the ownership checks.
        await self.filt.disable_all()
        win0_addr, win0_val = mcfg.windows[0]
        self.fcfg = SepInboundFilterCfg(entry=0, allow_addr=win0_addr, allow_value=win0_val)
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=True)

        win_start = await self.filt.read_cpu(self.fcfg.start_addr_reg)
        win_end = await self.filt.read_cpu(self.fcfg.end_addr_reg)
        expected_cfg = self.fcfg.config_word(read_allowed=True, write_allowed=True)
        names = []
        for name, addr in mcfg.ownership_targets(self.fcfg.cfg_addr):
            assert not (win_start <= addr <= win_end), (
                f"CHK-OWNERSHIP FAIL: {name} 0x{addr:08x} sits inside the live "
                f"allow window 0x{win_start:08x}..0x{win_end:08x}"
            )
            before = await self.filt.read_cpu(addr)
            if name == "inbound-cfg":
                assert (before & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
                    f"CPU-LSU should read the programmed filter cfg "
                    f"0x{addr:08x}=0x{before:08x} "
                    f"(rw 0x{before & FILTER_RW_MASK:08x} != "
                    f"0x{expected_cfg & FILTER_RW_MASK:08x})"
                )
            await self._assert_ext_deny_read(
                addr,
                staged=before,
                tag=(
                    f"CHK-OWNERSHIP FAIL: external read of {name} 0x{addr:08x} "
                    f"(outside allow 0x{win_start:08x}..0x{win_end:08x})"
                ),
            )
            resp = await self._ext_write(addr, 0xFFFF_FFFF)
            assert resp == RESP_DECERR, (
                f"CHK-OWNERSHIP FAIL: external write of {name} 0x{addr:08x} "
                f"resp={resp}, expected DECERR (outside allow "
                f"0x{win_start:08x}..0x{win_end:08x})"
            )
            after = await self.filt.read_cpu(addr)
            if name == "inbound-cfg":
                assert (after & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
                    f"filter cfg corrupted by denied ext write: 0x{after:08x}"
                )
            else:
                assert after == before, (
                    f"CHK-OWNERSHIP FAIL: {name} 0x{addr:08x} corrupted by "
                    f"denied ext write: 0x{after:08x} != 0x{before:08x}"
                )
            same_page = (addr >> PAGE_SHIFT) == (win0_addr >> PAGE_SHIFT)
            self.logger.info(
                "CHK-OWNERSHIP PASS: %s 0x%08x outside allow "
                "0x%08x..0x%08x -- CPU-LSU reads 0x%08x, external R+W DECERR, "
                "value intact%s",
                name,
                addr,
                win_start,
                win_end,
                before,
                ", same 4 KB page as window 0" if same_page else "",
            )
            names.append(name)
        self.logger.info(
            "CHK-OWNERSHIP PASS: %d CSRs outside every allow window (%s)",
            len(names),
            ", ".join(names),
        )

        self.logger.info(
            "CHK-NONVAC PASS: allow + block both observed with filter active (sep_debug=0)"
        )

        await self._check_page_widen(mcfg)
