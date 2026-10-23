# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register map, field masks, scrambler data model and seed plan of ``sep_km_kpv_rand_test``.

No cocotb import, so the model loads without a simulator.

Register map. Every KM port address and field mask comes from the generated
register header of the Key Manager RDL
(``hw/ip/key_manager/regs/gen/py/key_manager_reg.py``). At import the module
checks the KPV addresses against the formula of ``km_kpv.adoc``
("KEY_ENTRY[64].WORD[16]", "CTRL[64]"): key word w of slot s at
0x12000 + s x 0x40 + w x 4, and CTRL[s] at 0x13000 + 4 s.

Scrambler data model. The S-box and the bit permutation are the tables of
``hw/ip/scrambler/doc/architecture.adoc``, section "Data Scrambling
Algorithm". A stored word is ``player(sbox(data ^ rkey))``. For two writes of
d1 and d2 to the same cell, ``rkey`` and the physical index are the same, so
``ibox(iplayer(S1)) ^ ibox(iplayer(S2)) == d1 ^ d2`` for every key and every
address tweak. The model needs no address permutation and no key.

Seed plan. ``draw_plan`` turns one ``SepSeededRng`` into every value the leaf
uses and returns the ``DRAW`` lines the leaf logs.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

WORD = 0xFFFF_FFFF

_KM_REG_PY = (
    Path(__file__).resolve().parents[6]
    / "ip"
    / "key_manager"
    / "regs"
    / "gen"
    / "py"
    / "key_manager_reg.py"
)


