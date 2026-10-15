# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A WDT bark jumps to the NMI vector that holds, is not masked by the PIC or mstatus.MIE, and moves no PIC pending bit.

Firmware ``nmi_vector_bark_rand_test`` runs two boots of one image with a cold
reset (``rst_ni``) between them. This test draws the trampoline copy, the free
handler address ``A``, the bark thresholds, the second PIC case (b, c or d),
the pending source, its priority and ``priord`` from the run seed, places the
free handler ``Hk`` at ``A`` in the ICCM image outside the image bytes
(``env/sep_dtcm_param_patch.place_words``), patches the parameter block of each
boot, follows the console live (``env/sep_fw_console``: graded window on
``M G`` / ``M C``) and samples the CPU trace. It grades:

* CHK-NMI-TAKEN (host) each of the two barks of the locked-copy boot enters
  the common handler once through the drawn trampoline copy: the firmware
  entry address and run count, and the first retired PC after the wait loop
  on ``cpu_trace_addr_o``, equal the programmed vector. Bark 1 runs with
  mstatus.MIE 0, bark 2 with mstatus.MIE 1. ``wdt_timer_rst_req_o`` at the
  handler entry is logged (``OBS-BITE-REQ``).
* CHK-NMI-NOPIC (firmware) each of the eight meip words read in the NMI
  handler equals the same word read before the bark, with the six excluded
  idle bits masked; the pending source
  delivers once after its gate opens (case a and the drawn case).
* CHK-BARK-VEC (host) with SEP_NMI_VEC at its RDL reset value the first retired
  PC after the loop is 0xC000_0100 and the stub prints ``M0`` (control leg);
  after the cold reset, with ``A`` programmed and locked, it is ``A``, ``Hk``
  prints ``Mk`` and ``M0`` does not appear.

