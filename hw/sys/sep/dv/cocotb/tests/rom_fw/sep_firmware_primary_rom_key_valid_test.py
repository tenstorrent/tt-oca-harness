# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary names valid ROM key slot 0 and boots without failover.

Boot completion alone does not prove that key selection ran, so four channels are required:

  * ``PUBK_SEL=0x00000000`` exactly once: the ROM read slot 0 from the primary manifest.
  * ``PUBK_REVOKE=0x00000000`` exactly once: the revocation check ran and permitted the
    slot. ``PUBK_SEL_AMBIGUOUS`` and ``PUBK_OTP_EMPTY`` are forbidden, so the ROM-key arm
    was taken.
  * ``RSA_EXEC``, ``RSA_VERIFY_OK`` and ``MANIFEST_OK`` in that order after the selector echo.
  * No SPI read inside the backup slot span: a silent failover also reaches ``MANIFEST_OK``.

The flash image is byte-identical to that of
``sep_firmware_primary_pubkey_rom_0_revoked_key_test``: ``select_primary_rom_slot(buf, 0)``
is a no-op on the shipped primary, so the only difference is bit 0 of ``CHIPLET_PUBK_REVOKE``.

Compared with ``sep_rom_ot_secure_boot_test``, this run uses a PROD preload and adds the
key-selection echoes and the backup-span check. The shipped primary also sets the manifest's
secure-boot enforced bit, so enforcement is not attributed to the lifecycle;
``sep_firmware_enforced_secure_boot_flow_test`` covers that.

The ROM emits no architected status code for the ROM-key path, so the console echoes carry
the key-selection evidence.

Needs ``+esrc_noise_force``: the primary runs a full RSA-3072 modexp.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw.sep_pubkey_rom_revoked_primary_base import select_primary_rom_slot
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

# The slot the shipped image is signed against, so the positive case needs no graft
# (configs/oca_secure_boot_test.yaml). All six slots carry a digest.
_VALID_SLOT = 0
_PUBK_SEL_ECHO = f"PUBK_SEL=0x{_VALID_SLOT:08x}"
_REVOKE_ECHO = "PUBK_REVOKE=0x00000000"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_RSA_START = "RSA_EXEC"  #
_RSA_VERIFY_OK = "RSA_VERIFY_OK"
_BL1_COPIED = "BL1_COPIED"  # rom_handoff.c
_BL1_JUMP = "BL1_JUMP="  # rom_handoff.c

# Must never appear. SBOOT_OFF would mean the crypto chain was skipped, so the key
# selection under test never ran; MANIFEST_ERR= / MANIFEST_ALL_FAILED and the
# backup source would mean this was a failover result rather than a primary boot.
_SBOOT_OFF = "SBOOT_OFF"
_ANY_MANIFEST_ERR = "MANIFEST_ERR="
_ALL_FAILED = "MANIFEST_ALL_FAILED"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"

_CRYPTO_OK = "MANIFEST_OK"


@pyuvm.test()
class sep_firmware_primary_rom_key_valid_test(sep_rom_ot_dma_boot_test):
    """Primary names valid ROM slot 0 -> verifies -> boots, with no failover."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _PRIMARY_SRC,
        _PUBK_SEL_ECHO,
        _REVOKE_ECHO,
        _RSA_START,
        _RSA_VERIFY_OK,
        _CRYPTO_OK,
        _BL1_COPIED,
        _BL1_JUMP,
    )
    # Every rejecting arm of the signature path, plus the failover evidence. This is
    # a positive test, so none of them may fire: seeing any one would mean the boot
    # completed in spite of a key-selection complaint, or from a slot this testcase
    # did not select.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _SBOOT_OFF,
        _SBOOT_DIS_FUSE,
        _BACKUP_SRC,
        _ANY_MANIFEST_ERR,
        _ALL_FAILED,
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "RSA_PKCS1_FAIL",
        "MANIFEST_ERR=",
    )

    # --- stimulus ----------------------------------------------------------
    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
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
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: anti-rollback cannot reject a "
            f"manifest when the device carries no security flags, and that is what "
            f"keeps this verdict attributable to the check under test"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, BL1_VERSION=0x%x, "
            "PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            bl1_ver,
            revoke,
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        got, tbs_changed = select_primary_rom_slot(buf, _VALID_SLOT)
        assert not tbs_changed, (
            f"writing ROM slot {_VALID_SLOT} into the primary selector changed the "
            f"signed region, so the shipped image did not already select it; the signature is "
            f"now stale and this positive test could not boot for the reason it "
            f"claims"
        )
        # select_primary_rom_slot already ran verify_sealed and verify_public_key.
        self.logger.info(
            "CHK-STIMULUS-VALID-SLOT: primary public_key_sel=0x%04x (ROM key slot "
            "%d, populated and unrevoked); signed region unchanged, so the primary keeps its "
            "original dev0 signature and stays fully sealed",
            got,
            _VALID_SLOT,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

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
        i_sig = index_of(_RSA_VERIFY_OK)
        i_ok = index_of(_CRYPTO_OK)

        # CHK-KEYSEL-RAN: key selection is the feature under test, so it must have
        # executed on the PRIMARY and in the architected order -- slot read,
        # selector read, revocation bitmap consulted, verifier driven, signature
        # valid. Presence alone says nothing about order, and order is the substance.
        assert 0 <= i_psrc < i_sel < i_revoke < i_rsa < i_sig < i_ok, (
            f"key selection did not run on the primary in the architected order: "
            f"primary@{i_psrc} -> {_PUBK_SEL_ECHO}@{i_sel} -> {_REVOKE_ECHO}"
            f"@{i_revoke} -> {_RSA_START}@{i_rsa} -> {_RSA_VERIFY_OK}@{i_sig} -> "
            f"{_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # Exactly once each. The backup is never read in this scenario, so a second
        # occurrence of any of these would mean a slot this testcase did not select
        # also reached key selection or the verifier.
        for marker in (_PUBK_SEL_ECHO, _REVOKE_ECHO, _RSA_START, _RSA_VERIFY_OK):
            n = sum(1 for line in console if marker in line)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the primary's). "
                f"Console: {console}"
            )
        self.logger.info(
            "CHK-KEYSEL-RAN: primary@%d -> %s@%d -> %s@%d -> %s@%d -> %s@%d -> "
            "%s@%d, each exactly once; the ROM-key path executed and permitted "
            "slot %d",
            i_psrc,
            _PUBK_SEL_ECHO,
            i_sel,
            _REVOKE_ECHO,
            i_revoke,
            _RSA_START,
            i_rsa,
            _RSA_VERIFY_OK,
            i_sig,
            _CRYPTO_OK,
            i_ok,
            _VALID_SLOT,
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
            "boot",
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
            len(rds),
        )
