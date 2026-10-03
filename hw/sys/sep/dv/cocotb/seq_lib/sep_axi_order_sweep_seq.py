# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AW/W ordering sweep across every register the export says is safe to write.

Every block behind the crossbar has its own register adapter, so one scratch
word does not stand for the others. This sweep presents the three orderings at
the master port for every register bit-bash already establishes as write-safe
storage, and grades each write end to end at that register. The crossbar can
re-serialize a write before a block adapter sees it, so the sweep makes no
claim about the ordering each adapter port receives.

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
from sep_reg_meta import RegInfo, iter_register_walk, sym

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

# Blocks kept out of the sweep for a reason that is about the access, not
# about the register. Each entry states what a probe there would measure
# instead of the ordering contract.
BLOCK_EXCLUDE: dict[str, str] = {
    # aon_timer runs on clk_wdt at 5000ns against a 5ns system clock, so one
    # register access crosses into a domain 1000x slower and the AXI timeout
    # of 50000ns spans about ten of its clock edges. Whether a round trip
    # fits depends on the phase the access arrives on, so a probe here
    # measures CDC latency against the timeout, not whether AW and W were
    # delivered. sep_reg_bit_bash_rand_test covers the block's storage with a
    # single touch.
    "WDT_TIMER": "slow always-on clock domain; the access outruns the AXI timeout",
}

# Blocks kept out of the sweep when it is driven from the SMN inbound master,
# for a reason that belongs to that path. Each entry names the RTL fact.
BLOCK_EXCLUDE_M_AXI: dict[str, str] = {
    # Every INBOUND_FILTER_CTRL_<n>_ block IS the rule set that gates this bus.
    # hw/sys/sep/doc/fabric.adoc (Traffic Filter Decode) states the inbound
    # filter has 16 entries and that each entry is one filter_ctrl register
    # triple -- FILTER_CONFIG, START_ADDR, END_ADDR -- so the swept registers are
    # that entry's own address window. A
    # sweep write there moves the address window of the access in flight, so the
    # cell would measure filter reprogramming rather than an adapter's channel
    # ordering. Reaching them from m_axi at all would also need an allow window
    # over the filter CSR bank, which is the software hole
    # sep_fabric_inbound_filter_rule_matrix_test asserts must stay shut. The
    # CPU-LSU sweep covers these registers; that path has no inbound filter.
    f"INBOUND_FILTER_CTRL_{n}_": "inbound-filter rule bank: the entry's own address window gates this "
    "bus, so a sweep write reprograms the path under the walk"
    for n in range(16)
}

# Coarse inbound-filter allow windows for the m_axi walk, as
# (name, start, end_inclusive).
#
# The comparison granule is the specification's, not the design's:
# hw/ip/axi_filter/doc/index.adoc (Address Range Granule) states that with
# allow_burst = 0 the granule is the data bus width -- 8 bytes on a 64-bit bus
# -- and address bits [2:0] are ignored, that START_ADDR widens *down* to the
# base of its granule and END_ADDR widens *up* to the top of its granule. So END
# below is the last byte address inside the window and reads back with its low
# three bits set. allow_burst stays 0, so the 4 KB page widen does not apply.
#
# Five windows out of the sixteen filter entries, coarse so the walk needs no
# reprogramming mid-sweep. None of them covers the filter CSR bank at
# INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR: the external master must not be able
# to rewrite the rules that gate it.
#
# Both bounds come from the generated register map. START is the
# <BLOCK>_REG_MAP_BASE_ADDR of the first block in the window. END is the last
# byte of the block span (the last block's base plus its _REG_MAP_SIZE, minus 1),
# rounded up to the top of its 4 KB page. The page rounding is this sequence's
# choice of a coarse window, not a filter rule. The one exception is cpu_ctrl:
# it covers only the first 4 KB page of SEP_CPU_CTRL, which holds every
# SEP_CPU_CTRL register the walk sweeps. The block continues into a second page
# (SEP_CPU_CTRL_SEP_VERSION_ID_REG_ADDR) that the window leaves out.
_WINDOW_PAGE = 0x1000


def _page_top(addr: int) -> int:
    """Return the last byte address of the 4 KB page that holds ``addr``."""
    return addr | (_WINDOW_PAGE - 1)


def _block_last_byte(block: str) -> int:
    """Return the last byte address of ``block`` in the generated register map."""
    return sym(f"{block}_REG_MAP_BASE_ADDR") + sym(f"{block}_REG_MAP_SIZE") - 1


