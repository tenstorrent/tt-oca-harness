# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Channel-timing superset for sep_axi_superset_test.

Crosses the stimulus axes that a slave must tolerate and that nothing in the
SEP environment previously varied:

* **write order** -- AW first, W first, or both in the same cycle. AXI channels
  are independent (IHI 0022 A3.3) and all three are legal. A slave that latches
  a pending-write flag on AW accept and consumes it on W accept works only for
  AW-first; the other two orderings drop the write or misapply it to the next
  one, and the response is OKAY either way.
* **transfer size** -- 1, 2 and 4 byte beats, which also varies the byte lanes.
* **response backpressure** -- B and R held off for a few cycles.

The first two axes are walked exhaustively on every seed, because both are
small and leaving them to chance meant some runs covered neither. The seed
varies the staged data and the backpressure depth, so a failing run replays
under ``--stage sim --seed N``.

Every cell writes a known word and reads it back, so a dropped or misapplied
write fails on the data even though the response was clean. That data compare
is the point: the response channel cannot report this class of defect.

Coverage is tallied per cell and reported. A cell that could not run is
recorded with its reason -- silent truncation would read as full coverage.
"""

from __future__ import annotations

from dataclasses import dataclass

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from ocah_axi_vip import AxiTimingProfile
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

RESP_OKAY = 0

SIZE_BYTES = {0: 1, 1: 2, 2: 4}

# Scratch storage: plain RW, no side effects. Not restored -- each cell
# primes the word itself, so no cell depends on what the last one left.
TARGET = sym("SEP_SCRATCH_COLD_SCRATCH_0__REG_ADDR")
TARGET_ALT = sym("SEP_SCRATCH_WARM_SCRATCH_0__REG_ADDR")

# The three legal write orderings, as (aw_delay, w_delay) offsets. The seed
# scales them; the ordering itself is fixed so every run covers all three.
WRITE_ORDERS: tuple[tuple[str, int, int], ...] = (
    ("same-cycle", 0, 0),
    ("aw-first", 0, 1),
    ("w-first", 1, 0),
)


@dataclass(frozen=True)
class SupersetCell:
    """One (write order x size) cell with its staged data and timing."""

    order: str
    size: int
    addr: int
    value: int
    profile: AxiTimingProfile

    @property
    def key(self) -> tuple[str, int]:
        return (self.order, SIZE_BYTES[self.size])


class SepAxiSupersetCfg:
    """Exhaustive order x size cells; seed varies data and stall depth."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        cells: list[SupersetCell] = []
        for order, aw_off, w_off in WRITE_ORDERS:
            for size in sorted(SIZE_BYTES):
                nbytes = SIZE_BYTES[size]
                # Stall depth is seeded; the ordering is not. Scale by at
                # least 1 so an offset of 1 always separates the channels.
                depth = 1 + rng.randrange(0, 4)
                profile = AxiTimingProfile(
                    aw_delay=aw_off * depth,
                    w_delay=w_off * depth,
                    b_ready_delay=rng.randrange(0, 3),
                    r_ready_delay=rng.randrange(0, 3),
                )
                addr = TARGET if rng.getrandbits(1) else TARGET_ALT
                value = rng.getrandbits(8 * nbytes)
                cells.append(SupersetCell(order, size, addr, value, profile))
        self.cells = tuple(cells)

    def n_cells(self) -> int:
        return len(WRITE_ORDERS) * len(SIZE_BYTES)

    def summary(self) -> str:
        orders = ",".join(o for o, _a, _w in WRITE_ORDERS)
        sizes = ",".join(f"{SIZE_BYTES[s]}B" for s in sorted(SIZE_BYTES))
        return (
            f"seed={self.seed} cells={len(self.cells)}/{self.n_cells()} "
            f"orders=[{orders}] sizes=[{sizes}]"
        )


