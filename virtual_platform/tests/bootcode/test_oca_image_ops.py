# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import inspect
import sys

import boot_image_mutations as bim
import dv_env
import oca_image_ops
import oca_layout as L
import pytest
from sepvp import paths

pytestmark = pytest.mark.hostonly

_SIGNED = paths.OCA_IMAGE_PATHS["signed"]


@pytest.fixture(scope="module")
def golden():
    if not _SIGNED.is_file():
        pytest.skip("oca-images not built")
    return _SIGNED.read_bytes()


def test_dv_env_loads_without_cocotb():
    mm = dv_env.load("sep_manifest_mutate")
    assert mm.PRIMARY_MANIFEST_OFFSET == 0x1000
    assert "cocotb" not in sys.modules


# One sealing stimulus per op; args chosen so the op changes bytes.
_CASES = {
    "set_toc_image_count": {"value": 0},
    "set_toc_payload_length": {"value": 0x10},
    "set_toc_version_major": {"value": 2},
    "set_toc_entry_length": {"index": 0, "value": 0x10},
    "set_toc_entry_offset": {"index": 0, "value": 0x200},
    "permute_toc_entries": {"order": [1, 0, 2]},
    "set_payload_hashed_length": {"value": 0x20},
    "set_bl1_entry_point": {},
    "set_bl1_zero_length": {},
    "set_bl1_load_addr": {"value": 0x10002000},
    "set_encryption_iv": {"iv": "ff" * 16},
    "set_encryption_kdf_input": {"kdf_input": "ee" * 64},
    "declare_payload_length": {"payload_length": 0x100},
    "set_overlapping_payload_offset": {"value": 0x800},
    "set_demotion": {"bl1_valid": True, "bl1_enable": True},
    "set_lifecycle_states": {"value": 0x5, "scope": "chiplet"},
    "set_lifecycle_constraint": {"allowed": 0x5, "level": "chiplet"},
    "set_security_version": {"value": 1},
    "set_public_key_sel": {"selection": 0, "index": 3},
    "set_public_key_slots": {"bits": [0, 1]},
    "set_manifest_version": {"major": 2},
    "set_manifest_length": {"value": 4100},
    "set_signature_type": {"value": 5},
    "set_identity": {"kind": "package", "value": "00" * 32, "mask": 1 << 32},
    "set_secure_boot_enforced": {"value": False},
    "clear_secure_boot": {},
    "graft_slot_from": {"image": "rom_key1"},
}
# Ops that need a base with a property the secure-boot golden lacks.
_BASES = {
    "permute_toc_entries": "multi",
    "set_encryption_iv": "encrypted",
    "set_encryption_kdf_input": "encrypted",
}


@pytest.mark.parametrize("op", sorted(oca_image_ops.OPS))
def test_every_whitelisted_op_leaves_a_consistent_layout(golden, op):
    args = _CASES.get(op)
    if args is None:
        pytest.fail(f"add a stimulus for {op} to _CASES")
    base_path = paths.OCA_IMAGE_PATHS[_BASES.get(op, "signed")]
    if not base_path.is_file():
        pytest.skip(f"{base_path.name} not built")
    base = base_path.read_bytes()
    out = oca_image_ops.apply_ops(
        base, [bim.OcaOp(op=op, slot="primary", args=args)], images=paths.OCA_IMAGE_PATHS
    )
    assert out != base
    assert out[L.BACKUP_OFFSET :] == base[L.BACKUP_OFFSET :]
    dv_env.load("sep_manifest_mutate").verify_layout(out, "primary")


def test_a_backup_op_leaves_the_primary_slot_untouched(golden):
    out = oca_image_ops.apply_ops(
        golden, [bim.OcaOp("set_security_version", "backup", {"value": 1})], images={}
    )
    assert out[: L.BACKUP_OFFSET] == golden[: L.BACKUP_OFFSET]
    assert out[L.BACKUP_OFFSET :] != golden[L.BACKUP_OFFSET :]


def test_a_resealed_manifest_op_still_verifies_its_signature(golden):
    pm = dv_env.load("sep_payload_mutate")
    out = oca_image_ops.apply_ops(
        golden, [bim.OcaOp("set_security_version", "primary", {"value": 1})], images={}
    )
    pm.verify_sealed(out, "primary")


