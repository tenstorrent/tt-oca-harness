# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox config and golden depth model (outbound aperture, TX path).

The SEP axil_mailbox is a two-port cross-FIFO. The test drives the SEP/CPU side through the
CPU-LSU master (no inbound filter) on outbound_mailbox_0: WRITE_DATA pushes the TX FIFO
(SEP->peer) and READ_DATA pops the RX FIFO (peer->SEP). The peer (SMC) side is not driven,
so the RX FIFO stays empty and a read returns the 0xFEEDDEAD sentinel with SLVERR.

STATUS has no exact-depth field, so the golden keeps the TX occupancy and predicts the
visible bits. Thresholds compare with strict >.

Data round-trip and the read threshold need the RX FIFO filled from the peer side, which
only the external smn_inbound master (inbound_mailbox_0) can do, so read_level_above is
predicted as constant False.
"""

from __future__ import annotations

from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0, SEP_CPU_CTRL, sym
from sep_seeded_rng import SepSeededRng
from sep_spec_tables import (
    mailbox_depth,
    mailbox_empty_sentinel,
    mailbox_write_data_rd_sentinel,
)

# --- outbound_mailbox_0 register map (single source of truth) -------------------
OUTBOUND_BASE = sym(
    "AXIL_MAILBOX_OUTBOUND_MAILBOX_0_REG_MAP_BASE_ADDR"
)  # SEP/CPU aperture (CPU-LSU reachable, no filter)
WRITE_DATA = AXIL_MAILBOX_OUTBOUND_0.offset("WRITE_DATA")
READ_DATA = AXIL_MAILBOX_OUTBOUND_0.offset("READ_DATA")
STATUS = AXIL_MAILBOX_OUTBOUND_0.offset("STATUS")
ERROR_FLAGS = AXIL_MAILBOX_OUTBOUND_0.offset("ERROR_FLAGS")
WIRQT = AXIL_MAILBOX_OUTBOUND_0.offset("WIRQT")
RIRQT = AXIL_MAILBOX_OUTBOUND_0.offset("RIRQT")
IRQS = AXIL_MAILBOX_OUTBOUND_0.offset("IRQS")
IRQEN = AXIL_MAILBOX_OUTBOUND_0.offset("IRQEN")
IRQP = AXIL_MAILBOX_OUTBOUND_0.offset("IRQP")
CTRL = AXIL_MAILBOX_OUTBOUND_0.offset("CTRL")

# STATUS / IRQS / ERROR_FLAGS bit positions from the generated bitfields.
CTRL_WFLUSH = AXIL_MAILBOX_OUTBOUND_0.field_mask("CTRL", "wflush")
ST_EMPTY = AXIL_MAILBOX_OUTBOUND_0.field_mask("STATUS", "empty")
ST_FULL = AXIL_MAILBOX_OUTBOUND_0.field_mask("STATUS", "full")
ST_WLVL_ABOVE = AXIL_MAILBOX_OUTBOUND_0.field_mask("STATUS", "write_level_above_thresh")
ST_RLVL_ABOVE = AXIL_MAILBOX_OUTBOUND_0.field_mask("STATUS", "read_level_above_thresh")
IRQ_WTIRQ = AXIL_MAILBOX_OUTBOUND_0.field_mask("IRQS", "wtirq")
IRQ_RTIRQ = AXIL_MAILBOX_OUTBOUND_0.field_mask("IRQS", "rtirq")
IRQ_EIRQ = AXIL_MAILBOX_OUTBOUND_0.field_mask("IRQS", "eirq")
ERR_READ = AXIL_MAILBOX_OUTBOUND_0.field_mask("ERROR_FLAGS", "read_error")
ERR_WRITE = AXIL_MAILBOX_OUTBOUND_0.field_mask("ERROR_FLAGS", "write_error")

# CLOCK_GATE_CTRL, from the generated SystemRDL export. There is no
# dedicated mailbox gate bit in this repository's sep_cpu_ctrl.rdl -- CLOCK_GATE_CTRL
# is a placeholder with one implemented bit (pka_cg_enable[0:0]) -- so the mailbox is
# unconditionally clocked and the "ungate" is a CSR write-path exercise, not a gate
# release. Use the implemented mask so the value cannot claim a field that is not there.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_IMPL_MASK = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")

MAILBOX_DEPTH = mailbox_depth()
# Read-from-empty / write-only readback, from the mailbox interface.adoc.
READ_EMPTY_SENTINEL = mailbox_empty_sentinel()
WRITE_DATA_RD_SENTINEL = mailbox_write_data_rd_sentinel()
RESP_OKAY = 0
RESP_SLVERR = 2


def wirqt_halves(depth: int = MAILBOX_DEPTH) -> tuple[tuple[str, int, int], ...]:
    """The legal write thresholds [1, depth-1] split into a low and a high half,
    as (name, first, last). A threshold of 0 makes any fill "above" and one of
    depth can never be exceeded, so neither end is a threshold test."""
    return (("low", 1, depth // 2 - 1), ("high", depth // 2, depth - 1))


class SepMboxCfg:
    """Config object: seeded WIRQT + message payloads. Single source of truth for
    DUT programming and golden expectations. Regression mode can sweep this via
    TOML ``reseed = N``.

    ``wirqt_range`` (inclusive) bounds the threshold draw; the default is every
    legal threshold. ``rng`` lets several configs share one seeded stream."""

    def __init__(
        self,
        seed: int = 1,
        *,
        depth: int = MAILBOX_DEPTH,
        wirqt_range: tuple[int, int] | None = None,
        half: str = "any",
        rng: SepSeededRng | None = None,
    ) -> None:
        self.seed = seed
        self.depth = depth
        self.half = half
        rng = SepSeededRng(seed) if rng is None else rng
        lo, hi = (1, depth - 1) if wirqt_range is None else wirqt_range
        if not 1 <= lo <= hi <= depth - 1:
            raise ValueError(f"WIRQT range [{lo}, {hi}] is outside [1, {depth - 1}]")
        # RANDOM write threshold in [lo, hi] within [1, depth-1]: "exceeds
        # threshold" is reachable and a full FIFO always trips it.
        self.wirqt = rng.randrange(lo, hi + 1)
        # RANDOM "message length" for the first fill batch: enough to cross WIRQT but
        # not necessarily fill (the test then tops up to full for the overflow check).
        self.first_batch = rng.randrange(self.wirqt + 1, depth + 1)
        # RANDOM distinct nonzero 64-bit payloads (data actually varies per seed), one
        # more than depth so the write-to-full overflow has its own value.
        self.payloads: list[int] = []
        while len(self.payloads) < depth + 1:
            v = rng.getrandbits(64)
            if v != 0 and v not in self.payloads:
                self.payloads.append(v)

    @classmethod
    def per_half(cls, seed: int, *, depth: int = MAILBOX_DEPTH) -> list["SepMboxCfg"]:
        """One config per half of the legal thresholds, in seeded order, drawn
        from one stream. A run then programs a low and a high threshold on
        every seed instead of one threshold whose half the seed decides."""
        rng = SepSeededRng(seed)
        halves = list(wirqt_halves(depth))
        if rng.getrandbits(1):
            halves.reverse()
        return [
            cls(seed, depth=depth, wirqt_range=(lo, hi), half=name, rng=rng)
            for name, lo, hi in halves
        ]

    def summary(self) -> str:
        return (
            f"seed={self.seed} depth={self.depth} half={self.half} wirqt={self.wirqt} "
            f"first_batch={self.first_batch} payloads={len(self.payloads)} "
            f"(random data+threshold+batch)"
        )


class SepMboxGolden:
    """Golden depth model for the TX FIFO (outbound WRITE_DATA push side).

    Predicts the outbound-aperture STATUS bits + the write-threshold IRQ from the TX
    occupancy. The RX side (READ_DATA) stays empty on bare-sep. Thresholds use
    strict greater-than (``architecture.adoc``: fill level exceeds the configured
    threshold). SepMboxCfg draws wirqt inside [1, depth-1], so every threshold the
    config can program is below depth and needs no clamp.
    """

    def __init__(self, cfg: SepMboxCfg) -> None:
        self.cfg = cfg
        self.tx = 0  # TX FIFO occupancy
        self.wirqt = cfg.wirqt

    def push(self) -> bool:
        """WRITE_DATA push. False if TX full (write-to-full -> write_error/eirq)."""
        if self.tx >= self.cfg.depth:
            return False
        self.tx += 1
        return True

    def flush(self) -> None:
        self.tx = 0

    def status(self) -> dict:
        """Outbound-aperture STATUS: write side == TX FIFO; read side (RX) empty."""
        return {
            "full": self.tx >= self.cfg.depth,
            "wlvl_above": self.tx > self.wirqt,
            "empty": True,  # RX FIFO never filled on bare-sep
            "rlvl_above": False,
        }

    def wtirq(self) -> bool:
        return self.tx > self.wirqt
