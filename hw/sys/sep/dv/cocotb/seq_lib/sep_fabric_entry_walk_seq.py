# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Full-width filter-window and remap-offset walks over every entry.

Shared by ``sep_fabric_outbound_remap_filter_walk_test`` and
``sep_fabric_inbound_filter_window_walk_test``. Each walk programs every entry
of a bank with full-width values and grades the result two ways: the CSR
readback, and the response of live traffic that the programmed value decides.

Value plan. Every programmed field goes from its reset value to a seed value
V, then to ~V, then back to reset. So each bit of START_ADDR, END_ADDR and the
remap offset takes both a 0->1 and a 1->0 step, and the traffic check after
each step depends on the upper address bits, not only bits [31:0].

Filter address fields (``hw/ip/axi_filter/regs/filter_ctrl.rdl``):
``start_addr[55:0]`` / ``end_addr[55:0]``, matched at the granule
(2^data_bus_width bytes while allow_burst is 0). When START and END land in
the same granule, hardware writes the rounded values back (START rounds down,
END rounds up); otherwise the readback is the programmed value.
``SepFilterBoundsModel`` applies that rule after each 32-bit write, because
the 64-bit registers are written as two 32-bit halves.

Remap offset (``hw/ip/output_remap/regs/output_remap.rdl``):
``offset[55:0]`` ("RTL will use the number of bits appropriate for region
granularity") and ``valid[63]`` ("if clear, they pass through with their
address unchanged"). ``hw/sys/sep/doc/fabric.adoc`` states that the AP and
STEE output remaps replace the address with the programmed region offset, so
a valid region rewrites the address to
``{offset[55:IdxStart], adjusted[IdxStart-1:0]}`` with IdxStart the region
granularity (``sep_outbound_remap_seq.IDX_START``).
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import INBOUND_FILTER_CTRL_0

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_WRITE_ALLOWED,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_RW_MASK,
    FILTER_START_ADDR,
    FILTER_STRIDE,
)
from seq_lib.sep_inbound_filter_rule_seq import GRANULE_BYTES
from seq_lib.sep_outbound_remap_seq import (
    REMAP_ATTRS,
    REMAP_OFFSET_MASK,
    REMAP_STRIDE,
    REMAP_VALID,
)

# filter_ctrl.rdl start_addr / end_addr width; the hi word holds bits ADDR_W-1:32.
ADDR_W = INBOUND_FILTER_CTRL_0.field_width("START_ADDR", "start_addr")
ADDR_MASK = (1 << ADDR_W) - 1
HI_MASK = ADDR_MASK >> 32
GRAN_MASK = GRANULE_BYTES - 1
# filter_ctrl.rdl START_ADDR / END_ADDR resets (upper words reset to zero).
START_RESET = INBOUND_FILTER_CTRL_0.reset32("START_ADDR")
END_RESET = INBOUND_FILTER_CTRL_0.reset32("END_ADDR")
if REMAP_OFFSET_MASK != ADDR_MASK:
    raise RuntimeError(f"remap offset mask 0x{REMAP_OFFSET_MASK:x} is not offset[55:0]")
if END_RESET != GRAN_MASK:
    raise RuntimeError(f"END_ADDR reset 0x{END_RESET:x} is not the {GRANULE_BYTES}-byte granule")

# One read-allowed, write-allowed, any-source entry. src_id=0 is match-all
# (filter_ctrl.rdl); allow_ns matches the NONSECURE masters. Never sets locked.
ENTRY_CFG = F_ENTRY_ENABLED | F_READ_ALLOWED | F_WRITE_ALLOWED | F_ALLOW_NS


def granule(addr: int) -> int:
    return addr // GRANULE_BYTES


class SepFilterBoundsModel:
    """START/END readback model under the same-granule write-back rule."""

    def __init__(self) -> None:
        self.start = START_RESET
        self.end = END_RESET

    def _settle(self) -> None:
        if granule(self.start) == granule(self.end):
            self.start &= ~GRAN_MASK & ADDR_MASK
            self.end |= GRAN_MASK

    def write_half(self, field: str, hi: bool, word: int) -> None:
        cur = self.start if field == "START" else self.end
        if hi:
            cur = (cur & 0xFFFF_FFFF) | ((word & HI_MASK) << 32)
        else:
            cur = (cur & ~0xFFFF_FFFF) | (word & 0xFFFF_FFFF)
        if field == "START":
            self.start = cur & ADDR_MASK
        else:
            self.end = cur & ADDR_MASK
        self._settle()


