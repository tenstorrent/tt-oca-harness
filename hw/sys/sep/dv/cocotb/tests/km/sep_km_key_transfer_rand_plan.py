# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seed plan and key-path decode of ``sep_km_key_transfer_rand_test``.

No cocotb import, so the plan loads and grades without a simulator.

Destinations. DEST_VALID bit i is bank i in the order HMAC, KMAC, AES, OTBN,
ABR ML-DSA seed, ML-KEM seed D, ML-KEM seed Z, ML-KEM message
(``hw/ip/key_manager/doc/firmware.adoc``, "0x24 - CMD_KEY_TRANSFER"). The share
width is 8 words, 12 for OTBN (``hw/sys/sep/doc/crypto.adoc``, "Key Manager Key
Delivery").

Key-path decode. ``KM-BUS`` gives the AW handshakes on the five key-path ports:
0 OTBN, 1 AES, 2 HMAC, 3 KMAC, 4 Adams Bridge. A port of a single-bank engine
names the bank. On the Adams Bridge port the register window of the address
names the bank. The windows come from the generated register header of the Key
Manager RDL (``hw/ip/key_manager/regs/gen/py/key_manager_reg.py``,
``hw/ip/key_manager/regs/gen/adoc/abr_wrapper_key.adoc``). Every key block sits
at a 4 KiB boundary and is smaller than 4 KiB, so the low 12 address bits are
the offset inside the block whether the port carries the KM address or the
block offset; the module checks this at import.

Seed plan. ``draw_plan`` turns one ``SepSeededRng`` into every value the leaf
draws, and ``draw_lines`` gives the ``DRAW`` lines that the leaf logs.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from pathlib import Path

from env.sep_seeded_rng import SepSeededRng

WORD = 0xFFFF_FFFF

_KM_GEN_PY = Path(__file__).resolve().parents[6] / "ip" / "key_manager" / "regs" / "gen" / "py"


def _load(name: str):
    path = _KM_GEN_PY / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"km_xfer_{name}", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_KM = _load("key_manager_reg")


def _a(name: str) -> int:
    return int(getattr(_KM, name))


# --- destinations -------------------------------------------------------------

HMAC, KMAC, AES, OTBN, MLDSA, SEED_D, SEED_Z, MSG = range(8)
BANK_NAME = ("hmac", "kmac", "aes", "otbn", "mldsa", "seed_d", "seed_z", "msg")
WIDTH = {HMAC: 8, KMAC: 8, AES: 8, OTBN: 12, MLDSA: 8, SEED_D: 8, SEED_Z: 8, MSG: 8}
ALL_BANKS = 0xFF
ABR_BITS = (1 << SEED_D) | (1 << SEED_Z) | (1 << MSG)
MAX_KEY_WORDS = 128

# The delivery-leg engines: the two witnesses and the three without a witness.
WITNESS = (AES, HMAC)
NO_WITNESS = (KMAC, OTBN, MLDSA)
# Witness sizes run on every seed (width 8). The sizes below the width (1, 7)
# serve only the planned pad check and do not run.
FORCED_SIZES = (1, 7, 8, 9, 16, 17, 128)
DRAWN_SIZE_RANGE = (18, 127)
# Sizes whose witness output CHK-GOLD grades: above 16 words.
GOLD_MIN_SIZE = 17
# Sizes whose witness output is a control: the open sideload tests grade 8-16.
CONTROL_SIZES = (8, 9, 16)
SIZE_CLASSES = ("below", "equal", "above")


# --- key-path decode ----------------------------------------------------------

_BLOCK_SPAN = 0x1000
_PORT_BLOCK = {
    0: ("OTBN_WRAPPER_KEY_REG_MAP", OTBN),
    1: ("AES_WRAPPER_KEY_REG_MAP", AES),
    2: ("HMAC_WRAPPER_KEY_REG_MAP", HMAC),
    3: ("KMAC_WRAPPER_KEY_REG_MAP", KMAC),
}
ABR_PORT = 4
N_PORTS = 5
_PORT_SIZE = {p: _a(f"{blk}_SIZE") for p, (blk, _bit) in _PORT_BLOCK.items()}
_ABR_BASE = _a("ABR_WRAPPER_KEY_REG_MAP_BASE_ADDR")
_ABR_RF = {
    MLDSA: "ABR_WRAPPER_KEY_MLDSA_SEED_REG_FILE",
    SEED_D: "ABR_WRAPPER_KEY_MLKEM_SEED_D_REG_FILE",
    SEED_Z: "ABR_WRAPPER_KEY_MLKEM_SEED_Z_REG_FILE",
    MSG: "ABR_WRAPPER_KEY_MLKEM_MSG_REG_FILE",
}
_ABR_WIN = {
    bit: (_a(f"{rf}_BASE_ADDR") - _ABR_BASE, _a(f"{rf}_SIZE")) for bit, rf in _ABR_RF.items()
}
for _blk, _ in _PORT_BLOCK.values():
    if _a(f"{_blk}_BASE_ADDR") % _BLOCK_SPAN or _a(f"{_blk}_SIZE") > _BLOCK_SPAN:
        raise AssertionError(f"{_blk}: not a 4 KiB-aligned block below 4 KiB")
if _ABR_BASE % _BLOCK_SPAN or _a("ABR_WRAPPER_KEY_REG_MAP_SIZE") > _BLOCK_SPAN:
    raise AssertionError("ABR_WRAPPER_KEY: not a 4 KiB-aligned block below 4 KiB")


def bank_of(port: int, addr: int) -> int | None:
    """The bank of one key-path write, or None for an address outside every bank."""
    off = addr % _BLOCK_SPAN
    if port in _PORT_BLOCK:
        return _PORT_BLOCK[port][1] if off < _PORT_SIZE[port] else None
    if port == ABR_PORT:
        for bit, (lo, size) in _ABR_WIN.items():
            if lo <= off < lo + size:
                return bit
    return None


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    banks_in_order: int
    interleaved: int
    missing: tuple[int, ...]
    outside_mask: int
    unknown: int
    order: tuple[int, ...]
    writes: int

    def order_names(self) -> str:
        return ",".join(BANK_NAME[b] for b in self.order) or "-"


def grade_order(writes: list[tuple[int, int]], mask: int) -> OrderResult:
    """CHK-ENG-ORDER over the (port, address) AW handshakes of one transfer.

    The writes to the banks of ``mask`` must form one contiguous run per bank,
    and the runs must come in ascending DEST_VALID bit order. Every bank of the
    mask must show at least one write (the control). A write to a bank outside
    the mask, or to an address outside every bank, is counted and logged; the
    address set of a transfer is the planned delivery check, not this one.
    """
    seq: list[int] = []
    outside = unknown = 0
    for port, addr in writes:
        bank = bank_of(port, addr)
        if bank is None:
            unknown += 1
        elif not (mask >> bank) & 1:
            outside += 1
        else:
            seq.append(bank)
    runs: list[int] = []
    for bank in seq:
        if not runs or runs[-1] != bank:
            runs.append(bank)
    selected = tuple(b for b in range(8) if (mask >> b) & 1)
    missing = tuple(b for b in selected if b not in runs)
    interleaved = len(runs) - len(set(runs))
    ascending = all(a < b for a, b in zip(runs, runs[1:]))
    ok = not missing and interleaved == 0 and ascending
    in_order = len(runs) if ok else 0
    return OrderResult(ok, in_order, interleaved, missing, outside, unknown, tuple(runs), len(seq))


# --- seed plan ----------------------------------------------------------------


@dataclass(frozen=True)
class Round:
    eng: int
    size: int
    size_class: str
    words: tuple[int, ...]

    @property
    def width(self) -> int:
        return WIDTH[self.eng]

    @property
    def runs(self) -> bool:
        """False for a round below the width: it serves only planned checks."""
        return self.size >= self.width

    @property
    def mask(self) -> int:
        return 1 << self.eng


@dataclass(frozen=True)
class Plan:
    seed: int
    rounds: tuple[Round, ...]
    witness_drawn: dict[int, int]
    other_class: dict[int, str]
    p1: int
    p2: int
    m: int
    x: int
    z: int
    m2: int
    v: int
    s: int
    leg_order: tuple[str, str]
    k1: tuple[int, ...]
    k2: tuple[int, ...]
    k3: tuple[int, ...]


def _popcount(v: int) -> int:
    return bin(v).count("1")


def _key(rng: SepSeededRng, n: int, used: set[int]) -> tuple[int, ...]:
    """``n`` non-zero words, pairwise different over every key of the leaf."""
    out = []
    for _ in range(n):
        while True:
            w = rng.getrandbits(32)
            if w != 0 and w not in used:
                break
        used.add(w)
        out.append(w)
    return tuple(out)


def _subset(rng: SepSeededRng, of: int) -> int:
    return rng.getrandbits(8) & of


def _class_size(rng: SepSeededRng, cls: str, width: int) -> int:
    if cls == "below":
        return rng.randrange(1, width)
    if cls == "equal":
        return width
    return rng.randrange(width + 1, MAX_KEY_WORDS + 1)


def draw_plan(seed: int) -> Plan:
    rng = SepSeededRng(seed)
    used: set[int] = set()

    # Delivery leg (RANDCFG).
    witness_drawn = {
        e: rng.randrange(DRAWN_SIZE_RANGE[0], DRAWN_SIZE_RANGE[1] + 1) for e in WITNESS
    }
    other_class = {e: rng.choice(SIZE_CLASSES) for e in NO_WITNESS}
    specs: list[tuple[int, int, str]] = []
    for e in WITNESS:
        for size in (*FORCED_SIZES, witness_drawn[e]):
            cls = "below" if size < WIDTH[e] else ("equal" if size == WIDTH[e] else "above")
            specs.append((e, size, cls))
    for e in NO_WITNESS:
        cls = other_class[e]
        specs.append((e, _class_size(rng, cls, WIDTH[e]), cls))
    rng.shuffle(specs)
    rounds = tuple(Round(e, size, cls, _key(rng, size, used)) for e, size, cls in specs)

    # Policy leg (RAND-REP).
    while True:
        p1 = rng.getrandbits(8) | (1 << HMAC)
        if _popcount(p1) >= 3 and p1 != ALL_BANKS:
            break
    outside = ALL_BANKS & ~p1
    while True:
        p2 = rng.getrandbits(8)
        if p2:
            break
    while True:
        m = (1 << HMAC) | _subset(rng, p1)
        if _popcount(m) >= 2:
            break
    while True:
        x = (1 << HMAC) | _subset(rng, p1) | _subset(rng, outside)
        if x & outside:
            break
    while True:
        z = _subset(rng, outside)
        if z:
            break
    while True:
        m2 = _subset(rng, p2)
        if m2:
            break
    extra = (1 << KMAC) | (1 << OTBN) | (1 << MLDSA)
    v = (1 << HMAC) | (1 << AES) | ABR_BITS | _subset(rng, extra)
    s = (1 << HMAC) | ABR_BITS | _subset(rng, v & extra)
    leg_order = ("revoke", "shred") if rng.getrandbits(1) else ("shred", "revoke")
    k1 = _key(rng, 8, used)
    k2 = _key(rng, 8, used)
    k3 = _key(rng, 8, used)
    return Plan(
        seed,
        rounds,
        witness_drawn,
        other_class,
        p1,
        p2,
        m,
        x,
        z,
        m2,
        v,
        s,
        leg_order,
        k1,
        k2,
        k3,
    )


def _words(ws: tuple[int, ...]) -> str:
    return "[" + ",".join(f"0x{w:08x}" for w in ws) + "]"


def draw_lines(plan: Plan) -> list[str]:
    lines = [f"DRAW witness_size_{BANK_NAME[e]}={plan.witness_drawn[e]}" for e in WITNESS]
    lines += [f"DRAW size_class_{BANK_NAME[e]}={plan.other_class[e]}" for e in NO_WITNESS]
    for i, r in enumerate(plan.rounds):
        lines.append(
            f"DRAW round{i}=eng:{BANK_NAME[r.eng]},size:{r.size},class:{r.size_class},"
            f"runs:{int(r.runs)} key={_words(r.words)}"
        )
    lines += [
        f"DRAW p1=0x{plan.p1:02x}",
        f"DRAW p2=0x{plan.p2:02x}",
        f"DRAW m=0x{plan.m:02x}",
        f"DRAW x=0x{plan.x:02x}",
        f"DRAW z=0x{plan.z:02x}",
        f"DRAW m2=0x{plan.m2:02x}",
        f"DRAW v=0x{plan.v:02x}",
        f"DRAW s=0x{plan.s:02x}",
        f"DRAW leg_order={','.join(plan.leg_order)}",
        f"DRAW k1={_words(plan.k1)}",
        f"DRAW k2={_words(plan.k2)}",
        f"DRAW k3={_words(plan.k3)}",
    ]
    return lines


def check_plan(plan: Plan) -> None:
    """Construction rules of the contract; a violation is a testbench error."""
    for r in plan.rounds:
        assert 1 <= r.size <= MAX_KEY_WORDS and len(r.words) == r.size
        assert all(r.words) and len(set(r.words)) == r.size
    assert plan.p1 & (1 << HMAC) and _popcount(plan.p1) >= 3 and plan.p1 != ALL_BANKS
    assert plan.m & ~plan.p1 == 0 and plan.m & (1 << HMAC) and _popcount(plan.m) >= 2
    assert plan.x & (1 << HMAC) and plan.x & ~plan.p1 & ALL_BANKS
    assert plan.z and plan.z & plan.p1 == 0
    assert plan.m2 and plan.m2 & ~plan.p2 == 0
    assert plan.v & ((1 << HMAC) | (1 << AES) | ABR_BITS) == (1 << HMAC) | (1 << AES) | ABR_BITS
    assert plan.s & ~plan.v == 0 and plan.s != plan.v
    assert plan.s & ((1 << HMAC) | ABR_BITS) == (1 << HMAC) | ABR_BITS
    assert not plan.s & (1 << AES)
