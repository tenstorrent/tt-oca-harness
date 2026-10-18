# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed-drawn leaf plans and t=0 OTP images of the eFuse, lifecycle and SEC_DIS tests.

One function per test (``PLANNERS``) draws every seed dimension of the leaf from
``SepSeededRng(seed)`` in a fixed order and returns a ``SepEfusePlan``: the t=0
image, the lifecycle raw code, the disable-vector pair and every drawn value in
draw order. ``dv_sim_prestage.py`` calls ``plan(test, seed)`` before the
simulator starts and writes ``plan.image``; the test calls the same function at
runtime with the same seed, so the staged image and the test golden are the same
object built twice. A draw that depends on a value the leaf measures (a match
offset, a word-write order) comes from ``plan.draw`` after every static draw, so
it never moves a static draw.

The module is pure Python with sibling imports only, so the pre-sim hook can load
it with ``_load_env_module``. It holds no cocotb import. The token helpers take
the bus access as async callables.

Contents:

* Fixed named vectors. ``TOKEN_T1``, ``TOKEN_T2``, ``TOKEN_OTHER`` and the all-zero
  ``TOKEN_ZERO``; ``FIELD_VECTORS``, the pool of 256-bit field vectors (eight
  distinct words each, non-zero and not all ones, no word shared between two
  vectors). A draw picks a vector, an order or a position; no draw makes a token.
  The stream is not a CSPRNG: every token here is a simulation value.
* The vector filter of the disable-vector pair (DBG_1, DBG_2, Function groups).
* ``feat_ctrl_profile``: the Per-LC-state Feature Control Profile table, row by row.
* Token goldens: SHA-256 of the 32-byte big-endian token (index 7 first) and the
  match codes; token word writes in a drawn order, go, read runs and polls.
* Program and read control words from the RDL field layout, and a program go
  that does not wait.

Field offsets, widths, lock-slot positions and disable groups come from the
generated register header (``hw/sys/sep/regs/gen/py/sep_reg.py``), through
``sep_efuse_image`` and ``sep_reg_meta``. Where the contract states a narrower
used range than the RDL field (``CHIPLET_PUBK_REVOKE`` bits 25:0, two used bits
per ``REQUIRED_ALGS`` nibble), the RDL gives the position and the contract the
range.

A per-seed value of this module is a function of the generator stream and is never
quoted as verification-plan evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

# sep_reg_meta puts regs/gen/py on sys.path, so it comes before sep_reg.
from sep_reg_meta import EFUSE_INTERFACE_CTRL, EFUSE_MMR, RegBlock, sym

# isort: split
import sep_reg  # noqa: E402
from sep_efuse_image import (  # noqa: E402
    LC_PROD,
    LC_PROD_END,
    LC_RMA_CHIP_0,
    LC_RMA_SIP_0,
    LC_TEST_DEV,
    NUM_FUSE_WORDS,
    SHADOW_BASE,
    WORD_BITS,
    WORD_MASK,
    SepEfuseImage,
    lc_encode,
)
from sep_rma_token import token_digest  # noqa: E402
from sep_seeded_rng import SepSeededRng  # noqa: E402

__all__ = [
    "CH_CHIPLET",
    "CH_SEC_DIS",
    "CH_SIP",
    "CODE_ERROR",
    "CODE_IDLE",
    "CODE_MATCH",
    "CODE_MISMATCH",
    "FIELD_VECTORS",
    "PLANNERS",
    "PRESTAGED_TESTS",
    "SEC_DIS_BOUND_DIGEST",
    "TOKEN_OTHER",
    "TOKEN_T1",
    "TOKEN_T2",
    "TOKEN_ZERO",
    "SepEfusePlan",
    "feat_ctrl_profile",
    "plan",
    "vector_filter_legal",
]

_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")
_MASK64 = (1 << 64) - 1
# Bound of every redraw loop. Each predicate below accepts a large fraction of
# its draws, so the bound is never reached; reaching it raises.
_MAX_REDRAW = 4096


# --------------------------------------------------------------------------
# Field geometry (generated map, through SepEfuseImage)
# --------------------------------------------------------------------------

FIELD_NAMES: tuple[str, ...] = tuple(f.name for f in SepEfuseImage.fields)
WIDE_FIELDS: tuple[str, ...] = tuple(f.name for f in SepEfuseImage.fields if f.n_words == 8)
SPARE_FIELDS: tuple[str, ...] = tuple(n for n in WIDE_FIELDS if n.startswith("SPARE"))
DIGEST_FIELDS = ("RMA_SIP_TOKEN_DIGEST", "RMA_CHIPLET_TOKEN_DIGEST")
SECRET_FIELDS = ("CHIPLET_UID", "SIP_UID", "SYS_UID", "CLASS_KEY")
VERSION_FIELDS = ("BL1_VERSION", "BL2_VERSION")
# Shadow registers with writable bits (access RW in
# hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc).
SHADOW_RW_FIELDS = (
    "LOCKS",
    "LOCKS_SPARE",
    "SIP_DIS",
    "SYS_DIS",
    "REQUIRED_SIGNERS",
    "REQUIRED_ALGS",
)


def field_word(name: str) -> int:
    """First word index of a field in the 256-word array."""
    return int(SepEfuseImage.field(name).word)


def field_n_words(name: str) -> int:
    return int(SepEfuseImage.field(name).n_words)


def field_offset(name: str) -> int:
    """Byte offset of a field in the shadow map."""
    return int(SepEfuseImage.field(name).offset)


def bit_address(name: str, word: int = 0, bit: int = 0) -> int:
    """Program or read bit address: 8 times the byte offset of the word plus the bit.

    ``hw/sys/sep/doc/otp_fuse_controller.adoc``, section Fuse Fields;
    ``hw/ip/efuse/doc/interface.adoc``.
    """
    if not 0 <= word < field_n_words(name) or not 0 <= bit < WORD_BITS:
        raise ValueError(f"{name}: word {word} bit {bit} is outside the field")
    return 8 * (field_offset(name) + 4 * word) + bit


def shadow_addr(name: str, word: int = 0) -> int:
    """Frontdoor address of a shadow word."""
    return int(SHADOW_BASE) + field_offset(name) + 4 * word


def _rdl_mask(reg: str, *fields: str) -> int:
    m = 0
    for f in fields:
        m |= _EFUSE_MAP.field_mask(reg, f)
    return m


def _rdl_lsb(reg: str, fld: str) -> int:
    return int(_EFUSE_MAP.field_lsb(reg, fld))


# Used bits of the narrow 32-bit fields. RDL field masks where the RDL field is the
# used range; the contract range (hw/sys/sep/dv/docs/SEP_VPLAN.adoc entry of
# sep_efuse_field_layout_rand_test, used masks) at the RDL position otherwise.
_ALGS_NIBBLES = ("chiplet_algs", "sip_algs", "sys_algs")
NARROW_USED: dict[str, int] = {
    "SBOOT_DIS": _rdl_mask("SBOOT_DIS", "disable_secure_boot"),
    "TRANSIENT_RMA_EN": _rdl_mask("TRANSIENT_RMA_EN", "transient_rma_en"),
    "CHIPLET_PUBK_REVOKE": _rdl_mask("CHIPLET_PUBK_REVOKE", "select") & 0x03FF_FFFF,
    "STATUS_RPT": _rdl_mask("STATUS_RPT", "rpt"),
    "ROM_CTL": _rdl_mask("ROM_CTL", "rom_endianness_ctrl", "rom_swap_ctrl"),
    "SYSCLK_FREQ_MHZ": _rdl_mask("SYSCLK_FREQ_MHZ", "sysclk_freq_mhz"),
    "REQUIRED_SIGNERS": _rdl_mask("REQUIRED_SIGNERS", "required_signers"),
    "REQUIRED_ALGS": sum(0x3 << _rdl_lsb("REQUIRED_ALGS", n) for n in _ALGS_NIBBLES),
}
NARROW_FIELDS: tuple[str, ...] = tuple(NARROW_USED)

# Narrow values of every image that does not draw them. Each is non-zero except the
# two enables, has a 0 in its used bits, and differs from every other staged word.
NARROW_BASE: dict[str, int] = {
    "SBOOT_DIS": 0x0,
    "TRANSIENT_RMA_EN": 0x0,
    "CHIPLET_PUBK_REVOKE": 0x0155_5555,
    "STATUS_RPT": 0x1,
    "ROM_CTL": 0x15,
    "SYSCLK_FREQ_MHZ": 0x190,
    "REQUIRED_SIGNERS": 0x2,
    "REQUIRED_ALGS": 0x021,
}

_LOCKS_ASSIGNED_SPARE = _rdl_mask(
    "LOCKS_SPARE", *(f"spare{i}_{k}_lock" for i in range(9) for k in ("write", "read"))
)


def field_used_masks(name: str) -> list[int]:
    """Per-word used-bit mask of a field."""
    if name in NARROW_USED:
        return [NARROW_USED[name]]
    if name == "LC_STATE":
        return [_rdl_mask("LC_STATE", "lc_state")]
    if name == "LOCKS_SPARE":
        return [_LOCKS_ASSIGNED_SPARE]
    return [WORD_MASK] * field_n_words(name)


def zero_bits(image: SepEfuseImage, name: str) -> list[tuple[int, int]]:
    """(word, bit) of every used bit of ``name`` that reads 0 in ``image``."""
    base = field_word(name)
    out: list[tuple[int, int]] = []
    for w, used in enumerate(field_used_masks(name)):
        value = image.words[base + w]
        out.extend((w, b) for b in range(WORD_BITS) if (used >> b) & 1 and not (value >> b) & 1)
    return out


def used_bits(name: str) -> list[tuple[int, int]]:
    """(word, bit) of every used bit of ``name``."""
    out: list[tuple[int, int]] = []
    for w, used in enumerate(field_used_masks(name)):
        out.extend((w, b) for b in range(WORD_BITS) if (used >> b) & 1)
    return out


# --------------------------------------------------------------------------
# Disable-vector groups (SEP_EFUSE_MAP LC_DISABLE layout, shared by SIP_DIS/SYS_DIS)
# --------------------------------------------------------------------------


def _lc_disable_mask(*names: str) -> int:
    struct = sep_reg.SEP_EFUSE_MAP_LC_DISABLE_reg_t
    union = sep_reg.SEP_EFUSE_MAP_LC_DISABLE_reg_u
    widths = {f: w for f, _t, w in struct._fields_}
    m = 0
    for n in names:
        view = union()
        view.val = 0
        setattr(view.f, n, (1 << widths[n]) - 1)
        m |= int(view.val)
    return m


DBG1_MASK = _lc_disable_mask(
    "sep_debug", "chiplet_dbg", "sep_fuse_dbg", "smc_fuse_dbg", "debug_reserved_dbg1"
)
DBG2_MASK = _lc_disable_mask("sip_debug", "debug_reserved_dbg2")
FUNC_MASK = _lc_disable_mask("func_reserved")
DIS_GROUPS: tuple[tuple[str, int], ...] = (
    ("DBG_1", DBG1_MASK),
    ("DBG_2", DBG2_MASK),
    ("FUNC", FUNC_MASK),
)
# hw/sys/sep/doc/lifecycle_controller.adoc, section Disable Vector Format: DBG_1
# [23:0], DBG_2 [47:24], Function [63:48]. Independent anchor of the RDL layout.
if (DBG1_MASK, DBG2_MASK, FUNC_MASK) != (0xFF_FFFF, 0xFF_FFFF << 24, 0xFFFF << 48):
    raise RuntimeError(
        f"LC_DISABLE groups {DBG1_MASK:#x}/{DBG2_MASK:#x}/{FUNC_MASK:#x} differ from the "
        "specification layout DBG_1 [23:0], DBG_2 [47:24], Function [63:48]"
    )
# The five named DBG_1 bits SEP_DBG, CHIPLET_DBG, SEP_FUSE_DBG, SMC_FUSE_DBG,
# ENTROPY_DBG (lifecycle_controller.adoc, SEP feature-disable vector table).
NAMED_DBG_BITS = (0, 1, 2, 3, 4)
# Bits that the walk of sep_lcc_feat_ctrl_state_matrix_rand_test weights double and
# pins to the owner SIP_DIS in TEST_DEV and SYS_DIS in PROD (VPLAN entry).
WALK_PINNED_BITS = (0, 1, 2, 3, 4, 23, 24, 25, 47, 48, 63)


