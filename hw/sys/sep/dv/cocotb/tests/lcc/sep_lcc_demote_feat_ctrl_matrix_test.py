# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FEAT_CTRL and the inbound filter follow the golden for every LC x DEMOTE_1/2 x DIS cell.

RAND-REP. The test walks TEST_DEV and PROD against (0,0)/(1,0)/(0,1)/(1,1) demote
cells, first with DIS=0, then one PROD compose cell that closes
``sep_fuse_dbg`` / ``smc_fuse_dbg`` while the DTP cases stay open, then a
seed-extended pinned DIS pair. ``feat_ctrl`` is checked against the
spec-derived golden. One live inbound filter probe per cell follows
``sep_debug`` (DECERR when 0, OKAY when 1); that rule is the specification
contract recorded in ``seq_lib/sep_lcc_inbound_filter_gating_seq.py``
(``lifecycle_controller.adoc``, ``fabric.adoc`` sep-traffic-filter-decode,
``hw/ip/axi_filter/doc/index.adoc`` axi-traffic-filter-blocked). The two
DFT-inserted fuse-path disable ports follow the same FEAT_CTRL.

``sep_efuse_lcc_lc_state_stitch_test`` covers the end-to-end LC -> FEAT_CTRL
path. This test covers the LC x DEMOTE x DIS product.
Real fuse sense. DEMOTE is write-once-set; resense returns the CSRs to 0.
After the product walk, one seed-selected group is locked: a later demote
write is ignored until rst_ni.
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.sep_efuse_image import LC_WORD_IDX, SepEfuseImage
from env.sep_lcc_golden import (
    DBG_DISABLE_UNCLAIMED,
    LC_PROD,
    LC_TEST_DEV,
    SEP_FUSE_DBG_BIT,
    SIP_DBG_BIT,
    SMC_FUSE_DBG_BIT,
    dbg_disable_expected,
    dbg_disable_sample,
    feat_ctrl_expected,
    fuse_dft_disable_expected,
    lc_state_name,
)
from sep_base_test import sep_base_test
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_lcc_demote_matrix_seq import SepLccDemoteMatrixCfg
from seq_lib.sep_lcc_inbound_filter_gating_seq import (
    DEMOTE_BIT,
    DEMOTE_LOCK_BIT,
    RESP_DECERR,
    SepExtAxiProbeSeq,
    SepLccDemoteSeq,
    SepLccFeatCtrlCheckSeq,
)
from seq_lib.sep_lcc_stitch_check_seq import LC_STATE_SHADOW

_MAX_SENSE_CYCLES = 20_000
_LC_STATE_BIT_BASE = LC_WORD_IDX * 32
RESP_OKAY = 0


