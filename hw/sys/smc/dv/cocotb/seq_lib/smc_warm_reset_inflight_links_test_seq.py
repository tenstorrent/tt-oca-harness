# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_SEP_SCN_002 ANCHOR: smc_warm_reset_inflight_links_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 8f25395116e6b92eafd0f3052b2452949722c707422b7a24d22060deab3347b1
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_SEP_SCN_VPLAN_DETAIL.md @ artifact_revision 1 ENV: cocotb
"""Warm reset entered through the watchdog reset input and the JTAG override, with accesses pending.

Entries: ``tb_sep_wdt_reset_n`` driven low with a pending set armed, the JTAG warm override
written in one packed store with the bench idle, the armed core-3 watchdog second stage, and a
final watchdog-input reset after the core-3 reset vector is reprogrammed. The pending set is two
SEP_IN reads, a UART0 read and a write whose W beat trails its AW on SEP_IN, two SYS_IN reads
and a read of 0xB000_0000 whose DECERR response is held at SYS_IN, a JTAG_IN scratchpad read,
a JTAG_IN read of 0xB000_0000 held at the SYS_OUT responder and an eFuse JTAG read whose response
is not accepted. ``RESET_CTRL.core3_reset_n`` is 0 for the whole reset sequence.

SYS_IN and SEP_IN answer an address outside the SMC window with DECERR (fabric.adoc, input
fabric), so the access that reaches SYS_OUT goes through JTAG_IN. The leaf drives no traffic on
the CPU MMIO link and runs no firmware image; the MMIO nets are sampled with no MMIO traffic.

Graded: the watchdog input asserts only the warm reset and holds it 32 reference cycles after
the input returns; cores and uncore are held and the primary reset stays high at every sampled
edge of the warm window; no drain is requested; the reset-control, hang-threshold and fabric
configuration registers are kept across both entries; the warm scratch register reads its reset
after the release; one fresh write and read per link completes after the release; no link
answers without a request; the cluster-side VALIDs read 0 while the uncore reset is held; the
armed watchdog asserts the warm reset only at its second stage and a FEED does not withdraw it.
Pending-phase fates, the isolate state, the in-window accesses, the fuse-window accesses, the
SMC_ATTRIBUTES fields and the ROM fetch count are printed as ``OBS-*`` lines and never compared.
"""

from __future__ import annotations

from types import SimpleNamespace

import cocotb
from cocotb.triggers import ClockCycles, FallingEdge, RisingEdge, SimTimeoutError, with_timeout
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import (
    SmcSysAxiDriver,
    SmcSysAxiItem,
    SmcSysAxiOp,
    idle_axil_master_inputs,
)
from ocah_axi_vip import AxiTimingProfile, OcahAxiLiteMasterAgent, clear_profile

from ._one_shot import _OneShot
from .smc_addr_map import (
    cpu_ctrl_u32,
    jtag_smc_reset_ctrl_bit,
    smc_addr,
    smc_indexed_addr,
)
from .smc_base_test_seq import wait_fuse_sense_done
from .smc_output_fabric_vip_utils import (
    OUTBOUND0_FILTER_CONFIG,
    output_fabric_pass_all_cfg_seq,
)

SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
WDT_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_BASE_ADDR")
WDT_TIMEOUT_RESET = smc_addr("SMC_TOP_SMC_CPU_CTRL_WDT_TIMEOUT_RESET_BASE_ADDR")
SMC_ATTRIBUTES = smc_addr("SMC_TOP_SMC_CPU_CTRL_SMC_ATTRIBUTES_BASE_ADDR")
SCRATCH0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
THRESHOLD = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
SCRATCH_COLD = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 0)
SCRATCH_COLD_WARM = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", 0)
UART0_REG = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR", 0
)
EFUSE_WORD = smc_indexed_addr("SMC_TOP_SMC_EFUSE_MAP_SPARE_BASE_ADDR", 0)
WDT3_CTRL = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_CTRL_BASE_ADDR")
WDT3_COUNT = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_COUNT_BASE_ADDR")
WDT3_FEED = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_FEED_BASE_ADDR")
WDT3_KEY = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_KEY_BASE_ADDR")
WDT3_CMP = smc_addr("SMC_TOP_SMC_CLUSTER_CORE3_WDT_CMP_BASE_ADDR")


def _reset_vector(n: int) -> int:
    return smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_RESET_VECTOR_BASE_ADDR", n)


CORE3_RESET_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE3_RESET_N_N0_SCAN_bm")
RESET_CYCLE_COUNT_3 = cpu_ctrl_u32("CPU_CTRL__WDT_TIMEOUT_RESET__RESET_CYCLE_COUNT_3_bm")
ATTRIBUTE_FIELDS = tuple(
    (name, cpu_ctrl_u32(f"CPU_CTRL__SMC_ATTRIBUTES__{name.upper()}_bm"))
    for name in (
        "num_mailboxes",
        "mailbox_depth",
        "num_cores",
        "no_output_remap",
        "sram_size",
        "num_cpu_interrupts",
        "num_ext_interrupts",
        "chiplet_is_primary",
    )
)

# wdt.adoc: the KEY write that unlocks every other write in the block, and the FEED value.
WDT_MAGIC_KEY = 0x51F15E
WDT_FEED_VALUE = 0x0D09_F00D
WDT_CTRL_ARM = (1 << 8) | (1 << 12)
WDT_CMP_VALUE = 0x0010

SEP_READ_A = SPM_BASE + 0x20_000
SEP_READ_B = SPM_BASE + 0x20_008
SEP_WRITE = SPM_BASE + 0x20_100
SYS_READ_A = SPM_BASE + 0x20_040
SYS_READ_B = SPM_BASE + 0x20_048
JTAG_READ = SPM_BASE + 0x20_080
FRESH_SEP = SPM_BASE + 0x20_200
FRESH_SYS = SPM_BASE + 0x20_240
FRESH_JTAG = SPM_BASE + 0x20_280
WINDOW_SPM_WORD = SPM_BASE + 0x20_300
EXT_PENDING = 0xB000_0000
EXT_FRESH = 0xB000_0008
PRELOAD = (SEP_READ_A, SEP_READ_B, SYS_READ_A, SYS_READ_B, JTAG_READ, WINDOW_SPM_WORD)
PRELOAD_WORD = 0x1A71_0000_0000_0000
EXT_PENDING_WORD = 0x1A71_00B0_0000_0000

RESET_VECTOR_BASE_VALUE = 0xC004_1000
WDT_TIMEOUT_REF = 0x0000_0200
THRESHOLD_REF = 0x2345
SCRATCH_REF = 0xC002_0002
COLD_REF = 0x3C3C_C3C3
WARM_REF = 0x5A5A_A5A5
VECTOR3_OBS = SPM_BASE
SEP_WRITE_DATA = 0x5EC0_FFFF_0000_0001
FRESH_SEP_DATA = 0x5EC0_0001_0000_0001
FRESH_SYS_DATA = 0x5EC0_0002_0000_0002
FRESH_JTAG_DATA = 0x5EC0_0003_0000_0003
FRESH_EXT_DATA = 0x5EC0_0004

TAIL_EDGES = 64
RESPONSE_COUNT_LAG = 2
ASSERT_BOUND_SMC = 300
RELEASE_BOUND_SMC = 20_000
FUSE_RISE_BOUND_SMC = 200_000
WDT_FIRST_BOUND_SMC = 200_000
WDT_SECOND_BOUND_SMC = 200_000
WDT_QUIET_EDGES = 200_000
VECTOR_WINDOW_EDGES = 20_000
UNCORE_BOUND_SMC = 300
ARM_BOUND_SMC = 2_000
WARM_HOLD_EDGES = 256
JTAG_HOLD_EDGES = 64
JTAG_CLEAR_REF = 64
FUSE_SENSE_BOUND_SMC = 200_000
JOIN_BOUND_NS = 100_000
EJ_BOUND_NS = 5_000
PENDING_HOLD_CYCLES = 8_000
PENDING_ID_BASE = 0x30
WINDOW_ID_BASE = 0x38
JTAG_PENDING_IDS = (1, 2)
PENDING_SETTLE_NS = 50_000
AXI_BOUND_NS = 50_000
NO_RESPONSE = -1
REQUIRED_TOKENS = (
    "CHK-WDT-INPUT-WARM-ONLY",
    "CHK-WARM-HOLDS-CPU",
    "CHK-CTRL-REGS-KEPT-ACROSS-WARM",
    "CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM",
    "CHK-WARM-SCRATCH-RESET",
    "CHK-FUSE-ALONE-WARM-NOT-PRIMARY",
    "CHK-FRESH-ACCESS-SYS-IN-WARM",
    "CHK-FRESH-ACCESS-JTAG-IN-WARM",
    "CHK-FRESH-ACCESS-SEP-IN-WARM",
    "CHK-FRESH-ACCESS-SYS-OUT-WARM",
    "CHK-FRESH-ACCESS-EFUSE-JTAG-WARM",
    "CHK-FRESH-ACCESS-PERIPH-WARM",
    "CHK-NO-ORPHAN-RESPONSE-WARM",
    "CHK-NO-DRAIN-ON-WARM",
    "CHK-VALID-LOW-CLUSTER-UNCORE-WARM",
    "CHK-JTAG-WARM-OVERRIDE-ENTRY",
    "CHK-WDT-SECOND-STAGE-WARM",
    "CHK-WDT-LATCH-NOT-WITHDRAWN",
    "CHK-OBS-WARM-PHASE-FATE",
    "CHK-OBS-WARM-ISOLATE-STATE",
    "CHK-OBS-WARM-WINDOW-ACCESS",
    "CHK-OBS-FUSE-WINDOW-ACCESS",
    "CHK-OBS-ATTRIBUTES",
    "CHK-OBS-WARM-VECTOR",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)
REF_RELEASE_MIN = 32
PLANNED_ITEMS = {"SEP_IN": 4, "SYS_IN": 3, "JTAG_IN": 2, "EFUSE_JTAG": 1}

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

# Cluster-side VALIDs per link as (channels, first uncore-held sample at which they must read 0).
# Response-side VALIDs are checked from the first sample; request-side VALIDs of a
# synchronous-reset master may clear on the first edge, so they are checked from the second.
VALID_RULES = {"CPU_FRONT": (("b", "r"), 1), "CPU_MMIO": (("aw", "w", "ar"), 2)}

