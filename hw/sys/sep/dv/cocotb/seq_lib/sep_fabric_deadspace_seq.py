# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode for sep_fabric_deadspace_decode_test.

Each block owns a memory-map window and populates only ``REG_MAP_SIZE``
of it. An access past that allocated size owns no register and must be
refused -- DECERR or SLVERR. This walk grades refusal only; the past-extent
code ``sep.rdl`` states per block (``ocah_resp``) is graded by
``sep_unmapped_access_policy_test`` at the points that test probes.
Truncating the address, wrapping it onto a live register and answering
OKAY is what this sequence exists to catch.

Allocated size comes from the generated export (or the OT/IP header for
CSRNG / EDN / entropy_source). Window end comes from
``hw/sys/sep/doc/memory_map.adoc``. RTL decode width is never the judge
of legality.

Windows cover CSR apertures whose memory-map window is larger than
``REG_MAP_SIZE`` (DMA, WDT, AES, OTBN, ABR, CSRNG, EDN, ESRC, KM mailbox,
lifecycle, SPI). HMAC/KMAC fill their map window so they have no
intra-window dead span here. Remap / filter arrays and scratch are
owned elsewhere for live programming.

The TRNG window is forwarded whole to an adopter endpoint on
``ext_trng_axil``; SEP allocates no register in it. With no external TRNG
connected, as in the reference integration, no offset owns a register, and
``hw/sys/sep/doc/memory_map.adoc`` requires the access to be refused: a
single-beat read or write answers DECERR. The test grades that code per probe.
Its alias targets are the neighbouring ESRC registers, which an access
that drops address bit 12 reaches.

