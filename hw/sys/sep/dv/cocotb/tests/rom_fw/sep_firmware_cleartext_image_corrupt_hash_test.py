# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A cleartext image's TOC digest is zeroed; the primary's payload hash fails and the backup boots.

``verify_payload_hash`` (``bootrom/prod/src/manifest_crypto.c``) recomputes
SHA-256 over ``payload[:payload_hashed_length]`` and compares it with the
``payload_hash`` the manifest carries, announcing ``PLD_HASH_MISMATCH`` and
returning ``MANIFEST_ERR_PAYLOAD_HASH_MISMATCH`` (0x00030017). It is called from
inside ``manifest_crypto_validate``, so the slot error surfaces as
``CRYPTO_FAIL=0x00030017`` and the ROM falls over to the backup. No row in this
repository required that code or that token before this one -- both appear only in
forbidden lists.

WHY THAT IS THE REFERENCE'S RULE, which decides everything else here. The
reference zeroes ``primary.payload_images[].hash`` with an SPI-preload editor that
recomputes NOTHING -- not ``payload_hash``, not ``manifest_hash``, not the
signature. Its packer sets ``payload_hashed_length`` to the whole TOC region for a
cleartext payload, so the digest field it overwrites lies INSIDE the bytes
``payload_hash`` covers, and its ROM checks ``validate_payload_hash`` before
``validate_payload``. The verdict it expects, ``WARNING: PAYLOAD_HASH_INVALID``, is
therefore the manifest-level payload-hash rule; its per-image arm returns a
different status (``SEP_MSG_TOC_HASH_INVALID``) which its own firmware suite covers
from a separately re-sealed config.

This design has the same rule at the same point in the chain and the same geometry
-- ``payload_hashed_length`` is 248, the whole TOC region, and entry 0's digest
sits at payload offset 88 -- so the reference's stimulus ports across unchanged and
needs no re-seal. ``sep_payload_mutate.corrupt_toc_entry_hash`` is therefore called
with ``reseal=False``: re-sealing would move the rejection downstream to
``IMAGE_HASH_MISMATCH`` / 0x00030019, which is a DIFFERENT rule the reference does
not assert here, and that arm has no row in this repository either.

THE SLOT IS OTHERWISE GENUINELY SIGNED, which is what makes the verdict
attributable. ``payload_hash`` sits inside the TBS, so leaving it untouched keeps
``manifest_hash`` and the RSA signature valid: the mutator proves offline that the
signature still verifies against the dev0 modulus, that the manifest hash still
covers its TBS, and that the ROM's own payload-hash comparison now FAILS. On the
run, the primary must therefore print ``MANIFEST_HASH_OK``, ``RSA_VERIFY_START``
and ``SIG_VALID`` of its own before being refused.

THE PAYLOAD IS CLEARTEXT, which the row is named for. The reference builds its
image with ``primary.manifest.encrypted_payload = 0``; ``secure_boot.bin`` already
carries that in both slots, so no packer change is needed and the flag is asserted
on the loaded artefact. ``DECRYPT_START`` is forbidden, which is positive evidence
the plaintext arm ran: the ROM calls ``decrypt_payload`` only for a slot whose flag
is set. It also matters for the RULE, not just the name -- for an ENCRYPTED payload
``payload_hashed_length`` is the whole ciphertext rather than the TOC region, so
this stimulus would be a different geometry.

THE BODY IS NOT TOUCHED, and that is proved rather than claimed: the mutator
compares the image body before and after the write and refuses a change. A modified
body would break ``payload_hash`` too, and the two hash rules could no longer be
told apart.

ONE IMAGE, NOT TWO. The reference zeroes ``payload_images[0].hash`` AND
``payload_images[1].hash`` because its packed payload carries two images. The
payload shipped here declares exactly ONE, so entry 0 is the whole list. A
multi-image variant has no row here.

WHAT SEPARATES THIS ROW FROM EACH NEIGHBOUR:

  * from ``PLD_HASH_TIMEOUT`` -- the other outcome of the same comparison, which
    means the SHA engine never answered. It returns a DIFFERENT code
    (``MANIFEST_ERR_HASH_MISMATCH``, 0x0003000B); both the token and that code are
    forbidden;
  * from the per-image digest arm -- ``IMAGE_HASH_MISMATCH``, ``IMAGE_HASH_TIMEOUT``
    and 0x00030019 are forbidden, so a re-sealed variant of this very mutation
    could not satisfy this row;
  * from the ``payload_hashed_length`` family, which corrupts the LENGTH rather than
    the hashed bytes -- ``PAYLOAD_HASHED_LEN_BAD=`` is forbidden and
    ``MANIFEST_HASH_OK`` is required twice, so the primary reached the crypto chain;
  * from the secure-boot-off path -- ``PLD_HASH_FAIL=`` is the token the
    ``SBOOT_OFF`` branch prints for this same failure, and it is forbidden, so the
    refusal provably came through ``manifest_crypto_validate``;
  * from a run that never planted anything -- the device must be shown to have
    served thirty-two ZERO bytes at the exact flash address of entry 0's digest, and
    ``PLD_HASH_OK`` must appear exactly ONCE, the backup's.