def test_an_op_on_an_unsigned_slot_is_rehashed_without_signing():
    unsigned = paths.OCA_IMAGE_PATHS["unsigned"]
    if not unsigned.is_file():
        pytest.skip("oca-images not built")
    base = unsigned.read_bytes()
    out = oca_image_ops.apply_ops(
        base, [bim.OcaOp("set_security_version", "primary", {"value": 1})], images={}
    )
    mm = dv_env.load("sep_manifest_mutate")
    mm.verify_layout(out, "primary")
    sig = slice(L.PRIMARY_OFFSET + mm.OFF_SIGNATURE, L.PRIMARY_OFFSET + mm.OFF_MANIFEST_HASH)
    assert out[sig] == base[sig]


def test_ops_apply_in_order(golden):
    mm = dv_env.load("sep_manifest_mutate")
    out = oca_image_ops.apply_ops(
        golden,
        [
            bim.OcaOp("set_security_version", "primary", {"value": 1}),
            bim.OcaOp("set_security_version", "primary", {"value": 3}),
        ],
        images={},
    )
    assert mm.security_version(out, "primary") == 3


def test_an_op_that_changes_nothing_is_refused(golden):
    mm = dv_env.load("sep_manifest_mutate")
    current = mm.security_version(golden, "primary")
    with pytest.raises(ValueError, match="no-op"):
        oca_image_ops.apply_ops(
            golden, [bim.OcaOp("set_security_version", "primary", {"value": current})], images={}
        )


def test_unknown_op_is_refused(golden):
    with pytest.raises(ValueError, match="not a whitelisted"):
        oca_image_ops.apply_ops(golden, [bim.OcaOp("rehash", "primary", {})], images={})


def test_unknown_arg_is_refused(golden):
    with pytest.raises(ValueError, match="argument"):
        oca_image_ops.apply_ops(
            golden, [bim.OcaOp("set_toc_image_count", "primary", {"count": 0})], images={}
        )


def test_a_hex_argument_must_be_a_hex_string(golden):
    with pytest.raises(ValueError, match="hex"):
        oca_image_ops.apply_ops(
            golden,
            [bim.OcaOp("set_identity", "primary", {"kind": "package", "value": 0, "mask": 1})],
            images={},
        )


def test_graft_needs_a_known_image(golden):
    with pytest.raises(ValueError, match="image"):
        oca_image_ops.apply_ops(
            golden, [bim.OcaOp("graft_slot_from", "primary", {"image": "nope"})], images={}
        )


@pytest.mark.parametrize("op", sorted(oca_image_ops.OPS))
def test_every_whitelisted_arg_is_a_parameter_of_the_dv_function(op):
    spec = oca_image_ops.OPS[op]
    params = inspect.signature(getattr(dv_env.load(spec.module), spec.function)).parameters
    if op == "graft_slot_from":
        assert {"dst", "src", "slot"} <= set(params)
    else:
        assert spec.args <= set(params) - {"buf", "slot"}


def _payload_seals(mm, data, slot="primary"):
    base = mm.slot_base(slot)
    pm = dv_env.load("sep_payload_mutate")
    return (
        data[base + pm.OFF_PAYLOAD_HASH : base + pm.OFF_PAYLOAD_HASH + mm.HASH_FIELD_SIZE],
        data[
            base + pm.OFF_PAYLOAD_HASH_CHAIN : base + pm.OFF_PAYLOAD_HASH_CHAIN + mm.HASH_FIELD_SIZE
        ],
    )


@pytest.mark.parametrize(
    "first",
    [
        bim.OcaOp("declare_payload_length", "primary", {"payload_length": 0x100}),
        bim.OcaOp("set_overlapping_payload_offset", "primary", {"value": 0x800}),
    ],
    ids=lambda op: op.op,
)
def test_a_manifest_op_keeps_the_payload_seals_an_earlier_op_left(golden, first):
    mm = dv_env.load("sep_manifest_mutate")
    pm = dv_env.load("sep_payload_mutate")
    after_first = oca_image_ops.apply_ops(golden, [first], images={})
    second = bim.OcaOp("set_security_version", "primary", {"value": 1})
    out = oca_image_ops.apply_ops(golden, [first, second], images={})
    assert _payload_seals(mm, out) == _payload_seals(mm, after_first)
    assert mm.security_version(out, "primary") == 1
    pm.verify_signing_key(out, "primary")


