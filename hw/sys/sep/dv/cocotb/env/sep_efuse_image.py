# SPDX-License-Identifier: Apache-2.0
"""SEP eFuse/OTP image builder for the OSS cocotb flow.

Builds the 256-word (8192-bit) SEP fuse array as a ``$readmemh`` image the
generic efuse bank model (``hw/ip/efuse/dv/models/efuse_bank_model.sv``)
loads at t=0 via ``+sep_efuse_hex`` (staged pre-sim by dv_sim_prestage.py). The
field schema, offsets and widths mirror ``sep_efuse_pkg::EfuseFieldMap``
(``hw/sys/sep/rtl/efuse/sep_efuse_pkg.sv``, generated from
``hw/sys/sep/regs/blocks/sep_efuse_map/sep_efuse_map.rdl``); the constraints
mirror the reference UVM ``sep_efuse_item`` golden model.

The same object is the golden reference for the shadow-readout checker:
``expected_shadow(field)`` returns the value software should read back from the
shadow-register block after fuse-sense, applying the hardware transforms (only
LC_STATE is transformed — differential-encoded ``{~raw, raw}`` — every other
readable field reads back verbatim).
"""

from __future__ import annotations

from sep_reg_meta import sym

# The generated map itself, for enumerating the eFuse register set rather than
# naming each entry. Import order matters: sep_reg_meta puts regs/gen/py on
# sys.path as an import side effect, so it has to come first.
import sep_reg  # noqa: E402

import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Array geometry (sep_efuse_pkg: NumEfuseBits=8192, NumFuseWordWidth=32).
NUM_FUSE_WORDS = 256
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

# Software-visible shadow-register block base.
SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
# SEP CPU-ctrl fuse-sense-done status (separate block).
SEP_CPU_CTRL_BASE = sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")
SEP_FUSE_SENSE_STATUS = SEP_CPU_CTRL_BASE + 0x150

# LC_STATE's shadow word (efuse_pkg::SHADOW_IDX_LC_STATE). The OTP word carries the
# 4-bit raw code in [3:0] and the FSM differential-encodes it.
#
# Derived, never written down. This index moved 2 -> 3 when LOCKS_SPARE was inserted
# ahead of LC_STATE, and every hardcoded copy of it in this environment then pointed
# at LOCKS_SPARE while still claiming to read the lifecycle state -- which the shadow
# checkers could not flag, because a wrong-but-self-consistent differential pair looks
# exactly like a healthy one. Read it out of the generated map so the map is the only
# place it is stated.
LC_WORD_IDX = sym("SEP_EFUSE_MAP_LC_STATE_REG_OFFSET") // 4
LC_RAW_WIDTH = 4
# efuse_pkg::lc_state_raw_e — only these 7 codes are legal.
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SIP_0 = 0x2
LC_RMA_SIP_1 = 0x3
LC_RMA_CHIP_0 = 0x6
LC_RMA_CHIP_1 = 0x7
LC_PROD_END = 0x8
LEGAL_LC_RAW: Tuple[int, ...] = (
    LC_TEST_DEV, LC_PROD, LC_RMA_SIP_0, LC_RMA_SIP_1,
    LC_RMA_CHIP_0, LC_RMA_CHIP_1, LC_PROD_END,
)

# Field schema: (name, byte_offset, n_words, kind). Offsets/widths from
# sep_efuse_map_reg.svh; contiguous and summing to 256 words. kind drives
# randomization + the expected-shadow transform:
#   "lc"       — LC_STATE: word holds raw code, shadow reads {~raw, raw}.
#   "locks"    — LOCKS table: left unlocked by default so all fields read back.
#   "data"     — freely randomizable keys/digests/UIDs/ctrl fields.
# Kinds, keyed by generated register name. Everything not named here is "data":
# freely randomizable. Only the semantics live here -- offsets and lengths are read
# out of the generated map below, because a hand-written copy of the map is exactly
# what went stale when LOCKS_SPARE was inserted at 0x008 and shifted every field
# after it by one word.
_LOCK_REGS = ("LOCKS", "LOCKS_SPARE")
_LC_REGS = ("LC_STATE",)


