# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary boot: an invalid or out-of-window manifest offset fails the single slot.

rom.adoc, SMC Synchronization, Manifest Staging Hand-shake (Recovery / Secondary):

    [SEP-ROM-SMC-050] The ROM shall reject a manifest offset of `0xFFFFFFFF` and shall
    bounds-check the staged manifest and any payload region announced via scratch[13]/[14]
    against the 1 MiB SMC SRAM window before reading.

    The manifest is copied by secure DMA from `SMC_SRAM_base + scratch[8]` into SEP SRAM and
    from then on follows the same validation path as a SPI-loaded manifest

smc-coordination.adoc, Manifest handoff:

    The manifest header read is not checked. BL0 adds the offset from scratch register 8 to
    the SMC SRAM base and issues the header transfer without a range or overflow test, so
    keeping that offset inside the window is SMC's obligation. A header read from outside the
    window is caught only afterwards, by the manifest identifier, version, length, and hash
    checks on the bytes it returned.

rom.adoc, Failure Convergence:

    [SEP-ROM-RETRY-050] Every fatal path in the ROM shall converge in a single failure routine
    (`rom_err_fail`) that (a) records the error code in `bl0_state.error_code`, (b) writes the
    encoded `ERROR` status to `cold_scratch[1]`, (c) writes the FAIL verdict (`0xDEADBEEF`) to
    `cold_scratch[0]`, and (d) parks in `wfi`.

rom.adoc supporting facts: SMC SRAM is at SMC window offset `0x60000` and is 1 MiB; scratch[n]
is at SMC window offset `0x39080 + 8·n` (scratch[8] the manifest offset, scratch[11] the ring
offset); the manifest is 4096 B; secondary boot is a single attempt with no bank retry; the
stage trace names `MANIFEST_LOAD_FAILED` when all slots are exhausted and `MANIFEST_VALIDATED`
on success. The stage trace gives no type for `MANIFEST_LOAD_FAILED`; ERROR is this test's
expectation until the spec states one.

The testlist entry publishes the offset through `+sep_smc_scratch8`.

The two documents disagree on whether a read may precede the window check, so that part is
logged, not graded. Both require the slot to fail when the bytes at the offset are not a valid
manifest, which holds for every entry here.

* CHK-SLOT-REFUSED: the slot fails and the boot halts. Between the ROM's post-wait scratch[8]
  read and the verdict there is an ERROR `MANIFEST_LOAD_FAILED`; there is no
  `MANIFEST_VALIDATED`; the verdict is `0xDEADBEEF`; no status or console record follows it;
  no `MANIFEST_OK` or `BL1_JUMP=` console line appears.
* OBS-SMC-SRAM-READ: every PR-SMC read from the first scratch[8] read on that overlaps the SMC
  SRAM window or the 4096 B manifest at `SMC_SRAM_base + offset` (32-bit wrap). Single reads
  inside the status-ring header beats (`SMC_SRAM_base + scratch[11]`, head, tail and entry
  count) are left out, since every ring insert reads them. For `0xFFFFFFFF` the manifest range
  overlaps those beats, so a manifest read made only of single reads inside them would be left
  out too; its first beat, below the SMC SRAM base, would not.

Partial coverage: the `0xFFFFFFFF` entry shows a failed slot with no read, not a dedicated
sentinel check (its source is also not 8-byte aligned, and the alignment check refuses it). Not
covered: the payload region announced via scratch[13]/[14]; `bl0_state.error_code`; RETRY-050
(b), since with the bench's invalid status ring every status is followed by `0x0F010079`; the
recovery boot mode; offsets other than the one each testlist entry publishes; which check or
error code refuses the offset (the spec defines no code for SMC-050), so the statuses are logged
as OBS-REFUSAL.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from cocotb.utils import get_sim_time
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver
from rom_fw.sep_secondary_chiplet_base import (
    ALL_FAILED,
    MANIFEST_OK,
    SMC_MANIFEST_OFF_INVALID,
    SMC_SRAM_BASE,
    sep_secondary_chiplet_base,
)

_WORD = 0xFFFF_FFFF
_SMC_WINDOW = 0x4000_0000
_SCRATCH8 = _SMC_WINDOW + 0x39080 + 8 * 8
_SCRATCH9 = _SMC_WINDOW + 0x39080 + 8 * 9
_SCRATCH11 = _SMC_WINDOW + 0x39080 + 8 * 11
_SMC_SRAM_SIZE = 1 << 20
_MANIFEST_BYTES = 0x1000
# head, tail and entry count, the ring structure the producer validates before every insert.
_RING_HEADER_BYTES = 12
_BEAT_BYTES = 8
_STATUS_ID_CODE = 0x00FF_FFFF
_BL0 = 1 << 16
_WAIT_ID_CODE = _BL0 | 0x007D
_VALIDATED_ID_CODE = _BL0 | 0x0053
_INFO_EXT = 0x81
_LOAD_FAILED_ERROR = (0x0F << 24) | _BL0 | 0x0213
_FAIL_VERDICT = 0xDEAD_BEEF
_HALT_CYCLES = 20_000


