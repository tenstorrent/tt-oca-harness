# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DV-owned eFuse field map.

Write-policy and ``SECURE_TM`` membership come from ``_FIELD_ROWS``
(``hw/sys/sep/doc/otp_fuse_controller.adoc`` fuse-field table). Offsets and widths
come from the generated RDL header. The set-only, lock, and writable
walks together cover every row except ``LC_STATE``. ``LOCK`` is walked
only when both RDL windows (``LOCKS`` and ``LOCKS_SPARE``) are written.
``REQUIRED_SIGNERS`` is writable and is not on the ``SecureTmLock``
list.
"""

from __future__ import annotations

from dataclasses import dataclass

# Walk pins that are not write-policy. DIS word 0 carries sep_debug,
# chiplet_dbg, the fuse-dbg bits and sip_debug. Assigned LOCK slots lock a
# field this sweep still writes, so those bits stay 0 until the lock walk.
# LC_STATE used bits are the lifecycle nibble; the LC W1S leaves own them.
_DIS_FUNCTION_GROUP = (0xFFFF_0000, 1)
# LOCKS_SPARE: slots 32-40 in [17:0], slots 41-47 unassigned in [31:18].
_LOCK_ASSIGNED = 0x0003_FFFF
_LOCK_UNASSIGNED = 0xFFFC_0000
_SWEEP_EXCLUDE = frozenset({"LC_STATE", "LOCK"})


@dataclass(frozen=True)
class SpecField:
    """One DV-owned fuse-field row."""

    spec_name: str
    reg_name: str
    spec_index: int
    width_bits: int
    used_bits: int
    set_only: bool

    @property
    def word_used_mask(self) -> int:
        n = min(self.used_bits, 32)
        return (1 << n) - 1


# From hw/sys/sep/doc/otp_fuse_controller.adoc [[fuse-fields]].
# (spec_name, reg_name, index, width_bits, used_bits, set_only)
_FIELD_ROWS = (
    ("LOCK", "LOCKS", 0, 96, 96, True),
    ("LC_STATE", "LC_STATE", 1, 32, 4, True),
    ("SBOOT_DIS", "SBOOT_DIS", 2, 32, 1, False),
    ("TRANS_RMA_EN", "TRANSIENT_RMA_EN", 3, 32, 1, False),
    ("SIP_DIS", "SIP_DIS", 4, 64, 64, True),
    ("SYS_DIS", "SYS_DIS", 5, 64, 64, True),
    ("RMA_SIP_TOKEN_DIGEST", "RMA_SIP_TOKEN_DIGEST", 6, 256, 256, False),
    ("RMA_CHIPLET_TOKEN_DIGEST", "RMA_CHIPLET_TOKEN_DIGEST", 7, 256, 256, False),
    ("CLASS_KEY", "CLASS_KEY", 8, 256, 256, False),
    ("CHIPLET_PUBK_REVOKE", "CHIPLET_PUBK_REVOKE", 9, 32, 32, True),
    ("BL1_VERSION", "BL1_VERSION", 10, 256, 256, True),
    ("BL2_VERSION", "BL2_VERSION", 11, 256, 256, True),
    ("CHIPLET_UID", "CHIPLET_UID", 12, 256, 256, False),
    ("SIP_PUBK_HASH0", "SIP_PUBK_HASH0", 13, 256, 256, False),
    ("SIP_UID", "SIP_UID", 14, 256, 256, False),
    ("SYS_PUBK_HASH", "SYS_PUBK_HASH", 15, 256, 256, False),
    ("SYS_UID", "SYS_UID", 16, 256, 256, False),
    ("STATUS_RPT", "STATUS_RPT", 17, 32, 2, False),
    ("ROM_CTL", "ROM_CTL", 18, 32, 32, False),
    ("SYSCLK_FREQ_MHZ", "SYSCLK_FREQ_MHZ", 19, 32, 11, False),
    ("CHIPLET_PUBK_HASH0", "CHIPLET_PUBK_HASH0", 20, 256, 256, False),
    ("CHIPLET_PUBK_HASH1", "CHIPLET_PUBK_HASH1", 21, 256, 256, False),
    ("REQUIRED_SIGNERS", "REQUIRED_SIGNERS", 22, 32, 2, False),
    ("REQUIRED_ALGS", "REQUIRED_ALGS", 23, 32, 12, True),
    ("CHIPLET_PUBK_PQC_HASH0", "CHIPLET_PUBK_PQC_HASH0", 24, 256, 256, False),
    ("CHIPLET_PUBK_PQC_HASH1", "CHIPLET_PUBK_PQC_HASH1", 25, 256, 256, False),
    ("SIP_PUBK_PQC_HASH0", "SIP_PUBK_PQC_HASH0", 26, 256, 256, False),
    ("SYS_PUBK_PQC_HASH", "SYS_PUBK_PQC_HASH", 27, 256, 256, False),
    ("SIP_PUBK_HASH1", "SIP_PUBK_HASH1", 28, 256, 256, False),
    ("SIP_PUBK_PQC_HASH1", "SIP_PUBK_PQC_HASH1", 29, 256, 256, False),
    ("SEP_CHIPLET_ID", "SEP_CHIPLET_ID", 30, 256, 256, False),
    ("SEP_SIP_ID", "SEP_SIP_ID", 31, 256, 256, False),
    ("SEP_SYS_ID", "SEP_SYS_ID", 32, 256, 256, False),
    ("spare0", "SPARE0", 33, 256, 256, False),
    ("spare1", "SPARE1", 34, 256, 256, False),
    ("spare2", "SPARE2", 35, 256, 256, False),
    ("spare3", "SPARE3", 36, 256, 256, False),
    ("spare4", "SPARE4", 37, 256, 256, False),
    ("spare5", "SPARE5", 38, 256, 256, False),
    ("spare6", "SPARE6", 39, 256, 256, False),
    ("spare7", "SPARE7", 40, 256, 256, False),
    ("spare8", "SPARE8", 41, 256, 256, False),
)

NUM_FUSE_BITS = 8192
SECRET_REGS = ("CHIPLET_UID", "SIP_UID", "SYS_UID", "CLASS_KEY")
SECURE_TM_BLOCKED = ("LOCKS", "LOCKS_SPARE", "LC_STATE", "SIP_DIS", "SYS_DIS")


def spec_fields() -> tuple[SpecField, ...]:
    return tuple(SpecField(*row) for row in _FIELD_ROWS)


def spec_secure_tm_blocked() -> tuple[str, ...]:
    return SECURE_TM_BLOCKED


def spec_num_fuse_bits() -> int:
    return NUM_FUSE_BITS


def spec_secret_regs() -> tuple[str, ...]:
    return SECRET_REGS


def spec_set_only_walk() -> tuple[tuple[str, int, int | None], ...]:
    """Set-only rows other than ``LOCK`` and ``LC_STATE``.

    ``LOCK`` is ``spec_lock_walk``: both RDL windows, after the other rows.
    """
    out: list[tuple[str, int, int | None]] = []
    for field in spec_fields():
        if not field.set_only or field.spec_name in _SWEEP_EXCLUDE:
            continue
        if field.reg_name in ("SIP_DIS", "SYS_DIS"):
            mask, pin = _DIS_FUNCTION_GROUP
            out.append((field.reg_name, mask, pin))
        else:
            out.append((field.reg_name, field.word_used_mask, None))
    return tuple(out)


def spec_lock_walk() -> tuple[tuple[str, int, int, int, int], ...]:
    """``LOCK`` as both RDL windows.

    Each cell is ``(rdl_name, used_mask, word_idx, sensed_mask, set_mask)``.
    Assigned slots stay 0 at sense. ``LOCKS_SPARE`` stages ones only in the
    unassigned half; the assigned half is set from zero after the other
    rows finish.
    """
    return (
        ("LOCKS", 0xFFFF_FFFF, 0, 0, 0xFFFF_FFFF),
        ("LOCKS", 0xFFFF_FFFF, 1, 0, 0xFFFF_FFFF),
        (
            "LOCKS_SPARE",
            0xFFFF_FFFF,
            0,
            _LOCK_UNASSIGNED,
            _LOCK_ASSIGNED,
        ),
    )


def spec_writable_shadow_walk() -> tuple[tuple[str, int], ...]:
    """Every ``otp_fuse_controller.adoc`` SW-writable ``true`` row (not set-only)."""
    return tuple(
        (field.reg_name, field.word_used_mask) for field in spec_fields() if not field.set_only
    )


def spec_walked_rows() -> frozenset[str]:
    """Specification field names reached by the set-only, lock, or writable walk.

    ``LOCK`` is counted only when both ``LOCKS`` and ``LOCKS_SPARE`` are in
    the lock walk. A spare-only substitute does not count.
    """
    rdl_to_spec = {f.reg_name: f.spec_name for f in spec_fields()}
    names = {rdl_to_spec[n] for n, _, _ in spec_set_only_walk()}
    names.update(rdl_to_spec[n] for n, _ in spec_writable_shadow_walk())
    lock_rdl = {n for n, *_ in spec_lock_walk()}
    if {"LOCKS", "LOCKS_SPARE"} <= lock_rdl:
        names.add("LOCK")
    return frozenset(names)


def _selftest() -> None:
    fields = spec_fields()
    assert len(fields) == 42, f"DV-owned map has {len(fields)} rows, want 42"
    by_reg = {f.reg_name: f for f in fields}
    assert by_reg["REQUIRED_SIGNERS"].set_only is False
    assert "REQUIRED_SIGNERS" not in SECURE_TM_BLOCKED
    assert by_reg["REQUIRED_ALGS"].set_only is True
    assert by_reg["SYSCLK_FREQ_MHZ"].used_bits == 11
    assert "SEP_SPI_CTRL_FIELD_EN" not in by_reg
    assert spec_num_fuse_bits() == 8192
    assert spec_secret_regs() == SECRET_REGS
    walk = spec_set_only_walk()
    assert [n for n, _, _ in walk] == [
        "SIP_DIS",
        "SYS_DIS",
        "CHIPLET_PUBK_REVOKE",
        "BL1_VERSION",
        "BL2_VERSION",
        "REQUIRED_ALGS",
    ]
    lock = spec_lock_walk()
    assert [n for n, *_ in lock] == ["LOCKS", "LOCKS", "LOCKS_SPARE"]
    assert {n for n, *_ in lock} == {"LOCKS", "LOCKS_SPARE"}
    assert lock[0][2] == 0 and lock[1][2] == 1
    assert lock[2][3] == _LOCK_UNASSIGNED and lock[2][4] == _LOCK_ASSIGNED
    writable = spec_writable_shadow_walk()
    assert len(writable) == 34
    assert dict(writable)["REQUIRED_SIGNERS"] == 0x3
    assert dict(writable)["SYSCLK_FREQ_MHZ"] == 0x7FF
    assert dict(writable)["SPARE8"] == 0xFFFF_FFFF
    assert spec_walked_rows() == {f.spec_name for f in fields} - {"LC_STATE"}


_selftest()
