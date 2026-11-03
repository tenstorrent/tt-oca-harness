# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter match terms, priority, permission and source-ID wildcard on the three filter instances.

``hw/ip/axi_filter/doc/index.adoc`` "Match, Then Permit": an entry matches only when
``entry_enabled`` is 1, the address is in range after granule widening, ``prot[1]`` equals
``allow_ns``, the source ID equals ``src_id`` or ``src_id`` is 0, and ``allow_burst`` is 1 or the
transaction is a single beat; the lowest-numbered matching entry's ``read_allowed`` (AR) or
``write_allowed`` (AW) decides, and an unmatched transaction takes the instance's
unmatched-traffic policy (instance table: SMC inbound and SEP outbound block it, SMC outbound
permits it). "Blocked Transactions": a blocked transaction answers DECERR. "Address Range
Granule": ``allow_burst`` 1 gives a 4 KB granule and ``allow_burst`` 0 an 8-byte granule, and
hardware writes the widened values back into ``START_ADDR`` and ``END_ADDR`` when both land in
the same granule. The leaf programs granule-aligned edges, ``START_ADDR``, ``END_ADDR``, then
``FILTER_CONFIG``; an 8-byte-granule window written while the entry still holds
``allow_burst`` 1 lies in one 4 KB granule, so the write-back widens it to that granule. The
expected registers apply the write-back after every write under the ``allow_burst`` the entry
holds at that moment (the generated reset values before an entry's first write).

Every seed runs the three instances in this order: the SMC inbound (SYS_IN) instance, from the
external AXI master into the SMC SPM; the SMC outbound instance, from the SMC fabric JTAG2AXI
bridge and an iDMA copy to the bench responder outside both apertures; the SEP outbound instance,
from the SEP debug module's system bus to the responder through the SMU aperture. The SEP
instance is last because selecting the SEP STAP splices it into every later PTAP scan. On each
instance the seed draws two entry indices outside those that hold the fixed cells of the entries
this one extends, the granule of the admit window, the window sizes and positions at both
granules, the denied channel of the priority pair and the channel of each term cell; on SYS_IN
also the source ID, its class, ``prot`` and the burst class of the admitted access.

S1: TAP reset, JTAG2AXI gate open, SMC aperture at its local alias, external master; the draw.
S2..S4: SYS_IN admit (lower entry permit over a higher entry deny on one window), term breaks
    (entry_enabled, range one granule up and down at both granules, allow_ns, src_id,
    allow_burst), permission per channel, priority in both programming orders, src_id 0 wildcard.
S5..S9: SMC outbound reset-entry iDMA copy and bridge polarity probe, admit, term breaks of a deny
    entry (an unmatched access passes), measured-only allow_ns and src_id cells, permission,
    priority, and the iDMA allow_burst cell (last: a refused copy may not complete).
S10..S13: SEP outbound debug bring-up and polarity probe, admit, term breaks, measured-only
    cells, permission, priority.
S14: every bounded wait reports its bound, its use and its last state.
"""

from __future__ import annotations

import math
import random
from collections import Counter

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_DECERR, RESP_OKAY, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    INBOUND_FILTER_CONFIG_SYM,
    INBOUND_FILTER_END_SYM,
    INBOUND_FILTER_START_SYM,
    OUTBOUND_FILTER_CONFIG_SYM,
    OUTBOUND_FILTER_END_SYM,
    OUTBOUND_FILTER_START_SYM,
    c_header_u32,
    filter_ctrl_bm,
    filter_ctrl_field_encode,
    filter_ctrl_field_reset_encode,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DONE_0,
    DMA_DST_LO,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_POLL_CYCLES,
    DMA_REPS_LO,
    DMA_SRC_LO,
    DMA_STATUS_0,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    _FILTER_CTRL_H,
    _SEP_ADDR_H,
    SBA_POLLS,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    _indexed_addr,
)
from seq_lib.smu_filter_helpers import (
    FILTER_BURST_GRANULE_BITS,
    SMC_APERTURE_GLOBAL_BASE_REG,
    SMC_APERTURE_LOCAL_BASE,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_BUSY,
    J2A_STATUS_DECERR,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_lc_export_seq import _ReadCounter
from seq_lib.smu_out_filter_rule_matrix_test_seq import OUTBOUND_ENTRIES, _EgressTap
from seq_lib.smu_sep_out_filter_rule_matrix_test_seq import (
    ADMIT_ENTRY_HIGH,
    ADMIT_ENTRY_LOW,
    DENY_ENTRY_HIGH,
    DENY_ENTRY_LOW,
    INDEX_MID_HIGH,
    INDEX_MID_LOW,
)
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    SMU_BASE,
    SMU_SIZE,
    smu_sep_sba_fabric_sweep_test_seq,
)
from seq_lib.smu_tb_pins import smc_primary_reset

# hw/ip/axi_filter/regs/gen/c/filter_ctrl.h: FILTER_CONFIG field masks.
_F_READ = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__READ_ALLOWED_bm")
_F_WRITE = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__WRITE_ALLOWED_bm")
_F_ENTRY = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ENTRY_ENABLED_bm")
_F_ALLOW_NS = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bm")
_F_ALLOW_BURST = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__ALLOW_BURST_bm")
_F_SRC_ID = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm")
_F_GROUP_ID = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm")
_F_DATA_BUS_WIDTH = filter_ctrl_bm("FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bm")
_F_BUS_WIDTH_64 = filter_ctrl_field_reset_encode("DATA_BUS_WIDTH")
# Every FILTER_CONFIG field the leaf programs; LOCKED is never written and not compared.
CFG_MASK = (
    _F_READ
    | _F_WRITE
    | _F_ENTRY
    | _F_ALLOW_NS
    | _F_ALLOW_BURST
    | _F_SRC_ID
    | _F_GROUP_ID
    | _F_DATA_BUS_WIDTH
)
ADDR_MASK = (1 << c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__END_ADDR__END_ADDR_bw")) - 1
# Register reset values (filter_ctrl.h), the state an entry holds before the leaf writes it.
REG_RESET = {
    "start": c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__START_ADDR__START_ADDR_reset"),
    "end": c_header_u32(_FILTER_CTRL_H, "FILTER_CTRL__END_ADDR__END_ADDR_reset"),
    "config": filter_ctrl_field_reset_encode("ALLOW_BURST"),
}
SRC_ID_MAX = _F_SRC_ID // (_F_SRC_ID & -_F_SRC_ID)

SYS_IN = "SYS_IN"
SMC_OUT = "SMC_OUT"
SEP_OUT = "SEP_OUT"
INSTANCES = (SYS_IN, SMC_OUT, SEP_OUT)

# Entry counts: the generated *_NUM symbols of smc_addr.h and sep_addr.h.
SYS_IN_ENTRIES = smc_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_NUM")
SMC_OUT_ENTRIES = smc_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_NUM")
SEP_OUT_ENTRIES = c_header_u32(
    _SEP_ADDR_H, "SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_NUM"
)
# Indices holding the fixed cells of the entries this one extends: SYS_IN entry 0
# (smu_sys_in_filter_src_id_rule_test), SMC outbound entries 0 and 1
# (smu_out_filter_rule_matrix_test), SEP outbound entries 0, 1, 15, 16, 30 and 31
# (smu_sep_out_filter_rule_matrix_test).
FIXED_INDICES = {
    SYS_IN: (0,),
    SMC_OUT: OUTBOUND_ENTRIES,
    SEP_OUT: (
        DENY_ENTRY_LOW,
        DENY_ENTRY_HIGH,
        INDEX_MID_LOW,
        INDEX_MID_HIGH,
        ADMIT_ENTRY_LOW,
        ADMIT_ENTRY_HIGH,
    ),
}
ENTRY_COUNT = {SYS_IN: SYS_IN_ENTRIES, SMC_OUT: SMC_OUT_ENTRIES, SEP_OUT: SEP_OUT_ENTRIES}
ALLOWED_INDICES = {
    inst: tuple(i for i in range(ENTRY_COUNT[inst]) if i not in FIXED_INDICES[inst])
    for inst in INSTANCES
}
# Unmatched-traffic policy of each instance (index.adoc instance table).
UNMATCHED_BLOCKED = {SYS_IN: True, SMC_OUT: False, SEP_OUT: True}

# index.adoc "Address Range Granule": 4 KB with allow_burst 1, 8 bytes with allow_burst 0.
GRANULE_4K = 1 << FILTER_BURST_GRANULE_BITS
GRANULE_8B = 8
GRANULE = {1: GRANULE_4K, 0: GRANULE_8B}
GRANULES_PER_PAGE = GRANULE_4K // GRANULE_8B
N4_RANGE = (1, 3)
# An 8-byte window of at least two granules holds a 16-byte burst inside it.
N8_RANGE = (2, 4)
PAGE_RANGE = (1, 200)
# The 8-byte-granule window sits in its own page, past the 4 KB window moved up by one page.
W8_PAGE_OFFSET = 8
# Window bases: the SMC SPM inside the SMC aperture (SYS_IN), pages below 4 GiB outside both
# apertures (SMC outbound, as smu_out_filter_rule_matrix_test places them), the SMU aperture
# probe window (SEP outbound, as smu_sep_out_filter_rule_matrix_test places it).
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
SMC_OUT_BASE = 0x0200_0000
SEP_OUT_BASE = SMU_BASE + 0x1000_0000
REGION_BASE = {SYS_IN: SPM_BASE, SMC_OUT: SMC_OUT_BASE, SEP_OUT: SEP_OUT_BASE}
REGION_LIMIT = {SYS_IN: SPM_BASE + SPM_SIZE, SMC_OUT: 0x0300_0000, SEP_OUT: SMU_BASE + SMU_SIZE}
# iDMA pages of the SMC outbound allow_burst cell, apart from every drawn window.
DMA_SRC_PAGE = SMC_OUT_BASE + 0x10_0000
DMA_DST_PAGE = SMC_OUT_BASE + 0x11_0000
COPY_LENGTH = 64
DMA_REPETITIONS = 1
DMA_DONE_POLLS = 8

AR, AW = "AR", "AW"
CHANNELS = (AR, AW)
TERM_CELLS = ("entry_enabled", "range_up_4k", "range_down_4k", "range_up_8b", "range_down_8b")
SRC_CLASSES = ("wildcard", "equal")
PINNED_WILDCARD_USERS = (0, SRC_ID_MAX)
# hw/ip/axi_filter/doc/index.adoc "Match, Then Permit": a burst has AxLEN above 0; four 4-byte
# beats make a 16-byte INCR burst, AxLEN 3.
BURST_BEATS = 4
BEAT_SIZE = 2
WORD_BYTES = 4
OKAY = resp_name(RESP_OKAY)
DECERR = resp_name(RESP_DECERR)
SENTINEL_BYTE = 0xA5
PATTERN_SEED = 0x6B1D_3E95_C7A2_0F48

J2A_POLL_LIMIT = 128
# hw/ip/jtag/jtag_ptap/doc/architecture.adoc, single-operation size field: 2**size bytes.
AXSIZE_BYTE = 0
SB_SIZE_WORD = 2
SB_SIZE_DOUBLEWORD = 3
SBACCESS_SHIFT = 17
OBSERVE_BOUND_CYCLES = 4000
STEP_CLOCK_GAP = 2
STEPS = tuple(f"S{i}" for i in range(1, 15))
ACCESS_STEPS = STEPS[1:-1]
EXPECTED_SITES = (
    "dma_done",
    "dma_done_refused",
    "ext_axi",
    "j2a",
    "responder_observe",
    "sba_busy_poll",
)


def _require_layout() -> None:
    w8_top = (PAGE_RANGE[1] + W8_PAGE_OFFSET + 1) * GRANULE_4K
    facts = (
        (all(len(ALLOWED_INDICES[i]) >= 2 for i in INSTANCES), "two indices per instance"),
        (ALLOWED_INDICES[SEP_OUT] == (*range(2, 15), *range(17, 30)), "SEP outbound indices"),
        (
            all(REGION_BASE[i] + w8_top <= REGION_LIMIT[i] for i in INSTANCES),
            "windows inside their region",
        ),
        (PAGE_RANGE[0] >= 1, "a window moved down by one page stays in its region"),
        (
            SMC_OUT_BASE + w8_top <= DMA_SRC_PAGE < DMA_DST_PAGE,
            "iDMA pages apart from the windows",
        ),
        (SRC_ID_MAX == 15, "src_id is four bits"),
    )
    bad = [msg for ok, msg in facts if not ok]
    if bad:
        raise RuntimeError("filter match priority layout: " + "; ".join(bad))


_require_layout()


def draw_cells(seed: int) -> dict:
    """Every drawn dimension of a run, a pure function of the seed; no redraw is needed."""
    rng = random.Random(seed)
    out: dict[str, dict] = {}
    for inst in INSTANCES:
        lo, hi = sorted(rng.sample(ALLOWED_INDICES[inst], 2))
        cell = {
            "lo": lo,
            "hi": hi,
            "ab": rng.randint(0, 1),
            "n4": rng.randint(*N4_RANGE),
            "n8": rng.randint(*N8_RANGE),
            "page": rng.randint(*PAGE_RANGE),
            "prio_ch": rng.choice(CHANNELS),
        }
        cell["gran"] = rng.randint(1, GRANULES_PER_PAGE - cell["n8"] - 2)
        cell["term_ch"] = {name: rng.choice(CHANNELS) for name in TERM_CELLS}
        if inst == SYS_IN:
            cell["user"] = rng.randint(1, SRC_ID_MAX)
            cell["src_class"] = rng.choice(SRC_CLASSES)
            cell["prot"] = rng.randint(0, 7)
            cell["burst"] = rng.choice((False, True)) if cell["ab"] else False
            cell["src_break"] = rng.choice(
                [v for v in range(1, SRC_ID_MAX + 1) if v != cell["user"]]
            )
            cell["wild_users"] = rng.sample(
                [u for u in range(1, SRC_ID_MAX) if u != cell["user"]], 2
            )
        else:
            cell["meas_src_id"] = rng.randint(1, SRC_ID_MAX)
        out[inst] = cell
    return out


def windows(inst: str, cell: dict) -> dict[int, tuple[int, int]]:
    """The two granule-aligned windows {allow_burst: (START, END)}, END inclusive."""
    page = REGION_BASE[inst] + cell["page"] * GRANULE_4K
    w4 = (page, page + cell["n4"] * GRANULE_4K - 1)
    q = page + W8_PAGE_OFFSET * GRANULE_4K + cell["gran"] * GRANULE_8B
    w8 = (q, q + cell["n8"] * GRANULE_8B - 1)
    return {1: w4, 0: w8}


def check_cells(cells: dict) -> None:
    """The constraints every draw keeps; raises on a violation."""
    for inst in INSTANCES:
        cell = cells[inst]
        allowed = ALLOWED_INDICES[inst]
        assert cell["lo"] < cell["hi"] and {cell["lo"], cell["hi"]} <= set(allowed), inst
        for ab, (start, end) in windows(inst, cell).items():
            gran = GRANULE[ab]
            assert start % gran == 0 and (end + 1) % gran == 0, (inst, ab)
            assert REGION_BASE[inst] <= start - gran, (inst, ab)
            assert end + gran < REGION_LIMIT[inst], (inst, ab)
            assert (end + 1 - start) // gran >= (1 if ab else 2), (inst, ab)
        w4, w8 = windows(inst, cell)[1], windows(inst, cell)[0]
        assert w8[0] - GRANULE_8B > w4[1] + GRANULE_4K, inst
        assert (w8[0] - GRANULE_8B) // GRANULE_4K == (w8[1] + GRANULE_8B) // GRANULE_4K, inst
        if inst == SYS_IN:
            assert 1 <= cell["user"] <= SRC_ID_MAX
            assert cell["src_break"] not in (0, cell["user"])
            assert not (cell["burst"] and not cell["ab"])
            users = (*PINNED_WILDCARD_USERS, *cell["wild_users"])
            assert len(set(cell["wild_users"])) == 2 and cell["user"] not in cell["wild_users"]
            assert all(0 <= u <= SRC_ID_MAX for u in users)
        else:
            assert 1 <= cell["meas_src_id"] <= SRC_ID_MAX


def _config(
    *,
    read: int,
    write: int,
    enabled: int = 1,
    allow_ns: int = 0,
    src_id: int = 0,
    allow_burst: int = 1,
) -> int:
    word = _F_BUS_WIDTH_64 | filter_ctrl_field_encode("SRC_ID", src_id)
    for flag, mask in (
        (read, _F_READ),
        (write, _F_WRITE),
        (enabled, _F_ENTRY),
        (allow_ns, _F_ALLOW_NS),
        (allow_burst, _F_ALLOW_BURST),
    ):
        if flag:
            word |= mask
    return word


def _pattern(tag: int, nbytes: int) -> int:
    word = (PATTERN_SEED ^ (tag * 0x9E37_79B9_7F4A_7C15)) & ((1 << 64) - 1)
    value = word & ((1 << (8 * nbytes)) - 1)
    return (
        value ^ 0x1 if value == int.from_bytes(bytes([SENTINEL_BYTE]) * nbytes, "little") else value
    )


def _sentinel(nbytes: int) -> int:
    return int.from_bytes(bytes([SENTINEL_BYTE]) * nbytes, "little")


def _burst_bytes(tag: int, nbytes: int) -> bytes:
    return b"".join(
        _pattern(tag * 8 + i, WORD_BYTES).to_bytes(WORD_BYTES, "little")
        for i in range(nbytes // WORD_BYTES)
    )


_SMC_SYMS = {
    SYS_IN: {
        "start": INBOUND_FILTER_START_SYM,
        "end": INBOUND_FILTER_END_SYM,
        "config": INBOUND_FILTER_CONFIG_SYM,
    },
    SMC_OUT: {
        "start": OUTBOUND_FILTER_START_SYM,
        "end": OUTBOUND_FILTER_END_SYM,
        "config": OUTBOUND_FILTER_CONFIG_SYM,
    },
}
_SEP_SYMS = {
    "start": "SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR",
    "end": "SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR",
    "config": "SEP_TOP_OUTBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR",
}


class smu_filter_match_priority_rand_test_seq(smu_sep_sba_fabric_sweep_test_seq):
    """Seed-drawn match, priority, permission and wildcard cells on SYS_IN, SMC and SEP filters."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.clk = cocotb.top.clk_smu_i
        self.seed = test.random_seed()
        self.cells = draw_cells(self.seed)
        check_cells(self.cells)
        self.win = {inst: windows(inst, self.cells[inst]) for inst in INSTANCES}
        self.j2a_tap = None
        self.master = None
        self.tap: _EgressTap | None = None
        self.step = "S1"
        self.step_ts: dict[str, float] = {}
        self.step_access = dict.fromkeys(STEPS, 0)
        self.sites: dict[str, dict] = {}
        self.regs: dict[tuple, int] = {}
        self.spm: dict[int, bytes] = {}
        self.tag = 0
        self.verdicts = {inst: Counter() for inst in INSTANCES}
        self.ns = {inst: 0 for inst in INSTANCES}
        self.idma_ns = 0
        self.wild_refusals: dict = {}
        self.sep_admits: dict = {}
        self.done = False
        self.bound_clk = math.ceil(AXI_TIMEOUT_NS / self.cfg.smu_clk_period_ns)

    # ------------------------------------------------------------------
    # Fence, sites and checks.
    # ------------------------------------------------------------------

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step = step
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(
        self,
        name: str,
        bound: int,
        unit: str,
        used: int | None,
        last: str,
        *,
        expired: bool = False,
        outcome: bool = False,
    ) -> None:
        site = self.sites.setdefault(
            name,
            {
                "bound": bound,
                "unit": unit,
                "used": None,
                "count": 0,
                "expired": 0,
                "last": last,
                "outcome": outcome,
            },
        )
        site["count"] += 1
        site["expired"] += int(expired)
        site["last"] = last
        if used is not None:
            site["used"] = max(site["used"] or 0, used)

    def _chk(
        self, sb, chk: str, inst: str, observed, expected, text: str, *, evidence: str
    ) -> None:
        if evidence != chk:
            raise AssertionError(f"{chk} graded under evidence {evidence}")
        drawn = self._drawn(inst)
        self._log(f"{chk} {inst}: {text}; {drawn} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {inst} {drawn}", observed, expected, evidence=evidence)

    def _drawn(self, inst: str) -> str:
        cell = self.cells[inst]
        w4, w8 = self.win[inst][1], self.win[inst][0]
        text = (
            f"drawn lo={cell['lo']} hi={cell['hi']} ab={cell['ab']} "
            f"w4=[0x{w4[0]:x},0x{w4[1]:x}] w8=[0x{w8[0]:x},0x{w8[1]:x}] prio_ch={cell['prio_ch']}"
        )
        if inst == SYS_IN:
            text += (
                f" user={cell['user']} src_class={cell['src_class']} prot={cell['prot']} "
                f"burst={cell['burst']}"
            )
        return text

    def _next_tag(self) -> int:
        self.tag += 1
        return self.tag

    def _count(self, inst: str, admitted: bool) -> None:
        self.verdicts[inst]["admitted" if admitted else "blocked"] += 1

    # ------------------------------------------------------------------
    # JTAG2AXI (SMC fabric bridge).
    # ------------------------------------------------------------------

    async def _j2a(self, write: bool, addr: int, data: int = 0, **kw) -> tuple[int, int]:
        tap = _ReadCounter(self.j2a_tap)
        if write:
            status, raw = await jtag2axi_single_write(
                tap, addr, data, poll_limit=J2A_POLL_LIMIT, **kw
            )
        else:
            status, raw = await jtag2axi_single_read(tap, addr, poll_limit=J2A_POLL_LIMIT, **kw)
        require_jtag_tdo_resolved(f"J2A @0x{addr:x}")
        expired = status == J2A_STATUS_BUSY
        last = f"@0x{addr:x} status={status}"
        self._site("j2a", J2A_POLL_LIMIT, "polls", tap.reads, last, expired=expired)
        if expired:
            raise AssertionError(f"TIMEOUT j2a {last} after {tap.reads} polls")
        self.step_access[self.step] += 1
        return status, int(raw)

    async def _j2a_ok(self, write: bool, addr: int, data: int = 0, **kw) -> int:
        status, raw = await self._j2a(write, addr, data, **kw)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A @0x{addr:x} status={status} want SUCCESS")
        return raw

    async def _wr32(self, addr: int, value: int) -> None:
        word = int(value) & 0xFFFF_FFFF
        packed, wstrb = (word << 32, 0xF0) if addr & 0x4 else (word, 0x0F)
        await self._j2a_ok(True, addr, packed, wstrb=wstrb, size=SMC_DBG_AXSIZE_4B)

    async def _rd32(self, addr: int) -> int:
        raw = await self._j2a_ok(False, addr, size=SMC_DBG_AXSIZE_4B)
        return (raw >> 32) & 0xFFFF_FFFF if addr & 0x4 else raw & 0xFFFF_FFFF

    # ------------------------------------------------------------------
    # SEP debug system bus.
    # ------------------------------------------------------------------

    async def _bus(self, addr: int, size: int, data: int | None = None) -> tuple[int, int]:
        """One system-bus access of 2**size bytes; returns (sberror, read data)."""
        self.step_access[self.step] += 1
        jtag = self.jtag
        sbcs = (size << SBACCESS_SHIFT) | SBCS_SBERROR_W1C
        if data is None:
            sbcs |= SBCS_SBREADONADDR
        await self._post(jtag, SBCS_ADDR, sbcs)
        if data is not None and size == SB_SIZE_DOUBLEWORD:
            await self._post(jtag, SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF)
        await self._post(jtag, SBADDRESS0_ADDR, addr)
        if data is not None:
            await self._post(jtag, SBDATA0_ADDR, data & 0xFFFF_FFFF)
        status = 0
        for used in range(1, SBA_POLLS + 1):
            status = await self._dmi(jtag, SBCS_ADDR, 0, DMI_OP_READ)
            if not status & SBCS_SBBUSY:
                break
        else:
            self._site(
                "sba_busy_poll",
                SBA_POLLS,
                "polls",
                SBA_POLLS + 1,
                f"EXPIRED sbcs=0x{status:08x}",
                expired=True,
            )
            raise AssertionError(f"system-bus 0x{addr:x}: sbbusy never cleared, sbcs=0x{status:x}")
        self._site("sba_busy_poll", SBA_POLLS, "polls", used, f"sbcs=0x{status:08x}")
        if status & SBCS_SBBUSYERROR:
            raise AssertionError(f"system-bus 0x{addr:x}: sbbusyerror")
        if (status >> SBACCESS_SHIFT) & 0x7 != size:
            raise AssertionError(f"system-bus 0x{addr:x}: sbcs=0x{status:08x} lost")
        err = (status >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err or data is not None:
            return err, 0
        value = await self._dmi(jtag, SBDATA0_ADDR, 0, DMI_OP_READ)
        if size == SB_SIZE_DOUBLEWORD:
            value |= (await self._dmi(jtag, SBDATA1_ADDR, 0, DMI_OP_READ)) << 32
        return 0, value & ((1 << (8 << size)) - 1)

    async def _bus_ok(self, addr: int, size: int, data: int | None = None) -> int:
        err, value = await self._bus(addr, size, data)
        if err:
            raise AssertionError(f"system-bus 0x{addr:x}: sberror={err}")
        return value

    async def _observe(self, mark: tuple[int, int], want_aw: int, want_ar: int) -> None:
        last = "no sample"
        for used in range(OBSERVE_BOUND_CYCLES + 1):
            aw, ar = self.tap.since(mark)
            last = f"aw={len(aw)} ar={len(ar)}"
            if len(aw) >= want_aw and len(ar) >= want_ar:
                self._site("responder_observe", OBSERVE_BOUND_CYCLES, "clk_smu", used, last)
                return
            await ClockCycles(self.clk, 1)
        self._site(
            "responder_observe",
            OBSERVE_BOUND_CYCLES,
            "clk_smu",
            OBSERVE_BOUND_CYCLES + 1,
            f"EXPIRED {last}",
            expired=True,
        )
        raise AssertionError(f"responder observation expired, last {last}")

    # ------------------------------------------------------------------
    # Entry registers.
    # ------------------------------------------------------------------

    def _reg_addr(self, inst: str, idx: int, reg: str) -> int:
        if inst == SEP_OUT:
            return _indexed_addr(_SEP_SYMS[reg], idx)
        return smc_indexed_addr(_SMC_SYMS[inst][reg], idx)

    async def _reg_write(self, inst: str, idx: int, reg: str, value: int) -> None:
        key = (inst, idx, reg)
        if self.regs.get(key) == value:
            return
        addr = self._reg_addr(inst, idx, reg)
        if inst == SEP_OUT:
            await self._bus_ok(addr, SB_SIZE_DOUBLEWORD, value)
        else:
            await self._j2a_ok(True, addr, value, size=SMC_DBG_AXSIZE_8B)
        self.regs[key] = value
        self._write_back(inst, idx)

    def _write_back(self, inst: str, idx: int) -> None:
        """index.adoc "Address Range Granule": hardware writes the widened values back into
        START_ADDR and END_ADDR when both land in the same granule of the entry's allow_burst."""
        reg = {r: self.regs.get((inst, idx, r), REG_RESET[r]) for r in REG_RESET}
        gran = GRANULE[1 if reg["config"] & _F_ALLOW_BURST else 0]
        if reg["start"] // gran != reg["end"] // gran:
            return
        start, end = reg["start"] - reg["start"] % gran, reg["end"] | (gran - 1)
        if (start, end) != (reg["start"], reg["end"]):
            self._log(
                f"{inst} entry {idx}: START 0x{reg['start']:x} and END 0x{reg['end']:x} share "
                f"one {gran}-byte granule; expected write-back 0x{start:x}..0x{end:x}"
            )
        self.regs[(inst, idx, "start")] = start
        self.regs[(inst, idx, "end")] = end

    async def _reg_read(self, inst: str, idx: int, reg: str) -> int:
        addr = self._reg_addr(inst, idx, reg)
        if inst == SEP_OUT:
            return await self._bus_ok(addr, SB_SIZE_DOUBLEWORD)
        return await self._j2a_ok(False, addr, size=SMC_DBG_AXSIZE_8B)

    async def _program(self, inst: str, idx: int, window=None, config: int | None = None) -> None:
        if window is not None:
            await self._reg_write(inst, idx, "start", window[0])
            await self._reg_write(inst, idx, "end", window[1])
        if config is not None:
            await self._reg_write(inst, idx, "config", config)

    async def _disable(self, inst: str, idx: int) -> None:
        current = self.regs.get((inst, idx, "config"), 0)
        await self._reg_write(inst, idx, "config", current & ~_F_ENTRY)

    async def _readback(self, inst: str, entries: tuple[int, ...]) -> tuple[dict, dict]:
        """Read START, END and FILTER_CONFIG of each entry."""
        observed, expected = {}, {}
        for idx in entries:
            for reg in ("start", "end", "config"):
                value = await self._reg_read(inst, idx, reg)
                mask = CFG_MASK if reg == "config" else ADDR_MASK
                observed[f"entry {idx} {reg}"] = hex(value & mask)
                expected[f"entry {idx} {reg}"] = hex(self.regs[(inst, idx, reg)] & mask)
        return observed, expected

    # ------------------------------------------------------------------
    # Probes: each returns (observed, expected) for the stated verdict.
    # ------------------------------------------------------------------

    async def _ext(self, write: bool, addr: int, payload_len: int, payload: bytes, **kw):
        name = "ext_axi"
        t0 = get_sim_time("ns")
        common = {
            "check_response": False,
            "timeout_ns": AXI_TIMEOUT_NS,
            "allow_timeout": True,
            **kw,
        }
        if write:
            result = await self.master.write_bytes_result(addr, payload, **common)
        else:
            result = await self.master.read_bytes_result(addr, payload_len, **common)
        if result.timed_out:
            self._site(
                name,
                self.bound_clk,
                "clk_smu",
                self.bound_clk + 1,
                f"EXPIRED @0x{addr:x}",
                expired=True,
            )
            raise AssertionError(f"TIMEOUT {name} @0x{addr:x} bound={AXI_TIMEOUT_NS}ns")
        used = math.ceil((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        self._site(name, self.bound_clk, "clk_smu", used, f"@0x{addr:x} resp={result.resp}")
        self.step_access[self.step] += 1
        return result

    async def _sys_probe(self, ch: str, addr: int, admitted: bool, *, beats: int = 1, **kw):
        cell = self.cells[SYS_IN]
        user = kw.pop("user", cell["user"])
        prot = kw.pop("prot", cell["prot"])
        nbytes = WORD_BYTES * beats
        extra = {"user": user, "prot": prot}
        if beats > 1:
            extra["size"] = BEAT_SIZE
        tag = self._next_tag()
        if ch == AW:
            payload = _burst_bytes(tag, nbytes)
            result = await self._ext(True, addr, nbytes, payload, **extra)
            observed = resp_name(result.resp)
            expected = OKAY if admitted else DECERR
            if admitted:
                self.spm[addr] = payload
        else:
            result = await self._ext(False, addr, nbytes, b"", **extra)
            resp = resp_name(result.resp)
            data = bytes(result.data_bytes)[:nbytes] if resp == OKAY else None
            observed = (resp, None if data is None else data.hex())
            if admitted:
                held = self.spm.get(addr)
                if held is None or len(held) != nbytes:
                    raise AssertionError(f"SYS_IN read @0x{addr:x} has no admitted write before it")
                expected = (OKAY, held.hex())
            else:
                expected = (DECERR, None)
        self._count(SYS_IN, admitted)
        return observed, expected

    def _cross_check_polarity(self, table: str, ns: int, tapped: dict[int, list[int]]) -> None:
        """The probe's AxPROT[1] at the egress tap agrees with the allow_ns the filter paired it
        with: the probe that left the filter carries AxPROT[1] == ns, the other left nothing
        (hw/ip/axi_filter/doc/index.adoc, the ``prot[1] == allow_ns`` match term)."""
        got = {k: tapped[k] for k in (0, 1)}
        want = {ns: [ns], 1 - ns: []}
        self.sb.expect_eq(
            f"CHK-FMATCH-TERMS {table} polarity probe: the probe the filter let out carries "
            f"AxPROT[1]={ns} at the egress tap and the probe it refused reached the tap with "
            f"nothing, so allow_ns={ns} is the initiator's AxPROT[1] and not an inverted term",
            got,
            want,
            evidence="CHK-FMATCH-TERMS",
        )

    async def _smc_probe(self, ch: str, addr: int, admitted: bool):
        mem = self.cfg.axi_out_mem
        tag = self._next_tag()
        before = self.tap.snapshot()
        if ch == AW:
            mem.write(addr, bytes([SENTINEL_BYTE]))
            byte = _pattern(tag, 1)
            status, _ = await self._j2a(
                True, addr, byte << (8 * (addr & 7)), wstrb=1 << (addr & 7), size=AXSIZE_BYTE
            )
            delta = tuple(a - b for a, b in zip(self.tap.snapshot(), before))
            observed = (status, delta, mem.read_int(addr, 1))
            expected = (
                (J2A_STATUS_SUCCESS, (1, 1, 1, 0, 0), byte)
                if admitted
                else (J2A_STATUS_DECERR, (0, 0, 0, 0, 0), SENTINEL_BYTE)
            )
        else:
            word = _pattern(tag, 8)
            mem.write_int(addr, word, 8)
            status, raw = await self._j2a(False, addr)
            delta = tuple(a - b for a, b in zip(self.tap.snapshot(), before))
            observed = (status, delta, raw if status == J2A_STATUS_SUCCESS else None)
            expected = (
                (J2A_STATUS_SUCCESS, (0, 0, 0, 1, 1), word)
                if admitted
                else (J2A_STATUS_DECERR, (0, 0, 0, 0, 0), None)
            )
        self._count(SMC_OUT, admitted)
        return observed, expected

    async def _sep_probe(self, ch: str, addr: int, admitted: bool):
        mem = self.cfg.axi_out_mem
        tag = self._next_tag()
        value = _pattern(tag, WORD_BYTES)
        mark = self.tap.mark()
        if ch == AW:
            mem.write_int(addr, _sentinel(WORD_BYTES), WORD_BYTES)
            err, _ = await self._bus(addr, SB_SIZE_WORD, value)
            if err == 0:
                await self._observe(mark, 1, 0)
            aw, ar = self.tap.since(mark)
            held = mem.read_int(addr, WORD_BYTES)
            observed = (err != 0, [p[0] for p in aw], [p[0] for p in ar], held)
            expected = (
                (False, [addr], [], value) if admitted else (True, [], [], _sentinel(WORD_BYTES))
            )
        else:
            mem.write_int(addr, value, WORD_BYTES)
            err, data = await self._bus(addr, SB_SIZE_WORD)
            if err == 0:
                await self._observe(mark, 0, 1)
            aw, ar = self.tap.since(mark)
            observed = (err != 0, [p[0] for p in aw], [p[0] for p in ar], data)
            expected = (False, [], [addr], value) if admitted else (True, [], [], 0)
        if err:
            self._log(f"OBSERVATION SEP_OUT sberror={err} @0x{addr:x} (code measured only)")
        self._count(SEP_OUT, admitted)
        return observed, expected

    async def _probe(self, inst: str, ch: str, addr: int, admitted: bool, **kw):
        if inst == SYS_IN:
            return await self._sys_probe(ch, addr, admitted, **kw)
        if inst == SMC_OUT:
            return await self._smc_probe(ch, addr, admitted)
        return await self._sep_probe(ch, addr, admitted)

    def _edges(self, inst: str, ab: int, beats: int = 1) -> dict[str, int]:
        """Low-edge and high-edge probe addresses of the window of granule ``ab``."""
        start, end = self.win[inst][ab]
        width = {SYS_IN: WORD_BYTES * beats, SMC_OUT: 8, SEP_OUT: WORD_BYTES}[inst]
        return {"low edge": start, "high edge": end + 1 - width}

    async def _rw(self, inst: str, addr: int, admit: dict[str, bool], **kw) -> tuple[dict, dict]:
        """AW then AR at one address with the verdict of each channel."""
        obs, exp = {}, {}
        for ch in (AW, AR):
            obs[ch], exp[ch] = await self._probe(inst, ch, addr, admit[ch], **kw)
        return obs, exp

    # ------------------------------------------------------------------
    # Cells shared by the three instances.
    # ------------------------------------------------------------------

    def _base(self, inst: str, ab: int, *, read: int = 1, write: int = 1, **kw) -> int:
        cell = self.cells[inst]
        fields = {"allow_ns": self.ns[inst], "src_id": 0, "allow_burst": ab}
        if inst == SYS_IN and cell["src_class"] == "equal":
            fields["src_id"] = cell["user"]
        fields.update(kw)
        return _config(read=read, write=write, **fields)

    async def _admit(self, sb, inst: str) -> None:
        cell = self.cells[inst]
        ab, lo, hi = cell["ab"], cell["lo"], cell["hi"]
        window = self.win[inst][ab]
        beats = BURST_BEATS if inst == SYS_IN and cell["burst"] else 1
        await self._program(inst, hi, window, self._base(inst, ab, read=0, write=0, src_id=0))
        await self._program(inst, lo, window, self._base(inst, ab))
        obs, exp = {}, {}
        for label, addr in self._edges(inst, ab, beats).items():
            o, e = await self._rw(inst, addr, {AW: True, AR: True}, beats=beats)
            obs[label], exp[label] = o, e
        rb_obs, rb_exp = await self._readback(inst, (lo, hi))
        self._chk(
            sb,
            "CHK-FMATCH-ADMIT",
            inst,
            (obs, rb_obs),
            (exp, rb_exp),
            f"entry {lo} permit with every term satisfied over entry {hi} deny on one window: "
            f"AW then AR at both edges admitted ({beats} beat(s)), the read returns the written "
            "bytes, and every programmed register reads back the value written or, where "
            "START and END shared one granule, the granule edges the write-back sets",
            evidence="CHK-FMATCH-ADMIT",
        )
        if inst == SEP_OUT:
            self.sep_admits["admit"] = (obs, exp)

    async def _term_cell(self, inst: str, name: str, base_window, base_cfg, brk, addr, **kw):
        """Break one term alone, probe, restore, probe; the verdicts follow the policy."""
        lo = self.cells[inst]["lo"]
        await self._program(inst, lo, base_window, base_cfg)
        blocked = UNMATCHED_BLOCKED[inst]
        if inst == SYS_IN:
            chans = (AW, AR)
        else:
            chans = (self.cells[inst]["term_ch"].get(name, AW),)
        await brk()
        obs, exp = {"break": {}, "restore": {}}, {"break": {}, "restore": {}}
        for ch in chans:
            o, e = await self._probe(inst, ch, addr, not blocked, **kw)
            obs["break"][ch], exp["break"][ch] = o, e
        await self._program(inst, lo, base_window, base_cfg)
        for ch in chans:
            o, e = await self._probe(inst, ch, addr, blocked, **kw)
            obs["restore"][ch], exp["restore"][ch] = o, e
        return obs, exp

    async def _terms(self, sb, inst: str) -> None:
        cell = self.cells[inst]
        lo, hi, ab = cell["lo"], cell["hi"], cell["ab"]
        await self._disable(inst, hi)
        permit = 0 if inst == SMC_OUT else 1
        obs, exp = {}, {}

        def base(gran: int, **kw) -> int:
            return self._base(inst, gran, read=permit, write=permit, **kw)

        async def cfg(value: int) -> None:
            await self._program(inst, lo, config=value)

        async def rng_to(window) -> None:
            await self._program(inst, lo, window)

        w = self.win[inst]
        drawn_edges = self._edges(inst, ab)
        cells = [
            (
                "entry_enabled",
                w[ab],
                base(ab),
                lambda: cfg(base(ab, enabled=0)),
                drawn_edges["low edge"],
                {},
            )
        ]
        for gran, tag in ((1, "4k"), (0, "8b")):
            edges = self._edges(inst, gran)
            g = GRANULE[gran]
            up = (w[gran][0] + g, w[gran][1] + g)
            down = (w[gran][0] - g, w[gran][1] - g)
            cells.append(
                (
                    f"range_up_{tag}",
                    w[gran],
                    base(gran),
                    lambda r=up: rng_to(r),
                    edges["low edge"],
                    {},
                )
            )
            cells.append(
                (
                    f"range_down_{tag}",
                    w[gran],
                    base(gran),
                    lambda r=down: rng_to(r),
                    edges["high edge"],
                    {},
                )
            )
        if inst == SYS_IN:
            ns = self.ns[inst]
            cells.append(
                (
                    "allow_ns",
                    w[ab],
                    base(ab),
                    lambda: cfg(base(ab, allow_ns=ns ^ 1)),
                    drawn_edges["low edge"],
                    {},
                )
            )
            cells.append(
                (
                    "src_id",
                    w[ab],
                    base(ab),
                    lambda: cfg(base(ab, src_id=cell["src_break"])),
                    drawn_edges["low edge"],
                    {},
                )
            )
            burst_edges = self._edges(inst, 1, BURST_BEATS)
            cells.append(
                (
                    "allow_burst",
                    w[1],
                    base(1),
                    lambda: cfg(base(1, allow_burst=0)),
                    burst_edges["low edge"],
                    {"beats": BURST_BEATS},
                )
            )
        for name, window, base_cfg, brk, addr, kw in cells:
            obs[name], exp[name] = await self._term_cell(
                inst, name, window, base_cfg, brk, addr, **kw
            )
        if inst == SMC_OUT:
            self.wild_refusals["bridge restore cells"] = (
                {k: v["restore"] for k, v in obs.items()},
                {k: v["restore"] for k, v in exp.items()},
            )
        if inst == SEP_OUT:
            self.sep_admits["term restore cells"] = (
                {k: v["restore"] for k, v in obs.items()},
                {k: v["restore"] for k, v in exp.items()},
            )
        policy = "blocked" if UNMATCHED_BLOCKED[inst] else "permitted"
        verdict = "refuses" if UNMATCHED_BLOCKED[inst] else "passes"
        self._chk(
            sb,
            "CHK-FMATCH-TERMS",
            inst,
            obs,
            exp,
            f"entry {lo} alone ({'permit' if permit else 'deny'}); each term broken alone makes "
            f"the access unmatched, which the instance's {policy} policy {verdict}, and the "
            f"restored term decides it again; cells {sorted(obs)}",
            evidence="CHK-FMATCH-TERMS",
        )
        if inst != SYS_IN:
            await self._measured(inst)

    async def _measured(self, inst: str) -> None:
        """The refusing allow_ns value and a non-zero src_id: logged, not compared."""
        cell = self.cells[inst]
        lo, ab = cell["lo"], cell["ab"]
        permit = 0 if inst == SMC_OUT else 1
        addr = self._edges(inst, ab)["low edge"]
        out = {}
        for label, kw in (
            ("allow_ns other value", {"allow_ns": self.ns[inst] ^ 1}),
            (f"src_id {cell['meas_src_id']}", {"src_id": cell["meas_src_id"]}),
        ):
            cfg = self._base(inst, ab, read=permit, write=permit, **kw)
            await self._program(inst, lo, self.win[inst][ab], cfg)
            o, _ = await self._probe(inst, AW, addr, True)
            self.verdicts[inst]["admitted"] -= 1
            out[label] = o
        await self._program(inst, lo, config=self._base(inst, ab, read=permit, write=permit))
        self._log(f"OBSERVATION {inst} measured only (no document states the outcome): {out}")

    async def _perm(self, sb, inst: str) -> None:
        cell = self.cells[inst]
        lo, ab = cell["lo"], cell["ab"]
        addr = self._edges(inst, ab)["low edge"]
        obs, exp = {}, {}
        for read, write in ((0, 1), (1, 0)):
            await self._program(
                inst, lo, self.win[inst][ab], self._base(inst, ab, read=read, write=write)
            )
            key = f"read_allowed={read} write_allowed={write}"
            obs[key], exp[key] = await self._rw(inst, addr, {AW: bool(write), AR: bool(read)})
        self._chk(
            sb,
            "CHK-FMATCH-PERM",
            inst,
            obs,
            exp,
            f"entry {lo} alone: read_allowed 0 blocks AR and admits AW, write_allowed 0 blocks AW "
            "and admits AR (on SYS_IN the AR then returns the bytes the admitted AW wrote)",
            evidence="CHK-FMATCH-PERM",
        )

    async def _priority(self, sb, inst: str) -> None:
        cell = self.cells[inst]
        lo, hi, ab, ch = cell["lo"], cell["hi"], cell["ab"], cell["prio_ch"]
        window = self.win[inst][ab]
        addr = self._edges(inst, ab)["low edge"]
        deny = self._base(inst, ab, read=int(ch != AR), write=int(ch != AW))
        permit = self._base(inst, ab)
        obs, exp = {}, {}
        for order in ("lower first", "higher first"):
            await self._disable(inst, lo)
            await self._disable(inst, hi)
            pairs = ((lo, deny), (hi, permit))
            for idx, value in pairs if order == "lower first" else pairs[::-1]:
                await self._program(inst, idx, window, value)
            obs[order], exp[order] = await self._rw(
                inst, addr, {ch: False, (AW if ch == AR else AR): True}
            )
        self._chk(
            sb,
            "CHK-FMATCH-PRIORITY",
            inst,
            obs,
            exp,
            f"entry {lo} with the {ch} permission clear over entry {hi} permitting both on one "
            f"window, programmed in both orders: {ch} is blocked by the lower entry and the other "
            "channel is admitted",
            evidence="CHK-FMATCH-PRIORITY",
        )
        await self._disable(inst, hi)

    # ------------------------------------------------------------------
    # Steps.
    # ------------------------------------------------------------------

    async def _s1(self) -> None:
        dut = self.dut
        self.j2a_tap = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.j2a_tap.reset_tap()
        await self.j2a_tap.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.j2a_tap.step_tms(0)
        idcode = await self.j2a_tap.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate = dut.tb_smc_jtag2axi_security_disable.value
        if not gate.is_resolvable or int(gate) & 1:
            raise AssertionError(f"SMC J2A gated: security_disable={gate}")
        await self._j2a_ok(
            True,
            SMC_APERTURE_GLOBAL_BASE_REG,
            SMC_APERTURE_LOCAL_BASE,
            wstrb=0x0F,
            size=SMC_DBG_AXSIZE_4B,
        )
        rb = await self._j2a_ok(False, SMC_APERTURE_GLOBAL_BASE_REG, size=SMC_DBG_AXSIZE_4B)
        if rb & 0xFFFF_FFFF != SMC_APERTURE_LOCAL_BASE:
            raise AssertionError(f"SMC GLOBAL_BASE readback 0x{rb:x}")
        self.master = await make_smu_axi_master(dut, self.clk, smc_primary_reset(dut))
        self.tap = _EgressTap(dut)
        sys_cell = self.cells[SYS_IN]
        self.ns[SYS_IN] = (sys_cell["prot"] >> 1) & 1

    async def _sys_wildcard(self, sb) -> None:
        cell = self.cells[SYS_IN]
        lo, ab = cell["lo"], cell["ab"]
        addr = self._edges(SYS_IN, ab)["low edge"]
        await self._program(SYS_IN, lo, self.win[SYS_IN][ab], self._base(SYS_IN, ab, src_id=0))
        obs, exp = {}, {}
        for user in (*PINNED_WILDCARD_USERS, *cell["wild_users"]):
            obs[f"user={user}"], exp[f"user={user}"] = await self._rw(
                SYS_IN, addr, {AW: True, AR: True}, user=user
            )
        self._chk(
            sb,
            "CHK-FMATCH-WILDCARD",
            SYS_IN,
            obs,
            exp,
            f"src_id 0 at entry {lo} admits AxUSER[3:0] {PINNED_WILDCARD_USERS} (pinned) and "
            f"{cell['wild_users']} (drawn) on AW and AR, after src_id {cell['src_break']} "
            "refused the drawn source ID in the term cells",
            evidence="CHK-FMATCH-WILDCARD",
        )

    async def _dma_copy(self, src: int, dst: int, bound: int, site: str, outcome: bool):
        for addr, value in (
            (DMA_CONFIG, DMA_CONFIG_ENABLE_ND),
            (DMA_DST_LO, dst),
            (DMA_SRC_LO, src),
            (DMA_LEN_LO, COPY_LENGTH),
            (DMA_REPS_LO, DMA_REPETITIONS),
        ):
            await self._wr32(addr, value)
        mark, counts = self.tap.mark(), self.tap.snapshot()
        start_id = await self._rd32(DMA_NEXT_ID_0)
        done, used = None, 0
        for used in range(1, bound + 1):
            await ClockCycles(self.clk, DMA_POLL_CYCLES)
            done = await self._rd32(DMA_DONE_0)
            if done == start_id:
                break
        completed = done == start_id
        last = f"id={start_id} done={done} polls={used}"
        self._site(
            site,
            bound,
            "polls",
            used,
            last if completed else f"EXPIRED {last}",
            expired=not completed,
            outcome=outcome,
        )
        if not completed and not outcome:
            raise AssertionError(f"TIMEOUT {site} {last}")
        aw, ar = self.tap.since(mark)
        delta = tuple(a - b for a, b in zip(self.tap.snapshot(), counts))
        return completed, aw, ar, delta

    async def _smc_setup(self) -> None:
        mem = self.cfg.axi_out_mem
        src = bytes(_burst_bytes(0x700, COPY_LENGTH))
        mem.write(DMA_SRC_PAGE, src)
        mem.write(DMA_DST_PAGE, bytes(COPY_LENGTH))
        completed, aw, ar, _ = await self._dma_copy(
            DMA_SRC_PAGE, DMA_DST_PAGE, DMA_DONE_POLLS, "dma_done", False
        )
        aw_ns = sorted({(p[3] >> 1) & 1 for p in aw})
        ar_ns = sorted({(p[3] >> 1) & 1 for p in ar})
        aw_len = max((p[1] for p in aw), default=0)
        self._log(
            f"OBSERVATION SMC_OUT reset-entry iDMA copy AxPROT[1] aw={aw_ns} ar={ar_ns} "
            f"max AWLEN={aw_len} dst_ok={mem.read(DMA_DST_PAGE, COPY_LENGTH) == src} (measured)"
        )
        if not completed or len(aw_ns) != 1 or aw_len == 0:
            raise AssertionError(
                f"iDMA reset copy: completed={completed} AW AxPROT[1]={aw_ns} AWLEN={aw_len}; "
                "the allow_burst cell needs one AxPROT[1] value and a multi-beat AW"
            )
        self.idma_ns = aw_ns[0]
        cell = self.cells[SMC_OUT]
        window = self.win[SMC_OUT][1]
        addr = self._edges(SMC_OUT, 1)["low edge"]
        refused, tapped = {}, {}
        for ns in (0, 1):
            await self._program(SMC_OUT, cell["lo"], window, _config(read=0, write=0, allow_ns=ns))
            mark = self.tap.mark()
            o, _ = await self._smc_probe(AW, addr, True)
            self.verdicts[SMC_OUT]["admitted"] -= 1
            refused[ns] = o[0] == J2A_STATUS_DECERR
            aw, _ar = self.tap.since(mark)
            tapped[ns] = sorted({(p[3] >> 1) & 1 for p in aw})
        self._log(
            f"OBSERVATION SMC_OUT bridge polarity refused={refused}; AxPROT[1] of the probe at "
            f"the egress tap per allow_ns={tapped}"
        )
        if sum(refused.values()) != 1:
            raise AssertionError(f"SMC_OUT polarity probe: refused={refused}, want exactly one")
        self.ns[SMC_OUT] = 0 if refused[0] else 1
        self._cross_check_polarity(SMC_OUT, self.ns[SMC_OUT], tapped)
        await self._disable(SMC_OUT, cell["lo"])

    async def _smc_idma(self, sb) -> None:
        cell = self.cells[SMC_OUT]
        lo = cell["lo"]
        mem = self.cfg.axi_out_mem
        page = (DMA_DST_PAGE, DMA_DST_PAGE + GRANULE_4K - 1)
        src = bytes(_burst_bytes(0x710, COPY_LENGTH))
        d1 = bytes(_burst_bytes(0x720, COPY_LENGTH))
        mem.write(DMA_SRC_PAGE, src)
        obs, exp = {}, {}
        for label, ab in (("break allow_burst 0", 0), ("restore allow_burst 1", 1)):
            cfg = _config(read=1, write=0, allow_ns=self.idma_ns, allow_burst=ab)
            await self._program(SMC_OUT, lo, page, cfg)
            mem.write(DMA_DST_PAGE, d1)
            refused = bool(ab)
            # The refused copy is watched over the admitted copy's DONE window before the tap and
            # the destination bytes are read.
            completed, aw, ar, delta = await self._dma_copy(
                DMA_SRC_PAGE,
                DMA_DST_PAGE,
                DMA_DONE_POLLS,
                "dma_done_refused" if refused else "dma_done",
                refused,
            )
            dst_aw = sum(1 for p in aw if page[0] <= p[0] <= page[1])
            src_ar = sum(1 for p in ar if DMA_SRC_PAGE <= p[0] < DMA_SRC_PAGE + GRANULE_4K)
            status = await self._rd32(DMA_STATUS_0)
            self._log(
                f"OBSERVATION SMC_OUT iDMA {label} completed={completed} status=0x{status:x} "
                f"delta(aw,w,b,ar,r)={delta} (status and completion measured only)"
            )
            held = mem.read(DMA_DST_PAGE, COPY_LENGTH).hex()
            obs[label] = (dst_aw > 0, src_ar > 0, held)
            exp[label] = (not refused, True, (d1 if refused else src).hex())
            self._count(SMC_OUT, not refused)
        self.wild_refusals["iDMA restore cell"] = (
            obs["restore allow_burst 1"],
            exp["restore allow_burst 1"],
        )
        self._chk(
            sb,
            "CHK-FMATCH-TERMS",
            SMC_OUT,
            obs,
            exp,
            f"entry {lo} denying writes over the iDMA destination page with allow_ns "
            f"{self.idma_ns} (the copy's AxPROT[1]): allow_burst 0 leaves the multi-beat copy "
            "unmatched and it lands; allow_burst 1 matches it and no AW of the copy reaches the "
            "destination page, which keeps its bytes",
            evidence="CHK-FMATCH-TERMS",
        )
        self._chk(
            sb,
            "CHK-FMATCH-WILDCARD",
            SMC_OUT,
            self._wild_obs(),
            self._wild_exp(),
            "src_id 0 deny entries match the bridge (the restore cells refuse) and the iDMA copy "
            "(the restored copy is refused); the master source IDs are not stated, src_id 0 "
            "matches them",
            evidence="CHK-FMATCH-WILDCARD",
        )

    def _wild_obs(self):
        return {k: v[0] for k, v in self.wild_refusals.items()}

    def _wild_exp(self):
        return {k: v[1] for k, v in self.wild_refusals.items()}

    async def _sep_setup(self) -> None:
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        if not (self.s1_ok and self.s2_ok and self.s3_ok):
            raise AssertionError("SEP debug module bring-up incomplete")
        cell = self.cells[SEP_OUT]
        window = self.win[SEP_OUT][1]
        addr = self._edges(SEP_OUT, 1)["low edge"]
        admitted, tapped = {}, {}
        for ns in (0, 1):
            await self._program(SEP_OUT, cell["lo"], window, _config(read=1, write=1, allow_ns=ns))
            mark = self.tap.mark()
            o, _ = await self._sep_probe(AW, addr, True)
            self.verdicts[SEP_OUT]["admitted"] -= 1
            admitted[ns] = not o[0]
            aw, _ar = self.tap.since(mark)
            tapped[ns] = sorted({(p[3] >> 1) & 1 for p in aw})
        self._log(
            f"OBSERVATION SEP_OUT system-bus polarity admitted={admitted}; AxPROT[1] of the probe "
            f"at the egress tap per allow_ns={tapped}"
        )
        if sum(admitted.values()) != 1:
            raise AssertionError(f"SEP_OUT polarity probe: admitted={admitted}, want exactly one")
        self.ns[SEP_OUT] = 0 if admitted[0] else 1
        self._cross_check_polarity(SEP_OUT, self.ns[SEP_OUT], tapped)
        await self._disable(SEP_OUT, cell["lo"])

    def _timeout_paths(self, sb) -> None:
        for name, site in sorted(self.sites.items()):
            state = "EXPIRED" if site["expired"] else "ok"
            note = " (expiry is the measured outcome)" if site["outcome"] else ""
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} "
                f"most used={site['used']} {site['unit']} count={site['count']} {state}{note} "
                f"last={site['last']}"
            )
        unexpected = [n for n, s in self.sites.items() if s["expired"] and not s["outcome"]]
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] and s["used"] is not None for s in self.sites.values())
        self._log(f"CHK-TIMEOUT-PATHS: sites={sorted(self.sites)} unexpected={unexpected}")
        sb.expect_eq(
            "CHK-TIMEOUT-PATHS bounded waits, labels, uses and last states",
            (unexpected, finite, has_last, sorted(self.sites)),
            ([], True, True, sorted(EXPECTED_SITES)),
            evidence="CHK-TIMEOUT-PATHS",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        drawn = " ".join(f"{inst}={self.cells[inst]}" for inst in INSTANCES)
        self._log(f"SEED: RANDOM_SEED={self.seed} drawn {drawn}")
        await self.cfg.reset_done.wait()
        await self._mark("S1", "SETUP: TAP, JTAG2AXI gate, SMC aperture alias, master, tap")
        try:
            await self._s1()
            await self._mark("S2", "SYS_IN admit and register read-back")
            await self._admit(sb, SYS_IN)
            await self._mark("S3", "SYS_IN term breaks")
            await self._terms(sb, SYS_IN)
            await self._mark("S4", "SYS_IN permission, priority, wildcard")
            await self._perm(sb, SYS_IN)
            await self._priority(sb, SYS_IN)
            await self._sys_wildcard(sb)
            await self._mark("S5", "SMC_OUT reset-entry iDMA copy and bridge polarity")
            await self._smc_setup()
            await self._mark("S6", "SMC_OUT admit and register read-back")
            await self._admit(sb, SMC_OUT)
            await self._mark("S7", "SMC_OUT term breaks and measured cells")
            await self._terms(sb, SMC_OUT)
            await self._mark("S8", "SMC_OUT permission and priority")
            await self._perm(sb, SMC_OUT)
            await self._priority(sb, SMC_OUT)
            await self._mark("S9", "SMC_OUT iDMA allow_burst cell and wildcard")
            await self._smc_idma(sb)
            await self._mark("S10", "SEP_OUT debug bring-up and system-bus polarity")
            await self._sep_setup()
            await self._mark("S11", "SEP_OUT admit and register read-back")
            await self._admit(sb, SEP_OUT)
            await self._mark("S12", "SEP_OUT term breaks and measured cells")
            await self._terms(sb, SEP_OUT)
            await self._mark("S13", "SEP_OUT permission, priority, wildcard")
            await self._perm(sb, SEP_OUT)
            await self._priority(sb, SEP_OUT)
            self._chk(
                sb,
                "CHK-FMATCH-WILDCARD",
                SEP_OUT,
                {k: v[0] for k, v in self.sep_admits.items()},
                {k: v[1] for k, v in self.sep_admits.items()},
                "src_id 0 entries admit the system bus in the admit and term-restore cells; the "
                "master source ID is not stated, src_id 0 matches it",
                evidence="CHK-FMATCH-WILDCARD",
            )
            await self._mark("S14", "TIMEOUT: bounded waits and last state")
            self._timeout_paths(sb)
        finally:
            if self.tap is not None:
                self.tap.stop()
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = [self.step_ts[k] for k in order]
        every_step = all(self.step_access[s] > 0 for s in ACCESS_STEPS)
        both = {
            inst: (self.verdicts[inst]["admitted"] > 0, self.verdicts[inst]["blocked"] > 0)
            for inst in INSTANCES
        }
        fence = "<".join(f"{k}@{t:.0f}" for k, t in zip(order, stamps))
        self._log(f"OBSERVATION step fence {fence} (logged, not compared)")
        self._log(
            f"CHK-NONVAC: accesses {self.step_access}; verdicts "
            f"{ {i: dict(v) for i, v in self.verdicts.items()} }; seed {self.seed}"
        )
        sb.expect_eq(
            f"CHK-NONVAC accesses in S2..S13, an admitted and a blocked access per instance, "
            f"seed {self.seed}",
            (every_step, both),
            (True, {inst: (True, True) for inst in INSTANCES}),
            evidence="CHK-NONVAC",
        )
        self.done = True
