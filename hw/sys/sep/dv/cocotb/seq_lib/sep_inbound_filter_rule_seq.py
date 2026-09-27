# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Inbound-filter per-entry RULE stimulus.

With the SEP inbound filter ACTIVE (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs inbound FILTER_CONFIG allow-entries, then the EXTERNAL
SMN master (m_axi, the only path through u_inbound_filter) probes them:
  * allowed address (covered by the entry, read_allowed/write_allowed set, src_id
    match) -> the access traverses the filter + identity global->local remap
    (smc_global_base=0) and reaches the SEP-local CSR -> OKAY + exact value;
  * any other address (block-by-default) -> the filter's err-slave ->
    DECERR, and the read data is not the value staged at that address;
  * clearing read_allowed/write_allowed flips the matched read/write to DECERR.

This stays sep_debug=0 and proves PER-ENTRY rule enforcement (vs the global
sep_debug skip gate). The filter CSR layout is defined in sep_fabric_csr_bank_seq.
SepInboundFilterMatrixCfg is the single source of truth for the walked cells
(entry x window x R/W-allow x src-id class).

FILTER_CONFIG.src_id=0 is match-all (`filter_ctrl.rdl` src_id wildcard;
`hw/ip/axi_filter/doc/index.adoc`). A non-zero src_id matches only the
external master's ar/awuser[3:0]. allow_ns=1 matches the master's
NONSECURE prot.

FILTER_CONFIG.allow_burst (bit 24) is walked on both filter instances
(AR and AW). A 2-beat INCR (AxLEN=1) makes traffic_filter.sv pass_burst
depend on the bit. The burst deny/allow window spans two 4 KB pages so
the wrap same-page widen does not fire there.

SepInboundFilterWidenCfg covers the widen itself: with allow_burst=1 and
START/END in one 4 KB page, axi_filter_wrap.sv rewrites the window to that
whole page and traffic_filter.sv compares only addr[AddrWidth-1:12], so the
grant is the page, not the programmed range. FILTER_CONFIG.locked (bit 63)
is write-once per fabric.adoc, so the field must not change once set. That
document does not say how a write to a locked entry completes; SEP refuses it
with BRESP=SLVERR, steering AW/W to a separate AXI-Lite error slave, so the
frozen allow_burst keeps governing the granule. The held field is the
specified contract, the SLVERR is SEP's choice of completion code.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import INBOUND_FILTER_CTRL_0, SEP_CPU_CTRL, indexed_block_count, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_BASE,
    AP_BASE,
    DBW_RO_VAL,
    F_ALLOW_BURST,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_SRC_ID_LSB,
    F_WRITE_ALLOWED,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    OUTFILT_BASE,
    STEE_BASE,
)
from seq_lib.sep_scratch_reset_seq import (
    SCRATCH_COLD_0,
    SCRATCH_N,
    SCRATCH_STRIDE,
    SCRATCH_WARM_0,
)

# Same-page allow_burst=1 rewrites START down and END up to the 4 KB page
# (hw/ip/axi_filter/doc/index.adoc). The allow_burst=0 8-byte
# readback model is sep_reg_bit_bash_seq.inbound_addr_expected().

# Allowed target: a pure-RW scratch CSR (SEP_SW_DEBUG @ sep_cpu_ctrl+0x178) in the
# system_csr region the smn_inbound xbar reaches post-filter. Staged with a distinctive
# value by the CPU-LSU first, so the external read value-check proves the path reached
# the real CSR (not a dummy OKAY). Blocked addr = a different CSR outside the window.
TARGET_ADDR = sym("SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR")
TARGET_VALUE = 0xC0DE_F00D
WINDOW_B_ADDR = SCRATCH_COLD_0
WINDOW_B_VALUE = 0xA11C_BEEF
BLOCKED_ADDR = sym("SEP_CPU_CTRL_CLOCK_GATE_CTRL_REG_ADDR")
RESP_OKAY = 0
RESP_SLVERR = 2
# AMBA AXI4-Lite encodings (IHI 0022): OKAY=0, SLVERR=2, DECERR=3.
RESP_DECERR = 3


