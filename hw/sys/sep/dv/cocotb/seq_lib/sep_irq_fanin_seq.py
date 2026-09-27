# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Simultaneous multi-source interrupt fan-in sources.

sep_irq_simultaneous_fanin_no_alias_test drives SEVERAL IP interrupts at
once and proves the sep_internal_interrupts[8:33] OR-packing assembles exactly the
driven bits with NO neighbor aliasing, for the crypto/KM region. This asserts several
sources at once (vs sep_irq_ip_to_aggregator_test, which asserts one at a time).

Reuses the generic INTR_TEST driver (SepIrqIp) and IrqSrc from
sep_irq_aggregator_seq -- the OpenTitan INTR_STATE/ENABLE/TEST layout is identical
across these IPs. The CROSS-IP set spans four different
IPs (HMAC, KMAC, CSRNG, EDN) at non-adjacent aggregator bits so the anti-alias
check exercises a real OR-network fan-in, not adjacent bits of one IP.

Aggregator bit = PIC source − 1 from hw/sys/sep/doc/interrupts.adoc.
FANIN_SOURCES drives the four *_done bits (one per IP, so each IP's
INTR_ENABLE/INTR_TEST is a single-bit write -- the SepIrqIp driver writes
the whole register, so one bit per base avoids clobber). HMAC/KMAC INTR
bit0 = <ip>_done (OpenTitan INTR layout).
"""

from __future__ import annotations

from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import CSRNG, EDN, HMAC, KMAC, sym

from seq_lib.sep_irq_aggregator_seq import (
    CSRNG_BASE,
    EDN_BASE,
    PIC_CSRNG_CMD_REQ_DONE,
    PIC_EDN_CMD_REQ_DONE,
    PIC_HMAC_DONE,
    PIC_KMAC_DONE,
    IrqSrc,
    agg_from_pic,
)

HMAC_BASE = sym("HMAC_REG_MAP_BASE_ADDR")
KMAC_BASE = sym("KMAC_REG_MAP_BASE_ADDR")

# The simultaneous cross-IP set: four IPs, four non-adjacent aggregator bits.
FANIN_SOURCES = (
    IrqSrc(
        "hmac_done",
        HMAC_BASE,
        HMAC.field_lsb("INTR_STATE", "hmac_done"),
        agg_from_pic(PIC_HMAC_DONE),
    ),
    IrqSrc(
        "kmac_done",
        KMAC_BASE,
        KMAC.field_lsb("INTR_STATE", "kmac_done"),
        agg_from_pic(PIC_KMAC_DONE),
    ),
    IrqSrc(
        "csrng_cmd_req_done",
        CSRNG_BASE,
        CSRNG.fields("INTR_STATE")["CS_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_CSRNG_CMD_REQ_DONE),
    ),
    IrqSrc(
        "edn_cmd_req_done",
        EDN_BASE,
        EDN.fields("INTR_STATE")["EDN_CMD_REQ_DONE"]["bp"],
        agg_from_pic(PIC_EDN_CMD_REQ_DONE),
    ),
)

# The aggregator region this test owns: sep_internal_interrupts[8:33] (the
# crypto/KM/DMA fan-in; bits [7:0] are the mailbox region, covered elsewhere).
REGION_LO = 8
REGION_HI = 33
REGION_MASK = (((1 << (REGION_HI + 1)) - 1) >> REGION_LO) << REGION_LO


def driven_mask(sources) -> int:
    """OR of the aggregator bits driven by ``sources``."""
    m = 0
    for s in sources:
        m |= 1 << s.agg_idx
    return m


class SepIrqFaninCfg:
    """Seeded selection of the simultaneous cross-IP source subset.

    Picks a RANDOM subset (size >= 2, so it stays a genuine multi-source fan-in) of
    FANIN_SOURCES to assert together, plus one baseline source for the non-vacuity
    single-bit check. Every subset exercises the same anti-alias contract over the
    full [8:33] region; the randomization varies which non-adjacent bits fan in per
    seed. Seed + resolved subset logged; regression mode can sweep this via TOML ``reseed = N``.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        n = rng.randrange(2, len(FANIN_SOURCES) + 1)
        self.sources = rng.sample(list(FANIN_SOURCES), n)
        # Baseline single source for non-vacuity (any one source; reproducible).
        self.baseline = rng.choice(list(FANIN_SOURCES))

    def summary(self) -> str:
        names = ",".join(f"{s.name}[{s.agg_idx}]" for s in self.sources)
        return f"seed={self.seed} fanin={{{names}}} baseline={self.baseline.name}[{self.baseline.agg_idx}]"