class SepFilterEntryWalker(SepAxiRegDriver):
    """CPU-LSU driver for one filter bank: program, read back, disable, restore."""

    _DRIVER_TAG = "ENTRYWALK"

    def __init__(self, test, *, bank_base: int, bank: str, n_entries: int) -> None:
        super().__init__(test)
        self.bank_base = bank_base
        self.bank = bank
        self.n_entries = n_entries
        self.models = [SepFilterBoundsModel() for _ in range(n_entries)]
        self.readbacks = 0

    def _ebase(self, entry: int) -> int:
        return self.bank_base + entry * FILTER_STRIDE

    async def program_window(self, entry: int, start: int, end: int) -> tuple[int, int]:
        """Write START then END as lo/hi halves; return the model readback."""
        base = self._ebase(entry)
        model = self.models[entry]
        for field, off, val in (
            ("START", FILTER_START_ADDR, start),
            ("END", FILTER_END_ADDR, end),
        ):
            await self._wr(base + off, val & 0xFFFF_FFFF)
            model.write_half(field, False, val)
            await self._wr(base + off + 4, (val >> 32) & HI_MASK)
            model.write_half(field, True, val >> 32)
        return model.start, model.end

    async def read_window(self, entry: int) -> tuple[int, int]:
        base = self._ebase(entry)
        s_lo = await self._rd(base + FILTER_START_ADDR)
        s_hi = await self._rd(base + FILTER_START_ADDR + 4)
        e_lo = await self._rd(base + FILTER_END_ADDR)
        e_hi = await self._rd(base + FILTER_END_ADDR + 4)
        return ((s_hi << 32) | s_lo) & ADDR_MASK, ((e_hi << 32) | e_lo) & ADDR_MASK

    async def check_window(self, entry: int, tag: str) -> tuple[int, int]:
        """CHK-WALK-READBACK: the CSR holds the model value, all 56 bits."""
        want = (self.models[entry].start, self.models[entry].end)
        got = await self.read_window(entry)
        assert got == want, (
            f"CHK-WALK-READBACK FAIL: {self.bank} entry {entry} {tag} START/END read "
            f"0x{got[0]:014x}/0x{got[1]:014x}, want 0x{want[0]:014x}/0x{want[1]:014x}"
        )
        self.readbacks += 1
        return got

    async def set_enabled(self, entry: int, enabled: bool) -> None:
        await self._wr(self._ebase(entry) + FILTER_CONFIG, ENTRY_CFG if enabled else 0)
        got = await self._rd(self._ebase(entry) + FILTER_CONFIG)
        want = ENTRY_CFG if enabled else 0
        # Every RW field of the low word must read back as written; the RO
        # data_bus_width field is outside FILTER_RW_MASK.
        assert (got & FILTER_RW_MASK) == (want & FILTER_RW_MASK), (
            f"CHK-WALK-READBACK FAIL: {self.bank} entry {entry} FILTER_CONFIG read "
            f"0x{got:08x}, want RW fields 0x{want & FILTER_RW_MASK:08x}"
        )
        self.readbacks += 1

    async def restore(self, entry: int) -> None:
        """Disable the entry and return START/END to reset, so each bit steps back."""
        await self.set_enabled(entry, False)
        await self.program_window(entry, START_RESET, END_RESET)
        await self.check_window(entry, "restore")


class SepRemapRegionDriver(SepAxiRegDriver):
    """CPU-LSU driver for one AP/STEE output-remap region's ATTRS register."""

    _DRIVER_TAG = "REMAPWALK"

    def __init__(self, test) -> None:
        super().__init__(test)
        self.readbacks = 0

    async def program(self, csr_base: int, region: int, offset: int, valid: bool) -> None:
        attrs = csr_base + region * REMAP_STRIDE + REMAP_ATTRS
        word = (offset & ADDR_MASK) | (REMAP_VALID if valid else 0)
        await self._wr(attrs, word & 0xFFFF_FFFF)
        await self._wr(attrs + 4, word >> 32)
        lo = await self._rd(attrs)
        hi = await self._rd(attrs + 4)
        got = (hi << 32) | lo
        assert got == word, (
            f"CHK-WALK-READBACK FAIL: remap 0x{csr_base:08x} r{region} ATTRS read "
            f"0x{got:016x}, want 0x{word:016x}"
        )
        self.readbacks += 1


