# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register map, write values and the seeded plan of ``sep_km_drbg_sampler_rand_test``.

No cocotb import: the plan is a pure function of the seed, so it can be drawn
and checked without a simulator.

KM bus addresses come from the generated ``key_manager_addr.h``. Field masks
and reset values come from the generated ``km_drbg_sampler.h`` and
``km_csr.h`` (the RDL).
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


A_DATA = km_addr("DRBG_SAMPLER_DATA_BASE_ADDR")
A_CFG = km_addr("DRBG_SAMPLER_CFG_BASE_ADDR")
A_STATUS = km_addr("DRBG_SAMPLER_STATUS_BASE_ADDR")
A_PDATA = km_addr("DRBG_SAMPLER_PREFETCH_DATA_BASE_ADDR")
A_IRQ_STATUS = km_addr("KMCSR_IRQ_STATUS_BASE_ADDR")
A_IRQ_ENABLE = km_addr("KMCSR_IRQ_ENABLE_BASE_ADDR")

# --- generated fields and resets (RDL) -------------------------------------------
KM_CSR = CHeaderRegBlock("KM_CSR", ip_c_header("key_manager").with_name("km_csr.h"))
KM_SMP = CHeaderRegBlock(
    "KM_DRBG_SAMPLER", ip_c_header("key_manager").with_name("km_drbg_sampler.h")
)


def _f(blk: CHeaderRegBlock, reg: str, name: str) -> dict[str, int]:
    return blk.fields(reg)[name]


def _field_mask(blk: CHeaderRegBlock, reg: str) -> int:
    return sum(m.get("bm", 0) for n, m in blk.fields(reg).items() if n != "RSVD")


IRQ_SLVERR = _f(KM_CSR, "IRQ_STATUS_REG", "AXI_SLVERR")["bm"]
IRQ_DECERR = _f(KM_CSR, "IRQ_STATUS_REG", "AXI_DECERR")["bm"]
IRQ_DRBG_ERR = _f(KM_CSR, "IRQ_STATUS_REG", "DRBG_ERR")["bm"]
IRQ_FIELDS = _field_mask(KM_CSR, "IRQ_STATUS_REG")
IRQ_EN_DRBG_ERR = _f(KM_CSR, "IRQ_ENABLE_REG", "DRBG_ERR_EN")["bm"]
IRQ_ENABLE_RESET = KM_CSR.reset("IRQ_ENABLE_REG")

CFG_RESET = KM_SMP.reset("CFG_REG")
STATUS_RESET = KM_SMP.reset("STATUS_REG")
STATUS_FIELDS = _field_mask(KM_SMP, "STATUS_REG")
STATUS_NAMES = (
    "DRBG_READY",
    "PREFETCHED",
    "TIMEOUT_ERR",
    "STREAM_ERR",
    "COUNT_BAD",
    "COUNT_GOOD",
)
_ST = {n: _f(KM_SMP, "STATUS_REG", n) for n in STATUS_NAMES}
ST_DRBG_READY = _ST["DRBG_READY"]["bm"]
ST_PREFETCHED = _ST["PREFETCHED"]["bm"]
ST_TIMEOUT_ERR = _ST["TIMEOUT_ERR"]["bm"]
ST_STREAM_ERR = _ST["STREAM_ERR"]["bm"]
ST_STICKY = ST_TIMEOUT_ERR | ST_STREAM_ERR
# The four one-bit fields DRBG_READY, PREFETCHED, TIMEOUT_ERR and STREAM_ERR.
ST_FLAGS = ST_DRBG_READY | ST_PREFETCHED | ST_TIMEOUT_ERR | ST_STREAM_ERR
COUNT_BAD_MAX = (1 << _ST["COUNT_BAD"]["bw"]) - 1
COUNT_GOOD_MAX = (1 << _ST["COUNT_GOOD"]["bw"]) - 1
TIMEOUT_MAX = (1 << _f(KM_SMP, "CFG_REG", "TIMEOUT")["bw"]) - 1


def st(value: int, name: str) -> int:
    """Field ``name`` of a STATUS value."""
    meta = _ST[name]
    return (value & meta["bm"]) >> meta["bp"]


def status_write(**fields: int) -> int:
    """A STATUS write value: the named fields as given, every other field 0."""
    out = 0
    for name, v in fields.items():
        meta = _ST[name]
        out |= (v << meta["bp"]) & meta["bm"]
    return out


def cfg(timeout: int, prefetch: int) -> int:
    """A CFG value with ``timeout`` and ``prefetch``; the reserved field at its reset."""
    return KM_SMP.value("CFG_REG", TIMEOUT=timeout, PREFETCH=prefetch)


def status_text(value: int) -> str:
    return " ".join(f"{n.lower()}={st(value, n)}" for n in STATUS_NAMES)


