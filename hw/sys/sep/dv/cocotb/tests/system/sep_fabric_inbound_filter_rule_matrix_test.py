# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound-filter per-entry RULE matrix.

With the SEP inbound filter ACTIVE (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs inbound FILTER_CONFIG allow-entries and the EXTERNAL SMN
master (m_axi, the only path through u_inbound_filter) proves per-entry rule
enforcement: an allowed address -> OKAY + exact CSR value; any other address ->
DECERR (block-by-default); read_allowed/write_allowed gate the matched
read/write. With smc_global_base=0 the inbound global->local remap is identity, so
the external master drives the SEP-local address directly.

Walks first and last table entries x two address windows x {rw, read-only,
write-only} at src_id=0 (match-all), plus entry 0 / window 0 x {rw, r, w} at
src_id=5 with a matching AXI user and one src-mismatch cell. SepInboundFilterMatrixCfg
is the single source of truth. Stays at sep_debug=0 the whole time and proves
the PER-ENTRY allow-by-rule vs block-by-default policy, not the global
sep_debug skip gate (sep_lcc_uvm_inbound_filter_gating_test).

CHK-OWNERSHIP ports the CPU-vs-external asymmetry at the filter CFG CSR
(0x10A2_1000): CPU-LSU reads the programmed rule, the external master completes
DECERR on read and write, and the denied write does not land. That is the
spec's "only the SEP CPU can program these filters" under the programmed allow
window, which does not include the CFG address. CHK-OWNERSHIP-WINDOW keeps that
assert hard after a second entry allow-lists the CFG address.
RUN-MODE: no_cpu + external SMN master. FUSE-MODE: real PROD fuse sense (sep_debug=0
=> filter active). RAND-REP (entry x window x R/W-allow x src-id class; window
values from seed).
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq
from seq_lib.sep_inbound_filter_rule_seq import (
    SepInboundFilterCfg, SepInboundFilterMatrixCfg, SepInboundFilter,
    ext_read_seq, ext_write_seq, RESP_OKAY, RESP_DECERR, FILTER_BEAT_MASK,
)
from seq_lib.sep_fabric_csr_bank_seq import FILTER_RW_MASK

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

    async def _ext_write(self, addr: int, data: int, *, user: int = 0) -> int:
        seq = ext_write_seq(addr, data, user=user)
        await self.start_ext_seq(seq)
        return seq.resp_code

    async def _bring_up_prod_filter_active(self) -> None:
        """Real-sense a PROD image -> sep_debug=0 (inbound filter active)."""
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS})
        # No image.lc_raw() == LC_PROD assert here: select_efuse_image was called with
        # lc_raw=LC_PROD and randomize() pins the field to exactly that, so the check
        # compares a value to itself. The DUT-side evidence that PROD actually took
        # effect is the FEAT_CTRL read below, value-checked against feat_ctrl_expected.
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        # security_disable read from the DUT rather than passed as a literal. This
        # entry value-checks FEAT_CTRL against the Phase 1 lifecycle golden, so every
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
            assert staged == val, (
                f"staged target 0x{addr:08x}=0x{staged:08x} != 0x{val:08x}"
            )

        first = True
        src_match_logged = False
        src_mismatch_logged = False
        for (entry, widx, mode, addr, val, read_ok, write_ok,
             src_class, cfg_src_id, axi_user, expect_hit) in mcfg.cells():
            await self.filt.disable_all()
            cell = SepInboundFilterCfg(entry=entry, allow_addr=addr, allow_value=val)
            cell.src_id = cfg_src_id
            await self.filt.program_rule(cell, read_allowed=read_ok, write_allowed=write_ok)

            if not expect_hit:
                resp, _ = await self._ext_read(addr, user=axi_user)
                assert resp == RESP_DECERR, (
                    f"cell entry={entry} w{widx} {mode} {src_class}: "
                    f"src mismatch read resp={resp}, expected DECERR"
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
                        cfg_src_id, axi_user)
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
                            "CHK-ALLOW-RULE PASS: ext read 0x%08x -> OKAY, rdata=0x%08x",
                            addr, data)
                else:
                    resp, _ = await self._ext_read(addr, user=axi_user)
                    assert resp == RESP_DECERR, (
                        f"cell entry={entry} w{widx} {mode} {src_class}: "
                        f"read_allowed=0 got resp={resp}"
                    )

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
                        cfg_src_id, axi_user)
                    src_match_logged = True

            resp, _ = await self._ext_read(mcfg.blocked_addr, user=axi_user)
            assert resp == RESP_DECERR, (
                f"cell entry={entry} w{widx} {mode} {src_class}: "
                f"blocked 0x{mcfg.blocked_addr:08x} resp={resp}, expected DECERR"
            )
            if first:
                self.logger.info(
                    "CHK-BLOCK-DEFAULT PASS: ext read 0x%08x -> DECERR (block-by-default)",
                    mcfg.blocked_addr)
            if expect_hit and mode == "r":
                self.logger.info(
                    "CHK-WRITE-ALLOWED PASS: write_allowed gates the matched ext write "
                    "(DECERR) entry=%d window=%d src=%s", entry, widx, src_class)
                self.logger.info(
                    "CHK-READ-ALLOWED PASS: read_allowed gates the matched ext read "
                    "(OKAY) entry=%d window=%d src=%s", entry, widx, src_class)
            if expect_hit and mode == "w":
                self.logger.info(
                    "CHK-READ-ALLOWED PASS: read_allowed gates the matched ext read "
                    "(DECERR) entry=%d window=%d src=%s", entry, widx, src_class)
                self.logger.info(
                    "CHK-WRITE-ALLOWED PASS: write_allowed gates the matched ext write "
                    "(OKAY) entry=%d window=%d src=%s", entry, widx, src_class)
            self.logger.info(
                "CHK-CELL PASS: entry=%d window=%d mode=%s src=%s addr=0x%08x",
                entry, widx, mode, src_class, addr)
            first = False

        self.logger.info(
            "CHK-RAND-REP PASS: walked all %d discrete cells "
            "(entries %s x %d windows x rw/r/w match-all + "
            "entry0/window0 x rw/r/w match + 1 mismatch)",
            mcfg.n_cells(), list(mcfg.entries), len(mcfg.windows))

        # Restore entry 0 / window A / rw for the ownership checks.
        await self.filt.disable_all()
        win0_addr, win0_val = mcfg.windows[0]
        self.fcfg = SepInboundFilterCfg(
            entry=0, allow_addr=win0_addr, allow_value=win0_val)
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=True)

        cfg_addr = self.fcfg.cfg_addr
        expected_cfg = self.fcfg.config_word(read_allowed=True, write_allowed=True)
        cpu_cfg = await self.filt.read_cpu(cfg_addr)
        assert (cpu_cfg & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
            f"CPU-LSU should read the programmed filter cfg 0x{cfg_addr:08x}=0x{cpu_cfg:08x} "
            f"(rw 0x{cpu_cfg & FILTER_RW_MASK:08x} != 0x{expected_cfg & FILTER_RW_MASK:08x})"
        )
        resp, _ = await self._ext_read(cfg_addr)
        assert resp == RESP_DECERR, (
            f"external read of filter cfg 0x{cfg_addr:08x} resp={resp}, expected DECERR "
            f"(external master must NOT read the filter config)"
        )
        resp = await self._ext_write(cfg_addr, 0xFFFF_FFFF)
        assert resp == RESP_DECERR, (
            f"external write of filter cfg 0x{cfg_addr:08x} resp={resp}, expected DECERR "
            f"(external master must NOT program the filter)"
        )
        cpu_cfg_after = await self.filt.read_cpu(cfg_addr)
        assert (cpu_cfg_after & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
            f"filter cfg corrupted by denied ext write: 0x{cpu_cfg_after:08x}"
        )
        self.logger.info(
            "CHK-OWNERSHIP PASS: filter cfg 0x%08x -- CPU-LSU reads rule (rw 0x%08x), external "
            "R+W DECERR, rule intact",
            cfg_addr, cpu_cfg & FILTER_RW_MASK)

        self.logger.info(
            "CHK-NONVAC PASS: allow + block both observed with filter active (sep_debug=0)")

        own = SepInboundFilterCfg(entry=1)
        own.allow_addr = cfg_addr
        await self.filt.program_rule(own, read_allowed=True, write_allowed=True)
        own_cfg = await self.filt.read_cpu(own.cfg_addr)
        own_expected = own.config_word(read_allowed=True, write_allowed=True)
        assert (own_cfg & FILTER_RW_MASK) == (own_expected & FILTER_RW_MASK), (
            f"entry 1 FILTER_CONFIG not programmed: got 0x{own_cfg:08x}, "
            f"expected rw 0x{own_expected & FILTER_RW_MASK:08x}"
        )
        own_start = await self.filt.read_cpu(own.start_addr_reg)
        assert own_start == cfg_addr, (
            f"entry 1 START_ADDR does not cover CFG: got 0x{own_start:08x}, "
            f"expected 0x{cfg_addr:08x}"
        )
        own_end = await self.filt.read_cpu(own.end_addr_reg)
        # HW writeback: same-beat window expands END to the last byte of the
        # data-bus granule (filter_ctrl.rdl END_ADDR reset 0x7 / 8-byte beat).
        expected_end = cfg_addr | FILTER_BEAT_MASK
        assert own_end == expected_end, (
            f"entry 1 END_ADDR not granule-expanded: got 0x{own_end:08x}, "
            f"expected 0x{expected_end:08x} (START=0x{cfg_addr:08x} | beat_mask)"
        )
        own_end_hi = await self.filt.read_cpu(own.end_addr_reg + 4)
        assert own_end_hi == 0, (
            f"entry 1 END_ADDR hi is not 0: got 0x{own_end_hi:08x}"
        )
        self.logger.info(
            "CHK-FILTER-PROGRAMMED PASS: entry 1 FILTER_CONFIG rw=0x%08x "
            "START_ADDR=0x%08x END_ADDR=0x%08x",
            own_cfg & FILTER_RW_MASK, own_start, own_end)
        resp, _ = await self._ext_read(cfg_addr)
        assert resp == RESP_DECERR, (
            f"CHK-OWNERSHIP-WINDOW FAIL: after allow-listing filter cfg "
            f"0x{cfg_addr:08x} on entry 1, external read resp={resp}, expected "
            f"DECERR (RTL vs hw/sys/sep/doc/fabric.adoc: only the SEP CPU programs the filter)"
        )
        resp = await self._ext_write(cfg_addr, 0xFFFF_FFFF)
        assert resp == RESP_DECERR, (
            f"CHK-OWNERSHIP-WINDOW FAIL: after allow-listing filter cfg "
            f"0x{cfg_addr:08x} on entry 1, external write resp={resp}, expected "
            f"DECERR (RTL vs hw/sys/sep/doc/fabric.adoc)"
        )
        cpu_cfg_after2 = await self.filt.read_cpu(cfg_addr)
        assert (cpu_cfg_after2 & FILTER_RW_MASK) == (expected_cfg & FILTER_RW_MASK), (
            f"filter cfg corrupted by denied ext write after allow-list: "
            f"0x{cpu_cfg_after2:08x}"
        )
        self.logger.info(
            "CHK-OWNERSHIP-WINDOW PASS: filter cfg 0x%08x still DECERR after entry-1 allow "
            "window covers it (spec: only the SEP CPU can program the inbound filter)",
            cfg_addr)
