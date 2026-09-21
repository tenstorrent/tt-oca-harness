# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The primary's payload is declared inside its own manifest header; the backup boots.

``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) refuses
``payload_offset < manifest_length``, announces ``PAYLOAD_OVERLAPS_MANIFEST`` and
returns ``MANIFEST_ERR_PAYLOAD_OVERLAP`` (0x00030011). The offset is relative to
the manifest start, so a value below the header length would have the staged
payload written over the fields the ROM is still reading. No row in this repository
required that token before this one -- it appears only in forbidden lists.

THE REFUSAL IS UPSTREAM OF EVERYTHING, which is what this row is really about and
what it asserts rather than assumes. ``validate_manifest_header`` runs at the top
of ``try_manifest_slot``, ahead of ``manifest_check_integrity``, ahead of the
payload-source bounds gate and ahead of the staging transfer. So on a passing run:

  * ``MANIFEST_HASH_OK`` appears EXACTLY ONCE, the backup's -- the primary was
    refused before its own integrity check;
  * ``USING_SEP_SRAM`` and ``PAYLOAD_DST=`` appear EXACTLY ONCE each, the backup's
    -- the primary never chose a staging destination;
  * no SPI read BEGINS at the primary's declared payload source -- the primary's
    payload was never fetched;
  * ``primary_expected_rsa_starts`` and ``primary_expected_sig_valids`` are both 0,
    so the primary must not reach the verifier at all.

Together those separate "refused the declared offset" from "staged it, then
complained", which the error code alone cannot.

NO RE-SEAL, BY LAYOUT RATHER THAN BY OMISSION. ``boot_arguments.payload_offset``
sits outside the TBS and outside the bytes ``manifest_hash`` covers (``manifest.h``:
TBS is [0..743], the hash at [1128..1159]), so the primary stays a genuinely signed
slot whose only defect is the declared offset. The payload material is NOT moved
either: the refusal precedes the fetch, and relocating material into the header
would overwrite the very fields the check reads.

THE OFFSET IS DRAWN AT RANDOM from the reference's own range, every 8-byte-aligned
value inside the manifest length, EXCEPT ZERO. The reference draws from
``range(0, 1184, 8)``; zero is excluded here because this ROM refuses
``payload_offset <= 0`` two arms earlier with ``MANIFEST_ERR_BAD_LENGTH``, so a
zero draw would report a length verdict instead of the overlap one the row is named
for. Alignment is kept for the same reason: a misaligned offset fires
``PAYLOAD_OFF_ALIGN``, also ``BAD_LENGTH``. Both of those codes and both tokens are
forbidden, so a draw that slipped past the mutator's guards would fail here rather
than pass as a generic manifest failure. The seed is the runner's, so a failing
draw is reproducible with the run's own ``--seed``, and the drawn value is logged.

SCOPE LIMIT. The reference test of this name picks PRIMARY, BACKUP or BOTH at
random per run, so any single run of it covers one of the three. This row is the
PRIMARY scenario -- the reference's first, and the only one of the three whose
expected outcome is a completed boot. The BACKUP and BOTH scenarios of the overlap
rule have no row here; they would be the terminal mirror, shaped like
``sep_no_payload_images_base``'s terminal pair.

Needs ``+sep_crypto_edn_force``: the backup runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_no_payload_images_base as npi
from rom_fw import sep_toc_defect as td
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

# manifest.h. Returned by exactly one arm, the overlap one, which also announces
# itself -- so unlike most structural codes here the token and the code agree.
ERR_PAYLOAD_OVERLAP = 0x0003_0011
_TOKEN = "PAYLOAD_OVERLAPS_MANIFEST"

# The reference's range, minus the zero the ROM claims through an earlier arm.
_OFFSET_STEP = 8
_OFFSET_MIN = _OFFSET_STEP

# Every payload token except this row's own. Removing only the overlap token
# leaves the sibling arms of validate_manifest_header forbidden, which is the
# console half of the swap test.
_OTHER_TOKENS = tuple(t for t in td.OTHER_PAYLOAD_TOKENS if t != _TOKEN)
assert len(_OTHER_TOKENS) == len(td.OTHER_PAYLOAD_TOKENS) - 1, (
    f"{_TOKEN!r} is no longer in sep_toc_defect.OTHER_PAYLOAD_TOKENS, so this arm's "
    f"token would be neither required by this row nor forbidden by its neighbours; "
    f"the swap-test defence has silently lapsed"
)


