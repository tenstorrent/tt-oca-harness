# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and checks for the payload-size rom_fw testcases.

Accepted members repack the primary to a legal size and must boot it; the refused
member over-declares it and must fail over to the backup.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from env import sep_spi_slot_evidence as ev
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_rom_ot_dma_boot_test import SECURE_FLASH_IMAGE
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test
from sep_reg_meta import sym

# PROD lifecycle, so the ROM enforces the signature chain regardless of the manifest flag.
EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")

_SEP_ADDR_H = Path(__file__).resolve().parents[4] / "regs" / "gen" / "c" / "sep_addr.h"

# The current ROM stages the OCA body and payload contiguously in SEP SRAM.
OCA_BODY_BYTES = (mm.BODY_SIZE + 7) & ~7
ERR_PAYLOAD_TOO_LARGE = mm.rom_boot_err("OCA_BOOT_ERR_STAGE_OVERFLOW")

_OTHER_LENGTH_REFUSALS = (
    "PAYLOAD_LEN_RANGE",
    "PAYLOAD_OFF_RANGE",
    "PAYLOAD_OFF_ALIGN",
    "PAYLOAD_HASHED_LEN_BAD=",
    "ENC_HASHED_LEN_PARTIAL",
    "TOC_REGION_OOB=",
    "TOC_PLEN_MISMATCH=",
    "PAYLOAD_OVERLAPS_MANIFEST",
)
_STRUCTURAL_REFUSALS = (
    "IMAGE_OFF_ALIGN idx=",
    "IMAGE_END_OVERFLOW idx=",
    "IMAGE_OOB_BOUND idx=",
    "IMAGE_ORDER_BAD idx=",
    "IMAGE_LEN_ZERO idx=",
    "IMAGE_LEN_ALIGN idx=",
    "IMAGE_HASH_MISMATCH idx=",
    "IMAGE_HASH_TIMEOUT",
    "NO_BL1_IMAGE",
    "BL1_ADDR_RANGE",
    "BL1_ENTRY_RANGE",
    "PLD_HASH_FAIL=",
    "CRYPTO_FAIL=",
    "MANIFEST_ALL_FAILED",
)
_PRIMARY_SRC = fd.PRIMARY_SRC
_BACKUP_SRC = fd.BACKUP_SRC


def assert_rom_sram_bounds() -> tuple[int, int]:
    # A resized SRAM would silently make the refused size legal; the C and Python bounds must agree.
    text = _SEP_ADDR_H.read_text()
    found = {}
    for name in ("OCH_SEP_TOP_SEP_SRAM_BASE_ADDR", "OCH_SEP_TOP_SEP_SRAM_SIZE"):
        hit = re.search(rf"^#define\s+{name}\s+(0x[0-9a-fA-F]+)\s*$", text, re.MULTILINE)
        assert hit, (
            f"{name} is not defined in {_SEP_ADDR_H}; every payload size bound in "
            f"this module is then an unverified number"
        )
        found[name] = int(hit.group(1), 16)
    base = found["OCH_SEP_TOP_SEP_SRAM_BASE_ADDR"]
    size = found["OCH_SEP_TOP_SEP_SRAM_SIZE"]
    assert (base, size) == (SEP_SRAM_BASE, SEP_SRAM_SIZE), (
        f"{_SEP_ADDR_H} gives SEP SRAM base 0x{base:08x} size 0x{size:08x}, but the "
        f"generated Python map gives 0x{SEP_SRAM_BASE:08x}/0x{SEP_SRAM_SIZE:08x}. "
        f"The ROM is compiled against the C values, so the capacity this testcase "
        f"reasons about is not the one the DUT enforces"
    )
    return base, size


def shipped_payload_bytes(slot: str) -> int:
    with open(SECURE_FLASH_IMAGE, "rb") as fh:
        return pm.manifest_payload_length(bytearray(fh.read()), slot)


def shipped_payload_offset(slot: str) -> int:
    with open(SECURE_FLASH_IMAGE, "rb") as fh:
        buf = bytearray(fh.read())
    return pm.payload_base(buf, slot) - mm.slot_base(slot)


def payload_staging_capacity() -> int:
    assert_rom_sram_bounds()
    return SEP_SRAM_SIZE - OCA_BODY_BYTES


