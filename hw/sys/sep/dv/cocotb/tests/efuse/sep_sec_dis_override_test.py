# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEC_DIS token-match override of LCC ``FEAT_CTRL``.

RAND-NONE. Real fuse sense (no ``+skip_fuse_sense``). The comparator hashes
the written ``SEC_DISABLE_TOKEN_I`` and compares it to the metal expected
digest ``SEP_SEC_DISABLE_TOKEN``. ``tb_top`` binds that parameter to
SHA-256 of the all-zero 32-byte token so a frontdoor write of zeros can
match. A nonzero token still mismatches. On match, ``sec_dis`` asserts and
``FEAT_CTRL`` follows ``feat_ctrl_expected(..., sec_dis=1)`` (all features
on, test group still gated by ``SECURE_TM=0``). A later mismatch drops
``sec_dis`` and restores the fail-closed PROD golden. The test does not
force ``sec_dis``. The token is written over the CPU-LSU AXI MMR after
sense; JTAG ``TOKEN_EOP`` activate is not claimed.
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD, M64, feat_ctrl_expected, lc_state_name
from env.sep_rma_token import token_digest
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
    """Match opens FEAT_CTRL; mismatch restores fail-closed PROD."""

    async def _present(self, token: int) -> SepRmaTokenMatchSeq:
        seq = SepRmaTokenMatchSeq(TOKEN_SEC_DISABLE, token)
        await self.start_seq(seq)
        return seq

    async def _check_feat(self, sec_dis: int, label: str) -> int:
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=sec_dis)
        assert feat != (M64 if sec_dis else 0), (
            f"{label} FAIL: golden collapsed to a vacuous constant "
            f"0x{feat:016x} for sec_dis={sec_dis}"
        )
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert observed == sec_dis and ctl.feat_ctrl == feat, (
            f"{label} FAIL: sec_dis={observed} want {sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want 0x{feat:016x}"
        )
        self.logger.info(
            "%s PASS: %s sec_dis=%d FEAT_CTRL=0x%016x",
            label, lc_state_name(LC_PROD), observed, ctl.feat_ctrl)
        return ctl.feat_ctrl

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS})
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        zero_digest = token_digest(_MATCH_TOKEN)
        assert zero_digest == _TB_SEC_DIS_DIGEST, (
            "CHK-DIGEST-BIND FAIL: SHA-256(0)="
            f"0x{zero_digest:064x} want 0x{_TB_SEC_DIS_DIGEST:064x}"
        )
        self.logger.info(
            "CHK-DIGEST-BIND PASS: SHA-256(0)=0x%064x "
            "(tb_top SEP_SEC_DISABLE_TOKEN bind)",
            zero_digest)

        closed = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        opened = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=1)
        assert closed != opened, (
            "CHK-OVERRIDE FAIL: fail-closed and override goldens are identical"
        )

        mm = await self._present(_MISMATCH_TOKEN)
        assert mm.match_code == TOKEN_MISMATCH, (
            f"CHK-MISMATCH FAIL: token=1 code=0x{(mm.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1",
            mm.match_code)
        await self._check_feat(0, "CHK-NO-OVERRIDE")

        hit = await self._present(_MATCH_TOKEN)
        assert hit.match_code == TOKEN_MATCH, (
            f"CHK-MATCH FAIL: zero token code=0x{(hit.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x}"
        )
        self.logger.info(
            "CHK-MATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after all-zero token",
            hit.match_code)
        await self._check_feat(1, "CHK-OVERRIDE")

        drop = await self._present(_MISMATCH_TOKEN)
        assert drop.match_code == TOKEN_MISMATCH, (
            f"CHK-DEACTIVATE FAIL: token=1 code=0x{(drop.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-DEACTIVATE PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1",
            drop.match_code)
        await self._check_feat(0, "CHK-RESTORE")