# STATUS writes of the counter clears: a non-zero field value clears the field
# (km_drbg_sampler.adoc, "STATUS"). The leaf uses the value 1 for the first
# clear of each counter and the full field for the clear from saturation.
CLR_BAD_LOW = status_write(COUNT_BAD=1)
CLR_BAD_FULL = status_write(COUNT_BAD=COUNT_BAD_MAX)
CLR_GOOD_LOW = status_write(COUNT_GOOD=1)
CLR_GOOD_FULL = status_write(COUNT_GOOD=COUNT_GOOD_MAX)

# --- test parameters ---------------------------------------------------------------
FORCED_STALLED_T = (1, 2, 3, TIMEOUT_MAX)
GRADED_STALLED_T = frozenset(FORCED_STALLED_T)
# The CFG.TIMEOUT reset value (km_drbg_sampler.adoc, "CFG"), from the RDL reset.
RESET_T = (CFG_RESET & _f(KM_SMP, "CFG_REG", "TIMEOUT")["bm"]) >> _f(KM_SMP, "CFG_REG", "TIMEOUT")[
    "bp"
]
DRAWN_T_RANGE = (4, 400)
FED_T = (0, TIMEOUT_MAX)
PREFETCH_T = 8
PREFETCH_WINDOW_CLKS = 1024
# Read loops that run each counter to saturation and past it: 3 and 5 reads
# more than the field maximum.
BAD_LOOP_READS = COUNT_BAD_MAX + 3
GOOD_LOOP_READS = COUNT_GOOD_MAX + 5
EXTRA_READS = 2
GOOD_SAT_ONE_IN = 3
STRM_CASES = (("b", RESET_T), ("c", 1), ("d", 2))
PULSE_DELAY_MAX = 63
PDATA_READS = 3


@dataclass
class Plan:
    """The seeded draws of one leaf."""

    seed: int
    t_drawn: int
    t_order: list[int]
    good_sat: bool
    pulse_delay: int
    draws: list[tuple[str, object]] = field(default_factory=list)


def draw_plan(rng: SepSeededRng, seed: int) -> Plan:
    """Draw the leaf plan from ``rng``; every draw is listed in ``Plan.draws``."""
    t_drawn = rng.randrange(DRAWN_T_RANGE[0], DRAWN_T_RANGE[1] + 1)
    order = [*FORCED_STALLED_T, t_drawn, RESET_T]
    rng.shuffle(order)
    good_sat = rng.randrange(GOOD_SAT_ONE_IN) == 0
    pulse_delay = rng.randrange(PULSE_DELAY_MAX + 1)
    plan = Plan(seed, t_drawn, order, good_sat, pulse_delay)
    plan.draws = [
        ("t_drawn", t_drawn),
        ("t_order", ",".join(str(t) for t in order)),
        ("good_sat", int(good_sat)),
        ("pulse_delay_case_a", pulse_delay),
    ]
    return plan


# --- external-stream legs ------------------------------------------------------------
# The legs draw from their own generator, ``SepSeededRng(seed ^ EXT_SALT)``, so
# the draws of ``draw_plan`` keep their seed-to-value mapping.
EXT_SALT = 0x5A4D_5045
WORD_BYTES = 4
STRB_ALL = (1 << WORD_BYTES) - 1
IRQ_GATE_T_RANGE = (1, 8)
TO_ASM_T_RANGE = (4, 20)
PRE_PARTIAL_PATTERNS = 2
PRE_PARTIAL_BEATS = (2, 4)
# Clocks after a completed handshake before the next host action; every value
# is drawn once per seed.
PRE_PARTIAL_GAPS = (0, 1, 2, 5)
PACK_STRB0_BEATS = 2
STRM_DROP_GAP_RANGE = (1, 8)
# Clocks between the TREADY rise of a waiting DATA read and the host queueing
# the beat; every value is drawn once per seed, plus one from the range.
STRM_PULSE_DELAYS = (0, 1, 2)
STRM_PULSE_EXTRA_RANGE = (2, 6)

Beat = tuple[int, int]  # (TDATA, TSTRB)

_BY_COUNT = {c: [s for s in range(STRB_ALL + 1) if s.bit_count() == c] for c in range(5)}


def pack(beats: list[Beat]) -> tuple[int, int]:
    """The word a DATA read assembles from ``beats``, and the bytes it drops.

    Each beat gives its TSTRB-selected bytes, lanes 0 to 3 in order; the
    bytes fill the word from byte 0 upward in beat order; bytes past the
    fourth are dropped (architecture.adoc, "Reads, prefetch and register
    access"). A TSTRB 0x0 beat gives no byte.
    """
    got: list[int] = []
    for data, strb in beats:
        got += [(data >> (8 * j)) & 0xFF for j in range(WORD_BYTES) if strb >> j & 1]
    if len(got) < WORD_BYTES:
        raise ValueError(f"beats give {len(got)} valid bytes, a word needs {WORD_BYTES}")
    return sum(b << (8 * i) for i, b in enumerate(got[:WORD_BYTES])), len(got) - WORD_BYTES


