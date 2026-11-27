# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary boot with an invalid status ring: no write leaves the window and the boot continues.

rom.adoc, Status Reporting, Ring-Buffer Semantics:

    [SEP-ROM-STAT-010] The producer shall bounds-check the ring structure and every entry write
    against the SMC SRAM window, and shall degrade gracefully on an invalid ring (report
    `STATUS_REPORTING_INVALID` on the scratch channel; never write outside the window; never
    disable reporting on a possibly-transient error).

status-errors.adoc, Status ring:

    Before an entry write, BL0 validates the entry count, head, tail, remaining capacity, and
    destination address. An invalid state reports `SEP_MSG_STATUS_REPORTING_INVALID` through
    `cold_scratch[1]` and does not write the entry.

smc-coordination.adoc, Status-buffer handoff:

    It reads the ring-buffer offset from scratch register 11, checks that the ring header lies
    within SMC SRAM, and then publishes non-debug status through that ring.

    An invalid offset leaves the scratch-register status channel operational and prevents BL0
    from writing through an untrusted ring pointer.

rom.adoc supporting facts: SMC SRAM is at SMC window offset `0x60000` and is 1 MiB; scratch[n] is
at SMC window offset `0x39080 + 8·n`, scratch[11] `STATUS_BUFFER_ADDR` the ring offset; the
generated code registry gives `SEP_MSG_STATUS_REPORTING_INVALID` the value `0x79`. The SEP ROM
docs name head, tail and the entry count but give no layout; the leaf takes it from the SMC ROM
docs (hw/sys/smc/bootrom/prod/doc/status-coordination.adoc, Ring buffers, and
memory-security.adoc): `head`, `tail` and `num_entries` as three 32-bit fields, then the 32-bit
entries. That a header with head >= num_entries is invalid is an inference from status-errors.adoc
validating the head against the entry count; no SEP ROM doc states the bound.

`+sep_rom_ring_case` selects the ring the leaf publishes:

* `straddle`: scratch[11] is `0x000FFFFC`, so the 12-byte header crosses the window end.
* `bad_header`: the header sits at offset `0x000F0000`, outside the packed SMC image, and
  declares 16 entries with head 16 and tail 0, so `entries[head]` lies inside the window but
  past the declared ring.

* CHK-RING-NO-WRITE-OUTSIDE: up to the hand-off, every PR-SMC write lies inside the SMC SRAM
  window or the SMC scratch block. For `straddle` no write touches the header; for `bad_header`
  every write into the window lies inside the declared ring.
* CHK-INVALID-REPORTED: after the ROM reads scratch[11] (`bad_header`: after its first header
  read), `cold_scratch[1]` carries BL0 `STATUS_REPORTING_INVALID`. The type byte is logged, not
  graded, since the spec names no type for this report.
