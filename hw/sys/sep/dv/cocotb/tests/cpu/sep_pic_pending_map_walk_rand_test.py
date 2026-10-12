# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each driven source sets only its own meip bit; the crypto alerts reach source 33; the gateway cells and the boundary input follow the PIC register text.

Firmware ``pic_pending_map_walk_rand_test`` keeps ``mstatus.MIE`` at 0 and
drives, in the drawn orders, the 24 map sources (1 to 8, 12, 14, 18 to 30 and
33) over two map passes with complementary IP enable masks, the FIFO-empty
sources 19 and 22 after a real fill and drain, the SPI error cause, the 11
crypto alert kinds, the native errors, the DMA alert, the slotless blocks, the
gateway cells and the clear values, and prints every ``meip`` read. This test
draws every value from the run seed and patches it into the parameter block,
samples the aggregate vector ``sep_internal_interrupts_probe_o``, the ``irq``
field of ``sep_io_spi_req_o`` (``sep_io_spi_irq_w`` in ``tb_top``),
``crypto_alert_pulse_probe_o`` and
``pic_rd_data_probe_o`` at the firmware ``REQ`` lines, drives
``hmac_fifo_drain_stall_i``, ``kmac_fifo_drain_stall_i`` and
``sep_ext_interrupts_i`` on request, and grades:

* CHK-BASE         reset, map-release and final: every graded vector and
                   ``meip`` bit reads 0 (the band above 43 included); on VCS no
                   vector bit and no ``pic_rd_data_probe_o`` reset read is X,
                   and the tap equals the firmware word at the map-pass reads.
* CHK-VECTOR       the ``meip`` words of each map pass equal the OR vector of
                   the driven sources with IP enable 1; sources 12 and 33 show
                   a high vector clock; the single-source reads of 24 and 33.
* CHK-FIFO-EMPTY   sources 19 and 22 pending (``meip`` and vector) after the
                   fill under the drain stall and the drain with the enable at
                   1, and 0 after the enable clear. A fill that does not read
                   ``STATUS.fifo_full`` = 1 fails the check.
* CHK-SPI          vector bit 13 equals the SPI ``irq`` field, raised and after
                   the write-one-to-clear.
* CHK-ALERT12, CHK-ALERT-AGG, CHK-ALERT-IDX, CHK-ALERT-IDLE, CHK-ALERT-NONE,
  CHK-ALERT-NATIVE  the DMA alert on source 12, each crypto alert kind on
                   source 33 at exactly one receiver index of its block, the
                   pair trial, no source 33 in an idle-engine window, with no
                   write, or for a native error.
* CHK-SRC17, CHK-IDLE-BAND  source 17 and the band above 43 stay 0 with
                   ``meie`` and ``meipl`` armed; live source 24 reads 1.
* CHK-SLOTLESS     an OTP read and a life-cycle controller read move no vector
                   bit; the AES status reads done after the encryption (the
                   AES vector bits are the control).
* CHK-GW-CELL, CHK-EDGE-HOLD, CHK-HOLD, CHK-CLR-IDLE, CHK-GWCLR-VALUE,
  CHK-GW-NONVAC    the gateway cells LH, LL and EH, the edge hold with its level
                   twin, the level hold, the idle clear and the clear values.
* CHK-EXT-IN       one (two) asserted boundary bits show as one (two) pending
                   sources above 43, the assigned sources stay at their
                   baseline, and the band drops at the release.

Logged, not graded: ``OBS-IDLE-UNSTATED`` (sources 13, 15, 16, 37, 38, 39,
masked in every compare), ``OBS-GW-EL``, ``OBS-MASKED-VISIBLE``, ``OBS-SRC34``,
the source 12 latency and shape, the boundary source index, and the controls
``CTL-VECTOR``, ``CTL-FIFO-EMPTY`` and ``CTL-SLOTLESS``.

The firmware brings the entropy stack up before the engine runs (AES masking
and the OTBN URND draw from EDN); this test drives the raw noise of the ring
oscillators (``start_esrc_noise_driver``), which needs ``+esrc_noise_force``.
The idle-engine window runs before the FIFO-empty set-up: the HMAC drain stall
holds only the FIFO read side, so the HMAC message cannot complete after it
(logged as ``CTL-HMAC-AFTER-STALL``).