_EXTRA_NAMES = (
    "rst_primary_smc_clk_no",
    "tb_rst_warm_smc_clk_n",
    "tb_fuse_reset_n",
    "tb_cpu_core_resets_n",
    "tb_cpu_uncore_reset_n",
    "tb_cpu_isolate_req",
    "tb_cpu_l2_isolated",
    "tb_cpu_mmio_isolated",
    "tb_cpu_l2_flush_active",
    "tb_cpu_mmio_flush_active",
    "tb_cpu_l2_pending_aw",
    "tb_cpu_l2_pending_w",
    "tb_cpu_l2_pending_ar",
    "tb_cpu_mmio_pending_aw",
    "tb_cpu_mmio_pending_w",
    "tb_cpu_mmio_pending_ar",
    "tb_sep_wdt_reset_n",
    "tb_jtag_reset_ctrl",
    "tb_wdt_first_timeout",
    "tb_wdt_first_timeout_seen",
    "tb_cpu_rom_read_count",
    "tb_sep_axi_r_hold",
    "tb_sys_axi_r_hold",
    "tb_sep_axi_r_drop",
    "tb_sys_axi_r_drop",
    "tb_sep_axi_r_raw_valid",
    "tb_sys_axi_r_raw_valid",
    "tb_output_axi_resp_hold",
    "tb_output_axi_araddr",
    "tb_output_axi_read_count",
    "tb_output_axi_write_count",
    "s_axi_rlast",
    "sys_axi_rlast",
    "jtag_axi_rlast",
)


def _pack(*, warm_ovrd: int, warm_val: int) -> int:
    word = 0
    if warm_ovrd:
        word |= 1 << jtag_smc_reset_ctrl_bit("warm_reset_n_ovrd")
    if warm_val:
        word |= 1 << jtag_smc_reset_ctrl_bit("warm_reset_n_val")
    return word


def _signal_names(links: bool) -> tuple[str, ...]:
    names = list(_EXTRA_NAMES)
    if links:
        for prefix in PREFIX.values():
            for ch in CHANNELS:
                names += [f"{prefix}_{ch}valid", f"{prefix}_{ch}ready"]
        for ch in CHANNELS:
            names += [f"tb_output_axi_{ch}valid", f"tb_output_axi_{ch}ready"]
    for link, vec in VECTOR.items():
        if links or link != "PERIPH":
            names += [f"{vec}_valid", f"{vec}_ready"]
    return tuple(dict.fromkeys(names))


class _WarmMonitor:
    """Passive per-``clk_smc_i`` sampler started before a warm entry.

    A sample is taken half a clock before each capturing edge, so a handshake is a VALID and a
    READY that both read 1 in the sample. The window opens at the first sample at which
    ``tb_rst_warm_smc_clk_n`` reads 0 and closes at the first sample at which it reads 1. With
    ``links`` the monitor also counts the handshakes of every link from its start.
    """

    def __init__(self, seq, *, links: bool = False, on_pre_sample=None) -> None:
        self.seq = seq
        self.links = links
        self.on_pre_sample = on_pre_sample
        dut = cocotb.top
        names = _signal_names(links)
        for name in names:
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        self.handles = {name: getattr(dut, name) for name in names}
        self.stop = False
        self.task = None
        self.n = 0
        self.phase = "pre"
        self.w = 0
        self.u = 0
        self.pre_snapshot = None
        self.assert_n = self.release_n = None
        self.assert_ps = self.release_ps = self.last_window_ps = None
        self.assert_ref = self.release_ref = None
        self.assert_state: dict = {}
        self.window_samples = 0
        self.primary_high = 0
        self.held = 0
        self.isolate_low = 0
        self.violations: list[str] = []
        self.iso = {
            k: [0, None, None] for k in ("l2_isolated", "mmio_isolated", "l2_flush", "mmio_flush")
        }
        self.valid_edges = dict.fromkeys(VALID_RULES, 0)
        self.valid_violations = {link: [] for link in VALID_RULES}
        self.uncore_low_n = 0
        self.cnt = {link: dict.fromkeys(CHANNELS, 0) for link in LINKS}
        self.hist: dict[int, dict] = {}
        self.hs_events = {link: [] for link in ORPHAN_LINKS}
        self.orphan = {link: None for link in ORPHAN_LINKS}
        self.orphan_start = {link: None for link in ORPHAN_LINKS}
        self.base: dict = {}
        self.read_count = 0
        self.since_arm = {"SEP_IN_aw": 0, "SEP_IN_w": 0}
        self.seen = dict.fromkeys(
            ("sep_r", "sys_r", "jtag_r", "ej_r", "sys_out_ar", "sep_aw"), False
        )
        self.prev: dict = {}
        self.last_out_ar_addr = None
        self.pre_cnt = {link: dict.fromkeys(CHANNELS, 0) for link in LINKS}
        self.window_pending = None
        self.release_pending = None
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

    def pending_text(self) -> str:
        g = self._g
        out = []
        for side in ("l2", "mmio"):
            out.append("/".join(str(g(f"tb_cpu_{side}_pending_{k}")) for k in ("aw", "w", "ar")))
        return " ".join(f"{side}={text}" for side, text in zip(("l2", "mmio"), out))

    def _links(self) -> dict:
        g = self._g
        links = {}
        if self.links:
            for link, prefix in PREFIX.items():
                chans = {
                    ch: (g(f"{prefix}_{ch}valid"), g(f"{prefix}_{ch}ready")) for ch in CHANNELS
                }
                if link in RAW_VALID:
                    ready = g(R_DROP[link]) | (g(f"{prefix}_rready") & (1 - g(R_HOLD[link])))
                    chans["r"] = (g(RAW_VALID[link]), ready)
                links[link] = chans
            links["SYS_OUT"] = {
                ch: (g(f"tb_output_axi_{ch}valid"), g(f"tb_output_axi_{ch}ready"))
                for ch in CHANNELS
            }
        for link, vec in VECTOR.items():
            if self.links or link != "PERIPH":
                valid, ready = g(f"{vec}_valid"), g(f"{vec}_ready")
                links[link] = {
                    ch: ((valid >> bit) & 1, (ready >> bit) & 1) for ch, bit in VECTOR_BIT.items()
                }
        return links

    def _sample(self) -> None:
        g = self._g
        self.n += 1
        now = int(get_sim_time("ps"))
        warm = g("tb_rst_warm_smc_clk_n")
        links = self._links()
        hs = None
        if self.links:
            hs = {
                link: {ch: v & r for ch, (v, r) in chans.items()} for link, chans in links.items()
            }
            for link, prefix in (
                ("SEP_IN", "s_axi"),
                ("SYS_IN", "sys_axi"),
                ("JTAG_IN", "jtag_axi"),
            ):
                hs[link]["r"] &= g(f"{prefix}_rlast")
            reads = g("tb_output_axi_read_count")
            hs["SYS_OUT"]["r"] = max(0, reads - self.read_count) if self.n > 1 else 0
            self.read_count = reads
            self._count(hs)
        self.state_text = (
            f"sample {self.n} phase {self.phase} tb_rst_warm_smc_clk_n={warm} "
            f"rst_primary_smc_clk_no={g('rst_primary_smc_clk_no')}"
        )
        if self.phase == "pre":
            if self.links:
                self._pre(links, hs, g)
            if warm == 1 and self.on_pre_sample is not None:
                self.pre_snapshot = self.on_pre_sample()
            if warm == 0:
                self._open_window(now)
        if self.phase == "window":
            if warm == 1:
                self.phase = "post"
                self.release_n, self.release_ps = self.n, now
                self.release_ref = self.seq.ref_n
                self.release_pending = self.pending_text()
            else:
                self._window(now, links, g)
        if self.links and self.phase in ("window", "post"):
            self.hist[self.n] = {link: dict(self.cnt[link]) for link in LINKS}
            self._orphans()
        if self.links:
            self.prev = {
                "sep_r": links["SEP_IN"]["r"][0],
                "sys_r": links["SYS_IN"]["r"][0],
                "jtag_r": links["JTAG_IN"]["r"][0],
                "ej_r": links["EFUSE_JTAG"]["r"][0],
                "sep_wvalid": links["SEP_IN"]["w"][0],
            }

    def _pre(self, links, hs, g) -> None:
        for link in LINKS:
            for ch in CHANNELS:
                self.pre_cnt[link][ch] += hs[link][ch]
        if hs["SYS_OUT"]["ar"]:
            self.last_out_ar_addr = g("tb_output_axi_araddr")
        if hs["SEP_IN"]["aw"]:
            self.since_arm["SEP_IN_aw"] += 1
            self.seen["sep_aw"] = True
        if hs["SEP_IN"]["w"]:
            self.since_arm["SEP_IN_w"] += 1
        for key, link in (
            ("sep_r", "SEP_IN"),
            ("sys_r", "SYS_IN"),
            ("jtag_r", "JTAG_IN"),
            ("ej_r", "EFUSE_JTAG"),
        ):
            if links[link]["r"][0]:
                self.seen[key] = True
        if hs["SYS_OUT"]["ar"] and g("tb_output_axi_araddr") == EXT_PENDING:
            self.seen["sys_out_ar"] = True

    def arm_text(self) -> str:
        addr = "none" if self.last_out_ar_addr is None else f"0x{self.last_out_ar_addr:x}"
        pre = {k: "".join(str(v) for v in c.values()) for k, c in self.pre_cnt.items()}
        return (
            f"seen={self.seen} handshakes since arm (aw,w,b,ar,r)={pre} "
            f"last SYS_OUT AR address={addr}"
        )

    def _open_window(self, now) -> None:
        g = self._g
        self.phase = "window"
        self.assert_n, self.assert_ps, self.assert_ref = self.n, now, self.seq.ref_n
        self.window_pending = self.pending_text()
        self.base = {link: dict(self.cnt[link]) for link in LINKS}
        self.assert_state = {
            "pre_snapshot": self.pre_snapshot,
            "pending": self.pending_text(),
            "prev": dict(self.prev),
            "seen": dict(self.seen),
            "sep_aw_since_arm": self.since_arm["SEP_IN_aw"],
            "sep_w_since_arm": self.since_arm["SEP_IN_w"],
        }
        if self.links:
            self.assert_state["holds"] = (
                g("tb_sep_axi_r_hold"),
                g("tb_sys_axi_r_hold"),
                g("tb_output_axi_resp_hold"),
            )

    def _window(self, now, links, g) -> None:
        self.w += 1
        self.window_samples += 1
        self.last_window_ps = now
        resets = g("tb_cpu_core_resets_n")
        uncore = g("tb_cpu_uncore_reset_n")
        if g("rst_primary_smc_clk_no") == 1:
            self.primary_high += 1
        else:
            self.violations.append(f"sample {self.w}: rst_primary_smc_clk_no=0")
        if resets == 0 and uncore == 0:
            self.held += 1
        else:
            self.violations.append(f"sample {self.w}: core resets=0x{resets:x} uncore={uncore}")
        if g("tb_cpu_isolate_req") == 0:
            self.isolate_low += 1
        for key, name in (
            ("l2_isolated", "tb_cpu_l2_isolated"),
            ("mmio_isolated", "tb_cpu_mmio_isolated"),
            ("l2_flush", "tb_cpu_l2_flush_active"),
            ("mmio_flush", "tb_cpu_mmio_flush_active"),
        ):
            value = g(name)
            rec = self.iso[key]
            rec[0] += value
            rec[1] = value if rec[1] is None else rec[1]
            rec[2] = value
        if uncore == 0:
            self.u += 1
            self.uncore_low_n += 1
            for link, (chans, first) in VALID_RULES.items():
                if self.u >= first:
                    self.valid_edges[link] += 1
                    high = [ch for ch in chans if links[link][ch][0]]
                    if high:
                        self.valid_violations[link].append(f"sample {self.u}: {'/'.join(high)}")

    def _count(self, hs) -> None:
        for link in LINKS:
            for ch in CHANNELS:
                self.cnt[link][ch] += hs[link][ch]
        for link in ORPHAN_LINKS:
            for ch in CHANNELS:
                if hs[link][ch] and len(self.hs_events[link]) < 40:
                    self.hs_events[link].append(f"{ch}@{self.phase}{self.n}")

    def _orphans(self) -> None:
        for link in ORPHAN_LINKS:
            c = self.cnt[link]
            b = self.base[link]
            since = {k: c[k] - b[k] for k in CHANNELS}
            text = (
                f"{link} at monitor sample {self.n} ({self.phase}, window sample {self.w}, "
                f"release at {self.release_n}): AR/R/AW/B from the assertion = "
                f"{since['ar']}/{since['r']}/{since['aw']}/{since['b']}, from the monitor start = "
                f"{c['ar']}/{c['r']}/{c['aw']}/{c['b']}; handshakes {self.hs_events[link]}"
            )
            if self.orphan[link] is None and (since["r"] > since["ar"] or since["b"] > since["aw"]):
                self.orphan[link] = text
            if self.orphan_start[link] is None and (c["r"] > c["ar"] or c["b"] > c["aw"]):
                self.orphan_start[link] = text

    def snap(self, link: str) -> dict:
        return dict(self.cnt[link])


