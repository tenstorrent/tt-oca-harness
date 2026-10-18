# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Used bits of nine narrow fuse registers at drawn edge values; no shadow word holds the JTAG ID.

The used-bit ranges of ``LC_STATE``, ``SBOOT_DIS``, ``TRANSIENT_RMA_EN``,
``CHIPLET_PUBK_REVOKE``, ``STATUS_RPT``, ``ROM_CTL``, ``SYSCLK_FREQ_MHZ``,
``REQUIRED_SIGNERS`` and ``REQUIRED_ALGS`` read back as staged, at edge values that the
seed draws. A drawn non-zero ``jtag_id_i[31:1]`` enters no shadow word: the JTAG ID is
not in the fuse map and is a top-level port.

Sources: ``hw/sys/sep/doc/otp_fuse_controller.adoc`` (section Fuse Fields, field table
and the text after it); ``hw/ip/efuse/doc/interface.adoc`` (256 words of 32 bits);
``hw/sys/sep/regs/gen/adoc/blocks/sep_efuse_map.adoc`` (address map, field tables);
``hw/sys/sep/doc/port_table.adoc`` (port ``jtag_id_i[31:1]``).

Image: prestaged from ``plan(test, seed)`` of ``env/sep_efuse_plan.py`` (narrow values
by class, vector choice, ``LOCKS`` and ``LOCKS_SPARE`` write-lock sets, filter-legal
pair, adjacent-equal redraws); the same plan gives the drawn ``jtag_id_i``. The leaf
makes no program, no shadow write and no lock write.

The offset table comes from the address column of ``sep_efuse_map.adoc`` and the widths
from its field tables; a table that does not tile words 0 to 255 with 43 registers
fails the leaf before any DUT access (``SETUP FAIL reason=table_tile``).

Checkers:
  CHK-FIELD-USED  the used bits of each graded narrow register equal the staged value
                  in a 32-bit read at its table offset; reserved bits are logged.
  CHK-JTAGID      no sensed shadow word (probe and frontdoor) equals a 32-bit form of
                  the drawn ID; the same compare finds all 256 sensed words equal to
                  the staged words. Hook control: the DUT port ``jtag_id_i`` equals the
                  drawn ID (``CHK-HOOK FAIL`` otherwise).

