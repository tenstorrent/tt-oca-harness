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

import dv_env
import pytest
from sepvp import paths
from sepvp.config import SimConfig
from sepvp.harness import SEP_STATUS_ERROR_RE

pytestmark = pytest.mark.bootcode

TIMEOUT = 180

mm = dv_env.load("sep_manifest_mutate")
shared = dv_env.load("sep_secure_boot_cases")

CONFIGS = paths.OCAH_ROOT / "hw/sys/sep/dv/tb/efuse_preloads/efuse_configurations"
PROD = CONFIGS / "sep_efuse_lc_prod.toml"
TEST_DEV_SIP_LOCK = CONFIGS / "sep_efuse_lc_test_dev_chiplet_dbg_sip.toml"
RMA_SIP_SIP_LOCK = CONFIGS / "sep_efuse_lc_rma_sip_chiplet_dbg_sip.toml"
RMA_SIP_SYS_LOCK = CONFIGS / "sep_efuse_lc_rma_sip_chiplet_dbg_sys.toml"
RMA_SIP_OPEN = CONFIGS / "sep_efuse_lc_rma_sip.toml"
RMA_CHIPLET_SIP_LOCK = CONFIGS / "sep_efuse_lc_rma_chiplet_chiplet_dbg_sip.toml"

UNSIGNED_ERR = mm.boot_err("OCA_FAIL_SIGNATURE_CLASS_CONTROL")


def _both_slots(raw, case):
    """Apply the case to both slots, so the retry loop exhausts on the planted defect."""
    buf = bytearray(raw)
    for slot in ("primary", "backup"):
        case.mutate(buf, slot)
    return bytes(buf)


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

# (shared case, per-slot console markers in order, markers that must not appear before
#  the verdict). The mutation, MANIFEST_ERR code and terminal SEP_MSG come from the case.
MISSING_FIELD_CASES = [
    (
        # Enforced bit clear, classic class named, no key: the class satisfies the
        # determination, so the ROM's own key callback is what refuses it.
        "class_only",
        ("PUBK_NO_SIGNATURE",),
        ("PUBK_SEL=", "PUBK_AUTHORIZED", "RSA_EXEC"),
    ),
    # Enforced bit clear on a manifest still carrying its signing fields.
    ("flag_cleared_signed", (), ("PUBK_SEL=", "RSA_EXEC")),
    ("signature_absent", (), ("PUBK_SEL=", "RSA_EXEC")),
    (
        # 0^e mod n is 0, so the modexp leaves inout unchanged.
        "signature_zeroed",
        ("PUBK_AUTHORIZED", "RSA_EXEC", "RSA_INOUT_UNCHANGED"),
        ("RSA_PKCS1_FAIL", "RSA_VERIFY_OK"),
    ),
    ("public_key_absent", (), ("PUBK_SEL=", "RSA_EXEC")),
    ("public_key_zeroed", ("PUBK_SEL=", "PUBK_UNAUTHORIZED"), ("PUBK_AUTHORIZED", "RSA_EXEC")),
]


@pytest.mark.parametrize(
    "case,per_slot,forbidden", MISSING_FIELD_CASES, ids=[c[0] for c in MISSING_FIELD_CASES]
)
def test_prod_refuses_manifest_missing_secure_boot_field(
    vp, bootcode_elf, oca_images, tmp_path, case, per_slot, forbidden
):
    """PROD refuses a signed image with one secure-boot field removed from both slots."""
    shared_case = shared.CASES[case]
    img = tmp_path / f"{case}.bin"
    img.write_bytes(_both_slots(oca_images["signed"].read_bytes(), shared_case))
    t = _run(vp, bootcode_elf, img, PROD, f"oca_sb_{case}")
    _expect_posture(t, "PROD", debug_locked=False)
    _expect_refused(t, per_slot, shared_case.boot_error, shared_case.status_name, forbidden)
    t.close()


# --- chiplet debug lock in TEST_DEV and RMA_SiP ------------------------------

DEBUG_LOCK_CASES = [
    ("test_dev_sip_dis", "TEST_DEV", TEST_DEV_SIP_LOCK),
    ("rma_sip_sip_dis", "RMA_SIP", RMA_SIP_SIP_LOCK),
    ("rma_sip_sys_dis", "RMA_SIP", RMA_SIP_SYS_LOCK),
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
        UNSIGNED_ERR,
        mm.rom_status_name_for_result(UNSIGNED_ERR),
        ("SBOOT_OFF", "MANIFEST_OK", "PUBK_SEL="),
    )
    t.close()


def test_debug_locked_rma_sip_part_boots_signed(vp, bootcode_elf, oca_images):
    """Enforcement on a debug-locked RMA_SiP part still admits a validly signed image."""
    t = _run(
        vp,
        bootcode_elf,
        oca_images["signed"],
        RMA_SIP_SIP_LOCK,
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
    ("rma_sip_debug_open", "RMA_SIP", RMA_SIP_OPEN, False),
    # The lock is read and reported, and RMA_CHIPLET does not apply it.
    ("rma_chiplet_debug_locked", "RMA_CHIPLET", RMA_CHIPLET_SIP_LOCK, True),
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
