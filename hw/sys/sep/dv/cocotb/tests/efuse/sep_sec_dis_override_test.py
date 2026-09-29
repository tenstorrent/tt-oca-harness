# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEC_DIS token-match override of LCC ``FEAT_CTRL``, plus the sense-gated reset.

RAND-NONE. Real fuse sense (no ``+skip_fuse_sense``). The comparator hashes
the written ``SEC_DISABLE_TOKEN_I`` and compares it to the metal expected
digest ``SEP_SEC_DISABLE_TOKEN``. ``tb_top`` binds that parameter to
SHA-256 of the all-zero 32-byte token so a frontdoor write of zeros can
match. A nonzero token still mismatches. On match, ``sec_dis`` asserts and
``FEAT_CTRL`` follows ``feat_ctrl_expected(..., sec_dis=1)`` (all features
on). A later mismatch drops
``sec_dis`` and restores the fail-closed PROD golden. The test does not
force ``sec_dis``.

A SEC_DIS match does not by itself boot SEP. The reset contract comes from
hw/sys/sep/doc/reset_controller.adoc: ``sep_reset_n`` "holds every IP in
reset until eFuse sensing completes during boot". This leaf grades that
sentence: a match does not release ``sep_cpu_reset_n`` / ``sep_reset_n``
while sense is still open. hw/sys/sep/doc/security_disable.adoc also says
that with SEC_DIS active the SEP can boot even if fuse sense never
completes; that sentence is not graded here. The first match is presented after
``release_no_cpu_reset`` and before ``sep_fuse_sense_done_o``, and with
``ext_boot_seq_done_i`` already 1 the reset probes must stay 0. The
token is written over the CPU-LSU AXI MMR. The TDR release itself is
not claimed here, and neither is JTAG ``TOKEN_EOP`` activate.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_lcc_golden import LC_PROD, M64, feat_ctrl_expected, lc_state_name
from env.sep_rma_token import token_digest
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_MATCH,
    TOKEN_MISMATCH,
    TOKEN_SEC_DISABLE,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_MAX_SENSE_CYCLES = 20_000
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_MATCH_TOKEN = 0
_MISMATCH_TOKEN = 1
# SHA-256 of 32 zero bytes; must match ``SEC_DIS_TB_DIGEST`` in ``tb/tb_top.sv``.
_TB_SEC_DIS_DIGEST = 0x66687AADF862BD776C8FC18B8E9F8E20089714856EE233B3902A591D0D5F2925


@pyuvm.test()
class sep_sec_dis_override_test(sep_base_test):
    """Match opens FEAT_CTRL but does not release the sense-gated reset."""

    async def _present(self, token: int) -> SepRmaTokenMatchSeq:
        seq = SepRmaTokenMatchSeq(TOKEN_SEC_DISABLE, token)
        await self.start_seq(seq)
        return seq

    async def _check_feat(self, sec_dis: int, label: str) -> int:
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        if sec_dis:
            # hw/sys/sep/doc/lifecycle_controller.adoc: SEC_DIS=1 forces
            # feat_ctrl to all ones. That constant is the contract, not a
            # collapse. The fail-closed word above is the contrast.
            assert feat == M64, f"{label} FAIL: override golden 0x{feat:016x} is not all ones"
        else:
            assert feat not in (0, M64), (
                f"{label} FAIL: fail-closed golden collapsed to 0x{feat:016x}"
            )
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert observed == sec_dis and ctl.feat_ctrl == feat, (
            f"{label} FAIL: sec_dis={observed} want {sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want 0x{feat:016x}"
        )
        self.logger.info(
            "%s PASS: %s sec_dis=%d FEAT_CTRL=0x%016x",
            label,
            lc_state_name(LC_PROD),
            observed,
            ctl.feat_ctrl,
        )
        return ctl.feat_ctrl

    def _check_reset_stays_sense_gated(self) -> None:
        """A SEC_DIS match alone must NOT release the sense-gated reset.

        hw/sys/sep/doc/reset_controller.adoc: ``sep_reset_n`` holds every
        IP in reset until eFuse sensing completes during boot.
        ``ext_boot_seq_done_i`` is already 1, so sense is the only term
        still holding the reset -- this checker fails if a match releases
        it.
        """
        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            "CHK-SENSE-GATED-RESET WINDOW-CLOSED: sense finished during the token "
            "write, so the pre-sense window was never observed. This is not the reset "
            "contract failing -- rerun; if it repeats, present the token earlier"
        )
        assert self.rd(dut.ext_boot_seq_done_i), (
            "CHK-SENSE-GATED-RESET WINDOW-CLOSED: ext_boot_seq_done_i is 0, so sense "
            "is not the only held term and this window does not grade the contract"
        )
        sec_dis = int(dut.lcc_security_disable_probe_o.value) & 0x1
        assert sec_dis == 1, (
            f"CHK-SENSE-GATED-RESET FAIL: sec_dis={sec_dis} want 1 before the reset check"
        )
        cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
        assert cpu_rst == 0 and fabric_rst == 0, (
            f"CHK-SENSE-GATED-RESET FAIL: sec_dis=1 sense_done=0 ext_boot_seq_done=1 "
            f"but sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 0/0 "
            f"-- a SEC_DIS match bypassed the sense gate on the reset"
        )
        self.logger.info(
            "CHK-SENSE-GATED-RESET PASS: sec_dis=1 sense_done=0 ext_boot_seq_done=1 "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 (match alone does not boot SEP)"
        )

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS}
        )
        self.write_efuse_image(image)

        zero_digest = token_digest(_MATCH_TOKEN)
        assert zero_digest == _TB_SEC_DIS_DIGEST, (
            "test bug: SHA-256(0)="
            f"0x{zero_digest:064x} want TB digest 0x{_TB_SEC_DIS_DIGEST:064x} "
            "-- the match token and the tb_top bind constant disagree "
            "(DV consistency, not a DUT checker)"
        )

        closed = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        opened = feat_ctrl_expected(LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=1)
        assert closed != opened, "CHK-OVERRIDE FAIL: fail-closed and override goldens are identical"

        await self.release_no_cpu_reset()
        pre = await self._present(_MATCH_TOKEN)
        assert pre.match_code == TOKEN_MATCH, (
            f"CHK-SENSE-GATED-RESET FAIL: zero token code=0x{(pre.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x} before sense-done"
        )
        self._check_reset_stays_sense_gated()
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"CHK-SENSE-GATED-RESET FAIL: after sense-done "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1 "
            "-- the pre-sense low check has no live high control without this"
        )

        mm = await self._present(_MISMATCH_TOKEN)
        assert mm.match_code == TOKEN_MISMATCH, (
            f"CHK-MISMATCH FAIL: token=1 code=0x{(mm.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1", mm.match_code
        )
        await self._check_feat(0, "CHK-NO-OVERRIDE")

        hit = await self._present(_MATCH_TOKEN)
        assert hit.match_code == TOKEN_MATCH, (
            f"CHK-MATCH FAIL: zero token code=0x{(hit.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x}"
        )
        self.logger.info(
            "CHK-MATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after all-zero token", hit.match_code
        )
        await self._check_feat(1, "CHK-OVERRIDE")

        drop = await self._present(_MISMATCH_TOKEN)
        assert drop.match_code == TOKEN_MISMATCH, (
            f"CHK-DEACTIVATE FAIL: token=1 code=0x{(drop.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-DEACTIVATE PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1", drop.match_code
        )
        await self._check_feat(0, "CHK-RESTORE")