def _slot(beat) -> int | None:
    return None if beat.addr is None else beat.addr & ~7


def _span(beat) -> tuple[int, int]:
    return beat.addr, beat.addr + ((beat.len or 0) + 1) * (1 << (beat.size or 0))


def _overlaps(beat, lo: int, hi: int) -> bool:
    a, b = _span(beat)
    return a < hi and lo < b


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


@pyuvm.test()
class sep_rom_smc_manifest_offset_invalid_test(sep_secondary_chiplet_base):
    required_evidence = ("CHK-SLOT-REFUSED",)

    expect_boot = False
    # The spec names no code for this refusal; the halt is graded on the failed-load ERROR status.
    expected_error = _LOAD_FAILED_ERROR

    @property
    def manifest_offset(self) -> int:
        arg = cocotb.plusargs.get("sep_smc_scratch8")
        assert isinstance(arg, str), (
            "this leaf needs +sep_smc_scratch8=<hex offset> in its testlist entry; it names the "
            "offset the ROM must refuse"
        )
        return int(arg, 16) & _WORD

    @property
    def src_addr(self) -> int:
        return (SMC_SRAM_BASE + self.manifest_offset) & _WORD

    # The probe prints STATUS_BUF_OFF= after MANIFEST_OFF= and before its address-or-invalid line.
    @property
    def published_addr_echo(self) -> str:
        return "STATUS_BUF_OFF="

    @property
    def src_echo(self) -> str:
        return f"MANIFEST_SRC=0x{self.src_addr:08x}"

    @property
    def _forbidden(self) -> tuple[str, ...]:
        return tuple(m for m in super()._forbidden if m != SMC_MANIFEST_OFF_INVALID)

    def check_smc_image(self) -> None:
        """The offset lies outside the packed image by design, so there is no word at it to compare."""

    def prepare_smc_mem(self) -> None:
        assert self.cfg.smc_mem is not None, (
            "the rom_boot target did not bind its SMC responder; run this leaf on the rom_boot "
            "target, which sets cfg.smc_mem"
        )

    def check_outcome(self, console, status_seq, fw_done, fw_pass) -> None:
        """The leaf grades the outcome from its own observer after the base returns."""

    async def _clock_period(self) -> None:
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        t0 = int(get_sim_time("ps"))
        await RisingEdge(clk)
        self.clk_ps = int(get_sim_time("ps")) - t0

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.clk_ps = None
        # The observer and the tap start before reset release so the first SMC access is recorded.
        self.obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False).start()
        self.smc = SepFabricTap("PR-SMC").start()
        mark = self.smc.mark()
        cocotb.start_soon(self._clock_period())
        base_err = None
        try:
            await super().run_scenario()
        except AssertionError as err:
            base_err = err
        await self.obs.stop()
        end_ps = int(get_sim_time("ps"))
        await self.smc.stop()
        self._grade(self.smc.since(mark, "ar"), self.smc.since(mark, "aw"), end_ps)
        self.chk.ctrl("SECONDARY-PATH", base_err is None, base_error=str(base_err or "none"))
        self.chk.finish()

    def _grade(self, ar: list, aw: list, end_ps: int) -> None:
        chk, obs = self.chk, self.obs
        off = f"0x{self.manifest_offset:08x}"
        clk_ps = self.clk_ps or 1
        known = [b for b in ar if b.addr is not None]
        unknown = len(ar) - len(known)
        s8 = [b.t_ps for b in known if _slot(b) == _SCRATCH8]
        wait_t = next((t for t, w in obs.status if w & _STATUS_ID_CODE == _WAIT_ID_CODE), None)
        lo = None if wait_t is None else wait_t - STORE_LAG_MAX_CYCLES * clk_ps
        consume = next((t for t in s8 if lo is not None and t >= lo), None)
        first = s8[0] if s8 else None
        polls = [
            b
            for b in known
            if _slot(b) == _SCRATCH9 and lo is not None and lo <= b.t_ps < (consume or end_ps)
        ]
        after = [b for b in known if first is not None and b.t_ps >= first]
        chk.ctrl(
            "SMC-TAP-LIVE",
            bool(ar)
            and not unknown
            and self.clk_ps is not None
            and wait_t is not None
            and bool(polls)
            and consume is not None
            and any(b.t_ps > consume for b in known),
            ar=len(ar),
            unknown=unknown,
            first_scratch8_ps=first or -1,
            wait_ps=wait_t or -1,
            polls_before_consume=len(polls),
            consume_ps=consume or -1,
            ar_after_consume=sum(1 for b in known if consume is not None and b.t_ps > consume),
        )

        # The tap has no R channel, so the ROM's own echoes of the value it read are the evidence.
        s8_writes = [_hex(b.addr) for b in aw if b.addr is not None and b.addr & ~7 == _SCRATCH8]
        off_line = f"MANIFEST_OFF={off}"
        src_t = obs.line_t(self.src_echo)
        chk.ctrl(
            "OFFSET-PUBLISHED",
            obs.line_t(off_line) is not None
            and src_t is not None
            and wait_t is not None
            and src_t > wait_t
            and not s8_writes,
            probe_echo=off_line if obs.line_t(off_line) is not None else "absent",
            src_echo=self.src_echo,
            src_ps=src_t or -1,
            wait_ps=wait_t or -1,
            scratch8_writes=s8_writes,
        )

        ring = (SMC_SRAM_BASE + self.cfg.smc_mem.read32(_SCRATCH11)) & _WORD
        # The data beats that carry the header, since a 32-bit load may be issued as its full beat.
        ring_lo = ring & ~(_BEAT_BYTES - 1)
        ring_hi = (ring + _RING_HEADER_BYTES + _BEAT_BYTES - 1) & ~(_BEAT_BYTES - 1)

        def is_ring(b) -> bool:
            a, e = _span(b)
            return ring_lo <= a and e <= ring_hi

        pre_ring = [b for b in known if is_ring(b) and (first is None or b.t_ps < first)]
        ring_line = f"ring buffer address: 0x{ring:08x}"
        ring_seen = obs.line_t(ring_line) is not None
        chk.ctrl(
            "RING-HEADER-READS",
            ring_seen and bool(pre_ring),
            ring=_hex(ring),
            excluded=f"{_hex(ring_lo)}..{_hex(ring_hi)}",
            console=ring_line if ring_seen else "absent",
            reads_before_first_scratch8=len(pre_ring),
            reads_from_first_scratch8=sum(1 for b in after if is_ring(b)),
        )

        if consume is None:
            return
        src = self.src_addr

        def forbidden(b) -> bool:
            return not is_ring(b) and (
                _overlaps(b, SMC_SRAM_BASE, SMC_SRAM_BASE + _SMC_SRAM_SIZE)
                or _overlaps(b, src, src + _MANIFEST_BYTES)
            )

        bad = [b for b in after if forbidden(b)]
        other = sorted({_hex(_slot(b)) for b in after if not is_ring(b) and not forbidden(b)})
        overlap = max(0, min(ring_hi, src + _MANIFEST_BYTES) - max(ring_lo, src))
        chk.obs("OTHER-SMC-AR-FROM-FIRST-SCRATCH8", slots=other)
        chk.obs(
            "SMC-SRAM-READ",
            offset=off,
            src=_hex(src),
            window=f"{_hex(SMC_SRAM_BASE)}..{_hex(SMC_SRAM_BASE + _SMC_SRAM_SIZE)}",
            from_ps=first,
            consume_ps=consume,
            ring_overlap_bytes=overlap,
            reads=[f"{b.t_ps}:{_hex(b.addr)}/len{b.len}/size{b.size}" for b in bad[:8]],
            n_reads=len(bad),
        )

        after_status = [_hex(w) for t, w in obs.status if t > consume]
        after_console = [line for t, line in obs.console if t > consume]
        chk.obs("REFUSAL", statuses=after_status, console=after_console)

        validated = [
            _hex(w)
            for _, w in obs.status
            if w & _STATUS_ID_CODE == _VALIDATED_ID_CODE and w >> 24 != _INFO_EXT
        ]
        verdict_t, verdict = obs.verdict[-1] if obs.verdict else (None, None)
        failed = False
        moved = []
        held_clk = 0
        if verdict_t is not None and verdict == _FAIL_VERDICT:
            failed = any(w == _LOAD_FAILED_ERROR for t, w in obs.status if consume < t <= verdict_t)
            moved = [_hex(w) for t, w in obs.status if t > verdict_t]
            moved += [line for t, line in obs.console if t > verdict_t]
            held_clk = (end_ps - verdict_t) // clk_ps
        no_ok = obs.line_t(MANIFEST_OK) is None and obs.line_t("BL1_JUMP=") is None
        chk.ok(
            "SLOT-REFUSED",
            not validated
            and failed
            and verdict == _FAIL_VERDICT
            and held_clk >= _HALT_CYCLES
            and not moved
            and no_ok
            and obs.line_t(ALL_FAILED) is not None,
            validated=validated,
            load_failed_error_before_verdict=failed,
            verdict=_hex(verdict),
            held_clk=held_clk,
            moved_after_verdict=moved,
            manifest_ok_or_bl1_jump=not no_ok,
            all_failed=obs.line_t(ALL_FAILED) is not None,
        )