@pyuvm.test()
class sep_firmware_payload_overlaps_manifest_test(sep_primary_fail_backup_boot_base):
    """Primary payload_offset inside the manifest header -> refused -> backup boots."""

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_PAYLOAD_OVERLAP
    # The arm DOES print, but sep_primary_fail_backup_boot_base couples
    # primary_defect_marker to a required CRYPTO_FAIL= line and this rejection never
    # reaches manifest_crypto_validate. The token is required through
    # extra_required and attributed by check_transport below instead.
    primary_defect_marker = ""
    # Refused inside validate_manifest_header, upstream of the whole crypto chain.
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0

    extra_required = (_TOKEN, "MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED",
                      "BL1_JUMP=")
    extra_forbidden = tuple(
        npi.forbidden_errors()
        + [td.DECRYPT_START, "CRYPTO_FAIL=", "MANIFEST_ALL_FAILED"]
        + list(_OTHER_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; this row is the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one it is about"
            )
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        m_len = mm.manifest_length(buf, "primary")
        seed = self.random_seed()
        offset = SepSeededRng(seed).choice(
            range(_OFFSET_MIN, m_len, _OFFSET_STEP))
        # The payload SOURCE the ROM would have read, for the negative device check.
        # Recorded before the mutation lands so it is the address the mutated
        # manifest names, not the shipped one.
        self._overlap_src = mm.slot_base("primary") + offset
        was = pm.set_overlapping_payload_offset(buf, "primary", offset)
        self._offset = offset
        self._served = offset.to_bytes(8, "little")
        stored = bytes(buf[mm.slot_base("primary") + pm.OFF_BOOT_PAYLOAD_OFFSET:
                           mm.slot_base("primary") + pm.OFF_BOOT_PAYLOAD_OFFSET + 8])
        assert stored == self._served, (
            f"primary boot_arguments.payload_offset reads {stored.hex()} after the "
            f"write, expected {self._served.hex()}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-OVERLAP: seed %d drew payload_offset %d -> %d, "
            "which is inside the %d-byte manifest header and 8-byte aligned, so "
            "validate_manifest_header must refuse it as %s. The manifest hash and "
            "the signature are UNCHANGED -- boot_arguments sits outside the TBS -- "
            "and the payload material is not moved, because the refusal precedes "
            "the fetch. The device must serve %s at flash 0x%06x",
            seed, was, offset, m_len, _TOKEN, stored.hex(),
            mm.slot_base("primary") + pm.OFF_BOOT_PAYLOAD_OFFSET,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_OVERLAP:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-OVERLAP-ATTRIBUTION: the arm's own token and its error code are BOTH
        # the primary's, in that order, inside the primary's attempt. Exactly one
        # occurrence each: a second would mean the backup carried the same defect,
        # which is the terminal scenario rather than this one.
        i_token = fd.assert_slot_attributed(console, _TOKEN, after=i_psrc,
                                            before=i_bsrc)
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_token,
                                          before=i_bsrc)

        # CHK-REFUSED-BEFORE-INTEGRITY: the primary never reached its own manifest
        # hash check, which sits immediately after validate_manifest_header. One
        # occurrence means the only slot that got that far was the backup.
        n_hash = fd.count(console, "MANIFEST_HASH_OK")
        assert n_hash == 1, (
            f"MANIFEST_HASH_OK appeared {n_hash} times, expected exactly 1 (the "
            f"backup's): the primary was refused by validate_manifest_header, which "
            f"runs BEFORE manifest_check_integrity. Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} precedes the backup read@{i_bsrc}, so it is "
            f"the primary's: its rejection is not upstream of its integrity check. "
            f"Console: {console}"
        )

        # CHK-REFUSED-BEFORE-STAGING: the primary never chose a destination and
        # never transferred. Exactly one staging event in the run, the backup's, and
        # it sits inside the backup attempt.
        for marker in (ues.USING_SEP, f"PAYLOAD_DST=0x{ues.SEP_PAYLOAD_DST:08x}"):
            n = fd.count(console, marker)
            assert n == 1, (
                f"{marker} appeared {n} times, expected exactly 1 (the backup's): "
                f"the primary must be refused before it stages anything. "
                f"Console: {console}"
            )
            i = fd.first_index(console, marker)
            assert i_bsrc < i, (
                f"{marker}@{i} precedes the backup read@{i_bsrc}, so the primary "
                f"staged its payload and the refusal did not happen upstream of the "
                f"transfer. Console: {console}"
            )
        self.logger.info(
            "CHK-REFUSED-UPSTREAM: primary@%d -> %s@%d -> %s@%d, with "
            "MANIFEST_HASH_OK, %s and PAYLOAD_DST= each appearing once and after "
            "the backup read@%d -- the primary was refused before its integrity "
            "check and before any staging",
            i_psrc, _TOKEN, i_token, slot_err, i_err, ues.USING_SEP, i_bsrc,
        )

        # CHK-NO-READ: the device was never asked for the primary's payload at the
        # address the mutated manifest named. The absence of that read is a claim
        # about the ROM's decision, not about the transport.
        fd.assert_no_read_starting_at(
            self.logger, flash, self._overlap_src,
            f"the primary declared payload_offset {self._offset}, inside its own "
            f"manifest header, so validate_manifest_header must refuse the slot "
            f"before the payload fetch is ever issued",
        )

        # CHK-STIMULUS-SERVED: the device really returned the drawn offset at the
        # field's address, so the DUT was given the stimulus this row's name
        # describes rather than the shipped one.
        fd.assert_served_field(self.logger, flash, "primary",
                               pm.OFF_BOOT_PAYLOAD_OFFSET, self._served,
                               "primary boot_arguments.payload_offset")