@pytest.mark.parametrize("value", [0, 0x1000])
def test_a_manifest_op_after_an_unsealed_toc_count_does_not_parse_the_toc(golden, value):
    mm = dv_env.load("sep_manifest_mutate")
    pm = dv_env.load("sep_payload_mutate")
    first = bim.OcaOp("set_toc_image_count", "primary", {"value": value, "reseal_entries": False})
    after_first = oca_image_ops.apply_ops(golden, [first], images={})
    out = oca_image_ops.apply_ops(
        golden,
        [first, bim.OcaOp("set_security_version", "primary", {"value": 1})],
        images={},
    )
    payload = slice(L.PRIMARY_OFFSET + L.BODY_SIZE, L.BACKUP_OFFSET)
    assert out[payload] == after_first[payload]
    assert _payload_seals(mm, out) == _payload_seals(mm, after_first)
    pm.verify_signing_key(out, "primary")


def test_set_identity_after_a_payload_op_on_the_same_slot_is_refused(golden):
    identity = {"kind": "package", "value": "00" * 32, "mask": 1 << 32}
    with pytest.raises(ValueError, match="reseals the whole primary slot"):
        oca_image_ops.apply_ops(
            golden,
            [
                bim.OcaOp("set_toc_version_major", "primary", {"value": 2}),
                bim.OcaOp("set_identity", "primary", identity),
            ],
            images={},
        )


def test_set_identity_after_a_payload_op_on_the_other_slot_is_allowed(golden):
    identity = {"kind": "package", "value": "00" * 32, "mask": 1 << 32}
    oca_image_ops.apply_ops(
        golden,
        [
            bim.OcaOp("set_toc_version_major", "backup", {"value": 2}),
            bim.OcaOp("set_identity", "primary", identity),
        ],
        images={},
    )


def test_set_lifecycle_constraint_sets_the_selector_bit(golden):
    mm = dv_env.load("sep_manifest_mutate")
    out = oca_image_ops.apply_ops(
        golden,
        [bim.OcaOp("set_lifecycle_constraint", "primary", {"allowed": 0x5})],
        images={},
    )
    assert mm.lifecycle_states(out, "primary") == 0x5
    assert mm.selector_bits(out, "primary") & (1 << mm.SELECTOR_BIT_LIFECYCLE["chiplet"])


def test_set_lifecycle_constraint_after_a_payload_op_on_the_same_slot_is_refused(golden):
    with pytest.raises(ValueError, match="reseals the whole primary slot"):
        oca_image_ops.apply_ops(
            golden,
            [
                bim.OcaOp("set_toc_version_major", "primary", {"value": 2}),
                bim.OcaOp("set_lifecycle_constraint", "primary", {"allowed": 0x5}),
            ],
            images={},
        )


_ROM_KEY1 = {"rom_key1": paths.OCA_IMAGE_PATHS["rom_key1"]}


@pytest.mark.parametrize(
    "first",
    [
        bim.OcaOp("set_toc_version_major", "primary", {"value": 2}),
        bim.OcaOp("set_security_version", "primary", {"value": 1}),
    ],
    ids=["payload_op", "manifest_op"],
)
def test_a_graft_after_an_op_on_the_same_slot_is_refused(golden, first):
    with pytest.raises(ValueError, match="replaces the whole primary slot"):
        oca_image_ops.apply_ops(
            golden,
            [first, bim.OcaOp("graft_slot_from", "primary", {"image": "rom_key1"})],
            images=_ROM_KEY1,
        )


def test_a_graft_after_an_op_on_the_other_slot_is_allowed(golden):
    out = oca_image_ops.apply_ops(
        golden,
        [
            bim.OcaOp("set_toc_version_major", "backup", {"value": 2}),
            bim.OcaOp("graft_slot_from", "primary", {"image": "rom_key1"}),
        ],
        images=_ROM_KEY1,
    )
    rom_key1 = _ROM_KEY1["rom_key1"].read_bytes()
    assert out[L.PRIMARY_OFFSET : L.BACKUP_OFFSET] == rom_key1[L.PRIMARY_OFFSET : L.BACKUP_OFFSET]
