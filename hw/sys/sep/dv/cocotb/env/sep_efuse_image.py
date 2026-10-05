# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP eFuse/OTP image builder for the OSS cocotb flow.

Builds the 256-word (8192-bit) SEP fuse array as a ``$readmemh`` image the
generic efuse bank model (``hw/ip/efuse/dv/models/efuse_bank_model.sv``)
loads at t=0 via ``+sep_efuse_hex`` (staged pre-sim by dv_sim_prestage.py).
Write-policy and used-bit membership come from ``env/sep_efuse_field_map``;
offsets and widths come from the generated RDL header.

The same object is the golden reference for the shadow-readout checker:
``shadow_word(i)`` returns the value software should read back from the
shadow-register block after fuse-sense. ``expected_field(name)`` returns the
``(addr, expected)`` pairs for a field. Both apply the hardware transforms (only
LC_STATE is transformed — differential-encoded ``{~raw, raw}`` — every other
readable field reads back verbatim).
"""

from __future__ import annotations

from sep_reg_meta import SEP_CPU_CTRL, RegBlock, sym
import sep_efuse_field_map

# The generated map itself, for enumerating the eFuse register set rather than
# naming each entry. Import order matters: sep_reg_meta puts regs/gen/py on
# sys.path as an import side effect, so it has to come first.
import sep_reg  # noqa: E402

from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Stimulus randomness uses SepSeededRng. This generator is run twice per
# simulation from two different
# processes -- once by dv_sim_prestage.py to stage the t=0 OTP image the RTL $readmemh
# reads, and once inside the cocotb test to build the golden that the post-sense
# backdoor compare checks that image against. The two runs agree only because
# SepSeededRng is a pure function of RANDOM_SEED, so the stream must stay seedable.
#
# Bare sibling import: cocotb/env is on sys.path both in the sim (sep_sim_cfg.toml
# ``python_paths``) and in the prestage hook, which inserts it explicitly.
from sep_seeded_rng import SepSeededRng  # noqa: E402

# Array geometry from otp_fuse_controller.adoc ("exactly 8192 bits" / 256 x 32-bit words).
WORD_BITS = 32
NUM_FUSE_WORDS = sep_efuse_field_map.spec_num_fuse_bits() // WORD_BITS
WORD_MASK = (1 << WORD_BITS) - 1

# Software-visible shadow-register block base.
SHADOW_BASE = sym("SEP_EFUSE_MAP_REG_MAP_BASE_ADDR")
# SEP CPU-ctrl fuse-sense-done status (separate block).
SEP_FUSE_SENSE_STATUS = SEP_CPU_CTRL.addr("SEP_FUSE_SENSE_STATUS")

# LC_STATE's shadow word. The OTP word carries the 4-bit raw code in [3:0]
# and the FSM differential-encodes it.
#
# Derived, never written down. Read the index out of the generated map so a
# hardcoded word offset cannot silently point at a neighbour field (a wrong but
# self-consistent differential pair still looks healthy to a shadow checker).
LC_WORD_IDX = sym("SEP_EFUSE_MAP_LC_STATE_REG_OFFSET") // 4
# Bits of the LC_STATE word that hold the differential code, from the generated
# field metadata; the sense FSM writes the other bits verbatim.
LC_FIELD_MASK = RegBlock("SEP_EFUSE_MAP").field_mask("LC_STATE", "lc_state")
LC_RAW_WIDTH = 4
# Legal raw LC_STATE codes from hw/sys/sep/doc/lifecycle_controller.adoc
# (encoding table and the per-LC-state feature-control profile).
# Only these seven are legal.
LC_TEST_DEV = 0x0
LC_PROD = 0x1
LC_RMA_SIP_0 = 0x2
LC_RMA_SIP_1 = 0x3
LC_RMA_CHIP_0 = 0x6
LC_RMA_CHIP_1 = 0x7
LC_PROD_END = 0x8
LEGAL_LC_RAW: Tuple[int, ...] = (
    LC_TEST_DEV,
    LC_PROD,
    LC_RMA_SIP_0,
    LC_RMA_SIP_1,
    LC_RMA_CHIP_0,
    LC_RMA_CHIP_1,
    LC_PROD_END,
)

# SBOOT_DIS.disable_secure_boot, the chicken bit that turns secure boot off.
SBOOT_DIS_MASK = RegBlock("SEP_EFUSE_MAP").field_mask("SBOOT_DIS", "disable_secure_boot")

# Kinds, keyed by generated register name; offsets and lengths come from the
# generated map (_derive_fields). kind drives randomization and the
# expected-shadow transform:
#   "lc" -- LC_STATE: word holds the raw code, shadow reads {~raw, raw}.
#   "locks" -- LOCKS table: unlocked by default so every field reads back.
# Everything else is "data": freely randomizable.
_LOCK_REGS = ("LOCKS", "LOCKS_SPARE")
_LC_REGS = ("LC_STATE",)

# KM-secret fields named in otp_fuse_controller.adoc (Key Manager subset).
_SECRET_REGS = sep_efuse_field_map.spec_secret_regs()

# Lock-field geometry, from the otp_fuse_controller.adoc LOCK field (96 bits, two bits per
# protected slot). LOCKS (64-bit, OTP words 0-1) plus
# LOCKS_SPARE (32-bit, word 2) form one 96-bit field holding two bits per protected
# field -- a write lock and a read lock -- across 41 slots (idx 0-40). locks[81:0] are
# the meaningful pair bits; [95:82] are unassigned slots 41-47. Index 6'h3F is the
# no-lock sentinel.
LOCK_FIELD_BITS = 96
LOCK_SLOTS = 41
LOCK_BITS_PER_SLOT = 2
LOCK_SENTINEL_IDX = 0x3F

# Resolution of the per-slot lock probability draw in randomize(). 32 bits puts the
# quantisation error at 2^-32, far below any probability a test would ask for.
_PROB_BITS = 32

# Spec-stated anchors, asserted against the generated map below.
#
# The field table is derived from the generated map: DV takes each field's length from
# the gap to the next base, and efuse_guard derives its end address the same way, both
# reading the same map. A wrong RDL therefore moves the expectation and the DUT
# together and nothing disagrees. Pinning the handful of offsets and widths the
# specification states outright gives the derivation an independent anchor -- the
# same reason sep_reg_meta._selftest() exists.
_SPEC_ANCHORS = {
    # name:          (byte offset, width in bits)
    "LOCKS": (0x000, 64),
    "LOCKS_SPARE": (0x008, 32),
    "LC_STATE": (0x00C, 32),
    "SIP_DIS": (0x018, 64),
    "SYS_DIS": (0x020, 64),
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
        (int(getattr(sep_reg, n)), n[len(pfx) : -len(sfx)])
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
        raise RuntimeError(f"derived eFuse map covers {covered} words, expected {NUM_FUSE_WORDS}")
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
            raise RuntimeError(f"spec-stated field {name} is absent from the generated eFuse map")
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
            f"LOCKS + LOCKS_SPARE span {lock_bits} bits, but the specification "
            f"LOCK field is {LOCK_FIELD_BITS} bits"
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
        self.offset = offset  # byte offset within the fuse map
        self.word = offset >> 2  # word index into the 256-word array
        self.n_words = n_words
        self.kind = kind

    @property
    def shadow_addr(self) -> int:
        return SHADOW_BASE + self.offset


class SepEfuseImage:
    """A 256-word SEP fuse image plus the golden expected-shadow model.

    Golden assumptions (must match the tb wiring): the DUT runs with
    ``secure_tm`` tied 0 and LOCKS unlocked, so every field reads back verbatim
    except LC_STATE (differential-encoded). KM-secret disconnect under
    ``secure_tm`` is graded by the stitch leaf against the staged value, not
    by forcing those words to a constant here.
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
            raise ValueError(f"{name} expects {fld.n_words} words, got {len(values)}")
        for i, v in enumerate(values):
            self.words[fld.word + i] = v & WORD_MASK
        return self

    def set_int(self, name: str, value: int) -> "SepEfuseImage":
        """Set a field from a single (possibly wide) integer, little-endian."""
        fld = self.field(name)
        words = [(value >> (WORD_BITS * i)) & WORD_MASK for i in range(fld.n_words)]
        return self.set_words(name, words)

    def load(self, path: str | Path) -> "SepEfuseImage":
        """Load a preload, auto-detecting the format: a declarative ``*.toml``
        fuse configuration, a per-bit ``*.preload`` (one 0/1 per line), or a
        256-word hex image.

        This method is the single entry both execution points use --
        ``dv_sim_prestage.stage()`` to write the array the RTL ``$readmemh`` reads
        at t=0, and ``sep_base_test.select_efuse_image()`` to build the golden the
        post-sense shadow compare checks that array against -- so every format is
        available to both. A format known to only one of them would give the
        golden a zero-filled image and turn every field into a mismatch.
        """
        path = Path(path)
        if path.suffix == ".toml":
            # Lazy so a .hex-only run pays for neither tomllib nor the scan of
            # the generated header's bitfield structs.
            from sep_generate_efuse_preload import apply_toml

            return apply_toml(self, path)
        toks = path.read_text(encoding="utf-8").split()
        if toks and all(t in ("0", "1") for t in toks) and len(toks) > NUM_FUSE_WORDS:
            return self.load_preload_bits(path)
        return self.load_hex(path)

    def load_hex(self, path: str | Path) -> "SepEfuseImage":
        """Load a 256-word ``$readmemh`` image (LSB-first word layout) as the golden.

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
        """Load a per-bit OTP ``*.preload`` (one bit per line, LSB-first) as the
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
        matching the real OTP.

        Storing the encoded form is a convenience, not a requirement: only ``[3:0]``
        is significant. The sense FSM reads the raw nibble out of OTP and regenerates
        ``{~raw, raw}`` into the shadow itself, so a staged image carrying a bare nibble
        still senses as a valid pair. That is also why no staged image can present a
        BROKEN pair to the DUT. The stitch test injects that fault by forcing the LCC decoder input.
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

        Constraints:
          * LC_STATE is restricted to the 7 legal raw codes (never an illegal
            encoding) — pinned via ``lc_raw`` or drawn from the legal set.
          * LOCKS stays unlocked unless ``lock_prob`` > 0, so every field reads
            back (read-locks would return 0xbadcab1e instead of data).
          * ``fixed`` pins named fields to explicit values after randomization.
        """
        rng = SepSeededRng(seed)
        # LOCKS and LOCKS_SPARE are one 96-bit vector, not two independent
        # fields. Build it once, then slice each register by its bit offset
        # from the LOCKS base: LOCKS <- [63:0], LOCKS_SPARE <- [95:64]
        # (slots 32-40 in [81:64]; [95:82] are unassigned and stay 0).
        # Drawing per kind=="locks" field would write a fresh vector into each,
        # so LOCKS_SPARE would receive bits [31:0] of a second draw instead of
        # [95:64] of the first.
        #
        # The vector holds TWO bits per protected field -- a write lock and a
        # read lock -- so 41 slots cover 82 bits. Index 6'h3F is the no-lock
        # sentinel. The shadow checkers do not check lock ENFORCEMENT (read-lock ->
        # 0xbadcab1e, write-lock rejecting a program); shadow_word() assumes
        # fields stay readable.
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
                    lock_bits |= 1 << (slot * LOCK_BITS_PER_SLOT)  # write lock
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
                    self.words[fld.word + i] = (lock_bits >> (bit_off + i * WORD_BITS)) & WORD_MASK
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
        """Word indices of the four KM-secret fields (otp_fuse_controller.adoc)."""
        idx: set[int] = set()
        for name in _SECRET_REGS:
            fld = self.field(name)
            idx.update(range(fld.word, fld.word + fld.n_words))
        return frozenset(idx)

    def shadow_word(self, word_idx: int, *, secure_tm: int = 0) -> int:
        """Expected software-readback value for shadow word ``word_idx``.

        LC_STATE is transformed by the sense FSM. Everything else reads back
        verbatim (LOCKS unlocked). ``secure_tm`` does not change this golden:
        KM-secret disconnect is a not-equal check against the staged value,
        not an expected constant.
        """
        _ = secure_tm
        if word_idx == LC_WORD_IDX:
            upper = self.words[LC_WORD_IDX] & WORD_MASK & ~LC_FIELD_MASK
            return upper | lc_encode(self.lc_raw())
        return self.words[word_idx] & WORD_MASK

    def expected_field(self, name: str, *, secure_tm: int = 0) -> List[Tuple[int, int]]:
        """(addr, expected) pairs the checker reads for ``name``."""
        fld = self.field(name)
        return [
            (fld.shadow_addr + 4 * i, self.shadow_word(fld.word + i, secure_tm=secure_tm))
            for i in range(fld.n_words)
        ]

    def check_fields(self) -> List[str]:
        """Field names the shadow checker should read back (all readable)."""
        return [f.name for f in self.fields]


def _selftest_lock_pack() -> None:
    """LOCKS and LOCKS_SPARE must slice one 96-bit vector, not two draws.

    lock_prob=1.0 forces every assigned slot. 41 slots x 2 bits = 82 ones;
    LOCKS is [63:0], LOCKS_SPARE is [95:64] with [95:82] unassigned and 0.
    A per-field redraw would write [31:0] of a second vector into LOCKS_SPARE
    (0xffffffff); this pins the single-vector packing.
    """
    ones = SepEfuseImage().randomize(7, lock_prob=1.0)
    locks = ones.field_int("LOCKS")
    spare = ones.field_int("LOCKS_SPARE")
    if locks != (1 << 64) - 1:
        raise RuntimeError(f"lock_prob=1.0 packed LOCKS {locks:#018x}, expected 0xffffffffffffffff")
    if spare != 0x0003FFFF:
        raise RuntimeError(
            f"lock_prob=1.0 packed LOCKS_SPARE {spare:#010x}, expected 0x0003ffff "
            "(bits [81:64] of the 96-bit lock vector; [95:82] unassigned)"
        )
    zeros = SepEfuseImage().randomize(7, lock_prob=0.0)
    if zeros.field_int("LOCKS") != 0 or zeros.field_int("LOCKS_SPARE") != 0:
        raise RuntimeError("lock_prob=0 must leave LOCKS and LOCKS_SPARE clear")


_selftest_lock_pack()
