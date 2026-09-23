# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the four fuse-lock rows: a 2x2 of lifecycle x device control.

Each row boots the plaintext signed image under one OTP preload and checks that the ROM
sets all six secret read-lock bits before the BL1 handoff, on both secure-boot arms.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test

EFUSE_DIR = (Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
             / "efuse_configurations")

LC_RAW_TEST_DEV = 0x0
LC_RAW_PROD = 0x1
LC_MARKERS = {
    LC_RAW_TEST_DEV: "LC=TEST_DEV",
    LC_RAW_PROD: "LC=PROD",
}
# Forbidding every other decode catches a preload that failed to stage.
ALL_LC_MARKERS = ("LC=TEST_DEV", "LC=PROD", "LC=PROD_END", "LC=RMA_SIP",
                  "LC=RMA_CHIPLET")


def lc_raw_echo(raw: int) -> str:
    return f"LC_STATE=0x{raw:08x}"


# SEP_MSG_LIFECYCLE_INVALID is a status code only and never reaches the console.
LC_STATE_INVALID = "LC_STATE_INVALID="

SBOOT_DIS_MARKERS = {0: "FUSE: SBOOT_DIS: 0", 1: "FUSE: SBOOT_DIS: 1"}

CRYPTO_MARKERS = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK")
SBOOT_OFF = "SBOOT_OFF"
SHA_DISABLED = "SHA256_CHECKS_DISABLED"
MANIFEST_HASH_OK = "MANIFEST_HASH_OK"
# verify_payload_hash() returns silently when payload_hashed_length is 0, so require it.
PLD_HASH_OK = "PLD_HASH_OK"
MANIFEST_OK = "MANIFEST_OK"

FUSE_SECRETS_LOCKED = "FUSE_SECRETS_LOCKED"
FUSE_SECRETS_NOT_LOCKED = "FUSE_SECRETS_NOT_LOCKED"
BL1_COPIED = "BL1_COPIED"
BL1_JUMP = "BL1_JUMP="
# Printed by BL1 and by nothing in the ROM, so it is the transfer of control.
BL1_MARKER = "FUSE_CHK"
# BL1's own lock check covers only 0x0000A800, so the whole printed LOCKS word is required.
BL1_FUSE_OK = "FUSE_OK"
BL1_LOCK_RD_OK = "LOCK_RD_OK"
BL1_LOCK_FAILURES = ("FAIL:LOCKS", "FUSE_LOCK_VERIFY_FAIL", "LOCK_RD_FAIL",
                     "FAIL:CLASS_KEY=", "BL0S_VERIFY_FAIL")

BOOT_FAILURE_TOKENS = (
    "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "MANIFEST_BOOT_FAIL=", "CRYPTO_FAIL=",
    "LC_USAGE_CONSTRAINT_FAIL", "LC_ALLOWED=", "LC_BIT=", "CHIPLET_ID_MISMATCH",
    "PACKAGE_ID_MISMATCH", "MANIFEST_HASH_MISMATCH", "PLD_HASH_FAIL=",
    LC_STATE_INVALID, "VERSION_ROLLBACK",
)

KEY_AND_UID_LOCK_BITS = {
    "CLASS_KEY": 15,
    "CHIPLET_UID": 23,
    "SIP_UID": 27,
    "SYS_UID": 31,
}
EXTRA_LOCK_BITS = {
    "RMA_SIP_TOKEN_DIGEST": 11,
    "RMA_CHIPLET_TOKEN_DIGEST": 13,
}
ALL_LOCK_BITS = {**KEY_AND_UID_LOCK_BITS, **EXTRA_LOCK_BITS}
FUSE_SECRET_READ_LOCK_MASK = 0
for _bit in ALL_LOCK_BITS.values():
    FUSE_SECRET_READ_LOCK_MASK |= 1 << _bit

# efuse_shadow_probe_o puts OTP word i at bits 32*i; LOCKS[31:0] is word 0.
_LOCKS_WORD = 0


def bl1_locks_echo() -> str:
    return f"LOCKS=0x{FUSE_SECRET_READ_LOCK_MASK:08X}"


