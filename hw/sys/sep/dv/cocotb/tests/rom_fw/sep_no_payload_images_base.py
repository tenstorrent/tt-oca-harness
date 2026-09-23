# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and evidence for the three "manifest declares no payload images" rows.

Plants ``toc->image_count = 0`` in a plaintext slot, which the ROM must refuse with the
silent ``MANIFEST_ERR_TOC_COUNT`` arm after that slot's crypto chain has passed.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_manifest_fail_base import sep_backup_manifest_fail_base
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base

EMPTY_IMAGE_COUNT = 0
ERR_TOC_COUNT = td.ERR_TOC_COUNT

# Primary failover trigger for the BACKUP row: an invalid TOC major_version.
TRIGGER_TOC_VERSION = 99
ERR_BAD_TOC_VERSION = td.ERR_BAD_TOC_VERSION

IMAGE_COUNT_FIELD = (pm.TOC_OFF_IMAGE_COUNT, 8)
TOC_VERSION_FIELD = (pm.TOC_OFF_MAJOR_VERSION, 2)

# ROM emission order; each slot's four must sit inside its own attempt.
CRYPTO_CHAIN = ("RSA_VERIFY_START", "SIG_VALID", "PLD_HASH_OK",
                "CRYPTO_VALIDATE_OK")
MANIFEST_HASH_OK = "MANIFEST_HASH_OK"
ALL_FAILED = "MANIFEST_ALL_FAILED"
MANIFEST_OK = "MANIFEST_OK"
CRYPTO_FAIL = "CRYPTO_FAIL="
SBOOT_OFF = "SBOOT_OFF"
BOOT_PROGRESS = ("PRE_JUMP", "BL1_COPIED", "BL1_JUMP=")

_ALL_STRUCTURAL_ERRORS = (
    td.ERR_BAD_MAGIC, td.ERR_BAD_VERSION, td.ERR_BAD_LENGTH, td.ERR_BAD_TOC_ID,
    td.ERR_BAD_TOC_VERSION, td.ERR_PAYLOAD_TOO_LARGE, td.ERR_NO_BL1_IMAGE,
    td.ERR_TOC_COUNT,
)


def forbidden_errors(*produced: int) -> list[str]:
    return [f"MANIFEST_ERR=0x{c:08x}" for c in _ALL_STRUCTURAL_ERRORS
            if c not in produced]


def plant_empty_image_list(logger, buf: bytearray, slot: str) -> bytes:
    major, minor = mm.manifest_version(buf, slot)
    assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
        f"{slot} manifest version is {major}.{minor}: the slot would be refused by "
        f"validate_manifest_header before the TOC is ever parsed"
    )
    assert mm.manifest_length(buf, slot) == mm.MANIFEST_SIZE, (
        f"{slot} manifest_length is {mm.manifest_length(buf, slot)}, expected "
        f"{mm.MANIFEST_SIZE}: BAD_LENGTH would pre-empt the TOC arm"
    )
    off, size = IMAGE_COUNT_FIELD
    was = pm.set_toc_image_count(buf, slot, EMPTY_IMAGE_COUNT)
    assert was > 0, (
        f"{slot} TOC already declared {was} images before the mutation, so this row "
        f"would not have changed the count the ROM reads"
    )
    p = pm.payload_base(buf, slot)
    stored = bytes(buf[p + off:p + off + size])
    # Pin literal zero: n > 256 returns the same code and would pass every other check.
    assert EMPTY_IMAGE_COUNT == 0 and stored == bytes(size), (
        f"{slot} TOC image_count was planted as {EMPTY_IMAGE_COUNT} and stored as "
        f"{stored.hex()}; these rows are the ZERO half of the count bound, and the "
        f"over-large half already has four cells of its own "
        f"(sep_toc_defect.BAD_IMAGE_COUNT). Anything but zero here makes this row a "
        f"duplicate of those while still passing every other check"
    )
    now = int.from_bytes(bytes(pm.toc_plaintext(buf, slot)[off:off + size]), "little")
    assert now == EMPTY_IMAGE_COUNT, (
        f"{slot} TOC image_count reads {now} after the write, expected "
        f"{EMPTY_IMAGE_COUNT}; the mutation did not land"
    )
    logger.info(
        "CHK-STIMULUS-NO-PAYLOAD-IMAGES: %s TOC image_count %d -> %d. The field "
        "sits at flash 0x%06x and the device must serve %s there. Every other "
        "payload rule is left SATISFIED -- identifier PTOC, major_version %d, "
        "payload_length agreeing with the manifest, payload_hash and the signature "
        "recomputed over the edit -- so the empty image list is the only rule "
        "validate_manifest_payload can refuse this slot on, and it is refused "
        "BEFORE the TOC_REGION_OOB bound that follows it",
        slot, was, now, p + off, stored.hex(), pm.TOC_MAJOR_VERSION,
    )
    return stored


