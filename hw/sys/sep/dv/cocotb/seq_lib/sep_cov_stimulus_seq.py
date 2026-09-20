# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared frontdoor driver for the `sep_cov_*` code-coverage stimulus leaves.

Stimulus only. Nothing here compares a read value against an expectation and
nothing here asserts a design contract; the only failure this module raises is
an unexpected AXI response, which says the stimulus did not reach the target,
not that the target misbehaved. The plan these leaves serve is
`docs/SEP_COV_VPLAN.adoc`.

Geometry (bank bases, strides, per-entry offsets, field positions) is imported
from `seq_lib/sep_fabric_csr_bank_seq.py` rather than restated, so a register
move cannot leave this sweep addressing a stale slot.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    CLOCK_GATE_CTRL,
    CLOCK_GATE_UNGATE,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    INFILT_ENTRIES,
    OUTFILT_BASE,
    OUTFILT_ENTRIES,
)

# Data patterns the walks drive into every 32-bit word they touch. All-ones and
# the two alternating halves move every bit of a field in both directions; the
# trailing zero returns the slot to its reset value so a later walk step starts
# from a known word.
WALK_PATTERNS = (0xFFFF_FFFF, 0x5555_5555, 0xAAAA_AAAA, 0x0000_0000)

# FILTER_CONFIG hi word bit 31 is `locked` (FILTER_CONFIG[63], write-once-set).
# A data walk must leave it clear or the slot stops accepting writes.
FILTER_LOCK_HI_BIT = 1 << 31

__all__ = [
    "CLOCK_GATE_CTRL",
    "CLOCK_GATE_UNGATE",
    "FILTER_CONFIG",
    "FILTER_END_ADDR",
    "FILTER_LOCK_HI_BIT",
    "FILTER_START_ADDR",
    "FILTER_STRIDE",
    "INFILT_BASE",
    "INFILT_ENTRIES",
    "OUTFILT_BASE",
    "OUTFILT_ENTRIES",
    "SepCovStim",
    "WALK_PATTERNS",
]


class SepCovStim(SepAxiRegDriver):
    """CPU-LSU frontdoor accesses for the coverage stimulus leaves.

    ``_wr`` / ``_rd`` come from ``SepAxiRegDriver`` and raise on a non-OKAY
    response. The extra helpers here widen the access rather than the checking:
    an AXI attribute (``prot``, ``burst``, ``size``, multi-beat ``length``) or a
    tolerated error response, with no value compare anywhere.
    """

    _DRIVER_TAG = "COV"

    async def ungate_clocks(self) -> None:
        """Write the implemented CLOCK_GATE_CTRL mask, as every fabric bank
        driver in this tree does before touching a bank."""
        await self._wr(CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE)

    async def access(
        self,
        *,
        op: SepAxiOp,
        addr: int,
        wdata: int = 0,
        length: int = 4,
        size: int | None = 2,
        burst: int | None = None,
        prot: int | None = None,
        axi_id: int = 0,
        user: int = 0,
        allow_error: bool = False,
        allow_unverified_write_resp: bool = False,
        name: str = "cov",
    ) -> SepAxiAccessSeq:
        """Drive one access with the given AXI attributes and return the item.

        A non-OKAY response raises unless the caller marks the target as one
        the open tree answers with an error slave: ``allow_unverified_write_resp``
        tolerates it silently on a write, ``allow_error`` requires it. The
        returned sequence is handed back for logging only.
        """
        seq = SepAxiAccessSeq(
            name,
            op=op,
            addr=addr,
            wdata=wdata,
            length=length,
            size=size,
            burst=burst,
            prot=prot,
            axi_id=axi_id,
            user=user,
            allow_error=allow_error,
            allow_unverified_write_resp=allow_unverified_write_resp,
        )
        if allow_error:
            # The AXI monitor tallies DECERR beats separately from the
            # scoreboard. Credit exactly one for this intentional access; an
            # unexpected DECERR anywhere else still fails the monitor.
            mon = getattr(self.test.env, "axi_monitor", None)
            if mon is not None:
                mon.arm_expected_decerr(1)
        await self.test.start_seq(seq)
        if not (allow_error or allow_unverified_write_resp) and not seq.resp_ok:
            raise AssertionError(
                f"{self._DRIVER_TAG} {op.value} @0x{addr:08x} "
                f"len={length} size={size} burst={burst} prot={prot} "
                f"returned resp={seq.resp_code} (timed_out={seq.timed_out})"
            )
        return seq

    async def word_walk(self, addr: int, patterns=WALK_PATTERNS, *, or_mask: int = 0) -> None:
        """Write each pattern to one 32-bit CSR word, OR-ing in ``or_mask``.

        ``or_mask`` carries the bits a walk must hold constant (for example the
        REGION_ATTRS.valid enable), and is the only place a pattern is altered.
        """
        for pattern in patterns:
            await self._wr(addr, (pattern | or_mask) & 0xFFFF_FFFF)

    def filter_slot(self, *, inbound: bool, index: int) -> int:
        """Base address of one inbound or outbound filter slot."""
        base = INFILT_BASE if inbound else OUTFILT_BASE
        return base + index * FILTER_STRIDE