Needs ``+sep_crypto_edn_force``: both slots run a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_no_payload_images_base as npi
from rom_fw import sep_toc_defect as td
from rom_fw import sep_toc_entry_defect as ted
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

# manifest.h
ERR_PAYLOAD_HASH_MISMATCH = 0x0003_0017
ERR_HASH_MISMATCH = 0x0003_000B          # what PLD_HASH_TIMEOUT returns
ERR_IMAGE_HASH_MISMATCH = ted.ERR_IMAGE_HASH_MISMATCH
ERR_IMAGE_ALIGN = 0x0003_001B

# The shipped payload declares one image, so the digest is entry 0's.
_ENTRY_INDEX = 0
_ZERO_DIGEST = b"\x00" * 32
# manifest_crypto.c
_TOKEN = "PLD_HASH_MISMATCH"
_HASH_OK = "PLD_HASH_OK"

# Every payload token except this row's own. PLD_HASH_TIMEOUT, PLD_HASH_FAIL= and
# both IMAGE_HASH_* tokens deliberately STAY forbidden -- they are the neighbouring
# outcomes of the same comparison and of the arm a re-seal would move this onto.
_OTHER_TOKENS = tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != _TOKEN)
assert len(_OTHER_TOKENS) == len(td.OTHER_PAYLOAD_TOKENS) - 1, (
    f"{_TOKEN!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this arm's "
    f"token would be neither required by this row nor forbidden by its neighbours; "
    f"the swap-test defence has silently lapsed"
)
for _must_stay in ("PLD_HASH_FAIL=", "IMAGE_HASH_MISMATCH", "IMAGE_HASH_TIMEOUT"):
    assert _must_stay in _OTHER_TOKENS, (
        f"{_must_stay!r} must stay forbidden: it is either the same failure reported "
        f"through the secure-boot-off branch, or the per-entry arm a re-sealed "
        f"variant of this mutation would land on"
    )
# PLD_HASH_TIMEOUT is not in that shared list, so name it here.
_TIMEOUT_TOKEN = "PLD_HASH_TIMEOUT"

# The other ways a hash comparison can end a slot attempt. Forbidding each code is
# the swap test for a row whose own token names only the comparison, not the length.
_NEIGHBOUR_ERRORS = [
    f"MANIFEST_ERR=0x{c:08x}" for c in (
        ERR_HASH_MISMATCH, ERR_IMAGE_HASH_MISMATCH, ted.ERR_BAD_IMAGE_TYPE,
        ted.ERR_IMAGE_OOB, ted.ERR_IMAGE_OVERLAP, ERR_IMAGE_ALIGN,
    )
]


