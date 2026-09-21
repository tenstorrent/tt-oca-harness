# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Bind either manifest slot to any ROM public-key slot 0-5, and re-sign it.

The ROM binds a manifest's own modulus to the digest compiled in for the slot the
manifest selects (``check_pubkey_hash``), so pointing a selector at slot N while
leaving another key's modulus in place is refused at ``PUBK_HASH_MISMATCH`` --
a different verdict from whatever the testcase meant to reach. Any manifest that
must BOOT therefore needs three writes, not one: the selector, that slot's
modulus, and a signature by that slot's private key.

``sep_firmware_primary_rom_key_slot1_valid_test`` did this for one slot and one
manifest with a hardcoded digest. This module is the generalisation both it and
``sep_key_revocation_bitmap_random_test`` use, so one slot's binding and six
slots' bindings cannot drift apart.

THE SLOT TABLE IS READ OUT OF THE ROM SOURCE, NOT COPIED FROM IT. Slot -> key
name -> digest comes from parsing ``bootrom/prod/src/key_digests.c``, and each
PEM's modulus is hashed and checked against the digest that file holds for its
slot. A regenerated table, a swapped PEM or a slot reordering therefore fails
loudly here, at stimulus construction, instead of turning into a
``PUBK_HASH_MISMATCH`` in the middle of a simulation.

SLOTS 1-5 ARE TEST-ONLY. Their private halves are committed in the clear under
``bootrom/prod/tools/test_signing_keys/`` and they are compiled into the ROM only
under ``TEST_BUILD``; a release build leaves those slots NULL, where the same
selector is refused with ``ROM_KEY_EMPTY``. Slot 0's ``dev0`` key is the one the
packer already signs with, and lives in the tt-boot-manifest submodule.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Dict, Tuple

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm

# .../hw/sys/sep, this file being at .../hw/sys/sep/dv/cocotb/env/.
_SEP_ROOT = Path(__file__).resolve().parents[3]
_ROM_TOOLS = _SEP_ROOT / "bootrom" / "prod" / "tools"
KEY_DIGESTS_C = _SEP_ROOT / "bootrom" / "prod" / "src" / "key_digests.c"
# Same two sources generate_key_digests.py is invoked with. dev0 lives in the
# manifest packer's submodule; the five test keys are committed beside the ROM.
_KEY_DIRS = (
    _ROM_TOOLS / "test_signing_keys",
    _ROM_TOOLS / "tt-boot-manifest" / "tests" / "signing_keys",
)

_DIGEST_DEF_RE = re.compile(
    r"static\s+const\s+uint8_t\s+digest_(\w+)\s*\[[^\]]*\]\s*=\s*\{(.*?)\};", re.S
)
# Only the array initialiser matches: the release arms are `(void *)0`.
_SLOT_ENTRY_RE = re.compile(r"\.digest\s*=\s*digest_(\w+)")
_BYTE_RE = re.compile(r"0x([0-9a-fA-F]{2})")

SHA256_LEN = 32


def _parse_key_digests() -> Tuple[Tuple[str, ...], Dict[str, bytes]]:
    text = KEY_DIGESTS_C.read_text(encoding="utf-8")
    digests: Dict[str, bytes] = {}
    for name, body in _DIGEST_DEF_RE.findall(text):
        raw = bytes(int(b, 16) for b in _BYTE_RE.findall(body))
        if len(raw) != SHA256_LEN:
            raise AssertionError(
                f"{KEY_DIGESTS_C}: digest_{name} has {len(raw)} bytes, expected "
                f"{SHA256_LEN}; the generated table is not the format this parses"
            )
        digests[name] = raw
    # The SOURCE's slot order, which is all a text parse can establish. Both
    # arms of every `#if TEST_BUILD` are present in the file, so this count is
    # six whichever way the ROM was compiled: it catches a table whose LAYOUT
    # changed, never a release build. Which digests the simulated image really
    # carries is settled by the byte search over boot_rom.elf recorded with the
    # release-isolation evidence, not here.
    order = tuple(_SLOT_ENTRY_RE.findall(text))
    if len(order) != mm.PUBK_SEL_NUM_ROM_KEYS:
        raise AssertionError(
            f"{KEY_DIGESTS_C}: the table declares {len(order)} digest-carrying "
            f"slot entries {order}, expected {mm.PUBK_SEL_NUM_ROM_KEYS}; the "
            f"generated table's layout is not the one this helper parses, so the "
            f"slot -> key mapping it derives would be wrong"
        )
    missing = [n for n in order if n not in digests]
    if missing:
        raise AssertionError(
            f"{KEY_DIGESTS_C}: slots {missing} name a digest that is not defined "
            f"in the same file"
        )
    return order, digests


SLOT_NAMES, _SLOT_DIGESTS = _parse_key_digests()


def slot_name(index: int) -> str:
    """The key name ``key_digests.c`` gives ROM slot ``index``."""
    _check_index(index)
    return SLOT_NAMES[index]


def slot_digest(index: int) -> bytes:
    """The SHA-256 digest the ROM has compiled in for ROM slot ``index``."""
    return _SLOT_DIGESTS[slot_name(index)]


