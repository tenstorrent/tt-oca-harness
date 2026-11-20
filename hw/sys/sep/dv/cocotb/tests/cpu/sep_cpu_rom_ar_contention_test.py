# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The IFU and the LSU contend for the boot ROM; each holds its AR until ARREADY and every load returns the image.

Contract. SEP uses an AXI4 fabric (hw/sys/sep/doc/fabric.adoc:20, "SEP uses a
hierarchical AXI4 crossbar fabric"; doc/starting/src/guidelines.adoc:24-25,
"System interconnect is implemented with AMBA standard buses. AXI4 ..."). Under
the AMBA AXI handshake rule (as the bench checker states it,
hw/common/dv/vip/ocah_axi_vip/sva/ocah_axi_sva.sv:152-153), an AR transfer occurs only
in a cycle where ARVALID and ARREADY are both high, and a master that asserts
ARVALID keeps it high, with the AR payload stable, until that cycle. The boot-ROM
mux serves the VeeR EL2 instruction-fetch (IFU) and load/store (LSU) AXI ports
from one ROM interface, so one master sees ARREADY low while the other is
served. The test makes both masters present AR there, proves that each saw
ARVALID high with ARREADY low, and grades the data every load returned.

Stimulus. ``+sep_boot_rom_hex=rom_ar_contention_rom.hex`` preloads the boot ROM.
``fw/tests/rom_ar_contention_test/gen_rom_ar_contention_rom.py`` generates that
image and the firmware header ``rom_ar_contention_rom.h`` from one table: three
hash routines and a data block of 32 fixed words. Routine k runs k ``nop`` words
before its loop, so the three loops start at different offsets in the fetch
stream. The loop loads each word with ``lw`` from ROM and folds it into
``h = (h * 33) ^ w``. The firmware runs from ICCM, so every IFU AXI fetch in the
test is a fetch of ROM-resident code. For each routine k it prints
``ROM-AR-BEGIN k=<k>``, calls the routine four times over the whole block, and
prints ``ROM-AR-END k=<k>``. The console store of each marker completes (fence)
before the next instruction. The boot ROM sits in a side-effect region under
the crt0 mrac, so the LSU issues the loads one at a time; the IFU keeps fetching
the loop around each load. The IFU fetch reads only the mrac cacheable bit, so
ROM fetch is legal under the crt0 mrac, as in sep_rom_sanity_test.
``+skip_fuse_sense`` leaves the ROM lane order at its default: the low 32 bits
of an image word are the lower address, as sep_boot_rom_lsu_read_test reads
them. Nothing is random: every seed runs the same program, and the testlist
entry has no reseed.

Records:
  CTRL-ROM-AR-IMAGE : the staged ROM image equals the generator output, and
                      the firmware ROM-AR-CFG line equals the generator
                      parameters (routines, passes, groups, data address,
                      initial hash).
  CTRL-ROM-AR-WINDOW: the console holds one BEGIN/END pair for each routine
                      k = 0, 1, 2, in order, with no nested BEGIN.
  CTRL-ROM-AR-STALL : the bench counts, on ``clk_i`` after ReadOnly and only
                      between a BEGIN and its END marker, the clocks with
                      ``pr_cpu_ifu_arvalid_o`` = 1 and ``pr_cpu_ifu_arready_o``
                      = 0, and the clocks with ``pr_cpu_lsu_arvalid_o`` = 1,
                      ``pr_cpu_lsu_arready_o`` = 0 and ``pr_cpu_lsu_araddr_o``
                      in the boot ROM. These taps read the raw CPU request
                      and the raw response ready before any remap. Both totals
                      must be at least 1, or the leaf fails with CTRL-MISSING.
                      The per-routine counts are logged.
  INFO-ROM-AR-TRAFFIC : per routine, the IFU and LSU-to-ROM AR handshakes and
                      the clocks with both ARVALIDs high (logged, not graded).
  CHK-ROM-AR-SUM    : firmware, one line per routine and pass
                      (``routine=<k> pass=<p> got= want=``). Host side: the
                      console holds the twelve PASS lines, one per (k, p), and
                      no FAIL line; each ``got`` equals the hash the host
                      computes from the generator data words, chained from
                      the initial hash 5381; and the firmware summary is
                      ``PASS: 12/12``. Golden: the data words of the committed
                      image (stimulus), read back through the ROM.

