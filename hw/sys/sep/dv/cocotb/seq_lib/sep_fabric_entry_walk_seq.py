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

ADDR_W = 56
ADDR_MASK = (1 << ADDR_W) - 1
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
            cur = (cur & 0xFFFF_FFFF) | ((word & 0x00FF_FFFF) << 32)
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
            await self._wr(base + off + 4, (val >> 32) & 0x00FF_FFFF)
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
        assert (got & want) == want and (enabled or not (got & F_ENTRY_ENABLED)), (
            f"CHK-WALK-READBACK FAIL: {self.bank} entry {entry} FILTER_CONFIG read "
            f"0x{got:08x}, want enable bits 0x{want:08x}"
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


def bit_legs(x: int):
    """Per-bit windows where one START or END bit alone decides the response.

    For each address bit k above the granule, two windows relative to target x:
      * x[k] == 0: START = x[55:k+1] | 1<<k | 0  -> deny (START > x);
                   END   = x[55:k+1] | 1<<k | 0  -> allow (END > x).
      * x[k] == 1: START = x[55:k+1] | 0 | ones  -> allow (START < x);
                   END   = x[55:k+1] | 0 | ones  -> deny (END < x).
    The other bound is 0 or all-ones, so it cannot decide. A comparator that
    ignores START or END bit k sees that bound with bit k flipped, which moves
    it to the other side of x, so the response flips. Yields
    ``(k, field, (start, end), expect_allow)``; legs whose flipped bound would
    still land in x's granule are skipped, because there the bit cannot decide.
    """
    g = GRAN_MASK.bit_length()
    for k in range(g, ADDR_W):
        high = (x >> (k + 1)) << (k + 1)
        low_ones = (1 << k) - 1
        if not (x >> k) & 1:
            bound = high | (1 << k)
            flipped = high
            if granule(flipped) == granule(x):
                continue
            yield k, "START", (bound, ADDR_MASK), False
            yield k, "END", (0, bound), True
        else:
            bound = high | low_ones
            flipped = bound | (1 << k)
            if granule(flipped) == granule(x):
                continue
            yield k, "START", (bound, ADDR_MASK), True
            yield k, "END", (0, bound), False


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
    for x in (0x10A3_0178, 0x89F0_A9A7_3D30_90, ADDR_MASK & ~GRAN_MASK, GRANULE_BYTES):
        for k, field, (st, en), allow in bit_legs(x):
            assert st <= en
            assert (granule(st) <= granule(x) <= granule(en)) == allow, (hex(x), k, field)
            # The same window with bit k of the deciding bound flipped flips the answer.
            st2, en2 = (st ^ (1 << k), en) if field == "START" else (st, en ^ (1 << k))
            assert (granule(st2) <= granule(x) <= granule(en2)) != allow, (hex(x), k, field)


_selftest()
