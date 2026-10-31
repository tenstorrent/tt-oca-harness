# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The sensed eFuse shadow follows the image, and W1S programs persist across a resense.

Before sense-done, AXI-reads ``FEAT_CTRL`` and requires the fail-closed
zero vector (downstream shadow stays ``LcStateInvalid``). After sense,
the same register must follow the image golden and the software-visible
shadow must match field-by-field. Then programs ten random fuse bits
through the frontdoor and resenses to prove the shadow tracks the
PERSISTENT OTP image plus those newly write-one-to-set bits.

Exercises the eFuse goals: sense + resense, specific-or-random init, field
constraints, the generated sep_efuse_map, shadow-vs-loaded-mem comparison, and
multi-bit W1S program persistence across a resense.

Checkers:
  CHK-PRE-SENSE-FAIL-CLOSED  FEAT_CTRL reads the whole 64-bit zero (INVALID
                      profile) while sep_fuse_sense_done_o is 0 (base test).
  CHK-SENSE-SHADOW    after sense-done every shadow word matches the image
                      golden. The sep_fuse_sense_done field of
                      SEP_FUSE_SENSE_STATUS (OBS-SENSE-STATUS-DONE) and the
                      reserved bits (OBS-SENSE-STATUS-RSVD) have no stated value
                      and are logged.
  CHK-PRE-SENSE-OPEN  FEAT_CTRL reads the fail-closed zero before sense-done and
                      the image golden after it.
  CHK-OTP-DIRECT      the burned bits read 1 in a direct OTP read before the resense.
  CHK-W1S-NOCLOBBER   programming a second bit in a word keeps the first one set
                      (the bank ORs, it does not overwrite): both bits read 0
                      before the programs (no random burn draws them), and the
                      direct OTP read of that word equals the golden word
                      exactly before and after.
  CHK-W1S-PERSIST     after the resense the shadow equals the image plus every
                      W1S bit; the done field and the reserved bits are logged
                      OBS.

Bench record: INFO-EFUSE-OTP-PLAIN, after the first sense, the AXI read of every
shadow word of CLASS_KEY, CHIPLET_UID, SIP_UID and SYS_UID with its response,
beside the image word the bench loaded. No text states whether these fields are
stored obfuscated. The line shows only that the sense and read path returns the
stored word unchanged; it cannot show how the stored value relates to the secret
or UID it carries, or any transform firmware applies after the read.

