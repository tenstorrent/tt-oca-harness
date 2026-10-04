# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Secure-boot policy on sep-vp: who can force verification, and what an incomplete
manifest gets on a part that requires it.

The VP counterparts of the rom_fw DV members of the same names, for the purely logical
parts of SEP-ROM-SB-010/-025: the decision is made from fuse shadows and manifest bytes,
so a functional model reaches the same verdict as the RTL in seconds rather than hours.

Two groups:

* **Missing secure-boot fields on PROD.** A signed image with one field removed from
  both slots -- the enable flag, the signature, or the public key -- is refused, and by
  the check each case names. Mirrors ``sep_firmware_*_refuse_test``.
* **The chiplet debug lock in TEST_DEV and RMA_SiP.** ``CHIPLET_DBG`` in ``SIP_DIS``
  or ``SYS_DIS`` makes the part refuse an unsigned image and still boot a signed one;
  with debug open, or in RMA_CHIPLET whatever the lock, the unsigned image boots.
  Mirrors ``sep_rom_rma_*_test`` and ``sep_rom_dbg_lock_sip_dis_refuse_test``.

Every case first asserts the ROM's own ``LC=`` and ``FUSE: CHIPLET_DBG_DIS:`` lines, so a
fuse map the model did not apply fails here rather than passing for another reason.
"""

import hashlib

import oca_layout as L
import pytest
from sepvp.config import SimConfig
from sepvp.harness import SEP_STATUS_ERROR_RE

pytestmark = pytest.mark.bootcode

TIMEOUT = 180

C = L.C
OFF_SECURE_BOOT_CONTROL = C.OFF_SECURE_BOOT_CONTROL
OFF_SIGNATURE = C.OFF_SIGNATURE_CLASSIC
LEN_SIGNATURE = C.SIGNATURE_CLASSIC_SIZE
OFF_SIGNATURE_SIZE = C.OFF_SIGNATURE_SIZE_CLASSIC
OFF_PUBLIC_KEY = C.OFF_PUBLIC_KEY_CLASSIC
LEN_PUBLIC_KEY = C.PUBLIC_KEY_CLASSIC_SIZE
OFF_PUBLIC_KEY_SIZE = C.OFF_PUBLIC_KEY_SIZE_CLASSIC
OFF_PUBLIC_KEY_SELECT = C.OFF_PUBLIC_KEY_SELECT_CLASSIC
LEN_PUBLIC_KEY_SELECT = 16
# Zeroed alongside the key material when a manifest declares itself non-secure;
# the invariant refuses any of them non-zero on such a manifest.
CRYPTO_BYTE_FIELDS = (
    C.OFF_SIGNATURE_TYPE_CLASSIC,
    C.OFF_SIGNATURE_ENCODING_CLASSIC,
    C.OFF_PUBLIC_KEY_ENCODING_CLASSIC,
)
ENFORCED_BIT = 0x01
CLASSIC_BIT = 0x02


# --- manifest editing --------------------------------------------------------


def _hash_field(b, base):
    """manifest_hash as the packer writes it: SHA-256 of the signed region, zero-padded."""
    digest = hashlib.sha256(bytes(b[base : base + L.SIGNED_REGION_END])).digest()
    return digest + bytes(C.HASH_FIELD_SIZE - len(digest))


def _stored_hash(b, base):
    off = base + C.OFF_MANIFEST_HASH
    return bytes(b[off : off + C.HASH_FIELD_SIZE])


def _rehash(b, base):
    off = base + C.OFF_MANIFEST_HASH
    b[off : off + C.HASH_FIELD_SIZE] = _hash_field(b, base)


def _zero(b, base, off, length):
    b[base + off : base + off + length] = bytes(length)


def _both_slots(raw, fn):
    """Apply fn to both slots, so the retry loop exhausts on the planted defect."""
    b = bytearray(raw)
    for base in (L.PRIMARY_OFFSET, L.BACKUP_OFFSET):
        assert _stored_hash(b, base) == _hash_field(b, base), (
            f"slot at {base:#x}: recomputing manifest_hash does not reproduce the "
            f"packer's value, so the edits below would be refused for a broken hash"
        )
        assert b[base + OFF_SECURE_BOOT_CONTROL] == ENFORCED_BIT | CLASSIC_BIT, (
            f"slot at {base:#x} is not the signed classic image these cases assume"
        )
        fn(b, base)
        _rehash(b, base)
    return bytes(b)


def _strip_signing(b, base):
    """What the packer emits for secure_boot: 0 -- no signature, key or selector."""
    _zero(b, base, OFF_SIGNATURE, LEN_SIGNATURE)
    _zero(b, base, OFF_PUBLIC_KEY, LEN_PUBLIC_KEY)
    _zero(b, base, OFF_PUBLIC_KEY_SELECT, LEN_PUBLIC_KEY_SELECT)
    for off in CRYPTO_BYTE_FIELDS:
        b[base + off] = 0


def _class_only(b, base):
    _strip_signing(b, base)
    b[base + OFF_SECURE_BOOT_CONTROL] = CLASSIC_BIT


def _flag_cleared_signed(b, base):
    b[base + OFF_SECURE_BOOT_CONTROL] &= ~ENFORCED_BIT


def _signature_absent(b, base):
    _zero(b, base, OFF_SIGNATURE, LEN_SIGNATURE)
    _zero(b, base, OFF_SIGNATURE_SIZE, 2)


def _signature_zeroed(b, base):
    _zero(b, base, OFF_SIGNATURE, LEN_SIGNATURE)


def _public_key_absent(b, base):
    _zero(b, base, OFF_PUBLIC_KEY, LEN_PUBLIC_KEY)
    _zero(b, base, OFF_PUBLIC_KEY_SIZE, 2)


def _public_key_zeroed(b, base):
    _zero(b, base, OFF_PUBLIC_KEY, LEN_PUBLIC_KEY)


def _run(vp, elf, image, otp, name):
    t = vp(
        SimConfig(
            name=name,
            elf=str(elf),
            flash_image=str(image),
            otp=otp,
            boot="primary",
            boot_timeout=TIMEOUT,
        )
    )
    t.spawn()
    return t


def _expect_posture(t, lc, debug_locked):
    """The lifecycle and debug lock as the ROM itself resolved them at [S11]/[S18]."""
    t.expect(rf"LC={lc}\b", timeout=TIMEOUT)
    t.expect(rf"FUSE: CHIPLET_DBG_DIS: {int(debug_locked)}\b", timeout=TIMEOUT)


def _expect_refused(t, per_slot, code, sep_msg, forbidden):
    """Both slots refused with the planted verdict, then the terminal ERROR.

    expect() consumes the stream, so the per-slot markers are matched in order once
    per slot: each slot must have reached the same check.
    """
    errors = [SEP_STATUS_ERROR_RE, *forbidden]
    for _slot in ("primary", "backup"):
        for marker in per_slot:
            t.expect(marker, error_patterns=errors, timeout=TIMEOUT)
        t.expect(rf"MANIFEST_ERR=0x{code:08x}", error_patterns=errors, timeout=TIMEOUT)
    match = t.expect_status(sep_msg, type="ERROR", timeout=TIMEOUT)
    assert "ERROR" in match.group(0)


# --- missing secure-boot fields on PROD ---------------------------------------

# (id, mutation, per-slot console markers in order, MANIFEST_ERR code, terminal SEP_MSG,
#  markers that must not appear before the verdict)
MISSING_FIELD_CASES = [
    (
        # Enforced bit clear, classic class named, no key: the class satisfies the
        # determination, so the ROM's own key callback is what refuses it.
        "class_only",
        _class_only,
        ("PUBK_NO_SIGNATURE",),
        0x0003_0023,
        "SEP_MSG_INVALID_KEY_HASH",
        ("PUBK_SEL=", "PUBK_AUTHORIZED", "RSA_EXEC"),
    ),
    (
        # Enforced bit clear on a manifest still carrying its signing fields.
        "flag_cleared_signed",
        _flag_cleared_signed,
        (),
        0x0003_0006,
        "SEP_MSG_MANIFEST_SECURE_BOOT",
        ("PUBK_SEL=", "RSA_EXEC"),
    ),
    (
        "signature_absent",
        _signature_absent,
        (),
        0x0003_0022,
        "SEP_MSG_INVALID_SIGNATURE_TYPE",
        ("PUBK_SEL=", "RSA_EXEC"),
    ),
    (
        # 0^e mod n is 0, so the modexp leaves inout unchanged.
        "signature_zeroed",
        _signature_zeroed,
        ("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_INOUT_UNCHANGED"),
        0x0003_000E,
        "SEP_MSG_INVALID_SIGNATURE",
        ("RSA_PKCS1_FAIL", "RSA_VERIFY_OK"),
    ),
    (
        "public_key_absent",
        _public_key_absent,
        (),
        0x0003_0022,
        "SEP_MSG_INVALID_SIGNATURE_TYPE",
        ("PUBK_SEL=", "RSA_EXEC"),
    ),
    (
        "public_key_zeroed",
        _public_key_zeroed,
        ("PUBK_SEL=", "PUBK_UNAUTHORIZED"),
        0x0003_0023,
        "SEP_MSG_INVALID_KEY_HASH",
        ("PUBK_AUTHORIZED", "RSA_EXEC"),
    ),
]


@pytest.mark.parametrize(
    "case,mutate,per_slot,code,sep_msg,forbidden",
    MISSING_FIELD_CASES,
    ids=[c[0] for c in MISSING_FIELD_CASES],
)
def test_prod_refuses_manifest_missing_secure_boot_field(
    vp, bootcode_elf, oca_images, tmp_path, case, mutate, per_slot, code, sep_msg, forbidden
):
    """PROD refuses a signed image with one secure-boot field removed from both slots."""
    img = tmp_path / f"{case}.bin"
    img.write_bytes(_both_slots(oca_images["signed"].read_bytes(), mutate))
    t = _run(vp, bootcode_elf, img, "tests/fuse_maps/prod_secure.yaml", f"oca_sb_{case}")
    _expect_posture(t, "PROD", debug_locked=False)
    _expect_refused(t, per_slot, code, sep_msg, forbidden)
    t.close()


# --- chiplet debug lock in TEST_DEV and RMA_SiP ------------------------------

DEBUG_LOCK_CASES = [
    ("test_dev_sip_dis", "TEST_DEV", "tests/fuse_maps/test_dev_dbg_lock_sip.yaml"),
    ("rma_sip_sip_dis", "RMA_SIP", "tests/fuse_maps/rma_sip_dbg_lock_sip.yaml"),
    ("rma_sip_sys_dis", "RMA_SIP", "tests/fuse_maps/rma_sip_dbg_lock_sys.yaml"),
]


@pytest.mark.parametrize("case,lc,otp", DEBUG_LOCK_CASES, ids=[c[0] for c in DEBUG_LOCK_CASES])
def test_debug_locked_part_refuses_unsigned(vp, bootcode_elf, oca_images, case, lc, otp):
    """A debug-locked TEST_DEV or RMA_SiP part refuses an image that does not ask to be signed.

    The unsigned image names no signature class, so with secure boot in force the
    determination refuses both slots with OCA_FAIL_SIGNATURE_CLASS_CONTROL.
    """
    t = _run(vp, bootcode_elf, oca_images["unsigned"], otp, f"oca_dbg_lock_{case}")
    _expect_posture(t, lc, debug_locked=True)
    t.expect_status("SEP_MSG_SBOOT_DBG_LOCK", type="INFO", timeout=TIMEOUT)
    _expect_refused(
        t,
        (),
        0x0003_0024,
        "SEP_MSG_MANIFEST_SECURE_BOOT",
        ("SBOOT_OFF", "MANIFEST_OK", "PUBK_SEL="),
    )
    t.close()


def test_debug_locked_rma_sip_part_boots_signed(vp, bootcode_elf, oca_images):
    """Enforcement on a debug-locked RMA_SiP part still admits a validly signed image."""
    t = _run(
        vp,
        bootcode_elf,
        oca_images["signed"],
        "tests/fuse_maps/rma_sip_dbg_lock_sip.yaml",
        "oca_dbg_lock_rma_sip_signed",
    )
    _expect_posture(t, "RMA_SIP", debug_locked=True)
    t.expect_status("SEP_MSG_SBOOT_DBG_LOCK", type="INFO", timeout=TIMEOUT)
    t.expect("PUBK_AUTHORIZED", timeout=TIMEOUT)
    t.expect("RSA_VERIFY_OK", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_MANIFEST_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()


# (id, LC, fuse map, debug lock as the ROM must report it)
UNSIGNED_BOOT_CASES = [
    # The negative control for the refusals above: without it they could be the RMA
    # lifecycle refusing every unsigned image rather than the debug lock.
    ("rma_sip_debug_open", "RMA_SIP", "tests/fuse_maps/rma_sip_dbg_open.yaml", False),
    # The lock is read and reported, and RMA_CHIPLET does not apply it.
    (
        "rma_chiplet_debug_locked",
        "RMA_CHIPLET",
        "tests/fuse_maps/rma_chiplet_dbg_lock_sip.yaml",
        True,
    ),
]


@pytest.mark.parametrize(
    "case,lc,otp,debug_locked", UNSIGNED_BOOT_CASES, ids=[c[0] for c in UNSIGNED_BOOT_CASES]
)
def test_manifest_optional_rma_part_boots_unsigned(
    vp, bootcode_elf, oca_images, case, lc, otp, debug_locked
):
    """An RMA part the debug lock does not govern boots an unsigned image unverified."""
    t = _run(vp, bootcode_elf, oca_images["unsigned"], otp, f"oca_unsigned_{case}")
    _expect_posture(t, lc, debug_locked=debug_locked)
    errors = [SEP_STATUS_ERROR_RE, "SBOOT_DBG_LOCK"]
    t.expect_status("SEP_MSG_MANIFEST_VALIDATED", type="INFO", timeout=TIMEOUT)
    t.expect("SBOOT_OFF", error_patterns=errors, timeout=TIMEOUT)
    t.expect_status("SEP_MSG_STARTING_BL1", type="INFO", timeout=TIMEOUT)
    t.close()
