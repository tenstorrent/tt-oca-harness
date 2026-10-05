# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""BL1 security version carrying every device flag -> accepted, the primary boots.

The accept boundary of anti-rollback. ``manifest_security_version`` is a 128-flag
bitmap, not a counter: a manifest is refused when it omits a flag the device holds,
``(device & ~manifest) != 0``. Both slots are written with exactly the device's flags
and re-sealed, so equality is the boundary under test and one flag fewer would reject.

The reject side is covered by ``sep_firmware_backup_invalid_security_version_test``
and ``sep_firmware_primary_invalid_security_version_test``; this is the accept side.

Where anti-rollback sits, and why both halves are asserted here. The check runs after
the root key is authorized and BEFORE the signature. The key-selection family relies
on reaching the key decision before this check can reject, and the reject siblings
rely on a rolled-back manifest never being handed to the verifier, so the ordering is
pinned here rather than inherited: ``PUBK_SEL=`` then ``FUSE_VER=`` then ``RSA_EXEC``.

The flags are spread across all four words the platform reads -- the low 16 bytes of
the ``BL1_VERSION`` bank -- each word distinct and non-empty. A read that truncated
to one word, repeated a word, or mis-indexed would change the verdict rather than
pass, which a preload concentrating its bits in word 0 could not show.

The device flags are read TWICE per slot: the library re-runs the check after the
signature as fault-injection hardening, so ``FUSE_VER=`` appears twice on the one
slot attempted and a count of one would mean the recheck did not happen.

An accept-only test cannot exclude a ROM whose comparison has been deleted while the
two echoes remain: printing both operands does not show the comparison ran, and
ordering is sequence rather than comparison. The two reject siblings are what
establish that the comparison exists.

Needs ``+esrc_noise_force``: the primary is valid, so a real RSA-3072 modexp runs.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw.sep_rom_ot_dma_boot_test import (
    SECURE_FLASH_IMAGE,
    sep_rom_ot_dma_boot_test,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_bl1ver36_spread.toml"
)

# The device flag word the preload burns, and the value this testcase writes into
# both manifests. Equal on purpose: under the superset rule
# ``(device & ~manifest) == 0``, equality IS the accept boundary -- one flag fewer
# and the slot is refused.
#
# The platform reads the LOW 16 BYTES of the 32-byte BL1_VERSION bank, so only
# these four words of the preload participate. They carry distinct flags, so a
# manifest omitting any one of them rejects -- which is what makes a truncated
# read observable through the verdict even though the echo shows 32 bits.
_DEVICE_FLAGS = 0x0000000F_00000007_00000003_00000001
_FUSE_VER_ECHO = f"FUSE_VER=0x{_DEVICE_FLAGS & 0xFFFF_FFFF:08x}"
_MFST_VER_ECHO = f"MFST_VER=0x{_DEVICE_FLAGS & 0xFFFF_FFFF:08x}"

_LC_PROD = "LC=PROD"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_PUBK_SEL = "PUBK_SEL="  #
_RSA_START = "RSA_EXEC"  #
_RSA_VERIFY_OK = "RSA_VERIFY_OK"

_CRYPTO_OK = "MANIFEST_OK"