@dataclass
class ExtPlan:
    """The seeded draws of the external-stream legs."""

    irq_t: int
    to_asm_t: int
    to_asm_beat: Beat
    pre_patterns: list[list[Beat]]
    pre_gaps: list[int]
    pack_patterns: list[list[Beat]]
    strm_drop: tuple[int, int]
    strm_pulses: list[tuple[int, int]]
    draws: list[tuple[str, object]] = field(default_factory=list)


def _strb(rng: SepSeededRng, count: int) -> int:
    return rng.choice(_BY_COUNT[count])


def _beat(rng: SepSeededRng, strb: int) -> Beat:
    return rng.getrandbits(32), strb


def _pre_pattern(rng: SepSeededRng) -> list[Beat]:
    """2 to 4 beats with a non-zero TSTRB; four valid bytes only with the last beat."""
    n = rng.randrange(PRE_PARTIAL_BEATS[0], PRE_PARTIAL_BEATS[1] + 1)
    head = [1] * (n - 1)
    for _ in range(rng.randrange(WORD_BYTES - n + 1)):
        head[rng.randrange(n - 1)] += 1
    need = WORD_BYTES - sum(head)
    last = rng.randrange(need, WORD_BYTES + 1)
    return [_beat(rng, _strb(rng, c)) for c in [*head, last]]


def _pack_patterns(rng: SepSeededRng) -> list[list[Beat]]:
    """Every TSTRB 0x1 to 0xF once, in drawn order, with two TSTRB 0x0 beats
    inside; each pattern is the beats of one DATA read, and at least one
    pattern drops bytes."""
    strbs = list(range(1, STRB_ALL + 1))
    rng.shuffle(strbs)
    for _ in range(PACK_STRB0_BEATS):
        strbs.insert(rng.randrange(len(strbs) + 1), 0)
    patterns: list[list[Beat]] = []
    cur: list[Beat] = []
    for s in strbs:
        cur.append(_beat(rng, s))
        if sum(b[1].bit_count() for b in cur) >= WORD_BYTES:
            patterns.append(cur)
            cur = []
    if cur:
        patterns.append([*cur, _beat(rng, STRB_ALL)])
    if not any(pack(p)[1] for p in patterns):
        patterns.append([_beat(rng, 0x1), _beat(rng, STRB_ALL)])
    return patterns


def _strbs(patterns: list[list[Beat]]) -> str:
    return "|".join(",".join(f"{s:x}" for _, s in p) for p in patterns)


def draw_ext_plan(seed: int) -> ExtPlan:
    """Draw the external-stream legs from ``SepSeededRng(seed ^ EXT_SALT)``."""
    rng = SepSeededRng(seed ^ EXT_SALT)
    irq_t = rng.randrange(IRQ_GATE_T_RANGE[0], IRQ_GATE_T_RANGE[1] + 1)
    to_asm_t = rng.randrange(TO_ASM_T_RANGE[0], TO_ASM_T_RANGE[1] + 1)
    to_asm_beat = _beat(rng, _strb(rng, rng.randrange(1, WORD_BYTES)))
    pre = [_pre_pattern(rng) for _ in range(PRE_PARTIAL_PATTERNS)]
    n_pre = sum(len(p) for p in pre)
    gaps = [*PRE_PARTIAL_GAPS, *(rng.choice(PRE_PARTIAL_GAPS) for _ in range(n_pre - 4))]
    rng.shuffle(gaps)
    pack_patterns = _pack_patterns(rng)
    drop = (rng.getrandbits(32), rng.randrange(STRM_DROP_GAP_RANGE[0], STRM_DROP_GAP_RANGE[1] + 1))
    delays = [
        *STRM_PULSE_DELAYS,
        rng.randrange(STRM_PULSE_EXTRA_RANGE[0], STRM_PULSE_EXTRA_RANGE[1] + 1),
    ]
    rng.shuffle(delays)
    pulses = [(k, rng.getrandbits(32)) for k in delays]
    plan = ExtPlan(irq_t, to_asm_t, to_asm_beat, pre, gaps, pack_patterns, drop, pulses)
    plan.draws = [
        ("irq_gate_t", irq_t),
        ("to_asm_t", to_asm_t),
        ("to_asm_strb", f"0x{to_asm_beat[1]:x}"),
        ("pre_partial_strb", _strbs(pre)),
        ("pre_partial_gaps", ",".join(str(g) for g in gaps)),
        ("pack_strb", _strbs(pack_patterns)),
        ("pack_beats", sum(len(p) for p in pack_patterns)),
        ("strm_drop_gap", drop[1]),
        ("strm_pulse_delays", ",".join(str(k) for k, _ in pulses)),
    ]
    return plan
