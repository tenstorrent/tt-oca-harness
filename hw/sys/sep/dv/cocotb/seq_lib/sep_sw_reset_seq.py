# SPDX-License-Identifier: Apache-2.0
"""SEP per-engine software reset control (SW_RESET_N).

Active-low: a set bit releases the engine, a clear bit holds it in reset. This
helper keeps a shadow of the register so a test can release / park individual
engines without a read-modify-write race, the way the reference consume base sequence
releases KM first and the target crypto engine later.

The shadow is seeded with the HW reset default (hw/sys/sep/regs/rdl/
sep_reset_ctrl.rdl): km_sw_rst_n=0 (held), otbn/aes/hmac/kmac=1 (released) => 0x1E.
A test that wants the crypto engines parked (e.g. to dedicate entropy to the KM)
must park() them explicitly; do not rely on a wrong all-parked assumption.

Bit map (hw/sys/sep/rtl/sep_reset_ctrl.sv: SW_RESET_N fields):
  km=0, otbn=1, aes=2, hmac=3, kmac=4
"""

from __future__ import annotations

from sep_reg_meta import sym

from env.sep_axi_agent import SepAxiOp
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SEP_RESET_CTRL_SW_RESET_N = sym("SEP_RESET_CTRL_SW_RESET_N_REG_ADDR")

SW_RESET_N_BIT = {
    "km": 0,
    "otbn": 1,
    "aes": 2,
    "hmac": 3,
    "kmac": 4,
}

# HW reset default: km held (0), otbn/aes/hmac/kmac released (1) -> 0x1E.
SW_RESET_N_RESET_DEFAULT = 0x1E


class SepSwReset:
    """Tracks and drives SW_RESET_N; release/park engines by name."""

    def __init__(self, test, *, addr: int = SEP_RESET_CTRL_SW_RESET_N, logger=None) -> None:
        self.test = test
        self.addr = addr
        self.log = logger if logger is not None else test.logger
        self.value = SW_RESET_N_RESET_DEFAULT  # km held, crypto released (0x1E)

    async def _write(self) -> None:
        seq = SepAxiAccessSeq("sw_reset_n", op=SepAxiOp.WRITE, addr=self.addr, wdata=self.value)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SW_RESET_N write @0x{self.addr:08x} not OKAY")

    async def read_back(self) -> int:
        """Read SW_RESET_N from the DUT (the real HW state, not just the shadow).
        Lets a test prove, with positive evidence, which engines are released vs
        held in reset (e.g. key-bus isolation: only the target crypto engine out)."""
        seq = SepAxiAccessSeq("sw_reset_n_rd", op=SepAxiOp.READ, addr=self.addr)
        await self.test.start_seq(seq)
        if not seq.resp_ok:
            raise AssertionError(f"SW_RESET_N read @0x{self.addr:08x} not OKAY")
        return seq.rdata

    async def release(self, *engines: str) -> None:
        for eng in engines:
            self.value |= 1 << SW_RESET_N_BIT[eng]
        await self._write()
        self.log.info("SW_RESET_N released %s -> 0x%08x", ",".join(engines), self.value)

    async def park(self, *engines: str) -> None:
        for eng in engines:
            self.value &= ~(1 << SW_RESET_N_BIT[eng])
        await self._write()
        self.log.info("SW_RESET_N parked %s -> 0x%08x", ",".join(engines), self.value)
