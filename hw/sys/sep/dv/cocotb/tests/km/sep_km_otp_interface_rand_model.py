# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Field table, readout model, inject masks and seed plan of ``sep_km_otp_interface_rand_test``.

No cocotb import, so the model loads without a simulator.

Fields. The nine KMCSR OTP readout fields in OTP_READ_LOCK bit order
(``km_csr.adoc``, "OTP_READ_LOCK"): 0 life cycle, 1 demotion, 2 CHIPLET_UID,
3 SIP_UID, 4 SYS_UID, 5 CLASS_KEY, 6 SEP_CHIPLET_ID, 7 SEP_SIP_ID,
8 SEP_SYS_ID. Bits 2 to 5 are the four secrets, bits 6 to 8 the three public
identities. Every KMCSR address and field mask comes from the generated
register header of the Key Manager RDL
(``hw/ip/key_manager/regs/gen/py/key_manager_reg.py``).

Readout model. ``expected_readout`` gives the word that each of the 114
readout registers holds under an effective lock and the secure test strap:
a locked field reads 0 in every word; in secure test mode a secret value
word reads 0 and its complement word 0xFFFFFFFF; otherwise a value word is
the staged fuse word and its complement word the bitwise inverse
(``architecture.adoc``, "OTP Inputs and Readout"; ``km_csr.adoc``,
"OTP_READ_LOCK", "OTP_READ_LOCK_COLD"). OTP_LIFE_CYCLE is ``{~lc, lc}`` of the
staged life-cycle state. The demotion groups have no stated polarity, so the
model holds the value read in the first boot (a DUT readback), and the leaf
grades only their complementarity against the spec.

Inject masks. ``HK-OTP`` (``docs/SEP_TB_ARCH.adoc``, inject exceptions) XORs a
mask of the width of ``km_otp_data_t`` into the KM OTP input. The packed
struct puts its first member at the top, so the bit offset of each member is
the sum of the widths below it. Each 256-bit field is ``{complement, value}``;
the life-cycle byte is ``{~lc[3:0], lc[3:0]}``; each demotion group is two
bits. The value rail of a demotion group is its bit 0 and the complement rail
its bit 1 (a naming of the two bits only; the polarity is not graded).

Seed plan. ``draw_rep`` turns one ``SepSeededRng`` into every RAND-REP value of
the integrity and change legs and returns the ``DRAW`` lines the leaf logs.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

