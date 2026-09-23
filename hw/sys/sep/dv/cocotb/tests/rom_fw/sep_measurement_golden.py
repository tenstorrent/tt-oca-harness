# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Independent reference model for the BL0 boot measurement, and its checker.

Recomputes SHA-256 over the ROM's 48-byte measurement block from the inputs BL0
printed and compares it with the digest BL1 reads back from ``bl0_state``.
"""

from __future__ import annotations

import hashlib
import re

from rom_fw import sep_manifest_field_defect as fd

# The ROM masks each scalar to its field width before hashing.
LC_MASK = 0xF
DEMOTE_MASK = 0x7
BOOL_MASK = 0x1

_MEAS_TOKENS = {
    "lc_state": "MEAS_LC=",
    "demotion_decision": "MEAS_DEMOTE=",
    "secure_boot": "MEAS_SBOOT=",
    "sboot_dis": "MEAS_SBOOT_DIS=",
}

_DIGEST_RE = re.compile(r"BL0S_MEAS=([0-9A-F]{64})")
_HASH_RE = re.compile(r"MANIFEST_HASH=([0-9A-F]{64})")


def calculate_measurement(manifest_hash: bytes, lc_state: int, demotion_decision: int,
                          secure_boot: int, sboot_dis: int) -> bytes:
    assert len(manifest_hash) == 32, (
        f"manifest_hash is {len(manifest_hash)} bytes, expected 32"
    )
    blob = bytearray(manifest_hash)
    for value, mask in ((lc_state, LC_MASK), (demotion_decision, DEMOTE_MASK),
                        (secure_boot, BOOL_MASK), (sboot_dis, BOOL_MASK)):
        blob += (value & mask).to_bytes(4, "little")
    assert len(blob) == 48, f"input block is {len(blob)} bytes, expected 48"
    return hashlib.sha256(bytes(blob)).digest()


def read_inputs(console: list[str]) -> dict[str, int]:
    out = {}
    for name, token in _MEAS_TOKENS.items():
        line = next((l for l in console if l.startswith(token)), None)
        assert line is not None, (
            f"ROM never printed {token}. rom_record_measurement() emits all four "
            f"inputs before hashing, so a missing one means the measurement step "
            f"was not reached. Console: {console}"
        )
        out[name] = int(line[len(token):], 16)
    return out


def read_digest(console: list[str]) -> bytes:
    for line in console:
        m = _DIGEST_RE.search(line)
        if m:
            return bytes.fromhex(m.group(1))
    raise AssertionError(
        "BL1 never printed BL0S_MEAS=. The digest is only observable through "
        "BL1's bl0_state dump (dv/fw/tests/bl1_pass_test), so either BL1 was "
        f"not reached or that dump is missing. Console: {console}"
    )


def assert_inputs(logger, console: list[str], *, lc_state: int, secure_boot: int,
                  sboot_dis: int, demotion_decision: int | None = None) -> dict[str, int]:
    got = read_inputs(console)
    want = {"lc_state": lc_state & LC_MASK, "secure_boot": secure_boot & BOOL_MASK,
            "sboot_dis": sboot_dis & BOOL_MASK}
    if demotion_decision is not None:
        want["demotion_decision"] = demotion_decision & DEMOTE_MASK
    for name, expected in want.items():
        assert got[name] == expected, (
            f"MEAS {name} is 0x{got[name]:x}, expected 0x{expected:x}. The ROM "
            f"hashed a different boot state than this scenario established, so a "
            f"digest match would prove nothing. All inputs: {got}"
        )
    logger.info(
        "CHK-MEAS-INPUTS: lc_state=0x%x demotion=0x%x secure_boot=%d sboot_dis=%d "
        "-- the state the ROM hashed is the state this scenario set up",
        got["lc_state"], got["demotion_decision"], got["secure_boot"],
        got["sboot_dis"],
    )
    return got


def assert_digest(logger, console: list[str], manifest_hash: bytes,
                  inputs: dict[str, int]) -> bytes:
    got = read_digest(console)
    want = calculate_measurement(manifest_hash, **inputs)
    assert got == want, (
        f"measurement digest mismatch for inputs {inputs}\n"
        f"  BL1 read from bl0_state: {got.hex().upper()}\n"
        f"  Python golden:           {want.hex().upper()}\n"
        f"  manifest_hash:           {manifest_hash.hex().upper()}\n"
        "The ROM's SHA-256 over the 48-byte block in measurement.h disagrees "
        "with an independent model of the same layout. Either the input packing "
        "changed, or the digest did not survive the handoff into bl0_state."
    )

    first = f"MEASUREMENT=0x{int.from_bytes(got[:4], 'little'):08x}"
    assert fd.first_index(console, first) >= 0, (
        f"ROM printed no {first}. BL0's first-word report and BL1's full digest "
        f"must describe the same value. Console: {console}"
    )

    logger.info(
        "CHK-MEAS-GOLDEN: BL1 read %s from bl0_state, which equals the Python "
        "golden over {manifest_hash, lc=0x%x, demote=0x%x, sboot=%d, "
        "sboot_dis=%d}; BL0's own %s agrees with its first word",
        got.hex().upper(), inputs["lc_state"], inputs["demotion_decision"],
        inputs["secure_boot"], inputs["sboot_dis"], first,
    )
    return got
