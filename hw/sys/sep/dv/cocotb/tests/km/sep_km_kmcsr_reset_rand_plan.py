# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register map, goldens and the seeded plan of ``sep_km_kmcsr_reset_rand_test``.

No cocotb import: the plan is a pure function of the seed, so it can be drawn
and checked without a simulator.

KM bus addresses come from the generated ``key_manager_addr.h``. Field masks
and reset values come from the generated ``km_csr.h`` and
``km_drbg_sampler.h`` (the RDL). Values that the RDL does not carry are taken
from the specification text named next to each constant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import CHeaderRegBlock, ip_c_header

WORD_MASK = 0xFFFF_FFFF

# --- generated KM bus map ------------------------------------------------------
_ADDR_H = ip_c_header("key_manager").with_name("key_manager_addr.h")
_DEFINE = re.compile(r"^#define\s+(KEY_MANAGER_\w+)\s+(0x[0-9A-Fa-f]+)\s*$")


def _addr_map() -> dict[str, int]:
    out: dict[str, int] = {}
    for line in _ADDR_H.read_text(encoding="utf-8").splitlines():
        m = _DEFINE.match(line.strip())
        if m:
            out[m.group(1)] = int(m.group(2), 16)
    return out


_MAP = _addr_map()


def km_addr(name: str) -> int:
    """KM bus address ``KEY_MANAGER_<name>`` of the generated map."""
    try:
        return _MAP["KEY_MANAGER_" + name]
    except KeyError as exc:
        raise KeyError(f"KEY_MANAGER_{name} is not in {_ADDR_H}") from exc


def _csr(reg: str) -> int:
    return km_addr(f"KMCSR_{reg}_BASE_ADDR")


A_VERSION = _csr("VERSION")
A_CTRL = _csr("CTRL")
A_SOFT_RST = _csr("SOFT_RST_CODE")
A_IRQ_STATUS = _csr("IRQ_STATUS")
A_IRQ_ENABLE = _csr("IRQ_ENABLE")
A_SCR_KEY = _csr("SCRAMBLER_KEY")
A_SCR_CTRL = _csr("SCRAMBLER_CTRL")
A_SRAM_LOCK = _csr("SRAM_LOCK")
A_IRQ_SET = _csr("IRQ_SET")
A_VIOL = _csr("SRAM_WRITE_LOCK_VIOLATION")
A_BOOT = _csr("BOOT_STATUS")
A_ENTRY = _csr("IRQ_ENTRY_ADDR")
A_ENTRY_LOCK = _csr("IRQ_ENTRY_LOCK")
A_DEBUG = _csr("DEBUG")
A_OTP_LOCK = _csr("OTP_READ_LOCK")
A_OTP_LOCK_COLD = _csr("OTP_READ_LOCK_COLD")
A_SMP_DATA = km_addr("DRBG_SAMPLER_DATA_BASE_ADDR")
A_SMP_CFG = km_addr("DRBG_SAMPLER_CFG_BASE_ADDR")
A_MBOX_KM_STATUS = km_addr("MAILBOX_KM_KM_STATUS_BASE_ADDR")
ROM_BASE = km_addr("ROM_BASE_ADDR")
ROM_END = ROM_BASE + km_addr("ROM_SIZE")
SRAM_BASE = km_addr("SRAM_BASE_ADDR")
SRAM_SIZE = km_addr("SRAM_SIZE")
SRAM_END = SRAM_BASE + SRAM_SIZE
KPV_END = km_addr("KPV_BASE_ADDR") + km_addr("KPV_SIZE")

# --- generated fields and resets (RDL) -------------------------------------------
KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
KM_SMP = CHeaderRegBlock(
    "KM_DRBG_SAMPLER", ip_c_header("key_manager").with_name("km_drbg_sampler.h")
)
KM_MBX = CHeaderRegBlock("KM_MAILBOX_KM", ip_c_header("key_manager").with_name("km_mailbox_km.h"))


def field_mask(blk: CHeaderRegBlock, reg: str) -> int:
    """Union of the RDL field bits of ``reg`` without its reserved field."""
    return sum(m.get("bm", 0) for n, m in blk.fields(reg).items() if n != "RSVD")


def bm(blk: CHeaderRegBlock, reg: str, name: str) -> int:
    return blk.fields(reg)[name]["bm"]