WORD = 0xFFFF_FFFF
WORD_BITS = 32

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
    spec = importlib.util.spec_from_file_location("km_otp_iface_key_manager_reg", _KM_REG_PY)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(_KM_REG_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KM = _load_km_reg()


def _bits(struct_cls) -> dict[str, tuple[int, int]]:
    """{field: (lsb, width)} of a generated ctypes register struct (LSB first)."""
    out: dict[str, tuple[int, int]] = {}
    lsb = 0
    for name, _, width in struct_cls._fields_:
        out[name] = (lsb, width)
        lsb += width
    return out


def _mask(struct_cls, name: str) -> int:
    lsb, width = _bits(struct_cls)[name]
    return ((1 << width) - 1) << lsb


def _defined(struct_cls) -> int:
    """Mask of every field of a register except its reserved field."""
    return sum(_mask(struct_cls, n) for n in _bits(struct_cls) if n != "rsvd")


def _addr(name: str) -> int:
    return int(getattr(KM, f"KMCSR_{name}_REG_ADDR"))


# --- KMCSR registers ------------------------------------------------------------

A_IRQ_STATUS = _addr("IRQ_STATUS")
A_IRQ_SET = _addr("IRQ_SET")
A_LIFE_CYCLE = _addr("OTP_LIFE_CYCLE")
A_DEMOTION = _addr("OTP_DEMOTION_STATE")
A_READ_LOCK = _addr("OTP_READ_LOCK")
A_READ_LOCK_COLD = _addr("OTP_READ_LOCK_COLD")
A_CHANGE = _addr("OTP_CHANGE_STATUS")

_IRQ = KM.KM_CSR_IRQ_STATUS_REG_reg_t
IRQ_FIELDS = _defined(_IRQ)
IRQ_OTP_CHANGE = _mask(_IRQ, "otp_change")
IRQ_OTP_SIGINT = _mask(_IRQ, "otp_sigint")
IRQ_OTP = IRQ_OTP_CHANGE | IRQ_OTP_SIGINT
SET_OTP_SIGINT = _mask(KM.KM_CSR_IRQ_SET_REG_reg_t, "otp_sigint_set")
LC_FIELDS = _defined(KM.KM_CSR_OTP_LIFE_CYCLE_REG_reg_t)
_DEM = KM.KM_CSR_OTP_DEMOTION_STATE_REG_reg_t
DEM_FIELDS = _defined(_DEM)
DEM_GROUPS = (_mask(_DEM, "demote_1_value"), _mask(_DEM, "demote_2_value"))
_LOCK = KM.KM_CSR_OTP_READ_LOCK_REG_reg_t
LOCK_FIELDS = _defined(_LOCK)
CHANGE_FIELDS = _defined(KM.KM_CSR_OTP_CHANGE_STATUS_REG_reg_t)

# --- fields ---------------------------------------------------------------------

FIELD_NAMES = tuple(n for n in _bits(_LOCK) if n != "rsvd")
N_FIELDS = len(FIELD_NAMES)
LOCK_ALL = (1 << N_FIELDS) - 1
F_LC = FIELD_NAMES.index("life_cycle")
F_DEM = FIELD_NAMES.index("demotion")
DUAL = tuple(range(2, N_FIELDS))  # the seven 256-bit fields
SECRET = tuple(FIELD_NAMES.index(n) for n in ("chiplet_uid", "sip_uid", "sys_uid", "class_key"))
PUBLIC = tuple(FIELD_NAMES.index(n) for n in ("sep_chiplet_id", "sep_sip_id", "sep_sys_id"))
SECRET_MASK = sum(1 << f for f in SECRET)
N_WORDS = 8  # 256-bit field = 8 words per rail

if FIELD_NAMES[:2] != ("life_cycle", "demotion") or len(DUAL) != 7:
    raise RuntimeError(f"OTP_READ_LOCK field order changed: {FIELD_NAMES}")
for _f in range(N_FIELDS):
    if _mask(_LOCK, FIELD_NAMES[_f]) != 1 << _f:
        raise RuntimeError(f"OTP_READ_LOCK.{FIELD_NAMES[_f]} is not bit {_f}")


def efuse_name(f: int) -> str:
    """eFuse field name of a dual-rail field (``sep_km_fuse_plan.OTP_DUAL_RAIL_FIELDS``)."""
    return FIELD_NAMES[f].upper()


def word_addr(f: int, rail: str, w: int) -> int:
    return _addr(f"OTP_{efuse_name(f)}_{'VAL' if rail == 'val' else 'CPL'}_{w}")


# One readout slot: (field, rail, word); the life-cycle and demotion registers
# use rail "reg" and word 0.
Slot = tuple[int, str, int]


def _block(start: int, slots: list[Slot]) -> tuple[int, list[Slot]]:
    for k, (f, rail, w) in enumerate(slots):
        a = A_LIFE_CYCLE if f == F_LC else A_DEMOTION if f == F_DEM else word_addr(f, rail, w)
        if a != start + 4 * k:
            raise RuntimeError(f"readout block at 0x{start:x} is not contiguous at slot {k}")
    return start, slots


def _dual_slots(fields: tuple[int, ...]) -> list[Slot]:
    return [(f, rail, w) for f in fields for rail in ("val", "cpl") for w in range(N_WORDS)]


# The 114 readout words as three contiguous KMCSR blocks.
READOUT_BLOCKS: tuple[tuple[int, list[Slot]], ...] = (
    _block(A_LIFE_CYCLE, [(F_LC, "reg", 0), (F_DEM, "reg", 0)]),
    _block(word_addr(2, "val", 0), _dual_slots(DUAL[:4])),
    _block(word_addr(6, "val", 0), _dual_slots(DUAL[4:])),
)
READOUT_SLOTS: tuple[Slot, ...] = tuple(s for _, b in READOUT_BLOCKS for s in b)
if len(READOUT_SLOTS) != 114:
    raise RuntimeError(f"readout has {len(READOUT_SLOTS)} words, the contract names 114")


def lc_encode(lc_raw: int) -> int:
    """OTP_LIFE_CYCLE of a staged state: ``{~lc[3:0], lc[3:0]}``."""
    lc = lc_raw & 0xF
    return ((~lc & 0xF) << 4) | lc


def staged_word(otp_fields: dict[str, int], f: int, w: int) -> int:
    return (otp_fields[efuse_name(f)] >> (WORD_BITS * w)) & WORD


def expected_readout(
    otp_fields: dict[str, int],
    lc_raw: int,
    dem_record: int,
    eff_lock: int,
    tm: int,
) -> dict[Slot, int]:
    """The word each readout register holds (see the module text)."""
    out: dict[Slot, int] = {}
    for slot in READOUT_SLOTS:
        f, rail, w = slot
        if (eff_lock >> f) & 1:
            out[slot] = 0
        elif f == F_LC:
            out[slot] = lc_encode(lc_raw)
        elif f == F_DEM:
            out[slot] = dem_record
        elif tm and f in SECRET:
            out[slot] = 0 if rail == "val" else WORD
        else:
            v = staged_word(otp_fields, f, w)
            out[slot] = v if rail == "val" else (~v & WORD)
    return out


def dem_groups_cpl(value: int) -> int:
    """Number of the two demotion groups that hold a complementary pair (01 or 10)."""
    n = 0
    for m in DEM_GROUPS:
        lsb = (m & -m).bit_length() - 1
        g = (value & m) >> lsb
        n += int(g in (1, 2))
    return n


def dem_groups_changed(before: int, after: int) -> list[int]:
    """Indices (0 = DEMOTE_1 group, 1 = DEMOTE_2 group) of the groups that differ."""
    return [i for i, m in enumerate(DEM_GROUPS) if (before ^ after) & m]


# --- HK-OTP mask (km_otp_data_t layout) -------------------------------------------

# km_otp_data_t members, first (top) to last (bit 0), with their widths.
OTP_STRUCT = (
    ("life_cycle", 8),
    ("demotion_state_1", 2),
    ("demotion_state_2", 2),
    ("chiplet_uid", 512),
    ("class_key", 512),
    ("sip_uid", 512),
    ("sys_uid", 512),
    ("sep_chiplet_id", 512),
    ("sep_sip_id", 512),
    ("sep_sys_id", 512),
)
OTP_WIDTH = sum(w for _, w in OTP_STRUCT)
OTP_LSB: dict[str, int] = {}
_pos = OTP_WIDTH
for _name, _w in OTP_STRUCT:
    _pos -= _w
    OTP_LSB[_name] = _pos
if OTP_WIDTH != 3596:
    raise RuntimeError(f"km_otp_data_t width {OTP_WIDTH} is not 3596")

RAILS = ("val", "cpl")


def _rail_bits(f: int, rail: str, word: int, bit: int) -> list[int]:
    """Struct bit positions of ``bit`` of ``word`` on ``rail`` of field ``f``.

    ``word`` is the 32-bit word for a 256-bit field and the group (0 =
    DEMOTE_1, 1 = DEMOTE_2) for the demotion field; ``bit`` is the bit in the
    word, in the life-cycle nibble or unused for the demotion field.
    """
    rails = RAILS if rail == "both" else (rail,)
    out: list[int] = []
    for r in rails:
        if f == F_LC:
            if not 0 <= bit < 4:
                raise ValueError(f"life-cycle nibble bit {bit}")
            out.append(OTP_LSB["life_cycle"] + (4 if r == "cpl" else 0) + bit)
        elif f == F_DEM:
            if word not in (0, 1):
                raise ValueError(f"demotion group {word}")
            base = OTP_LSB["demotion_state_1" if word == 0 else "demotion_state_2"]
            out.append(base + (1 if r == "cpl" else 0))
        else:
            if not (0 <= word < N_WORDS and 0 <= bit < WORD_BITS):
                raise ValueError(f"word {word} bit {bit}")
            base = OTP_LSB[FIELD_NAMES[f]]
            out.append(base + (256 if r == "cpl" else 0) + WORD_BITS * word + bit)
    return out


def flip_mask(points: list[tuple[int, str, int, int]]) -> int:
    """HK-OTP mask of the points (field, rail, word, bit); rail ``both`` flips both."""
    mask = 0
    for f, rail, word, bit in points:
        for b in _rail_bits(f, rail, word, bit):
            mask |= 1 << b
    return mask


# --- RAND-REP plan ------------------------------------------------------------------


@dataclass(frozen=True)
class FlipPoint:
    """One inject point: field, rail (val, cpl or both), word or group, bit."""

    f: int
    rail: str
    word: int
    bit: int

    def tup(self) -> tuple[int, str, int, int]:
        return (self.f, self.rail, self.word, self.bit)

    def text(self) -> str:
        return f"{FIELD_NAMES[self.f]}.{self.rail}.w{self.word}.b{self.bit}"


@dataclass
class RepPlan:
    single: list[FlipPoint] = field(default_factory=list)
    double: list[FlipPoint] = field(default_factory=list)
    multi: list[FlipPoint] = field(default_factory=list)
    held: FlipPoint | None = None
    demote_first: int = 1
    algs_bit: int = 0
    signers_bit: int = 0
    draws: list[tuple[str, object]] = field(default_factory=list)


def _draw_point(rng, f: int, rail: str) -> FlipPoint:
    if f == F_LC:
        return FlipPoint(f, rail, 0, rng.randrange(4))
    if f == F_DEM:
        return FlipPoint(f, rail, rng.randrange(2), 0)
    return FlipPoint(f, rail, rng.randrange(N_WORDS), rng.randrange(WORD_BITS))


# Used bits of the two shadow-write fields (sep_efuse_map.adoc): bits 1:0 of
# each REQUIRED_ALGS nibble, bits 1:0 of REQUIRED_SIGNERS.
ALGS_USED_BITS = (0, 1, 4, 5, 8, 9)
SIGNERS_USED_BITS = (0, 1)


def draw_rep(rng) -> RepPlan:
    p = RepPlan()
    for f in range(N_FIELDS):
        for rail in RAILS:
            pt = _draw_point(rng, f, rail)
            p.single.append(pt)
            p.draws.append((f"single.{FIELD_NAMES[f]}.{rail}", f"w{pt.word}.b{pt.bit}"))
    for f in range(N_FIELDS):
        pt = _draw_point(rng, f, "both")
        p.double.append(pt)
        p.draws.append((f"double.{FIELD_NAMES[f]}", f"w{pt.word}.b{pt.bit}"))
    k = 2 + rng.randrange(3)
    for f in sorted(rng.sample(list(range(N_FIELDS)), k)):
        pt = _draw_point(rng, f, "both")
        p.multi.append(pt)
        p.draws.append((f"multi.{FIELD_NAMES[f]}", f"w{pt.word}.b{pt.bit}"))
    p.draws.append(("multi.k", k))
    p.demote_first = 1 + rng.randrange(2)
    p.draws.append(("demote_first", f"DEMOTE_{p.demote_first}"))
    p.held = _draw_point(rng, rng.randrange(N_FIELDS), "both")
    p.draws.append(("held.point", p.held.text()))
    p.algs_bit = int(rng.choice(ALGS_USED_BITS))
    p.signers_bit = int(rng.choice(SIGNERS_USED_BITS))
    p.draws.append(("required_algs.bit", p.algs_bit))
    p.draws.append(("required_signers.bit", p.signers_bit))
    return p


def lock_rounds(a: int) -> dict[str, int]:
    """The two lock masks of the plan: A and its complement over the nine field bits."""
    if not 1 <= bin(a).count("1") <= N_FIELDS - 1 or a & ~LOCK_ALL:
        raise ValueError(f"lock mask A=0x{a:x} must hold 1 to 8 of bits [8:0]")
    return {"a": a, "not_a": ~a & LOCK_ALL}