Every expected value comes from the stimulus model (the drawn sources,
enables, gateway cells and clear values; ``env/sep_pic_map``) and the PIC
register text, never from a DUT read. cpu run mode, ``+skip_fuse_sense``.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fw_console import SepFwConsole, parse_kv
from env.sep_pic_map import (
    EXCLUDED_IDLE_SOURCES,
    MEIP_WORDS,
    NUM_VEC,
    SRC_CRYPTO_ALERT,
    SRC_DMA_ALERT,
    SRC_HMAC_FIFO_EMPTY,
    SRC_KMAC_FIFO_EMPTY,
    SRC_MAILBOX,
    SRC_SPI,
    SRC_TIED,
    VEC_GRADED,
    assigned_masked,
    boundary_pending,
    idle_unstated_line,
    meip_idle_mask_words,
    meip_masked,
    meip_words,
    vec_bit,
    vec_mask,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AES, CSRNG, HMAC, KMAC, sym

_TEST = "sep_pic_pending_map_walk_rand_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "pic_pending_map_walk_rand_test")
_ITCM_HEX = os.path.join(_FW_DIR, "pic_pending_map_walk_rand_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "pic_pending_map_walk_rand_test.dtcm.hex")
_BANNER = "SEP PIC pending map walk test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 12_000_000
_NO_BOOT_CYCLES = 80_000
# The one CSRNG INTR_ENABLE bit the quiet window keeps set (generated field mask).
_CSRNG_EN_CTRL = CSRNG.fields("INTR_ENABLE")["CS_CMD_REQ_DONE"]["bm"]

# ---- Source model (hw/sys/sep/doc/interrupts.adoc via env/sep_pic_map) ----
SRC_CTRL = 24
MAP = (*SRC_MAILBOX, SRC_DMA_ALERT, SRC_SPI, 18, SRC_HMAC_FIFO_EMPTY, 20, 21, SRC_KMAC_FIFO_EMPTY,
       23, 24, 25, 26, 27, 28, 29, 30, SRC_CRYPTO_ALERT)  # fmt: skip
# Sources whose IP INTR_ENABLE bit the pass 1 mask draws, by IP.
MASK_IPS = {
    "hmac": (18, 20),
    "kmac": (21, 23),
    "csrng": (24, 25, 26, 27),
    "edn": (28, 29),
    "otbn": (30,),
    "spi": (SRC_SPI,),
}
DRAWN = tuple(s for v in MASK_IPS.values() for s in v)
PULSE = (SRC_DMA_ALERT, SRC_CRYPTO_ALERT)
ALWAYS = (*SRC_MAILBOX, *PULSE)
# Alert kinds: (block, kind, receiver index range) (crypto.adoc alert table).
ALERTS = (
    ("hmac", "fatal_fault", (0, 0)),
    ("otbn", "fatal", (1, 2)),
    ("otbn", "recov", (1, 2)),
    ("aes", "recov_ctrl_update_err", (3, 4)),
    ("aes", "fatal_fault", (3, 4)),
    ("kmac", "fatal_fault_err", (5, 6)),
    ("kmac", "recov_operation_err", (5, 6)),
    ("csrng", "fatal", (7, 8)),
    ("csrng", "recov", (7, 8)),
    ("edn", "fatal", (9, 10)),
    ("edn", "recov", (9, 10)),
)
N_ALERT_IDX = 11
# Native error sources and the OTBN done interrupt (firmware k_native_map order).
NATIVE = ((20, "hmac", "native"), (23, "kmac", "native"), (27, "csrng", "native"),
          (29, "edn", "native"), (30, "otbn", "non_alert"))  # fmt: skip
# Gateway sources (firmware k_gw_map order) and cells (meigwctrl: type bit 1, polarity bit 0).
GW_SRCS = (*SRC_MAILBOX, 18, 21, 24, 28)
GW_EVENT = (18, 21, 24, 28)
CELLS = ("LH", "LL", "EH", "EL")
# Level cells: (idle, asserted, deasserted); EH adds 0 after meigwclr (el2_pic.adoc).
CELL_MODEL = {"LH": (0, 1, 0), "LL": (1, 0, 1), "EH": (0, 1, 1)}
CLR_DIRECTED = (0x0, 0x1, 0x8000_0000, 0xFFFF_FFFF)
FIRST_BAND = 44
# Test parameters (clocks; FIFO writes).
HOLD_CLK = 2000
SETTLE_CLK = 64
FILL_MAX = 64
GAP_MAX = 64

P_MAGIC_WORD = 0x3A1C9E21

# Status fields of the idle window and the KMAC fifo_empty state (register export).
HMAC_IDLE = HMAC.field_mask("STATUS", "hmac_idle")
KMAC_IDLE = KMAC.field_mask("STATUS", "sha3_idle")
AES_IDLE = AES.field_mask("STATUS", "idle")
# AES STATUS after one automatic-mode block whose output is read and whose unit
# is idle (AES register description, STATUS): idle 1, input_ready 1, stall 0,
# output_valid 0, both alert bits 0. output_lost has no meaning in automatic
# mode and stays outside the mask.
AES_DONE_MASK = (
    AES_IDLE
    | AES.field_mask("STATUS", "input_ready")
    | AES.field_mask("STATUS", "stall")
    | AES.field_mask("STATUS", "output_valid")
    | AES.field_mask("STATUS", "alert_recov_ctrl_update_err")
    | AES.field_mask("STATUS", "alert_fatal_fault")
)
AES_DONE_WANT = AES_IDLE | AES.field_mask("STATUS", "input_ready")
KMAC_FE_STATE = KMAC.field_mask("INTR_STATE", "fifo_empty")
# meip word 0 offset in the PIC and the meip word stride (register export).
MEIP0_OFF = sym("PIC_MEIP_0__REG_OFFSET")
MEIP_STRIDE = sym("PIC_MEIP_1__REG_OFFSET") - MEIP0_OFF


def _pack(vals, bits: int, words: int) -> list[int]:
    per = 32 // bits
    out = [0] * words
    for i, v in enumerate(vals):
        assert 0 <= v < (1 << bits)
        out[i // per] |= v << (bits * (i % per))
    return out


def _shuffled(rng: SepSeededRng, seq) -> list:
    out = list(seq)
    rng.shuffle(out)
    return out


@dataclass(frozen=True)
class WalkCfg:
    """The seeded stimulus. A pure function of the run seed and the port width."""

    seed: int
    ord1: tuple[int, ...]
    ord2: tuple[int, ...]
    gap1: tuple[int, ...]
    gap2: tuple[int, ...]
    alert_order: tuple[int, ...]
    pair: tuple[int, int]
    pair_gap: int
    akind: tuple[int, int, int, int]  # pass 1, pass 2, single, masked
    native_order: tuple[int, ...]
    mask1: int
    gw_cell: tuple[int, ...]
    gw_order: tuple[int, ...]
    clr_x: int
    ext: tuple[int, int, int]
    ext_width: int

    @classmethod
    def from_seed(cls, seed: int, ext_width: int) -> "WalkCfg":
        rng = SepSeededRng(seed)
        ord1 = tuple(_shuffled(rng, range(len(MAP))))
        ord2 = tuple(_shuffled(rng, range(len(MAP))))
        gap1 = tuple(rng.randrange(0, GAP_MAX + 1) for _ in MAP)
        gap2 = tuple(rng.randrange(0, GAP_MAX + 1) for _ in MAP)
        alert_order = tuple(_shuffled(rng, range(len(ALERTS))))
        k1 = rng.randrange(len(ALERTS))
        k2 = rng.choice([k for k in range(len(ALERTS)) if ALERTS[k][0] != ALERTS[k1][0]])
        pair_gap = rng.randrange(0, GAP_MAX + 1)
        akind = tuple(rng.randrange(len(ALERTS)) for _ in range(4))
        native_order = tuple(_shuffled(rng, range(len(NATIVE))))
        mask1 = 0
        for srcs in MASK_IPS.values():
            bits = 0
            while bits == 0:
                bits = rng.getrandbits(len(srcs))
            for i, s in enumerate(srcs):
                if (bits >> i) & 1:
                    mask1 |= 1 << s
        ev = _shuffled(rng, range(4))
        mb = _shuffled(rng, [0, 1, 2, 3] + [rng.randrange(4) for _ in range(4)])
        gw_cell = tuple(mb + ev)
        gw_order = tuple(_shuffled(rng, range(len(GW_SRCS))))
        clr_x = rng.getrandbits(32)
        assert ext_width >= 2, f"sep_ext_interrupts_i is {ext_width} bits wide"
        b1 = rng.randrange(ext_width)
        b2, b3 = rng.sample(range(ext_width), 2)
        return cls(seed, ord1, ord2, gap1, gap2, alert_order, (k1, k2), pair_gap, akind,
                   native_order, mask1, gw_cell, gw_order, clr_x, (b1, b2, b3), ext_width)  # fmt: skip

    def enabled(self, src: int, pas: int) -> bool:
        on = bool((self.mask1 >> src) & 1)
        return on if pas == 1 else not on

    def words(self) -> list[int]:
        return [
            P_MAGIC_WORD,
            self.seed & 0xFFFF_FFFF,
            *_pack(self.ord1, 5, 4),
            *_pack(self.ord2, 5, 4),
            *_pack(self.gap1, 8, 6),
            *_pack(self.gap2, 8, 6),
            *_pack(self.alert_order, 4, 2),
            self.pair[0] | (self.pair[1] << 4) | (self.pair_gap << 8),
            self.akind[0] | (self.akind[1] << 4) | (self.akind[2] << 8) | (self.akind[3] << 12),
            sum(v << (3 * i) for i, v in enumerate(self.native_order)),
            self.mask1,
            sum(v << (2 * i) for i, v in enumerate(self.gw_cell)),
            *_pack(self.gw_order, 4, 2),
            self.clr_x,
            self.ext[0] | (self.ext[1] << 8) | (self.ext[2] << 16),
            meip_idle_mask_words()[0],
            meip_idle_mask_words()[1],
            HOLD_CLK,
            SETTLE_CLK,
            FILL_MAX,
        ]

    def cell(self, src: int) -> str:
        return CELLS[self.gw_cell[GW_SRCS.index(src)]]


def _value_bits(sig) -> tuple[int, int]:
    """(value with X/Z read as 0, mask of the X/Z bits) of a vector signal."""
    v = sig.value
    if v.is_resolvable:
        return int(v), 0
    s = getattr(v, "binstr", None)
    s = (s if s is not None else str(v)).strip()
    val = xm = 0
    for c in s:
        val = (val << 1) | (c == "1")
        xm = (xm << 1) | (c not in "01")
    return val, xm


def _hexw(words) -> str:
    return ",".join(f"0x{w:08x}" for w in words)


@pyuvm.test()
class sep_pic_pending_map_walk_rand_test(sep_base_test):
    """meip pending map, FIFO-empty, alert, gateway and boundary-input contracts of the SEP PIC."""

    required_evidence = (
        "CHK-BASE",
        "CHK-VECTOR",
        "CHK-FIFO-EMPTY",
        "CHK-SPI",
        "CHK-ALERT12",
        "CHK-ALERT-AGG",
        "CHK-ALERT-IDX",
        "CHK-ALERT-IDLE",
        "CHK-ALERT-NONE",
        "CHK-ALERT-NATIVE",
        "CHK-SRC17",
        "CHK-IDLE-BAND",
        "CHK-SLOTLESS",
        "CHK-GW-CELL",
        "CHK-EDGE-HOLD",
        "CHK-HOLD",
        "CHK-CLR-IDLE",
        "CHK-GWCLR-VALUE",
        "CHK-GW-NONVAC",
        "CHK-EXT-IN",
        "CHK-FW-IDENTITY",
        "CHK-FW-CONSOLE",
    )

    # The CPU owns the CPU-LSU port; the leaf drives no bus master.
    build_env = False

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    # ---- logging ----
    def _pass(self, name: str, text: str) -> None:
        self.logger.info("%s PASS seed=%d %s", name, self.wc.seed, text)
        self.n_pass[name] += 1

    def _check(self, ok: bool, name: str, text: str) -> None:
        assert ok, f"{name} FAIL seed={self.wc.seed} {text}"
        self._pass(name, text)

    # ---- host requests ----
    def _on_mark(self, kv: dict) -> None:
        tag = kv["t"]
        self.marks[tag] = (self.w.mark(), self.wa.mark(), self.w.level("b11"), self.w.level("b32"))

    async def _req_mark(self, kv: dict) -> None:
        self._on_mark(kv)

    async def _req_vec(self, kv: dict) -> None:
        vec, xm = _value_bits(self.dut.sep_internal_interrupts_probe_o)
        spi, sxm = _value_bits(self.dut.sep_io_spi_irq_w)
        tag = kv["t"]
        self.vecs[tag] = (vec, xm, spi, sxm)
        self.vec_marks[tag] = self.w.mark()
        if tag not in self.marks:
            self._on_mark(kv)

    async def _drive_stall(self, ip: str, kv: dict) -> None:
        self.logger.info("STALL-DRIVE LOG ip=%s on=%d", ip, int(kv["on"]))
        await RisingEdge(self.dut.clk_i)
        getattr(self.dut, f"{ip}_fifo_drain_stall_i").value = 1 if kv["on"] else 0

    async def _req_stall(self, kv: dict) -> None:
        await self._drive_stall("hmac", kv)

    async def _req_kstall(self, kv: dict) -> None:
        await self._drive_stall("kmac", kv)

    async def _req_ext(self, kv: dict) -> None:
        step = int(kv["step"])
        b1, b2, b3 = self.wc.ext
        mask = {0: 1 << b1, 2: (1 << b2) | (1 << b3)}.get(step, 0)
        await RisingEdge(self.dut.clk_i)
        self.dut.sep_ext_interrupts_i.value = mask
        self.logger.info("EXT-DRIVE LOG step=%d mask=0x%x", step, mask)

    async def _req_win(self, kv: dict) -> None:
        op = next(k for k in kv if k in ("aes", "otp", "lcc"))
        if kv[op]:
            bits = {f"v{i}": i for i in range(NUM_VEC)}
            self.slot_watch[op] = SepBitWatch(
                self.dut.sep_internal_interrupts_probe_o, bits, name=f"vec_{op}"
            ).start()
            return
        w = self.slot_watch[op]
        await w.stop()
        self.slot_rec[op] = (
            w.clk,
            {i: len(w.bits[f"v{i}"].rises) + len(w.bits[f"v{i}"].falls) for i in range(NUM_VEC)},
            w.bits[f"v{vec_bit(SRC_CTRL)}"].high_clocks,
        )

    async def _rd_tap(self) -> None:
        """Copies of the PIC read data at every PIC read (pic_rd_data_probe_o)."""
        sig = self.dut.pic_rd_data_probe_o
        while True:
            await RisingEdge(self.dut.clk_i)
            await ReadOnly()
            v = sig.value
            if v.is_resolvable:
                iv = int(v)
                if (iv >> 47) & 1:
                    self.rd_caps.append(
                        (len(self.con.lines), (iv >> 32) & 0x7FFF, iv & 0xFFFF_FFFF, 0)
                    )
                continue
            val, xm = _value_bits(sig)
            if (val >> 47) & 1 and not (xm >> 47) & 1:
                self.rd_caps.append(
                    (len(self.con.lines), (val >> 32) & 0x7FFF, val & 0xFFFF_FFFF, xm & 0xFFFF_FFFF)
                )

    # ---- record helpers ----
    def _lines(self, prefix: str) -> list[tuple[int, dict]]:
        out = []
        for i, (_c, t) in enumerate(self.con.lines):
            if t.startswith(prefix + " ") or t == prefix:
                out.append((i, parse_kv(t[len(prefix) :])))
        return out

    def _meip(self, tag: str) -> tuple[int, list[int]]:
        hits = [(i, kv) for i, kv in self._lines("MEIP") if kv.get("t") == tag]
        assert len(hits) == 1, f"expected one 'MEIP t={tag}' line, got {len(hits)}"
        i, kv = hits[0]
        return i, [kv[f"w{k}"] for k in range(MEIP_WORDS)]

    def _taps(self, line_idx: int) -> dict[int, tuple[int, int]]:
        """The last PIC read-data copy per meip word before console line ``line_idx``."""
        out: dict[int, tuple[int, int]] = {}
        for li, addr, data, xm in self.rd_caps:
            if li == line_idx and MEIP0_OFF <= addr < MEIP0_OFF + MEIP_STRIDE * MEIP_WORDS:
                out[(addr - MEIP0_OFF) // MEIP_STRIDE] = (data, xm)
        return out

    def _mark(self, tag: str):
        assert tag in self.marks, f"no host mark '{tag}' (firmware REQ missing)"
        return self.marks[tag]

    def _high(self, t0: str, t1: str, bit: str, watch: int = 0) -> int:
        m0, m1 = self._mark(t0)[watch], self._mark(t1)[watch]
        return m1.high[bit] - m0.high[bit]

    def _vec(self, tag: str) -> tuple[int, int, int, int]:
        assert tag in self.vecs, f"no vector sample '{tag}' (firmware REQ missing)"
        return self.vecs[tag]

    @staticmethod
    def _four_state() -> bool:
        return "vcs" in str(getattr(cocotb, "SIM_NAME", "") or "").lower()

    def _vec_bit_x(self, tag: str, b: int) -> tuple[int, bool, str]:
        """(bit b of vector sample ``tag``, X-free on that bit, log text).

        On a 4-state simulator an X or Z on the bit is not X-free, so a check that
        expects 0 cannot pass on an X read as 0. A 2-state simulator logs ``na``.
        """
        v, xm, _, _ = self._vec(tag)
        bit, xb = (v >> b) & 1, (xm >> b) & 1
        if not self._four_state():
            return bit, True, "na"
        return bit, xb == 0, str(xb)

    # ---- checks ----
    def _exp_srcs(self, pas: int) -> set[int]:
        srcs = set(ALWAYS) | {s for s in DRAWN if self.wc.enabled(s, pas)}
        if pas == 1:
            srcs |= {SRC_HMAC_FIFO_EMPTY, SRC_KMAC_FIFO_EMPTY}
        return srcs

    def _chk_vector(self) -> None:
        for pas in (1, 2):
            tag = f"p{pas}"
            _, got = self._meip(tag)
            srcs = self._exp_srcs(pas)
            exp = meip_words(srcs)
            gm, em = meip_masked(got), meip_masked(exp)
            h11 = self._high_between(tag, "b11")
            h32 = self._high_between(tag, "b32")
            self.logger.info(idle_unstated_line(words=got))
            self._check(
                gm == em and h11 > 0 and h32 > 0,
                "CHK-VECTOR",
                f"cell=pass{pas} drawn={','.join(str(s) for s in sorted(srcs))} meip0=0x{got[0]:08x} "
                f"meip1=0x{got[1]:08x} exp0=0x{exp[0]:08x} exp1=0x{exp[1]:08x} "
                f"meip2_7={_hexw(got[2:])} src12_high_clk={h11} src33_high_clk={h32}",
            )
            # Control: the vector equals the expected vector for the level sources.
            vec, xm, _, _ = self._vec(tag)
            lvl_mask = VEC_GRADED & ~vec_mask(PULSE)
            exp_vec = vec_mask(srcs - set(PULSE)) & lvl_mask
            self.logger.info(
                "CTL-VECTOR LOG pass=%d probe_equal=%d vec=0x%011x exp=0x%011x mask=0x%011x xz=0x%x",
                pas,
                int((vec & lvl_mask) == exp_vec),
                vec,
                exp_vec,
                lvl_mask,
                xm,
            )
        # Single-source reads.
        for src, word in ((SRC_CTRL, 0), (SRC_CRYPTO_ALERT, 1)):
            hits = [kv for _, kv in self._lines("SINGLE") if int(kv["src"]) == src]
            assert len(hits) == 1, f"expected one SINGLE src={src} line"
            got = hits[0][f"meip{word}"]
            exp = meip_words([src])[word]
            gm = got & ~meip_idle_mask_words()[word] & 0xFFFF_FFFF
            self._check(
                gm == exp,
                "CHK-VECTOR",
                f"cell=single src={src} meip{word}=0x{got:08x} exp{word}=0x{exp:08x} "
                f"rsvd_idle=0x{got & meip_idle_mask_words()[word]:08x}",
            )

    def _high_between(self, tag: str, bit: str) -> int:
        """High clocks of ``bit`` from the mark ``tag`` to the vector sample of the same tag."""
        m0 = self._mark(tag)[0]
        assert tag in self.vec_marks, f"no vector sample '{tag}' (firmware REQ missing)"
        m1 = self.vec_marks[tag]
        return m1.high[bit] - m0.high[bit]

    def _chk_base(self) -> None:
        four_state = self._four_state()
        # Control of the meip X part: the tap equals the firmware word at the map-pass reads.
        ctrl_reads = ctrl_match = ctrl_nonzero = 0
        for tag in ("p1", "p2"):
            li, words = self._meip(tag)
            taps = self._taps(li)
            for w in range(MEIP_WORDS):
                ctrl_reads += 1
                if w in taps and taps[w][1] == 0 and taps[w][0] == words[w]:
                    ctrl_match += 1
                    ctrl_nonzero += int(words[w] != 0)
        li0, base = self._meip("reset")
        base_m = meip_masked(base)
        for when, tag in (("reset", "reset"), ("map_release", "r1"), ("map_release", "r2"),
                          ("final", "final")):  # fmt: skip
            li, words = self._meip(tag)
            vec, xm, _, _ = self._vec(tag)
            band = boundary_pending(words)
            wm = meip_masked(words)
            self.logger.info(idle_unstated_line(vec=vec))
            self.logger.info(idle_unstated_line(words=words))
            ok = (vec & VEC_GRADED) == 0 and not band and all(w == 0 for w in wm) and wm == base_m
            text = (
                f"when={when} tag={tag} vec_masked=0x{vec & VEC_GRADED:011x} band_zero={int(not band)} "
                f"meip={_hexw(words)} meip_masked_equal_baseline={int(wm == base_m)} "
                f"vec_x_free={int(xm == 0) if four_state else 'na'}"
            )
            if four_state:
                ok = ok and xm == 0
            if when == "reset":
                taps = self._taps(li0)
                x_seen = sum(1 for d, x in taps.values() if x)
                text += (
                    f" meip_reads={len(taps)} x_seen={x_seen if four_state else 'na'} "
                    f"ctrl_reads={ctrl_reads} ctrl_match={ctrl_match} ctrl_nonzero={ctrl_nonzero}"
                )
                ok = (
                    ok and len(taps) == MEIP_WORDS and ctrl_match == ctrl_reads and ctrl_nonzero > 0
                )
                if four_state:
                    ok = ok and x_seen == 0
            self._check(ok, "CHK-BASE", text)

    def _chk_fifo_empty(self) -> None:
        fills = {kv["ip"]: kv for _, kv in self._lines("FILL")}
        fes = {kv["ip"]: kv for _, kv in self._lines("FE")}
        for ip, src in (("hmac", SRC_HMAC_FIFO_EMPTY), ("kmac", SRC_KMAC_FIFO_EMPTY)):
            f, fe = fills[ip], fes[ip]
            b = vec_bit(src)
            v0, x0_ok, x0_txt = self._vec_bit_x(f"fe{ip[0]}0", b)
            v1, x1_ok, x1_txt = self._vec_bit_x(f"fe{ip[0]}1", b)
            text = (
                f"ip={ip} src={src} exp_before=1 meip_before={fe['meip_before']} vec_before={v0} "
                f"exp_after=0 meip_after={fe['meip_after']} vec_after={v1} fill_writes={f['writes']} "
                f"fifo_full={f['full']} fifo_empty={f['empty']} "
                f"vec_before_x={x0_txt} vec_after_x={x1_txt}"
            )
            ok = (
                int(f["full"]) == 1
                and int(f["empty"]) == 1
                and int(fe["meip_before"]) == 1
                and v0 == 1
                and int(fe["meip_after"]) == 0
                and v1 == 0
                and x0_ok
                and x1_ok
            )
            if ip == "kmac":
                ok = ok and bool(f["intr_state"] & KMAC_FE_STATE)
                text += f" intr_state=0x{f['intr_state']:08x}"
            self._check(ok, "CHK-FIFO-EMPTY", text)

    def _chk_spi(self) -> None:
        b = vec_bit(SRC_SPI)
        _, _, i1, ix1 = self._vec("spi1")
        _, _, i0, ix0 = self._vec("spi0")
        b1, x1_ok, x1_txt = self._vec_bit_x("spi1", b)
        b0, x0_ok, x0_txt = self._vec_bit_x("spi0", b)
        self._check(
            b1 == 1 and i1 == 1 and b0 == 0 and i0 == 0 and not (ix1 or ix0) and x1_ok and x0_ok,
            "CHK-SPI",
            f"cause=error bit13={b1} port_irq={i1} after_w1c_bit13={b0} after_w1c_port_irq={i0} "
            f"bit13_x={x1_txt} after_w1c_bit13_x={x0_txt}",
        )

    def _alert_idx(self, t0: str, t1: str) -> set[int]:
        m0, m1 = self._mark(t0)[1], self._mark(t1)[1]
        return {
            i
            for i in range(N_ALERT_IDX)
            if m1.high[f"a{i}"] - m0.high[f"a{i}"] > 0 or m1.rises[f"a{i}"] - m0.rises[f"a{i}"] > 0
        }

    def _chk_alerts(self) -> int:
        ctrl = 0
        for k in self.wc.alert_order:
            blk, kind, (lo, hi) = ALERTS[k]
            q, w, e = f"aq{k}", f"aw{k}", f"ae{k}"
            pre = self._high(q, w, "b32")
            pre_lvl = self._mark(w)[3]
            hc = self._high(w, e, "b32")
            back = self._mark(e)[3]
            ctrl += hc
            self._check(
                pre == 0 and pre_lvl == 0 and hc > 0 and back == 0,
                "CHK-ALERT-AGG",
                f"block={blk} kind={kind} pic33_high_cycles={hc} pre_window_high={pre} back={back}",
            )
            idx = self._alert_idx(w, e)
            pv = sum(1 << i for i in idx)
            self._check(
                len(idx) == 1 and lo <= min(idx) <= hi,
                "CHK-ALERT-IDX",
                f"block={blk} kind={kind} idx={','.join(map(str, sorted(idx))) or 'none'} "
                f"range={lo}-{hi} pulse_vector=0x{pv:03x}",
            )
        alerts = [kv for _, kv in self._lines("ALERT")]
        self.logger.info(
            "ALERT-MEIP LOG meip1_bit1=%s",
            ",".join(str((kv["meip1"] >> 1) & 1) for kv in alerts),
        )
        # Pair trial.
        k1, k2 = self.wc.pair
        hc = self._high("pr0", "pr1", "b32")
        idx = self._alert_idx("pr0", "pr1")
        r1, r2 = ALERTS[k1][2], ALERTS[k2][2]
        in1 = [i for i in idx if r1[0] <= i <= r1[1]]
        in2 = [i for i in idx if r2[0] <= i <= r2[1]]
        self._check(
            hc > 0 and len(idx) == 2 and len(in1) == 1 and len(in2) == 1,
            "CHK-ALERT-IDX",
            f"pair={ALERTS[k1][0]}.{ALERTS[k1][1]}+{ALERTS[k2][0]}.{ALERTS[k2][1]} "
            f"gap={self.wc.pair_gap} idx={','.join(map(str, sorted(idx)))} "
            f"ranges={r1[0]}-{r1[1]},{r2[0]}-{r2[1]} pic33_high_cycles={hc}",
        )
        # No-write window.
        nw = self._high("nw0", "nw1", "b32")
        self._check(
            nw == 0 and ctrl > 0,
            "CHK-ALERT-NONE",
            f"pic33_high_cycles={nw} ctrl_high_cycles={ctrl}",
        )
        # Native errors.
        for n in self.wc.native_order:
            src, blk, kind = NATIVE[n]
            own = (self._vec(f"nb{src}")[0] >> vec_bit(src)) & 1
            p33 = self._high(f"na{src}", f"nb{src}", "b32")
            c33 = self._high(f"nb{src}", f"nc{src}", "b32")
            key = "native_src" if kind == "native" else "src"
            self._check(
                own == 1 and p33 == 0 and c33 > 0,
                "CHK-ALERT-NATIVE",
                f"block={blk} kind={kind} {key}={src} native_bit={own} pic33_high_cycles={p33} "
                f"ctrl_alert_cycles={c33}",
            )
        # DMA alert on source 12.
        pre = self._high("d0", "d1", "b11")
        pre_lvl = self._mark("d1")[2]
        hc = self._high("d1", "d2", "b11")
        rises = self.w.rise_clks_since(self._mark("d1")[0], "b11")
        lat = (rises[0] - self._mark("d1")[0].clk) if rises else -1
        shape = "pulse" if self._mark("d2")[2] == 0 else "level"
        self._check(
            pre == 0 and pre_lvl == 0 and hc > 0,
            "CHK-ALERT12",
            f"pre_window_src12={pre} src12_high_cycles={hc} shape={shape} latency_clk={lat}",
        )
        return ctrl

    def _chk_idle(self, ctrl: int) -> None:
        st = {kv["when"]: kv for _, kv in self._lines("IDLE-STATUS")}
        busy = {}
        for when in ("before", "after"):
            s = st[when]
            busy[when] = (
                int(not (s["hmac"] & HMAC_IDLE))
                + int(not (s["kmac"] & KMAC_IDLE))
                + int(s["otbn"] != 0)
            )
        hc = self._high("ia", "i1", "b32")
        aes_busy = int(not (st["before"]["aes"] & AES_IDLE))
        self._check(
            hc == 0 and busy["before"] == 3 and busy["after"] == 3,
            "CHK-ALERT-IDLE",
            f"pic33_high_cycles={hc} engines_busy={busy['before']} engines_busy_after={busy['after']} "
            f"aes_busy={aes_busy} ctrl_high_cycles={ctrl} hold_clk={HOLD_CLK} "
            f"status_before=hmac:0x{st['before']['hmac']:x},kmac:0x{st['before']['kmac']:x},"
            f"otbn:0x{st['before']['otbn']:x}",
        )

    def _chk_ctrl_window(self) -> None:
        _, words = self._meip("ctrl")
        live = (words[0] >> SRC_CTRL) & 1
        b17v, b17x_ok, b17x_txt = self._vec_bit_x("ctrl", vec_bit(SRC_TIED))
        b17m = (words[0] >> SRC_TIED) & 1
        self.logger.info(idle_unstated_line(words=words))
        self._check(
            live == 1 and b17v == 0 and b17m == 0 and b17x_ok,
            "CHK-SRC17",
            f"live_src={SRC_CTRL} live_bit={live} bit17={b17m} vec_bit16={b17v} vec_bit16_x={b17x_txt}",
        )
        band = boundary_pending(words)
        hi1 = words[1] >> (FIRST_BAND - 32)
        self._check(
            live == 1 and not band,
            "CHK-IDLE-BAND",
            f"live_src={SRC_CTRL} live_bit={live} meip1_hi=0x{hi1:x} meip2_7={_hexw(words[2:])}",
        )

    def _chk_slotless(self) -> None:
        q = [kv for _, kv in self._lines("CTL-QUIET")]
        assert q, "no CTL-QUIET record"
        en = q[0]
        cleared = int(
            all(en[f"en_{ip}"] == 0 for ip in ("hmac", "kmac", "edn", "otbn", "spi"))
            and en["en_csrng"] == _CSRNG_EN_CTRL
        )
        idle_bits = {vec_bit(s) for s in EXCLUDED_IDLE_SOURCES}
        src34 = vec_bit(34)
        ctrl_bit = vec_bit(SRC_CTRL)
        for op in ("aes", "otp", "lcc"):
            assert op in self.slot_rec, f"no slotless window for {op}"
            clks, changes, ctrl_high = self.slot_rec[op]
            masked = set(idle_bits)
            if op == "otp":
                masked.add(src34)
                self.logger.info("OBS-SRC34 LOG op=otp bit33_changed_clk=%d", changes[src34])
            other = sum(n for i, n in changes.items() if i not in masked)
            text = (
                f"op={op} ctrl_src24_high_clk={ctrl_high} window_clk={clks} "
                f"other_bits_changed_clk={other} ip_enables_cleared={cleared}"
            )
            if op == "aes":
                st = [kv for _, kv in self._lines("CTL-AES-STATUS")]
                assert len(st) == 1, f"expected one CTL-AES-STATUS record, got {len(st)}"
                status, cfg_ok = st[0]["status"], int(st[0]["cfg_ok"])
                self.logger.info("CTL-SLOTLESS LOG %s aes_status=0x%08x", text, status)
                self._check(
                    cfg_ok == 1 and status & AES_DONE_MASK == AES_DONE_WANT,
                    "CHK-SLOTLESS",
                    f"op=aes aes_status=0x{status:08x} field_mask=0x{AES_DONE_MASK:02x} "
                    f"want=0x{AES_DONE_WANT:02x} cfg_ok={cfg_ok}",
                )
                continue
            self._check(
                other == 0 and ctrl_high == clks and clks > 0 and cleared == 1
                and changes[ctrl_bit] == 0,
                "CHK-SLOTLESS",
                text,
            )  # fmt: skip

    def _chk_gateway(self) -> None:
        gws = {int(kv["src"]): kv for _, kv in self._lines("GW")}
        assert sorted(gws) == sorted(GW_SRCS), f"gateway cells ran for {sorted(gws)}"
        lh_asserted = []
        twin: dict[str, int] = {}
        for src in GW_SRCS:
            kv = gws[src]
            cell = self.wc.cell(src)
            cls = "event" if src in GW_EVENT else "mailbox"
            vals = (int(kv["idle"]), int(kv["asserted"]), int(kv["deasserted"]))
            if cell == "EL":
                self.logger.info(
                    "OBS-GW-EL LOG src=%d cfg=0x%x idle=%d asserted=%d deasserted=%d reasserted=%d "
                    "after_clr=%d clr_val=0x%08x",
                    src, kv["cfg"], *vals, int(kv["reasserted"]), int(kv["after_clr2"]), kv["clr_val"],
                )  # fmt: skip
                continue
            exp = CELL_MODEL[cell]
            ok = vals == exp
            text = (
                f"src={src} class={cls} type={'edge' if cell[0] == 'E' else 'level'} "
                f"pol={'high' if cell[1] == 'H' else 'low'} cfg=0x{kv['cfg']:x} start={vals[0]} "
                f"asserted={vals[1]} after_deassert={vals[2]}"
            )
            if cell == "EH":
                ok = ok and int(kv["after_clr"]) == 0 and kv["clr_val"] == self.wc.clr_x
                text += f" after_clr={int(kv['after_clr'])} clr_val=0x{kv['clr_val']:08x}"
            if cell == "LH":
                lh_asserted.append(vals[1])
                twin.setdefault(cls, vals[2])
            self._check(ok, "CHK-GW-CELL", text)
        for src in GW_SRCS:
            if self.wc.cell(src) != "EH":
                continue
            cls = "event" if src in GW_EVENT else "mailbox"
            held = int(gws[src]["deasserted"])
            self._check(
                held == 1 and twin.get(cls) == 0,
                "CHK-EDGE-HOLD",
                f"src={src} type=edge held={held} level_twin_dropped={int(twin.get(cls) == 0)} "
                f"twin_class={cls}",
            )
        self._check(
            len(lh_asserted) > 0 and any(a == 1 for a in lh_asserted),
            "CHK-GW-NONVAC",
            f"lh_cells={len(lh_asserted)} asserted_bit={int(any(a == 1 for a in lh_asserted))}",
        )
        # Clear-value corner on the event EH source.
        eh = next(s for s in GW_EVENT if self.wc.cell(s) == "EH")
        clr = [kv for _, kv in self._lines("GWCLR")]
        want = [*CLR_DIRECTED, self.wc.clr_x]
        clr_vals = [kv["v"] for kv in clr]
        clr_held = [int(kv["held"]) for kv in clr]
        clr_after = [int(kv["after"]) for kv in clr]
        self._check(
            clr_vals == want and all(h == 1 for h in clr_held) and all(a == 0 for a in clr_after)
            and all(int(kv["src"]) == eh for kv in clr),
            "CHK-GWCLR-VALUE",
            f"src={eh} values={','.join(f'0x{v:X}' for v in clr_vals)} "
            f"held_before={','.join(map(str, clr_held))} after_clr={','.join(map(str, clr_after))}",
        )  # fmt: skip
        ci = [kv for _, kv in self._lines("CLRIDLE")]
        assert len(ci) == 1, "expected one CLRIDLE line"
        c = ci[0]
        dropped = int(int(gws[eh]["after_clr"]) == 0 and clr_after[-1] == 0)
        self._check(
            int(c["meip_before"]) == 0 and int(c["meip_after"]) == 0 and c["clr_val"] == self.wc.clr_x
            and dropped == 1,
            "CHK-CLR-IDLE",
            f"src={eh} type=edge meip_before={int(c['meip_before'])} clr_val=0x{c['clr_val']:08x} "
            f"meip_after={int(c['meip_after'])} ctrl_held_dropped={dropped}",
        )  # fmt: skip
        hd = [kv for _, kv in self._lines("HOLD")]
        assert len(hd) == 1, "expected one HOLD line"
        h = hd[0]
        lh = next(s for s in GW_EVENT if self.wc.cell(s) == "LH")
        self._check(
            int(h["src"]) == lh and int(h["meip"]) == 1 and int(h["after_ip_clear"]) == 0,
            "CHK-HOLD",
            f"src={lh} meip={int(h['meip'])} after_ip_clear={int(h['after_ip_clear'])} hold_clk={HOLD_CLK}",
        )

    def _chk_ext(self) -> None:
        _, base = self._meip("ext_base")
        base_a = assigned_masked(base)
        ok0 = (base[0] >> SRC_CTRL) & 1 == 1 and not boundary_pending(base)
        for n, ton, toff in ((1, "ext1", "ext1r"), (2, "ext2", "ext2r")):
            _, on = self._meip(ton)
            _, off = self._meip(toff)
            pend = boundary_pending(on)
            rel = boundary_pending(off)
            same = assigned_masked(on) == base_a and assigned_masked(off) == base_a
            live = all((w[0] >> SRC_CTRL) & 1 for w in (base, on, off))
            self.logger.info("OBS-EXT-INDEX LOG bits_asserted=%d pending_sources=%s", n, pend)
            self._check(
                ok0 and len(pend) == n and same and not rel and live,
                "CHK-EXT-IN",
                f"bits_asserted={n} above43_pending={len(pend)} assigned_same={int(same)} "
                f"after_release={len(rel)} ctrl_src24={int(live)} width={self.wc.ext_width}",
            )

    def _check_params(self) -> None:
        p = dict(self._lines("PARAMS")[0][1])
        p2 = dict(self._lines("PARAMS2")[0][1])
        w = self.wc.words()
        got = (
            p["mask1"],
            p["gwcell"],
            p["clrx"],
            p["ext"],
            p2["o1a"],
            p2["o2a"],
            p2["idle0"],
            p2["idle1"],
        )
        exp = (w[27], w[28], w[31], w[32], w[2], w[6], w[33], w[34])
        assert got == exp, f"firmware ran params {got}, patched {exp}"

    # ---- scenario ----
    async def run_scenario(self) -> None:
        self.dut = cocotb.top
        width = len(self.dut.sep_ext_interrupts_i)
        self.wc = WalkCfg.from_seed(self.random_seed(), width)
        c = self.wc
        self.logger.info("SEED seed=%d", c.seed)
        self.logger.info("DRAW order_pass1=%s", ",".join(str(MAP[i]) for i in c.ord1))
        self.logger.info("DRAW order_pass2=%s", ",".join(str(MAP[i]) for i in c.ord2))
        self.logger.info("DRAW gaps_pass1=%s", ",".join(map(str, c.gap1)))
        self.logger.info("DRAW gaps_pass2=%s", ",".join(map(str, c.gap2)))
        self.logger.info(
            "DRAW alert_order=%s", ",".join(f"{ALERTS[k][0]}.{ALERTS[k][1]}" for k in c.alert_order)
        )
        self.logger.info("DRAW alert_pair=%d,%d alert_gap=%d", c.pair[0], c.pair[1], c.pair_gap)
        self.logger.info("DRAW alert_kind_pass1=%d pass2=%d single=%d masked=%d", *c.akind)
        self.logger.info(
            "DRAW native_order=%s", ",".join(str(NATIVE[n][0]) for n in c.native_order)
        )
        self.logger.info(
            "DRAW enable_mask_pass1=%s", ",".join(f"{s}:{int(c.enabled(s, 1))}" for s in DRAWN)
        )
        self.logger.info("DRAW gateway=%s", ",".join(f"{s}:{c.cell(s)}" for s in GW_SRCS))
        self.logger.info("DRAW gateway_order=%s", ",".join(str(GW_SRCS[g]) for g in c.gw_order))
        self.logger.info("DRAW clear_value=0x%08x", c.clr_x)
        self.logger.info("DRAW boundary_bit=%d boundary_pair=%d,%d width=%d", *c.ext, width)
        patched = os.path.join(os.getcwd(), "sep_dtcm_pic_walk.hex")
        patch_param_block(_DTCM_HEX, patched, P_MAGIC_WORD, c.words())

        self.n_pass: Counter = Counter()
        self.marks: dict = {}
        self.vecs: dict = {}
        self.vec_marks: dict = {}
        self.slot_watch: dict = {}
        self.slot_rec: dict = {}
        self.rd_caps: list = []
        vec = self.dut.sep_internal_interrupts_probe_o
        self.w = SepBitWatch(
            vec, {"b11": vec_bit(SRC_DMA_ALERT), "b32": vec_bit(SRC_CRYPTO_ALERT)}, name="vec"
        )
        self.wa = SepBitWatch(
            self.dut.crypto_alert_pulse_probe_o,
            {f"a{i}": i for i in range(N_ALERT_IDX)},
            name="alert",
        )
        tasks = []

        async def _after_release() -> None:
            # The watchers start once the reset is released; the first REQ comes later.
            self.w.start()
            self.wa.start()
            tasks.append(cocotb.start_soon(self._rd_tap()))

        self.sb.expected_line = _BANNER
        self.con = SepFwConsole(self, graded_test=_TEST).start()
        self.con.on_mark(
            lambda leg, kind: self.logger.info("LEG LOG %s %s clk=%d", kind, leg, self.con.clk)
        )
        self.con.on_request("m", self._req_mark)
        self.con.on_request("vec", self._req_vec)
        self.con.on_request("stall", self._req_stall)
        self.con.on_request("kstall", self._req_kstall)
        self.con.on_request("ext", self._req_ext)
        self.con.on_request("win", self._req_win)
        # The firmware brings the entropy stack up for the AES and OTBN runs; the
        # ring oscillators take their raw noise from this driver (+esrc_noise_force).
        noise = self.start_esrc_noise_driver()
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                patched,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                after_bring_up_hook=_after_release,
            )
        finally:
            await self.con.stop()
            noise.cancel()
            for t in tasks:
                t.cancel()
            await self.w.stop()
            await self.wa.stop()
            self.dut.sep_ext_interrupts_i.value = 0
            self.dut.hmac_fifo_drain_stall_i.value = 0
            self.dut.kmac_fifo_drain_stall_i.value = 0
        assert self.sb.fw_done and self.sb.fw_pass, "firmware did not complete with PASS"
        for r in self.con.recs:
            if not r.name.startswith("CHK-"):
                self.logger.info("%s (firmware)", r.text)
        self._check_params()
        self._chk_base()
        self._chk_vector()
        self._chk_fifo_empty()
        self._chk_spi()
        ctrl = self._chk_alerts()
        self._chk_idle(ctrl)
        self._chk_ctrl_window()
        self._chk_slotless()
        self._chk_gateway()
        self._chk_ext()
        _, mc = self._meip("masked_clr")
        self.logger.info(
            "CTL-MASKED-CLEAR LOG baseline_equal=%d meip=%s",
            int(meip_masked(mc) == meip_masked(self._meip("reset")[1])),
            _hexw(mc),
        )
        n_eh = sum(1 for s in GW_SRCS if c.cell(s) == "EH")
        n_el = sum(1 for s in GW_SRCS if c.cell(s) == "EL")
        want = {
            "CHK-BASE": 4,
            "CHK-VECTOR": 4,
            "CHK-FIFO-EMPTY": 2,
            "CHK-SPI": 1,
            "CHK-ALERT12": 1,
            "CHK-ALERT-AGG": len(ALERTS),
            "CHK-ALERT-IDX": len(ALERTS) + 1,
            "CHK-ALERT-IDLE": 1,
            "CHK-ALERT-NONE": 1,
            "CHK-ALERT-NATIVE": len(NATIVE),
            "CHK-SRC17": 1,
            "CHK-IDLE-BAND": 1,
            "CHK-SLOTLESS": 3,
            "CHK-GW-CELL": len(GW_SRCS) - n_el,
            "CHK-EDGE-HOLD": n_eh,
            "CHK-HOLD": 1,
            "CHK-CLR-IDLE": 1,
            "CHK-GWCLR-VALUE": 1,
            "CHK-GW-NONVAC": 1,
            "CHK-EXT-IN": 2,
        }
        bad = {k: (self.n_pass[k], v) for k, v in want.items() if self.n_pass[k] != v}
        assert not bad, f"CHK-COUNT FAIL (got, want): {bad}"
        self.logger.info("CHK-COUNT LOG %s", " ".join(f"{k}={v}" for k, v in want.items()))
        self.logger.info("RESULT %s seed=%d PASS checks=%d", _TEST, c.seed, len(want))
