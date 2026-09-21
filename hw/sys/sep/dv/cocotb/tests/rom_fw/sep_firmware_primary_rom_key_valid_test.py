# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest names a VALID ROM key index and boots -> success.

The positive member of the primary-side ROM-key family. The primary's
``public_key_sel`` names ROM key slot 0 -- populated, unrevoked, and the slot the
image is signed against -- and the ROM must complete the boot from the PRIMARY
without ever reading the backup. There is no failover in this scenario at all,
which is what makes it the primary-side twin of
``sep_firmware_backup_rom_key_valid_test`` rather than a copy of it.

A POSITIVE TEST THAT PASSES BECAUSE KEY SELECTION NEVER RAN WOULD PROVE NOTHING,
so "it booted" is not accepted as the result here. Four independent channels are
required, and none of them is boot completion:

  * ``PUBK_SEL=0x00000000`` -- the selector the ROM read out of the primary
    manifest (``manifest_crypto.c``), pinned to EXACTLY ONE occurrence. Be
    honest about what that count is worth: with a single slot attempt and no retry
    it is structurally guaranteed by the ROM's control flow, so it is redundant
    insurance rather than the load-bearing check. The failure mode it names -- a
    second slot reaching key selection -- is already caught independently by the
    forbidden backup ``MANIFEST_SRC`` and by the device-side backup-span check
    below. The weight here sits on the ORDERING and on the device record;
  * ``PUBK_REVOKE=0x00000000`` -- the fuse word ``check_pubkey_revoked`` read
    (``manifest_crypto.c``), also exactly once, proving the revocation
    check ran and PERMITTED this slot rather than being skipped. This marker alone
    does NOT prove the ROM-key arm was taken: ``check_pubkey_revoked`` is called
    from the fuse-key arm too (``manifest_crypto.c``). What excludes that arm is
    the ``PUBK_SEL=0x00000000`` value -- ``{index:4, selection:3}``
    (``manifest.h``) makes 0x0000 uniquely "selection=PUBK_SEL_ROM_KEY,
    index=0" -- together with ``BAD_KEY_SEL`` and ``FUSE_KEY_EMPTY`` being
    forbidden;
  * ``RSA_VERIFY_START`` then ``SIG_VALID`` then ``CRYPTO_VALIDATE_OK``, in that
    order and after the selector echo -- the modulus reached the verifier and the
    signature really verified (``manifest_crypto.c``), which only
    happens once the index bound, the revocation check and the digest bind have all
    passed;
  * the DEVICE side: not one read inside the backup slot's span. The console says
    which address the ROM intended to read; the BFM's transaction record is the half
    the ROM cannot fake, and it is the only channel that can say "the PRIMARY is
    what booted". A silent failover also reaches ``MANIFEST_OK``.

MATCHED PAIR, AND IT IS BYTE-IDENTICAL BY CONSTRUCTION. This testcase and
``sep_firmware_primary_pubkey_rom_0_revoked_key_test`` build their flash image from
the SAME single call, ``select_primary_rom_slot(buf, 0)``, which is a no-op because
the shipped primary already selects slot 0
(``configs/secure_boot_test.yaml``). Both therefore run bytes identical to
the shipped ``bootrom/prod/build/secure_boot.bin``, and the ONLY difference between
them is one bit of ``CHIPLET_PUBK_REVOKE``. Fuse clear boots; bit 0 set refuses
BOTH manifests with ``KEY_REVOKED idx=0x00000000`` and never reaches
``RSA_VERIFY_START``. Nothing else about revocation needs arguing.

WHAT THIS SHARES WITH ``sep_rom_ot_secure_boot_test``, AND WHAT IT ADDS. The flash
image is the same golden ``secure_boot.bin``, so the overlap is stated rather than
hidden. Three things differ. That test runs under the default zero OTP, i.e.
lifecycle TEST_DEV, where secure boot is enforced only because the manifest asks
(``sep_rom_ot_secure_boot_test.py``); this one runs under a committed PROD
preload, where enforcement no longer DEPENDS on the manifest flag. It does not
attribute enforcement to the lifecycle, and must not claim to: the shipped primary
also sets ``FLAG_ARGS_BIT_SECURE_BOOT`` (visible as ``secure_boot_bit=1`` in the
stimulus log line), so under PROD both conditions of ``secure_boot_enabled()``
(``manifest_load.c``) hold at once and no observable separates them.
Attributing enforcement to the lifecycle alone needs the manifest flag CLEARED,
which is ``sep_firmware_enforced_secure_boot_flow_test``'s job, not this one's.
Second, ``sep_rom_ot_secure_boot_test`` asserts that the crypto chain reached
``SIG_VALID`` and nothing at all about key selection; this one adds the selector and
revocation echoes with exact counts and their ordering against the verifier. Third,
that test has no device-side assertion; this one requires the backup span to be
untouched. The narrowing is real and is disclosed: slot 0 is the only index this
testcase can exercise WITHOUT re-signing, because the shipped image is signed
with ``rsa_private_key.dev0.pem``
(``bootrom/prod/tools/tt-boot-manifest/tests/signing_keys/``, which also holds an
unusable ``ec_private_key.pem``) and slot 0 is the digest that key binds to.
A proceed case on another slot needs the manifest re-signed with that slot's key;
``sep_firmware_primary_rom_key_slot1_valid_test`` does exactly that for slot 1.