def assert_crypto_chain_twice(logger, console: list[str], i_psrc: int,
                              i_bsrc: int, i_end: int) -> tuple[list[int], list[int]]:
    primary: list[int] = []
    backup: list[int] = []
    for markers, lo, hi, who in ((primary, i_psrc, i_bsrc, "primary"),
                                 (backup, i_bsrc, i_end, "backup")):
        previous = lo
        for marker in CRYPTO_CHAIN:
            n = fd.count(console, marker)
            assert n == 2, (
                f"{marker} appeared {n} times, expected exactly 2 (one per slot): "
                f"every member here plants a defect downstream of the crypto chain, "
                f"so both slots must reach it. Console: {console}"
            )
            i = fd.first_index(console, marker, after=previous)
            assert previous < i < hi, (
                f"the {who}'s {marker}@{i} does not sit between the previous "
                f"stage@{previous} and the end of its attempt@{hi}: its crypto chain "
                f"is out of order or outside its own attempt. Console: {console}"
            )
            markers.append(i)
            previous = i
    logger.info(
        "CHK-CRYPTO-BOTH-SLOTS: primary %s; backup %s -- each slot's signature "
        "verified inside its own attempt before its payload was graded",
        ", ".join(f"{m}@{p}" for m, p in zip(CRYPTO_CHAIN, primary)),
        ", ".join(f"{m}@{p}" for m, p in zip(CRYPTO_CHAIN, backup)),
    )
    return primary, backup