IRQ_FIELDS = field_mask(KM_CSR, "IRQ_STATUS_REG")
IRQ_NAMES = tuple(
    n
    for n, _ in sorted(
        ((n, m["bp"]) for n, m in KM_CSR.fields("IRQ_STATUS_REG").items() if n != "RSVD"),
        key=lambda t: t[1],
    )
)
IRQ_BITS = len(IRQ_NAMES)
IRQ_ROM_PARITY = bm(KM_CSR, "IRQ_STATUS_REG", "ROM_PARITY_ERR")
IRQ_SRAM_PARITY = bm(KM_CSR, "IRQ_STATUS_REG", "SRAM_PARITY_ERR")
IRQ_ROM_WRITE = bm(KM_CSR, "IRQ_STATUS_REG", "ROM_WRITE_ERR")
IRQ_SRAM_LOCK = bm(KM_CSR, "IRQ_STATUS_REG", "SRAM_WRITE_LOCK_ERR")
IRQ_SLVERR = bm(KM_CSR, "IRQ_STATUS_REG", "AXI_SLVERR")
IRQ_EN_FIELDS = field_mask(KM_CSR, "IRQ_ENABLE_REG")
ENTRY_LOCK_BIT = bm(KM_CSR, "IRQ_ENTRY_LOCK_REG", "LOCK")
CBD_BIT = bm(KM_CSR, "BOOT_STATUS_REG", "COLD_BOOT_DONE")
OTP_LOCK_FIELDS = field_mask(KM_CSR, "OTP_READ_LOCK_REG")
OTP_COLD_FIELDS = field_mask(KM_CSR, "OTP_READ_LOCK_COLD_REG")
SCR_CTRL_FIELDS = field_mask(KM_CSR, "SCRAMBLER_CTRL_REG")
CFG_FIELDS = field_mask(KM_SMP, "CFG_REG")
MBOX_KM_INBOUND_EMPTY = bm(KM_MBX, "STATUS_REG", "INBOUND_EMPTY")

VERSION_RESET = KM_CSR.reset("VERSION_REG")
CTRL_RESET = KM_CSR.reset("CTRL_REG")
DEBUG_RESET = KM_CSR.reset("DEBUG_REG")
ENTRY_RESET = KM_CSR.reset("IRQ_ENTRY_ADDR_REG")
ENTRY_LOCK_RESET = KM_CSR.reset("IRQ_ENTRY_LOCK_REG")
IRQ_ENABLE_RESET = KM_CSR.reset("IRQ_ENABLE_REG")
IRQ_STATUS_RESET = KM_CSR.reset("IRQ_STATUS_REG")
SCR_CTRL_RESET = KM_CSR.reset("SCRAMBLER_CTRL_REG")
SRAM_LOCK_RESET = KM_CSR.reset("SRAM_LOCK_REG")
OTP_LOCK_RESET = KM_CSR.reset("OTP_READ_LOCK_REG")
OTP_COLD_RESET = KM_CSR.reset("OTP_READ_LOCK_COLD_REG")
CBD_RESET = KM_CSR.reset("BOOT_STATUS_REG") & CBD_BIT
CFG_RESET = KM_SMP.reset("CFG_REG")

# The register text of km_csr.adoc and km_drbg_sampler.adoc states the same
# resets as the RDL; a mismatch is a specification conflict, not a leaf result.
for _what, _rdl, _text in (
    ("VERSION 1.0.0", VERSION_RESET, 0x0001_0000),
    ("DEBUG", DEBUG_RESET, 0xCAFE_BEEF),
    ("CTRL", CTRL_RESET, 0),
    ("IRQ_ENTRY_ADDR", ENTRY_RESET, 0x10),
    ("DRBG sampler CFG", CFG_RESET, 0x0100_0000),
):
    if _rdl != _text:
        raise RuntimeError(f"{_what}: RDL reset 0x{_rdl:08x} differs from the text 0x{_text:08x}")

# km_csr.adoc, "SOFT_RST_CODE": 0x53525354 ('SRST') triggers the soft reset;
# any other value has no effect.
SOFT_RST_CODE = 0x5352_5354
# architecture.adoc, "Reset Conditioning": the warm reset stays asserted at
# least MIN_RESET_CYCLES clocks after its trigger releases; 10 is the stated
# default and the bound has no upper limit.
MIN_RESET_CYCLES = 10
# km_csr.adoc, "SRAM_LOCK": 32 regions of 1 KiB; architecture.adoc,
# "Parameters": 8192 words of 32 bits.
SRAM_REGIONS = 32
REGION_BYTES = SRAM_SIZE // SRAM_REGIONS
SRAM_WORDS = SRAM_SIZE // 4
WORD_ADDR_BITS = SRAM_WORDS.bit_length() - 1
if REGION_BYTES != 0x400 or SRAM_WORDS != 8192:
    raise RuntimeError(f"KM SRAM map {SRAM_SIZE:#x} does not give 32 x 1 KiB and 8192 words")
