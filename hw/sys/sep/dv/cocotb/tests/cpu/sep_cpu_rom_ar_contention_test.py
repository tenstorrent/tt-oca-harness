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
ARVALID high with ARREADY low while the other master requested the ROM, grades
that each held its AR through those stalls, and grades the data every load
returned.

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
  CTRL-ROM-AR-STALL : the bench samples, on ``clk_i`` after ReadOnly and only
                      between a BEGIN and its END marker, which master
                      requests the boot ROM: the IFU when
                      ``pr_cpu_ifu_arvalid_o`` = 1 and ``pr_ifu_araddr_o``
                      (PR-IFU, the same AR after the combinational alias
                      remap) is in the boot ROM; the LSU when
                      ``pr_cpu_lsu_arvalid_o`` = 1 and ``pr_cpu_lsu_araddr_o``
                      is in the boot ROM. It counts the contended stall
                      clocks: the IFU requests the ROM with
                      ``pr_cpu_ifu_arready_o`` = 0 while the LSU requests the
                      ROM, and the converse with ``pr_cpu_lsu_arready_o``.
                      The valid and ready taps read the raw CPU request and
                      response before any remap. Both totals must be at
                      least 1, or the leaf fails with CTRL-MISSING. The
                      per-routine counts are logged.
  CHK-ROM-AR-HOLD   : on the same samples, every clock inside a window where
                      a port has ARVALID = 1 and ARREADY = 0 sets an
                      obligation: at the next sample, also when the END
                      marker has closed the window, that port has ARVALID = 1
                      and the same AR payload. IFU payload: address, ID,
                      AxLEN, AxSIZE (``pr_ifu_ar*_o``, PR-IFU) and AxPROT
                      (``pr_cpu_ifu_arprot_o``). LSU payload: address,
                      AxBURST, AxLOCK, AxCACHE, AxQOS, AxREGION and AxPROT
                      (``pr_cpu_lsu_ar*_o``). A violation logs
                      ``CHK-ROM-AR-HOLD FAIL: port= field= was= now= t=`` as
                      an error at once, and the leaf fails, also when the
                      firmware run ends by a timeout or an error. PASS logs
                      the held count of each port and the held count on
                      contended stall clocks. Each contended count must be
                      at least 1 and equal the CTRL-ROM-AR-STALL total of
                      its port, so every contended stall clock is graded.
  INFO-ROM-AR-TRAFFIC : per routine, the IFU and LSU-to-ROM AR handshakes, the
                      clocks with both masters requesting the ROM, the
                      contended stall clocks, and the stall clocks of each
                      port with or without the other master (logged, not
                      graded).
  CHK-ROM-AR-SUM    : firmware, one line per routine and pass
                      (``routine=<k> pass=<p> got= want=``). Host side: the
                      console holds the twelve PASS lines, one per (k, p), and
                      no FAIL line; each ``got`` equals the hash the host
                      computes from the generator data words, chained from
                      the initial hash 5381; and the firmware summary is
                      ``PASS: 12/12``. Golden: the data words of the committed
                      image (stimulus), read back through the ROM.

The bench AXI checkers on the raw ports (``u_cpu_lsu_axi_sva`` and
``u_cpu_ifu_axi_sva``: OCAH_AXI_AR_VALID_HELD, OCAH_AXI_AR_PAYLOAD_STABLE) grade
the same rule on every clock, inside and outside the windows, on both
simulators; this stimulus arms them. ``+axi_sva_need_lsu`` and
``+axi_sva_need_ifu`` fail a VCS run in which either checker graded no
handshake.

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
from cocotb.utils import get_sim_time
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
# AR valid, ready and payload taps of each CPU port. The IFU payload is read
# after the alias remap (PR-IFU), on the same clock as the raw valid; the remap
# changes only the address. The LSU payload is the raw request.
_AR_PORTS = {
    "ifu": (
        "pr_cpu_ifu_arvalid_o",
        "pr_cpu_ifu_arready_o",
        (
            ("addr", "pr_ifu_araddr_o"),
            ("id", "pr_ifu_arid_o"),
            ("len", "pr_ifu_arlen_o"),
            ("size", "pr_ifu_arsize_o"),
            ("prot", "pr_cpu_ifu_arprot_o"),
        ),
    ),
    "lsu": (
        "pr_cpu_lsu_arvalid_o",
        "pr_cpu_lsu_arready_o",
        (
            ("addr", "pr_cpu_lsu_araddr_o"),
            ("burst", "pr_cpu_lsu_arburst_o"),
            ("lock", "pr_cpu_lsu_arlock_o"),
            ("cache", "pr_cpu_lsu_arcache_o"),
            ("qos", "pr_cpu_lsu_arqos_o"),
            ("region", "pr_cpu_lsu_arregion_o"),
            ("prot", "pr_cpu_lsu_arprot_o"),
        ),
    ),
}
_SUM = re.compile(
    r"CHK-ROM-AR-SUM (PASS|FAIL): routine=(\d+) pass=(\d+) got=0x([0-9a-f]{8}) want=0x([0-9a-f]{8})"
)