class sep_no_payload_images_primary_base(sep_primary_fail_backup_boot_base):

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = ERR_TOC_COUNT
    # The TOC-count arm prints no token of its own.
    primary_defect_marker = ""
    primary_expected_rsa_starts = 1
    primary_expected_sig_valids = 1

    extra_required = (MANIFEST_HASH_OK, "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    extra_forbidden = tuple(
        forbidden_errors(ERR_TOC_COUNT)
        + [CRYPTO_FAIL, ALL_FAILED, td.DECRYPT_START]
        + list(td.OTHER_PAYLOAD_TOKENS)
        + list(td.DECRYPT_FAILURE_TOKENS)
    )

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; these rows are the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one they are about"
            )
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._served = plant_empty_image_list(self.logger, buf, "primary")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{ERR_TOC_COUNT:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(self.logger, flash, "primary",
                               self._payload_offset + off, self._served,
                               "primary TOC image_count")

        self.logger.info(
            "CHK-NO-PAYLOAD-IMAGES: primary@%d declared an empty image list and was "
            "refused %s@%d inside its own attempt, after its signature verified; the "
            "untouched backup was read@%d and booted",
            i_psrc, slot_err, i_err, i_bsrc,
        )


class sep_no_payload_images_terminal_base(sep_backup_manifest_fail_base):

    flash_image = td.PLAINTEXT_IMAGE
    efuse_preload = td.PLAINTEXT_EFUSE
    expected_error = ERR_TOC_COUNT
    # The TOC-count arm prints no token of its own.
    backup_defect_marker = ""
    requires_defect_marker = False
    primary_field: tuple[int, int] = IMAGE_COUNT_FIELD

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        for slot in ("primary", "backup"):
            assert not pm.is_encrypted(buf, slot), (
                f"{slot} payload carries encrypted_payload = 1; these rows are the "
                f"PLAINTEXT stimulus and the loaded image ({self.flash_image}) is "
                f"not the one they are about"
            )
        self._primary_payload_offset = (pm.payload_base(buf, "primary")
                                        - mm.slot_base("primary"))
        self._backup_payload_offset = (pm.payload_base(buf, "backup")
                                       - mm.slot_base("backup"))
        return super().mutate_flash_image(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        self._backup_served = plant_empty_image_list(self.logger, buf, "backup")

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        log = self.logger
        status_hex = [hex(v) for v in status_seq]
        log.info("cold_scratch[1] sequence: %s", status_hex)
        log.info("ROM console: %s", console)

        # An empty console would make every marker check below pass vacuously.
        assert retired, "core retired no instructions; the ROM never ran"
        assert console, (
            "ROM console is empty, so no marker check below means anything (the "
            "virt console is DEBUG-build only -- check the ROM build)"
        )

        primary_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        backup_err = f"MANIFEST_ERR=0x{self.expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)
        i_all = fd.first_index(console, ALL_FAILED)

        assert i_psrc >= 0, (
            f"ROM never read the primary slot ({fd.PRIMARY_SRC}). Console: {console}"
        )
        assert i_psrc < i_bsrc, (
            f"backup slot ({fd.BACKUP_SRC}@{i_bsrc}) was not read after the "
            f"primary@{i_psrc}: this is not a failover. Console: {console}"
        )
        assert i_bsrc < i_all, (
            f"{ALL_FAILED}@{i_all} did not follow the backup read@{i_bsrc}: the ROM "
            f"gave up before evaluating the backup. Console: {console}"
        )

        primary_chain, backup_chain = assert_crypto_chain_twice(
            log, console, i_psrc, i_bsrc, i_all)
        n_hash = fd.count(console, MANIFEST_HASH_OK)
        assert n_hash == 2, (
            f"{MANIFEST_HASH_OK} appeared {n_hash} times, expected exactly 2 (one "
            f"per slot): every defect here sits downstream of "
            f"manifest_check_integrity, so both slots must pass it and neither is "
            f"refused for a stale hash. Console: {console}"
        )
        for lo, hi, who in ((i_psrc, primary_chain[0], "primary"),
                            (i_bsrc, backup_chain[0], "backup")):
            i = fd.first_index(console, MANIFEST_HASH_OK, after=lo)
            assert lo < i < hi, (
                f"the {who}'s {MANIFEST_HASH_OK}@{i} does not sit between its "
                f"read@{lo} and its {CRYPTO_CHAIN[0]}@{hi}: its integrity check is "
                f"not part of its own attempt. Console: {console}"
            )

        n_err = fd.count(console, "MANIFEST_ERR=")
        assert n_err == 2, (
            f"MANIFEST_ERR= appeared {n_err} times, expected exactly 2 (one per "
            f"slot). Console: {console}"
        )
        if primary_err == backup_err:
            assert fd.count(console, primary_err) == 2, (
                f"{primary_err} appeared {fd.count(console, primary_err)} times; "
                f"this row plants the same defect in both slots, so the code must "
                f"appear once per slot. Console: {console}"
            )
            i_perr = fd.first_index(console, primary_err)
            i_berr = fd.first_index(console, backup_err, after=i_bsrc)
            assert i_psrc < i_perr < i_bsrc < i_berr < i_all, (
                f"the two rejections are not one per slot: primary read@{i_psrc}, "
                f"error@{i_perr}, backup read@{i_bsrc}, error@{i_berr}, "
                f"{ALL_FAILED}@{i_all}. Console: {console}"
            )
        else:
            i_perr = fd.assert_slot_attributed(console, primary_err, after=i_psrc,
                                               before=i_bsrc)
            i_berr = fd.assert_slot_attributed(console, backup_err, after=i_bsrc,
                                               before=i_all)
        assert primary_chain[-1] < i_perr, (
            f"{primary_err}@{i_perr} precedes the primary's "
            f"{CRYPTO_CHAIN[-1]}@{primary_chain[-1]}: its rejection is not "
            f"downstream of its own crypto chain. Console: {console}"
        )
        assert backup_chain[-1] < i_berr, (
            f"{backup_err}@{i_berr} precedes the backup's "
            f"{CRYPTO_CHAIN[-1]}@{backup_chain[-1]}: its rejection is not "
            f"downstream of its own crypto chain. Console: {console}"
        )
        log.info(
            "CHK-SLOT-ERRORS: primary@%d -> %s@%d -> backup@%d -> %s@%d -> %s@%d, "
            "and MANIFEST_ERR= appeared exactly twice",
            i_psrc, primary_err, i_perr, i_bsrc, backup_err, i_berr, ALL_FAILED,
            i_all,
        )

        for marker in (CRYPTO_FAIL, MANIFEST_OK, SBOOT_OFF):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, so the payload rejection under test is not "
                f"what ended this run. Console: {console}"
            )
        log.info("CHK-NOT-A-CRYPTO-FAILURE: neither %s, %s nor %s appeared",
                 CRYPTO_FAIL, MANIFEST_OK, SBOOT_OFF)

        expected_status = 0x0F01_0000 | (self.expected_error & 0xFFFF)
        assert expected_status in status_seq, (
            f"cold_scratch[1] never held 0x{expected_status:08x} "
            f"(STATUS_ENCODE(ERROR, 0x{self.expected_error & 0xFFFF:04x})); "
            f"observed {status_hex}"
        )
        assert fw_done, (
            f"ROM never signalled completion; two rejected slots must converge on a "
            f"FAIL verdict. cold_scratch[1]: {status_hex}"
        )
        assert not fw_pass, (
            "ROM signalled PASS: it booted an image it was supposed to reject"
        )
        log.info("CHK-TERMINAL: %s, %s, cold_scratch[1]=0x%08x, verdict FAIL",
                 backup_err, ALL_FAILED, expected_status)

        for marker in BOOT_PROGRESS + tuple(self.extra_forbidden):
            assert not any(marker in line for line in console), (
                f"ROM printed {marker}, which sits past the rejection: it continued "
                f"booting a manifest it had already failed. Console: {console}"
            )
        log.info("CHK-NO-BOOT: none of %s reached",
                 ", ".join(BOOT_PROGRESS + tuple(self.extra_forbidden)))

        off, _size = IMAGE_COUNT_FIELD
        fd.assert_served_field(log, self._flash, "backup",
                               self._backup_payload_offset + off,
                               self._backup_served, "backup TOC image_count")
        p_off, _p_size = self.primary_field
        fd.assert_served_field(log, self._flash, "primary",
                               self._primary_payload_offset + p_off,
                               self._primary_served,
                               "primary's failover-trigger field")
