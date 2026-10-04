# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Golden boot-state soft PCR computation (struct boot_state_record, include/bl0_state.h).

Record: manifest_hash[32] | lc_state u32 LE | secure_boot u8 | sboot_dis u8 | demotion u8 |
reserved u8. PCR = SHA256(0^32 | SHA256(record)).
"""

import hashlib

import oca_layout as L

_SLOTS = {"primary": L.PRIMARY_OFFSET, "backup": L.BACKUP_OFFSET}
_LC_STATE_MAX = 0xF
# MEAS_DEMOTION_BL1_DEMOTE | MEAS_DEMOTION_BL1_LOCKED | MEAS_DEMOTION_BL2_DECISION.
_DEMOTION_MAX = 0x7
_DIGEST_LEN = 32
_RECORD_LEN = 40


def _check(name: str, value: int, high: int) -> None:
    if type(value) is not int or not 0 <= value <= high:
        raise ValueError(f"{name} must be an integer in 0..{high:#x}, got {value!r}")


def boot_pcr(
    manifest_hash: bytes, *, lc_state: int, demotion_decision: int, secure_boot: int, sboot_dis: int
) -> bytes:
    if len(manifest_hash) != _DIGEST_LEN:
        raise ValueError(f"manifest_hash is {len(manifest_hash)} bytes, expected {_DIGEST_LEN}")
    _check("lc_state", lc_state, _LC_STATE_MAX)
    _check("demotion_decision", demotion_decision, _DEMOTION_MAX)
    _check("secure_boot", secure_boot, 1)
    _check("sboot_dis", sboot_dis, 1)
    record = (
        bytes(manifest_hash)
        + lc_state.to_bytes(4, "little")
        + bytes((secure_boot, sboot_dis, demotion_decision, 0))
    )
    assert len(record) == _RECORD_LEN
    return hashlib.sha256(bytes(_DIGEST_LEN) + hashlib.sha256(record).digest()).digest()


def manifest_hash(image: bytes, slot: str) -> bytes:
    """The SHA-256 in a slot's manifest_hash field, which the ROM measures once verified."""
    base = _SLOTS[slot]
    if bytes(image[base : base + 4]) != L.OCAC_MAGIC:
        raise ValueError(
            f"{slot} manifest is not {L.OCAC_MAGIC!r}; OFF_MANIFEST_HASH is the "
            "OCA-classic offset only"
        )
    at = base + L.C.OFF_MANIFEST_HASH
    return bytes(image[at : at + _DIGEST_LEN])


def pcr_token(pcr: bytes) -> str:
    """The console token BL1 prints for the boot-state soft PCR."""
    return f"BL0S_BOOT_PCR={pcr.hex().upper()}"
