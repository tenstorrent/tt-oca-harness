# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The secure DMA reaches its fabric endpoints, passes the local alias remap, leaves AxUSER at 0 and reaches no not-connected target.

Firmware ``dma_endpoint_matrix_test`` programs the DMA for every leg and prints
what it read back (``R`` records); ``M G`` / ``M C`` lines announce each
graded or control leg. This test draws the stimulus from the run seed and
patches it into the firmware parameter block, follows the legs live (tap
marks, coverage window), and grades every check from the records, its own
model of the staged data and the fabric taps:

* CHK-DMA-PAIR    the random pairs SRAM<->scratch, WDT and AES words to SRAM,
                  the outbound legs (PR-OUT) and the extension-port legs (PR-EXT):
                  the port answers DECERR (PR-EXT-RSP) and the DMA ends with
                  STATUS.ERROR and ERROR_CODE.BUS_ERROR only.
* CHK-DMA-ALIAS   alias source and destination copy as their direct twins; the
                  directed direct copy; the alias write to the extension top
                  word reaches PR-EXT at 0x3FFF_FFF8, the port answers DECERR and
                  the DMA reports a bus error.
* CHK-DMA-USER    the source-ID stack over the SMU window word refuses the DMA
                  write and its permission flip admits it; every DMA beat on
                  PR-OUT carries AxUSER 0 and the routed address; the CPU store
                  carries a non-zero source ID (SEP's ID, not OTHERS).
* CHK-DMA-EP-REG  SCRATCH[0], SPI CSID and SEP_SW_DEBUG at a fixed address in
                  both directions; the SW_RESET_N read.
* CHK-DMA-EP-FILT the DMA read of inbound entry 0 FILTER_CONFIG.
* CHK-DMA-SMC     every DMA beat on PR-SMC has AxUSER 0 and AxLEN 0, in both
                  directions, with the CPU beat as the control; the CPU beat
                  carries a non-zero source ID.
* CHK-DMA-NOTCONN the boot ROM base and a DMA CSR word are not reached, and each
                  transfer ends with STATUS.ERROR and ERROR_CODE.BUS_ERROR only.
                  The bus response code of these cells is logged.

The model of every expected value is the stimulus itself (the seeded words the
firmware stages) and the RDL field layout; no expected value is read from the
DUT. cpu run mode, ``+skip_fuse_sense``, BH-SMC through the SMC aperture
plusargs of the testlist entry. The X checks on copied register words read the
SRAM write data and run on VCS.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fabric_tap import start_taps, stop_taps
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import (
    AP_OUTPUT_REMAP_CTRL_0,
    INBOUND_FILTER_CTRL_0,
    RegBlock,
    register_fields,
    sym,
)
from seq_lib.sep_fabric_csr_bank_seq import (
    DBW_LSB,
    DBW_RO_VAL,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_GROUP_ID_LSB,
    F_READ_ALLOWED,
    F_SRC_ID_LSB,
    F_WRITE_ALLOWED,
)
from seq_lib.sep_irq_aggregator_seq import PIC_DMA_DONE, PIC_DMA_ERROR, agg_from_pic

_TEST = "sep_fabric_dma_endpoint_matrix_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "dma_endpoint_matrix_test")
_ITCM_HEX = os.path.join(_FW_DIR, "dma_endpoint_matrix_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "dma_endpoint_matrix_test.dtcm.hex")
_BANNER = "SEP DMA endpoint matrix test"
_MAX_RUN_CYCLES = 8_000_000
_NO_BOOT_CYCLES = 80_000

# ---- Address map (generated register map) ----
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
SRAM = sym("SEP_SRAM_MEM_BASE_ADDR")
ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
AP_REGION = sym("AP_REGION_MEM_BASE_ADDR")
SCRATCH = sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR")
SECURE_DMA = RegBlock("SECURE_DMA")
SEP_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
DMA_CONTROL = SECURE_DMA.addr("CONTROL")
DMA_CSR_WORD = SECURE_DMA.addr("ENABLED_MEMORY_RANGE_LIMIT")
ST_DONE = SECURE_DMA.field_mask("STATUS", "done")
ST_ERROR = SECURE_DMA.field_mask("STATUS", "error")
ST_CHUNK = SECURE_DMA.field_mask("STATUS", "chunk_done")
ST3 = ST_DONE | ST_ERROR | ST_CHUNK
EC_BUS = SECURE_DMA.field_mask("ERROR_CODE", "bus_error")
EC_DEFINED = SECURE_DMA.mask("ERROR_CODE")
RESP_DECERR = 3
SRC_ID = 0xF  # AxUSER[3:0]: the source ID
LOCAL_ALIAS = SEP_CPU_CTRL.reset("SEP_LOCAL_BASE_ADDR")
EXT_WORD = sym("SEP_EXTERNAL_REG_MAP_BASE_ADDR") + 0x100
# FILTER_CONFIG field bits (low word, RW fields plus the RO data_bus_width).
CFG_FIELDS = INBOUND_FILTER_CTRL_0.mask32("FILTER_CONFIG")
REMAP_OFFSET_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")
REMAP_VALID_FIELD = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid")
EXT_TOP_ALIAS = 0xFFFF_FFF8
EXT_TOP_WORD = 0x3FFF_FFF8
STDOUT = 0x8000_0000
# The SMC aperture of the testlist entry (+sep_smc_aperture_base/size).
SMC_BASE = 0x4000_0000
SMC_SIZE = 0x0100_0000
# fabric.adoc, Address Remapping: sixteen regions over the AP window.
AP_IDX_START = 19
SCRATCH_BANK = 64
# Registers of the register-endpoint leg, in firmware id order.
REG_ADDR = (SCRATCH, RegBlock("SPI_CONTROLLER").addr("CSID"), SEP_CPU_CTRL.addr("SEP_SW_DEBUG"))
REG_NAME = ("scratch0", "spi_csid", "sep_sw_debug")
SW_RESET_N = RegBlock("SEP_RESET_CTRL").addr("SW_RESET_N")
FILT_IN0_CFG = sym("INBOUND_FILTER_CTRL_0__FILTER_CONFIG_REG_ADDR")
IRQ_DONE = agg_from_pic(PIC_DMA_DONE)
IRQ_ERROR = agg_from_pic(PIC_DMA_ERROR)

# SRAM bands of the legs (keep in step with the firmware).
B_PAIR = (0x0000, 0x1000, 0x2000, 0x3000)
B_DIRECT_SRC, B_DIRECT_DST = 0x4000, 0x5000
B_ALIAS_SRC, B_ALIAS_DST = 0x6000, 0x7000
BAND = 0x1000

# Parameter block layout (fw/tests/dma_endpoint_matrix_test, enum P_*).
P_MAGIC_WORD = 0xDAE9D0A3
P_FIELDS = (
    "magic order form seed p0_len p0_sram p0_scr p1_len p1_scr p1_sram p2_len p2_sram "
    "p3_len p3_sram pd_len pd_src pd_dst pa_len pa_os pa_od ap_off_lo ap_off_hi ap_intra "
    "smu reg_order reg_len0 reg_len1 reg_len2 reg_last0 reg_last1 reg_last2 filt_src "
    "filt_grp smc_off smc_len"
).split()
PAIR_NAMES = (
    ("sram", "scratch"),
    ("scratch", "sram"),
    ("wdt_regwen", "sram"),
    ("aes_ctrl_aux_regwen", "sram"),
)
PAIR_LEG = ("pair_sram_scratch", "pair_scratch_sram", "pair_wdt_sram", "pair_aes_sram")


# ---- Data model shared with the firmware ----
def seed_of(seed: int, tag: int) -> int:
    return (seed ^ ((tag * 0x9E3779B9) & 0xFFFF_FFFF)) & 0xFFFF_FFFF


def model_words(seed: int, tag: int, n: int) -> list[int]:
    x = seed_of(seed, tag)
    out = []
    for _ in range(n):
        x = (x * 1664525 + 1013904223) & 0xFFFF_FFFF
        out.append(x)
    return out


def fnv(words) -> int:
    h = 0x811C9DC5
    for w in words:
        h = ((h ^ w) * 0x01000193) & 0xFFFF_FFFF
    return h


@dataclass(frozen=True)
class DmaEpCfg:
    """The seeded stimulus. A pure function of the run seed."""

    p: dict

    @classmethod
    def from_seed(cls, seed: int) -> "DmaEpCfg":
        rng = SepSeededRng(seed)
        p = {"magic": P_MAGIC_WORD}
        order = [0, 1, 2, 3]
        rng.shuffle(order)
        p["order"] = sum(v << (4 * k) for k, v in enumerate(order))
        p["form"] = rng.getrandbits(4)
        p["seed"] = rng.getrandbits(32) | 1
        # Scratch pairs: length plus offset stay inside the 64-byte bank.
        for k, side in ((0, "p0_scr"), (1, "p1_scr")):
            off = rng.randrange(0, SCRATCH_BANK, 4)
            ln = rng.randrange(4, SCRATCH_BANK - off + 1, 4)
            p[f"p{k}_len"] = ln
            p[side] = off
            p[f"p{k}_sram"] = B_PAIR[k] + rng.randrange(0, BAND - ln + 1, 4)
        # Register sources at a fixed address: one chunk of 4 to 4096 bytes.
        for k in (2, 3):
            ln = rng.randrange(4, 4097, 4)
            p[f"p{k}_len"] = ln
            p[f"p{k}_sram"] = B_PAIR[k] + rng.randrange(0, BAND - ln + 1, 4)
        ln = rng.randrange(4, 257, 4)
        p["pd_len"] = ln
        p["pd_src"] = B_DIRECT_SRC + rng.randrange(0, BAND - ln + 1, 4)
        p["pd_dst"] = B_DIRECT_DST + rng.randrange(0, BAND - ln + 1, 4)
        ln = rng.randrange(4, 257, 4)
        p["pa_len"] = ln
        p["pa_os"] = B_ALIAS_SRC + rng.randrange(0, BAND - ln + 1, 4)
        p["pa_od"] = B_ALIAS_DST + rng.randrange(0, BAND - ln + 1, 4)
        # AP region 0: a non-identity offset; the word stays clear of STDOUT.
        while True:
            off = rng.getrandbits(37) << AP_IDX_START
            if off != AP_REGION and off + (1 << AP_IDX_START) < (1 << 56):
                break
        p["ap_off_lo"] = off & 0xFFFF_FFFF
        p["ap_off_hi"] = off >> 32
        p["ap_intra"] = rng.randrange(0x100, 1 << AP_IDX_START, 8)
        p["smu"] = STDOUT + rng.randrange(0x1000, 0x10_0000, 8)
        regs = [0, 1, 2]
        rng.shuffle(regs)
        p["reg_order"] = sum(v << (4 * k) for k, v in enumerate(regs))
        for k in range(3):
            p[f"reg_len{k}"] = rng.randrange(4, 65, 4)
        for k in range(3):
            p[f"reg_last{k}"] = rng.getrandbits(32)
        p["filt_src"] = rng.randrange(1, 16)
        p["filt_grp"] = rng.randrange(1, 16)
        ln = rng.randrange(16, 1025, 4)
        p["smc_len"] = ln
        p["smc_off"] = rng.randrange(0, SMC_SIZE - ln + 1, 4)
        return cls(p)

    def words(self) -> list[int]:
        return [self.p[k] & 0xFFFF_FFFF for k in P_FIELDS]

    @property
    def ap_offset(self) -> int:
        return (self.p["ap_off_hi"] << 32) | self.p["ap_off_lo"]

    @property
    def ap_out(self) -> int:
        """{offset[55:19], issued[18:0]} (fabric.adoc, Address Remapping)."""
        mask = (1 << AP_IDX_START) - 1
        return (self.ap_offset & ~mask & ((1 << 56) - 1)) | (self.p["ap_intra"] & mask)


@dataclass
class Leg:
    kind: str
    name: str
    t_ps: int
    marks: dict = field(default_factory=dict)
    sram_mark: int = 0
    irq_mark: int = 0


def _kv(line: str) -> dict:
    out = {}
    for tok in line.split()[2:]:
        if "=" not in tok:
            continue
        k, v = tok.split("=", 1)
        out[k] = int(v, 16) if v.startswith("0x") else v
    return out


@pyuvm.test()
class sep_fabric_dma_endpoint_matrix_test(sep_base_test):
    """DMA endpoint reach, alias forms, DMA AxUSER, SMC beats and not-connected targets meet their fabric contracts."""

    build_env = False
    required_evidence = (
        "CHK-DMA-PAIR",
        "CHK-DMA-ALIAS",
        "CHK-DMA-USER",
        "CHK-DMA-EP-REG",
        "CHK-DMA-EP-FILT",
        "CHK-DMA-SMC",
        "CHK-DMA-NOTCONN",
    )

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    # ---- live monitors ----
    async def _console(self) -> None:
        """Follow the M and R lines; mark the taps and drive the window.

        The tap marks are taken in the read-only phase of the edge that ends an
        M line. The gate write waits for the next edge, where writes are legal;
        the firmware spins after every M line, so no bus access of the leg
        falls between the two.
        """
        dut = cocotb.top
        line = []
        gate = None
        while True:
            await RisingEdge(dut.clk_i)
            if gate is not None:
                if gate:
                    open_graded_window(_TEST, self.logger)
                else:
                    close_graded_window(self.logger)
                gate = None
            await ReadOnly()
            v = dut.fw_char_valid_o.value
            if not (v.is_resolvable and int(v)):
                continue
            ch = chr(int(dut.fw_char_o.value) & 0xFF)
            if ch != "\n":
                line.append(ch)
                continue
            text = "".join(line)
            line = []
            if text.startswith("M "):
                parts = text.split()
                leg = Leg(parts[1], parts[2], get_sim_time("ps"))
                leg.marks = {n: t.mark() for n, t in self.taps.items()}
                leg.sram_mark = len(self.sram_wr)
                leg.irq_mark = len(self.irq_edges)
                self.legs.append(leg)
                gate = leg.kind == "G"
            elif text.startswith("R "):
                self.recs.append((len(self.legs) - 1, text))

    async def _sram_writes(self) -> None:
        """Every SRAM write beat with its strobed bytes, X and Z kept."""
        dut = cocotb.top
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            req, gnt, we = dut.pr_sram_req_o.value, dut.pr_sram_gnt_o.value, dut.pr_sram_we_o.value
            if not (req.is_resolvable and gnt.is_resolvable and int(req) and int(gnt)):
                continue
            if not (we.is_resolvable and int(we)):
                continue
            strb = dut.pr_sram_strb_o.value
            bits = str(dut.pr_sram_wdata_o.value)
            addr = dut.pr_sram_addr_o.value
            self.sram_wr.append(
                (
                    int(addr) if addr.is_resolvable else None,
                    int(strb) if strb.is_resolvable else None,
                    bits,
                )
            )

    async def _irq_edges(self) -> None:
        """Rising edges of the DMA done and error interrupts."""
        dut = cocotb.top
        prev = 0
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            v = dut.sep_internal_interrupts_probe_o.value
            cur = int(v) if v.is_resolvable else 0
            now = ((cur >> IRQ_DONE) & 1) | (((cur >> IRQ_ERROR) & 1) << 1)
            rise = now & ~prev
            if rise:
                self.irq_edges.append((get_sim_time("ps"), rise))
            prev = now

    # ---- record and window helpers ----
    def _leg_index(self, name: str, nth: int = 0) -> int:
        hits = [i for i, leg in enumerate(self.legs) if leg.name == name]
        if len(hits) <= nth:
            raise AssertionError(
                f"leg {name} (#{nth}) never started; legs seen: {[x.name for x in self.legs]}"
            )
        return hits[nth]

    def _beats(self, tap: str, leg_i: int, ch: str):
        start = self.legs[leg_i].marks[tap]
        stop = self.legs[leg_i + 1].marks[tap] if leg_i + 1 < len(self.legs) else None
        beats = self.taps[tap].beats[start:stop]
        return [b for b in beats if b.ch == ch]

    def _sram_in(self, leg_i: int):
        start = self.legs[leg_i].sram_mark
        stop = self.legs[leg_i + 1].sram_mark if leg_i + 1 < len(self.legs) else None
        return self.sram_wr[start:stop]

    def _recs(self, kind: str) -> list[tuple[int, dict, str]]:
        out = []
        for leg_i, text in self.recs:
            if text.split()[1] == kind:
                out.append((leg_i, _kv(text), text))
        return out

    def _one(self, kind: str, **match) -> tuple[int, dict, str]:
        hits = [
            r
            for r in self._recs(kind)
            if all(r[2].find(f" {k}={v}") >= 0 for k, v in match.items())
        ]
        if len(hits) != 1:
            raise AssertionError(f"expected one R {kind} {match}, got {len(hits)}")
        return hits[0]

    def _xz_free(self, writes) -> tuple[int, int]:
        """(writes, writes with an X or Z in a strobed byte)."""
        bad = 0
        for _addr, strb, bits in writes:
            if strb is None:
                bad += 1
                continue
            width = len(bits)
            for b in range(width // 8):
                if (strb >> b) & 1:
                    byte = bits[width - 8 * (b + 1) : width - 8 * b]
                    if re.search(r"[xXzZuUwW-]", byte):
                        bad += 1
                        break
        return len(writes), bad

    def _recovery_after(self, after: str) -> dict:
        hits = [r for r in self._recs("RECOV") if f" after={after} " in r[2] + " "]
        assert len(hits) == 1, f"recovery copy after {after}: {len(hits)} records"
        _, r, text = hits[0]
        n = 32 // 4
        exp = fnv(model_words(self.ep.p["seed"], r["tag"], n))
        ok = (
            (r["pre"] & ST3) == 0
            and (r["st"] & ST_DONE)
            and not (r["st"] & ST_ERROR)
            and r["nbad"] == 0
            and r["dsum"] == exp
        )
        assert ok, f"recovery copy after {after} failed: {text} (dsum expected 0x{exp:08x})"
        return r

    @staticmethod
    def _bus_error(r: dict) -> bool:
        """STATUS.ERROR set and ERROR_CODE holds BUS_ERROR and no other defined bit."""
        return bool(r["st"] & ST_ERROR) and (r["ec"] & EC_DEFINED) == EC_BUS

    def _port_decerr(self, leg_i: int, ch: str) -> list:
        """The PR-EXT replies of a leg; every one must be DECERR and there must be one."""
        rep = self._beats("PR-EXT-RSP", leg_i, ch)
        return rep if rep and all(b.resp == RESP_DECERR for b in rep) else []

    @staticmethod
    def _done_ok(r: dict, pre: str = "pre", st: str = "st", ec: str = "ec") -> bool:
        return (
            (r[pre] & ST3) == 0 and bool(r[st] & ST_DONE) and not (r[st] & ST_ERROR) and r[ec] == 0
        )

    # ---- checks ----
    def _chk_pairs(self) -> None:
        p, seed = self.ep.p, self.ep.p["seed"]
        for pid in range(4):
            leg_i, r, text = self._one("PAIR", id=f"0x{pid:08x}")
            assert self._leg_index(PAIR_LEG[pid]) == leg_i, f"pair {pid} record outside its leg"
            ln = p[f"p{pid}_len"]
            n = ln // 4
            assert r["len"] == ln, f"pair {pid}: firmware ran len 0x{r['len']:x}, patched 0x{ln:x}"
            assert self._done_ok(r), (
                f"CHK-DMA-PAIR FAIL: pair {pid} did not complete cleanly: {text}"
            )
            if pid in (0, 1):
                m = model_words(seed, 0x10 + pid, n)
                scr = SCRATCH + (p["p0_scr"] if pid == 0 else p["p1_scr"])
                graded = [m[i] for i in range(n) if ((scr + 4 * i) & 4) == 0]
                exp = fnv(graded)
                ok = r["ng"] == len(graded) and r["nbad"] == 0 and r["dsum"] == exp
                assert ok, (
                    f"CHK-DMA-PAIR FAIL: src={PAIR_NAMES[pid][0]} dst={PAIR_NAMES[pid][1]} len={ln} "
                    f"graded={len(graded)} ng={r['ng']} nbad={r['nbad']} dsum=0x{r['dsum']:08x} "
                    f"expect=0x{exp:08x}"
                )
                self.logger.info(
                    "CHK-DMA-PAIR PASS: src=%s dst=%s len=%d data_ok=1 done=1 form=%s graded_words=%d "
                    "dsum=0x%08x expect=0x%08x rsvd_half_sum=0x%08x(logged)",
                    *PAIR_NAMES[pid],
                    ln,
                    "alias" if (p["form"] >> pid) & 1 else "direct",
                    len(graded),
                    r["dsum"],
                    exp,
                    r["rsum"],
                )
            else:
                nw, xz = self._xz_free(self._sram_in(leg_i))
                xz_graded = "vcs" in str(getattr(cocotb, "SIM_NAME", "") or "").lower()
                ok = (
                    (r["regpre"] & 1) == 1
                    and (r["regpost"] & 1) == 1
                    and r["nbit0bad"] == 0
                    and (r["dand"] & 1) == 1
                    and xz == 0
                    and nw >= n
                )
                assert ok, (
                    f"CHK-DMA-PAIR FAIL: src={PAIR_NAMES[pid][0]} dst=sram len={ln} regpre=0x{r['regpre']:x} "
                    f"regpost=0x{r['regpost']:x} nbit0bad={r['nbit0bad']} dand=0x{r['dand']:x} "
                    f"sram_writes={nw} xz={xz}"
                )
                self.logger.info(
                    "CHK-DMA-PAIR PASS: src=%s dst=sram len=%d data_ok=1 done=1 bit0_pre=1 bit0_post=1 "
                    "dst_bit0_all=1 sram_writes=%d xz=0 xz_graded=%d rsvd_or=0x%08x rsvd_and=0x%08x(logged)",
                    PAIR_NAMES[pid][0],
                    ln,
                    nw,
                    int(bool(xz_graded)),
                    r["dor"] & ~1,
                    r["dand"] & ~1,
                )

        # Outbound legs: completion and the PR-OUT beats of each leg.
        for tgt, leg, exp0 in (("ap", "out_ap", self.ep.ap_out), ("smu", "out_smu", p["smu"])):
            leg_i = self._leg_index(leg)
            _, r, text = self._one("OUT", tgt=tgt)
            assert self._done_ok(r), (
                f"CHK-DMA-PAIR FAIL: outbound {tgt} leg did not complete: {text}"
            )
            aws = [b for b in self._beats("PR-OUT", leg_i, "aw") if b.addr != STDOUT]
            addrs = [b.addr for b in aws]
            assert addrs == [exp0, exp0 + 4], (
                f"CHK-DMA-PAIR FAIL: PR-OUT {tgt} leg beats {[hex(a) if a is not None else 'X' for a in addrs]}, "
                f"expected 0x{exp0:x}, 0x{exp0 + 4:x}"
            )
            self.logger.info(
                "CHK-DMA-PAIR PASS: src=sram dst=%s len=8 data_ok=na done=1 seen=PR-OUT beats=%d first=0x%x",
                tgt,
                len(aws),
                exp0,
            )

        # Extension port: one beat each way; the response is logged only.
        for d, leg, ch in (("R", "ext_r", "ar"), ("W", "ext_w", "aw")):
            leg_i = self._leg_index(leg)
            _, r, text = self._one("EXT", dir=d)
            beats = self._beats("PR-EXT", leg_i, ch)
            assert beats and beats[0].addr == EXT_WORD, (
                f"CHK-DMA-PAIR FAIL: PR-EXT {ch} of the {leg} leg: {[b.fmt() for b in beats]}, "
                f"expected first at 0x{EXT_WORD:x}"
            )
            # The port answers DECERR (port table: tie to DECERR if unused), and
            # the DMA reports it as a bus error.
            rep = self._port_decerr(leg_i, "r" if d == "R" else "b")
            assert rep and self._bus_error(r), (
                f"CHK-DMA-PAIR FAIL: ext_{d.lower()} port_resp={[b.resp for b in self._beats('PR-EXT-RSP', leg_i, 'r' if d == 'R' else 'b')]} "
                f"dma_status=0x{r['st']:08x} error_code=0x{r['ec']:08x}; expected port DECERR, "
                "STATUS.ERROR and ERROR_CODE.BUS_ERROR only"
            )
            self._recovery_after(leg)
            self.logger.info(
                "CHK-DMA-PAIR PASS: src=%s dst=%s len=4 data_ok=na done=na seen=PR-EXT %s=0x%x beats=%d "
                "port_resp=DECERR replies=%d dma_status=0x%08x error_code=0x%08x recovery_ok=1",
                "ext" if d == "R" else "sram",
                "sram" if d == "R" else "ext",
                ch,
                EXT_WORD,
                len(beats),
                len(rep),
                r["st"],
                r["ec"],
            )

    def _chk_alias(self) -> None:
        p, seed = self.ep.p, self.ep.p["seed"]
        _, r, text = self._one("ALIAS", form="direct")
        n = p["pd_len"] // 4
        exp = fnv(model_words(seed, 0x20, n))
        ok = self._done_ok(r) and r["nbad"] == 0 and r["dsum"] == exp
        assert ok, f"CHK-DMA-ALIAS FAIL: direct copy {text} expect dsum=0x{exp:08x}"
        self.logger.info(
            "CHK-DMA-ALIAS PASS: form=direct alias=na direct=0x%08x data_ok=1 len=%d dsum=0x%08x expect=0x%08x",
            SRAM + p["pd_dst"],
            p["pd_len"],
            r["dsum"],
            exp,
        )

        _, r, text = self._one("ALIAS", form="alias")
        n = p["pa_len"] // 4
        exp = fnv(model_words(seed, 0x40, n))
        ok = (
            self._done_ok(r)
            and r["ctl_nbad"] == 0
            and r["ctl_sum"] == exp
            and r["nbad"] == 0
            and r["dsum"] == exp
            and r["src"] == LOCAL_ALIAS + p["pa_os"]
            and r["dst"] == LOCAL_ALIAS + p["pa_od"]
        )
        assert ok, f"CHK-DMA-ALIAS FAIL: alias copy {text} expect sum=0x{exp:08x}"
        self.logger.info(
            "CTL-DMA-ALIAS LOG: direct source 0x%08x read by the LSU sum=0x%08x expect=0x%08x",
            SRAM + p["pa_os"],
            r["ctl_sum"],
            exp,
        )
        self.logger.info(
            "CHK-DMA-ALIAS PASS: form=alias alias=0x%08x direct=0x%08x data_ok=1 side=src,dst len=%d",
            LOCAL_ALIAS + p["pa_os"],
            SRAM + p["pa_os"],
            p["pa_len"],
        )

        leg_i = self._leg_index("alias_ext_top")
        _, r, _text = self._one("ALIASEXT")
        aws = self._beats("PR-EXT", leg_i, "aw")
        assert aws and aws[0].addr == EXT_TOP_WORD, (
            f"CHK-DMA-ALIAS FAIL: alias write to 0x{EXT_TOP_ALIAS:x}: PR-EXT aw {[b.fmt() for b in aws]}, "
            f"expected first at 0x{EXT_TOP_WORD:x}"
        )
        rep = self._port_decerr(leg_i, "b")
        assert rep and self._bus_error(r), (
            f"CHK-DMA-ALIAS FAIL: alias_ext_top port_resp={[b.resp for b in self._beats('PR-EXT-RSP', leg_i, 'b')]} "
            f"dma_status=0x{r['st']:08x} error_code=0x{r['ec']:08x}; expected port DECERR, "
            "STATUS.ERROR and ERROR_CODE.BUS_ERROR only"
        )
        self._recovery_after("alias_ext_top")
        self.logger.info(
            "CTL-DMA-ALIAS LOG: alias_ext_top later_beats=%s port_resp=DECERR replies=%d "
            "dma_status=0x%08x error_code=0x%08x",
            [hex(b.addr) if b.addr is not None else "X" for b in aws[1:]],
            len(rep),
            r["st"],
            r["ec"],
        )
        self.logger.info(
            "CHK-DMA-ALIAS PASS: form=alias alias=0x%08x direct=0x%08x data_ok=1 seen=PR-EXT recovery_ok=1",
            EXT_TOP_ALIAS,
            EXT_TOP_WORD,
        )

    def _filter_sum(self, entries) -> int:
        """FNV over the FILTER_CONFIG field bits as written (data_bus_width reads 3).

        START and END are not in the sum: the specification states no
        write-back timing for them, so the firmware logs their read-back only.
        """
        dbw = DBW_RO_VAL << DBW_LSB
        return fnv([(cfg | dbw) & CFG_FIELDS for cfg, _start, _end in entries])

    def _chk_user(self) -> None:
        p = self.ep.p
        rw_en = F_READ_ALLOWED | F_WRITE_ALLOWED | F_ENTRY_ENABLED
        ns = F_ALLOW_NS
        _, r, text = self._one("OUTSET")
        ap, smu = self.ep.ap_out, p["smu"]
        exp_set = self._filter_sum(
            [
                (rw_en, ap, ap + 7),
                (rw_en | ns, ap, ap + 7),
                (rw_en, smu, smu + 7),
                (rw_en | ns, smu, smu + 7),
            ]
        )
        attrs = (r["attrs_hi"] << 32) | r["attrs_lo"]
        want_attrs = (self.ep.ap_offset & REMAP_OFFSET_FIELD) | REMAP_VALID_FIELD
        self.logger.info(
            "OBS-FILTER-RANGE: out_setup START/END read-back differences=%d (logged)", r["rng_diff"]
        )
        assert r["rb_bad"] == 0 and r["rb_sum"] == exp_set and attrs == want_attrs, (
            f"CHK-DMA-USER FAIL: outbound set-up read-back {text}; expected rb_sum=0x{exp_set:08x} "
            f"attrs=0x{want_attrs:016x}"
        )

        _, r, text = self._one("STACK")
        stack = [(rw_en | (i + 1) << F_SRC_ID_LSB, smu, smu + 7) for i in range(15)]
        stack += [(rw_en | ns | (i + 1) << F_SRC_ID_LSB, smu, smu + 7) for i in range(15)]
        ro_en = F_READ_ALLOWED | F_ENTRY_ENABLED
        stack += [(ro_en, smu, smu + 7), (ro_en | ns, smu, smu + 7)]
        exp1 = self._filter_sum(stack)
        exp2 = self._filter_sum([(rw_en, smu, smu + 7), (rw_en | ns, smu, smu + 7)])
        self.logger.info(
            "OBS-FILTER-RANGE: stack START/END read-back differences=%d, after the flip=%d (logged)",
            r["rng1_diff"],
            r["rng2_diff"],
        )
        refused = (r["pre"] & ST3) == 0 and bool(r["st"] & ST_ERROR) and bool(r["ec"] & EC_BUS)
        control = self._done_ok(r, "ctl_pre", "ctl_st", "ctl_ec")
        ok = (
            r["rb1_bad"] == 0
            and r["rb1_sum"] == exp1
            and r["rb2_bad"] == 0
            and r["rb2_sum"] == exp2
            and refused
            and control
        )
        assert ok, (
            f"CHK-DMA-USER FAIL: stack {text}; expected rb1_sum=0x{exp1:08x} rb2_sum=0x{exp2:08x}, "
            "a refused write (STATUS.ERROR with ERROR_CODE.BUS_ERROR) and a clean control write"
        )
        self._recovery_after("stack")

        # PR-OUT: every DMA beat carries AxUSER 0 and the routed address.
        legs = (
            ("out_ap", [self.ep.ap_out, self.ep.ap_out + 4]),
            ("out_smu", [smu, smu + 4]),
            ("stack", [smu, smu + 4]),
        )
        for leg, exp_addrs in legs:
            leg_i = self._leg_index(leg)
            aws = [b for b in self._beats("PR-OUT", leg_i, "aw") if b.addr != STDOUT]
            bad = [b.fmt() for b in aws if b.user != 0]
            addrs = [b.addr for b in aws]
            assert not bad and addrs == exp_addrs, (
                f"CHK-DMA-USER FAIL: PR-OUT in {leg}: beats {[b.fmt() for b in aws]}; expected AxUSER 0 at "
                f"{[hex(a) for a in exp_addrs]}"
            )
            self.logger.info(
                "OBS-BLOCKED: %s dma_prot=%s (the DMA prot[1] value is not stated; both allow_ns entries run)",
                leg,
                [b.prot for b in aws],
            )
            self.logger.info(
                "CHK-DMA-USER PASS: probe=PR-OUT leg=%s beats=%d user_nonzero=0 addr=%s",
                leg,
                len(aws),
                ",".join(f"0x{a:x}" for a in addrs),
            )
        leg_i = self._leg_index("out_cpu")
        cpu = [b for b in self._beats("PR-OUT", leg_i, "aw") if b.addr == smu]
        assert cpu, "CHK-DMA-USER FAIL: the CPU store to the SMU window word shows no PR-OUT beat"
        # The CPU masters drive SEP's source ID, not OTHERS (0); the number is
        # not stated, so the value is logged.
        cpu_ids = [None if b.user is None else b.user & SRC_ID for b in cpu]
        assert all(i not in (None, 0) for i in cpu_ids), (
            f"CHK-DMA-USER FAIL: the CPU store to the SMU window carries source ID {cpu_ids}; "
            "expected SEP's ID, not OTHERS (0)"
        )
        self.logger.info(
            "OBS-CPU-SRC-ID: cpu_store_to_smu user=%s (value logged)", [b.user for b in cpu]
        )
        self.logger.info(
            "CHK-DMA-USER PASS: dst=smu stack_resp=DECERR dma_status=0x%08x error_code=0x%08x "
            "control_complete=1 control_status=0x%08x",
            r["st"],
            r["ec"],
            r["ctl_st"],
        )

    def _chk_ep_reg(self) -> None:
        p, seed = self.ep.p, self.ep.p["seed"]
        _, pre_r, _ = self._one("REGPRE")
        for rid in range(3):
            leg_r = self._leg_index(f"reg_r_{REG_NAME[rid]}")
            _, r, text = self._one("REG", name=REG_NAME[rid])
            _w, fields = register_fields(REG_ADDR[rid])
            mask = 0
            for f in fields:
                mask |= f.mask
            mask &= 0xFFFF_FFFF
            assert mask == 0xFFFF_FFFF, (
                f"{REG_NAME[rid]} field bits changed (0x{mask:x}); revisit the destination compare"
            )
            pre = pre_r[REG_NAME[rid]]
            last = p[f"reg_last{rid}"]
            if last == pre:
                last ^= 1
            n = p[f"reg_len{rid}"] // 4
            nw, xz = self._xz_free(self._sram_in(leg_r))
            self.logger.info(
                "CTL-DMA-EP-REG LOG: reg=%s lsu_before=0x%08x lsu_after=0x%08x expect=0x%08x",
                REG_NAME[rid],
                r["ctl_a"],
                r["ctl_b"],
                last,
            )
            ok = (
                r["regpre"] == pre
                and r["last"] == last
                and last != pre
                and r["len"] == p[f"reg_len{rid}"]
                and self._done_ok(r, "w_pre", "w_st", "w_ec")
                and self._done_ok(r, "r_pre", "r_st", "r_ec")
                and (r["rb"] & mask) == last
                and (r["ctl_a"] & mask) == last
                and (r["ctl_b"] & mask) == last
                and r["nbad"] == 0
                and xz == 0
                and nw >= n
            )
            assert ok, (
                f"CHK-DMA-EP-REG FAIL: reg={REG_NAME[rid]} {text}; expected last=0x{last:08x} "
                f"sram_writes={nw} xz={xz}"
            )
            # The source words before the last one have no approved anchor.
            _ = model_words(seed, 0x60 + rid, n)
            self.logger.info(
                "CHK-DMA-EP-REG PASS: reg=%s dir=W words=%d conserve=1 readback=0x%08x expect=0x%08x",
                REG_NAME[rid],
                n,
                r["rb"],
                last,
            )
            self.logger.info(
                "CHK-DMA-EP-REG PASS: reg=%s dir=R words=%d conserve=1 readback=0x%08x expect=0x%08x "
                "sram_writes=%d xz=0 restored=0x%08x",
                REG_NAME[rid],
                n,
                r["dand"],
                last,
                nw,
                r["restored"],
            )

        leg_i = self._leg_index("rst_r")
        _, r, text = self._one("RST")
        nw, xz = self._xz_free(self._sram_in(leg_i))
        _w, fields = register_fields(SW_RESET_N)
        mask = 0
        for f in fields:
            mask |= f.mask
        mask &= 0xFFFF_FFFF
        ok = self._done_ok(r) and (r["dma"] & mask) == (r["lsu"] & mask) and xz == 0 and nw >= 1
        assert ok, (
            f"CHK-DMA-EP-REG FAIL: SW_RESET_N {text} mask=0x{mask:x} sram_writes={nw} xz={xz}"
        )
        self.logger.info(
            "CHK-DMA-EP-REG PASS: reg=sw_reset_n dir=R words=1 conserve=1 readback=0x%08x expect=0x%08x "
            "field_mask=0x%x rsvd=0x%08x(logged) xz=0",
            r["dma"] & mask,
            r["lsu"] & mask,
            mask,
            r["dma"] & ~mask & 0xFFFF_FFFF,
        )

    def _chk_ep_filt(self) -> None:
        p = self.ep.p
        leg_i = self._leg_index("filt_r")
        _, r, text = self._one("FILT")
        _w, fields = register_fields(FILT_IN0_CFG)
        mask = 0
        for f in fields:
            mask |= f.mask
        mask &= 0xFFFF_FFFF
        assert mask == CFG_FIELDS, f"FILTER_CONFIG field bits 0x{mask:x} differ from the RDL mask"
        expect = (
            (DBW_RO_VAL << DBW_LSB)
            | (p["filt_src"] << F_SRC_ID_LSB)
            | (p["filt_grp"] << F_GROUP_ID_LSB)
        )
        nw, xz = self._xz_free(self._sram_in(leg_i))
        ok = (
            self._done_ok(r)
            and (r["dma"] & mask) == expect
            and (r["lsu"] & mask) == expect
            and xz == 0
            and nw >= 1
        )
        assert ok, (
            f"CHK-DMA-EP-FILT FAIL: {text}; expected field bits 0x{expect:08x} sram_writes={nw} xz={xz}"
        )
        self.logger.info(
            "CHK-DMA-EP-FILT PASS: data_bus_width=3 word=0x%08x mask=0x%08x expect=0x%08x lsu=0x%08x "
            "rsvd=0x%08x restored=0x%08x",
            r["dma"],
            mask,
            expect,
            r["lsu"],
            r["dma"] & ~mask & 0xFFFF_FFFF,
            r["restored"],
        )

    def _chk_smc(self) -> None:
        p, seed = self.ep.p, self.ep.p["seed"]
        _, r, text = self._one("SMC")
        ln, n = p["smc_len"], p["smc_len"] // 4
        addr = SMC_BASE + p["smc_off"]
        m = model_words(seed, 0x70, n)
        assert r["fuse"] & SEP_CPU_CTRL.field_mask(
            "SMC_FUSE_SENSE_STATUS", "smc_fuse_sense_done"
        ), f"CHK-DMA-SMC FAIL: smc_fuse_sense_done reads 0 after {r['polls']} polls"
        assert self._done_ok(r, "w_pre", "w_st", "w_ec") and self._done_ok(
            r, "r_pre", "r_st", "r_ec"
        ), f"CHK-DMA-SMC FAIL: SMC legs did not complete: {text}"
        exp = fnv(m)
        assert r["nbad"] == 0 and r["dsum"] == exp, (
            f"CHK-DMA-SMC FAIL: SRAM after the read leg {text}; expected dsum=0x{exp:08x}"
        )
        assert r["cpu"] == m[0], (
            f"CHK-DMA-SMC FAIL: the CPU read of 0x{addr:x} returned 0x{r['cpu']:08x}; the SMC model "
            f"should hold the first source word 0x{m[0]:08x}"
        )
        ctl_i = self._leg_index("smc_cpu")
        ctl = [b for b in self._beats("PR-SMC", ctl_i, "ar") if b.addr == addr]
        assert ctl, "CHK-DMA-SMC FAIL: the CPU control read shows no beat on PR-SMC"
        ctl_ids = [None if b.user is None else b.user & SRC_ID for b in ctl]
        assert all(i not in (None, 0) for i in ctl_ids), (
            f"CHK-DMA-SMC FAIL: the CPU read on PR-SMC carries source ID {ctl_ids}; "
            "expected SEP's ID, not OTHERS (0)"
        )
        self.logger.info(
            "OBS-CPU-SRC-ID: smc cpu_beat user=%s (value logged)", [b.user for b in ctl]
        )
        for d, leg, ch in (("w", "smc_w", "aw"), ("r", "smc_r", "ar")):
            leg_i = self._leg_index(leg)
            beats = self._beats("PR-SMC", leg_i, ch)
            user_nz = sum(1 for b in beats if b.user != 0)
            len_nz = sum(1 for b in beats if b.len != 0)
            addrs = [b.addr for b in beats]
            want = [addr + 4 * i for i in range(n)]
            data_ok = True
            if d == "w":
                ws = self._beats("PR-SMC", leg_i, "w")
                lanes = []
                for k, b in enumerate(ws):
                    if b.data is None:
                        lanes.append(None)
                    else:
                        lanes.append(
                            (b.data >> 32) & 0xFFFF_FFFF if want[k] & 4 else b.data & 0xFFFF_FFFF
                        )
                data_ok = lanes == m
            ok = len(beats) == n and user_nz == 0 and len_nz == 0 and addrs == want and data_ok
            assert ok, (
                f"CHK-DMA-SMC FAIL: dir={d} beats={len(beats)} expected={n} user_nonzero={user_nz} "
                f"len_nonzero={len_nz} addr_ok={addrs == want} data_ok={data_ok}"
            )
            self.logger.info(
                "CHK-DMA-SMC PASS: fuse_done=1 dir=%s beats=%d user_nonzero=0 len_nonzero=0 data_ok=1 "
                "control_beats=%d addr=0x%x len=%d",
                d,
                len(beats),
                len(ctl),
                addr,
                ln,
            )

    def _go_and_irq(self, leg_i: int) -> tuple[int, int | None]:
        """Time of the CONTROL (GO) write handshake of the leg and of the next DMA interrupt edge."""
        gos = [
            b
            for b in self._beats("PR-DMACSR", leg_i, "aw")
            if b.addr is not None and (b.addr & 0xFFF) == (DMA_CONTROL & 0xFFF)
        ]
        assert gos, f"leg {self.legs[leg_i].name}: no CONTROL write on PR-DMACSR"
        t_go = gos[-1].t_ps
        edges = [t for t, _r in self.irq_edges[self.legs[leg_i].irq_mark :] if t > t_go]
        return t_go, (edges[0] if edges else None)

    def _chk_notconn(self) -> None:
        ctl_i = self._leg_index("nc_ctl")
        _, c0, _ = self._one("NCCTL")
        rom_ctl = [
            b
            for b in self._beats("PR-ROM", ctl_i, "req")
            if b.addr is not None and (b.addr & 0xFFFF) == 0
        ]
        assert len(rom_ctl) >= 1, (
            "CHK-DMA-NOTCONN FAIL: the LSU read of the boot ROM base shows no PR-ROM handshake"
        )
        _, c2, _ = self._one("NCCTL2")
        self.logger.info(
            "CTL-DMA-NOTCONN LOG: rom=0x%08x csr=0x%08x rom_after=0x%08x csr_after=0x%08x rom_ctrl_seen=%d",
            c0["rom"],
            c0["csr"],
            c2["rom"],
            c2["csr"],
            len(rom_ctl),
        )
        assert c0["csr"] != 0, (
            "the DMA CSR control word reads 0; the not-connected compare needs a non-zero word"
        )
        names = {"rom_src": "nc_rom_src", "rom_dst": "nc_rom_dst", "dma_csr_src": "nc_csr_src"}
        graded = 0
        for _leg_rec, r, text in self._recs("NC"):
            tgt = text.split("tgt=")[1].split()[0]
            leg_i = self._leg_index(names[tgt])
            end = {0: "done", 1: "error", 2: "timeout"}[r["end"]]
            assert (r["pre"] & ST3) == 0, (
                f"CHK-DMA-NOTCONN FAIL: {tgt} STATUS bits not clear before GO: {text}"
            )
            t_go, t_irq = self._go_and_irq(leg_i)
            assert t_irq is not None, (
                f"CHK-DMA-NOTCONN FAIL: {tgt} ended {end} with no DMA interrupt edge"
            )
            # No DMA path reaches the boot ROM or the DMA CSR port, so the transfer
            # ends in error with a bus error; the bus response code is logged.
            assert end == "error" and self._bus_error(r), (
                f"CHK-DMA-NOTCONN FAIL: {tgt} end={end} dma_status=0x{r['st']:08x} "
                f"error_code=0x{r['ec']:08x}; expected STATUS.ERROR and ERROR_CODE.BUS_ERROR only"
            )
            self.logger.info(
                "CHK-DMA-NOTCONN LOG: %s end=error dma_status=0x%08x error_code=0x%08x",
                tgt,
                r["st"],
                r["ec"],
            )
            rom_win = [b for b in self._beats("PR-ROM", leg_i, "req") if t_go < b.t_ps <= t_irq]
            self._recovery_after(names[tgt])
            if tgt == "rom_src":
                ok = r["dst"] != r["src_v"] and r["src_v"] == c0["rom"]
                assert ok, f"CHK-DMA-NOTCONN FAIL: {text}: the destination holds the boot ROM word"
                self.logger.info(
                    "CHK-DMA-NOTCONN PASS: target=rom_src src_value=0x%08x dst_value=0x%08x end=%s "
                    "dma_status=0x%08x control_value=0x%08x recovery_ok=1 rom_seen=%d",
                    r["src_v"],
                    r["dst"],
                    end,
                    r["st"],
                    c0["rom"],
                    len(rom_win),
                )
            elif tgt == "rom_dst":
                assert not rom_win, (
                    f"CHK-DMA-NOTCONN FAIL: PR-ROM shows {len(rom_win)} handshakes between GO and the interrupt"
                )
                self.logger.info(
                    "CHK-DMA-NOTCONN PASS: target=rom_dst rom_seen=0 rom_ctrl_seen=%d end=%s dma_status=0x%08x recovery_ok=1",
                    len(rom_ctl),
                    end,
                    r["st"],
                )
            else:
                csr = self._beats("PR-DMACSR", leg_i, "aw") + self._beats("PR-DMACSR", leg_i, "ar")
                in_win = [b for b in csr if t_go < b.t_ps <= t_irq]
                ctrl = [b for b in csr if b.t_ps <= t_go]
                ok = r["dst"] != r["src_v"] and r["src_v"] == c0["csr"] and not in_win and ctrl
                assert ok, (
                    f"CHK-DMA-NOTCONN FAIL: {text}: csr_seen={len(in_win)} csr_ctrl_seen={len(ctrl)} "
                    f"(destination must not hold 0x{c0['csr']:08x})"
                )
                self.logger.info(
                    "CHK-DMA-NOTCONN PASS: target=dma_csr_src src_value=0x%08x dst_value=0x%08x end=%s "
                    "dma_status=0x%08x control_value=0x%08x recovery_ok=1 csr_seen=0 csr_ctrl_seen=%d",
                    r["src_v"],
                    r["dst"],
                    end,
                    r["st"],
                    c0["csr"],
                    len(ctrl),
                )
            graded += 1
        assert graded == len(names), (
            f"CHK-DMA-NOTCONN FAIL: {graded} not-connected runs graded, expected {len(names)}"
        )
        self.logger.info("STEP not-connected: %d graded runs", graded)

    # ---- scenario ----
    def _stage_dtcm(self) -> str:
        self.ep = DmaEpCfg.from_seed(self.random_seed())
        patched = os.path.join(os.getcwd(), "sep_dtcm_dma_ep.hex")
        patch_param_block(_DTCM_HEX, patched, P_MAGIC_WORD, self.ep.words())
        self.logger.info(
            "DMA endpoint RAND seed=%d params=%s",
            self.random_seed(),
            " ".join(f"{k}=0x{v:x}" for k, v in self.ep.p.items()),
        )
        return patched

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        self.legs: list[Leg] = []
        self.recs: list[tuple[int, str]] = []
        self.sram_wr: list = []
        self.irq_edges: list = []
        dtcm = self._stage_dtcm()
        self.taps = start_taps("PR-OUT", "PR-EXT", "PR-EXT-RSP", "PR-SMC", "PR-ROM", "PR-DMACSR")
        mons = [
            cocotb.start_soon(self._console()),
            cocotb.start_soon(self._sram_writes()),
            cocotb.start_soon(self._irq_edges()),
        ]
        close_graded_window(self.logger)
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            dtcm,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
        )
        close_graded_window(self.logger)
        for m in mons:
            m.cancel()
        await stop_taps(self.taps)
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"

        _, prm, _ = self._one("PARAMS")
        for k in ("seed", "order", "form", "smu", "smc_off"):
            assert prm[k] == self.ep.p[k], (
                f"firmware ran {k}=0x{prm[k]:x}, patched 0x{self.ep.p[k]:x}"
            )
        self._chk_pairs()
        self._chk_alias()
        self._chk_user()
        self._chk_ep_reg()
        self._chk_ep_filt()
        self._chk_smc()
        self._chk_notconn()
