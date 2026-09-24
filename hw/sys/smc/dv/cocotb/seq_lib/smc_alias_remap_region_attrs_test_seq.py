# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An alias-remap region marked valid, and its attributes held across a write.

`smc_alias_remap_spare_block_decode_test` writes `REGION_START` on all eight
regions and restores it, but nothing writes `REGION_ATTRS`: no region has ever
been marked cacheable or valid, so the two attribute bits have never held a one
while a write arrived that did not select their lanes.

This leaf sets them on one region and then writes the other half of the
register, which is what puts that contract to the test.

**The region cannot match an address, by its own reset.** `alias_remap.rdl`
makes `REGION_END` "End of remap region (non-inclusive)", and the generated map
gives both `REGION_START` and `REGION_END` the reset `0x0`. A region whose end
is non-inclusive and equal to its start contains no address at all, so this
leaf **never writes either of them**: it leaves the window empty and touches
only `REGION_ATTRS`. That is a stronger guarantee than choosing an address
range believed to be unused, and it keeps the footprint to one register.

**`valid` is an identity remap even so.** `REGION_ATTRS.offset` is "added to
bits [55:12] of the input address when it falls within the remap region", and
this leaf leaves it at its reset of zero. So even if the empty window could
match, the remap would add nothing.

**Nothing else is remapping.** All eight regions are read first and every one
must have `valid` clear, so the region this leaf marks valid is the only one in
the block, and no rule of somebody else's can be what the readbacks below
report.

The sequence then sets `cacheable` and `valid` together, reads the register
back as a guard before depending on it, writes **only the low half** of the
register -- the half `offset` occupies, with the byte lanes over bits 62 and 63
deasserted -- and requires both attribute bits to still be set, which is the
retain behaviour of a field the write did not select. `REGION_ATTRS` is then
restored to its reset and read back.
"""

from __future__ import annotations

import cocotb

from .smc_addr_map import (
    ALIAS_REMAP_ATTRS_CACHEABLE,
    ALIAS_REMAP_ATTRS_OFFSET,
    ALIAS_REMAP_ATTRS_VALID,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"
_ATTRS_NUM = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_NUM"
_START = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_END = "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"

# The region this leaf marks valid: the last one, which leaves every
# lower-numbered region untouched for anything that ranks them.
_REGION = 7

# Both attribute bits, and the half of the register they do not occupy.
_ATTR_BITS = ALIAS_REMAP_ATTRS_CACHEABLE | ALIAS_REMAP_ATTRS_VALID
_LOW_HALF = 0xFFFF_FFFF

_ACCESSES = 8 + 2 + 2 + 2 + 2


class smc_alias_remap_region_attrs_test_seq(SmcCsrSeq):
    """Mark one empty alias-remap region valid and hold its attributes."""

    def __init__(self, name: str = "smc_alias_remap_region_attrs_test_seq") -> None:
        super().__init__(name)
        self.regions_checked = 0
        self.attrs_held = 0

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        count = smc_addr(_ATTRS_NUM)
        assert _REGION < count, f"the map declares {count} regions, so there is no {_REGION}"
        assert ALIAS_REMAP_ATTRS_OFFSET & _LOW_HALF, (
            "the offset field does not reach the low half of the register, so a write of "
            "that half would not be the write this leaf needs"
        )
        assert _ATTR_BITS & _LOW_HALF == 0, (
            f"the attribute bits 0x{_ATTR_BITS:x} reach the low half of the register, so "
            f"the write below would select their lanes instead of leaving them alone"
        )

        # Nothing else may be remapping, or a readback here could be its doing.
        for region in range(count):
            addr = smc_indexed_addr(_ATTRS, region)
            word = await self.csr_read(f"ATTRS{region}_IDLE", addr, length=8)
            assert word & ALIAS_REMAP_ATTRS_VALID == 0, (
                f"alias-remap region {region} reads 0x{word:016x} with valid already set "
                f"before this leaf wrote anything"
            )
            self.regions_checked += 1

        # The window is left at its reset, which is empty: `alias_remap.rdl`
        # makes REGION_END non-inclusive and both registers reset to zero.
        attrs = smc_indexed_addr(_ATTRS, _REGION)
        start = await self.csr_read("REGION_START", smc_indexed_addr(_START, _REGION), length=8)
        end = await self.csr_read("REGION_END", smc_indexed_addr(_END, _REGION), length=8)
        assert start == end, (
            f"alias-remap region {_REGION} spans 0x{start:x} to 0x{end:x}; this leaf marks "
            f"it valid only because a non-inclusive end equal to its start contains no "
            f"address, and that is no longer true"
        )

        await self.csr_write("ATTRS_SET", attrs, _ATTR_BITS, length=8)
        guard = await self.csr_read("ATTRS_SET_RB", attrs, length=8)
        assert guard & _ATTR_BITS == _ATTR_BITS, (
            f"REGION_ATTRS reads 0x{guard:016x} after cacheable and valid were written; "
            f"both have to read back before anything can depend on them"
        )
        assert guard & ALIAS_REMAP_ATTRS_OFFSET == 0, (
            f"REGION_ATTRS reads 0x{guard:016x} with a non-zero offset; this leaf leaves "
            f"it at its reset so the remap adds nothing"
        )

        # The low half only: the byte lanes over bits 62 and 63 are deasserted,
        # so a field that retains has to keep its value across this write.
        await self.csr_write("ATTRS_LOW_HALF", attrs, 0, length=4)
        held = await self.csr_read("ATTRS_HELD", attrs, length=8)
        assert held & _ATTR_BITS == _ATTR_BITS, (
            f"REGION_ATTRS reads 0x{held:016x} after a four-byte write of its low half; "
            f"that write did not select the lanes cacheable and valid sit in, so both have "
            f"to still be set"
        )
        assert held & ALIAS_REMAP_ATTRS_OFFSET == 0, (
            f"REGION_ATTRS reads 0x{held:016x}; the low-half write carried zero, so the "
            f"offset has to remain zero"
        )
        self.attrs_held = 2

        await self.csr_write("ATTRS_RESTORE", attrs, 0, length=8)
        restored = await self.csr_read("ATTRS_RESTORE_RB", attrs, length=8, expected=0)
        assert restored == 0, (
            f"REGION_ATTRS reads 0x{restored:016x} after being restored; its RDL reset is 0"
        )

        assert self.regions_checked == count, (
            f"{self.regions_checked} of {count} regions checked idle"
        )
        assert self.accesses >= _ACCESSES, (
            f"the sequence issued {self.accesses} SEP_IN accesses, fewer than {_ACCESSES}"
        )
        sb = getattr(getattr(self, "env", None), "scoreboard", None)
        assert sb is not None, "no scoreboard on this sequence's env"

        cocotb.log.info(
            "CHK-ALIAS-REMAP-ATTRS-RETAIN: all %d alias-remap regions read with valid "
            "clear, region %d was then marked cacheable and valid over a window its own "
            "reset leaves empty and with the remap offset at zero, and both attribute bits "
            "survived a four-byte write of the half of the register they do not occupy "
            "before the register was restored to its reset and read back",
            self.regions_checked,
            _REGION,
        )
