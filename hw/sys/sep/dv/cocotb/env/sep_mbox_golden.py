# SPDX-License-Identifier: Apache-2.0
"""axil_mailbox config + golden depth model (outbound aperture, TX path).

The SEP axil_mailbox (vendor/pulp-platform/axi/.../axi_lite_mailbox.sv, wrapped by
hw/ip/axi_lite_mailbox_unit) is a two-port cross-FIFO. This test drives the SEP/CPU
side over the CPU-LSU master (NO inbound filter): the OUTBOUND aperture
(outbound_mailbox_0 @ 0x10A0_0000). WRITE_DATA(+0x00) pushes the TX FIFO (SEP->peer);
READ_DATA(+0x08) pops the RX FIFO (peer->SEP), which stays EMPTY here because the
peer (SMC) side is not driven -> read returns the 0xFEEDDEAD sentinel + SLVERR. So
this is the TX-path test, exactly like OCAH ("CPU not running -> RX always empty;
verify the TX path").

STATUS has no exact-depth field (only empty/full/write_level_above/read_level_above),
so the golden keeps the TX occupancy internally and predicts the visible bits.
Thresholds compare with STRICT > (RTL); a programmed thold>=depth clamps to depth-1.
The config object is the single source of truth for DUT programming + golden.

Accepted deltas:
  * data round-trip readback and read-threshold (RIRQT/read_level_above) both need the RX
    FIFO filled by the peer side. A clean VCS repro proved the external smn_inbound
    frontdoor can write inbound_mailbox_0 @ 0x10A0_0800 and the CPU-LSU side can read the
    value back from outbound_mailbox_0. This model remains scoped to outbound TX
    occupancy because the permanent testcase is the TX-path randomized rep; a permanent
    peer-path closure should use the external master and its own checker contract.

Geometry note: post-#3548 MAILBOX_SIZE=0x800, so inbound_mailbox_0 is at 0x10A0_0800
(the pre-#3548 0x1000 stride put it at 0x10A0_1000 and mis-decoded 0x10A0_0800 onto
the outbound port -- fixed).
"""

from __future__ import annotations

from sep_reg_meta import SEP_CPU_CTRL

# --- outbound_mailbox_0 register map (single source of truth) -------------------
OUTBOUND_BASE = 0x10A0_0000      # SEP/CPU aperture (CPU-LSU reachable, no filter)
WRITE_DATA = 0x00                # 64-bit; pushes the TX FIFO (one access = one entry)
READ_DATA = 0x08                 # 64-bit; pops the RX FIFO (empty on bare-sep)
STATUS = 0x10                    # empty[0] full[1] wlvl_above[2] rlvl_above[3] (RO)
ERROR_FLAGS = 0x18               # read_error[0] write_error[1] (READ-CLEAR)
WIRQT = 0x20                     # write IRQ threshold [7:0]
RIRQT = 0x28                     # read IRQ threshold  [7:0]
IRQS = 0x30                      # wtirq[0] rtirq[1] eirq[2] (RW1C; level-held)
IRQEN = 0x38                     # wtirq[0] rtirq[1] eirq[2] (RW)
IRQP = 0x40                      # = IRQS & IRQEN (RO)
CTRL = 0x48                      # wflush[0] rflush[1] (WO)

# STATUS bit positions.
ST_EMPTY = 1 << 0
ST_FULL = 1 << 1
ST_WLVL_ABOVE = 1 << 2
ST_RLVL_ABOVE = 1 << 3
# IRQS/IRQEN/IRQP bit positions.
IRQ_WTIRQ = 1 << 0
IRQ_RTIRQ = 1 << 1
IRQ_EIRQ = 1 << 2
# ERROR_FLAGS bit positions.
ERR_READ = 1 << 0
ERR_WRITE = 1 << 1

# CLOCK_GATE_CTRL, from the generated SystemRDL export (AGENTS.md §7). There is no
# dedicated mailbox gate bit in this repository's sep_cpu_ctrl.rdl -- CLOCK_GATE_CTRL
# is a placeholder with one implemented bit (pka_cg_enable[0:0]) -- so the mailbox is
# unconditionally clocked and the "ungate" is a CSR write-path exercise, not a gate
# release. Use the implemented mask so the value cannot claim a field that is not there.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_MAILBOX = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")

MAILBOX_DEPTH = 8                # sep_pkg::MAILBOX_DEPTH
# Read-from-empty returns this sentinel + SLVERR (axi_lite_mailbox.sv).
READ_EMPTY_SENTINEL = 0xFEED_DEAD
RESP_OKAY = 0
RESP_SLVERR = 2


class SepMboxCfg:
    """Config object: seeded WIRQT + message payloads. Single source of truth for
    DUT programming and golden expectations. Regression mode can sweep this via
    TOML ``reseed = N``."""

    def __init__(self, seed: int = 1, *, depth: int = MAILBOX_DEPTH) -> None:
        import random
        self.seed = seed
        self.depth = depth
        rng = random.Random(seed)
        # RANDOM write threshold in [1, depth-1]: "exceeds threshold" is reachable and
        # a full FIFO always trips it.
        self.wirqt = rng.randint(1, depth - 1)
        # RANDOM "message length" for the first fill batch: enough to cross WIRQT but
        # not necessarily fill (the test then tops up to full for the overflow check).
        self.first_batch = rng.randint(self.wirqt + 1, depth)
        # RANDOM distinct nonzero 64-bit payloads (data actually varies per seed), one
        # more than depth so the write-to-full overflow has its own value.
        self.payloads: list[int] = []
        while len(self.payloads) < depth + 1:
            v = rng.getrandbits(64)
            if v != 0 and v not in self.payloads:
                self.payloads.append(v)

    def clamped(self, thold: int) -> int:
        return min(thold, self.depth - 1)

    def summary(self) -> str:
        return (f"seed={self.seed} depth={self.depth} wirqt={self.wirqt} "
                f"first_batch={self.first_batch} payloads={len(self.payloads)} "
                f"(random data+threshold+batch)")


class SepMboxGolden:
    """Golden depth model for the TX FIFO (outbound WRITE_DATA push side).

    Predicts the outbound-aperture STATUS bits + the write-threshold IRQ from the TX
    occupancy. The RX side (READ_DATA) stays empty on bare-sep. Thresholds use strict
    > (RTL); thold>=depth clamps to depth-1.
    """

    def __init__(self, cfg: SepMboxCfg) -> None:
        self.cfg = cfg
        self.tx = 0                          # TX FIFO occupancy
        self.wirqt = cfg.clamped(cfg.wirqt)

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
        return {"full": self.tx >= self.cfg.depth,
                "wlvl_above": self.tx > self.wirqt,
                "empty": True,            # RX FIFO never filled on bare-sep
                "rlvl_above": False}

    def wtirq(self) -> bool:
        return self.tx > self.wirqt