def _load_km_reg():
    spec = importlib.util.spec_from_file_location("key_manager_reg", _KM_REG_PY)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(_KM_REG_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KM = _load_km_reg()

# km_kpv.adoc, "Key and Policy Vault (KM Port)": KEY_ENTRY[64].WORD[16].
N_SLOTS = 64
N_WORDS = 16
N_KPV_WORDS = N_SLOTS * N_WORDS
KPV_BASE = int(KM.KPV_REG_MAP_BASE_ADDR)
KPV_DATA_END = KPV_BASE + N_KPV_WORDS * 4
SCR_KEY = int(KM.KPV_KPV_SCRAMBLER_KEY_REG_ADDR)
SCR_CTRL = int(KM.KPV_KPV_SCRAMBLER_CTRL_REG_ADDR)
IRQ_STATUS = int(KM.KMCSR_IRQ_STATUS_REG_ADDR)
HMAC_KEY_CTRL = int(KM.HMAC_WRAPPER_KEY_KEY_CTRL_REG_ADDR)
SRAM_BASE = int(KM.SRAM_MEM_BASE_ADDR)
SRAM_SIZE = int(KM.SRAM_MEM_SIZE)
# SRAM region 0 (0x8000-0x83FF) holds the POKE op buffer and result words; a
# test SRAM word is drawn from region 1 up.
SRAM_TEST_BASE = SRAM_BASE + 0x400

_WORD_ADDR = tuple(
    tuple(int(getattr(KM, f"KPV_KEY_ENTRY_{s}__WORD_{w}__REG_ADDR")) for w in range(N_WORDS))
    for s in range(N_SLOTS)
)
_CTRL_ADDR = tuple(int(getattr(KM, f"KPV_CTRL_{s}__REG_ADDR")) for s in range(N_SLOTS))


def word_addr(slot: int, word: int) -> int:
    """KM port address of key word ``word`` of slot ``slot``."""
    return _WORD_ADDR[slot][word]


def ctrl_addr(slot: int) -> int:
    """KM port address of CTRL[slot]."""
    return _CTRL_ADDR[slot]


for _s in range(N_SLOTS):
    if _CTRL_ADDR[_s] != 0x13000 + 4 * _s:
        raise RuntimeError(f"generated CTRL[{_s}] address 0x{_CTRL_ADDR[_s]:x} != km_kpv.adoc")
    for _w in range(N_WORDS):
        if _WORD_ADDR[_s][_w] != 0x12000 + _s * 0x40 + _w * 4:
            raise RuntimeError(f"generated KEY_ENTRY[{_s}].WORD[{_w}] address != km_kpv.adoc")


def _bitfields(struct_cls) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    lsb = 0
    for name, _ctype, width in struct_cls._fields_:
        out[name] = (lsb, width)
        lsb += width
    return out


def _mask(fields: dict[str, tuple[int, int]], *names: str) -> int:
    m = 0
    for n in names:
        lsb, width = fields[n]
        m |= ((1 << width) - 1) << lsb
    return m


def _defined(fields: dict[str, tuple[int, int]]) -> int:
    return _mask(fields, *(n for n in fields if not n.startswith("rsvd")))


_CTRL_F = _bitfields(KM.KM_KPV_CTRL_REG_reg_t)
LOCK_WRITE = _mask(_CTRL_F, "lock_write")
LOCK_USE = _mask(_CTRL_F, "lock_use")
ERASE = _mask(_CTRL_F, "erase")
SEAL = _mask(_CTRL_F, "seal")
CTRL_FIELDS = _defined(_CTRL_F)
RETIRED = SEAL | LOCK_USE | LOCK_WRITE
SEALED = SEAL | LOCK_WRITE

_SCR_F = _bitfields(KM.KM_KPV_KPV_SCRAMBLER_CTRL_REG_reg_t)
SCR_ENABLE = _mask(_SCR_F, "enable")
SCR_LOCK = _mask(_SCR_F, "lock")
SCR_FIELDS = _defined(_SCR_F)

_IRQ_F = _bitfields(KM.KM_CSR_IRQ_STATUS_REG_reg_t)
IRQ_WIPE = _mask(_IRQ_F, "wipe_state")
IRQ_FIELDS = _defined(_IRQ_F)

_HKC_F = _bitfields(KM.HMAC_WRAPPER_KEY_KEY_CTRL_REG_reg_t)
HMAC_KEY_VALID = _mask(_HKC_F, "key_valid")
HMAC_KEY_CTRL_FIELDS = _defined(_HKC_F)


@dataclass(frozen=True)
class KeyBank:
    """KEY_CTRL of one accelerator sideload register block."""

    name: str
    ctrl: int
    valid: int
    fields: int


def _key_bank(name: str, prefix: str) -> KeyBank:
    rtype = getattr(KM, f"{prefix}_KEY_CTRL_REG_TYPE")
    f = _bitfields(getattr(KM, f"{rtype}_reg_t"))
    return KeyBank(
        name, int(getattr(KM, f"{prefix}_KEY_CTRL_REG_ADDR")), _mask(f, "key_valid"), _defined(f)
    )


# The eight sideload register blocks, in the bit order of the KM-VALID tap
# km_engine_key_valid_o (docs/SEP_TB_ARCH.adoc, "KM-VALID"): bit i is
# KEY_CTRL.key_valid of KEY_BANKS[i].
KEY_BANKS = (
    _key_bank("hmac", "HMAC_WRAPPER_KEY"),
    _key_bank("kmac", "KMAC_WRAPPER_KEY"),
    _key_bank("aes", "AES_WRAPPER_KEY"),
    _key_bank("otbn", "OTBN_WRAPPER_KEY"),
    _key_bank("mldsa_seed", "ABR_WRAPPER_KEY_MLDSA_SEED"),
    _key_bank("mlkem_seed_d", "ABR_WRAPPER_KEY_MLKEM_SEED_D"),
    _key_bank("mlkem_seed_z", "ABR_WRAPPER_KEY_MLKEM_SEED_Z"),
    _key_bank("mlkem_msg", "ABR_WRAPPER_KEY_MLKEM_MSG"),
)
N_KEY_BANKS = len(KEY_BANKS)
ALL_KEY_BANKS = (1 << N_KEY_BANKS) - 1
if KEY_BANKS[0].ctrl != HMAC_KEY_CTRL or KEY_BANKS[1].name != "kmac":
    raise RuntimeError("KEY_BANKS order does not match the KM-VALID tap")

FIELD_NAME = {LOCK_WRITE: "lock_write", LOCK_USE: "lock_use", ERASE: "erase", SEAL: "seal"}

# --- scrambler data path (scrambler architecture.adoc, "Data Scrambling Algorithm")

SBOX = (0xC, 0x5, 0x6, 0xB, 0x9, 0x0, 0xA, 0xD, 0x3, 0xE, 0xF, 0x8, 0x4, 0x7, 0x1, 0x2)
IBOX = tuple(SBOX.index(x) for x in range(16))
# PERM[i] = output bit position of input bit i.
_PERM_31_16 = (0, 4, 8, 12, 16, 20, 24, 28, 1, 5, 9, 13, 17, 21, 25, 29)
_PERM_15_0 = (2, 6, 10, 14, 18, 22, 26, 30, 3, 7, 11, 15, 19, 23, 27, 31)
_PERM_MAP = {31 - k: p for k, p in enumerate(_PERM_31_16)} | {
    15 - k: p for k, p in enumerate(_PERM_15_0)
}
PERM = tuple(_PERM_MAP[i] for i in range(32))
if sorted(PERM) != list(range(32)):
    raise RuntimeError("scrambler permutation table is not a bijection")


def _nibbles(word: int, box: tuple[int, ...]) -> int:
    return sum(box[(word >> (4 * k)) & 0xF] << (4 * k) for k in range(8))


def sbox_word(word: int) -> int:
    return _nibbles(word, SBOX)


def ibox_word(word: int) -> int:
    return _nibbles(word, IBOX)


def player(word: int) -> int:
    return sum(((word >> i) & 1) << PERM[i] for i in range(32))


def iplayer(word: int) -> int:
    return sum(((word >> PERM[i]) & 1) << i for i in range(32))


def inverse_diff(s1: int, s2: int) -> int:
    """``ibox(iplayer(s1)) ^ ibox(iplayer(s2))``: equals d1 ^ d2 for one cell."""
    return ibox_word(iplayer(s1)) ^ ibox_word(iplayer(s2))


if any(ibox_word(iplayer(player(sbox_word(x)))) != x for x in (0, 1, 0x89ABCDEF, WORD)):
    raise RuntimeError("scrambler model: descramble does not invert scramble")

# --- seed plan ------------------------------------------------------------------

WIPE_HOLD_CHOICES = (2, 3, 8, 40)
N_DRAWN = 12
N_RACE_EXTRA = 5  # 4 repeats and 1 control, outside the drawn set
N_SCR_CELLS = 24
N_SCR_SLOTS = 3
N_SRAM_WORDS = 8
N_CIPHER = 32
N_CIPHER_LANE = 16


def nz_word(rng, avoid=()) -> int:
    """A drawn non-zero 32-bit word that is not in ``avoid``."""
    bad = set(avoid)
    while True:
        v = rng.getrandbits(32)
        if v and v not in bad:
            return v


def distinct_words(rng, n: int, avoid=()) -> list[int]:
    out: list[int] = []
    bad = set(avoid)
    for _ in range(n):
        v = nz_word(rng, bad)
        bad.add(v)
        out.append(v)
    return out


@dataclass
class KpvPlan:
    """Every drawn value of one leaf."""

    drawn: list[int]
    walk_slots: list[int]
    ctrlw_slots: dict[int, int]
    ctrlw_g: dict[int, int]
    race_slot: int
    trail_slot: int
    spare_slots: list[int]
    race_extra: list[int]
    addr_words: dict[int, list[int]]
    cells: dict[tuple[int, int], int]
    sweep_order: list[int]
    sweep_values: dict[int, int]
    walk_word: dict[int, int]
    walk_order: dict[int, list[str]]
    trail_k: int
    scr_slots: list[int]
    scr_cells: list[tuple[int, int]]
    scr_values: list[int]
    kk: int
    lock_before: bool
    wipe_hold: int
    kk2: int
    wipe_slots: tuple[int, int, int]
    sram_addrs: list[int]
    sram_values: list[int]
    cipher_key: int
    cipher_key2: int
    cipher: list[tuple[tuple[int, int], int, int]]
    draws: list[tuple[str, str]] = field(default_factory=list)


def neighbours(slot: int) -> list[int]:
    return [n for n in (slot - 1, slot + 1) if 0 <= n < N_SLOTS]


def draw_plan(rng) -> KpvPlan:
    """Draw the plan of step 1 from ``rng`` (a ``SepSeededRng``)."""
    draws: list[tuple[str, str]] = []

    def log(name: str, value) -> None:
        draws.append((name, value if isinstance(value, str) else repr(value).replace(" ", "")))

    inner = rng.sample(range(1, N_SLOTS - 1), N_DRAWN - 2)
    drawn = [0, N_SLOTS - 1, *inner]
    rng.shuffle(drawn)
    log("drawn_slots", drawn)
    rest = [s for s in drawn if s not in (0, N_SLOTS - 1)]
    fields = [LOCK_WRITE, LOCK_USE, ERASE, SEAL]
    ctrlw_slots = dict(zip(fields, rest[0:4], strict=True))
    walk_slots = [0, N_SLOTS - 1, *rest[4:6]]
    rng.shuffle(walk_slots)
    race_slot, trail_slot = rest[6], rest[7]
    spare = rest[8:10]
    log("ctrlw_slots", {FIELD_NAME[f]: s for f, s in ctrlw_slots.items()})
    log("walk_slots", walk_slots)
    log("race_slot", race_slot)
    log("trail_slot", trail_slot)
    log("spare_slots", spare)
    ctrlw_g = {}
    for f in fields:
        ctrlw_g[f] = rng.choice([g for g in (LOCK_WRITE, LOCK_USE, SEAL) if g != f])
    log("ctrlw_g", {FIELD_NAME[f]: FIELD_NAME[g] for f, g in ctrlw_g.items()})

    outside = [s for s in range(N_SLOTS) if s not in drawn]
    race_extra = rng.sample(outside, N_RACE_EXTRA)
    log("race_extra_slots", race_extra)

    addr_words = {}
    for s in drawn:
        addr_words[s] = sorted({0, N_WORDS - 1, rng.randrange(1, N_WORDS - 1)})
    log("addr_words", addr_words)
    cell_keys: list[tuple[int, int]] = []
    for s in drawn:
        cell_keys += [(s, w) for w in addr_words[s]]
        if s + 1 < N_SLOTS and (s + 1, 0) not in cell_keys:
            cell_keys.append((s + 1, 0))
    cell_keys = list(dict.fromkeys(cell_keys))
    cells = dict(zip(cell_keys, distinct_words(rng, len(cell_keys)), strict=True))
    log("addr_cells", len(cells))

    sweep_order = list(range(N_SLOTS))
    rng.shuffle(sweep_order)
    log("sweep_order", sweep_order)
    sweep_values = dict(zip(sweep_order, distinct_words(rng, N_SLOTS), strict=True))

    walk_word = {s: rng.randrange(0, N_WORDS) for s in walk_slots}
    walk_order = {}
    for s in walk_slots:
        order = ["W", "R", "WR"]
        rng.shuffle(order)
        walk_order[s] = order
    log("walk_word", walk_word)
    log("walk_order", walk_order)
    trail_k = rng.randrange(1, N_WORDS)
    log("trail_k", trail_k)

    pool = [s for s in outside if s not in race_extra]
    scr_slots = rng.sample(pool, N_SCR_SLOTS)
    scr_cells = rng.sample([(s, w) for s in scr_slots for w in range(N_WORDS)], N_SCR_CELLS)
    scr_values = distinct_words(rng, N_SCR_CELLS)
    kk = nz_word(rng)
    lock_before = bool(rng.getrandbits(1))
    wipe_hold = rng.choice(WIPE_HOLD_CHOICES)
    log("scr_slots", scr_slots)
    log("scr_cells", scr_cells)
    log("kk", f"0x{kk:08x}")
    log("lock_timing", "before" if lock_before else "after")
    log("wipe_hold_W", wipe_hold)

    kk2 = nz_word(rng)
    wipe_slots = tuple(rng.sample(range(N_SLOTS), 3))
    sram_words = rng.sample(range((SRAM_TEST_BASE - SRAM_BASE) // 4, SRAM_SIZE // 4), N_SRAM_WORDS)
    sram_addrs = [SRAM_BASE + 4 * w for w in sram_words]
    sram_values = distinct_words(rng, N_SRAM_WORDS)
    log("kk2", f"0x{kk2:08x}")
    log("wipe_slots_free_sealed_retired", list(wipe_slots))
    log("sram_addrs", [f"0x{a:05x}" for a in sram_addrs])

    cipher_key = nz_word(rng)
    cipher_key2 = nz_word(rng, (cipher_key,))
    cipher = []
    for i in range(N_CIPHER):
        cell = (rng.randrange(0, N_SLOTS), rng.randrange(0, N_WORDS))
        if i < N_CIPHER_LANE:
            d1 = i * 0x1111_1111
            d2 = ((i + 8) % 16) * 0x1111_1111
        else:
            d1 = nz_word(rng)
            d2 = nz_word(rng, (d1,))
        cipher.append((cell, d1, d2))
    log("cipher_key", f"0x{cipher_key:08x}")
    log("cipher_key2", f"0x{cipher_key2:08x}")
    log("cipher_cells", [c for c, _, _ in cipher])

    return KpvPlan(
        drawn=drawn,
        walk_slots=walk_slots,
        ctrlw_slots=ctrlw_slots,
        ctrlw_g=ctrlw_g,
        race_slot=race_slot,
        trail_slot=trail_slot,
        spare_slots=spare,
        race_extra=race_extra,
        addr_words=addr_words,
        cells=cells,
        sweep_order=sweep_order,
        sweep_values=sweep_values,
        walk_word=walk_word,
        walk_order=walk_order,
        trail_k=trail_k,
        scr_slots=scr_slots,
        scr_cells=scr_cells,
        scr_values=scr_values,
        kk=kk,
        lock_before=lock_before,
        wipe_hold=wipe_hold,
        kk2=kk2,
        wipe_slots=wipe_slots,
        sram_addrs=sram_addrs,
        sram_values=sram_values,
        cipher_key=cipher_key,
        cipher_key2=cipher_key2,
        cipher=cipher,
        draws=draws,
    )