def _hash_pass(h: int) -> int:
    for w in _GEN.data_words():
        h = ((h + (h << 5)) ^ w) & _MASK32
    return h


class _ArStallSampler:
    """Counts AR stalls and handshakes of the IFU and LSU ports between console markers, and grades the AR hold."""

    def __init__(self, dut, sb: SepBootScoreboard, rd, logger) -> None:
        self.dut = dut
        self.sb = sb
        self.rd = rd
        self.logger = logger
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
        self.ifu_contend = [0] * n
        self.lsu_contend = [0] * n
        self.ifu_hs = [0] * n
        self.lsu_rom_hs = [0] * n
        self.both_valid = [0] * n
        # Stall of the previous sample per port: (payload, contended).
        self.pending: dict[str, tuple[tuple[int, ...], bool]] = {}
        self.held = dict.fromkeys(_AR_PORTS, 0)
        self.contend_held = dict.fromkeys(_AR_PORTS, 0)
        self.hold_fails: list[str] = []

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

    def _payload(self, port: str) -> tuple[int, ...]:
        return tuple(self.rd(getattr(self.dut, tap)) for _, tap in _AR_PORTS[port][2])

    def _grade_pending(self) -> None:
        for port, (want, contended) in self.pending.items():
            valid_tap, _, fields = _AR_PORTS[port]
            if self.rd(getattr(self.dut, valid_tap)):
                got = self._payload(port)
                bad = [(name, w, g) for (name, _), w, g in zip(fields, want, got) if w != g]
            else:
                bad = [("valid", 1, 0)]
            if not bad:
                self.held[port] += 1
                self.contend_held[port] += contended
                continue
            for name, was, now in bad:
                line = (
                    f"CHK-ROM-AR-HOLD FAIL: port={port} field={name} was=0x{was:x} now=0x{now:x} "
                    f"t={get_sim_time('ns'):.2f}"
                )
                self.logger.error(line)
                self.hold_fails.append(line)
        self.pending.clear()

    def _sample(self, k: int) -> None:
        dut, rd = self.dut, self.rd
        ifu_v = rd(dut.pr_cpu_ifu_arvalid_o)
        ifu_r = rd(dut.pr_cpu_ifu_arready_o)
        lsu_v = rd(dut.pr_cpu_lsu_arvalid_o)
        lsu_r = rd(dut.pr_cpu_lsu_arready_o)
        ifu_rom = ifu_v and _ROM_BASE <= rd(dut.pr_ifu_araddr_o, mask=_MASK32) < _ROM_END
        lsu_rom = lsu_v and _ROM_BASE <= rd(dut.pr_cpu_lsu_araddr_o, mask=_MASK32) < _ROM_END
        if ifu_v:
            if ifu_r:
                self.ifu_hs[k] += 1
            else:
                self.ifu_stall[k] += 1
        if lsu_rom:
            if lsu_r:
                self.lsu_rom_hs[k] += 1
            else:
                self.lsu_stall[k] += 1
        if ifu_rom and lsu_rom:
            self.both_valid[k] += 1
            self.ifu_contend[k] += not ifu_r
            self.lsu_contend[k] += not lsu_r
        if ifu_v and not ifu_r:
            self.pending["ifu"] = (self._payload("ifu"), ifu_rom and lsu_rom)
        if lsu_v and not lsu_r:
            self.pending["lsu"] = (self._payload("lsu"), ifu_rom and lsu_rom)

    async def run(self) -> None:
        clk = self.dut.clk_i
        try:
            while not self.stop:
                await RisingEdge(clk)
                await ReadOnly()
                self._scan_console()
                self._grade_pending()
                if self.open_k is not None:
                    self._sample(self.open_k)
        except Exception as exc:
            self.error = exc