# Region 0 holds the POKE result words and the list buffer: never locked or written.
FIRST_FREE = SRAM_BASE + REGION_BYTES
LAST_WORD = SRAM_END - 4
R31_BASE = SRAM_BASE + 31 * REGION_BYTES
R31_FIXED = (R31_BASE, R31_BASE + 4, LAST_WORD)

# Witness values of the reset rounds (the test procedure states them).
W_IRQ_ENABLE = 0xAAA
W_IRQ_SET = (1 << 0) | (1 << 2) | (1 << 4)
W_ENTRY = 0x1230
W_CFG = KM_SMP.value("CFG_REG", TIMEOUT=77, PREFETCH=1)
if W_CFG != 0x004D_0001 or W_IRQ_ENABLE & W_IRQ_SET:
    raise RuntimeError("reset-round witness constants do not match the procedure")

PARK_HOLDS = (1, 2, 5, 12)
PARK_ROUND_HOLD = 200
RESET_KINDS = ("SOFT", "PARK", "COLD", "SOFT-WRONG")
LIST_HEADER_MAGIC = 0x50  # POKE list header [31:24]; a stale word avoids it


def region_of(addr: int) -> int:
    return (addr - SRAM_BASE) // REGION_BYTES


def bits_of(mask: int) -> list[int]:
    return [i for i in range(32) if (mask >> i) & 1]


# --- plan ------------------------------------------------------------------------


@dataclass
class EnCase:
    kind: str  # a, b, c, d
    e: int
    s: int
    src: int = -1  # case c: the source in S AND E


@dataclass
class SramRound:
    index: int
    lock: int  # m | m2
    m: int
    m2: int
    addrs: list[int]  # store addresses (step order)
    init: dict[int, int]  # address -> first word (also for R31_FIXED)
    store: dict[int, int]  # address -> store value (differs from init)
    rel_addr: int
    rel_val: int


@dataclass
class WitnessRound:
    kind: str
    otp_cold_bit: int
    otp_bit: int
    sram: list[tuple[int, int]]  # (address, value)
    sram_lock: int
    mbox_word: int


@dataclass
class Plan:
    seed: int
    ver_wr: int
    walk: list[tuple[int, int]]  # (i, j)
    set_masks: list[int]
    en_order: list[str]
    en_a: EnCase
    en_b: EnCase
    en_c: list[EnCase]
    en_d: EnCase
    scr_k: int
    scr_k2: int
    entry_aligned: int
    entry_unaligned: int
    entry_v2: int
    size_addrs: list[int]  # 14 walk words, then 8 drawn
    size_tags: list[int]
    park_w: list[int]
    sram_rounds: list[SramRound]
    wrong_codes: list[int]
    rounds: list[WitnessRound] = field(default_factory=list)


def _nz32(rng: SepSeededRng, avoid: set[int] = frozenset()) -> int:
    while True:
        v = rng.getrandbits(32)
        if v and v not in avoid:
            return v


def _mask(rng: SepSeededRng, lo: int, hi: int) -> int:
    k = rng.randrange(lo, hi + 1)
    out = 0
    for b in rng.sample(range(IRQ_BITS), k):
        out |= 1 << b
    return out


def _split(rng: SepSeededRng, mask: int) -> tuple[int, int]:
    """Two disjoint non-empty parts of ``mask`` (at least two bits)."""
    bits = bits_of(mask)
    rng.shuffle(bits)
    cut = rng.randrange(1, len(bits))
    m = sum(1 << b for b in bits[:cut])
    return m, mask & ~m


