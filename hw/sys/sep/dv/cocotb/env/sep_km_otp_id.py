# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Public-ID OTP config and KM readout layout for sep_efuse_km_public_id_test.

Importable from the pre-sim staging hook: no cocotb. ``SepKmOtpIdCfg(seed)`` is
the seed-to-image map for the test and for ``dv_sim_prestage.py``.

Each seed stages three public IDs and sets the eFuse read lock of exactly one of
them, so every run grades one read-locked field and two unlocked ones. The four
secret fields carry their fixed named vectors (``FIELD_VECTORS`` of
``sep_efuse_plan``), each of eight distinct words that are non-zero and not all
ones.

The KM SRAM layout below is the one ``tests/km_fw/km_rom_otp_id.S`` writes, and
it fits the 98 words of ``km_sram_probe_o``. The KMCSR word order comes from the
generated Key Manager map, the eFuse lock bits from the generated SEP map.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from sep_efuse_plan import DEFAULT_VECTOR, FIELD_VECTORS, SECRET_FIELDS, words_token
from sep_reg_meta import RegBlock
from sep_seeded_rng import SepSeededRng

ID_FIELDS = ("SEP_CHIPLET_ID", "SEP_SIP_ID", "SEP_SYS_ID")
ID_WORDS = 8
WORD_BITS = 32
WORD_MASK = (1 << WORD_BITS) - 1
RAILS = ("VAL", "CPL")

# KMCSR secret fields, in address order, and the eFuse field that feeds each.
KM_SECRET_FIELDS = ("CHIPLET_UID", "SIP_UID", "SYS_UID", "CLASS_KEY")
SECRET_WORDS = len(KM_SECRET_FIELDS) * ID_WORDS

# KM SRAM word indices, from the KM SRAM base.
DONE_WORD = 0
DONE_MARKER = 0x1D1D_1D1D
DUMP_WORDS = len(ID_FIELDS) * len(RAILS) * ID_WORDS
OPEN_DUMP_WORD = 1
LOCKED_OR_WORD = OPEN_DUMP_WORD + DUMP_WORDS  # OR of the 48 words after OTP_READ_LOCK
LOCK_READBACK_WORD = LOCKED_OR_WORD + 1
SECRET_VAL_WORD = LOCK_READBACK_WORD + 1  # the VAL words of the four secret fields
SECRET_RAIL_WORD = SECRET_VAL_WORD + SECRET_WORDS  # per field: AND over k of VAL_k ^ CPL_k
LIFE_CYCLE_WORD = SECRET_RAIL_WORD + len(KM_SECRET_FIELDS)
DEMOTION_WORD = LIFE_CYCLE_WORD + 1
LAST_WORD = DEMOTION_WORD
PROBE_WORDS = 98  # km_sram_probe_o width in words (tb/sep_tb_signal_list.svh)
if LAST_WORD >= PROBE_WORDS:
    raise RuntimeError(
        f"KM readout layout ends at word {LAST_WORD}, past the {PROBE_WORDS}-word probe"
    )
if (LOCKED_OR_WORD, SECRET_VAL_WORD, SECRET_RAIL_WORD, LIFE_CYCLE_WORD) != (49, 51, 83, 87):
    raise RuntimeError("KM readout layout differs from tests/km_fw/km_rom_otp_id.S")
# Valid zero of a dual-rail word (key_manager architecture.adoc, OTP Data Encoding).
RAIL_ALL_ONES = 0xFFFF_FFFF

# A draw that cannot find a fresh word in this many tries is a generator bug,
# not bad luck: each try fails with probability below 2^-29.
_DRAW_TRIES = 16

_EFUSE_MAP = RegBlock("SEP_EFUSE_MAP")


def _load_km_csr_reg() -> ModuleType:
    reg_py = Path(__file__).resolve().parents[5] / "ip/key_manager/regs/gen/py/km_csr_reg.py"
    spec = importlib.util.spec_from_file_location("km_csr_reg", reg_py)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {reg_py}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_KM_CSR = _load_km_csr_reg()
_WINDOW_BASE = int(_KM_CSR.OTP_SEP_CHIPLET_ID_VAL_0_REG_OFFSET)


def kmcsr_slot(field: str, rail: str, word: int) -> int:
    """Index of ``OTP_<field>_<rail>_<word>`` within the copied KMCSR window."""
    offset = int(getattr(_KM_CSR, f"OTP_{field}_{rail}_{word}_REG_OFFSET"))
    return (offset - _WINDOW_BASE) // 4


def _check_window() -> None:
    """The copied window must hold exactly the 48 public-ID words, once each.

    The image copies DUMP_WORDS words from the first one in address order, so a
    public-ID register outside that range, or a gap inside it, would leave the
    host comparing a word the image never copied.
    """
    slots = sorted(kmcsr_slot(f, r, k) for f in ID_FIELDS for r in RAILS for k in range(ID_WORDS))
    if slots != list(range(DUMP_WORDS)):
        raise RuntimeError(
            f"KMCSR public-ID registers do not tile {DUMP_WORDS} consecutive words "
            f"from OTP_SEP_CHIPLET_ID_VAL_0: slots {slots}"
        )


