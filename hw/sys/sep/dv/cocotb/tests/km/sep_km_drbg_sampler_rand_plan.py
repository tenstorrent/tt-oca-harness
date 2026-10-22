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
