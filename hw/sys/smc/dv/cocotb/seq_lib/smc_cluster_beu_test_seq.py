# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN accesses to the documented BEU window land on SMC_BASE_CONFIG.

THIS TESTCASE DOES NOT PROVE ANY BEU PROPERTY, AND NO LONGER CLAIMS TO.

The address map places one Bus Error Unit per core at
``0xC801_0000 + core*0x1000``. Nothing in this bench reaches them.
``hw/sys/smc/rtl/smc_fabric/smc_local_fabric/rtl/smc_local_fabric.sv:66-78``
rewrites the address of every request entering the local fabric as
``{local_base_addr_i[31:25], addr[24:0]}`` -- its own comment says "replace
upper 7 bits with local_base_addr" -- and ``local_base_addr_i`` comes from
``SMC_BASE_CONFIG.LOCAL_BASE`` (``smc_base.sv:381`` -> ``smc_fabric.sv:141``),
whose generated reset is ``0xC000_0000`` and which nothing here writes. Bits
``[31:25]`` of the incoming address are therefore discarded, and
``0xC801_x000`` becomes ``0xC001_x000``.

Filed as #1237, with the region-wide measurement and the RTL site in the comment
on it, and the parent #1249.

The reads do not reach the cluster at all, so the value mismatch is not an
unmodelled register block behind a cluster black-box. The three non-zero values
are bit-for-bit
the ``SMC_BASE_CONFIG`` RDL resets -- ``GLOBAL_BASE`` 0x4000_0000,
``REGION_SIZE`` 0x0100_0000, ``CLOCK_GATE_CONTROL.cg_hysteresis`` 0x1F -- and
the authoritative BEU resets (CAUSE 0x0, ENABLE 0xE6, PLIC_ENABLE 0x0) match
none of them.

WHAT IT PROVES NOW. The aliasing itself, asserted rather than assumed: each
documented BEU address is read, the ``0xC001_xxxx`` address the masking maps it
to is read in the same run, and the two must return the SAME word. That is a
real, fail-capable property of the current decode -- if the masking were
repaired the two reads would diverge and this testcase would fail, which is the
signal wanted. Cores 0 and 1 additionally return identical triples because
``SMC_BASE_CONFIG`` is an 8 KB window and ``0xC001_1xxx`` wraps inside it, while
cores 2 and 3 map onto ``alias_remap`` / ``mmode_remap`` at reset 0.
"""

from __future__ import annotations

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

BEU_CORE_BASE = 0xC801_0000
BEU_CORE_STRIDE = 0x1000
BEU_CORES = 4

# Representative BEU register offsets (subset of the 6-register block).
BEU_CAUSE_OFFSET = 0x00
BEU_ENABLE_OFFSET = 0x10
BEU_PLIC_ENABLE_OFFSET = 0x18

# The masking smc_local_fabric applies: keep addr[24:0], force [31:25] from
# LOCAL_BASE (reset 0xC000_0000). Written as the RTL expresses it rather than as
# a hand-computed constant, so the two sides of the compare below are derived
# the same way the hardware derives them.
LOCAL_BASE_RESET = 0xC000_0000


_UPPER7 = 0xFE00_0000   # addr[31:25], the bits the fabric overwrites
_LOWER25 = 0x01FF_FFFF  # addr[24:0],  the bits it keeps


def masked_addr(addr: int) -> int:
    """Address after smc_local_fabric.sv:66-78 rewrites the upper 7 bits."""
    return (LOCAL_BASE_RESET & _UPPER7) | (addr & _LOWER25)


# Values the aliased reads return today. These are a REGRESSION LOCK on the
# decode described above, NOT a BEU golden and NOT an RDL-traceable reset.
#                (CAUSE,        ENABLE,       PLIC_ENABLE)
ALIASED_EXPECTED = {
    0: (0x4000_0000, 0x0100_0000, 0x1F00_0000),
    1: (0x4000_0000, 0x0100_0000, 0x1F00_0000),
    2: (0x0,         0x0,         0x0),
    3: (0x0,         0x0,         0x0),
}

_OFFSETS = (
    ("CAUSE", BEU_CAUSE_OFFSET),
    ("ENABLE", BEU_ENABLE_OFFSET),
    ("PLIC_ENABLE", BEU_PLIC_ENABLE_OFFSET),
)


class smc_cluster_beu_test_seq(SmcCsrSeq):
    """Locks the BEU-window aliasing of #1237 by comparing both addresses."""

    def __init__(self, name: str = "smc_cluster_beu_test_seq") -> None:
        super().__init__(name)
        #: (beu_addr, mapped_addr, word) triples proven identical
        self.alias_pairs: list[tuple[int, int, int]] = []

    async def body(self) -> None:
        for core in range(BEU_CORES):
            base = BEU_CORE_BASE + core * BEU_CORE_STRIDE
            expected = dict(zip(("CAUSE", "ENABLE", "PLIC_ENABLE"),
                                ALIASED_EXPECTED[core]))
            for label, off in _OFFSETS:
                beu_addr = base + off
                mapped = masked_addr(beu_addr)
                assert mapped != beu_addr, (
                    f"core{core} {label}: the masking maps 0x{beu_addr:08x} onto "
                    f"itself, so this pair cannot demonstrate aliasing"
                )
                via_beu = await self.csr_read(
                    f"CORE{core}_BEU_{label}", beu_addr,
                    expected=expected[label],
                )
                via_mapped = await self.csr_read(
                    f"CORE{core}_MAPPED_{label}", mapped,
                    expected=expected[label],
                )
                # The aliasing itself, asserted. Both reads carry `expected=`
                # so the scoreboard enforces each word independently; this
                # additionally requires that the two ADDRESSES agree, which is
                # the property #1237 is about and which a repaired decode would
                # break.
                assert via_beu == via_mapped, (
                    f"core{core} {label}: documented BEU address 0x{beu_addr:08x} "
                    f"returned 0x{via_beu:08x} but the address the local-fabric "
                    f"masking maps it to, 0x{mapped:08x}, returned "
                    f"0x{via_mapped:08x}. If these have diverged the masking has "
                    f"changed -- see #1237 / #1249 -- and this testcase's premise "
                    f"needs revisiting."
                )
                self.alias_pairs.append((beu_addr, mapped, via_beu))

        assert len(self.alias_pairs) == BEU_CORES * len(_OFFSETS), (
            f"aliasing proven for {len(self.alias_pairs)} of "
            f"{BEU_CORES * len(_OFFSETS)} (core, register) pairs"
        )
        # `self.accesses` is incremented by every csr_* call in
        # smc_csr_seq_utils.py, so `self.accesses == <literal>` restates the
        # loop above and cannot fail on anything the DUT did
        # ([NO-ZERO-ACTIVITY-PASS]). `assert_all_reachable` cross-checks the
        # same count against the scoreboard, which a mis-bound analysis path
        # or a dead port fails.
        self.assert_all_reachable(BEU_CORES * len(_OFFSETS) * 2, "CLUSTER_BEU")
        cocotb.log.info(
            "CHK-BEU-WINDOW-ALIASED: %d (core, register) pairs read at BOTH the "
            "documented BEU address and the 0xC001_xxxx address that "
            "smc_local_fabric.sv:66-78 maps it to, and each pair returned the "
            "same word. This testcase locks the #1237 / #1249 aliasing; it "
            "proves NO BEU property, because no read reaches a BEU.",
            len(self.alias_pairs),
        )
