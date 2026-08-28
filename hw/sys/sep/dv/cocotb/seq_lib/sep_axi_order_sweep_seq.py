# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AW/W ordering sweep across every register the export says is safe to write.

sep_axi_superset_seq proves the three legal write orderings survive on two
scratch words. That proves the stimulus, not the fabric: a register adapter
that mishandles a channel ordering does so at its own AXI port, and every
block behind the crossbar has its own adapter. This sweep drives the same
three orderings at every register bit-bash already establishes as write-safe
storage, so an adapter that only works when AW leads W is caught wherever it
sits.

Two checks per cell, because an ordering bug has two distinct signatures:

* **Dropped write.** Prime with the complement, write under the ordering, read
  back. An adapter that latches its pending-write flag on AW accept and then
  reads that flag in the same cycle the W arrives answers OKAY while dropping
  the data. Only a data compare sees it.
* **Displaced write.** After the ordering write, write a DIFFERENT register in
  the same block at default timing and read that one back. A stale pending
  flag left set by the first access makes the next W handshake in the block
  commit the wrong data. The dropped-write check cannot see this: it reads the
  register that was written, and the corruption lands on the neighbour.

The register inventory and the exclusion reasons come from
sep_reg_bit_bash_seq, not a second list here. Two sweeps disagreeing about
which registers are safe to write would be a defect in itself, and a register
this sweep must skip is one bit-bash must skip too.

Ordering is a fabric property and applies to every register; transfer size is
a lane property and needs one target. So the sweep runs 4-byte beats over the
whole inventory, and crosses ordering with 1/2/4-byte sizes on the scratch
words, where a narrow write has no side effect and the lane model is exact.
sep_axi_strobe_window_test owns the strobe and window-data axis at default
timing; the size cells here exist to cross size WITH ordering, which no other
test does.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_reg_meta import RegInfo, iter_register_walk
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_reg_bit_bash_seq import (
    TOUCH_BLOCKS,
    touch_reason,
    touch_write_value,
    write_mask,
    write_reason,
)

RESP_OKAY = 0
SIZE_BYTES = {0: 1, 1: 2, 2: 4}
SIZE_4B = 2

# Blocks whose registers are plain scratch storage: a sub-word write there has
# no side effect and the surviving lanes are exactly the AXI lane rule, so the
# size axis can be crossed with ordering without modelling a block's own
# behaviour.
SIZE_CROSS_BLOCKS = ("SEP_SCRATCH_COLD", "SEP_SCRATCH_WARM")

# The three legal write orderings, as (aw_delay, w_delay) offsets. The seed
# scales the separation; the ordering itself is fixed, so every seed covers
# all three on every register.
WRITE_ORDERS: tuple[tuple[str, int, int], ...] = (
    ("same-cycle", 0, 0),
    ("aw-first", 0, 1),
    ("w-first", 1, 0),
)


@dataclass(frozen=True)
class OrderCell:
    """One register under one write ordering, with its displacement witness."""

    order: str
    info: RegInfo
    value: int
    size: int
    profile: AxiTimingProfile
    # The register read back to catch a displaced write: a different register
    # in the same block. None when the block offers only one candidate, and
    # the cell then checks the dropped-write signature alone.
    witness: RegInfo | None
    witness_value: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.order, self.info.block, self.info.name, self.size)

    @property
    def cross_key(self) -> tuple[str, int]:
        """The (ordering, size) cell this register contributes to."""
        return (self.order, SIZE_BYTES[self.size])