def containing_window(rng: SepSeededRng, x: int) -> tuple[int, int]:
    """A random window [start, end] with start <= x <= end, full 56-bit range."""
    return rng.randrange(0, x + 1), rng.randrange(x, ADDR_MASK + 1)


def exact_window(x: int) -> tuple[int, int]:
    """The one granule that holds x."""
    return x & ~GRAN_MASK & ADDR_MASK, x | GRAN_MASK


FIELDS = ("START", "END")
BIT_RANGE = range(GRAN_MASK.bit_length(), ADDR_W)


def _allows(field: str, bound: int, x: int) -> bool:
    if field == "START":
        return granule(bound) <= granule(x)
    return granule(bound) >= granule(x)


def _leg(field: str, k: int, x: int) -> tuple[tuple[int, int], bool] | None:
    """One window where bound bit k alone decides whether x is inside, or None.

    See ``bit_legs`` for the window shape. The leg counts only when flipping
    bit k of the bound flips the answer for x.
    """
    high = (x >> (k + 1)) << (k + 1)
    if (x >> k) & 1:
        bound = high | ((1 << k) - 1)
    else:
        bound = high | (1 << k)
    allow = _allows(field, bound, x)
    if allow == _allows(field, bound ^ (1 << k), x):
        return None
    win = (bound, ADDR_MASK) if field == "START" else (0, bound)
    return win, allow


def bit_legs(xs: list[int]):
    """Per-bit windows where one START or END bit alone decides the response.

    For every address bit k above the granule and for each bound, pick the first
    probe address x in ``xs`` where a window exists whose deciding bound has x's
    bits above k, bit k set (x[k]=0) or cleared with all-ones below (x[k]=1),
    and whose other bound is 0 or all-ones -- and where flipping bound bit k
    moves x across that bound. A compare that ignores bit k of that bound then
    gives the opposite answer. Yields ``(k, field, (start, end), allow, i)`` with
    i the index of the chosen probe. Raises when some (k, bound) has no probe,
    so a caller cannot claim a bit it did not test.
    """
    for k in BIT_RANGE:
        for field in FIELDS:
            for i, x in enumerate(xs):
                leg = _leg(field, k, x)
                if leg is not None:
                    yield k, field, leg[0], leg[1], i
                    break
            else:
                raise RuntimeError(
                    f"no probe in {[hex(v) for v in xs]} lets {field} bit {k} decide alone"
                )


def _selftest() -> None:
    m = SepFilterBoundsModel()
    m.write_half("START", False, 0x1000_0004)
    m.write_half("START", True, 0x0)
    m.write_half("END", False, 0x1000_0004)
    m.write_half("END", True, 0x0)
    assert (m.start, m.end) == (0x1000_0000, 0x1000_0007)
    m = SepFilterBoundsModel()
    m.write_half("START", False, 0x10)
    m.write_half("END", False, 0x20)
    m.write_half("END", True, 0xFF_FFFF)
    assert (m.start, m.end) == (0x10, 0xFF_FFFF_0000_0020)
    assert exact_window(0x1234_5678_9ABC) == (0x1234_5678_9AB8, 0x1234_5678_9ABF)
    for xs in (
        [0x10A3_0178, 0x1080_2000, 0x1080_2008, 0x1080_2010],
        [0x89F0_A9A7_3D30_90, 0x89F0_A9A7_3D30_98],
    ):
        legs = list(bit_legs(xs))
        assert len(legs) == 2 * len(BIT_RANGE)
        for k, field, (st, en), allow, i in legs:
            x = xs[i]
            assert st <= en
            assert (granule(st) <= granule(x) <= granule(en)) == allow, (hex(x), k, field)
            # The same window with bit k of the deciding bound flipped flips the answer.
            st2, en2 = (st ^ (1 << k), en) if field == "START" else (st, en ^ (1 << k))
            assert (granule(st2) <= granule(x) <= granule(en2)) != allow, (hex(x), k, field)


_selftest()
