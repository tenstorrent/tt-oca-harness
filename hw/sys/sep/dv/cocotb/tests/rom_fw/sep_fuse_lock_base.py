# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario for the four fuse-lock rows: a 2x2 of lifecycle x device control.

Each row checks that the ROM sets all six secret read-lock bits before the BL1 handoff.
The non-secure cells boot the unsigned image: a signed manifest's enforced bit outranks SBOOT_DIS.
"""

from __future__ import annotations

import os
from pathlib import Path

import cocotb
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE, sep_rom_ot_dma_boot_test
from sep_reg_meta import RegBlock, sym

EFUSE_DIR = Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations"
UNSIGNED_FLASH_IMAGE = sep_rom_ot_dma_boot_test.flash_image

LC_RAW_TEST_DEV = 0x0
LC_RAW_PROD = 0x1
LC_MARKERS = {
    LC_RAW_TEST_DEV: "LC=TEST_DEV",
    LC_RAW_PROD: "LC=PROD",
}
LC_TOKENS = {LC_RAW_TEST_DEV: 0, LC_RAW_PROD: 1}
# Forbidding every other decode catches a preload that failed to stage.
ALL_LC_MARKERS = ("LC=TEST_DEV", "LC=PROD", "LC=PROD_END", "LC=RMA_SIP", "LC=RMA_CHIPLET")


def lc_raw_echo(raw: int) -> str:
    return f"LC_STATE=0x{raw:08x}"


LC_STATE_INVALID = "LC_STATE_INVALID="

SBOOT_DIS_MARKERS = {0: "FUSE: SBOOT_DIS: 0", 1: "FUSE: SBOOT_DIS: 1"}

# Printed only when secure boot is engaged, in ROM order.
CRYPTO_MARKERS = ("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_VERIFY_OK")
SECURE_ONLY_MARKERS = CRYPTO_MARKERS + ("PUBK_SEL=", "PUBK_REVOKE=", "FUSE_VER=", "ENTROPY_OK")
SBOOT_OFF = "SBOOT_OFF"
MANIFEST_OK = "MANIFEST_OK"
PAYLOAD_OK = "PAYLOAD_OK"

FUSE_SECRETS_LOCKED = "FUSE_SECRETS_LOCKED"
FUSE_SECRETS_NOT_LOCKED = "FUSE_SECRETS_NOT_LOCKED"
BL1_COPIED = "BL1_COPIED"
BL1_JUMP = "BL1_JUMP="
# Printed by BL1 and by nothing in the ROM, so it is the transfer of control.
BL1_MARKER = "FUSE_CHK"
# BL1's own lock check covers only 0x0000A800, so the whole printed LOCKS word is required.
BL1_FUSE_OK = "FUSE_OK"
BL1_LOCK_RD_OK = "LOCK_RD_OK"
BL1_LOCK_FAILURES = (
    "FAIL:LOCKS",
    "FUSE_LOCK_VERIFY_FAIL",
    "LOCK_RD_FAIL",
    "FAIL:CLASS_KEY=",
    "BL0S_VERIFY_FAIL",
)

BOOT_FAILURE_TOKENS = (
    "MANIFEST_ERR=",
    "MANIFEST_ALL_FAILED",
    "MANIFEST_BOOT_FAIL=",
    LC_STATE_INVALID,
)

KEY_AND_UID_LOCK_BITS = {
    name: RegBlock("SEP_EFUSE_MAP").field_lsb("LOCKS", f"{name.lower()}_read_lock")
    for name in ("CLASS_KEY", "CHIPLET_UID", "SIP_UID", "SYS_UID")
}
EXTRA_LOCK_BITS = {
    name: RegBlock("SEP_EFUSE_MAP").field_lsb("LOCKS", f"{name.lower()}_read_lock")
    for name in ("RMA_SIP_TOKEN_DIGEST", "RMA_CHIPLET_TOKEN_DIGEST")
}
ALL_LOCK_BITS = {**KEY_AND_UID_LOCK_BITS, **EXTRA_LOCK_BITS}
FUSE_SECRET_READ_LOCK_MASK = 0
for _bit in ALL_LOCK_BITS.values():
    FUSE_SECRET_READ_LOCK_MASK |= 1 << _bit

# efuse_shadow_probe_o puts OTP word i at bits 32*i; LOCKS[31:0] is word 0.
_LOCKS_WORD = sym("SEP_EFUSE_MAP_LOCKS_REG_OFFSET") // 4


def bl1_locks_echo() -> str:
    return f"LOCKS=0x{FUSE_SECRET_READ_LOCK_MASK:08X}"


class sep_fuse_lock_base(sep_rom_ot_dma_boot_test):
    flash_image = SECURE_FLASH_IMAGE

    # Required even for TEST_DEV: without it the DUT senses the RTL array default.
    efuse_preload: Path | None = None
    expected_lc_raw: int = LC_RAW_TEST_DEV
    expected_sboot_dis: int = 0

    def __init_subclass__(cls, **kwargs) -> None:
        cls.flash_image = SECURE_FLASH_IMAGE if cls._secure_expected() else UNSIGNED_FLASH_IMAGE
        super().__init_subclass__(**kwargs)
        oc.assert_known(
            cls._required() + cls._forbidden() + cls._attempt_ordered() + cls._attempt_absent(),
            cls.__name__,
        )

    @classmethod
    def _secure_expected(cls) -> bool:
        # Only the secure cells' manifests carry the enforced bit, so SBOOT_DIS selects the arm.
        return cls.expected_sboot_dis == 0

    @classmethod
    def _required(cls) -> tuple[str, ...]:
        lc = LC_MARKERS[cls.expected_lc_raw]
        raw = lc_raw_echo(cls.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[cls.expected_sboot_dis]
        outcome = CRYPTO_MARKERS if cls._secure_expected() else (SBOOT_OFF,)
        return (
            sep_rom_ot_dma_boot_test.required_markers
            + (raw, lc, sboot)
            + outcome
            + (
                MANIFEST_OK,
                FUSE_SECRETS_LOCKED,
                BL1_COPIED,
                BL1_JUMP,
                BL1_MARKER,
                bl1_locks_echo(),
                BL1_FUSE_OK,
                BL1_LOCK_RD_OK,
            )
        )

    @classmethod
    def _forbidden(cls) -> tuple[str, ...]:
        lc = LC_MARKERS[cls.expected_lc_raw]
        other_lc = tuple(m for m in ALL_LC_MARKERS if m != lc)
        other_raw = tuple(
            lc_raw_echo(r) for r in (LC_RAW_TEST_DEV, LC_RAW_PROD) if r != cls.expected_lc_raw
        )
        other_sboot = (SBOOT_DIS_MARKERS[1 - cls.expected_sboot_dis],)
        outcome = (SBOOT_OFF,) if cls._secure_expected() else SECURE_ONLY_MARKERS
        return (
            sep_rom_ot_dma_boot_test.forbidden_markers
            + other_lc
            + other_raw
            + other_sboot
            + outcome
            + (FUSE_SECRETS_NOT_LOCKED,)
            + BL1_LOCK_FAILURES
            + BOOT_FAILURE_TOKENS
        )

    @classmethod
    def _attempt_ordered(cls) -> tuple[str, ...]:
        seq: tuple[str, ...] = ("OCA_BODY=", "MFST_VER=")
        seq += CRYPTO_MARKERS if cls._secure_expected() else ()
        seq += (MANIFEST_OK, PAYLOAD_OK)
        seq += () if cls._secure_expected() else (SBOOT_OFF,)
        return seq + (FUSE_SECRETS_LOCKED, BL1_COPIED, BL1_JUMP, BL1_MARKER)

    @classmethod
    def _attempt_absent(cls) -> tuple[str, ...]:
        return (SBOOT_OFF,) if cls._secure_expected() else SECURE_ONLY_MARKERS

    @property
    def required_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        return self._required()

    @property
    def forbidden_markers(self) -> tuple[str, ...]:  # type: ignore[override]
        return self._forbidden()

    def build_efuse_image(self):
        assert self.efuse_preload is not None and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}; set efuse_preload on the "
            f"subclass to a file under {EFUSE_DIR}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        self.check_efuse(image)
        return image

    def check_efuse(self, image) -> None:
        # select_efuse_image() silently falls back to a random image when the plusarg is absent.
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
        assert lc == self.expected_lc_raw, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x{self.expected_lc_raw:x}: the "
            f"testlist must pass +sep_efuse_preload={self.efuse_preload}"
        )
        assert sboot_dis == self.expected_sboot_dis, (
            f"SBOOT_DIS is {sboot_dis}, expected {self.expected_sboot_dis}: the "
            f"device-control axis of this cell did not stage"
        )
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
            "LOCKS_SPARE=0, so the validator's secure_boot_enabled must be %s",
            lc,
            LC_MARKERS[self.expected_lc_raw],
            sboot_dis,
            self._secure_expected(),
        )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        allowed = 1 << LC_TOKENS[self.expected_lc_raw]
        for slot in ("primary", "backup"):
            self.assert_manifest_preconditions(buf, slot)
            self.permit_live_lifecycle(buf, slot, allowed)
        return buf

    def permit_live_lifecycle(self, buf: bytearray, slot: str, allowed: int) -> None:
        bit = mm.SELECTOR_BIT_LIFECYCLE["chiplet"]
        if self._secure_expected():
            mm.set_lifecycle_constraint(buf, slot, allowed)
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
        else:
            # The unsigned image carries no signature to renew, only manifest_hash.
            mm.set_lifecycle_states(buf, slot, allowed)
            mm.set_selector_bit(buf, slot, bit, True)
        sel = mm.selector_bits(buf, slot)
        got = mm.lifecycle_states(buf, slot)
        assert sel == 1 << bit and got == allowed, (
            f"{slot} selector_bits 0x{sel:x} lifecycle_states 0x{got:x}, expected only "
            f"bit {bit} and 0x{allowed:x}: the constraint that names this cell's "
            f"lifecycle did not land"
        )
        assert mm.manifest_hash(buf, slot) == mm.signed_region_hash(buf, slot), (
            f"{slot} manifest_hash does not cover the planted constraint"
        )
        self.logger.info(
            "CHK-MANIFEST-LIFECYCLE: %s lifecycle_states=0x%x permits only %s, so a "
            "ROM that sensed any other state refuses the slot -- %s",
            slot,
            allowed,
            LC_MARKERS[self.expected_lc_raw],
            mm.describe(buf, slot),
        )

    def assert_manifest_preconditions(self, buf: bytearray, slot: str) -> None:
        mm.verify_layout(buf, slot)
        mm.verify_usage_constraints_layout(buf, slot)
        sel = mm.selector_bits(buf, slot)
        assert sel == 0, (
            f"{slot} selector_bits is 0x{sel:x} before the write, expected 0: another "
            f"constraint would share the slot and could refuse it"
        )
        secure_boot = mm.secure_boot_control(buf, slot)
        enforced = int(bool(secure_boot & mm.SECURE_BOOT_ENFORCED_BIT))
        assert enforced == int(self._secure_expected()), (
            f"{slot} secure_boot_control is 0x{secure_boot:02x}: the secure cells need "
            f"the enforced bit so TEST_DEV verifies, and the non-secure cells need it "
            f"clear because it outranks SBOOT_DIS (secure_boot.c)"
        )
        assert not pm.is_encrypted(buf, slot), (
            f"{slot} payload carries encrypted_payload = 1; an encrypted payload is "
            f"refused when secure boot is off, so the two non-secure cells could not boot"
        )
        self.logger.info(
            "CHK-MANIFEST-PRECONDITION: %s secure_boot_control=0x%02x, plaintext payload, "
            "no usage constraint -- %s",
            slot,
            secure_boot,
            mm.describe(buf, slot),
        )

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        self._check_decision_order(console)
        self._check_locks_register()

    def _check_decision_order(self, console: list[str]) -> None:
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: the unmodified primary must be accepted on its first read"
        )
        att = attempts[0]
        ordered = self._attempt_ordered()
        oc.assert_attempt(
            att, error=None, stage="accepted", ordered=ordered, absent=self._attempt_absent()
        )

        lc = LC_MARKERS[self.expected_lc_raw]
        raw = lc_raw_echo(self.expected_lc_raw)
        sboot = SBOOT_DIS_MARKERS[self.expected_sboot_dis]

        def first(marker: str) -> int:
            return next((i for i, line in enumerate(console) if oc.count([line], marker)), -1)

        i_raw, i_lc, i_sboot = first(raw), first(lc), first(sboot)
        assert 0 <= i_raw < i_lc < att.first and 0 <= i_sboot < att.first, (
            f"{raw}@{i_raw} -> {lc}@{i_lc} and {sboot}@{i_sboot} do not all precede "
            f"the slot attempt@{att.first}: the secure-boot verdict is not downstream "
            f"of the fuses this cell stages. Console: {console}"
        )
        self.logger.info(
            "CHK-DECISION-ORDER PASS: %s@%d -> %s@%d, %s@%d, then the primary@%d-%d "
            "accepted after %s",
            raw,
            i_raw,
            lc,
            i_lc,
            sboot,
            i_sboot,
            att.first,
            att.last,
            " -> ".join(ordered),
        )

    def _check_locks_register(self) -> None:
        probe = self.rd(cocotb.top.efuse_shadow_probe_o)
        locks_lo = (probe >> (32 * _LOCKS_WORD)) & 0xFFFF_FFFF
        missing = sorted(name for name, bit in ALL_LOCK_BITS.items() if not (locks_lo & (1 << bit)))
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
            "(key and UID locks plus %s)",
            locks_lo,
            ", ".join(sorted(ALL_LOCK_BITS)),
            ", ".join(sorted(EXTRA_LOCK_BITS)),
        )
