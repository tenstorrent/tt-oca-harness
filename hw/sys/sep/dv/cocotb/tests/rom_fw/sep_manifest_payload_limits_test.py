# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both slots declare a payload field past the 32-bit boundary; the ROM halts.

The ROM reads the payload with a 32-bit address and span, so a field k * 2^32 from the sealed
value reads a valid payload unless ``oca_locate_payload()``'s int64 range checks refuse it.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from env import sep_oca_console as oc
from env import sep_payload_mutate as pm
from env.sep_seeded_rng import SepSeededRng
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import err_marker, sep_backup_payload_fail_base

_ERR_PAYLOAD_LOCATION = mm.boot_err("OCA_FAIL_PAYLOAD_LOCATION")
_LOC_FAIL = "PAYLOAD_LOC_FAIL"

_INT64_MAX = (1 << 63) - 1
_INT64_MIN = -(1 << 63)
_WORD = 1 << 32
_LOW32 = _WORD - 1
_SLOT_STRIDE = mm.BACKUP_MANIFEST_OFFSET - mm.PRIMARY_MANIFEST_OFFSET
_WINDOW_SPAN = _SLOT_STRIDE - mm.PRIMARY_MANIFEST_OFFSET
# Multiples of 2^32 that keep the field inside int64, so the region bound is what refuses it.
_PRIMARY_WRAPS = (1, 0x7FFF_FFFF)
_BACKUP_WRAPS = (1, -1, 0x7FFF_FFFF, -0x8000_0000)


def locate_arm(buf, slot: str) -> str:
    assert not pm.is_encrypted(buf, slot), f"{slot} is encrypted; the span model is cleartext"
    span = pm.manifest_payload_length(buf, slot)
    at = mm.slot_base(slot) + pm.OFF_PAYLOAD_OFFSET
    offset = int.from_bytes(bytes(buf[at : at + 8]), "little", signed=True)
    base = mm.slot_base(slot)
    if span == 0:
        return "no_payload"
    if span > _INT64_MAX:
        return "span_exceeds_int64"
    if offset > 0 and base > _INT64_MAX - offset:
        return "addr_overflow"
    if offset < 0 and base < _INT64_MIN - offset:
        return "addr_underflow"
    if base + offset > _INT64_MAX - span:
        return "end_overflow"
    if base + offset < base or base + offset + span > base + _WINDOW_SPAN:
        return "region"
    return "none"


