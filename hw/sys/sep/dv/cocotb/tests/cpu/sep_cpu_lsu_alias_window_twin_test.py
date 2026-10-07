# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A CPU LSU access through the local alias window answers as its direct twin.

The 768 MiB window at ``SEP_LOCAL_BASE_ADDR`` (reset ``0xD000_0000``) rewrites
to ``0x1000_0000`` (``hw/sys/sep/doc/fabric.adoc``, "Address Remapping" and
"Fabric Topology"; ``hw/sys/sep/doc/memory_map.adoc``), so the alias of a local
address is the direct address plus ``0xC000_0000``. The window base stays at its
reset value, because the specification states no legal range for it.

The ``alias_twin_test`` firmware runs on the CPU: the alias remap sits in the
core path, so the ``no_cpu`` splice cannot drive it. The host draws the values
from the run seed and patches them into the firmware parameter block. The
firmware writes the writable words at their direct addresses, reads one static
word of each unit class (cold scratch, AES ``CTRL_SHADOWED``, ``SEP_VERSION_ID``,
SPI host ``CSID``, entropy source ``COMPONENT_ID``) direct, alias, direct, reads
the SRAM start and last words direct then alias, writes a marker through the
alias of the scratch word and reads it back direct. It prints every value. The
host grades the printed values against the seeded values and the RDL:

* CHK-TWIN: per unit class and SRAM word, the alias read equals the direct read
  and the two direct reads agree; a writable word equals its seeded value; AES
  ``CTRL_SHADOWED`` equals the RDL reset of its fields. Compares use the RDL
  field bits; the Reserved bits are logged. For the SRAM words PR-SRAM shows one
  read request for the direct read and one for the alias read, at one address.
* CHK-TWIN-WR: the marker written through the alias reads back at the direct
  address.

An X in a read value makes the console byte unknown, and the console sampler
of ``sep_base_test`` raises on it, so the leaf fails on VCS. PR-SRAM records an
unknown field as None, which the SRAM part of CHK-TWIN fails.

The leaf drives no LSU access to the extension window: its tie-off answers
DECERR and the specification states no CPU consequence of an error response on
a load.

cpu / ``+skip_fuse_sense``: the leaf reads no fuse data.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

import pyuvm
from env.sep_boot_scoreboard import SepBootScoreboard
from env.sep_dtcm_param_patch import patch_param_block
from env.sep_fabric_tap import SepFabricTap
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import register_fields, sym

_TEST = "sep_cpu_lsu_alias_window_twin_test"
_DV_ROOT = str(Path(__file__).resolve().parents[3])
_FW_DIR = os.path.join(_DV_ROOT, "fw", "build", "tests", "alias_twin_test")
_ITCM_HEX = os.path.join(_FW_DIR, "alias_twin_test.itcm.hex")
_DTCM_HEX = os.path.join(_FW_DIR, "alias_twin_test.dtcm.hex")

_ICCM_BASE = sym("SEP_ICCM_MEM_BASE_ADDR")
_MAX_RUN_CYCLES = 2_000_000
_NO_BOOT_CYCLES = 80_000
_PROGRESS_EVERY = 5_000
_BANNER = "SEP CPU LSU alias twin test"

# Must equal TWIN_PARAM_MAGIC of fw/tests/alias_twin_test/alias_twin_test.c.
_PARAM_MAGIC = 0xA7C1D3E5

_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
_WINDOW_BASE = sym("SEP_CPU_CTRL_SEP_LOCAL_BASE_ADDR_REG_DEFAULT")
_ALIAS_DELTA = _WINDOW_BASE - _SRAM_BASE

# Unit class -> (direct address, writable). The firmware reads the same words.
_UNITS: dict[str, tuple[int, bool]] = {
    "scratch": (sym("SEP_SCRATCH_COLD_SCRATCH_3__REG_ADDR"), True),
    "aes_word": (sym("AES_CTRL_SHADOWED_REG_ADDR"), False),
    "sys_csr": (sym("SEP_CPU_CTRL_SEP_VERSION_ID_REG_ADDR"), False),
    "spi_word": (sym("SPI_CONTROLLER_CSID_REG_ADDR"), True),
    "esrc_word": (sym("ENTROPY_SOURCE_COMPONENT_ID_REG_ADDR"), False),
}
_SRAM_WORDS: dict[str, int] = {
    "sram_start": _SRAM_BASE,
    "sram_end": _SRAM_BASE + _SRAM_SIZE - 4,
}

