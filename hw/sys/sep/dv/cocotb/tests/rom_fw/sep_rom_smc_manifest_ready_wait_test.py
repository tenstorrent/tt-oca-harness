# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secondary boot: the ROM waits for MANIFEST_READY before it consumes scratch[8].

rom.adoc, SMC Synchronization, Manifest Staging Hand-shake (Recovery / Secondary):

    [SEP-ROM-SMC-040] The ROM shall wait (unbounded poll) for `scratch9.MANIFEST_READY`
    before consuming scratch[8].

    The manifest is copied by secure DMA from `SMC_SRAM_base + scratch[8]` into SEP SRAM and
    from then on follows the same validation path as a SPI-loaded manifest

rom.adoc, tbl:smc_scratch: scratch[n] is at SMC window offset `0x39080 + 8·n`; scratch[8]
`MANIFEST_ADDR` is the staged manifest offset in SMC SRAM; scratch[9] `STATUS_TO_SEP` bit 1 is
`MANIFEST_READY`. rom.adoc, Watchdog Posture, unbounded waits: each wait reports a status
immediately before it starts waiting; for this wait that status is `WAIT_FOR_SMC_MANIFEST_READY`.

The leaf holds scratch[9].MANIFEST_READY low with a decoy offset in scratch[8], waits until the
ROM polls scratch[9] after that status, holds for `_HOLD_CYCLES`, then publishes the real offset
and raises MANIFEST_READY.

* CHK-NO-CONSUME-BEFORE-READY: from the wait status to the release there is no PR-SMC read of
  scratch[8], and from the first scratch[9] poll to the release no read of SMC SRAM. The status
  ring insert of the wait status itself may read SMC SRAM before the first poll.
* CHK-CONSUMED-PUBLISHED-OFFSET: after the release the ROM polls scratch[9], then reads
  scratch[8], then fetches the manifest from SMC SRAM at the published offset; it never reads
  the decoy page, and `MANIFEST_SRC=` names the published address after the release.

Not covered: the recovery boot mode; "unbounded" beyond `_HOLD_CYCLES`; that the copy is made
"by secure DMA" (only the source address of the fetch is graded). The pre-wait
coordination probe also reads scratch[8]; the spec does not say whether that read is a
"consume", so it is logged (OBS-PRE-WAIT-SCRATCH8), not graded.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_chk_log import SepChkLog
from env.sep_fabric_tap import SepFabricTap
from env.sep_rom_observer import STORE_LAG_MAX_CYCLES, SepRomObserver
from rom_fw.sep_firmware_secondary_chiplet_bootcode_test import (
    sep_firmware_secondary_chiplet_bootcode_test as _Base,
)
from rom_fw.sep_secondary_chiplet_base import (
    DEFAULT_MANIFEST_OFFSET,
    SMC_COORD_NOT_READY,
    SMC_SRAM_BASE,
)

_SMC_WINDOW = 0x4000_0000
_SCRATCH8 = _SMC_WINDOW + 0x39080 + 8 * 8
_SCRATCH9 = _SMC_WINDOW + 0x39080 + 8 * 9
_READY_BIT = 1 << 1
_SMC_SRAM_SIZE = 1 << 20
# BL0 id and SEP_MSG_WAIT_FOR_SMC_MANIFEST_READY of the status registry; the type byte is not graded.
_WAIT_ID_CODE = (1 << 16) | 0x007D
_ID_CODE_MASK = 0x00FF_FFFF
# Outside the packed SMC image, so no payload read can land on it by chance.
_DECOY_OFFSET = 0x8_0000
_MANIFEST_BYTES = 0x1000
_HOLD_CYCLES = 20_000
# A poll loop that leaves scratch[9] unread this long is not polling.
_POLL_GAP_CYCLES = 1_000


def _slot(beat) -> int | None:
    return None if beat.addr is None else beat.addr & ~7


def _hex(v: int | None) -> str:
    return "none" if v is None else f"0x{v:08x}"


