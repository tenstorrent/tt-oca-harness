# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
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

from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Stimulus randomness is deliberately the seeded, NON-cryptographic SepSeededRng, and
# must stay that way. This generator is run TWICE per simulation from two different
# processes -- once by dv_sim_prestage.py to stage the t=0 OTP image the RTL $readmemh
# reads, and once inside the cocotb test to build the golden that the post-sense
# backdoor compare checks that image against. The two runs agree only because
# SepSeededRng is a pure function of RANDOM_SEED. A cryptographically secure source
# (``secrets``, ``random.SystemRandom``, ``os.urandom``) cannot be seeded, so adopting
# one here would make every real-fuse-sense test fail its own shadow compare.
#
# Nothing this module produces is a secret, a token, or an access-control decision: the
# values are fuse-array contents for a simulated DUT, written to a plaintext hex file in
# the run directory and printed to the log.
#
# Bare sibling import: cocotb/env is on sys.path both in the sim (sep_sim_cfg.toml
# ``python_paths``) and in the prestage hook, which inserts it explicitly.
from sep_seeded_rng import SepSeededRng  # noqa: E402

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
# Derived, never written down. Read the index out of the generated map so a
# hardcoded word offset cannot silently point at a neighbour field (a wrong but
# self-consistent differential pair still looks healthy to a shadow checker).
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

# Class-1a device secrets. sep_efuse_pkg.sv:563 SecretShadowRanges disconnects these
# from the shadow-register hardware output while secure_tm is asserted, so no real
# secret reaches a scannable consumer. Named, not derived: which fields are secret is
# a security decision in the package, not a property of the map's shape, so a new
# field must be classified deliberately rather than inherited by position.
_SECRET_REGS = ("CHIPLET_UID", "SIP_UID", "SYS_UID", "CLASS_KEY")

# Lock-field geometry, from sep_efuse_pkg. LOCKS (64-bit, OTP words 0-1) plus
# LOCKS_SPARE (32-bit, word 2) form one 96-bit field holding two bits per protected
# field -- a write lock and a read lock -- across 40 slots (idx 0-39). locks[79:0] are
# the meaningful pair bits; [95:80] are unassigned slots 40-47. Index 6'h3F is the
# no-lock sentinel.
LOCK_FIELD_BITS = 96
LOCK_SLOTS = 40
LOCK_BITS_PER_SLOT = 2
LOCK_SENTINEL_IDX = 0x3F

# Resolution of the per-slot lock probability draw in randomize(). 32 bits puts the
# quantisation error at 2^-32, far below any probability a test would ask for.
_PROB_BITS = 32