@pyuvm.test()
class sep_manifest_payload_limits_test(sep_backup_payload_fail_base):
    """Seeded 32-bit wrap or int64 overflow in each slot -> both PAYLOAD_LOC_FAIL -> halt."""

    efuse_preload = td.PLAINTEXT_EFUSE
    primary_expected_error = _ERR_PAYLOAD_LOCATION
    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    primary_ordered = (_LOC_FAIL,)
    primary_absent = ("PAYLOAD_TOO_LARGE", "FLASH_READ_OOB")
    backup_defect_marker = _LOC_FAIL
    expected_error = _ERR_PAYLOAD_LOCATION
    backup_expected_stage = "payload"

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def corrupt_primary(self, buf: bytearray) -> None:
        assert locate_arm(buf, "primary") == "none", "the shipped primary is refused by locate"
        seed = self.random_seed()
        self._rng = SepSeededRng(seed)
        self._payload_src = {"primary": pm.payload_base(buf, "primary")}
        sealed = pm.manifest_payload_length(buf, "primary")
        pool = tuple(sealed + k * _WORD for k in _PRIMARY_WRAPS) + (1 << 63,)
        length = self._rng.choice(pool)
        self._primary_wraps = length <= _INT64_MAX
        want = "region" if self._primary_wraps else "span_exceeds_int64"
        pm.declare_payload_length(buf, "primary", length)
        arm = locate_arm(buf, "primary")
        assert arm == want, f"primary payload_length 0x{length:x} reaches the {arm} arm, not {want}"
        if self._primary_wraps:
            assert length & _LOW32 == sealed, (
                f"payload_length 0x{length:x} does not truncate to the sealed {sealed}"
            )
        mm.verify_layout(buf, "primary")
        assert mm.manifest_hash(buf, "primary") == mm.signed_region_hash(buf, "primary")
        pm.verify_signing_key(buf, "primary")
        mm.verify_public_key(buf, "primary")
        self._primary_served = length.to_bytes(8, "little")
        self.logger.info(
            "CHK-STIMULUS-SPAN: seed %d drew primary payload_length 0x%x from %s (sealed "
            "0x%x), re-signed; (uint32_t) of it is 0x%x, and oca_locate_payload() must "
            "refuse it on arm %s",
            seed,
            length,
            [hex(v) for v in pool],
            sealed,
            length & _LOW32,
            arm,
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        assert locate_arm(buf, "backup") == "none", "the shipped backup is refused by locate"
        assert pm.OFF_PAYLOAD_OFFSET >= mm.SIGNED_REGION_END, (
            "payload_offset is inside the signed region; the backup would need re-signing"
        )
        pm.verify_signing_key(buf, "backup")
        base = mm.slot_base("backup")
        src = pm.payload_base(buf, "backup")
        self._payload_src["backup"] = src
        at = base + pm.OFF_PAYLOAD_OFFSET
        sealed = int.from_bytes(bytes(buf[at : at + 8]), "little", signed=True)
        pool = tuple(sealed + k * _WORD for k in _BACKUP_WRAPS)
        # At least one slot carries a 32-bit wrap.
        if self._primary_wraps:
            pool += (_INT64_MAX,)
        offset = self._rng.choice(pool)
        wraps = offset != _INT64_MAX
        want = "region" if wraps else "addr_overflow"
        self._backup_served = offset.to_bytes(8, "little", signed=True)
        buf[at : at + 8] = self._backup_served
        arm = locate_arm(buf, "backup")
        assert arm == want, f"backup payload_offset {offset:#x} reaches the {arm} arm, not {want}"
        if wraps:
            assert (base + offset) & _LOW32 == src, (
                f"payload address {base + offset:#x} does not truncate to the sealed 0x{src:x}"
            )
        assert mm.manifest_hash(buf, "backup") == mm.signed_region_hash(buf, "backup")
        pm.verify_signing_key(buf, "backup")
        mm.verify_public_key(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-OFFSET: drew backup payload_offset %d from %s (sealed %d) in the "
            "unsigned tail, signature still valid; the payload address is %#x, (uint32_t) "
            "%#x, and oca_locate_payload() must refuse it on arm %s",
            offset,
            list(pool),
            sealed,
            base + offset,
            (base + offset) & _LOW32,
            arm,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        primary = oc.split_attempts(console)[0]
        tail = [line for _, line in primary.markers][-2:]
        assert (
            len(tail) == 2
            and oc.count(tail[:1], _LOC_FAIL) == 1
            and oc.count(tail[1:], err_marker(_ERR_PAYLOAD_LOCATION)) == 1
        ), (
            f"the primary does not end {_LOC_FAIL} -> {err_marker(_ERR_PAYLOAD_LOCATION)} "
            f"(attempt ends {tail}): a later check refused it, not the location bound"
        )
        self.logger.info(
            "CHK-LOCATE-BOTH PASS: primary@%d-%d and the backup both end %s -> %s",
            primary.first,
            primary.last,
            _LOC_FAIL,
            err_marker(_ERR_PAYLOAD_LOCATION),
        )

        for slot in ("primary", "backup"):
            fd.assert_no_read_starting_at(
                self.logger,
                self._flash,
                self._payload_src[slot],
                f"the {slot} payload was refused by oca_locate_payload(), so no read "
                f"is issued at the address its field truncates to",
            )
        fd.assert_served_field(
            self.logger,
            self._flash,
            "primary",
            pm.OFF_PAYLOAD_LENGTH,
            self._primary_served,
            "primary payload_length",
        )
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            pm.OFF_PAYLOAD_OFFSET,
            self._backup_served,
            "backup payload_offset",
        )