MARKER. There is no positive status code for the ROM-key path. This ROM
*defines* ``SEP_MSG_USING_ROM_KEY`` (``status_values.h``,
0x7f) and never emits it -- no ``report_status`` call for it exists anywhere under
``bootrom/prod/src`` -- so there is no UNIQUE architected code for the ROM-key path,
which is exactly what a positive key-selection testcase needs. The precise
statement, because "no architected evidence at all" would be too strong:
``report_status(STATUS_TYPE_INFO, SEP_MSG_VALIDATE_CHECK)``
(``manifest_crypto.c``) is emitted ONLY on the ROM-key arm, so an INFO 0x207
count could distinguish the two arms indirectly -- but 0x207 is also reported
unconditionally and again as DEBUG, so it is a count
argument rather than a marker, and this testcase does not use it. The console
echoes above are the evidence instead. Three further checkpoint codes are
unavailable for the same reason:
``SEP_MSG_START_MANIFEST_VALIDATION``, ``SEP_MSG_START_PAYLOAD_VALIDATION`` and
``SEP_MSG_PAYLOAD_VALIDATED`` also have zero emitters here.

Needs ``+sep_crypto_edn_force``: the primary is valid, so the full RSA-3072 modexp
runs on OTBN, which parks in UrndRefresh until EDN grants entropy. The shortcut
grants OTBN's EDN handshakes only; the RSA assertions are untouched, so
``SIG_VALID`` still means the signature really verified.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)
from rom_fw.sep_pubkey_rom_revoked_primary_base import select_primary_rom_slot

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# The slot the shipped image is signed against
# (configs/secure_boot_test.yaml), and the only entry in key_digests.c that a
# release build populates -- slots 1-5 carry test digests under TEST_BUILD only.
_VALID_SLOT = 0
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_VALID_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_RSA_START = "RSA_VERIFY_START"          # manifest_crypto.c
_SIG_VALID = "SIG_VALID"                 # manifest_crypto.c
_CRYPTO_OK = "CRYPTO_VALIDATE_OK"        # manifest_crypto.c
_BL1_COPIED = "BL1_COPIED"               # rom_handoff.c
_BL1_JUMP = "BL1_JUMP="                  # rom_handoff.c

# Must never appear. SBOOT_OFF would mean the crypto chain was skipped, so the key
# selection under test never ran; MANIFEST_ERR= / MANIFEST_ALL_FAILED and the
# backup source would mean this was a failover result rather than a primary boot.
_SBOOT_OFF = "SBOOT_OFF"
_ANY_MANIFEST_ERR = "MANIFEST_ERR="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"


