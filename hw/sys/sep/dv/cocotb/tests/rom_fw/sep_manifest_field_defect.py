# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Stimulus and console evidence for the manifest-field and usage-constraint defects.

This family plants one bad manifest field and asks
which check refuses it. Two things about this ROM decide the shape of every
testcase in that group, and both are established here once rather than restated
in ten modules.

**THE STRUCTURAL CHECKS EMIT NO PER-REASON CONSOLE TOKEN.**
``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) returns
``MANIFEST_ERR_BAD_MAGIC`` / ``_BAD_VERSION`` / ``_BAD_LENGTH`` without printing
anything of its own, and the four status codes that would name them --
``SEP_MSG_INVALID_MANIFEST_ID``, ``_INVALID_MANIFEST_VERSION``,
``_INVALID_MANIFEST_LENGTH``, ``_MANIFEST_TOO_LONG`` -- are *defined* in
``bootrom/prod/include/status_values.h`` and emitted by nothing under
``bootrom/prod/src``. So the only per-reason evidence for a structural rejection
is the error code in ``MANIFEST_ERR=``, and a testcase must pin its slot by
ORDER (which ``MANIFEST_SRC=`` preceded it) and by COUNT (exactly one slot
produced it). :func:`assert_slot_attributed` is that check.

**THE THREE USAGE-CONSTRAINT VERDICTS SHARE ONE ERROR CODE AND ARE SEPARABLE
ONLY ON THE CONSOLE.** Lifecycle, chiplet_id and package_id all return
``MANIFEST_ERR_LC_USAGE_CONSTRAINT`` (``manifest_load.c``), so asserting the code
alone would make the six chiplet/package/lifecycle testcases interchangeable.
Each arm does print a distinct token, and :data:`SIBLING_MARKERS` is what lets a
member require its own and forbid the other two.

A FOURTH site returns the same code: the encrypted-payload-without-secure-boot
rejection just ahead of the block, which prints ``ENC_WITHOUT_SBOOT``. It is
unreachable for these testcases -- the shipped image is not encrypted and the
bases assert ``SBOOT_DIS`` is clear -- and it prints a token none of the three
members requires, so it cannot satisfy one of them. It is named here because the
"three arms" framing is what justifies the whole sibling-forbid design, and the
framing should not hide a fourth emitter.