def sweep_candidates() -> tuple[list[RegInfo], dict[str, int]]:
    """Registers to sweep, and the skip tally by reason.

    Two sources, both already justified in sep_reg_bit_bash_seq:

    * ``write_reason() is None`` -- the no-side-effect blocks whose full write
      bash is safe (scratch, CPU control, the inbound filter windows).
    * ``touch_reason() is None`` restricted to ``TOUCH_BLOCKS`` -- plain RW
      storage inside the other major IPs. Restricted deliberately: a block
      outside that list may be held in reset or need an init sequence, and a
      readback mismatch there would report bring-up state as an ordering bug.
    """
    skipped: dict[str, int] = defaultdict(int)
    out: list[RegInfo] = []
    seen: set[tuple[str, str]] = set()
    for info in iter_register_walk().regs:
        why_w = write_reason(info)
        if why_w is None:
            out.append(info)
            seen.add((info.block, info.name))
            continue
        why_t = touch_reason(info)
        if why_t is None and info.block in TOUCH_BLOCKS:
            out.append(info)
            seen.add((info.block, info.name))
            continue
        # Counted under the write reason: that is the sweep this register is
        # being kept out of. A silent skip is a bug.
        skipped[why_w] += 1
    return out, dict(skipped)


class SepAxiOrderSweepCfg:
    """Every (write-safe register x ordering) cell. Seed varies data only."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        regs, self.skipped = sweep_candidates()
        if not regs:
            raise RuntimeError("ordering sweep is empty after exclusions")
        self.regs = tuple(regs)

        by_block: dict[str, list[RegInfo]] = defaultdict(list)
        for info in regs:
            by_block[info.block].append(info)
        self.blocks = tuple(sorted(by_block))

        cells: list[OrderCell] = []
        for info in regs:
            peers = [p for p in by_block[info.block] if p.name != info.name]
            # 4-byte everywhere; the narrow sizes only where a sub-word write
            # has no side effect and the surviving lanes are exactly the AXI
            # lane rule.
            sizes = (SIZE_4B,)
            if info.block in SIZE_CROSS_BLOCKS:
                sizes = tuple(sorted(SIZE_BYTES))
            for order, aw_off, w_off in WRITE_ORDERS:
                for size in sizes:
                    # At least 1 so an offset of 1 always separates the channels.
                    depth = 1 + rng.randrange(0, 4)
                    profile = AxiTimingProfile(
                        aw_delay=aw_off * depth,
                        w_delay=w_off * depth,
                        b_ready_delay=rng.randrange(0, 3),
                        r_ready_delay=rng.randrange(0, 3),
                    )
                    mask = write_mask(info)
                    value = touch_write_value(info.reset, mask, rng)
                    witness = (
                        peers[rng.randrange(0, len(peers))] if peers else None
                    )
                    w_value = 0
                    if witness is not None:
                        w_value = touch_write_value(
                            witness.reset, write_mask(witness), rng
                        )
                    cells.append(OrderCell(
                        order, info, value, size, profile, witness, w_value
                    ))
        self.cells = tuple(cells)

    def n_cells(self) -> int:
        wide = sum(1 for i in self.regs if i.block not in SIZE_CROSS_BLOCKS)
        narrow = len(self.regs) - wide
        return len(WRITE_ORDERS) * (wide + narrow * len(SIZE_BYTES))

    def cross_cells(self) -> set[tuple[str, int]]:
        """Every (ordering, size) pair the sweep must report a compare for."""
        return {
            (order, SIZE_BYTES[s])
            for order, _a, _w in WRITE_ORDERS
            for s in sorted(SIZE_BYTES)
        }

    def summary(self) -> str:
        orders = ",".join(o for o, _a, _w in WRITE_ORDERS)
        skips = " ".join(f"{k}={v}" for k, v in sorted(self.skipped.items()))
        return (
            f"seed={self.seed} regs={len(self.regs)} blocks={len(self.blocks)} "
            f"cells={len(self.cells)}/{self.n_cells()} orders=[{orders}] "
            f"skipped: {skips}"
        )


class SepAxiOrderSweep:
    """Drives each cell and checks both ordering-bug signatures."""

    def __init__(self, test) -> None:
        self.test = test
        self.covered: dict[str, int] = defaultdict(int)
        self.cross_covered: dict[tuple[str, int], int] = defaultdict(int)
        self.blocks_hit: set[str] = set()
        self.witnessed = 0
        self.dropped: dict[tuple[str, str, str], str] = {}

    def _driver(self):
        """The VIP master driver behind the SEP agent.

        Raises rather than returning None: without a timing handle no profile
        is applied, and the sweep would report orderings it never drove.
        """
        agent = self.test.env.axi_agent
        seq = getattr(getattr(agent, "driver", None), "axi", None)
        drv = getattr(seq, "driver", None)
        if drv is None or not hasattr(drv, "set_timing"):
            raise RuntimeError(
                "no VIP master with set_timing() behind env.axi_agent.driver"
                ".axi.driver; the ordering sweep cannot apply a timing "
                "profile and would report cells it never drove"
            )
        return drv

    async def _rd(self, addr: int, *, size: int = SIZE_4B) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"ord_rd_0x{addr:08x}", op=SepAxiOp.READ, addr=addr,
            length=SIZE_BYTES[size], size=size,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, size: int = SIZE_4B) -> int:
        nbytes = SIZE_BYTES[size]
        # The item carries exactly nbytes; a wider value is a caller error the
        # driver reports as OverflowError rather than as a lane mismatch.
        seq = SepAxiAccessSeq(
            f"ord_wr_0x{addr:08x}", op=SepAxiOp.WRITE, addr=addr,
            wdata=data & ((1 << (8 * nbytes)) - 1),
            length=nbytes, size=size,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def _commit(self, info: RegInfo, data: int, *, size: int = SIZE_4B) -> int:
        """One register write, honouring a shadowed register's two-write commit.

        A shadowed register latches on the second identical write, so a single
        write leaves the stored value unchanged and would read back as a lost
        write. Both writes go out under whatever timing profile is active, so
        the ordering under test applies to each of them.
        """
        resp = await self._wr(info.addr, data, size=size)
        if resp == RESP_OKAY and "SHADOWED" in info.name:
            resp = await self._wr(info.addr, data, size=size)
        return resp

    async def run_cell(self, cell: OrderCell) -> str | None:
        """None when the cell passed. A string names the failure."""
        drv = self._driver()
        info = cell.info
        nbytes = SIZE_BYTES[cell.size]
        # A narrow write reaches only its own lanes; the rest of the word must
        # survive. Anchored at the register address, so the lanes are the low
        # nbytes of the word.
        lane_mask = (1 << (8 * nbytes)) - 1
        mask = write_mask(info) & lane_mask
        tag = f"[{cell.order} {nbytes}B {info.block}.{info.name}]"

        drv.set_timing(AxiTimingProfile())          # prime at default timing
        # Prime with the complement under the mask so the write always
        # changes something and a dropped write cannot pass by luck.
        prime = (info.reset & ~mask) | (~cell.value & mask)
        if await self._commit(info, prime) != RESP_OKAY:
            self.dropped[cell.key] = "prime write refused"
            return None
        resp, staged = await self._rd(info.addr)
        if resp != RESP_OKAY or (staged & mask) != (prime & mask):
            self.dropped[cell.key] = (
                f"prime readback 0x{staged:08x} != 0x{prime:08x} under "
                f"mask 0x{mask:08x}"
            )
            return None

        drv.set_timing(cell.profile)
        try:
            resp = await self._commit(info, cell.value, size=cell.size)
            if resp != RESP_OKAY:
                return (
                    f"{tag} write 0x{info.addr:08x} resp={resp}, expected "
                    f"OKAY -- all three orderings are legal AXI"
                )
            # Read at default timing so the compare tests the write, not the read.
            drv.set_timing(AxiTimingProfile())
            resp, after = await self._rd(info.addr)
        finally:
            drv.set_timing(AxiTimingProfile())

        if resp != RESP_OKAY:
            return f"{tag} readback resp={resp}"

        if (after & mask) != (cell.value & mask):
            hint = (
                " -- the write did not land; an adapter that latches its "
                "pending-write flag on AW accept and reads it the same cycle "
                "W arrives fails exactly here"
                if (after & mask) == (prime & mask) else ""
            )
            return (
                f"{tag} 0x{info.addr:08x}: wrote 0x{cell.value:08x} over "
                f"0x{prime:08x}, read 0x{after:08x} under mask 0x{mask:08x} "
                f"({cell.profile.summary()}){hint}"
            )

        # Displaced-write check: the NEXT write in this block must land on the
        # register it addresses, not on this one. A pending flag the ordering
        # left set commits the next W to the wrong target.
        if cell.witness is not None:
            wit = cell.witness
            wmask = write_mask(wit)
            if await self._commit(wit, cell.witness_value) != RESP_OKAY:
                self.dropped[cell.key] = "witness write refused"
            else:
                resp, wafter = await self._rd(wit.addr)
                if resp != RESP_OKAY:
                    self.dropped[cell.key] = f"witness readback resp={resp}"
                elif (wafter & wmask) != (cell.witness_value & wmask):
                    return (
                        f"{tag} follow-on write to {wit.block}.{wit.name} "
                        f"(0x{wit.addr:08x}) wrote 0x{cell.witness_value:08x}, "
                        f"read 0x{wafter:08x} under mask 0x{wmask:08x} -- a "
                        f"pending-write flag left set by the {cell.order} "
                        f"access displaced the next write in the block"
                    )
                else:
                    # Re-read the swept register: the witness write must not
                    # have landed here either.
                    resp, again = await self._rd(info.addr)
                    if resp == RESP_OKAY and (again & mask) != (
                        cell.value & mask
                    ):
                        return (
                            f"{tag} 0x{info.addr:08x} changed to 0x{again:08x} "
                            f"when {wit.name} was written -- the {cell.order} "
                            f"access left this register latched as the target"
                        )
                    self.witnessed += 1

        self.covered[cell.order] += 1
        self.cross_covered[cell.cross_key] += 1
        self.blocks_hit.add(info.block)
        return None

    def coverage_report(self, cfg: SepAxiOrderSweepCfg) -> str:
        want = {o for o, _a, _w in WRITE_ORDERS}
        missing = sorted(want - set(self.covered))
        cross_missing = sorted(cfg.cross_cells() - set(self.cross_covered))
        counts = " ".join(f"{k}={v}" for k, v in sorted(self.covered.items()))
        return (
            f"{counts}; blocks={len(self.blocks_hit)}/{len(cfg.blocks)}; "
            f"order x size {len(self.cross_covered)}/{len(cfg.cross_cells())}; "
            f"displacement witnesses={self.witnessed}"
            + (f"; NOT covered: {missing}" if missing else "")
            + (f"; order x size NOT covered: {cross_missing}"
               if cross_missing else "")
            + (f"; dropped: {len(self.dropped)}" if self.dropped else "")
        )


def _selftest() -> None:
    cfg = SepAxiOrderSweepCfg(1)
    assert cfg.regs, "no registers in the ordering sweep"
    assert len(cfg.cells) == cfg.n_cells(), f"{len(cfg.cells)} cells"
    # Every ordering present on every register, every seed.
    for seed in (1, 2, 3):
        c = SepAxiOrderSweepCfg(seed)
        by_reg: dict[tuple[str, str], set[str]] = defaultdict(set)
        for cell in c.cells:
            by_reg[(cell.info.block, cell.info.name)].add(cell.order)
            assert cell.profile.write_order == cell.order, (
                f"profile {cell.profile.summary()} is not {cell.order}")
            assert cell.value < (1 << 32), cell
        for reg, orders in by_reg.items():
            assert len(orders) == len(WRITE_ORDERS), f"{reg} covers {orders}"
        # The nine (ordering x size) cells must all be constructible, or the
        # sweep does not subsume the axis it claims to.
        assert {cell.cross_key for cell in c.cells} == c.cross_cells(), (
            f"seed {seed} does not build every ordering x size cell"
        )
    # The sweep must reach past the scratch words, or it proves only stimulus.
    assert len(cfg.blocks) > 1, f"only {cfg.blocks} in the sweep"
    assert any(b in TOUCH_BLOCKS for b in cfg.blocks), (
        f"no IP block from TOUCH_BLOCKS reached: {cfg.blocks}"
    )
    # Seed changes data, not coverage.
    a, b = SepAxiOrderSweepCfg(1), SepAxiOrderSweepCfg(2)
    assert {c.key for c in a.cells} == {c.key for c in b.cells}, (
        "seed changed which cells run; it must change data only"
    )


_selftest()