# Spec-stated anchors, asserted against the generated map below.
#
# Deriving the field table from the map is what stopped a hand-written copy going stale,
# but it introduced a subtler failure: DV takes each field's length from the gap to the
# next base, and efuse_guard derives its end address the same way, both reading the same
# generated map. A wrong RDL therefore moves the expectation and the DUT together and
# nothing disagrees. Pinning the handful of offsets and widths the specification states
# outright gives the derivation an independent anchor -- the same reason
# sep_reg_meta._selftest() exists in this environment.
_SPEC_ANCHORS = {
    # name:          (byte offset, width in bits)
    "LOCKS":         (0x000, 64),
    "LOCKS_SPARE":   (0x008, 32),
    "LC_STATE":      (0x00C, 32),
    "SIP_DIS":       (0x018, 64),
    "SYS_DIS":       (0x020, 64),
}
_SPEC_TOTAL_BITS = 8192


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
    first = out[0]
    if first[1] != 0:
        raise RuntimeError(f"eFuse map does not start at 0: {first[0]} @ {first[1]:#x}")
    covered = sum(f[2] for f in out)
    if covered != NUM_FUSE_WORDS:
        raise RuntimeError(
            f"derived eFuse map covers {covered} words, expected {NUM_FUSE_WORDS}"
        )
    if covered * WORD_BITS != _SPEC_TOTAL_BITS:
        raise RuntimeError(
            f"derived eFuse array is {covered * WORD_BITS} bits, but the specification "
            f"states {_SPEC_TOTAL_BITS}"
        )
    # Independent anchor: the offsets and widths the specification states outright must
    # match what the generator produced. Without this the derivation and the DUT read the
    # same map, so a wrong RDL would move both and nothing would disagree.
    by_name = {f[0]: f for f in out}
    for name, (want_off, want_bits) in _SPEC_ANCHORS.items():
        if name not in by_name:
            raise RuntimeError(
                f"spec-stated field {name} is absent from the generated eFuse map"
            )
        _, got_off, got_words, _ = by_name[name]
        got_bits = got_words * WORD_BITS
        if (got_off, got_bits) != (want_off, want_bits):
            raise RuntimeError(
                f"{name} is at {got_off:#05x}/{got_bits}b in the generated map but the "
                f"specification states {want_off:#05x}/{want_bits}b"
            )
    lock_bits = sum(by_name[n][2] for n in _LOCK_REGS) * WORD_BITS
    if lock_bits != LOCK_FIELD_BITS:
        raise RuntimeError(
            f"LOCKS + LOCKS_SPARE span {lock_bits} bits, but sep_efuse_pkg states "
            f"LockFieldBits = {LOCK_FIELD_BITS}"
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
        toks = Path(path).read_text(encoding="utf-8").split()
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
        words = [int(tok, 16) for tok in path.read_text(encoding="utf-8").split()]
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
        bits = [c for c in path.read_text(encoding="utf-8").split() if c in ("0", "1")]
        self.words = [0] * NUM_FUSE_WORDS
        for bit_idx, c in enumerate(bits):
            if c == "1":
                self.words[bit_idx // WORD_BITS] |= 1 << (bit_idx % WORD_BITS)
        return self

    def set_lc_state(self, raw: int) -> "SepEfuseImage":
        """Set LC_STATE by raw code (must be legal).

        Stores the full differential encoding ``{~raw, raw}`` in LC_STATE[7:0],
        matching the real OTP and the reference-suite preload.

        Storing the encoded form is a convenience, not a requirement: only ``[3:0]``
        is significant. The sense FSM reads the raw nibble out of OTP and regenerates
        ``{~raw, raw}`` into the shadow itself, so a staged image carrying a bare nibble
        still senses as a valid
        pair. That is also why no staged image can present a BROKEN pair to the DUT.
        The stitch test injects that fault at the LCC decoder input (signed-off force).
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
          * The map has no reserved tail: the whole range is real registers
            (PQC hashes, SEP_*_ID, SPARE0-7), and every one is randomized like
            any other data field. Nothing here is pinned to zero.
          * LOCKS stays unlocked unless ``lock_prob`` > 0, so every field reads
            back (read-locks would return 0xbadcab1e instead of data).
          * ``fixed`` pins named fields to explicit values after randomization.
        """
        rng = SepSeededRng(seed)
        # LOCKS and LOCKS_SPARE are one 96-bit vector, not two independent
        # fields. Build it once, then slice each register by its bit offset
        # from the LOCKS base: LOCKS <- [63:0], LOCKS_SPARE <- [95:64]
        # (slots 32-39 in [79:64]; [95:80] are unassigned and stay 0).
        # Drawing per kind=="locks" field would write a fresh 80-bit vector
        # into each, so LOCKS_SPARE received bits [31:0] of a second draw
        # instead of [95:64] of the first.
        #
        # The vector holds TWO bits per protected field -- a write lock and a
        # read lock -- so 40 slots cover 80 bits. Index 6'h3F is the no-lock
        # sentinel. Lock ENFORCEMENT (read-lock -> 0xbadcab1e, write-lock
        # rejecting a program) is still not checked by the shadow checkers, so
        # expected_shadow() assumes fields stay readable. Extend both
        # together, and add a plan row, before relying on this.
        lock_bits = 0
        if lock_prob > 0.0:
            # Bernoulli draw as an integer comparison rather than a float one:
            # exact at the probability boundaries, and reproducible across
            # Python versions without depending on float formatting.
            threshold = int(lock_prob * (1 << _PROB_BITS))

            def _draw() -> bool:
                return rng.getrandbits(_PROB_BITS) < threshold

            for slot in range(LOCK_SLOTS):
                if _draw():
                    lock_bits |= 1 << (slot * LOCK_BITS_PER_SLOT)      # write lock
                if _draw():
                    lock_bits |= 1 << (slot * LOCK_BITS_PER_SLOT + 1)  # read lock
        locks_base_word = self.field("LOCKS").word
        for fld in self.fields:
            if fld.kind == "lc":
                raw = lc_raw if lc_raw is not None else rng.choice(LEGAL_LC_RAW)
                self.set_lc_state(raw)
                continue
            if fld.kind == "locks":
                if lock_prob <= 0.0:
                    continue
                bit_off = (fld.word - locks_base_word) * WORD_BITS
                for i in range(fld.n_words):
                    self.words[fld.word + i] = (
                        (lock_bits >> (bit_off + i * WORD_BITS)) & WORD_MASK)
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

    def secret_words(self) -> frozenset:
        """Word indices the DUT blanks while secure_tm is asserted."""
        idx = set()
        for name in _SECRET_REGS:
            fld = self.field(name)
            idx.update(range(fld.word, fld.word + fld.n_words))
        return frozenset(idx)

    def shadow_word(self, word_idx: int, *, secure_tm: int = 0) -> int:
        """Expected software-readback value for shadow word ``word_idx``.

        LC_STATE is transformed by the sense FSM. With ``secure_tm`` asserted the
        Class-1a secrets read back as zero -- the DUT disconnects them from the shadow
        output (sep_efuse_pkg.sv SecretShadowRanges), so a golden that returned the
        staged value would report 32 mismatches on a TEST_EN run. Everything else
        reads back verbatim (LOCKS unlocked).

        The blanking is conditional ON PURPOSE. Zeroing these words unconditionally
        would stop the compare proving they sensed correctly at all, which is the
        whole point of the post-sense check.
        """
        if secure_tm and word_idx in self.secret_words():
            return 0
        if word_idx == LC_WORD_IDX:
            upper = self.words[LC_WORD_IDX] & 0xFFFF_FF00
            return upper | lc_encode(self.lc_raw())
        return self.words[word_idx] & WORD_MASK

    def expected_field(self, name: str, *, secure_tm: int = 0) -> List[Tuple[int, int]]:
        """(addr, expected) pairs the checker reads for ``name``."""
        fld = self.field(name)
        return [
            (fld.shadow_addr + 4 * i,
             self.shadow_word(fld.word + i, secure_tm=secure_tm))
            for i in range(fld.n_words)
        ]

    def check_fields(self) -> List[str]:
        """Field names the shadow checker should read back (all readable)."""
        return [f.name for f in self.fields]


def _selftest_lock_pack() -> None:
    """LOCKS and LOCKS_SPARE must slice one 96-bit vector, not two draws.

    lock_prob=1.0 forces every assigned slot. 40 slots x 2 bits = 80 ones;
    LOCKS is [63:0], LOCKS_SPARE is [95:64] with [95:80] unassigned and 0.
    A per-field redraw writes [31:0] of a second vector into LOCKS_SPARE
    (0xffffffff) and is the packing bug this pins.
    """
    ones = SepEfuseImage().randomize(7, lock_prob=1.0)
    locks = ones.field_int("LOCKS")
    spare = ones.field_int("LOCKS_SPARE")
    if locks != (1 << 64) - 1:
        raise RuntimeError(
            f"lock_prob=1.0 packed LOCKS {locks:#018x}, expected 0xffffffffffffffff"
        )
    if spare != 0x0000FFFF:
        raise RuntimeError(
            f"lock_prob=1.0 packed LOCKS_SPARE {spare:#010x}, expected 0x0000ffff "
            "(bits [79:64] of the 96-bit lock vector; [95:80] unassigned)"
        )
    zeros = SepEfuseImage().randomize(7, lock_prob=0.0)
    if zeros.field_int("LOCKS") != 0 or zeros.field_int("LOCKS_SPARE") != 0:
        raise RuntimeError("lock_prob=0 must leave LOCKS and LOCKS_SPARE clear")


_selftest_lock_pack()