Known wrap offsets that alias onto live registers stay in the probe set
every seed. The seed adds further dead offsets. Do not shrink the set to
the addresses that already pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_decode_resp import sep_map_row
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import (
    block_size,
    iter_addrs,
    ot_reg_map_size,
    ot_reg_offsets,
    reg_hw_updating,
    reg_write_destructive,
    register_fields,
    sym,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import CSRNG_BASE, EDN_BASE

RESP_OKAY = 0
RESP_DECERR = 3

# Watch-list names that pop a FIFO or fire a trigger. Snapshotting them
# is a side effect, so they are not part of the no-alias compare.
# `RDATA` covers the entropy_source auto-incrementing read ports (FIFO_RDATA,
# BIW_OBS_RDATA, NOISE_OBS_RDATA, all `onread: ruser`). snapshot() reads every
# watched address twice, so without this each FIFO is popped twice per run:
# the pointer advances, FIFO_STATUS.LEVEL drops, and an empty FIFO raises
# INTR_STATUS.FIFO_UNDERFLOW into whatever test runs next.
_WATCH_SKIP_SUFFIX = (
    "INTR_TEST",
    "ALERT_TEST",
    "TXDATA",
    "RXDATA",
    "WRITE_DATA",
    "READ_DATA",
    "RDATA",
    "GENBITS",
    "CMD",
    "CMD_REQ",
)


@dataclass(frozen=True)
class DeadWindow:
    """One block window: allocated registers vs the memory-map remainder."""

    name: str
    base: int
    window_end: int
    alloc: int
    watch: tuple[int, ...]
    write_ok: bool = True
    # Watched addresses hardware may change on its own (sep_reg_meta.reg_hw_updating,
    # the same source the bit-bash reset walk uses). Excluded from the per-probe
    # change compare -- see probe(). They stay in the snapshot for the read-alias
    # compare, which does not care that they move.
    hw_updating: frozenset[int] = frozenset()
    # Watched addresses a sampled value cannot be written back to (woclr/woset).
    # restore() must skip them: on a woclr field every bit that read as 1 would be
    # CLEARED in the DUT, so the "restore" destroys the live status it claims to
    # put back.
    #
    # Populated for entropy_src only, the one leaf whose Python header carries
    # generated field-access metadata. For the other windows restore() writes
    # back W1C registers such as spi_controller ERROR_STATUS and km_mailbox
    # status_reg / irq_status_reg. restore() runs only after a probe has failed,
    # so the corruption is confined to a run that is already reporting failure.
    write_destructive: frozenset[int] = frozenset()
    # The window is forwarded whole to an adopter endpoint and allocates no SEP
    # register. ``watch`` then holds the neighbouring registers an aliasing
    # access reaches, named by ``watch_from``, and the caller reports the
    # refusal flavour of every probe.
    adopter: bool = False
    watch_from: str = ""

    @property
    def store_visible(self) -> frozenset[int]:
        """Watched addresses on which a stored write can show.

        A register qualifies when the generated IP-XACT gives it at least one
        ``read-write`` field. A ``read-only`` field has no bus write path and a
        ``write-only`` field reads back nothing, so a register made only of
        those is compared but cannot show a store.
        """
        return _store_visible(self.watch)

    def armed(self, snap: dict[int, int]) -> int:
        """Snapshot registers the change compare reads that can show a store."""
        return sum(1 for a in snap if a not in self.hw_updating and a in self.store_visible)

    @property
    def dead_lo(self) -> int:
        return self.base + self.alloc

    @property
    def dead_hi(self) -> int:
        return self.window_end


def _store_visible(watch: tuple[int, ...]) -> frozenset[int]:
    return frozenset(
        addr for addr in watch if any(f.access == "read-write" for f in register_fields(addr)[1])
    )


def _watch_skip(name: str) -> bool:
    return any(name == s or name.endswith("_" + s) for s in _WATCH_SKIP_SUFFIX)


def _sep_watch(base: int, alloc: int) -> tuple[int, ...]:
    addrs = [
        addr
        for _block, name, addr in iter_addrs()
        if base <= addr < base + alloc and not _watch_skip(name)
    ]
    return tuple(sorted(set(addrs)))


def _ot_watch(ip: str, base: int, alloc: int) -> tuple[int, ...]:
    addrs = [
        base + off for name, off in ot_reg_offsets(ip) if off < alloc and not _watch_skip(name)
    ]
    return tuple(sorted(set(addrs)))


def _ot_named(ip: str, base: int, alloc: int, names) -> frozenset[int]:
    """Watched addresses of an OT block whose register name is in ``names``."""
    return frozenset(
        base + off
        for name, off in ot_reg_offsets(ip)
        if off < alloc and not _watch_skip(name) and name in names
    )


_ABR = sym("ABR_REG_MAP_BASE_ADDR")

# The crypto region, OTBN through ABR (hw/sys/sep/doc/memory_map.adoc,
# "Single-Beat Register Access"). hw/sys/sep/doc/crypto.adoc,
# "Single-Beat Access Only": the sep_crypto demux answers every access whose
# AxLEN is non-zero with DECERR on every beat, and no beat reaches an
# accelerator. A burst into any other register region is outside the
# specification, so no burst contract exists there.
CRYPTO_LO = sym("OTBN_REG_MAP_BASE_ADDR")
CRYPTO_HI = sep_map_row(_ABR).end + 1


def in_crypto_region(addr: int) -> bool:
    return CRYPTO_LO <= addr < CRYPTO_HI


def dead_windows() -> tuple[DeadWindow, ...]:
    """Source-derived windows. Allocated size is never the RTL truncate width."""
    esrc_base = sym("ENTROPY_SOURCE_REG_MAP_BASE_ADDR")
    return (
        DeadWindow(
            "secure_dma",
            sym("SECURE_DMA_REG_MAP_BASE_ADDR"),
            sym("WDT_TIMER_REG_MAP_BASE_ADDR"),
            block_size("SECURE_DMA"),
            _sep_watch(sym("SECURE_DMA_REG_MAP_BASE_ADDR"), block_size("SECURE_DMA")),
        ),
        DeadWindow(
            "wdt_timer",
            sym("WDT_TIMER_REG_MAP_BASE_ADDR"),
            sym("SEP_SCRATCH_COLD_REG_MAP_BASE_ADDR"),
            block_size("WDT_TIMER"),
            _sep_watch(sym("WDT_TIMER_REG_MAP_BASE_ADDR"), block_size("WDT_TIMER")),
        ),
        DeadWindow(
            "aes",
            sym("AES_REG_MAP_BASE_ADDR"),
            sym("HMAC_REG_MAP_BASE_ADDR"),
            block_size("AES"),
            _sep_watch(sym("AES_REG_MAP_BASE_ADDR"), block_size("AES")),
        ),
        DeadWindow(
            "otbn",
            sym("OTBN_REG_MAP_BASE_ADDR"),
            sym("AES_REG_MAP_BASE_ADDR"),
            block_size("OTBN"),
            _sep_watch(sym("OTBN_REG_MAP_BASE_ADDR"), block_size("OTBN")),
        ),
        DeadWindow(
            "abr",
            _ABR,
            sym("ENTROPY_POOL_REG_MAP_BASE_ADDR"),
            block_size("ABR"),
            _sep_watch(_ABR, block_size("ABR")),
        ),
        DeadWindow(
            "csrng",
            CSRNG_BASE,
            EDN_BASE,
            ot_reg_map_size("csrng"),
            _ot_watch("csrng", CSRNG_BASE, ot_reg_map_size("csrng")),
        ),
        DeadWindow(
            "edn",
            EDN_BASE,
            esrc_base,
            ot_reg_map_size("edn"),
            _ot_watch("edn", EDN_BASE, ot_reg_map_size("edn")),
        ),
        DeadWindow(
            "entropy_src",
            esrc_base,
            sym("TRNG_REG_MAP_BASE_ADDR"),
            ot_reg_map_size("entropy_source"),
            _ot_watch("entropy_source", esrc_base, ot_reg_map_size("entropy_source")),
            hw_updating=_ot_named(
                "entropy_source",
                esrc_base,
                ot_reg_map_size("entropy_source"),
                reg_hw_updating("entropy_source"),
            ),
            write_destructive=_ot_named(
                "entropy_source",
                esrc_base,
                ot_reg_map_size("entropy_source"),
                reg_write_destructive("entropy_source"),
            ),
        ),
        DeadWindow(
            "km_mailbox",
            sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR"),
            # Aperture end from the generated SEP memory map; no neighbouring
            # REG_MAP_BASE_ADDR follows this block.
            sep_map_row(sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR")).end + 1,
            block_size("KM_MAILBOX_SEP"),
            _sep_watch(
                sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR"),
                block_size("KM_MAILBOX_SEP"),
            ),
        ),
        DeadWindow(
            "lifecycle",
            sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR"),
            sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR"),
            block_size("SEP_LIFECYCLE_CTRL"),
            _sep_watch(
                sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR"),
                block_size("SEP_LIFECYCLE_CTRL"),
            ),
            write_ok=False,
        ),
        DeadWindow(
            "spi_controller",
            sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR"),
            # Aperture end from the generated SEP memory map; no neighbouring
            # REG_MAP_BASE_ADDR follows this block.
            sep_map_row(sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR")).end + 1,
            block_size("SPI_CONTROLLER"),
            _sep_watch(
                sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR"),
                block_size("SPI_CONTROLLER"),
            ),
        ),
        DeadWindow(
            "trng",
            sym("TRNG_REG_MAP_BASE_ADDR"),
            sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR"),
            0,
            _ot_watch("entropy_source", esrc_base, ot_reg_map_size("entropy_source")),
            hw_updating=_ot_named(
                "entropy_source",
                esrc_base,
                ot_reg_map_size("entropy_source"),
                reg_hw_updating("entropy_source"),
            ),
            write_destructive=_ot_named(
                "entropy_source",
                esrc_base,
                ot_reg_map_size("entropy_source"),
                reg_write_destructive("entropy_source"),
            ),
            adopter=True,
            watch_from="entropy_src",
        ),
    )


_TRNG = sym("TRNG_REG_MAP_BASE_ADDR")

# (window name, addr, "r"|"w") — directed dead-space anchors. Every seed probes all of them.
DEADSPACE_ANCHORS: tuple[tuple[str, int, str], ...] = (
    ("km_mailbox", 0x1092_0414, "w"),
    ("km_mailbox", 0x1092_0C04, "w"),
    ("km_mailbox", 0x1092_0FF8, "w"),
    ("km_mailbox", 0x1092_080C, "r"),
    ("wdt_timer", 0x1080_1428, "w"),
    ("wdt_timer", 0x1080_181C, "w"),
    ("wdt_timer", 0x1080_1C0C, "w"),
    ("edn", 0x1091_5A34, "w"),
    ("edn", 0x1091_5E10, "w"),
    ("csrng", 0x1091_5248, "w"),
    ("entropy_src", 0x1091_651C, "w"),
    ("secure_dma", 0x1080_08A8, "w"),
    # First word past the ABR map, error_intr_en_r with offset bit 14 set, and
    # the last word of the ABR window.
    ("abr", _ABR + block_size("ABR"), "r"),
    ("abr", _ABR + block_size("ABR"), "w"),
    ("abr", sym("ABR_INTR_BLOCK_RF_ERROR_INTR_EN_R_REG_ADDR") | 0x4000, "w"),
    ("abr", sym("ENTROPY_POOL_REG_MAP_BASE_ADDR") - 4, "w"),
    # First, middle and last word of the adopter TRNG window, read and write.
    ("trng", _TRNG + 0x000, "r"),
    ("trng", _TRNG + 0x000, "w"),
    ("trng", _TRNG + 0x800, "r"),
    ("trng", _TRNG + 0x800, "w"),
    ("trng", _TRNG + 0xFFC, "r"),
    ("trng", _TRNG + 0xFFC, "w"),
)


@dataclass(frozen=True)
class DeadProbe:
    window: str
    addr: int
    op: str
    anchor: bool


class SepDeadspaceCfg:
    """Known-bad anchors every seed, plus seed-selected dead offsets."""

    def __init__(self, seed: int, *, n_random: int = 2) -> None:
        self.seed = seed
        self.windows = {w.name: w for w in dead_windows()}
        missing = {name for name, _a, _op in DEADSPACE_ANCHORS if name not in self.windows}
        if missing:
            raise RuntimeError(f"anchor window(s) not in dead_windows(): {sorted(missing)}")
        probes = [DeadProbe(name, addr, op, True) for name, addr, op in DEADSPACE_ANCHORS]
        rng = SepSeededRng(seed)
        taken = {(p.window, p.addr, p.op) for p in probes}
        # Windows that could not supply their full random quota within the spin
        # bound. Probe count is the coverage claim, so a shortfall is recorded
        # and logged rather than silently absorbed into a smaller probe set.
        self.short_windows: dict[str, tuple[int, int]] = {}
        for win in self.windows.values():
            if win.dead_lo >= win.dead_hi:
                # No dead span to probe. Recorded rather than skipped so a
                # window that loses its span to a map change shows up as 0/N
                # instead of quietly leaving the probe set.
                self.short_windows[win.name] = (0, n_random)
                continue
            added = 0
            spins = 0
            while added < n_random and spins < 32:
                spins += 1
                addr = rng.randrange(win.dead_lo, win.dead_hi) & ~0x3
                if addr < win.dead_lo:
                    continue
                op = "r" if (not win.write_ok or rng.getrandbits(1)) else "w"
                key = (win.name, addr, op)
                if key in taken:
                    continue
                taken.add(key)
                probes.append(DeadProbe(win.name, addr, op, False))
                added += 1
            if added < n_random:
                self.short_windows[win.name] = (added, n_random)
        self.probes = tuple(probes)

    def summary(self) -> str:
        n_anchor = sum(1 for p in self.probes if p.anchor)
        n_rand = len(self.probes) - n_anchor
        short = " ".join(
            f"{name}={got}/{want}" for name, (got, want) in sorted(self.short_windows.items())
        )
        return (
            f"seed={self.seed} probes={len(self.probes)} "
            f"anchors={n_anchor} random={n_rand} windows={len(self.windows)} "
            f"short=[{short}]"
        )


class SepDeadspace:
    """Snapshot allocated registers, probe a dead offset, compare."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger
        # Refusals whose flavour is not DECERR. Reported, not failed: this walk
        # grades refusal only.
        self.flavour_findings: list[str] = []
        # Response of the last probe(); -1 when it timed out.
        self.last_resp: int = -1

    async def _access(
        self,
        op: SepAxiOp,
        addr: int,
        *,
        wdata: int = 0,
        expect_error: bool = False,
    ) -> tuple[int, int, bool]:
        seq = SepAxiAccessSeq(
            f"dead_{op.value}_0x{addr:08x}",
            op=op,
            addr=addr,
            wdata=wdata,
            length=4,
            size=2,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF, seq.timed_out

    async def burst_across_extent(
        self, win, start: int | None = None
    ) -> tuple[int, list[int], bool, list[int], list[tuple[int, int]], list[int | None]]:
        """Read an INCR burst that starts inside the extent and ends past it.

        AXI routes a burst on its FIRST address and a burst may not cross a 4 KB
        boundary, which is what normally makes a refused address unreachable. An
        extent that does not end on a 4 KB boundary breaks that: a burst begun in
        the last live words is routed wholly to this block, and its later beats
        land past ``REG_MAP_SIZE`` -- the span `memory_map.adoc` says is
        refused at the fabric and never reaches a unit.

        ``start`` overrides the first address, for a window with no burst that
        crosses its extent; the caller then grades the burst rule alone.

        Returns the start address, the responses the master reported, the
        timeout flag, the four beats, a single-beat read of each of the same
        addresses, and the per-beat response vector the passive monitor observed.

        The master collapses a read burst to one response: the cocotbext-axi
        beat loop keeps the last non-OKAY RRESP and discards the rest, so
        ``seq.resp_list`` cannot say which beats were refused. The passive
        monitor records every R beat separately and publishes the whole vector
        at RLAST, so the per-beat contract is read from there instead.
        """
        beats = 4  # by default two live beats, then two past the extent
        if start is None:
            start = win.dead_lo - 4 * (beats // 2)
        mon = self.test.env.axi_monitor
        mon.start_beat_capture()
        # The later beats land in dead space, so a correct fabric answers this
        # burst with an error. Credit those beats and hand back whatever the
        # fabric did not use: without the credit the monitor reports a correct
        # refusal as a protocol error, and this walk could not pass against a
        # block that refuses correctly.
        mon.arm_expected_decerr(beats)
        seq = SepAxiAccessSeq(
            f"dead_burst_0x{start:08x}",
            op=SepAxiOp.READ,
            addr=start,
            length=4 * beats,
            size=2,
            expect_error=True,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        # Per-beat responses come from the monitor; the master has only the
        # collapsed one. The capture window records every R beat on this bus, not
        # this burst's beats specifically, so quiescence and the length check
        # below are what make the vector attributable to this burst.
        captured = mon.take_beat_capture()
        # Only a complete, fully resolved sequence is evidence. A shorter one
        # means beats were not observed and a longer one means unrelated traffic
        # shared the window, so neither is attributable to this burst. An entry
        # that did not resolve to an int is not evidence either, and it must not
        # be read as a refusal: the checker fails a beat that answers OKAY past
        # the extent, so an unresolved beat there would otherwise pass by
        # default. Rejecting the whole vector sends the window to the tally
        # instead, where it is named rather than counted as proof.
        usable = len(captured) == beats and all(r is not None for r in captured)
        mon_resps = [r for r in captured if r is not None] if usable else []
        # Credit from the per-beat vector when it is available: the collapsed
        # response holds at most one entry, so crediting from it releases beats
        # the fabric did refuse. That over-release can only make the monitor
        # report a refusal it was told to expect, never absorb one it was not:
        # release_expected_decerr floors at zero, so the failure direction is a
        # spurious monitor error, not a swallowed DECERR.
        used = (
            sum(1 for r in mon_resps if r == RESP_DECERR)
            if mon_resps
            else sum(1 for r in seq.resp_list if r == RESP_DECERR)
        )
        if beats > used:
            mon.release_expected_decerr(beats - used)
        words = [(seq.rdata >> (32 * i)) & 0xFFFF_FFFF for i in range(beats)]
        # Single-beat the same four addresses. Beats 0-1 are inside the extent
        # and must match; beats 2-3 are past it and are refused on their own, so
        # the test holds a burst word there to the single-beat no-alias rule.
        singles = []
        for i in range(beats):
            past = start + 4 * i >= win.dead_lo
            if past:
                mon.arm_expected_decerr(1)
            r, d, _to = await self._access(SepAxiOp.READ, start + 4 * i, expect_error=past)
            if past and r != RESP_DECERR:
                mon.release_expected_decerr(1)
            singles.append((r, d))
        return (start, list(seq.resp_list), seq.timed_out, words, singles, mon_resps)

    async def burst_write(
        self, win, start: int, snap: dict[int, int]
    ) -> tuple[int, bool, list[str]]:
        """Write a four-beat INCR burst at ``start``; return BRESP, timeout and changes.

        Every beat carries all ones, so a beat that reached a writable register
        moves it. One BRESP covers the burst, and the change compare is what
        shows whether any beat landed.
        """
        beats = 4
        mon = self.test.env.axi_monitor
        mon.arm_expected_decerr(1)
        seq = SepAxiAccessSeq(
            f"dead_burst_wr_0x{start:08x}",
            op=SepAxiOp.WRITE,
            addr=start,
            wdata=(1 << (32 * beats)) - 1,
            length=4 * beats,
            size=2,
            expect_error=True,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        resp = -1 if seq.timed_out else seq.resp_code
        if resp != RESP_DECERR:
            mon.release_expected_decerr(1)
        if seq.timed_out:
            return resp, True, []
        return resp, False, await self.changed_registers(win, snap, f"write burst 0x{start:08x}")

    async def snapshot(self, win) -> dict[int, int]:
        snap: dict[int, int] = {}
        volatile: set[int] = set()
        for addr in win.watch:
            resp1, a, to1 = await self._access(SepAxiOp.READ, addr)
            resp2, b, to2 = await self._access(SepAxiOp.READ, addr)
            if to1 or to2 or resp1 != RESP_OKAY or resp2 != RESP_OKAY:
                continue
            if a != b:
                volatile.add(addr)
                continue
            snap[addr] = a
        if volatile:
            self.log.info(
                "%s: %d self-changing watch address(es) dropped from no-alias",
                win.name,
                len(volatile),
            )
        return snap

    async def restore(self, win, snap: dict[int, int]) -> None:
        """Put the allocated image back after a probe disturbed it.

        Write-one-to-clear registers are skipped, and the skip is reported. On a
        W1C field, writing the sampled value back does not restore it -- every
        bit that READ as 1 is CLEARED in the DUT, so the restore would destroy
        the live status it claims to put back. entropy_source has 15 such
        registers (INTR_STATUS, HEALTH_TEST_STATUS, MAIN_SM_STATUS and the
        twelve GENERATOR_n_HEALTH_STATUS), all reachable from this snapshot.
        """
        skipped = 0
        for addr, val in snap.items():
            if addr in win.write_destructive:
                skipped += 1
                continue
            await self._access(SepAxiOp.WRITE, addr, wdata=val)
        self.test.logger.info(
            "deadspace restore: %s restored %d of %d register(s); %d skipped as "
            "write-destructive (a write-back would clear or re-set them)",
            win.name,
            len(snap) - skipped,
            len(snap),
            skipped,
        )

    async def changed_registers(self, win, snap: dict[int, int], label: str) -> list[str]:
        """Re-read the armed registers of ``win`` and return a failure per change."""
        fails: list[str] = []
        after = {}
        skipped = 0
        unread: list[str] = []
        for addr in snap:
            if addr in win.hw_updating:
                skipped += 1
                continue
            resp_a, val, to_a = await self._access(SepAxiOp.READ, addr)
            if resp_a == RESP_OKAY and not to_a:
                after[addr] = val
            else:
                unread.append(f"+0x{addr - win.base:x} resp={resp_a} timed_out={to_a}")
        # An armed register that cannot be read back cannot show it did not
        # move, so a failed re-read fails the probe instead of shrinking it.
        if unread:
            fails.append(
                f"{win.name} {label} re-read of armed register(s) failed: {' '.join(unread)}"
            )
        # Report the size of the change compare, not just its verdict. An
        # exclusion that silently grows -- a schema change widening the
        # software-read-only set onto a control register -- would otherwise
        # shrink the coverage with an identical-looking log.
        self.test.logger.info(
            "deadspace scope: %s %s compared %d of %d watched "
            "register(s); %d skipped as hardware-updating",
            win.name,
            label,
            len(after),
            len(snap),
            skipped,
        )
        changed = {
            addr: (snap[addr], after[addr])
            for addr in snap
            if addr in after and after[addr] != snap[addr]
        }
        if changed:
            detail = " ".join(
                f"+0x{addr - win.base:x}:0x{old:08x}->0x{new:08x}"
                for addr, (old, new) in sorted(changed.items())
            )
            fails.append(f"{win.name} {label} changed live register(s) {detail}")
            await self.restore(win, snap)
        return fails

    async def probe(self, win, item: DeadProbe, snap: dict[int, int]) -> list[str]:
        """Return failure strings. Empty means this probe matched the spec."""
        fails: list[str] = []
        mon = self.test.env.axi_monitor
        # Arm one credit for a DECERR refuse. Hand it back unless this beat
        # was DECERR, so the monitor can consume it. Key off resp, not the
        # monitor tally: expected_decerr_seen increments on the monitor's
        # own RisingEdge, which may not have run yet when start_seq returns.
        mon.arm_expected_decerr(1)
        if item.op == "w":
            resp, _rd, timed_out = await self._access(
                SepAxiOp.WRITE,
                item.addr,
                wdata=0xFFFF_FFFF,
                expect_error=True,
            )
        else:
            resp, rdata, timed_out = await self._access(
                SepAxiOp.READ,
                item.addr,
                expect_error=True,
            )
            # `memory_map.adoc` says an address past the extent a unit
            # allocates is refused at the fabric and never reaches a unit. The
            # second half holds whatever the response flavour was, so the
            # alias compare is not gated on OKAY -- a refused read that still
            # hands back a live register's value has reached the unit. A real
            # refusal carries the error slave's poison, which matches no
            # allocated value.
            if not timed_out:
                for live_addr, live_val in snap.items():
                    if rdata == live_val:
                        fails.append(
                            f"{win.name} read 0x{item.addr:08x} resp={resp} "
                            f"rdata=0x{rdata:08x} aliases 0x{live_addr:08x}"
                        )
                        break
        if timed_out or resp != RESP_DECERR:
            mon.release_expected_decerr(1)
        self.last_resp = -1 if timed_out else resp
        if timed_out:
            fails.append(f"{win.name} {item.op} 0x{item.addr:08x} timed out")
            return fails
        if resp == RESP_OKAY:
            fails.append(
                f"{win.name} {item.op} 0x{item.addr:08x} resp=OKAY, "
                f"expected refuse (allocated ends at +0x{win.alloc:x})"
            )
        elif resp != RESP_DECERR and not win.adopter:
            # The contract asserted here is that the access is REFUSED, and any
            # error response satisfies it. A refusal in another flavour is
            # reported rather than failed: the defect this walk exists to catch
            # is OKAY plus aliasing.
            self.flavour_findings.append(
                f"{win.name} {item.op} 0x{item.addr:08x} refused with "
                f"resp={resp}, not DECERR (allocated ends at +0x{win.alloc:x})"
            )
        # A read of a dead offset must not return a live register's value, and
        # no probe -- read or write -- may change the allocated image: a refused
        # write that still stores is the wrap this entry exists to catch, and a
        # refused read that still reaches a unit can pop a FIFO or clear a
        # read-to-clear field without returning anything that matches the
        # snapshot.
        #
        # The change compare covers software-WRITABLE registers only. A field
        # declared `sw = r` has no bus write path -- the generated regblock
        # answers a write to one with OKAY and no error (entropy_source_reg.sv
        # `is_valid_rw = '1'`, `cpuif_wr_err = '0'`) and stores nothing -- so
        # such an address can never hold evidence of a store, aliased or
        # otherwise. It stays in `snap` for the read-alias compare above.
        # Leaving it in this compare instead measures the entropy source's own
        # health-test counters advancing over the microseconds the readback
        # takes, and reports that drift as a wrap. Every `sw = rw` register
        # stays armed, so an access that aliases onto a control register is
        # still caught -- at that control register, where it lands.
        fails.extend(await self.changed_registers(win, snap, f"{item.op} 0x{item.addr:08x}"))
        return fails
