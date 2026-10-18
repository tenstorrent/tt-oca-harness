# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simultaneous multi-source interrupt fan-in sources.

sep_irq_simultaneous_fanin_no_alias_test drives SEVERAL IP interrupts at
once and proves the sep_internal_interrupts[8:33] OR-packing assembles exactly the
driven bits with NO neighbor aliasing, for the crypto/KM region. This asserts several
sources at once (vs sep_irq_ip_to_aggregator_test, which asserts one at a time).

Reuses the generic INTR_TEST driver (SepIrqIp) and IrqSrc from
sep_irq_aggregator_seq; each source takes its own IP's INTR_STATE/ENABLE/TEST
addresses from the generated register map. The CROSS-IP set spans four different
IPs (HMAC, KMAC, CSRNG, EDN) at non-adjacent aggregator bits so the anti-alias
check exercises a real OR-network fan-in, not adjacent bits of one IP.

Aggregator bit = PIC source - 1 from hw/sys/sep/doc/interrupts.adoc.
FANIN_SOURCES drives the four *_done bits (one per IP, so each IP's
INTR_ENABLE/INTR_TEST is a single-bit write -- the SepIrqIp driver writes
the whole register, so one bit per base avoids clobber). HMAC/KMAC INTR
bit0 = <ip>_done (OpenTitan INTR layout).
"""

from __future__ import annotations

from itertools import combinations

from env.sep_spec_tables import pic
from sep_reg_meta import CSRNG, EDN, HMAC, KMAC

from seq_lib.sep_irq_aggregator_seq import (
    PIC_CSRNG_CMD_REQ_DONE,
    PIC_EDN_CMD_REQ_DONE,
    PIC_HMAC_DONE,
    PIC_KMAC_DONE,
    IrqSrc,
    agg_from_pic,
)

# The simultaneous cross-IP set: four IPs, four non-adjacent aggregator bits.
FANIN_SOURCES = (
    IrqSrc(
        "hmac_done",
        "HMAC",
        HMAC.field_lsb("INTR_STATE", "hmac_done"),
        agg_from_pic(PIC_HMAC_DONE),
    ),
    IrqSrc(
        "kmac_done",
        "KMAC",
        KMAC.field_lsb("INTR_STATE", "kmac_done"),
        agg_from_pic(PIC_KMAC_DONE),
    ),
    IrqSrc(
        "csrng_cmd_req_done",
        "CSRNG",
        CSRNG.fields("INTR_STATE")["CS_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_CSRNG_CMD_REQ_DONE),
    ),
    IrqSrc(
        "edn_cmd_req_done",
        "EDN",
        EDN.fields("INTR_STATE")["EDN_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_EDN_CMD_REQ_DONE),
    ),
)

# The aggregator region this test owns: from the first source after the eight
# mailbox sources ("DMA transfer done", PIC 9) to "Locked field access" (PIC 34),
# both from hw/sys/sep/doc/interrupts.adoc (SEP PIC source assignments table) via
# the DV-owned PIC table in env/sep_spec_tables.py. That is
# sep_internal_interrupts[8:33], the DMA/crypto/KM fan-in; bits [7:0] are the
# mailbox sources.
REGION_LO = agg_from_pic(pic("DMA transfer done"))
REGION_HI = agg_from_pic(pic("Locked field access"))
assert (REGION_LO, REGION_HI) == (8, 33), (REGION_LO, REGION_HI)
REGION_MASK = (((1 << (REGION_HI + 1)) - 1) >> REGION_LO) << REGION_LO


def driven_mask(sources) -> int:
    """OR of the aggregator bits driven by ``sources``."""
    m = 0
    for s in sources:
        m |= 1 << s.agg_idx
    return m


class SepIrqFaninCfg:
    """Every simultaneous subset of FANIN_SOURCES, walked on every run.

    ``subsets`` holds each combination of two or more sources (six pairs, four
    triples and the full set), so a run proves the exact OR-packing for every
    combination rather than a seed-drawn one. ``baselines`` holds each source
    alone for the non-vacuity single-bit check. Nothing here depends on the
    seed.
    """

    def __init__(self) -> None:
        srcs = list(FANIN_SOURCES)
        self.subsets = [tuple(c) for n in range(2, len(srcs) + 1) for c in combinations(srcs, n)]
        self.baselines = tuple(srcs)

    def summary(self) -> str:
        return (
            f"{len(self.baselines)} single sources, {len(self.subsets)} simultaneous "
            f"subsets of {len(FANIN_SOURCES)} sources"
        )
