# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_001 ANCHOR: smc_primary_reset_inflight_links_test
# DV-TESTCASE-CONTRACT-REVISION: 6 RECORD-SHA256: 0a97ea48eab93d459baedd49eb405d5525d712830957b6d13e49c9e69853e4e3
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""Primary reset entered three ways while accesses are pending on every steerable AXI link.

Entries: the cool pin held for 40 ``clk_ref_i`` samples, the JTAG cool override, and the
FLR timed cool-reset sequence. Before each entry a pending set is armed: two SEP_IN reads
and a UART0 read held at the SEP_IN response, a SEP_IN write whose W beat trails its AW,
three SYS_IN reads held at the SYS_IN response, two JTAG_IN reads whose response is not
accepted, one of them held at the SYS_OUT responder, an eFuse JTAG read whose response is
not accepted, and a read of the DTP CSR window that no responder answers. The leaf passively
samples every link on each ``clk_smc_i`` edge from the arm until 64 edges after the last
fresh access.

SYS_IN and SEP_IN answer an address outside the SMC window with DECERR (fabric.adoc, input
fabric), so the accesses that reach SYS_OUT go through JTAG_IN. The SYS_IN read of 0xB000_0000
is a pending item whose DECERR response is held at the SYS_IN response channel.

Graded: the 31-sample pulse leaves every reset released; the primary reset effects on
``CPU_CTRL.SCRATCH[0]`` and the hang-detector threshold after each of the three entries (the
FLR cool reset feeds the primary reset, clk_rst.adoc); one fresh write and read per link
after each release; no response without a request; DUT-driven VALIDs low while
``rst_primary_smc_clk_no`` is low; the pending set armed at the assertion. Pending-phase
fates, the release latency, the override order and the VALIDs at the first reset edge are
printed as ``OBS-*`` lines and never compared.

This leaf drives no traffic on the CPU MMIO link and runs no firmware image: the cores boot
from the bench ROM after every release, so SYS_OUT also carries their instruction fetches
outside the fresh windows.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import (
    SmcSysAxiDriver,
    SmcSysAxiGroupItem,
    SmcSysAxiItem,
    SmcSysAxiOp,
    idle_axil_master_inputs,
)
from ocah_axi_vip import AxiTimingProfile, OcahAxiLiteMasterAgent

from ._one_shot import _OneShot
from .smc_addr_map import (
    cpu_ctrl_u32,
    jtag_smc_reset_ctrl_bit,
    reset_unit_u32,
    smc_addr,
    smc_indexed_addr,
)
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_efuse_vip_utils import EFUSE_DEFAULT_HEX, efuse_preload_word_at
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq
from .smc_reset_seq_base import SmcResetSeqBase

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT,
    UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT,
)

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SCRATCH0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
THRESHOLD = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
UART0_REG = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)
EFUSE_WORD = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
# HARNESS_LOCKS carries no read lock and its low word is the one non-zero word of the bench
# eFuse image.
EFUSE_FRESH_WORD = smc_addr("SMC_TOP_SMC_EFUSE_MAP_HARNESS_LOCKS_BASE_ADDR")
EFUSE_FRESH_EXPECT = efuse_preload_word_at(EFUSE_FRESH_WORD)
EFUSE_FRESH_SOURCE = (
    f"{EFUSE_DEFAULT_HEX.name} word for SMC_TOP_SMC_EFUSE_MAP_HARNESS_LOCKS_BASE_ADDR "
    f"0x{EFUSE_FRESH_WORD:08x}"
)
DTP_WINDOW = smc_addr("SMC_TOP_DTP_CTRL_REG_BASE_ADDR")
ISOLATE_SMC = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
FLR_DELAY_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_HOLD_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
ISOLATE_SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
SCRATCH_RESET = cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_reset")
THRESHOLD_RESET = SMC_BASE_CONFIG_HANG_DET_TIMEOUT_THRESHOLD_REG_DEFAULT
UART0_RESET = UART_LOG_ENGINE_CTRL_CTRL_REG_DEFAULT

SEP_READ_A = SPM_BASE + 0x20_000
SEP_READ_B = SPM_BASE + 0x20_008
SEP_WRITE = SPM_BASE + 0x20_100
SYS_READ_A = SPM_BASE + 0x20_040
SYS_READ_B = SPM_BASE + 0x20_048
JTAG_READ = SPM_BASE + 0x20_080
FRESH_SEP = SPM_BASE + 0x20_200
FRESH_SYS = SPM_BASE + 0x20_240
FRESH_JTAG = SPM_BASE + 0x20_280
EXT_PENDING = 0xB000_0000
EXT_FRESH = 0xB000_0008
PRELOAD = (SEP_READ_A, SEP_READ_B, SYS_READ_A, SYS_READ_B, JTAG_READ)
PRELOAD_WORD = 0x1A71_0000_0000_0000
EXT_PENDING_WORD = 0x1A71_00B0_0000_0000

SCRATCH_REF = 0xC001_0001
THRESHOLD_REF = 0x2345
FRESH_SEP_DATA = 0x5EC0_0001_0000_0001
FRESH_SYS_DATA = 0x5EC0_0002_0000_0002
FRESH_JTAG_DATA = 0x5EC0_0003_0000_0003
FRESH_EXT_DATA = 0x5EC0_0004
FLR_DELAY_VALUE = 0x20
FLR_HOLD_VALUE = 0x40

PIN_LOW_SAMPLES = 40
GLITCH_LOW_SAMPLES = 31
GLITCH_TAIL_SAMPLES = 64
TAIL_EDGES = 64
# The SYS_OUT read-completion count is a registered counter and lags the handshake it counts.
RESPONSE_COUNT_LAG = 2
ASSERT_BOUND_SMC = 300
RELEASE_BOUND_SMC = 20_000
COOL_FLR_BOUND_REF = 200_000
JTAG_HOLD_BOUND_REF = 400
JTAG_VAL1_BOUND_REF = 64
ARM_BOUND_SMC = 2_000
DTP_REQUEST_BOUND_SMC = 2_000
FUSE_SENSE_BOUND_SMC = 200_000
JOIN_BOUND_NS = 100_000
EJ_BOUND_NS = 5_000
PENDING_HOLD_CYCLES = 8_000
PLANNED_ITEMS = {"SEP_IN": 4, "SYS_IN": 4, "JTAG_IN": 2, "EFUSE_JTAG": 1}
EXPECTED_ABORTED_SEQUENCER_ITEMS = 3 * (4 + 3 + 2)

ENTRIES = ("pin", "jtag", "flr")
FRESH_BASE = {
    "SEP_IN": FRESH_SEP_DATA,
    "SYS_IN": FRESH_SYS_DATA,
    "JTAG_IN": FRESH_JTAG_DATA,
    "SYS_OUT": FRESH_EXT_DATA,
}
CHANNELS = ("aw", "w", "b", "ar", "r")
VECTOR_BIT = {"aw": 0, "w": 1, "b": 2, "ar": 3, "r": 4}
LINKS = (
    "SYS_IN",
    "JTAG_IN",
    "SEP_IN",
    "SYS_OUT",
    "EFUSE_JTAG",
    "PERIPH",
    "CPU_FRONT",
    "CPU_MMIO",
)
ORPHAN_LINKS = LINKS[:5]
PREFIX = {"SYS_IN": "sys_axi", "JTAG_IN": "jtag_axi", "SEP_IN": "s_axi", "EFUSE_JTAG": "ej_axi"}
VECTOR = {"PERIPH": "tb_periph_axil", "CPU_FRONT": "tb_cpu_front", "CPU_MMIO": "tb_cpu_mmio"}
RAW_VALID = {"SEP_IN": "tb_sep_axi_r_raw_valid", "SYS_IN": "tb_sys_axi_r_raw_valid"}
R_HOLD = {"SEP_IN": "tb_sep_axi_r_hold", "SYS_IN": "tb_sys_axi_r_hold"}
R_DROP = {"SEP_IN": "tb_sep_axi_r_drop", "SYS_IN": "tb_sys_axi_r_drop"}

# DUT-driven VALIDs per link as (channels, first window sample at which they must read 0).
# Response-side VALIDs are checked from the first sample; request-side VALIDs of a
# synchronous-reset master may clear on the first edge, so they are checked from the second.
VALID_RULES = {
    "SYS_IN": (("b", "r"), 1),
    "JTAG_IN": (("b", "r"), 1),
    "SEP_IN": (("b", "r"), 1),
    "EFUSE_JTAG": (("b", "r"), 1),
    "SYS_OUT": (("aw", "w", "ar"), 2),
    "PERIPH": (("aw", "w", "ar"), 2),
    "CPU_FRONT": (("b", "r"), 1),
    "CPU_MMIO": (("aw", "w", "ar"), 2),
}

_EXTRA_NAMES = (
    "rst_primary_smc_clk_no",
    "rst_cold_n_o",
    "tb_cpu_core_reset_n",
    "tb_sep_axi_r_hold",
    "tb_sys_axi_r_hold",
    "tb_sep_axi_r_drop",
    "tb_sys_axi_r_drop",
    "tb_sep_axi_r_raw_valid",
    "tb_sys_axi_r_raw_valid",
    "tb_output_axi_resp_hold",
    "tb_output_axi_araddr",
    "tb_output_axi_read_count",
    "s_axi_rlast",
    "sys_axi_rlast",
    "jtag_axi_rlast",
    "tb_axil_dtp_csr_active",
    "axil_dtp_csr_resp",
    "tb_cpu_l2_pending_ar",
    "tb_cpu_l2_pending_aw",
    "tb_cpu_mmio_pending_ar",
    "tb_cpu_mmio_pending_aw",
)


