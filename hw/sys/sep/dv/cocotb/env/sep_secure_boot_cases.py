# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure-boot field removals shared by the RTL DV and VP boot ROM tests.

Each case removes one secure-boot field from one slot of the shipped signed classic
image and names the ``OCA_FAIL_*`` result the ROM must report for it. The
``MANIFEST_ERR=`` code and the ``SEP_MSG_*`` status are derived from the ROM sources
through :mod:`sep_manifest_mutate`, never copied. Console and status evidence stays with
each harness, because the two observe different interfaces.

Every mutation verifies the slot's layout and manifest hash before it reads or writes a
byte, so a stale input is rejected rather than resealed, and verifies the layout again
afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from env import sep_manifest_mutate as mm

_SIGNED_CLASSIC = mm.SECURE_BOOT_ENFORCED_BIT | mm.SECURE_BOOT_CLASSIC_BIT


@dataclass(frozen=True)
class SecureBootCase:
    name: str
    result_name: str
    mutate: Callable[[bytearray, str], None]

    @property
    def boot_error(self) -> int:
        return int(mm.boot_err(self.result_name))

    @property
    def status_name(self) -> str:
        return str(mm.rom_status_name_for_result(self.boot_error))


def _require_signed_classic(buf: bytes, slot: str) -> None:
    mm.verify_layout(buf, slot)
    control = mm.secure_boot_control(buf, slot)
    assert control == _SIGNED_CLASSIC, (
        f"{slot} secure_boot_control is 0x{control:02x}; these cases start from the "
        f"shipped signed classic image (0x{_SIGNED_CLASSIC:02x})"
    )


def _class_only(buf: bytearray, slot: str) -> None:
    """Enforced bit clear, classic class named, no key or signature material."""
    _require_signed_classic(buf, slot)
    mm.clear_secure_boot(buf, slot)
    mm.set_secure_boot_control(buf, slot, mm.SECURE_BOOT_CLASSIC_BIT)
    mm.verify_layout(buf, slot)


def _flag_cleared_signed(buf: bytearray, slot: str) -> None:
    """Enforced bit clear on a manifest that still carries its signing fields."""
    _require_signed_classic(buf, slot)
    assert mm.signature_type(buf, slot) != mm.SIG_TYPE_NO_SIGNATURE, (
        f"{slot} carries no signature, so the invariant has nothing to refuse"
    )
    mm.set_secure_boot_enforced(buf, slot, False)
    mm.verify_layout(buf, slot)


def _signature_absent(buf: bytearray, slot: str) -> None:
    _require_signed_classic(buf, slot)
    assert mm.signature_size(buf, slot), f"{slot} signature_size is already zero"
    mm.remove_signature(buf, slot, keep_size=False)
    mm.verify_layout(buf, slot)


def _signature_zeroed(buf: bytearray, slot: str) -> None:
    _require_signed_classic(buf, slot)
    size = mm.signature_size(buf, slot)
    assert size == mm.MODULUS_LEN, (
        f"{slot} signature_size is {size}, expected {mm.MODULUS_LEN} (RSA-3072)"
    )
    assert any(mm.signature(buf, slot)), f"{slot} signature is already all zero"
    mm.remove_signature(buf, slot, keep_size=True)
    mm.verify_layout(buf, slot)


def _public_key_absent(buf: bytearray, slot: str) -> None:
    _require_signed_classic(buf, slot)
    assert any(mm.public_key_modulus(buf, slot)), f"{slot} public key is already zero"
    assert mm.public_key_size(buf, slot), f"{slot} public_key_size is already zero"
    mm.remove_public_key(buf, slot, keep_size=False)
    mm.verify_layout(buf, slot)


def _public_key_zeroed(buf: bytearray, slot: str) -> None:
    _require_signed_classic(buf, slot)
    assert mm.can_anchor_public_key(buf, slot), (
        f"{slot} key cannot be anchored, so a digest refusal would prove nothing"
    )
    assert any(mm.public_key_modulus(buf, slot)), f"{slot} public key is already zero"
    mm.remove_public_key(buf, slot, keep_size=True)
    mm.verify_layout(buf, slot)


CASES: Mapping[str, SecureBootCase] = {
    case.name: case
    for case in (
        SecureBootCase("class_only", "OCA_FAIL_ROOT_KEY_UNAUTHORIZED", _class_only),
        SecureBootCase(
            "flag_cleared_signed", "OCA_FAIL_SECURE_BOOT_INVARIANT", _flag_cleared_signed
        ),
        SecureBootCase("signature_absent", "OCA_FAIL_CRYPTO_FIELD_SIZE", _signature_absent),
        SecureBootCase("signature_zeroed", "OCA_FAIL_SIGNATURE", _signature_zeroed),
        SecureBootCase("public_key_absent", "OCA_FAIL_CRYPTO_FIELD_SIZE", _public_key_absent),
        SecureBootCase("public_key_zeroed", "OCA_FAIL_ROOT_KEY_UNAUTHORIZED", _public_key_zeroed),
    )
}