@pyuvm.test()
class sep_rom_smc_manifest_ready_wait_test(_Base):
    required_evidence = ("CHK-NO-CONSUME-BEFORE-READY", "CHK-CONSUMED-PUBLISHED-OFFSET")

    @property
    def _forbidden(self) -> tuple[str, ...]:
        return tuple(m for m in super()._forbidden if m != SMC_COORD_NOT_READY)

    # The coordination probe runs before the release, so it echoes the decoy and NOT_READY.
    @property
    def published_off_echo(self) -> str:
        return f"MANIFEST_OFF=0x{_DECOY_OFFSET:08x}"

    @property
    def published_addr_echo(self) -> str:
        return SMC_COORD_NOT_READY

    def prepare_smc_mem(self) -> None:
        super().prepare_smc_mem()
        mem = self.cfg.smc_mem
        assert mem is not None, (
            "the rom_boot target did not bind its SMC responder; run this leaf on the rom_boot "
            "target, which sets cfg.smc_mem"
        )
        self._status = mem.read32(_SCRATCH9)
        mem.write32(_SCRATCH9, self._status & ~_READY_BIT)
        mem.write32(_SCRATCH8, _DECOY_OFFSET)

    def _wait_t(self) -> int | None:
        return next(
            (t for t, w in self.obs.status if w & _ID_CODE_MASK == _WAIT_ID_CODE),
            None,
        )

    async def _release(self) -> None:
        clk = cocotb.top.clk_i
        await RisingEdge(clk)
        t0 = int(get_sim_time("ps"))
        await RisingEdge(clk)
        self.clk_ps = int(get_sim_time("ps")) - t0
        while self._wait_t() is None:
            await RisingEdge(clk)
        lo = self._wait_t() - STORE_LAG_MAX_CYCLES * self.clk_ps
        i = 0
        while self.poll_start_ps is None:
            beats = self.smc.beats
            for b in beats[i:]:
                if b.ch == "ar" and _slot(b) == _SCRATCH9 and b.t_ps >= lo:
                    self.poll_start_ps = int(b.t_ps)
                    break
            i = len(beats)
            await RisingEdge(clk)
        await ClockCycles(clk, _HOLD_CYCLES)
        mem = self.cfg.smc_mem
        mem.write32(_SCRATCH8, DEFAULT_MANIFEST_OFFSET)
        mem.write32(_SCRATCH9, self._status | _READY_BIT)
        self.release_ps = int(get_sim_time("ps"))

    async def run_scenario(self) -> None:
        self.chk = SepChkLog(self, self.get_type_name(), self.random_seed())
        self.clk_ps = self.poll_start_ps = self.release_ps = None
        # The observer and the tap start before reset release so the first SMC access is recorded.
        self.obs = SepRomObserver(self, keep=lambda _insn: False, tracker=False).start()
        self.smc = SepFabricTap("PR-SMC").start()
        mark = self.smc.mark()
        release = cocotb.start_soon(self._release())
        base_err = None
        try:
            await super().run_scenario()
        except AssertionError as err:
            base_err = err
        release.cancel()
        await self.obs.stop()
        await self.smc.stop()
        self._grade(self.smc.since(mark, "ar"))
        self.chk.ctrl("SECONDARY-BOOT", base_err is None, base_error=str(base_err or "none"))
        self.chk.finish()

    def _grade(self, ar: list) -> None:
        chk, obs = self.chk, self.obs
        unknown = sum(1 for b in ar if b.addr is None)
        chk.ctrl("SMC-AR-LIVE", bool(ar) and not unknown, ar=len(ar), unknown=unknown)

        wait_t = self._wait_t()
        rel = self.release_ps
        chk.ctrl(
            "RELEASED",
            wait_t is not None and rel is not None and self.poll_start_ps is not None,
            wait_ps=wait_t or -1,
            poll_start_ps=self.poll_start_ps or -1,
            release_ps=rel or -1,
        )
        if wait_t is None or rel is None or self.poll_start_ps is None:
            return
        lag = STORE_LAG_MAX_CYCLES * self.clk_ps
        lo = wait_t - lag
        # The hold must show no console or status progress, or the polls are not the wait itself.
        moved = [line for t, line in obs.console if self.poll_start_ps + lag <= t < rel]
        moved += [_hex(w) for t, w in obs.status if self.poll_start_ps + lag <= t < rel]
        # With the DV ring invalid, the last status is the ring-insert error word, not the wait status.
        held = [w for t, w in obs.status if t < rel]
        chk.ctrl(
            "PARKED-IN-WAIT",
            not moved,
            moved=moved,
            last_status_before_release=_hex(held[-1] if held else None),
        )

        s8 = [b for b in ar if _slot(b) == _SCRATCH8]
        s9 = [b for b in ar if _slot(b) == _SCRATCH9]
        polls = [b.t_ps for b in s9 if self.poll_start_ps <= b.t_ps < rel]
        edges = [self.poll_start_ps, *polls, rel]
        max_gap = int(max(b - a for a, b in zip(edges, edges[1:], strict=False))) // self.clk_ps
        hold = (rel - self.poll_start_ps) // self.clk_ps
        chk.ctrl(
            "POLLED-DURING-HOLD",
            len(polls) > 1 and hold >= _HOLD_CYCLES and max_gap <= _POLL_GAP_CYCLES,
            polls=len(polls),
            hold_clk=hold,
            max_gap_clk=max_gap,
        )
        chk.obs(
            "PRE-WAIT-SCRATCH8",
            reads_ps=[int(b.t_ps) for b in s8 if b.t_ps < lo],
            probe_echo=obs.line_t(self.published_off_echo) or -1,
        )

        def in_sram(b) -> bool:
            return b.addr is not None and SMC_SRAM_BASE <= b.addr < SMC_SRAM_BASE + _SMC_SRAM_SIZE

        early8 = [int(b.t_ps) for b in s8 if lo <= b.t_ps < rel]
        early_sram = [_hex(b.addr) for b in ar if self.poll_start_ps <= b.t_ps < rel and in_sram(b)]
        chk.ok(
            "NO-CONSUME-BEFORE-READY",
            not early8 and not early_sram,
            window_ps=f"{lo}..{rel}",
            sram_window_ps=f"{self.poll_start_ps}..{rel}",
            scratch8_reads=early8,
            sram_reads=early_sram,
        )

        pub = SMC_SRAM_BASE + DEFAULT_MANIFEST_OFFSET
        decoy = SMC_SRAM_BASE + _DECOY_OFFSET
        rd8 = next((b.t_ps for b in s8 if b.t_ps >= rel), None)
        ready_poll = rd8 is not None and any(rel <= b.t_ps < rd8 for b in s9)
        fetch = [b for b in ar if b.addr is not None and pub <= b.addr < pub + _MANIFEST_BYTES]
        fetch_t = next((b.t_ps for b in fetch if b.addr == pub), None)
        decoy_reads = [
            _hex(b.addr)
            for b in ar
            if b.addr is not None and decoy <= b.addr < decoy + _MANIFEST_BYTES
        ]
        want = f"MANIFEST_SRC=0x{pub:08x}"
        src_t = obs.line_t(want)
        chk.ok(
            "CONSUMED-PUBLISHED-OFFSET",
            ready_poll
            and fetch_t is not None
            and fetch_t > rd8
            and all(b.t_ps > rd8 for b in fetch)
            and not decoy_reads
            and src_t is not None
            and src_t > rel,
            release_ps=rel,
            scratch8_read_ps=int(rd8 or -1),
            ready_poll=ready_poll,
            fetch_ps=int(fetch_t or -1),
            fetch_reads=len(fetch),
            decoy_reads=decoy_reads,
            src_echo=want,
            src_ps=src_t or -1,
        )
