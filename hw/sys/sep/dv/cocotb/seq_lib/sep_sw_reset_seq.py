# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP per-engine software reset control (SW_RESET_N).

Active-low: a set bit releases the engine, a clear bit holds it in reset. This
helper keeps a shadow of the register so a test can release / park individual
engines without a read-modify-write race, the way the reference consume base sequence
releases KM first and the target crypto engine later.

The shadow is seeded with the generated HW reset default:
km_sw_rst_n=0 (held), otbn/aes/hmac/kmac/trng/abr=1 (released) => 0x7E.
A test that wants the crypto engines parked (e.g. to dedicate entropy to the KM)
must park() them explicitly; the reset default leaves them released.

Bit map (hw/sys/sep/regs/blocks/sep_reset_ctrl/sep_reset_ctrl.rdl):
  km=0, otbn=1, aes=2, hmac=3, kmac=4, trng=5, abr=6
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import SEP_RESET_CTRL, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq

SEP_RESET_CTRL_SW_RESET_N = sym("SEP_RESET_CTRL_SW_RESET_N_REG_ADDR")

SW_RESET_N_BIT = {
    "km": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "km_sw_rst_n"),
    "otbn": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "otbn_sw_rst_n"),
    "aes": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "aes_sw_rst_n"),
    "hmac": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "hmac_sw_rst_n"),
    "kmac": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "kmac_sw_rst_n"),
    "trng": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "trng_sw_rst_n"),
    "abr": SEP_RESET_CTRL.field_lsb("SW_RESET_N", "abr_sw_rst_n"),
}

# HW reset default: km held; otbn/aes/hmac/kmac/trng/abr released.
SW_RESET_N_RESET_DEFAULT = SEP_RESET_CTRL.reset32("SW_RESET_N")


class SepSwReset:
    """Tracks and drives SW_RESET_N; release/park engines by name."""

    def __init__(self, test, *, addr: int = SEP_RESET_CTRL_SW_RESET_N, logger=None) -> None:
        self.test = test
        self.addr = addr
        self.log = logger if logger is not None else test.logger
        self.value = SW_RESET_N_RESET_DEFAULT

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
        """Hold engines in SW reset.

        A reset of AES, KMAC, or OTBN pulses the shared crypto EDN adapter
        clear for one cycle. That clear drops every endpoint's staged word,
        not only the engine being parked. The arbiter hold-until-grant
        assumption is a separate check, and this write does not grade it."""
        for eng in engines:
            self.value &= ~(1 << SW_RESET_N_BIT[eng])
        await self._write()
        self.log.info("SW_RESET_N parked %s -> 0x%08x", ",".join(engines), self.value)

    async def begin_trng_recovery(self, *, reset_km: bool, release_trng: bool = True) -> int:
        """Quiesce consumers, reset TRNG, and leave consumers held.

        The caller must next run ``SepEsrcConfigSeq(reset_trng=False)``, start
        generators, enable EDN, and observe fresh endpoint/pool progress before
        calling :meth:`restore_after_trng_reinit`. Set ``release_trng=False`` to
        inspect behavior while the coordinated reset remains asserted; release
        it explicitly with ``release("trng")`` before reinitialization.
        """
        saved = await self.read_back()
        self.value = saved
        consumers = ["aes", "kmac", "otbn"]
        if reset_km:
            consumers.append("km")

        await self.park(*consumers)
        await self.park("trng")
        if release_trng:
            await self.release("trng")
        return saved

    async def restore_after_trng_reinit(self, saved_sw_reset_n: int) -> None:
        """Restore consumer reset state after fresh entropy progress is proven."""
        self.value = saved_sw_reset_n
        await self._write()
        self.log.info("SW_RESET_N restored consumers -> 0x%08x", self.value)
