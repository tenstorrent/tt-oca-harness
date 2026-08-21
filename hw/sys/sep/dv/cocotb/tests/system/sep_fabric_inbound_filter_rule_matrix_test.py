# SPDX-License-Identifier: Apache-2.0
"""Inbound-filter per-entry RULE matrix.

With the SEP inbound filter ACTIVE (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs ONE inbound FILTER_CONFIG allow-entry and the EXTERNAL SMN
master (m_axi, the only path through u_inbound_filter) proves per-entry rule
enforcement: an allowed address -> OKAY + exact CSR value; any other address ->
DECERR (block-by-default); clearing read_allowed/write_allowed flips the matched
read/write to DECERR. With smc_global_base=0 the inbound global->local remap is identity, so
the external master drives the SEP-local address directly.

Exercises the per-entry filter rule, not the whole-filter skip path
(sep_lcc_uvm_inbound_filter_gating_test proves the GLOBAL sep_debug skip gate,
filter wholly on/off). This test stays at sep_debug=0 the whole time and proves
the PER-ENTRY allow-by-rule vs block-by-default policy.

reference refs: fabric sep_inbound_filter_blockbydefault_test,
sep_inbound_filter_programming_ownership_test, sep_inbound_id_remap_test. Mapping: COVERED_STRONGER -- real external AXI master
through the live filter with an exact rdata value-check, vs the reference suite proxy / CSR-only.
CHK-OWNERSHIP ports the CPU-vs-external asymmetry at the filter CFG CSR
(0x10A2_1000): CPU-LSU reads the programmed rule, the external master completes
DECERR on read and write, and the denied write does not land. That is the
spec's "only the SEP CPU can program these filters" under the programmed allow
window, which does not include the CFG address.
RUN-MODE: no_cpu + external SMN master. FUSE-MODE: real PROD fuse sense (sep_debug=0
=> filter active). RAND-NONE (directed).
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD, feat_ctrl_expected, lc_state_name
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq
from seq_lib.sep_inbound_filter_rule_seq import (
    SepInboundFilterCfg, SepInboundFilter, ext_read_seq, ext_write_seq,
    RESP_OKAY, RESP_DECERR,
)
from seq_lib.sep_fabric_csr_bank_seq import FILTER_RW_MASK

_MAX_SENSE_CYCLES = 20_000
# Distinct non-zero disable vectors so the decoded FEAT_CTRL is non-vacuous.
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF


@pyuvm.test()
class sep_fabric_inbound_filter_rule_matrix_test(sep_base_test):
    """Per-entry inbound-filter allow-rule vs block-by-default, via the external master."""

    async def _ext_read(self, addr: int) -> tuple[int, int]:
        seq = ext_read_seq(addr)
        await self.start_ext_seq(seq)
        return seq.resp_code, (seq.rdata & 0xFFFF_FFFF)

    async def _ext_write(self, addr: int, data: int) -> int:
        seq = ext_write_seq(addr, data)
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
        self.fcfg = SepInboundFilterCfg()
        self.logger.info("inbound-filter config: %s", self.fcfg.summary())

        await self._bring_up_prod_filter_active()
        self.filt = SepInboundFilter(self)

        # Stage the allowed target with a distinctive value via the CPU-LSU (no filter).
        await self.filt.stage_target(self.fcfg.allow_addr, self.fcfg.allow_value)
        staged = await self.filt.read_cpu(self.fcfg.allow_addr)
        assert staged == self.fcfg.allow_value, (
            f"staged target 0x{self.fcfg.allow_addr:08x}=0x{staged:08x} != 0x{self.fcfg.allow_value:08x}"
        )

        # ---- PROVE-FIRST core: program one allow-entry, prove allow vs block ----
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=True)

        # CHK-ALLOW-RULE: external read of the allowed addr -> OKAY + the exact staged value
        # (proves the external path traversed the filter + remap and reached the real CSR).
        resp, data = await self._ext_read(self.fcfg.allow_addr)
        assert resp == RESP_OKAY, f"allowed ext read resp={resp}, expected OKAY (rule not enforced?)"
        assert data == self.fcfg.allow_value, (
            f"allowed ext read 0x{data:08x} != staged 0x{self.fcfg.allow_value:08x} "
            f"(external path did not reach the CSR)"
        )
        self.logger.info("CHK-ALLOW-RULE PASS: ext read 0x%08x -> OKAY, rdata=0x%08x",
                         self.fcfg.allow_addr, data)

        # CHK-BLOCK-DEFAULT: external read of a non-allowed addr -> DECERR (block-by-default).
        resp, _ = await self._ext_read(self.fcfg.blocked_addr)
        assert resp == RESP_DECERR, (
            f"non-allowed ext read 0x{self.fcfg.blocked_addr:08x} resp={resp}, expected DECERR"
        )
        self.logger.info("CHK-BLOCK-DEFAULT PASS: ext read 0x%08x -> DECERR (block-by-default)",
                         self.fcfg.blocked_addr)

        # ---- per-entry field enforcement (after the core is proven) ----
        # CHK-READ-ALLOWED: clear read_allowed (write_allowed stays) -> the SAME allowed read is
        # now DECERR; restore read_allowed -> OKAY again (read gated by read_allowed, matched to
        # a READ probe).
        await self.filt.program_rule(self.fcfg, read_allowed=False, write_allowed=True)
        resp, _ = await self._ext_read(self.fcfg.allow_addr)
        assert resp == RESP_DECERR, f"read_allowed=0 should block the read, got resp={resp}"
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=True)
        resp, data = await self._ext_read(self.fcfg.allow_addr)
        assert resp == RESP_OKAY and data == self.fcfg.allow_value, (
            f"restoring read_allowed should re-allow the read (resp={resp}, data=0x{data:08x})"
        )
        self.logger.info("CHK-READ-ALLOWED PASS: read_allowed gates the matched ext read (DECERR<->OKAY)")

        # CHK-WRITE-ALLOWED: clear write_allowed (read_allowed stays) -> ext WRITE to the allowed
        # addr is DECERR; set write_allowed -> the write is accepted (B-channel OKAY) and lands.
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=False)
        resp = await self._ext_write(self.fcfg.allow_addr, 0x5555_AAAA)
        assert resp == RESP_DECERR, f"write_allowed=0 should block the write, got resp={resp}"
        await self.filt.program_rule(self.fcfg, read_allowed=True, write_allowed=True)
        resp = await self._ext_write(self.fcfg.allow_addr, 0x5555_AAAA)
        assert resp == RESP_OKAY, f"write_allowed=1 should accept the write, got resp={resp}"
        landed = await self.filt.read_cpu(self.fcfg.allow_addr)
        assert landed == 0x5555_AAAA, f"allowed ext write did not land (0x{landed:08x})"
        self.logger.info("CHK-WRITE-ALLOWED PASS: write_allowed gates the matched ext write (DECERR<->OKAY, landed)")

        # CHK-OWNERSHIP: CPU-LSU vs external at the filter CFG CSR. The CPU reads
        # the programmed rule; the external master is denied read and write with a
        # completed DECERR; the denied write does not land. The allow window does
        # not cover this CSR; CHK-ALLOW-RULE already showed OKAY on the allowed
        # address in this run, so the DECERR is not a dead bus.
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

        # CHK-NONVAC before the spec-vs-RTL window check: allow + block were already
        # observed. The next assert is expected to FAIL on today's RTL.
        self.logger.info(
            "CHK-NONVAC PASS: allow + block both observed with filter active (sep_debug=0)")

        # fabric.adoc: "Only the SEP CPU can program these filters." The deny above
        # could still be block-by-default (CFG is outside entry 0's window). A second
        # entry allow-lists the CFG address with read+write; the spec sentence holds
        # only if the external path still DECERR and still cannot land a write.
        own = SepInboundFilterCfg(entry=1)
        own.allow_addr = cfg_addr
        await self.filt.program_rule(own, read_allowed=True, write_allowed=True)
        resp, _ = await self._ext_read(cfg_addr)
        assert resp == RESP_DECERR, (
            f"CHK-OWNERSHIP-WINDOW FAIL: after allow-listing filter cfg "
            f"0x{cfg_addr:08x} on entry 1, external read resp={resp}, expected "
            f"DECERR (RTL vs fabric.adoc: only the SEP CPU programs the filter)"
        )
        resp = await self._ext_write(cfg_addr, 0xFFFF_FFFF)
        assert resp == RESP_DECERR, (
            f"CHK-OWNERSHIP-WINDOW FAIL: after allow-listing filter cfg "
            f"0x{cfg_addr:08x} on entry 1, external write resp={resp}, expected "
            f"DECERR (RTL vs fabric.adoc)"
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