M_AXI_ALLOW_WINDOWS: tuple[tuple[str, int, int], ...] = (
    # SECURE_DMA, WDT_TIMER, SEP_SCRATCH_COLD and SEP_SCRATCH_WARM.
    (
        "dma_csr+scratch",
        sym("SECURE_DMA_REG_MAP_BASE_ADDR"),
        _page_top(_block_last_byte("SEP_SCRATCH_WARM")),
    ),
    # OTBN through KMAC.
    ("crypto", sym("OTBN_REG_MAP_BASE_ADDR"), _page_top(_block_last_byte("KMAC"))),
    # Outbound and inbound mailbox 0.
    (
        "mailbox",
        sym("AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR"),
        _page_top(_block_last_byte("AXIL_MAILBOX_INBOUND_MAILBOX_0")),
    ),
    (
        "cpu_ctrl",
        sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR"),
        _page_top(sym("SEP_CPU_CTRL_REG_MAP_BASE_ADDR")),
    ),
    (
        "spi",
        sym("SPI_CONTROLLER_REG_MAP_BASE_ADDR"),
        _page_top(_block_last_byte("SPI_CONTROLLER")),
    ),
)

# A floor on the m_axi walk, set to the count the walk presents: 75 registers
# over 11 blocks, three orderings each. BLOCK_EXCLUDE_M_AXI is the only
# reduction the path justifies, so a map or routing change that removes even one
# register must fail here rather than let a shrinking walk report a clean pass.
M_AXI_CELL_FLOOR = 225

# The same floor for s_axi, set to the count the walk presents, like
# M_AXI_CELL_FLOOR: slack here is registers that can go missing without failing
# anything, and three orderings per register means even a small slack hides
# several of them.
S_AXI_CELL_FLOOR = 321

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
    # Which software-usable bit of the witness to flip, as an index into its
    # mask bits. A bit rather than a value: the follow-on write has to differ
    # from whatever the witness holds when the cell reaches it, which is not
    # known when the cell is built.
    witness_bit: int

    @property
    def key(self) -> tuple[str, str, str, int]:
        return (self.order, self.info.block, self.info.name, self.size)

    @property
    def cross_key(self) -> tuple[str, int]:
        """The (ordering, size) cell this register contributes to."""
        return (self.order, SIZE_BYTES[self.size])


def block_exclusions(bus: str) -> dict[str, str]:
    """Block -> reason, for the bus the sweep is driven from.

    A block excluded on one bus stays swept on the other, so the reason has to
    be looked up per walk rather than folded into one table.
    """
    out = dict(BLOCK_EXCLUDE)
    if bus == "m_axi":
        out.update(BLOCK_EXCLUDE_M_AXI)
    return out


def sweep_candidates(bus: str = "s_axi") -> tuple[list[RegInfo], dict[str, int]]:
    """Registers to sweep, and the skip tally by reason.

    Two sources, both already justified in sep_reg_bit_bash_seq:

    * ``write_reason() is None`` -- the no-side-effect blocks whose full write
      bash is safe (scratch, CPU control, the inbound filter windows).
    * ``touch_reason() is None`` restricted to ``TOUCH_BLOCKS`` -- plain RW
      storage inside the other major IPs. Restricted to that list: a block
      outside that list may be held in reset or need an init sequence, and a
      readback mismatch there would report bring-up state as an ordering bug.

    ``block_exclusions(bus)`` then removes blocks where the access itself,
    rather than the register, would decide the result.
    """
    skipped: dict[str, int] = defaultdict(int)
    out: list[RegInfo] = []
    seen: set[tuple[str, str]] = set()
    excluded = block_exclusions(bus)
    for info in iter_register_walk().regs:
        block_why = excluded.get(info.block)
        if block_why is not None:
            skipped[block_why] += 1
            continue
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

    def __init__(self, seed: int, *, bus: str = "s_axi") -> None:
        self.seed = seed
        self.bus = bus
        rng = SepSeededRng(seed)
        regs, self.skipped = sweep_candidates(bus)
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
                    witness = peers[rng.randrange(0, len(peers))] if peers else None
                    w_bit = rng.randrange(0, 32)
                    cells.append(OrderCell(order, info, value, size, profile, witness, w_bit))
        self.cells = tuple(cells)

    def n_cells(self) -> int:
        wide = sum(1 for i in self.regs if i.block not in SIZE_CROSS_BLOCKS)
        narrow = len(self.regs) - wide
        return len(WRITE_ORDERS) * (wide + narrow * len(SIZE_BYTES))

    def n_witnessed(self) -> int:
        """Cells that carry the displacement check.

        A block with only one swept register offers no second register to
        write, so its cells prove the land contract alone. The count is
        stated here so the test can require exactly it rather than requiring
        merely that some cell ran.
        """
        return sum(1 for c in self.cells if c.witness is not None)

    def cross_cells(self) -> set[tuple[str, int]]:
        """Every (ordering, size) pair the sweep must report a compare for."""
        return {
            (order, SIZE_BYTES[s]) for order, _a, _w in WRITE_ORDERS for s in sorted(SIZE_BYTES)
        }

    def summary(self) -> str:
        orders = ",".join(o for o, _a, _w in WRITE_ORDERS)
        skips = " ".join(f"{k}={v}" for k, v in sorted(self.skipped.items()))
        return (
            f"seed={self.seed} bus={self.bus} regs={len(self.regs)} "
            f"blocks={len(self.blocks)} "
            f"cells={len(self.cells)}/{self.n_cells()} orders=[{orders}] "
            f"skipped: {skips}"
        )