def vector_filter_legal(sip_dis: int, sys_dis: int) -> bool:
    """Vector filter of a disable-vector pair (VPLAN eFuse rules, Vector filter).

    In each of DBG_1, DBG_2 and Function, the OR of the two vectors has a 1 and a 0,
    and at least one bit is set in only one vector.
    """
    for _name, m in DIS_GROUPS:
        both = (sip_dis | sys_dis) & m
        if both == 0 or both == m or (sip_dis ^ sys_dis) & m == 0:
            return False
    return True


# One fixed filter-legal pair, for the images that draw no pair.
FIXED_SIP_DIS = (0x000F << 48) | (0x00_000F << 24) | 0x00_000F
FIXED_SYS_DIS = (0x00F0 << 48) | (0x00_00F0 << 24) | 0x00_00F0
if not vector_filter_legal(FIXED_SIP_DIS, FIXED_SYS_DIS):
    raise RuntimeError("the fixed disable-vector pair is not filter-legal")


# --------------------------------------------------------------------------
# Lock slots (SEP_EFUSE_MAP LOCKS / LOCKS_SPARE layout)
# --------------------------------------------------------------------------


def _lock_slots() -> tuple[tuple[str, int, int], ...]:
    """(field, write-lock bit, read-lock bit) per slot, bits of the 96-bit lock vector."""
    out = []
    for reg, base in (("LOCKS", 0), ("LOCKS_SPARE", 64)):
        struct = getattr(sep_reg, f"SEP_EFUSE_MAP_{reg}_reg_t")
        for fname, _t, _w in struct._fields_:
            if not fname.endswith("_write_lock"):
                continue
            stem = fname[: -len("_write_lock")]
            wmask = _EFUSE_MAP.field_mask(reg, f"{stem}_write_lock")
            rmask = _EFUSE_MAP.field_mask(reg, f"{stem}_read_lock")
            out.append((stem.upper(), base + wmask.bit_length() - 1, base + rmask.bit_length() - 1))
    return tuple(out)


LOCK_SLOTS = _lock_slots()
LOCK_SLOT_FIELD: tuple[str, ...] = tuple(s[0] for s in LOCK_SLOTS)
SLOT_OF_FIELD: dict[str, int] = {n: i for i, n in enumerate(LOCK_SLOT_FIELD)}
# otp_fuse_controller.adoc LOCK field: 41 slots, write lock at bit 2s, read lock at 2s+1.
for _s, (_n, _wb, _rb) in enumerate(LOCK_SLOTS):
    if (_wb, _rb) != (2 * _s, 2 * _s + 1) or _n not in FIELD_NAMES:
        raise RuntimeError(
            f"lock slot {_s} ({_n}) sits at bits {_wb}/{_rb}, not {2 * _s}/{2 * _s + 1}"
        )
if len(LOCK_SLOTS) != 41 or LOCK_SLOT_FIELD[0] != "LC_STATE":
    raise RuntimeError("the lock vector does not hold 41 slots starting at LC_STATE")


def write_lock_bit(slot: int) -> int:
    return LOCK_SLOTS[slot][1]


def read_lock_bit(slot: int) -> int:
    return LOCK_SLOTS[slot][2]


# --------------------------------------------------------------------------
# Fixed named vectors
# --------------------------------------------------------------------------

TOKEN_ZERO = 0
TOKEN_T1 = 0xE8B28F4A_B8D3F6E0_81A301D4_E658D4CD_1C72E4CE_5BFA2C0F_749405CF_C26B13C9
TOKEN_T2 = 0x235BD071_D1150127_28092449_1699CEE7_61DB65CD_0835B68E_3E1A0A03_4CBD9CB6
TOKEN_OTHER = 0x3C1C51DF_AD42CF99_9939FFFB_1873D45A_924C457B_C776F81B_F89AB5E8_969602D8
TOKEN_ONES = (1 << 256) - 1
TOKENS = {
    "TOKEN_T1": TOKEN_T1,
    "TOKEN_T2": TOKEN_T2,
    "TOKEN_OTHER": TOKEN_OTHER,
    "TOKEN_ZERO": TOKEN_ZERO,
}

# Read data that memory_map.adoc lists for an unmapped read at the inbound port; no
# staged vector word takes it.
_UNMAPPED_RDATA = 0xBADC_AB1E
N_FIELD_VECTORS = 40


def token_words(token: int) -> list[int]:
    """Eight 32-bit words of a token, index 0 holding ``token[31:0]``."""
    return [(token >> (WORD_BITS * k)) & WORD_MASK for k in range(8)]


def words_token(words: Sequence[int]) -> int:
    """Inverse of ``token_words``."""
    return sum((w & WORD_MASK) << (WORD_BITS * k) for k, w in enumerate(words))


def _derive_field_vectors() -> tuple[tuple[int, ...], ...]:
    """The pool of 256-bit field vectors.

    Fixed constants: each vector is the SHA-256 of a label with a counter, with no
    seed input, so the pool is the same in every leaf. Candidates with a zero word,
    an all-ones word, the unmapped read data, a repeated word, or a word already used
    by a token, a narrow base value or an earlier vector are skipped.
    """
    seen = {0, WORD_MASK, _UNMAPPED_RDATA}
    for tok in (TOKEN_T1, TOKEN_T2, TOKEN_OTHER):
        seen.update(token_words(tok))
    seen.update(NARROW_BASE.values())
    out: list[tuple[int, ...]] = []
    ctr = 0
    while len(out) < N_FIELD_VECTORS:
        d = hashlib.sha256(b"sep-dv-field-vector-%d" % ctr).digest()
        ctr += 1
        words = tuple(int.from_bytes(d[4 * k : 4 * k + 4], "little") for k in range(8))
        if len(set(words)) != 8 or any(w in seen for w in words):
            continue
        seen.update(words)
        out.append(words)
    return tuple(out)


FIELD_VECTORS = _derive_field_vectors()
# Default vector of each 256-bit field: the field's index in map order.
DEFAULT_VECTOR: dict[str, int] = {n: i for i, n in enumerate(WIDE_FIELDS)}
if len(WIDE_FIELDS) > N_FIELD_VECTORS:
    raise RuntimeError("fewer field vectors than 256-bit fields")


# --------------------------------------------------------------------------
# Feature-control profile
# --------------------------------------------------------------------------

ST_TEST_DEV = "TEST_DEV"
ST_PROD = "PROD"
ST_PROD_END = "PROD_END"
ST_RMA_SIP = "RMA_SIP"
ST_RMA_CHIPLET = "RMA_CHIPLET"
ST_INVALID = "INVALID"
LC_INVALID_0101 = 0x5


def lc_state_class(raw: int) -> str:
    """State of a 4-bit raw code (lifecycle_controller.adoc, SEP lifecycle state encodings).

    TEST_DEV 0000, PROD 0001, PROD_END 1000, RMA_SIP 001X, RMA_CHIPLET 011X,
    INVALID every other value.
    """
    raw &= 0xF
    if raw == 0b0000:
        return ST_TEST_DEV
    if raw == 0b0001:
        return ST_PROD
    if raw == 0b1000:
        return ST_PROD_END
    if raw >> 1 == 0b001:
        return ST_RMA_SIP
    if raw >> 1 == 0b011:
        return ST_RMA_CHIPLET
    return ST_INVALID


_T = "T"
_F = "F"
_BOTH = "~(SIP_DIS|SYS_DIS)"
_SIP = "~SIP_DIS"

PROFILE_SOURCE = (
    "hw/sys/sep/doc/lifecycle_controller.adoc, section Per-LC-state Feature Control Profile"
)
SIGINT_SOURCE = (
    "hw/sys/sep/doc/lifecycle_controller.adoc, section Overrides and Final Gates (SEC_DIS)"
)

# The Per-LC-state Feature Control Profile table, one tuple per row, in table order:
# (state, SEC_DIS, (DEMOTE_1, DEMOTE_2), (DBG_1, DBG_2, Function)).
# SEC_DIS None is the RMA_CHIPLET "X"; a demotion None is "--" or "X".
FEAT_CTRL_PROFILE: tuple[
    tuple[str, int | None, tuple[int, int] | None, tuple[str, str, str]], ...
] = (
    (ST_TEST_DEV, 0, (0, 0), (_BOTH, _BOTH, _BOTH)),
    (ST_TEST_DEV, 0, (1, 0), (_T, _BOTH, _BOTH)),
    (ST_TEST_DEV, 0, (0, 1), (_BOTH, _T, _BOTH)),
    (ST_TEST_DEV, 0, (1, 1), (_T, _T, _BOTH)),
    (ST_TEST_DEV, 1, None, (_T, _T, _T)),
    (ST_PROD, 0, (0, 0), (_F, _F, _BOTH)),
    (ST_PROD, 0, (1, 0), (_BOTH, _F, _BOTH)),
    (ST_PROD, 0, (0, 1), (_F, _BOTH, _BOTH)),
    (ST_PROD, 0, (1, 1), (_BOTH, _BOTH, _BOTH)),
    (ST_PROD, 1, None, (_T, _T, _T)),
    (ST_PROD_END, 0, None, (_F, _F, _BOTH)),
    (ST_PROD_END, 1, None, (_T, _T, _T)),
    (ST_RMA_SIP, 0, None, (_SIP, _SIP, _SIP)),
    (ST_RMA_SIP, 1, None, (_T, _T, _T)),
    (ST_RMA_CHIPLET, None, None, (_T, _T, _T)),
    (ST_INVALID, 0, None, (_F, _F, _F)),
    (ST_INVALID, 1, None, (_T, _T, _T)),
)


@dataclass(frozen=True)
class FeatCtrlRow:
    """One evaluated profile cell: the 64-bit value and the row that produced it."""

    value: int
    state: str
    row: int
    """1-based row of the profile table; 0 for the integrity-error fail-closed base."""
    terms: tuple[str, str, str]
    source: str

    def log(self) -> str:
        return f'src="{self.source}" row={self.row} state={self.state} terms={"/".join(self.terms)}'


def _term(term: str, mask: int, sip_dis: int, sys_dis: int) -> int:
    if term == _T:
        return mask
    if term == _F:
        return 0
    if term == _BOTH:
        return ~(sip_dis | sys_dis) & mask
    if term == _SIP:
        return ~sip_dis & mask
    raise ValueError(f"unknown profile term {term}")


def feat_ctrl_profile(
    lc_raw: int,
    sip_dis: int,
    sys_dis: int,
    *,
    demote_1: int = 0,
    demote_2: int = 0,
    sec_dis: int = 0,
    sigint_err: int = 0,
) -> FeatCtrlRow:
    """``FEAT_CTRL`` of one cell, from the profile table row by row.

    The output is DBG_1 [23:0] / DBG_2 [47:24] / Function [63:48]; ``T`` enables
    every bit of the group, ``F`` none, a formula enables the bits that neither named
    mask disables. ``secure_tm`` is not a term (Overrides and Final Gates). Order of
    the overrides: an integrity error of the LC_STATE code forces the base to 0, and
    SEC_DIS = 1 then forces all ones (Overrides and Final Gates, steps 1 and 2).

    Sources: ``hw/sys/sep/doc/lifecycle_controller.adoc``, sections Per-LC-state
    Feature Control Profile (table ``feature-control-table``), SEP lifecycle state
    encodings, Overrides and Final Gates (SEC_DIS).
    """
    state = lc_state_class(lc_raw)
    sip_dis &= _MASK64
    sys_dis &= _MASK64
    sec = 1 if sec_dis else 0
    if sigint_err and not sec:
        return FeatCtrlRow(0, state, 0, (_F, _F, _F), SIGINT_SOURCE)
    demote = (1 if demote_1 else 0, 1 if demote_2 else 0)
    for idx, (st, row_sec, row_dem, terms) in enumerate(FEAT_CTRL_PROFILE, start=1):
        if st != state:
            continue
        if row_sec is not None and row_sec != sec:
            continue
        if row_dem is not None and row_dem != demote:
            continue
        value = 0
        for term, (_g, mask) in zip(terms, DIS_GROUPS):
            value |= _term(term, mask, sip_dis, sys_dis)
        return FeatCtrlRow(value, state, idx, terms, PROFILE_SOURCE)
    raise LookupError(f"no profile row for state={state} sec_dis={sec} demote={demote}")


def feat_ctrl_state_upper_bound(lc_raw: int) -> int:
    """OR of every SEC_DIS = 0 row of the state with both disable vectors 0.

    No ``FEAT_CTRL`` bit outside this mask can be 1 in the state without SEC_DIS.
    """
    out = 0
    for d1 in (0, 1):
        for d2 in (0, 1):
            out |= feat_ctrl_profile(lc_raw, 0, 0, demote_1=d1, demote_2=d2).value
    return out