def _pack(*, cool_ovrd: int, cool_val: int) -> int:
    word = 0
    if cool_ovrd:
        word |= 1 << jtag_smc_reset_ctrl_bit("cool_reset_n_ovrd")
    if cool_val:
        word |= 1 << jtag_smc_reset_ctrl_bit("cool_reset_n_val")
    return word


def _entry_word(base: int, name: str) -> int:
    """Return ``base`` with the entry number in bits 15:12.

    Each entry writes a word that no earlier entry left at the address, so a fresh write
    that does not land fails its read-back compare.
    """
    return base | ((ENTRIES.index(name) + 1) << 12)


def _signal_names() -> tuple[str, ...]:
    names = list(_EXTRA_NAMES)
    for prefix in PREFIX.values():
        for ch in CHANNELS:
            names += [f"{prefix}_{ch}valid", f"{prefix}_{ch}ready"]
    for ch in CHANNELS:
        names += [f"tb_output_axi_{ch}valid", f"tb_output_axi_{ch}ready"]
    for vec in VECTOR.values():
        names += [f"{vec}_valid", f"{vec}_ready"]
    return tuple(dict.fromkeys(names))


class _LinkMonitor:
    """Passive per-``clk_smc_i`` sampler of every link, started when the pending set is armed.

    A sample is taken half a clock before each capturing edge, so a handshake is a VALID
    and READY that both read 1 in the sample. The window opens at the first sample at which
    ``rst_primary_smc_clk_no`` reads 0 and closes at the first sample at which it reads 1.
    """

    def __init__(self, seq, on_pre_sample) -> None:
        self.seq = seq
        self.on_pre_sample = on_pre_sample
        self.pre_snapshot = None
        self.hs_events = {link: [] for link in ORPHAN_LINKS}
        dut = cocotb.top
        names = _signal_names()
        for name in names:
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        self.handles = {name: getattr(dut, name) for name in names}
        self.stop = False
        self.task = None
        self.read_count = 0
        self.hist = {}
        self.n = 0
        self.phase = "pre"
        self.w = 0
        self.assert_n = self.release_n = None
        self.assert_ps = self.release_ps = self.last_window_ps = None
        self.assert_ref = self.release_ref = None
        self.assert_state: dict = {}
        self.release_state: dict = {}
        self.window_samples = 0
        self.cores_low = 0
        self.cold_low = 0
        self.dtp_resp_nonzero = 0
        self.valid_edges = {link: 0 for link in (*VALID_RULES, "DTP")}
        self.live = {link: set() for link in VALID_RULES}
        self.valid_violations = {link: [] for link in (*VALID_RULES, "DTP")}
        self.first_edge = {}
        self.cnt = {link: dict.fromkeys(CHANNELS, 0) for link in LINKS}
        self.orphan = {link: None for link in ORPHAN_LINKS}
        self.since_arm = {"SEP_IN_aw": 0, "SEP_IN_w": 0}
        self.pre_cnt = {link: dict.fromkeys(CHANNELS, 0) for link in LINKS}
        self.last_valid = {}
        self.last_out_ar_addr = None
        self.seen = dict.fromkeys(
            ("sep_r", "sys_r", "jtag_r", "ej_r", "sys_out_ar", "dtp", "sep_aw"), False
        )
        self.prev: dict = {}
        self.sep_ar_after_release = self.sep_r_after_release = None
        self.core_violations: list[str] = []
        self.cold_violations: list[str] = []
        self.dtp_after_release_high = None
        self.state_text = "no sample yet"

    def start(self) -> None:
        self.task = cocotb.start_soon(self.run())

    async def finish(self) -> None:
        self.stop = True
        await self.task

    async def run(self) -> None:
        clk = cocotb.top.clk_smc_i
        while not self.stop:
            await FallingEdge(clk)
            self._sample()

    def _g(self, name: str) -> int:
        value = self.handles[name].value
        assert value.is_resolvable, f"{name} is X/Z at monitor sample {self.n}: {value}"
        return int(value)

    def _links(self) -> dict:
        g = self._g
        links = {}
        for link, prefix in PREFIX.items():
            chans = {ch: (g(f"{prefix}_{ch}valid"), g(f"{prefix}_{ch}ready")) for ch in CHANNELS}
            if link in RAW_VALID:
                ready = g(R_DROP[link]) | (g(f"{prefix}_rready") & (1 - g(R_HOLD[link])))
                chans["r"] = (g(RAW_VALID[link]), ready)
            links[link] = chans
        links["SYS_OUT"] = {
            ch: (g(f"tb_output_axi_{ch}valid"), g(f"tb_output_axi_{ch}ready")) for ch in CHANNELS
        }
        for link, vec in VECTOR.items():
            valid, ready = g(f"{vec}_valid"), g(f"{vec}_ready")
            links[link] = {
                ch: ((valid >> bit) & 1, (ready >> bit) & 1) for ch, bit in VECTOR_BIT.items()
            }
        return links

    def _sample(self) -> None:
        g = self._g
        self.n += 1
        now = int(get_sim_time("ps"))
        rst = g("rst_primary_smc_clk_no")
        links = self._links()
        hs = {link: {ch: v & r for ch, (v, r) in chans.items()} for link, chans in links.items()}
        for link, prefix in (("SEP_IN", "s_axi"), ("SYS_IN", "sys_axi"), ("JTAG_IN", "jtag_axi")):
            hs[link]["r"] &= g(f"{prefix}_rlast")
        reads = g("tb_output_axi_read_count")
        hs["SYS_OUT"]["r"] = max(0, reads - self.read_count) if self.n > 1 else 0
        self.read_count = reads
        dtp = g("tb_axil_dtp_csr_active")
        if g("axil_dtp_csr_resp") != 0:
            self.dtp_resp_nonzero += 1
        self.state_text = (
            f"sample {self.n} phase {self.phase} rst_primary_smc_clk_no={rst} dtp_active={dtp}"
        )
        if self.phase == "pre":
            self._pre(links, hs, dtp, g)
            if rst == 1:
                self.pre_snapshot = self.on_pre_sample()
            if rst == 0:
                self._open_window(now, links, dtp, g)
        if self.phase == "window":
            if rst == 1:
                self.phase = "post"
                self.release_n, self.release_ps = self.n, now
                self.release_ref = self.seq.ref_n
                self.release_state = self._pending_counts(g)
            else:
                self._window(now, links, dtp, g)
        if self.phase != "window":
            for link, (chans, _first) in VALID_RULES.items():
                self.live[link].update(ch for ch in chans if links[link][ch][0])
        if self.phase in ("window", "post"):
            self._count(hs)
            self.hist[self.n] = {link: dict(self.cnt[link]) for link in LINKS}
        if self.phase == "post":
            if hs["SEP_IN"]["ar"] and self.sep_ar_after_release is None:
                self.sep_ar_after_release = self.n
            if hs["SEP_IN"]["r"] and self.sep_r_after_release is None:
                self.sep_r_after_release = self.n
        self.prev = {
            "sep_r": links["SEP_IN"]["r"][0],
            "sys_r": links["SYS_IN"]["r"][0],
            "jtag_r": links["JTAG_IN"]["r"][0],
            "ej_r": links["EFUSE_JTAG"]["r"][0],
            "dtp": dtp,
            "sep_wvalid": links["SEP_IN"]["w"][0],
            "l2f_r": links["CPU_FRONT"]["r"][0],
        }

    def _pre(self, links, hs, dtp, g) -> None:
        for link in LINKS:
            for ch in CHANNELS:
                self.pre_cnt[link][ch] += hs[link][ch]
        self.last_valid = {link: self._joined_valid(links[link]) for link in LINKS}
        if hs["SYS_OUT"]["ar"]:
            self.last_out_ar_addr = g("tb_output_axi_araddr")
        if hs["SEP_IN"]["aw"]:
            self.since_arm["SEP_IN_aw"] += 1
            self.seen["sep_aw"] = True
        if hs["SEP_IN"]["w"]:
            self.since_arm["SEP_IN_w"] += 1
        if links["SEP_IN"]["r"][0]:
            self.seen["sep_r"] = True
        if links["SYS_IN"]["r"][0]:
            self.seen["sys_r"] = True
        if links["JTAG_IN"]["r"][0]:
            self.seen["jtag_r"] = True
        if links["EFUSE_JTAG"]["r"][0]:
            self.seen["ej_r"] = True
        if hs["SYS_OUT"]["ar"] and g("tb_output_axi_araddr") == EXT_PENDING:
            self.seen["sys_out_ar"] = True
        if dtp:
            self.seen["dtp"] = True

    @staticmethod
    def _joined_valid(chans) -> str:
        return ",".join(f"{ch}:{v}/{r}" for ch, (v, r) in chans.items())

    def arm_text(self) -> str:
        addr = "none" if self.last_out_ar_addr is None else f"0x{self.last_out_ar_addr:x}"
        pre = {k: "".join(str(v) for v in c.values()) for k, c in self.pre_cnt.items()}
        return (
            f"seen={self.seen} handshakes since arm (aw,w,b,ar,r)={pre} "
            f"last valid/ready={self.last_valid} last SYS_OUT AR address={addr} "
            f"dtp_active={self.prev.get('dtp')}"
        )

    def _pending_counts(self, g) -> dict:
        return {
            "l2_ar": g("tb_cpu_l2_pending_ar"),
            "l2_aw": g("tb_cpu_l2_pending_aw"),
            "mmio_ar": g("tb_cpu_mmio_pending_ar"),
            "mmio_aw": g("tb_cpu_mmio_pending_aw"),
        }

    def _open_window(self, now, links, dtp, g) -> None:
        self.phase = "window"
        self.assert_n, self.assert_ps, self.assert_ref = self.n, now, self.seq.ref_n
        self.assert_state = {
            "pre_snapshot": self.pre_snapshot,
            "holds": (
                g("tb_sep_axi_r_hold"),
                g("tb_sys_axi_r_hold"),
                g("tb_output_axi_resp_hold"),
            ),
            "prev": dict(self.prev),
            "seen": dict(self.seen),
            "sep_aw_since_arm": self.since_arm["SEP_IN_aw"],
            "sep_w_since_arm": self.since_arm["SEP_IN_w"],
            **self._pending_counts(g),
        }

    def _window(self, now, links, dtp, g) -> None:
        self.w += 1
        self.window_samples += 1
        self.last_window_ps = now
        if g("tb_cpu_core_reset_n") == 0:
            self.cores_low += 1
        else:
            self.core_violations.append(f"sample {self.w}: tb_cpu_core_reset_n=1")
        if g("rst_cold_n_o") == 0:
            self.cold_low += 1
            self.cold_violations.append(f"sample {self.w}: rst_cold_n_o=0")
        for link, (chans, first) in VALID_RULES.items():
            high = [ch for ch in chans if links[link][ch][0]]
            if self.w == 1:
                self.first_edge[link] = high
            if self.w >= first:
                self.valid_edges[link] += 1
                if high:
                    self.valid_violations[link].append(f"sample {self.w}: {'/'.join(high)}")
        if self.w == 1:
            self.first_edge["DTP"] = ["active"] if dtp else []
        if self.w >= 2:
            self.valid_edges["DTP"] += 1
            if dtp:
                self.valid_violations["DTP"].append(f"sample {self.w}: active")

    def _count(self, hs) -> None:
        for link in LINKS:
            for ch in CHANNELS:
                self.cnt[link][ch] += hs[link][ch]
        for link in ORPHAN_LINKS:
            for ch in CHANNELS:
                if hs[link][ch] and len(self.hs_events[link]) < 40:
                    self.hs_events[link].append(f"{ch}@{self.phase}{self.n}")
        for link in ORPHAN_LINKS:
            c = self.cnt[link]
            if self.orphan[link] is None and (c["r"] > c["ar"] or c["b"] > c["aw"]):
                self.orphan[link] = (
                    f"{link} at monitor sample {self.n} ({self.phase}, window sample {self.w}, "
                    f"release at {self.release_n}): AR/R/AW/B = "
                    f"{c['ar']}/{c['r']}/{c['aw']}/{c['b']}; handshakes {self.hs_events[link]}"
                )

    def snap(self, link: str) -> dict:
        return dict(self.cnt[link])


