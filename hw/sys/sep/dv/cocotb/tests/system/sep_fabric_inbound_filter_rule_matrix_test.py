# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each inbound-filter entry admits only the traffic its rule allows; all other traffic is DECERR.

With the SEP inbound filter active (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs inbound FILTER_CONFIG allow-entries and the external SMN
master (m_axi, the only path through u_inbound_filter) proves per-entry rule
enforcement: an allowed address -> OKAY + exact CSR value; any other address ->
DECERR, never the value staged there (block-by-default); read_allowed and
write_allowed gate the matched read/write. The external master drives the
SEP-local address directly; u_inbound_global_to_local_addr_remap passes addresses
outside the global window unchanged.

Walks entries 0 and 7 x two address windows x {rw, read-only, write-only} at
src_id=0 (match-all), plus entry 0 / window 0 x {rw, r, w} at src_id=5 with a
matching AXI user and one src-mismatch cell. SepInboundFilterMatrixCfg is the
single source of truth. Stays at sep_debug=0 the whole time and proves
the per-entry allow-by-rule vs block-by-default policy, not the global
sep_debug skip gate (sep_lcc_uvm_inbound_filter_gating_test).

CHK-OWNERSHIP grades the CPU-vs-external asymmetry at the CSRs that
reposition the inbound remap or program a filter: inbound CFG, outbound
CFG[0], alias/AP/STEE remap bases, SEP_GLOBAL_BASE_ADDR, and
SEP_REGION_SIZE. CPU-LSU reads each register; the external master
completes DECERR on read and write; the denied write does not land.
This checks that the external master can neither read nor write the filter
and remap CSRs while they stay outside every allow window.
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
singles (fabric.adoc: axi_to_axi_lite splits bursts into individual
transactions). CTRL-BURST-LITE-LIVE: the single-beat access of each deny cell
reaches the Lite port as one single at its address, so the watch is live
when the denied burst shows none. WRAP/FIXED/AxLEN>1 are
not walked. The denied 2-beat read also grades its R beats on the m_axi
pins: an error response still returns every beat of the burst with RLAST
on the last beat only, each beat with RID equal to the ARID (AMBA AXI
IHI 0022), and the filter answers DECERR on RRESP
(``hw/ip/axi_filter/doc/index.adoc``, "Blocked Transactions"). The ARID is
drawn from 1 to 62 (ARID 63 is the pre-sense read), so an RID that drops
to 0 fails.
OBS-SI-PRESENSE-READ runs last: after an ``rst_ni`` pulse, one external
read with ARID 63 is sent while fuse sensing runs and is watched for 256
clocks after ``sep_reset_n`` releases. It grades nothing.
CHK-PAGE-WIDEN / CHK-PAGE-BOUND / CHK-CONFIG-LOCK cover the same-page
allow_burst=1 window on entry 15. An 8-byte window inside the
dual-scratch page (0x1080_2000) is rewritten by axi_filter_wrap.sv to the
whole page, and traffic_filter.sv then compares only addr[ADDR_WIDTH-1:12].
CHK-PAGE-WIDEN proves the 4 KB page grant on the bus
(hw/ip/axi_filter/doc/index.adoc: START down, END up):
an external access to an address inside the granted page but outside the
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
cannot move. The lock is write-once, and every later write to the entry's
FILTER_CONFIG completes DECERR (filter_ctrl.rdl locked;
hw/ip/axi_filter/doc/index.adoc "Locking a Filter Entry"), so both refused
writes must answer DECERR. Each refused write is graded against a read of
the same register just before it: the low word reads back unchanged, and
locked stays 1. A 2-beat INCR
inside the widened page still passes OKAY as two Lite singles. A single beat
would not do: START/END already hold the page, so a single beat inside it passes
with allow_burst 0 or 1. The response codes are logged at once and graded after
the 2-beat INCR, so the burst is checked whatever code the writes answered. The
lock is sticky until reset, so this cell runs last on entry 15.

CHK-FILT-RSVD-READ: through an entry whose window runs from the last SRAM
granule to the Reserved row base 0x10050000, an external read of that base
answers DECERR with 0xBADCAB1E (``hw/sys/sep/regs/gen/adoc/memory_map.adoc:41``;
the column is the inbound-port answer, ``hw/sys/sep/doc/memory_map.adoc:66-69``).
CTRL-FILT-RSVD-ALLOW reads a staged SRAM word through the same entry first and
needs that word back, so the DECERR is not a filter denial.

Functional coverage: the window of this leaf holds only the graded bursts
and the refused FILTER_CONFIG writes with their read-backs. A
``cp_lite_split`` cell samples only after the check of its burst passed
(``lite_split_pass``); ``cp_locked_write`` samples at the read-back when it
equals the read before the DECERR write, the read pair that
CHK-CONFIG-LOCK grades.

Run mode: no_cpu with the external SMN master and real PROD fuse sense
(sep_debug=0, so the filter is active). RAND-REP: entry x window x R/W-allow x
src-id class; the seed sets the window values.
"""

from __future__ import annotations

import contextlib

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_lite_split_pass
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib import sep_row_response_seq as rr
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_fabric_csr_bank_seq import F_ALLOW_BURST, FILTER_RW_MASK
from seq_lib.sep_inbound_filter_rule_seq import (
    AXI_BURST_INCR,
    BURST_BYTES,
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

_TEST = "sep_fabric_inbound_filter_rule_matrix_test"
# Separate stream for the denied-burst ARID, so the matrix draws keep their seed mapping.
_BURST_ID_SALT = 0x4255_5253
_M_AXI_ID_MAX = 62
# Separate stream for the CTRL-FILT-RSVD-ALLOW staged word.
_RSVD_CTRL_SALT = 0x5253_5644
# Read data of the Reserved row cell (hw/sys/sep/regs/gen/adoc/memory_map.adoc:41).
RSVD_RDATA = 0xBADC_AB1E
# ARID of the read sent before fuse sensing ends; no other read of this leaf uses it,
# so an R beat that never comes leaves no later read of that ID to pair with.
_PRESENSE_ARID = 63
# clk_i cycles the pre-sense read is watched after sep_reset_n releases.
_PRESENSE_WAIT = 256
# clk_i cycles rst_ni is held low before the pre-sense read.
_PRESENSE_RST_HOLD = 20
_MAX_SENSE_CYCLES = 20_000
# Clocks the leaf keeps its coverage window open after a graded step, so the
# sampler sees a pass label rise while the window is still open.
_LABEL_HOLD_CLOCKS = 2
# Distinct non-zero disable vectors so the decoded FEAT_CTRL is non-vacuous.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF


@pyuvm.test()
class sep_fabric_inbound_filter_rule_matrix_test(sep_base_test):
    """External traffic gets OKAY only where an entry's rule allows it, and DECERR elsewhere."""

    def _grade(self, name: str, ok: bool, detail: str) -> None:
        """Log one PASS or FAIL line; a FAIL closes the coverage window, then raises.

        ``name`` is ``<PREFIX>-<NAME>`` optionally followed by a leg tag; the tag
        goes after the verdict as ``leg=<tag>``.
        """
        name, _, leg = name.partition(" ")
        if leg:
            detail = f"leg={leg.replace(' ', '_')} {detail}"
        if ok:
            self.logger.info("%s PASS: %s", name, detail)
            return
        self.logger.error("%s FAIL: %s", name, detail)
        close_graded_window(self.logger)
        set_lite_split_pass(False, self.logger)
        raise AssertionError(f"{name} FAIL: {detail}")

    @contextlib.asynccontextmanager
    async def _graded_window(self):
        """Open the coverage window of this leaf around one graded DUT step.

        The window holds only the graded access and its checks: programming,
        staging and entry reads stay outside. The ``cp_lite_split`` label is 0
        when the window opens; the body writes it 1 only after the check of its
        burst passed. A FAIL closes the window at once. After a passing body
        the window stays open ``_LABEL_HOLD_CLOCKS`` clocks, so the sampler sees
        the label rise inside it, then the label returns to 0 and the window
        closes.
        """
        set_lite_split_pass(False, self.logger)
        open_graded_window(_TEST, self.logger)
        try:
            yield
        except BaseException:
            # A failure may resume from ReadOnly, where no value can be written.
            await NextTimeStep()
            close_graded_window(self.logger)
            set_lite_split_pass(False, self.logger)
            raise
        await ClockCycles(cocotb.top.clk_i, _LABEL_HOLD_CLOCKS)
        set_lite_split_pass(False, self.logger)
        close_graded_window(self.logger)

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
        self.logger.info(
            "OBS-FILT-DENY-RDATA addr=0x%08x user=0x%x resp=%d rdata=0x%08x", addr, user, resp, data
        )
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

    async def _ext_burst_read(
        self, addr: int, *, expect_error: bool = False, axi_id: int = 0
    ) -> tuple[int, int]:
        if axi_id:
            seq = SepAxiAccessSeq(
                "infilt_ext_burst_rd_id",
                op=SepAxiOp.READ,
                addr=addr,
                length=BURST_BYTES,
                size=2,
                burst=AXI_BURST_INCR,
                expect_error=expect_error,
                axi_id=axi_id,
            )
        else:
            seq = ext_burst_read_seq(addr, expect_error=expect_error)
        await self.start_ext_seq(seq)
        return seq.resp_code, (seq.rdata & 0xFFFF_FFFF)

    async def _ext_burst_write(self, addr: int, data: int, *, expect_error: bool = False) -> int:
        seq = ext_burst_write_seq(addr, data, expect_error=expect_error)
        await self.start_ext_seq(seq)
        return seq.resp_code

    async def _ext_read_watch(self, addr: int) -> tuple[int, int, list[int]]:
        task, addrs = self.watch_sys_csr_lite(write=False)
        try:
            resp, data = await self._ext_read(addr)
        finally:
            task.kill()
        return resp, data, list(addrs)

    async def _ext_write_watch(self, addr: int, data: int) -> tuple[int, list[int]]:
        task, addrs = self.watch_sys_csr_lite(write=True)
        try:
            resp = await self._ext_write(addr, data)
        finally:
            task.kill()
        return resp, list(addrs)

    async def _ext_burst_read_watch(
        self, addr: int, *, expect_error: bool = False, axi_id: int = 0
    ) -> tuple[int, int, list[int]]:
        task, addrs = self.watch_sys_csr_lite(write=False)
        try:
            resp, data = await self._ext_burst_read(addr, expect_error=expect_error, axi_id=axi_id)
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
        """AxLEN=N-1 INCR of 4-byte beats becomes N AXI-Lite singles.

        Golden: ``hw/sys/sep/doc/fabric.adoc:21-22`` (the ``axi_to_axi_lite``
        bridge splits bursts into individual transactions): one Lite single per
        beat, at the beat address; a burst the filter refuses reaches none.
        """
        expected = [start + i * 4 for i in range(nbeats)]
        self._grade(
            tag,
            addrs == expected,
            f"Lite singles {[hex(a) for a in addrs]}, expected {[hex(a) for a in expected]}",
        )

    def _release_lite_split(self) -> None:
        """Write the ``cp_lite_split`` pass label after the burst check passed."""
        set_lite_split_pass(True, self.logger)

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

        resp, data, lite_sb = await self._ext_read_watch(burst_addr)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-DENY: single-beat read of 0x{burst_addr:08x} "
            f"resp={resp}, expected OKAY (anti-vacuous)"
        )
        assert data == burst_val, (
            f"CHK-BURST-DENY: single-beat rdata 0x{data:08x} != staged 0x{burst_val:08x}"
        )
        self._expect_lite_split(
            lite_sb, start=burst_addr, nbeats=1, tag="CTRL-BURST-LITE-LIVE single-beat AR"
        )
        arid = SepSeededRng(mcfg.seed ^ _BURST_ID_SALT).randrange(1, _M_AXI_ID_MAX + 1)
        mon = self.env.ext_axi_monitor
        async with self._graded_window():
            mon.start_beat_capture()
            resp, data, lite_ar = await self._ext_burst_read_watch(
                burst_addr, expect_error=True, axi_id=arid
            )
            mon.take_beat_capture()
            beats = list(mon.last_beat_detail)
            assert resp == RESP_DECERR, (
                f"CHK-BURST-DENY FAIL: allow_burst=0 2-beat INCR read of "
                f"0x{burst_addr:08x} resp={resp}, expected DECERR"
            )
            want = [(RESP_DECERR, arid, 0), (RESP_DECERR, arid, 1)]
            assert beats == want, (
                f"CHK-BURST-DENY FAIL: allow_burst=0 2-beat INCR read of 0x{burst_addr:08x} "
                f"arid={arid} R beats (rresp, rid, rlast)={beats}, expected {want}"
            )
            assert data != burst_val, (
                f"CHK-BURST-DENY FAIL: denied burst returned the staged value "
                f"0x{data:08x}; the blocked burst reached the target"
            )
            self._expect_lite_split(
                lite_ar, start=burst_addr, nbeats=0, tag="CHK-BURST-TO-SINGLE deny AR"
            )
            self._release_lite_split()
        self.logger.info(
            "CHK-BURST-DENY PASS: allow_burst=0 single-beat OKAY rdata=0x%08x as Lite AR %s; "
            "2-beat INCR DECERR at 0x%08x, rdata=0x%08x, Lite AR %s, arid=%d "
            "R beats (rresp, rid, rlast)=%s",
            burst_val,
            [hex(a) for a in lite_sb],
            burst_addr,
            data,
            [hex(a) for a in lite_ar],
            arid,
            beats,
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
        async with self._graded_window():
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
            self._release_lite_split()
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
        resp, lite_sb = await self._ext_write_watch(burst_addr, poke_sb)
        assert resp == RESP_OKAY, (
            f"CHK-BURST-WRITE-DENY: single-beat write of 0x{burst_addr:08x} "
            f"resp={resp}, expected OKAY (anti-vacuous)"
        )
        landed = await self.filt.read_cpu(burst_addr)
        assert landed == poke_sb, (
            f"CHK-BURST-WRITE-DENY: single-beat write did not land "
            f"(0x{landed:08x} != 0x{poke_sb:08x})"
        )
        self._expect_lite_split(
            lite_sb, start=burst_addr, nbeats=1, tag="CTRL-BURST-LITE-LIVE single-beat AW"
        )
        await self.filt.stage_target(burst_addr, burst_val)
        async with self._graded_window():
            resp, lite_aw = await self._ext_burst_write_watch(
                burst_addr, poke_burst, expect_error=True
            )
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
            self._release_lite_split()
        self.logger.info(
            "CHK-BURST-WRITE-DENY PASS: allow_burst=0 single-beat write OKAY "
            "and landed as Lite AW %s; 2-beat INCR DECERR, Lite AW %s, and did not "
            "land at 0x%08x (reads 0x%08x)",
            [hex(a) for a in lite_sb],
            [hex(a) for a in lite_aw],
            burst_addr,
            after,
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
        async with self._graded_window():
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
            self._release_lite_split()
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
            "CTRL-BURST-WALK PASS: allow_burst deny + allow walked on AR and AW "
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
            f"CHK-CONFIG-LOCK FAIL: allow_burst not set before the lock "
            f"(FILTER_CONFIG lo 0x{cfg_lo:08x})"
        )
        await self.filt.lock_entry(wcfg.entry)
        hi = await self.filt.read_cpu(cell.cfg_addr + 4)
        assert (hi >> FILTER_LOCKED_HI_BIT) & 1, (
            f"CHK-CONFIG-LOCK FAIL: locked did not set (hi 0x{hi:08x})"
        )
        # Each refused write is graded against a read of the same register just
        # before it: "reads still return the locked configuration"
        # (hw/ip/axi_filter/doc/index.adoc:151-156). The read stays outside the
        # coverage window; the window holds the write and its read-back.
        lock_bit = 1 << FILTER_LOCKED_HI_BIT
        lo_addr = cell.cfg_addr
        hi_addr = cell.cfg_addr + 4
        pre_lo = await self.filt.read_cpu(lo_addr)
        assert pre_lo == cfg_lo, (
            f"CHK-CONFIG-LOCK FAIL: FILTER_CONFIG lo moved when locked was set "
            f"(0x{pre_lo:08x} != 0x{cfg_lo:08x})"
        )
        lo_wr = cfg_lo & ~F_ALLOW_BURST & 0xFFFF_FFFF
        async with self._graded_window():
            resp_lo = await self.filt.write_tolerant(lo_addr, lo_wr)
            after = await self.filt.read_cpu(lo_addr)
            self._grade(
                "CHK-CONFIG-LOCK lo",
                lo_wr != pre_lo and after == pre_lo,
                f"entry {wcfg.entry} FILTER_CONFIG lo before 0x{pre_lo:08x}, write "
                f"0x{lo_wr:08x} (allow_burst 0) resp={resp_lo}, read-back 0x{after:08x} "
                f"(allow_burst={bool(after & F_ALLOW_BURST)}); expected the read-back "
                f"to equal the value before",
            )
        pre_hi = await self.filt.read_cpu(hi_addr)
        assert pre_hi & lock_bit, (
            f"CHK-CONFIG-LOCK FAIL: locked is not set before the hi write (hi 0x{pre_hi:08x})"
        )
        hi_wr = 0
        async with self._graded_window():
            resp_hi = await self.filt.write_tolerant(hi_addr, hi_wr)
            hi_after = await self.filt.read_cpu(hi_addr)
            self._grade(
                "CHK-CONFIG-LOCK hi",
                (hi_wr & lock_bit) != (pre_hi & lock_bit)
                and (hi_after & lock_bit) == (pre_hi & lock_bit),
                f"entry {wcfg.entry} FILTER_CONFIG hi before 0x{pre_hi:08x} (locked=1), "
                f"write 0x{hi_wr:08x} (locked=0) resp={resp_hi}, read-back "
                f"0x{hi_after:08x} (locked={(hi_after >> FILTER_LOCKED_HI_BIT) & 1}); "
                f"expected locked to stay 1",
            )
        rsvd = (lock_bit - 1) & 0xFFFF_FFFF
        self.logger.info(
            "OBS-CONFIG-LOCK-HI-RSVD: entry %d FILTER_CONFIG hi bits [62:32] before 0x%08x, "
            "after 0x%08x (filter_ctrl.rdl names no field there; not graded)",
            wcfg.entry,
            pre_hi & rsvd,
            hi_after & rsvd,
        )
        self.logger.info(
            "INFO-CONFIG-LOCK entry %d locked FILTER_CONFIG writes: lo resp=%d, hi resp=%d "
            "(spec DECERR=%d)",
            wcfg.entry,
            resp_lo,
            resp_hi,
            RESP_DECERR,
        )
        # The frozen bit still drives the hardware, not just the CSR readback.
        # START/END already hold the widened page, so a single beat inside it is
        # granted whether allow_burst is 0 or 1. The probe is a 2-beat INCR: the
        # filter passes it only while it still sees allow_burst=1, and a pass
        # reaches the target as two Lite singles.
        probe_addr, probe_val = wcfg.staged[1]
        probe_resp, data, lite_ar = await self._ext_burst_read_watch(probe_addr)
        assert probe_resp == RESP_OKAY and data == probe_val, (
            f"CHK-CONFIG-LOCK FAIL: 2-beat INCR read of 0x{probe_addr:08x} under the "
            f"lock resp={probe_resp} rdata=0x{data:08x} (staged 0x{probe_val:08x}); "
            "the filter refuses the burst, so the lock froze only the CSR "
            "readback of allow_burst"
        )
        self._expect_lite_split(lite_ar, start=probe_addr, nbeats=2, tag="CHK-CONFIG-LOCK burst AR")
        self.logger.info(
            "INFO-CONFIG-LOCK entry %d 2-beat INCR at 0x%08x under the lock: resp=%d "
            "rdata=0x%08x, Lite AR %s",
            wcfg.entry,
            probe_addr,
            probe_resp,
            data,
            [hex(a) for a in lite_ar],
        )
        assert (resp_lo, resp_hi) == (RESP_DECERR, RESP_DECERR), (
            f"CHK-CONFIG-LOCK FAIL: writes to locked FILTER_CONFIG answered lo resp={resp_lo}, "
            f"hi resp={resp_hi}; a write to a locked entry goes to the AXI error subordinate "
            f"and completes DECERR ({RESP_DECERR})"
        )
        self.logger.info(
            "CHK-CONFIG-LOCK PASS: entry %d locked -- clearing allow_burst (resp=%d, DECERR) "
            "leaves FILTER_CONFIG lo 0x%08x (allow_burst=%d), clearing locked "
            "(resp=%d, DECERR) leaves the bit set, and a 2-beat INCR at 0x%08x still "
            "passes OKAY rdata=0x%08x as Lite AR %s",
            wcfg.entry,
            resp_lo,
            after,
            bool(after & F_ALLOW_BURST),
            resp_hi,
            probe_addr,
            data,
            [hex(a) for a in lite_ar],
        )

    def _presense_si_read_start(self):
        """Send one SI read of SRAM word 0 before fuse sensing ends; watch its handshakes."""
        dut = cocotb.top
        addr = sym("SEP_SRAM_MEM_BASE_ADDR")
        rec: dict = {"stop": False}

        async def _watch() -> None:
            while not rec["stop"]:
                await RisingEdge(dut.clk_i)
                await ReadOnly()
                if (
                    "ar" not in rec
                    and dut.m_axi_arvalid.value == 1
                    and dut.m_axi_arready.value == 1
                    and int(dut.m_axi_arid.value) == _PRESENSE_ARID
                ):
                    rec["ar"] = self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True)
                if (
                    dut.m_axi_rvalid.value == 1
                    and dut.m_axi_rready.value == 1
                    and int(dut.m_axi_rid.value) == _PRESENSE_ARID
                ):
                    rec["r"] = int(dut.m_axi_rresp.value)

        watch = cocotb.start_soon(_watch())
        vip = self.env.ext_axi_agent.driver.axi
        read = cocotb.start_soon(
            vip.read_bytes_result(
                addr, 4, size=2, id=_PRESENSE_ARID, check_response=False, allow_timeout=True
            )
        )
        return addr, rec, watch, read

    async def _presense_si_read_after_pulse(self) -> None:
        """Pulse ``rst_ni`` and send the pre-sense SI read while fuse sensing runs.

        Runs after every graded step: the FCOV System Interface tracker pairs a
        completion with the one read outstanding, so a read left unanswered
        must not overlap graded reads.
        """
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        await ClockCycles(dut.clk_i, _PRESENSE_RST_HOLD)
        await ReadOnly()
        self._require_sense_restart()
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 1
        await ClockCycles(dut.clk_i, 2)
        pre_sense = self._presense_si_read_start()
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self._presense_si_read_log(*pre_sense)

    async def _presense_si_read_log(self, addr: int, rec: dict, watch, read) -> None:
        """OBS-SI-PRESENSE-READ: no line states what an SI read before sensing ends gets."""
        dut = cocotb.top
        while not self.rd(dut.dbg_sep_reset_n_o, allow_unknown=True):
            await RisingEdge(dut.clk_i)
        await ClockCycles(dut.clk_i, _PRESENSE_WAIT)
        rec["stop"] = True
        await watch
        self.env.ext_axi_monitor.forget_pending_reads(_PRESENSE_ARID)
        self.logger.info(
            "OBS-SI-PRESENSE-READ addr=0x%08x arid=%d accepted=%s sep_reset_n_at_accept=%s "
            "response=%s rresp=%s window_clk_after_release=%d vip_done=%d",
            addr,
            _PRESENSE_ARID,
            "y" if "ar" in rec else "n",
            rec.get("ar", "na"),
            "y" if "r" in rec else "n",
            rec.get("r", "na"),
            _PRESENSE_WAIT,
            int(read.done()),
        )

    async def _reserved_si_read(self, seed: int) -> None:
        """CHK-FILT-RSVD-READ: one SI read of a Reserved row through an allow entry over it.

        The memory map gives the Reserved row 0x10050000-0x107FFFFF the cell
        "DECERR, 0xBADCAB1E / DECERR" (``hw/sys/sep/regs/gen/adoc/memory_map.adoc:41``),
        the answer at the inbound AXI port (``hw/sys/sep/doc/memory_map.adoc:66-69``).
        A filter denial gives the same code and data, so CTRL-FILT-RSVD-ALLOW
        first reads the last SRAM word through the same entry, whose window
        runs from that word to the Reserved base: the staged value shows the entry
        admits the read (the response code is logged in the same line).
        """
        addr = rr.RESERVED_BASES[0]
        ctrl = sym("SEP_SRAM_MEM_BASE_ADDR") + sym("SEP_SRAM_MEM_SIZE") - GRANULE_BYTES
        staged = SepSeededRng(seed ^ _RSVD_CTRL_SALT).getrandbits(32)
        await self.filt.disable_all()
        await self.filt.stage_target(ctrl, staged)
        cell = SepInboundFilterCfg(entry=0, allow_addr=ctrl, allow_value=staged)
        await self.filt.program_rule(cell, read_allowed=True, write_allowed=False, end_addr=addr)
        resp, data = await self._ext_read(ctrl)
        self._grade(
            "CTRL-FILT-RSVD-ALLOW",
            data == staged,
            f"entry=0 window=0x{ctrl:08x}..0x{addr:08x} addr=0x{ctrl:08x} resp={resp} "
            f"rdata=0x{data:08x} expect=0x{staged:08x}",
        )
        resp, data = await self._ext_read(addr)
        self._grade(
            "CHK-FILT-RSVD-READ",
            (resp, data) == (RESP_DECERR, RSVD_RDATA),
            f"row=reserved addr=0x{addr:08x} resp={resp} rdata=0x{data:08x} "
            f"expect={RESP_DECERR}/0x{RSVD_RDATA:08x}",
        )
        await self.filt.disable_all()

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
        # sec_dis is the one FEAT_CTRL golden input the DUT exposes
        # (lcc_security_disable_probe_o); the lifecycle and DIS inputs are the
        # values written into the fuse image above.
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert ctl.sep_debug == 0, (
            f"sep_debug must be 0 (filter active) in PROD, got {ctl.sep_debug} "
            f"(FEAT_CTRL=0x{ctl.feat_ctrl:016x})"
        )
        self.logger.info("INFO-FILTER-ACTIVE %s sep_debug=0", lc_state_name(image.lc_raw()))

    async def run_scenario(self) -> None:
        mcfg = SepInboundFilterMatrixCfg.from_seed(self.random_seed())
        self.logger.info("INFO-CFG inbound-filter matrix: %s", mcfg.summary())

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
            f"CTRL-RAND-REP FAIL: walked {walked} cells, n_cells()={mcfg.n_cells()}"
        )
        self.logger.info(
            "CTRL-RAND-REP PASS: walked all %d discrete cells "
            "(entries %s x %d windows x rw/r/w match-all + "
            "entry0/window0 x rw/r/w match + 1 mismatch)",
            walked,
            list(mcfg.entries),
            len(mcfg.windows),
        )

        await self._check_burst_dimension(mcfg)
        await self._reserved_si_read(mcfg.seed)

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
            "CTRL-NONVAC PASS: allow + block both observed with filter active (sep_debug=0)"
        )

        await self._check_page_widen(mcfg)
        await self._presense_si_read_after_pulse()
