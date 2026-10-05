# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared stimulus and checks for the payload-size rom_fw testcases.

Accepted members repack the primary to a legal size and must boot it; the refused
member over-declares it past the slot window and must fail over to the backup.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
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

# The ROM stages the OCA body and payload contiguously in SEP SRAM.
OCA_BODY_BYTES = (mm.BODY_SIZE + 7) & ~7
ERR_PAYLOAD_LOCATION = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_SLOT_STRIDE = mm.BACKUP_MANIFEST_OFFSET - mm.PRIMARY_MANIFEST_OFFSET
_SLOT_WINDOW_SPAN = _SLOT_STRIDE - mm.PRIMARY_MANIFEST_OFFSET

_LOC_FAIL = "PAYLOAD_LOC_FAIL"
_TRANSPORT_REFUSALS = ("FLASH_READ_OOB", "DMA_STS=")
_OTHER_PAYLOAD_REFUSALS = (_LOC_FAIL,) + _TRANSPORT_REFUSALS
_PLACEMENT_REFUSALS = (
    "NO_BL1_IMAGE",
    "BL1_SRAM_EXEC_DISABLED",
    "BL1_ADDR_RANGE",
    "BL1_SIZE",
    "BL1_ENTRY_RANGE",
    "MANIFEST_ALL_FAILED",
)
_KEY_OK = "PUBK_AUTHORIZED"
_RSA_EXEC = "RSA_EXEC"
_RSA_OK = "RSA_VERIFY_OK"
_SIGNED_ACCEPT = (_KEY_OK, _RSA_EXEC, _RSA_OK, "MANIFEST_OK")
_BOOTED = ("PAYLOAD_OK", "BL1_COPIED", "BL1_JUMP=")
_PRIMARY_SRC = fd.PRIMARY_SRC
_BACKUP_SRC = fd.BACKUP_SRC


def assert_rom_sram_bounds() -> tuple[int, int]:
    # A resized SRAM would silently make the refused size legal; the C and Python bounds must agree.
    text = _SEP_ADDR_H.read_text()
    found = {}
    for name in ("SEP_TOP_SEP_SRAM_BASE_ADDR", "SEP_TOP_SEP_SRAM_SIZE"):
        hit = re.search(rf"^#define\s+{name}\s+(0x[0-9a-fA-F]+)\s*$", text, re.MULTILINE)
        assert hit, (
            f"{name} is not defined in {_SEP_ADDR_H}; every payload size bound in "
            f"this module is then an unverified number"
        )
        found[name] = int(hit.group(1), 16)
    base = found["SEP_TOP_SEP_SRAM_BASE_ADDR"]
    size = found["SEP_TOP_SEP_SRAM_SIZE"]
    assert (base, size) == (SEP_SRAM_BASE, SEP_SRAM_SIZE), (
        f"{_SEP_ADDR_H} gives SEP SRAM base 0x{base:08x} size 0x{size:08x}, but the "
        f"generated Python map gives 0x{SEP_SRAM_BASE:08x}/0x{SEP_SRAM_SIZE:08x}. "
        f"The ROM is compiled against the C values, so the capacity this testcase "
        f"reasons about is not the one the DUT enforces"
    )
    return base, size


def shipped_payload_offset(slot: str) -> int:
    with open(SECURE_FLASH_IMAGE, "rb") as fh:
        buf = bytearray(fh.read())
    return pm.payload_base(buf, slot) - mm.slot_base(slot)


def payload_staging_capacity() -> int:
    assert_rom_sram_bounds()
    return SEP_SRAM_SIZE - OCA_BODY_BYTES


def accepted_markers(payload_bytes: int, *, smc: bool) -> tuple[tuple[str, ...], tuple[str, ...]]:
    assert not smc, "the OCA ROM does not support manifest-selected SMC staging"
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
        _OTHER_PAYLOAD_REFUSALS
        + _PLACEMENT_REFUSALS
        + (
            "MANIFEST_BACKUP",
            _BACKUP_SRC,
            "MANIFEST_ERR=",
            "PAYLOAD_TOO_LARGE",
        ),
    )


def refused_markers() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        (
            "MANIFEST_PRIMARY",
            _PRIMARY_SRC,
            _LOC_FAIL,
            f"MANIFEST_ERR=0x{ERR_PAYLOAD_LOCATION:08x}",
            "MANIFEST_BACKUP",
            _BACKUP_SRC,
            "MANIFEST_OK",
            f"OCA_BODY=0x{mm.BODY_SIZE:08x}",
            "PAYLOAD_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        ),
        _TRANSPORT_REFUSALS + _PLACEMENT_REFUSALS + ("PAYLOAD_TOO_LARGE",),
    )