The AR handshake rule itself is graded by the bench AXI checkers on the raw
ports (``u_cpu_lsu_axi_sva`` and ``u_cpu_ifu_axi_sva``:
OCAH_AXI_AR_VALID_HELD, OCAH_AXI_AR_PAYLOAD_STABLE), which this stimulus arms.
``+axi_sva_need_lsu`` and ``+axi_sva_need_ifu`` fail a VCS run in which either
checker graded no handshake. A master that takes a transfer while ARREADY is
low also loses that AR, so its load or fetch never completes and the firmware
verdict times out.

fw/startup/crt0.s emits PASS/FAIL magic from main()'s error count, which the
boot scoreboard gates on with the banner and ICCM-execution checks.
"""

from __future__ import annotations

import importlib.util
import os
import re
from pathlib import Path

import cocotb
import pyuvm
from cocotb.triggers import ReadOnly, RisingEdge
from env.sep_boot_scoreboard import SepBootScoreboard
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_DV_ROOT = Path(__file__).resolve().parents[3]
_FW_SRC = _DV_ROOT / "fw" / "tests" / "rom_ar_contention_test"
_FW_DIR = os.path.join(str(_DV_ROOT), "fw", "build", "tests", "rom_ar_contention_test")
_ITCM_HEX = os.path.join(_FW_DIR, "rom_ar_contention_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "rom_ar_contention_test.dtcm.hex")
_ROM_HEX_PLUSARG = "sep_boot_rom_hex"


def _load_gen():
    path = _FW_SRC / "gen_rom_ar_contention_rom.py"
    spec = importlib.util.spec_from_file_location("gen_rom_ar_contention_rom", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GEN = _load_gen()

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_ROM_END = _ROM_BASE + sym("SEP_BOOT_ROM_MEM_SIZE")
_DATA_ADDR = _ROM_BASE + _GEN.DATA_OFF
_GROUPS = _GEN.DATA_WORDS // _GEN.GROUP_WORDS
# ROM_AR_PASSES and ROM_AR_HASH_INIT in rom_ar_contention_test.c; the firmware
# echoes both on its ROM-AR-CFG line and CTRL-ROM-AR-IMAGE compares them.
_PASSES = 4
_HASH_INIT = 5381
_MASK32 = 0xFFFF_FFFF

_MAX_RUN_CYCLES = 1_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP ROM AR contention test"

_MARKER = re.compile(r"ROM-AR-(BEGIN|END) k=(\d+)$")
_CFG = re.compile(
    r"ROM-AR-CFG routines=0x([0-9a-f]{8}) passes=0x([0-9a-f]{8}) groups=0x([0-9a-f]{8})"
    r" data=0x([0-9a-f]{8}) init=0x([0-9a-f]{8})"
)
_SUM = re.compile(
    r"CHK-ROM-AR-SUM (PASS|FAIL): routine=(\d+) pass=(\d+) got=0x([0-9a-f]{8}) want=0x([0-9a-f]{8})"
)


def _hash_pass(h: int) -> int:
    for w in _GEN.data_words():
        h = ((h + (h << 5)) ^ w) & _MASK32
    return h


class _ArStallSampler:
    """Counts AR stalls and handshakes of the raw IFU and LSU ports between console markers."""

    def __init__(self, dut, sb: SepBootScoreboard, rd) -> None:
        self.dut = dut
        self.sb = sb
        self.rd = rd
        self.stop = False
        self.error: BaseException | None = None
        self.pos = 0
        self.line = bytearray()
        self.open_k: int | None = None
        self.events: list[tuple[str, int]] = []
        self.bad_markers: list[str] = []
        n = _GEN.ROUTINES
        self.ifu_stall = [0] * n
        self.lsu_stall = [0] * n
        self.ifu_hs = [0] * n
        self.lsu_rom_hs = [0] * n
        self.both_valid = [0] * n

    def _scan_console(self) -> None:
        buf = self.sb.console
        while self.pos < len(buf):
            ch = buf[self.pos]
            self.pos += 1
            if ch != ord("\n"):
                self.line.append(ch)
                continue
            text = self.line.decode("ascii", "replace")
            self.line.clear()
            m = _MARKER.search(text)
            if not m:
                continue
            kind, k = m.group(1), int(m.group(2))
            self.events.append((kind, k))
            if k >= _GEN.ROUTINES:
                self.bad_markers.append(f"{kind} k={k} out of range")
            elif kind == "BEGIN":
                if self.open_k is not None:
                    self.bad_markers.append(f"BEGIN k={k} inside open k={self.open_k}")
                self.open_k = k
            else:
                if self.open_k != k:
                    self.bad_markers.append(f"END k={k} with open k={self.open_k}")
                self.open_k = None

    def _sample(self, k: int) -> None:
        dut, rd = self.dut, self.rd
        ifu_v = rd(dut.pr_cpu_ifu_arvalid_o)
        ifu_r = rd(dut.pr_cpu_ifu_arready_o)
        lsu_v = rd(dut.pr_cpu_lsu_arvalid_o)
        lsu_r = rd(dut.pr_cpu_lsu_arready_o)
        if ifu_v:
            if ifu_r:
                self.ifu_hs[k] += 1
            else:
                self.ifu_stall[k] += 1
        if lsu_v:
            addr = rd(dut.pr_cpu_lsu_araddr_o, mask=_MASK32)
            if _ROM_BASE <= addr < _ROM_END:
                if lsu_r:
                    self.lsu_rom_hs[k] += 1
                else:
                    self.lsu_stall[k] += 1
        if ifu_v and lsu_v:
            self.both_valid[k] += 1

    async def run(self) -> None:
        clk = self.dut.clk_i
        try:
            while not self.stop:
                await RisingEdge(clk)
                await ReadOnly()
                self._scan_console()
                if self.open_k is not None:
                    self._sample(self.open_k)
        except Exception as exc:
            self.error = exc


@pyuvm.test()
class sep_cpu_rom_ar_contention_test(sep_base_test):
    """IFU fetches and LSU loads of ROM-resident loops stall each other at the boot-ROM mux, and every hash matches."""

    build_env = False
    required_evidence = ("CHK-ROM-AR-SUM",)

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self._check_image()
        self.sb.expected_line = _BANNER
        sampler = _ArStallSampler(cocotb.top, self.sb, self.rd)
        cocotb.start_soon(sampler.run())
        await self.boot_firmware(
            self.sb,
            _ITCM_HEX,
            _DTCM_HEX,
            rst_vec=_ICCM_BASE >> 1,
            max_run_cycles=_MAX_RUN_CYCLES,
            no_boot_cycles=_NO_BOOT_CYCLES,
            progress_every=_PROGRESS_EVERY,
        )
        await RisingEdge(cocotb.top.clk_i)
        sampler.stop = True
        if sampler.error is not None:
            raise AssertionError(f"AR stall sampler died: {sampler.error!r}") from sampler.error

        console = self.sb.console_text()
        self._check_cfg(console)
        self._check_windows(sampler)
        self._check_stall(sampler)
        self._check_sums(console)

    def _check_image(self) -> None:
        name = cocotb.plusargs.get(_ROM_HEX_PLUSARG)
        assert name, f"+{_ROM_HEX_PLUSARG} is not set; the boot ROM holds no test image"
        path = Path(name) if os.path.isabs(name) else Path(os.getcwd()) / name
        assert path.is_file(), f"CTRL-ROM-AR-IMAGE FAIL: staged ROM image {path} is absent"
        same = path.read_text() == _GEN.hex_text()
        assert same, (
            f"CTRL-ROM-AR-IMAGE FAIL: {path} differs from the output of "
            "gen_rom_ar_contention_rom.py; regenerate the image and the header"
        )
        self.logger.info("CTRL-ROM-AR-IMAGE: staged %s equals the generator output", path.name)

    def _check_cfg(self, console: str) -> None:
        m = _CFG.search(console)
        assert m, f"CTRL-ROM-AR-IMAGE FAIL: no ROM-AR-CFG line. Console was:\n{console}"
        got = tuple(int(v, 16) for v in m.groups())
        want = (_GEN.ROUTINES, _PASSES, _GROUPS, _DATA_ADDR, _HASH_INIT)
        assert got == want, (
            f"CTRL-ROM-AR-IMAGE FAIL: firmware ROM-AR-CFG {tuple(hex(v) for v in got)} "
            f"differs from the host {tuple(hex(v) for v in want)}"
        )
        self.logger.info(
            "CTRL-ROM-AR-IMAGE: firmware parameters routines=%d passes=%d groups=%d "
            "data=0x%08x init=0x%08x equal the host's",
            *want,
        )

    def _check_windows(self, s: _ArStallSampler) -> None:
        want = [(kind, k) for k in range(_GEN.ROUTINES) for kind in ("BEGIN", "END")]
        ok = s.events == want and not s.bad_markers and s.open_k is None
        text = f"events={s.events} problems={s.bad_markers or '-'}"
        assert ok, f"CTRL-MISSING CTRL-ROM-AR-WINDOW: {text}; want {want}"
        self.logger.info("CTRL-ROM-AR-WINDOW: %d BEGIN/END pairs in order", _GEN.ROUTINES)

    def _check_stall(self, s: _ArStallSampler) -> None:
        for k in range(_GEN.ROUTINES):
            self.logger.info(
                "INFO-ROM-AR-TRAFFIC k=%d ifu_ar=%d lsu_rom_ar=%d both_arvalid_clk=%d "
                "ifu_stall_clk=%d lsu_stall_clk=%d",
                k,
                s.ifu_hs[k],
                s.lsu_rom_hs[k],
                s.both_valid[k],
                s.ifu_stall[k],
                s.lsu_stall[k],
            )
        ifu, lsu = sum(s.ifu_stall), sum(s.lsu_stall)
        text = (
            f"ifu_stall_clk={ifu} lsu_stall_clk={lsu} floor=1 each "
            f"per_k_ifu={s.ifu_stall} per_k_lsu={s.lsu_stall}"
        )
        if ifu < 1 or lsu < 1:
            raise AssertionError(
                f"CTRL-MISSING CTRL-ROM-AR-STALL: {text}; a port that never saw ARVALID=1 "
                "with ARREADY=0 inside a ROM loop window leaves its AR hold rule ungraded"
            )
        self.logger.info("CTRL-ROM-AR-STALL: %s", text)

    def _check_sums(self, console: str) -> None:
        want_chain = []
        h = _HASH_INIT
        for _ in range(_PASSES):
            h = _hash_pass(h)
            want_chain.append(h)
        lines = _SUM.findall(console)
        fails = [ln for ln in lines if ln[0] == "FAIL"]
        cells: dict[tuple[int, int], int] = {}
        problems: list[str] = []
        for verdict, k, p, got, want in lines:
            if verdict != "PASS":
                continue
            key = (int(k), int(p))
            if key in cells:
                problems.append(f"duplicate line for routine={k} pass={p}")
            cells[key] = int(got, 16)
            if not 0 <= key[1] < _PASSES or not 0 <= key[0] < _GEN.ROUTINES:
                problems.append(f"routine={k} pass={p} out of range")
            elif int(got, 16) != want_chain[key[1]] or int(want, 16) != want_chain[key[1]]:
                problems.append(
                    f"routine={k} pass={p} got=0x{got} fw_want=0x{want} "
                    f"host_want=0x{want_chain[key[1]]:08x}"
                )
        expected = {(k, p) for k in range(_GEN.ROUTINES) for p in range(_PASSES)}
        missing = sorted(expected - set(cells))
        total = _GEN.ROUTINES * _PASSES
        summary = f"PASS: {total}/{total} " in console
        text = (
            f"pass_lines={len(cells)}/{total} fail_lines={len(fails)} missing={missing or '-'} "
            f"summary={int(summary)} host_want={','.join(f'0x{v:08x}' for v in want_chain)}"
        )
        if fails or missing or problems or not summary:
            detail = "; ".join(problems + [str(f) for f in fails])
            raise AssertionError(f"CHK-ROM-AR-SUM FAIL: {text} {detail}")
        self.logger.info("CHK-ROM-AR-SUM PASS: %s", text)