# Entry count from the generated export, not a literal: the bank is an RDL
# array (`inbound_filter_ctrl[16]`), and a sequence that carries its own number
# goes stale the moment the array changes. disable_all() must clear every entry
# or a leftover allow window survives a walk that assumes it cleared them.
INFILT_N_ENTRIES = indexed_block_count("INBOUND_FILTER_CTRL")
WALK_ENTRIES = (0, 7)
ALLOW_MODES = (("rw", True, True), ("r", True, False), ("w", False, True))
# Non-zero FILTER_CONFIG.src_id and a distinct AXI user[3:0] for the mismatch
# cell. 0x5 is the CSR-bank RW pattern; 0xA is a legal 4-bit non-equal.
SRC_ID_MATCH = 0x5
SRC_ID_MISMATCH_USER = 0xA
SRC_ID_USER_MASK = 0xF
# AXI AxBURST INCR. A 2-beat 4-byte transfer (length=8, size=2) makes
# AxLEN=1 so traffic_filter.sv pass_burst is not vacuously true.
AXI_BURST_INCR = 1
BURST_BYTES = 8
# The burst deny/allow checkers isolate pass_burst from the granule rewrite: their
# window already spans two 4 KB pages, so the same-page widen does not fire there.
# SepInboundFilterWidenCfg owns the widen.
BURST_ALLOW_SPAN = 0x2000

# --- same-page 4 KB widen -----------------------------------------------------
# axi_filter_wrap.sv rewrites an allow_burst=1 window whose START and END share a
# 4 KB page to that whole page, and traffic_filter.sv then compares only
# addr[AddrWidth-1:12]. memory_map.adoc packs distinct blocks of the SEP System
# aperture at that same 4 KB pitch -- DMA CSR 0x1080_0000, WDT 0x1080_1000, the
# dual scratch banks 0x1080_2000 -- so a grant that crossed the page edge would
# reach a neighbouring block.
PAGE_SHIFT = 12
PAGE_SIZE = 1 << PAGE_SHIFT
GRANULE_BYTES = 1 << DBW_RO_VAL
# The dual scratch banks are the widen page: both banks are plain RW storage, so
# every probe lands on a real register and an OKAY/DECERR split can only come
# from the filter, never from an address-decode hole.
WIDEN_PAGE_BASE = SCRATCH_COLD_0 & ~(PAGE_SIZE - 1)
# Read probes in the WDT page, one page below the scratch page. The boundary is
# proven in both directions with these two pages, so every probe address is one
# the external master demonstrably reaches when its own page is granted.
WIDEN_ADJ_BELOW = (
    sym("WDT_TIMER_WKUP_THOLD_LO_REG_ADDR"),
    sym("WDT_TIMER_WDOG_BARK_THOLD_REG_ADDR"),
    sym("WDT_TIMER_WDOG_BITE_THOLD_REG_ADDR"),
)
# The last table entry: the write-once lock is sticky until reset, so it must not
# land on an entry the matrix or burst walk reprograms.
WIDEN_ENTRY = INFILT_N_ENTRIES - 1
FILTER_LOCKED_HI_BIT = INBOUND_FILTER_CTRL_0.field_lsb("FILTER_CONFIG", "locked") - 32