# --------------------------------------------------------------------------
# Token goldens and token-block access
# --------------------------------------------------------------------------

CH_SIP = "sip"
CH_CHIPLET = "chiplet"
CH_SEC_DIS = "sec_dis"
CHANNELS = (CH_SIP, CH_CHIPLET, CH_SEC_DIS)
_CH_ARRAY = {CH_SIP: "RMA_SIP", CH_CHIPLET: "RMA_CHIPLET", CH_SEC_DIS: "SEC_DISABLE"}
TOKEN_ARRAY_ADDR: dict[str, tuple[int, ...]] = {
    ch: tuple(sym(f"EFUSE_MMR_{arr}_TOKEN_I_{i}__REG_ADDR") for i in range(8))
    for ch, arr in _CH_ARRAY.items()
}
MATCH_ADDR: dict[str, int] = {
    ch: sym(f"EFUSE_MMR_{arr}_TOKEN_MATCH_REG_ADDR") for ch, arr in _CH_ARRAY.items()
}
TOKEN_EOP_ADDR = sym("EFUSE_MMR_TOKEN_EOP_REG_ADDR")
TOKEN_MATCH_FAULT_ADDR = sym("EFUSE_MMR_TOKEN_MATCH_FAULT_REG_ADDR")
GO_MASK: dict[str, int] = {
    CH_SIP: EFUSE_MMR.field_mask("TOKEN_EOP", "rma_sip_token_go"),
    CH_CHIPLET: EFUSE_MMR.field_mask("TOKEN_EOP", "rma_chiplet_token_go"),
    CH_SEC_DIS: EFUSE_MMR.field_mask("TOKEN_EOP", "secure_disable_token_go"),
}
MATCH_STATUS_MASK = EFUSE_MMR.field_mask("TOKEN_MATCH", "token_match_status")
# token_match_status codes (hw/ip/efuse/regs/gen/adoc/efuse_mmr.adoc, TOKEN_MATCH;
# hw/sys/sep/doc/token_processing.adoc, token match result table). 0x00 is Idle.
CODE_IDLE = 0x00
CODE_MATCH = 0x15
CODE_MISMATCH = 0x2A
CODE_ERROR = 0x3F

# The bench binds the SEC_DIS digest of the all-zero token (VPLAN eFuse rules, SEC_DIS
# token): SHA-256 of 32 zero bytes, read as the 256-bit FIPS 180-4 value.
SEC_DIS_BOUND_DIGEST = token_digest(TOKEN_ZERO)
_DIGEST_FIELD = {CH_SIP: "RMA_SIP_TOKEN_DIGEST", CH_CHIPLET: "RMA_CHIPLET_TOKEN_DIGEST"}
# Right token and foreign token of each channel (VPLAN token-channel entry).
RIGHT_TOKEN = {CH_SIP: TOKEN_T1, CH_CHIPLET: TOKEN_T2, CH_SEC_DIS: TOKEN_ZERO}
FOREIGN_TOKEN = {CH_SIP: TOKEN_T2, CH_CHIPLET: TOKEN_T1, CH_SEC_DIS: TOKEN_T1}


def rma_digest_pins() -> dict[str, int]:
    """Image pins of the two RMA digests: SHA-256 of ``TOKEN_T1`` and ``TOKEN_T2``.

    The digest is the 256-bit value with shadow word k holding bits [32k+31:32k]
    (VPLAN eFuse rules, Digest staging); ``SepEfuseImage.set_int`` stores it so.
    """
    return {
        "RMA_SIP_TOKEN_DIGEST": token_digest(TOKEN_T1),
        "RMA_CHIPLET_TOKEN_DIGEST": token_digest(TOKEN_T2),
    }


def expected_digest(channel: str, image: SepEfuseImage) -> int:
    """The digest a token of ``channel`` is compared with."""
    if channel == CH_SEC_DIS:
        return int(SEC_DIS_BOUND_DIGEST)
    return int(image.field_int(_DIGEST_FIELD[channel]))


def match_code(channel: str, token: int, image: SepEfuseImage) -> int:
    """Golden result of a go: Match when ``SHA256(token) == expected digest``.

    ``hw/sys/sep/doc/token_processing.adoc``, sections Token Matching Mechanism and
    Token Submission: the hash input is the 32-byte big-endian ``token[255:0]``.
    """
    return CODE_MATCH if token_digest(token) == expected_digest(channel, image) else CODE_MISMATCH


def token_write_ops(channel: str, token: int, order: Sequence[int]) -> list[tuple[int, int]]:
    """(address, word) of the eight word writes of ``token`` in ``order``."""
    if sorted(order) != list(range(8)):
        raise ValueError(f"word order {list(order)} is not a permutation of 0..7")
    words = token_words(token)
    return [(TOKEN_ARRAY_ADDR[channel][k], words[k]) for k in order]


def token_go_op(channel: str) -> tuple[int, int]:
    """(address, data) of a go with one go bit."""
    return TOKEN_EOP_ADDR, GO_MASK[channel]


WriteFn = Callable[[int, int], Awaitable[Any]]
ReadFn = Callable[[int], Awaitable[int]]


async def write_token(wr: WriteFn, channel: str, token: int, order: Sequence[int]) -> None:
    """Write the eight words of ``token`` to the array of ``channel`` in ``order``."""
    for addr, word in token_write_ops(channel, token, order):
        await wr(addr, word)


async def token_go(wr: WriteFn, channel: str) -> None:
    addr, data = token_go_op(channel)
    await wr(addr, data)


@dataclass
class ReadRun:
    """Result of a read run: reads from the go until two equal non-Idle codes."""

    final: int | None
    w_hash: int
    n_idle: int
    codes: list[int]


async def read_run(rd: ReadFn, channel: str, *, max_reads: int) -> ReadRun:
    """Read the match register back to back until two consecutive equal non-Idle codes.

    ``w_hash`` counts the reads, ``n_idle`` the reads that return Idle. ``final`` is
    None when ``max_reads`` ends the run first; the caller fails the check it feeds.
    """
    codes: list[int] = []
    for _ in range(max_reads):
        code = (await rd(MATCH_ADDR[channel])) & MATCH_STATUS_MASK
        codes.append(code)
        if len(codes) >= 2 and code != CODE_IDLE and codes[-2] == code:
            return ReadRun(code, len(codes), codes.count(CODE_IDLE), codes)
    return ReadRun(None, len(codes), codes.count(CODE_IDLE), codes)


async def poll_code(
    rd: ReadFn, channel: str, *, max_reads: int, until: int | None = None
) -> tuple[int | None, int]:
    """Read the match register until it is non-Idle (or equals ``until``).

    Returns (code, reads); code is None when ``max_reads`` ends the poll.
    """
    for n in range(1, max_reads + 1):
        code = (await rd(MATCH_ADDR[channel])) & MATCH_STATUS_MASK
        if (until is None and code != CODE_IDLE) or (until is not None and code == until):
            return code, n
    return None, max_reads


def shape_flip(token: int, pos: int) -> int:
    return token ^ (1 << pos)


def shape_swap(token: int, i: int, j: int) -> int:
    w = token_words(token)
    w[i], w[j] = w[j], w[i]
    return words_token(w)


def shape_byte_swap(token: int, k: int) -> int:
    w = token_words(token)
    w[k] = int.from_bytes(w[k].to_bytes(4, "little"), "big")
    return words_token(w)


def palindromic_word(word: int) -> bool:
    b = word.to_bytes(4, "little")
    return b == b[::-1]


# --------------------------------------------------------------------------
# Program and read interface control words (EFUSE_INTERFACE_CTRL RDL layout)
# --------------------------------------------------------------------------

STATUS_ADDR = EFUSE_INTERFACE_CTRL.addr("EFUSE_INTERFACE_CTRL_STATUS")
PROGRAM_CTRL_ADDR = EFUSE_INTERFACE_CTRL.addr("EFUSE_PROGRAM_CTRL")
READ_CTRL_ADDR = EFUSE_INTERFACE_CTRL.addr("EFUSE_READ_CTRL")
_PG = "EFUSE_PROGRAM_CTRL"
_RD = "EFUSE_READ_CTRL"


def _fld(reg: str, name: str, value: int) -> int:
    mask = EFUSE_INTERFACE_CTRL.field_mask(reg, name)
    lsb = EFUSE_INTERFACE_CTRL.field_lsb(reg, name)
    if value << lsb & ~mask:
        raise ValueError(f"{reg}.{name} = {value:#x} does not fit the field")
    return int(value << lsb)


def program_ctrl_word(
    bit_addr: int, *, data: int = 1, enable: int = 1, go: int = 1, read_back: int = 0
) -> int:
    """``EFUSE_PROGRAM_CTRL`` value with the named fields; every other bit 0."""
    return (
        _fld(_PG, "efuse_addr", bit_addr)
        | _fld(_PG, "efuse_data", data)
        | _fld(_PG, "efuse_program_go", go)
        | _fld(_PG, "efuse_program_read_back", read_back)
        | _fld(_PG, "program_enable", enable)
    )


def read_ctrl_word(bit_addr: int, *, enable: int = 1, go: int = 1) -> int:
    """``EFUSE_READ_CTRL`` value with the named fields; every other bit 0."""
    return (
        _fld(_RD, "efuse_addr", bit_addr)
        | _fld(_RD, "efuse_read_go", go)
        | _fld(_RD, "read_enable", enable)
    )


async def program_go_no_wait(
    wr: WriteFn, bit_addr: int, *, data: int = 1, read_back: int = 0
) -> int:
    """Write one ``EFUSE_PROGRAM_CTRL`` with enable, data, address and go; no poll.

    Returns the written value. The caller places every later step by a probe or a
    bounded window (VPLAN eFuse rules, Time).
    """
    value = program_ctrl_word(bit_addr, data=data, read_back=read_back)
    await wr(PROGRAM_CTRL_ADDR, value)
    return value


# --------------------------------------------------------------------------
# Image builder
# --------------------------------------------------------------------------


def build_image(
    *,
    lc_raw: int,
    sip_dis: int,
    sys_dis: int,
    vectors: dict[str, int] | None = None,
    narrow: dict[str, int] | None = None,
    lock_bits: int = 0,
    pins: dict[str, int] | None = None,
) -> SepEfuseImage:
    """A full 256-word image: every field set, reserved and unused bits 0.

    ``lc_raw`` may be any 4-bit code: the word holds ``{~raw, raw}``. ``vectors``
    maps a 256-bit field to an index of ``FIELD_VECTORS`` (default: its own);
    ``narrow`` overrides ``NARROW_BASE``; ``lock_bits`` is the 96-bit lock vector;
    ``pins`` sets named fields last.
    """
    img = SepEfuseImage()
    if lock_bits >> 64 & ~_LOCKS_ASSIGNED_SPARE:
        raise ValueError("lock vector sets an unassigned LOCKS_SPARE bit")
    img.set_int("LOCKS", lock_bits & _MASK64)
    img.set_int("LOCKS_SPARE", lock_bits >> 64)
    img.set_int("LC_STATE", lc_encode(lc_raw))
    img.set_int("SIP_DIS", sip_dis & _MASK64)
    img.set_int("SYS_DIS", sys_dis & _MASK64)
    vmap = {**DEFAULT_VECTOR, **(vectors or {})}
    for name in WIDE_FIELDS:
        img.set_words(name, list(FIELD_VECTORS[vmap[name]]))
    nvals = {**NARROW_BASE, **(narrow or {})}
    for name in NARROW_FIELDS:
        if nvals[name] & ~NARROW_USED[name]:
            raise ValueError(f"{name} = {nvals[name]:#x} sets a bit outside its used range")
        img.set_int(name, nvals[name])
    for name, value in (pins or {}).items():
        img.set_int(name, value)
    return img


