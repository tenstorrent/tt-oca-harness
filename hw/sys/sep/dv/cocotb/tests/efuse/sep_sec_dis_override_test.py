# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEC_DIS token-match reachability against the metal-fixed expected digest.

RAND-NONE. Real fuse sense (no ``+skip_fuse_sense``). The comparator hashes
the written ``SEC_DISABLE_TOKEN_I`` and compares it to a metal-fixed
constant reconstructed from ``SEP_SEC_DISABLE_TOKEN``
(``hw/ip/efuse/rtl/efuse_token_processing.sv``). That parameter is all-zero
in this tree, so the expected digest is 0. SHA-256 of the all-zero token is
not 0, and no other written token hashes to 0, so a match is unreachable
without a backdoor. This vehicle records that fact and proves fail-closed
``FEAT_CTRL``; it does not fake ``sec_dis``.

The unreferenced firmware ``fw/tests/sep_efuse_fw_token_match_test`` asserts
a zero-token match. That is a hint, not evidence: it is in no testlist and
disagrees with this RTL.
"""

from __future__ import annotations

import cocotb
import pyuvm

from sep_base_test import sep_base_test
from env.sep_lcc_golden import LC_PROD, M64, feat_ctrl_expected, lc_state_name
from env.sep_rma_token import token_digest
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_MISMATCH,
    TOKEN_SEC_DISABLE,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_MAX_SENSE_CYCLES = 20_000
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_METAL_EXPECTED = 0
_ZERO_TOKEN = 0
_NONZERO_TOKEN = 1


@pyuvm.test()
class sep_sec_dis_override_test(sep_base_test):
    """Zero and nonzero tokens mismatch; FEAT_CTRL stays fail-closed."""

    async def _present(self, token: int) -> SepRmaTokenMatchSeq:
        seq = SepRmaTokenMatchSeq(TOKEN_SEC_DISABLE, token)
        await self.start_seq(seq)
        return seq

    async def run_scenario(self) -> None:
        image = self.select_efuse_image(
            lc_raw=LC_PROD, fixed={"SIP_DIS": _SIP_DIS, "SYS_DIS": _SYS_DIS})
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        zero_digest = token_digest(_ZERO_TOKEN)
        assert zero_digest != _METAL_EXPECTED, (
            "CHK-REACHABILITY FAIL: SHA-256(0) equals the metal expected; "
            "this tree's all-zero constant would then be reachable"
        )
        self.logger.info(
            "CHK-REACHABILITY PASS: metal expected=0 SHA-256(0)=0x%064x "
            "(no preimage of 0; match unreachable)",
            zero_digest)

        zero = await self._present(_ZERO_TOKEN)
        assert zero.match_code == TOKEN_MISMATCH, (
            f"CHK-ZERO-MISMATCH FAIL: zero token code=0x{(zero.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-ZERO-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after all-zero token",
            zero.match_code)

        nz = await self._present(_NONZERO_TOKEN)
        assert nz.match_code == TOKEN_MISMATCH, (
            f"CHK-NONZERO-MISMATCH FAIL: token=1 code=0x{(nz.match_code or 0):02x} "
            f"want MISMATCH 0x{TOKEN_MISMATCH:02x}"
        )
        self.logger.info(
            "CHK-NONZERO-MISMATCH PASS: SEC_DISABLE_TOKEN_MATCH=0x%02x after token=1",
            nz.match_code)

        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(
            LC_PROD, _SIP_DIS, _SYS_DIS, demote_1=0, sec_dis=0)
        assert feat != M64, (
            "CHK-NO-OVERRIDE FAIL: fail-closed golden is all-ones; DIS pins "
            "must keep FEAT_CTRL non-vacuous"
        )
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        assert sec_dis == 0 and ctl.feat_ctrl == feat and ctl.feat_ctrl != M64, (
            f"CHK-NO-OVERRIDE FAIL: sec_dis={sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want fail-closed 0x{feat:016x}"
        )
        self.logger.info(
            "CHK-NO-OVERRIDE PASS: %s sec_dis=0 FEAT_CTRL=0x%016x "
            "(not all-ones; override not taken)",
            lc_state_name(LC_PROD), ctl.feat_ctrl)