@pyuvm.test()
class sep_cpu_rom_ar_contention_test(sep_base_test):
    """IFU fetches and LSU loads of ROM-resident loops stall each other at the boot-ROM mux, and every hash matches."""

    build_env = False
    required_evidence = ("CHK-ROM-AR-SUM", "CHK-ROM-AR-HOLD")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    async def run_scenario(self) -> None:
        self._check_image()
        self.sb.expected_line = _BANNER
        sampler = _ArStallSampler(cocotb.top, self.sb, self.rd, self.logger)
        sampler_task = cocotb.start_soon(sampler.run())
        try:
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
        finally:
            sampler.stop = True
            await sampler_task
            if sampler.hold_fails:
                raise AssertionError("; ".join(sampler.hold_fails))
        if sampler.error is not None:
            raise AssertionError(f"AR stall sampler died: {sampler.error!r}") from sampler.error

        console = self.sb.console_text()
        self._check_cfg(console)
        self._check_windows(sampler)
        self._check_stall(sampler)
        self._check_hold(sampler)
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
                "INFO-ROM-AR-TRAFFIC k=%d ifu_ar=%d lsu_rom_ar=%d both_rom_arvalid_clk=%d "
                "ifu_contend_stall_clk=%d lsu_contend_stall_clk=%d "
                "ifu_stall_clk=%d lsu_stall_clk=%d",
                k,
                s.ifu_hs[k],
                s.lsu_rom_hs[k],
                s.both_valid[k],
                s.ifu_contend[k],
                s.lsu_contend[k],
                s.ifu_stall[k],
                s.lsu_stall[k],
            )
        ifu, lsu = sum(s.ifu_contend), sum(s.lsu_contend)
        text = (
            f"ifu_contend_stall_clk={ifu} lsu_contend_stall_clk={lsu} floor=1 each "
            f"per_k_ifu={s.ifu_contend} per_k_lsu={s.lsu_contend}"
        )
        if ifu < 1 or lsu < 1:
            raise AssertionError(
                f"CTRL-MISSING CTRL-ROM-AR-STALL: {text}; a port that never saw ARVALID=1 "
                "with ARREADY=0 to the boot ROM while the other master requested the ROM "
                "inside a ROM loop window leaves the contended AR hold ungraded"
            )
        self.logger.info("CTRL-ROM-AR-STALL: %s", text)

    def _check_hold(self, s: _ArStallSampler) -> None:
        contend = {"ifu": sum(s.ifu_contend), "lsu": sum(s.lsu_contend)}
        text = (
            f"ifu_held={s.held['ifu']} ifu_contend_held={s.contend_held['ifu']} "
            f"lsu_held={s.held['lsu']} lsu_contend_held={s.contend_held['lsu']} floor=1 each"
        )
        short = [p for p in _AR_PORTS if s.contend_held[p] < 1 or s.contend_held[p] != contend[p]]
        if short:
            raise AssertionError(
                f"CHK-ROM-AR-HOLD FAIL: {text}; contended stall clocks ifu={contend['ifu']} "
                f"lsu={contend['lsu']}; ports {short} have a contended stall clock that was not "
                "graded held, or none at all"
            )
        fields = {p: ",".join(["valid"] + [name for name, _ in f[2]]) for p, f in _AR_PORTS.items()}
        self.logger.info(
            "CHK-ROM-AR-HOLD PASS: %s (contended) fields_ifu=%s fields_lsu=%s",
            text,
            fields["ifu"],
            fields["lsu"],
        )

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
