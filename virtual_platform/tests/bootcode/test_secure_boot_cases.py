# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""The shared secure-boot field removals, executed on a synthetic two-slot image.

Both harnesses refuse these images on the ROM, so a mutation that wrote the wrong bytes
would still be refused and still look correct there. These tests pin what each mutation
writes, and that it refuses an input it cannot start from without touching it.
"""

import dv_env
import pytest

pytestmark = pytest.mark.hostonly

mm = dv_env.load("sep_manifest_mutate")
shared = dv_env.load("sep_secure_boot_cases")
K = mm.K

CASE_NAMES = (
    "class_only",
    "flag_cleared_signed",
    "signature_absent",
    "signature_zeroed",
    "public_key_absent",
    "public_key_zeroed",
)
SLOTS = ("primary", "backup")
PAIRS = [(case, slot) for case in CASE_NAMES for slot in SLOTS]
PAIR_IDS = [f"{case}-{slot}" for case, slot in PAIRS]

SIGNED_CLASSIC = 0x03
SIGNATURE_SIZE = 384
PUBLIC_KEY_SIZE = 388

# (offset, length) of each field a case may change.
CONTROL = (mm.OFF_SECURE_BOOT_CONTROL, 1)
SIGNATURE = (mm.OFF_SIGNATURE, K.SIGNATURE_CLASSIC_SIZE)
SIGNATURE_SIZE_FIELD = (mm.OFF_SIGNATURE_SIZE, 2)
PUBLIC_KEY = (mm.OFF_PUBLIC_KEY, K.PUBLIC_KEY_CLASSIC_SIZE)
PUBLIC_KEY_SIZE_FIELD = (mm.OFF_PUBLIC_KEY_SIZE, 2)
SELECTOR = (mm.OFF_PUBLIC_KEY_SEL, mm.PUBLIC_KEY_SEL_LEN)
DESCRIPTORS = [
    (mm.OFF_SIGNATURE_TYPE, 1),
    (K.OFF_SIGNATURE_ENCODING_CLASSIC, 1),
    (mm.OFF_PUBLIC_KEY_ENCODING, 1),
]
HASH = (mm.OFF_MANIFEST_HASH, mm.HASH_FIELD_SIZE)

# case -> (fields set to zero, field values after, fields allowed to change, hash changes)
CONTRACT = {
    "class_only": (
        [SIGNATURE, PUBLIC_KEY, SELECTOR, *DESCRIPTORS],
        {
            CONTROL: 0x02,
            SIGNATURE_SIZE_FIELD: SIGNATURE_SIZE,
            PUBLIC_KEY_SIZE_FIELD: PUBLIC_KEY_SIZE,
        },
        [CONTROL, SIGNATURE, PUBLIC_KEY, SELECTOR, *DESCRIPTORS],
        True,
    ),
    "flag_cleared_signed": ([], {CONTROL: 0x02}, [CONTROL], True),
    "signature_absent": (
        [SIGNATURE],
        {SIGNATURE_SIZE_FIELD: 0},
        [SIGNATURE, SIGNATURE_SIZE_FIELD],
        True,
    ),
    "signature_zeroed": ([SIGNATURE], {SIGNATURE_SIZE_FIELD: SIGNATURE_SIZE}, [SIGNATURE], False),
    "public_key_absent": (
        [PUBLIC_KEY],
        {PUBLIC_KEY_SIZE_FIELD: 0},
        [PUBLIC_KEY, PUBLIC_KEY_SIZE_FIELD],
        True,
    ),
    "public_key_zeroed": (
        [PUBLIC_KEY],
        {PUBLIC_KEY_SIZE_FIELD: PUBLIC_KEY_SIZE},
        [PUBLIC_KEY],
        True,
    ),
}

# The second application of each case finds its own precondition false.
REAPPLIED = {
    "class_only": "secure_boot_control is 0x02",
    "flag_cleared_signed": "secure_boot_control is 0x02",
    "signature_absent": "signature_size is already zero",
    "signature_zeroed": "signature is already all zero",
    "public_key_absent": "public key is already zero",
    "public_key_zeroed": "public key is already zero",
}


def _put(buf, base, field, value):
    off, length = field
    buf[base + off : base + off + length] = value.to_bytes(length, "little")


def _get(buf, slot, field):
    off, length = field
    base = mm.slot_base(slot)
    return int.from_bytes(bytes(buf[base + off : base + off + length]), "little")


def _fixture():
    """A sealed two-slot signed classic image with every secure-boot field populated."""
    buf = bytearray(mm.BACKUP_MANIFEST_OFFSET + K.OCA_CLASSIC_BODY_SIZE)
    for slot in SLOTS:
        base = mm.slot_base(slot)
        body = bytes((index * 7 + 3) & 0xFF for index in range(K.OCA_CLASSIC_BODY_SIZE))
        buf[base : base + len(body)] = body
        buf[base : base + 4] = mm.MANIFEST_MAGIC
        _put(buf, base, CONTROL, SIGNED_CLASSIC)
        _put(buf, base, SIGNATURE, 0)
        signature = bytes(1 + (index % 255) for index in range(SIGNATURE_SIZE))
        buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + SIGNATURE_SIZE] = signature
        _put(buf, base, SIGNATURE_SIZE_FIELD, SIGNATURE_SIZE)
        _put(buf, base, PUBLIC_KEY, 0)
        modulus = bytes(0x80 | (index % 127) for index in range(mm.MODULUS_LEN))
        key = modulus + (65537).to_bytes(4, "big")
        buf[base + mm.OFF_PUBLIC_KEY : base + mm.OFF_PUBLIC_KEY + len(key)] = key
        _put(buf, base, PUBLIC_KEY_SIZE_FIELD, PUBLIC_KEY_SIZE)
        _put(buf, base, SELECTOR, 1 << mm.key_slot_for(mm.PUBK_SEL_ROM_KEY, 0))
        _put(buf, base, (mm.OFF_SIGNATURE_TYPE, 1), mm.SIG_TYPE_RSA_3072)
        _put(buf, base, (K.OFF_SIGNATURE_ENCODING_CLASSIC, 1), mm.ENCODING_RAW)
        _put(buf, base, (mm.OFF_PUBLIC_KEY_ENCODING, 1), mm.ENCODING_RAW)
        mm.rehash(buf, slot)
    return buf


FIXTURE = bytes(_fixture())


def test_fixture_starts_from_the_shipped_shape():
    for slot in SLOTS:
        mm.verify_layout(FIXTURE, slot)
        assert mm.secure_boot_control(FIXTURE, slot) == SIGNED_CLASSIC
        assert mm.signature_size(FIXTURE, slot) == SIGNATURE_SIZE
        assert mm.public_key_size(FIXTURE, slot) == PUBLIC_KEY_SIZE
        assert mm.can_anchor_public_key(FIXTURE, slot)
        assert all(mm.signature(FIXTURE, slot)[:SIGNATURE_SIZE])
        assert all(mm.public_key_modulus(FIXTURE, slot))


def _changed(before, after, base):
    return {i - base for i, (a, b) in enumerate(zip(before, after)) if a != b}


def _span(fields):
    return {off + i for off, length in fields for i in range(length)}


@pytest.mark.parametrize("case, slot", PAIRS, ids=PAIR_IDS)
def test_shared_mutation_matches_contract(case, slot):
    zeroed, values, allowed, rehashed = CONTRACT[case]
    buf = bytearray(FIXTURE)
    shared.CASES[case].mutate(buf, slot)

    mm.verify_layout(buf, slot)
    base = mm.slot_base(slot)
    assert len(buf) == len(FIXTURE)
    for field in zeroed:
        off, length = field
        assert not any(buf[base + off : base + off + length]), f"{case}: {field} not zeroed"
    for field, value in values.items():
        assert _get(buf, slot, field) == value, f"{case}: {field} is {_get(buf, slot, field)}"

    # Offsets relative to the mutated slot, so the other slot and the gap stay outside.
    changed = _changed(FIXTURE, buf, base)
    hash_span = _span([HASH])
    assert changed - hash_span <= _span(allowed), f"{case} wrote outside its fields"
    assert bool(changed & hash_span) == rehashed


@pytest.mark.parametrize("case, slot", PAIRS, ids=PAIR_IDS)
def test_stale_hash_is_rejected_without_repair(case, slot):
    buf = bytearray(FIXTURE)
    mm.corrupt_manifest_hash(buf, slot, byte_index=5)
    snapshot = bytes(buf)
    with pytest.raises(AssertionError, match="manifest_hash does not equal"):
        shared.CASES[case].mutate(buf, slot)
    assert bytes(buf) == snapshot


@pytest.mark.parametrize("case, slot", PAIRS, ids=PAIR_IDS)
def test_failed_precondition_is_rejected_without_mutation(case, slot):
    buf = bytearray(FIXTURE)
    shared.CASES[case].mutate(buf, slot)
    snapshot = bytes(buf)
    with pytest.raises(AssertionError, match=REAPPLIED[case]):
        shared.CASES[case].mutate(buf, slot)
    assert bytes(buf) == snapshot


def test_case_metadata():
    assert tuple(shared.CASES) == CASE_NAMES
    expected = {
        "class_only": ("OCA_FAIL_ROOT_KEY_UNAUTHORIZED", "SEP_MSG_INVALID_KEY_HASH"),
        "flag_cleared_signed": ("OCA_FAIL_SECURE_BOOT_INVARIANT", "SEP_MSG_MANIFEST_SECURE_BOOT"),
        "signature_absent": ("OCA_FAIL_CRYPTO_FIELD_SIZE", "SEP_MSG_INVALID_SIGNATURE_TYPE"),
        "signature_zeroed": ("OCA_FAIL_SIGNATURE", "SEP_MSG_INVALID_SIGNATURE"),
        "public_key_absent": ("OCA_FAIL_CRYPTO_FIELD_SIZE", "SEP_MSG_INVALID_SIGNATURE_TYPE"),
        "public_key_zeroed": ("OCA_FAIL_ROOT_KEY_UNAUTHORIZED", "SEP_MSG_INVALID_KEY_HASH"),
    }
    for name, case in shared.CASES.items():
        result_name, status_name = expected[name]
        assert case.name == name
        assert case.result_name == result_name
        assert case.boot_error == mm.boot_err(result_name)
        assert case.boot_error & 0xFF == mm.oca_result(result_name)
        assert case.status_name == status_name


def test_policy_cases_use_the_rtl_fuse_configurations():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).parent / "test_bootcode_oca_secure_boot_policy.py"
    spec = importlib.util.spec_from_file_location("secure_boot_policy", path)
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    used = {
        "prod": policy.PROD,
        **{case: otp for case, _lc, otp in policy.DEBUG_LOCK_CASES},
        **{case: otp for case, _lc, otp, _locked in policy.UNSIGNED_BOOT_CASES},
        "signed": policy.RMA_SIP_SIP_LOCK,
    }
    assert {case: otp.name for case, otp in used.items()} == {
        "prod": "sep_efuse_lc_prod.toml",
        "test_dev_sip_dis": "sep_efuse_lc_test_dev_chiplet_dbg_sip.toml",
        "rma_sip_sip_dis": "sep_efuse_lc_rma_sip_chiplet_dbg_sip.toml",
        "rma_sip_sys_dis": "sep_efuse_lc_rma_sip_chiplet_dbg_sys.toml",
        "rma_sip_debug_open": "sep_efuse_lc_rma_sip.toml",
        "rma_chiplet_debug_locked": "sep_efuse_lc_rma_chiplet_chiplet_dbg_sip.toml",
        "signed": "sep_efuse_lc_rma_sip_chiplet_dbg_sip.toml",
    }
    for otp in used.values():
        assert otp.parent == policy.CONFIGS and otp.is_file(), otp
