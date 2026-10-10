# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Program, read back and model one SEP filter bank (inbound or outbound).

Every entry of both banks has the layout of ``filter_ctrl.rdl``
(``hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc``): FILTER_CONFIG, then the
56-bit START_ADDR and END_ADDR as lo/hi 32-bit words. The layout constants
come from ``seq_lib.sep_fabric_csr_bank_seq``.

``program`` writes START, END and FILTER_CONFIG and reads each one back before
it returns, because the specification states no ordering between a CSR write
and the next transaction. The read-back compare uses the RDL field bits only:

* FILTER_CONFIG lo word: the RW fields (``FILTER_CFG_LO_FIELDS``); the RO
  ``data_bus_width`` field and the Reserved bits are logged, not graded;
* START_ADDR and END_ADDR: logged, not graded. The specification states no
  write-back timing for the granule rule, so a caller that needs the admitted
  set grades it through verdicts.

The driver also keeps a :class:`env.sep_filter_model.FilterModel` of the bank
in step with what it wrote, so a leaf asks the model for the verdict of a
probe. The ``locked`` bit is never written.
"""

from __future__ import annotations

from env.sep_fabric_common import FILTER_ADDR_MASK
from env.sep_filter_model import FilterEntry, FilterModel
from sep_reg_meta import INBOUND_FILTER_CTRL_0

from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    F_ALLOW_BURST,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_GROUP_ID_LSB,
    F_READ_ALLOWED,
    F_SRC_ID_LSB,
    F_WRITE_ALLOWED,
    FILTER_CFG_LO_FIELDS,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    INFILT_ENTRIES,
    OUTFILT_BASE,
    OUTFILT_ENTRIES,
)

# The START_ADDR / END_ADDR field (the same width in both banks), and its part
# above bit 31, which the hi word of each register holds.
ADDR_HI_MASK = FILTER_ADDR_MASK >> 32
SRC_ID_MASK = (1 << INBOUND_FILTER_CTRL_0.field_width("FILTER_CONFIG", "src_id")) - 1
GROUP_ID_MASK = (1 << INBOUND_FILTER_CTRL_0.field_width("FILTER_CONFIG", "group_id")) - 1
# RDL reset values of START_ADDR and END_ADDR (the same in both banks).
START_RESET = INBOUND_FILTER_CTRL_0.reset("START_ADDR")
END_RESET = INBOUND_FILTER_CTRL_0.reset("END_ADDR")


def config_word(e: FilterEntry) -> int:
    """FILTER_CONFIG lo word of ``e``. ``locked`` (hi word) is never set."""
    v = ((e.src_id & SRC_ID_MASK) << F_SRC_ID_LSB) | (
        (e.group_id & GROUP_ID_MASK) << F_GROUP_ID_LSB
    )
    if e.enabled:
        v |= F_ENTRY_ENABLED
    if e.read_allowed:
        v |= F_READ_ALLOWED
    if e.write_allowed:
        v |= F_WRITE_ALLOWED
    if e.allow_ns:
        v |= F_ALLOW_NS
    if e.allow_burst:
        v |= F_ALLOW_BURST
    return v


class SepFilterBank(SepAxiRegDriver):
    """CPU-LSU driver of one filter bank, with its reference model."""

    _DRIVER_TAG = "FILTBANK"

    def __init__(self, test, bank: str) -> None:
        super().__init__(test)
        if bank not in ("in", "out"):
            raise ValueError(f"bank must be 'in' or 'out', got {bank!r}")
        self.bank = bank
        self.base = INFILT_BASE if bank == "in" else OUTFILT_BASE
        self.n = INFILT_ENTRIES if bank == "in" else OUTFILT_ENTRIES
        self.model = FilterModel(self.n, bank)
        self.readbacks = 0

    def entry_base(self, idx: int) -> int:
        if not 0 <= idx < self.n:
            raise IndexError(f"{self.bank} filter entry {idx} out of range 0..{self.n - 1}")
        return self.base + idx * FILTER_STRIDE

    def cfg_addr(self, idx: int) -> int:
        return self.entry_base(idx) + FILTER_CONFIG

    async def _write_range(self, idx: int, start: int, end: int) -> None:
        b = self.entry_base(idx)
        await self._wr(b + FILTER_START_ADDR, start & 0xFFFF_FFFF)
        await self._wr(b + FILTER_START_ADDR + 4, (start >> 32) & ADDR_HI_MASK)
        await self._wr(b + FILTER_END_ADDR, end & 0xFFFF_FFFF)
        await self._wr(b + FILTER_END_ADDR + 4, (end >> 32) & ADDR_HI_MASK)

    async def read_entry(self, idx: int) -> tuple[int, int, int]:
        """(FILTER_CONFIG lo, START_ADDR, END_ADDR) as read."""
        b = self.entry_base(idx)
        cfg = await self._rd(b + FILTER_CONFIG)
        s = await self._rd(b + FILTER_START_ADDR) | (
            await self._rd(b + FILTER_START_ADDR + 4) << 32
        )
        e = await self._rd(b + FILTER_END_ADDR) | (await self._rd(b + FILTER_END_ADDR + 4) << 32)
        return cfg, s, e

    async def check_entry(self, idx: int, tag: str = "") -> tuple[int, int, int]:
        """Read the entry back and compare FILTER_CONFIG on its RW fields.

        Raises on a FILTER_CONFIG field mismatch. START and END are logged.
        """
        want = config_word(self.model.entries[idx])
        cfg, s, e = await self.read_entry(idx)
        rsvd = cfg & ~FILTER_CFG_LO_FIELDS & 0xFFFF_FFFF
        line = (
            f"{self.bank} entry {idx} {tag} cfg=0x{cfg & FILTER_CFG_LO_FIELDS:08x} "
            f"want=0x{want & FILTER_CFG_LO_FIELDS:08x} field_mask=0x{FILTER_CFG_LO_FIELDS:08x} "
            f"rsvd=0x{rsvd:08x} rb_start=0x{s:014x} rb_end=0x{e:014x}"
        )
        if (cfg & FILTER_CFG_LO_FIELDS) != (want & FILTER_CFG_LO_FIELDS):
            raise AssertionError(f"FILTER-READBACK FAIL: {line}")
        self.log.info("FILTER-READBACK LOG: %s", line)
        self.readbacks += 1
        return cfg, s, e

    async def program(self, idx: int, e: FilterEntry, *, check: bool = True) -> None:
        """Clear FILTER_CONFIG, write the range, write FILTER_CONFIG, read the entry back.

        The first write clears ``entry_enabled`` and ``allow_burst`` of the
        old configuration. The granule rule widens START_ADDR and END_ADDR by
        the ``allow_burst`` value in force, so a range written under an old
        ``allow_burst`` 1 would take the 4 KiB widening that the new entry
        does not ask for, and an old enabled entry would admit traffic over a
        half-written range.
        """
        await self._wr(self.cfg_addr(idx), 0)
        await self._write_range(idx, e.start, e.end)
        await self._wr(self.cfg_addr(idx), config_word(e))
        self.model.set(idx, FilterEntry(**vars(e)))
        if check:
            await self.check_entry(idx, "program")

    async def set_enabled(self, idx: int, enabled: bool, *, check: bool = True) -> None:
        """Change ``entry_enabled`` only; the other fields keep the model value."""
        self.model.entries[idx].enabled = enabled
        await self._wr(self.cfg_addr(idx), config_word(self.model.entries[idx]))
        if check:
            await self.check_entry(idx, "enable" if enabled else "disable")

    async def disable_all(self, *, check: bool = True) -> None:
        """Disable every entry; START and END keep their values."""
        for i in range(self.n):
            self.model.entries[i].enabled = False
            await self._wr(self.cfg_addr(i), config_word(self.model.entries[i]))
            if check:
                await self.check_entry(i, "disable_all")

    async def restore_reset(self, idx: int) -> None:
        """Write the RDL reset values back to one entry and read it back."""
        await self.program(idx, FilterEntry(start=START_RESET, end=END_RESET))