class SepAxiSuperset:
    """Applies each timing profile and checks the data survived it."""

    def __init__(self, test) -> None:
        self.test = test
        self.covered: dict[tuple[str, int], int] = {}
        self.dropped: dict[tuple[str, int], str] = {}

    def _driver(self):
        """The VIP master driver behind the SEP agent.

        env.axi_agent (SepAxiAgent) -> .driver (SepAxiDriver, the pyuvm
        adapter) -> .axi (OcahAxiMasterSequence) -> .driver (the VIP master).
        Raises rather than returning None: a missing handle means no timing
        profile is applied, and every cell would then be dropped while the
        test still reported cells.
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

    async def _rd(self, addr: int, *, size: int = 2) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"sup_rd_0x{addr:08x}", op=SepAxiOp.READ, addr=addr,
            length=SIZE_BYTES[size], size=size,
        )
        await self.test.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, size: int = 2) -> int:
        seq = SepAxiAccessSeq(
            f"sup_wr_0x{addr:08x}", op=SepAxiOp.WRITE, addr=addr, wdata=data,
            length=SIZE_BYTES[size], size=size,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def run_cell(self, cell: SupersetCell) -> str | None:
        """None when the cell passed. A string names the failure."""
        drv = self._driver()
        nbytes = SIZE_BYTES[cell.size]
        lane_mask = (1 << (8 * nbytes)) - 1
        # Prime with the complement so the write is always observable.
        prime = (~cell.value) & 0xFFFF_FFFF

        drv.set_timing(AxiTimingProfile())          # prime at default timing
        if await self._wr(cell.addr, prime) != RESP_OKAY:
            self.dropped[cell.key] = "prime write refused"
            return None
        resp, staged = await self._rd(cell.addr)
        if resp != RESP_OKAY or staged != prime:
            self.dropped[cell.key] = (
                f"prime readback 0x{staged:08x} != 0x{prime:08x}"
            )
            return None

        drv.set_timing(cell.profile)
        try:
            resp = await self._wr(cell.addr, cell.value, size=cell.size)
            if resp != RESP_OKAY:
                return (
                    f"[{cell.order} {nbytes}B] write 0x{cell.addr:08x} "
                    f"resp={resp}, expected OKAY -- the ordering is legal AXI"
                )
            # Read at default timing so the compare tests the write, not the read.
            drv.set_timing(AxiTimingProfile())
            resp, after = await self._rd(cell.addr)
        finally:
            drv.set_timing(AxiTimingProfile())

        if resp != RESP_OKAY:
            return f"[{cell.order} {nbytes}B] readback resp={resp}"

        want = (prime & ~lane_mask) | (cell.value & lane_mask)
        if after != want:
            hint = (
                " -- the write did not land; a slave that latches its pending "
                "flag on AW accept fails exactly here"
                if after == prime else ""
            )
            return (
                f"[{cell.order} {nbytes}B] 0x{cell.addr:08x}: wrote "
                f"0x{cell.value:x} over 0x{prime:08x}, read 0x{after:08x}, "
                f"expected 0x{want:08x} ({cell.profile.summary()}){hint}"
            )
        self.covered[cell.key] = self.covered.get(cell.key, 0) + 1
        return None

    def coverage_report(self, cfg: SepAxiSupersetCfg) -> str:
        want = {
            (o, SIZE_BYTES[s]) for o, _a, _w in WRITE_ORDERS
            for s in sorted(SIZE_BYTES)
        }
        hit = set(self.covered)
        missing = sorted(want - hit)
        return (
            f"{len(hit)}/{len(want)} cells covered"
            + (f"; NOT covered: {missing}" if missing else "")
            + (f"; dropped: {dict(self.dropped)}" if self.dropped else "")
        )


def _selftest() -> None:
    cfg = SepAxiSupersetCfg(1)
    assert len(cfg.cells) == cfg.n_cells() == 9, f"{len(cfg.cells)} cells"
    # Every ordering and size present on every seed.
    for seed in (1, 2, 3):
        c = SepAxiSupersetCfg(seed)
        keys = {cell.key for cell in c.cells}
        assert len(keys) == 9, f"seed {seed} covers only {len(keys)} cells"
        for cell in c.cells:
            assert cell.profile.write_order == cell.order, (
                f"profile {cell.profile.summary()} is not {cell.order}")
            assert cell.value < (1 << (8 * SIZE_BYTES[cell.size])), cell
    # Seed changes data, not coverage.
    a, b = SepAxiSupersetCfg(1), SepAxiSupersetCfg(2)
    assert {c.key for c in a.cells} == {c.key for c in b.cells}
    assert [c.value for c in a.cells] != [c.value for c in b.cells]


_selftest()
