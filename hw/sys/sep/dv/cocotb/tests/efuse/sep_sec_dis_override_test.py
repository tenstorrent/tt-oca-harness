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

hw/sys/sep/doc/security_disable.adoc: a match does not release the SEP
reset. The IC_RESET ``sep_reset_n`` override is an independent step: it
releases both reset probes and leaves feature control closed. The match
then opens feature control without waiting for sensing
(hw/sys/sep/doc/token_processing.adoc) and leaves the reset held. Clearing
the override returns both probes to 0.

The evidence is the two reset probes and ``FEAT_CTRL``. The test drives
``jtag_sep_reset_n_ovrd_i`` and ``jtag_sep_reset_n_val_i``. A transaction
to a block that reset holds, and a write of the DTP IC_RESET register,
are not claimed. JTAG ``TOKEN_EOP`` activate is not claimed.

While SEC_DIS is active and sensing is still open, a read of the
``LC_STATE`` shadow-map word must return AXI OKAY. The map gate input is
tied to 0, so that read returns an error and ``CHK-MAP-OPEN`` fails. The
other checkers run first.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import LC_PROD, M64, feat_ctrl_expected, lc_state_name
from env.sep_rma_token import token_digest
from sep_base_test import sep_base_test
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_rma_token_seq import (
    TOKEN_MATCH,
    TOKEN_MISMATCH,
    TOKEN_SEC_DISABLE,
    SepRmaTokenMatchSeq,
)
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_MAX_SENSE_CYCLES = 20_000
_RESET_SYNC_CYCLES = 32
_SIP_DIS = 0x0F0F_0F0F_0F0F_0F0F
_SYS_DIS = 0x00FF_00FF_00FF_00FF
_MATCH_TOKEN = 0
_MISMATCH_TOKEN = 1
# hw/sys/sep/doc/lifecycle_controller.adoc: the OTP controller initializes
# the shadow output to the INVALID encoding (4'b1111), and the life-cycle
# controller produces the INVALID feature-control profile before sensing
# completes. That encoding is outside the named lifecycle set, so the
# golden's other-encodings row is the closed feature-control value.
_WITHHELD_LC = 0xF
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
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0 (match alone leaves the reset held)"
        )

    def _require_sense_open(self, label: str, *, sec_dis: int | None = None) -> None:
        """Fail if fuse sense has already finished, so this window was not observed."""
        dut = cocotb.top
        assert not self.rd_known(dut.sep_fuse_sense_done_o), (
            f"{label} WINDOW-CLOSED: sense finished before this check. "
            "This is not the contract failing -- rerun; if it repeats, move the check earlier"
        )
        assert self.rd(dut.ext_boot_seq_done_i), (
            f"{label} WINDOW-CLOSED: ext_boot_seq_done_i is 0, so sense is not the only held term"
        )
        if sec_dis is not None:
            got = int(dut.lcc_security_disable_probe_o.value) & 0x1
            assert got == sec_dis, f"{label} FAIL: sec_dis={got} want {sec_dis}"

    def _drive_sep_reset_override(self, ovrd: int, val: int) -> None:
        dut = cocotb.top
        dut.jtag_sep_reset_n_ovrd_i.value = ovrd
        dut.jtag_sep_reset_n_val_i.value = val

    async def _wait_resets(self, want: int, label: str, *, sec_dis: int) -> None:
        """Poll both reset probes until they equal ``want``, while sense stays open."""
        dut = cocotb.top
        for _ in range(_RESET_SYNC_CYCLES):
            await RisingEdge(dut.clk_i)
            self._require_sense_open(label, sec_dis=sec_dis)
            cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
            fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
            if cpu_rst == want and fabric_rst == want:
                return
        cpu_rst = self.rd_known(dut.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(dut.dbg_sep_reset_n_o)
        raise AssertionError(
            f"{label} FAIL: sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst} "
            f"want {want}/{want} within {_RESET_SYNC_CYCLES} cycles "
            f"(jtag_sep_reset_n_ovrd_i={int(dut.jtag_sep_reset_n_ovrd_i.value)} "
            f"jtag_sep_reset_n_val_i={int(dut.jtag_sep_reset_n_val_i.value)})"
        )

    async def _check_window_feat(self, sec_dis: int, label: str) -> None:
        """Read FEAT_CTRL while sensing is still open.

        The withheld map presents the invalid lifecycle encoding, so the closed
        golden is that row. ``sec_dis=1`` forces every feature bit on.
        """
        self._require_sense_open(label, sec_dis=sec_dis)
        observed = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        feat = feat_ctrl_expected(_WITHHELD_LC, 0, 0, sec_dis=sec_dis)
        ctl = SepLccFeatCtrlCheckSeq(feat)
        await self.start_seq(ctl)
        self._require_sense_open(label, sec_dis=sec_dis)
        assert observed == sec_dis and ctl.feat_ctrl == feat, (
            f"{label} FAIL: sec_dis={observed} want {sec_dis} "
            f"FEAT_CTRL=0x{ctl.feat_ctrl:016x} want 0x{feat:016x} while sense_done=0"
        )
        self.logger.info(
            "%s PASS: sense_done=0 sec_dis=%d FEAT_CTRL=0x%016x",
            label,
            observed,
            ctl.feat_ctrl,
        )

    async def _check_override_alone(self) -> None:
        """The override releases reset and leaves feature control closed.

        hw/sys/sep/doc/security_disable.adoc: the override and the token match
        are independent. This step runs before any match.
        """
        self._require_sense_open("CHK-OVR-ALONE", sec_dis=0)
        self._drive_sep_reset_override(1, 1)
        await self._wait_resets(1, "CHK-OVR-ALONE", sec_dis=0)
        await self._check_window_feat(0, "CHK-OVR-ALONE")
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 1 and fabric_rst == 1, (
            f"CHK-OVR-ALONE FAIL: feature control stayed closed but the reset moved "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 1/1"
        )
        self.logger.info(
            "CHK-OVR-ALONE PASS: ovrd=1 sense_done=0 sec_dis=0 "
            "sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1"
        )
        self._drive_sep_reset_override(0, 0)
        await self._wait_resets(0, "CHK-OVR-ALONE", sec_dis=0)
        self.logger.info(
            "CHK-OVR-ALONE PASS: ovrd=0 sense_done=0 sec_dis=0 "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0"
        )

    async def _check_override_after_match(self) -> None:
        """The same override inputs release the reset after the match.

        A match has already left both probes at 0. This drives
        ``jtag_sep_reset_n_ovrd_i`` and ``jtag_sep_reset_n_val_i``. The DTP
        IC_RESET register write is not claimed.
        """
        self._require_sense_open("CHK-OVR-AFTER", sec_dis=1)
        self._drive_sep_reset_override(1, 1)
        await self._wait_resets(1, "CHK-OVR-AFTER", sec_dis=1)
        self.logger.info(
            "CHK-OVR-AFTER PASS: ovrd=1 val=1 sense_done=0 sec_dis=1 "
            "sep_cpu_reset_n_o=1 dbg_sep_reset_n_o=1"
        )
        self._drive_sep_reset_override(0, 0)
        await self._wait_resets(0, "CHK-OVR-AFTER", sec_dis=1)
        self.logger.info(
            "CHK-OVR-AFTER PASS: ovrd=0 sense_done=0 sec_dis=1 "
            "sep_cpu_reset_n_o=0 dbg_sep_reset_n_o=0"
        )

    async def _read_shadow_map(self) -> str | None:
        """Require an OKAY read of the LC_STATE shadow word while sense is open.

        Returns the failure text when the read is not OKAY. The scoreboard does
        not also grade this response: this checker owns that one failure.
        """
        self._require_sense_open("CHK-MAP-OPEN", sec_dis=1)
        addr = SepEfuseImage.field("LC_STATE").shadow_addr
        seq = SepAxiAccessSeq(
            "sec_dis_map_rd",
            op=SepAxiOp.READ,
            addr=addr,
            size=2,
            allow_ungraded_read_resp=True,
        )
        await self.start_seq(seq)
        self._require_sense_open("CHK-MAP-OPEN", sec_dis=1)
        if seq.resp_ok and not seq.timed_out:
            self.logger.info(
                "CHK-MAP-OPEN PASS: LC_STATE @0x%08x AXI OKAY rdata=0x%08x "
                "while sec_dis=1 sense_done=0",
                addr,
                seq.rdata & 0xFFFF_FFFF,
            )
            return None
        return (
            "CHK-MAP-OPEN FAIL: sec_dis=1 sense_done=0 "
            f"LC_STATE @0x{addr:08x} resp_ok={int(seq.resp_ok)} resp={seq.resp_code} "
            f"timed_out={int(seq.timed_out)} rdata=0x{seq.rdata & 0xFFFF_FFFF:08x}, "
            "want AXI OKAY"
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
        await self._check_override_alone()
        pre = await self._present(_MATCH_TOKEN)
        assert pre.match_code == TOKEN_MATCH, (
            f"CHK-SENSE-GATED-RESET FAIL: zero token code=0x{(pre.match_code or 0):02x} "
            f"want MATCH 0x{TOKEN_MATCH:02x} before sense-done"
        )
        self._check_reset_stays_sense_gated()
        await self._check_window_feat(1, "CHK-FEAT-PRESENSE")
        cpu_rst = self.rd_known(cocotb.top.sep_cpu_reset_n_o)
        fabric_rst = self.rd_known(cocotb.top.dbg_sep_reset_n_o)
        assert cpu_rst == 0 and fabric_rst == 0, (
            f"CHK-FEAT-PRESENSE FAIL: feature control opened but the reset moved "
            f"sep_cpu_reset_n_o={cpu_rst} dbg_sep_reset_n_o={fabric_rst}, want 0/0"
        )
        await self._check_override_after_match()
        map_fail = await self._read_shadow_map()
        if map_fail is not None:
            self.logger.info(map_fail)
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
        if map_fail is not None:
            raise AssertionError(map_fail)
