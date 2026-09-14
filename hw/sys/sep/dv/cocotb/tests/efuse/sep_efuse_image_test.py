# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse image + shadow-readout + W1S-persistence test (OSS).

Before sense-done, AXI-reads ``FEAT_CTRL`` and requires the fail-closed
zero vector (downstream shadow stays ``LC_STATE_INVALID``). After sense,
the same register must follow the image golden and the software-visible
shadow must match field-by-field. Then programs ten random fuse bits
through the frontdoor and resenses to prove the shadow tracks the
PERSISTENT OTP image plus those newly write-one-to-set bits.

Exercises the eFuse goals: sense + resense, specific-or-random init, field
constraints, the generated sep_efuse_map, shadow-vs-loaded-mem comparison, and
multi-bit W1S program persistence across a resense.
"""

from __future__ import annotations

import pyuvm
from env.sep_efuse_image import SepEfuseImage
from env.sep_lcc_golden import feat_ctrl_expected
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_efuse_direct_read_seq import sep_efuse_direct_read_seq
from seq_lib.sep_efuse_otp_program_seq import sep_efuse_otp_program_seq
from seq_lib.sep_efuse_shadow_check_seq import sep_efuse_shadow_check_seq
from seq_lib.sep_lcc_inbound_filter_gating_seq import SepLccFeatCtrlCheckSeq

_MAX_SENSE_CYCLES = 20_000

# CHIPLET_UID is a benign, shadow-visible data field (8 words = 256 bits) pinned to
# zero in the initial image, so every burn target is a known 0->1 bit. Global fuse
# bit index = word*32 + bit.
_UID_WORD0 = sym("SEP_EFUSE_MAP_CHIPLET_UID_REG_OFFSET") // 4
_UID_NBITS = 8 * 32  # 256 bits across the 8 CHIPLET_UID words
_NUM_BURN = 10


@pyuvm.test()
class sep_efuse_image_test(sep_base_test):
    """Sense a generated image, check shadow, burn 10 random bits, resense, re-check."""

    async def run_scenario(self) -> None:
        # One initial image with CHIPLET_UID pinned to 0 (the pre-sim efuse stage
        # reproduces this exact image for the model's t=0 load; see
        # cocotb/dv_sim_prestage.py). write_efuse_image records it as the golden for
        # the base post-sense backdoor compare.
        img = self.select_efuse_image(fixed={"CHIPLET_UID": 0})
        self.write_efuse_image(img)
        await self.release_no_cpu_reset()
        await self.check_pre_sense_fail_closed()
        await self.wait_fuse_sense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(img))
        opened = feat_ctrl_expected(
            img.lc_raw(), img.field_int("SIP_DIS"), img.field_int("SYS_DIS")
        )
        assert opened != 0, (
            "CHK-PRE-SENSE-OPEN FAIL: post-sense FEAT_CTRL golden is 0; "
            "the fail-closed contrast would be vacuous"
        )
        opened_seq = SepLccFeatCtrlCheckSeq(opened)
        await self.start_seq(opened_seq)
        self.logger.info(
            "CHK-PRE-SENSE-OPEN PASS: FEAT_CTRL=0x%016x after sense-done (guard opened)",
            opened_seq.feat_ctrl,
        )

        # Burn 10 distinct random known-zero fuse bits (real W1S through the
        # frontdoor), seeded by the run seed for reproducibility. The generic efuse
        # model's field_storage is persistent, so the resense must show the initial
        # image plus exactly these bits.
        rng = SepSeededRng(self.random_seed())
        burn_offsets = sorted(rng.sample(range(_UID_NBITS), _NUM_BURN))
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
        nc_word = _UID_WORD0 + 7  # last CHIPLET_UID word (offsets 224..255)
        nc_a, nc_b = 224, 225  # bits 0 and 1 of that word
        for off in (nc_a, nc_b):
            await self.start_seq(sep_efuse_otp_program_seq(_UID_WORD0 * 32 + off))
            golden.words[_UID_WORD0 + off // 32] |= 1 << (off % 32)
        rd = sep_efuse_direct_read_seq(nc_word)
        await self.start_seq(rd)
        got = rd.rdata & 0xFFFF_FFFF
        assert ((got >> (nc_a % 32)) & 1) and ((got >> (nc_b % 32)) & 1), (
            f"after programming bit {nc_b}, earlier bit {nc_a} is not "
            f"set (direct OTP word {nc_word} = 0x{got:08x}); bank must be OR, not overwrite"
        )

        # Advance the base post-sense golden to the post-program OTP state (the DUT
        # already holds the W1S bits from the programs above; this only updates the
        # expected image), resense, and verify the shadow tracks image + all bits.
        self.write_efuse_image(golden)
        await self.resense(max_cycles=_MAX_SENSE_CYCLES)
        await self.start_seq(sep_efuse_shadow_check_seq(golden))
        self.logger.info(
            "CHK-W1S-PERSIST PASS: resense shadow == initial image + %d W1S bits", _NUM_BURN
        )