def _word_in_region(rng: SepSeededRng, region: int, avoid: set[int]) -> int:
    base = SRAM_BASE + region * REGION_BYTES
    while True:
        a = base + 4 * rng.randrange(REGION_BYTES // 4)
        if a not in avoid:
            return a


def _free_word(rng: SepSeededRng, avoid: set[int], regions: set[int] | None = None) -> int:
    while True:
        a = FIRST_FREE + 4 * rng.randrange((SRAM_END - FIRST_FREE) // 4)
        if a in avoid or (regions is not None and region_of(a) not in regions):
            continue
        return a


def _sram_round(rng: SepSeededRng, index: int) -> SramRound:
    fixed = set(R31_FIXED)
    if index in (1, 2):
        lock = sum(1 << r for r in range(1, SRAM_REGIONS) if r % 2 == index % 2)
        addrs = [_word_in_region(rng, r, fixed) for r in range(1, SRAM_REGIONS)]
        rng.shuffle(addrs)
    else:
        k = rng.randrange(3, 9)
        regions = [*rng.sample(range(1, 31), k - 1), 31]
        lock = sum(1 << r for r in regions)
        locked_low = [r for r in regions if r != 31]
        unlocked = [r for r in range(1, SRAM_REGIONS) if not (lock >> r) & 1]
        addrs = [
            _word_in_region(rng, rng.choice(locked_low), fixed),
            _word_in_region(rng, rng.choice(unlocked), fixed),
        ]
        while len(addrs) < 12:
            a = _free_word(rng, fixed | set(addrs))
            addrs.append(a)
        rng.shuffle(addrs)
    m, m2 = _split(rng, lock)
    init: dict[int, int] = {}
    store: dict[int, int] = {}
    for a in [*addrs, *R31_FIXED]:
        init[a] = _nz32(rng)
        store[a] = _nz32(rng, {init[a]})
    locked_addrs = [a for a in addrs if (lock >> region_of(a)) & 1]
    rel_addr = rng.choice(locked_addrs)
    rel_val = _nz32(rng, {init[rel_addr], store[rel_addr]})
    return SramRound(index, lock, m, m2, addrs, init, store, rel_addr, rel_val)


def _wrong_codes(rng: SepSeededRng) -> list[int]:
    neighbours = [SOFT_RST_CODE ^ (1 << b) for b in range(32)]
    codes = [0x0000_0000, 0xFFFF_FFFF, rng.choice(neighbours)]
    while len(codes) < 5:
        v = rng.choice(neighbours) if rng.getrandbits(1) else rng.getrandbits(32)
        if v != SOFT_RST_CODE and v not in codes:
            codes.append(v)
    for c in codes:
        if c == SOFT_RST_CODE:
            raise AssertionError("a wrong SOFT_RST_CODE equals the reset code")
    return codes


def draw_plan(seed: int) -> Plan:
    rng = SepSeededRng(seed)
    ver_wr = _nz32(rng, {VERSION_RESET})

    order = list(range(IRQ_BITS))
    rng.shuffle(order)
    walk = [(i, rng.choice([j for j in range(IRQ_BITS) if j != i])) for i in order]
    set_masks = [_mask(rng, 1, 5) for _ in range(3)]

    en_order = ["a", "b", "c", "d"]
    rng.shuffle(en_order)
    en_a = EnCase("a", 0, _mask(rng, 1, IRQ_BITS))
    while True:
        e = _mask(rng, 1, IRQ_BITS - 1)
        s = _mask(rng, 1, IRQ_BITS) & ~e
        if s:
            en_b = EnCase("b", e, s)
            break
    srcs = list(range(IRQ_BITS))
    rng.shuffle(srcs)
    en_c = []
    for i in srcs:
        e = rng.getrandbits(IRQ_BITS) | (1 << i)
        s = rng.getrandbits(IRQ_BITS) | (1 << i)
        en_c.append(EnCase("c", e, s, i))
    s = _mask(rng, 1, IRQ_BITS)
    sub = [b for b in bits_of(s) if rng.getrandbits(1)] or [rng.choice(bits_of(s))]
    en_d = EnCase("d", sum(1 << b for b in sub), s)

    scr_k = _nz32(rng)
    scr_k2 = _nz32(rng, {scr_k})
    entry_aligned = _nz32(rng, {ENTRY_RESET, WORD_MASK}) & ~0x3
    while entry_aligned in (0, ENTRY_RESET):
        entry_aligned = _nz32(rng) & ~0x3
    while True:
        entry_unaligned = _nz32(rng, {WORD_MASK})
        if entry_unaligned & 0x3:
            break
    entry_v2 = _nz32(rng, {WORD_MASK})

    walk_addrs = [LAST_WORD] + [LAST_WORD - 4 * (1 << k) for k in range(WORD_ADDR_BITS)]
    drawn: list[int] = []
    while len(drawn) < 8:
        a = _free_word(rng, set(walk_addrs) | set(drawn))
        drawn.append(a)
    size_addrs = walk_addrs + drawn
    tags: list[int] = []
    for _ in size_addrs:
        tags.append(_nz32(rng, set(tags)))

    rest = [w for w in PARK_HOLDS if w != max(PARK_HOLDS)]
    rng.shuffle(rest)
    park_w = [max(PARK_HOLDS), *rest]

    sram_rounds = [_sram_round(rng, r) for r in (1, 2, 3)]
    wrong = _wrong_codes(rng)

    plan = Plan(
        seed,
        ver_wr,
        walk,
        set_masks,
        en_order,
        en_a,
        en_b,
        en_c,
        en_d,
        scr_k,
        scr_k2,
        entry_aligned,
        entry_unaligned,
        entry_v2,
        size_addrs,
        tags,
        park_w,
        sram_rounds,
        wrong,
    )

    kinds = list(RESET_KINDS)
    rng.shuffle(kinds)
    locked_regions = 0  # SRAM_LOCK bits a SOFT-WRONG round leaves set
    for kind in kinds:
        used: set[int] = set()
        sram = []
        for _ in range(8):
            free = {r for r in range(1, SRAM_REGIONS) if not (locked_regions >> r) & 1}
            a = _free_word(rng, used, free)
            used.add(a)
            sram.append(a)
        values: list[int] = []
        for _ in range(9):
            while True:
                v = _nz32(rng, set(values))
                if (v >> 24) != LIST_HEADER_MAGIC:
                    break
            values.append(v)
        held = {region_of(a) for a in sram}
        cand = [r for r in range(1, SRAM_REGIONS) if r not in held]
        lock = sum(1 << r for r in rng.sample(cand, rng.randrange(1, 4)))
        plan.rounds.append(
            WitnessRound(
                kind,
                rng.randrange(OTP_COLD_FIELDS.bit_length()),
                rng.randrange(OTP_LOCK_FIELDS.bit_length()),
                list(zip(sram, values[:8], strict=True)),
                lock,
                values[8],
            )
        )
        if kind == "SOFT-WRONG":
            locked_regions |= lock
        else:
            locked_regions = 0
    return plan


def plan_draw_lines(p: Plan) -> list[str]:
    """One ``DRAW`` line per drawn dimension, in draw order."""
    h = lambda v: f"0x{v:08x}"  # noqa: E731
    out = [
        f"DRAW version_wr={h(p.ver_wr)}",
        "DRAW irq_walk=" + ",".join(f"{i}/{j}" for i, j in p.walk),
        "DRAW irq_set_masks=" + ",".join(f"0x{m:03x}" for m in p.set_masks),
        "DRAW en_order=" + ",".join(p.en_order),
        f"DRAW en_a e=0x{p.en_a.e:03x} s=0x{p.en_a.s:03x}",
        f"DRAW en_b e=0x{p.en_b.e:03x} s=0x{p.en_b.s:03x}",
        "DRAW en_c=" + ",".join(f"src{c.src}:e=0x{c.e:03x}:s=0x{c.s:03x}" for c in p.en_c),
        f"DRAW en_d e=0x{p.en_d.e:03x} s=0x{p.en_d.s:03x}",
        f"DRAW scrambler_key k={h(p.scr_k)} k2={h(p.scr_k2)}",
        f"DRAW irq_entry aligned={h(p.entry_aligned)} unaligned={h(p.entry_unaligned)} "
        f"v2={h(p.entry_v2)}",
        "DRAW size_addrs=" + ",".join(f"0x{a:04x}" for a in p.size_addrs),
        "DRAW size_tags=" + ",".join(h(t) for t in p.size_tags),
        "DRAW park_w=" + ",".join(str(w) for w in p.park_w) + " first=max(fall-delay reference)",
    ]
    for r in p.sram_rounds:
        out.append(
            f"DRAW sram_round={r.index} lock=0x{r.lock:08x} m=0x{r.m:08x} m2=0x{r.m2:08x} "
            f"rel=0x{r.rel_addr:04x}/{h(r.rel_val)}"
        )
        out.append(
            f"DRAW sram_round={r.index} stores="
            + ",".join(f"0x{a:04x}:{h(r.init[a])}>{h(r.store[a])}" for a in r.addrs)
            + " r31="
            + ",".join(f"0x{a:04x}:{h(r.init[a])}>{h(r.store[a])}" for a in R31_FIXED)
        )
    out.append("DRAW wrong_codes=" + ",".join(h(c) for c in p.wrong_codes))
    out.append("DRAW reset_order=" + ",".join(w.kind for w in p.rounds))
    for k, w in enumerate(p.rounds):
        out.append(
            f"DRAW witness round={k} kind={w.kind} otp_cold_bit={w.otp_cold_bit} "
            f"otp_bit={w.otp_bit} sram_lock=0x{w.sram_lock:08x} mbox={h(w.mbox_word)} sram="
            + ",".join(f"0x{a:04x}:{h(v)}" for a, v in w.sram)
        )
    return out
