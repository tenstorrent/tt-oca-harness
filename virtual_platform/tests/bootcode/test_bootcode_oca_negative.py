# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""OCA boot-manifest rejection cases on sep-vp, asserted via the SEP_STATUS stream.

Each case tampers with a copy of a real packed image and asserts which check
refused it. The point is not that the ROM fails -- it is that it fails for the
stated reason, because the OCA validator's result codes are mapped one-for-one
onto SEP_MSG_* and a case that reported MANIFEST_LOAD_FAILED for everything would
prove nothing about which check ran.

Why these cases need no re-signing
----------------------------------
Two properties make byte-poking a signed image meaningful:

* Framing checks (magic, trailer, length) and the manifest hash run BEFORE the
  signature, so breaking them is reported without the signature ever mattering.
* `payload_offset` lives in the manifest's UNSIGNED tail (offset 3748, past the
  signed region's 3172), so it can be moved on a validly signed manifest. That is
  exactly the field an attacker controls on a genuine image, which is why the
  library bounds-checks it against the caller's permitted region.

oca_layout.py asserts the second property against the producer's own constants,
so this suite fails loudly rather than silently weakening if the format moves it.
"""

import struct

import oca_layout as L
import pytest
import shared
from sepvp.config import SimConfig

pytestmark = pytest.mark.bootcode

TIMEOUT = 180


# --- tamper helpers --------------------------------------------------------
#
# Each takes the whole SPI image and returns a tampered copy. They edit the
# PRIMARY slot only; the backup stays valid, so a case that expects a hard
# failure is also asserting the ROM did not quietly boot the backup instead.


def _both_slots(raw, fn):
    """Apply fn to both slots, for cases that must exhaust the retry loop."""
    b = bytearray(raw)
    for base in (L.PRIMARY_OFFSET, L.BACKUP_OFFSET):
        fn(b, base)
    return bytes(b)


def _primary_only(raw, fn):
    b = bytearray(raw)
    fn(b, L.PRIMARY_OFFSET)
    return bytes(b)


def _craft_bad_magic(raw):
    def f(b, base):
        b[base + L.OFF_MAGIC : base + L.OFF_MAGIC + 4] = b"XXXX"

    return _both_slots(raw, f)


def _craft_pqc_magic(raw):
    # A well-formed classic body claiming to be the PQC variant. Rejected as
    # OCA_FAIL_TRAILER, not a length failure: once the magic selects OCAP the
    # trailer is looked for at the PQC offset with the PQC marker, and neither is
    # there. Both map to SEP_MSG_INVALID_MANIFEST_ID -- the status stream cannot
    # tell magic from trailer, but MANIFEST_ERR carries the distinct
    # oca_result_t in its low byte for anyone who needs to.
    def f(b, base):
        b[base + L.OFF_MAGIC : base + L.OFF_MAGIC + 4] = L.OCAP_MAGIC

    return _both_slots(raw, f)


def _craft_bad_trailer(raw):
    def f(b, base):
        b[base + L.OFF_TRAILER] ^= 0xFF

    return _both_slots(raw, f)


def _craft_bad_manifest_length(raw):
    # manifest_length sits inside the signed region, but framing is checked
    # before integrity -- oca_check_manifest_length() runs ahead of
    # oca_check_manifest_hash() -- so the reported verdict is the length, not the
    # broken hash that also results.
    def f(b, base):
        struct.pack_into("<I", b, base + L.OFF_MANIFEST_LENGTH, L.BODY_SIZE + 16)

    return _both_slots(raw, f)


def _craft_hash_tamper(raw):
    # A byte inside the signed region. Breaks manifest_hash, which is checked
    # before anything reads a field out of the body.
    def f(b, base):
        b[base + L.SIGNED_REGION_BYTE] ^= 0xFF

    return _both_slots(raw, f)


def _craft_payload_offset_outside_region(raw):
    # payload_offset is in the unsigned tail, so this survives the signature and
    # is caught by the bounds check instead. Far enough out to land beyond the
    # flash region the slot is allowed to reach.
    def f(b, base):
        struct.pack_into("<q", b, base + L.OFF_PAYLOAD_OFFSET, 0x40000000)

    return _both_slots(raw, f)


def _craft_payload_offset_negative(raw):
    # Signed field, so a negative offset is representable and has to be rejected
    # rather than wrapping into a huge unsigned read.
    #
    # Big enough to be negative from BOTH slots. A smaller value like -0x10000 is
    # out of range from the primary at 0x1000 but resolves to 0x31000 from the
    # backup at 0x41000 -- still in region, so that slot reads real flash and
    # fails the payload hash instead. Since last_err reflects the final attempt,
    # the case would then assert the wrong check.
    def f(b, base):
        struct.pack_into("<q", b, base + L.OFF_PAYLOAD_OFFSET, -0x100000)

    return _both_slots(raw, f)


def _craft_revoke_selected_key(raw):
    # Revoke bit 0, which is the slot public_key_select_classic names. The
    # revocation bitmap is inside the signed region, so this also breaks the
    # manifest hash -- which is fine and is the point of the ordering: integrity
    # is settled first, so the reported failure is the hash, not the revocation.
    # The device-side revocation path is covered by test_revoked_key_fuse below.
    def f(b, base):
        b[base + L.OFF_REVOKE] |= 0x01

    return _both_slots(raw, f)


def _craft_toc_image_count_overflow(raw):
    # Claim more images than the TOC span can hold. Edits the payload, so the
    # payload hash catches it first on a signed image; the assertion is that a
    # structurally impossible TOC never reaches the handoff.
    def f(b, base):
        payload = base + 0x1000  # image layout: payload one body on
        struct.pack_into("<Q", b, payload + 16, 0xFFFF)

    return _both_slots(raw, f)


def _craft_rotate_to_backup(raw):
    # Corrupt the primary's magic only. The ROM must fall through to the backup
    # slot and boot it, which is the retry loop's whole purpose.
    def f(b, base):
        b[base + L.OFF_MAGIC : base + L.OFF_MAGIC + 4] = b"XXXX"

    return _primary_only(raw, f)


# (id, crafter, expected SEP_MSG, status type)
CASES = [
    ("bad_magic", _craft_bad_magic, "SEP_MSG_INVALID_MANIFEST_ID", "ERROR"),
    ("pqc_magic", _craft_pqc_magic, "SEP_MSG_INVALID_MANIFEST_ID", "ERROR"),
    ("bad_trailer", _craft_bad_trailer, "SEP_MSG_INVALID_MANIFEST_ID", "ERROR"),
    ("bad_manifest_len", _craft_bad_manifest_length, "SEP_MSG_INVALID_MANIFEST_LENGTH", "ERROR"),
    ("hash_tamper", _craft_hash_tamper, "SEP_MSG_INVALID_MANIFEST_HASH", "ERROR"),
    (
        "payload_outside",
        _craft_payload_offset_outside_region,
        "SEP_MSG_PAYLOAD_INVALID_LOCATION_FLASH",
        "ERROR",
    ),
    (
        "payload_negative",
        _craft_payload_offset_negative,
        "SEP_MSG_PAYLOAD_INVALID_LOCATION_FLASH",
        "ERROR",
    ),
    ("revoked_in_manifest", _craft_revoke_selected_key, "SEP_MSG_INVALID_MANIFEST_HASH", "ERROR"),
    (
        "toc_count_overflow",
        _craft_toc_image_count_overflow,
        "SEP_MSG_PAYLOAD_HASH_INVALID",
        "ERROR",
    ),
]


@pytest.mark.parametrize("case,craft,expect_msg,expect_type", CASES, ids=[c[0] for c in CASES])
def test_oca_manifest_negative(
    vp, bootcode_elf, oca_images, tmp_path, case, craft, expect_msg, expect_type
):
    """A tampered OCA image is refused, and by the check the case names."""
    raw = oca_images["signed"].read_bytes()
    img = tmp_path / "tampered.bin"
    img.write_bytes(craft(raw))

    # Run dir is keyed on the CASE, not the expected message: several cases share
    # an expected message, and a shared name means each run wipes the previous
    # one's logs and none of them can be diagnosed afterwards.
    t = vp(
        SimConfig(
            name=f"oca_neg_{case}",
            elf=str(bootcode_elf),
            flash_image=str(img),
            boot="primary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    match = t.expect_status(expect_msg, type=expect_type, timeout=TIMEOUT)
    if expect_type == "ERROR":
        assert "ERROR" in match.group(0)
    t.close()


def test_rotate_to_backup(vp, bootcode_elf, oca_images, tmp_path):
    """Primary corrupted -> the ROM falls through to the backup slot and boots."""
    img = tmp_path / "primary_bad.bin"
    img.write_bytes(_craft_rotate_to_backup(oca_images["signed"].read_bytes()))

    t = vp(
        SimConfig(
            name="oca_rotate_backup",
            elf=str(bootcode_elf),
            flash_image=str(img),
            boot="primary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    shared.expect_common_early(t, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


def test_revoked_key_fuse(vp, bootcode_elf, oca_images):
    """A device-revoked ROOT key is refused on an otherwise valid signed image.

    The manifest is untouched, so this exercises the DEVICE side of revocation --
    CHIPLET_PUBK_REVOKE -- which the in-manifest case cannot reach without also
    breaking the manifest hash.
    """
    t = vp(
        SimConfig(
            name="oca_revoked_fuse",
            elf=str(bootcode_elf),
            flash_image=str(oca_images["signed"]),
            otp="tests/fuse_maps/oca_key_revoked.yaml",
            boot="primary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    match = t.expect_status("SEP_MSG_REVOKED_KEY", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()


def test_security_version_rollback(vp, bootcode_elf, oca_images):
    """A manifest missing a security-version flag the device has recorded is a rollback.

    The check is `manifest & device == device`, so a device with a bit the
    manifest lacks rejects it. The image's manifest_security_version is zero, so
    any device bit at all is a rollback.
    """
    t = vp(
        SimConfig(
            name="oca_rollback",
            elf=str(bootcode_elf),
            flash_image=str(oca_images["signed"]),
            otp="tests/fuse_maps/oca_secver_set.yaml",
            boot="primary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    match = t.expect_status("SEP_MSG_INVALID_SECURITY_VERSION", type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)
    t.close()