Log-only: the word-by-word compare of the 43 registers (``OBS-FIELD LOG``).
"""

from __future__ import annotations

import re
from pathlib import Path

import cocotb
import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_chk_log import SepChkLog
from env.sep_efuse_image import SHADOW_BASE
from env.sep_efuse_plan import T_FIELD_LAYOUT, plan
from env.sep_efuse_test_lib import SepEfuseFd, hook_fail, log_line, probe_words
from env.sep_fcov_gate import close_graded_window, open_graded_window
from sep_base_test import sep_base_test

TEST = T_FIELD_LAYOUT

_MAP_ADOC = (
    Path(__file__).resolve().parents[4] / "regs" / "gen" / "adoc" / "blocks" / "sep_efuse_map.adoc"
)
_N_REGS = 43
_N_WORDS = 256
_WORD = 0xFFFF_FFFF

# Used masks of the 32-bit registers (contract procedure step 6).
_USED_MASK = {
    "LOCKS_SPARE": 0x0003_FFFF,
    "LC_STATE": 0x0000_00FF,
    "SBOOT_DIS": 0x1,
    "TRANSIENT_RMA_EN": 0x1,
    "CHIPLET_PUBK_REVOKE": 0x03FF_FFFF,
    "STATUS_RPT": 0x3,
    "REQUIRED_SIGNERS": 0x3,
    "ROM_CTL": 0x3F,
    "SYSCLK_FREQ_MHZ": 0x7FF,
    "REQUIRED_ALGS": 0x333,
}
_GRADED = (
    "LC_STATE",
    "SBOOT_DIS",
    "TRANSIENT_RMA_EN",
    "CHIPLET_PUBK_REVOKE",
    "STATUS_RPT",
    "ROM_CTL",
    "SYSCLK_FREQ_MHZ",
    "REQUIRED_SIGNERS",
    "REQUIRED_ALGS",
)

_ROW_MAP = re.compile(r"^\|\s*(0x[0-9A-Fa-f]+)\s*\|\s*<<[^,>]*,([A-Za-z0-9_]+)>>")
_ROW_SECTION = re.compile(r"^===\s+([A-Za-z0-9_]+)\s*$")
_ROW_BITS = re.compile(r"^\|\s*(\d+)(?::(\d+))?\s*\|")


def parse_offset_table(text: str) -> list[tuple[str, int, int]]:
    """(name, byte offset, words) of every register of the address map, in map order.

    Offsets come from the address column of the address map; widths from the highest
    bit of each register's field table (rounded up to 32-bit words).
    """
    offsets: list[tuple[str, int]] = []
    in_map = False
    hi_bit: dict[str, int] = {}
    section: str | None = None
    for line in text.splitlines():
        if line.startswith("| Address | Name"):
            in_map = True
            continue
        if in_map:
            if line.startswith("|==="):
                in_map = False
                continue
            m = _ROW_MAP.match(line)
            if m:
                offsets.append((m.group(2).upper(), int(m.group(1), 16)))
            continue
        m = _ROW_SECTION.match(line)
        if m:
            section = m.group(1).upper()
            continue
        if section is not None:
            m = _ROW_BITS.match(line)
            if m:
                hi_bit[section] = max(hi_bit.get(section, -1), int(m.group(1)))
    return [(n, off, (hi_bit[n] + 32) // 32 if n in hi_bit else 0) for n, off in offsets]


def table_tiles(table: list[tuple[str, int, int]]) -> bool:
    """43 rows that cover words 0..255 with no gap and no overlap."""
    if len(table) != _N_REGS:
        return False
    nxt = 0
    for _n, off, words in sorted(table, key=lambda r: r[1]):
        if off % 4 or off // 4 != nxt or words <= 0:
            return False
        nxt += words
    return nxt == _N_WORDS


def _words_int(words: list[int]) -> int:
    return sum((w & _WORD) << (32 * k) for k, w in enumerate(words))


@pyuvm.test()
class sep_efuse_field_layout_rand_test(sep_base_test):
    """Narrow-field used bits at drawn edge values; the JTAG ID is in no shadow word."""

    required_evidence = ("CHK-FIELD-USED", "CHK-JTAGID")

    async def _rd(self, addr: int) -> tuple[int, bool]:
        """32-bit frontdoor read whose response the leaf grades: (rdata, OKAY)."""
        seq = await self.fd.access(SepAxiOp.READ, addr, ungraded_read=True)
        return seq.rdata & _WORD, bool(seq.resp_ok)

    def _hook_ok(self, port: int, where: str) -> bool:
        """Hook control of the ``jtag_id_i`` drive; a miss ends the leaf (CHK-HOOK FAIL)."""
        if port != self.jtag_id:
            hook_fail(self.chk, where=where, port=f"0x{port:08x}", drawn=f"0x{self.jtag_id:08x}")
        self.chk.ctrl("HOOK", True, where=where, port=f"0x{port:08x}")
        return True

    def _port(self) -> int:
        return self.rd_known(cocotb.top.jtag_id_probe_o)

    async def run_scenario(self) -> None:
        dut = cocotb.top
        seed = self.random_seed()

        # Step 1: offset table from the address map; fails before any DUT access.
        table = parse_offset_table(_MAP_ADOC.read_text())
        if not table_tiles(table):
            self.logger.error(
                "SETUP FAIL seed=%d reason=table_tile rows=%d table=%s", seed, len(table), table
            )
            raise AssertionError(f"SETUP FAIL seed={seed} reason=table_tile")

        # Steps 2-4: the plan (prestaged image, drawn classes, jtag_id_i).
        p = plan(TEST, seed)
        for line in p.log_lines():
            self.logger.info("%s", line)
        self.chk = SepChkLog(self, TEST, seed)
        self.fd = SepEfuseFd(self)
        if p.setup_fail:
            raise AssertionError(f"SETUP FAIL seed={seed} reason={p.setup_fail}")
        staged = list(p.image.words)
        self.jtag_id = int(p.leg["jtag_id"])
        classes = p.leg["classes"]
        close_graded_window(self.logger)

        # Step 5: preload, jtag_id_i from reset release on, strap 0, cold reset, sense.
        # The window spans the sense-done rise (field value and JTAG ID class points).
        self.write_efuse_image(p.image)
        dut.jtag_id_i.value = self.jtag_id
        open_graded_window(TEST, self.logger)
        await self.bring_up_no_cpu()
        close_graded_window(self.logger)
        self.suppress_host_axi_transaction_info()
        hook = self._hook_ok(self._port(), "sense_done")

        # Step 6: every register word by word at its table offset (control, logged).
        fd_words = [0] * _N_WORDS
        for name, off, nw in table:
            got = []
            for k in range(nw):
                v, _ok = await self._rd(SHADOW_BASE + off + 4 * k)
                got.append(v)
                fd_words[off // 4 + k] = v
            exp = staged[off // 4 : off // 4 + nw]
            mask = _USED_MASK.get(name, _WORD) if nw == 1 else (1 << (32 * nw)) - 1
            log_line(
                self.logger,
                "OBS-FIELD",
                seed,
                field=name,
                off=f"0x{off:x}",
                words=nw,
                exp=f"0x{_words_int(exp) & mask:x}",
                got=f"0x{_words_int(got) & mask:x}",
            )
        hook = self._hook_ok(self._port(), "field_reads") and hook

        # Step 7: the nine graded narrow registers, one 32-bit read each.
        offs = {n: off for n, off, _nw in table}
        open_graded_window(TEST, self.logger)
        n_lines = 0
        for name in _GRADED:
            off = offs[name]
            mask = _USED_MASK[name]
            got, ok = await self._rd(SHADOW_BASE + off)
            exp = staged[off // 4] & mask
            if name == "LC_STATE":
                cls = "TEST_DEV"
            elif name == "TRANSIENT_RMA_EN":
                cls = f"v{staged[off // 4] & mask}"
            else:
                c = classes[name]
                cls = ".".join(str(x) for x in c) if isinstance(c, (tuple, list)) else str(c)
            self.chk.ok(
                "FIELD-USED",
                ok and (got & mask) == exp,
                field=name,
                **{"class": cls},
                used_mask=f"0x{mask:x}",
                exp=f"0x{exp:x}",
                got=f"0x{got & mask:x}",
                rsvd_got=f"0x{got & ~mask & _WORD:x}",
                resp_ok=int(ok),
            )
            n_lines += 1
        close_graded_window(self.logger)
        if n_lines != len(_GRADED):
            self.chk.ok("FIELD-USED", False, lines=n_lines, need=len(_GRADED))

        # Step 8: the port, and the 256 sensed words against the three ID forms.
        hook = self._hook_ok(self._port(), "probe_sample") and hook
        sensed = probe_words(self, dut.efuse_shadow_probe_o, _N_WORDS)
        f0 = (self.jtag_id << 1) & _WORD
        f1 = ((self.jtag_id << 1) | 1) & _WORD
        fz = self.jtag_id & 0x7FFF_FFFF
        forms = {f0, f1, fz}
        equal = sum(int(w in forms) for w in sensed)
        equal_fd = sum(int(w in forms) for w in fd_words)
        staged_equal = sum(int(s == g) for s, g in zip(sensed, staged))
        trap_ok = not any(w in forms for w in staged) and self.jtag_id != 0
        self.chk.ok(
            "JTAGID",
            hook and trap_ok and equal == 0 and equal_fd == 0 and staged_equal == _N_WORDS,
            id=f"0x{self.jtag_id:08x}",
            port=f"0x{self._port():08x}",
            f0=f"0x{f0:08x}",
            f1=f"0x{f1:08x}",
            fz=f"0x{fz:08x}",
            words_checked=_N_WORDS,
            equal=equal,
            equal_frontdoor=equal_fd,
            staged_equal=staged_equal,
        )
        self.chk.finish()