class SepInboundFilterWidenCfg:
    """Same-page allow_burst=1 window plus the probes that measure the widen.

    ``window_addr..window_end`` is one 8-byte granule inside the scratch page, so
    the wrap widens it to ``page_base..page_base+0xFFF``. The probes are chosen so
    each one proves a distinct contract:

      * ``window_addr`` -- inside the programmed range: the positive control.
      * ``in_page_addrs`` -- same 4 KB page, OUTSIDE the programmed range (cold
        scratch 0 and a warm scratch register): the widen, observed.
      * ``adj_addr`` -- a register in the page below (WDT): the grant must not
        reach it, and it must answer once the WDT page is the granted one.

    The seed picks which scratch register the window sits on, which warm register
    the out-of-window probe uses, which WDT register the adjacent probe uses, and
    the staged data words. Every probe runs on every seed.
    """

    def __init__(
        self, *, window_idx: int, warm_idx: int, below_addr: int, values: list[int]
    ) -> None:
        self.entry = WIDEN_ENTRY
        self.window_idx = window_idx
        self.window_addr = SCRATCH_COLD_0 + window_idx * SCRATCH_STRIDE
        self.window_end = self.window_addr + GRANULE_BYTES - 1
        self.page_base = WIDEN_PAGE_BASE
        self.page_end = WIDEN_PAGE_BASE + PAGE_SIZE - 1
        self.in_page_addrs = [SCRATCH_COLD_0, SCRATCH_WARM_0 + warm_idx * SCRATCH_STRIDE]
        self.adj_addr = below_addr
        # window_addr first, then the two out-of-window in-page probes.
        self.values = list(values)

    @classmethod
    def from_rng(cls, rng: SepSeededRng) -> "SepInboundFilterWidenCfg":
        # Cold scratch 0 stays outside the programmed window on every seed so it
        # is always a valid widen probe.
        window_idx = rng.randrange(1, SCRATCH_N)
        warm_idx = rng.randrange(SCRATCH_N)
        below_addr = rng.choice(list(WIDEN_ADJ_BELOW))
        vals: list[int] = []
        for i in range(3):
            v = rng.getrandbits(32) or (0x5EED_0000 | i)
            while v in vals:
                v = (v + 1) & 0xFFFF_FFFF
            vals.append(v)
        return cls(window_idx=window_idx, warm_idx=warm_idx, below_addr=below_addr, values=vals)

    @property
    def staged(self) -> list[tuple[int, int]]:
        """(addr, value) for the in-window probe then the two in-page probes."""
        return list(zip([self.window_addr] + self.in_page_addrs, self.values))

    def summary(self) -> str:
        return (
            f"entry={self.entry} window=0x{self.window_addr:08x}..0x{self.window_end:08x} "
            f"page=0x{self.page_base:08x}..0x{self.page_end:08x} "
            f"in_page={[hex(a) for a in self.in_page_addrs]} "
            f"adjacent=0x{self.adj_addr:08x}"
        )


