# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bind either manifest slot to any ROM public-key slot 0-5, and re-sign it.

The ROM checks a manifest's modulus against the digest compiled in for the slot it
selects (``plat_is_key_authorized()`` in ``oca_platform.c``), so a manifest that must
boot needs three writes: the selector, that slot's modulus, and a signature by that
slot's private key. Otherwise the ROM refuses the key (``PUBK_UNAUTHORIZED``).

Keys come from ``bootrom/prod/tests/signing_keys/rsa_private_key.rom_key<N>.pem``, the
PEMs the debug ROM's digest table is generated from; each modulus is checked against
that table under ``build/`` or ``build_pio/`` first. Release builds use externally
provisioned keys, so these scenarios do not apply to them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Tuple

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm

SLOT_NAMES = tuple(f"rom_key{index}" for index in range(mm.PUBK_SEL_NUM_ROM_KEYS))


def slot_name(index: int) -> str:
    """The generated-table key name for ROM slot ``index``."""
    _check_index(index)
    return SLOT_NAMES[index]


def slot_digest(index: int) -> bytes:
    """The SHA-256 digest the ROM has compiled in for ROM slot ``index``."""
    _check_index(index)
    return mm.rom_key_digest(index)


def slot_key_path(index: int) -> Path:
    """The private key PEM whose modulus hashes to ROM slot ``index``'s digest."""
    _check_index(index)
    return pm.rom_signing_key(index)


def load_slot_key(index: int) -> Tuple[int, int, int, bytes]:
    """``(n, e, d, modulus_bytes)`` for ROM slot ``index``.

    Raises if the PEM modulus does not hash to the compiled-in digest, so a later
    ``PUBK_UNAUTHORIZED`` cannot come from the stimulus.
    """
    pem = slot_key_path(index)
    n, e_pub, d = pm.load_rsa_private_key(pem)
    modulus = n.to_bytes(mm.MODULUS_LEN, "big")
    got = hashlib.sha256(modulus).digest()
    want = slot_digest(index)
    if got != want:
        raise AssertionError(
            f"SHA-256 of the modulus in {pem} is {got.hex()}, but the generated "
            f"key_digests.c has {want.hex()} for ROM slot {index}; regenerate the "
            f"digest table or restore the PEM"
        )
    return n, e_pub, d, modulus


def bind_manifest_to_rom_slot(buf: bytearray, slot: str, index: int) -> Dict[str, object]:
    """Make ``slot``'s manifest select, carry and be signed by ROM key ``index``.

    Returns the selector read back, whether the TBS changed, and the slot's digest. The
    payload is not touched, so ``payload_hash`` and the TOC digests stay valid. Pass a
    fresh copy of the packed image: the checks below need the as-shipped bytes.
    """
    _check_index(index)
    base = mm.slot_base(slot)
    n, e_pub, d, modulus = load_slot_key(index)

    # Prove the shipped slot is fully sealed first, so a pre-existing defect cannot
    # surface later as a rejection the caller reads as its own result.
    pm.verify_sealed(buf, slot)
    # Prove OFF_PUBLIC_KEY addresses the modulus by repeating the ROM's slot-0 digest
    # compare on the as-shipped image.
    mm.verify_public_key(buf, slot)
    # And the shipped signature must verify under the PEM's modulus, or the
    # signature written below is not a genuine one and the ROM's rejection would be
    # OCA_FAIL_SIGNATURE rather than whatever is under test.
    pm.verify_signing_key(buf, slot)

    tbs_before = bytes(buf[base : base + mm.SIGNED_REGION_END])
    mm.set_public_key_sel(buf, slot, selection=mm.PUBK_SEL_ROM_KEY, index=index)
    buf[base + mm.OFF_PUBLIC_KEY : base + mm.OFF_PUBLIC_KEY + mm.MODULUS_LEN] = modulus
    mm.rehash(buf, slot)
    tbs_after = bytes(buf[base : base + mm.SIGNED_REGION_END])
    tbs_changed = tbs_before != tbs_after

    if tbs_changed:
        # The writes must land inside the signed region; a shipped ROM-slot-0 signature
        # that still verifies would mean they did not.
        dev0_n, dev0_e, _dev0_d = pm.load_rsa_private_key(pm.rom_signing_key(0))
        stale = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
        if pm.verify_pkcs1v15_sha256(tbs_after, stale, dev0_n, dev0_e):
            raise AssertionError(
                f"{slot}: the shipped signature still verifies after selecting ROM "
                f"slot {index} and installing its modulus; the writes did not land "
                f"inside the TBS, so the ROM would read the original selector"
            )

    buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES] = (
        pm.sign_pkcs1v15_sha256(tbs_after, n, d)
    )

    # Prove offline what the ROM will prove in hardware. Without it a broken
    # re-sign reaches the simulation as an OCA_FAIL_SIGNATURE rejection and reads like
    # a DUT defect.
    mm.verify_layout(buf, slot)
    sig = bytes(buf[base + mm.OFF_SIGNATURE : base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
    if not pm.verify_pkcs1v15_sha256(bytes(buf[base : base + mm.SIGNED_REGION_END]), sig, n, e_pub):
        raise AssertionError(
            f"{slot}: the ROM slot {index} signature this stimulus wrote does not "
            f"verify against its own modulus; the re-sign is broken, not the ROM"
        )
    staged = mm.public_key_modulus(buf, slot)
    if hashlib.sha256(staged).digest() != slot_digest(index):
        raise AssertionError(
            f"{slot}: the modulus read back from the image is not ROM slot "
            f"{index}'s; the write did not land"
        )
    selector = mm.get_public_key_sel(buf, slot)
    expected = index & 0xF
    if selector != expected:
        raise AssertionError(
            f"{slot} public_key_sel encoded as 0x{selector:04x}, expected "
            f"0x{expected:04x} (selection=PUBK_SEL_ROM_KEY, index={index})"
        )
    return {
        "slot": slot,
        "index": index,
        "key_name": slot_name(index),
        "key_path": slot_key_path(index),
        "selector": selector,
        "tbs_changed": tbs_changed,
        "digest": slot_digest(index),
    }


def _check_index(index: int) -> None:
    if not 0 <= index < mm.PUBK_SEL_NUM_ROM_KEYS:
        raise AssertionError(
            f"ROM key slot {index} is outside the table [0, "
            f"{mm.PUBK_SEL_NUM_ROM_KEYS}); an out-of-range index is the separate "
            f"PUBK_SLOT_RESERVED refusal, not a key binding"
        )