def _served_intervals(flash) -> list[tuple[int, int]]:
    spans = []
    for txn in ev.reads(flash.get_transactions()):
        start, end = ev.read_span(txn)
        if end > start:
            spans.append((start, end))
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
    # SMC staging is not supported; a member that sets this fails before the run.
    stage_in_smc = False

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        oc.assert_known(tuple(cls.required_markers) + tuple(cls.forbidden_markers), cls.__name__)

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
            "the OCA ROM does not support manifest-selected SMC staging; this "
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
        attempts = oc.split_attempts(console)
        assert [a.src for a in attempts] == [mm.PRIMARY_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a.src) for a in attempts]}, expected the primary "
            f"only: the repacked primary must be accepted on its first read"
        )
        oc.assert_attempt(
            attempts[0],
            error=None,
            stage="accepted",
            ordered=_SIGNED_ACCEPT + _BOOTED,
            absent=_OTHER_PAYLOAD_REFUSALS + _PLACEMENT_REFUSALS + ("PAYLOAD_TOO_LARGE",),
        )
        self.logger.info(
            "CHK-SIZE-ACCEPTED PASS: the primary was accepted after %s, so %d bytes is inside "
            "the fixed SEP-SRAM staging bound",
            " -> ".join(_SIGNED_ACCEPT + _BOOTED),
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
        assert payload_offset + self.payload_bytes > _SLOT_WINDOW_SPAN, (
            f"payload_offset 0x{payload_offset:x} + {self.payload_bytes} bytes ends inside "
            f"the 0x{_SLOT_WINDOW_SPAN:x}-byte primary slot window, so the location check "
            f"would pass and the slot could boot"
        )
        # The ROM issues the payload read with 32-bit flash addresses.
        assert self.payload_bytes <= 0xFFFF_FFFF - payload_offset, (
            f"payload_offset 0x{payload_offset:x} + {self.payload_bytes} bytes "
            f"overflows 32 bits, so the refusal would no longer be attributable to "
            f"the slot window alone"
        )
        assert pm.spec_rule_violations(buf, "primary") == [], (
            "the shipped primary breaks a TOC rule"
        )
        was = pm.declare_payload_length(buf, "primary", self.payload_bytes)
        self._select_destination(buf)
        rules = pm.spec_rule_violations(buf, "primary")
        assert rules == ["toc_plen_mismatch"], (
            f"the over-declared primary breaks TOC rules {rules}; only the TOC length "
            f"mismatch, which the ROM checks after the location, may follow from the new length"
        )
        assert mm.manifest_hash(buf, "primary") == mm.signed_region_hash(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self._backup_payload_bytes = pm.manifest_payload_length(buf, "backup")
        self._src = self._payload_src(buf)
        self.logger.info(
            "CHK-STIMULUS-PAYLOAD-SIZE: primary payload_length %d -> %d (0x%x), "
            "which is %d bytes past the %d-byte fixed OCA staging capacity and ends "
            "%d bytes past the 0x%x-byte slot window; flash payload_offset remains 0x%x, "
            "the slot is re-signed and the backup keeps %d",
            was,
            self.payload_bytes,
            self.payload_bytes,
            self.payload_bytes - capacity,
            capacity,
            payload_offset + self.payload_bytes - _SLOT_WINDOW_SPAN,
            _SLOT_WINDOW_SPAN,
            payload_offset,
            self._backup_payload_bytes,
        )
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        err = f"MANIFEST_ERR=0x{ERR_PAYLOAD_LOCATION:08x}"
        attempts = oc.split_attempts(console)
        srcs = [a.src for a in attempts]
        assert srcs == [mm.PRIMARY_MANIFEST_OFFSET, mm.BACKUP_MANIFEST_OFFSET], (
            f"slot attempts read {[hex(a) for a in srcs]}, expected the primary then the "
            f"backup. Console: {console}"
        )
        primary, backup = attempts
        # The payload must lie within its slot window (rom.adoc Flash Layout).
        p_ordered = _SIGNED_ACCEPT + (_LOC_FAIL, err)
        oc.assert_attempt(
            primary,
            error=ERR_PAYLOAD_LOCATION,
            stage="payload",
            ordered=p_ordered,
            absent=_TRANSPORT_REFUSALS + _PLACEMENT_REFUSALS + ("PAYLOAD_OK", "PAYLOAD_TOO_LARGE"),
        )
        tail = [line for _, line in primary.markers][-2:]
        assert oc.count(tail[:1], _LOC_FAIL) == 1, (
            f"{_LOC_FAIL} is not the line before the primary's error (attempt ends "
            f"{tail}): a later check refused the slot, not the slot window"
        )
        b_ordered = _SIGNED_ACCEPT + _BOOTED
        oc.assert_attempt(
            backup,
            error=None,
            stage="accepted",
            ordered=b_ordered,
            absent=_OTHER_PAYLOAD_REFUSALS + _PLACEMENT_REFUSALS + ("PAYLOAD_TOO_LARGE",),
        )
        i_ph = fd.first_index(console, "MANIFEST_PRIMARY")
        i_bh = fd.first_index(console, "MANIFEST_BACKUP")
        assert 0 <= i_ph < primary.first and primary.last < i_bh < backup.first, (
            f"slot headers MANIFEST_PRIMARY@{i_ph} / MANIFEST_BACKUP@{i_bh} do not bracket "
            f"the attempts {primary.first}-{primary.last} / {backup.first}"
        )
        for marker, want in ((_RSA_EXEC, 2), (_RSA_OK, 2), ("MANIFEST_ERR=", 1)):
            n = oc.count(console, marker)
            assert n == want, f"{marker} appeared {n} times, expected {want}. Console: {console}"
        self.logger.info(
            "CHK-SIZE-REFUSED PASS: primary@%d-%d refused %s after %s; backup@%d-%d accepted "
            "after %s -- the primary payload past its slot window was refused before "
            "staging and the backup booted",
            primary.first,
            primary.last,
            err,
            " -> ".join(p_ordered),
            backup.first,
            backup.last,
            " -> ".join(b_ordered),
        )
        fd.assert_no_read_starting_at(
            self.logger,
            flash,
            self._src,
            "the primary declared a payload that ends past its slot window, so the "
            "location check must refuse the slot before the payload fetch is ever issued",
        )