@pyuvm.test()
class sep_lcc_demote_feat_ctrl_matrix_test(sep_base_test):
    """Every demote cell matches the feat_ctrl golden and gates one live filter probe."""

    def _check_dbg_disable(self, feat_ctrl: int, tag: str) -> None:
        """dbg_disable against the DTP gating ladder, for this same FEAT_CTRL.

        The eleven debug-disable outputs are the consumer side of feature
        control: FEAT_CTRL says which debug scopes are open, dbg_disable is what
        the DTP, JTAG and SMU paths are actually gated on. The two OTP
        JTAG2AXIL bits are tied to zero, so they cannot distinguish a correct
        gating formula from a broken one. The walk checks the rest against
        the same FEAT_CTRL the cell above just checked, so the two are one
        consistent claim rather than two independent guesses.
        """
        got = dbg_disable_sample(cocotb.top)
        want = dbg_disable_expected(feat_ctrl)
        for name, exp in want.items():
            assert got[name] == exp, (
                f"{tag}: dbg_disable.{name}={got[name]} expected {exp} for "
                f"FEAT_CTRL=0x{feat_ctrl:016x} "
                f"(sep_dbg={feat_ctrl & 1} chiplet_dbg={(feat_ctrl >> 1) & 1} "
                f"sip_dbg={(feat_ctrl >> SIP_DBG_BIT) & 1})"
            )
        if DBG_DISABLE_UNCLAIMED:
            self.logger.info(
                "CHK-DBG-DISABLE PASS: %s %d of %d bits match the gating ladder (unclaimed: %s)",
                tag,
                len(want),
                len(want) + len(DBG_DISABLE_UNCLAIMED),
                ", ".join(DBG_DISABLE_UNCLAIMED),
            )
        else:
            self.logger.info(
                "CHK-DBG-DISABLE PASS: %s all %d bits match the gating ladder",
                tag,
                len(want),
            )

    def _check_fuse_dft_disable(self, feat_ctrl: int, tag: str) -> None:
        """DFT-inserted fuse-path disables for this same FEAT_CTRL.

        The ports have no CSR mirror. sep_fuse_dft_disable is Case 3 AND
        sep_fuse_dbg, inverted; smc_fuse_dft_disable is Case 2 AND
        smc_fuse_dbg, inverted. A granular bit is an extra term, not a
        substitute for its case.
        """
        want = fuse_dft_disable_expected(feat_ctrl)
        got = {
            "sep_fuse_dft_disable": int(cocotb.top.sep_fuse_dft_disable_o.value) & 1,
            "smc_fuse_dft_disable": int(cocotb.top.smc_fuse_dft_disable_o.value) & 1,
        }
        for name, exp in want.items():
            assert got[name] == exp, (
                f"{tag}: {name}={got[name]} expected {exp} for "
                f"FEAT_CTRL=0x{feat_ctrl:016x} "
                f"(sep_fuse_dbg={(feat_ctrl >> SEP_FUSE_DBG_BIT) & 1} "
                f"smc_fuse_dbg={(feat_ctrl >> SMC_FUSE_DBG_BIT) & 1} "
                f"sep_dbg={feat_ctrl & 1} chiplet_dbg={(feat_ctrl >> 1) & 1} "
                f"sip_dbg={(feat_ctrl >> SIP_DBG_BIT) & 1})"
            )
        self.logger.info(
            "CHK-FUSE-DFT-DIS PASS: %s sep=%d smc=%d (sep_fuse_dbg=%d smc_fuse_dbg=%d)",
            tag,
            got["sep_fuse_dft_disable"],
            got["smc_fuse_dft_disable"],
            (feat_ctrl >> SEP_FUSE_DBG_BIT) & 1,
            (feat_ctrl >> SMC_FUSE_DBG_BIT) & 1,
        )

    async def _check_cell(
        self,
        image: SepEfuseImage,
        *,
        demote_1: int,
        demote_2: int,
        tag: str,
    ) -> None:
        # SEC_DIS forces FEAT_CTRL to all-ones, so feeding the probe into the
        # golden would make a stuck-at-1 probe agree with a stuck-at-1 DUT at
        # every cell in the matrix -- the whole walk would pass with the decode
        # bypassed. This test presents no SEC_DIS token, so the value is known
        # in advance: assert it and pass the literal.
        sec_dis = int(cocotb.top.lcc_security_disable_probe_o.value) & 0x1
        assert sec_dis == 0, (
            "SEC_DIS is asserted but this test never presents a token; with it "
            "set, FEAT_CTRL is all-ones regardless of LC state, the DIS vectors "
            "and both DEMOTE bits, so every cell below would be vacuous"
        )
        feat = feat_ctrl_expected(
            image.lc_raw(),
            image.field_int("SIP_DIS"),
            image.field_int("SYS_DIS"),
            demote_1=demote_1,
            demote_2=demote_2,
            sec_dis=0,
        )
        ctl = SepLccFeatCtrlCheckSeq(feat)
        mark = self.sb_mark()
        await self.start_seq(ctl)
        self.assert_sb_judged(mark, f"CHK-FEAT-CTRL {tag}")
        assert ctl.feat_ctrl == feat, (
            f"CHK-FEAT-CTRL FAIL: {tag} FEAT_CTRL=0x{ctl.feat_ctrl:016x} != golden 0x{feat:016x}"
        )
        assert ctl.sep_debug == (feat & 1), (
            f"{tag}: sep_debug={ctl.sep_debug} != FEAT_CTRL[0] of 0x{feat:016x}"
        )
        probe = SepExtAxiProbeSeq(LC_STATE_SHADOW)
        await self.start_ext_seq(probe)
        want = RESP_OKAY if ctl.sep_debug else RESP_DECERR
        assert probe.resp_code == want, (
            f"{tag}: ext probe resp={probe.resp_code}, expected {want} (sep_debug={ctl.sep_debug})"
        )
        self._check_dbg_disable(ctl.feat_ctrl, tag)
        self._check_fuse_dft_disable(ctl.feat_ctrl, tag)
        self.logger.info(
            "CHK-FEAT-CTRL PASS: %s FEAT_CTRL=0x%016x sep_debug=%d",
            tag,
            ctl.feat_ctrl,
            ctl.sep_debug,
        )
        self.logger.info(
            "CHK-LIVE-GATE PASS: %s ext %s (sep_debug=%d)",
            tag,
            "OKAY" if want == RESP_OKAY else "DECERR",
            ctl.sep_debug,
        )

    async def _walk_demotes(self, image: SepEfuseImage, *, dis_tag: str) -> int:
        n = 0
        lc = lc_state_name(image.lc_raw())
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{lc}/{dis_tag}/d00")
        n += 1
        d1 = SepLccDemoteSeq(group=1)
        await self.start_seq(d1)
        await self._check_cell(image, demote_1=1, demote_2=0, tag=f"{lc}/{dis_tag}/d10")
        n += 1
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{lc}/{dis_tag}/d00b")
        d2 = SepLccDemoteSeq(group=2)
        await self.start_seq(d2)
        await self._check_cell(image, demote_1=0, demote_2=1, tag=f"{lc}/{dis_tag}/d01")
        n += 1
        d1b = SepLccDemoteSeq(group=1)
        await self.start_seq(d1b)
        await self._check_cell(image, demote_1=1, demote_2=1, tag=f"{lc}/{dis_tag}/d11")
        n += 1
        return n

    async def _program_dis_bits(self, image: SepEfuseImage, sip_mask: int, sys_mask: int) -> None:
        """W1S each mask into the matching SIP_DIS / SYS_DIS word of this image."""
        for name, mask in (("SIP_DIS", sip_mask), ("SYS_DIS", sys_mask)):
            fld = SepEfuseImage.field(name)
            for word_i in range(fld.n_words):
                word = (mask >> (32 * word_i)) & 0xFFFF_FFFF
                cur = image.words[fld.word + word_i]
                new_bits = word & ~cur
                bit = 0
                while new_bits:
                    if new_bits & 1:
                        await self.start_seq(
                            sep_efuse_otp_program_seq(fld.word * 32 + word_i * 32 + bit)
                        )
                        image.words[fld.word + word_i] |= 1 << bit
                    new_bits >>= 1
                    bit += 1

    async def _check_lock(self, image: SepEfuseImage, *, group: int) -> None:
        """Lock DEMOTE_{group} at 0, reject a later set, then rst_ni releases it."""
        lc = lc_state_name(image.lc_raw())
        tag = f"{lc}/lock_g{group}"

        opened = SepLccDemoteSeq(group=group, value=DEMOTE_BIT)
        await self.start_seq(opened)
        assert opened.demote == 1 and opened.lock == 0, (
            f"{tag}: unlocked demote write did not land (demote={opened.demote} lock={opened.lock})"
        )
        d1 = 1 if group == 1 else 0
        d2 = 1 if group == 2 else 0
        await self._check_cell(image, demote_1=d1, demote_2=d2, tag=f"{tag}/unlocked")

        await self.resense(max_cycles=_MAX_SENSE_CYCLES)

        locked = SepLccDemoteSeq(group=group, value=DEMOTE_LOCK_BIT)
        await self.start_seq(locked)
        assert locked.demote == 0 and locked.lock == 1, (
            f"{tag}: lock write demote={locked.demote} lock={locked.lock}, expected 0/1"
        )

        blocked = SepLccDemoteSeq(group=group, value=DEMOTE_BIT, expected=DEMOTE_LOCK_BIT)
        await self.start_seq(blocked)
        assert blocked.demote == 0 and blocked.lock == 1, (
            f"{tag}: locked demote write landed (demote={blocked.demote} lock={blocked.lock})"
        )
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{tag}/held")
        self.logger.info(
            "CHK-DEMOTE-LOCK PASS: %s lock held demote at 0; feat_ctrl stayed undemoted", tag
        )

        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        released = SepLccDemoteSeq(group=group, value=DEMOTE_BIT)
        await self.start_seq(released)
        assert released.demote == 1 and released.lock == 0, (
            f"{tag}: post-rst_ni demote write did not land "
            f"(demote={released.demote} lock={released.lock})"
        )
        await self._check_cell(image, demote_1=d1, demote_2=d2, tag=f"{tag}/released")
        self.logger.info(
            "CHK-DEMOTE-LOCK-RESET PASS: %s rst_ni released the lock; demote write landed", tag
        )

    async def run_scenario(self) -> None:
        cfg = SepLccDemoteMatrixCfg(self.random_seed())
        self.logger.info("lcc demote matrix: %s", cfg.summary())

        sip0, sys0 = cfg.dis_zero
        # t=0 OTP load is staged by cocotb/dv_sim_prestage.py with DIS=0 / TEST_DEV.
        image = self.select_efuse_image(
            lc_raw=LC_TEST_DEV, fixed={"SIP_DIS": sip0, "SYS_DIS": sys0}
        )
        self.write_efuse_image(image)
        await self.bring_up_and_wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)

        cells = 0
        cells += await self._walk_demotes(image, dis_tag="dis0")

        await self.start_seq(sep_efuse_otp_program_seq(_LC_STATE_BIT_BASE + 0))
        image.set_lc_state(LC_PROD)
        self.write_efuse_image(image)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        cells += await self._walk_demotes(image, dis_tag="dis0")

        # Close sep_fuse_dbg / smc_fuse_dbg while Case 2 and Case 3 stay open
        # (PROD + both demotes, sep_debug still 1). A golden that ignored
        # those bits would still pass every DIS=0 cell.
        fuse_sip, fuse_sys = cfg.dis_fuse_dbg
        await self._program_dis_bits(image, fuse_sip, fuse_sys)
        self.write_efuse_image(image)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(SepLccDemoteSeq(group=2))
        await self.start_seq(SepLccDemoteSeq(group=1))
        await self._check_cell(image, demote_1=1, demote_2=1, tag="PROD/dis_fuse_dbg/d11")
        cells += 1

        sip1, sys1 = cfg.dis_pinned
        # W1S the remaining pinned DIS bits (fuse-dbg bits already burned).
        await self._program_dis_bits(image, sip1, sys1)
        self.write_efuse_image(image)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        cells += await self._walk_demotes(image, dis_tag="dis_pinned")

        # TEST_DEV cannot be restored (OTP W1S). The zero-DIS TEST_DEV product
        # already ran; the fuse-dbg compose and pinned DIS product are at PROD.
        assert cells == cfg.n_cells(), f"walked {cells} demote cells, expected {cfg.n_cells()}"
        self.logger.info(
            "CHK-RAND-REP PASS: walked %d demote cells "
            "(TEST_DEV/PROD x dis0 + PROD fuse-dbg compose + PROD x pinned DIS)",
            cells,
        )

        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_lock(image, group=cfg.lock_group)
