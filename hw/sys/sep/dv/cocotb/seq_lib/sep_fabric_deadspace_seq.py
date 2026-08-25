# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Intra-block dead-space decode for sep_fabric_deadspace_decode_test.

Each block owns a memory-map window and populates only ``REG_MAP_SIZE``
of it. An access past that allocated size owns no register and must be
refused (DECERR). Several SEP blocks truncate the address, wrap it onto
a live register, and answer OKAY.

Allocated size comes from the generated export (or the OT/IP header for
CSRNG / EDN / entropy_source). Window end comes from
``hw/sys/sep/doc/memory_map.adoc``. RTL decode width is never the judge
of legality.

Known-bad offsets from the RTL question
https://github.com/tenstorrent/tt-oca-harness/issues/228 stay in the
probe set every seed. The seed adds further dead offsets. Do not shrink
the set to the addresses that already pass.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import (
    block_size,
    iter_addrs,
    ot_reg_map_size,
    ot_reg_offsets,
    sym,
)
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_irq_aggregator_seq import CSRNG_BASE, EDN_BASE

RESP_OKAY = 0
RESP_DECERR = 3

# Watch-list names that pop a FIFO or fire a trigger. Snapshotting them
# is a side effect, so they are not part of the no-alias compare.
_WATCH_SKIP_SUFFIX = (
    "INTR_TEST", "ALERT_TEST", "TXDATA", "RXDATA", "WRITE_DATA",
    "READ_DATA", "GENBITS", "CMD", "CMD_REQ",
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

    @property
    def dead_lo(self) -> int:
        return self.base + self.alloc

    @property
    def dead_hi(self) -> int:
        return self.window_end


def _watch_skip(name: str) -> bool:
    return any(name == s or name.endswith("_" + s) for s in _WATCH_SKIP_SUFFIX)


def _sep_watch(base: int, alloc: int) -> tuple[int, ...]:
    addrs = [
        addr for _block, name, addr in iter_addrs()
        if base <= addr < base + alloc and not _watch_skip(name)
    ]
    return tuple(sorted(set(addrs)))


def _ot_watch(ip: str, base: int, alloc: int) -> tuple[int, ...]:
    addrs = [
        base + off for name, off in ot_reg_offsets(ip)
        if off < alloc and not _watch_skip(name)
    ]
    return tuple(sorted(set(addrs)))


def dead_windows() -> tuple[DeadWindow, ...]:
    """Source-derived windows. Allocated size is never the RTL truncate width."""
    esrc_base = 0x1091_6000
    return (
        DeadWindow(
            "secure_dma",
            sym("SECURE_DMA_REG_MAP_BASE_ADDR"),
            0x1080_1000,
            block_size("SECURE_DMA"),
            _sep_watch(sym("SECURE_DMA_REG_MAP_BASE_ADDR"), block_size("SECURE_DMA")),
        ),
        DeadWindow(
            "wdt_timer",
            sym("WDT_TIMER_REG_MAP_BASE_ADDR"),
            0x1080_2000,
            block_size("WDT_TIMER"),
            _sep_watch(sym("WDT_TIMER_REG_MAP_BASE_ADDR"), block_size("WDT_TIMER")),
        ),
        DeadWindow(
            "aes",
            sym("AES_REG_MAP_BASE_ADDR"),
            0x1091_1000,
            block_size("AES"),
            _sep_watch(sym("AES_REG_MAP_BASE_ADDR"), block_size("AES")),
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
            0x1091_6000,
            ot_reg_map_size("edn"),
            _ot_watch("edn", EDN_BASE, ot_reg_map_size("edn")),
        ),
        DeadWindow(
            "entropy_src",
            esrc_base,
            0x1091_7000,
            ot_reg_map_size("entropy_source"),
            _ot_watch("entropy_source", esrc_base, ot_reg_map_size("entropy_source")),
        ),
        DeadWindow(
            "km_mailbox",
            sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR"),
            0x1092_1000,
            block_size("KM_MAILBOX_SEP"),
            _sep_watch(
                sym("KM_MAILBOX_SEP_REG_MAP_BASE_ADDR"),
                block_size("KM_MAILBOX_SEP"),
            ),
        ),
        DeadWindow(
            "lifecycle",
            sym("SEP_LIFECYCLE_CTRL_REG_MAP_BASE_ADDR"),
            0x1092_0000,
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
            0x10C0_0000,
            block_size("SPI_CONTROLLER"),
            _sep_watch(
                sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR"),
                block_size("SPI_CONTROLLER"),
            ),
        ),
    )


# (window name, addr, "r"|"w") — the #228 wrap set. Every seed probes all of them.
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
        probes = [
            DeadProbe(name, addr, op, True)
            for name, addr, op in DEADSPACE_ANCHORS
        ]
        rng = SepSeededRng(seed)
        taken = {(p.window, p.addr, p.op) for p in probes}
        for win in self.windows.values():
            if win.dead_lo >= win.dead_hi:
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
        self.probes = tuple(probes)

    def summary(self) -> str:
        n_anchor = sum(1 for p in self.probes if p.anchor)
        n_rand = len(self.probes) - n_anchor
        return (
            f"seed={self.seed} probes={len(self.probes)} "
            f"anchors={n_anchor} random={n_rand} windows={len(self.windows)}"
        )


class SepDeadspace:
    """Snapshot allocated registers, probe a dead offset, compare."""

    def __init__(self, test) -> None:
        self.test = test
        self.log = test.logger

    async def _access(
        self, op: SepAxiOp, addr: int, *, wdata: int = 0, expect_error: bool = False,
    ) -> tuple[int, int, bool]:
        seq = SepAxiAccessSeq(
            f"dead_{op.value}_0x{addr:08x}",
            op=op, addr=addr, wdata=wdata, length=4, size=2,
            expect_error=expect_error,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF, seq.timed_out

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
                win.name, len(volatile))
        return snap

    async def restore(self, snap: dict[int, int]) -> None:
        for addr, val in snap.items():
            await self._access(SepAxiOp.WRITE, addr, wdata=val)

    async def probe(self, win, item: DeadProbe, snap: dict[int, int]) -> list[str]:
        """Return failure strings. Empty means this probe matched the spec."""
        fails: list[str] = []
        self.test.env.axi_monitor.arm_expected_decerr(1)
        if item.op == "w":
            resp, _rd, timed_out = await self._access(
                SepAxiOp.WRITE, item.addr, wdata=0xFFFF_FFFF, expect_error=True,
            )
        else:
            resp, rdata, timed_out = await self._access(
                SepAxiOp.READ, item.addr, expect_error=True,
            )
            if resp == RESP_OKAY:
                for live_addr, live_val in snap.items():
                    if rdata == live_val:
                        fails.append(
                            f"{win.name} read 0x{item.addr:08x} OKAY "
                            f"rdata=0x{rdata:08x} aliases 0x{live_addr:08x}"
                        )
                        break
        if timed_out:
            fails.append(f"{win.name} {item.op} 0x{item.addr:08x} timed out")
            return fails
        if resp == RESP_OKAY:
            fails.append(
                f"{win.name} {item.op} 0x{item.addr:08x} resp=OKAY, "
                f"expected refuse (allocated ends at +0x{win.alloc:x})"
            )
        # A read of a dead offset must not return a live register's value.
        # Write probes also require the allocated image to stay put: a
        # DECERR/SLVERR that still stores is the wrap this entry exists to
        # catch. Read probes skip that compare — health-test counters move
        # on their own and would false-fail it.
        if item.op == "w":
            after = {}
            for addr in snap:
                resp_a, val, _to = await self._access(SepAxiOp.READ, addr)
                if resp_a == RESP_OKAY:
                    after[addr] = val
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
                fails.append(
                    f"{win.name} {item.op} 0x{item.addr:08x} changed live "
                    f"register(s) {detail}"
                )
                await self.restore(snap)
        return fails