_check_window()


def _check_secret_window() -> None:
    """Each secret field is VAL_0..7 then CPL_0..7, the four fields back to back."""
    base = int(_KM_CSR.OTP_CHIPLET_UID_VAL_0_REG_OFFSET)
    for i, f in enumerate(KM_SECRET_FIELDS):
        for r, rail in enumerate(RAILS):
            for k in range(ID_WORDS):
                off = int(getattr(_KM_CSR, f"OTP_{f}_{rail}_{k}_REG_OFFSET"))
                want = base + 4 * (i * 2 * ID_WORDS + r * ID_WORDS + k)
                if off != want:
                    raise RuntimeError(f"OTP_{f}_{rail}_{k} at 0x{off:x}, image reads 0x{want:x}")
    if set(KM_SECRET_FIELDS) != set(SECRET_FIELDS):
        raise RuntimeError(f"KM secret fields {KM_SECRET_FIELDS} differ from {SECRET_FIELDS}")


_check_secret_window()

# Fixed named vectors of the secret fields.
SECRETS = {f: words_token(FIELD_VECTORS[DEFAULT_VECTOR[f]]) for f in KM_SECRET_FIELDS}


def secret_val_words(secrets: dict[str, int]) -> list[int]:
    """The 32 VAL words of the secret readout, field by field, word 0 first."""
    return [id_word(secrets[f], k) for f in KM_SECRET_FIELDS for k in range(ID_WORDS)]


def secret_label(slot: int) -> str:
    return f"OTP_{KM_SECRET_FIELDS[slot // ID_WORDS]}_VAL_{slot % ID_WORDS}"


def km_id_lock_mask() -> int:
    """OTP_READ_LOCK with the three public-ID bits set."""
    view = _KM_CSR.KM_CSR_OTP_READ_LOCK_REG_reg_u()
    view.val = 0
    for field in ID_FIELDS:
        setattr(view.f, field.lower(), 1)
    return int(view.val)


def efuse_read_lock_bit(field: str) -> int:
    """LOCKS bit that read-locks ``field`` (otp_fuse_controller.adoc LOCK field)."""
    return _EFUSE_MAP.field_lsb("LOCKS", f"{field.lower()}_read_lock")


def id_word(value: int, word: int) -> int:
    return (value >> (WORD_BITS * word)) & WORD_MASK


def dual_rail(value: int) -> int:
    """The 512-bit KM OTP encoding of a 256-bit field: {~value, value}."""
    width = ID_WORDS * WORD_BITS
    return (((~value) & ((1 << width) - 1)) << width) | value


def expected_window(ids: dict[str, int]) -> list[int]:
    """The 48 KMCSR words for ``ids``: VAL_k is word k, CPL_k its complement."""
    words = [0] * DUMP_WORDS
    for field in ID_FIELDS:
        for k in range(ID_WORDS):
            word = id_word(ids[field], k)
            words[kmcsr_slot(field, "VAL", k)] = word
            words[kmcsr_slot(field, "CPL", k)] = (~word) & WORD_MASK
    return words


def window_label(slot: int) -> str:
    """Register name of KMCSR window slot ``slot``."""
    for field in ID_FIELDS:
        for rail in RAILS:
            for k in range(ID_WORDS):
                if kmcsr_slot(field, rail, k) == slot:
                    return f"OTP_{field}_{rail}_{k}"
    raise ValueError(f"slot {slot} is outside the public-ID window")


def _draw_id(rng: SepSeededRng, taken: list[set[int]]) -> int:
    """A 256-bit ID with no word 0 or all-ones, and no word shared with an
    earlier ID at the same position.

    With no zero or all-ones word, every VAL and CPL word is non-zero, so a
    readout forced to zero differs from the value in every word. With no shared
    word, two fields crossed anywhere on the path differ in every word.
    """
    value = 0
    for k in range(ID_WORDS):
        for _ in range(_DRAW_TRIES):
            word = rng.getrandbits(WORD_BITS)
            if word not in (0, WORD_MASK) and word not in taken[k]:
                break
        else:
            raise RuntimeError(f"no fresh ID word {k} in {_DRAW_TRIES} draws")
        taken[k].add(word)
        value |= word << (WORD_BITS * k)
    return value


class SepKmOtpIdCfg:
    """Seed-selected public IDs and the one eFuse read lock among them."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.locked_field = rng.choice(ID_FIELDS)
        self.unlocked_fields = tuple(f for f in ID_FIELDS if f != self.locked_field)
        taken: list[set[int]] = [set() for _ in range(ID_WORDS)]
        self.ids = {field: _draw_id(rng, taken) for field in ID_FIELDS}
        self.locks = 1 << efuse_read_lock_bit(self.locked_field)

    def image_fixed(self) -> dict[str, int]:
        return {**self.ids, **SECRETS, "LOCKS": self.locks}

    def summary(self) -> str:
        ids = " ".join(f"{f}={self.ids[f]:#066x}" for f in ID_FIELDS)
        return (
            f"seed={self.seed} eFuse read-locked={self.locked_field} LOCKS={self.locks:#018x} {ids}"
        )