@pyuvm.test()
class sep_firmware_primary_rom_key_valid_test(sep_rom_ot_dma_boot_test):
    """Primary names valid ROM slot 0 -> verifies -> boots, with no failover."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, _PUBK_SEL_ECHO, _REVOKE_ECHO, _RSA_START,
        _SIG_VALID, _CRYPTO_OK, _BL1_COPIED, _BL1_JUMP,
    )
    # Every rejecting arm of validate_signature, plus the failover evidence. This is
    # a positive test, so none of them may fire: seeing any one would mean the boot
    # completed in spite of a key-selection complaint, or from a slot this testcase
    # did not select.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF, _SBOOT_DIS_FUSE, _BACKUP_SRC, _ANY_MANIFEST_ERR, _ALL_FAILED,
        "BAD_SIG_TYPE=", "BAD_KEY_IDX", "BAD_KEY_SEL", "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH", "KEY_REVOKED", "VERSION_ROLLBACK",
        "RSA_VERIFY_FAIL", "CRYPTO_FAIL=",
    )

    # --- stimulus ----------------------------------------------------------
    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & 0x1
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced by the lifecycle, or the key selection under test is not "
            f"reached on the production path"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: slot {_VALID_SLOT} "
            f"must not be revoked, or this positive case becomes its own negative "
            f"twin"
        )
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364 then :369) and would "
            f"reject the primary before the key path is reached"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, BL1_VERSION=0x%x, "
            "PUBK_REVOKE=0x%x", lc, sboot_dis, bl1_ver, revoke,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        got, tbs_changed = select_primary_rom_slot(buf, _VALID_SLOT)
        assert not tbs_changed, (
            f"writing ROM slot {_VALID_SLOT} into the primary selector changed the "
            f"TBS, so the shipped image did not already select it; the signature is "
            f"now stale and this positive test could not boot for the reason it "
            f"claims"
        )
        # select_primary_rom_slot already ran verify_sealed + verify_public_key on
        # the untouched-TBS branch. Log what that established, because it is the
        # claim the matched pair rests on.
        self.logger.info(
            "CHK-STIMULUS-VALID-SLOT: primary public_key_sel=0x%04x (ROM key slot "
            "%d, populated and unrevoked); TBS unchanged, so the primary keeps its "
            "original dev0 signature and stays fully sealed", got, _VALID_SLOT,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info("CHK-SPI-TXNS:\n%s",
                         ev.summarize(flash.get_transactions(), self._image_len))

    # --- checks ------------------------------------------------------------
    def check_transport(self, console: list[str], flash) -> None:
        def index_of(marker: str) -> int:
            for i, line in enumerate(console):
                if marker in line:
                    return i
            return -1

        i_psrc = index_of(_PRIMARY_SRC)
        i_sel = index_of(_PUBK_SEL_ECHO)
        i_revoke = index_of(_REVOKE_ECHO)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_SIG_VALID)
        i_ok = index_of(_CRYPTO_OK)

        # CHK-KEYSEL-RAN: key selection is the feature under test, so it must have
        # executed on the PRIMARY and in the architected order -- slot read,
        # selector read, revocation bitmap consulted, verifier driven, signature
        # valid. Presence alone says nothing about order, and order is the substance.
        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"key selection did not run on the primary in the architected order: "
            f"primary@{i_psrc} -> {_PUBK_SEL_ECHO}@{i_sel} -> {_REVOKE_ECHO}"
            f"@{i_revoke} -> {_RSA_START}@{i_rsa} -> {_SIG_VALID}@{i_sig} -> "
            f"{_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # Exactly once each. The backup is never read in this scenario, so a second
        # occurrence of any of these would mean a slot this testcase did not select
        # also reached key selection or the verifier.
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO, _RSA_START, _SIG_VALID):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-KEYSEL-RAN: primary@%d -> %s@%d -> %s@%d -> %s@%d -> %s@%d -> "
            "%s@%d, each exactly once; the ROM-key path executed and permitted "
            "slot %d", i_psrc, _PUBK_SEL_ECHO, i_sel, _REVOKE_ECHO, i_revoke,
            _RSA_START, i_rsa, _SIG_VALID, i_sig, _CRYPTO_OK, i_ok, _VALID_SLOT,
        )

        # --- device evidence -------------------------------------------------
        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so nothing was fetched over "
            f"SPI and the boot did not come from this device. All {len(txns)} "
            f"transactions: {[hex(t['opcode']) for t in txns]}"
        )
        hit = ev.covering_read(rds, mm.PRIMARY_MANIFEST_OFFSET)
        assert hit is not None, (
            f"no SPI read covered the primary manifest address "
            f"0x{mm.PRIMARY_MANIFEST_OFFSET:x}: the boot did not come from the "
            f"primary address"
        )
        idx, txn = hit
        magic = ev.bytes_at(txn, mm.PRIMARY_MANIFEST_OFFSET, 4)
        assert magic == mm.MANIFEST_MAGIC, (
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, "
            f"expected {mm.MANIFEST_MAGIC!r}"
        )
        # CHK-NO-FAILOVER: the channel the ROM cannot fake. Without it, a run whose
        # primary was refused and whose backup booted would satisfy every marker
        # above except the forbidden backup source -- and the forbidden marker is a
        # console claim, while this is the device's own record.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so this is a failover result and not a primary key-selection "
            f"result"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this "
            "boot", idx, mm.PRIMARY_MANIFEST_OFFSET, magic, len(rds),
        )