def accepted_markers(payload_bytes: int, *, smc: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    assert not smc, "the OCA ROM no longer supports manifest-selected SMC staging"
    return (
        (
            "MANIFEST_PRIMARY",
            _PRIMARY_SRC,
            "MANIFEST_OK",
            f"OCA_BODY=0x{mm.BODY_SIZE:08x}",
            "PAYLOAD_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        ),
        _OTHER_LENGTH_REFUSALS
        + _STRUCTURAL_REFUSALS
        + (
            "MANIFEST_BACKUP",
            _BACKUP_SRC,
            "MANIFEST_ERR=",
            "PAYLOAD_LOC_OT_OOB",
            "PAYLOAD_LOC_SMC_OOB",
            "PAYLOAD_LOC_OVERFLOW",
            "PAYLOAD_TOO_LARGE",
        ),
    )


def refused_markers(backup_payload_bytes: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        (
            "MANIFEST_PRIMARY",
            _PRIMARY_SRC,
            "PAYLOAD_TOO_LARGE",
            f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}",
            "MANIFEST_BACKUP",
            _BACKUP_SRC,
            "MANIFEST_OK",
            f"OCA_BODY=0x{mm.BODY_SIZE:08x}",
            "PAYLOAD_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        ),
        _OTHER_LENGTH_REFUSALS
        + _STRUCTURAL_REFUSALS
        + (
            "PAYLOAD_NO_ROOM=",
            "PAYLOAD_LOC_OT_OOB",
            "PAYLOAD_LOC_SMC_OOB",
            "PAYLOAD_LOC_OVERFLOW",
            "STAGED_WIPE=",
            "FLASH_REINIT_FAIL=",
        ),
    )


def _served_intervals(flash) -> list[tuple[int, int]]:
    # The flash model streams one byte past each request until CS deasserts; drop it from coverage.
    spans = []
    for txn in ev.reads(flash.get_transactions()):
        start, end = ev.read_span(txn)
        if end - 1 > start:
            spans.append((start, end - 1))
    spans.sort()
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def assert_payload_served(logger, flash, payload_src: int, payload_bytes: int, what: str) -> None:
    # Checks the bytes the device served, not the bytes staged at the destination.
    merged = _served_intervals(flash)
    want_end = payload_src + payload_bytes
    covering = [(s, e) for s, e in merged if s <= payload_src and e >= want_end]
    assert covering, (
        f"the device did not serve all of {what} at flash "
        f"0x{payload_src:x}..0x{want_end:x} ({payload_bytes} bytes). Served ranges: "
        f"{[f'0x{s:x}..0x{e:x}' for s, e in merged]}"
    )
    logger.info(
        "CHK-PAYLOAD-SERVED: the flash served 0x%06x..0x%06x (%d bytes) for %s, so "
        "the payload size under test is a property of the transfer. Served ranges: %s",
        payload_src,
        want_end,
        payload_bytes,
        what,
        [f"0x{s:x}..0x{e:x}" for s, e in merged],
    )


class _PayloadSizeTest(sep_rom_ot_secure_boot_test):
    efuse_preload = EFUSE_PRELOAD
    # Bytes the primary manifest declares; every member must set it.
    payload_bytes: int = 0
    # Kept only so removed SMC-era modules fail clearly if run directly.
    stage_in_smc = False

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        assert lc == 0x1, f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD)"
        assert (image.field_int("SBOOT_DIS") & 0x1) == 0, (
            "SBOOT_DIS is set: the crypto chain would be skipped"
        )
        fd.assert_clean_key_fuses(image)
        return image

    def _payload_src(self, buf) -> int:
        return pm.payload_base(buf, "primary")

    def _select_destination(self, buf: bytearray) -> None:
        assert not self.stage_in_smc, (
            "manifest-selected SMC staging was removed from the OCA ROM; this "
            "module must not be registered"
        )
        mm.verify_layout(buf, "primary")

    def log_transport(self, flash) -> None:
        self.logger.info(
            "SPI reads served: %s",
            [f"0x{s:x}..0x{e:x}" for s, e in _served_intervals(flash)],
        )


class PayloadSizeAcceptedTest(_PayloadSizeTest):
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert self.payload_bytes, "payload_bytes is unset"
        geometry = pm.repack_payload(buf, "primary", self.payload_bytes)
        self._select_destination(buf)
        capacity = payload_staging_capacity()
        assert self.payload_bytes <= capacity, (
            f"{self.payload_bytes} bytes exceeds the {capacity}-byte OCA payload "
            f"staging capacity after the {OCA_BODY_BYTES}-byte manifest body, so this member would "
            f"be refused rather than accepted"
        )
        mm.verify_public_key(buf, "primary")
        self._src = self._payload_src(buf)
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-SIZE: primary repacked to payload_length=%d "
            "(0x%x), %s, BL1 %d bytes at payload offset %d; fixed OCA SEP-SRAM "
            "staging capacity %d",
            self.payload_bytes,
            self.payload_bytes,
            geometry,
            geometry["bl1_length"],
            geometry["bl1_offset"],
            capacity,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        assert fd.count(console, "MANIFEST_PRIMARY") == 1, (
            f"MANIFEST_PRIMARY appeared "
            f"{fd.count(console, 'MANIFEST_PRIMARY')} times, expected 1. "
            f"Console: {console}"
        )
        self.logger.info(
            "CHK-SIZE-ACCEPTED: the ROM validated the payload and reached BL1, so "
            "%d bytes is inside its fixed SEP-SRAM staging bound",
            self.payload_bytes,
        )
        assert_payload_served(
            self.logger, flash, self._src, self.payload_bytes, "the primary payload"
        )


class PayloadSizeRefusedTest(_PayloadSizeTest):
    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        assert self.payload_bytes, "payload_bytes is unset"
        payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        capacity = payload_staging_capacity()
        assert self.payload_bytes > capacity, (
            f"{self.payload_bytes} bytes fits the {capacity}-byte OCA SEP-SRAM "
            f"staging capacity, so the ROM would "
            f"ACCEPT it and this member would prove the opposite of its name"
        )
        # The 32-bit overflow arm returns the same code with no token, so keep the sum below 2^32.
        assert self.payload_bytes <= 0xFFFF_FFFF - payload_offset, (
            f"payload_offset 0x{payload_offset:x} + {self.payload_bytes} bytes "
            f"overflows 32 bits, which validate_manifest_header refuses through a "
            f"silent arm returning the same error code as the capacity check; the "
            f"refusal would no longer be attributable to the size decision"
        )
        was = pm.declare_payload_length(buf, "primary", self.payload_bytes)
        self._select_destination(buf)
        mm.verify_public_key(buf, "primary")
        self._backup_payload_bytes = pm.manifest_payload_length(buf, "backup")
        self._src = self._payload_src(buf)
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-SIZE: primary payload_length %d -> %d (0x%x), "
            "which is %d bytes past the %d-byte fixed OCA staging capacity; "
            "flash payload_offset remains 0x%x and the backup keeps %d",
            was,
            self.payload_bytes,
            self.payload_bytes,
            self.payload_bytes - capacity,
            capacity,
            payload_offset,
            self._backup_payload_bytes,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_TOO_LARGE:08x}"
        i_primary = fd.first_index(console, "MANIFEST_PRIMARY")
        i_err = fd.first_index(console, err)
        i_backup = fd.first_index(console, "MANIFEST_BACKUP")
        i_ok = fd.first_index(console, "MANIFEST_OK")
        assert 0 <= i_primary < i_err < i_backup < i_ok, (
            f"the refusal is not attributable to the primary: MANIFEST_PRIMARY@"
            f"{i_primary}, {err}@{i_err}, MANIFEST_BACKUP@{i_backup}, "
            f"MANIFEST_OK@{i_ok}. Console: {console}"
        )
        assert fd.count(console, "MANIFEST_ERR=") == 1, (
            f"MANIFEST_ERR= appeared {fd.count(console, 'MANIFEST_ERR=')} times; "
            f"only the primary may fail here, so a second slot error means the "
            f"backup was refused for a reason this member does not model. "
            f"Console: {console}"
        )
        i_payload_ok = fd.first_index(console, "PAYLOAD_OK")
        assert i_backup < i_payload_ok, (
            f"PAYLOAD_OK@{i_payload_ok} precedes MANIFEST_BACKUP@{i_backup}: the "
            f"over-capacity primary was accepted instead of the healthy backup"
        )
        self.logger.info(
            "CHK-SIZE-REFUSED: MANIFEST_PRIMARY@%d -> %s@%d -> MANIFEST_BACKUP@%d "
            "-> PAYLOAD_OK@%d -> MANIFEST_OK@%d -- the over-capacity primary was refused "
            "before staging and the backup booted",
            i_primary,
            err,
            i_err,
            i_backup,
            i_payload_ok,
            i_ok,
        )
        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._src,
            "the primary declared a payload larger than SEP SRAM, so "
            "validate_manifest_header must refuse the slot before the payload "
            "fetch is ever issued",
        )