_HEX = r"0x([0-9a-f]{8})"
_RE_PARAMS = re.compile(
    rf"TWIN-PARAMS scratch={_HEX} csid={_HEX} sram_start={_HEX} sram_end={_HEX} marker={_HEX}"
)
_RE_STATIC = re.compile(rf"TWIN unit=(\w+) d1={_HEX} a={_HEX} d2={_HEX}\n")
_RE_SRAM = re.compile(rf"TWIN unit=(\w+) d1={_HEX} a={_HEX}\n")
_RE_WR = re.compile(rf"TWIN-WR alias={_HEX} direct={_HEX}")


def _alias(direct: int) -> int:
    return direct + _ALIAS_DELTA


def _word_fields(addr: int) -> tuple[int, int]:
    """(field mask, RDL reset) of the low 32 bits of the register at ``addr``.

    A 32-bit CPU load of a 64-bit register returns its bits [31:0]. A field with
    no RDL reset contributes 0 to the reset; the leaf grades a reset only for AES
    ``CTRL_SHADOWED``, whose fields all declare one.
    """
    _width, fields = register_fields(addr)
    mask = 0
    reset = 0
    for f in fields:
        if f.lsb >= 32:
            continue
        m = f.mask & 0xFFFF_FFFF
        mask |= m
        if f.reset is not None:
            reset |= (f.reset << f.lsb) & m
    return mask, reset


@dataclass(frozen=True)
class SepAliasTwinCfg:
    """Seeded static values, SRAM values and marker of one run."""

    seed: int
    scratch: int
    csid: int
    sram_start: int
    sram_end: int
    marker: int

    @classmethod
    def from_seed(cls, seed: int) -> "SepAliasTwinCfg":
        # A pure function of the seed, so `--stage sim --seed N` replays a leaf.
        rng = SepSeededRng(seed)
        vals: list[int] = []
        while len(vals) < 5:
            # Non-zero and pairwise different: a write that lands on another
            # word, or not at all, then reads back a different value.
            v = rng.getrandbits(32)
            if v != 0 and v not in vals:
                vals.append(v)
        return cls(seed, *vals)

    def param_words(self) -> list[int]:
        return [_PARAM_MAGIC, self.scratch, self.csid, self.sram_start, self.sram_end, self.marker]


