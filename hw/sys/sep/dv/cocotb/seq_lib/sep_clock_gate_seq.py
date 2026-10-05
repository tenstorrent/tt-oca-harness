# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CLOCK_GATE_CTRL placeholder driver.

sep_cpu_ctrl.rdl implements one bit, pka_cg_enable[0:0], and RTL sinks it into
an unused net. This driver is the single source of truth for that storage walk,
for the unimplemented-bit readback of both 32-bit halves of the 64-bit register,
and for the witness CSRs that stay reachable with the bit 0 and 1 -- a
decode-and-storage contract, not a live per-IP gate.
"""

from __future__ import annotations

from dataclasses import dataclass

from sep_reg_meta import SEP_CPU_CTRL, sym

from seq_lib.sep_aes_seq import AES_STATUS
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_hmac_seq import HMAC_INTR_STATE
from seq_lib.sep_otbn_seq import OTBN_ADDR_STATUS

CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_MASK = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")
# Every bit the register may store, reserved STORAGE fields included -- see
# mask_all() in env/sep_reg_meta.py, which exists because a field named `reserved`
# can still be real read/write storage. CLOCK_GATE_CTRL declares only
# pka_cg_enable[0:0] and no reserved storage, so here this equals the implemented
# mask. That is the contract the all-ones write proves: every other bit of both
# 32-bit halves is unimplemented and must not store.
CLOCK_GATE_STORAGE_MASK = SEP_CPU_CTRL.mask32_all("CLOCK_GATE_CTRL")
CLOCK_GATE_CTRL_HI = CLOCK_GATE_CTRL + 4

SW_DEBUG = sym("SEP_CPU_CTRL_SEP_SW_DEBUG_REG_ADDR")

# Discrete witnesses: one CSR per IP family that must read the same value
# whether pka_cg_enable is 0 or 1.
WITNESSES = (
    ("otbn_status", OTBN_ADDR_STATUS),
    ("aes_status", AES_STATUS),
    ("hmac_intr_state", HMAC_INTR_STATE),
    ("sw_debug", SW_DEBUG),
)


@dataclass(frozen=True)
class SepClockGateCfg:
    """Single source of truth for the clock-gate placeholder walk."""

    enables: tuple[int, ...] = (0, 1)
    witnesses: tuple[tuple[str, int], ...] = WITNESSES

    def cells(self):
        for enable in self.enables:
            for name, addr in self.witnesses:
                yield enable, name, addr

    def n_cells(self) -> int:
        return len(self.enables) * len(self.witnesses)

    def summary(self) -> str:
        names = ",".join(n for n, _ in self.witnesses)
        return f"enables={list(self.enables)} witnesses={{{names}}} cells={self.n_cells()}"


class SepClockGate(SepAxiRegDriver):
    """CPU-LSU driver for CLOCK_GATE_CTRL storage + witness CSR reads."""

    _DRIVER_TAG = "CLKGATE"

    async def write_enable(self, enable: int) -> None:
        await self._wr(CLOCK_GATE_CTRL, enable & CLOCK_GATE_MASK)

    async def read_enable(self) -> int:
        return (await self._rd(CLOCK_GATE_CTRL)) & CLOCK_GATE_MASK

    async def read_witness(self, addr: int) -> int:
        return await self._rd(addr)

    async def write_raw(self, addr: int, data: int) -> None:
        """Unmasked write, for driving the unimplemented CLOCK_GATE_CTRL bits."""
        await self._wr(addr, data)

    async def read_raw(self, addr: int) -> int:
        """Unmasked read, so an unimplemented bit that stores is visible."""
        return await self._rd(addr)