class SepAxiOrderSweep:
    """Drives each cell and checks both ordering-bug signatures."""

    def __init__(self, test, *, bus: str = "s_axi") -> None:
        self.test = test
        # Which TB-driven bus this walk drives. s_axi is the CPU-LSU splice;
        # m_axi is the SMN inbound master, which reaches the same adapters
        # through the inbound filter, so a block that mishandles an ordering
        # has to be caught on both.
        self.bus = bus
        env = test.env
        self._agent_name = "env.axi_agent" if bus == "s_axi" else "env.ext_axi_agent"
        self._agent = env.axi_agent if bus == "s_axi" else env.ext_axi_agent
        self._mon = env.axi_monitor if bus == "s_axi" else env.ext_axi_monitor
        self._start = test.start_seq if bus == "s_axi" else test.start_ext_seq
        self.covered: dict[str, int] = defaultdict(int)
        self.cross_covered: dict[tuple[str, int], int] = defaultdict(int)
        self.blocks_hit: set[str] = set()
        self.witnessed = 0
        self.stim_seen: dict[str, int] = defaultdict(int)
        self.hs_seen: dict[str, int] = defaultdict(int)
        self.dropped: dict[tuple[str, str, str, int], str] = {}

    def _driver(self):
        """The VIP master driver behind the SEP agent.

        Raises rather than returning None: without a timing handle no profile
        is applied, and the sweep would report orderings it never drove.
        """
        agent = self._agent
        seq = getattr(getattr(agent, "driver", None), "axi", None)
        drv = getattr(seq, "driver", None)
        if drv is None or not hasattr(drv, "set_timing"):
            raise RuntimeError(
                f"no VIP master with set_timing() behind "
                f"{self._agent_name}.driver.axi.driver on {self.bus}; the "
                f"ordering sweep cannot apply a timing profile and would "
                f"report cells it never drove"
            )
        return drv

    async def _rd(self, addr: int, *, size: int = SIZE_4B) -> tuple[int, int]:
        seq = SepAxiAccessSeq(
            f"ord_rd_0x{addr:08x}",
            op=SepAxiOp.READ,
            addr=addr,
            length=SIZE_BYTES[size],
            size=size,
        )
        await self._start(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _wr(self, addr: int, data: int, *, size: int = SIZE_4B) -> int:
        nbytes = SIZE_BYTES[size]
        # The item carries exactly nbytes; a wider value is a caller error the
        # driver reports as OverflowError rather than as a lane mismatch.
        seq = SepAxiAccessSeq(
            f"ord_wr_0x{addr:08x}",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data & ((1 << (8 * nbytes)) - 1),
            length=nbytes,
            size=size,
        )
        await self._start(seq)
        return seq.resp_code

    async def _commit(self, info: RegInfo, data: int, *, size: int = SIZE_4B) -> int:
        """One register write, honouring a shadowed register's two-write commit.

        A shadowed register latches on the second identical write, so a single
        write leaves the stored value unchanged and would read back as a lost
        write. The profile arms a one-shot release, so it shapes the FIRST
        write only: the committing second write always goes out same-cycle.
        The ordering under test is the one the register sees first, and the
        commit itself is not an ordered access.
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
        # A narrow write is compared on the lanes it addresses. Whether the
        # lanes it does NOT address survive is the strobe contract, checked by
        # sep_axi_strobe_window_test; here the question is whether the write
        # arrived at all under this channel ordering.
        lane_mask = (1 << (8 * nbytes)) - 1
        # The compare covers the whole software-usable word, not just the
        # lanes written. A narrow write must deliver its own lanes AND leave
        # the others alone, and both halves of that have to hold under a
        # non-default channel ordering.
        mask = write_mask(info)
        tag = f"[{cell.order} {nbytes}B {info.block}.{info.name}]"
        # An empty mask compares nothing while still counting as covered, so it
        # is a build error rather than a silent pass.
        assert mask != 0, (
            f"{tag} has no software-usable bit; the compare would be vacuous "
            f"but would still count toward coverage"
        )
        assert mask & lane_mask, (
            f"{tag} has no software-usable bit in the written lanes; the "
            f"write could not be observed"
        )

        drv.set_timing(AxiTimingProfile())  # prime at default timing
        # Prime the complement across the whole word, so the written lanes
        # always change and the untouched lanes hold a value a widened strobe
        # would destroy. A prime of the reset value would leave the upper
        # lanes at zero, which a strobe-ignoring write also produces.
        prime = (info.reset & ~mask) | (~cell.value & mask)
        if await self._commit(info, prime) != RESP_OKAY:
            self.dropped[cell.key] = "prime write refused"
            return None
        resp, staged = await self._rd(info.addr)
        if resp != RESP_OKAY or (staged & mask) != (prime & mask):
            self.dropped[cell.key] = (
                f"prime readback 0x{staged:08x} != 0x{prime:08x} under mask 0x{mask:08x}"
            )
            return None

        mon = self._mon
        mon.arm_write_order()
        drv.set_timing(cell.profile)
        try:
            resp = await self._commit(info, cell.value, size=cell.size)
            # Sample before the readback and the witness write, or the
            # measurement describes those instead of the profiled write.
            stim, hs = mon.last_write_stim, mon.last_write_hs
            cyc = mon.write_order_cycles
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

        # The AXI lane rule: the addressed lanes take the new data, every
        # other lane keeps what it held.
        want = (prime & ~lane_mask) | (cell.value & lane_mask)
        if (after & mask) != (want & mask):
            if (after & mask & lane_mask) == (prime & mask & lane_mask):
                hint = (
                    " -- the write did not land; an adapter that latches its "
                    "pending-write flag on AW accept and reads it the same "
                    "cycle W arrives fails exactly here"
                )
            elif (after & mask & ~lane_mask) != (prime & mask & ~lane_mask):
                hint = (
                    " -- the write reached lanes it did not address; the "
                    "strobe was widened somewhere on the path"
                )
            else:
                hint = ""
            return (
                f"{tag} 0x{info.addr:08x}: wrote 0x{cell.value:08x} over "
                f"0x{prime:08x}, read 0x{after:08x}, expected 0x{want:08x} "
                f"under mask 0x{mask:08x} ({cell.profile.summary()}){hint}"
            )

        # Displaced-write check: the NEXT write in this block must land on the
        # register it addresses, not on this one. A pending flag the ordering
        # left set commits the next W to the wrong target.
        if cell.witness is not None:
            wit = cell.witness
            wmask = write_mask(wit)
            resp, wbefore = await self._rd(wit.addr)
            if resp != RESP_OKAY:
                return (
                    f"{tag} witness {wit.block}.{wit.name} "
                    f"(0x{wit.addr:08x}) resp={resp} before the follow-on "
                    f"write"
                )
            # The follow-on value has to differ from what the witness already
            # holds. A value the register happens to contain would read back
            # correct even if the write never arrived, and the compare would
            # prove nothing. Flip one software-usable bit, chosen by the seed.
            bits = [b for b in range(32) if wmask & (1 << b)]
            flip = 1 << bits[cell.witness_bit % len(bits)]
            wvalue = (wbefore & 0xFFFF_FFFF) ^ flip

            resp = await self._commit(wit, wvalue)
            if resp != RESP_OKAY:
                return (
                    f"{tag} follow-on write to {wit.block}.{wit.name} "
                    f"(0x{wit.addr:08x}) resp={resp}, expected OKAY -- the "
                    f"{cell.order} access left the block unable to accept the "
                    f"next write"
                )
            resp, wafter = await self._rd(wit.addr)
            if resp != RESP_OKAY:
                return (
                    f"{tag} witness {wit.block}.{wit.name} readback "
                    f"resp={resp} after the follow-on write"
                )
            if (wafter & wmask) != (wvalue & wmask):
                return (
                    f"{tag} follow-on write to {wit.block}.{wit.name} "
                    f"(0x{wit.addr:08x}) wrote 0x{wvalue:08x} over "
                    f"0x{wbefore:08x}, read 0x{wafter:08x} under mask "
                    f"0x{wmask:08x} -- a pending-write flag left set by the "
                    f"{cell.order} access displaced the next write in the block"
                )
            # The swept register must not have taken the witness write either.
            resp, again = await self._rd(info.addr)
            if resp != RESP_OKAY:
                return f"{tag} 0x{info.addr:08x} re-read resp={resp}"
            if (again & mask) != (want & mask):
                return (
                    f"{tag} 0x{info.addr:08x} changed to 0x{again:08x} when "
                    f"{wit.name} was written -- the {cell.order} access left "
                    f"this register latched as the target"
                )
            self.witnessed += 1

        self.test.logger.info(
            "CHK-ORDER-STIM %s: requested=%s presented=%s handshake=%s "
            "(awv=%s wv=%s awhs=%s whs=%s) %s.%s",
            "OK " if stim == cell.order else "DIFF",
            cell.order,
            stim,
            hs,
            *cyc,
            info.block,
            info.name,
        )
        if stim != cell.order:
            return (
                f"{tag} requested {cell.order} but presented {stim} "
                f"(awvalid cycle {cyc[0]}, wvalid cycle {cyc[1]}); the "
                f"ordering under test never reached the bus"
            )
        allowed_hs = (
            (cell.order,)
            if self.bus == "m_axi" and cell.order == "w-first"
            else (cell.order, "same-cycle")
        )
        if hs not in allowed_hs:
            return (
                f"{tag} presented {stim} and the slave answered {hs}; a "
                f"handshake on {self.bus} must be one of {allowed_hs}"
            )
        self.stim_seen[stim] += 1
        if hs is not None:
            self.hs_seen[hs] += 1
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
            + (f"; order x size NOT covered: {cross_missing}" if cross_missing else "")
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
                f"profile {cell.profile.summary()} is not {cell.order}"
            )
            assert cell.value < (1 << 32), cell
        for reg, orders in by_reg.items():
            assert len(orders) == len(WRITE_ORDERS), f"{reg} covers {orders}"
        # The nine (ordering x size) cells must all be constructible, or the
        # sweep does not subsume the axis it claims to.
        assert {cell.cross_key for cell in c.cells} == c.cross_cells(), (
            f"seed {seed} does not build every ordering x size cell"
        )
    # A witness with an empty mask has no bit to flip, so the displacement
    # compare could not be built for it.
    for cell in cfg.cells:
        if cell.witness is not None:
            assert write_mask(cell.witness) != 0, (
                f"witness {cell.witness.block}.{cell.witness.name} has no "
                f"software-usable bit to flip"
            )
    # The sweep must reach past the scratch words, or it proves only stimulus.
    assert len(cfg.blocks) > 1, f"only {cfg.blocks} in the sweep"
    assert any(b in TOUCH_BLOCKS for b in cfg.blocks), (
        f"no IP block from TOUCH_BLOCKS reached: {cfg.blocks}"
    )
    # The m_axi walk: every register it keeps must sit inside a programmed
    # allow window, no window may cover the filter rule bank, and the walk must
    # not shrink below its floor.
    m = SepAxiOrderSweepCfg(1, bus="m_axi")
    assert len(m.cells) >= M_AXI_CELL_FLOOR, (
        f"CHK-COVERAGE FAIL: m_axi walk built {len(m.cells)} cells, below the floor of "
        f"{M_AXI_CELL_FLOOR}; a map or routing change removed registers the "
        f"inbound master can still reach"
    )
    for info in m.regs:
        assert any(lo <= info.addr <= hi for _n, lo, hi in M_AXI_ALLOW_WINDOWS), (
            f"{info.block}.{info.name} (0x{info.addr:08x}) is swept from "
            f"m_axi but no inbound-filter allow window covers it; every cell "
            f"there would be refused and counted as a drop"
        )
    infilt_base = sym("INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR")
    for name, lo, hi in M_AXI_ALLOW_WINDOWS:
        assert not (lo <= infilt_base <= hi), (
            f"allow window {name} 0x{lo:08x}..0x{hi:08x} covers the inbound "
            f"filter rule bank at 0x{infilt_base:08x}; that opens the external "
            f"master's own gate to rewriting"
        )
    # Seed changes data, not coverage.
    a, b = SepAxiOrderSweepCfg(1), SepAxiOrderSweepCfg(2)
    assert {c.key for c in a.cells} == {c.key for c in b.cells}, (
        "seed changed which cells run; it must change data only"
    )


_selftest()