@pyuvm.test()
class sep_firmware_cleartext_image_corrupt_hash_test(sep_primary_fail_backup_boot_base):
    """Primary's cleartext image digest is zeroed -> payload hash fails -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_HASH_MISMATCH
    # The arm prints its own token AND the rejection is returned by
    # manifest_crypto_validate, so the base's defect-marker path fits exactly: it
    # requires the token and CRYPTO_FAIL=0x00030017, and places the token inside the
    # primary's own attempt.
    primary_defect_marker = _TOKEN
    # The payload hash is checked AFTER the signature (manifest_load.c fixes the
    # order: security version -> signature -> payload hash -> decrypt -> TOC), so
    # the primary drives the verifier and reaches a verified signature of its own.
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    extra_required = ("MANIFEST_HASH_OK", _HASH_OK, "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + _NEIGHBOUR_ERRORS
        + [td.DECRYPT_START, _TIMEOUT_TOKEN, "MANIFEST_ALL_FAILED"]
        + list(_OTHER_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this row is the "
                f"CLEARTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about. For an encrypted payload "
                f"payload_hashed_length spans the whole ciphertext rather than the "
                f"TOC region, so the geometry this row depends on would differ"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        entries = pm.toc_entries(buf, "primary")
        assert len(entries) == 1, (
            f"primary TOC declares {len(entries)} images; this row plants the digest "
            f"of the single shipped image, and entry {_ENTRY_INDEX} is only the whole "
            f"list when the payload carries one"
        )
        hashed = pm.payload_hashed_length(buf, "primary")
        field = pm.toc_entry_at(_ENTRY_INDEX) + pm.E_HASH
        assert field + 32 <= hashed, (
            f"payload_hashed_length is {hashed}, which does not reach entry "
            f"{_ENTRY_INDEX}'s digest at {field}..{field + 32}: payload_hash would "
            f"not cover the edit and verify_payload_hash would ACCEPT the slot"
        )
        # reseal=False is the whole point of this row. See the module docstring: the
        # reference re-signs nothing, so payload_hash keeps describing the SHIPPED
        # bytes and verify_payload_hash is what refuses the slot. A re-seal would
        # move the verdict to the per-entry arm, which is a different rule.
        self._served = pm.corrupt_toc_entry_hash(
            buf, "primary", _ENTRY_INDEX, value=_ZERO_DIGEST, reseal=False)
        assert self._served == _ZERO_DIGEST, (
            f"the stored digest is {self._served.hex()} but a cleartext payload "
            f"stores what was written; the mutation reached the wrong bytes"
        )
        self.logger.info(
            "CHK-STIMULUS-IMAGE-HASH: primary TOC entry %d digest -> %s, with the "
            "image BODY left exactly as shipped and NOTHING re-sealed. "
            "payload_hashed_length is %d, so payload_hash covers the field at "
            "payload offset %d, and the mutator proved offline that the ROM's own "
            "sha256(payload[:%d]) no longer matches the stored payload_hash while "
            "manifest_hash and the RSA signature still verify. The field sits at "
            "flash 0x%06x and the device must serve %s there",
            _ENTRY_INDEX, self._served.hex(), hashed, field, hashed,
            mm.slot_base("primary") + self._payload_offset + field,
            self._served.hex(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_HASH_MISMATCH:08x}"
        crypto_fail = f"CRYPTO_FAIL=0x{ERR_PAYLOAD_HASH_MISMATCH:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-PAYLOAD-HASH-ATTRIBUTION: the arm's token, the crypto-chain wrapper
        # that carried it out of manifest_crypto_validate, and the slot error are
        # ALL the primary's, in that order, inside the primary's attempt. Exactly one
        # occurrence each: a second would mean the backup carried the same defect,
        # which is a terminal scenario rather than this one.
        i_token = fd.assert_slot_attributed(console, _TOKEN, after=i_psrc,
                                            before=i_bsrc)
        i_cf = fd.assert_slot_attributed(console, crypto_fail, after=i_token,
                                         before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_cf,
                                          before=i_bsrc)

        # CHK-HASH-FAILED-NOT-PASSED: the payload-hash comparison ran twice and
        # succeeded ONCE -- the backup's. One occurrence, after the backup read, is
        # what says the primary's comparison reached a verdict and that verdict was
        # "mismatch"; a second would mean the planted digest was accepted.
        n_ok = fd.count(console, _HASH_OK)
        assert n_ok == 1, (
            f"{_HASH_OK} appeared {n_ok} times, expected exactly 1 (the backup's): "
            f"the primary's payload hash must FAIL, and only the backup's may pass. "
            f"Console: {console}"
        )
        i_ok = fd.first_index(console, _HASH_OK)
        assert i_bsrc < i_ok, (
            f"{_HASH_OK}@{i_ok} precedes the backup read@{i_bsrc}, so it is the "
            f"primary's: its payload hash passed and this row proves nothing. "
            f"Console: {console}"
        )

        # CHK-SLOT-WAS-OTHERWISE-INTACT: the primary passed its own manifest
        # integrity check, which runs before the crypto chain. Two occurrences, one
        # per slot, says the slot was refused for its payload hash and not for a
        # stale manifest hash -- which is the claim the untouched TBS rests on.
        n_hash = fd.count(console, "MANIFEST_HASH_OK")
        assert n_hash == 2, (
            f"MANIFEST_HASH_OK appeared {n_hash} times, expected exactly 2 (one per "
            f"slot): payload_hash sits inside the TBS and was left untouched, so the "
            f"primary's manifest hash must still verify. Console: {console}"
        )
        i_mh = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_psrc < i_mh < i_token, (
            f"the primary's MANIFEST_HASH_OK@{i_mh} does not sit between its "
            f"read@{i_psrc} and {_TOKEN}@{i_token}. Console: {console}"
        )
        self.logger.info(
            "CHK-PAYLOAD-HASH-RULE: primary@%d -> MANIFEST_HASH_OK@%d -> %s@%d -> "
            "%s@%d -> %s@%d, inside its own attempt and after its signature "
            "verified; %s appeared once and only after the backup read@%d, so the "
            "primary's comparison reached a verdict of mismatch and the untouched "
            "backup booted",
            i_psrc, i_mh, _TOKEN, i_token, crypto_fail, i_cf, slot_err, i_err,
            _HASH_OK, i_bsrc,
        )

        # CHK-STIMULUS-SERVED: the device really returned thirty-two zero bytes at
        # entry 0's digest address. The console cannot separate this row from a run
        # that corrupted a different byte inside the hashed region; this can.
        fd.assert_served_field(
            self.logger, flash, "primary",
            self._payload_offset + pm.toc_entry_at(_ENTRY_INDEX) + pm.E_HASH,
            self._served, f"primary TOC entry {_ENTRY_INDEX} image digest",
        )
