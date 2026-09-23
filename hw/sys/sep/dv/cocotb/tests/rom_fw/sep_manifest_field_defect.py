# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus and console evidence for the manifest-field and usage-constraint defects.

Structural header checks print no per-reason token and the usage-constraint arms share
one error code, so testcases attribute a refusal by slot order, count and marker.
"""

from __future__ import annotations

import pathlib
import re

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev

PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

LC_MARKER = "LC_USAGE_CONSTRAINT_FAIL"
CHIPLET_MARKER = "CHIPLET_ID_MISMATCH"
PACKAGE_MARKER = "PACKAGE_ID_MISMATCH"

_USAGE_MARKERS = (LC_MARKER, CHIPLET_MARKER, PACKAGE_MARKER)

SIBLING_MARKERS = {
    marker: tuple(m for m in _USAGE_MARKERS if m != marker)
    for marker in _USAGE_MARKERS
}

# Per-arm echoes, in the ROM's emission order.
_DEVICE_ID_TOKENS = {
    "chiplet_id": ("CID_IDX=", "CID_FUSE=", "CID_MFST="),
    "package_id": ("PID_IDX=", "PID_FUSE=", "PID_MFST="),
}
_DEVICE_ID_MARKER = {"chiplet_id": CHIPLET_MARKER, "package_id": PACKAGE_MARKER}
_DEVICE_ID_SELECTOR_BASE = {
    "chiplet_id": mm.SELECTOR_BIT_CHIPLET_ID_BASE,
    "package_id": mm.SELECTOR_BIT_PACKAGE_ID_BASE,
}


def first_index(console: list[str], marker: str, after: int = -1) -> int:
    for i, line in enumerate(console):
        if i > after and marker in line:
            return i
    return -1


def count(console: list[str], marker: str) -> int:
    return sum(1 for line in console if marker in line)


def hex_value(console: list[str], token: str) -> int | None:
    pattern = re.compile(re.escape(token) + r"0x([0-9a-fA-F]{8})")
    for line in console:
        found = pattern.search(line)
        if found:
            return int(found.group(1), 16)
    return None


def assert_slot_attributed(console: list[str], marker: str, *, after: int,
                           before: int, expected_count: int = 1) -> int:
    i = first_index(console, marker)
    assert after < i < before, (
        f"{marker}@{i} does not sit between line {after} and line {before}: it "
        f"is not attributable to the slot under test. Console: {console}"
    )
    n = count(console, marker)
    assert n == expected_count, (
        f"{marker} appeared {n} times, expected exactly {expected_count}. "
        f"Console: {console}"
    )
    return i


_MANIFEST_H = (
    pathlib.Path(__file__).resolve().parents[4] / "bootrom" / "prod" / "include"
    / "manifest.h"
)


def assert_rom_manifest_bounds() -> int:
    # The Python copy of MANIFEST_MAX_SIZE can drift and silently make an over-bound length legal.
    text = _MANIFEST_H.read_text()
    found = re.search(r"^#define\s+MANIFEST_MAX_SIZE\s+(\d+)\s*$", text, re.MULTILINE)
    assert found, (
        f"MANIFEST_MAX_SIZE is not defined in {_MANIFEST_H}; either the header moved "
        f"or the define was renamed, in which case every length bound in "
        f"sep_manifest_mutate is an unverified number"
    )
    rom_value = int(found.group(1))
    assert rom_value == mm.MANIFEST_MAX_SIZE, (
        f"{_MANIFEST_H} defines MANIFEST_MAX_SIZE as {rom_value} but "
        f"sep_manifest_mutate.MANIFEST_MAX_SIZE is {mm.MANIFEST_MAX_SIZE}. Every "
        f"stimulus chosen relative to that bound is now addressing the wrong "
        f"number -- a length picked to sit ABOVE the bound may be inside it"
    )
    return rom_value


def reads_starting_at(flash, addr: int) -> list[int]:
    # Match the read's start: the flash BFM records one byte past each request, so spans over-cover.
    rds = ev.reads(flash.get_transactions())
    return [i for i, t in enumerate(rds) if ev.read_span(t)[0] == addr]


def assert_no_read_starting_at(logger, flash, addr: int, why: str) -> None:
    hits = reads_starting_at(flash, addr)
    spans = [f"0x{s:x}..0x{e:x}"
             for s, e in (ev.read_span(t) for t in ev.reads(flash.get_transactions()))]
    assert not hits, (
        f"read(s) {hits} began at 0x{addr:x}, which must not happen: {why}. "
        f"Read spans: {spans}"
    )
    logger.info(
        "CHK-NO-READ: no SPI read began at 0x%06x -- %s. Read spans: %s",
        addr, why, spans,
    )


def assert_served_field(logger, flash, slot: str, offset: int, expected: bytes,
                        what: str) -> None:
    # One read must cover the whole field; the ROM fetches the manifest in one transaction.
    addr = mm.slot_base(slot) + offset
    hit = ev.covering_read(ev.reads(flash.get_transactions()), addr)
    assert hit is not None, (
        f"no single SPI read covered {what} at flash 0x{addr:x}, so the device "
        f"record cannot confirm the stimulus reached the DUT"
    )
    idx, txn = hit
    got = ev.bytes_at(txn, addr, len(expected))
    assert got == expected, (
        f"the device served {got.hex()} for {what} at flash 0x{addr:x}, but this "
        f"testcase planted {expected.hex()}. The offline artefact check passed, so "
        f"the difference is in the transport, not in the mutation -- the DUT was "
        f"given a different stimulus from the one this testcase's name describes"
    )
    logger.info(
        "CHK-STIMULUS-SERVED: read[%d] returned %s for %s at flash 0x%06x, exactly "
        "the planted bytes", idx, got.hex(), what, addr,
    )


def assert_clean_key_fuses(image) -> None:
    bl1_ver = image.field_int("BL1_VERSION")
    assert bl1_ver == 0, (
        f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check would "
        f"reject a slot for a reason this testcase does not plant"
    )
    revoke = image.field_int("CHIPLET_PUBK_REVOKE")
    assert revoke == 0, (
        f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: the shipped manifests "
        f"select ROM key slot 0 and a revocation would refuse both slots"
    )


def plant_device_id_defect(buf: bytearray, slot: str, kind: str,
                           selector_mask: int) -> int:
    # Returns the lowest enabled word: the ROM rejects on the first mismatch.
    if kind not in _DEVICE_ID_TOKENS:
        raise ValueError(f"kind must be chiplet_id or package_id, got {kind!r}")
    if not 1 <= selector_mask <= 0xFF:
        raise ValueError("selector_mask must be a non-zero 8-bit mask")
    # Verify the arrays hold the shipped value before enabling the ROM to read them.
    mm.verify_device_id_layout(buf, slot)
    base_bit = _DEVICE_ID_SELECTOR_BASE[kind]
    for i in range(mm.DEVICE_ID_NUM_WORDS):
        if selector_mask & (1 << i):
            mm.set_selector_bit(buf, slot, base_bit + i, True)
    return (selector_mask & -selector_mask).bit_length() - 1


def device_id_tokens(kind: str) -> tuple[str, str, str]:
    # CID/PID prefixes cannot be derived from the field name; a built token silently never matches.
    return _DEVICE_ID_TOKENS[kind]


def device_id_required_markers(kind: str, reject_index: int) -> tuple[str, ...]:
    # *_FUSE= is omitted: the flat SMC memory model serves that value, so it is not asserted.
    idx_token, _fuse_token, mfst_token = _DEVICE_ID_TOKENS[kind]
    return (
        _DEVICE_ID_MARKER[kind],
        f"{idx_token}0x{reject_index:08x}",
        f"{mfst_token}0x{mm.SHIPPED_DEVICE_ID_WORD:08x}",
    )


def assert_device_id_mismatch(logger, console: list[str], kind: str,
                              reject_index: int) -> None:
    idx_token, fuse_token, mfst_token = _DEVICE_ID_TOKENS[kind]
    fuse = hex_value(console, fuse_token)
    mfst = hex_value(console, mfst_token)
    idx = hex_value(console, idx_token)
    assert fuse is not None and mfst is not None and idx is not None, (
        f"ROM did not echo all of {idx_token} / {fuse_token} / {mfst_token}, so "
        f"the {kind} comparison cannot be read back. Console: {console}"
    )
    assert idx == reject_index, (
        f"{idx_token}0x{idx:08x} but the planted selector mask makes word "
        f"{reject_index} the lowest enabled one: the ROM did not map selector "
        f"bits to array words the way this stimulus assumes"
    )
    assert mfst == mm.SHIPPED_DEVICE_ID_WORD, (
        f"{mfst_token}0x{mfst:08x}, expected the shipped "
        f"0x{mm.SHIPPED_DEVICE_ID_WORD:08x}: the ROM did not read the word this "
        f"testcase enabled"
    )
    assert fuse != mfst, (
        f"{fuse_token}0x{fuse:08x} equals {mfst_token}0x{mfst:08x}: the fuse map "
        f"served the same value the manifest declares, so the constraint was "
        f"satisfied and this testcase proves nothing about its rejection"
    )
    assert count(console, fuse_token) == 1, (
        f"{fuse_token} appeared more than once; the check returns on the first "
        f"mismatch, so a second read means another slot was also refused here. "
        f"Console: {console}"
    )
    logger.info(
        "CHK-DEVICE-ID: %s word %d -- manifest 0x%08x vs fuse 0x%08x, refused",
        kind, idx, mfst, fuse,
    )


def plant_lc_state_defect(buf: bytearray, slot: str, allowed: int) -> None:
    mm.verify_usage_constraints_layout(buf, slot)
    assert mm.selector_bits(buf, slot) & (1 << mm.SELECTOR_BIT_LIFE_CYCLE_STATES), (
        "selector_bits bit 16 is clear, so the ROM would skip the lifecycle "
        "usage-constraint check entirely and this stimulus would be inert"
    )
    mm.set_life_cycle_states(buf, slot, allowed)


def lc_state_required_markers(allowed: int, live_bit: int) -> tuple[str, ...]:
    return (LC_MARKER, f"LC_ALLOWED=0x{allowed:08x}", f"LC_BIT=0x{live_bit:08x}")
