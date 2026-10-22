# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register map, bank table and seed plan of ``sep_km_key_bank_register_rand_test``.

No cocotb import, so the plan loads without a simulator.

Register map. Every KM port address and field mask comes from the generated
register headers of the Key Manager RDL (``hw/ip/key_manager/regs/gen/py/``:
``key_manager_reg.py`` for the addresses, the per-block ``*_wrapper_key_reg.py``
files for the fields). At import the module checks that the share words of
every bank sit at a 4-byte stride, so one block read covers one share.

Bank vector. Bit i is bank i in the order OTBN, AES, KMAC, HMAC, MLDSA_SEED,
MLKEM_SEED_D, MLKEM_SEED_Z, MLKEM_MSG. The share widths are those of
``architecture.adoc`` ("Key Delivery"): 12 words for OTBN, 8 for the others.

Seed plan. ``draw_plan`` turns one ``SepSeededRng`` into every value the leaf
draws (the 136 share words, the bank order, the engine order and the idle
count) and ``draw_lines`` gives the ``DRAW`` lines the leaf logs.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from env.sep_abr_kem_nist import NIST_KEM_ENC_M
from env.sep_seeded_rng import SepSeededRng

WORD = 0xFFFF_FFFF

_KM_GEN_PY = Path(__file__).resolve().parents[6] / "ip" / "key_manager" / "regs" / "gen" / "py"


def _load(name: str):
    path = _KM_GEN_PY / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"km_bank_{name}", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


KM = _load("key_manager_reg")
_ABR = _load("abr_wrapper_key_reg")
_ENG = {e: _load(f"{e}_wrapper_key_reg") for e in ("otbn", "aes", "kmac", "hmac")}


def _field_mask(struct_cls, name: str) -> int:
    lsb = 0
    for fname, _ctype, width in struct_cls._fields_:
        if fname == name:
            return ((1 << width) - 1) << lsb
        lsb += width
    raise KeyError(f"{struct_cls.__name__} has no field {name}")


def _a(name: str) -> int:
    return int(getattr(KM, name))


@dataclass(frozen=True)
class Bank:
    """One key bank: two share arrays and its KEY_CTRL."""

    bit: int
    name: str
    engine: str
    share0: tuple[int, ...]
    share1: tuple[int, ...]
    ctrl: int
    valid_mask: int

    @property
    def words(self) -> int:
        return len(self.share0)


def _bank(bit: int, name: str, engine: str, prefix: str, n: int, valid_mask: int) -> Bank:
    s0 = tuple(_a(f"{prefix}_KEY_SHARE0_{i}__REG_ADDR") for i in range(n))
    s1 = tuple(_a(f"{prefix}_KEY_SHARE1_{i}__REG_ADDR") for i in range(n))
    for arr in (s0, s1):
        if any(b - a != 4 for a, b in zip(arr, arr[1:])):
            raise AssertionError(f"{name}: share words are not at a 4-byte stride")
    return Bank(bit, name, engine, s0, s1, _a(f"{prefix}_KEY_CTRL_REG_ADDR"), valid_mask)


_ENG_VALID = {
    e: _field_mask(getattr(m, f"{e.upper()}_WRAPPER_KEY_KEY_CTRL_REG_reg_t"), "key_valid")
    for e, m in _ENG.items()
}
_SEED_VALID = _field_mask(_ABR.ABR_SEED_RF_SEED_CTRL_REG_reg_t, "key_valid")

BANKS: tuple[Bank, ...] = (
    _bank(0, "otbn", "otbn", "OTBN_WRAPPER_KEY", 12, _ENG_VALID["otbn"]),
    _bank(1, "aes", "aes", "AES_WRAPPER_KEY", 8, _ENG_VALID["aes"]),
    _bank(2, "kmac", "kmac", "KMAC_WRAPPER_KEY", 8, _ENG_VALID["kmac"]),
    _bank(3, "hmac", "hmac", "HMAC_WRAPPER_KEY", 8, _ENG_VALID["hmac"]),
    _bank(4, "mldsa_seed", "abr", "ABR_WRAPPER_KEY_MLDSA_SEED", 8, _SEED_VALID),
    _bank(5, "mlkem_seed_d", "abr", "ABR_WRAPPER_KEY_MLKEM_SEED_D", 8, _SEED_VALID),
    _bank(6, "mlkem_seed_z", "abr", "ABR_WRAPPER_KEY_MLKEM_SEED_Z", 8, _SEED_VALID),
    _bank(7, "mlkem_msg", "abr", "ABR_WRAPPER_KEY_MLKEM_MSG", 8, _SEED_VALID),
)
N_BANKS = len(BANKS)
ALL_BANKS = (1 << N_BANKS) - 1
MSG_BANK = BANKS[7]
N_SHARE_WORDS = sum(2 * b.words for b in BANKS)
assert N_SHARE_WORDS == 136, N_SHARE_WORDS