class sep_fuse_lock_base(sep_rom_ot_dma_boot_test):

    flash_image = SECURE_FLASH_IMAGE

    # Required even for TEST_DEV: without it the DUT senses the RTL array default.
    efuse_preload: Path | None = None
    expected_lc_raw: int = LC_RAW_TEST_DEV
    expected_sboot_dis: int = 0

    @classmethod
    def _secure_expected(cls) -> bool:
        # SBOOT_DIS wins; otherwise the manifest's secure_boot flag applies in every lifecycle.
        return cls.expected_sboot_dis == 0

    @property
    def required_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        lc = LC_MARKERS[self.expected_lc_raw]
        raw = lc_raw_echo(self.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[self.expected_sboot_dis]
        outcome = CRYPTO_MARKERS if self._secure_expected() else (SBOOT_OFF,)
        return (
            sep_rom_ot_dma_boot_test.required_markers
            + (raw, lc, sboot, MANIFEST_HASH_OK, PLD_HASH_OK)
            + outcome
            + (MANIFEST_OK, FUSE_SECRETS_LOCKED, BL1_COPIED, BL1_JUMP, BL1_MARKER,
               bl1_locks_echo(), BL1_FUSE_OK, BL1_LOCK_RD_OK)
        )

    @property
    def forbidden_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        lc = LC_MARKERS[self.expected_lc_raw]
        other_lc = tuple(m for m in ALL_LC_MARKERS if m != lc)
        other_raw = tuple(
            lc_raw_echo(r) for r in (LC_RAW_TEST_DEV, LC_RAW_PROD)
            if r != self.expected_lc_raw
        )
        other_sboot = (SBOOT_DIS_MARKERS[1 - self.expected_sboot_dis],)
        outcome = (SBOOT_OFF,) if self._secure_expected() else CRYPTO_MARKERS
        return (
            sep_rom_ot_dma_boot_test.forbidden_markers
            + other_lc + other_raw + other_sboot + outcome
            + (FUSE_SECRETS_NOT_LOCKED, SHA_DISABLED) + BL1_LOCK_FAILURES
            + BOOT_FAILURE_TOKENS
        )

    def build_efuse_image(self):
        assert self.efuse_preload is not None and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}. Every cell names one, so "
            f"the t=0 staged image and this test's golden come from one file"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        self.check_efuse(image)
        return image

    def check_efuse(self, image) -> None:
        # select_efuse_image() silently falls back to a random image when the plusarg is absent.
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}: this "
            f"cell's whole identity is its lifecycle, and the testlist must pass "
            f"+sep_efuse_preload={self.efuse_preload}"
        )
        assert sboot_dis == self.expected_sboot_dis, (
            f"SBOOT_DIS is {sboot_dis}, expected {self.expected_sboot_dis}: the "
            f"device-control axis of this cell did not stage"
        )
        # A preload that arrived locked would pass the post-boot read without the ROM's work.
        for field in ("LOCKS", "LOCKS_SPARE"):
            got = image.field_int(field)
            assert got == 0, (
                f"{field} is 0x{got:x} in the staged image, expected 0: the "
                f"post-boot lock check would pass on a preload that arrived "
                f"locked, proving nothing about lock_fuse_secrets()"
            )
        # Version floors or revocations would refuse the image for an unrelated reason.
        fd.assert_clean_key_fuses(image)
        self.logger.info(
            "CHK-FUSE-LOCK-STIMULUS: LC raw=0x%x (%s), SBOOT_DIS=%d, LOCKS=0 and "
            "LOCKS_SPARE=0, so secure_boot_enabled() must return %s",
            lc, LC_MARKERS[self.expected_lc_raw], sboot_dis,
            self._secure_expected(),
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        self.assert_manifest_preconditions(buf)
        return buf

    def assert_manifest_preconditions(self, buf: bytearray) -> None:
        for slot in ("primary", "backup"):
            mm.verify_layout(buf, slot)
            mm.verify_usage_constraints_layout(buf, slot)
            sel = mm.selector_bits(buf, slot)
            assert sel & (1 << mm.SELECTOR_BIT_LIFE_CYCLE_STATES), (
                f"{slot} selector_bits is 0x{sel:x} and leaves bit "
                f"{mm.SELECTOR_BIT_LIFE_CYCLE_STATES} clear, so the ROM skips the "
                f"lifecycle usage constraint entirely and forbidding "
                f"LC_USAGE_CONSTRAINT_FAIL says nothing"
            )
            allowed = mm.life_cycle_states(buf, slot)
            live_bit = 0 if self.expected_lc_raw == LC_RAW_TEST_DEV else 1
            assert allowed & (1 << live_bit), (
                f"{slot} life_cycle_states is 0x{allowed:x} and does not permit "
                f"bit {live_bit} (the lifecycle this cell senses), so the slot "
                f"would be refused by the usage constraint instead of booting"
            )
            flags = mm.get_flag_args(buf, slot)
            assert (flags >> mm.FLAG_ARGS_BIT_SECURE_BOOT) & 1, (
                f"{slot} flag_args is 0x{flags:08x} and asks for NON-secure boot; "
                f"the two secure cells would then be indistinguishable from the "
                f"non-secure ones in TEST_DEV"
            )
            assert not (flags >> mm.FLAG_ARGS_BIT_SKIP_SHA256) & 1, (
                f"{slot} flag_args is 0x{flags:08x} and sets SKIP_SHA256; "
                f"MANIFEST_HASH_OK would be absent in TEST_DEV and "
                f"{SHA_DISABLED} is forbidden"
            )
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; manifest_load.c "
                f"refuses an encrypted payload outright when secure boot is off, "
                f"so the two non-secure cells could not boot"
            )
            self.logger.info(
                "CHK-MANIFEST-PRECONDITION: %s selector_bits=0x%x "
                "life_cycle_states=0x%x flag_args=0x%08x, plaintext payload, "
                "unmutated -- %s",
                slot, sel, allowed, flags, mm.describe(buf, slot),
            )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        self._check_decision_order(console)
        self._check_locks_register()

    def _check_decision_order(self, console: list[str]) -> None:
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        lc = LC_MARKERS[self.expected_lc_raw]
        raw = lc_raw_echo(self.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[self.expected_sboot_dis]
        i_raw = index_of(raw)
        i_lc = index_of(lc)
        i_sboot = index_of(sboot)
        decision = CRYPTO_MARKERS[0] if self._secure_expected() else SBOOT_OFF
        i_decision = index_of(decision)
        i_ok = index_of(MANIFEST_OK)
        i_lock = index_of(FUSE_SECRETS_LOCKED)
        i_jump = index_of(BL1_JUMP)
        i_bl1 = index_of(BL1_MARKER)

        # The fuse echoes must precede the verdict, or a ROM that decided first would pass.
        assert 0 <= i_raw < i_lc, (
            f"{raw}@{i_raw} does not precede {lc}@{i_lc}: lifecycle.c echoes the "
            f"raw sensed nibble before it decodes it, so this pair being out of "
            f"order means one of them did not come from that decode. "
            f"Console: {console}"
        )
        assert 0 <= i_lc < i_decision and 0 <= i_sboot < i_decision, (
            f"{lc}@{i_lc} and {sboot}@{i_sboot} do not both precede "
            f"{decision}@{i_decision}: the secure-boot verdict is not downstream "
            f"of the fuses this cell stages. Console: {console}"
        )
        # The lock must fall between manifest accept and the handoff to close the read window.
        assert 0 <= i_ok < i_lock < i_jump < i_bl1, (
            f"lock sequence is out of order: {MANIFEST_OK}@{i_ok} -> "
            f"{FUSE_SECRETS_LOCKED}@{i_lock} -> {BL1_JUMP}@{i_jump} -> "
            f"{BL1_MARKER}@{i_bl1}. Console: {console}"
        )
        self.logger.info(
            "CHK-DECISION-ORDER: %s@%d -> %s@%d, and %s@%d -> %s@%d; %s@%d -> "
            "%s@%d -> %s@%d -> %s@%d",
            raw, i_raw, lc, i_lc, sboot, i_sboot, decision, i_decision,
            MANIFEST_OK, i_ok, FUSE_SECRETS_LOCKED, i_lock, BL1_JUMP, i_jump,
            BL1_MARKER, i_bl1,
        )

    def _check_locks_register(self) -> None:
        probe = self.rd(cocotb.top.efuse_shadow_probe_o)
        locks_lo = (probe >> (32 * _LOCKS_WORD)) & 0xFFFF_FFFF
        missing = sorted(name for name, bit in ALL_LOCK_BITS.items()
                         if not (locks_lo & (1 << bit)))
        assert not missing, (
            f"LOCKS[31:0] read back 0x{locks_lo:08x} from the shadow register "
            f"file; the read-lock bits for {', '.join(missing)} are CLEAR, so "
            f"lock_fuse_secrets() did not close the window on those secrets "
            f"(expected mask 0x{FUSE_SECRET_READ_LOCK_MASK:08x})"
        )
        assert locks_lo & FUSE_SECRET_READ_LOCK_MASK == FUSE_SECRET_READ_LOCK_MASK, (
            f"LOCKS[31:0] = 0x{locks_lo:08x} does not cover the ROM's whole "
            f"FUSE_SECRET_READ_LOCK_MASK 0x{FUSE_SECRET_READ_LOCK_MASK:08x}"
        )
        self.logger.info(
            "CHK-FUSE-LOCK-REGISTER: LOCKS[31:0]=0x%08x, read locks set for %s "
            "(the reference's four plus %s)",
            locks_lo, ", ".join(sorted(ALL_LOCK_BITS)),
            ", ".join(sorted(EXTRA_LOCK_BITS)),
        )
