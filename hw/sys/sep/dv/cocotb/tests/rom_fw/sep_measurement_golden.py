# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Independent reference model for the BL0 boot-state soft PCR.

Rebuilds ``boot_state_record``, enrolls it as ``measurement.c`` does, and compares the result
with the soft PCR that BL1 reads from ``bl0_state``.
"""

from __future__ import annotations

import hashlib
import re

LC_MASK = 0xF
DEMOTE_MASK = 0x7
BOOL_MASK = 0x1

_PCR_RE = re.compile(r"BL0S_BOOT_PCR=([0-9A-F]{64})")


def calculate_boot_pcr(
    manifest_hash: bytes,
    lc_state: int,
    demotion_decision: int,
    secure_boot: int,
    sboot_dis: int,
) -> bytes:
    assert len(manifest_hash) == 32, f"manifest_hash is {len(manifest_hash)} bytes, expected 32"
    assert 0 <= lc_state <= LC_MASK
    assert 0 <= demotion_decision <= DEMOTE_MASK
    assert 0 <= secure_boot <= BOOL_MASK
    assert 0 <= sboot_dis <= BOOL_MASK
    record = (
        manifest_hash
        + lc_state.to_bytes(4, "little")
        + bytes((secure_boot, sboot_dis, demotion_decision, 0))
    )
    assert len(record) == 40, f"boot_state_record is {len(record)} bytes, expected 40"
    record_digest = hashlib.sha256(record).digest()
    return hashlib.sha256(bytes(32) + record_digest).digest()


def read_boot_pcr(console: list[str]) -> bytes:
    for line in console:
        m = _PCR_RE.search(line)
        if m:
            return bytes.fromhex(m.group(1))
    raise AssertionError(
        "BL1 never printed BL0S_BOOT_PCR=. The enrolled value is observable through "
        "BL1's bl0_state dump (dv/fw/tests/bl1_pass_test), so either BL1 was "
        f"not reached or that dump is missing. Console: {console}"
    )


def assert_boot_pcr(
    logger,
    console: list[str],
    manifest_hash: bytes,
    *,
    lc_state: int,
    demotion_decision: int,
    secure_boot: int,
    sboot_dis: int,
) -> bytes:
    got = read_boot_pcr(console)
    want = calculate_boot_pcr(
        manifest_hash,
        lc_state=lc_state,
        demotion_decision=demotion_decision,
        secure_boot=secure_boot,
        sboot_dis=sboot_dis,
    )
    assert got == want, (
        "boot-state soft PCR mismatch\n"
        f"  BL1 read from bl0_state: {got.hex().upper()}\n"
        f"  Python golden:           {want.hex().upper()}\n"
        f"  manifest_hash:           {manifest_hash.hex().upper()}\n"
        f"  lc_state:                0x{lc_state:x}\n"
        f"  demotion:                0x{demotion_decision:x}\n"
        f"  secure_boot:             {secure_boot}\n"
        f"  sboot_dis:               {sboot_dis}\n"
        "The enrolled value must be SHA256(zero-PCR || SHA256(packed "
        "boot_state_record))."
    )

    logger.info(
        "CHK-MEAS-GOLDEN PASS: BL1 read boot-state soft PCR %s from bl0_state; "
        "it equals SHA256(zero-PCR || SHA256({manifest_hash, lc=0x%x, "
        "demote=0x%x, sboot=%d, sboot_dis=%d}))",
        got.hex().upper(),
        lc_state,
        demotion_decision,
        secure_boot,
        sboot_dis,
    )
    return got


# Known-answer vector for the shipped secure-boot image: TEST_DEV, demotion
# decision 2, secure boot on, SBOOT_DIS clear. BL1 prints the PCR as BL0S_BOOT_PCR=.
_KAT_MANIFEST_HASH = bytes.fromhex(
    "975638FD2835ECDCD3DAD738EF26B2C1497982F54535F86076325326A63914C4"
)
_KAT_PCR = bytes.fromhex("7D9897C3FB08563C3A601D9CF39B29AD5DD4906BC0AFA798F60A537CFC6DF789")
_KAT_INPUTS = {"lc_state": 0x0, "demotion_decision": 0x2, "secure_boot": 1, "sboot_dis": 0}


def _selftest() -> int:
    got = calculate_boot_pcr(_KAT_MANIFEST_HASH, **_KAT_INPUTS)
    assert got == _KAT_PCR, f"boot PCR KAT: got {got.hex().upper()}, want {_KAT_PCR.hex().upper()}"
    # Each record field must reach the digest, or a wrong demotion or lifecycle input passes.
    for field, flip in (
        ("lc_state", 0x1),
        ("demotion_decision", 0x4),
        ("secure_boot", 0x1),
        ("sboot_dis", 0x1),
    ):
        changed = dict(_KAT_INPUTS, **{field: _KAT_INPUTS[field] ^ flip})
        assert calculate_boot_pcr(_KAT_MANIFEST_HASH, **changed) != _KAT_PCR, (
            f"boot PCR ignores {field}"
        )
    assert read_boot_pcr([f"ROM> BL0S_BOOT_PCR={_KAT_PCR.hex().upper()}"]) == _KAT_PCR
    print("sep_measurement_golden: boot PCR KAT and field sensitivity OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
