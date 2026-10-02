# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus and console evidence for the manifest-field and usage-constraint defects.

The OCA ROM prints no per-reason token for these checks, so testcases attribute a
refusal by slot order and the ``MANIFEST_ERR=`` code.
"""

from __future__ import annotations

import re
import struct

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev

PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"


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


def assert_slot_attributed(
    console: list[str], marker: str, *, after: int, before: int, expected_count: int = 1
) -> int:
    i = first_index(console, marker)
    assert after < i < before, (
        f"{marker}@{i} does not sit between line {after} and line {before}: it "
        f"is not attributable to the slot under test. Console: {console}"
    )
    n = count(console, marker)
    assert n == expected_count, (
        f"{marker} appeared {n} times, expected exactly {expected_count}. Console: {console}"
    )
    return i


def assert_consumer_body_size(buf: bytes | None = None, slot: str = "primary") -> int:
    # A packer/consumer drift would make an off-by-k manifest_length legal.
    assert mm.BODY_SIZE == mm.CONSUMER_BODY_SIZE, (
        f"the packer's body size is {mm.BODY_SIZE} but the consumer's "
        f"OCA_CLASSIC_BODY_SIZE is {mm.CONSUMER_BODY_SIZE}; every length stimulus "
        f"chosen relative to one of them is addressing the wrong bound"
    )
    if buf is not None:
        declared = mm.manifest_length(buf, slot)
        assert declared == mm.CONSUMER_BODY_SIZE, (
            f"{slot} declares manifest_length {declared}, not the body size "
            f"{mm.CONSUMER_BODY_SIZE}: the slot is already mutated, so a length "
            f"stimulus on it would not be the only defect"
        )
    return mm.CONSUMER_BODY_SIZE


def plant_manifest_length(logger, buf: bytearray, slot: str, *, minor: int, length: int) -> bytes:
    body = assert_consumer_body_size(buf, slot)
    before = mm.manifest_version(buf, slot)
    assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
        f"{slot} manifest version is {before[0]}.{before[1]}, expected "
        f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the baseline to mutate"
    )
    base = mm.slot_base(slot)
    assert bytes(buf[base : base + 4]) == mm.MANIFEST_MAGIC, (
        f"{slot} magic is not OCAC, so OCA_FAIL_MAGIC would preempt the length check"
    )
    # The major stays valid so FORMAT_VERSION_MISMATCH cannot preempt the length check.
    if minor:
        mm.set_manifest_version(buf, slot, minor=minor)
    if length != body:
        mm.set_manifest_length(buf, slot, length)
    after = (*mm.manifest_version(buf, slot), mm.manifest_length(buf, slot))
    assert after == (mm.MANIFEST_MAJOR_VERSION, minor, length), (
        f"{slot} declares {after} after the write, expected "
        f"{(mm.MANIFEST_MAJOR_VERSION, minor, length)}; the mutation did not land"
    )
    logger.info(
        "CHK-STIMULUS-LENGTH: %s v%d.0/%d -> v%d.%d/%d against body size %d (%+d)",
        slot,
        mm.MANIFEST_MAJOR_VERSION,
        body,
        mm.MANIFEST_MAJOR_VERSION,
        minor,
        length,
        body,
        length - body,
    )
    return struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, minor, length)


def reads_starting_at(flash, addr: int) -> list[int]:
    # Match the read's start: the flash BFM records one byte past each request, so spans over-cover.
    rds = ev.reads(flash.get_transactions())
    return [i for i, t in enumerate(rds) if ev.read_span(t)[0] == addr]


def assert_no_read_starting_at(logger, flash, addr: int, why: str) -> None:
    hits = reads_starting_at(flash, addr)
    spans = [
        f"0x{s:x}..0x{e:x}"
        for s, e in (ev.read_span(t) for t in ev.reads(flash.get_transactions()))
    ]
    assert not hits, (
        f"read(s) {hits} began at 0x{addr:x}, which must not happen: {why}. Read spans: {spans}"
    )
    logger.info(
        "CHK-NO-READ: no SPI read began at 0x%06x -- %s. Read spans: %s",
        addr,
        why,
        spans,
    )


def assert_served_field(logger, flash, slot: str, offset: int, expected: bytes, what: str) -> None:
    # One read must cover the field: the split peek read can straddle it, the body read cannot.
    addr = mm.slot_base(slot) + offset
    hit = next(
        (
            (i, t)
            for i, t in enumerate(ev.reads(flash.get_transactions()))
            if ev.read_span(t)[0] <= addr and addr + len(expected) <= ev.read_span(t)[1]
        ),
        None,
    )
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
        "the planted bytes",
        idx,
        got.hex(),
        what,
        addr,
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