* CHK-BOOT-CONTINUES: the invalid-ring report precedes `MANIFEST_OK`, the boot reaches BL1 and
  the verdict is PASS (the base's secondary-boot checks all hold).

Not covered: "never disable reporting on a possibly-transient error" (the leaf never makes the
ring valid again, so the repeated reports are logged only); an entry write whose destination
crosses the window end with head and entry count otherwise valid; the remaining-capacity check.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import SepRomObserver
from rom_fw.sep_firmware_secondary_chiplet_bootcode_test import (
    sep_firmware_secondary_chiplet_bootcode_test as _Base,
)
from rom_fw.sep_secondary_chiplet_base import MANIFEST_OK, SMC_SRAM_BASE

_WORD = 0xFFFF_FFFF
_SCRATCH0 = 0x4000_0000 + 0x39080
_SCRATCH_END = _SCRATCH0 + 8 * 16
_SCRATCH7 = _SCRATCH0 + 8 * 7
_SCRATCH11 = _SCRATCH0 + 8 * 11
_SMC_SRAM_END = SMC_SRAM_BASE + (1 << 20)
_HEADER_BYTES = 12
_ENTRY_BYTES = 4
_INVALID_ID_CODE = (1 << 16) | 0x0079
_ID_CODE_MASK = 0x00FF_FFFF
_BL1_ENTRY = 0xC000_0000

# offset, (head, tail, num_entries) or None when the leaf leaves the header bytes alone.
_CASES = {
    "straddle": (0x000F_FFFC, None),
    "bad_header": (0x000F_0000, (16, 0, 16)),
}


def _span(beat) -> tuple[int, int]:
    return beat.addr, beat.addr + ((beat.len or 0) + 1) * (1 << (beat.size or 0))


def _inside(beat, lo: int, hi: int) -> bool:
    if beat.addr is None:
        return False
    a, e = _span(beat)
    return lo <= a and e <= hi


def _overlaps(beat, lo: int, hi: int) -> bool:
    a, e = _span(beat)
    return a < hi and lo < e


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


def _fmt(beat) -> str:
    return f"{beat.t_ps}:{_hex(beat.addr)}/len{beat.len}/size{beat.size}"


@pyuvm.test()
class sep_rom_status_ring_bounds_test(_Base):
    required_evidence = (
        "CHK-RING-NO-WRITE-OUTSIDE",
        "CHK-INVALID-REPORTED",
        "CHK-BOOT-CONTINUES",
    )

    @property
    def case(self) -> str:
        arg = cocotb.plusargs.get("sep_rom_ring_case")
        assert arg in _CASES, (
            f"+sep_rom_ring_case={arg!r}; the testlist entry must name one of {sorted(_CASES)}"
        )
        return str(arg)

    @property
    def ring(self) -> int:
        return (SMC_SRAM_BASE + _CASES[self.case][0]) & _WORD

    def prepare_smc_mem(self) -> None:
        super().prepare_smc_mem()
        mem = self.cfg.smc_mem
        assert mem is not None, (
            "the rom_boot target did not bind its SMC responder; run this leaf on the rom_boot "
            "target, which sets cfg.smc_mem"
        )
        offset, header = _CASES[self.case]
        mem.write32(_SCRATCH11, offset)
        if header is not None:
            for i, word in enumerate(header):
                mem.write32(self.ring + 4 * i, word)
            for i in range(header[2]):
                mem.write32(self.ring + _HEADER_BYTES + _ENTRY_BYTES * i, 0)

    async def _sample_reads(self) -> None:
        """Snapshot the responder words each scratch[11] or header read returns."""
        mem = self.cfg.smc_mem
        clk = cocotb.top.clk_i
        i = 0
        while True:
            await RisingEdge(clk)
            beats = self.smc.beats
            for b in beats[i:]:
                if b.ch != "ar" or b.addr is None:
                    continue
                if b.addr & ~7 == _SCRATCH11:
                    self.s11_reads.append((b.t_ps, mem.read32(_SCRATCH11)))
                elif _overlaps(b, self.ring, self.ring + _HEADER_BYTES):
                    words = tuple(mem.read32(self.ring + 4 * k) for k in range(3))
                    self.header_reads.append((b.t_ps, words))
            i = len(beats)

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.s11_reads: list[tuple[int, int]] = []
        self.header_reads: list[tuple[int, tuple[int, int, int]]] = []
        # The observer and the tap start before reset release so the first SMC access is recorded.
        self.obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False).start()
        self.smc = SepFabricTap("PR-SMC").start()
        mark = self.smc.mark()
        sampler = cocotb.start_soon(self._sample_reads())
        base_err = None
        try:
            await super().run_scenario()
        except AssertionError as err:
            base_err = err
        sampler.cancel()
        await self.obs.stop()
        await self.smc.stop()
        self._grade(self.smc.since(mark, "ar"), self.smc.since(mark, "aw"), base_err)
        self.chk.finish()

    def _grade(self, ar: list, aw: list, base_err) -> None:
        chk, obs = self.chk, self.obs
        offset, header = _CASES[self.case]
        ring = self.ring

        s7 = [b for b in aw if b.addr is not None and b.addr & ~7 == _SCRATCH7]
        unknown = sum(1 for b in ar + aw if b.addr is None)
        chk.ctrl(
            "SMC-AW-LIVE",
            bool(s7) and not unknown,
            aw=len(aw),
            ar=len(ar),
            unknown=unknown,
            scratch7_writes=len(s7),
        )

        t11, s11 = self.s11_reads[0] if self.s11_reads else (None, None)
        h_t, h_words = self.header_reads[0] if self.header_reads else (None, None)
        if t11 is not None:
            h_t, h_words = next(((t, w) for t, w in self.header_reads if t > t11), (None, None))
        echo = f"ring buffer address: 0x{ring:08x}"
        case_ok = s11 == offset and all(v == offset for _, v in self.s11_reads)
        if header is not None:
            head, tail, num = header
            echoes = (
                echo,
                f"ring buffer head: 0x{head:08x}",
                f"ring buffer tail: 0x{tail:08x}",
                f"ring buffer num_entries: 0x{num:08x}",
            )
            case_ok = (
                case_ok
                and h_words == header
                and all(obs.line_t(e) is not None and obs.line_t(e) > t11 for e in echoes)
            )
        chk.ctrl(
            "RING-CASE",
            case_ok,
            case=self.case,
            scratch11_reads=len(self.s11_reads),
            scratch11_at_first_read=_hex(s11),
            first_read_ps=t11 or -1,
            published=_hex(offset),
            header_at_first_read=[_hex(w) for w in h_words] if h_words else "none",
            header_read_ps=h_t or -1,
            console=echo if obs.line_t(echo) is not None else "absent",
        )

        handoff = obs.post_mret.t_ps if obs.post_mret is not None else None
        rom_aw = [b for b in aw if handoff is None or b.t_ps < handoff]

        def allowed(b) -> bool:
            if _inside(b, _SCRATCH0, _SCRATCH_END):
                return True
            if not _inside(b, SMC_SRAM_BASE, _SMC_SRAM_END):
                return False
            if header is None:
                return not _overlaps(b, ring, ring + _HEADER_BYTES)
            return _inside(b, ring, ring + _HEADER_BYTES + _ENTRY_BYTES * header[2])

        bad = [b for b in rom_aw if not allowed(b)]
        in_window = [b for b in rom_aw if _inside(b, SMC_SRAM_BASE, _SMC_SRAM_END)]
        chk.ok(
            "RING-NO-WRITE-OUTSIDE",
            not bad and handoff is not None,
            case=self.case,
            aw_to_handoff=len(rom_aw),
            handoff_ps=handoff or -1,
            bad=[_fmt(b) for b in bad[:8]],
            n_bad=len(bad),
            sram_writes=[_fmt(b) for b in in_window[:8]],
        )
        chk.obs(
            "AW-AFTER-HANDOFF",
            writes=[_fmt(b) for b in aw if handoff is not None and b.t_ps >= handoff][:8],
        )

        lo = h_t if header is not None else t11
        invalid = [
            (t, w)
            for t, w in obs.status
            if lo is not None and t > lo and w & _ID_CODE_MASK == _INVALID_ID_CODE
        ]
        chk.ok(
            "INVALID-REPORTED",
            bool(invalid),
            case=self.case,
            after_ps=lo or -1,
            first_ps=invalid[0][0] if invalid else -1,
            n_records=len(invalid),
        )
        chk.obs("INVALID-TYPE", types=sorted({f"0x{w >> 24:02x}" for _, w in invalid}))

        ok_t = obs.line_t(MANIFEST_OK)
        chk.ok(
            "BOOT-CONTINUES",
            base_err is None
            and bool(invalid)
            and ok_t is not None
            and invalid[0][0] < ok_t
            and obs.verdict_pass() is True
            and obs.post_mret is not None
            and obs.post_mret.pc == _BL1_ENTRY,
            base_error=str(base_err or "none"),
            invalid_ps=invalid[0][0] if invalid else -1,
            manifest_ok_ps=ok_t or -1,
            verdict=_hex(obs.verdict[-1][1] if obs.verdict else None),
            post_mret_pc=_hex(obs.post_mret.pc if obs.post_mret else None),
        )

        if header is not None:
            mem = self.cfg.smc_mem
            words = [mem.read32(ring + 4 * k) for k in range(3 + header[2])]
            chk.obs("RING-MEM-AT-END", words=[_hex(w) for w in words])
