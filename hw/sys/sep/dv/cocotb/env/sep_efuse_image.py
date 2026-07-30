# SPDX-License-Identifier: Apache-2.0
"""SEP eFuse/OTP image builder for the OSS cocotb flow.

Builds the 256-word (8192-bit) SEP fuse array as a ``$readmemh`` image the
generic efuse bank model (``hw/.bos/models/efuse/efuse_bank_model.sv``)
loads at t=0 via ``+sep_efuse_hex`` (staged pre-sim by dv_sim_prestage.py). The
field schema, offsets and widths mirror ``sep_efuse_pkg::EfuseFieldMap``
(``meta/registers/svh/sep_efuse_map_reg.svh``); the constraints mirror the
OCAH UVM ``sep_efuse_item`` golden model.

The same object is the golden reference for the shadow-readout checker:
``expected_shadow(field)`` returns the value software should read back from the
shadow-register block after fuse-sense, applying the hardware transforms (only
LC_STATE is transformed — differential-encoded ``{~raw, raw}`` — every other
readable field reads back verbatim).
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Array geometry (sep_efuse_pkg: NumEfuseBits=8192, NumFuseWordWidth=32).
NUM_FUSE_WORDS = 256
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1

# Software-visible shadow-register block base (LC_STATE reads at base+0x08).
SHADOW_BASE = 0x1093_0000
# SEP CPU-ctrl fuse-sense-done status (separate block).
SEP_CPU_CTRL_BASE = 0x10A3_0000
SEP_FUSE_SENSE_STATUS = SEP_CPU_CTRL_BASE + 0x150

# LC_STATE lives in shadow word 2 (efuse_pkg::SHADOW_IDX_LC_STATE); the OTP word
# carries the 4-bit raw code in [3:0] and the FSM differential-encodes it.
LC_WORD_IDX = 2
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
#   "reserved" — reserved tail: must stay 0.
#   "data"     — freely randomizable keys/digests/UIDs/ctrl fields.
_FIELDS: Tuple[Tuple[str, int, int, str], ...] = (
    ("LOCKS",                     0x000,  2, "locks"),
    ("LC_STATE",                  0x008,  1, "lc"),
    ("SBOOT_DIS",                 0x00C,  1, "data"),
    ("TRANSIENT_RMA_EN",          0x010,  1, "data"),
    ("SIP_DIS",                   0x014,  2, "data"),
    ("SYS_DIS",                   0x01C,  2, "data"),
    ("RMA_SIP_TOKEN_DIGEST",      0x024,  8, "data"),
    ("RMA_CHIPLET_TOKEN_DIGEST",  0x044,  8, "data"),
    ("CLASS_KEY",                 0x064,  8, "data"),
    ("CHIPLET_PUBK_REVOKE",       0x084,  1, "data"),
    ("BL1_VERSION",               0x088,  8, "data"),
    ("BL2_VERSION",               0x0A8,  8, "data"),
    ("CHIPLET_UID",               0x0C8,  8, "data"),
    ("SIP_PUBK_DIGEST",           0x0E8,  8, "data"),
    ("SIP_UID",                   0x108,  8, "data"),
    ("SYS_PUBK_DIGEST",           0x128,  8, "data"),
    ("SYS_UID",                   0x148,  8, "data"),
    ("STATUS_RPT",                0x168,  1, "data"),
    ("SEP_ROM_CTRL",              0x16C,  1, "data"),
    ("SEP_SPI_CTRL_FIELD_EN",     0x170,  1, "data"),
    ("SPI_DISCOVERY_CTRL",        0x174,  1, "data"),
    ("SPI_PHY_DQ_TIMING",         0x178,  1, "data"),
    ("SPI_PHY_DQS_TIMING",        0x17C,  1, "data"),
    ("SPI_PHY_GATE_LPBK",         0x180,  1, "data"),
    ("SPI_PHY_DLL_SLAVE",         0x184,  1, "data"),
    ("SPI_PHY_DLL_MASTER",        0x188,  1, "data"),
    ("SPI_PHY_MISC",              0x18C,  1, "data"),
    ("SPI_RB_VALID_TIME",         0x190,  1, "data"),
    ("PUBLIC_KEY_0",              0x194,  8, "data"),
    ("PUBLIC_KEY_1",              0x1B4,  8, "data"),
    ("RESERVED_0",                0x1D4, 16, "reserved"),
    ("RESERVED_1",                0x214, 16, "reserved"),
    ("RESERVED_2",                0x254, 16, "reserved"),
    ("RESERVED_3",                0x294, 16, "reserved"),
    ("RESERVED_4",                0x2D4, 16, "reserved"),
    ("RESERVED_5",                0x314, 16, "reserved"),
    ("RESERVED_6",                0x354, 16, "reserved"),
    ("RESERVED_7",                0x394, 16, "reserved"),
    ("RESERVED_LAST_256",         0x3D4,  8, "reserved"),
    ("RESERVED_LAST_64",          0x3F4,  2, "reserved"),
    ("RESERVED_LAST_32",          0x3FC,  1, "reserved"),
)


def lc_encode(raw: int) -> int:
    """Differential LC encoding stored in shadow word 2: {~raw[3:0], raw[3:0]}."""
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
        """Load a preload file, auto-detecting the format: a per-bit OCAH
        ``*.preload`` (one 0/1 per line) vs a 256-word hex image."""
        toks = Path(path).read_text().split()
        if toks and all(t in ("0", "1") for t in toks) and len(toks) > NUM_FUSE_WORDS:
            return self.load_preload_bits(path)
        return self.load_hex(path)

    def load_hex(self, path: str | Path) -> "SepEfuseImage":
        """Load a 256-word ``$readmemh`` image (our format, or an OCAH
        ``*_shadow_reg.preload`` -- same LSB-first word layout) as the golden.

        LC_STATE may be stored raw or differential-encoded in the file; either
        works because only word[2][3:0] (== the raw nibble) is significant.
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
        """Load an OCAH OTP ``*.preload`` (one bit per line, LSB-first) as the
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

        Stores the full differential encoding ``{~raw, raw}`` in word[2][7:0] --
        a valid differential value, matching the real OTP and the OCAH preload.
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

        Constraints (mirrors OCAH sep_efuse_item):
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

        Only LC_STATE (word 2) is transformed by the sense FSM; all other
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