class SepInboundFilterCfg:
    """One programmed allow-entry: address window + R/W enables."""

    def __init__(
        self, *, entry: int = 0, allow_addr: int = TARGET_ADDR, allow_value: int = TARGET_VALUE
    ) -> None:
        self.entry = entry
        self.allow_addr = allow_addr
        self.allow_value = allow_value
        self.blocked_addr = BLOCKED_ADDR
        self.src_id = 0  # 0 = match-all; else exact user[3:0]

    @property
    def cfg_addr(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_CONFIG

    @property
    def start_addr_reg(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_START_ADDR

    @property
    def end_addr_reg(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_END_ADDR

    def config_word(
        self, *, read_allowed: bool, write_allowed: bool, allow_burst: bool = False
    ) -> int:
        """FILTER_CONFIG lo: entry_enabled + allow_ns + src_id + per-dir enables.
        Never sets the locked (woset) bit, so the entry stays reprogrammable."""
        v = F_ENTRY_ENABLED | F_ALLOW_NS | (self.src_id << F_SRC_ID_LSB)
        if read_allowed:
            v |= F_READ_ALLOWED
        if write_allowed:
            v |= F_WRITE_ALLOWED
        if allow_burst:
            v |= F_ALLOW_BURST
        return v

    def summary(self) -> str:
        return (
            f"entry={self.entry} allow=0x{self.allow_addr:08x} val=0x{self.allow_value:08x} "
            f"blocked=0x{self.blocked_addr:08x} src_id={self.src_id}"
        )


class SepInboundFilterMatrixCfg:
    """Single source of truth for the inbound-filter RAND-REP walk.

    Discrete cells (walked every seed): entries 0 and 7 x two
    address windows x {rw, read-only, write-only} at src_id=0 (match-all),
    plus entry 0 / window 0 x {rw, r, w} at src_id=5 / user=5 (exact match)
    and one src-mismatch cell (src_id=5 / user=0xA, both allows set).
    Continuous knobs (window values) come from the run seed so a failing seed
    reproduces the staged data. Entry 0 / window A / rw / match-all is always
    first so the allow-rule proof line still appears.
    """

    def __init__(
        self, *, seed: int, windows: list[tuple[int, int]], widen: SepInboundFilterWidenCfg
    ) -> None:
        self.seed = seed
        self.windows = list(windows)
        self.entries = WALK_ENTRIES
        self.modes = ALLOW_MODES
        self.blocked_addr = BLOCKED_ADDR
        self.widen = widen

    @classmethod
    def from_seed(cls, seed: int) -> "SepInboundFilterMatrixCfg":
        # Seed-reproducible by requirement: `--stage sim --seed N` must replay
        # the exact stimulus. These are AXI payload words written to a
        # simulated DUT, never secrets.
        rng = SepSeededRng(seed)
        va = rng.getrandbits(32) or TARGET_VALUE
        vb = rng.getrandbits(32) or WINDOW_B_VALUE
        if va == vb:
            vb ^= 0xFFFF_FFFF
        return cls(
            seed=seed,
            windows=[(TARGET_ADDR, va), (WINDOW_B_ADDR, vb)],
            widen=SepInboundFilterWidenCfg.from_rng(rng),
        )

    def cells(self):
        """Yield (entry, window_idx, mode_name, addr, value, read_ok, write_ok,
        src_class, cfg_src_id, axi_user, expect_hit)."""
        for entry in self.entries:
            for widx, (addr, val) in enumerate(self.windows):
                for name, read_ok, write_ok in self.modes:
                    yield (entry, widx, name, addr, val, read_ok, write_ok, "match-all", 0, 0, True)
        addr0, val0 = self.windows[0]
        for name, read_ok, write_ok in self.modes:
            yield (
                0,
                0,
                name,
                addr0,
                val0,
                read_ok,
                write_ok,
                "match",
                SRC_ID_MATCH,
                SRC_ID_MATCH & SRC_ID_USER_MASK,
                True,
            )
        yield (
            0,
            0,
            "rw",
            addr0,
            val0,
            True,
            True,
            "mismatch",
            SRC_ID_MATCH,
            SRC_ID_MISMATCH_USER,
            False,
        )

    def n_cells(self) -> int:
        return len(self.entries) * len(self.windows) * len(self.modes) + len(self.modes) + 1

    def burst_window(self) -> tuple[int, int, int]:
        """Scratch window used by the burst checkers: (addr, value, end_addr).

        ``end_addr`` is two 4 KB pages past ``addr`` so allow_burst=1 does not
        trigger the same-page widen in axi_filter_wrap.sv.
        """
        addr, val = self.windows[1]
        end = addr + BURST_ALLOW_SPAN
        if (addr >> 12) == (end >> 12):
            raise RuntimeError(
                f"burst allow window 0x{addr:08x}..0x{end:08x} shares a 4 KB "
                f"page; the page-widen would fire"
            )
        return addr, val, end

    def ownership_targets(self, inbound_cfg_addr: int) -> list[tuple[str, int]]:
        """CSRs that must stay outside every programmed allow window.

        Inbound CFG is the primary ownership probe. The rest sit in the same
        reachable system-CSR window. Window 0 is
        ``SEP_SW_DEBUG``; ``SEP_GLOBAL_BASE_ADDR`` and ``SEP_REGION_SIZE`` share
        that 4 KB page, so they prove START/END (not the page) under
        ``allow_burst=0``.
        """
        win0 = self.windows[0][0]
        global_base = SEP_CPU_CTRL.addr("SEP_GLOBAL_BASE_ADDR")
        region_size = SEP_CPU_CTRL.addr("SEP_REGION_SIZE")
        if (global_base >> PAGE_SHIFT) != (win0 >> PAGE_SHIFT):
            raise RuntimeError(
                f"SEP_GLOBAL_BASE_ADDR 0x{global_base:08x} is not on the "
                f"window-0 page 0x{win0:08x}; same-page ownership coverage lost"
            )
        if (region_size >> PAGE_SHIFT) != (win0 >> PAGE_SHIFT):
            raise RuntimeError(
                f"SEP_REGION_SIZE 0x{region_size:08x} is not on the "
                f"window-0 page 0x{win0:08x}; same-page ownership coverage lost"
            )
        return [
            ("inbound-cfg", inbound_cfg_addr),
            ("outbound-cfg", OUTFILT_BASE),
            ("alias-remap", ALIAS_BASE),
            ("ap-remap", AP_BASE),
            ("stee-remap", STEE_BASE),
            ("sep-global-base", global_base),
            ("sep-region-size", region_size),
        ]

    def summary(self) -> str:
        wins = " ".join(f"w{i}=0x{a:08x}/0x{v:08x}" for i, (a, v) in enumerate(self.windows))
        return (
            f"seed={self.seed} entries={self.entries} {wins} "
            f"blocked=0x{self.blocked_addr:08x} cells={self.n_cells()} "
            f"src_match=0x{SRC_ID_MATCH:x} src_mismatch_user=0x{SRC_ID_MISMATCH_USER:x} "
            f"widen[{self.widen.summary()}]"
        )


class SepInboundFilter(SepAxiRegDriver):
    """CPU-LSU driver: stage the target CSR + program the inbound filter entry."""

    _DRIVER_TAG = "INFILT"

    async def stage_target(self, addr: int, val: int) -> None:
        """CPU-LSU write (no inbound filter on this path) to stage the target value."""
        await self._wr(addr, val)

    async def read_cpu(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_tolerant(self, addr: int, data: int) -> int:
        """Write tolerating a non-OKAY response; return the AXI resp_code.

        A locked entry refuses further writes, which SEP completes as
        SLVERR, so the proof is the resp code plus the read-back.
        """
        seq = SepAxiAccessSeq(
            "infilt_wr_tol",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            size=self._AXI_SIZE,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def lock_entry(self, entry: int) -> None:
        """Write-once-set FILTER_CONFIG.locked (bit 63) of one entry.

        Same 32-bit hi-word poke as ``sep_fabric_csr_bank_seq.woset_probe``:
        PeakRDL decodes FILTER_CONFIG only at offset 0, and the 64-bit AXI-Lite
        converter aligns the +4 beat into WDATA[63:32].
        """
        hi = INFILT_BASE + entry * FILTER_STRIDE + FILTER_CONFIG + 4
        cur = await self._rd(hi)
        await self._wr(hi, cur | (1 << FILTER_LOCKED_HI_BIT))

    async def disable_entry(self, entry: int) -> None:
        """Clear FILTER_CONFIG.lo for one entry (does not set the woset lock)."""
        await self._wr(INFILT_BASE + entry * FILTER_STRIDE + FILTER_CONFIG, 0)

    async def disable_all(self) -> None:
        """Disable every inbound-filter entry so a leftover allow cannot leak."""
        for entry in range(INFILT_N_ENTRIES):
            await self.disable_entry(entry)

    async def program_rule(
        self,
        cfg: SepInboundFilterCfg,
        *,
        read_allowed: bool,
        write_allowed: bool,
        allow_burst: bool = False,
        end_addr: int | None = None,
        expect_page_widen: bool = False,
    ) -> None:
        """Program the inbound filter entry.

        Default window is one 8-byte granule at ``allow_addr``. ``end_addr``
        sets the programmed range explicitly: the burst-allow checker spans two
        4 KB pages so the wrap page-widen does not fire, and the widen checkers
        keep START and END in one page so it does.

        ``expect_page_widen`` must be set to program ``allow_burst=1`` with
        START and END inside one 4 KB page. Hardware then widens the range to
        the whole page: ``START_ADDR`` rounds down, ``END_ADDR`` rounds up,
        and ``allow_burst=1`` selects the 4 KB granule
        (``hw/ip/axi_filter/doc/index.adoc``). The entry grants every
        address in that page -- in the SEP CSR region a page is a whole
        block. A caller that wants a narrow window and sets ``allow_burst``
        by habit gets the page, and the CSR readback shows the widened
        bounds. Requiring the opt-in fails that configuration.
        """
        end = cfg.allow_addr if end_addr is None else end_addr
        if allow_burst and not expect_page_widen:
            if (cfg.allow_addr >> 12) == (end >> 12):
                raise AssertionError(
                    f"CHK-WIDEN-GUARD: entry {cfg.entry} programs "
                    f"0x{cfg.allow_addr:08x}..0x{end:08x} with allow_burst=1 "
                    f"inside page 0x{cfg.allow_addr >> 12:05x}; hardware widens "
                    f"this to 0x{cfg.allow_addr & ~0xFFF:08x}.."
                    f"0x{(end & ~0xFFF) | 0xFFF:08x} and the entry grants the "
                    "whole page. Pass expect_page_widen=True if that is "
                    "intended, or keep START and END in different pages."
                )
        await self._wr(cfg.start_addr_reg, cfg.allow_addr)
        await self._wr(cfg.start_addr_reg + 4, 0)
        await self._wr(cfg.end_addr_reg, end)
        await self._wr(cfg.end_addr_reg + 4, 0)
        await self._wr(
            cfg.cfg_addr,
            cfg.config_word(
                read_allowed=read_allowed, write_allowed=write_allowed, allow_burst=allow_burst
            ),
        )


def ext_read_seq(addr: int, *, user: int = 0) -> SepAxiAccessSeq:
    """A 32-bit external-master READ (run via start_ext_seq). allow_timeout stays
    False: a blocked access must return DECERR from the filter err-slave, not wedge."""
    return SepAxiAccessSeq(
        "infilt_ext_rd",
        op=SepAxiOp.READ,
        addr=addr,
        length=4,
        size=2,
        expect_error=False,
        user=user,
    )


def ext_burst_read_seq(addr: int, *, user: int = 0, expect_error: bool = False) -> SepAxiAccessSeq:
    """Two-beat INCR read (AxLEN=1) on the external master."""
    return SepAxiAccessSeq(
        "infilt_ext_burst_rd",
        op=SepAxiOp.READ,
        addr=addr,
        length=BURST_BYTES,
        size=2,
        burst=AXI_BURST_INCR,
        expect_error=expect_error,
        user=user,
    )


def ext_burst_write_seq(
    addr: int, data: int, *, user: int = 0, expect_error: bool = False
) -> SepAxiAccessSeq:
    """Two-beat INCR write (AxLEN=1) on the external master."""
    return SepAxiAccessSeq(
        "infilt_ext_burst_wr",
        op=SepAxiOp.WRITE,
        addr=addr,
        wdata=data,
        length=BURST_BYTES,
        size=2,
        burst=AXI_BURST_INCR,
        expect_error=expect_error,
        allow_unverified_write_resp=expect_error,
        user=user,
    )


def ext_write_seq(addr: int, data: int, *, user: int = 0) -> SepAxiAccessSeq:
    """A 32-bit external-master WRITE (run via start_ext_seq). allow_unverified_write_resp
    so a blocked write's DECERR is tolerated for inspection (the test asserts the code)."""
    return SepAxiAccessSeq(
        "infilt_ext_wr",
        op=SepAxiOp.WRITE,
        addr=addr,
        wdata=data,
        length=4,
        size=2,
        allow_unverified_write_resp=True,
        user=user,
    )