The expected vectors come from the RDL reset (``sep_reg_meta``), the image
layout (the firmware symbol listing) and the drawn ``A``, never from a DUT
read. cpu run mode, ``+skip_fuse_sense``, Verilator and VCS.
"""

from __future__ import annotations

import glob
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import parse_hex_cells, patch_param_block, place_words
from env.sep_fcov_gate import close_graded_window
from env.sep_fw_console import SepFwConsole
from env.sep_pic_map import meip_idle_mask_words, never_value
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import RegBlock, sym

TEST = "sep_nmi_vector_bark_rand_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "nmi_vector_bark_rand_test")
_ITCM_HEX = os.path.join(_FW_DIR, "nmi_vector_bark_rand_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "nmi_vector_bark_rand_test.dtcm.hex")
_BANNER = "SEP NMI vector bark test"
_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_ICCM_SIZE = sym("SEP_ICCM_MEM_SIZE")
_MAX_RUN_CYCLES = 8_000_000
_NO_BOOT_CYCLES = 80_000

_CPU_CTRL = RegBlock("SEP_CPU_CTRL")
VEC_RESET = _CPU_CTRL.reset("SEP_NMI_VEC") & _CPU_CTRL.mask("SEP_NMI_VEC")
LOCK_RESET = _CPU_CTRL.reset("SEP_NMI_VEC_LOCK") & _CPU_CTRL.mask("SEP_NMI_VEC_LOCK")
VEC_MASK = _CPU_CTRL.mask("SEP_NMI_VEC")
LOCK_MASK = _CPU_CTRL.mask("SEP_NMI_VEC_LOCK")

# Parameter block (fw/tests/nmi_vector_bark_rand_test, enum P_*).
P_MAGIC = 0x324A7B0C
N_BARK = 8  # bark thresholds 1..N_BARK; far below the bite threshold 0xFFFF_FFFF
WAIT_ITERS = 200_000  # > N_BARK clk_wdt_i periods of the wait loop
HOLD_ITERS = 3000
# OpenTitan event sources the firmware drives (hw/sys/sep/doc/interrupts.adoc).
SOURCES = (18, 20, 21, 23, 24, 28, 30)
CASES = {1: "b", 2: "c", 3: "d"}
# The console word and the completion magic of the bench responder
# (tb/sep_outbound_mbx.sv, fw/include/tb.h).
STDOUT = 0x8000_0000
MAGIC0 = 0xA5A5_5A5A
MAGIC_PASS = 0xCAFE_BABE


# ---- Hk: the free handler, RV32I machine code ----
def _lui(rd: int, imm20: int) -> int:
    return ((imm20 & 0xFFFFF) << 12) | (rd << 7) | 0x37


def _addi(rd: int, rs1: int, imm: int) -> int:
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (rd << 7) | 0x13


def _store(f3: int, rs2: int, rs1: int, off: int = 0) -> int:
    return ((off >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | ((off & 0x1F) << 7) | 0x23


def _li(rd: int, v: int) -> list[int]:
    hi = ((v + 0x800) >> 12) & 0xFFFFF
    lo = (v - (hi << 12)) & 0xFFF
    return [_lui(rd, hi), _addi(rd, rd, lo)]


FENCE = 0x0FF0000F
T0, T1 = 5, 6


def hk_words() -> list[int]:
    """Hk prints "Mk", writes the PASS magic pair to the console word and loops."""
    w = _li(T0, STDOUT)
    for ch in "Mk\n":
        w += [_addi(T1, 0, ord(ch)), _store(0, T1, T0), FENCE]
    for v in (MAGIC0, MAGIC_PASS):
        w += _li(T1, v) + [_store(2, T1, T0), FENCE]
    w.append(0x0000006F)  # jal x0, 0
    return w


def hk_block(a: int) -> tuple[int, list[int]]:
    """(ICCM byte offset, words) that put Hk at ``a``; a halfword-aligned ``a``
    gets a leading c.nop so the block stays word-aligned."""
    words = hk_words()
    off = a - _ICCM_BASE
    if off % 4 == 0:
        return off, words
    data = b"\x01\x00" + b"".join(x.to_bytes(4, "little") for x in words) + b"\x00\x00"
    return off - 2, [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


def load_symbols(fw_dir: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for path in glob.glob(os.path.join(fw_dir, "nmi_vector_bark_rand_test*.sym")):
        with open(path) as fh:
            for line in fh:
                parts = line.split()
                if len(parts) == 3:
                    try:
                        out[parts[2]] = int(parts[0], 16)
                    except ValueError:
                        continue
    return out


@dataclass(frozen=True)
class NmiCfg:
    """The seeded stimulus. A pure function of the run seed (and the image extent)."""

    seed: int
    copy: int
    case: int
    src: int
    priord: int
    raw: int
    barks: tuple[int, int, int, int]
    a: int

    @classmethod
    def from_seed(cls, seed: int, image_end: int) -> "NmiCfg":
        rng = SepSeededRng(seed)
        copy = rng.randrange(4)
        case = rng.randrange(1, 4)
        src = rng.choice(SOURCES)
        priord = rng.randrange(2)
        never = never_value(priord)
        raw = rng.choice([v for v in range(16) if v != never])
        barks = tuple(rng.randrange(1, N_BARK + 1) for _ in range(4))
        h = 4 * len(hk_words()) + 4
        lo = max(_ICCM_BASE + 0x1000, (image_end + 0x40 + 15) & ~15)
        hi = _ICCM_BASE + _ICCM_SIZE - h
        # A is halfword-aligned and never 256-byte aligned, so it is not a
        # trampoline-copy slot address.
        a = lo + 2 * rng.randrange((hi - lo) // 2)
        while a % 0x100 == 0:
            a = lo + 2 * rng.randrange((hi - lo) // 2)
        return cls(seed, copy, case, src, priord, raw, barks, a)

    def words(self, leg: int) -> list[int]:
        return [
            P_MAGIC,
            self.seed & 0xFFFF_FFFF,
            leg,
            self.copy,
            self.a,
            self.case,
            self.src,
            self.raw,
            self.priord,
            *self.barks,
            WAIT_ITERS,
            HOLD_ITERS,
            *meip_idle_mask_words(),
        ]

    def draw_line(self) -> str:
        return (
            f"DRAW copy={self.copy} case={CASES[self.case]} src={self.src} priord={self.priord} "
            f"raw={self.raw} bark_thold={','.join(str(b) for b in self.barks)} A=0x{self.a:08x} "
            f"H={4 * len(hk_words())} n_bark={N_BARK}"
        )


@pyuvm.test()
class sep_nmi_vector_bark_rand_test(sep_base_test):
    """The WDT bark NMI reaches the vector that holds, unmasked, and leaves the PIC pending state."""

    build_env = False
    required_evidence = ("CHK-NMI-TAKEN", "CHK-NMI-NOPIC", "CHK-BARK-VEC")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def _trace(self) -> None:
        """First retired PC after each stay in the wait loop, with the bite request."""
        dut = cocotb.top
        in_loop = False
        while True:
            await RisingEdge(dut.clk_i)
            await ReadOnly()
            v = dut.cpu_trace_valid_o.value
            if not (v.is_resolvable and int(v)):
                continue
            pc = int(dut.cpu_trace_addr_o.value) & 0xFFFF_FFFF
            e = dut.dbg_cpu_trace_exc_o.value
            exc = int(e) if e.is_resolvable else 1
            if self.loop[0] <= pc < self.loop[1]:
                in_loop = True
                continue
            if exc:
                self.exc_events.append((self.con.clk, pc))
                continue
            if in_loop:
                self.trans.append((self.con.clk, pc, str(dut.wdt_timer_rst_req_o.value)))
                in_loop = False

    def _leg(self, name: str) -> tuple[int, int]:
        legs = self.con.legs
        for i, (clk, _, leg) in enumerate(legs):
            if leg == name:
                return clk, legs[i + 1][0] if i + 1 < len(legs) else 1 << 62
        raise AssertionError(f"CHK-FW-CONSOLE FAIL: leg '{name}' never started")

    def _first_trans(self, name: str):
        lo, hi = self._leg(name)
        for t in self.trans:
            if lo <= t[0] < hi:
                return t
        return None

    def _one(self, name: str, **match):
        recs = [
            r
            for r in self.con.records(name)
            if all(str(r.kv.get(k)) == str(v) for k, v in match.items())
        ]
        if len(recs) != 1:
            raise AssertionError(f"expected one {name} {match}, got {len(recs)}")
        return recs[0]

    async def _second_boot(self, itcm: str, dtcm: str) -> None:
        """Cold reset (rst_ni) with the clocks running, TCM reload, CPU release."""
        dut = cocotb.top
        await RisingEdge(dut.clk_i)
        dut.rst_ni.value = 0
        self._set_pin(dut, "dbg_rstb_i", 0)
        await ClockCycles(dut.clk_i, 20)
        shutil.copyfile(itcm, os.path.join(os.getcwd(), "sep_itcm.hex"))
        shutil.copyfile(dtcm, os.path.join(os.getcwd(), "sep_dtcm.hex"))
        dut.tcm_load_i.value = 1
        await ClockCycles(dut.clk_i, 4)
        dut.tcm_load_i.value = 0
        await ClockCycles(dut.clk_i, 4)
        self.logger.info("cold reset: TCM reloaded with the leg-2 parameter block")
        dut.rst_ni.value = 1
        self._set_pin(dut, "dbg_rstb_i", 1)
        await self._wait_fuse_sense(20_000)
        await ClockCycles(dut.clk_i, 30)
        dut.i_cpu_run_req_i.value = 1
        await ClockCycles(dut.clk_i, 40)
        dut.i_cpu_run_req_i.value = 0
        await self.poll_boot(
            self.sb, max_run_cycles=_MAX_RUN_CYCLES, no_boot_cycles=_NO_BOOT_CYCLES
        )

    def _chk_taken(self, sy: dict[str, int]) -> int:
        cfg = self.tcfg
        vec = sy[f"nmivb_copy{cfg.copy}"]
        slots = [(sy[f"nmivb_copy{k}"] >> 8) & 3 for k in range(4)]
        if slots != [0, 1, 2, 3] or any(sy[f"nmivb_copy{k}"] % 0x100 for k in range(4)):
            raise AssertionError(
                f"CHK-NMI-TAKEN FAIL: copies not in four consecutive 256-byte slots: {slots}"
            )
        vs = self._one("CTL-VEC-SET", boot=1)
        if (vs.kv["vec"] & VEC_MASK) != vec or (vs.kv["lock"] & LOCK_MASK) != 1:
            raise AssertionError(
                f"CHK-NMI-TAKEN FAIL: vector or lock not set before the barks: {vs.text}"
            )
        legs = ("case_a", f"case_{CASES[cfg.case]}")
        for bark, (leg, mie) in enumerate(zip(legs, (0, 1), strict=True), start=1):
            rec = self._one("CTL-NMI-ENTRY", bark=bark)
            t = self._first_trans(leg)
            pc = t[1] if t else None
            bite = t[2] if t else "na"
            self.logger.info("OBS-BITE-REQ LOG bark=%d wdt_timer_rst_req_o=%s", bark, bite)
            kv = rec.kv
            ok = (
                kv.get("entry") == vec
                and int(kv.get("copy", -1)) == cfg.copy
                and int(kv.get("handler_runs", -1)) == 1
                and int(kv.get("mie", -1)) == mie
                and int(kv.get("timeout", 1)) == 0
                and pc == vec
            )
            body = (
                f"seed={cfg.seed} copy={cfg.copy} bark={bark} mie={kv.get('mie')} vec=0x{vec:08x} "
                f"handler_runs={kv.get('handler_runs')} entry=0x{kv.get('entry', 0):08x} "
                f"retired_pc={'0x%08x' % pc if pc is not None else 'none'}"
            )
            if not ok:
                raise AssertionError(f"CHK-NMI-TAKEN FAIL {body} exc={self.exc_events[-4:]}")
            self.logger.info("CHK-NMI-TAKEN PASS %s", body)
        return 2

    def _chk_bark_vec(self, sy: dict[str, int], boot2_clk: int) -> int:
        cfg = self.tcfg
        stub = sy["nmivb_stub"]
        if stub != VEC_RESET:
            raise AssertionError(
                f"CHK-BARK-VEC FAIL: image stub at 0x{stub:08x}, reset vector 0x{VEC_RESET:08x}"
            )
        r1 = self._one("CTL-VEC-RESET", boot=1)
        st = self.con.records("CTL-STUB")
        t = self._first_trans("reset_vector")
        pc0 = t[1] if t else None
        lo, hi = self._leg("reset_vector")
        m0 = [c for c, txt in self.con.lines if txt == "M0" and lo <= c < hi]
        pre = (r1.kv["vec"] & VEC_MASK) == VEC_RESET and (r1.kv["lock"] & LOCK_MASK) == LOCK_RESET
        ok = (
            pre
            and pc0 == VEC_RESET
            and len(m0) == 1
            and st
            and int(st[0].kv.get("stub_runs", 0)) == 1
        )
        body = (
            f"leg=reset_vector retired_pc={'0x%08x' % pc0 if pc0 is not None else 'none'} marker=M0 "
            f"m0_lines={len(m0)} vec_before=0x{r1.kv['vec']:08x} lock_before={r1.kv['lock']}"
        )
        if not ok:
            raise AssertionError(f"CHK-BARK-VEC FAIL {body} stub={st[0].text if st else None}")
        self.logger.info("CHK-BARK-VEC PASS %s", body)
        r2 = self._one("CTL-VEC-RESET", boot=2)
        vs = self._one("CTL-VEC-SET", boot=2)
        t = self._first_trans("programmed")
        pc = t[1] if t else None
        mk = [c for c, txt in self.con.lines if txt == "Mk" and c >= boot2_clk]
        m0b = [c for c, txt in self.con.lines if txt == "M0" and c >= boot2_clk]
        pre2 = (r2.kv["vec"] & VEC_MASK) == VEC_RESET and (r2.kv["lock"] & LOCK_MASK) == LOCK_RESET
        set2 = (vs.kv["vec"] & VEC_MASK) == (cfg.a & VEC_MASK) and (vs.kv["lock"] & LOCK_MASK) == 1
        ok = pre2 and set2 and pc == cfg.a and len(mk) == 1 and not m0b
        body = (
            f"leg=programmed programmed=0x{cfg.a:08x} retired_pc={'0x%08x' % pc if pc is not None else 'none'} "
            f"marker=Mk reset_marker_seen={int(bool(m0b))} control_pc=0x{pc0:08x} "
            f"vec_after_reset=0x{r2.kv['vec']:08x} lock_after_reset={r2.kv['lock']} "
            f"vec_rd=0x{vs.kv['vec']:08x} lock_rd={vs.kv['lock']}"
        )
        if not ok:
            raise AssertionError(f"CHK-BARK-VEC FAIL {body} mk={len(mk)}")
        self.logger.info("CHK-BARK-VEC PASS %s", body)
        return 2

    async def run_scenario(self) -> None:
        seed = self.random_seed()
        cells = parse_hex_cells(_ITCM_HEX)
        image_end = _ICCM_BASE + max(cells) + 1
        self.tcfg = cfg = NmiCfg.from_seed(seed, image_end)
        self.logger.info("SEED seed=%d", seed)
        self.logger.info("%s", cfg.draw_line())
        sy = load_symbols(_FW_DIR)
        need = ["nmivb_stub", "nmivb_loop_lo", "nmivb_loop_hi"] + [
            f"nmivb_copy{k}" for k in range(4)
        ]
        missing = [n for n in need if n not in sy]
        if missing:
            raise AssertionError(f"firmware symbol listing lacks {missing} in {_FW_DIR}")
        self.loop = (sy["nmivb_loop_lo"], sy["nmivb_loop_hi"])
        itcm = os.path.join(os.getcwd(), "sep_itcm_nmivb.hex")
        off, words = hk_block(cfg.a)
        place_words(_ITCM_HEX, itcm, off, words, limit=_ICCM_SIZE)
        dtcm1 = os.path.join(os.getcwd(), "sep_dtcm_nmivb_leg1.hex")
        dtcm2 = os.path.join(os.getcwd(), "sep_dtcm_nmivb_leg2.hex")
        patch_param_block(_DTCM_HEX, dtcm1, P_MAGIC, cfg.words(1))
        patch_param_block(_DTCM_HEX, dtcm2, P_MAGIC, cfg.words(2))
        self.logger.info(
            "Hk placed at ICCM offset 0x%x (%d words), image ends at 0x%08x",
            off,
            len(words),
            image_end,
        )
        self.sb.expected_line = _BANNER
        self.trans: list[tuple[int, int, str]] = []
        self.exc_events: list[tuple[int, int]] = []
        self.con = SepFwConsole(self, graded_test=TEST).start()
        tr = cocotb.start_soon(self._trace())
        close_graded_window(self.logger)
        try:
            await self.boot_firmware(
                self.sb,
                itcm,
                dtcm1,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
            )
            assert self.sb.fw_done and self.sb.fw_pass, (
                "boot 1: firmware did not complete with PASS"
            )
            if not self.con.text_lines("BOOT1-END"):
                raise AssertionError("boot 1 ended without its end-of-boot marker")
            close_graded_window(self.logger)
            self.sb.fw_done = False
            self.sb.fw_pass = False
            boot2_clk = self.con.clk
            await self._second_boot(itcm, dtcm2)
        finally:
            tr.cancel()
            await self.con.stop()
        assert self.sb.fw_done and self.sb.fw_pass, "boot 2: Hk did not write the PASS magic"
        lay = self.con.text_lines("LAYOUT")
        prm = self.con.text_lines("PARAMS")
        if (
            len(prm) != 2
            or f"seed=0x{seed & 0xFFFF_FFFF:08x}" not in prm[0]
            or "leg=2" not in prm[1]
        ):
            raise AssertionError(f"firmware did not run the patched blocks: {prm}")
        if not lay or f"stub=0x{sy['nmivb_stub']:08x}" not in lay[0]:
            raise AssertionError(f"firmware layout {lay} disagrees with the symbol listing")
        n_fw = self.con.relay_chk()
        self.con.require_counts({"CHK-NMI-NOPIC": 2})
        cases = [r.kv.get("case") for r in self.con.records("CHK-NMI-NOPIC")]
        if cases != ["a", CASES[cfg.case]]:
            raise AssertionError(f"CHK-NMI-NOPIC FAIL: cases {cases}, drawn a,{CASES[cfg.case]}")
        n_host = self._chk_taken(sy) + self._chk_bark_vec(sy, boot2_clk)
        self.result_pass(TEST, seed, n_fw + n_host)
