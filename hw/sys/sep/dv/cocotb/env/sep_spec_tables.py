# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DV-owned apertures, PIC IDs, and mailbox constants.

``WINDOWS``, ``PIC``, mailbox sentinels, and ``OUTPUT_REMAP_REGIONS`` are
the expectation. ABR offsets come from ``abr_reg.rdl``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_REPO = Path(__file__).resolve().parents[6]
_ABR_RDL = (
    _REPO
    / "vendor"
    / "chipsalliance"
    / "adams-bridge"
    / "upstream"
    / "src"
    / "abr_top"
    / "rtl"
    / "abr_reg.rdl"
)

_ABR_CLOSE = re.compile(
    r"^    \} ([A-Za-z0-9_]+)(?:\[(\d+)\])?(?:\s*@(0x[0-9A-Fa-f]+))?;",
    re.M,
)
_ABR_NAMED = re.compile(
    r"^    (\w+)\s+(\w+)(?:\s*@(0x[0-9A-Fa-f]+))?;",
    re.M,
)


@dataclass(frozen=True)
class MapWindow:
    """One aperture. Inclusive ``end`` except SEP Local Alias (exclusive)."""

    unit: str
    base: int
    end: int
    size: int


# From hw/sys/sep/doc/memory_map.adoc.
WINDOWS = {
    "SEP Local Alias": MapWindow("SEP Local Alias", 0xD000_0000, 0x1_0000_0000, 0x3000_0000),
    "ABR": MapWindow("ABR", 0x1094_0000, 0x1094_FFFF, 0x1_0000),
    "EPOOL": MapWindow("EPOOL", 0x1095_0000, 0x1095_FFFF, 0x1_0000),
    "AP Remap Region": MapWindow("AP Remap Region", 0x1100_0000, 0x117F_FFFF, 0x80_0000),
    "STEE Remap Region": MapWindow("STEE Remap Region", 0x1180_0000, 0x11FF_FFFF, 0x80_0000),
}

# From hw/sys/sep/doc/interrupts.adoc. 1-based PIC source.
PIC = {
    "KM mailbox IRQ": 15,
    "HMAC done": 18,
    "KMAC done": 21,
    "CSRNG command request done": 24,
    "CSRNG entropy request": 25,
    "CSRNG HW instance exception": 26,
    "CSRNG fatal error": 27,
    "EDN command request done": 28,
    "EDN fatal error": 29,
    "Adams Bridge error": 35,
    "Adams Bridge notification": 36,
    "Entropy pool low": 37,
    "Entropy pool fill stall": 38,
    "DMA register-path bus error": 41,
    "DMA host-path integrity/bus fault": 42,
    "Peripheral register-bridge fault": 43,
}

# From hw/ip/axi_lite_mailbox_unit/doc/{architecture,interface}.adoc.
MAILBOX_DEPTH = 8
MAILBOX_EMPTY_SENTINEL = 0xFEEDDEAD
MAILBOX_WRITE_DATA_RD_SENTINEL = 0xFEEDC0DE

# From hw/sys/sep/doc/fabric.adoc ("Sixteen remap regions").
OUTPUT_REMAP_REGIONS = 16

# DV-owned BIW lane packing: out[i] = (b[i] * b[i+4]) + b[i+8]; out[0] is MSB.
BIW_TRIPLES = ((0, 4, 8), (1, 5, 9), (2, 6, 10), (3, 7, 11))
BIW_OUT_SHIFTS = (24, 16, 8, 0)

# KMAC / SHA-3 walk set. SHA-3 strengths and digest sizes are FIPS 202.
# SHAKE / cSHAKE accept 128 and 256 only (kmac.adoc / kmac.rdl kstrength).
# Keyed KMAC is cSHAKE plus kmac_en (kmac.adoc). KEY_LEN is a 3-bit choice
# with no RDL enum; the five widths below are the DV-owned walk.
KMAC_SHA3_STRENGTHS = (224, 256, 384, 512)
KMAC_SHA3_DIGEST_BYTES = {224: 28, 256: 32, 384: 48, 512: 64}
KMAC_XOF_STRENGTHS = (128, 256)
KMAC_KEY_LENGTHS = (128, 192, 256, 384, 512)