# --------------------------------------------------------------------------
# Draw record and plan
# --------------------------------------------------------------------------


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return f"0x{value:x}" if value > 9 else str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(_fmt(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(f"{k}:{_fmt(v)}" for k, v in value.items()) + "}"
    return str(value)


class SepEfuseDraws:
    """The leaf stream and the record of every value drawn from it, in draw order."""

    def __init__(self, seed: int) -> None:
        self.rng = SepSeededRng(seed)
        self.values: dict[str, Any] = {}
        self._serial: dict[str, int] = {}

    def put(self, name: str, value: Any) -> Any:
        """Record a value. A repeated name takes the suffix ``#<n>``."""
        key = name
        if key in self.values:
            n = self._serial.get(name, 1) + 1
            self._serial[name] = n
            key = f"{name}#{n}"
        self.values[key] = value
        return value

    def choice(self, name: str, seq: Sequence[Any]) -> Any:
        return self.put(name, self.rng.choice(list(seq)))

    def weighted(self, name: str, items: Sequence[tuple[Any, int]]) -> Any:
        """One item, with integer weights."""
        total = sum(w for _v, w in items)
        r = self.rng.randrange(total)
        for value, w in items:
            if r < w:
                return self.put(name, value)
            r -= w
        raise AssertionError("weighted draw fell through")

    def randrange(self, name: str, start: int, stop: int) -> int:
        return int(self.put(name, self.rng.randrange(start, stop)))

    def shuffled(self, name: str, seq: Sequence[Any]) -> list[Any]:
        out = list(seq)
        self.rng.shuffle(out)
        return list(self.put(name, out))

    def sample(self, name: str, population: Sequence[Any], k: int) -> list[Any]:
        return list(self.put(name, self.rng.sample(list(population), k)))

    def word_order(self, label: str) -> list[int]:
        """A word-write order of a token array (a permutation of 0..7)."""
        return self.shuffled(f"word_order.{label}", range(8))

    def until(self, name: str, draw: Callable[[], Any], ok: Callable[[Any], bool]) -> Any:
        """Redraw ``draw()`` until ``ok``; record the accepted value only."""
        for _ in range(_MAX_REDRAW):
            v = draw()
            if ok(v):
                return self.put(name, v)
        raise RuntimeError(f"draw {name}: no accepted value in {_MAX_REDRAW} tries")


@dataclass
class SepEfusePlan:
    """The leaf plan of one test and seed."""

    test: str
    seed: int
    lc_raw: int
    sip_dis: int
    sys_dis: int
    image: SepEfuseImage
    draw: SepEfuseDraws
    prestaged: bool
    leg: dict[str, Any] = field(default_factory=dict)
    """Derived values a test reads by name (cell lists, addresses, bit addresses)."""
    setup_fail: str | None = None
    """Reason of a SETUP FAIL that the plan found (the leaf fails before its first read)."""

    @property
    def draws(self) -> dict[str, Any]:
        return self.draw.values

    def words(self) -> list[int]:
        return list(self.image.words)

    def log_lines(self) -> list[str]:
        """``SEED`` line and one ``DRAW`` line per drawn value, in draw order."""
        head = (
            f"SEED seed={self.seed} test={self.test} lc_raw=0x{self.lc_raw:x} "
            f"state={lc_state_class(self.lc_raw)} sip_dis=0x{self.sip_dis:016x} "
            f"sys_dis=0x{self.sys_dis:016x} prestaged={int(self.prestaged)}"
        )
        lines = [head]
        lines += [f"DRAW seed={self.seed} name={k} value={_fmt(v)}" for k, v in self.draws.items()]
        if self.setup_fail:
            lines.append(f"SETUP FAIL seed={self.seed} reason={self.setup_fail}")
        return lines


def _make_plan(
    test: str,
    seed: int,
    d: SepEfuseDraws,
    lc_raw: int,
    sip: int,
    sys_: int,
    image: SepEfuseImage,
    leg: dict[str, Any] | None = None,
    setup_fail: str | None = None,
) -> SepEfusePlan:
    if (
        image.lc_raw() != lc_raw & 0xF
        or image.field_int("SIP_DIS") != sip
        or image.field_int("SYS_DIS") != sys_
    ):
        raise AssertionError(f"{test}: plan fields disagree with the image")
    return SepEfusePlan(
        test=test,
        seed=seed,
        lc_raw=lc_raw,
        sip_dis=sip,
        sys_dis=sys_,
        image=image,
        draw=d,
        prestaged=test in PRESTAGED_TESTS,
        leg=leg or {},
        setup_fail=setup_fail,
    )


def draw_dis_pair(
    d: SepEfuseDraws, name: str = "dis_pair", extra: Callable[[int, int], bool] | None = None
) -> tuple[int, int]:
    """A filter-legal (SIP_DIS, SYS_DIS) pair, with an optional further filter."""

    def _draw() -> tuple[int, int]:
        return d.rng.getrandbits(64), d.rng.getrandbits(64)

    def _ok(p: tuple[int, int]) -> bool:
        return vector_filter_legal(*p) and (extra is None or extra(*p))

    sip, sys_ = d.until(name, _draw, _ok)
    return sip, sys_


def _pick_bit(
    d: SepEfuseDraws, name: str, image: SepEfuseImage, field_name: str, *, zero: bool = True
) -> dict[str, Any]:
    """Draw a (word, bit) of ``field_name``: a used bit at 0 in ``image`` (or any used bit)."""
    cands = zero_bits(image, field_name) if zero else used_bits(field_name)
    if not cands:
        raise RuntimeError(f"{name}: {field_name} has no candidate bit")
    w, b = d.rng.choice(cands)
    rec = {"field": field_name, "word": w, "bit": b, "addr": bit_address(field_name, w, b)}
    d.put(name, rec)
    return rec


# --------------------------------------------------------------------------
# Per-test planners
# --------------------------------------------------------------------------

T_WINDOW_DECODE = "sep_efuse_window_decode_reset_test"
T_FIELD_LAYOUT = "sep_efuse_field_layout_rand_test"
T_CODEWORD = "sep_lcc_state_codeword_rand_test"
T_FEAT_MATRIX = "sep_lcc_feat_ctrl_state_matrix_rand_test"
T_TRANSIENT = "sep_efuse_transient_rma_rand_test"
T_TOKEN_CHANNEL = "sep_efuse_token_channel_rand_test"
T_TOKEN_FAULT = "sep_efuse_token_fault_matrix_test"
T_IF_STATUS = "sep_efuse_interface_status_rand_test"
T_LOCK_SLOT = "sep_efuse_lock_slot_matrix_rand_test"
T_SECURE_TM = "sep_efuse_secure_tm_matrix_rand_test"
T_JTAG_ACCESS = "sep_efuse_jtag_access_rand_test"
T_SEC_DIS_TIMING = "sep_sec_dis_timing_rand_test"
T_SHIM_FAULT = "sep_efuse_shim_response_fault_test"

# Tests whose t=0 image has a seed-drawn dimension; dv_sim_prestage stages these.
PRESTAGED_TESTS: tuple[str, ...] = (
    T_FIELD_LAYOUT,
    T_CODEWORD,
    T_FEAT_MATRIX,
    T_TRANSIENT,
    T_TOKEN_FAULT,
    T_IF_STATUS,
    T_LOCK_SLOT,
    T_SECURE_TM,
    T_JTAG_ACCESS,
    T_SEC_DIS_TIMING,
)

_TIMEOUT_CYCLES_RESET = 0x80_0000


def _timeout_count(d: SepEfuseDraws, name: str) -> int:
    mask = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles")
    return int(
        d.until(
            name,
            lambda: d.rng.getrandbits(32) & mask,
            lambda v: v not in (0, _TIMEOUT_CYCLES_RESET),
        )
    )


def plan_window_decode_reset(seed: int) -> SepEfusePlan:
    """Fixed TEST_DEV image; runtime draws in the Randomization order.

    Order: two timeout counts; ``EFUSE_PROGRAM_CTRL`` pattern (bits 18, 16, 15:0);
    ``EFUSE_READ_CTRL`` pattern (15:0); word order of the SIP, CHIPLET and SEC_DIS
    arrays; seven past-extent offsets (one in {0x20, 0x24}); six reserved-span
    addresses (one alias target per zone); control-write word index w.
    """
    d = SepEfuseDraws(seed)
    img = build_image(lc_raw=LC_TEST_DEV, sip_dis=FIXED_SIP_DIS, sys_dis=FIXED_SYS_DIS)
    _timeout_count(d, "read_req_timeout_cycles")
    _timeout_count(d, "program_req_timeout_cycles")
    pg_mask = (
        EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_addr")
        | EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_data")
        | EFUSE_INTERFACE_CTRL.field_mask(_PG, "efuse_program_read_back")
    )
    rd_mask = EFUSE_INTERFACE_CTRL.field_mask(_RD, "efuse_addr")
    d.until("program_ctrl_pattern", lambda: d.rng.getrandbits(32) & pg_mask, lambda v: v != 0)
    d.until("read_ctrl_pattern", lambda: d.rng.getrandbits(32) & rd_mask, lambda v: v != 0)
    for ch in CHANNELS:
        d.word_order(ch)
    # Past the 28-byte interface-control extent: word offsets 0x20..0xFC.
    cands = list(range(0x20, 0x100, 4))
    alias = d.choice("past_extent_alias", (0x20, 0x24))
    rest = d.sample("past_extent_rest", [c for c in cands if c != alias], 6)
    offsets = d.shuffled("past_extent_offsets", [alias, *rest])
    rw_offs = {field_offset(n) + 4 * w for n in SHADOW_RW_FIELDS for w in range(field_n_words(n))}
    pinned = {0x600, 0xC1C, 0xFFFC}
    zone1 = [a for a in range(0x604, 0x1000, 4) if a not in pinned]
    zone2 = [a for a in range(0x1000, 0xFFFC, 4) if a not in pinned]
    a1 = d.choice("rsvd_alias_zone1", [a for a in zone1 if a & 0x3FF in rw_offs])
    a2 = d.choice("rsvd_alias_zone2", [a for a in zone2 if a & 0x3FF in rw_offs])
    more = d.sample("rsvd_rest", [a for a in zone1 + zone2 if a not in (a1, a2)], 4)
    rsvd = d.shuffled("rsvd_addresses", [a1, a2, *more])
    w = d.choice("sys_dis_ctl_word", (0, 1))
    leg = {
        "past_extent_addrs": [
            EFUSE_INTERFACE_CTRL.addr("EFUSE_INTERFACE_CTRL_STATUS") + o for o in offsets
        ],
        "rsvd_addrs": [SHADOW_BASE + a for a in rsvd],
        "ctl_word_addr": shadow_addr("SYS_DIS", w),
        "rw_shadow_offsets": sorted(rw_offs),
    }
    return _make_plan(T_WINDOW_DECODE, seed, d, LC_TEST_DEV, FIXED_SIP_DIS, FIXED_SYS_DIS, img, leg)


# Graded narrow fields of the field-layout test, in draw order, and their class counts
# (a composite field counts the product of its part classes).
FIELD_LAYOUT_GRADED = (
    "SBOOT_DIS",
    "STATUS_RPT",
    "REQUIRED_SIGNERS",
    "REQUIRED_ALGS",
    "SYSCLK_FREQ_MHZ",
    "ROM_CTL",
    "CHIPLET_PUBK_REVOKE",
)
_FIELD_LAYOUT_N_CLASSES = {
    "SBOOT_DIS": 2,
    "STATUS_RPT": 4,
    "REQUIRED_SIGNERS": 4,
    "REQUIRED_ALGS": 64,
    "SYSCLK_FREQ_MHZ": 3,
    "ROM_CTL": 16,
    "CHIPLET_PUBK_REVOKE": 4,
}
# A word of TRANSIENT_RMA_EN is redrawn through SBOOT_DIS, which sets it.
_FIELD_LAYOUT_GROUP = {"TRANSIENT_RMA_EN": "SBOOT_DIS"}
# Bound of the redraws of one adjacent pair before SETUP FAIL.
FIELD_LAYOUT_PAIR_TRIES = 32


def _revoke_multi(rng: SepSeededRng) -> int:
    for _ in range(_MAX_REDRAW):
        v = rng.getrandbits(26)
        if bin(v).count("1") >= 2 and v != (1 << 26) - 1:
            return int(v)
    raise RuntimeError("CHIPLET_PUBK_REVOKE multi-bit class: no value")


def plan_field_layout(seed: int) -> SepEfusePlan:
    """Drawn narrow values, vector choice, LOCKS and LOCKS_SPARE sets, pair, ``jtag_id_i``.

    Order: narrow fields, each class then value (``SBOOT_DIS``, with
    ``TRANSIENT_RMA_EN`` = 1 - ``SBOOT_DIS``; ``STATUS_RPT``; ``REQUIRED_SIGNERS``;
    the three ``REQUIRED_ALGS`` nibbles; ``SYSCLK_FREQ_MHZ``; ``ROM_CTL`` endianness
    and swap; ``CHIPLET_PUBK_REVOKE``); the vector of each 256-bit field (no two
    alike); the ``LOCKS`` set; the ``LOCKS_SPARE`` set; the pair; the adjacent-equal
    redraws (procedure step 3); ``jtag_id_i[31:1]`` (procedure step 4).

    Adjacent-equal redraw: while two adjacent staged words are equal, one word of the
    first equal pair is redrawn and every pair is checked again. A 256-bit field takes
    an unused vector. Otherwise the graded narrow field with the most classes draws a
    fresh class and a fresh value (equal weight, same legal ranges, recorded as
    ``redraw.<field>.class`` / ``.value`` DRAW lines); after half of the
    ``FIELD_LAYOUT_PAIR_TRIES`` tries of the pair, the other word's field is redrawn.
    When a pair reaches the bound, the plan sets ``setup_fail = "adjacent_equal"``.
    """
    d = SepEfuseDraws(seed)
    rng = d.rng
    narrow: dict[str, int] = {}
    classes: dict[str, Any] = {}

    def cls_value(name: str, cls_list: Sequence[Any]) -> tuple[int, int]:
        """Class (equal weight), then a value inside it; both recorded."""
        idx = d.randrange(f"{name}.class", 0, len(cls_list))
        c = cls_list[idx]
        v = d.put(f"{name}.value", c()) if callable(c) else d.choice(f"{name}.value", c)
        return idx, int(v)

    four = ((0,), (1,), (2,), (3,))
    named_swaps = (0b00000, 0b00001, 0b00010, 0b00100, 0b01000, 0b10000, 0b11111)
    swap_classes = tuple((v,) for v in named_swaps) + (
        tuple(v for v in range(32) if v not in named_swaps),
    )
    revoke_classes = (
        (0,),
        tuple(1 << i for i in range(26)),
        ((1 << 26) - 1,),
        lambda: _revoke_multi(rng),
    )

    def draw_field(name: str, pfx: str = "") -> None:
        """Draw one graded narrow field (class then value) into ``narrow``.

        ``TRANSIENT_RMA_EN`` = 1 - ``SBOOT_DIS`` is kept on every draw of ``SBOOT_DIS``.
        """
        if name == "SBOOT_DIS":
            c, v = cls_value(f"{pfx}SBOOT_DIS", ((0,), (1,)))
            narrow["SBOOT_DIS"] = v << _rdl_lsb("SBOOT_DIS", "disable_secure_boot")
            narrow["TRANSIENT_RMA_EN"] = d.put(f"{pfx}TRANSIENT_RMA_EN.value", 1 - v)
            classes["SBOOT_DIS"] = c
        elif name in ("STATUS_RPT", "REQUIRED_SIGNERS"):
            c, v = cls_value(f"{pfx}{name}", four)
            fld = "rpt" if name == "STATUS_RPT" else "required_signers"
            narrow[name] = v << _rdl_lsb(name, fld)
            classes[name] = c
        elif name == "REQUIRED_ALGS":
            algs, cl = 0, []
            for nib in _ALGS_NIBBLES:
                c, v = cls_value(f"{pfx}REQUIRED_ALGS.{nib}", four)
                algs |= v << _rdl_lsb("REQUIRED_ALGS", nib)
                cl.append(c)
            narrow[name] = algs
            classes[name] = tuple(cl)
        elif name == "SYSCLK_FREQ_MHZ":
            c, v = cls_value(f"{pfx}SYSCLK_FREQ_MHZ", ((1,), (2047,), tuple(range(2, 2047))))
            narrow[name] = v
            classes[name] = c
        elif name == "ROM_CTL":
            ce, e = cls_value(f"{pfx}ROM_CTL.endianness", ((0,), (1,)))
            cs, sw = cls_value(f"{pfx}ROM_CTL.swap", swap_classes)
            narrow[name] = e << _rdl_lsb("ROM_CTL", "rom_endianness_ctrl") | sw << _rdl_lsb(
                "ROM_CTL", "rom_swap_ctrl"
            )
            classes[name] = (ce, cs)
        elif name == "CHIPLET_PUBK_REVOKE":
            c, v = cls_value(f"{pfx}CHIPLET_PUBK_REVOKE", revoke_classes)
            narrow[name] = v
            classes[name] = c
        else:
            raise KeyError(name)

    for name in FIELD_LAYOUT_GRADED:
        draw_field(name)
    picks = d.sample("field_vectors", range(N_FIELD_VECTORS), len(WIDE_FIELDS))
    vectors = dict(zip(WIDE_FIELDS, picks))
    # LOCKS: non-zero set of write-lock bits of slots 1..31, the two words different.
    locks_slots = list(range(1, 32))

    def _locks_draw() -> int:
        m = rng.getrandbits(len(locks_slots))
        return sum(1 << write_lock_bit(s) for i, s in enumerate(locks_slots) if (m >> i) & 1)

    locks = d.until("LOCKS", _locks_draw, lambda v: v != 0 and (v & WORD_MASK) != (v >> 32))
    spare_slots = list(range(32, 41))

    def _spare_draw() -> int:
        m = rng.getrandbits(len(spare_slots))
        return sum(1 << write_lock_bit(s) for i, s in enumerate(spare_slots) if (m >> i) & 1)

    spare = d.until("LOCKS_SPARE", _spare_draw, lambda v: v != 0)
    sip, sys_ = draw_dis_pair(d)

    def build() -> SepEfuseImage:
        return build_image(
            lc_raw=LC_TEST_DEV,
            sip_dis=sip,
            sys_dis=sys_,
            vectors=vectors,
            narrow=narrow,
            lock_bits=locks | spare,
        )

    img = build()
    word_owner = {}
    for name in FIELD_NAMES:
        for k in range(field_n_words(name)):
            word_owner[field_word(name) + k] = name
    setup_fail = None
    tries: dict[int, int] = {}
    while True:
        pair = next(
            (i for i in range(NUM_FUSE_WORDS - 1) if img.words[i] == img.words[i + 1]), None
        )
        if pair is None:
            break
        n = tries.get(pair, 0)
        if n >= FIELD_LAYOUT_PAIR_TRIES:
            setup_fail = "adjacent_equal"
            break
        tries[pair] = n + 1
        owners = [_FIELD_LAYOUT_GROUP.get(word_owner[w], word_owner[w]) for w in (pair, pair + 1)]
        wide = next((o for o in owners if o in WIDE_FIELDS), None)
        if wide is not None:
            used = set(vectors.values())
            vectors[wide] = d.choice(
                f"redraw.{wide}", [v for v in range(N_FIELD_VECTORS) if v not in used]
            )
        else:
            # The word whose field has the most classes first; the other word after
            # half the tries of the pair.
            cands = sorted(
                {o for o in owners if o in FIELD_LAYOUT_GRADED},
                key=lambda o: -_FIELD_LAYOUT_N_CLASSES[o],
            )
            if not cands:
                setup_fail = "adjacent_equal"
                break
            pick = cands[0] if len(cands) == 1 or n < FIELD_LAYOUT_PAIR_TRIES // 2 else cands[1]
            draw_field(pick, "redraw.")
        img = build()
    words = set(img.words)

    def _jtag_ok(v: int) -> bool:
        forms = ((v << 1) & WORD_MASK, ((v << 1) | 1) & WORD_MASK, v & 0x7FFF_FFFF)
        return v != 0 and not any(f in words for f in forms)

    jtag_id = d.until("jtag_id_31_1", lambda: rng.getrandbits(31), _jtag_ok)
    leg = {
        "narrow": dict(narrow),
        "classes": dict(classes),
        "vectors": dict(vectors),
        "jtag_id": jtag_id,
    }
    return _make_plan(T_FIELD_LAYOUT, seed, d, LC_TEST_DEV, sip, sys_, img, leg, setup_fail)


_CODEWORD_NIBBLES = (
    (0b0000, 2),
    (0b0001, 1),
    (0b0010, 1),
    (0b0011, 1),
    (0b0110, 1),
    (0b0111, 1),
    (0b1000, 1),
)
_TIMEOUT_MASK = EFUSE_INTERFACE_CTRL.field_mask("EFUSE_READ_REQ_TIMEOUT", "read_req_timeout_cycles")


def plan_state_codeword(seed: int) -> SepEfusePlan:
    """Nibble n of ``{~n, n}``, pair; leg C draws when n = 0000.

    Order: n (weight 2 for 0000, 1 for each other open-profile nibble); pair; leg C
    only: JTAG shadow-word index, control bit and drawn bit of ``SIP_DIS`` (two
    different bits the staged ``SIP_DIS`` lacks), counts c1 and c2, token word order.
    """
    d = SepEfuseDraws(seed)
    n = d.weighted("lc_nibble", _CODEWORD_NIBBLES)
    sip, sys_ = draw_dis_pair(d)
    img = build_image(lc_raw=n, sip_dis=sip, sys_dis=sys_)
    leg: dict[str, Any] = {"leg_c": n == 0b0000}
    if n == 0b0000:
        leg["jtag_shadow_word"] = d.randrange("jtag_shadow_word", 0, NUM_FUSE_WORDS)
        free = [b for b in range(64) if not (sip >> b) & 1]
        ctl, drawn = d.sample("sip_dis_ctl_and_drawn_bit", free, 2)
        leg["ctl_bit"], leg["drawn_bit"] = ctl, drawn
        c1 = d.until(
            "c1",
            lambda: d.rng.getrandbits(32) & _TIMEOUT_MASK,
            lambda v: v not in (0, _TIMEOUT_CYCLES_RESET),
        )
        c2 = d.until(
            "c2",
            lambda: d.rng.getrandbits(32) & _TIMEOUT_MASK,
            lambda v: v not in (0, _TIMEOUT_CYCLES_RESET, c1),
        )
        leg["c1"], leg["c2"] = c1, c2
        leg["token_order"] = d.word_order("leg_c_sip")
    return _make_plan(T_CODEWORD, seed, d, n, sip, sys_, img, leg)


LEG_B = "B"
LEG_C = "C"
LEG_D_RMA = "D_rma_bypass"
LEG_D_EARLIER = "D_earlier_owner"
LEG_D_WALK = "D_walk"
LEG_E = "E"
_FEAT_LEGS = (
    (LEG_B, 3),
    (LEG_C, 2),
    (LEG_D_RMA, 1),
    (LEG_D_EARLIER, 1),
    (LEG_D_WALK, 2),
    (LEG_E, 2),
)
_DEMOTE_OPS = ("demote", "lock", "zero")
DEMOTE_OP_VALUE = {"demote": 0x1, "lock": 0x2, "zero": 0x0}


def _feat_extra_filter(sip: int, sys_: int) -> bool:
    """Feature-matrix pair filter: SIP_DIS has a bit in each group and SYS_DIS one outside SIP_DIS."""
    return all(sip & m and sys_ & ~sip & m for _g, m in DIS_GROUPS)


def _group_nonzero(v: int) -> bool:
    return all(v & m for _g, m in DIS_GROUPS)


def plan_feat_ctrl_matrix(seed: int) -> SepEfusePlan:
    """Leaf plan of the feature-control matrix (order stated by the contract).

    Order: follow-on leg (B 3, C 2, RMA bypass 1, earlier owner 1, walk 2, E 2); raw
    code r of the leg; strap s; the pair (legs B, C and RMA bypass); then per leg:
    B reset vector v, register A, count L and the L operations, control bit b; the
    earlier-owner vector S; the walk positions, owners and widths; the leg E order
    and widths.
    """
    d = SepEfuseDraws(seed)
    leg_name = d.weighted("leg", _FEAT_LEGS)
    if leg_name in (LEG_B, LEG_C):
        r = d.randrange("lc_raw", 0, 16)
    elif leg_name == LEG_D_RMA:
        base = d.choice("rma_state", (LC_RMA_SIP_0, LC_RMA_CHIP_0))
        r = base | d.choice("x_bit", (0, 1))
    elif leg_name == LEG_D_EARLIER:
        r = d.choice("lc_raw", (LC_TEST_DEV, LC_PROD))
    elif leg_name == LEG_D_WALK:
        r = d.choice("walk_state", (LC_TEST_DEV, LC_PROD, LC_PROD_END, LC_RMA_SIP_0))
        if r == LC_RMA_SIP_0:
            r |= d.choice("x_bit", (0, 1))
    else:
        r = LC_TEST_DEV
    strap = d.choice("strap_s", (0, 1))
    leg: dict[str, Any] = {"leg": leg_name, "strap": strap}
    if leg_name in (LEG_B, LEG_C, LEG_D_RMA):
        sip, sys_ = draw_dis_pair(d, extra=_feat_extra_filter)
    elif leg_name == LEG_D_EARLIER:
        sip = d.until("earlier_owner_S", lambda: d.rng.getrandbits(64), _group_nonzero)
        sys_ = 0
    else:
        sip, sys_ = 0, 0
    img = build_image(lc_raw=r, sip_dis=sip, sys_dis=sys_)
    if leg_name == LEG_B:
        weights = [(v, 1 if v in (2, 10) else 2) for v in range(1, 16)]
        leg["reset_vector"] = d.weighted("reset_vector", weights)
        leg["reg_a"] = d.choice("reg_a", (1, 2))
        count = d.randrange("op_count", 6, 13)

        def _ops() -> list[tuple[str, int]]:
            return [(d.rng.choice(_DEMOTE_OPS), d.rng.choice((1, 2))) for _ in range(count)]

        leg["ops"] = d.until("ops", _ops, lambda ops: any(o != "zero" for o, _r in ops))
        # The control bit is a 0 bit of the first SPARE8 word.
        b0 = d.choice("ctl_bit", [b for (w, b) in zero_bits(img, "SPARE8") if w == 0])
        leg["ctl_bit"] = {
            "field": "SPARE8",
            "word": 0,
            "bit": b0,
            "addr": bit_address("SPARE8", 0, b0),
        }
    elif leg_name == LEG_D_WALK:
        remaining = list(range(64))
        positions = []
        for _ in range(16):
            items = [(b, 2 if b in WALK_PINNED_BITS else 1) for b in remaining]
            total = sum(w for _b, w in items)
            pick = d.rng.randrange(total)
            for b, w in items:
                if pick < w:
                    positions.append(b)
                    remaining.remove(b)
                    break
                pick -= w
        d.put("walk_positions", positions)
        state = lc_state_class(r)
        steps = []
        for b in positions:
            if b in WALK_PINNED_BITS and state == ST_TEST_DEV:
                owner = "SIP_DIS"
            elif b in WALK_PINNED_BITS and state == ST_PROD:
                owner = "SYS_DIS"
            else:
                owner = d.choice(f"walk_owner.{b}", ("SIP_DIS", "SYS_DIS"))
            width = d.choice(f"walk_width.{b}", (64, 32))
            steps.append({"bit": b, "owner": owner, "width": width})
        leg["walk"] = steps
    elif leg_name == LEG_E:
        order = d.shuffled("leg_e_order", NAMED_DBG_BITS)
        leg["leg_e"] = [{"bit": b, "width": d.choice(f"leg_e_width.{b}", (64, 32))} for b in order]
    return _make_plan(T_FEAT_MATRIX, seed, d, r, sip, sys_, img, leg)


TRANSIENT_STARTS = {
    "TEST_DEV": LC_TEST_DEV,
    "PROD": LC_PROD,
    "RMA_SIP": LC_RMA_SIP_0,
    "RMA_CHIPLET": LC_RMA_CHIP_0,
    "INVALID": LC_INVALID_0101,
}
TRANSIENT_SCRIPTS = (("SIP",), ("CHIPLET",), ("CHIPLET", "SIP"), ("SIP", "CHIPLET"))


def plan_transient_rma(seed: int) -> SepEfusePlan:
    """(enable, start state), token script, X bit, pair, window-control spare bit.

    Order as the Randomization field. (0, TEST_DEV) weighs 1 in 3; the other nine
    pairs share 2 in 3. INVALID is raw ``0101``.
    """
    d = SepEfuseDraws(seed)
    pairs = [((0, "TEST_DEV"), 9)] + [
        ((en, st), 2) for en in (0, 1) for st in TRANSIENT_STARTS if (en, st) != (0, "TEST_DEV")
    ]
    en, start = d.weighted("enable_start", pairs)
    script = d.choice("script", TRANSIENT_SCRIPTS)
    raw = TRANSIENT_STARTS[start]
    if start in ("RMA_SIP", "RMA_CHIPLET"):
        raw |= d.choice("x_bit", (0, 1))
    sip, sys_ = draw_dis_pair(d)
    img = build_image(
        lc_raw=raw, sip_dis=sip, sys_dis=sys_, pins={**rma_digest_pins(), "TRANSIENT_RMA_EN": en}
    )
    spare_field = d.choice("window_ctl_field", SPARE_FIELDS)
    spare = _pick_bit(d, "window_ctl_bit", img, spare_field)
    leg = {
        "enable": en,
        "start": start,
        "script": script,
        "leg_b": en == 0 and start == "TEST_DEV",
        "spare": spare,
    }
    return _make_plan(T_TRANSIENT, seed, d, raw, sip, sys_, img, leg)


TOKEN_SHAPES = ("flip", "swap", "byte_swap", "zeros", "ones", "digest", "foreign")
_SEC_DIS_SHAPES = ("flip", "ones", "digest", "foreign")


def token_channel_cells() -> list[tuple[str, str]]:
    """The 18 legal (shape, channel) mismatch cells."""
    return [
        (s, ch) for ch in CHANNELS for s in TOKEN_SHAPES if ch != CH_SEC_DIS or s in _SEC_DIS_SHAPES
    ]


def plan_token_channel(seed: int) -> SepEfusePlan:
    """Fixed image; runtime draws: walk order, 18-cell order, independence order, decoys,
    flip positions, swap words and byte-swap words. Word orders come from
    ``plan.draw.word_order`` at each array write."""
    d = SepEfuseDraws(seed)
    img = build_image(
        lc_raw=LC_TEST_DEV,
        sip_dis=FIXED_SIP_DIS,
        sys_dis=FIXED_SYS_DIS,
        pins={**rma_digest_pins(), "TRANSIENT_RMA_EN": 0},
    )
    leg: dict[str, Any] = {}
    leg["walk_order"] = d.shuffled("walk_channel_order", CHANNELS)
    leg["cell_order"] = d.shuffled("cell_order", token_channel_cells())
    leg["independence_order"] = d.shuffled("independence_order", CHANNELS)
    leg["decoys"] = {
        ch: d.until(f"decoy_subset.{ch}", lambda: d.rng.getrandbits(8), lambda v: v != 0)
        for ch in leg["walk_order"]
    }
    shapes: dict[tuple[str, str], int] = {}
    for shape, ch in leg["cell_order"]:
        base = RIGHT_TOKEN[ch]
        if shape == "flip":
            shapes[(shape, ch)] = shape_flip(base, d.randrange(f"flip_pos.{ch}", 0, 256))
        elif shape == "swap":
            i, j = d.sample(f"swap_words.{ch}", range(8), 2)
            shapes[(shape, ch)] = shape_swap(base, i, j)
        elif shape == "byte_swap":
            k = d.choice(
                f"byte_swap_word.{ch}",
                [k for k, w in enumerate(token_words(base)) if not palindromic_word(w)],
            )
            shapes[(shape, ch)] = shape_byte_swap(base, k)
        elif shape == "zeros":
            shapes[(shape, ch)] = 0
        elif shape == "ones":
            shapes[(shape, ch)] = TOKEN_ONES
        elif shape == "digest":
            shapes[(shape, ch)] = expected_digest(ch, img)
        else:
            shapes[(shape, ch)] = FOREIGN_TOKEN[ch]
    leg["shape_tokens"] = shapes
    return _make_plan(T_TOKEN_CHANNEL, seed, d, LC_TEST_DEV, FIXED_SIP_DIS, FIXED_SYS_DIS, img, leg)


FAULT_CELL_LABELS = (
    "fault_sip",
    "fault_chiplet",
    "fault_sec_dis",
    "common_match",
    "common_mismatch",
    "freeze_sip",
    "freeze_chiplet",
    "freeze_sec_dis",
)


def plan_token_fault(seed: int) -> SepEfusePlan:
    """Fault cell per channel, held phase per RMA cell, order of the eight cells, pair.

    RMA_SIP draws among (collapse or disagree) x copy {1, 2}; RMA_CHIPLET and SEC_DIS
    add the copy-0 disagree cell. SEC_DIS holds a Mismatch. Word orders come from
    ``plan.draw.word_order`` at each array write, after the pair.
    """
    d = SepEfuseDraws(seed)
    new_cells = [(k, c) for k in ("collapse", "disagree") for c in (1, 2)]
    faults = {}
    for ch in CHANNELS:
        cands = new_cells if ch == CH_SIP else [*new_cells, ("disagree", 0)]
        kind, copy = d.choice(f"fault_cell.{ch}", cands)
        faults[ch] = {"kind": kind, "copy": copy}
    for ch in (CH_SIP, CH_CHIPLET):
        faults[ch]["held"] = d.choice(f"held_phase.{ch}", ("match", "mismatch"))
    faults[CH_SEC_DIS]["held"] = "mismatch"
    order = d.shuffled("cell_order", FAULT_CELL_LABELS)
    sip, sys_ = draw_dis_pair(d)
    img = build_image(
        lc_raw=LC_TEST_DEV,
        sip_dis=sip,
        sys_dis=sys_,
        pins={**rma_digest_pins(), "TRANSIENT_RMA_EN": 0},
    )
    leg = {"faults": faults, "cell_order": order}
    return _make_plan(T_TOKEN_FAULT, seed, d, LC_TEST_DEV, sip, sys_, img, leg)


IF_CASES = (
    "presense",
    "read_go_no_enable",
    "oor_read",
    "oor_program",
    "lock_program",
    "lock_read",
    "both_enables",
    "data0",
)


def plan_interface_status(seed: int) -> SepEfusePlan:
    """Case order, out-of-range address, the two lock slots, program and read bits.

    Order: case order; out-of-range address in 8193..65534; write-lock slot
    (1..39); read-lock slot (1..39, not 11, 13, 15, not the write-lock slot); the
    four spare fields of the pre-sense program, its twin, the lock twin and the data-0
    program (pairwise different, none a lock-slot field), each with a zero bit; the
    zero bit of the lock-blocked program; the bit of the lock-blocked read; the
    unlocked read bits of the case frame, the read-go case, the lock-read twin and
    the both-enables case.
    """
    d = SepEfuseDraws(seed)
    order = d.shuffled("case_order", IF_CASES)
    oor = d.randrange("oor_address", 8193, 65535)
    wl = d.randrange("write_lock_slot", 1, 40)
    rl = d.choice("read_lock_slot", [s for s in range(1, 40) if s not in (11, 13, 15, wl)])
    sip, sys_ = draw_dis_pair(d)
    locks = (1 << write_lock_bit(wl)) | (1 << read_lock_bit(rl))
    img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, lock_bits=locks)
    locked = {LOCK_SLOT_FIELD[wl], LOCK_SLOT_FIELD[rl]}
    spares = d.sample("program_spare_fields", [f for f in SPARE_FIELDS if f not in locked], 4)
    progs = {}
    for role, f in zip(("presense", "presense_twin", "lock_twin", "data0"), spares):
        progs[role] = _pick_bit(d, f"program.{role}", img, f)
    lock_prog = _pick_bit(d, "program.lock_blocked", img, LOCK_SLOT_FIELD[wl])
    lock_read = _pick_bit(d, "read.lock_blocked", img, LOCK_SLOT_FIELD[rl], zero=False)
    unlocked = [f for f in FIELD_NAMES if f not in locked and f != "LC_STATE"]
    reads = {}
    for role in ("frame", "read_go_no_enable", "lock_read_twin", "both_enables"):
        f = d.choice(f"read_field.{role}", unlocked)
        reads[role] = _pick_bit(d, f"read.{role}", img, f, zero=False)
    leg = {
        "case_order": order,
        "oor_addresses": [8192, 65535, oor],
        "write_lock_slot": wl,
        "read_lock_slot": rl,
        "programs": progs,
        "lock_program": lock_prog,
        "lock_read": lock_read,
        "reads": reads,
    }
    return _make_plan(T_IF_STATUS, seed, d, LC_TEST_DEV, sip, sys_, img, leg)


LOCK_KINDS = (("lock_leg", 4), ("single_bit", 1), ("exempt", 1), ("order", 2), ("chain", 2))
_LOCK_KIND_NONE, _LOCK_KIND_W, _LOCK_KIND_R, _LOCK_KIND_WR = "none", "write", "read", "write_read"
_SHADOW_WRITE_FIELDS = ("SIP_DIS", "SYS_DIS", "REQUIRED_SIGNERS", "REQUIRED_ALGS")


def _lock_bits_of(slot: int, kind: str) -> int:
    out = 0
    if kind in (_LOCK_KIND_W, _LOCK_KIND_WR):
        out |= 1 << write_lock_bit(slot)
    if kind in (_LOCK_KIND_R, _LOCK_KIND_WR):
        out |= 1 << read_lock_bit(slot)
    return out


def _all_words_nonzero(sip: int, sys_: int) -> bool:
    return all((v >> (32 * k)) & WORD_MASK for v in (sip, sys_) for k in (0, 1))


def plan_lock_slot_matrix(seed: int) -> SepEfusePlan:
    """Leaf kind (lock leg 4, single bit 1, exempt 1, order 2, chain 2), pair, then per kind.

    Lock leg: target slot (3..40); lock kind per other data slot of 3..40 (the
    target's neighbours unlocked; read alone never on 11, 13, 15); three program
    slots; slot order 1..40; the zero bit of each program slot; the read bit of
    each read-locked field and unlocked neighbour; the shadow-write bit of each
    shadow-write field. Single bit: slot, kind, twin neighbour. Exempt: the
    ``CLASS_KEY`` bit and the ``LOCKS`` twin bit. Order: slot, permutation, bits a,
    b, c, control slot and bit. Chain: round count, version field, index class and
    index, then per round field, bit and read-back flag.
    """
    d = SepEfuseDraws(seed)
    kind = d.weighted("leaf_kind", LOCK_KINDS)
    # A read-locked field reads its staged value at the probe in every word.
    sip, sys_ = draw_dis_pair(d, extra=_all_words_nonzero)
    leg: dict[str, Any] = {"kind": kind}
    lock_bits = 0
    narrow: dict[str, int] = {}
    pins: dict[str, int] = {}
    if kind == "lock_leg":
        target = d.randrange("target_slot", 3, 41)
        neighbours = {target - 1, target + 1}
        layout: dict[int, str] = {target: _LOCK_KIND_WR}
        for s in range(3, 41):
            if s == target or s in neighbours:
                continue
            kinds = (
                (_LOCK_KIND_NONE, _LOCK_KIND_W, _LOCK_KIND_WR)
                if s in (11, 13, 15)
                else (_LOCK_KIND_NONE, _LOCK_KIND_W, _LOCK_KIND_R, _LOCK_KIND_WR)
            )
            layout[s] = d.choice(f"lock_kind.{s}", kinds)
        for s, k in layout.items():
            lock_bits |= _lock_bits_of(s, k)
        prog_slots = d.sample(
            "program_slots", [s for s in range(3, 41) if s != target and s not in neighbours], 3
        )
        leg.update(target=target, layout=layout, program_slots=prog_slots)
        leg["slot_order"] = d.shuffled("slot_order", range(1, 41))
        img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, lock_bits=lock_bits)
        prog_set = [target, *[n for n in sorted(neighbours) if 1 <= n <= 40], *prog_slots]
        leg["program_bits"] = {
            s: _pick_bit(d, f"program_bit.{s}", img, LOCK_SLOT_FIELD[s]) for s in prog_set
        }
        read_slots = [s for s in range(1, 41) if layout.get(s) in (_LOCK_KIND_R, _LOCK_KIND_WR)]
        read_slots += [n for n in sorted(neighbours) if 1 <= n <= 40]
        leg["read_bits"] = {
            s: _pick_bit(d, f"read_bit.{s}", img, LOCK_SLOT_FIELD[s], zero=False)
            for s in read_slots
        }
        leg["shadow_write_bits"] = {
            f: _pick_bit(d, f"shadow_write_bit.{f}", img, f) for f in _SHADOW_WRITE_FIELDS
        }
    elif kind == "single_bit":
        slot = d.choice("single_slot", (1, 2))
        lk = d.choice("single_kind", (_LOCK_KIND_R, _LOCK_KIND_W))
        fname = LOCK_SLOT_FIELD[slot]
        used = NARROW_USED[fname]
        narrow[fname] = used if lk == _LOCK_KIND_R else 0
        lock_bits = _lock_bits_of(slot, lk)
        twin = 2 if slot == 1 else d.choice("twin_neighbour", (1, 3))
        leg.update(slot=slot, lock_kind=lk, twin_slot=twin)
        img = build_image(
            lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, narrow=narrow, lock_bits=lock_bits
        )
        leg["twin_bit"] = _pick_bit(
            d, "twin_bit", img, LOCK_SLOT_FIELD[twin], zero=lk == _LOCK_KIND_W
        )
    elif kind == "exempt":
        lock_bits = _MASK64 | (_LOCKS_ASSIGNED_SPARE << 64)
        img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, lock_bits=lock_bits)
        leg["class_key_bit"] = _pick_bit(d, "class_key_bit", img, "CLASS_KEY", zero=False)
        leg["locks_bit"] = _pick_bit(d, "locks_bit", img, "LOCKS", zero=False)
    elif kind == "order":
        slot = d.choice("order_slot", (3, 4, 22))
        perm = d.shuffled("order_permutation", ("write_a", "lock", "write_b"))
        img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_)
        fname = LOCK_SLOT_FIELD[slot]
        abc = d.sample("order_bits_abc", zero_bits(img, fname), 3)
        ctl_slot = d.choice("control_slot", [s for s in (3, 4, 22) if s != slot])
        leg.update(slot=slot, permutation=perm, bits_abc=abc, control_slot=ctl_slot)
        leg["control_bit"] = _pick_bit(d, "control_bit", img, LOCK_SLOT_FIELD[ctl_slot])
    else:
        rounds = d.randrange("round_count", 1, 5)
        version = d.choice("version_field", VERSION_FIELDS)
        idx_class = d.choice("index_class", ("0", "255", "middle"))
        index = {"0": 0, "255": 255}.get(idx_class)
        if index is None:
            index = d.randrange("middle_index", 1, 255)
        pins[version] = 0
        img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, pins=pins)
        ref = SepEfuseImage()
        ref.words = list(img.words)
        excluded = {"LC_STATE", "LOCKS", "LOCKS_SPARE", version}
        chain = []
        for rnd in range(rounds):
            # The drawn bit is 0 in the model image, so a field with no 0 bit left is not drawn.
            fields = [
                LOCK_SLOT_FIELD[s] for s in range(1, 41) if LOCK_SLOT_FIELD[s] not in excluded
            ]
            fname = d.choice(f"round.{rnd}.field", [f for f in fields if zero_bits(ref, f)])
            bit = _pick_bit(d, f"round.{rnd}.bit", ref, fname)
            rb = d.choice(f"round.{rnd}.read_back", (0, 1))
            ref.words[field_word(fname) + bit["word"]] |= 1 << bit["bit"]
            chain.append({**bit, "read_back": rb})
        leg.update(rounds=chain, version_field=version, index_class=idx_class, version_index=index)
        leg["version_bit"] = {
            "field": version,
            "word": index // 32,
            "bit": index % 32,
            "addr": bit_address(version, index // 32, index % 32),
        }
    return _make_plan(T_LOCK_SLOT, seed, d, LC_TEST_DEV, sip, sys_, img, leg)


_STM_STATES = ((LC_TEST_DEV, 2), (LC_PROD, 1), (LC_RMA_SIP_0, 1))
STM_TARGETS = ("LOCKS", "LOCKS_SPARE", "SIP_DIS", "SYS_DIS")
STM_PROGRAM_CLASSES = ("wide", "narrow32", "dis", "locks", "spare")


def plan_secure_tm_matrix(seed: int) -> SepEfusePlan:
    """State, pair, target order, five program classes, written bits of both sources.

    The pair precedes the target bits because a written bit must be absent from the
    staged shadow. Program classes: a 256-bit field other than the two digests, the
    secret fields and the spares; a 32-bit narrow field; a disable bit; a ``LOCKS``
    bit; a spare word. A lock bit (target or program) never locks a slot of a target,
    a program field or a secret field. Each target takes four distinct absent bits:
    frontdoor and JTAG at strap 1, frontdoor and JTAG at strap 0.
    """
    d = SepEfuseDraws(seed)
    raw = d.weighted("state", _STM_STATES)
    sip, sys_ = draw_dis_pair(d)
    img = build_image(lc_raw=raw, sip_dis=sip, sys_dis=sys_)
    target_order = d.shuffled("target_order", STM_TARGETS)
    progs: dict[str, dict[str, Any]] = {}
    wide_cands = [f for f in WIDE_FIELDS if f not in DIGEST_FIELDS + SECRET_FIELDS + SPARE_FIELDS]
    progs["wide"] = _pick_bit(d, "program.wide", img, d.choice("program.wide.field", wide_cands))
    progs["narrow32"] = _pick_bit(
        d, "program.narrow32", img, d.choice("program.narrow32.field", NARROW_FIELDS)
    )
    progs["dis"] = _pick_bit(
        d, "program.dis", img, d.choice("program.dis.field", ("SIP_DIS", "SYS_DIS"))
    )
    spare_field = d.choice("program.spare.field", SPARE_FIELDS)
    used_slots = {SLOT_OF_FIELD[f] for f in ("SIP_DIS", "SYS_DIS", *SECRET_FIELDS)}
    used_slots |= {SLOT_OF_FIELD[progs[c]["field"]] for c in ("wide", "narrow32", "dis")}
    used_slots |= {SLOT_OF_FIELD[spare_field], 0}
    safe_locks = [
        (b // 32, b % 32)
        for s in range(41)
        if s not in used_slots
        for b in (write_lock_bit(s), read_lock_bit(s))
        if b < 64
    ]
    safe_spare = [
        (0, b - 64)
        for s in range(41)
        if s not in used_slots
        for b in (write_lock_bit(s), read_lock_bit(s))
        if b >= 64
    ]
    lw, lb = d.choice("program.locks", safe_locks)
    progs["locks"] = {"field": "LOCKS", "word": lw, "bit": lb, "addr": bit_address("LOCKS", lw, lb)}
    progs["spare"] = _pick_bit(d, "program.spare", img, spare_field)
    taken_locks = {(lw, lb)}
    targets: dict[str, list[dict[str, Any]]] = {}
    for t in target_order:
        if t == "LOCKS":
            cands = [c for c in safe_locks if c not in taken_locks]
        elif t == "LOCKS_SPARE":
            cands = safe_spare
        else:
            cands = [
                c
                for c in zero_bits(img, t)
                if not (
                    t == progs["dis"]["field"] and c == (progs["dis"]["word"], progs["dis"]["bit"])
                )
            ]
        picks = d.sample(f"target_bits.{t}", cands, 4)
        targets[t] = [
            {"field": t, "word": w, "bit": b, "source": src}
            for (w, b), src in zip(picks, ("fd_strap1", "jtag_strap1", "fd_strap0", "jtag_strap0"))
        ]
    leg = {
        "target_order": target_order,
        "programs": progs,
        "targets": targets,
        "jtag_leg": raw == LC_TEST_DEV,
    }
    return _make_plan(T_SECURE_TM, seed, d, raw, sip, sys_, img, leg)


_IFCTL_REGS = (
    "EFUSE_INTERFACE_CTRL_STATUS",
    "EFUSE_PROGRAM_CTRL",
    "EFUSE_READ_CTRL",
    "EFUSE_PROGRAM_INTERFACE_READ_DATA",
    "EFUSE_READ_INTERFACE_READ_DATA",
    "EFUSE_READ_REQ_TIMEOUT",
    "EFUSE_PROGRAM_REQ_TIMEOUT",
)
_IFCTL_WR_REGS = ("EFUSE_INTERFACE_CTRL_STATUS", "EFUSE_PROGRAM_CTRL", "EFUSE_READ_CTRL")
_REQUIRED_CELLS = (
    ("shadow", "rd"),
    ("shadow", "wr"),
    ("ifctl", "rd"),
    ("ifctl", "wr"),
    ("token_word", "rd"),
    ("token_word", "wr"),
    ("eop", "wr"),
    ("match", "rd"),
)
_EXTRA_CELLS = (
    ("shadow", "rd"),
    ("shadow", "wr"),
    ("ifctl", "rd"),
    ("ifctl", "wr"),
    ("token_word", "rd"),
    ("token_word", "wr"),
    ("match", "rd"),
)
_JTAG_VECTORS = ("TOKEN_T1", "TOKEN_T2", "TOKEN_OTHER")


def plan_jtag_access(seed: int) -> SepEfusePlan:
    """State, image vectors, spare bits c and p, then the access list.

    The image dimensions come first because a shadow-write pattern sets a writable bit
    at 0 in the staged image. Order: state (PROD or RMA_SIP); ``SIP_DIS`` function
    bits (DBG_1 and DBG_2 all set, a 0 left in Function); ``SYS_DIS`` (non-zero, a 0
    bit); c and p; N (15..20); the go channel; the word order and the vector of each
    word write of its array; insert positions of the other token-block accesses and
    the extras; the class and operation of each extra; per access its address and
    pattern.
    """
    d = SepEfuseDraws(seed)
    raw = d.choice("state", (LC_PROD, LC_RMA_SIP_0))
    func = d.until("sip_dis_func", lambda: d.rng.getrandbits(16), lambda v: v != 0xFFFF)
    sip = DBG1_MASK | DBG2_MASK | (func << 48)
    sys_ = d.until("sys_dis", lambda: d.rng.getrandbits(64), lambda v: v not in (0, _MASK64))
    img = build_image(
        lc_raw=raw, sip_dis=sip, sys_dis=sys_, pins={**rma_digest_pins(), "TRANSIENT_RMA_EN": 0}
    )
    c_field, p_field = d.sample("spare_fields_c_p", SPARE_FIELDS, 2)
    c_bit = _pick_bit(d, "spare_bit_c", img, c_field)
    p_bit = _pick_bit(d, "spare_bit_p", img, p_field)
    n = d.randrange("access_count", 15, 21)
    go_ch = d.choice("go_channel", (CH_SIP, CH_CHIPLET))
    order = d.word_order(f"go_{go_ch}")
    writes = []
    content = [0] * 8
    for k in order:
        vec = d.choice(f"word_vector.{k}", _JTAG_VECTORS)
        word = token_words(TOKENS[vec])[k]
        content[k] = word
        writes.append(
            {
                "cls": "token_word",
                "op": "wr",
                "channel": go_ch,
                "index": k,
                "vector": vec,
                "addr": TOKEN_ARRAY_ADDR[go_ch][k],
                "data": word,
            }
        )
    golden = match_code(go_ch, words_token(content), img)
    token_block: list[dict[str, Any]] = list(writes)
    eop_pos = d.randrange("eop_position", 8, len(token_block) + 1)
    token_block.insert(
        eop_pos,
        {
            "cls": "eop",
            "op": "wr",
            "channel": go_ch,
            "addr": TOKEN_EOP_ADDR,
            "data": GO_MASK[go_ch],
            "golden": golden,
        },
    )
    denied: list[dict[str, Any]] = [
        {"cls": c, "op": o} for c, o in _REQUIRED_CELLS if c in ("shadow", "ifctl")
    ]
    others: list[dict[str, Any]] = [{"cls": "token_word", "op": "rd"}, {"cls": "match", "op": "rd"}]
    for i in range(n - 15):
        c, o = d.choice(f"extra.{i}", _EXTRA_CELLS)
        (denied if c in ("shadow", "ifctl") else others).append({"cls": c, "op": o})
    for i, acc in enumerate(others):
        lo = 0
        if acc["cls"] == "token_word" and acc["op"] == "rd":
            # A token word read follows the first word write.
            lo = 1 + next(
                j for j, a in enumerate(token_block) if a["cls"] == "token_word" and a["op"] == "wr"
            )
        pos = d.randrange(f"token_block_position.{i}", lo, len(token_block) + 1)
        token_block.insert(pos, acc)
    written: list[tuple[str, int]] = []
    for i, acc in enumerate(token_block):
        if acc["cls"] == "token_word" and acc["op"] == "wr" and "addr" not in acc:
            k = d.randrange(f"sec_dis_word.{i}", 0, 8)
            acc.update(
                channel=CH_SEC_DIS,
                index=k,
                vector="TOKEN_OTHER",
                addr=TOKEN_ARRAY_ADDR[CH_SEC_DIS][k],
                data=token_words(TOKEN_OTHER)[k],
            )
        elif acc["cls"] == "token_word" and acc["op"] == "rd":
            ch, k = d.choice(f"token_read_word.{i}", written)
            acc.update(channel=ch, index=k, addr=TOKEN_ARRAY_ADDR[ch][k])
        elif acc["cls"] == "match":
            ch = d.choice(f"match_channel.{i}", (CH_SIP, CH_CHIPLET, CH_SEC_DIS))
            acc.update(channel=ch, addr=MATCH_ADDR[ch])
        if acc["cls"] == "token_word" and acc["op"] == "wr":
            written.append((acc["channel"], acc["index"]))
    denied = d.shuffled("denied_order", denied)
    rw_cands = [f for f in SHADOW_RW_FIELDS if zero_bits(img, f)]
    for i, acc in enumerate(denied):
        if acc["cls"] == "shadow" and acc["op"] == "rd":
            w = d.randrange(f"shadow_read_word.{i}", 0, NUM_FUSE_WORDS)
            acc.update(addr=SHADOW_BASE + 4 * w)
        elif acc["cls"] == "shadow":
            f = d.choice(f"shadow_write_field.{i}", rw_cands)
            bit = _pick_bit(d, f"shadow_write_bit.{i}", img, f)
            acc.update(field=f, addr=shadow_addr(f, bit["word"]), data=1 << bit["bit"])
        elif acc["op"] == "rd":
            reg = d.choice(f"ifctl_read_reg.{i}", _IFCTL_REGS)
            acc.update(reg=reg, addr=EFUSE_INTERFACE_CTRL.addr(reg))
        else:
            reg = d.choice(f"ifctl_write_reg.{i}", _IFCTL_WR_REGS)
            if reg == "EFUSE_INTERFACE_CTRL_STATUS":
                data = EFUSE_INTERFACE_CTRL.field_mask(reg, "efuse_read_addr_error_clear")
            elif reg == "EFUSE_PROGRAM_CTRL":
                data = program_ctrl_word(p_bit["addr"])
            else:
                data = read_ctrl_word(d.randrange(f"ifctl_read_addr.{i}", 0, 8192))
            acc.update(reg=reg, addr=EFUSE_INTERFACE_CTRL.addr(reg), data=data)
    leg = {
        "access_count": n,
        "go_channel": go_ch,
        "go_golden": golden,
        "denied": denied,
        "token_block": token_block,
        "spare_c": c_bit,
        "spare_p": p_bit,
    }
    return _make_plan(T_JTAG_ACCESS, seed, d, raw, sip, sys_, img, leg)


_SDIS_CANDIDATES = tuple(
    f
    for f in FIELD_NAMES
    if f in WIDE_FIELDS
    or f
    in (
        "CHIPLET_PUBK_REVOKE",
        "STATUS_RPT",
        "ROM_CTL",
        "SYSCLK_FREQ_MHZ",
        "REQUIRED_SIGNERS",
        "REQUIRED_ALGS",
    )
)
_SDIS_SPLIT = 0x200


def plan_sec_dis_timing(seed: int) -> SepEfusePlan:
    """Class (B or C), staged fields, pair; class B match offset k at runtime.

    Staged fields: 4 to 8 fields hold their non-zero distinct values, at least one
    below byte offset 0x200 and one at or above it; every other field is 0 except
    ``LC_STATE`` and the pair. ``plan.leg["m"]`` counts the staged non-zero fields
    (``LC_STATE`` excepted).
    """
    d = SepEfuseDraws(seed)
    cls = d.choice("class", ("B", "C"))
    count = d.randrange("staged_field_count", 4, 9)
    lo = d.choice(
        "staged_low_field", [f for f in _SDIS_CANDIDATES if field_offset(f) < _SDIS_SPLIT]
    )
    hi = d.choice(
        "staged_high_field", [f for f in _SDIS_CANDIDATES if field_offset(f) >= _SDIS_SPLIT]
    )
    rest = d.sample(
        "staged_other_fields", [f for f in _SDIS_CANDIDATES if f not in (lo, hi)], count - 2
    )
    staged = [lo, hi, *rest]
    sip, sys_ = draw_dis_pair(d)
    full = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_)
    zero_pins = {
        f: 0 for f in FIELD_NAMES if f not in staged and f not in ("LC_STATE", "SIP_DIS", "SYS_DIS")
    }
    img = build_image(lc_raw=LC_TEST_DEV, sip_dis=sip, sys_dis=sys_, pins=zero_pins)
    for f in staged:
        img.set_words(f, [full.words[field_word(f) + k] for k in range(field_n_words(f))])
    m = sum(1 for f in FIELD_NAMES if f != "LC_STATE" and img.field_int(f) != 0)
    leg = {"class": cls, "staged_fields": staged, "m": m}
    return _make_plan(T_SEC_DIS_TIMING, seed, d, LC_TEST_DEV, sip, sys_, img, leg)


def draw_match_offset(p: SepEfusePlan, k_lo: int, k_hi: int) -> int:
    """Class B match offset k in [k_lo, k_hi], drawn after every static draw."""
    if k_lo > k_hi:
        raise ValueError(f"empty match window [{k_lo}, {k_hi}]")
    return p.draw.randrange("match_offset_k", k_lo, k_hi + 1)


_SHIM_CLASSES = (("edge_10", 2), ("edge_254", 2), ("revoke", 1), ("inner", 1))
# Hold budget of the timeout cell in clocks: m x T never exceeds it (test parameter).
SHIM_HOLD_BUDGET = 120_000
SHIM_T_MIN = 2_000
SHIM_M_MAX = 4


def plan_shim_response_fault(seed: int) -> SepEfusePlan:
    """Fixed image; runtime draws: word class, inner word, spare bits a, b, c, T, m.

    Order: word class (10 and 254 weight 2, the ``CHIPLET_PUBK_REVOKE`` word and an
    inner 256-bit word weight 1); the inner word (11..253, in a 256-bit field); the
    three spare bits; T in [SHIM_T_MIN, SHIM_HOLD_BUDGET // SHIM_M_MAX]; m in
    [2, SHIM_M_MAX].
    """
    d = SepEfuseDraws(seed)
    img = build_image(lc_raw=LC_TEST_DEV, sip_dis=FIXED_SIP_DIS, sys_dis=FIXED_SYS_DIS)
    cls = d.weighted("word_class", _SHIM_CLASSES)
    if cls == "edge_10":
        w = 10
    elif cls == "edge_254":
        w = 254
    elif cls == "revoke":
        w = field_word("CHIPLET_PUBK_REVOKE")
    else:
        wide_words = [
            field_word(f) + k
            for f in WIDE_FIELDS
            for k in range(8)
            if 11 <= field_word(f) + k <= 253
        ]
        w = d.choice("inner_word", wide_words)
    cands = [(f, wb) for f in SPARE_FIELDS for wb in zero_bits(img, f)]
    picks = d.sample("spare_bits_abc", cands, 3)
    spares = [
        {"field": f, "word": ww, "bit": b, "addr": bit_address(f, ww, b)} for f, (ww, b) in picks
    ]
    t = d.randrange("timeout_cycles_T", SHIM_T_MIN, SHIM_HOLD_BUDGET // SHIM_M_MAX + 1)
    m = d.randrange("hold_multiple_m", 2, SHIM_M_MAX + 1)
    leg = {
        "word_class": cls,
        "word": w,
        "spare_a": spares[0],
        "spare_b": spares[1],
        "spare_c": spares[2],
        "timeout_T": t,
        "hold_m": m,
    }
    return _make_plan(T_SHIM_FAULT, seed, d, LC_TEST_DEV, FIXED_SIP_DIS, FIXED_SYS_DIS, img, leg)


PLANNERS: dict[str, Callable[[int], SepEfusePlan]] = {
    T_WINDOW_DECODE: plan_window_decode_reset,
    T_FIELD_LAYOUT: plan_field_layout,
    T_CODEWORD: plan_state_codeword,
    T_FEAT_MATRIX: plan_feat_ctrl_matrix,
    T_TRANSIENT: plan_transient_rma,
    T_TOKEN_CHANNEL: plan_token_channel,
    T_TOKEN_FAULT: plan_token_fault,
    T_IF_STATUS: plan_interface_status,
    T_LOCK_SLOT: plan_lock_slot_matrix,
    T_SECURE_TM: plan_secure_tm_matrix,
    T_JTAG_ACCESS: plan_jtag_access,
    T_SEC_DIS_TIMING: plan_sec_dis_timing,
    T_SHIM_FAULT: plan_shim_response_fault,
}


def plan(test: str, seed: int) -> SepEfusePlan:
    """The plan of ``test`` for ``seed``: the one call of prestage and runtime."""
    try:
        planner = PLANNERS[test]
    except KeyError:
        raise KeyError(f"no eFuse plan for test {test!r}") from None
    return planner(int(seed))


def image_words(test: str, seed: int) -> list[int]:
    """The 256 t=0 image words of ``test`` for ``seed``."""
    return plan(test, seed).words()