class smc_warm_reset_inflight_links_test_seq(output_fabric_pass_all_cfg_seq):
    """Watchdog-input and JTAG-override warm resets with every link carrying a pending set."""

    def __init__(self, name: str = "smc_warm_reset_inflight_links_test_seq") -> None:
        super().__init__(name)
        self._timeout_paths: list[str] = []
        self.ref_n = 0
        self._ref_run = True
        self.fence: list[tuple[str, int, int]] = []
        self.ej = None
        self.bounded = False
        self.wedged: dict[str, str] = {}
        self.skipped: list[str] = []
        self._token = "CHK-NONVAC"
        self._raw_seq = 0
        self.chain = None
        self.vector = None
        self.fails: list[str] = []
        self.lines: list[tuple[str, str]] = []
        self.obs: dict[str, list[str]] = {
            "OBS-WARM-PHASE-FATE": [],
            "OBS-WARM-ISOLATE-STATE": [],
            "OBS-WARM-WINDOW-ACCESS": [],
            "OBS-ATTRIBUTES": [],
            "OBS-WARM-VECTOR": [],
        }

    @staticmethod
    def _v(name: str) -> int:
        value = getattr(cocotb.top, name).value
        assert value.is_resolvable, f"{name} is X/Z: {value}"
        return int(value)

    def _stamp(self, name: str, count: int, when: int | None = None) -> None:
        self.fence.append((name, int(get_sim_time("ps")) if when is None else when, count))

    def _bound(self, label: str, bound: str, state: str) -> None:
        self._timeout_paths.append(f"{label}: bound={bound} last={state}")

    def _fail(self, token: str, text: str) -> None:
        self.fails.append(f"{token}: {text}")

    async def _count_ref_edges(self) -> None:
        clk = cocotb.top.clk_ref_i
        while self._ref_run:
            await RisingEdge(clk)
            self.ref_n += 1

    async def _wait_smc(self, label: str, cond, bound: int, state, each=None) -> int:
        clk = cocotb.top.clk_smc_i
        for n in range(bound + 1):
            if each is not None:
                each()
            if cond():
                self._bound(label, f"{bound}clk_smc_i", f"reached after {n} edges, {state()}")
                return n
            await RisingEdge(clk)
        self._bound(label, f"{bound}clk_smc_i", f"EXPIRED {state()}")
        raise AssertionError(f"{label}: not reached within {bound} clk_smc_i edges; {state()}")

    async def _wait_ref(self, label: str, cond, bound: int, state) -> int:
        clk = cocotb.top.clk_ref_i
        for n in range(bound + 1):
            if cond():
                self._bound(label, f"{bound}clk_ref_i", f"reached after {n} edges, {state()}")
                return n
            await RisingEdge(clk)
        self._bound(label, f"{bound}clk_ref_i", f"EXPIRED {state()}")
        raise AssertionError(f"{label}: not reached within {bound} clk_ref_i edges; {state()}")

    # --- bench access helpers ---------------------------------------------------------
    def _agent(self, port: str):
        return {
            "SEP": self.env.sys_axi_agent,
            "SYS": self.env.sys_in_axi_agent,
            "JTAG": self.env.jtag_axi_agent,
        }[port]

    @staticmethod
    def _item(op, label, addr, data=0, length=8, axi_id=None) -> SmcSysAxiItem:
        item = SmcSysAxiItem(label)
        item.op = op
        item.addr = addr
        item.length = length
        item.wdata = data
        item.axi_id = axi_id
        return item

    def _start(self, port: str, item, label: str):
        return cocotb.start_soon(_OneShot(item, f"{label}_os").start(self._agent(port).sequencer))

    async def _join(self, port: str, task, label: str) -> None:
        try:
            await with_timeout(task, JOIN_BOUND_NS, "ns")
        except SimTimeoutError as exc:
            raise AssertionError(
                f"{port} {label}: access not finished within {JOIN_BOUND_NS} ns"
            ) from exc

    async def _acc(self, port, op, label, addr, data=0, length=8):
        """One raw access with a bounded wait; an expiry is a checker FAIL, not an exception."""
        if port in self.wedged:
            self.skipped.append(label)
            self._bound(
                f"{label}.axi",
                f"{AXI_BOUND_NS}ns",
                f"NOT-SAMPLED {port} wedged by {self.wedged[port]}",
            )
            return None, None
        self._raw_seq += 1
        axi_id = None if port == "JTAG" else 0x10 + (self._raw_seq % 0x20)
        item = self._item(op, label, addr, data, length, axi_id)
        event = self._agent(port).driver._start_transfer(item)
        try:
            await with_timeout(event.wait(), AXI_BOUND_NS, "ns")
        except SimTimeoutError:
            self.wedged[port] = f"{label} @0x{addr:x}"
            self._fail(
                self._token,
                f"{port} {label} @0x{addr:x}: no response within {AXI_BOUND_NS} ns "
                f"(AR/AW accepted, no R/B)",
            )
            self._bound(f"{label}.axi", f"{AXI_BOUND_NS}ns", f"EXPIRED {port} @0x{addr:x}")
            return None, None
        code, value = self._raw_result(SimpleNamespace(event=event, op=op))
        self.accesses += 1
        self._bound(f"{label}.axi", f"{AXI_BOUND_NS}ns", f"answered resp={code}")
        if code != 0:
            self._fail(self._token, f"{port} {label} @0x{addr:x}: resp={code}")
        return code, value

    async def csr_read(self, name, addr, expected=None, length=4, prot=0):
        if not self.bounded:
            return await super().csr_read(name, addr, expected, length, prot)
        _, value = await self._acc("SEP", SmcSysAxiOp.READ, f"rd_{name}", addr, length=length)
        return NO_RESPONSE if value is None else value

    async def csr_write(self, name, addr, data, length=4, prot=0):
        if not self.bounded:
            await super().csr_write(name, addr, data, length, prot)
            return
        await self._acc("SEP", SmcSysAxiOp.WRITE, f"wr_{name}", addr, data, length)

    async def _okay(self, port, op, label, addr, data=0, length=8):
        if self.bounded:
            code, value = await self._acc(port, op, label, addr, data, length)
            return SimpleNamespace(rdata=NO_RESPONSE if value is None else value, resp_code=code)
        item = self._item(op, label, addr, data, length)
        await self._join(port, self._start(port, item, label), label)
        self.accesses += 1
        assert item.resp_code == 0 and not item.timed_out, (
            f"{port} {label} @0x{addr:x}: resp={item.resp_code} timed_out={item.timed_out}"
        )
        return item

    async def _rd(self, label: str, addr: int, length: int = 8) -> int:
        got = await self.csr_read(label, addr, length=length)
        return got if got == NO_RESPONSE else got & ((1 << (8 * length)) - 1)

    async def _ej_read(self, label: str, addr: int = EFUSE_WORD) -> int:
        event = self.ej.init_read(address=addr, length=4)
        try:
            await with_timeout(event.wait(), EJ_BOUND_NS, "ns")
        except SimTimeoutError:
            if not self.bounded:
                raise AssertionError(f"{label}: eFuse JTAG read of 0x{addr:x} not answered")
            self._fail(
                self._token, f"EFUSE_JTAG {label} @0x{addr:x}: no response within {EJ_BOUND_NS} ns"
            )
            self._bound(f"{label}.ej_read", f"{EJ_BOUND_NS}ns", "EXPIRED")
            return NO_RESPONSE
        assert event.data is not None, f"{label}: eFuse JTAG read flushed without a response"
        code = SmcSysAxiDriver._resp_code(event.data)
        if code != 0:
            self._fail(self._token, f"EFUSE_JTAG {label}: resp={code}")
        self._bound(f"{label}.ej_read", f"{EJ_BOUND_NS}ns", f"answered resp={code}")
        return int.from_bytes(event.data.data, "little") & 0xFFFF_FFFF

    # --- presented-but-unjoined accesses (observation only) -----------------------------
    def _raw(self, port, link, op, label, addr, data=0, length=8, axi_id=None):
        item = self._item(op, label, addr, data, length, axi_id)
        event = self._agent(port).driver._start_transfer(item)
        return SimpleNamespace(
            label=label, link=link, event=event, op=op, addr=addr, fate=None, items=item
        )

    @staticmethod
    def _raw_result(raw):
        if not raw.event.is_set():
            return None, None
        data = raw.event.data
        if data is None:
            return None, None
        code = SmcSysAxiDriver._resp_code(data)
        value = int.from_bytes(data.data, "little") if raw.op is SmcSysAxiOp.READ else None
        return code, value

    # --- S1 ---------------------------------------------------------------------------
    async def _write_check(self, label: str, addr: int, value: int, length: int) -> None:
        await self.csr_write(f"{label}_SET", addr, value, length=length)
        got = await self._rd(f"{label}_RB", addr, length)
        if got != value:
            if not self.bounded:
                raise AssertionError(f"{label}: reads 0x{got:x} after writing 0x{value:x}")
            if "SEP" not in self.wedged:
                self._fail(self._token, f"{label}: reads {got} after writing 0x{value:x}")

    async def _setup(self) -> None:
        dut = cocotb.top
        assert self._v("rst_primary_smc_clk_no") == 1, "SETUP: primary reset is asserted"
        assert self._v("tb_sep_wdt_reset_n") == 1, "SETUP: tb_sep_wdt_reset_n is low"
        assert self._v("tb_jtag_reset_ctrl") == 0, "SETUP: tb_jtag_reset_ctrl is not 0"
        assert self._v("tb_rst_warm_smc_clk_n") == 1, "SETUP: the warm reset is asserted"
        await self.program_inbound_pass_all()
        await self.program_outbound_pass_all()
        for n in range(4):
            await self._write_check(
                f"RESET_VECTOR{n}", _reset_vector(n), RESET_VECTOR_BASE_VALUE + n, 8
            )
        await self._write_check("WDT_TIMEOUT", WDT_TIMEOUT, WDT_TIMEOUT_REF, 4)
        await self._write_check("THRESHOLD", THRESHOLD, THRESHOLD_REF, 4)
        await self._write_check("SCRATCH0", SCRATCH0, SCRATCH_REF, 8)
        await self._write_check("SCRATCH_COLD", SCRATCH_COLD, COLD_REF, 4)
        await self._write_check("SCRATCH_COLD_WARM", SCRATCH_COLD_WARM, WARM_REF, 4)
        for addr in PRELOAD:
            await self.csr_write(f"PRELOAD_{addr:x}", addr, PRELOAD_WORD | addr, length=8)
        sys_out_mem = self.cfg.sys_out_mem
        assert sys_out_mem is not None, "SYS_OUT responder not bound"
        sys_out_mem.write_int(EXT_PENDING, EXT_PENDING_WORD, 8)
        self.reset_ctrl_read = await self._rd("RESET_CTRL_BEFORE", RESET_CTRL)
        self.reset_ctrl_held = self.reset_ctrl_read & ~CORE3_RESET_N
        self.attr_before = await self._rd("SMC_ATTRIBUTES_BEFORE", SMC_ATTRIBUTES)
        self.uart_pre = await self._rd("UART0_PRE", UART0_REG, 4)
        self.outfilt_pre = await self._rd("OUTBOUND_FILTER_PRE", OUTBOUND0_FILTER_CONFIG)
        self.ej_pre_value = await self._ej_read("SETUP")
        for name in ("tb_sep_axi_r_hold", "tb_sys_axi_r_hold", "tb_output_axi_resp_hold"):
            assert self._v(name) == 0, f"SETUP: {name} is set outside the pending phase"
        assert dut.tb_wdt_first_timeout_seen.value == 0, "SETUP: a watchdog timeout was latched"

    async def _core3_held(self) -> None:
        await self._write_check("RESET_CTRL_CORE3_HELD", RESET_CTRL, self.reset_ctrl_held, 8)

    # --- S2 ---------------------------------------------------------------------------
    def _fuse_alone(self, fuse_low_at_start: bool) -> None:
        if fuse_low_at_start:
            raise AssertionError(
                "tb_fuse_reset_n reads 0 at the leaf start: the fuse-alone window is open and "
                "the leaf has no implementation for it without +smc_hold_cpu_boot"
            )
        reason = (
            "tb_fuse_reset_n already reads 1 when the leaf starts (no +smc_hold_cpu_boot), "
            "no fuse-alone window exists to sample"
        )
        self.fuse_reason = reason
        self.lines.append(("CHK-FUSE-ALONE-WARM-NOT-PRIMARY", f"NOT-SAMPLED {reason}"))
        self._bound("S2.fuse_window", "1probe", f"tb_fuse_reset_n={self._v('tb_fuse_reset_n')}")

    # --- pending set (S3) ---------------------------------------------------------------
    async def _arm(self, rec, mon) -> None:
        dut = cocotb.top
        dut.tb_sep_axi_r_hold.value = 1
        dut.tb_sys_axi_r_hold.value = 1
        dut.tb_output_axi_resp_hold.value = 1
        self._agent("SEP").driver._vip.driver.set_timing(
            AxiTimingProfile(w_delay=PENDING_HOLD_CYCLES)
        )
        self._agent("JTAG").driver._vip.driver.set_timing(
            AxiTimingProfile(r_ready_delay=PENDING_HOLD_CYCLES)
        )
        rd, wr = SmcSysAxiOp.READ, SmcSysAxiOp.WRITE
        # A SYS_IN address outside the SMC window answers DECERR (fabric.adoc, input
        # fabric), so the access that must reach SYS_OUT goes through JTAG_IN.
        rec.pending = [
            self._raw("SEP", "SEP_IN", rd, "sep_rd_a", SEP_READ_A, axi_id=PENDING_ID_BASE + 0),
            self._raw("SEP", "SEP_IN", rd, "sep_rd_b", SEP_READ_B, axi_id=PENDING_ID_BASE + 1),
            self._raw(
                "SEP", "SEP_IN", rd, "sep_uart", UART0_REG, length=4, axi_id=PENDING_ID_BASE + 2
            ),
            self._raw(
                "SEP", "SEP_IN", wr, "sep_wr", SEP_WRITE, SEP_WRITE_DATA, axi_id=PENDING_ID_BASE + 3
            ),
            self._raw("SYS", "SYS_IN", rd, "sys_rd_a", SYS_READ_A, axi_id=PENDING_ID_BASE + 4),
            self._raw("SYS", "SYS_IN", rd, "sys_rd_b", SYS_READ_B, axi_id=PENDING_ID_BASE + 5),
            self._raw("SYS", "SYS_IN", rd, "sys_ext", EXT_PENDING, axi_id=PENDING_ID_BASE + 6),
            self._raw("JTAG", "JTAG_IN", rd, "jtag_rd", JTAG_READ, axi_id=JTAG_PENDING_IDS[0]),
            self._raw("JTAG", "JTAG_IN", rd, "jtag_ext", EXT_PENDING, axi_id=JTAG_PENDING_IDS[1]),
        ]
        r_channel = self.ej.backend.read_if.r_channel
        r_channel.pause = True
        rec.ej_event = self.ej.init_read(address=EFUSE_WORD, length=4)
        await self._wait_smc("S3.arm", lambda: all(mon.seen.values()), ARM_BOUND_SMC, mon.arm_text)
        cocotb.log.info("S3: pending set armed: %s", mon.arm_text())

    def _snapshot_outstanding(self, rec) -> dict | None:
        if not hasattr(rec, "ej_event"):
            return None
        out = dict.fromkeys(PLANNED_ITEMS, 0)
        for raw in rec.pending:
            out[raw.link] += int(not raw.event.is_set())
        out["EFUSE_JTAG"] = 0 if rec.ej_event.is_set() else 1
        labels = {raw.label for raw in rec.pending if not raw.event.is_set()}
        return {"outstanding": out, "labels": labels}

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
        if st["sep_aw_since_arm"] < 1 or st["sep_w_since_arm"] != 0 or prev.get("sep_wvalid"):
            problems.append(
                f"SEP_IN write AW handshakes {st['sep_aw_since_arm']}, W handshakes "
                f"{st['sep_w_since_arm']}, wvalid {prev.get('sep_wvalid')}"
            )
        for key in ("sep_r", "sys_r", "jtag_r", "ej_r"):
            if prev.get(key) != 1:
                problems.append(f"{key} not pending at the last sample before the assertion")
        if not st["seen"]["sys_out_ar"]:
            problems.append("no SYS_OUT AR handshake for the external read")
        return problems

    # --- generic warm entries -----------------------------------------------------------
    async def _wait_assert(self, label: str, mon) -> int:
        return await self._wait_smc(
            f"{label}.warm_assert",
            lambda: mon.phase != "pre",
            ASSERT_BOUND_SMC,
            lambda: mon.state_text,
        )

    async def _wait_release(self, label: str, mon, bound: int = RELEASE_BOUND_SMC) -> int:
        return await self._wait_smc(
            f"{label}.warm_release", lambda: mon.phase == "post", bound, lambda: mon.state_text
        )

    async def _wait_uncore(self, label: str, mon) -> int:
        return await self._wait_smc(
            f"{label}.uncore_release",
            lambda: self._v("tb_cpu_uncore_reset_n") == 1,
            UNCORE_BOUND_SMC,
            lambda: f"tb_cpu_uncore_reset_n={self._v('tb_cpu_uncore_reset_n')} {mon.state_text}",
        )

    def _window_ok(self, token: str, label: str, mon) -> None:
        n = mon.window_samples
        if n == 0 or mon.primary_high != n or mon.held != n:
            self._fail(
                token,
                f"{label}: window {n} samples, primary high {mon.primary_high}, cores/uncore held "
                f"{mon.held}; {mon.violations[:3]}",
            )

    # --- S3 / S4: watchdog-input entry -----------------------------------------------------
    async def _wdt_input_entry(self) -> SimpleNamespace:
        dut = cocotb.top
        rec = SimpleNamespace(name="wdt")
        await self._core3_held()
        self.bounded = True
        mon = _WarmMonitor(self, links=True, on_pre_sample=lambda: self._snapshot_outstanding(rec))
        rec.mon = mon
        mon.start()
        await self._arm(rec, mon)
        dut.tb_sep_wdt_reset_n.value = 0
        rec.pin_fall_ref = self.ref_n
        await self._wait_assert("wdt", mon)
        snapshot = mon.assert_state["pre_snapshot"]
        assert snapshot is not None, "wdt: the pending set was not armed at the assertion"
        rec.outstanding = snapshot["outstanding"]
        rec.assert_labels = snapshot["labels"]
        await self._wait_smc(
            "wdt.uncore_assert",
            lambda: mon.uncore_low_n > 0,
            ASSERT_BOUND_SMC,
            lambda: mon.state_text,
        )
        rd, wr = SmcSysAxiOp.READ, SmcSysAxiOp.WRITE
        rec.window = [
            self._raw(
                "SEP", "SEP_IN", rd, "win_reset_ctrl_rd", RESET_CTRL, axi_id=WINDOW_ID_BASE + 0
            ),
            self._raw(
                "SEP",
                "SEP_IN",
                wr,
                "win_reset_ctrl_wr",
                RESET_CTRL,
                self.reset_ctrl_held,
                axi_id=WINDOW_ID_BASE + 1,
            ),
            self._raw(
                "SEP",
                "SEP_IN",
                rd,
                "win_cold_rd",
                SCRATCH_COLD,
                length=4,
                axi_id=WINDOW_ID_BASE + 2,
            ),
            self._raw(
                "SEP",
                "SEP_IN",
                wr,
                "win_cold_wr",
                SCRATCH_COLD,
                COLD_REF,
                4,
                axi_id=WINDOW_ID_BASE + 3,
            ),
            self._raw(
                "SEP",
                "SEP_IN",
                rd,
                "win_wdt_ctrl_rd",
                WDT3_CTRL,
                length=4,
                axi_id=WINDOW_ID_BASE + 4,
            ),
            self._raw(
                "SEP", "SEP_IN", rd, "win_spm_rd", WINDOW_SPM_WORD, axi_id=WINDOW_ID_BASE + 5
            ),
        ]
        await ClockCycles(dut.clk_smc_i, WARM_HOLD_EDGES)
        self._bound("wdt.hold", f"{WARM_HOLD_EDGES}clk_smc_i", mon.state_text)
        self._stamp("WDT_ENTRY", sum(rec.outstanding.values()), mon.assert_ps)

        # RELEASE
        dut.tb_sep_wdt_reset_n.value = 1
        rec.pin_rise_ref = self.ref_n
        await self._wait_release("wdt", mon)
        rec.measured_ref = mon.release_ref - rec.pin_rise_ref
        if (
            mon.window_samples == 0
            or mon.primary_high != mon.window_samples
            or rec.measured_ref < REF_RELEASE_MIN
        ):
            self._fail(
                "CHK-WDT-INPUT-WARM-ONLY",
                f"primary high {mon.primary_high}/{mon.window_samples}, warm held "
                f"{rec.measured_ref} ref cycles after the input rose",
            )
        self._stamp("WDT_RELEASE", mon.window_samples, mon.release_ps)
        dut.tb_sep_axi_r_hold.value = 0
        dut.tb_sys_axi_r_hold.value = 0
        dut.tb_output_axi_resp_hold.value = 0
        rec.uncore_wait = await self._wait_uncore("wdt", mon)
        rec.core3_after_release = int((self._v("tb_cpu_core_resets_n") >> 3) & 1)
        self.ej.backend.read_if.r_channel.pause = False
        await self._settle(rec)
        rec.pending_counts = {link: mon.snap(link) for link in LINKS}
        return rec

    @staticmethod
    def _fate(raw, in_window: bool) -> str:
        if not raw.event.is_set():
            return "never"
        return "in_window" if in_window else "after_release"

    async def _settle(self, rec) -> None:
        """Wait, bounded, for every presented access to answer and book its fate."""
        for raw in rec.pending + rec.window:
            raw.fate = "in_window" if raw.event.is_set() else None
        rec.ej_fate = "in_window" if rec.ej_event.is_set() else None
        deadline = int(get_sim_time("ns")) + PENDING_SETTLE_NS
        for raw in [*rec.pending, *rec.window]:
            if raw.fate is None:
                left = deadline - int(get_sim_time("ns"))
                if left > 0:
                    try:
                        await with_timeout(raw.event.wait(), left, "ns")
                    except SimTimeoutError:
                        pass
                raw.fate = self._fate(raw, False)
        if rec.ej_fate is None:
            left = max(1, deadline - int(get_sim_time("ns")))
            try:
                await with_timeout(rec.ej_event.wait(), left, "ns")
            except SimTimeoutError:
                pass
            rec.ej_fate = self._fate(SimpleNamespace(event=rec.ej_event), False)
        for raw in [*rec.pending, *rec.window]:
            self._bound(f"wdt.settle.{raw.label}", f"{PENDING_SETTLE_NS}ns", f"fate={raw.fate}")
        self._bound("wdt.settle.efuse_jtag", f"{PENDING_SETTLE_NS}ns", f"fate={rec.ej_fate}")
        for raw in [*rec.pending, *rec.window]:
            code, value = self._raw_result(raw)
            cocotb.log.info(
                "S4: settle %s link=%s fate=%s resp=%s data=%s",
                raw.label,
                raw.link,
                raw.fate,
                code,
                value,
            )
        cocotb.log.info(
            "S4: link counts after settle %s",
            {k: rec.mon.snap(k) for k in ("SEP_IN", "SYS_IN", "JTAG_IN", "SYS_OUT")},
        )
        cocotb.log.info(
            "S4: SEP_IN valid/ready AR %d/%d AW %d/%d W %d/%d B %d/%d R %d/%d",
            self._v("s_axi_arvalid"),
            self._v("s_axi_arready"),
            self._v("s_axi_awvalid"),
            self._v("s_axi_awready"),
            self._v("s_axi_wvalid"),
            self._v("s_axi_wready"),
            self._v("s_axi_bvalid"),
            self._v("s_axi_bready"),
            self._v("s_axi_rvalid"),
            self._v("s_axi_rready"),
        )
        clear_profile(self._agent("SEP").driver._vip.driver)
        clear_profile(self._agent("JTAG").driver._vip.driver)
        await RisingEdge(cocotb.top.clk_smc_i)

    # --- S4 registers and fresh accesses ----------------------------------------------------
    @staticmethod
    def _delta(before: dict, after: dict) -> dict:
        return {ch: after[ch] - before[ch] for ch in CHANNELS}

    async def _kept_words(self, label: str) -> dict:
        words = {}
        for n in range(4):
            words[f"RESET_VECTOR[{n}]"] = (
                await self._rd(f"{label}_RV{n}", _reset_vector(n), 8),
                RESET_VECTOR_BASE_VALUE + n,
            )
        words["WDT_TIMEOUT"] = (
            await self._rd(f"{label}_WDT_TIMEOUT", WDT_TIMEOUT, 4),
            WDT_TIMEOUT_REF,
        )
        words["RESET_CTRL"] = (
            await self._rd(f"{label}_RESET_CTRL", RESET_CTRL),
            self.reset_ctrl_held,
        )
        words["THRESHOLD"] = (await self._rd(f"{label}_THRESHOLD", THRESHOLD, 4), THRESHOLD_REF)
        words["SCRATCH[0]"] = (await self._rd(f"{label}_SCRATCH0", SCRATCH0, 8), SCRATCH_REF)
        return words

    async def _fresh(self, rec) -> None:
        mon = rec.mon
        rec.fresh, rec.fresh_idx = {}, {}
        start = mon.n
        self._token = "CHK-FRESH-ACCESS-SEP-IN-WARM"
        await self._okay("SEP", SmcSysAxiOp.WRITE, "wdt_sep_wr", FRESH_SEP, FRESH_SEP_DATA)
        read = await self._okay("SEP", SmcSysAxiOp.READ, "wdt_sep_rd", FRESH_SEP)
        rec.fresh_idx["SEP_IN"] = (start, mon.n)
        rec.sep_read = read.rdata
        rec.l2_pending = (self._v("tb_cpu_l2_pending_ar"), self._v("tb_cpu_l2_pending_aw"))

        start = mon.n
        self._token = "CHK-FRESH-ACCESS-SYS-IN-WARM"
        await self._okay("SYS", SmcSysAxiOp.WRITE, "wdt_sys_wr", FRESH_SYS, FRESH_SYS_DATA)
        read = await self._okay("SYS", SmcSysAxiOp.READ, "wdt_sys_rd", FRESH_SYS)
        rec.fresh_idx["SYS_IN"] = (start, mon.n)
        rec.sys_read = read.rdata

        start = mon.n
        self._token = "CHK-FRESH-ACCESS-JTAG-IN-WARM"
        await self._okay("JTAG", SmcSysAxiOp.WRITE, "wdt_jtag_wr", FRESH_JTAG, FRESH_JTAG_DATA)
        read = await self._okay("JTAG", SmcSysAxiOp.READ, "wdt_jtag_rd", FRESH_JTAG)
        rec.fresh_idx["JTAG_IN"] = (start, mon.n)
        rec.jtag_read = read.rdata

        start = mon.n
        self._token = "CHK-FRESH-ACCESS-SYS-OUT-WARM"
        writes0, reads0 = self._v("tb_output_axi_write_count"), self._v("tb_output_axi_read_count")
        await self._okay("JTAG", SmcSysAxiOp.WRITE, "wdt_ext_wr", EXT_FRESH, FRESH_EXT_DATA)
        writes1 = self._v("tb_output_axi_write_count")
        read = await self._okay("JTAG", SmcSysAxiOp.READ, "wdt_ext_rd", EXT_FRESH)
        reads1 = self._v("tb_output_axi_read_count")
        rec.fresh_idx["SYS_OUT"] = (start, mon.n)
        rec.ext = (writes1 - writes0, reads1 - reads0, read.rdata & 0xFFFF_FFFF)

        await wait_fuse_sense_done(FUSE_SENSE_BOUND_SMC)
        self._bound("wdt.fuse_sense", f"{FUSE_SENSE_BOUND_SMC}clk_smc_i", "sense done")
        start = mon.n
        self._token = "CHK-FRESH-ACCESS-EFUSE-JTAG-WARM"
        rec.efuse_value = await self._ej_read("wdt_efuse")
        rec.fresh_idx["EFUSE_JTAG"] = (start, mon.n)

        start = mon.n
        self._token = "CHK-FRESH-ACCESS-PERIPH-WARM"
        read = await self._okay("SEP", SmcSysAxiOp.READ, "wdt_uart", UART0_REG, length=4)
        rec.fresh_idx["PERIPH"] = (start, mon.n)
        rec.uart_value = read.rdata & 0xFFFF_FFFF

        await ClockCycles(cocotb.top.clk_smc_i, TAIL_EDGES)
        self._bound("wdt.tail", f"{TAIL_EDGES}clk_smc_i", "counted window")
        for link, (first, last) in rec.fresh_idx.items():
            lag = RESPONSE_COUNT_LAG if link == "SYS_OUT" else 0
            rec.fresh[link] = self._delta(mon.hist[first][link], mon.hist[last + lag][link])

    async def _after_release(self, rec) -> None:
        self._token = "CHK-CTRL-REGS-KEPT-ACROSS-WARM"
        rec.kept_wdt = await self._kept_words("wdt")
        self._token = "CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM"
        rec.outfilt_after = await self._rd("OUTBOUND_FILTER_AFTER", OUTBOUND0_FILTER_CONFIG)
        rec.uart_after = await self._rd("UART0_AFTER", UART0_REG, 4)
        await self._fresh(rec)
        # S5 after the release only: the warm scratch register is never accessed in a window.
        self._token = "CHK-WARM-SCRATCH-RESET"
        rec.warm_scratch = await self._rd("SCRATCH_COLD_WARM_AFTER", SCRATCH_COLD_WARM, 4)
        self._token = "CHK-OBS-ATTRIBUTES"
        rec.cold_scratch = await self._rd("SCRATCH_COLD_AFTER", SCRATCH_COLD, 4)
        self.attr_after = await self._rd("SMC_ATTRIBUTES_AFTER", SMC_ATTRIBUTES)
        self._token = "CHK-OBS-WARM-WINDOW-ACCESS"
        rec.fresh_window = {
            "RESET_CTRL": await self._rd("FRESH_RESET_CTRL", RESET_CTRL),
            "SCRATCH_COLD": rec.cold_scratch,
            "WDT3_CTRL": await self._rd("FRESH_WDT3_CTRL", WDT3_CTRL, 4),
            "SPM_WORD": await self._rd("FRESH_SPM_WORD", WINDOW_SPM_WORD),
        }
        assert rec.core3_after_release == 0, "wdt: core 3 reads released while RESET_CTRL holds it"
        self._token = "CHK-WARM-HOLDS-CPU"
        await self.csr_write("RESET_CTRL_CORE3_RELEASE", RESET_CTRL, self.reset_ctrl_read, length=8)
        if "SEP" in self.wedged:
            rec.core3_wait = NO_RESPONSE
            self._fail(
                self._token, "core 3 release not observable: the RESET_CTRL write got no response"
            )
        else:
            rec.core3_wait = await self._wait_smc(
                "wdt.core3_release",
                lambda: (self._v("tb_cpu_core_resets_n") >> 3) & 1 == 1,
                UNCORE_BOUND_SMC,
                lambda: f"tb_cpu_core_resets_n=0x{self._v('tb_cpu_core_resets_n'):x}",
            )
        self._stamp("REGS_AFTER", self.accesses)
        await rec.mon.finish()

    # --- S6: JTAG override entry ---------------------------------------------------------
    async def _jtag_entry(self) -> SimpleNamespace:
        dut = cocotb.top
        rec = SimpleNamespace(name="jtag")
        self._token = "CHK-JTAG-WARM-OVERRIDE-ENTRY"
        await self._core3_held()
        assert self._v("tb_sep_wdt_reset_n") == 1 and self._v("tb_jtag_reset_ctrl") == 0
        mon = _WarmMonitor(self)
        rec.mon = mon
        mon.start()
        await RisingEdge(dut.clk_ref_i)
        rec.ref_write = self.ref_n
        dut.tb_jtag_reset_ctrl.value = _pack(warm_ovrd=1, warm_val=0)
        await self._wait_assert("jtag", mon)
        assert self._v("tb_sep_wdt_reset_n") == 1, "jtag: the watchdog input is not idle"
        await ClockCycles(dut.clk_smc_i, JTAG_HOLD_EDGES)
        self._bound("jtag.hold", f"{JTAG_HOLD_EDGES}clk_smc_i", mon.state_text)
        rec.ref_val1 = self.ref_n
        dut.tb_jtag_reset_ctrl.value = _pack(warm_ovrd=1, warm_val=1)
        await self._wait_release("jtag", mon)
        dut.tb_jtag_reset_ctrl.value = 0
        high = 0
        for _ in range(JTAG_CLEAR_REF):
            await RisingEdge(dut.clk_ref_i)
            high += self._v("tb_rst_warm_smc_clk_n")
        self._bound("jtag.clear", f"{JTAG_CLEAR_REF}clk_ref_i", f"warm high {high}")
        if high != JTAG_CLEAR_REF:
            self._fail(
                "CHK-JTAG-WARM-OVERRIDE-ENTRY", f"warm high {high}/{JTAG_CLEAR_REF} after the clear"
            )
        rec.fall_ref = mon.assert_ref - rec.ref_write
        rec.rise_ref = mon.release_ref - rec.ref_val1
        await self._wait_uncore("jtag", mon)
        self._window_ok("CHK-JTAG-WARM-OVERRIDE-ENTRY", "jtag", mon)
        self._token = "CHK-CTRL-REGS-KEPT-ACROSS-WARM"
        rec.kept = await self._kept_words("jtag")
        self._stamp("JTAG_WARM", mon.window_samples, mon.assert_ps)
        await mon.finish()
        return rec

    # --- S7: armed watchdog second stage -------------------------------------------------
    async def _wdt_arm(self, tag: str) -> None:
        for name, addr, value in (
            ("CTRL", WDT3_CTRL, WDT_CTRL_ARM),
            ("CMP", WDT3_CMP, WDT_CMP_VALUE),
            ("COUNT", WDT3_COUNT, 0),
        ):
            await self.csr_write(f"{tag}_KEY_{name}", WDT3_KEY, WDT_MAGIC_KEY)
            await self.csr_write(f"{tag}_{name}", addr, value)

    async def _wdt_chain(self) -> SimpleNamespace:
        dut = cocotb.top
        rec = SimpleNamespace(name="chain")
        assert self._v("tb_wdt_first_timeout_seen") == 0, (
            "chain: a first timeout is already latched"
        )
        mon = _WarmMonitor(self)
        mon.start()
        await self._wdt_arm("chain1")
        early = []

        def _watch() -> None:
            if self._v("tb_wdt_first_timeout_seen") == 0 and self._v("tb_rst_warm_smc_clk_n") == 0:
                early.append(mon.n)

        a = await self._wait_smc(
            "S7.first_timeout",
            lambda: self._v("tb_wdt_first_timeout_seen") == 1,
            WDT_FIRST_BOUND_SMC,
            lambda: (
                f"seen={self._v('tb_wdt_first_timeout_seen')} warm={self._v('tb_rst_warm_smc_clk_n')}"
            ),
            each=_watch,
        )
        rec.warm_at_first = self._v("tb_rst_warm_smc_clk_n")
        rec.a = a
        b = await self._wait_smc(
            "S7.second_stage_warm",
            lambda: self._v("tb_rst_warm_smc_clk_n") == 0,
            WDT_SECOND_BOUND_SMC,
            lambda: f"warm={self._v('tb_rst_warm_smc_clk_n')} {mon.state_text}",
        )
        rec.b = a + b
        rec.primary_at_assert = self._v("rst_primary_smc_clk_no")
        await self._wait_release("chain1", mon)
        rec.early = early
        rec.mon1 = mon
        await mon.finish()

        # Second run: a FEED and the second-stage restart after the first timeout.
        mon = _WarmMonitor(self)
        mon.start()
        await self._wdt_arm("chain2")
        await self._wait_smc(
            "S7.second_run_first_timeout",
            lambda: self._v("tb_wdt_first_timeout") == 1,
            WDT_FIRST_BOUND_SMC,
            lambda: f"tb_wdt_first_timeout={self._v('tb_wdt_first_timeout')}",
        )
        await self.csr_write("chain2_CYCLE_COUNT_RESET", WDT_TIMEOUT_RESET, RESET_CYCLE_COUNT_3)
        await self.csr_write("chain2_KEY_FEED", WDT3_KEY, WDT_MAGIC_KEY)
        await self.csr_write("chain2_FEED", WDT3_FEED, WDT_FEED_VALUE)
        rec.warm_at_feed = self._v("tb_rst_warm_smc_clk_n")
        rec.b2 = await self._wait_smc(
            "S7.second_run_warm",
            lambda: self._v("tb_rst_warm_smc_clk_n") == 0,
            WDT_SECOND_BOUND_SMC,
            lambda: f"warm={self._v('tb_rst_warm_smc_clk_n')} {mon.state_text}",
        )
        await self._wait_release("chain2", mon)
        rec.mon2 = mon
        await mon.finish()
        reasserted = []
        for k in range(WDT_QUIET_EDGES):
            await RisingEdge(dut.clk_smc_i)
            if self._v("tb_rst_warm_smc_clk_n") == 0:
                reasserted.append(k)
                break
        rec.reasserted = reasserted
        self._bound("S7.quiet", f"{WDT_QUIET_EDGES}clk_smc_i", f"re-assertions {reasserted}")
        self._stamp("WDT_CHAIN", rec.a + 1, int(get_sim_time("ps")))
        return rec

    # --- S8: reset vector observation ------------------------------------------------------
    async def _vector(self) -> SimpleNamespace:
        dut = cocotb.top
        rec = SimpleNamespace(name="vector")
        await self._write_check("RESET_VECTOR3_SPM", _reset_vector(3), VECTOR3_OBS, 8)
        await self._core3_held()
        mon = _WarmMonitor(self)
        mon.start()
        dut.tb_sep_wdt_reset_n.value = 0
        await self._wait_assert("vector", mon)
        await ClockCycles(dut.clk_smc_i, JTAG_HOLD_EDGES)
        dut.tb_sep_wdt_reset_n.value = 1
        await self._wait_release("vector", mon)
        await self._wait_uncore("vector", mon)
        rec.mon = mon
        await self.csr_write(
            "RESET_CTRL_VECTOR_RELEASE", RESET_CTRL, self.reset_ctrl_read, length=8
        )
        count0 = self._v("tb_cpu_rom_read_count")
        await ClockCycles(dut.clk_smc_i, VECTOR_WINDOW_EDGES)
        self._bound("S8.rom_window", f"{VECTOR_WINDOW_EDGES}clk_smc_i", "counted window")
        rec.delta = (self._v("tb_cpu_rom_read_count") - count0) & 0xFFFF_FFFF
        self._stamp("VECTOR", mon.window_samples, mon.assert_ps)
        await mon.finish()
        return rec

    # --- orchestration ----------------------------------------------------------------------
    async def body(self) -> None:
        dut = cocotb.top
        counter = cocotb.start_soon(self._count_ref_edges())
        for name in _EXTRA_NAMES:
            assert hasattr(dut, name), f"{name} is not a signal of the testbench top"
        fuse_low_at_start = self._v("tb_fuse_reset_n") == 0
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
        await self._setup()
        self._stamp("SETUP", self.accesses)

        self._fuse_alone(fuse_low_at_start)
        self._stamp("FUSE_WINDOW", 1)

        self.wdt = self.jtag = None
        try:
            self.wdt = await self._wdt_input_entry()
            await self._after_release(self.wdt)
            self.jtag = await self._jtag_entry()
            if "SEP" in self.wedged:
                self._bound(
                    "S7.S8.skipped",
                    "n/a",
                    f"NOT-SAMPLED the watchdog and vector steps program through SEP_IN, "
                    f"wedged by {self.wedged['SEP']}",
                )
            else:
                self.chain = await self._wdt_chain()
                self.vector = await self._vector()
        except AssertionError as exc:
            self._fail("CHK-NONVAC", f"step aborted: {exc}")
        self._ref_run = False
        await counter
        self._report()

    # --- evidence -----------------------------------------------------------------------
    @staticmethod
    def _joined(values) -> str:
        return "/".join(str(v) for v in values)

    def _check_kept(self, rec_words: dict, label: str) -> None:
        bad = {k: f"0x{got:x} != 0x{want:x}" for k, (got, want) in rec_words.items() if got != want}
        if bad:
            self._fail("CHK-CTRL-REGS-KEPT-ACROSS-WARM", f"{label}: {bad}")

    def _report(self) -> None:
        w, j, c = self.wdt, self.jtag, self.chain
        lines = self.lines
        if w is None or not hasattr(w, "fresh_window"):
            self._emit()
            return
        mon = w.mon

        # CHK-WDT-INPUT-WARM-ONLY
        lines.append(
            (
                "CHK-WDT-INPUT-WARM-ONLY",
                f"warm low, primary high at {mon.primary_high}/{mon.window_samples} edges; warm "
                f"low >= {REF_RELEASE_MIN} ref cycles after release (measured {w.measured_ref})",
            )
        )

        # CHK-WARM-HOLDS-CPU
        if mon.window_samples == 0 or mon.held != mon.window_samples:
            self._fail(
                "CHK-WARM-HOLDS-CPU", f"held {mon.held}/{mon.window_samples}; {mon.violations[:3]}"
            )
        if w.core3_after_release != 0 or w.core3_wait < 0:
            self._fail("CHK-WARM-HOLDS-CPU", f"core 3 probe after release {w.core3_after_release}")
        lines.append(
            (
                "CHK-WARM-HOLDS-CPU",
                f"cores/uncore held {mon.held}/{mon.window_samples} edges in warm; after release "
                f"uncore 1, core3 0 -> 1 after RESET_CTRL write",
            )
        )

        # CHK-CTRL-REGS-KEPT-ACROSS-WARM
        self._check_kept(w.kept_wdt, "wdt-input")
        if j is not None:
            self._check_kept(j.kept, "jtag-override")
        lines.append(
            (
                "CHK-CTRL-REGS-KEPT-ACROSS-WARM",
                f"wdt-input and jtag-override: RESET_VECTOR 4/4, WDT_TIMEOUT, RESET_CTRL, "
                f"threshold, SCRATCH[0] kept ({len(w.kept_wdt) + (len(j.kept) if j else 0)} words, "
                f"{2 if j else 1} entries)",
            )
        )

        # CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM
        threshold = w.kept_wdt["THRESHOLD"][0]
        if (
            threshold != THRESHOLD_REF
            or w.uart_after != self.uart_pre
            or w.outfilt_after != self.outfilt_pre
        ):
            self._fail(
                "CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM",
                f"threshold 0x{threshold:x}, UART0 0x{w.uart_after:x} vs 0x{self.uart_pre:x}, "
                f"outbound filter 0x{w.outfilt_after:x} vs 0x{self.outfilt_pre:x}",
            )
        lines.append(
            (
                "CHK-INTERCONNECT-KEPT-ACROSS-WDT-WARM",
                f"threshold 0x{threshold:x} kept, UART0 register == pre-reset value "
                f"0x{self.uart_pre:x}, outbound filter == pre-reset value",
            )
        )

        # CHK-WARM-SCRATCH-RESET
        if w.warm_scratch != 0:
            self._fail("CHK-WARM-SCRATCH-RESET", f"SCRATCH_COLD_WARM[0] reads 0x{w.warm_scratch:x}")
        lines.append(
            (
                "CHK-WARM-SCRATCH-RESET",
                f"SCRATCH_COLD_WARM[0] 0x{WARM_REF:X} -> 0x{w.warm_scratch:x} after release",
            )
        )

        # fresh accesses
        def fresh(token, attr, want, text):
            got = getattr(w, attr)
            if got != want:
                self._fail(token, f"read 0x{got:x} != 0x{want:x}")
            lines.append((token, text))

        fresh(
            "CHK-FRESH-ACCESS-SYS-IN-WARM",
            "sys_read",
            FRESH_SYS_DATA,
            f"write OKAY, read 0x{FRESH_SYS_DATA:016x}",
        )
        fresh(
            "CHK-FRESH-ACCESS-JTAG-IN-WARM",
            "jtag_read",
            FRESH_JTAG_DATA,
            f"write OKAY, read 0x{FRESH_JTAG_DATA:016x}",
        )
        if w.l2_pending != (0, 0):
            self._fail("CHK-FRESH-ACCESS-SEP-IN-WARM", f"L2 pending AR/AW {w.l2_pending}")
        fresh(
            "CHK-FRESH-ACCESS-SEP-IN-WARM",
            "sep_read",
            FRESH_SEP_DATA,
            f"write OKAY, read 0x{FRESH_SEP_DATA:016x}, L2 pending AR/AW 0/0",
        )
        if w.ext != (1, 1, FRESH_EXT_DATA):
            self._fail("CHK-FRESH-ACCESS-SYS-OUT-WARM", f"count deltas and data {w.ext}")
        lines.append(
            (
                "CHK-FRESH-ACCESS-SYS-OUT-WARM",
                f"write count +{w.ext[0]}, read count +{w.ext[1]}, both OKAY, via JTAG_IN",
            )
        )
        if w.efuse_value != self.ej_pre_value:
            self._fail(
                "CHK-FRESH-ACCESS-EFUSE-JTAG-WARM",
                f"0x{w.efuse_value:x} vs 0x{self.ej_pre_value:x}",
            )
        lines.append(
            (
                "CHK-FRESH-ACCESS-EFUSE-JTAG-WARM",
                f"read completed, word == pre-reset value 0x{self.ej_pre_value:08x}",
            )
        )
        if w.uart_value != self.uart_pre:
            self._fail("CHK-FRESH-ACCESS-PERIPH-WARM", f"0x{w.uart_value:x} vs 0x{self.uart_pre:x}")
        lines.append(
            (
                "CHK-FRESH-ACCESS-PERIPH-WARM",
                f"UART0 register read OKAY, value == pre-reset value 0x{self.uart_pre:x}",
            )
        )

        # CHK-NO-ORPHAN-RESPONSE-WARM
        orphan = [mon.orphan[link] for link in ORPHAN_LINKS if mon.orphan[link]]
        delta_bad, pairs = [], 0
        for link in ORPHAN_LINKS:
            d = w.fresh[link]
            want = (
                {"aw": 0, "w": 0, "b": 0, "ar": 1, "r": 1}
                if link == "EFUSE_JTAG"
                else {"aw": 1, "w": 1, "b": 1, "ar": 1, "r": 1}
            )
            pairs += 1
            if d != want:
                delta_bad.append(f"{link}: {d}")
        if orphan or delta_bad or pairs < 5:
            self._fail("CHK-NO-ORPHAN-RESPONSE-WARM", f"{orphan} {delta_bad} links={pairs}")
        lines.append(
            (
                "CHK-NO-ORPHAN-RESPONSE-WARM",
                f"per link R<=AR and B<=AW at every edge; fresh deltas AR/R/AW/B = 1/1/1/1 on 4 "
                f"links (SYS_IN, JTAG_IN, SEP_IN, SYS_OUT) and 1/1/0/0 on the read-only eFuse JTAG "
                f"fresh access; {pairs} links checked from the warm assertion (counted from the monitor start, "
                f"R>AR or B>AW on {sum(1 for v in mon.orphan_start.values() if v)} links)",
            )
        )

        # CHK-NO-DRAIN-ON-WARM
        if mon.window_samples == 0 or mon.isolate_low != mon.window_samples:
            self._fail(
                "CHK-NO-DRAIN-ON-WARM", f"isolate_req low {mon.isolate_low}/{mon.window_samples}"
            )
        lines.append(
            (
                "CHK-NO-DRAIN-ON-WARM",
                f"isolate_req_i low at {mon.isolate_low}/{mon.window_samples} edges of the warm window",
            )
        )

        # CHK-VALID-LOW-CLUSTER-UNCORE-WARM
        bad = []
        for link in VALID_RULES:
            if mon.valid_edges[link] == 0 or mon.valid_violations[link]:
                bad.append(
                    f"{link}: {mon.valid_edges[link]} edges {mon.valid_violations[link][:3]}"
                )
        if bad:
            self._fail("CHK-VALID-LOW-CLUSTER-UNCORE-WARM", f"{bad}")
        lines.append(
            (
                "CHK-VALID-LOW-CLUSTER-UNCORE-WARM",
                f"L2F B/R and MMIO AW/W/AR VALID low at {mon.valid_edges['CPU_FRONT']} edges of the "
                f"uncore reset (L2F B/R {mon.valid_edges['CPU_FRONT']} edges; MMIO AW/W/AR "
                f"{mon.valid_edges['CPU_MMIO']} edges sampled with no MMIO traffic, c-fw MMIO leg "
                f"deferred); 0 violations",
            )
        )

        if j is None:
            lines.append(("CHK-JTAG-WARM-OVERRIDE-ENTRY", "NOT-SAMPLED step not reached"))
        else:
            # CHK-JTAG-WARM-OVERRIDE-ENTRY
            jm = j.mon
            self._window_ok("CHK-JTAG-WARM-OVERRIDE-ENTRY", "jtag", jm)
            lines.append(
                (
                    "CHK-JTAG-WARM-OVERRIDE-ENTRY",
                    f"warm low, primary high, cores/uncore held at {jm.held}/{jm.window_samples} edges; "
                    f"released after override clear",
                )
            )
            cocotb.log.info(
                "OBS-JTAG-WARM-OVERRIDE: write_to_fall=%d ref cycles value1_to_release=%d ref cycles",
                j.fall_ref,
                j.rise_ref,
            )

        if c is None:
            for tok in ("CHK-WDT-SECOND-STAGE-WARM", "CHK-WDT-LATCH-NOT-WITHDRAWN"):
                lines.append(
                    (
                        tok,
                        f"NOT-SAMPLED SEP_IN wedged by {self.wedged.get('SEP', '?')}: the watchdog is armed through SEP_IN",
                    )
                )
        else:
            # CHK-WDT-SECOND-STAGE-WARM / CHK-WDT-LATCH-NOT-WITHDRAWN
            m1 = c.mon1
            if (
                c.early
                or c.warm_at_first != 1
                or c.b <= c.a
                or c.primary_at_assert != 1
                or m1.primary_high != m1.window_samples
            ):
                self._fail(
                    "CHK-WDT-SECOND-STAGE-WARM",
                    f"warm low before the first timeout {c.early[:3]}, warm at first timeout "
                    f"{c.warm_at_first}, edges {c.a}/{c.b}, primary {c.primary_at_assert}",
                )
            lines.append(
                (
                    "CHK-WDT-SECOND-STAGE-WARM",
                    f"first_timeout_seen at edge {c.a} with warm {c.warm_at_first}; warm low at edge "
                    f"{c.b} > {c.a}, primary high",
                )
            )
            if c.warm_at_feed != 1 or c.reasserted or c.mon2.primary_high != c.mon2.window_samples:
                self._fail(
                    "CHK-WDT-LATCH-NOT-WITHDRAWN",
                    f"warm at the FEED {c.warm_at_feed}, re-assertions {c.reasserted}",
                )
            lines.append(
                (
                    "CHK-WDT-LATCH-NOT-WITHDRAWN",
                    f"feed written, warm asserted at edge {c.b2}; no re-assertion in {WDT_QUIET_EDGES} edges",
                )
            )

        self._observations(lines)
        self._emit()

    def _emit(self) -> None:
        lines = self.lines
        if self.wdt is not None and hasattr(self.wdt, "fresh_window"):
            lines.append(("CHK-NONVAC", self._fence_check()))
        else:
            self._fail(
                "CHK-NONVAC", f"the watchdog-input entry did not complete; terms {self.fence}"
            )
        expired = [t for t in self._timeout_paths if "EXPIRED" in t]
        if expired:
            self._fail("CHK-TIMEOUT-PATHS", f"{len(expired)} bounded waits expired: {expired}")
        lines.append(("CHK-TIMEOUT-PATHS", self._timeout_summary()))
        printed = set()
        for token, text in lines:
            mine = [f.split(": ", 1)[1] for f in self.fails if f.split(":", 1)[0] == token]
            if mine:
                cocotb.log.info("%s: FAIL %s", token, "; ".join(mine))
            else:
                cocotb.log.info("%s: %s", token, text)
            printed.add(token)
        for token in REQUIRED_TOKENS:
            if token not in printed:
                mine = [f.split(": ", 1)[1] for f in self.fails if f.split(":", 1)[0] == token]
                detail = "; ".join(mine) if mine else "step not reached, see CHK-NONVAC"
                cocotb.log.info("%s: %s %s", token, "FAIL" if mine else "NOT-SAMPLED", detail)
        for line in self._timeout_paths:
            cocotb.log.info("CHK-TIMEOUT-PATHS: wait %s", line)
        assert not self.fails, "contract checkers failed:\n" + "\n".join(
            f"FAIL {f}" for f in self.fails
        )

    def _observations(self, lines) -> None:
        w, v = self.wdt, self.vector
        mon = w.mon
        obs = self.obs
        ej = SimpleNamespace(
            label="efuse_jtag",
            link="EFUSE_JTAG",
            event=w.ej_event,
            op=SmcSysAxiOp.READ,
            fate=w.ej_fate,
        )
        by_label = {raw.label: raw for raw in w.pending}
        groups = {
            "SEP_IN": [r for r in w.pending if r.link == "SEP_IN"],
            "SYS_IN": [r for r in w.pending if r.link == "SYS_IN"],
            "JTAG_IN": [r for r in w.pending if r.link == "JTAG_IN"],
            "SYS_OUT": [by_label["jtag_ext"]],
            "EFUSE_JTAG": [ej],
            "PERIPH": [by_label["sep_uart"]],
            "CPU_FRONT": [
                by_label[k]
                for k in ("sep_rd_a", "sep_rd_b", "sep_wr", "sys_rd_a", "sys_rd_b", "jtag_rd")
            ],
            "CPU_MMIO": [],
        }
        for link, raws in groups.items():
            ch = w.pending_counts[link]
            fates = dict.fromkeys(("before_assert", "in_window", "after_release", "never"), 0)
            codes, aborted = [], 0
            for raw in raws:
                fate = "before_assert" if raw.label not in w.assert_labels else raw.fate
                fates[fate] += 1
                code, _ = self._raw_result(raw)
                if code is not None:
                    codes.append(code)
                elif raw.event.is_set():
                    aborted += 1
            code_text = ",".join(str(x) for x in sorted(set(codes))) or "none"
            l2, mmio = mon.window_pending.split()
            obs["OBS-WARM-PHASE-FATE"].append(
                f"OBS-WARM-PHASE-FATE: link={link} items={len(raws)} aborted={aborted} "
                f"late_resp={code_text} ar={ch['ar']} r={ch['r']} aw={ch['aw']} b={ch['b']} "
                f"l2_pending={l2[3:]} mmio_pending={mmio[5:]} fates={fates} "
                f"(pending at release: {mon.release_pending})"
            )
        iso = mon.iso
        n = mon.window_samples
        obs["OBS-WARM-ISOLATE-STATE"].append(
            f"OBS-WARM-ISOLATE-STATE: l2_isolated high {iso['l2_isolated'][0]}/{n} edges "
            f"mmio_isolated high {iso['mmio_isolated'][0]}/{n} flush l2={iso['l2_flush'][0]} "
            f"mmio={iso['mmio_flush'][0]} (first/last l2_isolated {iso['l2_isolated'][1]}/"
            f"{iso['l2_isolated'][2]} mmio_isolated {iso['mmio_isolated'][1]}/{iso['mmio_isolated'][2]})"
        )
        for raw in w.window:
            code, value = self._raw_result(raw)
            data = "none" if value is None else f"0x{value:x}"
            obs["OBS-WARM-WINDOW-ACCESS"].append(
                f"OBS-WARM-WINDOW-ACCESS: target={raw.label} resp={'none' if code is None else code} "
                f"data={data} completed={raw.fate}"
            )
        for name, value in w.fresh_window.items():
            cocotb.log.info(
                "OBS-WARM-WINDOW-FRESH: target=%s fresh read OKAY data=0x%x", name, value
            )
        changed = "yes" if self.attr_before != self.attr_after else "no"
        fields_b = {
            k: (self.attr_before & m) >> ((m & -m).bit_length() - 1) for k, m in ATTRIBUTE_FIELDS
        }
        fields_a = {
            k: (self.attr_after & m) >> ((m & -m).bit_length() - 1) for k, m in ATTRIBUTE_FIELDS
        }
        obs["OBS-ATTRIBUTES"].append(
            f"OBS-ATTRIBUTES: before=0x{self.attr_before:x} after=0x{self.attr_after:x} "
            f"changed={changed} fields_before={fields_b} fields_after={fields_a}"
        )
        if v is None:
            obs["OBS-WARM-VECTOR"].append(
                f"OBS-WARM-VECTOR: NOT-SAMPLED window={VECTOR_WINDOW_EDGES} vector3=0x{VECTOR3_OBS:X} "
                f"(SEP_IN wedged by {self.wedged.get('SEP', '?')})"
            )
        else:
            obs["OBS-WARM-VECTOR"].append(
                f"OBS-WARM-VECTOR: rom_read_count_delta={v.delta} window={VECTOR_WINDOW_EDGES} "
                f"vector3=0x{VECTOR3_OBS:X}"
            )
        for token, key in (
            ("CHK-OBS-WARM-PHASE-FATE", "OBS-WARM-PHASE-FATE"),
            ("CHK-OBS-WARM-ISOLATE-STATE", "OBS-WARM-ISOLATE-STATE"),
            ("CHK-OBS-WARM-WINDOW-ACCESS", "OBS-WARM-WINDOW-ACCESS"),
            ("CHK-OBS-ATTRIBUTES", "OBS-ATTRIBUTES"),
            ("CHK-OBS-WARM-VECTOR", "OBS-WARM-VECTOR"),
        ):
            for line in obs[key]:
                cocotb.log.info("%s", line)
            lines.append((token, f"recorded {len(obs[key])} {key} lines"))
        lines.append(
            (
                "CHK-OBS-FUSE-WINDOW-ACCESS",
                f"recorded 0 OBS-FUSE-WINDOW-ACCESS lines; items=0 ({self.fuse_reason})",
            )
        )

    def _fence_check(self) -> str:
        want = [
            "SETUP",
            "FUSE_WINDOW",
            "WDT_ENTRY",
            "WDT_RELEASE",
            "REGS_AFTER",
            "JTAG_WARM",
            "WDT_CHAIN",
            "VECTOR",
        ]
        names = [f[0] for f in self.fence]
        missing = [t for t in want if t not in names]
        if missing:
            self._fail("CHK-NONVAC", f"terms not reached {missing}: wedged {self.wedged}")
        times = [f[1] for f in self.fence]
        if names != want or any(b <= a for a, b in zip(times, times[1:])):
            self._fail("CHK-NONVAC", f"terms {self.fence}")
        floors = {"WDT_ENTRY": 9}
        for term, count in ((f[0], f[2]) for f in self.fence):
            if count < floors.get(term, 1):
                self._fail("CHK-NONVAC", f"term {term} count {count} below {floors.get(term, 1)}")
        problems = self._inflight_problems(self.wdt)
        if problems:
            self._fail("CHK-NONVAC", f"pending set not in flight at the assertion: {problems}")
        links = sum(1 for d in self.wdt.fresh.values() if d["ar"] == 1)
        if links < 5:
            self._fail("CHK-NONVAC", f"fresh-handshake links {links}")
        return (
            " < ".join(names)
            + " (counts and times per term): "
            + "; ".join(f"{n} t={t}ps count={c}" for n, t, c in self.fence)
            + f"; fresh-handshake links {links}"
        )

    def _timeout_summary(self) -> str:
        expired = sum(1 for t in self._timeout_paths if "EXPIRED" in t)
        return (
            f"{len(self._timeout_paths)} bounded waits, bound/last-state per wait, "
            f"{expired} expired"
        )