def window(unit: str) -> MapWindow:
    try:
        return WINDOWS[unit]
    except KeyError as exc:
        raise KeyError(f"{unit!r} missing from the DV-owned memory-map table") from exc


def pic(source: str) -> int:
    try:
        return PIC[source]
    except KeyError as exc:
        raise KeyError(f"{source!r} missing from the DV-owned PIC table") from exc


def agg_from_pic(source: str) -> int:
    """Aggregator bit = documented 1-based PIC source minus 1."""
    return pic(source) - 1


def mailbox_depth() -> int:
    return MAILBOX_DEPTH


def mailbox_empty_sentinel() -> int:
    return MAILBOX_EMPTY_SENTINEL


def mailbox_write_data_rd_sentinel() -> int:
    return MAILBOX_WRITE_DATA_RD_SENTINEL


def fabric_output_remap_regions() -> int:
    return OUTPUT_REMAP_REGIONS


def mldsa_name_words(label: str = "MLDSA-87") -> tuple[int, int]:
    """NAME registers: 8-char ASCII, each 32-bit word half-word swapped.

    crypto.adoc names ML-DSA-87. Caliptra NAME endian stores each
    four-character group as a 16-bit-swapped word.
    """
    raw = label.encode("ascii")
    if len(raw) != 8:
        raise ValueError(f"NAME label must be 8 ASCII chars, got {label!r}")

    def word(chunk: bytes) -> int:
        x = int.from_bytes(chunk, "big")
        return ((x & 0xFFFF) << 16) | (x >> 16)

    return word(raw[:4]), word(raw[4:])


