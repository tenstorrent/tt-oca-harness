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
``hw/ip/axi_filter/doc/index.adoc`` axi-traffic-filter-blocked).

``CHK-DBG-DISABLE`` reads each ``dbg_disable_<name>_o`` field by name: a field is
1 exactly when the access case of its path does not hold for the same FEAT_CTRL
(polarity: ``doc/integrator/src/smu-sep.adoc``, ``dbg_disable_o``, 1 = path
disabled; paths: ``hw/sys/dtp/doc/jtag.adoc``, Debug Disable; cases:
``lifecycle_controller.adoc``, Debug and Test Port Path Gating).

``CHK-FUSE-DFT-DIS`` is class-relative. A fuse DFT port is in its open class when
Case 3 AND SEP_FUSE_DBG (``sep_fuse_dft_disable_o``) or Case 2 AND SMC_FUSE_DBG
(``smc_fuse_dft_disable_o``) holds for the FEAT_CTRL of the cell, and in its
closed class otherwise (``lifecycle_controller.adoc``, DTP path feature gates).
No document states the level of either class, so the first cell of each class
is its control: every cell equals the control of its class, and the two
controls of a port differ. The walk reaches both classes (TEST_DEV with DIS 0
is open, PROD undemoted with DIS 0 is closed); a leaf that does not fails.
``OBS-DTP-PORT-LEVEL`` logs the open and closed level of each port once both
are known.

``sep_efuse_lcc_lc_state_stitch_test`` covers the end-to-end LC -> FEAT_CTRL
path. This test covers the LC x DEMOTE x DIS product.
Real fuse sense. DEMOTE is write-once-set; resense returns the CSRs to 0.
After the product walk, one seed-selected group is locked: a later demote
write is ignored until rst_ni. That blocked write also sets one ``rsvd`` marker
bit (write-one-to-set with no write enable, ``sep_lifecycle_ctrl.rdl``
DEMOTE_1/2), drawn with ``SepSeededRng``; ``CHK-DEMOTE-LOCK`` requires ``demote``
0, ``lock`` 1 and the marker bit in the readback, so the write is proven to reach
the register. ``OBS-LCC-WR-RESP`` logs its response, which no document states.