**WHY A DEVICE-ID TESTCASE PLANTS ONLY A SELECTOR BIT.** The shipped image
already carries ``0xa5a5a5a5`` in all eight ``chiplet_id`` and all eight
``package_id`` words with both selectors clear
(``bootrom/prod/configs/secure_boot_test.yaml``), which is the same value the
reference writes as its invalid device ID. The ROM reads a word only when its
selector bit is set, so setting the bit is the whole stimulus and the array needs
no write. ``sep_manifest_mutate.verify_device_id_layout`` anchors that claim
against the real bytes, because a wrong offset would enable a comparison against
something nobody chose and the ROM would still reject the slot.
"""

from __future__ import annotations

import pathlib
import re

from env import sep_manifest_mutate as mm
from env import sep_spi_slot_evidence as ev

PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# manifest_load.c -- the discriminating token of each usage-constraint arm.
LC_MARKER = "LC_USAGE_CONSTRAINT_FAIL"
CHIPLET_MARKER = "CHIPLET_ID_MISMATCH"
PACKAGE_MARKER = "PACKAGE_ID_MISMATCH"

_USAGE_MARKERS = (LC_MARKER, CHIPLET_MARKER, PACKAGE_MARKER)

# The other two arms' tokens, for a member's forbidden list. Requiring one of
# three markers proves which arm complained; forbidding the other two is what
# stops a member from being satisfied by a sibling's evidence.
SIBLING_MARKERS = {
    marker: tuple(m for m in _USAGE_MARKERS if m != marker)
    for marker in _USAGE_MARKERS
}

# manifest_load.c: the per-arm echoes, in emission order.
_DEVICE_ID_TOKENS = {
    "chiplet_id": ("CID_IDX=", "CID_FUSE=", "CID_MFST="),
    "package_id": ("PID_IDX=", "PID_FUSE=", "PID_MFST="),
}
_DEVICE_ID_MARKER = {"chiplet_id": CHIPLET_MARKER, "package_id": PACKAGE_MARKER}
_DEVICE_ID_SELECTOR_BASE = {
    "chiplet_id": mm.SELECTOR_BIT_CHIPLET_ID_BASE,
    "package_id": mm.SELECTOR_BIT_PACKAGE_ID_BASE,
}


# --- console helpers -------------------------------------------------------
def first_index(console: list[str], marker: str, after: int = -1) -> int:
    """Index of the first console line past ``after`` containing ``marker``, or -1.

    ``after`` exists for the markers a two-slot run prints twice: the caller wants
    a specific slot's occurrence, and "the first one" is the other slot's. The
    default searches from the start, so an existing caller is unaffected.
    """
    for i, line in enumerate(console):
        if i > after and marker in line:
            return i
    return -1


def count(console: list[str], marker: str) -> int:
    return sum(1 for line in console if marker in line)


def hex_value(console: list[str], token: str) -> int | None:
    """The value the ROM echoed after ``token``, e.g. ``CID_FUSE=0x...``.

    Returns None when the token never appeared, so a caller can tell "the ROM
    did not print this" apart from "the ROM printed zero".
    """
    pattern = re.compile(re.escape(token) + r"0x([0-9a-fA-F]{8})")
    for line in console:
        found = pattern.search(line)
        if found:
            return int(found.group(1), 16)
    return None


def assert_slot_attributed(console: list[str], marker: str, *, after: int,
                           before: int, expected_count: int = 1) -> int:
    """Prove ``marker`` is one slot's verdict, by position and by count.

    ``after`` and ``before`` bracket the slot attempt: the marker has to sit
    inside it. The count is the other half -- a token that also appeared on the
    other slot would satisfy the position check while meaning something else, and
    for the structural defects there is no per-reason token at all, so the
    ``MANIFEST_ERR=`` code is carrying the whole attribution.
    """
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
    """Cross-check ``sep_manifest_mutate.MANIFEST_MAX_SIZE`` against the ROM header.

    ``MANIFEST_MAX_SIZE`` is hand-copied into the Python mirror, and a testcase that
    picks its stimulus relative to that bound is only as correct as the copy. The
    failure mode is silent in one direction: raise the C value alone and a length
    chosen to be ABOVE the bound quietly becomes a legal length, so a testcase that
    asserts "this value is out of range" keeps passing while measuring nothing. Read
    the define back out of the header and require agreement, so that divergence is
    loud at the first testcase that depends on it.

    Returns the value parsed from the header, so a caller can log its provenance.
    """
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
    """Indices of the flash reads whose COMMAND address is exactly ``addr``.

    "Did the ROM issue a fetch at this address" must be asked of the read's own
    start, not of the span it covers. ``ocah_spi_flash._do_read`` streams bytes until
    CS deasserts, so ``data_out`` carries one byte more than the controller asked
    for, and every recorded span therefore ends one byte past the request. A
    1184-byte manifest read at ``base`` is recorded as ``base..base+1185`` and so
    COVERS ``base + 1184`` -- the very address the manifest-extension fetch would
    start at. A coverage predicate cannot separate the two; the start address can.
    """
    rds = ev.reads(flash.get_transactions())
    return [i for i, t in enumerate(rds) if ev.read_span(t)[0] == addr]


def assert_no_read_starting_at(logger, flash, addr: int, why: str) -> None:
    """Require that the ROM issued NO flash read beginning at ``addr``.

    The negative counterpart of :func:`assert_served_field`, and unlike it this one
    IS a claim about the ROM's behaviour rather than about the transport: the ROM
    issues a read only when it decided to, so the absence of one is evidence that
    the decision under test went the other way.
    """
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
    """Require the flash DEVICE to have returned ``expected`` for one manifest field.

    The offline artefact check proves what was STAGED; between it and the ROM sit
    the flash BFM and the whole SPI/DMA transport. This is the DUT-side half, and it
    is the only run-time channel on which two testcases can differ when the ROM's
    console cannot separate them -- two structural rejections that share one error
    code, or a stimulus bit the ROM never reads.

    The field must be covered by a SINGLE read. The ROM fetches the whole 1184-byte
    manifest in one transaction, so it is; if the transport ever splits a field
    across two reads, the fix is to stitch the reads rather than drop the check.
    """
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
    """No OTP-side reason for a slot to be refused by the crypto chain.

    Every defect in this group is refused inside the manifest loop, ahead of
    ``manifest_crypto_validate``. A non-zero ``BL1_VERSION`` or a set
    ``CHIPLET_PUBK_REVOKE`` bit would give the run a second, earlier reason to
    reject a slot -- and on the primary-side members it would also stop the
    backup from booting, turning a failover testcase into a terminal one with a
    verdict that belongs to a different check.
    """
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


# --- device-id stimulus ----------------------------------------------------
def plant_device_id_defect(buf: bytearray, slot: str, kind: str,
                           selector_mask: int) -> int:
    """Enable the selected ``chiplet_id`` / ``package_id`` words for one slot.

    Returns the index the ROM must reject on: its check loops from word 0 and
    returns on the first mismatch (``manifest_load.c``), and every enabled word
    holds the same mismatching value, so that is the lowest set bit of the mask.
    """
    if kind not in _DEVICE_ID_TOKENS:
        raise ValueError(f"kind must be chiplet_id or package_id, got {kind!r}")
    if not 1 <= selector_mask <= 0xFF:
        raise ValueError("selector_mask must be a non-zero 8-bit mask")
    # Anchor the arrays BEFORE touching the selector: the whole stimulus is
    # "make the ROM read words it was ignoring", which is only that if the words
    # really hold what this module claims.
    mm.verify_device_id_layout(buf, slot)
    base_bit = _DEVICE_ID_SELECTOR_BASE[kind]
    for i in range(mm.DEVICE_ID_NUM_WORDS):
        if selector_mask & (1 << i):
            mm.set_selector_bit(buf, slot, base_bit + i, True)
    return (selector_mask & -selector_mask).bit_length() - 1


def device_id_tokens(kind: str) -> tuple[str, str, str]:
    """The ``*_IDX=`` / ``*_FUSE=`` / ``*_MFST=`` tokens one device-id arm echoes.

    The prefix is ``CID``/``PID`` (``manifest_load.c``) and cannot be derived from
    the field name, so a caller that needs one token has to read it from here
    rather than build it. A built token silently never matches, which turns
    :func:`hex_value` into ``None`` and any assertion resting on it into a crash
    or a pass.
    """
    return _DEVICE_ID_TOKENS[kind]


def device_id_required_markers(kind: str, reject_index: int) -> tuple[str, ...]:
    """Console lines a device-id rejection must produce.

    ``*_FUSE=`` is deliberately absent: the fuse map is served by the testbench's
    flat SMC memory model, so its VALUE is not this testbench's to assert. What
    is asserted is that the ROM read it and found it different from the
    manifest's -- see :func:`assert_device_id_mismatch`.
    """
    idx_token, _fuse_token, mfst_token = _DEVICE_ID_TOKENS[kind]
    return (
        _DEVICE_ID_MARKER[kind],
        f"{idx_token}0x{reject_index:08x}",
        f"{mfst_token}0x{mm.SHIPPED_DEVICE_ID_WORD:08x}",
    )


def assert_device_id_mismatch(logger, console: list[str], kind: str,
                              reject_index: int) -> None:
    """The ROM read the selected fuse word and refused the manifest's copy.

    The pair is the point. ``*_MFST=`` alone is the stimulus echoed back, and a
    testbench that asserted ``*_FUSE=`` against a hardcoded number would be
    asserting its own memory model. Requiring the two to DIFFER is the part that
    belongs to the ROM: it is the comparison ``manifest_load.c`` performs, and it
    cannot pass on a run where the two agreed.

    ONE CARVE-OUT. ``sep_device_id_variation_base`` does assert the ``*_FUSE=``
    value, because it plants a MATCHING word and therefore depends on which value
    the model serves. That family states the dependency rather than hiding it; the
    rule above still holds for every row that only needs a mismatch.
    """
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


# --- lifecycle stimulus ----------------------------------------------------
def plant_lc_state_defect(buf: bytearray, slot: str, allowed: int) -> None:
    """Narrow ``life_cycle_states`` so the LIVE lifecycle is not permitted.

    The selector bit is already set in the shipped image, so unlike the device-id
    arms this is a value change rather than an enable. The bitmap keeps the two
    states the part is NOT in, which is what makes the rejection specific to the
    live one instead of to an empty bitmap that would refuse everything.
    """
    mm.verify_usage_constraints_layout(buf, slot)
    assert mm.selector_bits(buf, slot) & (1 << mm.SELECTOR_BIT_LIFE_CYCLE_STATES), (
        "selector_bits bit 16 is clear, so the ROM would skip the lifecycle "
        "usage-constraint check entirely and this stimulus would be inert"
    )
    mm.set_life_cycle_states(buf, slot, allowed)


def lc_state_required_markers(allowed: int, live_bit: int) -> tuple[str, ...]:
    """Console lines a lifecycle usage-constraint rejection must produce.

    ``LC_BIT=`` is the strongest line here: it is
    ``lc_state_to_manifest_bit(lc_state)`` (``bootrom/prod/src/lifecycle.c``), so
    requiring the live state's bit proves the ROM decoded the OTP lifecycle
    rather than refusing an unreadable bitmap.
    """
    return (LC_MARKER, f"LC_ALLOWED=0x{allowed:08x}", f"LC_BIT=0x{live_bit:08x}")