@lru_cache(maxsize=1)
def abr_offsets() -> dict[str, int]:
    """CSR offsets from ``abr_reg.rdl``."""
    text = _ABR_RDL.read_text(encoding="utf-8")
    off = 0
    out: dict[str, int] = {}
    for m in _ABR_CLOSE.finditer(text):
        name, count, at = m.group(1), m.group(2), m.group(3)
        n = int(count) if count else 1
        prefix = text[: m.start()]
        last_mem = prefix.rfind("external mem")
        last_reg = max(prefix.rfind("    reg {"), prefix.rfind("    external reg"))
        is_mem = last_mem > last_reg
        mem_body = prefix[last_mem:] if is_mem else ""
        if at:
            addr = int(at, 16)
        elif is_mem:
            entries = int(re.search(r"mementries\s*=\s*(\d+)", mem_body).group(1))
            width = int(re.search(r"memwidth\s*=\s*(\d+)", mem_body).group(1))
            size = entries * (width // 8)
            align = 1 << (size - 1).bit_length()
            addr = (off + align - 1) & ~(align - 1)
        else:
            addr = off
        out[name] = addr
        if is_mem:
            entries = int(re.search(r"mementries\s*=\s*(\d+)", mem_body).group(1))
            width = int(re.search(r"memwidth\s*=\s*(\d+)", mem_body).group(1))
            off = addr + entries * (width // 8)
        else:
            off = addr + n * 4
    for m in _ABR_NAMED.finditer(text):
        _kind, name, at = m.group(1), m.group(2), m.group(3)
        if at:
            out[name] = int(at, 16)
    if "intr_block_rf" not in out:
        raise RuntimeError("intr_block_rf missing from abr_reg.rdl")
    out["global_intr_en_r"] = 0x0
    out["error_intr_en_r"] = 0x4
    out["notif_intr_en_r"] = 0x8
    out["error_internal_intr_r"] = 0x14
    out["notif_internal_intr_r"] = 0x18
    out["error_intr_trig_r"] = 0x1C
    return out


def abr_off(name: str) -> int:
    try:
        return abr_offsets()[name]
    except KeyError as exc:
        raise KeyError(f"{name!r} missing from abr_reg.rdl") from exc


_ESRC_RDL = _REPO / "hw" / "ip" / "entropy_source" / "regs" / "entropy_source.rdl"

_RDL_REG = re.compile(r"^\s*reg\s+([A-Za-z_]\w*)\s*\{", re.M)
_RDL_FIELD = re.compile(r"field\s*\{(?P<body>[^{}]*)\}\s*(?P<name>[A-Za-z_]\w*)\s*\[", re.S)


@lru_cache(maxsize=1)
def esrc_fips_locked_fields() -> dict[str, frozenset[str]]:
    """Fields FIPS_LOCK.LOCK freezes, keyed by register, from ``entropy_source.rdl``.

    The certified-configuration inventory is the set of fields the RDL marks
    ``swwel``; FIPS_LOCK's own block documents it in those terms. The generated
    Python and C exports drop ``swwel``, so the property is read from the RDL
    source, as ``abr_offsets`` reads ``abr_reg.rdl``.

    This is the DV-side expectation of what must freeze. It is deliberately not
    taken from ``entropy_source.sv``: the RTL is hand-written and maintained
    separately from this file, so a lock the RTL adds or drops on its own shows
    up here as a disagreement instead of being copied into the expectation.
    """
    text = _ESRC_RDL.read_text(encoding="utf-8")
    bounds = [(m.group(1), m.start()) for m in _RDL_REG.finditer(text)]
    out: dict[str, frozenset[str]] = {}
    for i, (reg, start) in enumerate(bounds):
        end = bounds[i + 1][1] if i + 1 < len(bounds) else len(text)
        locked = {
            f.group("name")
            for f in _RDL_FIELD.finditer(text[start:end])
            if "swwel" in f.group("body")
        }
        if locked:
            out[reg] = frozenset(locked)
    if not out:
        raise RuntimeError(
            f"no swwel fields parsed from {_ESRC_RDL}; the walked lock set would "
            "be empty and every post-lock check would pass without poking anything"
        )
    return out


def esrc_fips_locked(reg: str) -> frozenset[str]:
    """The FIPS-locked fields of one register. Raises if the register locks none."""
    try:
        return esrc_fips_locked_fields()[reg]
    except KeyError as exc:
        raise KeyError(
            f"{reg!r} has no swwel field in entropy_source.rdl; it is not part of "
            "the certified-configuration inventory FIPS_LOCK freezes"
        ) from exc


def _selftest() -> None:
    assert window("ABR").base == 0x1094_0000
    assert window("EPOOL").base == 0x1095_0000
    assert pic("CSRNG command request done") == 24
    assert pic("KM mailbox IRQ") == 15
    assert agg_from_pic("KM mailbox IRQ") == 14
    assert agg_from_pic("Adams Bridge notification") == 35
    assert MAILBOX_DEPTH == 8
    assert BIW_TRIPLES[0] == (0, 4, 8)
    assert BIW_OUT_SHIFTS[0] == 24
    assert KMAC_SHA3_STRENGTHS == (224, 256, 384, 512)
    assert KMAC_XOF_STRENGTHS == (128, 256)
    assert abr_off("MLDSA_CTRL") == 0x10
    assert abr_off("MLDSA_PUBKEY") == 0x1000
    assert abr_off("kv_mldsa_seed_rd_ctrl") == 0x8000
    name0, name1 = mldsa_name_words()
    assert name0 == 0x44534D4C
    assert name1 == 0x3837412D
    locked = esrc_fips_locked_fields()
    # A parse that silently matched nothing would empty the post-lock walk.
    assert len(locked) >= 10, locked
    assert sum(len(v) for v in locked.values()) >= 30
    assert esrc_fips_locked("CTRL") >= {"MODULE_ENABLE", "SHA256_WHITENING_ENABLE"}
    assert esrc_fips_locked("HEALTH_TEST_CTRL") >= {"ENABLE", "REPETITION_LIMIT"}
    assert "LOCK" not in locked.get("FIPS_LOCK", frozenset())


_selftest()