FCOV graded window (owner sep_efuse_image_test): it opens after the reset
release and before the pre-sense FEAT_CTRL read, and closes after
CHK-SENSE-SHADOW, or on the first FAIL inside it. It owns
``sep_lc_feat_ctrl_profile_cg.cp_presense_feat`` (FEAT_CTRL read before
sense-done) and ``sep_boot_milestone_cg.cp_sense_surface[status1_port1]``
(SEP_FUSE_SENSE_STATUS read after sense-done). The sampler holds each read
outcome as pending and samples it only when the pass label rises, which the
leaf raises once the owning check has passed: a run whose check FAILs leaves
both bins empty.
"""

from __future__ import annotations

from collections.abc import Awaitable

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_axi_agent import SepAxiItem, SepAxiOp
from env.sep_efuse_feat_ctrl import feat_ctrl_nonvacuous_fixed
from env.sep_efuse_image import SEP_FUSE_SENSE_STATUS, WORD_BITS, SepEfuseImage
from env.sep_fabric_common import RESP_NAME
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_efimg_pass
from env.sep_lcc_golden import feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

TEST = "sep_efuse_image_test"
_MAX_SENSE_CYCLES = 20_000

# SEP_FUSE_SENSE_STATUS after sense-done: the done field reads 1
# (regs/gen/adoc/blocks/sep_cpu_ctrl.adoc:322). Bits 63:1 are reserved with no
# stated reset (:321), so they are logged, not graded.
_SENSE_DONE_MASK = SEP_CPU_CTRL.field_mask("SEP_FUSE_SENSE_STATUS", "sep_fuse_sense_done")

# CHIPLET_UID is a benign, shadow-visible data field pinned to zero in the initial
# image, so every burn target is a known 0->1 bit. Its word offset and width come
# from the generated map. Global fuse bit index = word*32 + bit.
_UID_FIELD = SepEfuseImage.field("CHIPLET_UID")
_UID_WORD0 = sym("SEP_EFUSE_MAP_CHIPLET_UID_REG_OFFSET") // 4
assert _UID_FIELD.word == _UID_WORD0, "CHIPLET_UID offset disagrees with the generated map"
_UID_NBITS = _UID_FIELD.n_words * WORD_BITS
_NUM_BURN = 10
_PLAIN_FIELDS = ("CLASS_KEY", "CHIPLET_UID", "SIP_UID", "SYS_UID")


class _ShadowStatusSeq(sep_efuse_shadow_check_seq):
    """The shadow check sequence; the status read is graded by the leaf.

    The scoreboard judges every shadow word. The status read carries no
    scoreboard expectation, because its reserved bits have no golden; the leaf
    grades the ``sep_fuse_sense_done`` field from the kept word.
    """

    def __init__(self, image: SepEfuseImage) -> None:
        super().__init__(image, name="shadow_status_seq")
        self.status: int | None = None
        self.n_reads = 0

    async def _read_expect(self, addr: int, expected: int, label: str) -> None:
        item = SepAxiItem(f"rd_{label}_0x{addr:08x}")
        item.op = SepAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = None if addr == SEP_FUSE_SENSE_STATUS else expected
        await self.start_item(item)
        await self.finish_item(item)
        self.n_reads += 1
        if addr == SEP_FUSE_SENSE_STATUS:
            self.status = item.rdata & 0xFFFF_FFFF


@pyuvm.test()
class sep_efuse_image_test(sep_base_test):
    """The shadow matches the image, and burned W1S bits persist in OTP and across a resense."""

    async def _grade(self, step: Awaitable[None]) -> None:
        """Run one graded step; on a FAIL close the FCOV window, then re-raise."""
        try:
            await step
        except Exception:
            close_graded_window(self.logger)
            raise

    async def _pass_label(self) -> None:
        """Raise the FCOV pass label for two clocks, so the sampler sees one rise."""
        set_efimg_pass(True, self.logger)
        await ClockCycles(cocotb.top.clk_i, 2)
        set_efimg_pass(False, self.logger)

    async def _check_sense_shadow(self, img: SepEfuseImage, chk: str = "CHK-SENSE-SHADOW") -> None:
        """``chk``: every shadow word after sense-done.

        No specification line states the value of the ``sep_fuse_sense_done`` field
        of ``SEP_FUSE_SENSE_STATUS`` after sense-done, so it is logged
        (OBS-SENSE-STATUS-DONE). The reserved bits have no stated reset, so they are
        logged (OBS-SENSE-STATUS-RSVD). Neither is graded.
        """
        seq = _ShadowStatusSeq(img)
        mark = self.sb_mark()
        await self.start_seq(seq)
        assert seq.status is not None, f"{chk} FAIL: no SEP_FUSE_SENSE_STATUS read"
        done_field = seq.status & _SENSE_DONE_MASK
        self.logger.info(
            "OBS-SENSE-STATUS-DONE: %s sep_fuse_sense_done field=0x%x SEP_FUSE_SENSE_STATUS=0x%08x",
            chk,
            done_field,
            seq.status,
        )
        self.assert_sb_judged(mark, chk)
        done = int(self.rd(cocotb.top.sep_fuse_sense_done_o))
        judged = self.env.scoreboard.value_checks - mark[1]
        shadow_reads = seq.n_reads - 1
        assert judged == shadow_reads, (
            f"{chk} FAIL: scoreboard judged {judged} of {shadow_reads} shadow reads"
        )
        assert done == 1, f"{chk} FAIL: sep_fuse_sense_done_o={done} after the status read"
        self.logger.info(
            "%s PASS: sep_fuse_sense_done_o=%d shadow judged=%d/%d reads",
            chk,
            done,
            judged,
            shadow_reads,
        )
        self.logger.info(
            "OBS-SENSE-STATUS-RSVD: %s SEP_FUSE_SENSE_STATUS reserved bits 31:1 = 0x%08x",
            chk,
            seq.status & ~_SENSE_DONE_MASK & 0xFFFF_FFFF,
        )

    async def _log_otp_plain(self, img: SepEfuseImage) -> None:
        """INFO-EFUSE-OTP-PLAIN: each shadow word of the key and UID fields beside its image word."""
        for name in _PLAIN_FIELDS:
            fld = SepEfuseImage.field(name)
            shadow, resp = [], []
            for i in range(fld.n_words):
                addr = fld.shadow_addr + 4 * i
                seq = SepAxiAccessSeq(f"plain_rd_0x{addr:08x}", op=SepAxiOp.READ, addr=addr, size=2)
                await self.start_seq(seq)
                shadow.append(seq.rdata & 0xFFFF_FFFF)
                resp.append(RESP_NAME.get(seq.resp_code, seq.resp_code))
            image = img.words[fld.word : fld.word + fld.n_words]
            self.logger.info(
                "INFO-EFUSE-OTP-PLAIN: field=%s words=%d equal=%d resp=[%s] shadow=[%s] image=[%s]",
                name,
                fld.n_words,
                int(shadow == image),
                ",".join(str(r) for r in resp),
                ",".join(f"0x{w:08x}" for w in shadow),
                ",".join(f"0x{w:08x}" for w in image),
            )

    async def run_scenario(self) -> None:
        # One initial image with CHIPLET_UID pinned to 0 (the pre-sim efuse stage
        # reproduces this exact image for the model's t=0 load; see
        # cocotb/dv_sim_prestage.py). write_efuse_image records it as the golden for
        # the base post-sense backdoor compare.
        # CHIPLET_UID is pinned because the test programs one of its bits after
        # the first sense. The disable vectors stay random: the helper returns
        # them untouched unless the draw would make post-sense FEAT_CTRL zero,
        # which would make the fail-closed contrast below vacuous.
        # MIRROR: dv_sim_prestage.py EFUSE_IMAGE_REGISTRY["sep_efuse_image_test"].
        img = self.select_efuse_image(
            fixed=feat_ctrl_nonvacuous_fixed(self.random_seed(), base={"CHIPLET_UID": 0})
        )
        self.write_efuse_image(img)
        await self.release_no_cpu_reset()
        set_efimg_pass(False, self.logger)
        open_graded_window(TEST, self.logger)
        await self._grade(self.check_pre_sense_fail_closed())
        await self._pass_label()
        await self._grade(self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES))
        await self._grade(self._check_sense_shadow(img))
        await self._pass_label()
        close_graded_window(self.logger)
        await self._log_otp_plain(img)
        opened = feat_ctrl_expected(
            img.lc_raw(), img.field_int("SIP_DIS"), img.field_int("SYS_DIS")
        )
        assert opened != 0, (
            "CHK-PRE-SENSE-OPEN FAIL: post-sense FEAT_CTRL golden is 0; "
            "the fail-closed contrast would be vacuous"
        )
        opened_seq = SepLccFeatCtrlCheckSeq(opened)
        mark = self.sb_mark()
        await self.start_seq(opened_seq)
        self.assert_sb_judged(mark, "CHK-PRE-SENSE-OPEN")
        assert opened_seq.feat_ctrl == opened, (
            f"CHK-PRE-SENSE-OPEN FAIL: FEAT_CTRL=0x{opened_seq.feat_ctrl:016x} after "
            f"sense-done, expected 0x{opened:016x}"
        )
        self.logger.info(
            "CHK-PRE-SENSE-OPEN PASS: FEAT_CTRL=0x%016x after sense-done (guard opened)",
            opened_seq.feat_ctrl,
        )

        # Burn 10 distinct random known-zero fuse bits (real W1S through the
        # frontdoor), seeded by the run seed for reproducibility. The generic efuse
        # model's field_storage is persistent, so the resense must show the initial
        # image plus exactly these bits. The draw excludes bits 0 and 1 of the last
        # CHIPLET_UID word: CHK-W1S-NOCLOBBER programs them later and requires
        # both to read 0 before its first program.
        nc_word = _UID_WORD0 + _UID_FIELD.n_words - 1  # last CHIPLET_UID word
        nc_a = (_UID_FIELD.n_words - 1) * WORD_BITS  # bit 0 of that word
        nc_b = nc_a + 1  # bit 1 of that word
        rng = SepSeededRng(self.random_seed())
        burn_pool = [off for off in range(_UID_NBITS) if off not in (nc_a, nc_b)]
        burn_offsets = sorted(rng.sample(burn_pool, _NUM_BURN))
        golden = SepEfuseImage()
        golden.words = list(img.words)
        for off in burn_offsets:
            await self.start_seq(sep_efuse_otp_program_seq(_UID_WORD0 * 32 + off))
            golden.words[_UID_WORD0 + off // 32] |= 1 << (off % 32)
        assert golden.words != img.words, "W1S golden identical to initial -- vacuous"
        self.logger.info("[efuse] burned %d random CHIPLET_UID bits: %s", _NUM_BURN, burn_offsets)

        # CHK-OTP-DIRECT (pre-resense): read the burned words straight from OTP via the
        # EFUSE_READ_CTRL read interface, which BYPASSES the sense->shadow path. The
        # burned bits must read 1 there NOW -- before any resense -- proving the programs
        # landed in persistent OTP, not just in a re-sensed shadow. Non-vacuous: the read
        # word must equal the golden word exactly, so every un-burned bit reads 0 too.
        for off in (burn_offsets[0], burn_offsets[-1]):
            word = _UID_WORD0 + off // 32
            rd = sep_efuse_direct_read_seq(word)
            await self.start_seq(rd)
            got = rd.rdata & 0xFFFF_FFFF
            assert (got >> (off % 32)) & 1, (
                f"CHK-OTP-DIRECT: burned bit off={off} reads 0 in the direct OTP read of "
                f"word {word} (got 0x{got:08x})"
            )
            assert got == golden.words[word], (
                f"CHK-OTP-DIRECT: direct OTP word {word} = 0x{got:08x} != expected "
                f"0x{golden.words[word]:08x}"
            )
        self.logger.info("CHK-OTP-DIRECT PASS: burned bits read 1 directly from OTP pre-resense")

        # CHK-W1S-NOCLOBBER (negative): the bank storage is write-one-to-set (OR-only:
        # next = value | wr_data), so programming a bit must never clear an already-set
        # bit in the same word. Program two bits in one UID word in sequence and confirm
        # a direct OTP read shows BOTH set -- catches a bank that overwrites (=) instead
        # of OR (|=), which would clear the first bit when the second is programmed.
        # The whole word must equal the golden word, so a program that sets any
        # other bit fails too. A direct read before the first program is the
        # positive probe: both bits read 0 and the word equals the golden, so
        # each set bit afterwards is the work of its own program.
        pre = sep_efuse_direct_read_seq(nc_word)
        await self.start_seq(pre)
        pre_got = pre.rdata & 0xFFFF_FFFF
        nc_mask = (1 << (nc_a % 32)) | (1 << (nc_b % 32))
        assert pre_got == golden.words[nc_word] and not pre_got & nc_mask, (
            f"CHK-W1S-NOCLOBBER FAIL: before the programs direct OTP word {nc_word} = "
            f"0x{pre_got:08x}, expected 0x{golden.words[nc_word]:08x} with bits "
            f"{nc_a % 32} and {nc_b % 32} at 0"
        )
        for off in (nc_a, nc_b):
            await self.start_seq(sep_efuse_otp_program_seq(_UID_WORD0 * 32 + off))
            golden.words[_UID_WORD0 + off // 32] |= 1 << (off % 32)
        rd = sep_efuse_direct_read_seq(nc_word)
        await self.start_seq(rd)
        got = rd.rdata & 0xFFFF_FFFF
        assert ((got >> (nc_a % 32)) & 1) and ((got >> (nc_b % 32)) & 1), (
            f"CHK-W1S-NOCLOBBER FAIL: after programming bit {nc_b}, earlier bit {nc_a} is not "
            f"set (direct OTP word {nc_word} = 0x{got:08x}); bank must be OR, not overwrite"
        )
        assert got == golden.words[nc_word], (
            f"CHK-W1S-NOCLOBBER FAIL: direct OTP word {nc_word} = 0x{got:08x} != expected "
            f"0x{golden.words[nc_word]:08x}"
        )
        self.logger.info(
            "CHK-W1S-NOCLOBBER PASS: direct OTP word %d = 0x%08x before, 0x%08x after "
            "(expected 0x%08x), bits %d and %d set",
            nc_word,
            pre_got,
            got,
            golden.words[nc_word],
            nc_a % 32,
            nc_b % 32,
        )

        # Advance the base post-sense golden to the post-program OTP state (the DUT
        # already holds the W1S bits from the programs above; this only updates the
        # expected image), resense, and verify the shadow tracks image + all bits.
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self._check_sense_shadow(golden, chk="CHK-W1S-PERSIST")
        self.logger.info(
            "CHK-W1S-PERSIST PASS: resense shadow == initial image + %d W1S bits", _NUM_BURN
        )
