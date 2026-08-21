# SPDX-License-Identifier: Apache-2.0
"""Inbound-filter per-entry RULE stimulus.

With the SEP inbound filter ACTIVE (feat_ctrl.sep_debug=0, real PROD fuse), the
CPU-LSU master programs inbound FILTER_CONFIG allow-entries, then the EXTERNAL
SMN master (m_axi, the only path through u_inbound_filter) probes them:
  * allowed address (covered by the entry, read_allowed/write_allowed set, src_id
    match) -> the access traverses the filter + identity global->local remap
    (smc_global_base=0) and reaches the SEP-local CSR -> OKAY + exact value;
  * any other address (block-by-default) -> the filter's err-slave -> DECERR;
  * clearing read_allowed/write_allowed flips the matched read/write to DECERR.

This stays sep_debug=0 and proves PER-ENTRY rule enforcement (vs the global
sep_debug skip gate). The filter CSR layout is defined in sep_fabric_csr_bank_seq.
SepInboundFilterMatrixCfg is the single source of truth for the walked cells
(entry x window x R/W-allow).

src_id=0 in the rule is match-all (traffic_filter.sv), so the external master's
ar/awuser[3:0]=0 still matches; allow_ns=1 matches the master's NONSECURE prot.
"""

from __future__ import annotations

from sep_reg_meta import sym

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    INFILT_BASE, FILTER_STRIDE, FILTER_CONFIG,
    F_READ_ALLOWED, F_WRITE_ALLOWED, F_ENTRY_ENABLED, F_ALLOW_NS, F_SRC_ID_LSB,
)
from seq_lib.sep_scratch_reset_seq import SCRATCH_COLD_0

# Inbound FILTER_* per-entry register offsets (64-bit START/END as lo/hi 32-bit words).
FILTER_START_ADDR = 0x08
FILTER_END_ADDR = 0x10
# filter_ctrl.rdl FILTER_CONFIG.data_bus_width reset = 3 (8-byte beat).
# axi_filter_wrap expands a same-beat [start,end] window so END's low bits are 1
# (RDL reset of END_ADDR is 0x7 for that reason).
FILTER_DBUS_WIDTH_LOG2 = 3
FILTER_BEAT_MASK = (1 << FILTER_DBUS_WIDTH_LOG2) - 1

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
RESP_DECERR = 3
INFILT_N_ENTRIES = 8
WALK_ENTRIES = (0, 7)
ALLOW_MODES = (("rw", True, True), ("r", True, False), ("w", False, True))


