# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Whitelisted DV OCA mutation ops that a boot-image spec may run.

Every op keeps manifest_hash consistent so the ROM reaches the named field; a deliberately
broken seal belongs in a byte patch. Rehash-only writers are re-signed; payload seals stay
as earlier ops left them.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import dv_env


@dataclass(frozen=True)
class OpSpec:
    module: str
    function: str
    args: frozenset[str]
    resign: bool = False
    hex_args: frozenset[str] = frozenset()
    tuple_args: frozenset[str] = frozenset()
    # The DV helper recomputes every payload seal, which would undo an earlier payload op.
    reseals_payload: bool = False


_PM = "sep_payload_mutate"
_MM = "sep_manifest_mutate"


def _op(module, function, *args, resign=False, hex_args=(), tuple_args=(), reseals_payload=False):
    return OpSpec(
        module,
        function,
        frozenset(args),
        resign,
        frozenset(hex_args),
        frozenset(tuple_args),
        reseals_payload,
    )


OPS: Mapping[str, OpSpec] = {
    # sep_payload_mutate helpers reseal the slot themselves.
    "set_toc_image_count": _op(
        _PM, "set_toc_image_count", "value", "reseal_entries", "hashed_to_span"
    ),
    "set_toc_payload_length": _op(_PM, "set_toc_payload_length", "value"),
    "set_toc_version_major": _op(_PM, "set_toc_version_major", "value"),
    "set_toc_entry_length": _op(_PM, "set_toc_entry_length", "index", "value"),
    "set_toc_entry_offset": _op(_PM, "set_toc_entry_offset", "index", "value"),
    "permute_toc_entries": _op(_PM, "permute_toc_entries", "order", tuple_args=("order",)),
    "set_payload_hashed_length": _op(_PM, "set_payload_hashed_length", "value"),
    "set_bl1_entry_point": _op(_PM, "set_bl1_entry_point", "value"),
    "set_bl1_zero_length": _op(_PM, "set_bl1_zero_length"),
    "set_bl1_load_addr": _op(_PM, "set_bl1_load_addr", "value"),
    "set_encryption_iv": _op(_PM, "set_encryption_iv", "iv", hex_args=("iv",)),
    "set_encryption_kdf_input": _op(
        _PM, "set_encryption_kdf_input", "kdf_input", hex_args=("kdf_input",)
    ),
    "declare_payload_length": _op(_PM, "declare_payload_length", "payload_length"),
    "set_overlapping_payload_offset": _op(_PM, "set_overlapping_payload_offset", "value"),
    # sep_manifest_mutate setters only rehash, so the signature is refreshed here.
    "set_demotion": _op(
        _MM, "set_demotion", "bl1_valid", "bl1_enable", "bl2_valid", "bl2_enable", resign=True
    ),
    "set_lifecycle_states": _op(_MM, "set_lifecycle_states", "value", "scope", resign=True),
    "set_security_version": _op(_MM, "set_security_version", "value", resign=True),
    "set_public_key_sel": _op(_MM, "set_public_key_sel", "selection", "index", resign=True),
    "set_public_key_slots": _op(
        _MM, "set_public_key_slots", "bits", resign=True, tuple_args=("bits",)
    ),
    "set_manifest_version": _op(_MM, "set_manifest_version", "major", "minor", resign=True),
    "set_manifest_length": _op(_MM, "set_manifest_length", "value", resign=True),
    "set_signature_type": _op(_MM, "set_signature_type", "value", resign=True),
    # set_identity reseals the whole slot itself, payload seals included.
    "set_identity": _op(
        _MM, "set_identity", "kind", "value", "mask", hex_args=("value",), reseals_payload=True
    ),
    # Sets the selector bit the ROM gates its lifecycle check on; set_lifecycle_states does not.
    "set_lifecycle_constraint": _op(
        _MM, "set_lifecycle_constraint", "allowed", "level", reseals_payload=True
    ),
    "set_secure_boot_enforced": _op(_MM, "set_secure_boot_enforced", "value", resign=True),
    # The slot becomes validly unsigned, so there is no signature to refresh.
    "clear_secure_boot": _op(_MM, "clear_secure_boot"),
    # The grafted slot carries its source image's own seals.
    "graft_slot_from": _op(_MM, "graft_slot", "image"),
}


def _convert(op, spec: OpSpec) -> dict:
    unknown = sorted(set(op.args) - spec.args)
    if unknown:
        raise ValueError(
            f"op {op.op} has no argument {unknown[0]!r}; it takes {sorted(spec.args) or 'none'}"
        )
    kwargs = dict(op.args)
    for name in spec.hex_args & set(kwargs):
        if not isinstance(kwargs[name], str):
            raise ValueError(f"op {op.op} argument {name!r} must be a hex string")
        try:
            kwargs[name] = bytes.fromhex(kwargs[name])
        except ValueError:
            raise ValueError(f"op {op.op} argument {name!r} is not a valid hex string") from None
    for name in spec.tuple_args & set(kwargs):
        kwargs[name] = tuple(kwargs[name])
    return kwargs


def _signed(mm, buf, slot: str) -> bool:
    return mm.signature_type(buf, slot) != mm.SIG_TYPE_NO_SIGNATURE


def _resign(mm, pm, buf: bytearray, slot: str) -> None:
    """Refresh manifest_hash and the signature only, keeping every payload seal as it is."""
    mm.rehash(buf, slot)
    n, _e, d = pm.load_rsa_private_key(pm.rom_signing_key(pm.signing_key_for_slot(buf, slot)))
    base = mm.slot_base(slot)
    signature = pm.sign_pkcs1v15_sha256(bytes(buf[base : base + mm.SIGNED_REGION_END]), n, d)
    buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES] = signature


def apply_ops(data: bytes, ops: Sequence, *, images: Mapping[str, Path]) -> bytes:
    """Run each op on its slot in order, checking the layout after each one."""
    mm = dv_env.load(_MM)
    pm = dv_env.load(_PM)
    buf = bytearray(data)
    payload_edited: set[str] = set()
    edited: set[str] = set()
    for op in ops:
        spec = OPS.get(op.op)
        if spec is None:
            raise ValueError(f"{op.op!r} is not a whitelisted OCA op; known: {sorted(OPS)}")
        kwargs = _convert(op, spec)
        if spec.reseals_payload and op.slot in payload_edited:
            raise ValueError(
                f"op {op.op} reseals the whole {op.slot} slot and would undo the earlier "
                "payload op there; run it before the payload op"
            )
        if spec.function == "graft_slot" and op.slot in edited:
            raise ValueError(
                f"op {op.op} replaces the whole {op.slot} slot and would undo the earlier op "
                "there; run it first"
            )
        before = bytes(buf)
        # An unsigned slot has no signature to refresh; the op's own rehash seals it.
        resign = spec.resign and _signed(mm, buf, op.slot)
        if spec.function == "graft_slot":
            source = images.get(kwargs.get("image"))
            if source is None:
                raise ValueError(f"op {op.op} needs an image from {sorted(images)}")
            mm.graft_slot(buf, Path(source).read_bytes(), op.slot)
        else:
            getattr(dv_env.load(spec.module), spec.function)(buf, op.slot, **kwargs)
        if resign:
            _resign(mm, pm, buf, op.slot)
        if spec.module == _PM:
            payload_edited.add(op.slot)
        edited.add(op.slot)
        if bytes(buf) == before:
            raise ValueError(f"op {op.op} on {op.slot} with {dict(op.args)} is a no-op")
        mm.verify_layout(buf, op.slot)
    return bytes(buf)