@pyuvm.test()
class sep_firmware_bl1_ver_test(sep_rom_ot_dma_boot_test):
    """manifest security_version carries every BL1_VERSION flag -> accepted, primary boots."""

    flash_image = SECURE_FLASH_IMAGE
    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _PRIMARY_SRC,
        _FUSE_VER_ECHO,
        _MFST_VER_ECHO,
        _RSA_START,
        _RSA_VERIFY_OK,
        _CRYPTO_OK,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # VERSION_ROLLBACK is the load-bearing forbid: it is the arm this boundary must
    # NOT take. The rest exclude a boot that completed for some other reason -- a
    # failover, a skipped crypto chain, or a different rejecting arm firing first.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "MANIFEST_ERR=",
        "RSA_PKCS1_FAIL",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SLOT_RESERVED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
        "PUBK_HASH_TIMEOUT",
    )

    # --- stimulus ----------------------------------------------------------
    def build_efuse_image(self):
        assert _EFUSE_PRELOAD.is_file(), f"eFuse preload missing: {_EFUSE_PRELOAD}"
        image = self.select_efuse_image(default_preload=_EFUSE_PRELOAD)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): the rollback check is "
            f"reached through manifest validation, which only runs when secure "
            f"boot is enabled"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the whole crypto chain, including the "
            f"rollback check under test, would be skipped"
        )
        # The device flags themselves, and the spread that makes a truncated read
        # observable. Only the low 16 bytes are read by the platform, so those are
        # what must match; bits above them are burned but out of the field's reach.
        bl1_ver = image.field_int("BL1_VERSION")
        low16 = bl1_ver & ((1 << 128) - 1)
        words = [(low16 >> (32 * i)) & 0xFFFF_FFFF for i in range(4)]
        assert low16 == _DEVICE_FLAGS, (
            f"BL1_VERSION's low 16 bytes are 0x{low16:032x}, expected "
            f"0x{_DEVICE_FLAGS:032x}: the device flags must EQUAL what this testcase "
            f"writes into both manifests, or the run is no longer the accept boundary"
        )
        assert all(words), (
            f"BL1_VERSION's low 16 bytes have an empty word ({[hex(w) for w in words]}): "
            f"the claim this testcase rests on is that a manifest omitting any word's "
            f"flags is refused, and a word with no flags cannot be omitted"
        )
        assert len(set(words)) == len(words), (
            f"BL1_VERSION's low words are {[hex(w) for w in words]}, which repeat. "
            f"Distinct words are what make a mis-indexed read observable: reading one "
            f"word four times would reproduce an all-equal field exactly"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: a revoked key would "
            f"reject the manifest after the version check passed, and this positive "
            f"testcase would fail for a reason that has nothing to do with rollback"
        )
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, PUBK_REVOKE=0x%x, "
            "BL1_VERSION low 16 bytes = %s, four distinct non-empty words, so a read "
            "that truncated or mis-indexed them would change the verdict",
            lc,
            sboot_dis,
            revoke,
            [hex(w) for w in words],
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            # Anchor before mutating: the shipped slot is fully sealed, its modulus
            # is the dev0 key the ROM has in slot 0, and the local signer reproduces
            # the packer's own signature byte for byte. Only then is a re-seal a
            # sound operation rather than an assumption.
            pm.verify_sealed(buf, slot)
            mm.verify_public_key(buf, slot)
            pm.verify_signing_key(buf, slot)

            before = mm.security_version(buf, slot)
            assert before & _DEVICE_FLAGS != _DEVICE_FLAGS, (
                f"shipped {slot} security_version 0x{before:032x} already carries "
                f"every device flag, so the write would be a no-op and the boundary "
                f"would not be set by this testcase"
            )
            mm.set_security_version(buf, slot, _DEVICE_FLAGS)
            got = mm.security_version(buf, slot)
            assert got == _DEVICE_FLAGS, (
                f"{slot} security_version reads back 0x{got:032x} after the write, "
                f"expected 0x{_DEVICE_FLAGS:032x}"
            )
            pm.reseal(buf, slot)
            # The re-seal must be complete: a slot still carrying a stale payload
            # hash, manifest hash or signature would be rejected for THAT, and this
            # positive testcase would fail for a reason it did not choose.
            pm.verify_sealed(buf, slot)
            self.logger.info("CHK-STIMULUS-%s: %s", slot.upper(), mm.describe(buf, slot))
        self.logger.info(
            "CHK-STIMULUS-BOUNDARY: both slots security_version -> 0x%032x, re-signed "
            "and re-verified sealed; the device carries exactly those flags, so the "
            "manifest sits EXACTLY on the accept boundary of the superset rule",
            _DEVICE_FLAGS,
        )
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
        i_fuse = index_of(_FUSE_VER_ECHO)
        i_mfst = index_of(_MFST_VER_ECHO)
        i_sel = index_of(_PUBK_SEL)
        i_rsa = index_of(_RSA_START)
        i_sig = index_of(_RSA_VERIFY_OK)
        i_ok = index_of(_CRYPTO_OK)

        # CHK-ROLLBACK-BOUNDARY: the version check ran on the primary, read the
        # device flags this testcase burned, read the manifest value this testcase
        # wrote, and then let the boot proceed -- in that order. Presence alone
        # would be satisfied by a run that never compared the two.
        assert 0 <= i_psrc < i_mfst < i_fuse < i_rsa < i_sig < i_ok, (
            f"the rollback check did not run on the primary in the architected "
            f"order: primary@{i_psrc} -> {_MFST_VER_ECHO}@{i_mfst} -> "
            f"{_FUSE_VER_ECHO}@{i_fuse} -> {_RSA_START}@{i_rsa} -> "
            f"{_RSA_VERIFY_OK}@{i_sig} -> {_CRYPTO_OK}@{i_ok}. Console: {console}"
        )
        # CHK-ROLLBACK-AFTER-KEYSEL-BEFORE-SIGNATURE: anti-rollback sits BETWEEN
        # root-key authorization and the signature. Both halves are load-bearing and
        # neither is inherited: the key-selection testcases rely on reaching the key
        # decision before this check can reject, and the reject siblings rely on a
        # rolled-back manifest never being handed to the verifier.
        assert 0 <= i_sel < i_fuse < i_rsa, (
            f"the version comparison is not between key selection and the "
            f"verifier: {_PUBK_SEL}@{i_sel} -> {_FUSE_VER_ECHO}@{i_fuse} -> "
            f"{_RSA_START}@{i_rsa}. Console: {console}"
        )
        # One slot is attempted and there is no retry, so each marker's count is
        # fixed by how many times the ROM emits it per slot. The device flags are
        # read TWICE: the library re-runs the version check after the signature
        # (OCA_RECHECK_SECURITY_VERSION), which is fault-injection hardening, so
        # a count of one there would mean the recheck did not happen.
        for marker, want in (
            (_FUSE_VER_ECHO, 2),
            (_MFST_VER_ECHO, 1),
            (_RSA_START, 1),
            (_RSA_VERIFY_OK, 1),
        ):
            n = sum(1 for line in console if marker in line)
            assert n == want, (
                f"{marker} appeared {n} times, expected {want} (the primary's). Console: {console}"
            )
        self.logger.info(
            "CHK-ROLLBACK-BOUNDARY: primary@%d -> %s@%d -> %s@%d (equal, so accepted) "
            "-> %s@%d -> %s@%d -> %s@%d, each exactly once; and it followed %s@%d",
            i_psrc,
            _MFST_VER_ECHO,
            i_mfst,
            _FUSE_VER_ECHO,
            i_fuse,
            _RSA_START,
            i_rsa,
            _RSA_VERIFY_OK,
            i_sig,
            _CRYPTO_OK,
            i_ok,
            _PUBK_SEL,
            i_sel,
        )

        # --- device evidence -------------------------------------------------
        txns = flash.get_transactions()
        rds = ev.reads(txns)
        assert rds, (
            f"flash BFM served no read transactions, so nothing was fetched over SPI "
            f"and the boot did not come from this device. All {len(txns)} "
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
            f"device returned {magic!r} at 0x{mm.PRIMARY_MANIFEST_OFFSET:x}, expected "
            f"{mm.MANIFEST_MAGIC!r}"
        )
        # CHK-NO-FAILOVER: the channel the ROM cannot fake. Both slots carry the same
        # accepted version here, so a failover would still boot and still print the
        # same version echoes -- the device record is what pins the result to the
        # PRIMARY.
        backup_hits = ev.slot_read_indices(rds, "backup", self._image_len)
        assert not backup_hits, (
            f"device served {len(backup_hits)} read(s) inside the backup slot span "
            f"(read indices {backup_hits}): the primary alone did not serve this "
            f"boot, so the accepted version cannot be attributed to the primary"
        )
        self.logger.info(
            "CHK-NO-FAILOVER: read[%d] at 0x%06x returned magic %r, and no read "
            "touched the backup span across %d reads -- the PRIMARY served this boot",
            idx,
            mm.PRIMARY_MANIFEST_OFFSET,
            magic,
            len(rds),
        )
