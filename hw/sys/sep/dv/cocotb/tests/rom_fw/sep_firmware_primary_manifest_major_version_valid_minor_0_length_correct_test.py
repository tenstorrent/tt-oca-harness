# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest is a valid v1.0 whose manifest_length is the body size; it boots.

The ROM must read exactly the declared body and payload, and nothing else.
Needs ``+esrc_noise_force``: the accepted primary runs a full RSA-3072 modexp on OTBN.
"""

from __future__ import annotations

import os
import struct
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from env.sep_efuse_image import SBOOT_DIS_MASK
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR
_ORDERED = (
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_AUTHORIZED",
    "RSA_EXEC",
    "RSA_VERIFY_OK",
    "MANIFEST_OK",
    "PAYLOAD_OK",
    "BL1_COPIED",
    "BL1_JUMP=",
)


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test(
    sep_rom_ot_secure_boot_test
):
    """v1.0 with manifest_length equal to the body size is accepted, and the primary boots."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + ("LC=PROD",) + _ORDERED
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + (
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "RSA_PKCS1_FAIL",
        "PAYLOAD_LOC_FAIL",
        "PAYLOAD_TOO_LARGE",
        "FLASH_READ_OOB",
        "NO_BL1_IMAGE",
    )

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        sboot_dis = image.field_int("SBOOT_DIS") & SBOOT_DIS_MASK
        assert lc == 0x1, (
            f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD): secure boot must be "
            f"enforced, or the accepted slot would not be graded on a completed "
            f"crypto chain"
        )
        assert sboot_dis == 0, (
            f"SBOOT_DIS is {sboot_dis}: the crypto chain would be skipped entirely"
        )
        fd.assert_clean_key_fuses(image)
        self.logger.info(
            "CHK-STIMULUS-EFUSE: LC raw=0x%x (PROD), SBOOT_DIS=%d, "
            "BL1_VERSION=0x%x, PUBK_REVOKE=0x%x",
            lc,
            sboot_dis,
            image.field_int("BL1_VERSION"),
            image.field_int("CHIPLET_PUBK_REVOKE"),
        )
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        # sep_manifest_mutate refuses no-op writes, so the shipped values are asserted.
        fd.assert_consumer_body_size()
        major, minor = mm.manifest_version(buf, "primary")
        length = mm.manifest_length(buf, "primary")
        assert major == mm.MANIFEST_MAJOR_VERSION, (
            f"primary manifest_version_major is {major}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}: the slot under test is supposed to be "
            f"the ACCEPTED one and would be refused as BAD_VERSION"
        )
        assert minor == 0, (
            f"primary manifest_version_minor is {minor}, expected 0: this testcase "
            f"grades a v1.0 manifest"
        )
        assert length == mm.BODY_SIZE, (
            f"primary manifest_length is {length}, expected exactly the {mm.BODY_SIZE}-byte "
            f"body: oca_check_manifest_length refuses any other value"
        )
        assert (
            bytes(buf[mm.PRIMARY_MANIFEST_OFFSET : mm.PRIMARY_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), "primary manifest magic is not OCAC"
        pm.verify_sealed(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-PRIMARY-VERSION: primary declares %d.%d with "
            "manifest_length %d == the body size. It passes payload_hash, every TOC image digest, "
            "manifest_hash over the signed region and RSA verification against the dev0 "
            "modulus, and the modulus it carries hashes to the ROM's compiled-in "
            "slot-0 digest",
            major,
            minor,
            length,
        )
        self.logger.info("CHK-STIMULUS-PRIMARY: %s", mm.describe(buf, "primary"))
        self._payload = (
            pm.payload_base(buf, "primary"),
            pm.manifest_payload_length(buf, "primary"),
        )
        return buf

    def log_transport(self, flash) -> None:
        self.logger.info(
            "CHK-SPI-TXNS:\n%s", ev.summarize(flash.get_transactions(), self._image_len)
        )

    def check_transport(self, console: list[str], flash) -> None:
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, 0, mm.BODY_SIZE),
            "primary manifest_version_major/minor + manifest_length",
        )

        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: the length-correct primary must be accepted on its first read"
        )
        att = attempts[0]
        oc.assert_attempt(att, error=None, stage="accepted", ordered=_ORDERED)

        body = (mm.PRIMARY_MANIFEST_OFFSET, mm.PRIMARY_MANIFEST_OFFSET + mm.BODY_SIZE)
        p_start, p_len = self._payload
        payload = (p_start, p_start + p_len)
        rds = ev.reads(flash.get_transactions())
        spans = [ev.read_span(t) for t in rds]
        stray = [
            (s, e)
            for s, e in spans
            if not (body[0] <= s and e <= body[1]) and not (payload[0] <= s and e <= payload[1])
        ]
        assert not stray, (
            f"read(s) {[f'0x{s:x}..0x{e:x}' for s, e in stray]} fall outside the declared "
            f"body 0x{body[0]:x}..0x{body[1]:x} and payload 0x{payload[0]:x}..0x{payload[1]:x}: "
            f"the ROM fetched bytes manifest_length and payload_length do not describe"
        )
        assert body in spans, (
            f"no single read fetched exactly the {mm.BODY_SIZE}-byte body "
            f"0x{body[0]:x}..0x{body[1]:x}: the ROM did not size the body read from the "
            f"manifest it peeked. Read spans: {[f'0x{s:x}..0x{e:x}' for s, e in spans]}"
        )
        self.logger.info(
            "CHK-LENGTH-RULE PASS: primary@%d-%d declared v%d.0 with manifest_length %d and was "
            "accepted after %s; every read fell inside the body 0x%x..0x%x or the payload "
            "0x%x..0x%x, and none covered the backup slot",
            att.first,
            att.last,
            mm.MANIFEST_MAJOR_VERSION,
            mm.BODY_SIZE,
            " -> ".join(_ORDERED),
            body[0],
            body[1],
            payload[0],
            payload[1],
        )


oc.assert_known(
    sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test.required_markers
    + sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test.forbidden_markers,
    "sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test",
)
