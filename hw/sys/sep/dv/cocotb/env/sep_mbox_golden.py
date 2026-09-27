# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""axil_mailbox config + golden depth model (outbound aperture, TX path).

The SEP axil_mailbox (vendor/pulp-platform/axi/.../axi_lite_mailbox.sv, wrapped by
hw/ip/axi_lite_mailbox_unit) is a two-port cross-FIFO. This test drives the SEP/CPU
side over the CPU-LSU master (NO inbound filter): the OUTBOUND aperture
(outbound_mailbox_0 @ 0x10A0_0000). WRITE_DATA(+0x00) pushes the TX FIFO (SEP->peer);
READ_DATA(+0x08) pops the RX FIFO (peer->SEP), which stays EMPTY here because the
peer (SMC) side is not driven -> read returns the 0xFEEDDEAD sentinel + SLVERR. So
this is the TX-path test: with no CPU running the RX side is always empty.

STATUS has no exact-depth field (only empty/full/write_level_above/read_level_above),
so the golden keeps the TX occupancy internally and predicts the visible bits.
Thresholds compare with STRICT >. The config object is the single source of
truth for DUT programming + golden.

Scope: data round-trip readback and the read threshold (RIRQT/read_level_above)
both need the RX FIFO filled from the peer side, which this aperture cannot do, so
the model covers outbound TX occupancy only and predicts read_level_above as
constant False. The peer path is reachable only through the external smn_inbound
master (inbound_mailbox_0 @ 0x10A0_0800, MAILBOX_SIZE=0x800).
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


class SepMboxCfg:
    """Config object: seeded WIRQT + message payloads. Single source of truth for
    DUT programming and golden expectations. Regression mode can sweep this via
    TOML ``reseed = N``."""

    def __init__(self, seed: int = 1, *, depth: int = MAILBOX_DEPTH) -> None:
        self.seed = seed
        self.depth = depth
        rng = SepSeededRng(seed)
        # RANDOM write threshold in [1, depth-1]: "exceeds threshold" is reachable and
        # a full FIFO always trips it.
        self.wirqt = rng.randrange(1, depth)
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

    def summary(self) -> str:
        return (
            f"seed={self.seed} depth={self.depth} wirqt={self.wirqt} "
            f"first_batch={self.first_batch} payloads={len(self.payloads)} "
            f"(random data+threshold+batch)"
        )


class SepMboxGolden:
    """Golden depth model for the TX FIFO (outbound WRITE_DATA push side).

    Predicts the outbound-aperture STATUS bits + the write-threshold IRQ from the TX
    occupancy. The RX side (READ_DATA) stays empty on bare-sep. Thresholds use
    strict greater-than (``architecture.adoc``: fill level exceeds the configured
    threshold). SepMboxCfg draws wirqt in [1, depth-1], so every threshold the config
    can program is below depth and needs no clamp.
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