class smc_primary_reset_inflight_links_test_seq(SmcResetSeqBase, output_fabric_pass_all_cfg_seq):
    """Cool pin, JTAG cool override and FLR cool reset with every link carrying a pending set."""

    def __init__(self, name: str = "smc_primary_reset_inflight_links_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.ref_n = 0
        self._ref_run = True
        self.fence: list[tuple[str, int, int]] = []
        self.records: dict[str, SimpleNamespace] = {}
        self.glitch = SimpleNamespace()
        self.ref_rb: dict[str, tuple[int, int]] = {}
        self.ej = None
        self.ej_pre_value = None
        self.dtp_event = None
        self.expected_aborted_items = EXPECTED_ABORTED_SEQUENCER_ITEMS
        self.expired_waits = 0

    async def _dispatch_reset_item(self, item: SmcResetItem) -> None:
        assert self.dispatch_reset is not None, "dispatch_reset not bound by the test"
        await self.dispatch_reset(item)

    @staticmethod
    def _v(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _stamp(self, name: str, count: int, when: int | None = None) -> None:
        self.fence.append((name, int(get_sim_time("ps")) if when is None else when, count))

    def _bound(self, label: str, bound: str, state: str) -> None:
        self._timeout_paths.append(f"{label}: bound={bound} last={state}")

    async def _count_ref_edges(self) -> None:
        clk = cocotb.top.clk_ref_i
        while self._ref_run:
            await RisingEdge(clk)
            self.ref_n += 1

    async def _wait_smc(self, label: str, cond, bound: int, state) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(bound + 1):
            if cond():
                self._bound(label, f"{bound}clk_smc_i", f"reached after {n} edges, {state()}")
                return n
            await RisingEdge(clk)
        self.expired_waits += 1
        raise AssertionError(f"{label}: not reached within {bound} clk_smc_i edges; {state()}")

    async def _wait_ref(self, label: str, cond, bound: int, state) -> int:
        clk = cocotb.top.clk_ref_i
        for n in range(bound + 1):
            if cond():
                self._bound(label, f"{bound}clk_ref_i", f"reached after {n} edges, {state()}")
                return n
            await RisingEdge(clk)
        self.expired_waits += 1
        raise AssertionError(f"{label}: not reached within {bound} clk_ref_i edges; {state()}")

    # --- bench access helpers ---------------------------------------------------------
    def _sequencer(self, port: str):
        return {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port].sequencer

    @staticmethod
    def _item(op, label, addr, data=0, length=8, abort=False, timing=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.allow_reset_abort = abort
        item.timing = timing
        return item

    def _start(self, port: str, item, label: str):
        return cocotb.start_soon(_OneShot(item, f"{label}_os").start(self._sequencer(port)))

    async def _join(self, port: str, task, label: str) -> None:
        try:
            await with_timeout(task, JOIN_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            self.expired_waits += 1
            raise AssertionError(
                f"{port} {label}: access not finished within {JOIN_BOUND_NS} ns"
            ) from exc

    async def _okay(self, port, op, label, addr, data=0, length=8) -> SmcSysAxiItem:
        item = self._item(op, label, addr, data, length)
        await self._join(port, self._start(port, item, label), label)
        self.accesses += 1
        assert item.resp_code == 0 and not item.timed_out, (
            f"{port} {label} @0x{addr:x}: resp={item.resp_code} timed_out={item.timed_out}"
        )
        return item

    async def _ej_read(self, label: str, addr: int = EFUSE_WORD) -> int:
        event = self.ej.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), EJ_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            self.expired_waits += 1
            raise AssertionError(
                f"{label}: eFuse JTAG read of 0x{addr:x} not answered within {EJ_BOUND_NS} ns"
            ) from exc
        assert event.data is not None, f"{label}: eFuse JTAG read flushed without a response"
        code = SmcSysAxiDriver._resp_code(event.data)
        assert code == 0, f"{label}: eFuse JTAG read resp={code}"
        self._bound(f"{label}.ej_read", f"{EJ_BOUND_NS}ns", "answered OKAY")
        return int.from_bytes(event.data.data, "little") & 0xFFFF_FFFF

    # --- setup and per-entry preparation ----------------------------------------------
    async def _ref_words(self, label: str) -> None:
        await self.csr_write(f"{label}_SCRATCH_REF", SCRATCH0, SCRATCH_REF, length=8)
        scratch = await self.csr_read(f"{label}_SCRATCH_RB", SCRATCH0, length=8)
        await self.csr_write(f"{label}_THRESHOLD_REF", THRESHOLD, THRESHOLD_REF)
        threshold = await self.csr_read(f"{label}_THRESHOLD_RB", THRESHOLD)
        self.ref_rb[label] = (scratch & 0xFFFF_FFFF, threshold)

    async def _flr_counters(self, label: str) -> None:
        delay = await self.csr_read(f"{label}_FLR_DELAY_BEFORE", FLR_DELAY_REG)
        hold = await self.csr_read(f"{label}_FLR_HOLD_BEFORE", FLR_HOLD_REG)
        cocotb.log.info("%s: FLR counters read 0x%x/0x%x before programming", label, delay, hold)
        await self.csr_write(f"{label}_FLR_DELAY", FLR_DELAY_REG, FLR_DELAY_VALUE)
        await self.csr_write(f"{label}_FLR_HOLD", FLR_HOLD_REG, FLR_HOLD_VALUE)
        got = await self.csr_read(f"{label}_FLR_DELAY_RB", FLR_DELAY_REG)
        assert got == FLR_DELAY_VALUE, f"{label}: FLR delay counter reads 0x{got:x}"
        got = await self.csr_read(f"{label}_FLR_HOLD_RB", FLR_HOLD_REG)
        assert got == FLR_HOLD_VALUE, f"{label}: FLR reset counter reads 0x{got:x}"

    async def _prepare(self, label: str, *, flr: bool = False) -> None:
        assert self._v("rst_primary_smc_clk_no") == 1, f"{label}: primary reset is asserted"
        assert self._v("rst_cool_ni") == 1, f"{label}: rst_cool_ni is low"
        assert self._v("tb_jtag_reset_ctrl") == 0, f"{label}: tb_jtag_reset_ctrl is not 0"
        assert self._v("tb_rst_cool_from_flr") == 1, f"{label}: the FLR cool reset is asserted"
        assert self._v("tb_cfg_flr_pf_active") == 0, f"{label}: FLR is requested"
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        await self._ref_words(label)
        for addr in PRELOAD:
            await self.csr_write(f"{label}_PRELOAD_{addr:x}", addr, PRELOAD_WORD | addr, length=8)
        sys_out_mem = self.cfg.sys_out_mem
        assert sys_out_mem is not None, "SYS_OUT responder not bound"
        sys_out_mem.write_int(EXT_PENDING, EXT_PENDING_WORD, 8)
        if flr:
            smc_reg = await self.csr_read(f"{label}_ISOLATE_SMC_IDLE", ISOLATE_SMC)
            assert smc_reg == 0, (
                f"{label}: ISOLATE_REQ_SMC_REG reads 0x{smc_reg:x} before the FLR edge"
            )
            await self._flr_counters(label)
        for name in ("tb_sep_axi_r_hold", "tb_sys_axi_r_hold", "tb_output_axi_resp_hold"):
            assert self._v(name) == 0, f"{label}: {name} is set outside the pending phase"

    # --- 31-sample pulse --------------------------------------------------------------
    async def _glitch(self) -> None:
        dut = cocotb.top
        clk = dut.clk_ref_i
        assert self._v("rst_primary_smc_clk_no") == 1 and self._v("rst_cool_ni") == 1
        await RisingEdge(clk)
        await self._send(SmcResetOp.COOL_RST_LO)
        low_driven = 0
        stable = 0
        bad = []
        total = GLITCH_LOW_SAMPLES + GLITCH_TAIL_SAMPLES
        for k in range(1, total + 1):
            await RisingEdge(clk)
            if self._v("rst_cool_ni") == 0:
                low_driven += 1
            levels = (
                self._v("rst_primary_smc_clk_no"),
                self._v("rst_primary_ref_clk_no"),
                self._v("rst_cold_n_o"),
            )
            if levels == (1, 1, 1):
                stable += 1
            else:
                bad.append(f"edge {k}: primary_smc/primary_ref/cold = {levels}")
            if k == GLITCH_LOW_SAMPLES:
                await self._send(SmcResetOp.COOL_RST_HI)
        self.glitch.low_driven, self.glitch.stable, self.glitch.total = low_driven, stable, total
        self.glitch.bad = bad
        self._bound("S2.glitch_window", f"{total}clk_ref_i", f"{stable}/{total} edges stable")
        assert low_driven == GLITCH_LOW_SAMPLES, f"the pulse was {low_driven} samples long"
        scratch = await self.csr_read("GLITCH_SCRATCH_STILL", SCRATCH0, length=8)
        self.glitch.scratch = scratch & 0xFFFF_FFFF
        self._stamp("GLITCH", total)

    # --- pending set --------------------------------------------------------------------
    async def _arm(self, rec, mon) -> None:
        dut = cocotb.top
        dut.tb_sep_axi_r_hold.value = 1
        dut.tb_sys_axi_r_hold.value = 1
        dut.tb_output_axi_resp_hold.value = 1
        sep_timing = AxiTimingProfile(w_delay=PENDING_HOLD_CYCLES)
        jtag_timing = AxiTimingProfile(r_ready_delay=PENDING_HOLD_CYCLES)
        rec.sep_items = [
            self._item(SmcSysAxiOp.READ, "sep_rd_a", SEP_READ_A, abort=True),
            self._item(SmcSysAxiOp.READ, "sep_rd_b", SEP_READ_B, abort=True),
            self._item(SmcSysAxiOp.READ, "sep_uart", UART0_REG, length=4, abort=True),
            self._item(SmcSysAxiOp.WRITE, "sep_wr", SEP_WRITE, 0x5EC0_FFFF_0000_0001, abort=True),
        ]
        # A SYS_IN address outside the SMC window answers DECERR (fabric.adoc, input
        # fabric), so the reads and writes that must reach SYS_OUT go through JTAG_IN.
        rec.sys_items = [
            self._item(SmcSysAxiOp.READ, "sys_rd_a", SYS_READ_A, abort=True),
            self._item(SmcSysAxiOp.READ, "sys_rd_b", SYS_READ_B, abort=True),
            self._item(SmcSysAxiOp.READ, "sys_ext", EXT_PENDING, abort=True),
        ]
        rec.jtag_items = [
            self._item(SmcSysAxiOp.READ, "jtag_rd", JTAG_READ, abort=True),
            self._item(SmcSysAxiOp.READ, "jtag_ext", EXT_PENDING, abort=True),
        ]
        sep_group = SmcSysAxiGroupItem("sep_pending", rec.sep_items, timing=sep_timing)
        sys_group = SmcSysAxiGroupItem("sys_pending", rec.sys_items)
        jtag_group = SmcSysAxiGroupItem("jtag_pending", rec.jtag_items, timing=jtag_timing)
        rec.tasks = {
            "SEP_IN": self._start("SEP", sep_group, "sep_pending"),
            "SYS_IN": self._start("SYS", sys_group, "sys_pending"),
            "JTAG_IN": self._start("JTAG", jtag_group, "jtag_pending"),
        }
        r_channel = self.ej.backend.read_if.r_channel
        r_channel.pause = True
        rec.ej_event = self.ej.init_read(address=EFUSE_WORD, length=4)
        if self.dtp_event is None:
            self.dtp_event = self.env.sys_in_axi_agent.driver.axi.init_read(
                address=DTP_WINDOW, length=4, size=2, prot=0
            )
        rec.dtp_event = self.dtp_event
        await self._wait_smc(
            f"{rec.name}.arm",
            lambda: all(mon.seen.values()),
            ARM_BOUND_SMC,
            mon.arm_text,
        )
        rec.arm_ps = int(get_sim_time("ps"))
        cocotb.log.info("%s: pending set armed: %s", rec.name, mon.arm_text())

    @staticmethod
    def _outstanding(items) -> int:
        return sum(1 for it in items if it.resp_code is None and not it.timed_out)

    def _snapshot_outstanding(self, rec) -> dict | None:
        if not hasattr(rec, "dtp_event"):
            return None
        return {
            "outstanding": {
                "SEP_IN": self._outstanding(rec.sep_items),
                "SYS_IN": self._outstanding(rec.sys_items) + (0 if rec.dtp_event.is_set() else 1),
                "JTAG_IN": self._outstanding(rec.jtag_items),
                "EFUSE_JTAG": 0 if rec.ej_event.is_set() else 1,
                "DTP": 0 if rec.dtp_event.is_set() else 1,
            },
            "tasks_done": {k: t.done() for k, t in rec.tasks.items()},
        }

    # --- entry triggers -----------------------------------------------------------------
    def _assert_state(self, mon) -> str:
        return (
            f"{mon.state_text}, rst_cool_ni={self._v('rst_cool_ni')}, "
            f"tb_cfg_flr_pf_active={self._v('tb_cfg_flr_pf_active')}, "
            f"tb_rst_cool_from_flr={self._v('tb_rst_cool_from_flr')}"
        )

    async def _wait_assert(self, rec, mon, source: str) -> None:
        n = await self._wait_smc(
            f"{rec.name}.primary_assert({source})",
            lambda: mon.phase != "pre",
            ASSERT_BOUND_SMC,
            lambda: self._assert_state(mon),
        )
        rec.assert_wait_smc = n

    async def _wait_release(self, rec, mon, source: str) -> None:
        await self._wait_smc(
            f"{rec.name}.primary_release({source})",
            lambda: mon.phase == "post",
            RELEASE_BOUND_SMC,
            lambda: self._assert_state(mon),
        )

    async def _pin_pulse(self, rec) -> None:
        clk = cocotb.top.clk_ref_i
        low = 0
        for _ in range(PIN_LOW_SAMPLES):
            await RisingEdge(clk)
            low += int(self._v("rst_cool_ni") == 0)
        rec.pin_low_samples = low
        await self._send(SmcResetOp.COOL_RST_HI)

    async def _pin_entry(self, rec, mon) -> None:
        await RisingEdge(cocotb.top.clk_ref_i)
        await self._send(SmcResetOp.COOL_RST_LO)
        pulse = cocotb.start_soon(self._pin_pulse(rec))
        await self._wait_assert(rec, mon, "rst_cool_ni low")
        await pulse
        assert rec.pin_low_samples == PIN_LOW_SAMPLES, f"pin low {rec.pin_low_samples} samples"
        rec.source_end_ref = self.ref_n
        await self._wait_release(rec, mon, "rst_cool_ni high")

    async def _jtag_entry(self, rec, mon) -> None:
        dut = cocotb.top
        await RisingEdge(dut.clk_ref_i)
        rec.ref_write = self.ref_n
        dut.tb_jtag_reset_ctrl.value = _pack(cool_ovrd=1, cool_val=0)
        await self._wait_assert(rec, mon, "override val 0")
        rec.sources_at_assert = (self._v("rst_cool_ni"), self._v("tb_cfg_flr_pf_active"))
        held = 0

        def _held_enough() -> bool:
            nonlocal held
            held += int(self._v("rst_primary_smc_clk_no") == 0)
            return held >= PIN_LOW_SAMPLES

        await self._wait_ref(
            f"{rec.name}.override_hold",
            _held_enough,
            JTAG_HOLD_BOUND_REF,
            lambda: f"primary low samples {held}",
        )
        rec.ref_val1 = self.ref_n
        dut.tb_jtag_reset_ctrl.value = _pack(cool_ovrd=1, cool_val=1)
        await self._wait_ref(
            f"{rec.name}.override_cool_high",
            lambda: self._v("tb_rst_cool_from_flr") == 1,
            JTAG_VAL1_BOUND_REF,
            lambda: f"tb_rst_cool_from_flr={self._v('tb_rst_cool_from_flr')}",
        )
        dut.tb_jtag_reset_ctrl.value = 0
        await self._wait_release(rec, mon, "override val 1")

    async def _flr_entry(self, rec, mon) -> None:
        dut = cocotb.top
        await RisingEdge(dut.clk_ref_i)
        dut.tb_cfg_flr_pf_active.value = 1
        rec.ref_flr = self.ref_n
        await self._wait_ref(
            f"{rec.name}.cool_from_flr_fall",
            lambda: self._v("tb_rst_cool_from_flr") == 0,
            COOL_FLR_BOUND_REF,
            lambda: f"tb_rst_cool_from_flr={self._v('tb_rst_cool_from_flr')}",
        )
        rec.cool_fall_ref = self.ref_n
        await self._wait_assert(rec, mon, "tb_rst_cool_from_flr low")
        await self._wait_ref(
            f"{rec.name}.cool_from_flr_rise",
            lambda: self._v("tb_rst_cool_from_flr") == 1,
            COOL_FLR_BOUND_REF,
            lambda: f"tb_rst_cool_from_flr={self._v('tb_rst_cool_from_flr')}",
        )
        rec.cool_low_ref = self.ref_n - rec.cool_fall_ref
        await self._wait_release(rec, mon, "tb_rst_cool_from_flr high")

    # --- after the release --------------------------------------------------------------
    @staticmethod
    def _late_code(event):
        if not event.is_set() or event.data is None:
            return None
        return SmcSysAxiDriver._resp_code(event.data)

    async def _after_release(self, rec, mon) -> None:
        dut = cocotb.top
        for link, task in rec.tasks.items():
            await self._join(link, task, f"{rec.name}_{link}_abort")
        assert rec.ej_event.is_set(), f"{rec.name}: the eFuse JTAG read is still pending"
        self.ej.backend.read_if.r_channel.pause = False
        dut.tb_sep_axi_r_hold.value = 0
        dut.tb_sys_axi_r_hold.value = 0
        dut.tb_output_axi_resp_hold.value = 0
        groups = {
            "SEP_IN": rec.sep_items,
            "SYS_IN": rec.sys_items,
            "JTAG_IN": rec.jtag_items,
        }
        rec.aborted = {k: sum(1 for it in v if it.reset_aborted) for k, v in groups.items()}
        rec.late = {
            k: sorted({it.resp_code for it in v if it.resp_code is not None})
            for k, v in groups.items()
        }
        rec.aborted["SYS_IN"] += int(rec.dtp_event.is_set() and rec.dtp_event.data is None)
        rec.aborted["EFUSE_JTAG"] = int(rec.ej_event.is_set() and rec.ej_event.data is None)
        rec.aborted["DTP"] = int(rec.dtp_event.is_set() and rec.dtp_event.data is None)
        rec.late["EFUSE_JTAG"] = [c for c in (self._late_code(rec.ej_event),) if c is not None]
        rec.late["DTP"] = [c for c in (self._late_code(rec.dtp_event),) if c is not None]
        rec.pending_counts = {link: mon.snap(link) for link in LINKS}
        self.dtp_event = None

    async def _effects(self, rec) -> None:
        name = rec.name
        scratch = await self.csr_read(f"{name}_SCRATCH_AFTER", SCRATCH0, length=8)
        threshold = await self.csr_read(f"{name}_THRESHOLD_AFTER", THRESHOLD)
        rec.scratch_after, rec.threshold_after = scratch & 0xFFFF_FFFF, threshold
        if name == "flr":
            rec.isolate_after = await self.csr_read(f"{name}_ISOLATE_SMC", ISOLATE_SMC)
            await self.csr_write(f"{name}_ISOLATE_SMC_CLEAR", ISOLATE_SMC, ISOLATE_SMC_BIT)
            rec.isolate_cleared = await self.csr_read(f"{name}_ISOLATE_SMC_RB", ISOLATE_SMC)

    @staticmethod
    def _delta(before: dict, after: dict) -> dict:
        return {ch: after[ch] - before[ch] for ch in CHANNELS}

    async def _fresh(self, rec, mon) -> None:
        name = rec.name
        rec.fresh = {}
        rec.fresh_idx = {}
        rec.resp = {}
        rec.words = {link: _entry_word(base, name) for link, base in FRESH_BASE.items()}
        words = rec.words
        start_sep_in = mon.n
        wr = await self._okay(
            "SEP", SmcSysAxiOp.WRITE, f"{name}_sep_wr", FRESH_SEP, words["SEP_IN"]
        )
        read = await self._okay("SEP", SmcSysAxiOp.READ, f"{name}_sep_rd", FRESH_SEP)
        rec.fresh_idx["SEP_IN"] = (start_sep_in, mon.n)
        rec.resp["SEP_IN"] = (wr.resp_code, read.resp_code)
        rec.sep_read = read.rdata
        rec.l2_pending = (self._v("tb_cpu_l2_pending_ar"), self._v("tb_cpu_l2_pending_aw"))
        await self._effects(rec)
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()

        start_sys_in = mon.n
        wr = await self._okay(
            "SYS", SmcSysAxiOp.WRITE, f"{name}_sys_wr", FRESH_SYS, words["SYS_IN"]
        )
        read = await self._okay("SYS", SmcSysAxiOp.READ, f"{name}_sys_rd", FRESH_SYS)
        rec.fresh_idx["SYS_IN"] = (start_sys_in, mon.n)
        rec.resp["SYS_IN"] = (wr.resp_code, read.resp_code)
        rec.sys_read = read.rdata

        start_jtag_in = mon.n
        wr = await self._okay(
            "JTAG", SmcSysAxiOp.WRITE, f"{name}_jtag_wr", FRESH_JTAG, words["JTAG_IN"]
        )
        read = await self._okay("JTAG", SmcSysAxiOp.READ, f"{name}_jtag_rd", FRESH_JTAG)
        rec.fresh_idx["JTAG_IN"] = (start_jtag_in, mon.n)
        rec.resp["JTAG_IN"] = (wr.resp_code, read.resp_code)
        rec.jtag_read = read.rdata

        start_sys_out = mon.n
        writes0, reads0 = self._v("tb_output_axi_write_count"), self._v("tb_output_axi_read_count")
        wr = await self._okay(
            "JTAG", SmcSysAxiOp.WRITE, f"{name}_ext_wr", EXT_FRESH, words["SYS_OUT"]
        )
        writes1 = self._v("tb_output_axi_write_count")
        read = await self._okay("JTAG", SmcSysAxiOp.READ, f"{name}_ext_rd", EXT_FRESH)
        reads1 = self._v("tb_output_axi_read_count")
        rec.fresh_idx["SYS_OUT"] = (start_sys_out, mon.n)
        rec.ext = (writes1 - writes0, reads1 - reads0, read.rdata & 0xFFFF_FFFF)
        rec.resp["SYS_OUT"] = (wr.resp_code, read.resp_code)

        await wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC)
        self._bound(f"{name}.fuse_sense", f"{FUSE_SENSE_BOUND_SMC}clk_smc_i", "sense done")
        start_efuse_jtag = mon.n
        rec.efuse_value = await self._ej_read(f"{name}_efuse", EFUSE_FRESH_WORD)
        rec.fresh_idx["EFUSE_JTAG"] = (start_efuse_jtag, mon.n)

        start_periph = mon.n
        read = await self._okay("SEP", SmcSysAxiOp.READ, f"{name}_uart", UART0_REG, length=4)
        rec.fresh_idx["PERIPH"] = (start_periph, mon.n)
        rec.uart_value = read.rdata & 0xFFFF_FFFF
        rec.resp["PERIPH"] = (None, read.resp_code)

        if name != "flr":
            await self._flr_counters(f"{name}_rearm")
        assert self._v("tb_axil_dtp_csr_active") == 0, (
            f"{name}: the DTP link is active before the fresh request"
        )
        self.dtp_event = self.env.sys_in_axi_agent.driver.axi.init_read(
            address=DTP_WINDOW, length=4, size=2, prot=0
        )
        rec.dtp_wait = await self._wait_smc(
            f"{name}.dtp_request",
            lambda: self._v("tb_axil_dtp_csr_active") == 1,
            DTP_REQUEST_BOUND_SMC,
            lambda: f"tb_axil_dtp_csr_active={self._v('tb_axil_dtp_csr_active')}",
        )
        await ClockCycles(cocotb.top.clk_smc_i, TAIL_EDGES)
        self._bound(f"{name}.tail", f"{TAIL_EDGES}clk_smc_i", "counted window")
        for link, (first, last) in rec.fresh_idx.items():
            lag = RESPONSE_COUNT_LAG if link == "SYS_OUT" else 0
            rec.fresh[link] = self._delta(mon.hist[first][link], mon.hist[last + lag][link])

    # --- orchestration ------------------------------------------------------------------
    async def _entry(self, name: str, trigger) -> None:
        rec = SimpleNamespace(name=name)
        self.records[name] = rec
        await self._prepare(name)
        mon = _LinkMonitor(self, lambda: self._snapshot_outstanding(rec))
        rec.mon = mon
        mon.start()
        await self._arm(rec, mon)
        await trigger(rec, mon)
        snapshot = mon.assert_state["pre_snapshot"]
        assert snapshot is not None, f"{name}: the pending set was not armed at the assertion"
        rec.outstanding = snapshot["outstanding"]
        rec.tasks_done_at_assert = snapshot["tasks_done"]
        await self._after_release(rec, mon)
        await self._fresh(rec, mon)
        await mon.finish()
        planned = sum(rec.outstanding[k] for k in PLANNED_ITEMS)
        self._stamp(f"{name.upper()}_ENTRY", planned, mon.assert_ps)

    async def body(self) -> None:
        dut = cocotb.top
        counter = cocotb.start_soon(self._count_ref_edges())
        dut.tb_cfg_flr_pf_active.value = 0
        dut.tb_jtag_reset_ctrl.value = 0
        await wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC)
        self._bound("SETUP.fuse_sense", f"{FUSE_SENSE_BOUND_SMC}clk_smc_i", "sense done")
        idle_axil_master_inputs(dut, "ej_axi")
        self.ej = OcahAxiLiteMasterAgent.from_prefix(
            dut,
            "ej_axi",
            dut.clk_smc_i,
            dut.rst_primary_smc_clk_no,
            name="smc_ej_axil",
            reset_active_level=False,
        ).sequence
        self.ej_pre_value = await self._ej_read("SETUP", EFUSE_FRESH_WORD)
        await self._prepare("SETUP", flr=True)
        self._stamp("SETUP", self.accesses)

        await self._glitch()
        await self._entry("pin", self._pin_entry)
        await self._entry("jtag", self._jtag_entry)
        await self._entry("flr", self._flr_entry)
        self._ref_run = False
        await counter
        self._report()

    # --- evidence -----------------------------------------------------------------------
    @staticmethod
    def _joined(values) -> str:
        return "/".join(str(v) for v in values)

    def _window_effects(self, rec, label: str, fails: list[str]) -> tuple[int, int]:
        mon = rec.mon
        n, cores = mon.window_samples, mon.cores_low
        if n == 0 or cores != n or mon.cold_low:
            fails.append(
                f"{label}: primary low {n} samples, cores held {cores}, cold low {mon.cold_low}; "
                f"{mon.core_violations[:3]} {mon.cold_violations[:3]}"
            )
        if rec.scratch_after != SCRATCH_RESET:
            fails.append(f"{label}: SCRATCH[0] reads 0x{rec.scratch_after:x} after the release")
        if rec.threshold_after != THRESHOLD_RESET:
            fails.append(f"{label}: threshold reads 0x{rec.threshold_after:x} after the release")
        return n, cores

    def _inflight_problems(self, rec) -> list[str]:
        mon = rec.mon
        st = mon.assert_state
        prev = st["prev"]
        problems = []
        if st["holds"] != (1, 1, 1):
            problems.append(f"holds sep/sys/out = {st['holds']}")
        for link, planned in PLANNED_ITEMS.items():
            if rec.outstanding[link] != planned:
                problems.append(f"{link} outstanding {rec.outstanding[link]} != planned {planned}")
            if rec.aborted[link] != rec.outstanding[link]:
                problems.append(
                    f"{link} reset_aborted {rec.aborted[link]} != outstanding {rec.outstanding[link]}"
                )
        if rec.outstanding["DTP"] != 1 or rec.aborted["DTP"] != 1:
            problems.append(
                f"DTP outstanding/aborted {rec.outstanding['DTP']}/{rec.aborted['DTP']}"
            )
        if any(rec.tasks_done_at_assert.values()):
            problems.append(
                f"a pending group finished before the assertion {rec.tasks_done_at_assert}"
            )
        if st["sep_aw_since_arm"] < 1 or st["sep_w_since_arm"] != 0 or prev.get("sep_wvalid"):
            problems.append(
                f"SEP_IN write AW handshakes {st['sep_aw_since_arm']}, W handshakes "
                f"{st['sep_w_since_arm']}, wvalid {prev.get('sep_wvalid')}"
            )
        for key in ("sep_r", "sys_r", "jtag_r", "ej_r", "dtp"):
            if prev.get(key) != 1:
                problems.append(f"{key} not pending at the last sample before the assertion")
        if not st["seen"]["sys_out_ar"]:
            problems.append("no SYS_OUT AR handshake for the external read")
        return problems

    def _report(self) -> None:
        recs = {n: self.records[n] for n in ENTRIES}
        fails: list[str] = []
        lines: list[tuple[str, str]] = []
        obs: dict[str, list[str]] = {
            "OBS-COOL-PHASE-FATE": [],
            "OBS-COOL-RELEASE-LATENCY": [],
            "OBS-JTAG-COOL-OVERRIDE": [],
            "OBS-VALID-FIRST-EDGE": [],
        }

        glitch = self.glitch
        if glitch.stable != glitch.total or glitch.total != 95 or glitch.low_driven != 31:
            fails.append(f"CHK-COOL-GLITCH-NO-ASSERT: {glitch.bad[:3]}")
        setup_scratch, setup_threshold = self.ref_rb["SETUP"]
        if setup_scratch != SCRATCH_REF or glitch.scratch != SCRATCH_REF:
            fails.append(
                f"CHK-COOL-GLITCH-NO-ASSERT: SCRATCH[0] reads 0x{setup_scratch:x} before and "
                f"0x{glitch.scratch:x} after the pulse, want 0x{SCRATCH_REF:x}"
            )
        lines.append(
            (
                "CHK-COOL-GLITCH-NO-ASSERT",
                f"{glitch.low_driven}-sample low pulse; primary_smc/primary_ref/cold stayed 1 at "
                f"{glitch.stable}/{glitch.total} edges; SCRATCH[0] read 0x{setup_scratch:X} "
                f"before and 0x{glitch.scratch:X} after the pulse (want 0x{SCRATCH_REF:X})",
            )
        )

        cool, flr_req = recs["jtag"].sources_at_assert
        if (cool, flr_req) != (1, 0):
            fails.append(
                f"CTRL-JTAG-ENTRY-SOURCES-IDLE/CHK-JTAG-COOL-OVERRIDE-ENTRY: rst_cool_ni={cool} "
                f"tb_cfg_flr_pf_active={flr_req} at the assertion, want 1/0"
            )
        lines.append(
            (
                "CTRL-JTAG-ENTRY-SOURCES-IDLE",
                f"rst_cool_ni={cool} tb_cfg_flr_pf_active={flr_req} at the override assertion "
                "(pin and FLR idle)",
            )
        )
        for name, token, head in (
            ("pin", "CHK-COOL-PIN-PRIMARY-EFFECTS", ""),
            ("jtag", "CHK-JTAG-COOL-OVERRIDE-ENTRY", "override val=0 -> "),
        ):
            rec = recs[name]
            n, cores = self._window_effects(rec, token, fails)
            scratch_before, threshold_before = self.ref_rb[name]
            if (scratch_before, threshold_before) != (SCRATCH_REF, THRESHOLD_REF):
                fails.append(
                    f"{token}: pre-reset readback SCRATCH[0] 0x{scratch_before:x} threshold "
                    f"0x{threshold_before:x}, want 0x{SCRATCH_REF:x}/0x{THRESHOLD_REF:x}"
                )
            lines.append(
                (
                    token,
                    f"{head}primary low={n} edges, cores held {cores}/{n}, SCRATCH[0] "
                    f"0x{scratch_before:X} -> 0x{rec.scratch_after:x}, threshold "
                    f"0x{threshold_before:x} -> 0x{rec.threshold_after:x} (pre-reset values read "
                    f"back after writing 0x{SCRATCH_REF:X}/0x{THRESHOLD_REF:x})",
                )
            )

        flr = recs["flr"]
        scratch_before, threshold_before = self.ref_rb["flr"]
        if (
            flr.cool_low_ref <= 0
            or flr.mon.window_samples == 0
            or flr.isolate_after != ISOLATE_SMC_BIT
            or flr.isolate_cleared != 0
            or (scratch_before, threshold_before) != (SCRATCH_REF, THRESHOLD_REF)
            or (flr.scratch_after, flr.threshold_after) != (SCRATCH_RESET, THRESHOLD_RESET)
        ):
            fails.append(
                f"CHK-FLR-ENTRY-PRIMARY: cool low {flr.cool_low_ref} ref, primary low "
                f"{flr.mon.window_samples}, ISOLATE_REQ_SMC 0x{flr.isolate_after:x} -> "
                f"0x{flr.isolate_cleared:x}, SCRATCH[0] 0x{scratch_before:x} -> "
                f"0x{flr.scratch_after:x} (want 0x{SCRATCH_REF:x} -> 0x{SCRATCH_RESET:x}), "
                f"threshold 0x{threshold_before:x} -> 0x{flr.threshold_after:x} (want "
                f"0x{THRESHOLD_REF:x} -> 0x{THRESHOLD_RESET:x})"
            )
        lines.append(
            (
                "CHK-FLR-ENTRY-PRIMARY",
                f"cool_from_flr low {flr.cool_low_ref} ref cycles, primary low, ISOLATE_REQ_SMC "
                f"0x{flr.isolate_after:x} -> 0x{flr.isolate_cleared:x}, SCRATCH[0] "
                f"0x{scratch_before:X} -> 0x{flr.scratch_after:x}, threshold "
                f"0x{threshold_before:x} -> 0x{flr.threshold_after:x} (pre-reset values read "
                f"back after writing 0x{SCRATCH_REF:X}/0x{THRESHOLD_REF:x})",
            )
        )

        def fresh(token, attr, link):
            bad = [
                f"{n}: 0x{getattr(r, attr):x} want 0x{r.words[link]:x}"
                for n, r in recs.items()
                if getattr(r, attr) != r.words[link]
            ]
            if bad:
                fails.append(f"{token}: {link} read wrong {bad}")

        def resp(link, idx):
            return self._joined(recs[n].resp[link][idx] for n in ENTRIES)

        def words(attr, width=16):
            return self._joined(f"0x{getattr(recs[n], attr):0{width}x}" for n in ENTRIES)

        def written(link, width=16):
            return self._joined(f"0x{recs[n].words[link]:0{width}x}" for n in ENTRIES)

        fresh("CHK-FRESH-ACCESS-SYS-IN", "sys_read", "SYS_IN")
        lines.append(
            (
                "CHK-FRESH-ACCESS-SYS-IN",
                f"pin/jtag/flr: BRESP {resp('SYS_IN', 0)}, RRESP {resp('SYS_IN', 1)}, read "
                f"{words('sys_read')} (written this entry {written('SYS_IN')})",
            )
        )
        fresh("CHK-FRESH-ACCESS-JTAG-IN", "jtag_read", "JTAG_IN")
        lines.append(
            (
                "CHK-FRESH-ACCESS-JTAG-IN",
                f"pin/jtag/flr: BRESP {resp('JTAG_IN', 0)}, RRESP {resp('JTAG_IN', 1)}, read "
                f"{words('jtag_read')} (written this entry {written('JTAG_IN')})",
            )
        )
        fresh("CHK-FRESH-ACCESS-SEP-IN", "sep_read", "SEP_IN")
        l2 = {n: r.l2_pending for n, r in recs.items()}
        if any(p != (0, 0) for p in l2.values()):
            fails.append(f"CHK-FRESH-ACCESS-SEP-IN: L2 pending AR/AW {l2}")
        lines.append(
            (
                "CHK-FRESH-ACCESS-SEP-IN",
                f"pin/jtag/flr: BRESP {resp('SEP_IN', 0)}, RRESP {resp('SEP_IN', 1)}, read "
                f"{words('sep_read')} (written this entry {written('SEP_IN')}), L2 pending AR/AW "
                f"{self._joined(f'{ar}/{aw}' for ar, aw in (l2[n] for n in ENTRIES))}",
            )
        )
        ext = {n: r.ext for n, r in recs.items()}
        if any(e != (1, 1, recs[n].words["SYS_OUT"]) for n, e in ext.items()):
            fails.append(f"CHK-FRESH-ACCESS-SYS-OUT: write/read count deltas and data {ext}")
        lines.append(
            (
                "CHK-FRESH-ACCESS-SYS-OUT",
                f"pin/jtag/flr via JTAG_IN: write count "
                f"{self._joined(f'+{ext[n][0]}' for n in ENTRIES)}, read count "
                f"{self._joined(f'+{ext[n][1]}' for n in ENTRIES)}, BRESP {resp('SYS_OUT', 0)}, "
                f"RRESP {resp('SYS_OUT', 1)}, read "
                f"{self._joined(f'0x{ext[n][2]:08x}' for n in ENTRIES)} "
                f"(written this entry {written('SYS_OUT', 8)})",
            )
        )
        efuse = {n: r.efuse_value for n, r in recs.items()}
        if EFUSE_FRESH_EXPECT:
            if self.ej_pre_value != EFUSE_FRESH_EXPECT or any(
                v != EFUSE_FRESH_EXPECT for v in efuse.values()
            ):
                fails.append(
                    f"CHK-FRESH-ACCESS-EFUSE-JTAG: {efuse}, pre-reset 0x{self.ej_pre_value:x}, "
                    f"expected 0x{EFUSE_FRESH_EXPECT:x} ({EFUSE_FRESH_SOURCE})"
                )
            efuse_text = (
                f"pin/jtag/flr: read completed, word {words('efuse_value', 8)} vs expected "
                f"0x{EFUSE_FRESH_EXPECT:08x} from {EFUSE_FRESH_SOURCE}; pre-reset read "
                f"0x{self.ej_pre_value:08x} (stability leg)"
            )
        else:
            for n in ENTRIES:
                cocotb.log.info("OBS-EFUSE-FRESH-WORD: word=0x%08x", recs[n].efuse_value)
            efuse_text = (
                f"pin/jtag/flr: read completed OKAY; {EFUSE_FRESH_SOURCE} is 0, so the word is "
                f"not graded (completion only, value on OBS-EFUSE-FRESH-WORD)"
            )
        lines.append(("CHK-FRESH-ACCESS-EFUSE-JTAG", efuse_text))
        uart = {n: r.uart_value for n, r in recs.items()}
        if any(v != UART0_RESET for v in uart.values()):
            fails.append(f"CHK-FRESH-ACCESS-PERIPH: UART0 register {uart}")
        lines.append(
            (
                "CHK-FRESH-ACCESS-PERIPH",
                f"pin/jtag/flr: UART0 register RRESP {resp('PERIPH', 1)}, value "
                f"{words('uart_value', 1)} vs reset value 0x{UART0_RESET:x}",
            )
        )

        orphan = [r.mon.orphan[link] for r in recs.values() for link in ORPHAN_LINKS]
        orphan = [o for o in orphan if o]
        delta_bad = []
        pairs = 0
        for n, r in recs.items():
            for link in ORPHAN_LINKS:
                d = r.fresh[link]
                want = (
                    {"aw": 0, "w": 0, "b": 0, "ar": 1, "r": 1}
                    if link == "EFUSE_JTAG"
                    else {"aw": 1, "w": 1, "b": 1, "ar": 1, "r": 1}
                )
                pairs += 1
                if d != want:
                    delta_bad.append(f"{n} {link}: {d}")
        if orphan or delta_bad or pairs < 15:
            fails.append(f"CHK-NO-ORPHAN-RESPONSE: {orphan} {delta_bad} pairs={pairs}")
        deltas = "; ".join(
            f"{link} "
            + "|".join(
                "/".join(str(recs[n].fresh[link][ch]) for ch in ("ar", "r", "aw", "b"))
                for n in ENTRIES
            )
            for link in ORPHAN_LINKS
        )
        lines.append(
            (
                "CHK-NO-ORPHAN-RESPONSE",
                f"per link R<=AR and B<=AW at every edge, orphan responses {len(orphan)}; fresh "
                f"deltas AR/R/AW/B pin|jtag|flr: {deltas}; {pairs} link-entry pairs checked",
            )
        )

        def valid_check(token, links):
            bad = []
            per_entry = {}
            for link in links:
                for n, r in recs.items():
                    edges = r.mon.valid_edges[link]
                    per_entry.setdefault(link, []).append(edges)
                    if edges == 0 or r.mon.valid_violations[link]:
                        bad.append(f"{n} {link}: {edges} edges {r.mon.valid_violations[link][:3]}")
                    if not r.mon.live[link]:
                        bad.append(f"{n} {link}: no graded VALID high outside the reset window")
            if bad:
                fails.append(f"{token}: {bad}")
            return per_entry, violations(links)

        def live_text(links):
            """Live control: the graded VALIDs each link raised outside the reset window per
            entry, and the channels that never did, whose VALID-low result is not claimed."""
            live = "; ".join(
                f"{link} " + "|".join(",".join(sorted(recs[n].mon.live[link])) for n in ENTRIES)
                for link in links
            )
            idle = sorted(
                {
                    f"{link} {ch}"
                    for link in links
                    for r in recs.values()
                    for ch in VALID_RULES[link][0]
                    if ch not in r.mon.live[link]
                }
            )
            return (
                f"live control: VALIDs high outside the window pin|jtag|flr {live}; no traffic "
                f"outside the window, not claimed: {', '.join(idle) or 'none'}"
            )

        def violations(links):
            return sum(len(r.mon.valid_violations[link]) for r in recs.values() for link in links)

        per, nviol = valid_check(
            "CHK-VALID-LOW-INBOUND", ("SYS_IN", "JTAG_IN", "SEP_IN", "EFUSE_JTAG")
        )
        edges = per["SYS_IN"]
        lines.append(
            (
                "CHK-VALID-LOW-INBOUND",
                f"B/R VALID low at {sum(edges)} edges x 4 links x 3 entries (per entry "
                f"{self._joined(edges)}); {nviol} violations; "
                f"{live_text(('SYS_IN', 'JTAG_IN', 'SEP_IN', 'EFUSE_JTAG'))}",
            )
        )
        per, nviol = valid_check("CHK-VALID-LOW-SYS-OUT", ("SYS_OUT", "PERIPH"))
        edges = per["SYS_OUT"]
        lines.append(
            (
                "CHK-VALID-LOW-SYS-OUT",
                f"AW/W/AR VALID low from edge 2 at {sum(edges)} edges x 2 links x 3 entries "
                f"(per entry {self._joined(edges)}); {nviol} violations; "
                f"{live_text(('SYS_OUT', 'PERIPH'))}",
            )
        )
        per, nviol = valid_check("CHK-VALID-LOW-CLUSTER", ("CPU_FRONT",))
        l2f_before = self._joined(recs[n].mon.assert_state["prev"].get("l2f_r") for n in ENTRIES)
        live = {
            n: (
                r.mon.pre_cnt["CPU_FRONT"]["r"],
                r.mon.cnt["CPU_FRONT"]["b"],
                r.mon.cnt["CPU_FRONT"]["r"],
            )
            for n, r in recs.items()
        }
        dead = [f"{n}: pre R/post B/post R {v}" for n, v in live.items() if 0 in v]
        if dead:
            fails.append(f"CHK-VALID-LOW-CLUSTER: L2F B/R VALID never seen high outside {dead}")
        lines.append(
            (
                "CHK-VALID-LOW-CLUSTER",
                f"L2F B/R VALID low at {sum(per['CPU_FRONT'])} edges x 3 entries (per entry "
                f"{self._joined(per['CPU_FRONT'])}; L2F R VALID at the sample before the "
                f"assertion {l2f_before}); {nviol} violations; live control: L2F R handshakes "
                f"between arm and assertion / B and R handshakes after the release "
                f"{self._joined('/'.join(str(x) for x in live[n]) for n in ENTRIES)} (each > 0); "
                f"MMIO leg not driven (c-fw image deferred)",
            )
        )
        mmio_edges = [r.mon.valid_edges["CPU_MMIO"] for r in recs.values()]
        cocotb.log.info("INFO-CELL-NOT-DRIVABLE: MMIO rows (c-fw image not staged)")
        cocotb.log.info(
            "CPU MMIO AW/W/AR sampled, not claimed: %s edges (per entry %s), %d VALID high",
            sum(mmio_edges),
            self._joined(mmio_edges),
            violations(("CPU_MMIO",)),
        )

        dtp_bad = []
        dtp_pre = {}
        for n, r in recs.items():
            dtp_pre[n] = r.mon.assert_state["prev"].get("dtp")
            if dtp_pre[n] != 1:
                dtp_bad.append(f"{n}: not active before the reset")
            if r.mon.valid_edges["DTP"] == 0 or r.mon.valid_violations["DTP"]:
                dtp_bad.append(
                    f"{n}: {r.mon.valid_edges['DTP']} edges {r.mon.valid_violations['DTP'][:3]}"
                )
        if dtp_bad:
            fails.append(f"CHK-DTP-LINK-REQUEST-PHASE/CHK-VALID-LOW-DTP: {dtp_bad}")
        lines.append(
            (
                "CHK-DTP-LINK-REQUEST-PHASE",
                f"pin/jtag/flr: active before {self._joined(dtp_pre[n] for n in ENTRIES)}, active "
                f"samples in reset from edge 2 "
                f"{self._joined(len(recs[n].mon.valid_violations['DTP']) for n in ENTRIES)}, "
                f"active after fresh request in "
                f"{self._joined(recs[n].dtp_wait for n in ENTRIES)} clk_smc_i edges "
                f"(request phase only; the response vector is not graded)",
            )
        )
        cocotb.log.info(
            "INFO-DTP-RESP-TIEOFF: response vector tied to 0 in the bench, not graded "
            "(nonzero samples %s)",
            self._joined(recs[n].mon.dtp_resp_nonzero for n in ENTRIES),
        )
        dtp_edges = [r.mon.valid_edges["DTP"] for r in recs.values()]
        lines.append(
            (
                "CHK-VALID-LOW-DTP",
                f"AW/W/AR VALID low from edge 2 at {sum(dtp_edges)} edges x 3 entries (per entry "
                f"{self._joined(dtp_edges)}); high before reset "
                f"{sum(1 for v in dtp_pre.values() if v == 1)}/3",
            )
        )

        inflight = {n: self._inflight_problems(r) for n, r in recs.items()}
        if any(inflight.values()):
            fails.append(f"CHK-INFLIGHT-AT-ASSERT: {inflight}")
        out = {k: self._joined(recs[n].outstanding[k] for n in ENTRIES) for k in PLANNED_ITEMS}
        out["DTP"] = self._joined(recs[n].outstanding["DTP"] for n in ENTRIES)
        aborted = {k: self._joined(recs[n].aborted[k] for n in ENTRIES) for k in out}
        mmio = self._joined(
            recs[n].mon.assert_state["mmio_ar"] + recs[n].mon.assert_state["mmio_aw"]
            for n in ENTRIES
        )
        lines.append(
            (
                "CHK-INFLIGHT-AT-ASSERT",
                f"pin/jtag/flr: outstanding at assert SEP_IN {out['SEP_IN']} SYS_IN "
                f"{out['SYS_IN']} JTAG_IN {out['JTAG_IN']} eFuse {out['EFUSE_JTAG']} dtp "
                f"{out['DTP']} mmio {mmio}; reset_aborted SEP_IN {aborted['SEP_IN']} SYS_IN "
                f"{aborted['SYS_IN']} JTAG_IN {aborted['JTAG_IN']} eFuse {aborted['EFUSE_JTAG']} "
                f"dtp {aborted['DTP']}",
            )
        )

        self._observations(recs, obs)
        for token, key in (
            ("CHK-OBS-PHASE-FATE", "OBS-COOL-PHASE-FATE"),
            ("CHK-OBS-RELEASE-LATENCY", "OBS-COOL-RELEASE-LATENCY"),
            ("CHK-OBS-JTAG-OVERRIDE-ORDER", "OBS-JTAG-COOL-OVERRIDE"),
            ("CHK-OBS-VALID-FIRST-EDGE", "OBS-VALID-FIRST-EDGE"),
        ):
            for line in obs[key]:
                cocotb.log.info("%s", line)
            lines.append((token, f"recorded {len(obs[key])} {key} lines"))

        fence_text = self._fence_check(recs, fails)
        lines.append(("CHK-NONVAC", fence_text))
        lines.append(("CHK-TIMEOUT-PATHS", self._timeout_summary()))

        for token, text in lines:
            if not any(f.startswith(token) or token in f.split(":", 1)[0] for f in fails):
                cocotb.log.info("%s: %s", token, text)
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: wait %s", line)
        assert not fails, "contract checkers failed:\n" + "\n".join(f"FAIL {f}" for f in fails)

    def _observations(self, recs, obs) -> None:
        item_counts = {
            "SEP_IN": 4,
            "SYS_IN": 4,
            "JTAG_IN": 2,
            "SYS_OUT": 1,
            "EFUSE_JTAG": 1,
            "DTP": 1,
            "PERIPH": 1,
            "CPU_FRONT": 6,
            "CPU_MMIO": 0,
        }
        for n, r in recs.items():
            aborted = {
                "SEP_IN": r.aborted["SEP_IN"],
                "SYS_IN": r.aborted["SYS_IN"],
                "JTAG_IN": r.aborted["JTAG_IN"],
                "SYS_OUT": int(r.jtag_items[1].reset_aborted),
                "EFUSE_JTAG": r.aborted["EFUSE_JTAG"],
                "DTP": r.aborted["DTP"],
                "PERIPH": int(r.sep_items[2].reset_aborted),
                "CPU_FRONT": sum(
                    int(it.reset_aborted)
                    for it in (*r.sep_items[:2], r.sep_items[3], *r.sys_items[:2], r.jtag_items[0])
                ),
                "CPU_MMIO": 0,
            }
            late = {
                "SEP_IN": r.late["SEP_IN"],
                "SYS_IN": r.late["SYS_IN"],
                "JTAG_IN": r.late["JTAG_IN"],
                "SYS_OUT": [r.jtag_items[1].resp_code]
                if r.jtag_items[1].resp_code is not None
                else [],
                "EFUSE_JTAG": r.late["EFUSE_JTAG"],
                "DTP": r.late["DTP"],
                "PERIPH": [r.sep_items[2].resp_code]
                if r.sep_items[2].resp_code is not None
                else [],
                "CPU_FRONT": [],
                "CPU_MMIO": [],
            }
            for link in item_counts:
                c = r.pending_counts.get(link) or dict.fromkeys(CHANNELS, 0)
                code = ",".join(str(v) for v in late[link]) or "none"
                obs["OBS-COOL-PHASE-FATE"].append(
                    f"OBS-COOL-PHASE-FATE: entry={n} link={link} items={item_counts[link]} "
                    f"aborted={aborted[link]} late_resp={code} ar={c['ar']} r={c['r']} "
                    f"aw={c['aw']} b={c['b']}"
                )
            mon = r.mon
            to_ar = (
                "none"
                if mon.sep_ar_after_release is None
                else (mon.sep_ar_after_release - mon.release_n)
            )
            to_r = (
                "none"
                if mon.sep_r_after_release is None
                else (mon.sep_r_after_release - mon.release_n)
            )
            obs["OBS-COOL-RELEASE-LATENCY"].append(
                f"OBS-COOL-RELEASE-LATENCY: entry={n} release_to_ar={to_ar} release_to_r={to_r} "
                f"clk_smc_i cycles"
            )
            for link, high in mon.first_edge.items():
                obs["OBS-VALID-FIRST-EDGE"].append(
                    f"OBS-VALID-FIRST-EDGE: link={link} entry={n} "
                    f"valids_high_at_first_edge={','.join(high) or 'none'}"
                )
        j = recs["jtag"]
        fall = j.mon.assert_ref - j.ref_write
        rise = j.mon.release_ref - j.ref_val1
        passed = "yes" if fall >= 32 else "no"
        obs["OBS-JTAG-COOL-OVERRIDE"].append(
            f"OBS-JTAG-COOL-OVERRIDE: write_to_fall={fall} value1_to_release={rise} "
            f"deglitch_passed={passed}"
        )

    def _fence_check(self, recs, fails: list[str]) -> str:
        last = recs["flr"].mon
        total_window = sum(r.mon.window_samples for r in recs.values())
        self._stamp("VALID_WINDOW", total_window, last.last_window_ps)
        names = [f[0] for f in self.fence]
        want = ["SETUP", "GLITCH", "PIN_ENTRY", "JTAG_ENTRY", "FLR_ENTRY", "VALID_WINDOW"]
        times = [f[1] for f in self.fence]
        if names != want or any(b <= a for a, b in zip(times, times[1:])):
            fails.append(f"CHK-NONVAC: terms {self.fence}")
        counts = {f[0]: f[2] for f in self.fence}
        floors = {"SETUP": 1, "GLITCH": 95, "VALID_WINDOW": 3 * 3}
        for term in ("PIN_ENTRY", "JTAG_ENTRY", "FLR_ENTRY"):
            floors[term] = 10
        for term, floor in floors.items():
            if counts.get(term, 0) < floor:
                fails.append(f"CHK-NONVAC: term {term} count {counts.get(term)} below {floor}")
        for n, r in recs.items():
            if r.mon.window_samples < 3 or sum(1 for d in r.fresh.values() if d["ar"] == 1) < 5:
                fails.append(f"CHK-NONVAC: {n} reset samples {r.mon.window_samples}")
        return (
            " < ".join(names)
            + " (counts and times per term): "
            + "; ".join(f"{n} t={t}ps count={c}" for n, t, c in self.fence)
            + "; fresh-handshake links per entry "
            + self._joined(sum(1 for d in recs[n].fresh.values() if d["ar"] == 1) for n in ENTRIES)
        )

    def _timeout_summary(self) -> str:
        return (
            f"{len(self._timeout_paths)} bounded waits, bound/last-state per wait, "
            f"{self.expired_waits} expired"
        )