def _derive_fields() -> Tuple[Tuple[str, int, int, str], ...]:
    """Build the field table from the generated eFuse map.

    Lengths come from the gap to the next register, so an inserted or resized field
    cannot leave this environment describing a map the DUT no longer has. The result
    is asserted to tile the array exactly, which is what lets the backdoor checker
    claim it covered all 256 words.
    """
    pfx, sfx = "SEP_EFUSE_MAP_", "_REG_OFFSET"
    regs = sorted(
        (int(getattr(sep_reg, n)), n[len(pfx):-len(sfx)])
        for n in dir(sep_reg)
        if n.startswith(pfx) and n.endswith(sfx)
    )
    if not regs:
        raise RuntimeError(
            f"no {pfx}*{sfx} symbols in the generated register header; "
            "regenerate it before running the eFuse tests"
        )
    out, total_bytes = [], NUM_FUSE_WORDS * (WORD_BITS // 8)
    for i, (off, name) in enumerate(regs):
        end = regs[i + 1][0] if i + 1 < len(regs) else total_bytes
        kind = "lc" if name in _LC_REGS else "locks" if name in _LOCK_REGS else "data"
        out.append((name, off, (end - off) // 4, kind))
    first, last = out[0], out[-1]
    if first[1] != 0:
        raise RuntimeError(f"eFuse map does not start at 0: {first[0]} @ {first[1]:#x}")
    covered = sum(f[2] for f in out)
    if covered != NUM_FUSE_WORDS:
        raise RuntimeError(
            f"derived eFuse map covers {covered} words, expected {NUM_FUSE_WORDS}"
        )
    return tuple(out)


_FIELDS: Tuple[Tuple[str, int, int, str], ...] = _derive_fields()


def lc_encode(raw: int) -> int:
    """Differential LC encoding stored in the LC_STATE shadow word: {~raw, raw}."""
    raw &= (1 << LC_RAW_WIDTH) - 1
    return (((~raw) & 0xF) << LC_RAW_WIDTH) | raw


class SepEfuseField:
    """One named fuse field: byte offset, word count, kind."""

    def __init__(self, name: str, offset: int, n_words: int, kind: str) -> None:
        self.name = name
        self.offset = offset            # byte offset within the fuse map
        self.word = offset >> 2         # word index into the 256-word array
        self.n_words = n_words
        self.kind = kind

    @property
    def shadow_addr(self) -> int:
        return SHADOW_BASE + self.offset


class SepEfuseImage:
    """A 256-word SEP fuse image plus the golden expected-shadow model.

    Golden assumptions (must match the tb wiring): the DUT runs with
    ``secure_tm`` tied 0 and LOCKS unlocked, so every field reads back verbatim
    except LC_STATE (differential-encoded). If a read-lock or secure_tm test is
    added, ``expected_shadow`` must model the gated readback (read-lock ->
    0xbadcab1e, secure_tm -> token digests zeroed) for those cases.
    """

    fields: Tuple[SepEfuseField, ...] = tuple(
        SepEfuseField(n, off, nw, k) for (n, off, nw, k) in _FIELDS
    )
    _by_name: Dict[str, SepEfuseField] = {f.name: f for f in fields}

    def __init__(self) -> None:
        self.words: List[int] = [0] * NUM_FUSE_WORDS

    # -- construction ------------------------------------------------------

    @classmethod
    def field(cls, name: str) -> SepEfuseField:
        return cls._by_name[name]

    def set_words(self, name: str, values: List[int]) -> "SepEfuseImage":
        """Set a field from a little-endian list of 32-bit words."""
        fld = self.field(name)
        if len(values) != fld.n_words:
            raise ValueError(
                f"{name} expects {fld.n_words} words, got {len(values)}"
            )
        for i, v in enumerate(values):
            self.words[fld.word + i] = v & WORD_MASK
        return self

    def set_int(self, name: str, value: int) -> "SepEfuseImage":
        """Set a field from a single (possibly wide) integer, little-endian."""
        fld = self.field(name)
        words = [(value >> (WORD_BITS * i)) & WORD_MASK for i in range(fld.n_words)]
        return self.set_words(name, words)

    def load(self, path: str | Path) -> "SepEfuseImage":
        """Load a preload file, auto-detecting the format: a per-bit reference suite
        ``*.preload`` (one 0/1 per line) vs a 256-word hex image."""
        toks = Path(path).read_text().split()
        if toks and all(t in ("0", "1") for t in toks) and len(toks) > NUM_FUSE_WORDS:
            return self.load_preload_bits(path)
        return self.load_hex(path)

    def load_hex(self, path: str | Path) -> "SepEfuseImage":
        """Load a 256-word ``$readmemh`` image (our format, or a reference-suite
        ``*_shadow_reg.preload`` -- same LSB-first word layout) as the golden.

        LC_STATE may be stored raw or differential-encoded in the file; either
        works because only the LC_STATE word's [3:0] (== the raw nibble) is significant.
        """
        path = Path(path)
        words = [int(tok, 16) for tok in path.read_text().split()]
        if len(words) > NUM_FUSE_WORDS:
            raise ValueError(f"{path}: {len(words)} words > {NUM_FUSE_WORDS}")
        self.words = [0] * NUM_FUSE_WORDS
        for i, w in enumerate(words):
            self.words[i] = w & WORD_MASK
        return self

    def load_preload_bits(self, path: str | Path) -> "SepEfuseImage":
        """Load a reference-suite OTP ``*.preload`` (one bit per line, LSB-first) as the
        golden, packing 32 bits/word to match the fuse-array word layout."""
        path = Path(path)
        bits = [c for c in path.read_text().split() if c in ("0", "1")]
        self.words = [0] * NUM_FUSE_WORDS
        for bit_idx, c in enumerate(bits):
            if c == "1":
                self.words[bit_idx // WORD_BITS] |= 1 << (bit_idx % WORD_BITS)
        return self

    def set_lc_state(self, raw: int) -> "SepEfuseImage":
        """Set LC_STATE by raw code (must be legal).

        Stores the full differential encoding ``{~raw, raw}`` in LC_STATE[7:0] --
        a valid differential value, matching the real OTP and the reference suite preload.
        A bare raw nibble (upper nibble 0) is itself a differential error, so LC
        is *always* constrained to a legal code AND a valid encoding.
        """
        if raw not in LEGAL_LC_RAW:
            raise ValueError(f"illegal LC raw code 0x{raw:x}")
        self.words[LC_WORD_IDX] = lc_encode(raw)
        return self

    def lc_raw(self) -> int:
        # Low nibble is the raw code whether the word holds raw or {~raw, raw}.
        return self.words[LC_WORD_IDX] & 0xF

    def field_int(self, name: str) -> int:
        """Read a field back as a single little-endian integer (inverse of
        ``set_int``). Used by the LCC golden model to source the 64-bit
        SIP_DIS / SYS_DIS disable vectors that drive feat_ctrl."""
        fld = self.field(name)
        value = 0
        for i in range(fld.n_words):
            value |= (self.words[fld.word + i] & WORD_MASK) << (WORD_BITS * i)
        return value

    def randomize(
        self,
        seed: int,
        *,
        lc_raw: Optional[int] = None,
        lock_prob: float = 0.0,
        fixed: Optional[Dict[str, int]] = None,
    ) -> "SepEfuseImage":
        """Seeded randomization honoring the non-randomizable-field constraints.

        Constraints (mirrors reference sep_efuse_item):
          * LC_STATE is restricted to the 7 legal raw codes (never an illegal
            encoding) — pinned via ``lc_raw`` or drawn from the legal set.
          * RESERVED_* fields stay 0.
          * LOCKS stays unlocked unless ``lock_prob`` > 0, so every field reads
            back (read-locks would return 0xbadcab1e instead of data).
          * ``fixed`` pins named fields to explicit values after randomization.
        """
        rng = random.Random(seed)
        for fld in self.fields:
            if fld.kind == "reserved":
                continue  # must stay zero
            if fld.kind == "lc":
                raw = lc_raw if lc_raw is not None else rng.choice(LEGAL_LC_RAW)
                self.set_lc_state(raw)
                continue
            if fld.kind == "locks":
                if lock_prob <= 0.0:
                    continue
                # NOTE: only the low 32 lock regions (LOCKS word 0) are modeled
                # here; word 1 stays 0. Lock *enforcement* (read-lock -> 0xbadcab1e,
                # write-lock) is not yet checked by the shadow checkers, so the
                # golden assumes fields stay readable. Extend both this and
                # expected_shadow() together when a lock-enforcement test is added.
                bits = 0
                for region in range(32):
                    if rng.random() < lock_prob:
                        bits |= 1 << region
                self.words[fld.word] = bits & WORD_MASK
                continue
            # generic data field: random per word
            for i in range(fld.n_words):
                self.words[fld.word + i] = rng.getrandbits(WORD_BITS)
        for name, value in (fixed or {}).items():
            self.set_int(name, value)
        return self

    # -- emission ----------------------------------------------------------

    def write_hex(self, path: str | Path) -> Path:
        """Emit a 256-line ``$readmemh`` image (one 8-hex-digit word per line)."""
        path = Path(path)
        path.write_text("".join(f"{w & WORD_MASK:08x}\n" for w in self.words))
        return path

    # -- golden model ------------------------------------------------------

    def shadow_word(self, word_idx: int) -> int:
        """Expected software-readback value for shadow word ``word_idx``.

        Only LC_STATE is transformed by the sense FSM; all other
        readable words read back verbatim (secure_tm=0, LOCKS unlocked).
        """
        if word_idx == LC_WORD_IDX:
            upper = self.words[LC_WORD_IDX] & 0xFFFF_FF00
            return upper | lc_encode(self.lc_raw())
        return self.words[word_idx] & WORD_MASK

    def expected_field(self, name: str) -> List[Tuple[int, int]]:
        """(addr, expected) pairs the checker reads for ``name``."""
        fld = self.field(name)
        return [
            (fld.shadow_addr + 4 * i, self.shadow_word(fld.word + i))
            for i in range(fld.n_words)
        ]

    def check_fields(self) -> List[str]:
        """Field names the shadow checker should read back (all readable)."""
        return [f.name for f in self.fields]