# Engines of the reset leg and the banks behind each (SW_RESET_N bit names).
ENGINES = ("otbn", "aes", "hmac", "kmac", "abr")
ENGINE_BANKS = {e: sum(1 << b.bit for b in BANKS if b.engine == e) for e in ENGINES}
# KM-ISO probes (tb_top) of the engines that have one; AES and OTBN have none.
ISO_PROBE = {
    "hmac": "hmac_km_isolated_probe_o",
    "kmac": "kmac_km_isolated_probe_o",
    "abr": "abr_km_isolated_probe_o",
}

# ML-KEM shared-key output block (abr_wrapper_key.adoc, "MLKEM_SHARED_KEY").
SK_KEY = tuple(_a(f"ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_KEY_{i}__REG_ADDR") for i in range(8))
SK_CTRL = _a("ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_KEY_CTRL_REG_ADDR")
SK_IRQ_STATUS = _a("ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_IRQ_STATUS_REG_ADDR")
SK_IRQ_ENABLE = _a("ABR_WRAPPER_KEY_MLKEM_SHARED_KEY_IRQ_ENABLE_REG_ADDR")
SK_VALID = _field_mask(_ABR.ABR_SHAREDKEY_RF_SK_CTRL_REG_reg_t, "key_valid")
SK_IRQ = _field_mask(_ABR.ABR_SHAREDKEY_RF_SK_IRQ_STATUS_REG_reg_t, "key_valid")
SK_IRQ_EN = _field_mask(_ABR.ABR_SHAREDKEY_RF_SK_IRQ_ENABLE_REG_reg_t, "key_valid_en")
if any(b - a != 4 for a, b in zip(SK_KEY, SK_KEY[1:])):
    raise AssertionError("MLKEM_SHARED_KEY.KEY words are not at a 4-byte stride")

# Range of the drawn idle count between the shared-key delivery and the enable write.
IDLE_OPS_MAX = 8


def vector(values: dict[int, int]) -> int:
    """Bank vector from the KEY_CTRL read of each bank (bank bit -> raw word)."""
    v = 0
    for b in BANKS:
        if values[b.bit] & b.valid_mask:
            v |= 1 << b.bit
    return v


def rsvd_bits(values: dict[int, int]) -> int:
    """OR of the reserved bits that the KEY_CTRL reads returned (logged, not graded)."""
    out = 0
    for b in BANKS:
        out |= values[b.bit] & ~b.valid_mask & WORD
    return out


@dataclass(frozen=True)
class Plan:
    seed: int
    shares: dict[int, tuple[tuple[int, ...], tuple[int, ...]]]
    bank_order: tuple[int, ...]
    engine_order: tuple[str, ...]
    idle_ops: int

    def msg_stage(self) -> tuple[tuple[int, ...], tuple[int, ...]]:
        """Message shares of each staging: share0 the drawn MLKEM_MSG share0,
        share1 = share0 XOR the encapsulation message, so the two shares XOR to
        the message (``architecture.adoc``, "Adams Bridge Key Sideload
        Interfaces": the XOR of the two share banks is the value)."""
        s0 = self.shares[MSG_BANK.bit][0]
        s1 = tuple(a ^ m for a, m in zip(s0, NIST_KEM_ENC_M, strict=True))
        return s0, s1


def draw_plan(seed: int) -> Plan:
    rng = SepSeededRng(seed)
    used: set[int] = set()
    shares: dict[int, tuple[tuple[int, ...], tuple[int, ...]]] = {}
    for b in BANKS:
        pair = []
        for _ in range(2):
            words = []
            for _ in range(b.words):
                # Non-zero and pairwise different over all 136 words, which
                # includes the contract rule for the first share of each bank.
                while True:
                    w = rng.getrandbits(32)
                    if w != 0 and w not in used:
                        break
                used.add(w)
                words.append(w)
            pair.append(tuple(words))
        shares[b.bit] = (pair[0], pair[1])
    order = list(range(N_BANKS))
    rng.shuffle(order)
    engines = list(ENGINES)
    rng.shuffle(engines)
    idle = rng.randrange(0, IDLE_OPS_MAX + 1)
    return Plan(seed, shares, tuple(order), tuple(engines), idle)


def draw_lines(plan: Plan) -> list[str]:
    lines = []
    for b in BANKS:
        s0, s1 = plan.shares[b.bit]
        lines.append(
            f"DRAW share bank={b.name} s0=[{','.join(f'0x{w:08x}' for w in s0)}] "
            f"s1=[{','.join(f'0x{w:08x}' for w in s1)}]"
        )
    lines.append("DRAW bank_order=" + ",".join(BANKS[i].name for i in plan.bank_order))
    lines.append("DRAW engine_order=" + ",".join(plan.engine_order))
    lines.append(f"DRAW idle_ops={plan.idle_ops}")
    return lines