def slot_key_path(index: int) -> Path:
    """The private key PEM whose modulus hashes to ROM slot ``index``'s digest."""
    name = slot_name(index)
    for directory in _KEY_DIRS:
        candidate = directory / f"rsa_private_key.{name}.pem"
        if candidate.is_file():
            return candidate
    tried = ", ".join(str(d) for d in _KEY_DIRS)
    raise AssertionError(
        f"no rsa_private_key.{name}.pem for ROM slot {index} (looked in {tried}). "
        f"Slots 1-5 are populated only under TEST_BUILD; see key_digests.c"
    )


def load_slot_key(index: int) -> Tuple[int, int, int, bytes]:
    """``(n, e, d, modulus_bytes)`` for ROM slot ``index``, digest cross-checked.

    The cross-check is what makes a later ``PUBK_HASH_MISMATCH`` impossible to
    blame on the stimulus: the PEM and the compiled-in table are proved to agree
    before a single byte of the image moves.
    """
    pem = slot_key_path(index)
    n, e_pub, d = pm.load_rsa_private_key(pem)
    modulus = n.to_bytes(mm.PUBLIC_KEY_LEN, "big")
    got = hashlib.sha256(modulus).digest()
    want = slot_digest(index)
    if got != want:
        raise AssertionError(
            f"SHA-256 of the modulus in {pem} is {got.hex()}, but {KEY_DIGESTS_C} "
            f"has {want.hex()} for ROM slot {index}; regenerate the digest table "
            f"or restore the PEM"
        )
    return n, e_pub, d, modulus


def bind_manifest_to_rom_slot(buf: bytearray, slot: str, index: int) -> Dict[str, object]:
    """Make ``slot``'s manifest select, carry and be signed by ROM key ``index``.

    Returns the measured facts a caller logs or asserts on: the encoded selector
    read back from the image, whether the selector write changed the TBS, and the
    slot's digest.

    The payload is deliberately untouched, so ``payload_hash`` and the TOC digests
    stay valid and are not recomputed. Nothing here can therefore repair a damaged
    payload, and ``verify_sealed`` before the writes is what proves there was none.
    """
    _check_index(index)
    base = mm.slot_base(slot)
    n, e_pub, d, modulus = load_slot_key(index)

    # The shipped slot must be completely sealed BEFORE anything moves: magic,
    # payload_hash, every TOC image digest, manifest_hash over the TBS and a dev0
    # signature that verifies. Without this a pre-existing defect would surface
    # later as a rejection the caller would read as its own result.
    pm.verify_sealed(buf, slot)
    # And OFF_PUBLIC_KEY must really address the modulus, which is what makes the
    # write below land where this claims. Proved by reproducing the ROM's own
    # comparison against the slot-0 digest on the AS-SHIPPED image; the caller
    # therefore passes a fresh copy of the packed image, not an already-bound one.
    mm.verify_public_key(buf, slot)
    # And the local signer must reproduce the packer's signature byte for byte,
    # or the signature written below is not a genuine one and the ROM's rejection
    # would say SIG_FAILED rather than whatever is under test.
    pm.verify_signing_key(buf, slot)

    tbs_before = bytes(buf[base:base + mm.TBS_LEN])
    mm.set_public_key_sel(buf, slot, selection=mm.PUBK_SEL_ROM_KEY, index=index)
    buf[base + mm.OFF_PUBLIC_KEY:base + mm.OFF_PUBLIC_KEY + mm.PUBLIC_KEY_LEN] = modulus
    mm.rehash(buf, slot)
    tbs_after = bytes(buf[base:base + mm.TBS_LEN])
    tbs_changed = tbs_before != tbs_after

    if tbs_changed:
        # The writes landed inside the SIGNED region, which is the only reason the
        # ROM will read this selector and this modulus. Measured through the
        # shipped dev0 signature going stale rather than assumed: a signature that
        # still verified would mean the bytes moved outside the TBS.
        dev0_n, dev0_e, _dev0_d = pm.load_rsa_private_key()
        stale = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
        if pm.verify_pkcs1v15_sha256(tbs_after, stale, dev0_n, dev0_e):
            raise AssertionError(
                f"{slot}: the shipped signature still verifies after selecting ROM "
                f"slot {index} and installing its modulus; the writes did not land "
                f"inside the TBS, so the ROM would read the original selector"
            )

    buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES] = \
        pm.sign_pkcs1v15_sha256(tbs_after, n, d)

    # Prove offline what the ROM will prove in hardware. Without it a broken
    # re-sign reaches the simulation as RSA_VERIFY_FAIL and reads like a DUT defect.
    mm.verify_layout(buf, slot)
    sig = bytes(buf[base + mm.OFF_SIGNATURE:base + mm.OFF_SIGNATURE + pm.RSA_KEY_BYTES])
    if not pm.verify_pkcs1v15_sha256(bytes(buf[base:base + mm.TBS_LEN]), sig, n, e_pub):
        raise AssertionError(
            f"{slot}: the ROM slot {index} signature this stimulus wrote does not "
            f"verify against its own modulus; the re-sign is broken, not the ROM"
        )
    staged = mm.public_key(buf, slot)
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
            f"BAD_KEY_IDX arm, not a key binding"
        )