FCOV: each cell runs once, inside the graded window. The sampler holds the
legal ``sep_dtp_gating_ladder_cg`` ``x_path_case`` and ``x_prod_demote_case3``
cells of the cell's FEAT_CTRL read as pending, and samples them only on the
rise of the pass label ``dem_pass``, which the leaf writes after every check
of that cell passed. The window closes after the cell, or on its first FAIL,
which drops the pending cells. Resense, OTP programming and demote writes stay
outside it.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_efuse_image import LC_WORD_IDX, SepEfuseImage
from env.sep_efuse_test_lib import SepEfuseFd
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_demote_pass
from env.sep_lcc_golden import (
    DBG_DISABLE_FIELDS,
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
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_LIFECYCLE_CTRL
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

TEST = "sep_lcc_demote_feat_ctrl_matrix_test"
_MAX_SENSE_CYCLES = 20_000
_LC_STATE_BIT_BASE = LC_WORD_IDX * 32
# PROD (4'b0001) is TEST_DEV (4'b0000) plus bit 0 of the LC_STATE field
# (hw/sys/sep/doc/lifecycle_controller.adoc:366, :374).
_LC_PROD_BIT = _LC_STATE_BIT_BASE + LC_PROD.bit_length() - 1
# AMBA AXI RRESP OKAY (IHI 0022); no generated enum carries it.
RESP_OKAY = 0
DEMOTE_ADDR = {1: SEP_LIFECYCLE_CTRL.addr("DEMOTE_1"), 2: SEP_LIFECYCLE_CTRL.addr("DEMOTE_2")}
# rsvd bits a 32-bit DEMOTE write can carry as a marker.
_MARK_BITS = tuple(
    b for b in range(32) if (SEP_LIFECYCLE_CTRL.field_mask("DEMOTE_1", "rsvd") >> b) & 1
)
# Salt of the marker-bit stream; SepLccDemoteMatrixCfg draws nothing from it.
_MARK_SALT = 0x4D41_524B_4C4F_434B
_FUSE_DFT_PORTS = ("sep_fuse_dft_disable", "smc_fuse_dft_disable")


def _dbg_disable_word(bits: dict[str, int]) -> int:
    """Pack named dbg_disable bits into one word, DBG_DISABLE_FIELDS order MSB first."""
    n = len(DBG_DISABLE_FIELDS)
    word = 0
    for i, name in enumerate(DBG_DISABLE_FIELDS):
        if name in bits:
            word |= (bits[name] & 1) << (n - 1 - i)
    return word


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
        consistent claim rather than two independent guesses. A field is 1
        (path disabled, ``smu-sep.adoc`` ``dbg_disable_o``) exactly when the
        case of its path does not hold.
        """
        sampled = dbg_disable_sample(cocotb.top)
        want = dbg_disable_expected(feat_ctrl)
        got = {name: sampled[name] for name in want}
        got_w = _dbg_disable_word(got)
        want_w = _dbg_disable_word(want)
        width = len(DBG_DISABLE_FIELDS)
        wrong = [name for name in want if got[name] != want[name]]
        assert got_w == want_w, (
            f"CHK-DBG-DISABLE FAIL: {tag} dbg_disable=0b{got_w:0{width}b} "
            f"!= golden 0b{want_w:0{width}b} (wrong: {', '.join(wrong)}) for "
            f"FEAT_CTRL=0x{feat_ctrl:016x} "
            f"(sep_dbg={feat_ctrl & 1} chiplet_dbg={(feat_ctrl >> 1) & 1} "
            f"sip_dbg={(feat_ctrl >> SIP_DBG_BIT) & 1})"
        )
        if DBG_DISABLE_UNCLAIMED:
            self.logger.info(
                "CHK-DBG-DISABLE PASS: %s dbg_disable=0b%s == golden, %d of %d bits "
                "(unclaimed: %s)",
                tag,
                format(got_w, f"0{width}b"),
                len(want),
                width,
                ", ".join(DBG_DISABLE_UNCLAIMED),
            )
        else:
            self.logger.info(
                "CHK-DBG-DISABLE PASS: %s dbg_disable=0b%s == golden, all %d bits",
                tag,
                format(got_w, f"0{width}b"),
                width,
            )

    def _check_fuse_dft_disable(self, feat_ctrl: int, tag: str) -> None:
        """DFT-inserted fuse-path disables for this same FEAT_CTRL, class-relative.

        The ports have no CSR mirror. ``fuse_dft_disable_expected`` gives 0 exactly
        when Case 3 AND sep_fuse_dbg (Case 2 AND smc_fuse_dbg) holds; only that
        class is used, not its level. The first cell of each class is the control
        of that class; each cell equals the control of its class, and the open and
        closed controls of a port differ.
        """
        open_cls = {name: int(v == 0) for name, v in fuse_dft_disable_expected(feat_ctrl).items()}
        got = {
            name: self.rd_known(getattr(cocotb.top, f"{name}_o")) & 1 for name in _FUSE_DFT_PORTS
        }
        for name in _FUSE_DFT_PORTS:
            ctl = self._dft_ctl[name]
            cls = open_cls[name]
            if ctl[cls] is None:
                ctl[cls] = (got[name], tag)
            want, want_tag = ctl[cls]
            other = ctl[1 - cls]
            ok = got[name] == want and (other is None or other[0] != want)
            fields = (
                f"{tag} port={name} got={got[name]} class={'open' if cls else 'closed'} "
                f"control={want} control_cell={want_tag} "
                f"other_control={other[0] if other else 'na'} "
                f"(sep_fuse_dbg={(feat_ctrl >> SEP_FUSE_DBG_BIT) & 1} "
                f"smc_fuse_dbg={(feat_ctrl >> SMC_FUSE_DBG_BIT) & 1} "
                f"sep_dbg={feat_ctrl & 1} chiplet_dbg={(feat_ctrl >> 1) & 1} "
                f"sip_dbg={(feat_ctrl >> SIP_DBG_BIT) & 1})"
            )
            assert ok, f"CHK-FUSE-DFT-DIS FAIL: {fields} FEAT_CTRL=0x{feat_ctrl:016x}"
            self.logger.info("CHK-FUSE-DFT-DIS PASS: %s", fields)
        known = all(c[k] is not None for c in self._dft_ctl.values() for k in (0, 1))
        if known and not self._dft_level_logged:
            self._dft_level_logged = True
            sep, smc = (self._dft_ctl[n] for n in _FUSE_DFT_PORTS)
            self.logger.info(
                "OBS-DTP-PORT-LEVEL sep_open=%d sep_closed=%d smc_open=%d smc_closed=%d",
                sep[1][0],
                sep[0][0],
                smc[1][0],
                smc[0][0],
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
        # The owned bins hold the cells of the FEAT_CTRL read as pending; the
        # pass label releases them only after every check of this cell passed.
        # A FAIL raises before the label, and the finally clause closes the
        # window, which drops the pending cells.
        set_demote_pass(False, self.logger)
        open_graded_window(TEST, self.logger)
        try:
            ctl = await self._graded_cell(feat, tag)
            set_demote_pass(True, self.logger)
            await ClockCycles(cocotb.top.clk_i, 2)
            set_demote_pass(False, self.logger)
        finally:
            close_graded_window(self.logger)
        self.logger.info(
            "CHK-FEAT-CTRL PASS: %s FEAT_CTRL=0x%016x sep_debug=%d",
            tag,
            ctl.feat_ctrl,
            ctl.sep_debug,
        )
        self.logger.info(
            "CHK-LIVE-GATE PASS: %s ext %s (sep_debug=%d)",
            tag,
            "OKAY" if ctl.sep_debug else "DECERR",
            ctl.sep_debug,
        )

    async def _graded_cell(self, feat: int, tag: str) -> SepLccFeatCtrlCheckSeq:
        """FEAT_CTRL read, live filter probe, dbg_disable and fuse-path disables."""
        ctl = SepLccFeatCtrlCheckSeq(feat)
        mark = self.sb_mark()
        await self.start_seq(ctl)
        assert ctl.feat_ctrl == feat, (
            f"CHK-FEAT-CTRL FAIL: {tag} FEAT_CTRL=0x{ctl.feat_ctrl:016x} != golden 0x{feat:016x}"
        )
        self.assert_sb_judged(mark, f"CHK-FEAT-CTRL {tag}")
        assert ctl.sep_debug == (feat & 1), (
            f"CHK-FEAT-CTRL FAIL: {tag} sep_debug={ctl.sep_debug} != FEAT_CTRL[0] of 0x{feat:016x}"
        )
        probe = SepExtAxiProbeSeq(LC_STATE_SHADOW)
        await self.start_ext_seq(probe)
        want = RESP_OKAY if ctl.sep_debug else RESP_DECERR
        assert probe.resp_code == want, (
            f"CHK-LIVE-GATE FAIL: {tag} ext probe resp={probe.resp_code}, expected {want} "
            f"(sep_debug={ctl.sep_debug})"
        )
        self._check_dbg_disable(ctl.feat_ctrl, tag)
        self._check_fuse_dft_disable(ctl.feat_ctrl, tag)
        return ctl

    async def _set_demote(self, group: int, tag: str) -> None:
        """Write ``demote`` to DEMOTE_<group>; CTRL-DEMOTE-RB requires the readback to show it.

        A cell whose golden is the same with and without the demote (TEST_DEV
        at DIS 0) is then still shown to run with the demote set.
        """
        seq = SepLccDemoteSeq(group=group)
        await self.start_seq(seq)
        line = f"{tag} group={group} demote={int(bool(seq.demote))} lock={int(seq.lock)}"
        if not seq.demote or seq.lock:
            self.logger.error("CTRL-DEMOTE-RB FAIL (control not met): %s", line)
            raise AssertionError(f"CTRL-DEMOTE-RB control not met: {line}")
        self.logger.info("CTRL-DEMOTE-RB: %s", line)

    async def _require_demotes_clear(self, tag: str) -> None:
        """CTRL-DEMOTE-CLEAR: DEMOTE_1 and DEMOTE_2 read ``demote`` 0 and ``lock`` 0.

        An undemoted cell after a resense then runs with both demotes clear,
        also where its golden equals the demoted golden (TEST_DEV at DIS 0).
        """
        fd = SepEfuseFd(self)
        got = {g: await fd.rd(DEMOTE_ADDR[g]) for g in (1, 2)}
        line = f"{tag} " + " ".join(f"demote_{g}=0x{v:08x}" for g, v in got.items())
        if any(v & (DEMOTE_BIT | DEMOTE_LOCK_BIT) for v in got.values()):
            self.logger.error("CTRL-DEMOTE-CLEAR FAIL (control not met): %s", line)
            raise AssertionError(f"CTRL-DEMOTE-CLEAR control not met: {line}")
        self.logger.info("CTRL-DEMOTE-CLEAR: %s", line)

    async def _walk_demotes(self, image: SepEfuseImage, *, dis_tag: str) -> int:
        n = 0
        lc = lc_state_name(image.lc_raw())
        await self._require_demotes_clear(f"{lc}/{dis_tag}/d00")
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{lc}/{dis_tag}/d00")
        n += 1
        await self._set_demote(1, f"{lc}/{dis_tag}/d10")
        await self._check_cell(image, demote_1=1, demote_2=0, tag=f"{lc}/{dis_tag}/d10")
        n += 1
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._require_demotes_clear(f"{lc}/{dis_tag}/d00b")
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{lc}/{dis_tag}/d00b")
        await self._set_demote(2, f"{lc}/{dis_tag}/d01")
        await self._check_cell(image, demote_1=0, demote_2=1, tag=f"{lc}/{dis_tag}/d01")
        n += 1
        await self._set_demote(1, f"{lc}/{dis_tag}/d11")
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

        mark = SepSeededRng(self.random_seed() ^ _MARK_SALT).choice(_MARK_BITS)
        fd = SepEfuseFd(self)
        wdata = DEMOTE_BIT | (1 << mark)
        resp = await fd.wr_graded_by_readback(DEMOTE_ADDR[group], wdata)
        self.logger.info(
            "OBS-LCC-WR-RESP reg=DEMOTE_%d op=set_demote applied=0 wdata=0x%08x resp=%d",
            group,
            wdata,
            resp,
        )
        got = await fd.rd(DEMOTE_ADDR[group])
        demote, lock, marked = got & DEMOTE_BIT, int(bool(got & DEMOTE_LOCK_BIT)), (got >> mark) & 1
        lock_fields = (
            f"{tag} demote={int(bool(demote))} lock={lock} mark_bit={mark} mark={marked} "
            f"readback=0x{got:08x}"
        )
        assert demote == 0 and lock == 1 and marked == 1, (
            f"CHK-DEMOTE-LOCK FAIL: {lock_fields} (expected demote=0 lock=1 mark=1)"
        )
        await self._check_cell(image, demote_1=0, demote_2=0, tag=f"{tag}/held")
        self.logger.info(
            "CHK-DEMOTE-LOCK PASS: %s; feat_ctrl stayed undemoted",
            lock_fields,
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
        self._dft_ctl: dict[str, dict[int, tuple[int, str] | None]] = {
            name: {0: None, 1: None} for name in _FUSE_DFT_PORTS
        }
        self._dft_level_logged = False
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

        await self.start_seq(sep_efuse_otp_program_seq(_LC_PROD_BIT))
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
        await self._set_demote(2, "PROD/dis_fuse_dbg/d11")
        await self._set_demote(1, "PROD/dis_fuse_dbg/d11")
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

        missing = [
            f"{name}:{'open' if k else 'closed'}"
            for name, c in self._dft_ctl.items()
            for k in (0, 1)
            if c[k] is None
        ]
        assert not missing, (
            f"CHK-FUSE-DFT-DIS FAIL: the walk reached no cell of {', '.join(missing)}; "
            "a class-relative check needs both classes of each port"
        )