@pyuvm.test()
class sep_cpu_lsu_alias_window_twin_test(sep_base_test):
    """An alias read of each local unit class and SRAM edge word equals its direct twin."""

    build_env = False
    required_evidence = ("CHK-TWIN", "CHK-TWIN-WR")

    def build_phase(self) -> None:
        super().build_phase()
        self.sb = SepBootScoreboard("sb", self)

    def _stage_dtcm(self) -> str:
        cfg = SepAliasTwinCfg.from_seed(self.random_seed())
        patched = os.path.join(os.getcwd(), "sep_dtcm_alias_twin.hex")
        patch_param_block(_DTCM_HEX, patched, _PARAM_MAGIC, cfg.param_words())
        self.logger.info(
            "alias twin RANDCFG seed=%d scratch=0x%08x csid=0x%08x sram_start=0x%08x "
            "sram_end=0x%08x marker=0x%08x window_base=0x%08x",
            cfg.seed,
            cfg.scratch,
            cfg.csid,
            cfg.sram_start,
            cfg.sram_end,
            cfg.marker,
            _WINDOW_BASE,
        )
        self._cfg = cfg
        return patched

    async def _open_window(self) -> None:
        # The CPU is released; everything the firmware does from here is the
        # graded stimulus of this entry.
        open_graded_window(_TEST, self.logger)

    async def run_scenario(self) -> None:
        self.sb.expected_line = _BANNER
        dtcm = self._stage_dtcm()
        sram = SepFabricTap("PR-SRAM").start()
        try:
            await self.boot_firmware(
                self.sb,
                _ITCM_HEX,
                dtcm,
                rst_vec=_ICCM_BASE >> 1,
                max_run_cycles=_MAX_RUN_CYCLES,
                no_boot_cycles=_NO_BOOT_CYCLES,
                progress_every=_PROGRESS_EVERY,
                after_bring_up_hook=self._open_window,
            )
        finally:
            close_graded_window(self.logger)
            await sram.stop()

        # Grade the printed values first: a firmware that trapped part way still
        # names the first word whose alias read went wrong.
        console = self.sb.console_text()
        self._check_params(console)
        self._check_twin(console, sram)
        self._check_twin_wr(console)
        assert "TWIN-DONE" in console, "CHK-TWIN FAIL: firmware console has no TWIN-DONE line"
        assert self.sb.fw_done and self.sb.fw_pass, (
            "CHK-TWIN FAIL: the alias_twin_test firmware did not complete with PASS "
            f"(done={self.sb.fw_done} pass={self.sb.fw_pass})"
        )

    def _check_params(self, console: str) -> None:
        cfg = self._cfg
        m = _RE_PARAMS.search(console)
        assert m is not None, "CHK-TWIN FAIL: firmware console has no TWIN-PARAMS line"
        got = [int(x, 16) for x in m.groups()]
        want = cfg.param_words()[1:]
        assert got == want, (
            "CHK-TWIN FAIL: the firmware did not consume the patched parameter block "
            f"(printed {[hex(x) for x in got]}, patched {[hex(x) for x in want]}); "
            "the patch was inert or the image is stale"
        )

    def _check_twin(self, console: str, sram: SepFabricTap) -> None:
        cfg = self._cfg
        seeded = {"scratch": cfg.scratch, "spi_word": cfg.csid}
        static_lines = {m.group(1): m.groups()[1:] for m in _RE_STATIC.finditer(console)}
        srams = {m.group(1): m.groups()[1:] for m in _RE_SRAM.finditer(console)}

        for unit, (direct, writable) in _UNITS.items():
            assert unit in static_lines, f"CHK-TWIN FAIL: unit={unit} has no TWIN console line"
            d1, a, d2 = (int(x, 16) for x in static_lines[unit])
            mask, rdl_reset = _word_fields(direct)
            alias = _alias(direct)
            if writable:
                expect = seeded[unit]
                src = "seeded"
            elif unit == "aes_word":
                expect = rdl_reset
                src = "rdl_reset"
            else:
                # Read-only word with no graded value: the direct read is the
                # reference of the alias read.
                expect = d1
                src = "direct"
            cmp_d1 = field_compare(d1, expect, mask)
            cmp_a = field_compare(a, d1, mask)
            cmp_d2 = field_compare(d2, d1, mask)
            line = (
                f"unit={unit} direct=0x{direct:08x} alias=0x{alias:08x} value=0x{d1 & mask:08x} "
                f"field_mask=0x{mask:08x} rsvd=0x{cmp_d1.rsvd:x} "
                f"alias_rsvd=0x{cmp_a.rsvd:x} d2_rsvd=0x{cmp_d2.rsvd:x} expect_src={src} "
                f"expect=0x{expect & mask:08x} alias_value=0x{a & mask:08x} "
                f"direct2_value=0x{d2 & mask:08x}"
            )
            assert cmp_d1.ok, f"CHK-TWIN FAIL: {line} match=0 (direct read differs from expect)"
            assert cmp_a.ok, f"CHK-TWIN FAIL: {line} match=0 (alias read differs from direct)"
            assert cmp_d2.ok, f"CHK-TWIN FAIL: {line} match=0 (second direct read differs)"
            self.logger.info("CHK-TWIN PASS: %s match=1", line)

        # SRAM words: the console values, then the PR-SRAM address compare. The
        # firmware makes exactly two SRAM writes (start word, then last word),
        # then reads start direct, start alias, last direct, last alias, in
        # program order. A partial-word write may add a read-modify-write read
        # before its write, so only the reads after the last write are graded.
        reqs = sram.since(0, "req")
        for b in reqs:
            self.logger.info("PR-SRAM req %s", b.fmt())
        # The write data and strobe of a read request carry no contract, so only
        # the address and the direction must be known.
        unknown = [b for b in reqs if b.addr is None or b.we is None]
        assert not unknown, "CHK-TWIN FAIL: a PR-SRAM address or direction is X or Z: " + "; ".join(
            b.fmt() for b in unknown
        )
        writes = [b for b in reqs if b.we == 1]
        assert len(writes) >= 2, (
            f"CHK-TWIN FAIL: PR-SRAM shows {len(writes)} SRAM write request(s), expected the two "
            "seed writes of the start and last words"
        )
        w_start, w_end = writes[-2], writes[-1]
        reads = [b for b in reqs if b.seq > w_end.seq and b.we == 0]
        assert len(reads) == 4, (
            f"CHK-TWIN FAIL: PR-SRAM shows {len(reads)} SRAM read request(s) after the seed "
            "writes, expected 4 (start direct, start alias, last direct, last alias): "
            + "; ".join(b.fmt() for b in reads)
        )
        rsps = [b for b in sram.since(0, "rsp") if b.seq > w_end.seq]
        assert rsps and all(b.rdata is not None for b in rsps), (
            "CHK-TWIN FAIL: PR-SRAM read data after the seed writes is missing or X/Z: "
            + "; ".join(b.fmt() for b in rsps)
        )
        pairs = {
            "sram_start": (w_start, reads[0], reads[1]),
            "sram_end": (w_end, reads[2], reads[3]),
        }
        seeded_sram = {"sram_start": cfg.sram_start, "sram_end": cfg.sram_end}
        assert w_start.addr != w_end.addr, (
            f"CHK-TWIN FAIL: the start and last SRAM words wrote one address 0x{w_start.addr:x}"
        )
        for unit, direct in _SRAM_WORDS.items():
            assert unit in srams, f"CHK-TWIN FAIL: unit={unit} has no TWIN console line"
            d1, a = (int(x, 16) for x in srams[unit])
            w, rd_direct, rd_alias = pairs[unit]
            alias = _alias(direct)
            expect = seeded_sram[unit]
            line = (
                f"unit={unit} direct=0x{direct:08x} alias=0x{alias:08x} value=0x{d1:08x} "
                f"field_mask=0xffffffff rsvd=0x0 expect=0x{expect:08x} alias_value=0x{a:08x} "
                f"sram_direct_seen=0x{rd_direct.addr:x} sram_alias_seen=0x{rd_alias.addr:x} "
                f"sram_write_seen=0x{w.addr:x}"
            )
            assert d1 == expect, f"CHK-TWIN FAIL: {line} match=0 (direct read differs from seeded)"
            assert a == d1, f"CHK-TWIN FAIL: {line} match=0 (alias read differs from direct)"
            assert rd_direct.addr == rd_alias.addr == w.addr, (
                f"CHK-TWIN FAIL: {line} match=0 (PR-SRAM direct and alias addresses differ, or "
                "differ from the seed write of the word)"
            )
            self.logger.info("CHK-TWIN PASS: %s match=1", line)

    def _check_twin_wr(self, console: str) -> None:
        cfg = self._cfg
        m = _RE_WR.search(console)
        assert m is not None, "CHK-TWIN-WR FAIL: firmware console has no TWIN-WR line"
        alias, back = (int(x, 16) for x in m.groups())
        direct = _UNITS["scratch"][0]
        mask, _ = _word_fields(direct)
        want_alias = _alias(direct)
        assert alias == want_alias, (
            f"CHK-TWIN-WR FAIL: firmware wrote alias=0x{alias:08x}, model alias=0x{want_alias:08x}"
        )
        cmp = field_compare(back, cfg.marker, mask)
        line = (
            f"alias=0x{alias:08x} marker=0x{cfg.marker:08x} direct_read=0x{back:08x} "
            f"seeded=0x{cfg.scratch:08x} field_mask=0x{mask:08x} rsvd=0x{cmp.rsvd:x}"
        )
        assert cmp.ok, f"CHK-TWIN-WR FAIL: {line}"
        self.logger.info("CHK-TWIN-WR PASS: %s", line)