class SepInboundFilterCfg:
    """One programmed allow-entry: address window + R/W enables."""

    def __init__(self, *, entry: int = 0, allow_addr: int = TARGET_ADDR,
                 allow_value: int = TARGET_VALUE) -> None:
        self.entry = entry
        self.allow_addr = allow_addr
        self.allow_value = allow_value
        self.blocked_addr = BLOCKED_ADDR
        self.src_id = 0                       # match-all

    @property
    def cfg_addr(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_CONFIG

    @property
    def start_addr_reg(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_START_ADDR

    @property
    def end_addr_reg(self) -> int:
        return INFILT_BASE + self.entry * FILTER_STRIDE + FILTER_END_ADDR

    def config_word(self, *, read_allowed: bool, write_allowed: bool) -> int:
        """FILTER_CONFIG lo: entry_enabled + allow_ns + src_id + per-dir enables.
        Never sets the locked (woset) bit, so the entry stays reprogrammable."""
        v = F_ENTRY_ENABLED | F_ALLOW_NS | (self.src_id << F_SRC_ID_LSB)
        if read_allowed:
            v |= F_READ_ALLOWED
        if write_allowed:
            v |= F_WRITE_ALLOWED
        return v

    def summary(self) -> str:
        return (f"entry={self.entry} allow=0x{self.allow_addr:08x} val=0x{self.allow_value:08x} "
                f"blocked=0x{self.blocked_addr:08x} src_id={self.src_id}")


class SepInboundFilterMatrixCfg:
    """Single source of truth for the inbound-filter RAND-REP walk.

    Discrete cells (walked every seed): first and last table entries x two
    address windows x {rw, read-only, write-only}. Continuous knobs (window
    values) come from the run seed so a failing seed reproduces the staged
    data. Entry 0 / window A / rw is always first so the original allow-rule
    proof line still appears.
    """

    def __init__(self, *, seed: int, windows: list[tuple[int, int]]) -> None:
        self.seed = seed
        self.windows = list(windows)
        self.entries = WALK_ENTRIES
        self.modes = ALLOW_MODES
        self.blocked_addr = BLOCKED_ADDR

    @classmethod
    def from_seed(cls, seed: int) -> "SepInboundFilterMatrixCfg":
        # Seed-reproducible by requirement: `--stage sim --seed N` must replay
        # the exact stimulus. These are AXI payload words written to a
        # simulated DUT, never secrets. See AGENTS.md "Stimulus randomness".
        rng = SepSeededRng(seed)
        va = rng.getrandbits(32) or TARGET_VALUE
        vb = rng.getrandbits(32) or WINDOW_B_VALUE
        if va == vb:
            vb ^= 0xFFFF_FFFF
        return cls(seed=seed, windows=[(TARGET_ADDR, va), (WINDOW_B_ADDR, vb)])

    def cells(self):
        """Yield (entry, window_idx, mode_name, addr, value, read_ok, write_ok)."""
        for entry in self.entries:
            for widx, (addr, val) in enumerate(self.windows):
                for name, read_ok, write_ok in self.modes:
                    yield entry, widx, name, addr, val, read_ok, write_ok

    def n_cells(self) -> int:
        return len(self.entries) * len(self.windows) * len(self.modes)

    def summary(self) -> str:
        wins = " ".join(f"w{i}=0x{a:08x}/0x{v:08x}" for i, (a, v) in enumerate(self.windows))
        return (f"seed={self.seed} entries={self.entries} {wins} "
                f"blocked=0x{self.blocked_addr:08x} cells={self.n_cells()}")


class SepInboundFilter(SepAxiRegDriver):
    """CPU-LSU driver: stage the target CSR + program the inbound filter entry."""

    _DRIVER_TAG = "INFILT"

    async def stage_target(self, addr: int, val: int) -> None:
        """CPU-LSU write (no inbound filter on this path) to stage the target value."""
        await self._wr(addr, val)

    async def read_cpu(self, addr: int) -> int:
        return await self._rd(addr)

    async def disable_entry(self, entry: int) -> None:
        """Clear FILTER_CONFIG.lo for one entry (does not set the woset lock)."""
        await self._wr(INFILT_BASE + entry * FILTER_STRIDE + FILTER_CONFIG, 0)

    async def disable_all(self) -> None:
        """Disable every inbound-filter entry so a leftover allow cannot leak."""
        for entry in range(INFILT_N_ENTRIES):
            await self.disable_entry(entry)

    async def program_rule(self, cfg: SepInboundFilterCfg, *, read_allowed: bool, write_allowed: bool) -> None:
        """Program the inbound filter entry to cover [allow_addr, allow_addr] (one
        8-byte block) with the given read/write enables."""
        await self._wr(cfg.start_addr_reg, cfg.allow_addr)
        await self._wr(cfg.start_addr_reg + 4, 0)
        await self._wr(cfg.end_addr_reg, cfg.allow_addr)
        await self._wr(cfg.end_addr_reg + 4, 0)
        await self._wr(cfg.cfg_addr, cfg.config_word(read_allowed=read_allowed, write_allowed=write_allowed))


def ext_read_seq(addr: int) -> SepAxiAccessSeq:
    """A 32-bit external-master READ (run via start_ext_seq). allow_timeout stays
    False: a blocked access must return DECERR from the filter err-slave, not wedge."""
    return SepAxiAccessSeq("infilt_ext_rd", op=SepAxiOp.READ, addr=addr, length=4, size=2,
                           expect_error=False)


def ext_write_seq(addr: int, data: int) -> SepAxiAccessSeq:
    """A 32-bit external-master WRITE (run via start_ext_seq). allow_unverified_write_resp
    so a blocked write's DECERR is tolerated for inspection (the test asserts the code)."""
    return SepAxiAccessSeq("infilt_ext_wr", op=SepAxiOp.WRITE, addr=addr, wdata=data,
                           length=4, size=2, allow_unverified_write_resp=True)
